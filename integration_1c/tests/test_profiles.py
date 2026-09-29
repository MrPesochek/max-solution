from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from connector.actions import DocView, EstimateLine, plan_actions
from connector.profile import Profile, load_profile
from connector.settings import PROFILES_DIR, Settings

MSK = ZoneInfo("Europe/Moscow")


def _profile(name: str) -> Profile:
    return load_profile(PROFILES_DIR / f"{name}.yaml")


def _card(status: str = "awaiting_provider", assignment_state: str = "pending") -> dict:
    return {
        "id": "req_1",
        "status": status,
        "version": 7,
        "assignment": {"id": "asg_1", "state": assignment_state},
        "visit_proposals": [],
        "repair_quotes": [],
    }


def _view(**fields) -> DocView:
    base = {
        "ref_key": "11111111-1111-1111-1111-111111111111",
        "number": "ЗН00-000001",
        "data_version": "AAAAAQ==",
        "posted": True,
        "deletion_mark": False,
        "state_name": None,
        "stage": None,
    }
    base.update(fields)
    return DocView(**base)


def _never(kind: str, fp: str) -> bool:
    return False


@pytest.mark.parametrize("name", ["unf", "generic"])
def test_profiles_load(name: str) -> None:
    profile = _profile(name)
    assert profile.name == name
    assert "new" in profile.state.stages.values()


def test_unf_profile_names_match_emulator() -> None:
    from emulator.metadata import ENTITIES, SEED_PROPERTIES, SEED_STATES

    profile = _profile("unf")
    assert profile.document.entity in ENTITIES
    assert profile.state.catalog in ENTITIES
    assert profile.attachments.catalog in ENTITIES
    assert set(profile.state.stages) <= set(SEED_STATES)
    assert profile.additional_names() <= set(SEED_PROPERTIES)


def test_invalid_profile_rejected() -> None:
    data = _profile("unf").model_dump()
    data["estimate"] = {"stages": ["accepted"]}
    data["works"] = None
    with pytest.raises(ValidationError):
        Profile.model_validate(data)
    with pytest.raises(ValidationError):
        Profile.model_validate({**_profile("unf").model_dump(), "timezone": "Mars/Base"})


def test_stage_mapping_to_actions() -> None:
    profile = _profile("unf")
    pending = _card()

    accept = plan_actions(profile, _view(stage="accepted"), pending, _never)
    assert [a.kind for a in accept] == ["accept"]
    assert accept[0].body == {"assignment_id": "asg_1", "expected_version": 7}

    assert [a.kind for a in plan_actions(profile, _view(stage="in_progress"), pending, _never)] == [
        "accept"
    ]
    decline = plan_actions(
        profile, _view(stage="declined", decline_reason="Нет мастера"), pending, _never
    )
    assert decline[0].kind == "decline" and decline[0].body["reason"] == "Нет мастера"
    default = plan_actions(profile, _view(stage="declined"), pending, _never)
    assert default[0].body["reason"] == "Отказ исполнителя"
    assert plan_actions(profile, _view(stage="new"), pending, _never) == []
    assert plan_actions(profile, _view(stage="accepted", posted=False), pending, _never) == []
    assert plan_actions(profile, _view(stage="accepted", deletion_mark=True), pending, _never) == []

    accepted = _card("accepted", "accepted")
    assert [a.kind for a in plan_actions(profile, _view(stage="declined"), accepted, _never)] == [
        "withdraw"
    ]
    scheduled = _card("scheduled", "accepted")
    assert [
        a.kind for a in plan_actions(profile, _view(stage="in_progress"), scheduled, _never)
    ] == ["start-work"]
    in_progress = _card("in_progress", "accepted")
    done = plan_actions(profile, _view(stage="not_resolved"), in_progress, _never)
    assert done[0].kind == "complete"
    assert done[0].body["outcome"] == "not_resolved"
    assert done[0].body["summary"] == "Работы выполнены"


