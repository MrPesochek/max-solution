import { useState, type ReactNode } from 'react';
import { Link, useParams } from 'react-router-dom';
import { Screen, BottomActions } from '../layout/Screen';
import { ActionButton, type ActionKind } from '../layout/ActionButton';
import { TabBar } from '../layout/TabBar';
import type { TabSide } from '../layout/layoutContext';
import { Banner, Note, PageTitle, PriceBlock, SectionCaption, TextCard } from '../blocks/Blocks';
import { List, ListRow } from '../List';
import { TextAreaField, TextField, SelectField, PhoneField } from '../FormField';
import { Segmented } from '../Segmented';
import { Chips, Chip, FilterChip } from '../Chips';
import { PhotoGrid, PhotoTile } from '../PhotoGrid';
import { Stars } from '../Stars';
import { StatusHero } from '../StatusHero';
import { MessageBubble } from '../MessageBubble';
import { ThemeSwitcher } from '../theme/ThemeSwitcher';
import { ConfirmDialog } from '../../components/ConfirmDialog';
import { SceneBanner } from '../SceneBanner';
import { KeyValueRows } from '../KeyValueRows';
import { Stepper, StepProgress } from '../Stepper';
import { EventTimeline } from '../EventTimeline';
import { ChoiceCard, ChoiceGroup } from '../ChoiceCard';
import { ChipGroup } from '../Chips';
import { Toggle } from '../Toggle';
import { StarRating } from '../Stars';
import { SkeletonRows } from '../Skeleton';
import { Avatar } from '../blocks/Blocks';

interface Frame {
  id: string;
  title: string;
  subtitle?: string;
  back?: boolean;
  tab?: { side: TabSide; active: string };
  actions?: [string, ActionKind?][];
  body: ReactNode;
}

function Demo13() {
  const [noScreen, setNoScreen] = useState(true);
  return (
    <>
      <PageTitle subtitle="По ним мастер поймёт, какие запчасти взять. JPEG, PNG, WebP, до 10 МБ, не больше 10 фото.">
        Фото
      </PageTitle>
      <PhotoGrid>
        <PhotoTile label="Общий вид" state="ok" />
        <PhotoTile label="Шильдик · 14 МБ" state="e" onClick={() => {}} actionLabel="Заменить фото шильдика" />
        <PhotoTile label="Экран ошибки" state="add" onClick={() => {}} actionLabel="Добавить фото экрана" />
        <PhotoTile label="Внутри" state="q" />
      </PhotoGrid>
      <Note tone="error">
        Шильдик: файл больше 10 МБ. Снимите заново или выберите другой — остальное сохранено.
      </Note>
      <List>
        <ListRow title="На технике нет экрана" control={{ type: 'switch', checked: noScreen }} onToggle={setNoScreen} />
        <ListRow title="Не могу сделать фото" chevron onClick={() => {}} />
      </List>
    </>
  );
}

function Demo12() {
  const [urgency, setUrgency] = useState('today');
  const [text, setText] = useState('Держит +9 °C вместо +4. Компрессор щёлкает и выключается');
  const [code, setCode] = useState('');
  return (
    <>
      <List>
        <ListRow title="Витрина Carboma" subtitle="Садовая, 12 → ХолодСервис" icon="В" />
      </List>
      <TextAreaField label="Что случилось" value={text} onChange={setText} autoFocus />
      <TextField label="Код ошибки" value={code} onChange={setCode} placeholder="Если есть, например E1" />
      <SectionCaption>Когда нужен мастер</SectionCaption>
      <List role="radiogroup" aria-label="Когда нужен мастер">
        {[
          ['today', 'Сегодня'],
          ['soon', 'В течение 1–2 дней'],
          ['later', 'Не срочно'],
        ].map(([id, label]) => (
          <ListRow
            key={id}
            title={label}
            control={{ type: 'radio', checked: urgency === id }}
            onToggle={() => setUrgency(id!)}
          />
        ))}
      </List>
      <Note>Черновик сохранён · 10:14</Note>
    </>
  );
}

