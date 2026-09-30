# Руководство интегратора (интеграционный API)

Материал к ТЗ 17.2, п. 5. Схемы OpenAPI 3.1 лежат рядом:

| Файл | Контур | Base path (за прокси стенда) |
|---|---|---|
| `app-api.json` | Пользовательский API бота/Web App | `/app-api/v1` |
| `operator-api.json` | API платформенного оператора (модерация, проверка исполнителей) | `/operator-api/v1` |
| `integration-api.json` | API для CRM сервисной компании — предмет этого руководства | `/api/v1` |
| `data-api.json` | Сводная карта путей и методов всех контуров (без схем тел) плюс `/healthz`, `/readyz` — для перекрёстной проверки `DATA-API.yaml` эталонным валидатором | пути уже с префиксами |

Схемы генерируются из кода (`scripts/export_openapi.py`, `python -m app.demo.seed` не нужен для
этого шага) и обязаны совпадать с реализацией: расхождение — повод перегенерировать файлы, а не
править их руками.

Базовый адрес интеграционного API на стенде: `https://<домен-стенда>/api/v1` (в `compose.yaml`
`web`-прокси отдаёт этот путь наружу; при прямом обращении к контейнеру `api` — `http://api:8000/api/v1`).

## 1. Получение ключа

Ключ интеграции выпускает администратор сервисной компании (роль `provider_admin`) через
пользовательский API — тем же аккаунтом, которым он работает в боте/Web App:

```
POST /app-api/v1/api-keys
Authorization: Bearer <сессионный токен provider_admin>
X-Organization-Id: <org_...>
Idempotency-Key: <8-128 символов>
Content-Type: application/json

{"name": "Название CRM", "scopes": ["requests:read", "requests:write", "webhooks:manage", "events:read"]}
```

Ответ содержит поле `key` — полный ключ вида `rk_<env>_<prefix>_<secret>`. Он показывается **один
раз**, в БД хранится только его SHA-256 и несекретный префикс (`app/modules/integration/keys.py`).
Потеряли ключ — только `POST /app-api/v1/api-keys/{client_id}/rotate` (выпускает новый, старый
`revoked`).

На demo-стенде ключ для коннектора 1С фиксирован переменной окружения `CONNECTOR_API_KEY` и заводится
сидом демо-данных (`python -m app.demo.seed`) — см. корневой `README.md`.

Все запросы к интеграционному API — `Authorization: Bearer <ключ>`.

## 2. Scopes

Ключ несёт список областей действия; запрос вне выданных областей — `403 FORBIDDEN` с кодом
`INSUFFICIENT_SCOPE` (поле `details.required_scope`). Нужный scope указан у каждой операции
в `integration-api.json` — расширение `x-required-scopes` (пустой список — достаточно любого
действующего ключа, как у `GET /me`).

| Scope | Даёт доступ к |
|---|---|
| `requests:read` | Чтение заявок и назначений (`GET /requests`, `GET /requests/{id}`, история, сообщения) |
| `requests:write` | Действия исполнителя по заявке (принять/отклонить, выезд, смета, начать работу, завершить и т.д.), привязка внешнего номера |
| `marketplace:read` | Чтение биржи внешнего поиска |
| `marketplace:write` | Отклики на бирже |
| `equipment:read` | `GET /equipment` — только оборудование с подтверждённой привязкой к вашей компании, в договорном объёме |
| `service_bindings:read` | `GET /service-bindings` — привязки, включая ожидающие вашего ответа |
| `service_bindings:write` | `POST /service-bindings/{id}/response`, `POST /service-binding-invitations`, `POST /service-binding-invitations/{id}/revoke` |
| `reviews:read` / `reviews:write` | Отзывы и ответы на них |
| `webhooks:manage` | Просмотр и управление подписками на вебхуки этого ключа (список, создание, ротация секрета, тестовая доставка, удаление); подписки других ключей организации не видны |
| `events:read` | Чтение ленты событий (`GET /events`) — независимо от вебхуков, для восстановления |

Выдавайте ключу только то, что реально использует интеграция (принцип минимальных полномочий).

Scope действует и на события: вебхук и элемент ленты `/events` получает только ключ со scope на
чтение соответствующих данных — `requests:read` для событий заявок, `marketplace:read` для
`marketplace.request.*`, `service_bindings:read` для `service_binding.changed`. Отзыв ключа
отключает его подписки; уже поставленные доставки не отправляются.

Ключ выпускается для окружения (`rk_<env>_…`): ключ demo-стенда не принимается рабочим
контуром и наоборот.

