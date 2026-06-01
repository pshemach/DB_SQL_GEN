from typing import Any, Optional
from sqlalchemy import text
from ...core.database import db_manager


def get_value(data: dict, *keys, default=None):
    for key in keys:
        if isinstance(data, dict) and key in data:
            return data[key]
    return default


def normalize_list(value: Any) -> list:
    if value is None:
        return []

    if isinstance(value, list):
        return value

    if isinstance(value, str):
        return [x.strip() for x in value.split(",") if x.strip()]

    return []


def extract_allowed_rep_codes_from_phone_auth(auth_data: dict) -> list[str]:
    """
    Phone AuthenticateUser response usually returns allowedNodes.
    We use allowedNodes[].Code for FIND_IN_SET(shn.Code, @AllowedNodes).
    """

    if not auth_data:
        return []

    success = get_value(auth_data, "success", "Success", default=True)

    if success is False:
        return []

    allowed_codes = []

    allowed_nodes = get_value(
        auth_data,
        "allowedNodes",
        "AllowedNodes",
        default=[]
    )

    for node in normalize_list(allowed_nodes):
        if isinstance(node, dict):
            code = get_value(node, "Code", "code", "NodeCode", "nodeCode")
            if code:
                allowed_codes.append(str(code).strip())

        elif isinstance(node, str):
            allowed_codes.append(node.strip())

    rep = get_value(auth_data, "rep", "Rep", default=None)

    if isinstance(rep, dict):
        rep_code = get_value(
            rep,
            "Code",
            "code",
            "NodeCode",
            "nodeCode",
            "RepCode",
            "repCode"
        )

        if rep_code:
            allowed_codes.append(str(rep_code).strip())

    return sorted(set(x for x in allowed_codes if x))


def extract_allowed_node_ids_from_system_login(user_context: dict) -> list[str]:
    value = (
        user_context.get("AllowedNodeIds")
        or user_context.get("allowedNodeIds")
        or []
    )

    if isinstance(value, str):
        return [x.strip() for x in value.split(",") if x.strip()]

    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]

    return []


def convert_node_ids_to_codes(node_ids: list[str]) -> list[str]:
    """
    Converts SalesHierarchyNode Ids to Code values.
    Equivalent SQL:
    SELECT Code FROM sales_hierarchy_nodes WHERE Id IN (...)
    """

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

    return sorted(set(row[0] for row in rows if row[0]))


def extract_user_role_from_phone_auth(auth_data: dict) -> str:
    user_type = get_value(auth_data, "userType", "UserType", default=None)

    if user_type:
        return str(user_type).lower()

    if get_value(auth_data, "rep", "Rep"):
        return "rep"

    if get_value(auth_data, "customer", "Customer"):
        return "customer"

    return "unknown"


def extract_user_role_from_system_login(user_context: dict) -> str:
    return (
        user_context.get("Role")
        or user_context.get("role")
        or user_context.get("UserRole")
        or user_context.get("userRole")
        or "system_user"
    )


def extract_display_name_from_phone_auth(auth_data: dict) -> str:
    rep = get_value(auth_data, "rep", "Rep", default=None)

    if isinstance(rep, dict):
        return (
            get_value(rep, "Name", "name", "UserName", "userName")
            or "Rep User"
        )

    customer = get_value(auth_data, "customer", "Customer", default=None)

    if isinstance(customer, dict):
        return (
            get_value(customer, "Name", "name", "DisplayName", "displayName")
            or "Customer User"
        )

    return "User"


def extract_display_name_from_system_login(user_context: dict) -> str:
    return (
        user_context.get("UserName")
        or user_context.get("userName")
        or user_context.get("Name")
        or user_context.get("name")
        or "System User"
    )
    
def extract_user_id_from_phone_auth(auth_data: dict) -> Optional[Any]:
    """
    Extract user ID from phone authentication response.
    """
    return auth_data.get("UserId") or auth_data.get("user_id") or auth_data.get("id")

def extract_user_id_from_system_login(user_context: dict) -> Optional[str]:
    """
    Extract user ID from system login user context.
    """
    return user_context.get("UserId") or user_context.get("user_id") or user_context.get("id")