from typing import Annotated

from fastapi import APIRouter, Query

from app.adapters.http.errors import STANDARD_ERROR_RESPONSES
from app.adapters.integration_api.deps import EventsRead
from app.modules.integration import api as integration
from app.modules.integration.api import EventsPageView

router = APIRouter(tags=["events"], responses=STANDARD_ERROR_RESPONSES)


@router.get(
    "/events",
    response_model=EventsPageView,
    description=(
        "Лента восстановления после курсора. Истёкший курсор — "
        "`409 CURSOR_EXPIRED`: выполните сверку через `GET /requests` и начните "
        "ленту заново без курсора. В ленте только события, которые ключ получил бы "
        "и вебхуком — по scope на чтение соответствующих данных."
    ),
)
async def list_events(
    actor: EventsRead,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> EventsPageView:
    return await integration.list_events(actor, cursor=cursor, limit=limit)
