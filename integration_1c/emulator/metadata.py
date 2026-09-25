from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Kind = Literal["catalog", "document", "chart", "register"]

EMPTY_REF = "00000000-0000-0000-0000-000000000000"
EMPTY_DATE = "0001-01-01T00:00:00"


@dataclass(frozen=True)
class EntityDef:
    name: str
    kind: Kind
    fields: dict[str, Any]
    tables: dict[str, dict[str, Any]] = field(default_factory=dict)
    number_prefix: str = ""

    def standard_fields(self) -> dict[str, Any]:
        if self.kind == "register":
            return {}
        common: dict[str, Any] = {"Ref_Key": EMPTY_REF, "DataVersion": "", "DeletionMark": False}
        if self.kind == "document":
            return {**common, "Number": "", "Date": EMPTY_DATE, "Posted": False}
        return {**common, "Code": "", "Description": "", "Predefined": False}

    def all_fields(self) -> dict[str, Any]:
        return {**self.standard_fields(), **self.fields}


ORDER = "Document_ЗаказНаряд"
STATES = "Catalog_СостоянияЗаказНарядов"
COUNTERPARTIES = "Catalog_Контрагенты"
ITEMS = "Catalog_Номенклатура"
PROPERTIES = "ChartOfCharacteristicTypes_ДополнительныеРеквизитыИСведения"
FILES = "Catalog_ЗаказНарядПрисоединенныеФайлы"
BINARY = "InformationRegister_ДвоичныеДанныеФайлов"

ENTITIES: dict[str, EntityDef] = {
    COUNTERPARTIES: EntityDef(
        COUNTERPARTIES, "catalog", {"НаименованиеПолное": "", "ИНН": "", "КПП": ""}
    ),
    STATES: EntityDef(STATES, "catalog", {"Цвет": ""}),
    ITEMS: EntityDef(ITEMS, "catalog", {"Артикул": "", "ТипНоменклатуры": "Работа"}),
    PROPERTIES: EntityDef(
        PROPERTIES,
        "chart",
        {"Заголовок": "", "ТипЗначения": "Строка", "ЭтоДополнительноеСведение": False},
    ),
    ORDER: EntityDef(
        ORDER,
        "document",
        {
            "Контрагент_Key": EMPTY_REF,
            "СостояниеЗаказа_Key": EMPTY_REF,
            "Начало": EMPTY_DATE,
            "Окончание": EMPTY_DATE,
            "Комментарий": "",
            "СуммаДокумента": 0,
        },
        tables={
            "Работы": {
                "LineNumber": "",
                "Номенклатура_Key": EMPTY_REF,
                "Содержание": "",
                "Количество": 1,
                "Цена": 0,
                "Сумма": 0,
            },
            "ДополнительныеРеквизиты": {
                "LineNumber": "",
                "Свойство_Key": EMPTY_REF,
                "Значение": "",
                "Значение_Type": "Edm.String",
                "ТекстоваяСтрока": "",
            },
        },
        number_prefix="ЗН00-",
    ),
    FILES: EntityDef(
        FILES,
        "catalog",
        {
            "ВладелецФайла_Key": EMPTY_REF,
            "Расширение": "",
            "Размер": 0,
            "ТипХраненияФайла": "ВИнформационнойБазе",
            "Описание": "",
            "ДатаСоздания": EMPTY_DATE,
        },
    ),
    BINARY: EntityDef(
        BINARY,
        "register",
        {"Файл": EMPTY_REF, "Файл_Type": "", "ДвоичныеДанныеФайла_Base64Data": ""},
    ),
}

SEED_STATES = [
    "Новый",
    "Принят",
    "Отказ",
    "В работе",
    "Выполнен",
    "Не выполнен",
    "Отменен",
    "Отмена не согласована",
]
SEED_ITEMS = [
    ("Выезд мастера (диагностика)", "Услуга"),
    ("Замена термостата", "Работа"),
    ("Заправка хладагентом", "Работа"),
    ("Замена вентилятора конденсатора", "Работа"),
    ("Чистка конденсатора", "Работа"),
]
SEED_PROPERTIES = [
    "Заявка платформы",
    "Статус на платформе",
    "Неисправность",
    "Оборудование",
    "Адрес объекта",
    "Контакт на объекте",
    "Срочность",
    "Комментарий для заказчика",
    "Причина отказа",
    "Итог работ",
    "Причина несогласия с отменой",
    "Сообщения заказчика",
    "Обмен с платформой",
    "Фото с платформы",
]
EDITABLE_PROPERTIES = [
    "Комментарий для заказчика",
    "Причина отказа",
    "Итог работ",
    "Причина несогласия с отменой",
]
