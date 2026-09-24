GREETING_NEW = (
    "Здравствуйте! Здесь можно вызвать мастера на оборудование и следить за заявками.\n"
    "Начните с организации: создайте свою или примите приглашение."
)
HELP = (
    "Команды:\n"
    "/start — главное меню\n"
    "/help — эта справка\n"
    "/cancel — отменить текущий шаг\n"
    "Основные действия доступны кнопками, а списки и карточки — в мини-приложении."
)

MENU_HEADER_NO_ORG = "Организация не выбрана"
PERSONAL_ONLY = "Работаю только в личных сообщениях"
MENU_HEADER = "Организация: {name}"
MENU_SIDE = "Вы действуете как: {side}"
MENU_PROMPT = "Выберите раздел:"
SECTION_LATER = "Раздел появится позже."
OPEN_WEBAPP = "Открыть приложение"
LOGIN_LINK_READY = (
    "Ссылка для входа в приложение. Она одноразовая и действует {minutes} мин — "
    "не пересылайте её. Нужна новая — нажмите кнопку открытия приложения ещё раз."
)
LOGIN_LINK_BUTTON = "Войти в приложение"
LOGIN_LINK_UNAVAILABLE = "Вход в приложение сейчас недоступен. Продолжите в чате."

CANCELLED = "Отменено."
NOTHING_TO_CANCEL = "Сейчас нечего отменять."
UNKNOWN_INPUT = "Не понял. Откройте меню командой /start."
DIALOG_EXPIRED = "Диалог долго был без ответа и закрыт. Начните заново: /start."
ACTION_OUTDATED = "Действие устарело."
ROLE_UNAVAILABLE = "Роль, от имени которой пришла кнопка, сейчас недоступна."
TRY_AGAIN = "Не получилось. Попробуйте ещё раз позже."

BUTTON_BACK = "Назад"
BUTTON_CANCEL = "Отмена"
BUTTON_SKIP = "Пропустить"
BUTTON_MORE = "Ещё"
BUTTON_PREV = "Предыдущие"


NO_ORG_PROMPT = "У вас пока нет организации."
CREATE_CUSTOMER = "Я заказчик"
CREATE_PROVIDER = "Я исполнитель"
CHOOSE_ORG = "Выберите активную организацию:"
MEMBERSHIP_PENDING = "Доступ ещё не подтверждён администратором организации."
CHANGE_ORG = "Сменить организацию"
ORG_SWITCHED = "Активная организация: {name}"

ASK_ORG_NAME = "Как называется организация?"
ASK_ORG_NAME_AGAIN = "Название не может быть пустым. Введите название."
ASK_PHONE = "Контактный телефон для обращений? Можно отправить свой контакт кнопкой."
ASK_PHONE_AGAIN = "Нужен телефон. Отправьте контакт или введите номер."
SHARE_CONTACT = "Отправить мой контакт"
ASK_CITY = "Город первой точки:"
ASK_DISTRICT = "Район:"
NO_DISTRICT = "Без района"
ASK_ADDRESS = "Адрес точки (улица, дом):"
ASK_ADDRESS_AGAIN = "Нужен адрес. Введите его текстом."
NO_CITIES = "Справочник городов пуст. Обратитесь в поддержку."

ORG_CREATED_CUSTOMER = "Организация «{name}» создана, первая точка добавлена."
ORG_CREATED_PROVIDER = (
    "Организация «{name}» создана. Заполним профиль исполнителя для проверки — это несколько шагов."
)

ORG_SUMMARY = "Организация: {name}\nТип: {kinds}\nТелефон: {phone}\nРеквизиты: {details}"
ORG_KIND_CUSTOMER = "заказчик"
ORG_KIND_PROVIDER = "исполнитель"
ORG_NO_PHONE = "не указан"
ORG_MANAGE = "Управлять организацией"


