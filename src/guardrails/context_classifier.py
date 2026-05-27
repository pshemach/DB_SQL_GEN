"""
Context-aware classifier: Conversation history aware domain filtering.
"""

import json
import re
from datetime import datetime
from loguru import logger
from langsmith import traceable
from langchain_core.prompts import ChatPromptTemplate

from ..config import settings
from ..utils.llm_factory import openai_llm, groq_llm
from .base import BaseGuardrail, GuardrailDecision, GuardrailResult
from .social_messages import is_social_message

DOMAIN_CLASSIFIER_PROMPT = """
You are a domain classifier for a sales analytics system.

SYSTEM CONTEXT:
- Previous topics discussed: {previous_topics}
- Conversation history summary: {conversation_summary}
- User role: {user_role}

CURRENT QUESTION: {question}

Task: Determine if this question is related to sales analytics (IN-SCOPE) or not (OUT-OF-SCOPE).

Sales analytics topics (IN-SCOPE):
- Sales metrics, KPIs, performance
- Sales team productivity, rep data
- Business/revenue analytics
- System/database questions about sales data

Non-sales topics (OUT-OF-SCOPE):
- General knowledge unrelated to sales
- Off-topic jokes/entertainment unrelated to this product
- Personal questions unrelated to work

Always IN-SCOPE (assistant will handle without SQL):
- Greetings (hi, hello, thanks)
- Questions about what this assistant can do

Important: RESPOND ONLY WITH VALID JSON, NO OTHER TEXT.

{{
    "classification": "IN_SCOPE" or "OUT_OF_SCOPE",
    "confidence": 0.95,
    "reason": "Brief explanation",
    "inferred_topic": "What the question is about"
}}
"""



class ContextAwareClassifier(BaseGuardrail):
    """Conversation-aware classification using LLM."""
    
    def __init__(self, llm_model: str = None, api_key: str = None):
        super().__init__(enabled=True, priority=10)
        self.llm = groq_llm()
        self.prompt = ChatPromptTemplate.from_template(DOMAIN_CLASSIFIER_PROMPT)
        self.chain = self.prompt | self.llm
    
    @traceable(name="context_classification", run_type="tool", tags=["guardrails", "domain-classification"])
    async def evaluate(self, question: str, context: dict) -> GuardrailDecision:
        start = datetime.now()

        if is_social_message(question):
            return GuardrailDecision(
                result=GuardrailResult.PASS,
                reason="Greeting or chitchat",
                confidence=1.0,
                guardrail_name="ContextAwareClassifier",
                processing_time_ms=(datetime.now() - start).total_seconds() * 1000,
            )

        # Build conversation context
        conversation_history = context.get("conversation_history", [])
        conversation_summary = self._summarize_conversation(conversation_history)
        previous_topics = self._extract_previous_topics(conversation_history)
        
        try:
            response = self.chain.invoke({
                "question": question,
                "conversation_summary": conversation_summary,
                "previous_topics": ", ".join(previous_topics[-5:]) if previous_topics else "None",
                "user_role": context.get("user_role", "analyst")
            })
            
            # Extract JSON from response
            response_text = response.content if hasattr(response, 'content') else str(response)
            result = self._extract_json(response_text)
            
            if not result:
                logger.warning(f"Could not parse classifier response: {response_text[:200]}")
                return GuardrailDecision(
                    result=GuardrailResult.PASS,
                    reason="Classifier parsing failed (fail-open)",
                    confidence=0.0,
                    guardrail_name="ContextAwareClassifier",
                    processing_time_ms=(datetime.now() - start).total_seconds() * 1000
                )
            
            is_in_scope = result.get("classification", "IN_SCOPE") == "IN_SCOPE"
            confidence = float(result.get("confidence", 0.0))
            
            # Reject only if high confidence that it's out-of-scope
            if not is_in_scope and confidence > 0.7:
                decision = GuardrailResult.REJECT
                logger.info(f"Rejected out-of-scope question (confidence: {confidence})")
            elif not is_in_scope and confidence <= 0.7:
                decision = GuardrailResult.REVIEW
                logger.warning(f"Uncertain scope classification (confidence: {confidence})")
            else:
                decision = GuardrailResult.PASS
            
            return GuardrailDecision(
                result=decision,
                reason=result.get("reason", "Classification complete"),
                confidence=confidence,
                guardrail_name="ContextAwareClassifier",
                processing_time_ms=(datetime.now() - start).total_seconds() * 1000
            )
        
        except Exception as e:
            logger.error(f"Classifier error: {e}")
            # On error, fail open (let it through) and log
            return GuardrailDecision(
                result=GuardrailResult.PASS,
                reason=f"Classifier error (fail-open): {str(e)}",
                confidence=0.0,
                guardrail_name="ContextAwareClassifier",
                processing_time_ms=(datetime.now() - start).total_seconds() * 1000
            )
    
    def _extract_json(self, text: str) -> dict:
        """Extract JSON from text, handling cases where LLM includes extra text."""
        if not text:
            return None
        
        text = text.strip()
        
        # Try direct JSON parsing first
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        
        # Try to find JSON object in text (look for { ... })
        match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        
        # Try markdown code blocks
        match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass
        
        logger.warning(f"Could not extract JSON from text: {text[:300]}")
        return None
    
    def _summarize_conversation(self, history: list, max_chars: int = 500) -> str:
        """Create brief summary of conversation history."""
        if not history:
            return "No previous conversation"
        
        summary = "; ".join([
            f"Q: {h.get('question', '')[:50]}"
            for h in history[-3:]  # Last 3 exchanges
        ])
        return summary[:max_chars] if summary else "No previous conversation"
    
    def _extract_previous_topics(self, history: list) -> list:
        """Extract main topics from conversation."""
        topics = []
        for msg in history[-10:]:  # Last 10 messages
            q = msg.get("question", "").lower() if isinstance(msg, dict) else str(msg).lower()
            if any(kw in q for kw in ["sales", "rep", "productivity", "revenue", "outlet", "kpi"]):
                topics.append(msg.get("question", "") if isinstance(msg, dict) else str(msg))
        return topics
    
    def get_rejection_message(self) -> str:
        return "This question appears to be outside the scope of sales analytics. Please ask about sales metrics, KPIs, or rep performance."
