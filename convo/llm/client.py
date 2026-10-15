"""Generate evidence-grounded answers through a connected ChatGPT account."""

from __future__ import annotations

import time

import httpx
from openai import BadRequestError

from convo.core.contracts import (
    Answer,
    ChatModel,
    GenerationSelection,
    Hit,
    Message,
    ReasoningEffort,
)
from convo.core.exceptions import BackendNotConnected
from convo.llm.auth import RESOURCE, ChatGPTAuth
from convo.llm.models import parse_model_catalog
from convo.llm.streaming import complete_chatgpt
from convo.prompts.answers import INSTRUCTIONS, bounded_hits, make_input
from convo.prompts.schema import insufficient_answer, parse_answer

MODEL_LIST_URL = f"{RESOURCE}/models"


class ChatGPTProvider:
    """OpenAI generation through the user's connected ChatGPT account."""

    def __init__(self, auth: ChatGPTAuth) -> None:
        self.auth = auth
        self._models: tuple[ChatModel, ...] = ()
        self._catalog_at = 0.0
        self._catalog_account: tuple[str, str] | None = None

    def reset_catalog(self) -> None:
        self._models = ()
        self._catalog_at = 0.0
        self._catalog_account = None

    def generation_selection(self) -> GenerationSelection:
        profile = self.auth.account_profile()
        if profile is None:
            return GenerationSelection()
        if profile.selected_model is None:
            return GenerationSelection(connected=True)
        model = next((item for item in self._models if item.id == profile.selected_model), None)
        if model is None:
            model = ChatModel(
                profile.selected_model, profile.selected_model_name or profile.selected_model
            )
        return GenerationSelection(model, profile.selected_reasoning_effort, connected=True)

    async def list_models(self) -> tuple[ChatModel, ...]:
        await self._refresh_catalog(await self.auth.access_token())
        return self._models

    async def _refresh_catalog(self, access_token: str) -> None:
        models = await list_account_models(access_token)
        if not models:
            raise BackendNotConnected("This ChatGPT account has no models available for Convo.")
        profile = self.auth.account_profile()
        if profile is None:
            raise BackendNotConnected("Connect your ChatGPT account with /login")
        model = next((item for item in models if item.id == profile.selected_model), models[0])
        effort = (
            profile.selected_reasoning_effort
            if model.id == profile.selected_model
            and profile.selected_reasoning_effort in model.reasoning_efforts
            else None
        )
        if (
            profile.selected_model,
            profile.selected_model_name,
            profile.selected_reasoning_effort,
        ) != (model.id, model.name, effort):
            self.auth.save_generation_preferences(model.id, model.name, effort)
        self._models = models
        self._catalog_account = (profile.client_id, profile.subject)
        self._catalog_at = time.monotonic()

    async def _ensure_catalog(self, access_token: str | None = None) -> None:
        profile = self.auth.account_profile()
        account = (profile.client_id, profile.subject) if profile else None
        if (
            not self._models
            or account != self._catalog_account
            or time.monotonic() - self._catalog_at > 300
        ):
            await self._refresh_catalog(access_token or await self.auth.access_token())

    async def select_model(self, model_id: str) -> GenerationSelection:
        await self._ensure_catalog()
        model = next((item for item in self._models if item.id == model_id), None)
        if model is None:
            raise ValueError("That model is no longer available. Run /models to refresh the list.")
        current = self.generation_selection()
        effort = (
            current.reasoning_effort
            if current.reasoning_effort in model.reasoning_efforts
            else None
        )
        self.auth.save_generation_preferences(model.id, model.name, effort)
        return GenerationSelection(model, effort, connected=True)

    async def cycle_reasoning(self) -> GenerationSelection:
        await self._ensure_catalog()
        current = self.generation_selection()
        model = current.model
        if model is None:
            raise BackendNotConnected("Choose a ChatGPT model with /models first")
        choices = (None, *model.reasoning_efforts)
        index = (
            choices.index(current.reasoning_effort) if current.reasoning_effort in choices else 0
        )
        effort = choices[(index + 1) % len(choices)]
        self.auth.save_generation_preferences(model.id, model.name, effort)
        return GenerationSelection(model, effort, connected=True)

    async def select_reasoning(self, effort: ReasoningEffort | None) -> GenerationSelection:
        await self._ensure_catalog()
        model = self.generation_selection().model
        if model is None:
            raise BackendNotConnected("Choose a ChatGPT model with /models first")
        if effort is not None and effort not in model.reasoning_efforts:
            supported = ", ".join(("auto", *model.reasoning_efforts))
            raise ValueError(f"{model.name} supports these thinking levels: {supported}.")
        self.auth.save_generation_preferences(model.id, model.name, effort)
        return GenerationSelection(model, effort, connected=True)

    async def answer(
        self,
        filename: str,
        question: str,
        history: tuple[Message, ...],
        hits: list[Hit],
    ) -> Answer:
        excerpts = bounded_hits(hits)
        if not excerpts:
            return insufficient_answer()
        access_token = await self.auth.access_token()
        await self._ensure_catalog(access_token)
        selection = self.generation_selection()
        if selection.model is None:
            raise BackendNotConnected("Choose a ChatGPT model with /models first")
        input_items = make_input(filename, question, history, excerpts)
        for attempt in range(2):
            try:
                raw = await complete_chatgpt(
                    access_token=access_token,
                    model=selection.model.id,
                    instructions=INSTRUCTIONS,
                    input_items=input_items,
                    reasoning_effort=selection.reasoning_effort,
                    structured=True,
                )
            except BadRequestError as error:
                raise BackendNotConnected(
                    "The selected model could not accept the structured-answer request. "
                    "Choose another model with /models and retry."
                ) from error
            try:
                return parse_answer(raw, filename, excerpts)
            except ValueError:
                if attempt:
                    raise BackendNotConnected(
                        "ChatGPT could not produce a valid answer with supporting quotations. "
                        "Try a more specific question; no incomplete answer was saved."
                    ) from None
                input_items.extend(
                    [
                        {"role": "assistant", "content": raw[:30_000]},
                        {
                            "role": "user",
                            "content": "Your response failed evidence validation. Return the "
                            "required schema with a supporting citation for each answer section. Use only "
                            "the current source IDs and exact quotes copied from their excerpts. No inline "
                            "citation markers in text. If unsupported, use insufficient_evidence.",
                        },
                    ]
                )
        raise RuntimeError("No validated answer")


async def list_account_models(access_token: str) -> tuple[ChatModel, ...]:
    """Fetch the account's displayable model catalog in the server's order."""
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                MODEL_LIST_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            response.raise_for_status()
            return parse_model_catalog(response.json())
    except httpx.HTTPStatusError as error:
        if error.response.status_code in (401, 403):
            raise BackendNotConnected(
                "ChatGPT model access was denied. Reconnect with /login."
            ) from error
        raise BackendNotConnected(
            "Could not load ChatGPT models. Retry /models shortly."
        ) from error
    except httpx.HTTPError as error:
        raise BackendNotConnected(
            "Could not reach ChatGPT. Check your connection and retry /models."
        ) from error