function Demo03() {
  const [name, setName] = useState('Кофе Точка');
  const [inn, setInn] = useState('7701234567');
  const [phone, setPhone] = useState('+7 900 123-45-67');
  const [point, setPoint] = useState('Садовая, 12, Москва');
  return (
    <>
      <TextField label="Название" value={name} onChange={setName} />
      <TextField
        label="ИНН"
        value={inn}
        onChange={setInn}
        inputMode="numeric"
        error="Эта компания уже зарегистрирована. Попросите руководителя пригласить вас."
      />
      <PhoneField label="Телефон для обращений" value={phone} onChange={setPhone} />
      <TextField label="Первая точка" value={point} onChange={setPoint} />
      <Note>
        Организация сразу станет вашей рабочей областью. Проверка представителя нужна только для
        подтверждённых договоров и отзывов.
      </Note>
    </>
  );
}

function Demo04() {
  const [org, setOrg] = useState('kt');
  return (
    <>
      <SectionCaption>Ваши организации</SectionCaption>
      <List role="radiogroup" aria-label="Организация">
        <ListRow title="Кофе Точка" subtitle="Руководитель · заказчик" icon="КТ" gradient="o" control={{ type: 'radio', checked: org === 'kt' }} onToggle={() => setOrg('kt')} />
        <ListRow title="ХолодСервис" subtitle="Мастер · исполнитель" icon="ХС" gradient="g" control={{ type: 'radio', checked: org === 'hs' }} onToggle={() => setOrg('hs')} />
        <ListRow title="Пекарня Мука" subtitle="Сотрудник" icon="ПМ" gradient="r" tag={{ label: 'Ждёт подтверждения администратора', tone: 'y' }} />
      </List>
      <Note>Незаконченный ввод в текущей организации сохранится как черновик перед переключением.</Note>
      <List>
        <ListRow title="Создать организацию" action="accent" onClick={() => {}} />
        <ListRow title="Ввести приглашение" action="accent" onClick={() => {}} />
      </List>
    </>
  );
}

function Demo06() {
  return (
    <>
      <PageTitle subtitle="ИНН 7701234567 · реквизиты не проверены">Кофе Точка</PageTitle>
      <List>
        <ListRow title="Точки" value="2" valueTone="secondary" chevron to="/__ui" />
        <ListRow title="Сотрудники" value="4" valueTone="secondary" chevron to="/__ui" />
        <ListRow title="Подключённые сервисы" value="1" valueTone="secondary" chevron to="/__ui" />
      </List>
      <List>
        <ListRow title="Проверка представителя" subtitle="Нужна для подтверждённых договоров и отзывов" tag={{ label: 'Не пройдена', tone: 'w' }} chevron to="/__ui" />
      </List>
      <List>
        <ListRow title="Сменить организацию" action="accent" onClick={() => {}} />
      </List>
      <ThemeSwitcher />
    </>
  );
}

function Demo06Invite() {
  const [role, setRole] = useState('employee');
  const [points, setPoints] = useState({ a: true, b: false });
  return (
    <>
      <SectionCaption>Роль</SectionCaption>
      <List role="radiogroup" aria-label="Роль">
        <ListRow title="Сотрудник" subtitle="Заявки своих точек" control={{ type: 'radio', checked: role === 'employee' }} onToggle={() => setRole('employee')} />
        <ListRow title="Руководитель" subtitle="Все заявки, цены, выбор исполнителя" control={{ type: 'radio', checked: role === 'manager' }} onToggle={() => setRole('manager')} />
      </List>
      <SectionCaption>Доступные точки</SectionCaption>
      <List>
        <ListRow title="Садовая, 12" control={{ type: 'checkbox', checked: points.a }} onToggle={(v) => setPoints((p) => ({ ...p, a: v }))} />
        <ListRow title="Ленина, 4" control={{ type: 'checkbox', checked: points.b }} onToggle={(v) => setPoints((p) => ({ ...p, b: v }))} />
      </List>
      <Note>Ссылка одноразовая и действует 24 часа. Отправьте её сотруднику в MAX.</Note>
    </>
  );
}