INVITATION_PREVIEW = "Приглашение в «{organization}»{role}.\nПодтвердите, чтобы присоединиться."
INVITATION_ROLE = ", роль: {role}"
INVITATION_ACCEPT = "Принять"
INVITATION_ACCEPTED = "Вы присоединились к «{organization}»."
INVITATION_PENDING = "Заявка отправлена: администратор «{organization}» подтвердит доступ."
INVITATION_UNKNOWN = "Приглашение недействительно."
INVITATION_EXPIRED = "Срок действия приглашения истёк. Попросите новое."
INVITATION_USED = "Приглашение уже использовано."
INVITATION_REVOKED = "Приглашение отозвано."

ROLE_TITLES = {
    "customer_manager": "руководитель",
    "customer_employee": "сотрудник",
    "provider_admin": "администратор",
    "provider_dispatcher": "диспетчер",
}


NO_ORGANIZATION = "Сначала нужна организация. Откройте /start."
NOT_CUSTOMER_SIDE = "Раздел доступен только стороне заказчика."
NOT_PROVIDER_SIDE = "Раздел доступен только стороне исполнителя."
NO_LOCATIONS = "У организации пока нет точек. Добавьте точку в приложении."
NO_EQUIPMENT = "На этой точке пока нет оборудования. Добавьте оборудование в приложении."
ASK_LOCATION = "Точка:"
ASK_EQUIPMENT = "Оборудование:"
EQUIPMENT_CARD = "Оборудование: {title}\nТочка: {location}\nАдрес: {address}\nСервис: {service}"
NO_CONFIRMED_BINDING = (
    "Подтверждённой привязки к сервису у этого оборудования нет.\n"
    "Можно поискать исполнителя во внешнем поиске."
)
BINDING_KNOWN_SERVICE = "{name} (привязка подтверждена)"
BINDING_UNKNOWN = "не назначен"
GO_FIND_PROVIDER = "Найти исполнителя"

RESUME_DRAFT_FOUND = "У вас есть незавершённая заявка №{number}. Продолжить её?"
RESUME_CONTINUE = "Продолжить"
RESUME_RESTART = "Начать заново"
RESUME_RESTARTED = "Черновик отменён, начинаем заново."

ASK_SYMPTOMS = "Опишите неисправность:"
ASK_SYMPTOMS_AGAIN = "Нужно короткое описание неисправности."
ASK_ERROR_CODE = "Код ошибки на экране, если есть:"
BUTTON_NO_ERROR_CODE = "Кода нет"

ASK_URGENCY = "Насколько срочно?"
URGENCY_CRITICAL = "Критично: оборудование стоит"
URGENCY_URGENT = "Срочно: нужно сегодня"
URGENCY_NORMAL = "Обычная заявка"

URGENCY_LABELS = {
    "critical": "критично",
    "urgent": "срочно",
    "normal": "обычная",
}

PHOTO_SLOT_PROMPT = "Фото «{label}»{required}. Пришлите фото сообщением."
PHOTO_SLOT_REQUIRED = " (обязательно)"
PHOTO_SLOT_OPTIONAL = ""
BUTTON_CANT_PHOTO = "Не могу сделать фото"
ASK_PHOTO_REASON = "Почему не получится сделать фото?"
PHOTO_SAVED = "Фото «{label}» сохранено."
PHOTO_FAILED = "Не удалось сохранить фото «{label}», попробуйте другое или нажмите «Пропустить»."
PHOTO_SKIPPED_INCOMPLETE = "Отмечено: фото «{label}» не будет приложено."
PHOTOS_DONE_INCOMPLETE = "Не хватает части фото — заявку можно отправить с пометкой об этом."

