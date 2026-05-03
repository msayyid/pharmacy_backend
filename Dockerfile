# syntax=docker/dockerfile:1.7
#
# Pharmacy API — production multistage image.
# Builder installs deps with uv; runtime ships only the .venv + app code.

# ─── Builder stage ─────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Build deps for asyncmy / argon2-cffi / cryptography wheels (some platforms).
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libffi-dev \
        libssl-dev \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Pin uv to the version we developed against.
COPY --from=ghcr.io/astral-sh/uv:0.11.8 /uv /uvx /usr/local/bin/

# 1) Cache dep layer separately from source.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# 2) Bring in source and finalise install.
COPY README.md ./
COPY app ./app
RUN uv sync --frozen --no-dev

# ─── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# Build-time arg → label → env. CI sets ``--build-arg GIT_SHA=$GITHUB_SHA``;
# local builds default to "dev". The label feeds Sentry release tagging
# and `docker inspect` for in-container provenance.
ARG GIT_SHA=dev

LABEL org.opencontainers.image.source="https://github.com/msayyid/pharmacy_backend" \
      org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.title="pharmacy-api" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    GIT_SHA="${GIT_SHA}"

WORKDIR /app

# Minimal runtime libs:
#   libffi8     — argon2-cffi
#   libssl3     — cryptography (in case wheel isn't fully self-contained)
#   curl        — healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
        libffi8 \
        libssl3 \
        curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system pharmacy \
    && useradd --system --gid pharmacy --no-create-home --uid 1000 pharmacy

COPY --from=builder --chown=pharmacy:pharmacy /app /app

USER pharmacy
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl --fail --silent http://localhost:8000/health || exit 1

CMD ["gunicorn", "app.main:app", \
     "-k", "uvicorn.workers.UvicornWorker", \
     "-w", "4", "-b", "0.0.0.0:8000", \
     "--access-logfile", "-", "--error-logfile", "-"]
