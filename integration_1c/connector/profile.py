from __future__ import annotations

from pathlib import Path
from typing import Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

Stage = Literal[
    "new",
    "accepted",
    "declined",
    "in_progress",
    "done",
    "not_resolved",
    "cancelled",
    "cancellation_declined",
]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FieldRef(_Model):
    """Реквизит документа (`attribute`) либо дополнительный реквизит БСП (`additional`,
    по наименованию) — второй заводится пользователем 1С без изменения конфигурации."""

    attribute: str | None = None
    additional: str | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> Self:
        if (self.attribute is None) == (self.additional is None):
            raise ValueError("укажите ровно одно из attribute/additional")
        return self


class FieldMapping(_Model):
    """Поле, которое коннектор пишет в 1С из карточки заявки (шаблон `str.format`)."""

    target: FieldRef
    template: str
    when: Literal["create", "always"] = "always"


class AdditionalAttributes(_Model):
    table: str = "ДополнительныеРеквизиты"
    property_field: str = "Свойство_Key"
    value_field: str = "Значение"
    chart: str = "ChartOfCharacteristicTypes_ДополнительныеРеквизитыИСведения"


class CounterpartyMapping(_Model):
    field: str
    catalog: str
    name_field: str = "Description"
    inn_field: str | None = None
    create_if_missing: bool = True
    placeholder: str = "Заказчик платформы"


class DocumentMapping(_Model):
    entity: str
    number_field: str = "Number"
    date_field: str = "Date"
    react_only_posted: bool = True
    post_after_create: bool = False
    counterparty: CounterpartyMapping | None = None
    fields: list[FieldMapping] = Field(default_factory=list)


class StateMapping(_Model):
    attribute: str
    catalog: str | None = None
    stages: dict[str, Stage]
    inbound: dict[str, str] = Field(default_factory=dict)

    def stage_for(self, state_name: str | None) -> Stage | None:
        if state_name is None:
            return None
        return self.stages.get(state_name)


class WorksMapping(_Model):
    table: str
    amount_field: str
    item_field: str | None = None
    item_catalog: str | None = None
    title_fields: list[str] = Field(default_factory=list)


class VisitAmount(_Model):
    """Сумма выезда: реквизит документа или строки табличной части работ с указанной
    номенклатурой (в типовых конфигурациях отдельного реквизита для выезда нет)."""

    attribute: str | None = None
    table_items: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _one_source(self) -> Self:
        if (self.attribute is None) == (not self.table_items):
            raise ValueError("сумма выезда: укажите attribute либо table_items")
        return self


class VisitMapping(_Model):
    start: str
    end: str | None = None
    default_window_hours: float = 2.0
    amount: VisitAmount
    allow_unknown_price: bool = False
    scope_template: str = "{visit_items}"


class EstimateMapping(_Model):
    stages: list[Stage] = Field(default_factory=lambda: list[Stage](["accepted", "in_progress"]))
    description_template: str = "Смета по документу {number}"


class TextSource(_Model):
    source: FieldRef
    default: str


class MessagesMapping(_Model):
    outbound: FieldRef | None = None
    inbound: FieldRef | None = None
    inbound_limit: int = 10


class CancellationMapping(_Model):
    """Ответ на запрос отмены: этап `cancelled` — согласиться, `cancellation_declined` —
    оспорить; причина несогласия обязательна, без неё уходит `decline_reason.default`."""

    decline_reason: TextSource = TextSource(
        source=FieldRef(attribute="Комментарий"), default="Исполнитель не согласен с отменой"
    )


class AttachmentsMapping(_Model):
    """`attached_files` — присоединённые файлы БСП: элемент справочника
    `<Документ>ПрисоединенныеФайлы` + двоичные данные в регистре сведений;
    `none` — фото остаются на платформе, в 1С пишется только их перечень."""

    mode: Literal["attached_files", "none"] = "none"
    catalog: str | None = None
    owner_field: str = "ВладелецФайла_Key"
    binary_register: str | None = None
    binary_file_field: str = "Файл"
    binary_data_field: str = "ДвоичныеДанныеФайла_Base64Data"
    list_field: FieldRef | None = None

    @model_validator(mode="after")
    def _files_need_catalog(self) -> Self:
        if self.mode == "attached_files" and (not self.catalog or not self.binary_register):
            raise ValueError("attached_files: нужны catalog и binary_register")
        return self


class Profile(_Model):
    name: str
    title: str
    timezone: str = "Europe/Moscow"
    document: DocumentMapping
    additional_attributes: AdditionalAttributes = AdditionalAttributes()
    state: StateMapping
    works: WorksMapping | None = None
    visit: VisitMapping | None = None
    estimate: EstimateMapping | None = None
    decline_reason: TextSource = TextSource(
        source=FieldRef(attribute="Комментарий"), default="Отказ исполнителя"
    )
    completion_summary: TextSource = TextSource(
        source=FieldRef(attribute="Комментарий"), default="Работы выполнены"
    )
    messages: MessagesMapping = MessagesMapping()
    cancellation: CancellationMapping = CancellationMapping()
    exchange_status: FieldRef | None = None
    attachments: AttachmentsMapping = AttachmentsMapping()

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.visit is not None and self.visit.amount.table_items and self.works is None:
            raise ValueError("visit.amount.table_items требует секции works")
        if self.estimate is not None and self.works is None:
            raise ValueError("estimate требует секции works")
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"неизвестный часовой пояс {self.timezone!r}") from exc
        return self

    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    def additional_names(self) -> set[str]:
        refs: list[FieldRef | None] = [
            *(f.target for f in self.document.fields),
            self.decline_reason.source,
            self.completion_summary.source,
            self.cancellation.decline_reason.source,
            self.messages.outbound,
            self.messages.inbound,
            self.exchange_status,
            self.attachments.list_field,
        ]
        return {ref.additional for ref in refs if ref is not None and ref.additional}


def load_profile(path: Path) -> Profile:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Profile.model_validate(data)
