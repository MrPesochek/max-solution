import pytest

from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed, VersionConflict
from app.db.models import Assignment, RepairRequest
from app.modules.requests import api
from tests.requests import helpers as h
from tests.requests.factories import World

pytestmark = pytest.mark.usefixtures("clean_db")


async def test_s1_full_cycle(world: World) -> None:
    draft = await h.make_draft(world)
    assert draft["status"] == "draft"
    assert draft["version"] == 1
    assert draft["equipment"]["serial_number"] == "SN-0001"

    updated = (
        await api.update_draft(
            world.employee,
            h.rid(draft),
            urgency="critical",
            symptom_description="Течёт хладагент",
            expected_version=draft["version"],
        )
    ).body
    assert updated["urgency"] == "critical"
    assert updated["version"] == 2

    submitted = (
        await api.submit_to_own_service(
            world.employee,
            h.rid(updated),
            photos_incomplete=True,
            photos_incomplete_reason="Камера не работает",
            expected_version=updated["version"],
        )
    ).body
    assert submitted["status"] == "awaiting_provider"
    assert submitted["assignment"]["state"] == "pending"
    assert submitted["photos_incomplete"] is True
    assert submitted["submitted_at"] is not None
    assert submitted["accepted_at"] is None

    accepted = (
        await api.accept_assignment(
            world.dispatcher,
            h.rid(submitted),
            assignment_id=h.assignment_id(submitted),
            expected_version=submitted["version"],
        )
    ).body
    assert accepted["status"] == "accepted"
    assert accepted["assignment"]["state"] == "accepted"
    assert accepted["contacts_disclosed"] is True
    assert accepted["location"]["address"] == "ул. Примерная, 1"

    proposed = (
        await api.propose_visit(
            world.dispatcher,
            h.rid(accepted),
            assignment_id=h.assignment_id(accepted),
            data=api.VisitProposalInput(
                **h.visit_window(),
                amount_minor=250000,
                currency="RUB",
                vat_mode="included",
                scope_description="Выезд",
            ),
            expected_version=accepted["version"],
        )
    ).body
    assert proposed["status"] == "accepted"
    assert proposed["visit_proposals"][0]["version"] == 1
    assert proposed["visit_proposals"][0]["price"]["is_known"] is True

    scheduled = (
        await api.approve_visit_proposal(
            world.manager,
            h.rid(proposed),
            proposal_id=h.proposal_id(proposed),
            proposal_version=1,
            expected_version=proposed["version"],
        )
    ).body
    assert scheduled["status"] == "scheduled"
    assert scheduled["visit_proposals"][0]["status"] == "approved"

    started = (
        await api.start_work(
            world.dispatcher,
            h.rid(scheduled),
            assignment_id=h.assignment_id(scheduled),
            expected_version=scheduled["version"],
        )
    ).body
    assert started["status"] == "in_progress"

    reported = (
        await api.report_completion(
            world.dispatcher,
            h.rid(started),
            assignment_id=h.assignment_id(started),
            outcome="resolved",
            summary="Заменён термостат",
            expected_version=started["version"],
        )
    ).body
    assert reported["status"] == "completion_reported"

    closed = (
        await api.confirm_completion(
            world.manager, h.rid(reported), expected_version=reported["version"]
        )
    ).body
    assert closed["status"] == "closed"
    assert closed["closure_kind"] == "customer_confirmed"
    assert closed["assignment"]["state"] == "completed"

    history, _ = await api.request_history(world.manager, h.rid(closed))
    assert [event.event_type for event in history] == [
        "RequestDrafted",
        "RequestDraftUpdated",
        "RequestSubmittedToOwnService",
        "AssignmentAccepted",
        "VisitProposed",
        "VisitAgreed",
        "WorkStarted",
        "CompletionReported",
        "RequestClosed",
    ]


async def test_a04_same_request_number_for_both_sides(world: World) -> None:
    accepted = await h.make_accepted(world)
    customer_view = await api.get_request(world.manager, h.rid(accepted))
    provider_view = await api.get_request(world.dispatcher, h.rid(accepted))
    assert customer_view.request_number == provider_view.request_number


async def test_a05_incomplete_photos_require_reason(world: World) -> None:
    draft = await h.make_draft(world)
    with pytest.raises(ValidationFailed):
        await api.submit_to_own_service(
            world.employee, h.rid(draft), photos_incomplete=True, expected_version=draft["version"]
        )


async def test_submit_requires_confirmed_binding_and_active_provider(world: World) -> None:
    draft = (
        await api.create_draft(world.other_employee, equipment_id=world.other_equipment_id)
    ).body
    with pytest.raises(Conflict) as exc:
        await api.submit_to_own_service(
            world.other_employee, h.rid(draft), expected_version=draft["version"]
        )
    assert exc.value.code == "SERVICE_BINDING_REQUIRED"


