import pytest

from app.core.errors import Conflict, Forbidden, ValidationFailed
from app.core.scope import scope_of
from app.modules.catalog import api as catalog
from app.modules.trust import api as trust
from tests.support import CUSTOMER_INN, OTHER_INN, idem, make_customer, make_provider
from tests.trust.test_bindings import _one, _pair

pytestmark = pytest.mark.usefixtures("clean_db")


async def _invite(provider: object, key: str, **extra: object) -> dict[str, object]:
    result = await trust.create_binding_invitation(
        provider.admin,
        trust.BindingInvitationData(
            customer_inn=CUSTOMER_INN,
            contract_number="Д-100",
            basis="warranty",
            equipment_descriptions=["Холодильная витрина"],
            **extra,
        ),
        idem=idem(key),
    )
    return result.body


async def test_stated_guarantor_reaches_preview_and_binding() -> None:
    provider, customer = await _pair("gua-ok")
    issued = await _invite(
        provider, "gua-ok-1", guarantor_kind="manufacturer", guarantor_name="Polair"
    )
    assert issued["guarantor_kind"] == "manufacturer"
    token = str(issued["token"])

    preview = await trust.preview_binding_invitation(token, customer.manager)
    assert preview.guarantor_kind == "manufacturer"
    assert preview.guarantor_name == "Polair"

    accepted = await trust.accept_binding_invitation(
        customer.manager, token, _one(customer), idem=idem("gua-ok-2")
    )
    binding = accepted.body["items"][0]
    assert binding["guarantor_kind"] == "manufacturer"
    assert binding["guarantor_name"] == "Polair"
    assert binding["guarantor_stated_by_provider"] is True
    assert binding["warranty_authorization"] is None

    equipment = await catalog.get_equipment(scope_of(customer.manager), customer.equipment_id)
    assert equipment.binding is not None
    assert equipment.binding.guarantor_name == "Polair"


async def test_guarantor_hidden_from_strangers() -> None:
    provider, customer = await _pair("gua-hid")
    stranger = await make_customer("gua-hid-x", inn=OTHER_INN, verified=True)
    issued = await _invite(provider, "gua-hid-1", guarantor_kind="seller", guarantor_name="Склад")
    token = str(issued["token"])
    for actor in (None, stranger.manager, customer.employee):
        preview = await trust.preview_binding_invitation(token, actor)
        assert preview.guarantor_kind is None
        assert preview.guarantor_name is None


async def test_guarantor_validation_and_roles() -> None:
    provider, _ = await _pair("gua-val")
    with pytest.raises(ValidationFailed):
        await _invite(provider, "gua-val-1", guarantor_kind="platform")
    with pytest.raises(ValidationFailed):
        await _invite(provider, "gua-val-2", guarantor_name="Без вида")
    with pytest.raises(ValidationFailed):
        await _invite(provider, "gua-val-3", guarantor_kind="seller", guarantor_name="x" * 201)
    draft = await make_provider("gua-val-d", inn=None)
    with pytest.raises((Forbidden, Conflict)):
        await trust.create_binding_invitation(
            draft.admin,
            trust.BindingInvitationData(
                customer_inn=CUSTOMER_INN,
                contract_number="Д-1",
                equipment_descriptions=["Витрина"],
                guarantor_kind="seller",
            ),
            idem=idem("gua-val-4"),
        )
