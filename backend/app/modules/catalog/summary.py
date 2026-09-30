import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ids
from app.core.scope import AccessScope
from app.db.enums import (
    AttachmentState,
    BindingStatus,
    RequestStatus,
)
from app.db.models import (
    Attachment,
    Equipment,
    EquipmentCategory,
    Location,
    Organization,
    RepairRequest,
    ServiceBinding,
)
from app.modules.integration import api as integration

NAMEPLATE_SLOT = "nameplate"
_FINISHED = (RequestStatus.CLOSED.value, RequestStatus.CANCELLED.value)


@dataclass(frozen=True, slots=True)
class BindingSummary:
    id: str
    status: str
    basis: str
    is_contact_only: bool
    provider_name: str | None
    valid_until: date | None
    guarantor_kind: str | None
    guarantor_name: str | None
    provider_has_crm: bool
    contact_phone: str | None = None
    guarantor_stated_by_provider: bool = False
    warranty_authorization_id: str | None = None


@dataclass(frozen=True, slots=True)
class ActiveRequestSummary:
    id: str
    request_number: int
    status: str


@dataclass(frozen=True, slots=True)
class EquipmentSummary:
    category_code: str | None = None
    category_name: str | None = None
    location_name: str | None = None
    binding: BindingSummary | None = None
    active_request: ActiveRequestSummary | None = None
    has_nameplate_photo: bool = False


def _binding_rank(binding: ServiceBinding) -> int:
    if binding.provider_org_id is None:
        return 1
    return 0 if binding.status == BindingStatus.CONFIRMED else 2


async def equipment_summaries(
    session: AsyncSession, scope: AccessScope, equipment: Sequence[Equipment]
) -> dict[uuid.UUID, EquipmentSummary]:
    if not equipment:
        return {}
    equipment_ids = tuple(eq.id for eq in equipment)

    categories = {
        row.id: row
        for row in (
            await session.execute(
                select(EquipmentCategory).where(
                    EquipmentCategory.id.in_({eq.equipment_category_id for eq in equipment})
                )
            )
        ).scalars()
    }
    locations = {
        row[0]: row[1]
        for row in (
            await session.execute(
                select(Location.id, Location.name).where(
                    Location.id.in_({eq.location_id for eq in equipment})
                )
            )
        ).all()
    }

    bindings = list(
        (
            await session.execute(
                select(ServiceBinding)
                .where(
                    ServiceBinding.equipment_id.in_(equipment_ids),
                    ServiceBinding.customer_org_id == scope.organization_id,
                    ServiceBinding.status.in_(
                        (BindingStatus.CONFIRMED.value, BindingStatus.PENDING.value)
                    ),
                )
                .order_by(ServiceBinding.id.desc())
            )
        ).scalars()
    )
    best: dict[uuid.UUID, ServiceBinding] = {}
    for binding in bindings:
        current = best.get(binding.equipment_id)
        if current is None or _binding_rank(binding) < _binding_rank(current):
            best[binding.equipment_id] = binding
    org_ids = {
        org_id
        for binding in best.values()
        for org_id in (binding.provider_org_id, binding.guarantor_org_id)
        if org_id is not None
    }
    org_names = (
        {
            row[0]: row[1]
            for row in (
                await session.execute(
                    select(Organization.id, Organization.display_name).where(
                        Organization.id.in_(org_ids)
                    )
                )
            ).all()
        }
        if org_ids
        else {}
    )
    provider_ids = {b.provider_org_id for b in best.values() if b.provider_org_id is not None}
    with_crm = await integration.providers_with_active_webhook(session, provider_ids)

    requests_stmt = (
        select(RepairRequest)
        .where(
            RepairRequest.equipment_id.in_(equipment_ids),
            RepairRequest.customer_org_id == scope.organization_id,
            RepairRequest.status.not_in(_FINISHED),
        )
        .order_by(RepairRequest.id.desc())
    )
    if scope.location_ids is not None:
        requests_stmt = requests_stmt.where(
            RepairRequest.location_id.in_(tuple(scope.location_ids) or (None,))
        )
    active: dict[uuid.UUID, RepairRequest] = {}
    for request in (await session.execute(requests_stmt)).scalars():
        active.setdefault(request.equipment_id, request)

    with_nameplate = set(
        (
            await session.execute(
                select(Attachment.equipment_id).where(
                    Attachment.equipment_id.in_(equipment_ids),
                    Attachment.slot == NAMEPLATE_SLOT,
                    Attachment.processing_state == AttachmentState.READY.value,
                )
            )
        ).scalars()
    )

    result: dict[uuid.UUID, EquipmentSummary] = {}
    for eq in equipment:
        category = categories.get(eq.equipment_category_id)
        found_binding = best.get(eq.id)
        found_request = active.get(eq.id)
        result[eq.id] = EquipmentSummary(
            category_code=category.code if category else None,
            category_name=category.name if category else None,
            location_name=locations.get(eq.location_id),
            binding=_binding_summary(found_binding, org_names, with_crm),
            active_request=(
                ActiveRequestSummary(
                    id=ids.encode("request", found_request.id),
                    request_number=found_request.request_number,
                    status=found_request.status,
                )
                if found_request is not None
                else None
            ),
            has_nameplate_photo=eq.id in with_nameplate,
        )
    return result


def _binding_summary(
    binding: ServiceBinding | None,
    org_names: dict[uuid.UUID, str],
    with_crm: set[uuid.UUID],
) -> BindingSummary | None:
    if binding is None:
        return None
    return BindingSummary(
        id=ids.encode("service_binding", binding.id),
        status=binding.status,
        basis=binding.basis,
        is_contact_only=binding.provider_org_id is None,
        provider_name=(
            org_names.get(binding.provider_org_id)
            if binding.provider_org_id is not None
            else binding.personal_contact_name
        ),
        valid_until=binding.valid_until,
        guarantor_kind=binding.guarantor_kind,
        guarantor_name=(
            org_names.get(binding.guarantor_org_id)
            if binding.guarantor_org_id is not None
            else binding.stated_guarantor_name
        ),
        provider_has_crm=binding.provider_org_id in with_crm,
        contact_phone=binding.personal_contact_phone if binding.provider_org_id is None else None,
        guarantor_stated_by_provider=(
            binding.guarantor_kind is not None and binding.warranty_authorization_id is None
        ),
        warranty_authorization_id=ids.encode_opt(
            "warranty_authorization", binding.warranty_authorization_id
        ),
    )
