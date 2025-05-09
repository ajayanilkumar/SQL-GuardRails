# examples/run_analysis.py
import json
import logging
import os
from sql_guardrail import (
    SQLRail,
    LevenshteinDistance,
    SemanticDistance,
    FuzzyWuzzyDistance # Assuming you created this
)

# Setup basic logging to see output from the module
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def get_asset_path(filename: str) -> str:
    return os.path.join(os.path.dirname(__file__), "sample_references", filename)

def main():
    logger.info("Starting SQL Guardrail example script.")

    # --- Configuration ---
    # 1. Initialize Distance Calculators
    # Make sure you have a model for SemanticDistance, e.g., 'all-MiniLM-L6-v2'
    # You might need to download it the first time:
    # from sentence_transformers import SentenceTransformer
    # SentenceTransformer('all-MiniLM-L6-v2')
    
    distance_calculators = [
        LevenshteinDistance(),
        SemanticDistance(model_name_or_path='all-MiniLM-L6-v2'), # Ensure this model is available
        FuzzyWuzzyDistance()
    ]
    logger.info(f"Initialized {len(distance_calculators)} distance calculators.")

    # 2. Configure Reference Data
    # Option A: Load from files
    references_config = {
        "country": {"path": get_asset_path("countries.csv"), "value_column": "CountryName"},
        "product_name": {"path": get_asset_path("products.csv"), "value_column": 0} # Use column index
    }
    logger.info(f"Reference config: {references_config}")

    # Option B: Use preloaded references (example)
    # preloaded_references_data = {
    #     "country": ["United States", "Canada", "Mexico", "Germany", "Untied Stats"],
    #     "product_name": ["Laptop Pro", "Desktop Gamer", "Wireless Mouse", "Laptoo Pro"]
    # }

    # --- Initialize SQLRail ---
    # Using file-based config:
    try:
        sql_rail_instance = SQLRail(
            distance_calculators=distance_calculators,
            references_config=references_config
        )
        logger.info("SQLRail instance created successfully with file-based references.")
    except ImportError as e:
        logger.error(f"Failed to initialize SQLRail due to missing dependency: {e}")
        logger.error("Please ensure all required libraries (e.g., sentence-transformers, torch, Levenshtein, rapidfuzz) are installed.")
        return
    except Exception as e:
        logger.error(f"An unexpected error occurred during SQLRail initialization: {e}", exc_info=True)
        return


    # Using preloaded data (uncomment to test this path):
    # sql_rail_instance = SQLRail(
    #     distance_calculators=distance_calculators,
    #     preloaded_references=preloaded_references_data
    # )
    # logger.info("SQLRail instance created successfully with preloaded references.")

    # --- Perform Analysis ---
    # Test SQL queries
    queries_to_test = [
        "SELECT * FROM orders WHERE country = 'Unted States' AND order_date > '2024-01-01'",
        "SELECT name, price FROM products WHERE product_name IN ('Laptoo Pro X1', 'Wirless Mouse Elite') AND category = 'Electronics'",
        "SELECT id FROM users WHERE location = 'Canda' OR location = 'Brazil'",
        "SELECT * FROM events WHERE event_type = 'Concert' AND city_name = 'New Yrok'", # city_name has no reference data
        "SELECT data FROM logs WHERE machine_id = 123 AND status_code = 'ERORR'", # status_code has no ref data
        "SELECT * FROM employees WHERE department = 'Human Resources' AND employee_name LIKE 'Jon %'", # LIKE not fully supported yet by parser for suggestions
        "SELECT * FROM sales WHERE item = 'Some Unknown Item'"
    ]

    k_suggestions = 3

    for i, sql_query in enumerate(queries_to_test):
        logger.info(f"\n--- Analyzing Query {i+1}/{len(queries_to_test)} (top {k_suggestions} suggestions) ---")
        logger.info(f"Original Query: {sql_query}")
        
        analysis_result = sql_rail_instance.analyze_query(sql_query, k=k_suggestions)

        # Output results (Pydantic models can be easily converted to dict/JSON)
        result_dict = analysis_result.model_dump(exclude_none=True) # Pydantic v2
        
        print("\nAnalysis Result (JSON):")
        print(json.dumps(result_dict, indent=2))

        if analysis_result.warnings:
            logger.warning("Analysis generated warnings:")
            for warn in analysis_result.warnings:
                logger.warning(f"  - {warn}")
        
        if not analysis_result.analyzed_conditions and not analysis_result.warnings:
            logger.info("No specific conditions were analyzed, and no warnings were generated for this query.")


    # Example of how SemanticDistance caches embeddings (illustrative)
    if any(isinstance(dc, SemanticDistance) for dc in sql_rail_instance.distance_calculators):
        semantic_dc = next(dc for dc in sql_rail_instance.distance_calculators if isinstance(dc, SemanticDistance))
        if hasattr(semantic_dc, 'candidate_embeddings'):
            logger.info("\n--- Illustrative: SemanticDistance Cached Embedding Keys ---")
            for key in semantic_dc.candidate_embeddings.keys():
                num_embeddings = semantic_dc.candidate_embeddings[key].shape[0] if semantic_dc.candidate_embeddings[key].nelement() > 0 else 0
                logger.info(f"Column/Key '{key}' has {num_embeddings} cached embeddings.")


if __name__ == "__main__":
    main()