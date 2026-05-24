"""
Production-grade Text-to-SQL LangGraph workflow.

Architecture: thin orchestrator + isolated SQL subgraph + ingress/egress gates.
"""
from __future__ import annotations

import time
from typing import Literal

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from loguru import logger
from langsmith import traceable