## 3. Идемпотентность

Каждый мутирующий запрос (`POST`/`PATCH`/`DELETE`, включая тестовую доставку вебхука) требует заголовок `Idempotency-Key` (8–128 символов).
Повтор с тем же ключом и тем же телом запроса возвращает тот же ответ без повторных побочных
эффектов; тот же ключ с другим телом — `409 IDEMPOTENCY_CONFLICT`. Срок жизни ключа —
`idempotency_ttl_seconds` (по умолчанию 7 дней), после истечения ключ можно переиспользовать.

Рекомендация: формируйте ключ детерминированно от содержимого операции —
`sha256(действие|заявка|поля)`, а не случайным образом на каждый HTTP-запрос — тогда повтор после
сетевого сбоя/таймаута не создаёт дубль (пример реализован в `integration_1c/connector/platform_client.py`,
функция `idempotency_key`, и в `integration_1c/connector/services/outbound.py` — ключ сохраняется
в журнал до вызова и переиспользуется при повторе). Для загрузки файла в отпечаток запроса входит SHA-256 содержимого:
другой файл под тем же ключом — `409 IDEMPOTENCY_CONFLICT`.

Исключение — операции, которые сознательно повторяют: ротация секрета подписки. Каждой ротации
нужен свой ключ; повтор того же ключа секрет повторно не выдаёт
(`409 IDEMPOTENT_SECRET_NOT_REPLAYABLE`).

## 4. Версии и `assignment_id`

Заявка — согласуемый агрегат с полем `version`, которое растёт на каждое изменение. Изменения
заявки и назначения обязательно указывают `expected_version` (без него — `422 VALIDATION_FAILED`);
несовпадение с текущей версией — `409 VERSION_CONFLICT` с `details.current_version`. Необязательно
оно только для сообщений и откликов биржи: публичная карточка биржи версию заявки не раскрывает. Открытая на экране диспетчера карточка должна
быть перечитана (`GET /requests/{id}`) прежде чем повторить действие — так устаревшая форма не
подтверждает уже неактуальные условия (A28).

Активное назначение заявки исполнителю несёт отдельный `assignment_id` — он нужен в теле действий
исполнителя (`accept`, `decline`, `withdraw`, `start-work`, `report-completion`, визиты, сметы).
Берите его из ответа предыдущего запроса (`assignment.id`), не кэшируйте между заявками.

## 5. Подписка на вебхуки

```
POST /api/v1/webhook-subscriptions
Authorization: Bearer <ключ>
Idempotency-Key: <...>
Content-Type: application/json

{"url": "https://crm.example.com/webhooks/platform", "events": []}
```

`events: []` — подписка на все типы событий; можно передать конкретный список
(`request.assigned`, `request.changed`, `message.created`, `offer.selected`, `assignment.revoked`,
`visit_proposal.responded`, `repair_quote.responded`, `cancellation.requested`, `request.closed`,
`service_binding.changed`, `marketplace.request.available`, `marketplace.request.closed`).

Ответ содержит `secret` — тоже отдаётся один раз (при создании и при
`POST /api/v1/webhook-subscriptions/{id}/rotate-secret`), хранится у платформы зашифрованным
(`SECRETS_ENCRYPTION_KEY`, Fernet). `url` должен быть `https` на публичный адрес; `http` и приватные адреса допускаются
только для хостов из `ALLOWED_PRIVATE_WEBHOOK_HOSTS` (не в prod; на demo-стенде — коннектор 1С в сети
compose) — иначе `422` с кодом `VALIDATION_FAILED`.

Проверка канала без ожидания реального события:
`POST /api/v1/webhook-subscriptions/{id}/test` (тело `{"event_type": "ping"}` необязательно) — тип
`ping` есть только в конверте, в ленте `/events` его не будет.

### Конверт события (тело вебхука и элемент `/events`)

```json
{
  "schema_version": "1",
  "event_id": "evt_...",
  "type": "request.assigned",
  "occurred_at": "2026-01-01T10:00:00Z",
  "recipient_organization_id": "org_...",
  "resource_id": "req_...",
  "resource_version": 4,
  "data": { "...": "представление ресурса, разрешённое получателю" }
}
```

### Заголовки доставки

| Заголовок | Значение |
|---|---|
| `X-Event-ID` | Идентификатор события — для дедупликации |
| `X-Delivery-ID` | Новый на каждую попытку доставки того же события |
| `X-Timestamp` | Unix-время подписи (секунды) |
| `X-Signature` | `sha256=<hex>` — HMAC-SHA256 от `"{timestamp}." + raw_body` секретом подписки |

