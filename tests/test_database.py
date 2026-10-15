"""Opt-in real PostgreSQL tests; always use a disposable database or cluster.

Set CONVO_TEST_DATABASE_URL to a PostgreSQL/Psycopg admin URL (e.g. your Podman
instance), or CONVO_TEST_POSTGRES=1 to use installed initdb/pg_ctl with pgvector.
No existing application database is migrated, cleared, or dropped by these tests.
"""

import os
import shutil
import socket
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url

from convo.core.config import Settings
from convo.core.contracts import Answer, ChunkData, Document, Hit, Source
from convo.core.exceptions import BackendNotConnected
from convo.db.chunks import replace_chunks, retrieve
from convo.db.conversations import Conversations
from convo.db.documents import upsert_document
from convo.db.models import ChunkRow, DocumentRow
from convo.db.session import make_session_factory
from convo.pipeline.chat import RagBackend
from convo.pipeline.index import DocumentIndex


@contextmanager
def postgres_database():
    source = os.getenv("CONVO_TEST_DATABASE_URL")
    if source:
        name = "convo_test_" + uuid4().hex[:12]
        engine = create_engine(source, isolation_level="AUTOCOMMIT")
        try:
            with engine.connect() as connection:
                connection.execute(text(f'CREATE DATABASE "{name}"'))
            url = make_url(source).set(database=name).render_as_string(hide_password=False)
            yield url
        finally:
            with engine.connect() as connection:
                connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
            engine.dispose()
        return
    if os.getenv("CONVO_TEST_POSTGRES") != "1":
        pytest.skip("Set CONVO_TEST_DATABASE_URL or CONVO_TEST_POSTGRES=1 for PostgreSQL checks")
    initdb, pg_ctl = shutil.which("initdb"), shutil.which("pg_ctl")
    if not initdb or not pg_ctl:
        pytest.skip("PostgreSQL initdb/pg_ctl are unavailable")
    # A short path also fits macOS's Unix-domain socket path limit.
    with tempfile.TemporaryDirectory(prefix="convo-pg-", dir="/tmp") as directory:
        root = Path(directory)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        subprocess.run(
            [initdb, "-D", str(root / "data"), "-A", "trust", "-U", "convo"],
            check=True,
            capture_output=True,
        )
        started = False
        try:
            subprocess.run(
                [
                    pg_ctl,
                    "-D",
                    str(root / "data"),
                    "-l",
                    str(root / "postgres.log"),
                    "-o",
                    f"-h 127.0.0.1 -p {port} -k {root} -c fsync=off",
                    "-w",
                    "start",
                ],
                check=True,
                capture_output=True,
            )
            started = True
            yield f"postgresql+psycopg://convo@127.0.0.1:{port}/postgres"
        finally:
            if started:
                subprocess.run(
                    [pg_ctl, "-D", str(root / "data"), "-m", "immediate", "-w", "stop"],
                    check=True,
                    capture_output=True,
                )


@pytest.fixture(scope="module")
def database():
    with postgres_database() as url:
        old = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = url
        try:
            config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
            command.upgrade(config, "5c3b75f9c5c1")
            # An existing vector snapshot must survive and gain full-text indexing.
            engine = create_engine(url)
            legacy_id = uuid4()
            try:
                with engine.begin() as connection:
                    connection.execute(
                        text("INSERT INTO documents VALUES (:id, :path, :hash, :signature)"),
                        {
                            "id": legacy_id,
                            "path": "legacy-migration.md",
                            "hash": "a" * 64,
                            "signature": "test:v1",
                        },
                    )
                    connection.execute(
                        text(
                            "INSERT INTO chunks (document_id, ordinal, text, locator, embedding) "
                            "VALUES (:id, 0, 'Legacy retention is seven days.', 'section 1', CAST(:vector AS vector))"
                        ),
                        {"id": legacy_id, "vector": "[" + ",".join(["1"] + ["0"] * 1023) + "]"},
                    )
            finally:
                engine.dispose()
            command.upgrade(config, "head")
            command.check(config)
            yield Settings(url, "Qwen/Qwen3-Embedding-0.6B")
        finally:
            if old is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = old


def seed_document(settings, path, passages, vectors=None):
    identity = uuid4()
    engine, sessions = make_session_factory(settings)
    try:
        with sessions.begin() as session:
            upsert_document(session, identity, path, "a" * 64, "test:v1")
            replace_chunks(
                session,
                identity,
                [ChunkData(value, f"section {index}") for index, value in enumerate(passages, 1)],
                vectors or [[1.0] + [0.0] * 1023 for _ in passages],
            )
    finally:
        engine.dispose()
    return Document(str(identity), path)


