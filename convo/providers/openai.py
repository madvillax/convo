"""Generate answers through the user's connected ChatGPT account."""

from convo.auth.chatgpt import ChatGPTAuth
from convo.core.contracts import Answer, Hit, Message


class ChatGPTProvider:
    """OpenAI generation through the user's connected ChatGPT account."""

    def __init__(self, auth: ChatGPTAuth) -> None:
        self.auth = auth

    async def answer(
        self,
        filename: str,
        question: str,
        history: tuple[Message, ...],
        hits: list[Hit],
    ) -> Answer:
        raise NotImplementedError("Implement the ChatGPT provider described in backend.md step 8")
