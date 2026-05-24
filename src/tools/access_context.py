from typing import Any


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


def extract_allowed_rep_codes(auth_data: dict) -> list[str]:
    """
    Extract allowed RepCodes for SQL filter:
    FIND_IN_SET(shn.Code, @AllowedNodes) > 0

    For Rep response:
      use allowedNodes[].Code

    For Customer response:
      use rep.Code or rep.NodeCode
    """

    if not auth_data:
        return []

    success = get_value(auth_data, "success", "Success", default=True)
    if success is False:
        return []

    user_type = get_value(auth_data, "userType", "UserType", default="")

    allowed_codes = []

    # Rep response: allowedNodes contains accessible hierarchy nodes
    allowed_nodes = get_value(auth_data, "allowedNodes", "AllowedNodes", default=[])

    for node in normalize_list(allowed_nodes):
        if isinstance(node, dict):
            code = get_value(node, "Code", "code", "NodeCode", "nodeCode")
            if code:
                allowed_codes.append(str(code).strip())
        elif isinstance(node, str):
            allowed_codes.append(node.strip())

    # Some APIs may return direct allowed rep code arrays
    for key in ["allowedRepCodes", "AllowedRepCodes", "repCodes", "RepCodes"]:
        for code in normalize_list(auth_data.get(key)):
            if isinstance(code, str):
                allowed_codes.append(code.strip())
            elif isinstance(code, dict):
                value = get_value(code, "Code", "code", "RepCode", "repCode")
                if value:
                    allowed_codes.append(str(value).strip())

    # Customer response: assigned rep object
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

    # Remove duplicates
    return sorted(set(x for x in allowed_codes if x))


def extract_user_role(auth_data: dict) -> str:
    user_type = get_value(auth_data, "userType", "UserType", default=None)

    if user_type:
        return str(user_type).lower()

    if get_value(auth_data, "rep", "Rep"):
        return "rep"

    if get_value(auth_data, "customer", "Customer"):
        return "customer"

    return "unknown"


def extract_user_context(auth_data: dict) -> dict:
    return {
        "user_type": extract_user_role(auth_data),
        "allowed_rep_codes": extract_allowed_rep_codes(auth_data),
        "raw_auth": auth_data
    }