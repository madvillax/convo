"""Normalize account catalogs and limit reasoning controls to known capabilities."""

import re

from convo.core.contracts import REASONING_EFFORTS, ChatModel, ReasoningEffort

# A conservative subset documented for these standard models. Catalog-provided
# capabilities take precedence; unfamiliar models keep the server's default.
_STANDARD_REASONING_MODELS = (
    "gpt-5.5",
    "gpt-5.6",
    "gpt-6-astra",
    "gpt-6-sol",
    "gpt-6.1-sol",
    "gpt-6-luna",
)


def reasoning_effort(value: object) -> ReasoningEffort | None:
    if isinstance(value, str) and value in REASONING_EFFORTS:
        return value
    return None


def parse_model_catalog(payload: object) -> tuple[ChatModel, ...]:
    if not isinstance(payload, dict) or not isinstance(payload.get("models"), list):
        raise RuntimeError("ChatGPT returned an invalid model catalog")
    models: list[ChatModel] = []
    seen: set[str] = set()
    for item in payload["models"]:
        if not isinstance(item, dict) or item.get("visibility") != "list":
            continue
        slug = item.get("slug")
        if not isinstance(slug, str) or not slug or slug in seen:
            continue
        seen.add(slug)
        display_name = item.get("display_name")
        capabilities = item.get(
            "supported_reasoning_levels", item.get("supported_reasoning_efforts")
        )
        if isinstance(capabilities, list):
            efforts = {
                effort
                for entry in capabilities
                if (
                    effort := reasoning_effort(
                        entry.get("effort") if isinstance(entry, dict) else entry
                    )
                )
                is not None
            }
            supported = tuple(effort for effort in REASONING_EFFORTS if effort in efforts)
        elif any(
            re.fullmatch(re.escape(model) + r"(?:-\d{4}-\d{2}-\d{2})?", slug)
            for model in _STANDARD_REASONING_MODELS
        ):
            supported = ("low", "medium", "high")
        else:
            supported = ()
        default = reasoning_effort(
            item.get("default_reasoning_level", item.get("default_reasoning_effort"))
        )
        models.append(
            ChatModel(
                id=slug,
                name=display_name if isinstance(display_name, str) and display_name else slug,
                reasoning_efforts=supported,
                default_reasoning_effort=default if default in supported else None,
            )
        )
    return tuple(models)
