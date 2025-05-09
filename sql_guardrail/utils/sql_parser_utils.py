# sql_guardrail/utils/sql_parser_utils.py
import sqlparse
from sqlparse.sql import Identifier, Comparison, Parenthesis, TokenList, Where
from sqlparse.tokens import Keyword, DML, Punctuation, Literal, Name, Operator
from typing import List, Dict, Any, Union, Tuple

import logging
logger = logging.getLogger(__name__)

def _extract_value_from_token(token) -> Union[str, List[str], None]:
    """
    Extracts value(s) from a token (string literal, identifier, or parenthesized list).
    
    Args:
        token: A sqlparse token to extract values from
        
    Returns:
        String value, list of string values, or None if extraction fails
    """
    logger.debug(f"Extracting value from token: {token}, type: {type(token)}, ttype: {token.ttype}")
    
    # Handle string literals
    if token.ttype in Literal.String:
        value = str(token)
        # Remove surrounding quotes
        return value[1:-1] if value and len(value) >= 2 and value[0] in ["'", '"'] and value[-1] in ["'", '"'] else value
    
    # Handle parenthesized lists (for IN clause)
    elif isinstance(token, Parenthesis):
        content = str(token)[1:-1].strip()  # Remove parentheses
        if not content:
            return []
            
        # Split based on commas, considering quoted strings
        import re
        values = []
        
        # Find all quoted strings
        matches = re.findall(r'\'([^\']*?)\'|\"([^\"]*?)\"', content)
        if matches:
            for match in matches:
                # Each match is a tuple with two elements, one of which is empty
                value = match[0] if match[0] else match[1]
                values.append(value)
        
        return values if values else None
    
    # Handle other cases
    elif isinstance(token, Identifier):
        return str(token).strip()
        
    logger.debug(f"Could not extract value from token: {token}")
    return None

def parse_sql_where_clauses(sql_query: str) -> List[Dict[str, Any]]:
    """
    Parses an SQL query to extract conditions from WHERE clauses.
    Focuses on column-operator-value expressions for string literals.
    
    Args:
        sql_query: SQL query string to parse
        
    Returns:
        List of dictionaries containing parsed WHERE clause conditions
    """
    parsed_conditions = []
    
    try:
        # Parse the SQL query
        parsed = sqlparse.parse(sql_query)
        logger.debug(f"Parsed SQL: {parsed}")
        
        if not parsed or len(parsed) == 0:
            logger.warning(f"Failed to parse SQL query: {sql_query}")
            return []
            
        for stmt in parsed:
            # Find WHERE clauses
            where_clauses = []
            
            def find_where_tokens(token_list):
                for token in token_list.tokens:
                    if isinstance(token, Where):
                        where_clauses.append(token)
                    elif token.is_group:
                        find_where_tokens(token)

            find_where_tokens(stmt)
            logger.debug(f"Found {len(where_clauses)} WHERE clauses")
            
            # Process each WHERE clause
            for where_token in where_clauses:
                # First, check for direct Comparison tokens inside the WHERE clause
                for token in where_token.tokens:
                    if isinstance(token, Comparison):
                        # Process the comparison (column = value)
                        comp_tokens = [t for t in token.tokens if not t.is_whitespace]
                        
                        if len(comp_tokens) >= 3:
                            # Extract column name, operator, and value
                            column_name = str(comp_tokens[0]).strip()
                            operator = str(comp_tokens[1]).strip().upper()
                            value_token = comp_tokens[2]
                            
                            # Extract value based on token type
                            value = _extract_value_from_token(value_token)
                            
                            if value is not None:
                                parsed_conditions.append({
                                    "column_name": column_name,
                                    "operator": operator,
                                    "query_parameter_values": [value] if not isinstance(value, list) else value,
                                    "raw_value_in_query": str(value_token).strip()
                                })
                                logger.debug(f"Added condition from Comparison: {column_name} {operator} {value}")
                
                # If no direct comparisons were found, try to manually identify patterns
                tokens = [t for t in where_token.tokens if not t.is_whitespace and t.ttype is not Keyword]
                
                i = 0
                while i < len(tokens):
                    token = tokens[i]
                    
                    # Pattern: Identifier Operator Value
                    if isinstance(token, Identifier) and i + 2 < len(tokens):
                        column_name = str(token).strip()
                        op_token = tokens[i+1]
                        val_token = tokens[i+2]
                        
                        if op_token.ttype == Operator or str(op_token).upper() in ['IN', 'LIKE', '=']:
                            operator = str(op_token).upper().strip()
                            
                            # Handle IN clause
                            if operator == 'IN' and isinstance(val_token, Parenthesis):
                                values = _extract_value_from_token(val_token)
                                if values:
                                    parsed_conditions.append({
                                        "column_name": column_name,
                                        "operator": operator,
                                        "query_parameter_values": values if isinstance(values, list) else [values],
                                        "raw_value_in_query": str(val_token).strip()
                                    })
                                    logger.debug(f"Added IN condition: {column_name} {operator} {values}")
                                i += 3
                                continue
                            
                            # Handle simple equality or LIKE
                            elif val_token.ttype in Literal.String:
                                value = _extract_value_from_token(val_token)
                                if value is not None:
                                    parsed_conditions.append({
                                        "column_name": column_name,
                                        "operator": operator,
                                        "query_parameter_values": [value],
                                        "raw_value_in_query": str(val_token).strip()
                                    })
                                    logger.debug(f"Added condition: {column_name} {operator} {value}")
                                i += 3
                                continue
                    
                    i += 1
                
        logger.debug(f"Final parsed conditions: {parsed_conditions}")
        return parsed_conditions
        
    except Exception as e:
        logger.error(f"Error parsing SQL WHERE clauses: {e}", exc_info=True)
        return []