function Demo15() {
  const [scope, setScope] = useState<'active' | 'done'>('active');
  const [point, setPoint] = useState('');
  const [status, setStatus] = useState('');
  return (
    <>
      <PageTitle>Заявки</PageTitle>
      <Segmented label="Какие заявки показать" items={[{ id: 'active', label: 'Активные · 5' }, { id: 'done', label: 'Завершённые' }]} value={scope} onChange={setScope} />
      <Chips label="Фильтры">
        <FilterChip label="Точка" allLabel="Все точки" value={point} onChange={setPoint} options={[{ value: 'l4', label: 'Ленина, 4' }, { value: 's12', label: 'Садовая, 12' }]} />
        <FilterChip label="Статус" allLabel="Все статусы" value={status} onChange={setStatus} options={[{ value: 'x', label: 'Отменена' }, { value: 'w', label: 'Мастер работает' }]} />
      </Chips>
      <List>
        <ListRow title="Витрина Carboma" subtitle="Р-1042 · Садовая, 12" tag={{ label: 'Согласуйте выезд', tone: 'a' }} chevron to="/__ui" />
        <ListRow title="Льдогенератор Scotsman" subtitle="Р-1038 · Ленина, 4" tag={{ label: 'Выберите исполнителя', tone: 'a' }} chevron to="/__ui" />
        <ListRow title="Кофемашина La Cimbali" subtitle="Р-1045 · Садовая, 12" tag={{ label: 'Ждём ответа сервиса', tone: 'w' }} chevron to="/__ui" />
        <ListRow title="Холодильный стол Polair" subtitle="Р-1031 · Ленина, 4" tag={{ label: 'Мастер работает', tone: 'w' }} chevron to="/__ui" />
        <ListRow title="Посудомоечная машина" subtitle="Сохранён вчера" tag={{ label: 'Черновик', tone: 'y' }} chevron to="/__ui" />
      </List>
    </>
  );
}

function Demo20Changed() {
  return (
    <>
      <PageTitle subtitle="ХолодСервис изменил предложение">Витрина Carboma</PageTitle>
      <Banner tone="y" title="Версия 2 заменила версию 1">
        Прежнее согласие к новым условиям не применяется.
      </Banner>
      <PriceBlock value="4 200 ₽" caption="Выезд и диагностика до 1 часа" oldValue="3 500 ₽" />
      <List>
        <ListRow title="Когда" oldValue="Чт, 10:00–13:00" value="Чт, 15:00–18:00 МСК" />
        <ListRow title="Причина" value="Утром нет мастера" />
        <ListRow title="Ответить до" value="24 сент, 12:00" />
      </List>
    </>
  );
}

function Demo14Sent() {
  return (
    <>
      <StatusHero icon="✓" tone="ok" top={120} title="Заявка Р-1045 отправлена">
        ХолодСервис получит её в CRM. Когда сервис примет заявку, придёт уведомление.
      </StatusHero>
      <List>
        <ListRow title="Отправлено" marker="ok" value="10:16" />
        <ListRow title="Доставлено в CRM" marker="w" value="ожидаем" valueTone="secondary" />
        <ListRow title="Принято сервисом" marker="-" value="—" valueTone="secondary" />
      </List>
    </>
  );
}

function Demo27() {
  const [rating, setRating] = useState(4);
  const [text, setText] = useState('Приехали вовремя, но пришлось вызывать повторно');
  const [showName, setShowName] = useState(false);
  return (
    <>
      <PageTitle subtitle="Заявка Р-1031 · холодильный стол">Как поработал ХолодСервис?</PageTitle>
      <Stars value={rating} onChange={setRating} />
      <TextAreaField label="Отзыв" value={text} onChange={setText} />
      <List>
        <ListRow title="Показывать название организации" subtitle="Иначе — «Подтверждённый бизнес-клиент»" control={{ type: 'switch', checked: showName }} onToggle={setShowName} />
        <ListRow title="Фото к отзыву" subtitle="Выберите отдельно, фото заявки не публикуются сами" chevron onClick={() => {}} />
      </List>
    </>
  );
}

function Demo28() {
  return (
    <>
      <PageTitle subtitle="9 организаций · 14 отзывов">★ 4,7</PageTitle>
      <MessageBubble author="Кофе Точка · ★★★★" time="20 сент">Приехали вовремя, но пришлось вызывать повторно.</MessageBubble>
      <MessageBubble author="Ответ исполнителя" time="21 сент" mine>Спасибо. Повторный выезд был бесплатным.</MessageBubble>
      <MessageBubble author="Подтверждённый бизнес-клиент · ★★★★★" time="12 сент">Быстро починили льдогенератор.</MessageBubble>
      <List>
        <ListRow title="Пожаловаться на отзыв" action="accent" onClick={() => {}} />
      </List>
    </>
  );
}

