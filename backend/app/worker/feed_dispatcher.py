from datetime import datetime

from app.modules.integration import api as integration


async def run_once(now: datetime) -> int:
    return await integration.assign_feed_seq(now)
