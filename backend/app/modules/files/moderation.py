import uuid

from app.core import ids
from app.core.actor import Actor, OperatorActor
from app.core.errors import Forbidden, NotFound, ValidationFailed
from app.core.pipeline import CommandContext, CommandResult, Handler
from app.db.enums import ModerationStatus
from app.modules.files import queries
from app.modules.files.views import to_attachment_view

DECIDABLE = (ModerationStatus.PENDING, ModerationStatus.PUBLISHED, ModerationStatus.REJECTED)


def require_operator(actor: Actor) -> OperatorActor:
    if not isinstance(actor, OperatorActor):
        raise Forbidden("Действие доступно оператору платформы")
    return actor


def decide(attachment_id: uuid.UUID, *, approve: bool, reason: str | None) -> Handler:
    async def handler(ctx: CommandContext) -> CommandResult:
        require_operator(ctx.actor)
        if not approve and not (reason or "").strip():
            raise ValidationFailed("Решение об отклонении требует основания", field="reason")
        attachment = await queries.get_attachment(ctx.session, attachment_id)
        case = await queries.publication_case(ctx.session, attachment_id)
        if case is None or case.status not in DECIDABLE:
            raise NotFound()
        case.status = ModerationStatus.PUBLISHED if approve else ModerationStatus.REJECTED
        case.decision_reason = reason
        case.operator_user_id = ctx.actor.user_id if isinstance(ctx.actor, OperatorActor) else None
        attachment.publication_state = case.status
        ctx.audit(
            "attachment.moderate",
            "attachment",
            attachment_id,
            decision=case.status,
        )
        return CommandResult(to_attachment_view(attachment).model_dump(mode="json"))

    return handler


def encode_cursor(value: uuid.UUID | None) -> str | None:
    return ids.encode_opt("moderation_case", value)
