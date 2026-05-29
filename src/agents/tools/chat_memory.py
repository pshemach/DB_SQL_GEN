from typing import Dict, List, Any, Optional
from datetime import datetime
from uuid import uuid4
from loguru import logger


class ChatMemoryStore:
    """
    In-memory conversation memory.
    """

    def __init__(self):
        self.sessions: Dict[str, Dict[str, Any]] = {}

    def get_or_create_session(self, session_id: Optional[str] = None) -> str:
        if session_id and session_id in self.sessions:
            return session_id

        new_session_id = session_id or str(uuid4())

        self.sessions[new_session_id] = {
            "messages": [],
            "clarifications": [],
            "knowledge_gaps": [],
            "last_state": None,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat()
        }

        return new_session_id

    def get_session(self, session_id: str) -> Dict[str, Any]:
        return self.sessions.get(session_id, {})

    def get_last_state(self, session_id: str) -> Optional[Dict[str, Any]]:
        return self.sessions.get(session_id, {}).get("last_state")

    def set_last_state(self, session_id: str, state: Dict[str, Any]):
        self.sessions[session_id]["last_state"] = state
        self.sessions[session_id]["updated_at"] = datetime.utcnow().isoformat()

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        message_type: str = "message",
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Add a conversational message to the session.
        
        Valid message_type values:
        - "message": Regular message
        - "question": User question
        - "answer": Assistant answer to user
        - "clarification_question": Question asking user for clarification
        - "error": Error message
        
        DO NOT use for technical artifacts:
        - "sql": Use set_last_state() instead - SQL is internal and shouldn't be in conversation memory
        - "plan": Use set_last_state() instead - Plans are internal reasoning artifacts
        """
        # Prevent technical artifacts from polluting conversation memory
        if message_type in ["sql", "plan"]:
            logger.warning(
                f"Prevented {message_type} from being saved as conversational message. "
                f"Store technical artifacts in last_state instead."
            )
            return
        
        self.sessions[session_id]["messages"].append({
            "role": role,
            "type": message_type,
            "content": content,
            "metadata": metadata or {},
            "created_at": datetime.utcnow().isoformat()
        })

        self.sessions[session_id]["updated_at"] = datetime.utcnow().isoformat()

    def add_clarification(
        self,
        session_id: str,
        original_question: str,
        clarification_question: str,
        user_answer: Optional[str] = None,
        resolved: bool = False
    ):
        self.sessions[session_id]["clarifications"].append({
            "original_question": original_question,
            "clarification_question": clarification_question,
            "user_answer": user_answer,
            "resolved": resolved,
            "created_at": datetime.utcnow().isoformat()
        })

        self.sessions[session_id]["updated_at"] = datetime.utcnow().isoformat()

    def resolve_latest_clarification(self, session_id: str, user_answer: str):
        clarifications = self.sessions[session_id]["clarifications"]

        if clarifications:
            clarifications[-1]["user_answer"] = user_answer
            clarifications[-1]["resolved"] = True
            clarifications[-1]["resolved_at"] = datetime.utcnow().isoformat()

        self.sessions[session_id]["updated_at"] = datetime.utcnow().isoformat()

    def add_knowledge_gap(
        self,
        session_id: str,
        question: str,
        missing_pieces: List[str],
        reason: str,
        resolved: bool = False
    ):
        self.sessions[session_id]["knowledge_gaps"].append({
            "question": question,
            "missing_pieces": missing_pieces,
            "reason": reason,
            "resolved": resolved,
            "created_at": datetime.utcnow().isoformat()
        })

        self.sessions[session_id]["updated_at"] = datetime.utcnow().isoformat()

    def resolve_latest_knowledge_gap(self, session_id: str):
        gaps = self.sessions[session_id]["knowledge_gaps"]

        if gaps:
            gaps[-1]["resolved"] = True
            gaps[-1]["resolved_at"] = datetime.utcnow().isoformat()

        self.sessions[session_id]["updated_at"] = datetime.utcnow().isoformat()

    def build_memory_context(self, session_id: str, max_messages: int = 10) -> str:
        """
        Build memory context for LLM reasoning.
        Excludes technical artifacts (SQL, plan) to keep context clean.
        """
        session = self.sessions.get(session_id)

        if not session:
            return ""

        # Filter messages: exclude technical artifacts (sql, plan)
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
                parts.append(
                    f"- Asked: {c['clarification_question']} | "
                    f"Answered: {c.get('user_answer')} | "
                    f"Resolved: {c.get('resolved')}"
                )

        if knowledge_gaps:
            parts.append("\nKnowledge Gaps:")
            for g in knowledge_gaps:
                parts.append(
                    f"- Question: {g['question']} | "
                    f"Missing: {', '.join(g.get('missing_pieces', []))} | "
                    f"Resolved: {g.get('resolved')}"
                )

        return "\n".join(parts)

    def add_discovered_knowledge(
        self,
        session_id: str,
        original_question: str,
        clarification_question: str,
        user_answer: str,
        extracted_knowledge: dict
    ):
        """
        Store discovered business knowledge in chat memory.
        This knowledge is session-scoped and used to answer follow-up questions.
        
        Args:
            session_id: Current session
            original_question: "Show YTD productivity"
            clarification_question: "How is YTD calculated?"
            user_answer: "Sum of calls / total calls, YTD"
            extracted_knowledge: {
                "metric_name": "YTD Productivity Rate",
                "formula": "SUM(productive_calls) / SUM(total_calls)",
                "filters": ["period=YTD", "group_by=region"],
                "confidence": 0.8
            }
        """
        if session_id not in self.sessions:
            self.get_or_create_session(session_id)
        
        # Mark clarification as resolved with the knowledge
        self.resolve_latest_clarification(session_id, user_answer)
        
        # Store discovered knowledge
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
        logger.info(f"✓ Discovered knowledge stored: {extracted_knowledge.get('metric_name')}")

    def get_discovered_knowledge(self, session_id: str) -> str:
        """
        Get all discovered knowledge as formatted text for LLM context.
        
        Returns:
            Formatted string like:
            "DISCOVERED IN THIS SESSION:
             - YTD Productivity Rate: SUM(calls)/SUM(total), by region"
        """
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
        """
        Get complete context for planner including discovered knowledge.
        
        Returns:
            {
                "conversation_history": [messages],
                "discovered_knowledge_text": "DISCOVERED...",
                "discovered_knowledge_list": [extracted dicts]
            }
        """
        session = self.sessions.get(session_id, {})
        
        return {
            "messages": session.get("messages", []),
            "discovered_knowledge_text": self.get_discovered_knowledge(session_id),
            "discovered_knowledge_list": session.get("discovered_knowledge", []),
            "clarifications": session.get("clarifications", [])
        }


chat_memory = ChatMemoryStore()