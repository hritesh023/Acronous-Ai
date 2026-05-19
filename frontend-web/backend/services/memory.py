from collections import OrderedDict
from typing import Optional


class ConversationMemory:
    def __init__(self, max_context: int = 50):
        self.sessions: dict[str, list[dict]] = OrderedDict()
        self.max_context = max_context

    def get_context(self, session_id: str) -> list[dict]:
        return self.sessions.get(session_id, [])

    def add_message(self, session_id: str, role: str, content: str):
        if session_id not in self.sessions:
            self.sessions[session_id] = []
        self.sessions[session_id].append({"role": role, "content": content})
        if len(self.sessions[session_id]) > self.max_context:
            self.sessions[session_id] = self.sessions[session_id][-self.max_context:]

    def clear(self, session_id: str):
        self.sessions.pop(session_id, None)

    def get_or_create(self, session_id: str) -> list[dict]:
        if session_id not in self.sessions:
            self.sessions[session_id] = []
        return self.sessions[session_id]


memory = ConversationMemory()