REVIEW_TITLE = "Проверьте заявку №{number}"
REVIEW_RECIPIENT = "Получатель: {recipient}"
REVIEW_EQUIPMENT = "Оборудование: {title}"
REVIEW_SYMPTOMS = "Неисправность: {symptoms}"
REVIEW_ERROR_CODE = "Код ошибки: {code}"
REVIEW_URGENCY = "Срочность: {urgency}"
REVIEW_PHOTOS = "Фото: {count}"
REVIEW_INCOMPLETE = "Не все фото приложены: {reason}"
RECIPIENT_OWN_SERVICE = "ваш сервис"
RECIPIENT_MANAGER = "руководитель на согласование"
RECIPIENT_PUBLICATION = "публикация для исполнителей"
BUTTON_SEND = "Отправить"

DRAFT_SUBMITTED_OWN = "Заявка №{number} отправлена вашему сервису."
DRAFT_SUBMITTED_APPROVAL = "Заявка №{number} отправлена руководителю на согласование."
DRAFT_ALREADY_SUBMITTED = "Заявка уже отправлена."

APPROVAL_SEND = "Отправить руководителю на согласование"

PUBLISH_PREVIEW_TITLE = "Что увидят исполнители по заявке №{number}:"
PUBLISH_PREVIEW_HIDDEN = "Не раскрывается: {fields}"
PUBLISH_PREVIEW_MATCHED = "Подходящих исполнителей: {count}"
PUBLISH_PREVIEW_BINDING = "Есть свой сервис: {name}. Можно отправить туда вместо публикации."
PUBLIC_CARD_CATEGORY = "Категория: {category}"
PUBLIC_CARD_EQUIPMENT = "Оборудование: {equipment}"
PUBLIC_CARD_PLACE = "Где: {place}"
PUBLIC_CARD_URGENCY = "Срочность: {urgency}"
PUBLIC_CARD_DESCRIPTION = "Описание: {description}"
PUBLISH_PHOTOS_CHOSEN = "Публикуются фото: {photos}"
PUBLISH_PHOTOS_NONE = "Фото не публикуются."
BUTTON_PHOTOS_NONE = "Без фото"
BUTTON_PHOTOS_PLAIN = "Все фото, кроме шильдика"
BUTTON_CHANGE_DISTRICT = "Изменить район"
ASK_PUBLISH_DISTRICT = "В каком районе искать исполнителя?"
DISTRICT_AS_LOCATION = "Как у точки"
ONLY_MANAGER_CAN_PUBLISH = "Публиковать заявку во внешнем поиске может только руководитель."
PUBLISH_PHOTOS_TITLE = "Фото для публикации (нажмите, чтобы включить/выключить):"
PUBLISH_PHOTO_ON = "✅ {label}"
PUBLISH_PHOTO_OFF = "☐ {label}"
PUBLISH_SENSITIVE_TITLE = "Чувствительные фото (шильдик, документы):"
PUBLISH_SENSITIVE_ON = "✅ {label} (виден серийный номер)"
PUBLISH_SENSITIVE_OFF = "☐ {label} (виден серийный номер)"
PUBLISH_SENSITIVE_NOTE = "Публикуются только после явного подтверждения ниже."
PUBLISH_SENSITIVE_CONFIRM_ASK = (
    "На фото может быть серийный номер оборудования. Опубликовать его во внешнем поиске?"
)
BUTTON_CONFIRM_SENSITIVE = "Да, опубликовать"
BUTTON_KEEP_SENSITIVE_HIDDEN = "Не публиковать"
BUTTON_REVIEW_PUBLICATION = "Что увидят исполнители"
BUTTON_PUBLISH = "Опубликовать"
PUBLISH_DONE = "Заявка опубликована. Подходящих исполнителей: {count}."
PUBLISH_NO_PROVIDERS = (
    "Подходящих исполнителей не нашлось. Заявка осталась в статусе «нужно решение»: "
    "можно повторить поиск в другом районе или отменить заявку."
)

BUTTON_CANCEL_DRAFT = "Отменить черновик"
DRAFT_CANCELLED = "Черновик отменён."


