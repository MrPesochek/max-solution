from __future__ import annotations

from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from connector.onec_client import OneCClient, is_empty_ref
from connector.profile import FieldRef, Profile


class ProfileMismatchError(Exception):
    """В базе нет объекта, на который ссылается профиль (состояние, доп. реквизит)."""


class Directory:
    def __init__(self, onec: OneCClient, profile: Profile) -> None:
        self.onec = onec
        self.profile = profile
        self._states: dict[str, str] | None = None
        self._properties: dict[str, str] = {}
        self._items: dict[str, str] = {}
        self._item_keys: dict[str, str] = {}
        self._counterparties: dict[str, str] = {}

    async def _load_states(self) -> dict[str, str]:
        catalog = self.profile.state.catalog
        assert catalog is not None
        rows = await self.onec.query(catalog, select=["Ref_Key", "Description"])
        self._states = {str(r["Ref_Key"]): str(r.get("Description", "")) for r in rows}
        return self._states

    async def state_name(self, doc: dict[str, Any]) -> str | None:
        value = doc.get(self.profile.state.attribute)
        if self.profile.state.catalog is None:
            return str(value) if value else None
        if is_empty_ref(value):
            return None
        states = self._states or await self._load_states()
        if str(value) not in states:
            states = await self._load_states()
        return states.get(str(value))

    async def state_value(self, name: str) -> str:
        """Значение реквизита состояния для записи: GUID элемента справочника либо
        строка перечисления."""
        if self.profile.state.catalog is None:
            return name
        for attempt in range(2):
            states = self._states if (self._states and attempt == 0) else await self._load_states()
            for key, description in states.items():
                if description == name:
                    return key
        raise ProfileMismatchError(
            f"в {self.profile.state.catalog} нет состояния «{name}» (профиль {self.profile.name})"
        )

    async def initial_state_value(self) -> str | None:
        names = [name for name, stage in self.profile.state.stages.items() if stage == "new"]
        return await self.state_value(names[0]) if names else None

    async def property_key(self, name: str) -> str:
        cached = self._properties.get(name)
        if cached is not None:
            return cached
        found = await self.onec.find_by(
            self.profile.additional_attributes.chart,
            "Description",
            name,
            select=["Ref_Key", "Description"],
        )
        if found is None:
            raise ProfileMismatchError(
                f"в базе нет дополнительного реквизита «{name}» — заведите его "
                f"для документа {self.profile.document.entity}"
            )
        self._properties[name] = str(found["Ref_Key"])
        return self._properties[name]

    async def read(self, doc: dict[str, Any], ref: FieldRef | None) -> str | None:
        if ref is None:
            return None
        if ref.attribute is not None:
            value = doc.get(ref.attribute)
            return str(value).strip() or None if value is not None else None
        assert ref.additional is not None
        spec = self.profile.additional_attributes
        key = await self.property_key(ref.additional)
        for row in doc.get(spec.table) or []:
            if str(row.get(spec.property_field)) == key:
                value = row.get("ТекстоваяСтрока") or row.get(spec.value_field)
                return str(value).strip() or None if value is not None else None
        return None

    async def build_patch(
        self, doc: dict[str, Any] | None, values: dict[FieldRef, str]
    ) -> dict[str, Any]:
        """Тело PATCH: реквизиты как есть, дополнительные реквизиты — вся табличная
        часть (1С заменяет её целиком), строки чужих свойств сохраняются."""
        body: dict[str, Any] = {}
        spec = self.profile.additional_attributes
        rows = [dict(r) for r in (doc or {}).get(spec.table) or []]
        rows_changed = False
        for ref, value in values.items():
            if ref.attribute is not None:
                if doc is None or doc.get(ref.attribute) != value:
                    body[ref.attribute] = value
                continue
            assert ref.additional is not None
            key = await self.property_key(ref.additional)
            existing = next((r for r in rows if str(r.get(spec.property_field)) == key), None)
            if existing is None:
                if not value:
                    continue
                rows.append(
                    {
                        spec.property_field: key,
                        spec.value_field: value,
                        f"{spec.value_field}_Type": "Edm.String",
                    }
                )
                rows_changed = True
            elif (existing.get("ТекстоваяСтрока") or existing.get(spec.value_field)) != value:
                existing[spec.value_field] = value
                existing[f"{spec.value_field}_Type"] = "Edm.String"
                existing.pop("ТекстоваяСтрока", None)
                rows_changed = True
        if rows_changed:
            for number, row in enumerate(rows, start=1):
                row["LineNumber"] = str(number)
            body[spec.table] = rows
        return body

    async def item_title(self, ref_key: str) -> str:
        if ref_key in self._items:
            return self._items[ref_key]
        works = self.profile.works
        if works is None or works.item_catalog is None or is_empty_ref(ref_key):
            return ""
        item = await self.onec.get(works.item_catalog, ref_key)
        title = str(item.get("Description", "")) if item else ""
        self._items[ref_key] = title
        return title

    async def item_key(self, name: str) -> str | None:
        if name in self._item_keys:
            return self._item_keys[name]
        works = self.profile.works
        if works is None or works.item_catalog is None:
            return None
        found = await self.onec.find_by(
            works.item_catalog, "Description", name, select=["Ref_Key", "Description"]
        )
        if found is None:
            return None
        self._item_keys[name] = str(found["Ref_Key"])
        self._items[str(found["Ref_Key"])] = name
        return self._item_keys[name]

    async def counterparty_key(self, *, name: str, inn: str | None) -> str | None:
        mapping = self.profile.document.counterparty
        if mapping is None:
            return None
        cache_key = f"{inn or ''}|{name}"
        if cache_key in self._counterparties:
            return self._counterparties[cache_key]
        found = None
        if inn and mapping.inn_field:
            found = await self.onec.find_by(mapping.catalog, mapping.inn_field, inn)
        if found is None:
            found = await self.onec.find_by(mapping.catalog, mapping.name_field, name)
        if found is None:
            if not mapping.create_if_missing:
                if name == mapping.placeholder:
                    return None
                return await self.counterparty_key(name=mapping.placeholder, inn=None)
            body: dict[str, Any] = {mapping.name_field: name}
            if inn and mapping.inn_field:
                body[mapping.inn_field] = inn
            found = await self.onec.create(mapping.catalog, body)
        self._counterparties[cache_key] = str(found["Ref_Key"])
        return self._counterparties[cache_key]


def parse_onec_datetime(value: Any, profile: Profile) -> datetime | None:
    """Дата 1С без зоны — местное время базы; пустая дата 1С — `0001-01-01T00:00:00`."""
    if not value or str(value).startswith("0001-01-01"):
        return None
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=profile.zone())
    return parsed


def format_onec_datetime(value: datetime, profile: Profile) -> str:
    return value.astimezone(profile.zone()).replace(tzinfo=None, microsecond=0).isoformat()


def default_window_end(start: datetime, profile: Profile) -> datetime:
    hours = profile.visit.default_window_hours if profile.visit else 2.0
    return start + timedelta(hours=hours)


def amount_to_minor(value: Any) -> int | None:
    """Суммы 1С — десятичные рубли (`1500` или `1500.5`); в платформу — копейки."""
    if value is None or value == "":
        return None
    minor = (Decimal(str(value)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(minor)
