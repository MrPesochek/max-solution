# src/ui — каркас и компоненты дизайна

Источник истины — итоговый макет `design/final/Ремонт в MAX - итог.dc.html` и его части
`design/final/part-*.dc.html` (36 экранов, коды 9a–16g), иллюстрации
`design/final/assets/chatti-v11/*.svg`, требования — `design/final/uploads/design-specification.md`,
расхождения с реализацией — `design/final/GAP.md`. Прежний макет (`design/Все экраны.dc.html`,
`design/screens-*.js`, коды D01–D38) устарел.

Компоненты повторяют блоки макета: размеры и шрифты — из разметки экранов, цвета — только через
токены `tokens.css`. Импорт — из `src/ui` (index.ts) или напрямую из файла.

## Визуальный язык

- Шрифт Onest 400–800, моноширинный — IBM Plex Mono 500/600 (ИНН, ключи, вебхуки). Шрифты
  подключены из пакетов `@fontsource/*` в `main.tsx` и отдаются с нашего домена: в MAX действует
  CSP, внешние CDN не используем.
- Белый экран без карточек-подложек: серые заливки `--c` (#F4F5F8) у полей, баннеров сцен,
  вторичных кнопок и чипов; ряды через разделитель `--d` (#ECEDF0); рамка выбора 1.5px `--d`,
  выбранное — 2px `--a`.
- Текст: `--t1` #111, `--t2` #6E7178, `--t3` #9A9DA3, длинный текст `--tb` #3A3D42.
- Акцент #0077FF — только действие и выбранное: кнопка `--a-bg`, наведение `--a-h` #0066DD,
  неактивная `--a-off` #B8D6FF. Выбранный чип и выполненный шаг — инверсия `--inv` (#111), не
  акцент.
- Статусы: ok #E3F5EA/#137A40, y #FFF1DB/#9A5B00, w #F0F1F3/#5F636A, x (отказ, срочно) #C2410C.
- Радиусы: кнопка 16 (высота 54), поле 14 (52), чип 12 (40) или «таблетка» 18 (36), карточка
  выбора 20, баннер сцены 24–28, лист снизу 28.
- Заголовок экрана 30/800 (−1px), корень вкладки 26/800 (−0.8px), секция 17/700, кнопка 17/600,
  текст 15px, подпись поля 13/600.
- Поля экрана 20px (`--ui-gutter`), между блоками 22px (`--ui-gap`).

## Тема

- `tokens.css` — светлая в `:root`, тёмная в `:root[data-theme=dark]`. Тёмной темы в макете нет:
  она выведена из тех же ролей (фон #121316, заливка #1E1F24, линия #26272D, текст #F2F3F5 /
  #A2A5AC / #75787F). Кнопка остаётся #0077FF, акцент-текст светлее (#4C9DFF) ради контраста.
  Файл ставит фон и шрифт на body и сводит переменные MaxUI к токенам.
- `theme/ThemeRoot.tsx` — корень приложения. В MAX тема из bridge (`colorScheme`), вне MAX — выбор
  пользователя: `localStorage['max-repair.theme']` = `system | light | dark`, по умолчанию светлая.
- `useThemePreference()`, `<ThemeSwitcher />` — секция «Оформление»; в MAX не рисуется.
- Иллюстрации нарисованы с белой заливкой, поэтому в тёмной теме лежат на светлой плашке
  `--scene` (#F4F5F8): баннер сцены целиком, остальные рисунки (герой пустого состояния, техника
  в строках и карточках, карточки выбора) — на плашке с радиусом 12. Правило — в `ui.css`,
  отдельный класс компонентам не нужен.

## Каркас экрана

```tsx
<Screen
  title="Заявка № 412"           // шапка 44px: ‹ / заголовок 14px --t2 / ⋯
  back={...}                     // по умолчанию — к родителю маршрута; '/путь' | () => void | false
  onClose={...}                  // ✕ слева (корневые экраны вне вкладок, мастер заявки)
  menu={[{ label, onSelect }]}
  actions={
    <BottomActions layout="row" note="Черновик сохранён">
      <ActionButton kind="s">Отказаться</ActionButton>
      <ActionButton onClick={...} loading={busy}>Согласовать</ActionButton>
    </BottomActions>
  }
>
  <StepProgress current={2} total={3} />
  <SceneBanner name="status-price" height={130} />
  <PageTitle subtitle="ХолодСервис · версия 2">Цена ремонта</PageTitle>
  ...
</Screen>
```

- В MAX ‹ и ✕ не рисуются: «назад» уходит в `BackButton` MAX. ⋯ с пунктами `menu` остаётся и в MAX —
  своего меню действий у клиента нет. Уход с экрана ждёт `FlowExitGuard`.
- Пока экран не на `Screen`, MainLayout рисует временную шапку (`data-chrome=legacy`).
- Нижнее меню (`TabBar`) — на корнях вкладок. Заказчик: Главная `/`, Заявки `/requests`,
  Техника `/equipment`, Организация `/organization`. Исполнитель: Заявки `/provider/requests`
  (хаб 11a; пока ведёт на `/provider/incoming`, а `/provider/incoming|available|in-work` — его
  вкладки с `ProviderRequestsSegments`), Чаты `/provider/chats`, Профиль `/provider/profile`,
  CRM `/integration` — только `provider_admin` (`TabDef.visible`). «Назад» по умолчанию —
  `parentPathOf()` в `layout/layoutContext.ts`; новый маршрут — добавьте туда правило.
- `BottomActions` липнет к низу (над меню), `layout="row"` — две кнопки поровну.
- `HeaderBar` — только разметка шапки, для экранов вне роутера.

## Блоки макета → компоненты

| Блок макета | Где в макете | Компонент |
|---|---|---|
| Шапка 44px с ‹ или ✕ | все | `Screen` / `ScreenHeader` / `HeaderBar` |
| Полоски шагов мастера | 10b, 15a, 15b | `StepProgress` (`current`, `total`) |
| Баннер сцены: серый блок, иллюстрация снизу | 9a, 10c, 10d, 12b, 14c, 15d, 15e | `SceneBanner` (`name`, `height`, `width`, `align`) |
| Иллюстрация | везде | `Illustration` (`name`, `width`), `illustrationUrl()`, `ILLUSTRATIONS` |
| Иллюстрация техники по категории | 13a, 15c, 10a | `EquipmentIcon` (`code`, `name`, `width`), `equipmentIllustration()` |
| Заголовок 30/26 + подзаголовок, «СРОЧНО · СЕГОДНЯ» | все | `PageTitle` (`size` l/m, `subtitle`, `eyebrow`, `eyebrowTone`) |
| Шапка корня вкладки: подпись, заголовок 26/800, действие справа | 11a, 15c, 15f | `WorkspaceHeader` (`eyebrow`, `title`, `subtitle`, `side`) |
| Баннер сцены + крупный статус, окно выезда акцентом | 9a, 14d, 15d | `CardHero` (`scene`, `title`, `accent`, `text`, `note`, `size` xl/l/m) |
| Заголовок секции + «Все 6» / «Добавить» | 10a, 12c, 11c | `SectionCaption` (`action`, `large`) |
| Ряды с разделителями | 10a, 13a, 12c, 15c | `List` (`variant` plain/card) + `ListRow` (`media`, `icon`, `control`…) |
| «Ключ — значение», смета с итогом | 12b, 13b, 14d, 15h, 10d, 16d | `KeyValueRows` (`rows`, `variant` info/items, `total`) |
| Карточка выбора с радио | 12a, 10c, 14a, 15a, 16b | `ChoiceCard` в `ChoiceGroup` |
| Переключатель 40×24 | 12d, 11a, 15f | `Toggle` (`pill`, `size`), в строке — `ListRow control switch` |
| Чекбокс / радио 24px | 12b, 10c, 15g | `CheckMark`, `Radio` (`variant` check/dot) |
| Сегменты / вкладки экрана | 10a, 13a, 13b, 11a | `Segmented` (`mode`, `size` m/s, `count`), `SegmentTabs` |
| Чипы: симптомы, слоты, фильтр точек, быстрые ответы | 10b, 11b, 15f, 13a, 13c | `Chip` (`variant` fill/outline, `size`), `Chips` (`scroll`), `ChipGroup`, `FilterChip` |
| Поле, textarea | 16a, 15h, 14b | `TextField`, `TextAreaField`, `SelectField`, `PhoneField`; моноширинное — `className="ui-field__control--mono"` |
| Фото-плитки | 10b, 11b, 11d, 15f | `PhotoGrid` (`columns` 3/4) + `PhotoTile` |
| Шаги хода работ, проверки, жалобы | 15e, 14c, 15g | `Stepper` (`steps`, `variant` marks/dots) |
| История событий | 15d, 13b | `EventTimeline` (`events`, `variant` dot/date, `collapsible`) |
| Оценка звёздами | 11d | `StarRating` (`captions`, `size`); `Stars` — прежнее имя |
| Аватар с инициалами | 9a, 12c, 13c, 11c, 14a | `Avatar` (`name`, `size`, `square`, `gradient` n/a) |
| Тег «★ 4,9», «Новый», «Срочно» | 10c, 15g | `Tag` (`tone` ok/y/w/a/x) |
| Цена крупно | 10d | `PriceBlock` или `KeyValueRows total` |
| Серый блок с текстом | 15g, 16g | `TextCard`, `Banner` (`tone`) |
| Пузырь переписки | 13c, 16g | `MessageBubble` (`mine`) |
| Пустое состояние / ошибка / нет доступа | 13d, 16e | `StatusHero` (`illustration`), `EmptyState`, `ErrorState`, `NoAccessState` |
| Скелетон | 16f | `SkeletonRows`, `SkeletonBlock`; `components/states/Skeleton` |
| Лист снизу | 16d | `Sheet`, `ConfirmDialog` / `useConfirm` |
| Нижнее меню | 10a, 13a, 11a | `TabBar` |
| Кнопки 54px | все | `ActionButton` (`kind` p/s/d/g/i, `compact`, `loading`, `to`, `href`) |

`ListRow`: `title`, `subtitle` (+`subtitleTone` error/accent), `media` (иллюстрация 52px),
`icon`+`gradient` (аватар), `marker` ok/x/w/-, `tag`, `value` (+`valueTone` strong/accent/secondary),
`oldValue`, `count`, `chevron`, `action` accent/danger, `control` `{type:'checkbox'|'radio'|'switch',
checked}` + `onToggle`, `to`/`href`/`onClick`, `expanded`, `loading`, `disabled`. Группа радио —
`<List role="radiogroup" aria-label=...>`.

Статус заявки → иллюстрация сцены: `requestStatusIllustration()` в `lib/status.ts`.
Прочее: `format.ts` — `requestNo`, `shortDateTime`, `visitWindowShort`, `relativeDay`.

## Строки

`strings/ru.ts` собирает прежний объект `strings` из разделов `strings/ru/<раздел>.ts`: common,
nav, onboarding, organization, requests (главная, мастер, список), card (карточка, предложения,
согласования; `requestsCard` входит в `strings.requests`), equipment, bindings, provider,
integration, reviews, operator. Импорты `strings` не меняются; новые строки — в файл своего раздела.

## Коды экранов макета

| Коды | Часть | Экраны |
|---|---|---|
| 9a | part-card | карточка заявки |
| 10a–10d | part-customer | главная, новая заявка шаг 2, предложения, согласование цены |
| 11a–11d | part-provider | рабочее место исполнителя, отклик, публичный профиль, отзыв |
| 12a–12d | part-entry | вход, подключение сервиса, организация, интеграция CRM |
| 13a–13d | part-requests | мои заявки, карточка техники, чат, ошибки и пустые состояния |
| 14a–14d | part-other | выбор организации, добавление техники, проверка исполнителя, приёмка |
| 15a–15h | part-extra | новая заявка шаги 1 и 3, техника, состояния карточки, ход работ, настройки профиля, жалоба, привязка по договору |
| 16a–16g | part-reg | регистрация заказчика и исполнителя, приглашение, конфликт версий, нет доступа, загрузка, уточнение из CRM |

## Как перевести экран

1. Найдите экран в `design/final/part-*.dc.html` по id (`<div id="10d">`); данные состояний — в
   `renderVals()` скрипта части, соответствие маршрутам — в `design/final/GAP.md`.
2. Соберите его из `Screen` и блоков сверху вниз. Тексты — в свой `strings/ru/<раздел>.ts`,
   данные — из хуков `api/hooks/*` (слой API не меняется).
3. Старые куски временно оборачивайте в `<div className="ui-pad">`.
4. Поправьте тесты своего пакета, сохраняя проверяемое поведение.
5. Удалите из `styles/app.css` классы, которые больше не используются.

## Витрина и скриншоты

`#/__ui` — витрина (только dev и сборка с моками): рамки `9a` и `kit` собраны из новых блоков,
рамки D… — прежние экраны на новых токенах (проверка старых API). Снимки приложения —
`scratchpad/shots` (`node shots.mjs app --route /__ui/kit --both-themes`); макет открывается в
браузере файлом `design/final/Ремонт в MAX - итог.dc.html`.

Отличия от макета, заданные устройством: статус-бар 9:41 и скругления рамки; внизу вместо
домашнего индикатора — safe-area; ✕ и ⋯ в MAX рисует клиент.