## 6. Проверка подписи

Проверяйте подпись **до** разбора JSON, по сырому телу запроса, с допуском по времени
(например ±300 секунд) — иначе перехваченный и позже воспроизведённый запрос будет принят.

### Python

```python
import hashlib
import hmac
import time

def verify_signature(secret: bytes, timestamp: str, raw_body: bytes, signature: str, *, max_age: int = 300) -> bool:
    if abs(time.time() - int(timestamp)) > max_age:
        return False
    mac = hmac.new(secret, f"{timestamp}.".encode() + raw_body, hashlib.sha256).hexdigest()
    expected = f"sha256={mac}"
    return hmac.compare_digest(expected, signature)

# в обработчике вебхука:
# raw_body = await request.body()  # именно сырые байты, не json.dumps(await request.json())
# ok = verify_signature(secret, request.headers["X-Timestamp"], raw_body, request.headers["X-Signature"])
```

### Node.js

```javascript
const crypto = require("crypto");

function verifySignature(secret, timestamp, rawBody, signature, maxAgeSeconds = 300) {
  if (Math.abs(Date.now() / 1000 - Number(timestamp)) > maxAgeSeconds) return false;
  const mac = crypto
    .createHmac("sha256", secret)
    .update(`${timestamp}.`)
    .update(rawBody) // Buffer сырого тела запроса, не JSON.stringify(req.body)
    .digest("hex");
  const expected = `sha256=${mac}`;
  const a = Buffer.from(expected);
  const b = Buffer.from(signature);
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}
```

## 7. Дедупликация по `event_id`

Платформа повторяет недоставленные события (недоступность CRM, таймаут, 5xx) — обработчик вебхука
обязан быть идемпотентным по `event_id`: сохраните обработанные `event_id` (с TTL) и на повтор
отвечайте `200` без повторного побочного эффекта. Ответ должен быть быстрым — тяжёлую обработку
(скачивание вложений, запись карточки) стоит выносить в фоновую задачу уже после `200 OK`
(см. `integration_1c/connector/webhooks.py`).

## 8. Порядок событий

Порядок доставки не гарантирован. У каждого события ресурса есть `resource_version` (может быть
`null` для событий без версии — например `ping`). Правило: применять событие, только если его
`resource_version` больше уже сохранённой локально версии этого ресурса; более старое — игнорировать
как устаревшее, не как ошибку. При сомнении — перечитать ресурс (`GET /requests/{id}`), это
источник истины, конверт события — лишь сигнал, что стоит сходить и обновить карточку.

## 9. Привязка CRM ID

Собственный номер тикета CRM сохраняется на стороне платформы через:

```
POST /api/v1/requests/{request_id}/external-reference
{"external_id": "CRM-000123", "expected_version": 4}
```

Значение возвращается платформой в дальнейших ответах и **не обязано** быть уникальным для
платформы — уникальность и формат номера полностью на стороне CRM.

## 10. Восстановление через `/events`

`GET /api/v1/events?cursor=<курсор>&limit=<N>` — постраничная лента событий вашей организации в
порядке ленты (`feed_seq`), с полями `events[]`, `next_cursor`, `has_more`. Курсор — непрозрачная
строка, интерпретировать не нужно, только передавать дальше. Используйте после простоя обработчика
или подозрения на пропуск, вместо повторной подписки.

Курсор может устареть (лента хранится `events_retention_days`, по умолчанию 30 дней) —
в этом случае ответ `409 CURSOR_EXPIRED`. Нумерация ленты не сбрасывается после уборки старых
событий: курсор, указывающий на удалённый участок (или «в будущее»), всегда даёт этот ответ. После него нет смысла запрашивать `/events` дальше:
нужна полная сверка через постраничный `GET /requests` (с `updated_since`, если поддерживается) и
переход на текущую позицию ленты с нуля.

## 11. Коды ошибок

Единый формат тела ошибки на всех трёх контурах API:

```json
{"error": {"code": "NOT_FOUND", "message": "Объект не найден", "request_id": "…", "details": {}}}
```

`request_id` совпадает с заголовком ответа `X-Request-ID` — указывайте его при обращении в
поддержку. Основные коды:

