# SQL Guardrail Module Documentation

**Version:** 1.1
**Date:** May 8, 2025

## 1. Introduction & Motivation

In many data-driven applications, users or automated systems construct SQL queries to retrieve specific information. Often, parameters within the `WHERE` clause of these queries might contain typos, slight variations in terminology, or values that are close but not identical to the actual data stored in the reference lists (e.g., "Unted States" instead of "United States"). Such discrepancies can lead to queries returning empty result sets or incorrect data, causing confusion and potentially impacting decision-making.

The **SQL Guardrail Module** is designed to address this challenge. Its primary purpose is to analyze string parameters within the `WHERE` clauses of an SQL query and suggest the closest valid or intended matches from predefined reference datasets. By providing these suggestions, the module aims to:

* Improve data quality by catching potential errors in query parameters.
* Enhance query accuracy by guiding users towards valid parameter values.
* Reduce the time spent debugging queries that return unexpected results due to parameter mismatches.
* Offer a "guardrail" to ensure queries are more likely to interact with the database as intended.

This module achieves this by parsing the input SQL, identifying relevant parameters, and comparing them against user-provided reference lists using various configurable similarity and distance metrics.

## 2. High-Level Flow

The module operates through the following conceptual steps:

1.  **Initialization**: The system is configured with:
    * Reference datasets for specific database columns (e.g., a list of all valid country names, product names).
    * A selection of distance/similarity algorithms to use for matching (e.g., Levenshtein, semantic similarity).
    * Reference data is loaded, and any necessary preprocessing (like generating embeddings for semantic search) is performed.
2.  **Query Input**: An SQL query string is provided to the module for analysis.
3.  **SQL Parsing**: The module parses the input SQL query to identify `WHERE` clause conditions, specifically focusing on column-operator-value expressions (e.g., `country = 'USA'`, `product_name IN ('Laptop', 'Mouse')`).
4.  **Parameter Identification**: For each condition, the column name and the value(s) being queried are extracted.
5.  **Candidate Retrieval**: If reference data is available for an identified column, that list of valid values is retrieved.
6.  **Similarity Search**: For each query parameter value and its corresponding reference list:
    * Each configured distance/similarity metric is applied.
    * The chosen metric's `search` method finds the top 'k' closest matches from the reference list.
7.  **Result Aggregation**: The suggestions from all distance metrics for all relevant `WHERE` clause parameters are collected.
8.  **Structured Output**: The aggregated results, including the original query parameter, the distance metric used, the suggested values, and their similarity scores, are returned in a structured format (typically JSON, facilitated by Pydantic models).

## 3. Core Components: Class Design

The module is built around a few key classes that encapsulate its logic and data.

### 3.1. `Distance` (Abstract Base Class)

* **Purpose**: Defines the common interface and contract for all distance and similarity calculation strategies. It ensures that any new matching algorithm can be seamlessly integrated into the system.
* **Key Methods**:
    * `__init__(**kwargs)`: Allows specific distance implementations to accept configuration parameters (e.g., path to an AI model, specific algorithm settings).
    * `search(query_value, candidates, k, column_name_or_key)`: The core method that each concrete distance class must implement. It takes a value from the SQL query, a list of candidate values from the reference data, the number of top matches (`k`) to return, and an optional key identifying the candidate set (for retrieving preprocessed data). It returns a list of top `k` matching candidates and their similarity scores (normalized to a 0.0-1.0 range, where higher is better).
    * `preprocess_candidates(column_name_or_key, candidates)`: An optional method that allows distance implementations to perform any necessary pre-computation or caching on the candidate values for a specific column. For example, a semantic distance metric would use this to pre-generate embeddings for all candidate values. This method is called once when reference data is loaded or provided.

### 3.2. Concrete `Distance` Implementations

These classes inherit from `Distance` and provide specific matching algorithms.

* **`LevenshteinDistance`**:
    * **Strategy**: Calculates similarity based on the Levenshtein distance (edit distance) between strings. Effective for catching typos and minor variations.
* **`SemanticDistance`**:
    * **Strategy**: Uses natural language processing (NLP) models (e.g., sentence transformers) to compute embeddings (numerical representations) for the query value and candidate values. Similarity is then calculated based on the closeness of these embeddings (e.g., using cosine similarity). This is powerful for finding semantically similar but lexically different phrases. It requires a pre-trained model.
* **`FuzzyWuzzyDistance` (Conceptual)**:
    * **Strategy**: Would use libraries like FuzzyWuzzy to provide various fuzzy string matching ratios. Often based on Levenshtein distance but with convenient scoring wrappers.

*(Other distance metrics can be added by extending the `Distance` base class).*

### 3.3. `SQLRail`

