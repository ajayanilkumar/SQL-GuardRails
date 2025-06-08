# sql_guardrail/utils/sql_parser_utils.py
import sqlglot
import sqlglot.expressions as exp
from typing import List, Dict, Any, Union, Optional, Tuple
import logging

logger = logging.getLogger(__name__)

def _extract_literal_value(value_node: exp.Expression) -> Optional[str]:
    """
    Extracts the string representation of a literal value from a sqlglot node.
    Handles Strings, Numbers, Booleans, and Nulls.

    Args:
        value_node: A sqlglot expression node.

    Returns:
        The string representation of the literal, or None if not a simple literal.
    """
    if isinstance(value_node, exp.Literal):
        if value_node.is_string:
            return str(value_node.this) # .this gives the string content without quotes
        # Check for Python bool type if sqlglot wraps it in a generic Literal
        # However, exp.Boolean is more specific.
        elif isinstance(value_node.this, bool): # Handles cases where a boolean might be parsed as Literal(this=True)
            return str(value_node.this).upper()
        else:
            return str(value_node.this) # For numbers, .this holds the number
    elif isinstance(value_node, exp.Boolean): # Explicit handling for sqlglot's Boolean expression
        return str(value_node.this).upper() # 'TRUE' or 'FALSE'
    elif isinstance(value_node, exp.Null):
        return "NULL"
    else:
        logger.debug(f"Node is not a simple literal: {type(value_node)} - {value_node.sql()}")
        return None

def _parse_condition(condition_expression: exp.Expression) -> Optional[Union[Dict[str, Any], List[Dict[str, Any]]]]:
    """
    Parses a single sqlglot condition expression (like EQ, In, Like, Is)
    into the desired dictionary format or a list of dictionaries for IN clauses.

    Args:
        condition_expression: A sqlglot expression node representing a condition.

    Returns:
        A dictionary representing the parsed condition, 
        a list of dictionaries for IN/NOT IN clauses with multiple literal values,
        or None if parsing fails or the condition is not a simple column-operator-literal(s) type.
    """
    column_node: Optional[exp.Expression] = None
    value_nodes: List[exp.Expression] = []
    operator_str: Optional[str] = None
    # is_negated for IN, LIKE, IS is handled by how operator_str is formed.
    # Negation like NOT (A=B) is a more complex AST transformation not fully handled here.

    # Determine operator, column, value(s) based on expression type
    if isinstance(condition_expression, (exp.EQ, exp.NEQ, exp.GT, exp.LT, exp.GTE, exp.LTE)):
        column_node = condition_expression.left
        value_nodes = [condition_expression.right]
        op_map = {
            exp.EQ: '=', exp.NEQ: '!=', exp.GT: '>', exp.LT: '<',
            exp.GTE: '>=', exp.LTE: '<='
        }
        operator_str = op_map.get(type(condition_expression))
    elif isinstance(condition_expression, exp.In):
        column_node = condition_expression.this
        value_nodes = condition_expression.expressions if hasattr(condition_expression, 'expressions') else []
        is_negated = condition_expression.args.get("not", False)
        operator_str = "NOT IN" if is_negated else "IN"
    elif isinstance(condition_expression, exp.Like):
        column_node = condition_expression.this
        value_nodes = [condition_expression.expression]
        is_negated = condition_expression.args.get("not", False)
        operator_str = "NOT LIKE" if is_negated else "LIKE"
    elif isinstance(condition_expression, exp.Is):
        column_node = condition_expression.this
        value_nodes = [condition_expression.expression] # Should be exp.Null or exp.Boolean
        is_negated = condition_expression.args.get("not", False)
        operator_str = "IS NOT" if is_negated else "IS"
    else:
        logger.debug(f"Unsupported condition type for _parse_condition: {type(condition_expression)} - {condition_expression.sql()}")
        return None

    # --- Validation of Column and Operator ---
    if not isinstance(column_node, exp.Column):
        logger.debug(f"Condition LHS is not a simple column: {type(column_node)} in '{condition_expression.sql()}'")
        return None
    
    # Use .sql() for potentially quoted or complex identifiers for column name
    parsed_column_name = column_node.sql()

    if operator_str is None: # Should ideally not happen with current checks
        logger.warning(f"Could not determine operator for condition: {condition_expression.sql()}")
        return None

    # Collect raw SQL for all value nodes upfront
    raw_sql_for_value_nodes = [vn.sql() for vn in value_nodes]

    # --- Special handling for IN/NOT IN clauses ---
    if operator_str in ("IN", "NOT IN"):
        if not value_nodes: # Handles IN () or NOT IN ()
            return {
                "column_name": parsed_column_name,
                "operator": operator_str,
                "query_parameter_values": [],
                "raw_value_in_query": "()" # Standard SQL for empty IN list
            }

        per_value_conditions = []
        for i, current_value_node in enumerate(value_nodes):
            literal_str = _extract_literal_value(current_value_node)
            if literal_str is not None: # This item in the IN list is an extractable literal
                per_value_conditions.append({
                    "column_name": parsed_column_name,
                    "operator": operator_str, # Retain "IN" or "NOT IN"
                    "query_parameter_values": [literal_str], # List contains the single literal value
                    "raw_value_in_query": raw_sql_for_value_nodes[i] # Raw SQL of the individual value
                })
        
        if per_value_conditions: # If we found any literals in the IN list
            return per_value_conditions
        else: # IN list with no literals (e.g., IN (colA, colB))
            logger.debug(f"IN/NOT IN clause '{condition_expression.sql()}' contains no extractable literal values.")
            return None # Not extracting if no literals found in IN list

    # --- Handling for operators other than IN/NOT IN (EQ, GT, LT, LIKE, IS) ---
    # These operators generally expect a single value on the RHS.
    if not value_nodes:
        logger.warning(f"Operator '{operator_str}' in '{condition_expression.sql()}' is missing its RHS value node.")
        return None
    if len(value_nodes) > 1:
        # This could happen if sqlglot parses something like `col = (val1, val2)` which is not standard for these ops.
        logger.warning(f"Operator '{operator_str}' in '{condition_expression.sql()}' has multiple RHS value nodes: {[vn.sql() for vn in value_nodes]}. Expected one.")
        return None # Treat as non-extractable if RHS is not a single element for these operators

    # At this point, value_nodes has exactly one element for non-IN/NOT IN operators.
    val_node = value_nodes[0]
    # raw_sql_for_val = val_node.sql() # Or raw_sql_for_value_nodes[0]
    raw_sql_for_val = raw_sql_for_value_nodes[0] if raw_sql_for_value_nodes else val_node.sql() # Defensive
    
    literal_str = _extract_literal_value(val_node)

    if operator_str in ("IS", "IS NOT"):
        # For IS/IS NOT, the literal_str should be "NULL", "TRUE", or "FALSE"
        if literal_str in ("NULL", "TRUE", "FALSE"):
            return {
                "column_name": parsed_column_name,
                "operator": operator_str,
                "query_parameter_values": [literal_str], # e.g., ["NULL"]
                "raw_value_in_query": raw_sql_for_val    # e.g., "NULL", "TRUE"
            }
        else:
            logger.debug(f"IS/IS NOT operator in '{condition_expression.sql()}' has a non-standard or non-literal RHS '{raw_sql_for_val}'. Expected NULL, TRUE, or FALSE.")
            return None
    else: # For EQ, GT, LT, GTE, LTE, LIKE
        if literal_str is not None: # RHS is an extractable literal
            return {
                "column_name": parsed_column_name,
                "operator": operator_str,
                "query_parameter_values": [literal_str],
                "raw_value_in_query": raw_sql_for_val
            }
        else: # RHS is not a simple literal (e.g., another column, a function call)
            logger.debug(f"Operator '{operator_str}' in '{condition_expression.sql()}' has a non-literal RHS '{raw_sql_for_val}'.")
            return None
    
    # Fallback, should ideally not be reached if all cases for supported operators are covered
    logger.error(f"Unhandled case in _parse_condition for {condition_expression.sql()}. This should not happen.")
    return None


