import uuid
from datetime import datetime, timedelta


class Quarantine:
    def __init__(self, *, base: timedelta, maximum: timedelta) -> None:
        self._base = base
        self._maximum = maximum
        self._held: dict[tuple[str, uuid.UUID], tuple[datetime, int]] = {}

    def held(self, kind: str, moment: datetime) -> set[uuid.UUID]:
        return {
            item_id
            for (stage, item_id), (until, _) in self._held.items()
            if stage == kind and until > moment
        }

    def hold(self, kind: str, item_id: uuid.UUID, moment: datetime) -> None:
        _, failures = self._held.get((kind, item_id), (moment, 0))
        pause = min(self._base * (2**failures), self._maximum)
        self._held[(kind, item_id)] = (moment + pause, failures + 1)

    def release(self, kind: str, item_id: uuid.UUID) -> None:
        self._held.pop((kind, item_id), None)

    def clear(self) -> None:
        self._held.clear()
