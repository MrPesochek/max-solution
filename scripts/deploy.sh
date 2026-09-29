#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT/.env}"
STATE_DIR="$ROOT/var/deploy"
HISTORY="$STATE_DIR/history"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-240}"
KEEP_IMAGES="${KEEP_IMAGES:-3}"

fail() { echo "ОШИБКА: $*" >&2; exit 1; }
info() { printf '\n== %s ==\n' "$*"; }

MODE=build
TAG=""
BACKUP=1
while [ $# -gt 0 ]; do
    case "$1" in
        --pull) MODE=pull; TAG="${2:-}"; [ -n "$TAG" ] || fail "--pull требует тег"; shift ;;
        --rollback) MODE=rollback ;;
        --no-backup) BACKUP="" ;;
        -h | --help) sed -n '2,24p' "$0"; exit 0 ;;
        *) fail "неизвестный параметр $1 (есть --pull TAG, --rollback, --no-backup)" ;;
    esac
    shift
done

cd "$ROOT"
command -v docker >/dev/null || fail "нет docker"
docker compose version >/dev/null 2>&1 || fail "нет docker compose v2"
[ -f "$ENV_FILE" ] || fail "нет $ENV_FILE (cp .env.prod.example .env, docs/deploy.md)"

env_value() {
    grep -E "^$1=" "$ENV_FILE" | tail -n1 | cut -d= -f2- | sed -e 's/^["'\'']//' -e 's/["'\'']$//' || true
}

set_env_value() {
    local tmp
    tmp="$(mktemp "$ENV_FILE.XXXXXX")"
    awk -v key="$1" -v value="$2" '
        BEGIN { done = 0 }
        $0 ~ "^" key "=" { if (!done) { print key "=" value; done = 1 }; next }
        { print }
        END { if (!done) print key "=" value }
    ' "$ENV_FILE" >"$tmp"
    chmod --reference="$ENV_FILE" "$tmp" 2>/dev/null || chmod 600 "$tmp"
    mv "$tmp" "$ENV_FILE"
}

compose() { docker compose --env-file "$ENV_FILE" "$@"; }

COMPOSE_FILES="${COMPOSE_FILE:-$(env_value COMPOSE_FILE)}"
case "$COMPOSE_FILES" in
    *compose.demo.yaml*) fail "в COMPOSE_FILE подключён compose.demo.yaml — на сервер он не выкладывается" ;;
    *compose.prod.yaml*) ;;
    *) fail "в $ENV_FILE нужен COMPOSE_FILE=compose.yaml:compose.prod.yaml" ;;
esac
compose config -q || fail "конфигурация compose не собирается (см. сообщение выше)"

PUBLIC_BASE_URL="$(env_value PUBLIC_BASE_URL)"
case "$PUBLIC_BASE_URL" in https://*) ;; *) fail "PUBLIC_BASE_URL должен начинаться с https://" ;; esac

mkdir -p "$STATE_DIR"
touch "$HISTORY"
CURRENT_TAG="$(env_value IMAGE_TAG)"
IMAGE_PREFIX="$(env_value IMAGE_PREFIX)"
IMAGE_PREFIX="${IMAGE_PREFIX:-repair-hub}"

health_services() {
    local services=(postgres api worker web)
    local optional
    for optional in onec-connector onec-emulator; do
        if compose config --services | grep -qx "$optional"; then
            services+=("$optional")
        fi
    done
    printf '%s\n' "${services[@]}"
}

service_state() {
    local cid
    cid="$(compose ps -q "$1" 2>/dev/null | head -n1)"
    [ -n "$cid" ] || { echo missing; return; }
    docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$cid"
}

wait_healthy() {
    local deadline=$((SECONDS + HEALTH_TIMEOUT)) pending svc state
    while :; do
        pending=""
        for svc in $(health_services); do
            state="$(service_state "$svc")"
            case "$state" in
                healthy) ;;
                unhealthy | exited | dead | missing) echo "  $svc: $state" >&2; return 1 ;;
                *) pending="$pending $svc($state)" ;;
            esac
        done
        if [ -z "$pending" ]; then
            if [ -n "${SKIP_PUBLIC_CHECK:-}" ] || curl -fsS --max-time 5 -o /dev/null "$PUBLIC_BASE_URL/readyz"; then
                return 0
            fi
            pending=" $PUBLIC_BASE_URL/readyz"
        fi
        [ "$SECONDS" -lt "$deadline" ] || { echo "  не готовы за ${HEALTH_TIMEOUT} с:$pending" >&2; return 1; }
        sleep 5
    done
}

start_tag() {
    set_env_value IMAGE_TAG "$1"
    compose up -d --remove-orphans
}