def parse_sql_where_clauses(sql_query: str, dialect: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Parses an SQL query using sqlglot to extract conditions from WHERE clauses.
    Focuses on simple column-operator-literal expressions (e.g., =, IN, LIKE, IS NULL).
    For IN clauses with multiple literals, each literal will result in a separate entry.

    Args:
        sql_query: The SQL query string to parse.
        dialect: Optional sqlglot dialect string (e.g., "mysql", "postgres", "tsql", "bigquery").
                 If None, sqlglot attempts to guess.

    Returns:
        A list of dictionaries, where each dictionary represents a parsed WHERE clause condition
        matching the specified format. Returns empty list on parsing errors or if no suitable
        conditions are found.
    """
    parsed_conditions: List[Dict[str, Any]] = []
    try:
        parsed_expressions = sqlglot.parse(sql_query, read=dialect)
        if not parsed_expressions:
            logger.warning(f"sqlglot could not parse the query: {sql_query}")
            return []

        for expression_tree in parsed_expressions:
            if expression_tree is None: continue

            for where_clause in expression_tree.find_all(exp.Where):
                condition_root = where_clause.this # The root of the condition (e.g. an exp.And, exp.Or, or a single condition)

                # Define the specific expression types we want to extract conditions from
                supported_condition_types = (
                    exp.EQ, exp.NEQ, exp.GT, exp.LT, exp.GTE, exp.LTE, # Basic comparisons
                    exp.In, exp.Like, exp.Is # Other supported types
                )
                # We need to find all instances of these supported types within the WHERE clause's condition tree
                for comparison_node in condition_root.find_all(*supported_condition_types):
                    # Example: In "A=1 AND NOT (B=2)", find_all(exp.EQ) yields A=1 and B=2.
                    # The negation of B=2 is not directly handled by _parse_condition for EQ here.
                    # _parse_condition handles negation if it's part of the node itself (e.g. NOT IN, IS NOT).
                    
                    parsed_item = _parse_condition(comparison_node)
                    
                    if parsed_item:
                        if isinstance(parsed_item, list): # For IN clauses that were split
                            for item_dict in parsed_item:
                                # Basic check to avoid adding exact duplicates if query structure somehow leads to it
                                # (less likely with per-value splitting but good for safety)
                                if item_dict not in parsed_conditions:
                                    parsed_conditions.append(item_dict)
                        elif isinstance(parsed_item, dict): # For single conditions
                            if parsed_item not in parsed_conditions:
                                 parsed_conditions.append(parsed_item)

    except sqlglot.errors.ParseError as e:
        logger.error(f"sqlglot failed to parse SQL query '{sql_query}'. Error: {e}", exc_info=False)
        logger.debug(f"sqlglot ParseError details:", exc_info=True) # exc_info=True for debug log
        return []
    except Exception as e:
        logger.error(f"Error processing SQL WHERE clauses with sqlglot for query '{sql_query}': {e}", exc_info=True)
        return []

    logger.info(f"Parsed {len(parsed_conditions)} conditions from query '{sql_query}'.")
    return parsed_conditions


# Example Usage (can be removed or placed in a test file)
if __name__ == '__main__':
    # Configure logging to see debug messages from the parser
    # logging.basicConfig(level=logging.DEBUG) # Uncomment for detailed parsing logs
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(name)s: %(message)s') # Cleaner default output
    logger.name = __name__ # Ensure logger name is set for __main__ context if not already configured


    test_queries = [
        "SELECT a, b FROM my_table WHERE id = 123 AND name = 'test_user' AND status IN ('active', 'pending') AND description LIKE '%pattern%' AND created_at > '2023-01-01' AND flag IS TRUE AND notes IS NOT NULL AND value != 45.6 AND role NOT IN ('guest') AND name LIKE 'A%' AND amount >= 100 AND type_code IN (10, 20, 30)",
        "SELECT * FROM another_table WHERE user_id IN (1, 2, 3) OR active = false", # Note: OR conditions are parsed as separate branches by sqlglot
        "SELECT col FROM table3 WHERE complex_col = other_col OR val = FUNCTION(x)", # Non-literals, should not be extracted
        "UPDATE stats SET count = 1 WHERE date = '2024-05-13' AND category IN ('A')",
        "SELECT 1 WHERE 1=1", # Simple case
        "SELECT * FROM empty_table WHERE id IN ()", # Empty IN list
        "SELECT * from tsql_table where col = N'nvarchar_string'", # Dialect specific string (ensure dialect is passed if needed)
        """
        SELECT *
        FROM my_table
        WHERE column1 = 'value1' AND column2 > 10 OR column3 IN ('valA', 'valB') AND NOT column4 LIKE 'prefix%'
        GROUP BY some_column
        LIMIT 10;
        """,
        # The problematic query from the user
        """SELECT
        browser,
        country,
        vertical,
        sub_vertical,
    FROM
        user_sessions 
    WHERE
        country IN ('India', 'USA', 'Germany', 'Brazil', 'Japan')
        AND browser NOT IN ('Internet Explorer', 'Opera Mini', 'Safari 7')
        AND vertical IS NOT NULL
        AND NOT (sub_vertical = 'Search Engine Optimization') -- This NOT() around EQ is not handled for operator negation
        AND (browser = 'Chrome' OR country = 'United Kingdom');
        """,
        "SELECT * FROM test WHERE status IN ('A', 'B', 'C') AND id = 1",
        "SELECT * FROM test WHERE tags NOT IN ('internal', 'deprecated') AND name IS NOT NULL",
        "SELECT * FROM test WHERE value_col = 123.45 AND is_active = TRUE AND is_processed = FALSE",
        "SELECT * FROM test WHERE name = 'single_in' AND category IN ('X')",
        "SELECT * FROM test WHERE items IN (col_a, 'literal_b', 123)", # Mixed IN list
        """SELECT
        browser,
        country,
        vertical,
        sub_vertical,
    FROM
        user_sessions -- Changed table name to something more fitting
    WHERE
        country IN ('India', 'USA', 'Germany', 'Brazil', 'Japan')
        AND browser NOT IN ('Internet Explorer', 'Opera Mini', 'Safari 7')
        AND vertical IS NOT NULL
        AND NOT (sub_vertical = 'Search Engine Optimization')
        AND (browser != 'Chrome' OR country = 'United Kingdom');
        """
    ]

    for sql in test_queries:
        print("-" * 50)
        print(f"Query: {sql}")
        
        # Try with dialect guessing first (None)
        # For specific dialect features like N'string' in T-SQL, specify the dialect.
        # dialect_to_use = 'tsql' if "N'" in sql else None
        conditions = parse_sql_where_clauses(sql, dialect=None) # dialect_to_use)
        
        print("Parsed Conditions:")
        import json
        # Using a custom encoder for any non-serializable types if they were to appear, though unlikely here.
        print(json.dumps(conditions, indent=2))
        print("-" * 50)