def test_handled_fingerprint_is_not_planned_again() -> None:
    profile = _profile("unf")
    first = plan_actions(profile, _view(stage="accepted"), _card(), _never)[0]

    again = plan_actions(
        profile,
        _view(stage="accepted", data_version="AAAAAg=="),
        _card(),
        lambda kind, fp: (kind, fp) == (first.kind, first.fingerprint),
    )

    assert again == []


def test_visit_and_estimate_from_view() -> None:
    profile = _profile("unf")
    card = _card("accepted", "accepted")
    view = _view(
        stage="accepted",
        visit_start=datetime(2026, 9, 30, 10, 0, tzinfo=MSK),
        visit_amount_minor=150000,
        visit_items=("Выезд мастера (диагностика)",),
        estimate=(EstimateLine("Замена термостата", 320000), EstimateLine("Чистка", 0)),
    )

    planned = plan_actions(profile, view, card, _never)

    assert [a.kind for a in planned] == ["visit-proposal", "repair-quote"]
    visit = planned[0].body
    assert visit["visit_window_start"] == "2026-09-30T10:00:00+03:00"
    assert visit["visit_window_end"] == "2026-09-30T12:00:00+03:00"
    assert visit["amount_minor"] == 150000
    quote = planned[1].body
    assert quote["items"] == [
        {"title": "Замена термостата", "amount_minor": 320000},
        {"title": "Чистка", "amount_minor": 0},
    ]
    assert quote["amount_minor"] == 320000
    assert quote["description_of_work"].startswith("Смета по заказ-наряду ЗН00-000001")

    no_price = plan_actions(
        profile, _view(stage="accepted", visit_start=view.visit_start), card, _never
    )
    assert no_price == []


def test_existing_equal_proposal_is_not_duplicated() -> None:
    profile = _profile("unf")
    card = _card("scheduled", "accepted")
    card["visit_proposals"] = [
        {
            "status": "approved",
            "visit_window_start": "2026-09-30T07:00:00Z",
            "visit_window_end": "2026-09-30T09:00:00Z",
            "price": {"amount_minor": 150000},
        }
    ]
    view = _view(
        stage="accepted",
        visit_start=datetime(2026, 9, 30, 10, 0, tzinfo=MSK),
        visit_amount_minor=150000,
    )

    assert plan_actions(profile, view, card, _never) == []


def test_generic_profile_uses_attribute_amount() -> None:
    profile = _profile("generic")
    assert profile.visit is not None and profile.visit.amount.attribute == "СуммаВыезда"
    assert profile.state.catalog is None
    assert profile.state.stage_for("Принята") == "accepted"
    assert profile.attachments.mode == "none"


def test_message_planned_without_version() -> None:
    profile = _profile("unf")
    planned = plan_actions(profile, _view(stage="new", message="Когда удобно?"), _card(), _never)
    assert [a.kind for a in planned] == ["message"]
    assert planned[0].changes_version is False
    assert "expected_version" not in planned[0].body


