import argparse
from pathlib import Path

from convo.ui.app import ConvoApp
from convo.ui.preview import ShellBackend


def main() -> None:
    parser = argparse.ArgumentParser(description="Chat with a file in your current directory.")
    parser.add_argument("--directory", type=Path, default=None, help="Browse this folder instead")
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
        ConvoApp(directory=directory, backend=ShellBackend()).run()
        return

    try:
        from convo.core.config import load_settings
        from convo.pipeline.chat import RagBackend
    except ImportError as error:
        parser.error(
            f"Backend dependency {error.name} is missing. Install the published command with "
            "`uv tool install --force 'convo-rag[backend]'`; from a checkout run "
            "`uv run --extra backend convo`."
        )

    if args.setup:
        from convo.bootstrap import SetupError, setup

        try:
            settings_path = setup()
        except SetupError as error:
            parser.error(str(error))
        print(f"Convo storage is ready. Settings are in {settings_path}. Run `convo` to start.")
        return

    try:
        settings = load_settings()
    except ValueError as error:
        parser.error(str(error))
    if args.download_model:
        from convo.core.contracts import Hit
        from convo.pipeline.embeddings import Embedder
        from convo.pipeline.reranking import Reranker

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

    backend = RagBackend(settings)
    try:
        ConvoApp(directory=directory, backend=backend).run()
    finally:
        backend.close()


if __name__ == "__main__":
    main()
