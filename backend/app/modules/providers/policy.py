from app.core.actor import Actor, UserActor, require_roles
from app.core.errors import Forbidden, InvalidTransition
from app.db.enums import MembershipRole, ProviderProfileStatus

REQUISITE_EDIT_STATUSES = frozenset(
    {ProviderProfileStatus.DRAFT, ProviderProfileStatus.NEEDS_INFORMATION}
)
PROFILE_EDIT_STATUSES = REQUISITE_EDIT_STATUSES | {
    ProviderProfileStatus.ACTIVE,
    ProviderProfileStatus.PENDING_REVIEW,
}
SUBMIT_STATUSES = REQUISITE_EDIT_STATUSES


def require_provider_admin(actor: Actor) -> UserActor:
    return require_roles(actor, MembershipRole.PROVIDER_ADMIN)


def require_provider_side(actor: Actor) -> UserActor:
    return require_roles(actor, MembershipRole.PROVIDER_ADMIN, MembershipRole.PROVIDER_DISPATCHER)


def check_editable(status: str) -> None:
    if status not in PROFILE_EDIT_STATUSES:
        raise InvalidTransition("Профиль нельзя изменить в текущем состоянии")


def check_requisites_editable(status: str) -> None:
    if status not in REQUISITE_EDIT_STATUSES:
        raise InvalidTransition(
            "Изменение реквизитов проверенного профиля выполняется через оператора",
            code="REVERIFICATION_REQUIRED",
        )


def check_submittable(status: str) -> None:
    if status not in SUBMIT_STATUSES:
        raise InvalidTransition("Профиль уже отправлен на проверку или проверен")


def check_accepting_allowed(status: str) -> None:
    """Переключатель «принимаю новые заявки» доступен только допущенному профилю (ТЗ 6.2.4)."""
    if status != ProviderProfileStatus.ACTIVE:
        raise InvalidTransition("Приём заявок доступен только допущенному профилю")


def require_own_organization(actor: UserActor, organization_id: object) -> None:
    if actor.organization_id != organization_id:
        raise Forbidden()
