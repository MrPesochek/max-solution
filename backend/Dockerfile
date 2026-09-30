ARG PYTHON_IMAGE=python:3.13.15-slim-trixie
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.10.2

FROM ${UV_IMAGE} AS uv

FROM ${PYTHON_IMAGE} AS builder
COPY --from=uv /uv /bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev
COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app
RUN /app/.venv/bin/python -m compileall -q app migrations

FROM ${PYTHON_IMAGE}
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --create-home app \
    && mkdir -p /data/files /data/secrets \
    && chown -R app:app /data \
    && chmod 0700 /data/secrets
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/alembic.ini ./
COPY --from=builder /app/migrations ./migrations
COPY --from=builder /app/app ./app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    FILE_STORAGE_PATH=/data/files FORWARDED_ALLOW_IPS=127.0.0.1
USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--no-access-log"]
