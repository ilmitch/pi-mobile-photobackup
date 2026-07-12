# Linux development / test image for the Aethereal backup engine.
#
# Debian Bookworm + Python 3.11 mirrors Raspberry Pi OS (Bookworm), so this container is
# the faithful place to run the Linux-specific work (real POSIX_FADV_DONTNEED, ext4
# loopback mounts, udev) that cannot be exercised on macOS. GPIO (the `pi` extra) is
# deliberately excluded — that is real Raspberry Pi hardware.
FROM python:3.11-slim-bookworm

# The project venv lives OUTSIDE the (bind-mounted) source tree so it never collides with
# the host's macOS .venv when the repo is mounted in at runtime.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH

# System tooling for the Linux-only tests: ext4 (e2fsprogs), loopback/mount (util-linux),
# and udev libraries for pyudev.
RUN apt-get update && apt-get install -y --no-install-recommends \
        e2fsprogs \
        dosfstools \
        exfatprogs \
        util-linux \
        mount \
        kmod \
        udev \
        libudev1 \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install dependencies first (cached layer) from the manifest + lock only.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --extra linux --no-install-project

# Install the project itself.
COPY . .
RUN uv sync --frozen --extra linux

CMD ["pytest", "-q"]
