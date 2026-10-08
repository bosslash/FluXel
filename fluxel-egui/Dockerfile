FROM rust:1.95-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    CARGO_TERM_COLOR=always

# Native dependencies required by eframe/winit, file dialogs, and the Glow renderer.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        clang \
        cmake \
        fonts-noto-cjk \
        libasound2-dev \
        libdbus-1-dev \
        libegl1-mesa-dev \
        libfontconfig1-dev \
        libgl1-mesa-dev \
        libudev-dev \
        libwayland-dev \
        libx11-dev \
        libx11-xcb-dev \
        libxcb-render0-dev \
        libxcb-shape0-dev \
        libxcb-xfixes0-dev \
        libxcursor-dev \
        libxi-dev \
        libxkbcommon-dev \
        libxrandr-dev \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*

RUN rustup component add rustfmt clippy

WORKDIR /workspace

CMD ["cargo", "test", "--all-targets"]
