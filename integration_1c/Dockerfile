ARG PYTHON_IMAGE=python:3.13.15-slim-trixie
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.10.2

FROM ${UV_IMAGE} AS uv

FROM ${PYTHON_IMAGE} AS base

FROM base AS builder
COPY --from=uv /uv /uvx /bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

FROM base AS runtime
WORKDIR /app
RUN groupadd --system --gid 999 onec \
    && useradd --system --uid 999 --gid onec --home-dir /app onec \
    && mkdir -p /app/data && chown -R onec:onec /app/data
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:${PATH}" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
VOLUME ["/app/data"]

FROM runtime AS connector
COPY connector ./connector
COPY profiles ./profiles
RUN python -m compileall -q connector
ENV CONNECTOR_DATABASE_PATH=/app/data/connector.sqlite3
USER onec
EXPOSE 8083
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8083/healthz', timeout=2)" || exit 1
CMD ["uvicorn", "connector.main:app", "--host", "0.0.0.0", "--port", "8083", "--no-access-log"]

FROM runtime AS emulator
COPY emulator ./emulator
RUN python -m compileall -q emulator
ENV ONEC_EMULATOR_DATABASE_PATH=/app/data/onec_emulator.sqlite3
USER onec
EXPOSE 8082
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8082/healthz', timeout=2)" || exit 1
CMD ["uvicorn", "emulator.main:app", "--host", "0.0.0.0", "--port", "8082"]
