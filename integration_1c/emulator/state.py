from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from emulator.settings import Settings


@dataclass
class EmulatorState:
    conn: sqlite3.Connection
    settings: Settings