async def test_update_draft_null_semantics(world: World) -> None:
    draft = await h.make_draft(world)
    updated = (
        await api.update_draft(
            world.employee,
            h.rid(draft),
            symptom_description="Течёт хладагент",
            expected_version=draft["version"],
        )
    ).body
    assert updated["urgency"] == "normal"

    untouched = (
        await api.update_draft(
            world.employee, h.rid(draft), error_code="E1", expected_version=updated["version"]
        )
    ).body
    assert untouched["symptom_description"] == "Течёт хладагент"

    cleared = (
        await api.update_draft(
            world.employee,
            h.rid(draft),
            symptom_description=None,
            expected_version=untouched["version"],
        )
    ).body
    assert cleared["symptom_description"] is None

    with pytest.raises(ValidationFailed) as exc:
        await api.update_draft(
            world.employee, h.rid(draft), urgency=None, expected_version=cleared["version"]
        )
    assert exc.value.details.get("field") == "urgency"

    with pytest.raises(ValidationFailed) as exc:
        await api.update_draft(
            world.employee, h.rid(draft), equipment_id=None, expected_version=cleared["version"]
        )
    assert exc.value.details.get("field") == "equipment_id"


async def test_a28_stale_expected_version(world: World) -> None:
    draft = await h.make_draft(world)
    await api.update_draft(
        world.employee, h.rid(draft), urgency="urgent", expected_version=draft["version"]
    )
    with pytest.raises(VersionConflict) as exc:
        await api.update_draft(
            world.employee, h.rid(draft), urgency="critical", expected_version=draft["version"]
        )
    assert exc.value.details["current_version"] == 2


async def test_a13_stale_proposal_version_is_rejected(world: World) -> None:
    accepted = await h.make_accepted(world)
    first = (
        await api.propose_visit(
            world.dispatcher,
            h.rid(accepted),
            assignment_id=h.assignment_id(accepted),
            data=api.VisitProposalInput(**h.visit_window(), amount_minor=100000, currency="RUB"),
            expected_version=accepted["version"],
        )
    ).body
    second = (
        await api.propose_visit(
            world.dispatcher,
            h.rid(first),
            assignment_id=h.assignment_id(first),
            data=api.VisitProposalInput(**h.visit_window(), amount_minor=180000, currency="RUB"),
            expected_version=first["version"],
        )
    ).body
    old_proposal = h.proposal_id(first)

    with pytest.raises(Conflict) as exc:
        await api.approve_visit_proposal(
            world.manager,
            h.rid(second),
            proposal_id=old_proposal,
            proposal_version=1,
            expected_version=second["version"],
        )
    assert exc.value.code == "PROPOSAL_NOT_CURRENT"

    approved = (
        await api.approve_visit_proposal(
            world.manager,
            h.rid(second),
            proposal_id=h.proposal_id(second),
            proposal_version=2,
            expected_version=second["version"],
        )
    ).body
    assert approved["status"] == "scheduled"


async def test_a13_new_conditions_need_new_approval(world: World) -> None:
    scheduled = await h.make_scheduled(world)
    changed = (
        await api.propose_visit(
            world.dispatcher,
            h.rid(scheduled),
            assignment_id=h.assignment_id(scheduled),
            data=api.VisitProposalInput(**h.visit_window(), amount_minor=300000, currency="RUB"),
            expected_version=scheduled["version"],
        )
    ).body
    assert changed["status"] == "accepted"
    assert changed["visit_proposals"][0]["version"] == 2
    full = await api.get_request(world.manager, h.rid(changed))
    assert [(p.version, p.status) for p in full.visit_proposals] == [
        (2, "pending"),
        (1, "superseded"),
    ]

    with pytest.raises(Conflict):
        await api.start_work(
            world.dispatcher,
            h.rid(changed),
            assignment_id=h.assignment_id(changed),
            expected_version=changed["version"],
        )


async def test_price_unknown_cannot_be_approved(world: World) -> None:
    accepted = await h.make_accepted(world)
    proposed = (
        await api.propose_visit(
            world.dispatcher,
            h.rid(accepted),
            assignment_id=h.assignment_id(accepted),
            data=api.VisitProposalInput(**h.visit_window(), amount_minor=None),
            expected_version=accepted["version"],
        )
    ).body
    assert proposed["visit_proposals"][0]["price"]["is_known"] is False
    with pytest.raises(Conflict) as exc:
        await api.approve_visit_proposal(
            world.manager,
            h.rid(proposed),
            proposal_id=h.proposal_id(proposed),
            proposal_version=1,
            expected_version=proposed["version"],
        )
    assert exc.value.code == "PRICE_UNKNOWN"


