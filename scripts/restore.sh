#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT/.env}"

fail() { echo "ОШИБКА: $*" >&2; exit 1; }

SOURCE=""
YES=""
FORCE=""
for arg in "$@"; do
    case "$arg" in
        --yes) YES=1 ;;
        --force) FORCE=1 ;;
        -h | --help) sed -n '2,12p' "$0"; exit 0 ;;
        -*) fail "неизвестный параметр $arg (есть --yes, --force)" ;;
        *) SOURCE="$arg" ;;
    esac
done

[ -n "$SOURCE" ] || fail "укажите каталог копии: bash scripts/restore.sh <BACKUP_DIR>/<время> --yes"
[ -f "$SOURCE/manifest.txt" ] || fail "в $SOURCE нет manifest.txt — копия не завершена"
[ -f "$SOURCE/db.dump" ] || fail "в $SOURCE нет db.dump"
[ -f "$ENV_FILE" ] || fail "нет $ENV_FILE"
[ -n "$YES" ] || fail "восстановление заменит БД и файлы стенда; подтвердите флагом --yes"

compose() { docker compose --project-directory "$ROOT" --env-file "$ENV_FILE" "$@"; }

EXPECTED="$(grep -E '^key_fingerprint=' "$SOURCE/manifest.txt" | cut -d= -f2-)"
ACTUAL="$(compose run --rm --no-deps -T init-secrets 2>/dev/null | head -n1 | cut -d' ' -f1 || true)"
echo "Ключ в копии: ${EXPECTED:-unknown}, ключ в .env: ${ACTUAL:-не читается}"
if [ "$EXPECTED" != "$ACTUAL" ] && [ -z "$FORCE" ]; then
    fail "ключ шифрования не совпадает с копией: верните SECRETS_ENCRYPTION_KEY из секретов копии (или --force)"
fi

echo "Остановка сервисов приложения"
services=(web api worker)
for optional in onec-connector onec-emulator; do
    if compose config --services | grep -qx "$optional"; then
        services+=("$optional")
    fi
done
compose stop "${services[@]}"

echo "PostgreSQL"
compose up -d --wait postgres

echo "БД <- $SOURCE/db.dump"
compose exec -T postgres dropdb -U repair --if-exists --force repair
compose exec -T postgres createdb -U repair -O repair repair
compose exec -T postgres pg_restore -U repair -d repair --no-owner --exit-on-error <"$SOURCE/db.dump"

if [ -f "$SOURCE/files.tar.gz" ]; then
    echo "Вложения <- $SOURCE/files.tar.gz"
    compose run --rm --no-deps -T --entrypoint sh api -c \
        'find /data/files -mindepth 1 -delete && tar xzf - -C /data/files' <"$SOURCE/files.tar.gz"
fi

if [ -f "$SOURCE/connector.tar.gz" ] && compose config --services | grep -qx onec-connector; then
    echo "Коннектор 1С <- $SOURCE/connector.tar.gz"
    compose run --rm --no-deps -T --entrypoint sh onec-connector -c \
        'find /app/data -mindepth 1 -delete && tar xzf - -C /app/data' <"$SOURCE/connector.tar.gz"
fi

if [ -f "$SOURCE/onec.tar.gz" ] && compose config --services | grep -qx onec-emulator; then
    echo "Демо-CRM <- $SOURCE/onec.tar.gz"
    compose run --rm --no-deps -T --entrypoint sh onec-emulator -c \
        'find /app/data -mindepth 1 -delete && tar xzf - -C /app/data' <"$SOURCE/onec.tar.gz"
fi

echo "Проверка ключа на секретах из дампа"
compose run --rm --no-deps -T api python -m app.infra.crypto_keys check \
    || fail "ключ не расшифровывает секреты из дампа — верните ключ из копии секретов"

echo "Запуск стенда"
compose up -d
echo "Готово. Проверьте docker compose ps и $(grep -E '^PUBLIC_BASE_URL=' "$ENV_FILE" | tail -n1 | cut -d= -f2-)/readyz"
