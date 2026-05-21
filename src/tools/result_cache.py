"""
Result caching for query optimization and follow-up detection.
"""

import json
import uuid
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from loguru import logger


@dataclass
class CachedQueryResult:
    """Cache entry for query results with metadata."""
    query_id: str
    session_id: str
    original_question: str
    sql_query: str
    result_data: List[Dict[str, Any]]  # Pandas-compatible (list of dicts)
    schema: Dict[str, str]  # column_name -> data_type
    tables_used: List[str]
    columns_used: List[str]
    timestamp: str
    ttl_seconds: int = 3600  # 1 hour default
    
    def is_expired(self) -> bool:
        """Check if cache entry is stale."""
        try:
            created = datetime.fromisoformat(self.timestamp)
            return datetime.utcnow() - created > timedelta(seconds=self.ttl_seconds)
        except Exception as e:
            logger.warning(f"Error checking cache expiry: {e}")
            return False


class ResultCache:
    """Session-scoped result caching with follow-up intelligence."""
    
    def __init__(self):
        self.sessions: Dict[str, CachedQueryResult] = {}
    
    def cache_result(
        self, 
        session_id: str,
        question: str,
        sql: str,
        data: List[Dict],
        tables: List[str],
        schema: Dict[str, str]
    ) -> str:
        """
        Cache query result with full metadata.
        
        Args:
            session_id: Current session
            question: Original question
            sql: Generated SQL
            data: Query result rows
            tables: Tables used in query
            schema: Column type mapping
        
        Returns:
            query_id for tracking
        """
        query_id = str(uuid.uuid4())
        
        cached = CachedQueryResult(
            query_id=query_id,
            session_id=session_id,
            original_question=question,
            sql_query=sql,
            result_data=data,
            schema=schema,
            tables_used=tables,
            columns_used=list(schema.keys()),
            timestamp=datetime.utcnow().isoformat()
        )
        
        self.sessions[session_id] = cached
        logger.info(
            f"✓ Cached result for session {session_id}: "
            f"{len(data)} rows, {len(tables)} tables"
        )
        return query_id
    
    def get_cached_result(self, session_id: str) -> Optional[CachedQueryResult]:
        """Get last cached result if not expired."""
        cached = self.sessions.get(session_id)
        if cached and not cached.is_expired():
            return cached
        if cached and cached.is_expired():
            logger.info(f"Cache expired for session {session_id}")
            del self.sessions[session_id]
        return None
    
    def get_result_context(self, session_id: str) -> str:
        """Format cached result info for LLM reasoning."""
        cached = self.get_cached_result(session_id)
        if not cached:
            return ""
        
        return f"""
LAST QUERY CONTEXT:
- Question: {cached.original_question}
- Tables: {', '.join(cached.tables_used)}
- Columns: {', '.join(cached.columns_used)}
- Rows returned: {len(cached.result_data)}
- Data sample: {json.dumps(cached.result_data[:2], default=str)}
"""
    
    def clear_session(self, session_id: str):
        """Clear cached result for session."""
        if session_id in self.sessions:
            del self.sessions[session_id]
            logger.info(f"Cleared cache for session {session_id}")


# Global instance
result_cache = ResultCache()