function Demo16Draft() {
  return (
    <>
      <PageTitle subtitle="Садовая, 12 · сохранён на сервере вчера в 18:20">Посудомоечная машина</PageTitle>
      <Banner tone="w" title="Заявка ещё не отправлена">
        Никто её не видит. Продолжить можно здесь или в чате с ботом.
      </Banner>
      <List>
        <ListRow title="Описание" marker="ok" />
        <ListRow title="Фото" marker="-" value="не добавлены" valueTone="secondary" />
        <ListRow title="Получатель" marker="-" value="не выбран" valueTone="secondary" />
      </List>
    </>
  );
}

function DemoMisc() {
  const [confirm, setConfirm] = useState(false);
  const [chips, setChips] = useState([0]);
  const [point, setPoint] = useState('');
  return (
    <>
      <PageTitle subtitle="Остальные варианты блоков">Разное</PageTitle>
      <Banner tone="a" title="Опубликует руководитель">Анна Соколова проверит, что увидят исполнители, и откроет поиск.</Banner>
      <Banner tone="ok" title="Выезд согласован">Чт 24 сент, 15:00–18:00 МСК · Иван Петров</Banner>
      <Banner tone="x" title="CRM сервиса недоступна">Заявка сохранена. Повторяем доставку автоматически.</Banner>
      <TextCard>Не делает лёд, вода не набирается.</TextCard>
      <Chips label="Чипы">
        {['Холод', 'Кофе', 'Посуда'].map((label, index) => (
          <Chip key={label} selected={chips.includes(index)} onClick={() => setChips((c) => (c.includes(index) ? c.filter((i) => i !== index) : [...c, index]))}>
            {label}
          </Chip>
        ))}
      </Chips>
      <SelectField label="Точка" value={point} onChange={setPoint} placeholder="Выберите точку" options={[{ value: 'a', label: 'Садовая, 12' }]} />
      <List>
        <ListRow title="Переписка" count={1} chevron onClick={() => {}} />
        <ListRow title="Ремонт" value="6 700 ₽" valueTone="strong" />
        <ListRow title="Ссылка" value="Открыть" valueTone="accent" />
        <ListRow title="Мой сервис" subtitle="Для этой техники сервис не подключён" subtitleTone="error" icon="—" />
        <ListRow title="Сервис" subtitle="Договор подтверждён" subtitleTone="accent" icon="ХС" gradient="g" />
        <ListRow title="Идёт загрузка" loading />
        <ListRow title="Отменить заявку" action="danger" onClick={() => setConfirm(true)} />
      </List>
      <Stars value={3} />
      <div className="ui-pad">
        <ActionButton kind="g">Текстовая кнопка</ActionButton>
        <ActionButton kind="p" loading>
          Отправляем
        </ActionButton>
        <ActionButton kind="p" disabled>
          Недоступно
        </ActionButton>
      </div>
      <ConfirmDialog
        open={confirm}
        title="Отменить заявку?"
        description="Сервис получит уведомление."
        confirmLabel="Отменить заявку"
        cancelLabel="Не отменять"
        destructive
        onConfirm={() => setConfirm(false)}
        onCancel={() => setConfirm(false)}
      />
    </>
  );
}

function Demo9a() {
  return (
    <>
      <SceneBanner name="status-travel" height={150} />
      <PageTitle subtitle="Андрей отметил выезд в 14:02.">Мастер едет</PageTitle>
      <List>
        <ListRow media="display" title="Ремонт витрины" subtitle="Carboma F16 · Кафе «Лето»" chevron onClick={() => {}} />
        <ListRow icon={<Avatar name="Андрей Ковалёв" aria-hidden />} title="Андрей Ковалёв" subtitle="ХолодСервис · ★ 4,9 (64)" />
      </List>
      <KeyValueRows
        variant="items"
        rows={[
          { label: 'Замена пускового реле', value: '2 400 ₽' },
          { label: 'Заправка фреоном R134a', value: '4 700 ₽', oldValue: '4 000 ₽', tone: 'accent' },
          { label: 'Работа мастера', value: '2 500 ₽' },
        ]}
        total={{ label: 'Итого', value: '9 600 ₽' }}
      />
      <EventTimeline
        title="История"
        collapsible
        defaultOpen
        events={[
          { title: 'Мастер выехал', time: '14:02', tone: 'accent' },
          { title: 'Отказ: нет мастеров на сегодня', time: '12:15', tone: 'danger' },
          { title: 'Создана Е. Смирновой', time: '11:58' },
        ]}
      />
    </>
  );
}