* **Purpose**: The main orchestrator of the SQL guardrail process. It manages configurations, reference data, SQL parsing, and coordinates the search process using the configured `Distance` objects.
* **Key Attributes**:
    * `distance_calculators`: A list of instantiated `Distance` objects (e.g., an instance of `LevenshteinDistance`, an instance of `SemanticDistance`) that will be used for matching.
    * `column_reference_values`: An in-memory dictionary holding the loaded reference values for each column. The key is the column name (e.g., "country"), and the value is a list of strings (e.g., ["USA", "Canada", ...]).
    * `references_config` (Optional): A dictionary configuring how to load reference data from external files if `preloaded_references` is not used. Maps column names to file paths or more detailed configuration objects (e.g., specifying which column in a CSV to use).
* **Key Methods**:
    * `__init__(distance_calculators, references_config=None, preloaded_references=None)`: Initializes the `SQLRail` object. It requires a list of distance calculators. Reference data can be provided either via `references_config` (to be loaded from files) or directly via `preloaded_references`.
    * `_load_reference_data_from_config()`: (Private helper) If `references_config` is provided, this method reads the specified files (e.g., CSVs), extracts the relevant values, and populates the `column_reference_values` attribute.
    * `_preprocess_all_references()`: (Private helper) After reference data is loaded (either from files or preloaded), this method iterates through all configured `distance_calculators` and calls their `preprocess_candidates` method for each column's reference list. This allows metrics like `SemanticDistance` to build their caches (e.g., embeddings).
    * `_parse_query(sql_query)`: (Private helper) Takes an SQL query string and uses a library like `sqlparse` to identify `WHERE` clause conditions. It extracts the column name, operator, and the literal value(s) being used in the query for each relevant condition.
    * `analyze_query(sql_query, k=5)`: The primary public method. It takes an SQL query string and an integer `k` (for top-k matches). It orchestrates the entire analysis process: calls `_parse_query`, then for each relevant query parameter, it iterates through all configured `distance_calculators`, calling their `search` method with the appropriate reference data. Finally, it aggregates all suggestions into a structured `GuardRailAnalysisResult` object.

## 4. Key Data Structures (Output Format)

The module returns its analysis in a structured way, typically represented by Pydantic models, which can be easily serialized to JSON.

* **`MatchSuggestion`**: Represents a single suggested alternative for a query parameter.
    * `suggested_value`: The actual string value suggested from the reference list.
    * `similarity_score`: The score (0.0 to 1.0) indicating how similar this suggestion is to the original query parameter, according to the specific distance metric used.
* **`DistanceMetricAnalysis`**: Contains the results from a single distance metric for a specific query parameter value.
    * `metric_name`: The name of the distance metric used (e.g., "LevenshteinDistance").
    * `query_parameter_value`: The specific value from the query that was analyzed (especially relevant for `IN` clauses with multiple values).
    * `suggestions`: A list of `MatchSuggestion` objects.
* **`WhereClauseConditionAnalysis`**: Encapsulates all analyses performed for a single condition (e.g., `country = 'Unted Stats'`) found in the SQL `WHERE` clause.
    * `column_name`: The database column identified in the condition.
    * `operator`: The SQL operator used (e.g., `=`, `IN`, `LIKE`).
    * `raw_value_in_query`: The original string representation of the value(s) as it appeared in the query.
    * `analyses_by_metric`: A list of `DistanceMetricAnalysis` objects, one for each distance metric applied to this condition's parameters.
* **`GuardRailAnalysisResult`**: The top-level object returned by the `analyze_query` method.
    * `original_query`: The SQL query string that was analyzed.
    * `analyzed_conditions`: A list of `WhereClauseConditionAnalysis` objects, covering all analyzed parts of the `WHERE` clause.
    * `warnings` (Optional): A list of any warnings generated during the process (e.g., reference data not found for a queried column).

## 5. Detailed Workflow: `analyze_query`

When the `analyze_query(sql_query, k)` method of an `SQLRail` object is called, the following sequence of operations occurs:

1.  **Parse SQL Query**: The input `sql_query` is parsed (via `_parse_query`) to identify individual conditions within `WHERE` clauses. Each condition typically yields a column name, an operator, and one or more query values (e.g., for `column IN ('val1', 'val2')`, "val1" and "val2" are distinct query values).
2.  **Iterate Through Conditions**: For each parsed condition:
    a.  **Identify Column and Query Values**: The `column_name` and the `parsed_values` (a list, even if usually one item) are extracted from the condition.
    b.  **Check for Reference Data**: The system checks if `column_reference_values` contains an entry for this `column_name`. If not, this condition might be skipped, or a warning might be noted.
    c.  **Iterate Through Query Values**: For each `value_to_check` in the `parsed_values` from the condition:
        i.  **Iterate Through Distance Calculators**: For each `distance_calculator` (e.g., `LevenshteinDistance`, `SemanticDistance`) configured in `SQLRail`:
            1.  **Perform Search**: The `distance_calculator.search()` method is called with `value_to_check`, the reference list for `column_name` (from `column_reference_values`), the desired number of top matches `k`, and the `column_name` (as `column_name_or_key` for retrieving preprocessed data like embeddings).
            2.  **Collect Suggestions**: The returned list of `(matched_value, score)` tuples is converted into `MatchSuggestion` objects.
            3.  **Store Metric Analysis**: These suggestions are stored in a `DistanceMetricAnalysis` object for the current `distance_calculator` and `value_to_check`.
    d.  **Aggregate for Condition**: All `DistanceMetricAnalysis` objects for the current condition (across all its query values and all distance metrics) are collected into a `WhereClauseConditionAnalysis` object.
