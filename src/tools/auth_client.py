# src/tools/auth_client.py

import httpx
from loguru import logger
from ..config import settings


class ChatBotAuthClient:
    def __init__(self):
        self.base_url = getattr(
            settings,
            "chatbot_auth_url"
        )
        self.api_key = getattr(settings, "chatbot_api_key")

    async def authenticate_user(self, phone_no: str) -> dict:
        payload = {
            "Phoneno": phone_no
        }

        headers = {
            "Content-Type": "application/json",
            "CHatBot-Key": self.api_key
        }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    self.base_url,
                    json=payload,
                    headers=headers
                )

            response.raise_for_status()
            data = response.json()

            logger.info(f"Authenticated phone number: {phone_no}")
            return {
                "success": True,
                "data": data
            }

        except httpx.HTTPStatusError as e:
            logger.error(f"Auth API HTTP error: {e.response.text}")
            return {
                "success": False,
                "error": f"Auth API error: {e.response.status_code}",
                "data": None
            }

        except Exception as e:
            logger.error(f"Auth API failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "data": None
            }


chatbot_auth_client = ChatBotAuthClient()