def test_basic_auth_over_http_refused(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        Settings(onec_odata_url="http://1c.local/unf/odata/standard.odata")
    ok = Settings(
        onec_odata_url="http://onec-emulator:8082/x/odata/standard.odata", onec_allow_http=True
    )
    assert ok.verify_tls() is True
    assert Settings(onec_verify_tls="/etc/ssl/1c-ca.pem").verify_tls() == "/etc/ssl/1c-ca.pem"


def _cancellation_card(status: str = "pending") -> dict:
    card = _card("cancellation_pending", "accepted")
    card["cancellation"] = {"id": "can_1", "status": status, "previous_status": "accepted"}
    return card


def test_cancellation_response_by_stage() -> None:
    profile = _profile("unf")
    card = _cancellation_card()

    accept = plan_actions(profile, _view(stage="cancelled"), card, _never)
    assert [a.kind for a in accept] == ["cancellation-response"]
    assert accept[0].path == "cancellation-response"
    assert accept[0].body == {
        "assignment_id": "asg_1",
        "cancellation_id": "can_1",
        "decision": "accept",
        "expected_version": 7,
    }
    decline = plan_actions(
        profile,
        _view(stage="cancellation_declined", cancellation_comment="Мастер в пути"),
        card,
        _never,
    )
    assert decline[0].body["decision"] == "decline"
    assert decline[0].body["comment"] == "Мастер в пути"
    assert decline[0].fingerprint != accept[0].fingerprint
    default = plan_actions(profile, _view(stage="cancellation_declined"), card, _never)
    assert default[0].body["comment"] == "Исполнитель не согласен с отменой"

    assert plan_actions(profile, _view(stage="in_progress"), card, _never) == []
    assert (
        plan_actions(profile, _view(stage="cancelled"), _cancellation_card("disputed"), _never)
        == []
    )
    assert (
        plan_actions(profile, _view(stage="cancelled"), _card("accepted", "accepted"), _never) == []
    )
    revoked = _cancellation_card()
    revoked["assignment"]["state"] = "revoked"
    assert plan_actions(profile, _view(stage="cancelled"), revoked, _never) == []


def test_waiting_topic_blocks_until_document_changed() -> None:
    profile = _profile("unf")
    card = _cancellation_card()
    seen: list[str] = []

    def unchanged(topic: str) -> bool:
        seen.append(topic)
        return False

    assert plan_actions(profile, _view(stage="in_progress"), card, _never, unchanged) == []
    assert seen == ["cancellation:can_1"]
    assert plan_actions(profile, _view(stage="cancelled"), card, _never, unchanged) == []
    planned = plan_actions(profile, _view(stage="cancelled"), card, _never, lambda _t: True)
    assert [a.kind for a in planned] == ["cancellation-response"]


def test_complete_fingerprint_changes_after_rejection() -> None:
    profile = _profile("unf")
    first_round = _card("in_progress", "accepted")
    first = plan_actions(profile, _view(stage="done"), first_round, _never)[0]
    rejected = _card("in_progress", "accepted")
    rejected["completion_report"] = {"outcome": "resolved", "reported_at": "2026-09-19T12:00:00Z"}

    again = plan_actions(
        profile,
        _view(stage="done"),
        rejected,
        lambda kind, fp: (kind, fp) == (first.kind, first.fingerprint),
    )
    assert [a.kind for a in again] == ["complete"]
    assert again[0].fingerprint != first.fingerprint
    assert plan_actions(profile, _view(stage="done"), rejected, _never, lambda _t: False) == []


def test_same_visit_after_rejection_needs_document_change() -> None:
    profile = _profile("unf")
    card = _card("accepted", "accepted")
    card["visit_proposals"] = [
        {
            "id": "vp_1",
            "version": 1,
            "status": "rejected",
            "visit_window_start": "2026-09-30T07:00:00Z",
            "visit_window_end": "2026-09-30T09:00:00Z",
            "price": {"amount_minor": 150000},
        }
    ]
    view = _view(
        stage="accepted",
        visit_start=datetime(2026, 9, 30, 10, 0, tzinfo=MSK),
        visit_amount_minor=150000,
    )
    original = plan_actions(profile, view, _card("accepted", "accepted"), _never)[0]

    assert plan_actions(profile, view, card, _never, lambda _t: False) == []
    resent = plan_actions(
        profile,
        view,
        card,
        lambda kind, fp: (kind, fp) == (original.kind, original.fingerprint),
        lambda _t: True,
    )
    assert [a.kind for a in resent] == ["visit-proposal"]
    assert resent[0].fingerprint != original.fingerprint


def test_generic_profile_has_cancellation_states() -> None:
    profile = _profile("generic")
    assert profile.state.stage_for("Отменена") == "cancelled"
    assert profile.state.stage_for("ОтменаНеСогласована") == "cancellation_declined"
    assert profile.cancellation.decline_reason.source.attribute == "ПричинаНесогласияСОтменой"
