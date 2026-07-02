"""
Base guardrail interface and data structures.
"""

from abc import ABC, abstractmethod
from enum import Enum
from dataclasses import dataclass
from datetime import datetime


class GuardrailResult(Enum):
    """Possible outcomes from a guardrail evaluation."""
    PASS = "pass"
    REJECT = "reject"
    REVIEW = "review"  # Uncertain, flag for human review


@dataclass
class GuardrailDecision:
    """Result of a guardrail evaluation."""
    result: GuardrailResult
    reason: str
    confidence: float = 1.0  # 0-1 scale
    guardrail_name: str = ""
    processing_time_ms: float = 0.0
    metadata: dict = None


class BaseGuardrail(ABC):
    """Base class for all guardrails."""
    
    def __init__(self, enabled: bool = True, priority: int = 0):
        """
        Initialize guardrail.
        
        Args:
            enabled: Whether this guardrail is active
            priority: Higher priority runs first (0-100)
        """
        self.enabled = enabled
        self.priority = priority
    
    @abstractmethod
    async def evaluate(self, question: str, context: dict) -> GuardrailDecision:
        """
        Evaluate if input passes this guardrail.
        
        Args:
            question: User's input question
            context: Session/conversation context
                    {
                        "session_id": str,
                        "conversation_history": List[Dict],
                        "user_role": str,
                        "previous_topics": List[str],
                        ...
                    }
        
        Returns:
            GuardrailDecision with pass/reject/review
        """
        pass
    
    @abstractmethod
    def get_rejection_message(self) -> str:
        """User-friendly rejection message."""
        pass