REQUESTS_EMPTY = "Заявок нет."
REQUESTS_TAB_ACTIVE = "Активные"
REQUESTS_TAB_DONE = "Завершённые"
REQUEST_LIST_ITEM = "№{number} · {status} · {title}"
REQUEST_CARD_HEADER = "Заявка №{number}"
REQUEST_CARD_STATUS = "Статус: {status}"
REQUEST_CARD_WAITING = "Ждём: {who}"
REQUEST_CARD_PROVIDER = "Исполнитель: {name}"
REQUEST_CARD_PROVIDER_UNKNOWN = "исполнитель ещё не назначен"
REQUEST_CARD_VISIT = "Выезд: {window}"
REQUEST_CARD_VISIT_UNKNOWN = "время не согласовано"
REQUEST_CARD_DELIVERED = "Заявка передана исполнителю"
REQUEST_CARD_ACCEPTED = "Исполнитель принял заявку"
REQUEST_CARD_SCHEDULED = "Выезд согласован"
REQUEST_CARD_QUOTE = "Смета согласована: {price}"
REQUEST_CARD_DECISION_NEEDED = "Исполнитель не назначен — выберите, как искать дальше."
REQUEST_CARD_REASON = "Причина: {reason}"
BUTTON_OPEN_IN_APP = "Открыть в приложении"
BUTTON_OFFERS = "Предложения"
BUTTON_CANCEL_REQUEST = "Отменить или сменить исполнителя"
BUTTON_TO_MENU = "В меню"


STATUS_LABELS = {
    "draft": "черновик",
    "approval_required": "ждём согласования руководителя",
    "awaiting_provider": "ждём ответа сервиса",
    "searching": "ищем исполнителя",
    "awaiting_assignment_confirmation": "ждём подтверждения исполнителя",
    "accepted": "принята исполнителем",
    "scheduled": "выезд согласован",
    "in_progress": "работа идёт",
    "completion_reported": "ждём вашего подтверждения",
    "closed": "завершена",
    "action_required": "нужно решение",
    "cancellation_pending": "решается отмена",
    "cancelled": "отменена",
}

REQUEST_CARD_WAITING_UNTIL = "Ждём подтверждения исполнителя до {deadline}."

WAITING_FOR = {
    "draft": "заполните и отправьте заявку",
    "approval_required": "руководителя",
    "awaiting_provider": "ваш сервис",
    "searching": "отклики исполнителей",
    "awaiting_assignment_confirmation": "подтверждение исполнителя",
    "accepted": "предложение по выезду",
    "scheduled": "выезд по согласованному времени",
    "in_progress": "завершение работ",
    "completion_reported": "ваше подтверждение результата",
    "action_required": "ваше решение",
    "cancellation_pending": "ответ по отмене",
}


VISIT_PROPOSAL_TITLE = "Условия выезда по заявке №{number} (версия {version})"
VISIT_PROPOSAL_WINDOW = "Время: {window}"
VISIT_PROPOSAL_PRICE = "Стоимость выезда: {price}"
VISIT_PROPOSAL_SCOPE = "Состав работ: {scope}"
VISIT_PROPOSAL_VALID = "Действует до: {valid_until}"
BUTTON_APPROVE = "Согласовать"
BUTTON_REJECT = "Отклонить"
VISIT_PROPOSAL_APPROVED = "Выезд согласован."
VISIT_PROPOSAL_REJECTED = "Условия отклонены."

REPAIR_QUOTE_TITLE = "Смета ремонта по заявке №{number} (версия {version})"
REPAIR_QUOTE_SCOPE = "Состав работ: {scope}"
REPAIR_QUOTE_PRICE = "Стоимость: {price}"
REPAIR_QUOTE_VALID = "Действует до: {valid_until}"
REPAIR_QUOTE_APPROVED = "Смета согласована."
REPAIR_QUOTE_REJECTED = "Смета отклонена."

BUTTON_APPROVE_VISIT = "Согласовать выезд (версия {version})"
BUTTON_REJECT_VISIT = "Отклонить выезд"
BUTTON_APPROVE_QUOTE = "Согласовать смету (версия {version})"
BUTTON_REJECT_QUOTE = "Отклонить смету"
APPROVAL_BY_MANAGER = "Согласует руководитель организации."
TERMS_CHANGED = "Условия изменились — вот актуальные."

