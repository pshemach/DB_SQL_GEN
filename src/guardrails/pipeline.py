"""
Guardrail pipeline: Orchestrates all guardrails with observability.
"""

import logging
from typing import List
from datetime import datetime
from langsmith import traceable

from .base import BaseGuardrail, GuardrailDecision, GuardrailResult
from .fast_guardrails import (
    InputValidationGuardrail,
    InjectionGuardrail,
    RateLimitGuardrail
)
from .context_classifier import ContextAwareClassifier

logger = logging.getLogger(__name__)


class GuardrailPipeline:
    """Orchestrates all guardrails with observability and early exit on rejection."""
    
    def __init__(self, guardrails: List[BaseGuardrail]):
        # Sort by priority (higher first)
        self.guardrails = sorted(guardrails, key=lambda g: g.priority, reverse=True)
        logger.info(f"Pipeline initialized with {len(self.guardrails)} guardrails")
    
    @traceable(name="guardrail_pipeline_evaluate", run_type="tool", tags=["guardrails", "safety"])
    async def evaluate(self, question: str, context: dict) -> dict:
        """
        Run all guardrails and return decision.
        
        Returns:
            {
                "passed": bool,
                "reason": str,
                "guardrail_decisions": List[GuardrailDecision],
                "total_time_ms": float,
                "review_required": bool
            }
        """
        import time
        pipeline_start = time.time()
        decisions = []
        review_required = False
        
        for guardrail in self.guardrails:
            if not guardrail.enabled:
                continue
            
            try:
                decision = await guardrail.evaluate(question, context)
                decisions.append(decision)
                
                logger.info(
                    f"Guardrail {decision.guardrail_name}: {decision.result.value} "
                    f"({decision.processing_time_ms:.2f}ms)"
                )
                
                # Hard reject: stop immediately
                if decision.result == GuardrailResult.REJECT:
                    return {
                        "passed": False,
                        "reason": guardrail.get_rejection_message(),
                        "guardrail_decisions": decisions,
                        "failed_guardrail": decision.guardrail_name,
                        "total_time_ms": (time.time() - pipeline_start) * 1000,
                        "review_required": False
                    }
                
                # Review: flag for logging but continue
                if decision.result == GuardrailResult.REVIEW:
                    review_required = True
                    logger.warning(f"Review required: {decision.reason}")
            
            except Exception as e:
                logger.error(f"Guardrail {guardrail.__class__.__name__} failed: {e}")
                # On error, fail open (let it through) but log
                decisions.append(
                    GuardrailDecision(
                        result=GuardrailResult.PASS,
                        reason=f"Guardrail error (fail-open): {str(e)}",
                        guardrail_name=guardrail.__class__.__name__,
                        processing_time_ms=0
                    )
                )
        
        # All guardrails passed
        return {
            "passed": True,
            "reason": "All guardrails passed",
            "guardrail_decisions": decisions,
            "total_time_ms": (time.time() - pipeline_start) * 1000,
            "review_required": review_required
        }


# === GLOBAL INSTANCE ===
# Initialize with all guardrails
_default_guardrails = [
    InputValidationGuardrail(),
    InjectionGuardrail(),
    RateLimitGuardrail(),
    ContextAwareClassifier()
]

guardrail_pipeline = GuardrailPipeline(_default_guardrails)
