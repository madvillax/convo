import argparse
from pathlib import Path

from convo.chat.shell import ShellBackend
from convo.ui.app import ConvoApp


def main() -> None:
    parser = argparse.ArgumentParser(description="Chat with a file in your current directory.")
    parser.add_argument("--directory", type=Path, default=None, help="Browse this folder instead")
    args = parser.parse_args()
    directory = (args.directory or Path.cwd()).expanduser().resolve()
    if not directory.is_dir():
        parser.error(f"Not a directory: {directory}")
    # Your only wiring change later: replace ShellBackend() with RagBackend().
    ConvoApp(directory=directory, backend=ShellBackend()).run()


if __name__ == "__main__":
    main()