VAT_LABELS = {
    "included": "НДС включён",
    "excluded": "без учёта НДС",
    "not_applicable": "НДС не облагается",
}

NOT_MANAGER_FOR_APPROVAL = "Согласовывать условия может только руководитель."
ONLY_MANAGER_CAN_SELECT = "Выбирать исполнителя может только руководитель."


BUTTON_CONFIRM_DONE = "Подтвердить"
BUTTON_PROBLEM_REMAINS = "Проблема осталась"
COMPLETION_REPORTED_TEXT = (
    "Исполнитель сообщил о завершении работ ({outcome}). Подтвердите результат."
)
OUTCOME_RESOLVED = "проблема решена"
OUTCOME_NOT_RESOLVED = "проблема не решена"
CONFIRM_DONE_TEXT = "Спасибо, заявка закрыта."
ASK_PROBLEM_REASON = "Опишите, что осталось не так:"
PROBLEM_REPORTED = "Сообщение передано исполнителю, заявка возвращена в работу."


ASK_CANCEL_TARGET = "Что сделать с заявкой?"
CHANGE_PROVIDER_DONE = "Назначение снято. Выберите, как искать исполнителя дальше."
CANCEL_TARGET_STOP = "Отменить совсем"
CANCEL_TARGET_CHANGE = "Сменить исполнителя"
ASK_CANCEL_REASON = "Укажите причину (можно коротко):"
CANCEL_DONE = "Заявка отменена."
CANCEL_REQUESTED = "Запрос на отмену отправлен исполнителю."
CANCEL_WITHDRAW = "Отозвать запрос отмены"
CANCEL_WITHDRAWN = "Запрос отмены отозван."
ASK_DISPUTE_REASON = (
    "Почему вы не согласны с отменой? Причину увидят заказчик и оператор при согласовании."
)
CANCEL_DISPUTE_SENT = "Несогласие с отменой отправлено заказчику."
CANCEL_FORCE = "Прекратить в одностороннем порядке"
CANCEL_FORCED = "Заявка прекращена в одностороннем порядке."


BUTTON_REVOKE_ASSIGNMENT = "Отозвать у сервиса и сменить маршрут"
ASK_REVOKE_REASON = "Почему отзываете заявку у сервиса?"
ASSIGNMENT_REVOKED = "Заявка отозвана у сервиса."
BUTTON_EXTERNAL_SEARCH = "Искать во внешнем поиске"
BUTTON_REPEAT_SEARCH = "Повторить поиск"
BUTTON_RESEND_OWN = "Отправить своему сервису"
BUTTON_RETURN_TO_DRAFT = "Вернуть на доработку"
ASK_RETURN_COMMENT = "Что доработать? Комментарий увидит автор заявки."
RETURNED_TO_DRAFT = "Заявка возвращена автору на доработку."
BUTTON_FOLLOWUP = "Новая заявка по этому оборудованию"
FOLLOWUP_CREATED = "Создан черновик №{number}, связанный с прежней заявкой."


BUTTON_CHANGE_TERMS = "Изменить условия"
DETAILS_TITLE = "Условия заявки №{number}"
DETAILS_DISTRICT = "Район поиска: {district}"
DETAILS_HINT = "Выберите, что изменить. Отправленная заявка и оборудование не переписываются."
DETAILS_CHANGED = "Проверьте изменения и нажмите «Сохранить»."
BUTTON_DETAILS_DESCRIPTION = "Описание"
BUTTON_DETAILS_URGENCY = "Срочность"
BUTTON_DETAILS_SAVE = "Сохранить"
ASK_DETAILS_DESCRIPTION = "Опишите неисправность заново:"
DETAILS_SAVED = "Условия заявки обновлены."


