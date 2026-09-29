#!/usr/bin/env bash

set -euo pipefail

API_BASE_URL="${API_BASE_URL:-http://localhost:8080}"
ONEC_BASE_URL="${ONEC_BASE_URL:-http://localhost:8082}"
ONEC_BASE_NAME="${ONEC_BASE_NAME:-unf_demo}"
ONEC_ODATA_USER="${ONEC_ODATA_USER:-odata}"
ONEC_ODATA_PASSWORD="${ONEC_ODATA_PASSWORD:-odata-demo}"
ONEC_UI_PASSWORD="${ONEC_UI_PASSWORD:-demo}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PHOTO_FIXTURE="${PHOTO_FIXTURE:-${SCRIPT_DIR}/fixtures/smoke-photo.jpg}"

APP_API="${API_BASE_URL}/app-api/v1"
umask 077
COOKIE_JAR="$(mktemp)"
HEADERS_FILE="$(mktemp)"
trap 'rm -f "$COOKIE_JAR" "$HEADERS_FILE"' EXIT
export ONEC_ODATA_PASSWORD

log() { printf '\n== %s ==\n' "$1"; }
fail() { printf 'ОШИБКА: %s\n' "$1" >&2; exit 1; }

csrf_from() {
    python3 -c "
import re, sys
match = re.search(r'name=\"csrf_token\" value=\"([^\"]+)\"', sys.stdin.read())
print(match.group(1) if match else '')
"
}

