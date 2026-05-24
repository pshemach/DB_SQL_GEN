import httpx
from loguru import logger
from ..config import settings


class ChatBotAuthClient:
    def __init__(self):
        self.auth_url = getattr(
            settings,
            "chatbot_auth_url"
        )
        self.api_key = getattr(settings, "chatbot_api_key")

    async def authenticate_user(self, phone_no: str) -> dict:
        headers = {
            "Content-Type": "application/json",
            "CHatBot-Key": self.api_key
        }

        payload = {
            "Phoneno": phone_no
        }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    self.auth_url,
                    json=payload,
                    headers=headers
                )

            response.raise_for_status()
            return response.json()

        except Exception as e:
            logger.error(f"AuthenticateUser API failed: {e}")
            raise


chatbot_auth_client = ChatBotAuthClient()