import uuid
from datetime import date

from pydantic import BaseModel
from sqlalchemy import select

from app.core import ids
from app.core.actor import IntegrationActor
from app.db import session as db_session
from app.db.enums import BindingStatus
from app.db.models import Equipment, Organization, ServiceBinding, ServiceContract
from app.modules.integration import policy


class EquipmentBindingView(BaseModel):
    service_binding_id: str
    basis: str
    contract_number: str | None
    valid_from: date | None
    valid_until: date | None


class ProviderEquipmentView(BaseModel):
    id: str
    equipment_category_id: str
    brand: str | None
    model: str | None
    serial_number: str | None
    customer_organization_id: str
    customer_name: str
    bindings: list[EquipmentBindingView]


async def list_bound_equipment(
    actor: IntegrationActor, *, cursor: str | None, limit: int
) -> tuple[list[ProviderEquipmentView], str | None]:
    policy.require_scope(actor, policy.EQUIPMENT_READ)
    after = ids.decode("equipment", cursor) if cursor else None
    confirmed = select(ServiceBinding.equipment_id).where(
        ServiceBinding.provider_org_id == actor.organization_id,
        ServiceBinding.status == BindingStatus.CONFIRMED,
    )
    async with db_session.transaction() as session:
        stmt = (
            select(Equipment, Organization)
            .join(Organization, Organization.id == Equipment.customer_org_id)
            .where(Equipment.id.in_(confirmed), Equipment.archived_at.is_(None))
            .order_by(Equipment.id)
            .limit(limit + 1)
        )
        if after is not None:
            stmt = stmt.where(Equipment.id > after)
        rows = list((await session.execute(stmt)).all())
        page = rows[:limit]

        bindings: dict[uuid.UUID, list[EquipmentBindingView]] = {}
        if page:
            binding_rows = (
                await session.execute(
                    select(ServiceBinding, ServiceContract)
                    .outerjoin(ServiceContract, ServiceContract.id == ServiceBinding.contract_id)
                    .where(
                        ServiceBinding.provider_org_id == actor.organization_id,
                        ServiceBinding.status == BindingStatus.CONFIRMED,
                        ServiceBinding.equipment_id.in_([equipment.id for equipment, _ in page]),
                    )
                    .order_by(ServiceBinding.id)
                )
            ).all()
            for binding, contract in binding_rows:
                bindings.setdefault(binding.equipment_id, []).append(
                    EquipmentBindingView(
                        service_binding_id=ids.encode("service_binding", binding.id),
                        basis=binding.basis,
                        contract_number=(
                            contract.contract_number
                            if contract
                            else binding.claimed_contract_number
                        ),
                        valid_from=binding.valid_from,
                        valid_until=binding.valid_until,
                    )
                )

    items = [
        ProviderEquipmentView(
            id=ids.encode("equipment", equipment.id),
            equipment_category_id=ids.encode("category", equipment.equipment_category_id),
            brand=equipment.brand,
            model=equipment.model,
            serial_number=equipment.serial_number,
            customer_organization_id=ids.encode("organization", customer.id),
            customer_name=customer.display_name,
            bindings=bindings.get(equipment.id, []),
        )
        for equipment, customer in page
    ]
    next_cursor = ids.encode("equipment", page[-1][0].id) if len(rows) > limit else None
    return items, next_cursor