function DemoKit() {
  const [role, setRole] = useState('customer');
  const [slot, setSlot] = useState<string | null>('Сегодня 14:30');
  const [cats, setCats] = useState<string[]>(['Холодильное']);
  const [online, setOnline] = useState(true);
  const [stars, setStars] = useState(4);
  const [tab, setTab] = useState<'my' | 'find'>('my');
  return (
    <>
      <StepProgress current={2} total={3} />
      <PageTitle eyebrow="СРОЧНО · СЕГОДНЯ" eyebrowTone="danger" subtitle="Carboma F16 · ЦАО">
        Витрина не держит холод
      </PageTitle>
      <SegmentTabsDemo value={tab} onChange={setTab} />
      <ChoiceGroup label="Кто вы">
        <ChoiceCard illustration="role-employee" title="Заказчик" subtitle="Кафе, магазин, пекарня" selected={role === 'customer'} onSelect={() => setRole('customer')} />
        <ChoiceCard illustration="role-master" title="Исполнитель" subtitle="Сервисная компания или мастер" selected={role === 'provider'} onSelect={() => setRole('provider')} />
      </ChoiceGroup>
      <SectionCaption action={<button type="button">Все 6</button>}>Когда приедете</SectionCaption>
      <ChipGroup label="Когда приедете" options={['Сегодня 14:30', 'Сегодня 17:00', 'Завтра 10:00'].map((v) => ({ value: v, label: v }))} value={slot} onChange={setSlot} />
      <ChipGroup multiple label="Что ремонтирую" variant="outline" size="s" options={['Холодильное', 'Льдогенераторы', 'Кофемашины'].map((v) => ({ value: v, label: v }))} value={cats} onChange={setCats} />
      <div className="ui-pad">
        <Toggle pill checked={online} onChange={setOnline} aria-label="Принимаю заявки">
          {online ? 'Принимаю' : 'Пауза'}
        </Toggle>
      </div>
      <List>
        <ListRow title="Получать и обрабатывать заявки" subtitle="requests:rw" control={{ type: 'switch', checked: online }} onToggle={setOnline} />
        <ListRow title="Витрина Carboma F16" subtitle="Тверская 12" media="display" control={{ type: 'checkbox', checked: true }} onToggle={() => {}} />
      </List>
      <Stepper
        aria-label="Ход работ"
        steps={[
          { label: 'Выехал', time: '14:02', state: 'done' },
          { label: 'На месте', time: '14:38', state: 'done' },
          { label: 'Диагностика', state: 'current' },
          { label: 'Работа завершена', state: 'todo' },
        ]}
      />
      <Stepper
        steps={[
          { label: 'Реквизиты компании', sub: 'Оператор сверил с ФНС', state: 'done' },
          { label: 'Полномочия представителя', sub: 'Загрузите доверенность', state: 'attention' },
          { label: 'Категории работ', sub: 'После проверки полномочий', state: 'todo' },
        ]}
      />
      <Stepper variant="dots" steps={[{ label: 'Жалоба отправлена', time: 'сейчас', state: 'done' }, { label: 'Проверяет оператор', time: 'до 2 дней', state: 'todo' }]} />
      <StarRating value={stars} onChange={setStars} captions />
      <KeyValueRows rows={[{ label: 'Вебхук', value: 'crm.holodservis.ru/max', mono: true }, { label: 'Событий за сутки', value: '148 · ошибок 0' }]} />
      <SkeletonRows rows={2} />
    </>
  );
}