odata() {
    python3 - "$ONEC_BASE_URL" "$ONEC_BASE_NAME" "$ONEC_ODATA_USER" "$@" <<'PY'
import base64, os, sys, urllib.parse, urllib.request
base, name, user, resource = sys.argv[1:5]
password = os.environ["ONEC_ODATA_PASSWORD"]
query = {"$format": "json"}
if len(sys.argv) > 5:
    query["$filter"] = sys.argv[5]
url = f"{base}/{name}/odata/standard.odata/{urllib.parse.quote(resource, safe='()\'/')}?{urllib.parse.urlencode(query)}"
request = urllib.request.Request(url)
request.add_header("Authorization", "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode())
with urllib.request.urlopen(request, timeout=10) as response:
    print(response.read().decode())
PY
}

idem_key() { python3 -c "import uuid; print(uuid.uuid4().hex)"; }

json_get() {
    printf '%s' "$1" | python3 -c "
import json, sys
data = json.load(sys.stdin)
path = sys.argv[1].split('.')
for part in path:
    if part.isdigit():
        data = data[int(part)]
    else:
        data = data[part]
print(data)
" "$2"
}

log "0. Проверка живости API (${API_BASE_URL})"
curl -fsS "${API_BASE_URL}/healthz" >/dev/null || fail "API недоступен на ${API_BASE_URL} (см. переменную API_BASE_URL; без web используйте профиль compose 'debug': docker compose --profile debug up -d api-debug)"
curl -fsS "${API_BASE_URL}/readyz" >/dev/null || fail "API не готов (readyz)"
echo "API готов."

log "1. Demo-вход сотрудником (user_key=employee)"
LOGIN_RESPONSE="$(curl -fsS -X POST "${APP_API}/auth/demo" \
    -H 'Content-Type: application/json' \
    -d '{"user_key":"employee"}')" || fail "demo-вход не прошёл — стенд поднят с DEMO_LOGIN_ENABLED=true и APP_ENV=demo, сид запускался?"
TOKEN="$(json_get "$LOGIN_RESPONSE" token)"
ORG_ID="$(json_get "$LOGIN_RESPONSE" memberships.0.organization.id)"
[ -n "$TOKEN" ] || fail "не удалось получить токен сессии"
echo "Сессия получена, организация: ${ORG_ID}"

printf 'Authorization: Bearer %s\nX-Organization-Id: %s\n' "$TOKEN" "$ORG_ID" >"$HEADERS_FILE"

log "2. Список оборудования точки сотрудника"
EQUIPMENT_RESPONSE="$(curl -fsS "${APP_API}/equipment" -H "@$HEADERS_FILE")" \
    || fail "не удалось получить список оборудования"
EQUIPMENT_ID="$(json_get "$EQUIPMENT_RESPONSE" items.0.id)"
[ -n "$EQUIPMENT_ID" ] || fail "у сотрудника нет доступного оборудования — сид демо-данных запускался?"
echo "Оборудование: ${EQUIPMENT_ID}"

log "3. Создание заявки (свой сервис)"
DRAFT_BODY="$(python3 -c "
import json, sys
print(json.dumps({
    'equipment_id': sys.argv[1],
    'route': 'own_service',
    'urgency': 'normal',
    'symptom_description': 'Смоук-тест: оборудование не набирает температуру.',
}))
" "$EQUIPMENT_ID")"
DRAFT_RESPONSE="$(curl -fsS -X POST "${APP_API}/requests" \
    -H "@$HEADERS_FILE" \
    -H "Idempotency-Key: $(idem_key)" -H 'Content-Type: application/json' \
    -d "$DRAFT_BODY")" || fail "не удалось создать черновик заявки"
REQUEST_ID="$(json_get "$DRAFT_RESPONSE" id)"
[ -n "$REQUEST_ID" ] || fail "черновик заявки создан без id"
echo "Заявка: ${REQUEST_ID}"

log "4. Загрузка фото к заявке"
[ -f "$PHOTO_FIXTURE" ] || fail "не найден файл фото ${PHOTO_FIXTURE} (переменная PHOTO_FIXTURE)"
ATTACHMENT_RESPONSE="$(curl -fsS -X POST "${APP_API}/requests/${REQUEST_ID}/attachments" \
    -H "@$HEADERS_FILE" \
    -H "Idempotency-Key: $(idem_key)" \
    -F "slot=overview" \
    -F "file=@${PHOTO_FIXTURE};type=image/jpeg")" || fail "не удалось загрузить фото к заявке"
ATTACHMENT_ID="$(json_get "$ATTACHMENT_RESPONSE" id)"
[ -n "$ATTACHMENT_ID" ] || fail "вложение загружено без id"
echo "Вложение: ${ATTACHMENT_ID}"

log "5. Ожидание обработки фото (processing_state=ready, нужен worker)"
PROCESSING_STATE=""
for _ in $(seq 1 30); do
    ATTACHMENT_STATUS_RESPONSE="$(curl -fsS "${APP_API}/attachments/${ATTACHMENT_ID}" -H "@$HEADERS_FILE")" \
        || fail "не удалось получить состояние вложения"
    PROCESSING_STATE="$(json_get "$ATTACHMENT_STATUS_RESPONSE" processing_state)"
    [ "$PROCESSING_STATE" = "ready" ] && break
    [ "$PROCESSING_STATE" = "rejected" ] && fail "фото отклонено платформой: ${ATTACHMENT_STATUS_RESPONSE}"
    sleep 1
done
[ "$PROCESSING_STATE" = "ready" ] || fail "фото не перешло в ready за отведённое время (worker запущен? docker compose up ... worker)"
echo "Фото обработано: ${PROCESSING_STATE}"

log "6. Отправка заявки своему сервису"
REQUEST_RESPONSE="$(curl -fsS "${APP_API}/requests/${REQUEST_ID}" -H "@$HEADERS_FILE")" \
    || fail "не удалось перечитать заявку перед отправкой"
REQUEST_VERSION="$(json_get "$REQUEST_RESPONSE" version)"
[ -n "$REQUEST_VERSION" ] || fail "в карточке заявки нет version"
SUBMIT_RESPONSE="$(curl -fsS -X POST "${APP_API}/requests/${REQUEST_ID}/actions/submit-to-own-service" \
    -H "@$HEADERS_FILE" \
    -H "Idempotency-Key: $(idem_key)" -H 'Content-Type: application/json' \
    -d "{\"expected_version\": ${REQUEST_VERSION}}")" || fail "не удалось отправить заявку своему сервису (нет подтверждённой привязки к сервису? см. python -m app.demo.seed)"
STATUS="$(json_get "$SUBMIT_RESPONSE" status)"
[ "$STATUS" = "awaiting_provider" ] || fail "неожиданный статус после отправки: ${STATUS}"
echo "Статус заявки: ${STATUS}"

log "7. Ожидание заказ-наряда в эмуляторе 1С (вебхук -> коннектор -> OData)"
REF_KEY=""
for _ in $(seq 1 30); do
    ORDERS="$(odata "Document_ЗаказНаряд" 2>/dev/null || true)"
    if [ -n "$ORDERS" ]; then
        REF_KEY="$(python3 -c "
import json, sys
for doc in json.loads(sys.argv[1]).get('value', []):
    if any(sys.argv[2] in str(row.get('Значение', '')) for row in doc.get('ДополнительныеРеквизиты', [])):
        print(doc['Ref_Key'] + '\t' + doc['Number'])
        break
" "$ORDERS" "$REQUEST_ID")"
    fi
    [ -n "$REF_KEY" ] && break
    sleep 2
done
[ -n "$REF_KEY" ] || fail "коннектор не создал заказ-наряд за отведённое время (подписка: curl -s http://localhost:8083/status)"
DOC_NUMBER="$(printf '%s' "$REF_KEY" | cut -f2)"
REF_KEY="$(printf '%s' "$REF_KEY" | cut -f1)"
echo "Заказ-наряд ${DOC_NUMBER} (${REF_KEY})"

log "8. Фото заявки приложено к документу 1С"
FILE_SEEN=0
for _ in $(seq 1 15); do
    FILES="$(odata "Catalog_ЗаказНарядПрисоединенныеФайлы" "ВладелецФайла_Key eq guid'${REF_KEY}'" 2>/dev/null || true)"
    FILE_KEY="$(python3 -c "
import json, sys
items = json.loads(sys.argv[1] or '{}').get('value', [])
print(items[0]['Ref_Key'] if items else '')
" "${FILES:-}")"
    if [ -n "$FILE_KEY" ]; then
        BINARY="$(odata "InformationRegister_ДвоичныеДанныеФайлов" "Файл eq guid'${FILE_KEY}'")"
        SIZE="$(python3 -c "
import base64, json, sys
items = json.loads(sys.argv[1]).get('value', [])
print(len(base64.b64decode(items[0]['ДвоичныеДанныеФайла_Base64Data'])) if items else 0)
" "$BINARY")"
        if [ "$SIZE" -gt 0 ]; then
            FILE_SEEN=1
            echo "Присоединённый файл ${FILE_KEY}, ${SIZE} байт"
            break
        fi
    fi
    sleep 2
done
[ "$FILE_SEEN" = "1" ] || fail "коннектор не приложил фото к заказ-наряду за отведённое время"

log "9. Вход «пользователя 1С» в веб-форму эмулятора"
LOGIN_CSRF="$(curl -fsS -c "$COOKIE_JAR" -b "$COOKIE_JAR" "${ONEC_BASE_URL}/login" | csrf_from)"
[ -n "$LOGIN_CSRF" ] || fail "в форме входа эмулятора 1С нет CSRF-токена"
curl -fsS -c "$COOKIE_JAR" -b "$COOKIE_JAR" -X POST "${ONEC_BASE_URL}/login" \
    --data-urlencode "password@-" < <(printf '%s' "$ONEC_UI_PASSWORD") \
    --data-urlencode "csrf_token=${LOGIN_CSRF}" >/dev/null \
    || fail "не удалось войти в эмулятор 1С (проверьте ONEC_UI_PASSWORD)"
echo "Пользователь 1С вошёл."

submit_order_form() {
    local csrf
    csrf="$(curl -fsS -b "$COOKIE_JAR" "${ONEC_BASE_URL}/ui/orders/${REF_KEY}" | csrf_from)"
    [ -n "$csrf" ] || fail "в форме заказ-наряда нет CSRF-токена"
    local args=(--data-urlencode "csrf_token=${csrf}")
    for pair in "$@"; do args+=(--data-urlencode "$pair"); done
    curl -fsS -b "$COOKIE_JAR" -X POST "${ONEC_BASE_URL}/ui/orders/${REF_KEY}" "${args[@]}" \
        -o /dev/null -w '%{redirect_url}'
}

log "10. Состояние «Принят» и проведение документа в 1С"
REDIRECT="$(submit_order_form "state=Принят" "action=post")"
case "$REDIRECT" in *error=0*) ;; *) fail "эмулятор не провёл документ: ${REDIRECT}" ;; esac
echo "Документ проведён с состоянием «Принят»."

