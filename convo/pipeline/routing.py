"""Conservative conversational routing and history-aware follow-up search queries."""

import re

from convo.core.contracts import Message

_GREETING = re.compile(
    r"(?:hi|hello|hey|hey there|hello there|good morning|good evening|good afternoon)[!.\s]*", re.I
)
_THANKS = re.compile(r"(?:thanks|thank you|thanks a lot|thank you so much)[!.\s]*", re.I)


def conversation_reply(question: str) -> str | None:
    if _GREETING.fullmatch(question.strip()):
        return "Hi! Ask me about your selected file, or use /file to choose one."
    if _THANKS.fullmatch(question.strip()):
        return "You're welcome! Ask another question whenever you're ready."
    return None


def is_overview(question: str) -> bool:
    normalized = re.sub(r"[^\w\s]", "", question.casefold()).strip()
    normalized = re.sub(r"^(?:please|can you|could you)\s+", "", normalized)
    return normalized in {
        "summarize",
        "summarise",
        "summary",
        "summarize this",
        "summarise this",
        "summarize this file",
        "summarise this file",
        "summarize the file",
        "summarize this document",
        "summarise this document",
        "summarize the document",
        "what is this file about",
        "what is this document about",
        "explain this file",
        "explain this document",
        "give me an overview of this file",
        "give me a summary of this file",
        "give me a summary of this document",
    }


def search_query(question: str, history: tuple[Message, ...]) -> str:
    # Mixed greetings/questions remain document queries. Short references use the
    # last user question to avoid embedding an ambiguous 'what about that?' alone.
    if is_overview(question):
        return question
    if len(question.split()) <= 16 and re.search(
        r"\b(it|that|those|they|them|more|further|why|explain|elaborate)\b", question, re.I
    ):
        previous = next(
            (
                message.content
                for message in reversed(history)
                if message.role == "user" and conversation_reply(message.content) is None
            ),
            None,
        )
        if previous:
            return f"{previous[:600]}\n{question}"[:4_000]
    return question
