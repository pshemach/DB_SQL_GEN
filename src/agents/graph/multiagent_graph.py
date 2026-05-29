"""
LangGraph workflow entry — delegates to production graph when enabled.
"""

from ...config import settings

if settings.enable_production_graph:
    from .production_graph import (
        build_production_graph,
        compile_production_graph,
        graph,
        run_agent,
    )

__all__ = ["graph", "run_agent", "build_production_graph", "compile_production_graph"]
