from __future__ import annotations

from contextvars import ContextVar
from typing import Any

runtime_ctx: ContextVar[dict[str, Any]] = ContextVar("runtime_ctx", default={})
