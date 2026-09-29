#!/usr/bin/env bash
# Поведение scripts/deploy.sh на заглушке docker: коды выхода и история выкладок
# при удачной выкладке, автооткате и ручном откате (docs/deploy.md, «Обновление и откат»).
#
#   bash scripts/tests/test_deploy.sh
#
# Docker, сеть и настоящий .env не нужны: скрипт копируется во временный каталог,
# docker подменяется заглушкой в PATH. Здоровье сервисов задаётся по тегу образа.

set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/scripts/deploy.sh"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

FAILED=0
PASSED=0

# Заглушка docker: `compose up` запоминает тег из env-файла, `inspect` отвечает
# unhealthy для тегов из STUB_UNHEALTHY; `compose up` падает для тегов из STUB_UP_FAIL;
# `compose run ... --pending` печатает STUB_PENDING (список миграций новой версии).
make_stub() {
    mkdir -p "$WORK/bin"
    cat >"$WORK/bin/docker" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
state="$STUB_STATE"
in_list() { case " $2 " in *" $1 "*) return 0 ;; *) return 1 ;; esac; }
if [ "$1" = inspect ]; then
    tag="$(cat "$state/running" 2>/dev/null || true)"
    if in_list "$tag" "${STUB_UNHEALTHY:-}"; then echo unhealthy; else echo healthy; fi
    exit 0
fi
if [ "$1" = image ]; then exit 0; fi
[ "$1" = compose ] || exit 1
shift
env_file=""
if [ "${1:-}" = --env-file ]; then env_file="$2"; shift 2; fi
case "$1" in
    version | pull | build | logs) exit 0 ;;
    config)
        if [ "${2:-}" = --services ]; then printf '%s\n' postgres api worker web; fi
        exit 0 ;;
    ps) echo "cid-$3"; exit 0 ;;
    run)
        [ -n "${STUB_PENDING:-}" ] && printf '%s\n' "$STUB_PENDING"
        exit 0 ;;
    up)
        tag="$(grep -E '^IMAGE_TAG=' "$env_file" | tail -n1 | cut -d= -f2-)"
        echo "up $tag" >>"$state/calls"
        if in_list "$tag" "${STUB_UP_FAIL:-}"; then exit 1; fi
        echo "$tag" >"$state/running"
        exit 0 ;;
esac
exit 1
STUB
    chmod +x "$WORK/bin/docker"
}

# Новый стенд: текущий тег $1, история — остальные аргументы.
setup() {
    local current="$1"
    shift
    ROOT="$WORK/root"
    rm -rf "$ROOT" "$WORK/state"
    mkdir -p "$ROOT/scripts" "$ROOT/var/deploy" "$WORK/state"
    cp "$SRC" "$ROOT/scripts/deploy.sh"
    cat >"$ROOT/.env" <<ENV
COMPOSE_FILE=compose.yaml:compose.prod.yaml
PUBLIC_BASE_URL=https://repair.example
IMAGE_TAG=$current
ENV
    : >"$ROOT/var/deploy/history"
    local tag
    for tag in "$@"; do echo "$tag" >>"$ROOT/var/deploy/history"; done
    echo "$current" >"$WORK/state/running"
}

# Запуск deploy.sh; код выхода — в STATUS, stderr — в $WORK/stderr.
deploy() {
    STATUS=0
    PATH="$WORK/bin:$PATH" STUB_STATE="$WORK/state" SKIP_PUBLIC_CHECK=1 HEALTH_TIMEOUT=5 \
        bash "$ROOT/scripts/deploy.sh" "$@" >"$WORK/stdout" 2>"$WORK/stderr" || STATUS=$?
}

image_tag() { grep -E '^IMAGE_TAG=' "$ROOT/.env" | cut -d= -f2-; }
history_lines() { paste -sd' ' "$ROOT/var/deploy/history"; }

