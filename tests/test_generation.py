import json
import time
from dataclasses import replace

import httpx
import pytest
from openai import AsyncOpenAI

from convo.core.contracts import ChatModel, Hit
from convo.llm import streaming
from convo.llm.auth import TOKEN_KEY, ChatGPTAuth
from convo.llm.client import ChatGPTProvider
from convo.llm.credentials import AccountProfile, AccountProfileStore
from convo.llm.models import parse_model_catalog


class Credentials:
    def __init__(self):
        self.values: dict[str, str] = {}

    def save(self, key: str, value: str) -> None:
        self.values[key] = value

    def load(self, key: str) -> str | None:
        return self.values.get(key)

    def delete(self, key: str) -> None:
        self.values.pop(key, None)


def connected_auth(tmp_path):
    credentials = Credentials()
    credentials.save(
        TOKEN_KEY,
        json.dumps(
            {"access_token": "test-access", "refresh_token": "test-refresh", "id_token": "test-id"}
        ),
    )
    profiles = AccountProfileStore(tmp_path / "config")
    profiles.save(
        AccountProfile(
            client_id="oaiapp_test",
            subject="subject",
            email="test@example.com",
            name="Test",
            issuer="https://auth.openai.com",
            scopes=("chatgpt.tokens.use.direct",),
            expires_at=time.time() + 3600,
        )
    )
    return ChatGPTAuth(credentials, profiles)


def test_catalog_keeps_account_models_and_normalizes_capabilities():
    models = parse_model_catalog(
        {
            "models": [
                {"slug": "gpt-6.1-sol", "display_name": "Sol", "visibility": "list"},
                {
                    "slug": "custom",
                    "display_name": "Custom",
                    "visibility": "list",
                    "supported_reasoning_levels": [
                        {"effort": "high"},
                        {"effort": "low"},
                        {"effort": "xhigh"},
                        {"effort": "unknown"},
                    ],
                    "default_reasoning_level": "high",
                },
                {"slug": "fixed", "visibility": "list", "supported_reasoning_levels": []},
                {"slug": "hidden", "visibility": "hide"},
                {"slug": "gpt-6.1-sol", "visibility": "list"},
                {"slug": None, "visibility": "list"},
            ]
        }
    )
    assert [model.id for model in models] == ["gpt-6.1-sol", "custom", "fixed"]
    assert models[0].reasoning_efforts == ("low", "medium", "high")
    assert models[1].reasoning_efforts == ("low", "high", "xhigh")
    assert models[1].default_reasoning_effort == "high"
    assert models[2].reasoning_efforts == ()
    variants = parse_model_catalog(
        {
            "models": [
                {"slug": "gpt-6.1-sol-2026-10-01", "visibility": "list"},
                {"slug": "gpt-6.1-sol-pro", "visibility": "list"},
                {"slug": "gpt-6.1-sol", "visibility": "list", "supported_reasoning_levels": []},
            ]
        }
    )
    assert variants[0].reasoning_efforts == ("low", "medium", "high")
    assert variants[1].reasoning_efforts == ()
    assert variants[2].reasoning_efforts == ()
    assert (
        parse_model_catalog({"models": [{"slug": "unfamiliar", "visibility": "list"}]})[
            0
        ].reasoning_efforts
        == ()
    )
    with pytest.raises(RuntimeError, match="invalid model catalog"):
        parse_model_catalog({"data": []})


