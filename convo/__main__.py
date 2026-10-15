import argparse
import os
from pathlib import Path

from convo.ui.app import ConvoApp
from convo.ui.preview import ShellBackend
from convo.ui.thinking import thinking_key


def main() -> None:
    parser = argparse.ArgumentParser(description="Chat with a file in your current directory.")
    parser.add_argument("--directory", type=Path, default=None, help="Browse this folder instead")
    parser.add_argument(
        "--thinking-key",
        type=thinking_key,
        default=None,
        help="Thinking cycle shortcut (default: CONVO_THINKING_KEY or ctrl+t)",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--shell",
        action="store_true",
        help="Run the UI preview without PostgreSQL, embeddings, or ChatGPT",
    )
    mode.add_argument(
        "--download-model",
        action="store_true",
        help="Download and warm Qwen3 and the reranker outside the TUI, then exit",
    )
    mode.add_argument(
        "--setup",
        action="store_true",
        help="Create and migrate Convo's local PostgreSQL/pgvector storage, then exit",
    )
    args = parser.parse_args()
    directory = (args.directory or Path.cwd()).expanduser().resolve()
    if not directory.is_dir():
        parser.error(f"Not a directory: {directory}")
    if args.shell:
        try:
            app = ConvoApp(directory, ShellBackend(), thinking_shortcut=args.thinking_key)
        except ValueError as error:
            parser.error(str(error))
        app.run()
        return

    try:
        from convo.core.config import load_settings
        from convo.pipeline.chat import RagBackend
    except ImportError as error:
        parser.error(
            f"Backend dependency {error.name} is missing. Install the published command with "
            "`uv tool install --force convo-cli`; from a checkout run `uv run convo`."
        )

    if args.setup:
        from convo.bootstrap import SetupError, setup

        try:
            settings_path = setup()
        except (SetupError, ValueError) as error:
            parser.error(str(error))
        print(f"Convo storage is ready. Settings are in {settings_path}. Run `convo` to start.")
        return

    if args.download_model:
        # Warming models does not require a running database or a container runtime.
        from convo.core.config import Settings, load_environment
        from convo.core.contracts import Hit
        from convo.pipeline.embeddings import Embedder
        from convo.pipeline.reranking import Reranker

        load_environment()
        settings = Settings(
            "",
            os.getenv("EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-0.6B"),
            reranker_model=os.getenv("RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L6-v2"),
        )
        print(
            "Downloading/loading Qwen3 embeddings. First use can take several minutes.", flush=True
        )
        Embedder(settings.embedding_model).query("warm up")
        print("Downloading/loading the local reranker…", flush=True)
        Reranker(settings.reranker_model).rerank(
            "What is being cached?", [Hit("Model weights are cached locally.", "warmup", 0.0)]
        )
        print("Both models are ready. Run convo and choose a file with /file.")
        return

    from convo.bootstrap import SetupError, ensure_storage

    try:
        ensure_storage()
        settings = load_settings()
    except (SetupError, ValueError) as error:
        parser.error(str(error))

    backend = RagBackend(settings)
    try:
        try:
            app = ConvoApp(directory, backend, thinking_shortcut=args.thinking_key)
        except ValueError as error:
            parser.error(str(error))
        app.run()
    finally:
        backend.close()


if __name__ == "__main__":
    main()
