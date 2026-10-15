"""Collect ChatGPT's required streamed Responses API events into one answer."""

from typing import cast

from openai import AsyncOpenAI, omit
from openai.types.responses import ResponseFormatTextJSONSchemaConfigParam, ResponseInputParam

from convo.core.contracts import ReasoningEffort
from convo.core.exceptions import BackendNotConnected
from convo.prompts.schema import response_format


async def complete_chatgpt(
    access_token: str,
    model: str,
    instructions: str,
    input_items: ResponseInputParam,
    reasoning_effort: ReasoningEffort | None = None,
    *,
    structured: bool = False,
) -> str:
    """Return text only after a successful terminal response event."""
    async with AsyncOpenAI(
        api_key=access_token,
        base_url="https://api.openai.com/v1",
        max_retries=0,
        timeout=90,
    ) as client:
        stream = await client.responses.create(
            model=model,
            instructions=instructions,
            input=input_items,
            store=False,
            stream=True,
            reasoning={"effort": reasoning_effort} if reasoning_effort is not None else omit,
            text={"format": cast(ResponseFormatTextJSONSchemaConfigParam, response_format())}
            if structured
            else omit,
        )
        text: list[str] = []
        completed = False
        async with stream:
            async for event in stream:
                if event.type == "response.output_text.delta":
                    text.append(event.delta)
                elif event.type == "response.refusal.delta":
                    raise BackendNotConnected(
                        "ChatGPT declined this request. Try a different question."
                    )
                elif event.type == "response.failed":
                    error = event.response.error
                    code = error.code if error else "unknown_error"
                    raise RuntimeError(f"ChatGPT response failed ({code})")
                elif event.type == "response.incomplete":
                    raise RuntimeError("ChatGPT response was incomplete")
                elif event.type == "error":
                    raise RuntimeError("ChatGPT stream returned an error")
                elif event.type == "response.completed":
                    completed = True
        if not completed:
            raise RuntimeError("ChatGPT stream ended before response.completed")
    return "".join(text)
