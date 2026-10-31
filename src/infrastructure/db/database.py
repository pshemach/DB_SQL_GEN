"""
Database utilities for schema inspection and query execution.
"""

from typing import List, Dict, Any, Optional
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import SQLAlchemyError
import sqlglot
from loguru import logger

from pathlib import Path
import time
from src.infrastructure.db.sql_safety import assess_sql
from src.infrastructure.config import DATABASE_URI, QUERY_TIMEOUT_SECONDS 

class DatabaseManager:
    """Manages database connections and operations."""
    def __init__(self, database_uri: Optional[str] = None):
        self.database_uri = database_uri or DATABASE_URI
        if not self.database_uri:
            raise ValueError("DATABASE_URI is not set. Add it to the .env file.")
        
        # Create data directory if using SQLite and directory doesn't exist
        self._ensure_database_directory()
        
        self.engine = create_engine(self.database_uri)
        self.inspector = inspect(self.engine)
        self._schema_cache: Dict[str, str] = {}
        logger.info(f"Connected to database: {self.database_uri}")
        
    def _ensure_database_directory(self):
        """Create database directory if it doesn't exist (for SQLite)."""
        if self.database_uri.startswith('sqlite:///'):
            # Extract file path from SQLite URI
            # sqlite:///./data/database.db -> ./data/database.db
            db_path = self.database_uri.replace('sqlite:///', '')
            
            # Handle absolute paths on Windows (e.g., C:/...)
            if not db_path.startswith('/') and ':' not in db_path:
                db_path_obj = Path(db_path)
                db_dir = db_path_obj.parent
                
                # Create directory if it doesn't exist
                if not db_dir.exists():
                    db_dir.mkdir(parents=True, exist_ok=True)
                    logger.info(f"Created database directory: {db_dir}")
                    
                # Create empty database file if it doesn't exist
                if not db_path_obj.exists():
                    db_path_obj.touch()
                    logger.info(f"Created empty database file: {db_path_obj}")
    
    def get_all_table_names(self) -> List[str]:
        """Get list of all table names in the database."""
        return self.inspector.get_table_names()

    def get_schema_for_tables(self, table_names: List[str]) -> str:
        """
        Compact schema for the selected tables.

        Includes column names, types, nullability, primary keys, foreign keys,
        and column comments. Sample rows are omitted so the prompt stays small.
        """
        try:
            known = set(self.get_all_table_names())
            blocks = []
            for name in table_names:
                if name not in known:
                    logger.warning(f"Table not found while building schema: {name}")
                    continue
                blocks.append(self._format_table_schema(name))
            return "\n\n".join(blocks)
        except Exception as e:
            logger.error(f"Error retrieving schema: {e}")
            return ""

    def _format_table_schema(self, table_name: str) -> str:
        cached = self._schema_cache.get(table_name)
        if cached is not None:
            return cached

        columns = self.inspector.get_columns(table_name)
        pk_cols = set(
            (self.inspector.get_pk_constraint(table_name) or {}).get("constrained_columns") or []
        )
        fk_by_column: Dict[str, str] = {}
        for fk in self.inspector.get_foreign_keys(table_name):
            referred = fk.get("referred_table") or ""
            local_cols = fk.get("constrained_columns") or []
            referred_cols = fk.get("referred_columns") or []
            for local, remote in zip(local_cols, referred_cols):
                if referred and remote:
                    fk_by_column[local] = f"{referred}.{remote}"

        lines = [f"TABLE {table_name}"]
        table_comment = self._table_comment(table_name)
        if table_comment:
            lines.append(f"  {table_comment}")

        for column in columns:
            name = column["name"]
            flags = []
            if name in pk_cols:
                flags.append("PK")
            if not column.get("nullable", True) and name not in pk_cols:
                flags.append("NOT NULL")
            fk_target = fk_by_column.get(name)
            if fk_target:
                flags.append(f"FK -> {fk_target}")
            flag_text = f" [{', '.join(flags)}]" if flags else ""
            comment = " ".join(str(column.get("comment") or "").split())
            comment_text = f"  -- {comment[:160]}" if comment else ""
            lines.append(f"  {name} {column['type']}{flag_text}{comment_text}")

        text_block = "\n".join(lines)
        self._schema_cache[table_name] = text_block
        return text_block

    def _table_comment(self, table_name: str) -> str:
        try:
            comment = (self.inspector.get_table_comment(table_name) or {}).get("text") or ""
        except Exception:
            return ""
        return " ".join(str(comment).split())[:200]
    
    def get_table_metadata(self, table_name: str) -> Dict[str, Any]:
        """
        Get detailed metadata about a table including columns, keys, and relationships.
        
        Args:
            table_name: Name of the table
            
        Returns:
            Dictionary with table metadata
        """
        try:
            columns = self.inspector.get_columns(table_name)
            pk = self.inspector.get_pk_constraint(table_name)
            fks = self.inspector.get_foreign_keys(table_name)
            indexes = self.inspector.get_indexes(table_name)
            
            from src.infrastructure.utils import sanitize_state

            return sanitize_state({
                "name": table_name,
                "columns": columns,
                "primary_key": pk,
                "foreign_keys": fks,
                "indexes": indexes,
            })
        except Exception as e:
            logger.error(f"Error getting metadata for {table_name}: {e}")
            return {}
    
    def validate_sql_syntax(self, sql: str) -> tuple[bool, Optional[str]]:
        """
        Validate SQL syntax without executing.
        
        Args:
            sql: SQL query string
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            # Use sqlglot to parse and validate
            parsed = sqlglot.parse_one(sql)
            if parsed:
                return True, None
            return False, "Failed to parse SQL"
        except Exception as e:
            return False, str(e)
    
    def execute_query(self, sql: str, timeout: Optional[int] = None) -> tuple[Any, Optional[str], Optional[float]]:
        """
        Execute SQL query with error handling and timing.
        
        Args:
            sql: SQL query to execute
            timeout: Query timeout in seconds
            
        Returns:
            Tuple of (result, error_message, execution_time_ms)
        """
        
        timeout = timeout or QUERY_TIMEOUT_SECONDS
        start = time.time()
        
        try:
            blocked = self._reject_unless_select(sql)
            if blocked:
                return None, blocked, None
            
            # Execute query
            with self.engine.connect() as conn:
                result = conn.execute(text(sql))
                execution_time = (time.time() - start) * 1000

                if not result.returns_rows:
                    conn.rollback()
                    return None, "Access denied. Only SELECT queries are allowed.", execution_time

                rows = result.fetchall()
                return rows, None, execution_time
                    
        except SQLAlchemyError as e:
            execution_time = (time.time() - start) * 1000
            error_msg = str(e.orig) if hasattr(e, 'orig') else str(e)
            logger.error(f"SQL execution error: {error_msg}")
            return None, error_msg, execution_time
        except Exception as e:
            execution_time = (time.time() - start) * 1000
            logger.error(f"Unexpected error executing query: {e}")
            return None, str(e), execution_time
        
    def allowed_execute_query(self, sql: str, allowed_rep_codes: List[str], timeout: Optional[int] = None) -> tuple[Any, Optional[str], Optional[float]]:
        """
        Execute query with allowed rep codes filtering.
        Binds @AllowedNodes variable that SQL can use with FIND_IN_SET().
        """
        timeout = timeout or QUERY_TIMEOUT_SECONDS
        start = time.time()
        
        try:
            blocked = self._reject_unless_select(sql)
            if blocked:
                return None, blocked, None
            
            allowed_nodes = ",".join(allowed_rep_codes)
            
            # Execute query with allowed_nodes parameter
            with self.engine.connect() as conn:
                # Set the user variable for the connection session
                conn.execute(text("SET @AllowedNodes = :allowed_nodes"), {"allowed_nodes": allowed_nodes})
                
                # Now execute the actual query
                result = conn.execute(text(sql))
                execution_time = (time.time() - start) * 1000

                if not result.returns_rows:
                    conn.rollback()
                    return None, "Access denied. Only SELECT queries are allowed.", execution_time

                rows = result.fetchall()
                logger.info(f"Query executed: {len(rows)} rows in {execution_time:.2f}ms")
                return rows, None, execution_time
                        
        except SQLAlchemyError as e:
            execution_time = (time.time() - start) * 1000
            error_msg = str(e.orig) if hasattr(e, 'orig') else str(e)
            logger.error(f"SQL execution error: {error_msg}")
            return None, error_msg, execution_time
        except Exception as e:
            execution_time = (time.time() - start) * 1000
            logger.error(f"Unexpected error executing query: {e}")
            return None, str(e), execution_time
        
    def _reject_unless_select(self, sql: str) -> Optional[str]:
        """Return an error message when SQL is not a single read-only SELECT."""
        kind, message = assess_sql(sql)
        if kind == "ok":
            return None
        if kind == "parse":
            return f"Syntax Error: {message}"
        logger.warning(f"Blocked non-SELECT SQL: {message}")
        return message

    def close(self):
        """Close database connections."""
        self.engine.dispose()
        logger.info("Database connections closed")

# Global database instance
db_manager = DatabaseManager()
