"""Shared FastAPI dependencies and in-memory auth sessions."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import Depends, Header, HTTPException


AUTH_SESSIONS: dict[str, dict[str, Any]] = {}


def is_rep(role: Optional[str]) -> bool:
    return str(role or "").strip().lower() == "rep"


def public_user(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "display_name": user.get("display_name"),
        "user_id": user.get("user_id"),
        "user_role": user.get("user_role"),
        "login_method": user.get("login_method"),
        "allowed_rep_codes": user.get("allowed_rep_codes") or [],
        "allowed_node_ids": user.get("allowed_node_ids") or [],
        "session_id": user.get("session_id"),
        "can_edit_kb": not is_rep(user.get("user_role")),
    }


def require_user(authorization: Optional[str] = Header(default=None)) -> dict[str, Any]:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Please login first.")

    token = authorization.split(" ", 1)[1].strip()
    user = AUTH_SESSIONS.get(token)
    if not user:
        raise HTTPException(status_code=401, detail="Session expired. Please login again.")
    return user


def require_knowledge_admin(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    if is_rep(user.get("user_role")):
        raise HTTPException(
            status_code=403,
            detail="Knowledge base editing is not available for Rep users.",
        )
    return user


def bearer_token(authorization: Optional[str]) -> Optional[str]:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    return None
