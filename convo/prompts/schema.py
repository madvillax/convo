"""Strict model output plus application checks for evidence IDs and exact quotations."""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from convo.core.contracts import Answer, Hit, Source


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source_id: int
    quote: str = Field(min_length=8, max_length=600)


class AnswerSection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    text: str = Field(min_length=1, max_length=6_000)
    citations: list[Citation] = Field(max_length=5)


class GroundedAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    status: Literal["answered", "insufficient_evidence"]
    sections: list[AnswerSection] = Field(min_length=1, max_length=8)


def response_format() -> dict[str, object]:
    return {
        "type": "json_schema",
        "name": "grounded_answer",
        "strict": True,
        "schema": GroundedAnswer.model_json_schema(),
    }


def _normalized(text: str) -> str:
    return " ".join(text.split())


def parse_answer(raw: str, filename: str, evidence: list[Hit]) -> Answer:
    result = GroundedAnswer.model_validate_json(raw)
    if result.status == "insufficient_evidence":
        if any(section.citations for section in result.sections):
            raise ValueError("Insufficient-evidence answers must not contain citations")
        # Keep this refusal factual without letting unsupported generated facts through.
        return insufficient_answer()

    source_numbers: dict[int, int] = {}
    quotes: dict[int, list[str]] = {}
    paragraphs = []
    for section in result.sections:
        if not section.text.strip() or not section.citations:
            raise ValueError("Every answered section must have text and supporting citations")
        prose = re.sub(r"```.*?```|~~~.*?~~~|`[^`]*`", "", section.text, flags=re.S)
        if re.search(r"\[\d+\]", prose):
            raise ValueError("Return citations in citation objects, not inline markers")
        markers = []
        for citation in section.citations:
            identity = citation.source_id
            if identity < 1 or identity > len(evidence):
                raise ValueError("Citation source_id was not in the evidence")
            quote = citation.quote.strip()
            if len(_normalized(quote)) < 8 or _normalized(quote) not in _normalized(
                evidence[identity - 1].text
            ):
                raise ValueError("Citation quote must be copied verbatim from its evidence")
            if identity not in source_numbers:
                source_numbers[identity] = len(source_numbers) + 1
                quotes[identity] = []
            if quote not in quotes[identity]:
                quotes[identity].append(quote)
            marker = f"[{source_numbers[identity]}]"
            if marker not in markers:
                markers.append(marker)
        body = section.text.strip()
        separator = "\n\n" if body.endswith(("```", "~~~")) else " "
        paragraphs.append(f"{body}{separator}{' '.join(markers)}")
    sources = tuple(
        Source(f"{filename} · {evidence[identity - 1].locator}", "\n…\n".join(quotes[identity]))
        for identity in source_numbers
    )
    # Persist the same IDs shown in text/sources, including when unused retrieved
    # excerpts were removed. Reopened structured answers remain self-consistent.
    for section in result.sections:
        for citation in section.citations:
            citation.source_id = source_numbers[citation.source_id]
    return Answer("\n\n".join(paragraphs), sources, result.model_dump(mode="json"))


def insufficient_answer() -> Answer:
    text = "I couldn't find enough supporting information in the selected file to answer that. Try a more specific question or select another file."
    result = GroundedAnswer(
        status="insufficient_evidence", sections=[AnswerSection(text=text, citations=[])]
    )
    return Answer(text, structured=result.model_dump(mode="json"))
