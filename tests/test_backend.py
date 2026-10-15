import asyncio
import base64
import hashlib
import json
import time
from contextlib import contextmanager
from dataclasses import dataclass, replace
from types import SimpleNamespace
from typing import cast
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import httpx
import jwt
import numpy as np
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from sqlalchemy.exc import OperationalError, ProgrammingError

from convo.core.config import Settings
from convo.core.contracts import ChatModel, ChunkData, Hit, Message
from convo.core.exceptions import BackendNotConnected
from convo.llm.auth import TOKEN_KEY, ChatGPTAuth
from convo.llm.client import ChatGPTProvider
from convo.llm.credentials import AccountProfile, AccountProfileStore
from convo.pipeline import index as index_module
from convo.pipeline.chunking import split_documents
from convo.pipeline.embeddings import Embedder
from convo.pipeline.ingestion import read_file


class MemoryCredentialStore:
    def __init__(self):
        self.values = {}

    def save(self, key, value):
        self.values[key] = value

    def load(self, key):
        return self.values.get(key)

    def delete(self, key):
        self.values.pop(key, None)


def profile(*, expires_at=None, selected_model=None):
    return AccountProfile(
        client_id="oaiapp_test",
        subject="subject-1",
        email="reader@example.com",
        name="Reader",
        issuer="https://auth.openai.com",
        scopes=("chatgpt.tokens.use.direct", "openid", "offline_access"),
        expires_at=expires_at if expires_at is not None else time.time() + 3600,
        selected_model=selected_model,
    )


def test_profile_store_persists_private_account_metadata_and_stable_host(tmp_path):
    store = AccountProfileStore(tmp_path / "config")
    host_id = store.host_id()
    store.save(profile())
    saved_profile = store.load()

    assert host_id.startswith("urn:uuid:")
    assert store.host_id() == host_id
    assert saved_profile is not None
    assert saved_profile == profile(expires_at=saved_profile.expires_at)
    assert store.profile_path.stat().st_mode & 0o777 == 0o600


def test_embedder_checks_qwen_dimensions_for_chunks_and_queries(monkeypatch):
    calls: list[tuple[list[str], dict[str, object]]] = []

    class FakeModel:
        max_seq_length = 0
        tokenizer = SimpleNamespace(encode=lambda text, **_kwargs: text.split())

        def __init__(self, _model_name, **_kwargs):
            pass

        def encode(self, texts, **kwargs):
            calls.append((texts, kwargs))
            return np.ones((len(texts), 1024), dtype=np.float32)

    monkeypatch.setattr("sentence_transformers.SentenceTransformer", FakeModel)
    embedder = Embedder("Qwen/Qwen3-Embedding-0.6B")
    vectors = embedder.documents(["one", "two"])
    query = embedder.query("question")

    assert len(vectors) == 2
    assert all(len(vector) == 1024 for vector in vectors)
    assert len(query) == 1024
    assert embedder.model.max_seq_length == 2048
    assert calls[-1][1]["prompt_name"] == "query"


def test_llamaindex_reads_only_the_selected_file_and_returns_chunk_values(tmp_path):
    selected = tmp_path / "notes.md"
    selected.write_text("The selected file has two sentences. It stays local.", encoding="utf-8")
    (tmp_path / "ignored.md").write_text("This file should not be included.", encoding="utf-8")

    documents = read_file(selected)
    chunks = split_documents(documents, tokenizer=lambda text: list(range(len(text.split()))))

    assert len(documents) == 1
    assert len(chunks) == 1
    assert "selected file" in chunks[0].text
    assert chunks[0].locator == "reader section 1"


@pytest.mark.parametrize(
    ("failure", "instruction"),
    [(OperationalError, "Podman"), (ProgrammingError, "alembic upgrade head")],
)
async def test_database_is_checked_before_reading_or_loading_qwen(
    tmp_path, monkeypatch, failure, instruction
):
    def cannot_connect():
        raise failure("query", {}, Exception("private-database-details"))

    engine = SimpleNamespace(connect=cannot_connect, dispose=lambda: None)
    monkeypatch.setattr(index_module, "make_session_factory", lambda _settings: (engine, None))
    index = index_module.DocumentIndex(Settings("postgresql+psycopg://unused", "fake"))
    with pytest.raises(BackendNotConnected) as caught:
        await index.prepare(tmp_path / "not-even-present.md")
    assert instruction in str(caught.value)
    assert "private-database-details" not in str(caught.value)
    assert index.embedder._model is None
    index.close()


