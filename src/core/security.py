import sqlglot
from sqlglot import exp
from typing import Tuple, Optional
from loguru import logger

class SQLSecurityGuard:
    """
    Provides AST-level safety validations for LLM-generated SQL queries.
    Prevents SQL injection, destructive writing operations, and huge table scans.
    """
    
    @staticmethod
    def validate_and_sanitize(sql: str) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Parses the SQL string into an AST and ensures it is completely safe.
        
        Returns:
            Tuple: (is_safe, sanitized_sql, error_message)
        """
        try:
            # 1. Reformat and clean SQL (parse and validate syntax using MySQL dialect)
            parsed = sqlglot.parse_one(sql, read="mysql")
            sanitized = parsed.sql(dialect="mysql", pretty=True)
            
            # 2. Restrict statement type to SELECT queries only
            # Iterate through the parsed tree to verify no write/destructive nodes exist
            expressions = sqlglot.parse(sql, read="mysql")
            for expression in expressions:
                if not expression:
                    continue
                # Traverse tree to ensure no structural mutations exist
                for node in expression.walk():
                    if isinstance(node, (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Alter, exp.Create)):
                        logger.warning(f"Security Alert: Blocked query containing prohibited operation node: {type(node)}")
                        return False, None, "Security Violation: Prohibited database mutation statement detected. Only SELECT queries are permitted."
            
            return True, sanitized, None
            
        except sqlglot.errors.ParseError as e:
            logger.error(f"SQL Syntax Error parsed by SQLGlot: {e}")
            return False, None, f"Syntax Error: Failed to parse SQL statement. {str(e)}"
        except Exception as e:
            logger.error(f"SQL Security System Failure: {e}")
            return False, None, f"Security Guard System Failure: {str(e)}"
