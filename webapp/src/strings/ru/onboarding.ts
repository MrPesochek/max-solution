export const session = {
  signingIn: 'Выполняется вход…',
  checkingTitle: 'Проверяем вход',
  checkingText: 'Выполняем вход через MAX…',
  reopenRequired: 'Сессия истекла',
  reopenDescription:
    'Откройте мини-приложение заново из чата. Сохранённые черновики не пропадут. Несохранённый текст на этом экране восстановить нельзя.',
  unavailableTitle: 'Сервис временно недоступен',
  loginRetryableError:
    'Не удалось связаться с сервером. Создать заявку, ответить мастеру и проверить статус можно в чате с ботом.',
  outsideMaxTitle: 'Откройте приложение в MAX',
  outsideMaxText: 'Мини-приложение работает внутри MAX. Откройте его из чата с ботом сервиса.',
  openBotChat: 'Открыть чат с ботом',
  continueInBot: 'Продолжить в чате с ботом',
  linkInvalidTitle: 'Ссылка устарела',
  linkInvalidText:
    'Ссылка для входа одноразовая и действует несколько минут. Нажмите «Открыть приложение» в чате с ботом ещё раз.',
  linkReopenText:
    'Вход по ссылке действует только в этой вкладке. Нажмите «Открыть приложение» в чате с ботом ещё раз. Сохранённые черновики не пропадут.',
  demoLoginTitle: 'Демонстрационный вход',
  demoLoginSubtitle: 'Приложение открыто вне MAX. Выберите, под кем войти.',
  demoUsersCaption: 'Демо-пользователи',
  demoOtherCaption: 'Другой пользователь',
  demoUserKeyLabel: 'Идентификатор демо-пользователя',
  demoLoginButton: 'Войти в демо-режиме',
  demoLoginError: 'Не удалось выполнить демо-вход',
} as const;

export const onboarding = {
  title: 'Ремонт техники без звонков',
  subtitle: 'Заявки, мастера и согласования в MAX. Кто вы?',
  rolesLabel: 'Кто вы',
  roleCustomer: 'Заказчик',
  roleCustomerHint: 'Кафе, магазин, пекарня. Нужно чинить своё оборудование',
  roleProvider: 'Исполнитель',
  roleProviderHint: 'Сервисная компания или мастер. Беру заявки от бизнеса',
  continue: 'Продолжить',
  haveInvitation: 'Есть приглашение?',
  enterCode: 'Ввести код',
  invitationTitle: 'Ввести приглашение',
  invitationNote: 'Приглашение приходит от руководителя вашей организации или от вашего сервиса.',
  invitationLinkLabel: 'Ссылка или код приглашения',
  openInvitation: 'Открыть приглашение',
} as const;

export const orgForm = {
  title: 'Регистрация',
  customerTitle: 'Ваша организация',
  customerSubtitle:
    'Реквизиты проверит оператор, обычно до одного рабочего дня. Заявки можно создавать сразу.',
  name: 'Название',
  namePlaceholder: 'Как в документах',
  inn: 'ИНН',
  innPlaceholder: '10 или 12 цифр',
  innHintEmpty: 'Необязательно. Для ИП — 12 цифр',
  innHintLeft: (left: number) =>
    `Ещё ${left} ${left === 1 ? 'цифра' : left < 5 ? 'цифры' : 'цифр'}`,
  innHintOk: 'ИНН введён',
  innInvalid: 'Проверьте ИНН: 10 цифр у организации или 12 у ИП',
  innTaken: 'Эта компания уже зарегистрирована. Попросите руководителя пригласить вас.',
  contactPhone: 'Телефон для обращений',
  contactPhoneHint: 'По нему оператор и сервис свяжутся с организацией',
  firstLocationTitle: 'Первая точка',
  firstLocationHint: 'Остальные точки добавите позже',
  locationName: 'Название точки',
  locationNamePlaceholder: 'Кафе «Лето»',
  city: 'Город',
  district: 'Район',
  address: 'Адрес',
  addressPlaceholder: 'Улица, дом',
  submitCustomer: 'Создать организацию',
  providerTitle: 'Как вы работаете?',
  providerSubtitle: 'Заявки начнут приходить после проверки реквизитов и полномочий оператором.',
  providerKindLabel: 'Как вы работаете',
  providerCompany: 'Сервисная компания',
  providerCompanyHint: 'ООО или ИП, есть сотрудники-мастера',
  providerSelf: 'Самостоятельный мастер',
  providerSelfHint: 'Самозанятый или ИП, работаю сам',
  legalFormLabel: 'Форма',
  legalFormIp: 'ИП',
  legalFormSelfEmployed: 'Самозанятый (НПД)',
  companyName: 'Название компании',
  selfName: 'Имя и фамилия',
  companyInn: 'ИНН компании',
  selfInn: 'ИНН мастера',
  innDigits: (n: number) => `${n} цифр`,
  innInvalidProvider: 'Проверьте ИНН — контрольные цифры не сходятся',
  requiredName: 'Укажите название',
  requiredSelfName: 'Укажите имя',
  requiredPhone: 'Укажите телефон для связи',
  requiredLocationName: 'Укажите название точки',
  requiredCity: 'Выберите город',
  requiredDistrict: 'Выберите район — по нему подбираются исполнители',
  requiredAddress: 'Укажите адрес точки',
  requiredInnProvider: 'Укажите ИНН',
  providerPhone: 'Рабочий телефон',
  providerPhoneHint:
    'Оператор перезвонит по номеру из официального источника, а не только по этому',
  submitProvider: 'Продолжить',
  providerNextNote:
    'Дальше — категории, территория и полномочия представителя. После этого профиль уйдёт на проверку.',
  powerTitle: 'Полномочия представителя',
  docTitle: 'Доверенность или приказ',
  docHint: 'PDF или фото, до 10 МБ',
  docPick: 'Приложить доверенность или приказ',
  docOperatorOnly: 'видит только оператор',
  docRemove: 'Убрать',
  docTooLarge: 'Файл больше 10 МБ — сожмите его или приложите фото страницы',
  powerNote:
    'Доверенность поможет, но оператор всё равно подтвердит полномочия по независимому каналу — например, звонком по номеру из официального источника.',
  docEvidenceNote: 'Доверенность или приказ представителя приложены при регистрации',
  docUploadFailed:
    'Профиль отправлен, но документ не загрузился. Приложите его ещё раз на этом экране.',
  fileSize: (bytes: number) =>
    bytes < 1024 * 1024
      ? `${Math.max(1, Math.round(bytes / 1024))} КБ`
      : `${(bytes / 1024 / 1024).toFixed(1).replace('.', ',')} МБ`,
  unknownKind: 'Неизвестный тип организации',
} as const;

