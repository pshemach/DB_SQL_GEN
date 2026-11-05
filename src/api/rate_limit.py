"""In-memory request rate limit for conversation and query endpoints."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Iterable

from fastapi import Request
from fastapi.responses import JSONResponse
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from src.api.dependencies import AUTH_SESSIONS, bearer_token
from src.infrastructure.config import API_RATE_LIMIT, API_RATE_WINDOW_SECONDS

_LIMITED_PREFIXES = ("/conversations", "/query")


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit = limit
        self.window = timedelta(seconds=window_seconds)
        self._hits: dict[str, list[datetime]] = defaultdict(list)

    def allow(self, key: str) -> bool:
        now = datetime.now()
        cutoff = now - self.window
        recent = [stamp for stamp in self._hits.get(key, []) if stamp > cutoff]
        if len(recent) >= self.limit:
            return False
        recent.append(now)
        self._hits[key] = recent
        return True


def _client_key(request: Request) -> str:
    token = bearer_token(request.headers.get("authorization"))
    if token:
        user = AUTH_SESSIONS.get(token) or {}
        user_id = user.get("user_id")
        if user_id:
            return f"user:{user_id}"
        return f"token:{token}"
    host = request.client.host if request.client else "unknown"
    return f"ip:{host}"


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        limiter: SlidingWindowLimiter | None = None,
        prefixes: Iterable[str] = _LIMITED_PREFIXES,
    ) -> None:
        super().__init__(app)
        self.limiter = limiter or SlidingWindowLimiter(API_RATE_LIMIT, API_RATE_WINDOW_SECONDS)
        self.prefixes = tuple(prefixes)

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if request.method == "POST" and any(
            path == prefix or path.startswith(f"{prefix}/") for prefix in self.prefixes
        ):
            key = _client_key(request)
            if not self.limiter.allow(key):
                logger.warning(f"Rate limit exceeded for {key}")
                return JSONResponse(
                    status_code=429,
                    content={"detail": "You're sending requests too quickly. Please wait a moment."},
                )
        return await call_next(request)