@pytest.mark.parametrize("failure", [OSError, TypeError])
def test_partial_qwen_cache_is_completed_when_supporting_assets_are_missing(monkeypatch, failure):
    calls = []

    class FakeModel:
        max_seq_length = 0

        def __init__(self, model_name, **kwargs):
            calls.append(kwargs)
            if kwargs.get("local_files_only"):
                raise failure("Incomplete model cache")

    monkeypatch.setattr("sentence_transformers.SentenceTransformer", FakeModel)
    embedder = Embedder("Qwen/Qwen3-Embedding-0.6B")
    assert isinstance(embedder.model, FakeModel)
    assert calls == [{"local_files_only": True}, {}]
    assert embedder.model is embedder.model
    assert len(calls) == 2


async def test_callback_rejects_wrong_state_and_client_then_accepts_valid_code(tmp_path):
    auth = ChatGPTAuth(MemoryCredentialStore(), AccountProfileStore(tmp_path / "config"))
    future = asyncio.get_running_loop().create_future()
    auth._callback_future = future
    server = await asyncio.start_server(
        lambda reader, writer: auth._handle_callback(
            reader, writer, "expected-state", "oaiapp_saved"
        ),
        "127.0.0.1",
        0,
    )
    port = server.sockets[0].getsockname()[1]
    try:
        async with httpx.AsyncClient(trust_env=False) as client:
            wrong_state = await client.get(
                f"http://127.0.0.1:{port}/auth/callback",
                params={"state": "attacker-state", "code": "bad"},
            )
            wrong_client = await client.get(
                f"http://127.0.0.1:{port}/auth/callback",
                params={"state": "expected-state", "code": "bad", "client_id": "other"},
            )
            valid = await client.get(
                f"http://127.0.0.1:{port}/auth/callback",
                params={"state": "expected-state", "code": "good"},
            )
        assert wrong_state.status_code == 400
        assert wrong_client.status_code == 400
        assert valid.status_code == 200
        assert future.result().code == "good"
        assert future.result().client_id == "oaiapp_saved"
    finally:
        server.close()
        await server.wait_closed()
        auth._callback_future = None


async def test_authorize_uses_dynamic_registration_pkce_and_loopback_callback(
    tmp_path, monkeypatch
):
    auth = ChatGPTAuth(MemoryCredentialStore(), AccountProfileStore(tmp_path / "config"))
    loop = asyncio.get_running_loop()
    observed = {}

    async def deliver_callback(redirect_uri, params):
        async with httpx.AsyncClient(trust_env=False) as client:
            response = await client.get(
                redirect_uri,
                params={
                    "state": params["state"][0],
                    "code": "authorization-code",
                    "client_id": "oaiapp_registered",
                },
            )
        assert response.status_code == 200

    def fake_browser_open(url, *_args):
        parsed = urlsplit(url)
        params = parse_qs(parsed.query)
        observed.update(params)
        redirect_uri = params["redirect_uri"][0]
        loop.call_soon_threadsafe(asyncio.create_task, deliver_callback(redirect_uri, params))
        return True

    monkeypatch.setattr("convo.llm.auth.webbrowser.open", fake_browser_open)
    result, redirect_uri, nonce, verifier = await auth._authorize(None, None)
    expected_challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())

    callback = urlsplit(redirect_uri)
    assert result.code == "authorization-code"
    assert result.client_id == "oaiapp_registered"
    assert callback.scheme == "http"
    assert callback.hostname == "127.0.0.1"
    assert callback.path == "/auth/callback"
    assert observed["client_id"] == ["dynamic_agent_client"]
    assert observed["agent_name_hint"] == ["convo"]
    assert observed["ext_agent_host_id"] == [auth.profiles.host_id()]
    assert observed["code_challenge_method"] == ["S256"]
    assert observed["code_challenge"] == [expected_challenge.decode().rstrip("=")]
    assert observed["nonce"] == [nonce]