ASK_REPLY = "Введите ответ (текстом или фото) по заявке №{number}:"
REPLY_SENT = "Ответ отправлен."
BUTTON_REPLY = "Ответить"


INBOX_EMPTY = "Новых заявок нет."
INBOX_ITEM = "№{number} · {title} · {urgency}"
BUTTON_ACCEPT = "Принять"
BUTTON_DECLINE = "Отклонить"
BUTTON_ASK_QUESTION = "Задать вопрос"
ASK_DECLINE_REASON = "Причина отказа:"
ASSIGNMENT_ACCEPTED = "Заявка принята в работу."
ASSIGNMENT_DECLINED = "Заявка отклонена."

OFFERS_EMPTY = "Активных предложений пока нет."
OFFER_TITLE = "Предложение: {name} (версия {version})"
OFFER_PROVIDER_UNKNOWN = "исполнитель"
BUTTON_SELECT_OFFER = "Выбрать это предложение"
OFFER_CONFIRM_ASK = "Выбрать исполнителя на этих условиях?"
BUTTON_CONFIRM_OFFER = "Подтвердить выбор"
OFFER_SELECTED = "Исполнитель выбран, ждём подтверждения."


MARKETPLACE_EMPTY = "Сейчас нет доступных заявок."
MARKETPLACE_ITEM = "№{number} · {category} · {urgency}"
MARKETPLACE_EQUIPMENT = "Оборудование: {title}"
MARKETPLACE_PLACE = "Район: {place}"
MARKETPLACE_DESCRIPTION = "Описание: {text}"
MARKETPLACE_PHOTOS = "Фото: {count} — смотрите в приложении"
ASK_MARKET_QUESTION = (
    "Вопрос заказчику по заявке №{number}. Его увидит только заказчик, "
    "адрес и контакты до выбора исполнителя не раскрываются:"
)
MARKET_QUESTION_SENT = "Вопрос отправлен заказчику."
BUTTON_RESPOND = "Откликнуться"
LOCAL_TIME_HINT = "Время — по местному времени точки ({tz})."
OFFER_ASK_DAY = "На какой день предложить выезд?"
OFFER_ASK_SLOT = "Время:"
OFFER_SLOT_MORNING = "Утро (9:00–13:00)"
OFFER_SLOT_DAY = "День (13:00–17:00)"
OFFER_SLOT_EVENING = "Вечер (17:00–21:00)"
OFFER_ASK_PRICE_MODE = "Стоимость выезда:"
OFFER_PRICE_SUM = "Назову сумму"
OFFER_PRICE_LATER = "Уточню после осмотра"
OFFER_PRICE_FREE = "Бесплатно"
ASK_RUBLES = "Сумма в рублях:"
ASK_RUBLES_AGAIN = (
    "Введите сумму числом больше нуля, например 1500 или 1500,50. "
    "Бесплатный выезд — кнопкой «Бесплатно»."
)
ASK_FREE_REASON = "Основание бесплатного выезда:"
ASK_OFFER_SCOPE = "Что входит в выезд:"
OFFER_SUBMITTED = "Предложение отправлено заказчику."
BUTTON_WITHDRAW_OFFER = "Отозвать предложение"
OFFER_WITHDRAWN = "Предложение отозвано."