log "11. Коннектор отправил accept — статус заявки на платформе"
FINAL_STATUS=""
for _ in $(seq 1 20); do
    REQUEST_RESPONSE="$(curl -fsS "${APP_API}/requests/${REQUEST_ID}" -H "@$HEADERS_FILE")"
    FINAL_STATUS="$(json_get "$REQUEST_RESPONSE" status)"
    [ "$FINAL_STATUS" = "accepted" ] && break
    sleep 2
done
[ "$FINAL_STATUS" = "accepted" ] || fail "статус заявки не стал accepted (получено: ${FINAL_STATUS})"
echo "Статус заявки: accepted"

log "12. В 1С заданы дата выезда и сумма выезда"
ITEMS="$(odata "Catalog_Номенклатура" "Description eq 'Выезд мастера (диагностика)'")"
VISIT_ITEM="$(json_get "$ITEMS" value.0.Ref_Key)"
VISIT_DAY="$(python3 -c "import datetime; print((datetime.date.today() + datetime.timedelta(days=1)).isoformat())")"
REDIRECT="$(submit_order_form "start=${VISIT_DAY}T10:00" "end=${VISIT_DAY}T12:00" \
    "row-0-item=${VISIT_ITEM}" "row-0-content=" "row-0-amount=1500" "action=post")"
case "$REDIRECT" in *error=0*) ;; *) fail "эмулятор не провёл документ: ${REDIRECT}" ;; esac
echo "Выезд ${VISIT_DAY} 10:00–12:00, 1500 руб."

log "13. На платформе появилось предложение выезда"
PROPOSAL=""
for _ in $(seq 1 20); do
    REQUEST_RESPONSE="$(curl -fsS "${APP_API}/requests/${REQUEST_ID}" -H "@$HEADERS_FILE")"
    PROPOSAL="$(python3 -c "
import json, sys
card = json.loads(sys.argv[1])
for item in card.get('visit_proposals') or []:
    if item.get('status') == 'pending' and (item.get('price') or {}).get('amount_minor') == 150000:
        print(item['id'], item.get('visit_window_start'))
        break
" "$REQUEST_RESPONSE")"
    [ -n "$PROPOSAL" ] && break
    sleep 2
done
[ -n "$PROPOSAL" ] || fail "предложение выезда на 1500 руб. не появилось на платформе"
echo "Предложение выезда: ${PROPOSAL}"

log "Готово"
echo "A04 пройдена через 1С: заявка ${REQUEST_ID} -> заказ-наряд ${DOC_NUMBER}, принята в 1С, статус на платформе — accepted, предложение выезда передано."
