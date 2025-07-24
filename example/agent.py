from google.adk.agents import Agent
from google.genai import types
import google.genai as genai
from dotenv import load_dotenv
from typing import Dict, Any

load_dotenv()

import os
import re
import pandas as pd
from sqlalchemy import create_engine, text
import json

llm_client = None
GOOGLE_API_KEY = os.environ["GOOGLE_API_KEY"]

if not GOOGLE_API_KEY:
    print("Error : API Key not found")

llm_client = genai.Client(api_key=GOOGLE_API_KEY)

# --- 0. Setup and Configuration ---

DATABASE_FILE_NAME = 'example/superstore.db'
TABLE_NAME = 'sales'
DB_URI = f'sqlite:///{DATABASE_FILE_NAME}'
REFERENCE_DATA_DIR = 'example/reference_data'

# --- 1. Database and Reference Data Initialization ---

def initialize_database():
    """Checks if the database exists, and if not, creates it from the CSV."""
    if os.path.exists(DATABASE_FILE_NAME):
        print(f"Database '{DATABASE_FILE_NAME}' already exists. Skipping creation.")
        return
    print(f"Database not found. Creating '{DATABASE_FILE_NAME}'...")
    try:
        csv_path = 'example/SampleSuperstore.csv'
        df = pd.read_csv(csv_path, encoding='windows-1252')
        def clean_col_names(df):
            cols = df.columns
            new_cols = [re.sub(r'[^a-zA-Z0-9_]', '', col.lower().replace(' ', '_').replace('-', '_')) for col in cols]
            df.columns = new_cols
            return df
        df = clean_col_names(df)
        engine = create_engine(DB_URI)
        df.to_sql(TABLE_NAME, con=engine, if_exists='replace', index=False)
        print("Database created successfully.")
    except Exception as e:
        print(f"An error occurred during database initialization: {e}")
        exit()

def create_reference_data_if_not_exists():
    """Creates JSON files for categorical columns to be used by sql-rail."""
    if os.path.exists(REFERENCE_DATA_DIR):
        print(f"Reference data directory '{REFERENCE_DATA_DIR}' already exists. Skipping creation.")
        return
    print(f"Creating reference data directory at '{REFERENCE_DATA_DIR}'...")
    os.makedirs(REFERENCE_DATA_DIR)
    try:
        df = pd.read_csv('example/SampleSuperstore.csv', encoding='windows-1252')
        # Use original column names for user-friendliness
        categorical_cols = df.select_dtypes(include=['object']).columns
        # Clean names just for file naming
        cleaned_col_names = {col: re.sub(r'[^a-zA-Z0-9_]', '', col.lower().replace(' ', '_').replace('-', '_')) for col in categorical_cols}

        for col_name in categorical_cols:
            unique_values = df[col_name].unique().tolist()
            file_name = f"{cleaned_col_names[col_name]}_values.json"
            file_path = os.path.join(REFERENCE_DATA_DIR, file_name)
            with open(file_path, 'w') as f:
                json.dump(unique_values, f)
        print("Reference data created successfully.")
    except Exception as e:
        print(f"An error occurred during reference data creation: {e}")
        exit()

# Run initialization steps
initialize_database()
create_reference_data_if_not_exists()
engine = create_engine(DB_URI)

# --- 2. Initialize sql-rail ---
from sql_rail import SQLRail
from sql_rail.core.distance_metrics import LevenshteinDistance, JaroWinklerSimilarity, TokenSetRatio
from sql_rail.utils.data_loader_utils import load_all_reference_data

# Load reference data from the directory we created
column_values_map = load_all_reference_data(REFERENCE_DATA_DIR)

# Initialize SQLRail instance
sql_rail_instance = SQLRail(
    distance_calculators=[
        LevenshteinDistance(),
        JaroWinklerSimilarity(),
        TokenSetRatio(),
    ],
    preloaded_references=column_values_map
)
print("\n--- sql-rail initialized successfully ---")

# --- 3. Define the Tools for the Agent ---

def generate_sql(user_query: str) -> str:
    """Generates an SQL query from a user's natural language question."""
    schema_prompt = f"""
    You are a text-to-SQL model. Your task is to generate a SQL query based on the user's question.
    The query will be executed on a table named 'sales'.
    The schema of the 'sales' table is: ['row_id', 'order_id', 'order_date', 'ship_date', 'ship_mode', 'customer_id', 'customer_name', 'segment', 'country', 'city', 'state', 'postal_code', 'region', 'product_id', 'category', 'subcategory', 'product_name', 'sales', 'quantity', 'discount', 'profit']
    Generate only the SQL query. Try not to use string matching conditions as that it handled by another function.

    * **Column Names:** Use *ONLY* the column names mentioned in the Schema details below. Enclose column names in double quotes if they contain special characters or match reserved words, otherwise quotes are optional but recommended for clarity. Use the exact column names as given above.
    * **Schema Adherence:** Strictly use the columns and types defined in the schema. Pay attention to column descriptions and sample values for context. eg: (product_name)
    * **Filtering:** Use `WHERE` clauses effectively based on the user's question. Use single quotes for string literals (e.g., `WHERE country = 'Canada'`).


    Question: {user_query}
    SQL Query:
    """
    generation_config = genai.types.GenerateContentConfig(temperature=0.1)

    response = llm_client.models.generate_content(
        model = "gemini-2.0-flash",
        contents = schema_prompt,
        config = generation_config,
    )

    sql_query = response.text.strip()

    # Remove potential markdown fences (same logic applies)
    if sql_query.startswith("```sql"):
        sql_query = sql_query[len("```⁠sql"):].strip()
    if sql_query.endswith("```"):
        sql_query = sql_query[:-len("```")].strip()

    # Basic check for SELECT statement (same logic applies)
    if not sql_query or not sql_query.lower().startswith("select"):
            return f"Error: Generated invalid SQL - {sql_query}" # Return error string

    return sql_query