IN_PROGRESS_EMPTY = "Сейчас нет заявок в работе."
BUTTON_PROPOSE_VISIT = "Предложить выезд"
BUTTON_REPAIR_QUOTE = "Смета ремонта"
BUTTON_START_WORK = "Начать работу"
BUTTON_REPORT_DONE = "Сообщить результат"
BUTTON_WARRANTY = "Гарантийный случай?"
WARRANTY_YES = "Да, по гарантии"
WARRANTY_NO = "Нет, платно"
WARRANTY_UNDETERMINED = "Пока не ясно"
WARRANTY_SAVED = "Отмечено."
ASK_WARRANTY_COMMENT = "Решение: {decision}. Поясните его — пояснение увидит заказчик:"
ASK_COMMENT_AGAIN = "Нужен текст пояснения."
BUTTON_EN_ROUTE = "Выехал"
EN_ROUTE_MARKED = "Отмечено: мастер выехал, заказчик уведомлён."
WORK_CARD_EN_ROUTE = "Мастер выехал."
WORK_CARD_COMPLETION_REPORTED = "Результат отправлен, ждём подтверждения заказчика."
ASK_QUOTE_SCOPE = "Опишите состав ремонта:"
QUOTE_ASK_PRICE_MODE = "Стоимость ремонта:"
WORK_CARD_HEADER = "№{number} · {status}"
WORK_CARD_ADDRESS = "Адрес: {address}"
WORK_CARD_FIELD_WORKER = "Выездной мастер: {name}"
WORK_CARD_WARRANTY = "Гарантия: {decision}"
WORK_CARD_CANCEL_REQUESTED = "Заказчик просит отменить заявку: {reason}"
WARRANTY_LABELS = {
    "warranty": "гарантийный случай",
    "not_warranty": "не гарантийный",
    "undetermined": "пока не ясно",
}
BUTTON_ACCEPT_CANCELLATION = "Принять отмену"
BUTTON_DISPUTE_CANCELLATION = "Не согласен"
BUTTON_WITHDRAW_ASSIGNMENT = "Отказаться от заявки"
ASK_WITHDRAW_REASON = "Почему отказываетесь? Причину увидит заказчик."
ASSIGNMENT_WITHDRAWN = "Вы отказались от заявки, заказчик уведомлён."
BUTTON_FIELD_WORKER = "Назначить мастера"
ASK_FIELD_WORKER = "Кто поедет на выезд?"
BUTTON_WORKER_BY_NAME = "Мастер не в списке — ввести имя"
ASK_FIELD_WORKER_NAME = "Имя мастера:"
ASK_FIELD_WORKER_PHONE = "Телефон мастера для заказчика:"
BUTTON_NO_PHONE = "Без телефона"
FIELD_WORKER_SET = "Выездной мастер назначен, заказчик уведомлён."
VISIT_PROPOSED = "Условия выезда отправлены заказчику."
QUOTE_CREATED = "Смета отправлена заказчику."
WORK_STARTED = "Работа начата."
ASK_OUTCOME = "Результат работ:"
OUTCOME_BUTTON_RESOLVED = "Проблема решена"
OUTCOME_BUTTON_NOT_RESOLVED = "Проблема не решена"
ASK_SUMMARY = "Кратко опишите результат:"
COMPLETION_SENT = "Результат передан заказчику."


EQUIPMENT_CHOOSE_LOCATION = "Оборудование — выберите точку:"
EQUIPMENT_LIST_TITLE = "Точка «{location}», {address}. Оборудование:"
EQUIPMENT_CATEGORY = "Категория: {category}"
EQUIPMENT_SERIAL = "Серийный номер: {serial}"
EQUIPMENT_NEW_REQUEST_OWN = "Новая заявка уйдёт вашему сервису."
EQUIPMENT_NEW_REQUEST_SEARCH = "Своего сервиса нет — новая заявка пойдёт во внешний поиск."
BUTTON_NEW_REQUEST = "Новая заявка"


