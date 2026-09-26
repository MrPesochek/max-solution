export const common = {
  retry: 'Повторить',
  cancel: 'Отмена',
  save: 'Сохранить',
  create: 'Создать',
  edit: 'Изменить',
  back: 'Назад',
  copy: 'Скопировать',
  copied: 'Скопировано',
  copyFailed: 'Не удалось скопировать — выделите и скопируйте вручную',
  close: 'Закрыть',
  open: 'Открыть',
  loading: 'Загрузка…',
  accept: 'Принять',
  revoke: 'Отозвать',
  yes: 'Да',
  no: 'Нет',
  optional: 'необязательно',
  unknownError: 'Что-то пошло не так',
  notSpecified: 'Не указано',
} as const;

export const states = {
  empty: 'Пока пусто',
  error: 'Не удалось загрузить данные',
  noAccess: 'Нет доступа',
  noAccessDescription: 'У вас нет прав для просмотра этого раздела.',
  offline: 'Нет сети. Изменения не сохранены.',
  offlineLoad: 'Нет соединения с сервером. Проверьте сеть и повторите.',
  offlineTitle: 'Нет соединения',
  unavailableTitle: 'Сервис временно недоступен',
  openBot: 'Открыть бота',
  savingUnavailable: 'Соединение потеряно — попробуйте ещё раз, когда сеть появится.',
} as const;

export const ui = {
  appTitle: 'Ремонт техники',
  requestTitle: (number: number | string) => `Заявка Р-${number}`,
  requestGenericTitle: 'Заявка',
  back: 'Назад',
  close: 'Закрыть',
  menu: 'Меню',
  menuTitle: 'Действия',
  offline: 'Нет сети. Изменения не сохранены.',
  unsavedTitle: 'Выйти без сохранения?',
  unsavedText: 'Введённые данные не сохранятся.',
  unsavedLeave: 'Выйти',
  unsavedStay: 'Остаться',
  tabBadge: (count: number) => `${count} новых`,
  clearFilter: (label: string) => `Сбросить: ${label}`,
  photoReplace: 'Заменить',
  photoChecking: 'Проверяем…',
  photoRejected: 'Отклонено',
  photoNone: 'Нет',
  photoPlaceholder: 'фото',
  photoAdd: 'Добавить фото',
  starsLabel: 'Оценка',
  star: (n: number) => `${n} из 5`,
  starCaptions: ['Плохо', 'Есть проблемы', 'Нормально', 'Хорошо', 'Отлично'],
  starPrompt: 'Поставьте оценку',
  show: 'Показать',
  hide: 'Скрыть',
  history: 'История',
  stepOf: (current: number, total: number) => `Шаг ${current} из ${total}`,
  stepState: {
    done: 'выполнено',
    current: 'сейчас',
    todo: 'впереди',
    attention: 'нужно действие',
  },
  theme: {
    caption: 'Оформление',
    label: 'Тема',
    system: 'Как в системе',
    light: 'Светлая',
    dark: 'Тёмная',
  },
  sections: {
    caption: 'Разделы',
    locations: 'Точки',
    bindings: 'Подключённые сервисы',
    providers: 'Исполнители',
    complaints: 'Мои жалобы',
    integration: 'Интеграция',
    clientBindings: 'Привязки клиентов',
    bindingInvitations: 'Приглашения клиентов',
    reviews: 'Отзывы',
    operator: 'Оператор',
  },
} as const;

export const header = {
  switchOrganization: 'Сменить организацию',
  back: 'Назад к списку',
} as const;

export const money = {
  priceUnknown: 'Цена требует уточнения',
  vatIncluded: 'НДС включён',
  vatExcluded: 'НДС не включён отдельно',
  vatNotApplicable: 'Без НДС',
  free: 'Бесплатно',
} as const;

export const attachments = {
  defaultAlt: 'Фотография',
  photoAlt: (index: number) => `Фотография ${index}`,
  ratingStar: (star: number) => `${star} из 5`,
  requestPhotoAlt: (requestNumber: string | number, index: number) =>
    `Фото к заявке №${requestNumber}, ${index}`,
  messagePhotoAlt: (index: number) => `Фото в сообщении, ${index}`,
  portfolioAlt: (index: number) => `Работа из портфолио, ${index}`,
  addPhoto: 'Добавить фото',
  replaceRejected: (alt: string) => `${alt}: отклонено, заменить`,
  uploading: 'Загружаем…',
  uploadError: 'Не удалось загрузить фото',
  closedNotice: 'Заявка завершена — новые фото добавить нельзя',
} as const;

export const errorCodes = {
  IDEMPOTENT_SECRET_NOT_REPLAYABLE:
    'Ключ уже выдан, повторно показать его нельзя. При необходимости перевыпустите ключ.',
  PAYLOAD_TOO_LARGE: 'Слишком большой объём данных — уменьшите файл или текст и повторите.',
  RATE_LIMITED: 'Слишком много попыток, попробуйте позже.',
  OFFER_NOT_CURRENT: 'Исполнитель обновил предложение — проверьте актуальные условия и выберите снова.',
  ASSIGNMENT_EXPIRED: 'Срок подтверждения назначения истёк.',
  OFFER_ALREADY_ACTIVE: 'У вас уже есть активное предложение по этой заявке.',
  REVIEW_ALREADY_EXISTS: 'Отзыв по этому исполнителю уже оставлен — показываем сохранённый вариант.',
  MEMBERSHIP_AMBIGUOUS: 'У вас несколько ролей в этой организации — выберите, от чьего имени работать.',
  PARTICIPATION_EXISTS: 'Организация уже участвует в этом качестве.',
  INN_ALREADY_VERIFIED: 'Этот ИНН уже подтверждён у другой организации — обратитесь к оператору.',
  INN_LOCKED: 'ИНН проверенной организации изменить нельзя — обратитесь к оператору платформы.',
  REQUISITES_UNDER_REVIEW: 'Реквизиты сейчас на проверке — изменить их можно после решения оператора.',
  SELF_BINDING_FORBIDDEN: 'Нельзя привязать собственную организацию как сервис.',
  SENSITIVE_PHOTO_NOT_CONFIRMED:
    'На выбранном фото может быть серийный номер или документ — подтвердите публикацию или снимите выбор.',
  BAD_REQUEST: 'Некорректный запрос — обновите экран и попробуйте ещё раз.',
  SERVICE_UNAVAILABLE: 'Сервис временно недоступен. Попробуйте повторить чуть позже.',
  DEMO_LOGIN_DISABLED: 'Демо-вход на этом сервере выключен.',
  OFFER_DIALOG_CLOSED:
    'Вопросы до выбора закрыты: исполнитель уже выбран или поиск завершён. Дальше — в переписке по заявке.',
  QUOTE_ITEMS_SUM_MISMATCH: 'Итог не совпадает с суммой позиций — проверьте суммы и отправьте снова.',
  APPEAL_NOT_ALLOWED: 'Обжаловать можно только отказ или приостановку профиля.',
  PROFILE_APPEAL_ALREADY_OPEN: 'Обжалование уже на рассмотрении — дождитесь решения оператора.',
} as const;

export const actions = {
  staleTitle: 'Данные изменились',
  staleDescription: 'Данные изменились, проверьте и повторите. Введённое сохранено.',
  offlineError: 'Нет соединения. Введённое сохранено — повторите, когда сеть появится.',
  genericError: 'Не удалось выполнить действие',
} as const;
