# syntax=docker/dockerfile:1
# Образ backend: api, worker, миграции и служебные разовые команды.
# Версии закреплены: одна и та же ревизия репозитория собирает один и тот же образ.
# Обновление базовых образов — правкой ARG ниже (и того же uv в integration_1c/Dockerfile).
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
# Байт-код приложения готовится при сборке: в контейнере корневая ФС только для чтения.
RUN /app/.venv/bin/python -m compileall -q app migrations

FROM ${PYTHON_IMAGE}
# uid/gid 10001 закреплены: на них опираются права томов (compose.yaml, init-secrets).
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
# FORWARDED_ALLOW_IPS — адрес обратного прокси, которому верим X-Forwarded-For
# (uvicorn читает переменную сам); compose подставляет адрес контейнера web.
# Журнал доступа uvicorn выключен: он пишет query-строку, а запросы и так
# журналирует RequestContextMiddleware — без query и тел.
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    FILE_STORAGE_PATH=/data/files FORWARDED_ALLOW_IPS=127.0.0.1
USER app
EXPOSE 8000
# Проверки живости — в compose.yaml: у api, worker и разовых сервисов они разные.
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--no-access-log"]
