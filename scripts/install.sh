#!/usr/bin/env sh
# Install Convo from PyPI. Review this script before running it with curl.
set -eu

PACKAGE="${CONVO_PACKAGE:-convo-cli}"

if command -v uv >/dev/null 2>&1; then
  UV_BIN="$(command -v uv)"
else
  echo "uv was not found; installing it from astral.sh..."
  curl --fail --location --silent --show-error https://astral.sh/uv/install.sh | sh
  UV_BIN="${HOME}/.local/bin/uv"
  if [ ! -x "$UV_BIN" ]; then
    echo "uv installed, but was not found at $UV_BIN. Open a new terminal and run this installer again." >&2
    exit 1
  fi
fi

"$UV_BIN" tool install --python 3.12 --force "$PACKAGE"
"$UV_BIN" tool update-shell

echo
echo "Convo is installed. Start it with: convo"