def test_hybrid_query_uses_full_text_and_vectors_with_document_isolation(database, tmp_path):
    document = seed_document(
        database,
        tmp_path / "hybrid.md",
        [
            "Backups remain available for seven days.",
            "Application settings are configurable.",
            "The retention schedule is seven days.",
        ],
        [[1.0] + [0.0] * 1023, [0.9, 0.1] + [0.0] * 1022, [-1.0] + [0.0] * 1023],
    )
    seed_document(
        database, tmp_path / "other.md", ["The retention schedule in ANOTHER FILE is forever."]
    )
    engine, sessions = make_session_factory(database)
    try:
        with sessions() as session:
            hits = retrieve(
                session,
                uuid_from(document.id),
                "test:v1",
                [1.0] + [0.0] * 1023,
                "Can you explain the retention policy?",
                limit=2,
            )
            assert len(hits) == 2
            assert any("retention schedule is seven" in hit.text for hit in hits)
            assert all("ANOTHER FILE" not in hit.text for hit in hits)
            assert len({hit.chunk_id for hit in hits}) == 2
    finally:
        engine.dispose()


def uuid_from(value):
    from uuid import UUID

    return UUID(value)


def test_existing_vectors_survive_migration_and_fts_is_backfilled(database):
    engine, sessions = make_session_factory(database)
    try:
        with sessions() as session:
            row = session.execute(
                select(ChunkRow)
                .join(DocumentRow)
                .where(
                    DocumentRow.source_path == "legacy-migration.md",
                    ChunkRow.search_vector.op("@@")(func.plainto_tsquery("english", "retention")),
                )
            ).scalar_one()
            assert row.text == "Legacy retention is seven days."
            assert len(row.embedding) == 1024
    finally:
        engine.dispose()


def test_overview_samples_beginning_middle_and_end(database, tmp_path):
    document = seed_document(
        database, tmp_path / "overview.md", [f"Section {i}." for i in range(12)]
    )
    engine, sessions = make_session_factory(database)
    try:
        with sessions() as session:
            hits = retrieve(
                session,
                uuid_from(document.id),
                "test:v1",
                [1.0] + [0.0] * 1023,
                "Summarize this file",
                limit=3,
                overview=True,
            )
            assert [hit.text for hit in hits] == ["Section 0.", "Section 6.", "Section 11."]
    finally:
        engine.dispose()


def test_sessions_history_sources_and_structured_answers_survive_store_restart(database, tmp_path):
    document = seed_document(database, tmp_path / "saved.md", ["A persistent fact."])
    first = Conversations(database)
    snapshot = first.create(document)
    answer = Answer(
        "A persistent fact. [1]",
        (Source("saved.md · section 1", "A persistent fact."),),
        {"status": "answered", "sections": []},
    )
    first.append_turn(snapshot.id, "What is the fact?", answer, expected_messages=0)
    first.close()
    restarted = Conversations(database)
    try:
        restored = restarted.load(snapshot.id)
        assert restored.document == document
        assert [message.content for message in restored.history] == [
            "What is the fact?",
            answer.text,
        ]
        assert restored.history[-1].sources == answer.sources
        assert restored.history[-1].structured == answer.structured
        listed = next(item for item in restarted.list() if item.id == snapshot.id)
        assert listed.message_count == 2 and listed.filename == "saved.md"
        with pytest.raises(BackendNotConnected, match="another process"):
            restarted.append_turn(snapshot.id, "Stale question", answer, expected_messages=0)
        assert len(restarted.load(snapshot.id).history) == 2
        new = restarted.create(document)
        assert new.id != restored.id and new.history == ()
        assert restarted.load(snapshot.id).history == restored.history
    finally:
        restarted.close()


async def test_chat_service_commits_successful_turns_and_preserves_history_after_failures(
    database, tmp_path, monkeypatch
):
    document = seed_document(database, tmp_path / "flow.md", ["Backups run nightly."])
    backend = RagBackend(database)
    received = []

    async def search(_document, query, _progress=None):
        received.append(query)
        return [Hit("Backups run nightly.", "section 1", 0.1)]

    async def answer(_filename, question, history, hits):
        if question == "fail":
            raise RuntimeError("Generation failed")
        return Answer("Backups run nightly. [1]", (Source("flow.md · section 1", hits[0].text),))

    monkeypatch.setattr(backend.documents, "search", search)
    monkeypatch.setattr(backend.chat, "answer", answer)
    try:
        snapshot = await backend.new_session(document)
        greeting = await backend.answer_session(snapshot.id, "hello")
        assert not greeting.sources and not received
        await backend.answer_session(snapshot.id, "When do backups run?")
        before = await backend.load_session(snapshot.id)
        with pytest.raises(RuntimeError, match="Generation failed"):
            await backend.answer_session(snapshot.id, "fail")
        assert (await backend.load_session(snapshot.id)).history == before.history
        assert len(before.history) == 4
    finally:
        backend.close()