3.  **Compile Final Result**: All `WhereClauseConditionAnalysis` objects are gathered into a `GuardRailAnalysisResult` object, which also includes the `original_query`.
4.  **Return Result**: The `GuardRailAnalysisResult` object is returned.

## 6. Configuration & Usage

Using the SQL Guardrail module involves two main steps: initialization and analysis.

### 6.1. Initializing `SQLRail`

An instance of the `SQLRail` class must be created. This requires:

1.  **`distance_calculators`**: A Python list of instantiated `Distance` metric objects.
    * Example: `[LevenshteinDistance(), SemanticDistance(model_name_or_path='path/to/embedding_model')]`
2.  **Reference Data**: This can be supplied in one of two ways:
    * **`references_config` (Dictionary)**: To load data from files (e.g., CSVs).
        * The dictionary keys are column names for which reference data is being provided.
        * Values can be:
            * A simple string path to a CSV file (assumes the first column contains the values).
            * A dictionary specifying details like `{"path": "file.csv", "value_column": 0}` (to use column index 0) or `{"value_column": "CountryName"}` (to use a named column).
    * **`preloaded_references` (Dictionary)**: To provide data that is already in memory.
        * The dictionary keys are column names.
        * The values are Python lists of strings representing the reference values for that column.
        * If `preloaded_references` is provided, it takes precedence, and `references_config` will be ignored (if also provided).

If neither `references_config` nor `preloaded_references` is given, `SQLRail` will initialize but will not have any reference data to check against, making analyses less useful.

Upon initialization, `SQLRail` will:
* Load data if `references_config` is used.
* Call `preprocess_candidates()` on all its `distance_calculators` for all loaded reference lists, allowing them to build any necessary caches or indexes (like semantic embeddings).

### 6.2. Performing Analysis

Once `SQLRail` is initialized:
* Call its `analyze_query(sql_query_string, k)` method.
    * `sql_query_string`: The SQL query to analyze.
    * `k`: (Optional, defaults to 5) The number of top suggestions to return for each metric.
* The method returns a `GuardRailAnalysisResult` object containing the detailed findings.

## 7. Assumptions & Limitations

* **Reference Data Quality**: The quality of suggestions heavily depends on the accuracy and completeness of the provided reference CSVs/lists.
* **SQL Parsing Scope**: The initial SQL parsing focuses on common `WHERE` clause patterns (e.g., `column = 'value'`, `column IN ('v1', 'v2')`). Very complex nested conditions, subqueries, or dialect-specific SQL syntax might not be fully analyzed in the initial versions.
* **Performance**:
    * Loading very large reference datasets entirely into memory might impact performance and memory usage.
    * Semantic search, especially without precomputed embeddings (though the design includes precomputation), can be computationally intensive.
* **Contextual Understanding**: The module primarily matches string values. It does not (currently) deeply understand the semantic context of the SQL query beyond basic `WHERE` clause parameter extraction.
* **Focus on String Parameters**: The primary focus is on suggesting alternatives for string literals in `WHERE` clauses. Numeric or date comparisons are typically not candidates for fuzzy matching in the same way.
* **`LIKE` Clause Handling**: Suggestions for `LIKE` patterns require specific strategies (e.g., stripping wildcards for some metrics, using them for others). The initial approach may be simple.

## 8. Future Enhancements

* **Advanced SQL Parsing**: Support for more complex SQL constructs, aliases, joins affecting `WHERE` clauses, and different SQL dialects.
* **Enhanced Configuration**: More granular control over CSV parsing (delimiters, encodings), and ability to map specific distance metrics to specific columns.
* **Performance Optimizations**:
    * Lazy loading or alternative storage (e.g., lightweight databases like SQLite) for very large reference datasets.
    * Further optimization of search algorithms.
* **Dynamic Data Sources**: Support for fetching reference data directly from databases or APIs instead of just static files.
* **Type Awareness**: Differentiating between column types (string, number, date) and applying appropriate suggestion strategies or skipping non-applicable ones.
* **User Feedback Loop**: Mechanism for users to confirm/reject suggestions to potentially fine-tune models or reference lists over time (more advanced).
* **Suggestion of Operators**: Potentially suggesting operator changes (e.g., "Did you mean `LIKE` instead of `=`?" based on common patterns for a column).
* **Threshold-based Filtering**: Allow users to specify a minimum similarity threshold for suggestions, in addition to top-k.