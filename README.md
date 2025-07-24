
# SQL Rail Module

**Version:** 0.0.8
**Date:** June 7, 2025

A Python module designed to parse parameters within the `WHERE` clauses of SQL queries. It then suggests the closest valid or intended matches from predefined reference datasets, helping to catch potential errors or typos in query parameters.

---

## ✨ Features

-   **SQL `WHERE` Clause Parsing**: Intelligently identifies parameters and their values within SQL queries.
-   **Multiple Similarity Metrics**: Compares extracted parameters against reference lists using various algorithms:
    -   Levenshtein Distance (for edit distance)
    -   Jaro-Winkler Similarity (good for short strings, like names)
    -   Token Set Ratio (FuzzyWuzzy-like matching, handles word order and extra/missing words)
-   **Extensible Design**: Easily add your own custom distance or similarity metrics by inheriting from a base class.
-   **Structured Output**: Delivers analysis results in a clear, JSON-friendly format, including suggested corrections and similarity scores.
-   **Reference Data Management**: Utilities to load reference values for columns from JSON files.

---

## 📦 Installation

You can install `sql-rail` using pip:

```bash
pip install sql-rail
````

This will also install necessary dependencies. Key dependencies include:

- `python-Levenshtein`
- `fuzzywuzzy[speedup]`
- `scikit-learn`
- `sqlglot`

Make sure you have Python 3.11+ installed.

---

## Demo in 'example' folder

![](https://github.com/ajayanilkumar/SQL-GuardRails/blob/main/example/GIF/SQL-Rail.gif)

---

## 🚀 Getting Started

Here's how to get up and running with `sql-rail`:

### 1. Loading Reference Data

Your reference data should consist of lists of valid string values for database columns against which query parameters will be checked. `sql-rail` expects this data to be preloaded into a dictionary where keys are column names and values are lists of their valid entries.

There are a couple of utility functions to help you load this data:

**A. Loading all reference data from a directory:**

If you have your reference values in a directory, with each column's values in a separate JSON file named `{column_name}_values.json` (e.g., `country_values.json`), you can use `load_all_reference_data`. Each JSON file should contain a simple list of strings.

```Python
from sql_rail.utils.data_loader_utils import load_all_reference_data

# Example: Your folder "path/to/column/values" might contain:
# - country_values.json: ["United States", "Canada", "United Kingdom", "Germany", ...]
# - vertical_values.json: ["Retail", "Finance", "Healthcare", ...]

reference_data_folder = "path/to/column/values"
column_values_map = load_all_reference_data(reference_data_folder)

# column_values_map will look like:
# {
#   "country": ["United States", "Canada", "United Kingdom", "Germany", ...],
#   "vertical": ["Retail", "Finance", "Healthcare", ...]
# }
```

**B. Loading reference data from a specific JSON file via configuration:**

For more fine-grained control, or if a column's data is in a uniquely named JSON file, use `load_reference_data_from_json`.

```Python
from sql_rail.utils.data_loader_utils import load_reference_data_from_json
from typing import Dict, Any, List # For type hinting context

# Example usage:
browser_config = {"path": "/path/to/your/specific/values.json"}
browser_list = load_reference_data_from_json(browser_config)
# browser_list would be like: ["Chrome", "Firefox", "Safari", ...]

# You would then typically structure this into the main map:
# preloaded_references = {
#     "browser": browser_list,
#     **column_values_map # If using both methods
# }
```

### 2. Initializing `SQLRail`

Once your reference data is loaded (as a dictionary mapping column names to their lists of valid values), you can initialize the `SQLRail` engine. You'll also need to provide a list of the distance/similarity calculators you wish to employ.


```Python
from sql_rail import SQLRail
from sql_rail.core.distance_metrics import (
    LevenshteinDistance,
    JaroWinklerSimilarity,
    TokenSetRatio,
)

# Assuming column_values_map is loaded as shown in step 1A
# column_values_map = load_all_reference_data("directory/to/json_files")

# Initialize SQLRail with desired distance calculators
sql_rail_instance = SQLRail(
    distance_calculators=[
        LevenshteinDistance(),
        JaroWinklerSimilarity(),
        TokenSetRatio(),
    ],
    preloaded_references=column_values_map
)
```

### 3. Understanding Distance & Similarity Metrics 

`sql-rail` uses various metrics to find the closest matches. All metrics are implementations of the `Distance` abstract base class.

**The `Distance` Abstract Base Class:**

This class defines the contract for all similarity and distance calculation strategies.

```Python
from abc import ABC, abstractmethod
from typing import List, Tuple, Optional

