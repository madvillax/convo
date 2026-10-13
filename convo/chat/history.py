"""Helpers for completed in-memory conversation turns."""

from convo.core.contracts import Message


def append_completed_turn(
    history: tuple[Message, ...], question: str, answer: str
) -> tuple[Message, ...]:
    """Add a successful exchange; failed requests must not enter history."""
    return history + (Message("user", question), Message("assistant", answer))
