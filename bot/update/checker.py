import logging

import httpx

from bot.config.constants import BOT_VERSION
from bot.update.models import UpdateInfo

logger = logging.getLogger(__name__)


def _parse(version: str) -> tuple[int, ...]:
    return tuple(int(p) for p in version.strip().split("."))


def _is_newer(latest: str, current: str) -> bool:
    try:
        return _parse(latest) > _parse(current)
    except ValueError:
        return False


class UpdateChecker:
    def __init__(self, manifest_url: str, current_version: str = BOT_VERSION) -> None:
        self._url = manifest_url
        self._current = current_version
        self.info = UpdateInfo()

    async def check(self) -> None:
        if not self._url:
            return
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(self._url)
            resp.raise_for_status()
            data = resp.json()
            version = str(data["version"])
            if _is_newer(version, self._current):
                self.info = UpdateInfo(
                    available=True,
                    version=version,
                    notes=str(data.get("notes", "")),
                    url=str(data["url"]),
                    sha256=str(data["sha256"]),
                )
            else:
                self.info = UpdateInfo()
        except (httpx.HTTPError, KeyError, ValueError):
            logger.warning("Update check failed", exc_info=True)