rollback_to() {
    local target="$1" schema_tag="$2"
    info "Откат на $target"
    echo "Схема БД не откатывается: $target запускается на схеме версии $schema_tag" \
        "(migrate новых миграций не ждёт, БД новее кода допустима)."
    echo "Откат допустим только на теги, чья схема обратно совместима с текущей" \
        "(docs/deploy.md «Обновление и откат», backend/migrations/README.md);" \
        "иначе — восстановление из дампа (scripts/restore.sh)."
    if start_tag "$target" && wait_healthy; then
        echo "Стенд работает на предыдущем теге $target."
        return 0
    fi
    echo "ОШИБКА: и после отката на $target стенд не здоров — docker compose logs," \
        "docs/deploy.md «Обновление и откат» и «Восстановление»." >&2
    return 1
}

prune_images() {
    local keep
    keep="$(tail -n "$KEEP_IMAGES" "$HISTORY")"
    for repo in backend web onec-connector onec-emulator; do
        docker image ls "$IMAGE_PREFIX/$repo" --format '{{.Tag}}' | while read -r tag; do
            [ -n "$tag" ] && [ "$tag" != "<none>" ] || continue
            grep -qx "$tag" <<<"$keep" && continue
            docker image rm "$IMAGE_PREFIX/$repo:$tag" >/dev/null 2>&1 || true
        done
    done
}

if [ "$MODE" = rollback ]; then
    PREV="$(grep -vx "$CURRENT_TAG" "$HISTORY" | tail -n1 || true)"
    [ -n "$PREV" ] || fail "нет предыдущей выкладки в $HISTORY"
    rollback_to "$PREV" "$CURRENT_TAG" || exit 1
    echo "$PREV" >>"$HISTORY"
    exit 0
fi

if [ "$MODE" = build ]; then
    REV="$(git -C "$ROOT" rev-parse --short=12 HEAD 2>/dev/null || echo nogit)"
    if [ "$REV" != nogit ] && [ -n "$(git -C "$ROOT" status --porcelain 2>/dev/null)" ]; then
        REV="$REV-dirty"
    fi
    TAG="$(date -u +%Y%m%d%H%M%S)-$REV"
    info "Сборка образов $IMAGE_PREFIX/*:$TAG"
    IMAGE_TAG="$TAG" compose build
else
    info "Загрузка образов $IMAGE_PREFIX/*:$TAG"
    IMAGE_TAG="$TAG" compose pull
fi

pending_migrations() {
    IMAGE_TAG="$1" compose run --rm --no-deps -T migrate python -m app.db.migrate --pending 2>/dev/null
}

if [ "$(service_state postgres)" = healthy ]; then
    info "Миграции схемы в $TAG"
    if PENDING="$(pending_migrations "$TAG")"; then
        if [ -n "$PENDING" ]; then
            echo "Новая версия применит миграции (откат образов схему не вернёт):"
            while IFS= read -r line; do echo "  $line"; done <<<"$PENDING"
            if grep -q "ломает откат" <<<"$PENDING"; then
                echo "ВНИМАНИЕ: есть миграции с пометкой «ломает откат» — вернуться на $CURRENT_TAG" \
                    "после выкладки можно только восстановлением БД из дампа."
            fi
            if [ -n "$BACKUP" ]; then
                echo "Дамп БД будет сделан перед миграциями (scripts/backup.sh --db-only)."
            else
                echo "ВНИМАНИЕ: --no-backup — дампа БД перед миграциями не будет." >&2
            fi
        else
            echo "Миграций нет: схема БД уже подходит версии $TAG."
        fi
    else
        echo "Список миграций получить не удалось (образ без app.db.migrate или БД" \
            "недоступна) — после запуска смотрите docker compose logs migrate." >&2
    fi
fi

if [ -n "$BACKUP" ] && [ "$(service_state postgres)" = healthy ]; then
    info "Резервная копия БД перед миграциями"
    ENV_FILE="$ENV_FILE" bash "$ROOT/scripts/backup.sh" --db-only
fi

info "Миграции и запуск ($TAG)"
if start_tag "$TAG" && wait_healthy; then
    echo "$TAG" >>"$HISTORY"
    prune_images
    info "Готово: $PUBLIC_BASE_URL работает на $TAG"
    exit 0
fi

echo "Выкладка $TAG не прошла проверку. Последние строки журналов:" >&2
compose logs --tail=40 migrate api worker web >&2 || true
if [ -n "$CURRENT_TAG" ] && [ "$CURRENT_TAG" != "$TAG" ]; then
    rollback_to "$CURRENT_TAG" "$TAG" || exit 2
    echo "Выкладка $TAG не удалась, стенд возвращён на $CURRENT_TAG." >&2
else
    set_env_value IMAGE_TAG "$CURRENT_TAG"
    echo "Предыдущей выкладки нет — откатывать некуда." >&2
fi
exit 1
