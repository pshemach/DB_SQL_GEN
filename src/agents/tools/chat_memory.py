import json
from typing import Dict, List, Any, Optional
from datetime import datetime
from uuid import uuid4
from loguru import logger
from sqlalchemy import text
from ...core.database import db_manager


class MySQLSessionStore:
    """Handles MySQL persistence for chat sessions with feedback."""
    
    def __init__(self):
        self.table_name = "chat_sessions"
        self.sql_executions_table = "sql_executions"
        self.feedback_table = "response_feedback"
        self._create_tables()
        self._migrate_tables()
    
    def _create_tables(self):
        """Create sessions, sql_executions, and feedback tables."""
        try:
            # Main sessions table
            sessions_table_sql = f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                session_id VARCHAR(36) PRIMARY KEY,
                user_id VARCHAR(50) NOT NULL,
                user_role VARCHAR(50),
                
                last_sql_query LONGTEXT,
                last_sql_result JSON,
                last_execution_time_ms FLOAT,
                last_query_success BOOLEAN,
                
                messages JSON,
                clarifications JSON,
                knowledge_gaps JSON,
                discovered_knowledge JSON,
                
                total_likes INT DEFAULT 0,
                total_dislikes INT DEFAULT 0,
                average_satisfaction FLOAT DEFAULT 0,
                
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                
                INDEX idx_user_id (user_id),
                INDEX idx_created_at (created_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
            
            # SQL executions history table
            executions_table_sql = f"""
            CREATE TABLE IF NOT EXISTS {self.sql_executions_table} (
                id INT AUTO_INCREMENT PRIMARY KEY,
                session_id VARCHAR(36),
                user_id VARCHAR(50),
                sql_query LONGTEXT NOT NULL,
                execution_result JSON,
                execution_time_ms FLOAT,
                success BOOLEAN,
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                
                FOREIGN KEY (session_id) REFERENCES {self.table_name}(session_id),
                INDEX idx_session (session_id),
                INDEX idx_user (user_id),
                INDEX idx_created_at (created_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
            
            # Response feedback table
            feedback_table_sql = f"""
            CREATE TABLE IF NOT EXISTS {self.feedback_table} (
                id INT AUTO_INCREMENT PRIMARY KEY,
                session_id VARCHAR(36),
                user_id VARCHAR(50),
                message_id VARCHAR(36),
                message_type VARCHAR(50),
                message_content LONGTEXT,
                feedback_type ENUM('like', 'dislike'),
                feedback_reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                
                FOREIGN KEY (session_id) REFERENCES {self.table_name}(session_id),
                INDEX idx_session (session_id),
                INDEX idx_user (user_id),
                INDEX idx_message (message_id),
                INDEX idx_feedback_type (feedback_type),
                UNIQUE KEY unique_feedback (session_id, message_id, user_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
            
            messages_table_sql = """
            CREATE TABLE IF NOT EXISTS messages (
                id INT AUTO_INCREMENT PRIMARY KEY,
                session_id VARCHAR(36) NOT NULL,
                user_id VARCHAR(50),
                message_id VARCHAR(36) UNIQUE NOT NULL,
                role ENUM('user', 'assistant') NOT NULL,
                message_type VARCHAR(50),
                content LONGTEXT,
                metadata JSON,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (session_id) REFERENCES chat_sessions(session_id) ON DELETE CASCADE,
                INDEX idx_session (session_id),
                INDEX idx_user (user_id),
                INDEX idx_message_id (message_id),
                INDEX idx_created_at (created_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
            
            with db_manager.engine.begin() as conn:
                conn.execute(text(sessions_table_sql))
                conn.execute(text(executions_table_sql))
                conn.execute(text(feedback_table_sql))
                conn.execute(text(messages_table_sql))
                logger.info("✓ Chat sessions, SQL executions, and feedback tables initialized")
        except Exception as e:
            logger.warning(f"Tables may already exist: {e}")
    
    def save_session(
        self,
        session_id: str,
        session_data: Dict[str, Any],
        user_id: Optional[str] = None,
        user_role: Optional[str] = None
    ):
        try:
            effective_user_id = user_id or session_data.get("user_id")
            effective_user_role = user_role or session_data.get("user_role")

            if not effective_user_id:
                logger.warning(f"Skipping save_session for {session_id}: user_id is missing")
                return

            insert_sql = f"""
            INSERT INTO {self.table_name} 
            (session_id, user_id, user_role, messages, clarifications, knowledge_gaps, discovered_knowledge, created_at, updated_at)
            VALUES (:session_id, :user_id, :user_role, :messages, :clarifications, :knowledge_gaps, :discovered_knowledge, :created_at, :updated_at)
            ON DUPLICATE KEY UPDATE
                messages = VALUES(messages),
                clarifications = VALUES(clarifications),
                knowledge_gaps = VALUES(knowledge_gaps),
                discovered_knowledge = VALUES(discovered_knowledge),
                user_role = VALUES(user_role),
                updated_at = VALUES(updated_at)
            """

            with db_manager.engine.begin() as conn:
                conn.execute(text(insert_sql), {
                    "session_id": session_id,
                    "user_id": effective_user_id,
                    "user_role": effective_user_role,
                    "messages": json.dumps(session_data.get("messages", [])),
                    "clarifications": json.dumps(session_data.get("clarifications", [])),
                    "knowledge_gaps": json.dumps(session_data.get("knowledge_gaps", [])),
                    "discovered_knowledge": json.dumps(session_data.get("discovered_knowledge", [])),
                    "created_at": session_data.get("created_at", datetime.utcnow().isoformat()),
                    "updated_at": datetime.utcnow().isoformat()
                })

            logger.debug(f"✓ Session {session_id} saved to MySQL")

        except Exception as e:
            logger.error(f"Error saving session {session_id}: {e}")
    
    def save_sql_execution(self, session_id: str, user_id: str, sql_query: str, result: Any, execution_time_ms: float, success: bool = True, error_message: Optional[str] = None):
        """Save SQL query execution to dedicated table."""
        try:
            insert_sql = f"""
            INSERT INTO {self.sql_executions_table}
            (session_id, user_id, sql_query, execution_result, execution_time_ms, success, error_message, created_at)
            VALUES (:session_id, :user_id, :sql_query, :execution_result, :execution_time_ms, :success, :error_message, :created_at)
            """
            
            with db_manager.engine.begin() as conn:
                conn.execute(text(insert_sql), {
                    "session_id": session_id,
                    "user_id": user_id,
                    "sql_query": sql_query,
                    "execution_result": json.dumps(result) if result else None,
                    "execution_time_ms": execution_time_ms,
                    "success": success,
                    "error_message": error_message,
                    "created_at": datetime.utcnow().isoformat()
                })
                logger.info(f"✓ SQL execution logged for session {session_id}")
        except Exception as e:
            logger.error(f"Error saving SQL execution: {e}")
    
    def update_session_latest_sql(self, session_id: str, sql_query: str, result: Any, execution_time_ms: float, success: bool = True):
        """Update the latest SQL query in session."""
        try:
            update_sql = f"""
            UPDATE {self.table_name}
            SET 
                last_sql_query = :sql_query,
                last_sql_result = :sql_result,
                last_execution_time_ms = :execution_time_ms,
                last_query_success = :success,
                updated_at = NOW()
            WHERE session_id = :session_id
            """
            
            with db_manager.engine.begin() as conn:
                conn.execute(text(update_sql), {
                    "session_id": session_id,
                    "sql_query": sql_query,
                    "sql_result": json.dumps(result) if result else None,
                    "execution_time_ms": execution_time_ms,
                    "success": success
                })
        except Exception as e:
            logger.error(f"Error updating session latest SQL: {e}")
    
    def save_feedback(
        self,
        session_id: str,
        user_id: str,
        message_id: str,
        message_type: str,
        message_content: str,
        feedback_type: str,
        feedback_reason: Optional[str] = None
    ) -> bool:
        """Save user feedback without blocking UI due to nested DB locks."""
        try:
            insert_sql = f"""
            INSERT INTO {self.feedback_table}
            (session_id, user_id, message_id, message_type, message_content, feedback_type, feedback_reason, created_at)
            VALUES (:session_id, :user_id, :message_id, :message_type, :message_content, :feedback_type, :feedback_reason, NOW())
            ON DUPLICATE KEY UPDATE
                feedback_type = VALUES(feedback_type),
                feedback_reason = VALUES(feedback_reason),
                created_at = NOW()
            """

            with db_manager.engine.begin() as conn:
                conn.execute(text(insert_sql), {
                    "session_id": session_id,
                    "user_id": user_id,
                    "message_id": message_id,
                    "message_type": message_type,
                    "message_content": message_content,
                    "feedback_type": feedback_type,
                    "feedback_reason": feedback_reason
                })

            logger.info(f"✓ Feedback saved: {feedback_type} for message {message_id}")

            # Run after feedback transaction is committed
            self._update_session_satisfaction_stats(session_id)

            return True

        except Exception as e:
            logger.error(f"Error saving feedback: {e}")
            return False
        
    def _update_session_satisfaction_stats(self, session_id: str) -> bool:
        """Update session satisfaction stats using one short DB transaction."""
        try:
            update_sql = f"""
            UPDATE {self.table_name} cs
            LEFT JOIN (
                SELECT
                    session_id,
                    SUM(CASE WHEN feedback_type = 'like' THEN 1 ELSE 0 END) AS likes,
                    SUM(CASE WHEN feedback_type = 'dislike' THEN 1 ELSE 0 END) AS dislikes,
                    COUNT(*) AS total_feedback
                FROM {self.feedback_table}
                WHERE session_id = :session_id
                GROUP BY session_id
            ) fb ON fb.session_id = cs.session_id
            SET
                cs.total_likes = COALESCE(fb.likes, 0),
                cs.total_dislikes = COALESCE(fb.dislikes, 0),
                cs.average_satisfaction =
                    CASE
                        WHEN COALESCE(fb.total_feedback, 0) = 0 THEN 0
                        ELSE ROUND(COALESCE(fb.likes, 0) / fb.total_feedback * 100, 2)
                    END,
                cs.updated_at = NOW()
            WHERE cs.session_id = :session_id
            """

            with db_manager.engine.begin() as conn:
                conn.execute(text(update_sql), {"session_id": session_id})

            logger.info(f"✓ Session feedback stats updated for {session_id}")
            return True

        except Exception as e:
            logger.error(f"Error updating satisfaction stats: {e}")
            return False
            
    def _migrate_tables(self):
        """Add missing columns to existing tables."""
        try:
            required_columns = {
                "messages": "JSON NULL",
                "clarifications": "JSON NULL",
                "knowledge_gaps": "JSON NULL",
                "discovered_knowledge": "JSON NULL",
            }

            with db_manager.engine.begin() as conn:
                rows = conn.execute(text("""
                    SELECT COLUMN_NAME
                    FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE()
                    AND TABLE_NAME = :table_name
                """), {"table_name": self.table_name}).fetchall()

                existing_columns = {row[0] for row in rows}

                for column_name, column_def in required_columns.items():
                    if column_name not in existing_columns:
                        conn.execute(text(f"""
                            ALTER TABLE {self.table_name}
                            ADD COLUMN {column_name} {column_def}
                        """))
                        logger.info(f"✓ Added missing column {column_name} to {self.table_name}")

        except Exception as e:
            logger.error(f"Error migrating chat tables: {e}")
        
    def get_feedback_for_session(self, session_id: str) -> List[Dict[str, Any]]:
        """Get all feedback for a session."""
        try:
            select_sql = f"""
            SELECT 
                id, session_id, user_id, message_id, message_type, 
                feedback_type, feedback_reason, created_at
            FROM {self.feedback_table}
            WHERE session_id = :session_id
            ORDER BY created_at DESC
            """
            
            with db_manager.engine.connect() as conn:
                result = conn.execute(text(select_sql), {"session_id": session_id})
                rows = result.fetchall()
                
                return [{
                    "id": row[0],
                    "session_id": row[1],
                    "user_id": row[2],
                    "message_id": row[3],
                    "message_type": row[4],
                    "feedback_type": row[5],
                    "feedback_reason": row[6],
                    "created_at": str(row[7])
                } for row in rows]
        except Exception as e:
            logger.error(f"Error retrieving feedback: {e}")
            return []
    
    def get_feedback_stats(self, session_id: str) -> Dict[str, Any]:
        """Get feedback statistics for a session."""
        try:
            select_sql = f"""
            SELECT 
                total_likes,
                total_dislikes,
                average_satisfaction
            FROM {self.table_name}
            WHERE session_id = :session_id
            """
            
            with db_manager.engine.connect() as conn:
                result = conn.execute(text(select_sql), {"session_id": session_id})
                row = result.fetchone()
                
                if not row:
                    return {"likes": 0, "dislikes": 0, "satisfaction": 0}
                
                return {
                    "likes": row[0] or 0,
                    "dislikes": row[1] or 0,
                    "satisfaction": row[2] or 0
                }
        except Exception as e:
            logger.error(f"Error retrieving feedback stats: {e}")
            return {"likes": 0, "dislikes": 0, "satisfaction": 0}
    
    def load_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Load session from MySQL."""
        try:
            select_sql = f"""
            SELECT 
                session_id, user_id, user_role,
                last_sql_query, last_sql_result, last_execution_time_ms, last_query_success,
                messages, clarifications, knowledge_gaps, discovered_knowledge,
                total_likes, total_dislikes, average_satisfaction,
                created_at, updated_at
            FROM {self.table_name}
            WHERE session_id = :session_id
            """
            
            with db_manager.engine.connect() as conn:
                result = conn.execute(text(select_sql), {"session_id": session_id})
                row = result.fetchone()
                
                if not row:
                    return None
                
                return {
                    "session_id": row[0],
                    "user_id": row[1],
                    "user_role": row[2],
                    "last_sql_query": row[3],
                    "last_sql_result": json.loads(row[4]) if row[4] else None,
                    "last_execution_time_ms": row[5],
                    "last_query_success": row[6],
                    "messages": json.loads(row[7]) if row[7] else [],
                    "clarifications": json.loads(row[8]) if row[8] else [],
                    "knowledge_gaps": json.loads(row[9]) if row[9] else [],
                    "discovered_knowledge": json.loads(row[10]) if row[10] else [],
                    "total_likes": row[11] or 0,
                    "total_dislikes": row[12] or 0,
                    "average_satisfaction": row[13] or 0,
                    "created_at": str(row[14]),
                    "updated_at": str(row[15])
                }
        except Exception as e:
            logger.error(f"Error loading session {session_id}: {e}")
            return None
    
    def get_user_sessions(self, user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Retrieve all sessions for a user."""
        try:
            select_sql = f"""
            SELECT 
                session_id, user_id, user_role,
                last_sql_query, last_execution_time_ms, last_query_success,
                total_likes, total_dislikes, average_satisfaction,
                created_at, updated_at
            FROM {self.table_name}
            WHERE user_id = :user_id
            ORDER BY created_at DESC
            LIMIT :limit
            """
            
            with db_manager.engine.connect() as conn:
                result = conn.execute(text(select_sql), {
                    "user_id": user_id,
                    "limit": limit
                })
                rows = result.fetchall()
                
                return [{
                    "session_id": row[0],
                    "user_id": row[1],
                    "user_role": row[2],
                    "last_sql_query": row[3],
                    "last_execution_time_ms": row[4],
                    "last_query_success": row[5],
                    "total_likes": row[6] or 0,
                    "total_dislikes": row[7] or 0,
                    "average_satisfaction": row[8] or 0,
                    "created_at": str(row[9]),
                    "updated_at": str(row[10])
                } for row in rows]
        except Exception as e:
            logger.error(f"Error retrieving user sessions: {e}")
            return []
        
    def save_message(
        self,
        session_id: str,
        user_id: str,
        message_id: str,
        role: str,
        message_type: str,
        content: str,
        metadata: Optional[Dict] = None
    ) -> bool:
        """Save individual message to messages table."""
        try:
            insert_sql = """
            INSERT INTO messages
            (session_id, user_id, message_id, role, message_type, content, metadata, created_at)
            VALUES (:session_id, :user_id, :message_id, :role, :message_type, :content, :metadata, :created_at)
            """

            with db_manager.engine.begin() as conn:
                conn.execute(text(insert_sql), {
                    "session_id": session_id,
                    "user_id": user_id,
                    "message_id": message_id,
                    "role": role,
                    "message_type": message_type,
                    "content": content,
                    "metadata": json.dumps(metadata or {}),
                    "created_at": datetime.utcnow().isoformat()
                })

            logger.info(f"✓ Message saved: {role} - {message_type} (ID: {message_id})")
            return True

        except Exception as e:
            logger.error(f"Error saving message: {e}")
            return False

    def get_session_messages(self, session_id: str) -> List[Dict[str, Any]]:
        """Get all messages for a session."""
        try:
            select_sql = """
            SELECT message_id, role, message_type, content, metadata, created_at
            FROM messages
            WHERE session_id = :session_id
            ORDER BY created_at ASC
            """
            
            with db_manager.engine.connect() as conn:
                result = conn.execute(text(select_sql), {"session_id": session_id})
                rows = result.fetchall()
                
                return [{
                    "message_id": row[0],
                    "role": row[1],
                    "type": row[2],
                    "content": row[3],
                    "metadata": json.loads(row[4]) if row[4] else {},
                    "created_at": str(row[5])
                } for row in rows]
        except Exception as e:
            logger.error(f"Error retrieving messages: {e}")
            return []


class ChatMemoryStore:
    """In-memory conversation memory with MySQL persistence and feedback."""

    def __init__(self):
        self.sessions: Dict[str, Dict[str, Any]] = {}
        self.mysql_store = MySQLSessionStore()

    def get_or_create_session(self, session_id: Optional[str] = None, user_id: Optional[str] = None, user_role: Optional[str] = None) -> str:
        if session_id and session_id in self.sessions:
            return session_id

        new_session_id = session_id or str(uuid4())

        # Try to load from MySQL first
        mysql_session = self.mysql_store.load_session(new_session_id)
        
        if mysql_session:
            self.sessions[new_session_id] = mysql_session
            logger.info(f"✓ Loaded session {new_session_id} from MySQL")
        else:
            # Create new session
            self.sessions[new_session_id] = {
                "user_id": user_id,
                "user_role": user_role,
                "messages": [],
                "clarifications": [],
                "knowledge_gaps": [],
                "discovered_knowledge": [],
                "last_state": None,
                "total_likes": 0,
                "total_dislikes": 0,
                "average_satisfaction": 0,
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat()
            }
            
            # Save to MySQL
            self.mysql_store.save_session(new_session_id, self.sessions[new_session_id], user_id, user_role)
            logger.info(f"✓ Created and saved session {new_session_id} for user {user_id}")

        return new_session_id

    def get_session(self, session_id: str) -> Dict[str, Any]:
        return self.sessions.get(session_id, {})

    def get_user_sessions(self, user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Get all sessions for a user."""
        return self.mysql_store.get_user_sessions(user_id, limit)

    def get_last_state(self, session_id: str) -> Optional[Dict[str, Any]]:
        return self.sessions.get(session_id, {}).get("last_state")

    def set_last_state(self, session_id: str, state: Dict[str, Any]):
        self.sessions[session_id]["last_state"] = state
        self.sessions[session_id]["updated_at"] = datetime.utcnow().isoformat()
        self.mysql_store.save_session(session_id, self.sessions[session_id])

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        message_type: str = "message",
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        if message_type in ["sql", "plan"]:
            logger.warning(f"Prevented {message_type} from being saved as conversational message.")
            return ""

        if session_id not in self.sessions:
            self.get_or_create_session(session_id)

        message_id = str(uuid4())

        message = {
            "message_id": message_id,
            "role": role,
            "type": message_type,
            "content": content,
            "metadata": metadata or {},
            "created_at": datetime.utcnow().isoformat()
        }

        # update memory
        self.sessions[session_id]["messages"].append(message)
        self.sessions[session_id]["updated_at"] = datetime.utcnow().isoformat()

        user_id = self.sessions[session_id].get("user_id")

        message_saved = self.mysql_store.save_message(
            session_id=session_id,
            user_id=user_id,
            message_id=message_id,
            role=role,
            message_type=message_type,
            content=content,
            metadata=metadata
        )

        if not message_saved:
            logger.error(f"Message was NOT saved to DB: {message_id}")

        # save session JSON also
        self.mysql_store.save_session(
            session_id,
            self.sessions[session_id],
            user_id=user_id,
            user_role=self.sessions[session_id].get("user_role")
        )

        logger.info(f"✓ Message stored: {role} - {message_type} (ID: {message_id})")

        return message_id

    def save_feedback(self, session_id: str, user_id: str, message_id: str, message_type: str, message_content: str, feedback_type: str, feedback_reason: Optional[str] = None):
        """Save feedback (like/dislike) for a message."""
        if feedback_type not in ["like", "dislike"]:
            logger.error(f"Invalid feedback type: {feedback_type}")
            return
        
        saved = self.mysql_store.save_feedback(
            session_id,
            user_id,
            message_id,
            message_type,
            message_content,
            feedback_type,
            feedback_reason
        )

        if not saved:
            return

        # Optional: update in-memory values after DB save
        stats = self.mysql_store.get_feedback_stats(session_id)

        if session_id in self.sessions:
            self.sessions[session_id]["total_likes"] = stats["likes"]
            self.sessions[session_id]["total_dislikes"] = stats["dislikes"]
            self.sessions[session_id]["average_satisfaction"] = stats["satisfaction"]

    def get_feedback_stats(self, session_id: str) -> Dict[str, Any]:
        """Get feedback statistics for a session."""
        return self.mysql_store.get_feedback_stats(session_id)

    def get_session_feedback(self, session_id: str) -> List[Dict[str, Any]]:
        """Get all feedback for a session."""
        return self.mysql_store.get_feedback_for_session(session_id)

    def save_sql_execution(
        self,
        session_id: str,
        user_id: str,
        sql: str,
        result: Any,
        execution_time_ms: float
    ):
        execution_time_ms = execution_time_ms or 0

        self.mysql_store.save_sql_execution(
            session_id=session_id,
            user_id=user_id,
            sql_query=sql,
            result=result,
            execution_time_ms=execution_time_ms,
            success=True
        )

        self.mysql_store.update_session_latest_sql(
            session_id=session_id,
            sql_query=sql,
            result=result,
            execution_time_ms=execution_time_ms,
            success=True
        )

        logger.info(f"✓ SQL execution saved: {execution_time_ms:.2f}ms")

    def save_sql_execution_error(self, session_id: str, user_id: str, sql: str, error: str, execution_time_ms: float):
        """Save failed SQL execution."""
        self.mysql_store.save_sql_execution(session_id, user_id, sql, None, execution_time_ms, success=False, error_message=error)
        self.mysql_store.update_session_latest_sql(session_id, sql, {"error": error}, execution_time_ms, success=False)
        logger.warning(f"⚠ SQL error: {error}")

    def add_clarification(self, session_id: str, original_question: str, clarification_question: str, user_answer: Optional[str] = None, resolved: bool = False):
        self.sessions[session_id]["clarifications"].append({
            "original_question": original_question,
            "clarification_question": clarification_question,
            "user_answer": user_answer,
            "resolved": resolved,
            "created_at": datetime.utcnow().isoformat()
        })

        self.sessions[session_id]["updated_at"] = datetime.utcnow().isoformat()
        self.mysql_store.save_session(session_id, self.sessions[session_id])

    def resolve_latest_clarification(self, session_id: str, user_answer: str):
        clarifications = self.sessions[session_id]["clarifications"]

        if clarifications:
            clarifications[-1]["user_answer"] = user_answer
            clarifications[-1]["resolved"] = True
            clarifications[-1]["resolved_at"] = datetime.utcnow().isoformat()

        self.sessions[session_id]["updated_at"] = datetime.utcnow().isoformat()
        self.mysql_store.save_session(session_id, self.sessions[session_id])

    def add_knowledge_gap(self, session_id: str, question: str, missing_pieces: List[str], reason: str, resolved: bool = False):
        self.sessions[session_id]["knowledge_gaps"].append({
            "question": question,
            "missing_pieces": missing_pieces,
            "reason": reason,
            "resolved": resolved,
            "created_at": datetime.utcnow().isoformat()
        })

        self.sessions[session_id]["updated_at"] = datetime.utcnow().isoformat()
        self.mysql_store.save_session(session_id, self.sessions[session_id])

    def resolve_latest_knowledge_gap(self, session_id: str):
        gaps = self.sessions[session_id]["knowledge_gaps"]

        if gaps:
            gaps[-1]["resolved"] = True
            gaps[-1]["resolved_at"] = datetime.utcnow().isoformat()

        self.sessions[session_id]["updated_at"] = datetime.utcnow().isoformat()
        self.mysql_store.save_session(session_id, self.sessions[session_id])

    def build_memory_context(self, session_id: str, max_messages: int = 10) -> str:
        """Build memory context for LLM reasoning."""
        session = self.sessions.get(session_id)

        if not session:
            return ""

        all_messages = session.get("messages", [])
        messages = [
            msg for msg in all_messages 
            if msg.get("type") not in ["sql", "plan"]
        ][-max_messages:]
        
        clarifications = session.get("clarifications", [])[-10:]
        knowledge_gaps = session.get("knowledge_gaps", [])[-10:]

        parts = []

        if messages:
            parts.append("Recent Conversation:")
            for msg in messages:
                parts.append(f"- {msg['role']} ({msg['type']}): {msg['content']}")

        if clarifications:
            parts.append("\nClarifications:")
            for c in clarifications:
                parts.append(f"- Q: {c['clarification_question']} | A: {c.get('user_answer')} | Resolved: {c.get('resolved')}")

        if knowledge_gaps:
            parts.append("\nKnowledge Gaps:")
            for g in knowledge_gaps:
                parts.append(f"- Q: {g['question']} | Missing: {', '.join(g.get('missing_pieces', []))} | Resolved: {g.get('resolved')}")

        return "\n".join(parts)

    def add_discovered_knowledge(self, session_id: str, original_question: str, clarification_question: str, user_answer: str, extracted_knowledge: dict):
        """Store discovered business knowledge."""
        if session_id not in self.sessions:
            self.get_or_create_session(session_id)
        
        self.resolve_latest_clarification(session_id, user_answer)
        
        if "discovered_knowledge" not in self.sessions[session_id]:
            self.sessions[session_id]["discovered_knowledge"] = []
        
        self.sessions[session_id]["discovered_knowledge"].append({
            "original_question": original_question,
            "clarification_q": clarification_question,
            "user_answer": user_answer,
            "extracted": extracted_knowledge,
            "created_at": datetime.utcnow().isoformat()
        })
        
        self.sessions[session_id]["updated_at"] = datetime.utcnow().isoformat()
        self.mysql_store.save_session(session_id, self.sessions[session_id])
        logger.info(f"✓ Discovered knowledge: {extracted_knowledge.get('metric_name')}")

    def get_discovered_knowledge(self, session_id: str) -> str:
        """Get all discovered knowledge as formatted text."""
        session = self.sessions.get(session_id, {})
        knowledge_list = session.get("discovered_knowledge", [])
        
        if not knowledge_list:
            return ""
        
        formatted = "DISCOVERED IN THIS SESSION:\n"
        for item in knowledge_list:
            extracted = item.get("extracted", {})
            metric = extracted.get("metric_name", "Unknown")
            formula = extracted.get("formula", "Unknown")
            formatted += f"- {metric}: {formula}\n"
        
        return formatted

    def get_session_context_for_planner(self, session_id: str) -> dict:
        """Get complete context for planner."""
        session = self.sessions.get(session_id, {})
        
        return {
            "messages": session.get("messages", []),
            "discovered_knowledge_text": self.get_discovered_knowledge(session_id),
            "discovered_knowledge_list": session.get("discovered_knowledge", []),
            "clarifications": session.get("clarifications", [])
        }
    
    def get_message_feedback(self, message_id: str) -> Optional[Dict[str, Any]]:
        """Get feedback for a specific message."""
        feedback_list = self.mysql_store.get_feedback_for_session("")
        for feedback in feedback_list:
            if feedback.get("message_id") == message_id:
                return feedback
        return None

    def get_session_feedback_stats(self, session_id: str) -> Dict[str, Any]:
        """Get feedback statistics for a session."""
        return self.mysql_store.get_feedback_stats(session_id)
    
chat_memory = ChatMemoryStore()