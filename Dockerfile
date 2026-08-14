# ──────────────────────────────────────────────────────────────
# Stage 1: Charm base runtime
# ──────────────────────────────────────────────────────────────
FROM ghcr.io/charmaios/charm-runner-base:latest AS base

# ──────────────────────────────────────────────────────────────
# Stage 2: System dependencies for Hermes Agent
# ──────────────────────────────────────────────────────────────
USER root

# Hermes requires: git (for skills hub), ripgrep (code search tool),
# ffmpeg (voice memo transcription), and sqlite3 (FTS5 session store).
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        git \
        ripgrep \
        ffmpeg \
        sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Install uv (Hermes's package manager of choice)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# ──────────────────────────────────────────────────────────────
# Stage 3: Install Hermes Agent from source
# ──────────────────────────────────────────────────────────────
WORKDIR /opt/hermes

# Clone the pinned release of hermes-agent
ARG HERMES_VERSION=v0.19.1
RUN git clone --depth 1 --branch ${HERMES_VERSION} \
    https://github.com/NousResearch/hermes-agent.git . \
    && uv venv /opt/hermes/.venv \
    && uv pip install --python /opt/hermes/.venv/bin/python -e "." \
    && rm -rf .git

# Make the hermes package importable from anywhere
ENV PYTHONPATH="/opt/hermes:${PYTHONPATH}"
ENV PATH="/opt/hermes/.venv/bin:${PATH}"

# ──────────────────────────────────────────────────────────────
# Stage 4: Install the Charm adapter bridge
# ──────────────────────────────────────────────────────────────
COPY . /opt/charm-adapter-hermes
RUN pip install --no-cache-dir /opt/charm-adapter-hermes

# ──────────────────────────────────────────────────────────────
# Runtime defaults
# ──────────────────────────────────────────────────────────────
# HERMES_HOME is redirected at runtime by the adapter to
# CHARM_WORKSPACE_DIR for daemon persistence, but set a safe
# default for local testing.
ENV HERMES_HOME="/workspace/.hermes"

WORKDIR /app/agent_code