function SegmentTabsDemo({ value, onChange }: { value: 'my' | 'find'; onChange: (v: 'my' | 'find') => void }) {
  return (
    <Segmented
      mode="tab"
      label="Раздел"
      items={[
        { id: 'my', label: 'Мой сервис' },
        { id: 'find', label: 'Найти исполнителя', count: 3 },
      ]}
      value={value}
      onChange={onChange}
    />
  );
}

const FRAMES: Frame[] = [
  { id: '9a', title: 'Заявка № 412', actions: [['Написать мастеру']], body: <Demo9a /> },
  { id: 'kit', title: 'Шаг 2 из 3', actions: [['Отказаться', 's'], ['Согласовать']], body: <DemoKit /> },
  { id: 'D03', title: 'Новая организация', actions: [['Создать']], body: <Demo03 /> },
  { id: 'D04', title: 'Организации', body: <Demo04 /> },
  { id: 'D06', title: 'Организация', back: false, tab: { side: 'customer', active: '/organization' }, body: <Demo06 /> },
  { id: 'D06.3', title: 'Пригласить', actions: [['Создать ссылку']], body: <Demo06Invite /> },
  { id: 'D12', title: 'Мой сервис', subtitle: 'Шаг 1 из 3', actions: [['Далее']], body: <Demo12 /> },
  { id: 'D13', title: 'Мой сервис', subtitle: 'Шаг 2 из 3', actions: [['Далее']], body: <Demo13 /> },
  { id: 'D14.3', title: 'Заявка Р-1045', actions: [['Открыть заявку'], ['На главную', 's']], body: <Demo14Sent /> },
  { id: 'D15', title: 'Ремонт техники', back: false, tab: { side: 'customer', active: '/requests' }, body: <Demo15 /> },
  { id: 'D16', title: 'Черновик', actions: [['Продолжить заполнение'], ['Удалить черновик', 'd']], body: <Demo16Draft /> },
  { id: 'D20.3', title: 'Заявка Р-1042', actions: [['Согласовать 4 200 ₽'], ['Отклонить', 's']], body: <Demo20Changed /> },
  { id: 'D27', title: 'Отзыв', actions: [['Отправить на проверку']], body: <Demo27 /> },
  { id: 'D28', title: 'Отзывы', body: <Demo28 /> },
  {
    id: '—.1',
    title: 'Мой сервис',
    actions: [['Повторить отправку'], ['Продолжить в чате с ботом', 's']],
    body: (
      <StatusHero icon="!" top={120} title="Нет соединения">
        Заявка не отправлена. Черновик сохранён на сервере в 10:14. Изменения после этого остались на телефоне.
      </StatusHero>
    ),
  },
  { id: 'misc', title: 'Компоненты', body: <DemoMisc /> },
];

function FrameView({ frame }: { frame: Frame }) {
  return (
    <div className="ui-layout" data-tabbar={Boolean(frame.tab)}>
      <Screen
        title={frame.title}
        subtitle={frame.subtitle}
        back={frame.back === false ? false : '/__ui'}
        onClose={frame.back === false ? () => {} : undefined}
        menu={[{ label: 'Все рамки', onSelect: () => (window.location.hash = '#/__ui') }]}
        actions={
          frame.actions ? (
            <BottomActions>
              {frame.actions.map(([label, kind]) => (
                <ActionButton key={label} kind={kind ?? 'p'}>
                  {label}
                </ActionButton>
              ))}
            </BottomActions>
          ) : undefined
        }
      >
        {frame.body}
      </Screen>
      {frame.tab && <TabBar side={frame.tab.side} activeTo={frame.tab.active} />}
    </div>
  );
}

export function Showcase() {
  const { frame: frameId } = useParams<{ frame?: string }>();
  const frame = FRAMES.find((f) => f.id === frameId);
  if (frame) return <FrameView frame={frame} />;
  return (
    <Screen title="Витрина компонентов" back={false}>
      <ThemeSwitcher />
      <List>
        {FRAMES.map((f) => (
          <ListRow key={f.id} title={f.id} subtitle={f.title} chevron to={`/__ui/${encodeURIComponent(f.id)}`} />
        ))}
      </List>
      <Note>
        Рамки 9a и kit — блоки итогового макета design/final; D… — прежние экраны на новых
        токенах.
      </Note>
      <Link to="/" className="ui-note">
        В приложение
      </Link>
    </Screen>
  );
}
