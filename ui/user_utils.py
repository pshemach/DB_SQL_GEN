import asyncio
from typing import Optional, Dict, Any
from sqlalchemy import text
from src.core.database import db_manager
from src.agents.tools.chatbot_auth_client import chatbot_auth_client
from src.agents.tools.access_context import (
    extract_allowed_rep_codes_from_phone_auth,
    extract_allowed_node_ids_from_system_login,
    convert_node_ids_to_codes,
    extract_user_role_from_phone_auth,
    extract_user_role_from_system_login,
    extract_display_name_from_phone_auth,
    extract_display_name_from_system_login,
    extract_user_id_from_phone_auth,
    extract_user_id_from_system_login
)

def login_with_phone(phone_no: str) -> dict:
    async def _login():
        auth_result = await chatbot_auth_client.authenticate_phone(phone_no)

        if not auth_result.get("success"):
            return auth_result

        auth_data = auth_result.get("data") or {}
        user_id = extract_user_id_from_phone_auth(auth_data)
        allowed_rep_codes = extract_allowed_rep_codes_from_phone_auth(auth_data)

        return {
            "success": True,
            "login_method": "phone",
            "user_id": user_id,
            "display_name": extract_display_name_from_phone_auth(auth_data),
            "user_role": extract_user_role_from_phone_auth(auth_data),
            "allowed_rep_codes": allowed_rep_codes,
            "auth_data": auth_data
        }
    return asyncio.run(_login())


def login_with_system(username: str, password: str) -> dict:
    async def _login():
        login_result = await chatbot_auth_client.system_login(username, password)

        if not login_result.get("success"):
            return login_result

        user_context = login_result.get("user_context") or {}
        
        user_id = extract_user_id_from_system_login(user_context)
        allowed_node_ids = extract_allowed_node_ids_from_system_login(user_context)
        allowed_rep_codes = convert_node_ids_to_codes(allowed_node_ids)

        return {
            "success": True,
            "login_method": "system",
            "user_id": user_id,
            "display_name": extract_display_name_from_system_login(user_context),
            "user_role": extract_user_role_from_system_login(user_context),
            "allowed_node_ids": allowed_node_ids,
            "allowed_rep_codes": allowed_rep_codes,
            "auth_data": login_result.get("data"),
            "user_context": user_context
        }

    return asyncio.run(_login())


def get_node_codes_by_ids(node_ids: list[str]) -> list[str]:
    if not node_ids:
        return []

    clean_ids = [int(x) for x in node_ids if str(x).strip().isdigit()]

    if not clean_ids:
        return []

    placeholders = ", ".join([f":id_{i}" for i in range(len(clean_ids))])
    params = {f"id_{i}": node_id for i, node_id in enumerate(clean_ids)}

    sql = text(f"""
        SELECT Code
        FROM sales_hierarchy_nodes
        WHERE Id IN ({placeholders})
          AND Code IS NOT NULL
    """)

    with db_manager.engine.connect() as connection:
        rows = connection.execute(sql, params).fetchall()

    return [row[0] for row in rows if row[0]]