async def test_selection_persists_and_is_sent_to_generation(tmp_path, monkeypatch):
    auth = connected_auth(tmp_path)
    catalog = (
        ChatModel("alpha", "Alpha", ("low", "medium", "high")),
        ChatModel("beta", "Beta", ("low", "high")),
    )

    async def fake_catalog(_token):
        return catalog

    requests = []

    async def fake_complete(**kwargs):
        requests.append(kwargs)
        return json.dumps(
            {
                "status": "answered",
                "sections": [
                    {
                        "text": "The fact is in the selected file.",
                        "citations": [{"source_id": 1, "quote": "A factual statement."}],
                    }
                ],
            }
        )

    monkeypatch.setattr("convo.llm.client.list_account_models", fake_catalog)
    monkeypatch.setattr("convo.llm.client.complete_chatgpt", fake_complete)
    provider = ChatGPTProvider(auth)
    await provider.list_models()
    await provider.select_model("beta")
    await provider.cycle_reasoning()
    assert (await provider.cycle_reasoning()).reasoning_effort == "high"

    restarted = ChatGPTProvider(ChatGPTAuth(auth.credentials, auth.profiles))
    await restarted.list_models()
    restored_selection = restarted.generation_selection()
    assert restored_selection.model is not None
    assert restored_selection.model.id == "beta"
    assert restarted.generation_selection().reasoning_effort == "high"
    await restarted.answer(
        "notes.md", "What is the fact?", (), [Hit("A factual statement.", "page 1", 0.1)]
    )
    assert requests[-1]["model"] == "beta"
    assert requests[-1]["reasoning_effort"] == "high"

    before = restarted.generation_selection()
    with pytest.raises(ValueError, match="no longer available"):
        await restarted.select_model("unavailable")
    assert restarted.generation_selection() == before
    assert (await restarted.cycle_reasoning()).reasoning_effort is None

    # A refreshed account catalog can remove the saved model. Reset its incompatible
    # thinking preference together with the fallback model, before the next request.
    catalog = (ChatModel("fixed", "Fixed"),)
    await restarted.list_models()
    fallback_selection = restarted.generation_selection()
    assert fallback_selection.model is not None
    assert fallback_selection.model.id == "fixed"
    assert restarted.generation_selection().reasoning_effort is None


async def test_refresh_retains_model_and_thinking_preferences(tmp_path, monkeypatch):
    auth = connected_auth(tmp_path)
    saved = auth.account_profile()
    assert saved is not None
    auth.profiles.save(
        replace(
            saved,
            expires_at=time.time() - 10,
            selected_model="beta",
            selected_model_name="Beta",
            selected_reasoning_effort="high",
        )
    )

    async def fake_refresh(_data):
        return {
            "access_token": "new-access",
            "refresh_token": "rotated-refresh",
            "expires_in": 3600,
        }

    monkeypatch.setattr(auth, "_post_token", fake_refresh)
    assert await auth.access_token() == "new-access"
    restored = auth.account_profile()
    assert restored is not None
    assert restored.selected_model == "beta"
    assert restored.selected_model_name == "Beta"
    assert restored.selected_reasoning_effort == "high"


async def test_responses_wire_payload_includes_effort_and_omits_auto(monkeypatch):
    requests = []
    events = [
        {
            "type": "response.output_text.delta",
            "delta": "Hello",
            "sequence_number": 1,
            "item_id": "msg_test",
            "output_index": 0,
            "content_index": 0,
        },
        {
            "type": "response.completed",
            "sequence_number": 2,
            "response": {"id": "resp_test", "status": "completed", "output": []},
        },
    ]
    body = "".join(f"data: {json.dumps(event)}\n\n" for event in events) + "data: [DONE]\n\n"

    def handle(request):
        assert request.url.path == "/v1/responses"
        requests.append(json.loads(request.content))
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, content=body)

    def sdk_client(**kwargs):
        return AsyncOpenAI(
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)), **kwargs
        )

    monkeypatch.setattr(streaming, "AsyncOpenAI", sdk_client)
    assert (
        await streaming.complete_chatgpt("test-access", "beta", "instructions", [], "high")
        == "Hello"
    )
    assert requests[-1]["reasoning"] == {"effort": "high"}
    assert await streaming.complete_chatgpt("test-access", "beta", "instructions", []) == "Hello"
    assert "reasoning" not in requests[-1]
    assert requests[-1]["store"] is False
    assert requests[-1]["stream"] is True
    assert "previous_response_id" not in requests[-1]
    await streaming.complete_chatgpt("test-access", "beta", "instructions", [], structured=True)
    format = requests[-1]["text"]["format"]
    assert format["type"] == "json_schema" and format["strict"] is True
    assert format["schema"]["required"] == ["status", "sections"]
    assert format["schema"]["additionalProperties"] is False
