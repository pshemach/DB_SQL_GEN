"""
Fast guardrails: Input validation, injection detection, rate limiting.
"""

import re
from datetime import datetime, timedelta
from loguru import logger
from langsmith import traceable

from .base import BaseGuardrail, GuardrailDecision, GuardrailResult
from .social_messages import is_social_message


class InputValidationGuardrail(BaseGuardrail):
    """Fast: Check format, length, encoding."""
    
    MAX_LENGTH = 2000
    MIN_LENGTH = 3
    
    def __init__(self):
        super().__init__(enabled=True, priority=100)
    
    @traceable(name="input_validation", run_type="tool", tags=["guardrails", "validation"])
    async def evaluate(self, question: str, context: dict) -> GuardrailDecision:
        start = datetime.now()
        
        stripped = (question or "").strip()

        # Greetings / small talk (handled by agent chitchat, not analytics)
        if is_social_message(stripped):
            return GuardrailDecision(
                result=GuardrailResult.PASS,
                reason="Social message (greeting/chitchat)",
                guardrail_name="InputValidation",
                processing_time_ms=(datetime.now() - start).total_seconds() * 1000,
            )

        # Length check
        if not stripped or len(stripped) < self.MIN_LENGTH:
            return GuardrailDecision(
                result=GuardrailResult.REJECT,
                reason="Question too short",
                guardrail_name="InputValidation",
                processing_time_ms=(datetime.now() - start).total_seconds() * 1000
            )
        
        if len(question) > self.MAX_LENGTH:
            return GuardrailDecision(
                result=GuardrailResult.REJECT,
                reason=f"Question exceeds {self.MAX_LENGTH} characters",
                guardrail_name="InputValidation",
                processing_time_ms=(datetime.now() - start).total_seconds() * 1000
            )
        
        # Encoding check
        try:
            question.encode('utf-8')
        except UnicodeDecodeError:
            return GuardrailDecision(
                result=GuardrailResult.REJECT,
                reason="Invalid character encoding",
                guardrail_name="InputValidation",
                processing_time_ms=(datetime.now() - start).total_seconds() * 1000
            )
        
        return GuardrailDecision(
            result=GuardrailResult.PASS,
            reason="Input format valid",
            guardrail_name="InputValidation",
            processing_time_ms=(datetime.now() - start).total_seconds() * 1000
        )
    
    def get_rejection_message(self) -> str:
        return "Please enter a valid question (3-2000 characters)"


class InjectionGuardrail(BaseGuardrail):
    """Fast: Detect SQL/prompt injection patterns."""
    
    DANGEROUS_PATTERNS = [
        r"(?i)(DROP\s+TABLE|DELETE\s+FROM|TRUNCATE|ALTER\s+TABLE)",
        r"(?i)(UNION\s+SELECT|OR\s+1\s*=\s*1)",
        r"(?i)(--\s*$|;\s*DROP)",
        r"(?i)({.*exec.*}|<script|javascript:)",
    ]
    
    def __init__(self):
        super().__init__(enabled=True, priority=90)
    
    @traceable(name="injection_detection", run_type="tool", tags=["guardrails", "security"])
    async def evaluate(self, question: str, context: dict) -> GuardrailDecision:
        start = datetime.now()
        
        for pattern in self.DANGEROUS_PATTERNS:
            if re.search(pattern, question):
                logger.warning(f"Injection pattern detected: {pattern}")
                return GuardrailDecision(
                    result=GuardrailResult.REJECT,
                    reason="Suspicious pattern detected",
                    guardrail_name="InjectionDetection",
                    processing_time_ms=(datetime.now() - start).total_seconds() * 1000
                )
        
        return GuardrailDecision(
            result=GuardrailResult.PASS,
            reason="No injection patterns detected",
            guardrail_name="InjectionDetection",
            processing_time_ms=(datetime.now() - start).total_seconds() * 1000
        )
    
    def get_rejection_message(self) -> str:
        return "Your question contains suspicious patterns. Please rephrase."


class RateLimitGuardrail(BaseGuardrail):
    """Fast: Prevent abuse."""
    
    def __init__(self, max_requests: int = 100, window_seconds: int = 60):
        super().__init__(enabled=True, priority=80)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.request_tracker = {}  # session_id -> [timestamps]
    
    @traceable(name="rate_limit_check", run_type="tool", tags=["guardrails", "rate-limiting"])
    async def evaluate(self, question: str, context: dict) -> GuardrailDecision:
        start = datetime.now()
        session_id = context.get("session_id", "anonymous")
        
        # Cleanup old requests
        cutoff = datetime.now() - timedelta(seconds=self.window_seconds)
        self.request_tracker[session_id] = [
            ts for ts in self.request_tracker.get(session_id, [])
            if ts > cutoff
        ]
        
        # Check limit
        if len(self.request_tracker.get(session_id, [])) >= self.max_requests:
            logger.warning(f"Rate limit exceeded for session {session_id}")
            return GuardrailDecision(
                result=GuardrailResult.REJECT,
                reason="Rate limit exceeded",
                guardrail_name="RateLimit",
                processing_time_ms=(datetime.now() - start).total_seconds() * 1000
            )
        
        # Record this request
        self.request_tracker.setdefault(session_id, []).append(datetime.now())
        
        return GuardrailDecision(
            result=GuardrailResult.PASS,
            reason="Within rate limits",
            guardrail_name="RateLimit",
            processing_time_ms=(datetime.now() - start).total_seconds() * 1000
        )
    
    def get_rejection_message(self) -> str:
        return "You're sending requests too quickly. Please wait a moment."
