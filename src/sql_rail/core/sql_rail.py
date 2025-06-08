# sql_guardrail/core/sql_rail.py
from typing import List, Dict, Optional, Any
import logging

from ..models.results import (
    MatchSuggestion,
    DistanceMetricAnalysis,
    WhereClauseConditionAnalysis,
    GuardRailAnalysisResult,
)
from .distance_metrics import Distance
from ..utils.sql_parser_utils import parse_sql_where_clauses
from ..utils.data_loader_utils import load_reference_data_from_file, load_reference_data_from_json, load_all_reference_data

logger = logging.getLogger(__name__)

class SQLRail:
    """
    Main orchestrator for the SQL guardrail process.
    """
    def __init__(self,
                 distance_calculators: List[Distance],
                 references_config: Optional[Dict[str, Any]] = None,
                 preloaded_references: Optional[Dict[str, List[str]]] = None):
        """
        Initializes the SQLRail object.

        Args:
            distance_calculators: List of instantiated Distance objects.
            references_config: Configuration to load reference data from files.
                               Example: {"country": {"path": "countries.csv", "value_column": "CountryName"}}
                                        {"product_name": "products.csv"} (assumes first column)
            preloaded_references: Dictionary of already loaded reference data.
                                  Example: {"country": ["USA", "Canada", ...]}
                                  Takes precedence over references_config if provided.
        """
        self.distance_calculators: List[Distance] = distance_calculators
        self.column_reference_values: Dict[str, List[str]] = {}
        self.warnings: List[str] = []

        if not self.distance_calculators:
            logger.warning("SQLRail initialized with no distance calculators.")
            self.warnings.append("No distance calculators configured. Analysis will be limited.")

        if preloaded_references:
            logger.info("Loading preloaded reference data.")
            self.column_reference_values = preloaded_references
        elif references_config:
            logger.info("Loading reference data from configuration.")
            self._load_reference_data_from_config(references_config)
        else:
            logger.warning("No reference data provided (neither preloaded_references nor references_config).")
            self.warnings.append("No reference data loaded. Guardrail suggestions will not be available.")

        if self.column_reference_values:
            self._preprocess_all_references()
        else:
            logger.info("Skipping preprocessing as no reference data is available.")


    def _load_reference_data_from_config(self, references_config: Dict[str, Any]):
        """
        (Private helper) Loads reference data from files based on references_config.
        Populates self.column_reference_values.
        """
        for column_name, config_value in references_config.items():
            if isinstance(config_value, str): # Simple case: path to CSV, use first column
                config = {"path": config_value, "value_column": 0}
            elif isinstance(config_value, dict) and "path" in config_value:
                config = config_value
            else:
                logger.warning(f"Invalid configuration for column '{column_name}': {config_value}. Skipping.")
                self.warnings.append(f"Invalid reference config for column: {column_name}")
                continue
            
            logger.info(f"Loading reference data for column '{column_name}' from '{config.get('path')}'.")
            data = load_reference_data_from_file(config)
            if data:
                self.column_reference_values[column_name] = data
                logger.info(f"Loaded {len(data)} reference values for column '{column_name}'.")
            else:
                logger.warning(f"No data loaded for column '{column_name}' from config: {config}")
                self.warnings.append(f"Could not load reference data for column: {column_name}")


    def _preprocess_all_references(self):
        """
        (Private helper) Calls preprocess_candidates on all distance_calculators
        for each column's reference list.
        """
        logger.info("Starting preprocessing of all reference data for distance calculators...")
        for calc in self.distance_calculators:
            logger.debug(f"Preprocessing for calculator: {calc.get_name()}")
            for column_name, ref_values in self.column_reference_values.items():
                try:
                    calc.preprocess_candidates(column_name, ref_values)
                except Exception as e:
                    logger.error(f"Error during preprocessing for {calc.get_name()} on column {column_name}: {e}", exc_info=True)
                    self.warnings.append(f"Preprocessing error for {calc.get_name()} on {column_name}: {str(e)}")
        logger.info("Finished preprocessing all reference data.")

    def _parse_query(self, sql_query: str) -> List[Dict[str, Any]]:
        """
        (Private helper) Parses the SQL query to identify WHERE clause conditions.
        Uses the utility function from sql_parser_utils.
        """
        try:
            return parse_sql_where_clauses(sql_query)
        except Exception as e:
            logger.error(f"Error parsing SQL query: {e}", exc_info=True)
            self.warnings.append(f"SQL parsing failed: {str(e)}")
            return []

    def analyze_query(self, sql_query: str, k: int = 5) -> GuardRailAnalysisResult:
        """
        Primary public method to analyze an SQL query.

        Args:
            sql_query: The SQL query string to analyze.
            k: The number of top suggestions to return for each metric.

        Returns:
            A GuardRailAnalysisResult object with the findings.
        """
        logger.info(f"Starting analysis for query: {sql_query[:100]}...") # Log snippet of query
        current_warnings = list(self.warnings) # Copy initial warnings
        analyzed_conditions_output: List[WhereClauseConditionAnalysis] = []

        parsed_conditions = self._parse_query(sql_query)
        if not parsed_conditions:
            logger.warning("No relevant WHERE clause conditions found or parsing failed.")
            current_warnings.append("No relevant WHERE clause conditions found or SQL parsing failed.")
            # Still return a result object, but it will be empty of conditions
            return GuardRailAnalysisResult(
                original_query=sql_query,
                analyzed_conditions=[],
                warnings=current_warnings if current_warnings else None
            )

        for condition in parsed_conditions:
            column_name = condition["column_name"].strip("\"")
            operator = condition["operator"]
            # query_parameter_values is a list, even for '=' operator
            query_parameter_values = condition["query_parameter_values"]
            logger.info(f"Analyzing condition: {column_name} {operator} {query_parameter_values}")
            raw_value_in_query_segment = condition["raw_value_in_query"]

            condition_analyses_by_metric: List[DistanceMetricAnalysis] = []

            if column_name not in self.column_reference_values:
                msg = f"No reference data found for column '{column_name}' queried in WHERE clause."
                logger.warning(msg)
                current_warnings.append(msg)
                # We can still create a WhereClauseConditionAnalysis entry, but it won't have metric analyses
                # Or we can skip it. Let's include it to show what was parsed.
                analyzed_conditions_output.append(
                    WhereClauseConditionAnalysis(
                        column_name=column_name,
                        operator=operator,
                        raw_value_in_query=raw_value_in_query_segment,
                        analyses_by_metric=[] # Empty as no reference data
                    )
                )
                continue # Move to the next parsed condition

            reference_list_for_column = self.column_reference_values[column_name]
            if not reference_list_for_column:
                msg = f"Reference data for column '{column_name}' is empty."
                logger.warning(msg)
                current_warnings.append(msg)
                # As above, include the condition but without metric analyses
                analyzed_conditions_output.append(
                    WhereClauseConditionAnalysis(
                        column_name=column_name,
                        operator=operator,
                        raw_value_in_query=raw_value_in_query_segment,
                        analyses_by_metric=[]
                    )
                )
                continue


            # For this condition, iterate through each value (e.g., multiple values in an IN clause)
            # And for each value, iterate through all distance metrics
            # The current design implies one DistanceMetricAnalysis PER query_parameter_value
            # This means if we have `country IN ('Unted Stats', 'Canda')`,
            # we'd have two sets of DistanceMetricAnalysis lists (one for 'Unted Stats', one for 'Canda')
            # The WhereClauseConditionAnalysis seems to aggregate these.
            # Let's re-read section 4:
            # DistanceMetricAnalysis: query_parameter_value (singular)
            # WhereClauseConditionAnalysis: analyses_by_metric (list of DistanceMetricAnalysis)
            # This implies that for `country IN ('val1', 'val2')`, the `WhereClauseConditionAnalysis` for `country`
            # will contain multiple `DistanceMetricAnalysis` objects PER metric, if each value is analyzed.
            # The provided model structure suggests one list of DistanceMetricAnalysis per WhereClauseConditionAnalysis.
            # This might mean we need to aggregate suggestions if multiple query_parameter_values exist
            # OR create multiple WhereClauseConditionAnalysis (one per value in IN).
            #
            # Given: "For each query parameter value and its corresponding reference list: Each configured distance/similarity metric is applied."
            # And: DistanceMetricAnalysis.query_parameter_value (singular)
            # And: WhereClauseConditionAnalysis.analyses_by_metric (list of DistanceMetricAnalysis)
            # This implies that `analyses_by_metric` will contain entries for *each* `query_parameter_value` from the IN clause,
            # for *each* metric.
            #
            # Let's adjust. The `WhereClauseConditionAnalysis` is for the whole `country IN (...)`.
            # `analyses_by_metric` should then contain, for each metric, the analysis for EACH `value_to_check`.
            #
            # Revisiting the Pydantic models and flow:
            # GuardRailAnalysisResult -> List[WhereClauseConditionAnalysis]
            # WhereClauseConditionAnalysis -> column_name, operator, raw_value_in_query, List[DistanceMetricAnalysis]
            # DistanceMetricAnalysis -> metric_name, query_parameter_value (singular!), List[MatchSuggestion]
            # This means for a single `country IN ('val1', 'val2')` condition:
            # We'll have one `WhereClauseConditionAnalysis`.
            # Its `analyses_by_metric` list will contain:
            #  - Levenshtein results for 'val1'
            #  - Levenshtein results for 'val2'
            #  - Semantic results for 'val1'
            #  - Semantic results for 'val2'
            # This structure seems correct and matches the "Result Aggregation" section.

            all_metric_analyses_for_this_condition: List[DistanceMetricAnalysis] = []

            for value_to_check in query_parameter_values:
                if not isinstance(value_to_check, str): # Ensure we are dealing with strings
                    logger.warning(f"Skipping non-string value '{value_to_check}' for column '{column_name}'.")
                    current_warnings.append(f"Skipping non-string value for column {column_name}: {value_to_check}")
                    continue
                
                for calculator in self.distance_calculators:
                    logger.debug(f"Applying {calculator.get_name()} to '{value_to_check}' for column '{column_name}'")
                    try:
                        # Pass column_name as key for semantic distance to use correct precomputed embeddings
                        search_results = calculator.search(value_to_check, reference_list_for_column, k, column_name_or_key=column_name)
                        
                        suggestions = [
                            MatchSuggestion(suggested_value=res[0], similarity_score=res[1])
                            for res in search_results
                        ]
                        
                        all_metric_analyses_for_this_condition.append(
                            DistanceMetricAnalysis(
                                metric_name=calculator.get_name(),
                                query_parameter_value=value_to_check,
                                suggestions=suggestions
                            )
                        )
                    except Exception as e:
                        logger.error(f"Error during search with {calculator.get_name()} for '{value_to_check}' on column '{column_name}': {e}", exc_info=True)
                        current_warnings.append(f"Search error with {calculator.get_name()} for '{value_to_check}' on {column_name}: {str(e)}")
            
            analyzed_conditions_output.append(
                WhereClauseConditionAnalysis(
                    column_name=column_name,
                    operator=operator,
                    raw_value_in_query=raw_value_in_query_segment, # The string "('val1', 'val2')" or "'val'"
                    analyses_by_metric=all_metric_analyses_for_this_condition
                )
            )

        logger.info("Analysis complete.")
        return GuardRailAnalysisResult(
            original_query=sql_query,
            analyzed_conditions=analyzed_conditions_output,
            warnings=current_warnings if current_warnings else None
        )