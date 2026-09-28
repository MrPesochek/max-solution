from __future__ import annotations

import io
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import update

from app.core import ids
from app.core.actor import OperatorActor, UserActor
from app.core.clock import utcnow
from app.db import session as db_session
from app.db.enums import ModerationStatus
from app.db.models import Review, VisitProposal
from app.modules.files import api as files
from app.modules.reputation.api import ReviewSubmitData, decide_review, submit_review
from app.modules.requests.api import (
    OfferInput,
    RepairQuoteInput,
    RepairQuoteItemInput,
    VisitProposalInput,
    accept_assignment,
    approve_repair_quote,
    approve_visit_proposal,
    cancel_draft,
    confirm_completion,
    create_draft,
    create_repair_quote,
    post_dialog_message,
    post_message,
    propose_visit,
    publish_search,
    report_completion,
    request_approval,
    select_offer,
    start_work,
    submit_offer,
    submit_to_own_service,
)

RUB = "RUB"
VAT = "included"


@dataclass(frozen=True, slots=True)
class Cast:
    """Участники и оборудование сценариев."""

    manager: UserActor
    employee: UserActor
    bakery_manager: UserActor
    provider_admin: UserActor
    provider_dispatcher: UserActor
    ext: dict[str, UserActor]
    operator: OperatorActor
    equipment: dict[str, uuid.UUID]
    timezone: str


class _Clock:
    """Местное время города стенда: окна выезда задаются «завтра 15:00», а не в UTC."""

    def __init__(self, timezone: str) -> None:
        self.tz = ZoneInfo(timezone)
        self.now = utcnow()

    def at(self, days: int, hour: int, minute: int = 0) -> datetime:
        day = self.now.astimezone(self.tz).date() + timedelta(days=days)
        return datetime(day.year, day.month, day.day, hour, minute, tzinfo=self.tz)

    def after(self, **delta: float) -> datetime:
        return utcnow() + timedelta(**delta)


