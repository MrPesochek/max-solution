from datetime import datetime

from app.modules.files import api as files


async def run_once(now: datetime) -> int:
    return await files.process_images(now)


async def run_cleanup(now: datetime) -> int:
    return await files.cleanup_files(now)
