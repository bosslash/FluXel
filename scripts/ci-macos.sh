#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "This script must run on macOS." >&2
    exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
    echo "uv is required: https://docs.astral.sh/uv/getting-started/installation/" >&2
    exit 1
fi

if [[ ! -f fluxel/__about__.py ]]; then
    echo "FluXel source package is missing: fluxel/__about__.py" >&2
    exit 1
fi

uv python install 3.14
uv sync --locked
QT_QPA_PLATFORM=offscreen uv run python -m unittest discover \
    -s tests \
    -p 'test_*.py' \
    -v