class Distance(ABC):
    def __init__(self, **kwargs):
        pass

    @abstractmethod
    def search(self, query_value: str, candidates: List[str], k: int, column_name_or_key: Optional[str] = None) -> List[Tuple[str, float]]:
        """Finds top k matching candidates. Returns list of (candidate, similarity_score 0.0-1.0)."""
        pass

    def preprocess_candidates(self, column_name_or_key: str, candidates: List[str]):
        """Optional: Pre-computation on candidate values (e.g., generating embeddings)."""
        pass

    def get_name(self) -> str:
        return self.__class__.__name__
```

**Pre-defined Metrics:**

- **`LevenshteinDistance`**:
    
    - Calculates similarity based on the Levenshtein (edit) distance: the minimum number of single-character edits (insertions, deletions, or substitutions) required to change one word into the other.
    - Effective for catching typos or minor misspellings.
    - Similarity is normalized: `1.0 - (edit_distance / max_length_of_strings)`.
- **`JaroWinklerSimilarity`**:
    
    - Measures string similarity, giving a higher weight to strings that match from the beginning (prefix).
    - Particularly useful for shorter strings like names or unique identifiers.
    - Outputs a score directly between 0.0 (no similarity) and 1.0 (exact match).
- **`TokenSetRatio`**:
    
    - Leverages `fuzzywuzzy`'s token set ratio logic. It tokenizes strings and compares the intersection and differences of the token sets.
    - Robust against differences in word order and the presence of extra or missing words.
    - Score is normalized to 0.0-1.0 (after dividing `fuzzywuzzy`'s 0-100 score by 100).


### 4. Creating Custom Distance Metrics 🛠️

You can extend `sql-rail` with your own custom similarity logic by inheriting from the `Distance` base class and implementing the required methods.


```Python
from sql_rail.core.distance_metrics import Distance
from typing import List, Tuple, Optional

class MySimpleSubstringMatcher(Distance):
    def __init__(self, case_sensitive: bool = False, **kwargs):
        super().__init__(**kwargs)
        self.case_sensitive = case_sensitive
        # print(f"MySimpleSubstringMatcher initialized (case_sensitive: {self.case_sensitive})")

    def search(self, query_value: str, candidates: List[str], k: int,
               column_name_or_key: Optional[str] = None) -> List[Tuple[str, float]]:
        results = []
        
        processed_query = query_value if self.case_sensitive else query_value.lower()

        for candidate in candidates:
            processed_candidate = candidate if self.case_sensitive else candidate.lower()
            
            score = 0.0
            if processed_query == processed_candidate:
                score = 1.0
            elif processed_query in processed_candidate:
                # Simple score based on length ratio for partial match
                score = len(processed_query) / len(processed_candidate)
            elif processed_candidate in processed_query:
                 score = len(processed_candidate) / len(processed_query)
            
            results.append((candidate, score))

        # Sort by similarity (higher is better) and take top k
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:k]

    def preprocess_candidates(self, column_name_or_key: str, candidates: List[str]):
        # This simple matcher doesn't need preprocessing, but you could implement it here.
        # print(f"Preprocessing {len(candidates)} candidates for '{column_name_or_key}' with MySimpleSubstringMatcher.")
        pass

# To use it:
# sql_rail_instance_custom = SQLRail(
#     distance_calculators=[MySimpleSubstringMatcher(case_sensitive=True)],
#     preloaded_references=column_values_map
# )
```

### 5. Analyzing an SQL Query 🔍

Use the `analyze_query` method of your initialized `SQLRail` instance. Provide the SQL query string and `k` (the number of top suggestions you want for each parameter).


```Python
# Assuming sql_rail_instance is initialized and column_values_map contains 'country' and 'vertical' references.

sql_query_to_analyze = """
SELECT
    country,
    vertical,
    SUM(sales) AS total_sales
FROM
    sales_data
WHERE
    country IN ('Canad', 'United Stats', 'UK') 
    AND vertical = 'Retial'
    AND date > '2024-01-01';
"""

# Analyze the query, requesting top 2 suggestions for each identified parameter
analysis_result = sql_rail_instance.analyze_query(
    sql_query=sql_query_to_analyze,
    k=2 # Number of suggestions per parameter
)

