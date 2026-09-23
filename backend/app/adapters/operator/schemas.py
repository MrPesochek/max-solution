import uuid
from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from app.core import ids
from app.db.enums import GuarantorKind


class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None = None


def page_of[T](items: list[T], kind: str, next_cursor: uuid.UUID | None) -> Page[T]:
    return Page[T](items=items, next_cursor=ids.encode_opt(kind, next_cursor))


VerificationDecision = Literal["approved", "rejected", "needs_information"]


class VerificationDecisionBody(BaseModel):
    decision: Annotated[VerificationDecision, Field(description="Решение по делу проверки")]
    reason: Annotated[str, Field(min_length=1, max_length=2000)]
    source: Annotated[str, Field(max_length=500)] | None = None
    expires_at: datetime | None = None
    is_demo: bool = False


class ProfileStatusBody(BaseModel):
    reason: Annotated[str, Field(min_length=1, max_length=2000)]


class ReopenVerificationBody(BaseModel):
    check_kind: Annotated[
        Literal["requisites", "representative"],
        Field(description="Что проверяется заново: реквизиты или представитель"),
    ]
    reason: Annotated[str, Field(min_length=1, max_length=2000)]
    compromise: Annotated[
        bool, Field(description="Компрометация: отозвать ключи интеграции и сессии")
    ] = False


class WarrantyAuthorizationBody(BaseModel):
    provider_organization_id: str
    guarantor_kind: Annotated[GuarantorKind, Field(description="Кто выступает гарантом")]
    source: Annotated[str, Field(min_length=1, max_length=500)]
    reason: Annotated[str, Field(min_length=1, max_length=2000)]
    guarantor_name: Annotated[str, Field(max_length=300)] | None = None
    guarantor_organization_id: str | None = None
    equipment_category_id: str | None = None
    brands: list[str] = Field(default_factory=list)
    city_id: str | None = None
    valid_from: date | None = None
    valid_until: date | None = None
    is_demo: bool = False


class RevokeBody(BaseModel):
    reason: Annotated[str, Field(min_length=1, max_length=2000)]


class GrantOperatorBody(BaseModel):
    max_user_id: Annotated[str, Field(min_length=1, max_length=64)]


class PlatformRoleView(BaseModel):
    max_user_id: str
    role: str


class OperatorBindingView(BaseModel):
    id: str
    status: str
    basis: str
    customer_organization_id: str
    customer_name: str
    provider_organization_id: str | None
    provider_name: str | None
    equipment_id: str
    contract_number: str | None
    status_reason: str | None
    created_at: datetime


def to_operator_binding_view(row: dict[str, Any]) -> OperatorBindingView:
    return OperatorBindingView(
        id=ids.encode("service_binding", row["id"]),
        status=row["status"],
        basis=row["basis"],
        customer_organization_id=ids.encode("organization", row["customer_org_id"]),
        customer_name=row["customer_name"],
        provider_organization_id=ids.encode_opt("organization", row["provider_org_id"]),
        provider_name=row["provider_name"],
        equipment_id=ids.encode("equipment", row["equipment_id"]),
        contract_number=row["contract_number"],
        status_reason=row["status_reason"],
        created_at=row["created_at"],
    )
