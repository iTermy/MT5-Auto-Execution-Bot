from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class LicenseStatus(str, Enum):
    VALID = "valid"
    INVALID = "invalid"
    EXPIRED = "expired"
    ERROR = "error"


@dataclass
class LicenseResult:
    status: LicenseStatus
    expires_at: datetime | None
    message: str
