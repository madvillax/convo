"""Contract shared by model-generation adapters."""

from typing import Protocol

from convo.core.contracts import Answer, Hit, Message


class ChatProvider(Protocol):
    async def answer(
        self,
        filename: str,
        question: str,
        history: tuple[Message, ...],
        hits: list[Hit],
    ) -> Answer: ...