def sql_rails_validator(sql_query: str) -> Dict[str, Any]:
    """
    Validates SQL query parameters against preloaded reference data and
    suggests closest matches for potentially invalid parameters.

    Args:
        sql_query: The SQL query string to analyze.

    Returns:
        A dictionary containing the analysis results.
    """

    # Try to convert analysis_result to a dict for JSON serialization
    try:
    
        result = sql_rail_instance.analyze_query(sql_query=sql_query.lower(), k=3)
        analysis_results = []
        for condition in result.analyzed_conditions:
            suggestions_by_metric = {}
            for metric_analysis in condition.analyses_by_metric:
                suggestions = []
                for suggestion in metric_analysis.suggestions:
                    suggestions.append({
                        "suggested_value": suggestion.suggested_value,
                        "similarity_score": suggestion.similarity_score
                    })
                suggestions_by_metric[metric_analysis.metric_name] = suggestions
            analysis_results.append({
                "column_name": condition.column_name,
                "operator": condition.operator,
                "raw_value_in_query": condition.raw_value_in_query,
                "suggestions": suggestions_by_metric
            })

        return {"analysis": analysis_results}
    except Exception as e:
        return {"error": f"Error during SQL parameter validation: {e}"}

def execute_sql(sql_query: str) -> str:
    """Executes a validated SQL query on the 'sales' table and returns the result."""
    print(f"\n--- Executing SQL Query: {sql_query} ---")
    try:
        with engine.connect() as connection:
            result_df = pd.read_sql(text(sql_query), connection)
            if result_df.empty:
                return "Query executed successfully, but returned no results."
            return result_df.to_string()
    except Exception as e:
        return f"Execution Error: {e}"

# --- 4. Create the LangChain Tools and Agent ---

from typing import Dict, Any, Optional


root_agent = Agent(
    model="gemini-2.5-flash",
    name="sql_agent",
    instruction="""You are a helpful AI assistant specialized in querying an sqlalchemy database table named `sales`. Your goal is to help users explore this table using natural language.

**Your Capabilities:**
* Understand user requests in natural language regarding the `sales` table.
* Maintain conversation history and use context from previous turns to understand follow-up questions.
* Use the provided tools to generate and execute SQL queries.
* Format and present the results clearly, including summarizing findings or showing data tables.
* Explain any errors encountered during query generation or execution.
* Utilize the `sql_rails_validator` tool to check the validity of parameters in the generated SQL and suggest corrections.

**Available Tools:**

* **`generate_sql`**: Use this tool to convert a user's natural language question (potentially informed by conversation context) into a SQL query. Input is the natural language question. Output is the generated SQL string.
* **`sql_rails_validator`**: Use this tool to analyze the SQL query generated by `generate_sql` and identify potential issues with the parameters used in `WHERE` clauses (e.g., typos, abbreviations). Input is the SQL string. Output is a dictionary containing analysis results with suggested corrections and similarity scores, or an empty list if no issues are found.
* **`execute_sql`**: Use this tool to execute a provided SQL query against the database.

**Workflow:**
1.  **Analyze Request:** Understand the user's latest query in the context of the conversation history. Determine if it's a request about the `sales` table. If it's a greeting or off-topic, respond conversationally. If it is a complex request, break it down into simpler parts.
2.  **Generate SQL (if applicable):** If the request requires querying the table, call the `generate_sql` tool, providing the user's question (potentially reformulated based on context).
3.  **Validate SQL Parameters:** If the SQL string returned by `generate_sql` has a where claude, pass it to the `sql_rails_validator` tool.
4.  **Handle Parameter Issues (if any):**
    * If parameters returned are valid, just proceed to `execute_sql`. DO NOT ask the user for confirmation.
    * If `sql_rails_validator` returns changes that do not match the query, present them to the user and ask if they want to use any of the corrections. 
    * If changes are required and the user agrees to a correction, you should modify the SQL query directly (with caution) and proceed to `execute_sql`.
5.  **Execute SQL (if applicable):** Take the SQL string returned by `generate_sql` or corrected by you and pass it to the `execute_sql` tool.
6.  **Format Response:**
    * If `execute_sql` returns a `query_result`, summarize the findings in natural language and/or present the data clearly (e.g., as a markdown table). You can optionally include the executed SQL for transparency.
    * If `execute_sql` returns an `error_message`, explain the error to the user in a helpful way. Do not show the erroneous SQL unless specifically asked or it helps clarify the error.
    * If `generate_sql` fails to produce valid SQL, inform the user you couldn't translate their request.

**Table Schema:**
['row_id', 'order_id', 'order_date', 'ship_date', 'ship_mode', 'customer_id', 'customer_name', 'segment', 'country', 'city', 'state', 'postal_code', 'region', 'product_id', 'category', 'subcategory', 'product_name', 'sales', 'quantity', 'discount', 'profit']

USE ONLY THE ABOVE COLUMN NAMES in SQL Generation. Dont change the casing. Let everything be in lower case.


    """,
    tools=[
        generate_sql,
        sql_rails_validator,
        execute_sql,
    ],
    generate_content_config=types.GenerateContentConfig(temperature=0.2),

)