# The result is a Pydantic model, which can be easily printed or converted to dict/JSON
print(analysis_result.model_dump_json(indent=2)) # Pretty print as JSON
```

### 6. Understanding the Output 📊

The `analyze_query` method returns a `GuardRailAnalysisResult` object. Here's an example structure based on the query above and assuming `LevenshteinDistance` was among the calculators:

```JSON
// Example JSON output from analysis_result.model_dump_json(indent=2)
// (Actual scores and suggestions will depend on your reference data and chosen metrics)
{
  "original_query": "SELECT\n    country,\n    vertical,\n    SUM(sales) AS total_sales\nFROM\n    sales_data\nWHERE\n    country IN ('Canad', 'United Stats', 'UK') \n    AND vertical = 'Retial'\n    AND date > '2024-01-01';",
  "analyzed_conditions": [
    {
      "column_name": "country",
      "operator": "IN",
      "raw_value_in_query": "('Canad', 'United Stats', 'UK')",
      "analyses_by_metric": [
        {
          "metric_name": "LevenshteinDistance",
          "query_parameter_value": "Canad",
          "suggestions": [
            { "suggested_value": "Canada", "similarity_score": 0.8333333333333334 },
            { "suggested_value": "Chad", "similarity_score": 0.6 }
          ]
        },
        {
          "metric_name": "LevenshteinDistance",
          "query_parameter_value": "United Stats",
          "suggestions": [
            { "suggested_value": "United States", "similarity_score": 0.8461538461538461 },
            { "suggested_value": "Austria", "similarity_score": 0.4 }
          ]
        },
        {
          "metric_name": "LevenshteinDistance",
          "query_parameter_value": "UK",
          "suggestions": [
            { "suggested_value": "United Kingdom", "similarity_score": 0.15384615384615385 }, // Assuming 'UK' is not a direct match but 'United Kingdom' is in reference
            { "suggested_value": "Ukraine", "similarity_score": 0.1428571428571429 }
          ]
        }
        // ... results from other metrics like JaroWinklerSimilarity, SemanticDistance etc. would also be listed here
      ]
    },
    {
      "column_name": "vertical",
      "operator": "=",
      "raw_value_in_query": "'Retial'",
      "analyses_by_metric": [
        {
          "metric_name": "LevenshteinDistance",
          "query_parameter_value": "Retial",
          "suggestions": [
            { "suggested_value": "Retail", "similarity_score": 0.8333333333333334 },
            { "suggested_value": "Retail & eTail", "similarity_score": 0.5714285714285714 }
          ]
        }
        // ... results from other metrics
      ]
    }
  ],
  "warnings": null // Or a list of warnings, e.g., if a WHERE clause column isn't in reference_data
}
```

**Key components of the output:**

- `original_query`: The exact SQL query string that was analyzed.
- `analyzed_conditions`: A list, where each item represents a condition from the `WHERE` clause that was analyzed (i.e., the column was found in your `preloaded_references`).
    - `column_name`: The database column name (e.g., `country`).
    - `operator`: The SQL operator used (e.g., `IN`, `=`).
    - `raw_value_in_query`: The literal value(s) as they appeared in the SQL query for that column.
    - `analyses_by_metric`: A list of results, one for each distance metric applied to each parameter value.
        - `metric_name`: Name of the distance metric (e.g., `LevenshteinDistance`).
        - `query_parameter_value`: The specific value from the query that was analyzed (e.g., if `country IN ('UK', 'US')`, one analysis block will be for `UK`, and another for `US`).
        - `suggestions`: A list of `MatchSuggestion` objects.
            - `suggested_value`: A potential correct or intended value from your reference list.
            - `similarity_score`: A normalized score (0.0 to 1.0) indicating how similar the `suggested_value` is to the `query_parameter_value`, according to the specific metric. Higher is better.
- `warnings`: A list of any warnings encountered during parsing or analysis (e.g., if a column in a `WHERE` clause condition does not have corresponding reference data, it won't be analyzed, and a warning might be issued).

---

## 🤝 Contributing

Contributions are welcome! If you'd like to contribute, please feel free to fork the repository, make your changes, and submit a pull request. For major changes, please open an issue first to discuss what you would like to change.

(You can add more specific guidelines, like running tests, code style, etc.)

---

## 📄 License

This project is licensed under the MIT License. See the `LICENSE` file for more details.
