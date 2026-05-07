from typing import List, Optional
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
import json
import os

class ChatMemory:
    def __init__(self, storage_path: str = "data/chat_memory.json"):
        self.storage_path = storage_path
        os.makedirs(os.path.dirname(storage_path), exist_ok=True)
        self._load()

    def _load(self):
        if os.path.exists(self.storage_path):
            with open(self.storage_path, 'r') as f:
                data = json.load(f)
                self.history = [self._deserialize_msg(msg) for msg in data.get("history", [])]
        else:
            self.history = []

    def _save(self):
        data = {"history": [self._serialize_msg(msg) for msg in self.history]}
        with open(self.storage_path, 'w') as f:
            json.dump(data, f)

    def _serialize_msg(self, msg: BaseMessage) -> dict:
        return {"type": msg.__class__.__name__, "content": msg.content}

    def _deserialize_msg(self, data: dict) -> BaseMessage:
        if data["type"] == "HumanMessage":
            return HumanMessage(content=data["content"])
        elif data["type"] == "AIMessage":
            return AIMessage(content=data["content"])
        # Add more types as needed
        return HumanMessage(content=data["content"])  # Fallback

    def add_message(self, message: BaseMessage):
        self.history.append(message)
        self._save()

    def get_history(self) -> List[BaseMessage]:
        return self.history.copy()

    def clear_history(self):
        self.history = []
        self._save()