def jpeg(caption: str, color: tuple[int, int, int]) -> bytes:
    image = Image.new("RGB", (960, 720), color)
    draw = ImageDraw.Draw(image)
    draw.text((48, 620), caption, font=ImageFont.load_default(size=44), fill=(255, 255, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=85)
    return buffer.getvalue()


async def one_chunk(data: bytes) -> AsyncIterator[bytes]:
    yield data


async def _attach(
    actor: UserActor,
    request_id: uuid.UUID,
    slot: str,
    caption: str,
    color: tuple[int, int, int],
) -> None:
    await files.upload_attachment(
        actor,
        owner=files.request_owner(request_id),
        purpose=slot,
        filename_hint=f"{slot}.jpg",
        content_type_hint="image/jpeg",
        stream=one_chunk(jpeg(caption, color)),
    )


def _request_id(body: dict[str, object]) -> uuid.UUID:
    return ids.decode("request", str(body["id"]))


async def _own_service(
    actor: UserActor, equipment_id: uuid.UUID, symptom: str, *, urgency: str = "normal"
) -> tuple[uuid.UUID, uuid.UUID]:
    """Черновик и отправка своему сервису: (заявка, назначение)."""
    result = await create_draft(
        actor,
        equipment_id=equipment_id,
        route="own_service",
        urgency=urgency,
        symptom_description=symptom,
    )
    request_id = _request_id(result.body)
    result = await submit_to_own_service(actor, request_id)
    return request_id, ids.decode("assignment", result.body["assignment"]["id"])


async def _propose(
    actor: UserActor,
    request_id: uuid.UUID,
    assignment_id: uuid.UUID,
    *,
    start: datetime,
    end: datetime,
    amount_minor: int,
    valid_until: datetime | None,
    scope: str,
    comment: str | None = None,
) -> tuple[uuid.UUID, int]:
    result = await propose_visit(
        actor,
        request_id,
        assignment_id=assignment_id,
        data=VisitProposalInput(
            visit_window_start=start,
            visit_window_end=end,
            amount_minor=amount_minor,
            currency=RUB,
            vat_mode=VAT,
            scope_description=scope,
            comment=comment,
            valid_until=valid_until,
        ),
    )
    proposal = result.body["visit_proposals"][0]
    return ids.decode("visit_proposal", proposal["id"]), int(proposal["version"])


async def _agreed_visit(
    cast: Cast,
    clock: _Clock,
    request_id: uuid.UUID,
    assignment_id: uuid.UUID,
    *,
    amount_minor: int,
    start: datetime,
    end: datetime,
) -> None:
    """Сервис принял заявку, руководитель согласовал выезд — `scheduled`.

    Ядро не согласует уже прошедшее окно (ТЗ 8.1). Для выезда из истории стенда
    согласуется ближайшее окно той же длины, затем оно переносится на заданное время.
    """
    await accept_assignment(cast.provider_admin, request_id, assignment_id=assignment_id)
    past = end <= utcnow()
    agreed_start, agreed_end = (
        (clock.after(hours=1), clock.after(hours=1) + (end - start)) if past else (start, end)
    )
    proposal_id, version = await _propose(
        cast.provider_dispatcher,
        request_id,
        assignment_id,
        start=agreed_start,
        end=agreed_end,
        amount_minor=amount_minor,
        valid_until=clock.after(days=1),
        scope="Выезд и диагностика до 1 часа",
    )
    await approve_visit_proposal(
        cast.manager, request_id, proposal_id=proposal_id, proposal_version=version
    )
    if past:
        async with db_session.transaction() as session:
            await session.execute(
                update(VisitProposal)
                .where(VisitProposal.id == proposal_id)
                .values(visit_window_start=start, visit_window_end=end)
            )


async def _quote(
    actor: UserActor,
    request_id: uuid.UUID,
    assignment_id: uuid.UUID,
    description: str,
    items: tuple[tuple[str, int], ...],
    valid_until: datetime,
) -> tuple[uuid.UUID, int]:
    result = await create_repair_quote(
        actor,
        request_id,
        assignment_id=assignment_id,
        data=RepairQuoteInput(
            description_of_work=description,
            currency=RUB,
            vat_mode=VAT,
            valid_until=valid_until,
            items=tuple(RepairQuoteItemInput(title=t, amount_minor=a) for t, a in items),
            warranty_terms="Гарантия на выполненные работы — 3 месяца",
        ),
    )
    quote = result.body["repair_quotes"][0]
    return ids.decode("repair_quote", quote["id"]), int(quote["version"])


async def _offer(
    actor: UserActor,
    request_id: uuid.UUID,
    *,
    start: datetime,
    end: datetime,
    amount_minor: int | None,
    valid_until: datetime,
    scope: str,
    comment: str | None = None,
    access: str | None = None,
) -> tuple[uuid.UUID, int]:
    result = await submit_offer(
        actor,
        request_id,
        data=OfferInput(
            visit_window_start=start,
            visit_window_end=end,
            amount_minor=amount_minor,
            currency=RUB if amount_minor is not None else None,
            vat_mode=VAT if amount_minor is not None else None,
            scope_description=scope,
            comment=comment,
            access_requirements=access,
            valid_until=valid_until,
        ),
    )
    return ids.decode("offer", str(result.body["id"])), int(result.body["version"])


async def _visit_to_approve(cast: Cast, clock: _Clock) -> None:
    """«Согласуйте выезд»: сервис принял заявку и предложил выезд на завтра."""
    request_id, assignment_id = await _own_service(
        cast.manager,
        cast.equipment["equipment_1"],
        "Витрина не держит температуру: днём +9 °C вместо +4 °C, компрессор почти не выключается.",
        urgency="urgent",
    )
    await accept_assignment(cast.provider_admin, request_id, assignment_id=assignment_id)
    await _propose(
        cast.provider_dispatcher,
        request_id,
        assignment_id,
        start=clock.at(1, 15),
        end=clock.at(1, 18),
        amount_minor=350000,
        valid_until=clock.after(days=1),
        scope="Выезд и диагностика до 1 часа",
        comment="Мастер позвонит за 30 минут до приезда.",
    )


async def _visit_changed(cast: Cast, clock: _Clock) -> None:
    """«Условия изменились»: вторая версия предложения выезда с новой ценой."""
    request_id, assignment_id = await _own_service(
        cast.manager,
        cast.equipment["equipment_4"],
        "Шкаф сильно шумит и покрывается инеем по задней стенке.",
    )
    await accept_assignment(cast.provider_admin, request_id, assignment_id=assignment_id)
    await _propose(
        cast.provider_dispatcher,
        request_id,
        assignment_id,
        start=clock.at(1, 10),
        end=clock.at(1, 13),
        amount_minor=350000,
        valid_until=clock.after(days=1),
        scope="Выезд и диагностика до 1 часа",
    )
    await _propose(
        cast.provider_dispatcher,
        request_id,
        assignment_id,
        start=clock.at(2, 10),
        end=clock.at(2, 13),
        amount_minor=420000,
        valid_until=clock.after(days=1),
        scope="Выезд двух мастеров, диагностика и оттайка испарителя",
        comment="Шкаф придётся отодвинуть от стены — поедут два мастера, поэтому "
        "выезд перенесли на послезавтра.",
    )


async def _search_with_offers(cast: Cast, clock: _Clock) -> None:
    """Внешний поиск: три отклика, один «после осмотра», и вопрос кандидата."""
    result = await create_draft(
        cast.manager,
        equipment_id=cast.equipment["equipment_3"],
        route="marketplace",
        urgency="normal",
        symptom_description="Льдогенератор перестал делать лёд, горит индикатор воды.",
    )
    request_id = _request_id(result.body)
    await publish_search(cast.manager, request_id)
    await _offer(
        cast.ext["ext_provider_2"],
        request_id,
        start=clock.at(1, 13),
        end=clock.at(1, 15),
        amount_minor=400000,
        valid_until=clock.after(days=1),
        scope="Выезд и диагностика, чистка водяного клапана",
    )
    await _offer(
        cast.ext["ext_provider_4"],
        request_id,
        start=clock.at(1, 16),
        end=clock.at(1, 18),
        amount_minor=200000,
        valid_until=clock.after(days=1),
        scope="Выезд и диагностика",
        access="Доступ к розетке и крану подачи воды",
    )
    await _offer(
        cast.ext["ext_provider_3"],
        request_id,
        start=clock.at(2, 9),
        end=clock.at(2, 11),
        amount_minor=None,
        valid_until=clock.after(days=2),
        scope="Осмотр, стоимость назову на месте",
    )
    await post_dialog_message(
        cast.ext["ext_provider_3"],
        request_id,
        body="Льдогенератор подключён через фильтр? Если картридж давно не меняли, привезу новый.",
    )


async def _search_without_offers(cast: Cast, clock: _Clock) -> None:
    """Поиск только открыт: откликов нет, исполнитель уточняет детали."""
    result = await create_draft(
        cast.manager,
        equipment_id=cast.equipment["equipment_9"],
        route="marketplace",
        urgency="normal",
        symptom_description="Холодильная камера не выходит на режим, внешний блок "
        "отключается через 10 минут.",
    )
    request_id = _request_id(result.body)
    await publish_search(cast.manager, request_id)
    await post_dialog_message(
        cast.provider_admin,
        request_id,
        body="Где стоит внешний блок — на крыше или на фасаде? Нужна ли вышка?",
    )


async def _repair_to_approve(cast: Cast, clock: _Clock) -> None:
    """«Согласуйте ремонт»: мастер на месте, смета с позициями ждёт решения."""
    request_id, assignment_id = await _own_service(
        cast.manager,
        cast.equipment["equipment_6"],
        "Витрина не включается после отключения света, слышен щелчок.",
    )
    await _agreed_visit(
        cast,
        clock,
        request_id,
        assignment_id,
        amount_minor=420000,
        start=clock.after(hours=-2),
        end=clock.after(hours=1),
    )
    await start_work(cast.provider_admin, request_id, assignment_id=assignment_id)
    await _quote(
        cast.provider_dispatcher,
        request_id,
        assignment_id,
        "Замена пускового реле и заправка фреоном",
        (("Пусковое реле", 190000), ("Заправка фреоном", 380000), ("Работа", 100000)),
        clock.after(days=1),
    )


async def _incoming_with_photos(cast: Cast, clock: _Clock) -> None:
    """Входящая заявка своему сервису с фото — ждёт ответа исполнителя."""
    result = await create_draft(
        cast.manager,
        equipment_id=cast.equipment["equipment_10"],
        route="own_service",
        urgency="normal",
        symptom_description="Ларь не морозит, на табло ошибка E05.",
        error_code="E05",
    )
    request_id = _request_id(result.body)
    await _attach(cast.manager, request_id, "overview", "Chest freezer - overview", (60, 90, 120))
    await _attach(cast.manager, request_id, "display_error", "Display - E05", (140, 50, 50))
    await submit_to_own_service(cast.manager, request_id)


async def _incoming_from_bakery(cast: Cast, clock: _Clock) -> None:
    """Срочная входящая от второго заказчика со своим договором."""
    await _own_service(
        cast.bakery_manager,
        cast.equipment["bakery_1"],
        "Камера с тестом нагрелась до +12 °C, утром выпечка.",
        urgency="urgent",
    )


async def _incoming_clarification(cast: Cast, clock: _Clock) -> None:
    """«Уточнение»: исполнитель задал вопрос до принятия, заказчик ещё не ответил."""
    request_id, assignment_id = await _own_service(
        cast.employee,
        cast.equipment["equipment_8"],
        "Подсветка витрины мигает, стекло запотевает изнутри.",
    )
    await post_message(
        cast.provider_admin,
        request_id,
        assignment_id=assignment_id,
        body="Витрина ещё на гарантии производителя? Если да, пришлите, пожалуйста, "
        "фото гарантийного талона.",
    )


async def _visit_scheduled(cast: Cast, clock: _Clock) -> None:
    """«Выезд согласован» на завтра — у исполнителя во вкладке «В работе»."""
    request_id, assignment_id = await _own_service(
        cast.manager,
        cast.equipment["equipment_11"],
        "Льдогенератор выдаёт мелкий мутный лёд и подтекает.",
    )
    await _agreed_visit(
        cast,
        clock,
        request_id,
        assignment_id,
        amount_minor=350000,
        start=clock.at(1, 10),
        end=clock.at(1, 12),
    )


async def _marketplace_in_progress(cast: Cast, clock: _Clock) -> None:
    """Выбран внешний исполнитель с биржи, мастер уже работает."""
    result = await create_draft(
        cast.manager,
        equipment_id=cast.equipment["equipment_5"],
        route="marketplace",
        urgency="urgent",
        symptom_description="Сплит-система камеры не держит режим, температура +8 °C.",
    )
    request_id = _request_id(result.body)
    await publish_search(cast.manager, request_id)
    ext1 = cast.ext["ext_provider_1"]
    offer_id, version = await _offer(
        ext1,
        request_id,
        start=clock.after(hours=-1),
        end=clock.after(hours=2),
        amount_minor=250000,
        valid_until=clock.after(days=1),
        scope="Выезд, диагностика и дозаправка контура при необходимости",
    )
    result = await select_offer(cast.manager, request_id, offer_id=offer_id, offer_version=version)
    assignment_id = ids.decode("assignment", result.body["assignment"]["id"])
    await accept_assignment(ext1, request_id, assignment_id=assignment_id)
    await start_work(ext1, request_id, assignment_id=assignment_id)


async def _completion_reported(cast: Cast, clock: _Clock) -> None:
    """Отчёт мастера с фото «до» и «после» ждёт подтверждения руководителя."""
    request_id, assignment_id = await _own_service(
        cast.manager,
        cast.equipment["equipment_7"],
        "Холодильный стол не охлаждает, компрессор щёлкает и не запускается.",
    )
    await _agreed_visit(
        cast,
        clock,
        request_id,
        assignment_id,
        amount_minor=350000,
        start=clock.after(hours=-4),
        end=clock.after(hours=-1),
    )
    await start_work(cast.provider_admin, request_id, assignment_id=assignment_id)
    quote_id, quote_version = await _quote(
        cast.provider_admin,
        request_id,
        assignment_id,
        "Замена пускового реле",
        (("Пусковое реле", 190000), ("Работа", 290000)),
        clock.after(days=1),
    )
    await approve_repair_quote(
        cast.manager, request_id, quote_id=quote_id, quote_version=quote_version
    )
    await _attach(cast.provider_admin, request_id, "before", "Before - relay", (90, 70, 60))
    await _attach(cast.provider_admin, request_id, "after", "After - +3 C", (40, 120, 80))
    await report_completion(
        cast.provider_admin,
        request_id,
        assignment_id=assignment_id,
        outcome="resolved",
        summary="Заменил пусковое реле. Через 40 минут камера держит +3 °C.",
    )


async def _closed_with_review(cast: Cast, clock: _Clock) -> None:
    """Полный цикл до закрытия с опубликованным отзывом."""
    request_id, assignment_id = await _own_service(
        cast.manager,
        cast.equipment["equipment_2"],
        "Морозильный ларь не морозит, слышен стук компрессора.",
        urgency="urgent",
    )
    await _agreed_visit(
        cast,
        clock,
        request_id,
        assignment_id,
        amount_minor=150000,
        start=clock.after(hours=-6),
        end=clock.after(hours=-4),
    )
    await start_work(cast.provider_admin, request_id, assignment_id=assignment_id)
    await report_completion(
        cast.provider_admin,
        request_id,
        assignment_id=assignment_id,
        outcome="resolved",
        summary="Заменён компрессор, ларь вышел на −18 °C.",
    )
    await confirm_completion(cast.manager, request_id)
    review = await submit_review(
        cast.manager,
        request_id,
        ReviewSubmitData(
            rating=4,
            text="Отремонтировали быстро, но мастер приехал на час позже согласованного окна.",
        ),
        idem=None,
    )
    async with db_session.get_sessionmaker()() as session:
        row = await session.get(Review, ids.decode("review", review.body["id"]))
        assert row is not None
        review_id = row.id
    await decide_review(cast.operator, review_id, ModerationStatus.PUBLISHED.value, None, idem=None)


async def _cancelled(cast: Cast, clock: _Clock) -> None:
    result = await create_draft(
        cast.manager,
        equipment_id=cast.equipment["equipment_2"],
        route="own_service",
        urgency="normal",
        symptom_description="Ларь снова гудит громче обычного.",
    )
    await cancel_draft(
        cast.manager,
        _request_id(result.body),
        reason="После перезапуска ларь работает тихо, ремонт не нужен.",
    )


async def _employee_draft(cast: Cast, clock: _Clock) -> None:
    await create_draft(
        cast.employee,
        equipment_id=cast.equipment["equipment_12"],
        route="own_service",
        urgency="normal",
        symptom_description="Дверь шкафа перестала плотно закрываться.",
    )


async def _employee_approval(cast: Cast, clock: _Clock) -> None:
    """Сотрудник отправил черновик руководителю на согласование."""
    result = await create_draft(
        cast.employee,
        equipment_id=cast.equipment["equipment_13"],
        route="marketplace",
        urgency="normal",
        symptom_description="Морозильник не выходит на −18 °C, мороженое подтаивает.",
    )
    await request_approval(
        cast.employee,
        _request_id(result.body),
        comment="Своего сервиса на этот ларь нет — нужно найти мастера.",
    )


SCENARIOS = (
    _visit_to_approve,
    _visit_changed,
    _search_with_offers,
    _search_without_offers,
    _repair_to_approve,
    _incoming_with_photos,
    _incoming_from_bakery,
    _incoming_clarification,
    _visit_scheduled,
    _marketplace_in_progress,
    _completion_reported,
    _closed_with_review,
    _cancelled,
    _employee_draft,
    _employee_approval,
)


async def create_all(cast: Cast) -> int:
    clock = _Clock(cast.timezone)
    for scenario in SCENARIOS:
        await scenario(cast, clock)
    while await files.process_images(utcnow()):
        pass
    return len(SCENARIOS)