async def test_id_token_validation_checks_signature_audience_issuer_and_nonce(monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = json.loads(RSAAlgorithm.to_jwk(private_key.public_key()))
    public_jwk["kid"] = "signing-key-1"
    claims = {
        "iss": "https://auth.openai.com",
        "aud": "oaiapp_test",
        "sub": "subject-1",
        "iat": int(time.time()),
        "exp": int(time.time()) + 300,
        "nonce": "request-nonce",
        "email": "reader@example.com",
    }
    token = jwt.encode(
        claims,
        private_key,
        algorithm="RS256",
        headers={"kid": "signing-key-1"},
    )

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url):
            if url.endswith("openid-configuration"):
                return FakeResponse(
                    {
                        "issuer": "https://auth.openai.com",
                        "jwks_uri": "https://auth.openai.com/.well-known/jwks.json",
                    }
                )
            return FakeResponse({"keys": [public_jwk]})

    monkeypatch.setattr("convo.llm.auth.httpx.AsyncClient", lambda **_kwargs: FakeClient())
    auth = ChatGPTAuth(MemoryCredentialStore(), AccountProfileStore())

    identity, issuer = await auth._verify_id_token(token, "oaiapp_test", "request-nonce")
    assert identity["sub"] == "subject-1"
    assert issuer == "https://auth.openai.com"
    with pytest.raises(jwt.InvalidTokenError):
        await auth._verify_id_token(token, "wrong-client", "request-nonce")


async def test_access_token_refreshes_and_saves_rotated_credentials(tmp_path, monkeypatch):
    credentials = MemoryCredentialStore()
    credentials.save(
        TOKEN_KEY,
        json.dumps(
            {
                "access_token": "expired-access",
                "refresh_token": "old-refresh",
                "id_token": "saved-id-token",
            }
        ),
    )
    profile_store = AccountProfileStore(tmp_path / "config")
    profile_store.save(profile(expires_at=time.time() - 1))
    auth = ChatGPTAuth(credentials, profile_store)
    requests = []

    async def fake_post_token(data):
        requests.append(data)
        return {
            "access_token": "fresh-access",
            "refresh_token": "rotated-refresh",
            "expires_in": 3600,
            "scope": "openid chatgpt.tokens.use.direct",
            "token_type": "Bearer",
        }

    monkeypatch.setattr(auth, "_post_token", fake_post_token)
    assert await auth.access_token() == "fresh-access"
    assert requests == [
        {
            "grant_type": "refresh_token",
            "client_id": "oaiapp_test",
            "refresh_token": "old-refresh",
            "resource": "https://api.openai.com/v1",
        }
    ]
    assert json.loads(credentials.load(TOKEN_KEY))["refresh_token"] == "rotated-refresh"


async def test_provider_sends_bounded_history_and_only_real_citations(monkeypatch):
    class FakeAuth:
        def __init__(self):
            self.profile = profile()
            self.saved_model = None

        async def access_token(self):
            return "access-token"

        def account_profile(self):
            return self.profile

        def save_generation_preferences(self, model, display_name, effort):
            self.saved_model = model
            self.profile = replace(
                self.profile,
                selected_model=model,
                selected_model_name=display_name,
                selected_reasoning_effort=effort,
            )

    auth = FakeAuth()
    captured = {}

    async def fake_models(_token):
        return (ChatModel("gpt-test", "Test model"),)

    async def fake_complete(**kwargs):
        captured.update(kwargs)
        return json.dumps(
            {
                "status": "answered",
                "sections": [
                    {
                        "text": "The answer is grounded in the passage.",
                        "citations": [{"source_id": 1, "quote": "The exact answer."}],
                    }
                ],
            }
        )

    monkeypatch.setattr("convo.llm.client.list_account_models", fake_models)
    monkeypatch.setattr("convo.llm.client.complete_chatgpt", fake_complete)
    hits = [Hit("The exact answer.", "page 2", 0.1)]
    history = (Message("user", "Earlier question"), Message("assistant", "Earlier answer"))

    answer = await ChatGPTProvider(cast(ChatGPTAuth, auth)).answer(
        "notes.md", "What is exact?", history, hits
    )

    assert answer.text.endswith("[1]")
    assert answer.sources[0].label == "notes.md · page 2"
    assert auth.saved_model == "gpt-test"
    assert captured["model"] == "gpt-test"
    assert [item["role"] for item in captured["input_items"]] == ["user", "assistant", "user"]
    current_question = captured["input_items"][-1]["content"]
    assert current_question.count("What is exact?") == 1
    assert json.loads(current_question)["evidence"][0]["text"] == "The exact answer."
    assert captured["structured"] is True

    async def bad_citation(**_kwargs):
        return json.dumps(
            {
                "status": "answered",
                "sections": [
                    {
                        "text": "Unsupported citation.",
                        "citations": [{"source_id": 2, "quote": "The exact answer."}],
                    }
                ],
            }
        )

    monkeypatch.setattr("convo.llm.client.complete_chatgpt", bad_citation)
    with pytest.raises(BackendNotConnected, match="supporting quotations"):
        await ChatGPTProvider(cast(ChatGPTAuth, auth)).answer("notes.md", "Question", (), hits)


