import json
import httpx
from loguru import logger
from ...config import settings


class ChatBotAuthClient:
    def __init__(self):
        self.api_key = getattr(settings, "chatbot_api_key")

        self.phone_auth_url = getattr(
            settings,
            "chatbot_auth_url"
        )

        self.system_login_url = getattr(
            settings,
            "chatbot_system_login_url"
        )

    def _headers(self):
        return {
            "Content-Type": "application/json",
            "CHatBot-Key": self.api_key
        }

    async def authenticate_phone(self, phone_no: str) -> dict:
        payload = {
            "Phoneno": phone_no
        }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    self.phone_auth_url,
                    json=payload,
                    headers=self._headers()
                )

            response.raise_for_status()
            return {
                "success": True,
                "data": response.json()
            }

        except Exception as e:
            logger.error(f"Phone authentication failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "data": None
            }

    async def system_login(self, username: str, password: str) -> dict:
        payload = {
            "UserName": username,
            "Password": password
        }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    self.system_login_url,
                    json=payload,
                    headers=self._headers()
                )

            response.raise_for_status()
            data = response.json()

            if not data.get("success", False):
                return {
                    "success": False,
                    "error": data.get("error", "Invalid username or password"),
                    "data": data
                }

            user_context_raw = data.get("userContext")

            if isinstance(user_context_raw, str):
                user_context = json.loads(user_context_raw)
            else:
                user_context = user_context_raw or {}

            return {
                "success": True,
                "data": data,
                "user_context": user_context
            }

        except Exception as e:
            logger.error(f"System login failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "data": None
            }


chatbot_auth_client = ChatBotAuthClient()