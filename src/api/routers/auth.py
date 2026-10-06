from __future__ import annotations

from typing import Any, Optional
from uuid import uuid4

import secrets
from fastapi import APIRouter, Depends, Header, HTTPException
from loguru import logger

from ...agents.tools.access_context import (
    convert_node_ids_to_codes,
    extract_allowed_node_ids_from_system_login,
    extract_allowed_rep_codes_from_phone_auth,
    extract_display_name_from_phone_auth,
    extract_display_name_from_system_login,
    extract_user_id_from_phone_auth,
    extract_user_id_from_system_login,
    extract_user_role_from_phone_auth,
    extract_user_role_from_system_login,
)
from ...agents.tools.chat_memory import chat_memory
from ...agents.tools.chatbot_auth_client import chatbot_auth_client
from ..data_models import PhoneLoginRequest, SystemLoginRequest
from ..dependencies import AUTH_SESSIONS, bearer_token, public_user, require_user

router = APIRouter(prefix="/auth", tags=["auth"])


def _create_auth_session(payload: dict[str, Any]) -> dict[str, Any]:
    session_id = str(uuid4())
    chat_memory.get_or_create_session(
        session_id=session_id,
        user_id=payload.get("user_id"),
        user_role=payload.get("user_role"),
    )
    token = secrets.token_urlsafe(32)
    AUTH_SESSIONS[token] = {**payload, "session_id": session_id}
    return {"token": token, "user": public_user(AUTH_SESSIONS[token])}


@router.post("/phone")
async def login_phone(request: PhoneLoginRequest):
    phone_no = (request.phone_no or "").strip()
    if not phone_no:
        raise HTTPException(status_code=400, detail="Please enter phone number.")

    try:
        auth_result = await chatbot_auth_client.authenticate_phone(phone_no)
        if not auth_result.get("success"):
            raise HTTPException(status_code=401, detail=auth_result.get("error", "Login failed."))

        auth_data = auth_result.get("data") or {}
        allowed_rep_codes = extract_allowed_rep_codes_from_phone_auth(auth_data)
        if not allowed_rep_codes:
            raise HTTPException(status_code=403, detail="Access denied. No allowed rep codes found.")

        return {
            "success": True,
            **_create_auth_session({
                "login_method": "phone",
                "user_id": extract_user_id_from_phone_auth(auth_data),
                "display_name": extract_display_name_from_phone_auth(auth_data),
                "user_role": extract_user_role_from_phone_auth(auth_data),
                "allowed_rep_codes": allowed_rep_codes,
                "allowed_node_ids": [],
            }),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Phone login failed: {e}")
        raise HTTPException(status_code=500, detail=f"Login failed: {e}")


@router.post("/system")
async def login_system(request: SystemLoginRequest):
    username = (request.username or "").strip()
    password = (request.password or "").strip()
    if not username or not password:
        raise HTTPException(status_code=400, detail="Please enter username and password.")

    try:
        login_result = await chatbot_auth_client.system_login(username, password)
        if not login_result.get("success"):
            raise HTTPException(status_code=401, detail=login_result.get("error", "Login failed."))

        user_context = login_result.get("user_context") or {}
        allowed_node_ids = extract_allowed_node_ids_from_system_login(user_context)
        allowed_rep_codes = convert_node_ids_to_codes(allowed_node_ids)
        if not allowed_rep_codes:
            raise HTTPException(status_code=403, detail="Access denied. No allowed rep codes found.")

        return {
            "success": True,
            **_create_auth_session({
                "login_method": "system",
                "user_id": extract_user_id_from_system_login(user_context),
                "display_name": extract_display_name_from_system_login(user_context),
                "user_role": extract_user_role_from_system_login(user_context),
                "allowed_rep_codes": allowed_rep_codes,
                "allowed_node_ids": allowed_node_ids,
            }),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"System login failed: {e}")
        raise HTTPException(status_code=500, detail=f"Login failed: {e}")


@router.get("/me")
async def me(user: dict[str, Any] = Depends(require_user)):
    return {"success": True, "user": public_user(user)}


@router.post("/logout")
async def logout(authorization: Optional[str] = Header(default=None)):
    token = bearer_token(authorization)
    if token:
        AUTH_SESSIONS.pop(token, None)
    return {"success": True}