async def test_streaming_requires_completed_terminal_event(monkeypatch):
    from convo.llm import streaming

    class FakeStream:
        def __init__(self, events):
            self.events = events

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def __aiter__(self):
            async def events():
                for event in self.events:
                    yield event

            return events()

    class FakeClient:
        def __init__(self, **_kwargs):
            self.responses = SimpleNamespace(create=self.create)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def create(self, **kwargs):
            captured.update(kwargs)
            return FakeStream(events)

    events = [
        SimpleNamespace(type="response.output_text.delta", delta="Hello"),
        SimpleNamespace(type="response.completed"),
    ]
    captured = {}
    monkeypatch.setattr(streaming, "AsyncOpenAI", FakeClient)
    answer = await streaming.complete_chatgpt("token", "gpt-test", "instructions", [])
    assert answer == "Hello"
    assert captured["store"] is False
    assert captured["stream"] is True

    events = [SimpleNamespace(type="response.incomplete")]
    with pytest.raises(RuntimeError, match="incomplete"):
        await streaming.complete_chatgpt("token", "gpt-test", "instructions", [])


async def test_document_index_commits_a_deterministic_snapshot_and_scoped_search(
    tmp_path, monkeypatch
):
    source = tmp_path / "notes.md"
    source.write_text("Known fact from the selected file.", encoding="utf-8")

    @dataclass
    class CapturedIndexCalls:
        chunks: tuple[UUID, list[ChunkData], list[list[float]]] | None = None
        retrieval: tuple[UUID, str, list[float]] | None = None

    captured = CapturedIndexCalls()

    class FakeEngine:
        def __init__(self):
            self.disposed = False

        def dispose(self):
            self.disposed = True

        @contextmanager
        def connect(self):
            yield SimpleNamespace(execute=lambda _statement: None)

    class FakeSessions:
        @contextmanager
        def begin(self):
            yield object()

        @contextmanager
        def __call__(self):
            yield object()

    class FakeEmbedder:
        signature = "fake:qwen:v1"
        model = object()

        def __init__(self, _model_name):
            pass

        def tokenize(self, text):
            return text.split()

        def documents(self, texts):
            assert texts == ["Known fact from the selected file."]
            return [[0.1] * 1024]

        def query(self, _question):
            return [0.2] * 1024

    engine = FakeEngine()
    sessions = FakeSessions()
    monkeypatch.setattr(index_module, "make_session_factory", lambda _settings: (engine, sessions))
    monkeypatch.setattr(index_module, "Embedder", FakeEmbedder)

    class FakeDocument:
        text = "Known fact from the selected file."

    def fake_reader(path):
        assert path.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")
        return [FakeDocument()]

    monkeypatch.setattr(index_module, "read_file", fake_reader)
    monkeypatch.setattr(
        index_module,
        "split_documents",
        lambda docs, tokenizer: [ChunkData(text=docs[0].text, locator="reader section 1")],
    )
    monkeypatch.setattr(index_module, "upsert_document", lambda *_args: None)
    monkeypatch.setattr(
        index_module,
        "replace_chunks",
        lambda _session, document_id, chunks, vectors: setattr(
            captured, "chunks", (document_id, chunks, vectors)
        ),
    )
    monkeypatch.setattr(
        index_module,
        "retrieve",
        lambda _session, document_id, signature, query, question, **_kwargs: (
            setattr(captured, "retrieval", (document_id, signature, query))
            or [Hit("Known fact", "reader section 1", 0.1)]
        ),
    )

    monkeypatch.setattr(
        index_module.Reranker, "rerank", lambda _self, _question, hits, **_kwargs: hits
    )

    index = index_module.DocumentIndex(Settings("postgresql+psycopg://unused", "fake"))
    document = await index.prepare(source)
    results = await index.search(document, "What is the fact?")
    index.close()

    assert document.path == source.resolve()
    assert captured.chunks is not None
    assert captured.retrieval is not None
    assert captured.chunks[0].version == 5
    assert len(captured.chunks[2][0]) == 1024
    assert captured.retrieval[0].version == 5
    assert results[0].text == "Known fact"
    assert engine.disposed
