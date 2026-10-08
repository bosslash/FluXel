# syntax=docker/dockerfile:1.7

FROM ghcr.io/astral-sh/uv:0.12.21-python3.14-trixie-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    QT_QPA_PLATFORM=offscreen \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# Shared libraries used by the PySide6/Qt wheels when tests run headlessly.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libdbus-1-3 \
        libegl1 \
        libfontconfig1 \
        libgl1 \
        libglib2.0-0t64 \
        libgssapi-krb5-2 \
        libice6 \
        libsm6 \
        libx11-6 \
        libx11-xcb1 \
        libxcb-cursor0 \
        libxcb-glx0 \
        libxcb-icccm4 \
        libxcb-image0 \
        libxcb-keysyms1 \
        libxcb-randr0 \
        libxcb-render-util0 \
        libxcb-shape0 \
        libxcb-shm0 \
        libxcb-sync1 \
        libxcb-util1 \
        libxcb-xfixes0 \
        libxcb-xinerama0 \
        libxcb-xkb1 \
        libxext6 \
        libxkbcommon0 \
        libxkbcommon-x11-0 \
        libxrender1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Resolve third-party dependencies in a cacheable layer.
COPY pyproject.toml uv.lock .python-version ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project

COPY . .
RUN test -f fluxel/__about__.py \
    || (echo "fluxel source package is missing (expected fluxel/__about__.py)" >&2; exit 1)
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked

CMD ["uv", "run", "python", "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-v"]
