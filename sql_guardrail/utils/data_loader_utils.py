# sql_guardrail/utils/data_loader_utils.py
import csv
import logging
import json
from typing import List, Dict, Any, Optional, Mapping
import os
import re


logger = logging.getLogger(__name__)

def load_reference_data_from_file(config: Dict[str, Any]) -> List[str]:
    """
    Loads reference data from a CSV file based on configuration.

    Args:
        config: A dictionary, e.g.,
                {"path": "file.csv", "value_column": 0} or
                {"path": "file.csv", "value_column": "CountryName"}

    Returns:
        A list of string values from the specified column.
    """
    file_path = config.get("path")
    if not file_path:
        logger.error("File path missing in reference data configuration.")
        return []

    value_column_key = config.get("value_column", 0) # Default to first column (index 0)
    values: List[str] = []

    try:
        with open(file_path, mode='r', encoding='utf-8-sig') as infile: # utf-8-sig handles BOM
            reader = csv.reader(infile)
            header = next(reader, None) # Read header

            if header is None:
                logger.warning(f"CSV file is empty: {file_path}")
                return []

            col_idx: Optional[int] = None
            if isinstance(value_column_key, int):
                if 0 <= value_column_key < len(header):
                    col_idx = value_column_key
                else:
                    logger.error(f"Column index {value_column_key} out of bounds for file {file_path} with {len(header)} columns.")
                    return []
            elif isinstance(value_column_key, str):
                try:
                    col_idx = header.index(value_column_key)
                except ValueError:
                    logger.error(f"Column name '{value_column_key}' not found in header of {file_path}. Header: {header}")
                    return []
            else:
                logger.error(f"Invalid value_column type '{type(value_column_key)}' in config for {file_path}.")
                return []

            if col_idx is not None:
                for row in reader:
                    if len(row) > col_idx:
                        values.append(str(row[col_idx]).strip())
                    else:
                        logger.warning(f"Row too short in {file_path}: {row}")
            return values
    except FileNotFoundError:
        logger.error(f"Reference data file not found: {file_path}")
    except Exception as e:
        logger.error(f"Error reading reference data file {file_path}: {e}")
    return []


def load_reference_data_from_json(config: Dict[str, Any]) -> List[str]:
    """
    Loads reference data from a JSON file based on configuration.
    Expected JSON format: An array of strings representing values for the column.

    Args:
        config: A dictionary, e.g., {"path": "browser_values.json"}

    Returns:
        A list of string values from the JSON file.
    """
    file_path = config.get("path")
    if not file_path:
        logger.error("File path missing in reference data configuration.")
        return []

    try:
        with open(file_path, mode='r', encoding='utf-8-sig') as infile:
            values = json.load(infile)
            
            # Validate that the loaded data is a list
            if not isinstance(values, list):
                logger.error(f"JSON file {file_path} does not contain a list. Found {type(values)}.")
                return []
                
            # Convert all values to strings
            string_values = [str(val).strip() for val in values]
            return string_values
            
    except FileNotFoundError:
        logger.error(f"Reference data file not found: {file_path}")
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in file {file_path}: {e}")
    except Exception as e:
        logger.error(f"Error reading reference data file {file_path}: {e}")
    return []


def discover_reference_json_files(directory_path: str) -> Dict[str, str]:
    """
    Discovers all JSON files matching the pattern {column_name}_values.json 
    in the specified directory.

    Args:
        directory_path: Path to the directory containing reference JSON files.

    Returns:
        A dictionary mapping column names to file paths.
    """
    reference_files = {}
    
    try:
        for filename in os.listdir(directory_path):
            if filename.endswith('_values.json'):
                match = re.match(r'(.+)_values\.json\$', filename)
                if match:
                    column_name = match.group(1)
                    file_path = os.path.join(directory_path, filename)
                    reference_files[column_name] = file_path
                    logger.debug(f"Discovered reference data for column '{column_name}': {file_path}")
    except Exception as e:
        logger.error(f"Error discovering reference JSON files in {directory_path}: {e}")
    
    return reference_files


def load_all_reference_data(directory_path: str) -> Dict[str, List[str]]:
    """
    Loads all reference data from JSON files in the specified directory.

    Args:
        directory_path: Path to the directory containing reference JSON files.

    Returns:
        A dictionary mapping column names to lists of reference values.
    """
    reference_data = {}
    reference_files = discover_reference_json_files(directory_path)
    
    for column_name, file_path in reference_files.items():
        config = {"path": file_path}
        values = load_reference_data_from_json(config)
        if values:
            reference_data[column_name] = values
            logger.info(f"Loaded {len(values)} reference values for column '{column_name}'")
    
    return reference_data