# Мини-приложение MAX

Интерфейс заказчика, исполнителя и оператора на React, TypeScript и `@maxhub/max-ui`. Данные приходят из `/app-api/v1` и `/operator-api/v1`.

## Разработка

Из каталога `webapp`:

```bash
pnpm install --frozen-lockfile
pnpm dev
```

Vite проксирует запросы к API на `http://localhost:8000`. Для работы без бэкенда включите MSW:

```bash
VITE_USE_MOCKS=true VITE_DEMO_LOGIN=true pnpm dev
```

В этом режиме можно выбрать роль на стартовом экране. Данные моков сбрасываются после перезагрузки. Для проверки регистрации есть пользователь `new_user`, а для разных состояний исполнителя доступны профили с черновиком, активным статусом и приостановленным доступом.

При обычной работе пользователь входит через MAX или одноразовую ссылку из бота. Токен сессии хранится только в памяти вкладки. После перезагрузки вкладки, открытой по одноразовой ссылке, понадобится новая ссылка.

## Структура

| Каталог | Содержимое |
|---|---|
| `src/screens/` | Экраны приложения |
| `src/ui/` | Компоненты, стили и темы |
| `src/api/` | HTTP-клиент, типы и React Query |
| `src/session/` | Вход и выбор организации |
| `src/max/` | Bridge MAX и обработка начального маршрута |
| `src/mocks/` | MSW и тестовые данные |
| `src/test/` | Тесты пользовательских сценариев |

## Проверки и сборка

```bash
pnpm lint
pnpm typecheck
pnpm test --run
pnpm build
```

Готовая сборка находится в `dist/`. Производственный Dockerfile удаляет карты исходников. Если моки выключены, service worker MSW в сборку не попадает.

## Типы API

Типы `src/api/schema.d.ts` и `src/api/operatorSchema.d.ts` создаются из OpenAPI. Их не нужно редактировать вручную. Из корня репозитория:

```bash
(cd backend && uv run python ../scripts/export_openapi.py)
cp openapi/app-api.json openapi/operator-api.json webapp/openapi/
(cd webapp && pnpm gen:api)
```

Параметры сборки и подключения MAX описаны в [основном README](../README.md) и [инструкции развёртывания](../docs/deploy.md).
