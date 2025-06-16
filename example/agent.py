from google.adk.agents import Agent
from google.genai import types
import google.genai as genai
from dotenv import load_dotenv

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

DATABASE_FILE_NAME = 'examplesuperstore.db'
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
    The schema of the 'sales' table is: 'ship_mode', 'segment', 'country', 'city', 'state', 'postal_code', 'region', 'category', 'sub_category', 'sales', 'quantity', 'discount', 'profit'.
    Generate only the SQL query.
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



def sql_rails_validator(sql_query: str) -> str:
    """
    Validates the WHERE conditions in a SQL query using sql-rail.
    If a parameter has a low similarity score to the reference data, it raises an error.
    """
    print(f"\n--- Validating SQL Query with sql-rail: {sql_query} ---")
    if "WHERE" not in sql_query.upper():
        print("No WHERE clause found. Skipping validation.")
        return sql_query
        
    analysis_result = sql_rail_instance.analyze_query(sql_query=sql_query, k=1)
    
    for condition in analysis_result.analyzed_conditions:
        for analysis in condition.analyses_by_metric:
            # We only care about the first (top) suggestion
            if analysis.suggestions:
                top_suggestion = analysis.suggestions[0]
                if top_suggestion.similarity_score < 1.0:
                    error_message = (
                        f"Validation Error: Potential typo found. "
                        f"Value '{analysis.query_parameter_value}' in column '{condition.column_name}' is not an exact match. "
                        f"Did you mean '{top_suggestion.suggested_value}'? "
                        f"(Similarity score: {top_suggestion.similarity_score:.2f})"
                    )
                    raise ValueError(error_message)
                    
    print("--- SQL Query validation successful ---")
    return sql_query

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
    model="gemini-2.0-flash",
    name="sql_agent",
    instruction="""You are a specialized AI agent designed to answer questions about a sales database.

Your goal is to answer the user's question by following a strict, multi-step process:
1.  Generate a SQL query from the user's question.
2.  Validate the generated SQL query to catch potential typos or errors in the `WHERE` clause.
3.  If validation fails, you MUST correct the SQL query based on the feedback and re-validate it.
4.  Once the query is successfully validated, execute it to retrieve the final answer.
5.  Provide the final answer to the user.
    """,
    tools=[
        generate_sql,
        sql_rails_validator,
        execute_sql,
    ],
    generate_content_config=types.GenerateContentConfig(temperature=0.2),

)