export const roleShort = {
  customer_manager: 'Руководитель',
  customer_employee: 'Сотрудник',
  provider_admin: 'Администратор',
  provider_dispatcher: 'Диспетчер/мастер',
} as const;

type RoleKey = keyof typeof roleShort;

export const roleLower = Object.fromEntries(
  Object.entries(roleShort).map(([role, label]) => [role, label.toLowerCase()]),
) as Record<RoleKey, string>;

export const orgPicker = {
  title: 'Организации',
  heading: 'Где работаем сегодня?',
  count: (n: number) =>
    `Вы состоите в ${n} ${n % 10 === 1 && n % 100 !== 11 ? 'организации' : 'организациях'}`,
  caption: 'Ваши организации',
  sideRole: (side: string, role: string) => `${side} · ${role}`,
  points: (n: number) =>
    `${n} ${n % 10 === 1 && n % 100 !== 11 ? 'точка' : n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 12 || n % 100 > 14) ? 'точки' : 'точек'}`,
  roleLower: roleLower as Record<string, string>,
  sideTitle: { customer: 'Заказчик', provider: 'Исполнитель' },
  enter: 'Войти',
  noOrganizations: 'У вас пока нет организаций',
  pending: 'Ждёт подтверждения',
  switchNote:
    'Заказчик и исполнитель — разные кабинеты. Переключиться можно в любой момент в разделе «Организация». Незаконченный ввод сохранится как черновик.',
  createOrganization: 'Создать новую организацию',
  enterInvitation: 'Ввести приглашение',
  side: {
    customer: 'заказчик',
    provider: 'исполнитель',
  },
  switchTitle: 'Переключить организацию',
  currentContext: 'Сейчас',
  switchTo: (label: string) => `Перейти: ${label}`,
} as const;

export const roles = {
  customer_manager: 'Руководитель заказчика',
  customer_employee: 'Сотрудник заказчика',
  provider_admin: 'Администратор исполнителя',
  provider_dispatcher: 'Диспетчер/мастер исполнителя',
} as const;

export const orgKinds = {
  customer: 'Заказчик',
  provider: 'Исполнитель',
} as const;

export const invitationAccept = {
  title: 'Приглашение',
  loading: 'Проверяем приглашение…',
  heroTitle: (organization: string) => `Вас приглашают в ${organization}`,
  roleText: {
    customer_employee: 'Сможете подавать заявки по своим точкам и видеть их статус.',
    customer_manager: 'Сможете видеть все заявки, выбирать исполнителя и согласовывать цены.',
    provider_dispatcher: 'Сможете принимать заявки, согласовывать выезды и отмечать работы.',
    provider_admin: 'Сможете вести профиль сервиса, сотрудников и интеграцию.',
  } as Record<string, string>,
  organization: 'Организация',
  role: 'Роль',
  location: 'Точка',
  locations: 'Точки',
  invitedBy: 'Приглашение от',
  expiresAt: 'Действует до',
  acceptButton: 'Принять',
  joinedTitle: 'Вы в команде',
  joinedText: (places: string | null) =>
    places
      ? `Теперь заявки точки ${places} доступны в разделе «Заявки».`
      : 'Теперь заявки организации доступны в разделе «Заявки».',
  joinedPlacesText: (places: string) =>
    `Теперь заявки точек ${places} доступны в разделе «Заявки».`,
  toHome: 'На главную',
  awaitingTitle: 'Ждёт подтверждения руководителя',
  awaitingText:
    'Доступ откроется, когда руководитель организации подтвердит вас. Мы сообщим в чате.',
  toOrganizations: 'К организациям',
  expiredTitle: 'Ссылка устарела',
  expiredUntil: (date: string) =>
    `Приглашение действовало до ${date}. Попросите руководителя прислать новую ссылку.`,
  expiredText: 'Срок приглашения истёк. Попросите руководителя прислать новую ссылку.',
  revokedTitle: 'Приглашение отозвано',
  revokedText:
    'Руководитель отменил это приглашение. Если это ошибка, попросите прислать новую ссылку.',
  usedTitle: 'Приглашение уже использовано',
  usedText: 'Ссылка одноразовая. Если вы ещё не в команде, попросите руководителя прислать новую.',
  rejectedTitle: 'Приглашение не сработало',
  rejectedText:
    'Возможно, оно выдано другому человеку или уже недействительно. Если его отправили вам, попросите руководителя прислать новое.',
  invalidTitle: 'Приглашение не найдено',
  invalidText: 'Проверьте ссылку или попросите руководителя прислать новую.',
} as const;