async def test_a25_repair_quote_is_separate_from_visit(world: World) -> None:
    in_progress = await h.make_in_progress(world)
    quoted = (
        await api.create_repair_quote(
            world.integration,
            h.rid(in_progress),
            assignment_id=h.assignment_id(in_progress),
            data=api.RepairQuoteInput(
                description_of_work="Замена компрессора", amount_minor=900000, currency="RUB"
            ),
            expected_version=in_progress["version"],
        )
    ).body
    assert quoted["status"] == "in_progress"
    assert quoted["repair_quotes"][0]["status"] == "pending"

    with pytest.raises(Forbidden):
        await api.approve_repair_quote(
            world.employee,
            h.rid(quoted),
            quote_id=h.quote_id(quoted),
            quote_version=1,
            expected_version=quoted["version"],
        )

    approved = (
        await api.approve_repair_quote(
            world.manager,
            h.rid(quoted),
            quote_id=h.quote_id(quoted),
            quote_version=1,
            expected_version=quoted["version"],
        )
    ).body
    assert approved["repair_quotes"][0]["status"] == "approved"
    assert approved["status"] == "in_progress"
    types = await h.event_types()
    assert types.count("repair_quote.responded") == 1


async def test_repair_quote_requires_amount(world: World) -> None:
    in_progress = await h.make_in_progress(world)
    with pytest.raises(ValidationFailed):
        await api.create_repair_quote(
            world.dispatcher,
            h.rid(in_progress),
            assignment_id=h.assignment_id(in_progress),
            data=api.RepairQuoteInput(description_of_work="Ремонт", amount_minor=None),
            expected_version=in_progress["version"],
        )


async def test_reject_completion_returns_to_work(world: World) -> None:
    reported = await h.make_completion_reported(world)
    with pytest.raises(ValidationFailed):
        await api.reject_completion(
            world.manager, h.rid(reported), reason=" ", expected_version=reported["version"]
        )
    back = (
        await api.reject_completion(
            world.manager,
            h.rid(reported),
            reason="Холод не держит",
            expected_version=reported["version"],
        )
    ).body
    assert back["status"] == "in_progress"
    assert back["assignment"]["state"] == "accepted"


async def test_warranty_and_field_worker_are_recorded(world: World) -> None:
    accepted = await h.make_accepted(world)
    with_warranty = (
        await api.set_warranty_decision(
            world.dispatcher,
            h.rid(accepted),
            assignment_id=h.assignment_id(accepted),
            decision="warranty",
            comment="Гарантия производителя до 2027",
            expected_version=accepted["version"],
        )
    ).body
    assert with_warranty["assignment"]["warranty_decision"] == "warranty"

    with_worker = (
        await api.set_field_worker(
            world.integration,
            h.rid(with_warranty),
            assignment_id=h.assignment_id(with_warranty),
            display_name="Мастер Иванов",
            contact_phone="+70000000001",
            expected_version=with_warranty["version"],
        )
    ).body
    assert with_worker["assignment"]["field_worker"]["stated_by_company"] is True
    assert with_worker["assignment"]["field_worker"]["display_name"] == "Мастер Иванов"


async def test_external_reference_is_unique_per_integration(world: World) -> None:
    submitted = await h.make_submitted(world)
    linked = (
        await api.set_external_reference(
            world.integration,
            h.rid(submitted),
            external_id="CRM-1",
            expected_version=submitted["version"],
        )
    ).body
    again = (
        await api.set_external_reference(world.integration, h.rid(submitted), external_id="CRM-1")
    ).body
    assert again["version"] == linked["version"]

    other = await h.make_submitted(world)
    with pytest.raises(Conflict) as exc:
        await api.set_external_reference(world.integration, h.rid(other), external_id="CRM-1")
    assert exc.value.code == "EXTERNAL_REFERENCE_CONFLICT"

    with pytest.raises(Forbidden):
        await api.set_external_reference(world.dispatcher, h.rid(other), external_id="CRM-2")


async def test_messages_are_visible_to_participants(world: World) -> None:
    accepted = await h.make_accepted(world)
    await api.post_message(world.employee, h.rid(accepted), body="Когда приедете?")
    await api.post_message(
        world.dispatcher,
        h.rid(accepted),
        body="Завтра до 12",
        assignment_id=h.assignment_id(accepted),
    )
    customer_messages, _ = await api.list_messages(world.manager, h.rid(accepted))
    provider_messages, _ = await api.list_messages(world.dispatcher, h.rid(accepted))
    assert [m.body for m in customer_messages] == ["Когда приедете?", "Завтра до 12"]
    assert len(provider_messages) == 2
    assert (await h.event_types()).count("message.created") == 1


async def test_second_active_assignment_is_rejected(world: World) -> None:
    submitted = await h.make_submitted(world)
    with pytest.raises(Conflict) as exc:
        await api.submit_to_own_service(world.manager, h.rid(submitted))
    assert exc.value.code in {"INVALID_TRANSITION", "ASSIGNMENT_ALREADY_ACTIVE"}
    assert await h.count_of(Assignment) == 1
    assert await h.count_of(RepairRequest) == 1


async def test_foreign_request_is_not_found(world: World, other_world: World) -> None:
    accepted = await h.make_accepted(world)
    with pytest.raises(NotFound):
        await api.get_request(other_world.manager, h.rid(accepted))
    with pytest.raises(NotFound):
        await api.get_request(other_world.dispatcher, h.rid(accepted))
    with pytest.raises(NotFound):
        await api.confirm_completion(other_world.manager, h.rid(accepted))