| HTTP | `code` | Когда |
|---|---|---|
| 400 | `BAD_REQUEST` | Некорректный запрос общего вида, в том числе тело — не JSON |
| 401 | `API_KEY_INVALID` | Ключ не распознан, отозван или профиль исполнителя неактивен |
| 403 | `FORBIDDEN` / `INSUFFICIENT_SCOPE` | Нет прав / нет нужного scope (`details.required_scope`) |
| 404 | `NOT_FOUND` | Объект не найден либо недоступен — платформа не различает эти случаи для чужих данных |
| 409 | `CONFLICT`, `VERSION_CONFLICT`, `INVALID_TRANSITION`, `IDEMPOTENCY_CONFLICT`, `ASSIGNMENT_ALREADY_ACTIVE`, `CURSOR_EXPIRED` | Конфликт состояния — см. `details` конкретного кода |
| 422 | `VALIDATION_FAILED` | Ошибка проверки полей (`details.field`) |
| 413 / 415 | `FILE_TOO_LARGE` / `UNSUPPORTED_MEDIA_TYPE` | Загрузка вложения: превышен размер / формат не поддерживается |
| 429 | `RATE_LIMITED` | Превышен лимит запросов — см. заголовки ниже и `Retry-After` |
| 503 | `SERVICE_UNAVAILABLE` | Временная недоступность (например, БД) — повторите после `Retry-After` |

## 12. Лимиты

- Частота запросов на ключ — token bucket в процессе api (по умолчанию `10` RPS, всплеск `20`
  запросов; настраивается `INTEGRATION_RATE_LIMIT_RPS`/`INTEGRATION_RATE_LIMIT_BURST`). Ответ 429
  несёт заголовки `RateLimit-Limit`, `RateLimit-Remaining`, `RateLimit-Reset` и `Retry-After`
  (секунды).
- Неудачные попытки аутентификации с одного адреса ограничены отдельно, до проверки ключа
  (`INTEGRATION_AUTH_FAILURE_BURST`, по умолчанию 10, восполнение `INTEGRATION_AUTH_FAILURE_RPS`);
  после исчерпания адрес получает `429`, пока корзина не восполнится.
- Курсорные страницы: `/events` — `limit` до `events_page_max_limit` (по умолчанию 100).
- Доставка вебхука: таймаут `webhook_timeout_seconds` (10 с по умолчанию), повторы с экспоненциальной
  задержкой в окне `webhook_retry_window_seconds` (24 часа), после — доставка помечается
  окончательно неуспешной (видно в `GET /api/v1/webhook-subscriptions`),
  событие остаётся доступным через `/events`.

## 13. Пример основного сценария (curl)

Прямая заявка своему сервису — от получения ключа до принятия (ТЗ, приёмка A04). Значения
`<...>` — из предыдущего ответа.

```bash
BASE=https://<домен-стенда>/api/v1
KEY=rk_demo_...

# 1. Кто я — проверка ключа и его scope
curl -s "$BASE/me" -H "Authorization: Bearer $KEY"

# 2. Список заявок, назначенных сервису
curl -s "$BASE/requests?assignment_state=pending" -H "Authorization: Bearer $KEY"

# 3. Карточка заявки
curl -s "$BASE/requests/<request_id>" -H "Authorization: Bearer $KEY"

# 4. Привязать номер тикета CRM
curl -s -X POST "$BASE/requests/<request_id>/external-reference" \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -H "Idempotency-Key: crm-ext-ref-<request_id>" \
  -d '{"external_id": "CRM-000123"}'

# 5. Принять заявку
curl -s -X POST "$BASE/requests/<request_id>/accept" \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -H "Idempotency-Key: crm-accept-<request_id>" \
  -d '{"assignment_id": "<assignment_id>"}'

# 6. Подписаться на вебхуки (один раз при настройке интеграции)
curl -s -X POST "$BASE/webhook-subscriptions" \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -H "Idempotency-Key: crm-subscribe-1" \
  -d '{"url": "https://crm.example.com/webhooks/platform", "events": []}'
```

Полный рабочий пример на Python — коннектор 1С `integration_1c/` целиком (не фрагмент, а реально
работающий адаптер: подпись, дедупликация, идемпотентность, конфликты версий, восстановление через
`/events`, запись в 1С через OData), см. `docs/architecture/06-1c-integration.md`.

## Ограничения этого руководства

Поля тел запросов/ответов сведены из реализации; при расхождении с `app-api.json`/
`integration-api.json`/`operator-api.json` в этой директории источник истины — файлы схемы
(перегенерируйте их: `uv run python scripts/export_openapi.py` из `backend/`, либо
`python scripts/export_openapi.py` из корня — оба варианта работают).