check() {
    local name="$1" expected="$2" actual="$3"
    if [ "$expected" = "$actual" ]; then
        PASSED=$((PASSED + 1))
    else
        FAILED=$((FAILED + 1))
        echo "FAIL ${CASE}: $name — ожидалось «${expected}», получено «${actual}»" >&2
        sed 's/^/    stderr: /' "$WORK/stderr" >&2
    fi
}

make_stub

CASE="удачная выкладка"
setup A A
deploy --pull B --no-backup
check "код выхода" 0 "$STATUS"
check "IMAGE_TAG" B "$(image_tag)"
check "история" "A B" "$(history_lines)"

CASE="выкладка с миграциями: список и напоминание про дамп"
setup A A
STUB_PENDING=$'0024: журнал ревизий\n0025: новая колонка' deploy --pull B --no-backup
check "код выхода" 0 "$STATUS"
check "список миграций" 1 "$(grep -c '^  0025: новая колонка' "$WORK/stdout" || true)"
check "заголовок списка" 1 "$(grep -c 'применит миграции' "$WORK/stdout" || true)"
check "дампа не будет" 1 "$(grep -c 'дампа БД перед миграциями не будет' "$WORK/stderr" || true)"
check "без пометки — без предупреждения" 0 "$(grep -c 'ломает откат' "$WORK/stdout" || true)"

CASE="выкладка с миграцией, ломающей откат"
setup A A
STUB_PENDING='0025: переименование столбца [ломает откат]' deploy --pull B --no-backup
check "код выхода" 0 "$STATUS"
check "предупреждение" 1 "$(grep -c 'вернуться на A после выкладки можно только восстановлением' "$WORK/stdout" || true)"

CASE="выкладка без миграций"
setup A A
deploy --pull B --no-backup
check "сообщение" 1 "$(grep -c 'Миграций нет' "$WORK/stdout" || true)"

CASE="выкладка не прошла, автооткат удался"
setup B A B
STUB_UNHEALTHY="C" deploy --pull C --no-backup
check "код выхода" 1 "$STATUS"
check "IMAGE_TAG" B "$(image_tag)"
check "история без C" "A B" "$(history_lines)"
check "предупреждение о схеме при автооткате" 1 "$(grep -c 'Схема БД не откатывается: B запускается на схеме версии C' "$WORK/stdout" || true)"

CASE="выкладка не прошла, автооткат тоже"
setup B A B
STUB_UNHEALTHY="B C" deploy --pull C --no-backup
check "код выхода" 2 "$STATUS"
check "история без C" "A B" "$(history_lines)"
check "сообщение об ошибке" 1 "$(grep -c 'и после отката на B стенд не здоров' "$WORK/stderr" || true)"

CASE="ручной откат удался"
setup B A B
deploy --rollback
check "код выхода" 0 "$STATUS"
check "IMAGE_TAG" A "$(image_tag)"
check "история" "A B A" "$(history_lines)"
check "предупреждение о схеме" 1 "$(grep -c 'Схема БД не откатывается: A запускается на схеме версии B' "$WORK/stdout" || true)"
check "условие отката" 1 "$(grep -c 'обратно совместима' "$WORK/stdout" || true)"

CASE="ручной откат: стенд не здоров"
setup B A B
STUB_UNHEALTHY="A" deploy --rollback
check "код выхода" 1 "$STATUS"
check "история не изменилась" "A B" "$(history_lines)"
check "сообщение об ошибке" 1 "$(grep -c 'ОШИБКА: и после отката на A' "$WORK/stderr" || true)"

CASE="ручной откат: compose up упал"
setup B A B
STUB_UP_FAIL="A" deploy --rollback
check "код выхода" 1 "$STATUS"
check "история не изменилась" "A B" "$(history_lines)"

CASE="ручной откат без истории"
setup B B
deploy --rollback
check "код выхода" 1 "$STATUS"
check "история не изменилась" "B" "$(history_lines)"

echo "deploy.sh: проверок пройдено $PASSED, провалено $FAILED"
[ "$FAILED" -eq 0 ]