async def test_real_qwen_hybrid_search_and_reranking(database, tmp_path):
    if os.getenv("CONVO_TEST_MODELS") != "1":
        pytest.skip("Set CONVO_TEST_MODELS=1 to load the cached/downloadable ML models")
    source = tmp_path / "real-model.md"
    source.write_text(
        "# Backup policy\nBackups run nightly at 02:00 UTC. Retention is seven days.\n"
    )
    index = DocumentIndex(database)
    try:
        document = await index.prepare(source)
        hits = await index.search(document, "When do backups run?")
        assert hits and "02:00 UTC" in hits[0].text
        assert hits[0].score is not None
        assert await index.search(document, "Summarize this file")
        assert await index.search(document, "Who won the FIFA World Cup in 2018?") == []
    finally:
        index.close()


async def test_worker_grounded_turn_and_ui_session_resume(database, tmp_path, monkeypatch):
    """Real ML, process pipe and storage; the external ChatGPT response is mocked."""
    if os.getenv("CONVO_TEST_MODELS") != "1":
        pytest.skip("Set CONVO_TEST_MODELS=1 for the full local pipeline")
    import json

    from textual.widgets import Input

    from convo.core.contracts import ChatModel, GenerationSelection
    from convo.ui.app import ConvoApp
    from convo.ui.sessions import SessionPicker

    source = tmp_path / "backup-policy.md"
    source.write_text(
        "# Backup policy\nBackups run nightly at 02:00 UTC. Retention is seven days.\n"
    )
    backend = RagBackend(database)

    async def token():
        return "test-token"

    async def catalog(*_args):
        pass

    async def generated(**kwargs):
        assert kwargs["structured"] is True
        evidence = json.loads(kwargs["input_items"][-1]["content"])["evidence"]
        return json.dumps(
            {
                "status": "answered",
                "sections": [
                    {
                        "text": "Backups run nightly at 02:00 UTC.",
                        "citations": [{"source_id": 1, "quote": evidence[0]["text"]}],
                    }
                ],
            }
        )

    monkeypatch.setattr(backend.auth, "access_token", token)
    monkeypatch.setattr(backend.chat, "_ensure_catalog", catalog)
    monkeypatch.setattr(
        backend.chat,
        "generation_selection",
        lambda: GenerationSelection(ChatModel("test-model", "Test model"), connected=True),
    )
    monkeypatch.setattr("convo.llm.client.complete_chatgpt", generated)
    try:
        document = await backend.prepare(source)
        snapshot = await backend.new_session(document)
        answer = await backend.answer_session(snapshot.id, "When do backups run?")
        assert answer.text.endswith("[1]") and len(answer.sources) == 1
        assert "02:00 UTC" in answer.sources[0].excerpt
    finally:
        backend.close()

    restarted = RagBackend(database)
    try:
        restored = await restarted.load_session(snapshot.id)
        assert len(restored.history) == 2
        assert restored.history[-1].structured == answer.structured
        assert restored.history[-1].sources == answer.sources
        assert restarted.documents._process is None
        # Resume uses the indexed snapshot even if the original file disappears.
        source.unlink()
        app = ConvoApp(tmp_path, restarted)
        async with app.run_test(size=(110, 32)) as pilot:
            await app.dispatch_text("/sessions")
            await app.workers.wait_for_complete()
            assert isinstance(app.screen, SessionPicker)
            app.screen.query_one("#session-search", Input).value = "When do backups run?"
            await pilot.pause()
            if os.getenv("CONVO_CAPTURE_UI") == "1":
                Path("/tmp/convo-sessions.svg").write_text(app.export_screenshot())
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.session.id == snapshot.id and len(app.history) == 2
            assert not app.query_one("#prompt", Input).disabled
            if os.getenv("CONVO_CAPTURE_UI") == "1":
                Path("/tmp/convo-grounded-answer.svg").write_text(app.export_screenshot())
    finally:
        restarted.close()
