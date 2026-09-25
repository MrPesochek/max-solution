from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from connector.onec_client import OneCClient
from connector.onec_directory import Directory
from connector.platform_client import PlatformClient
from connector.profile import Profile
from connector.settings import Settings


@dataclass
class AppState:
    conn: sqlite3.Connection
    client: PlatformClient
    onec: OneCClient
    profile: Profile
    settings: Settings
    directory: Directory = field(init=False)
    background_tasks: set[asyncio.Task[None]] = field(default_factory=set)
    in_flight_events: set[str] = field(default_factory=set)
    _locks: dict[str, tuple[asyncio.Lock, int]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.directory = Directory(self.onec, self.profile)

    @asynccontextmanager
    async def lock_for(self, request_id: str) -> AsyncIterator[None]:
        lock, users = self._locks.get(request_id, (asyncio.Lock(), 0))
        self._locks[request_id] = (lock, users + 1)
        try:
            async with lock:
                yield
        finally:
            lock, users = self._locks[request_id]
            if users <= 1:
                del self._locks[request_id]
            else:
                self._locks[request_id] = (lock, users - 1)
