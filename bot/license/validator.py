import asyncio
import logging
from datetime import datetime

import httpx

from bot.license.models import LicenseResult, LicenseStatus

logger = logging.getLogger(__name__)


class LicenseValidator:
    def __init__(self, url: str) -> None:
        self._url = url
        self._license_key: str = ""
        self._mt5_account: int = 0
        self.license_valid: bool = False

    async def validate(self, license_key: str, mt5_account: int) -> LicenseResult:
        self._license_key = license_key
        self._mt5_account = mt5_account

        # Dev/contributor mode: no URL configured
        if not self._url:
            self.license_valid = True
            return LicenseResult(LicenseStatus.VALID, None, "No license URL (dev mode)")

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    self._url,
                    json={"license_key": license_key, "mt5_account": mt5_account},
                )
            if resp.status_code >= 400:
                result = LicenseResult(LicenseStatus.INVALID, None, f"HTTP {resp.status_code}")
            else:
                data = resp.json()
                raw_status = data.get("status", "error")
                try:
                    status = LicenseStatus(raw_status)
                except ValueError:
                    status = LicenseStatus.ERROR
                expires_raw = data.get("expires_at")
                expires_at = datetime.fromisoformat(expires_raw) if expires_raw else None
                result = LicenseResult(
                    status=status,
                    expires_at=expires_at,
                    message=data.get("message", ""),
                )
        except httpx.HTTPError as e:
            logger.error("License HTTP error: %s", e)
            result = LicenseResult(LicenseStatus.ERROR, None, str(e))
        except Exception as e:
            logger.error("License validate error", exc_info=True)
            result = LicenseResult(LicenseStatus.ERROR, None, str(e))

        self.license_valid = result.status == LicenseStatus.VALID
        logger.info("License: %s — %s", result.status.value, result.message)
        return result

    async def heartbeat_loop(self, interval_seconds: int) -> None:
        while True:
            await asyncio.sleep(interval_seconds)
            try:
                result = await self.validate(self._license_key, self._mt5_account)
                if not self.license_valid:
                    logger.warning(
                        "License heartbeat failed: %s — %s",
                        result.status.value,
                        result.message,
                    )
            except Exception:
                logger.error("License heartbeat unhandled error", exc_info=True)
                self.license_valid = False
