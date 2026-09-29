#!/usr/bin/env bash

set -euo pipefail
umask 077

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT/.env}"

fail() { echo "ОШИБКА: $*" >&2; exit 1; }

DB_ONLY=""
for arg in "$@"; do
    case "$arg" in
        --db-only) DB_ONLY=1 ;;
        -h | --help) sed -n '2,16p' "$0"; exit 0 ;;
        *) fail "неизвестный параметр $arg (есть --db-only)" ;;
    esac
done

[ -f "$ENV_FILE" ] || fail "нет $ENV_FILE"
env_value() {
    grep -E "^$1=" "$ENV_FILE" | tail -n1 | cut -d= -f2- | sed -e 's/^["'\'']//' -e 's/["'\'']$//' || true
}
compose() { docker compose --project-directory "$ROOT" --env-file "$ENV_FILE" "$@"; }

BACKUP_DIR="${BACKUP_DIR:-$(env_value BACKUP_DIR)}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/repair-hub}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-$(env_value BACKUP_KEEP_DAYS)}"
KEEP_DAYS="${KEEP_DAYS:-14}"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
TARGET="$BACKUP_DIR/$STAMP"
mkdir -p "$TARGET" "$BACKUP_DIR/secrets"
chmod 700 "$BACKUP_DIR" "$BACKUP_DIR/secrets" "$TARGET"

trap '[ -f "$TARGET/manifest.txt" ] || { echo "копия не завершена, удаляю $TARGET" >&2; rm -rf "$TARGET"; }' EXIT

echo "БД -> $TARGET/db.dump"
compose exec -T postgres pg_dump -U repair -d repair -Fc --no-owner >"$TARGET/db.dump"
compose exec -T postgres pg_restore --list <"$TARGET/db.dump" >/dev/null \
    || fail "дамп не читается pg_restore"

if [ -z "$DB_ONLY" ]; then
    echo "Вложения -> $TARGET/files.tar.gz"
    compose run --rm --no-deps -T --entrypoint tar api czf - -C /data/files . >"$TARGET/files.tar.gz"

    if compose config --services | grep -qx onec-connector; then
        echo "Коннектор 1С -> $TARGET/connector.tar.gz"
        compose run --rm --no-deps -T --entrypoint tar onec-connector czf - -C /app/data . >"$TARGET/connector.tar.gz"
    fi

    if compose config --services | grep -qx onec-emulator; then
        echo "Демо-CRM -> $TARGET/onec.tar.gz"
        compose run --rm --no-deps -T --entrypoint python onec-emulator - >"$TARGET/onec.tar.gz" <<'PY'
import sqlite3
import sys
import tarfile
import tempfile
from pathlib import Path

with tempfile.TemporaryDirectory() as directory:
    snapshot = Path(directory) / "onec_emulator.sqlite3"
    source = sqlite3.connect("file:/app/data/onec_emulator.sqlite3?mode=ro", uri=True)
    target = sqlite3.connect(snapshot)
    source.backup(target)
    target.close()
    source.close()
    with tarfile.open(fileobj=sys.stdout.buffer, mode="w|gz") as archive:
        archive.add(snapshot, arcname=snapshot.name)
PY
    fi

    echo "Секреты -> $BACKUP_DIR/secrets/$STAMP.env"
    cp "$ENV_FILE" "$BACKUP_DIR/secrets/$STAMP.env"
    chmod 600 "$BACKUP_DIR/secrets/$STAMP.env"
fi

FINGERPRINT="$(compose run --rm --no-deps -T init-secrets 2>/dev/null | head -n1 | cut -d' ' -f1 || true)"
{
    echo "created=$STAMP"
    echo "image_tag=$(env_value IMAGE_TAG)"
    echo "key_fingerprint=${FINGERPRINT:-unknown}"
    echo "db_only=${DB_ONLY:-0}"
    (cd "$TARGET" && ls -l)
} >"$TARGET/manifest.txt.tmp"
mv "$TARGET/manifest.txt.tmp" "$TARGET/manifest.txt"

echo "Удаление копий старше $KEEP_DAYS дней"
find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 -type d -name '20*' -mtime +"$KEEP_DAYS" -exec rm -rf {} +
find "$BACKUP_DIR/secrets" -type f -name '*.env' -mtime +"$KEEP_DAYS" -delete

echo "Готово: $TARGET (ключ ${FINGERPRINT:-unknown})"