PROFILE_TITLE = "Профиль исполнителя «{name}»"
PROFILE_STATUS = "Статус: {status}"
PROFILE_STATUS_REASON = "Комментарий проверки: {reason}"
PROFILE_STATUS_LABELS = {
    "draft": "черновик, не отправлен на проверку",
    "pending_review": "на проверке",
    "needs_information": "нужны уточнения",
    "active": "допущен к заявкам",
    "suspended": "приостановлен",
    "rejected": "не допущен",
}
PROFILE_VERIFICATION = "Подтверждено: {items}"
PROFILE_NOTHING_CONFIRMED = "пока ничего"
PROFILE_CATEGORIES = "Категории: {categories}"
PROFILE_AREAS = "Территория: {areas}"
PROFILE_ACCEPTING_ON = "Новые заявки: принимаю"
PROFILE_ACCEPTING_OFF = "Новые заявки: не принимаю"
BUTTON_ACCEPTING_ON = "Принимать новые заявки"
BUTTON_ACCEPTING_OFF = "Не принимать новые заявки"
PROFILE_ACCEPTING_SAVED_ON = "Готово: новые заявки принимаются."
PROFILE_ACCEPTING_SAVED_OFF = "Готово: новые заявки не принимаются."
PROFILE_ADMIN_ONLY = "Приём заявок переключает администратор исполнителя."
PROFILE_ACCEPTING_UNAVAILABLE = "Приём заявок включается после допуска профиля."
PROFILE_MISSING = "Профиль исполнителя ещё не заполнен."
PROFILE_EDIT = "Профиль в приложении"
BUTTON_PROFILE_SETUP = "Заполнить и отправить на проверку"


SETUP_ASK_KIND = "Кто вы как исполнитель?"
SETUP_KIND_COMPANY = "Сервисная компания"
SETUP_KIND_SPECIALIST = "Самостоятельный мастер"
SETUP_ASK_LEGAL_FORM = "Правовая форма:"
SETUP_FORM_OOO = "ООО"
SETUP_FORM_IP = "ИП"
SETUP_FORM_SELF_EMPLOYED = "Самозанятый"
SETUP_ASK_INN = "ИНН (10 или 12 цифр) — по нему проверяются реквизиты:"
SETUP_ASK_CATEGORIES = "С каким оборудованием работаете? Отметьте категории и нажмите «Готово»."
SETUP_CATEGORIES_REQUIRED = "Отметьте хотя бы одну категорию."
SETUP_DONE = "Готово"
SETUP_ASK_CITY = "Город, где вы работаете:"
SETUP_ASK_DISTRICTS = "Районы выезда: отметьте нужные или выберите весь город."
SETUP_WHOLE_CITY = "Весь город"
SETUP_ASK_CONFIRM = (
    "Отправить профиль на проверку? Портфолио, бренды и условия выезда можно добавить в приложении."
)
SETUP_SUBMIT = "Отправить на проверку"
SETUP_SAVE_DRAFT = "Сохранить черновик"
SETUP_SAVED_DRAFT = "Профиль сохранён. Отправить на проверку можно из «Профиля»."
SETUP_SUBMITTED = "Профиль отправлен на проверку. Сообщим о результате."


INTEGRATION_ADMIN_ONLY = "Раздел доступен администратору исполнителя."
INTEGRATION_CONNECTED = "CRM подключена."
INTEGRATION_NOT_CONNECTED = "CRM не подключена: нет действующих ключей и подписок."
INTEGRATION_KEYS = "Действующих ключей API: {count}"
INTEGRATION_SUBSCRIPTIONS = "Активных подписок на вебхуки: {count}"
INTEGRATION_LAST_USED = "Последнее обращение CRM: {when}"
INTEGRATION_ERRORS_TITLE = "Последние ошибки доставки:"
INTEGRATION_ERROR_ITEM = "• {event} — {state}: {detail} ({when})"
INTEGRATION_NO_ERRORS = "Ошибок доставки нет."
INTEGRATION_SETUP = "Настроить в приложении"
DELIVERY_STATE_LABELS = {
    "failed": "не доставлено",
    "blocked": "заблокировано",
    "retrying": "повтор",
}


ASSIGNMENT_CONFIRM_TITLE = (
    "Вас выбрали исполнителем по заявке №{number}. Подтвердите готовность до {deadline}."
)
BUTTON_CONFIRM_ASSIGNMENT = "Подтверждаю"
BUTTON_DECLINE_ASSIGNMENT = "Не готов"
INBOX_CONFIRM_DEADLINE = "Подтвердите до {deadline}."


NOTIF_NOW_OUTDATED = "Условия уже неактуальны — откройте заявку в приложении."
