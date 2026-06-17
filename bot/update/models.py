from dataclasses import dataclass


@dataclass
class UpdateInfo:
    available: bool = False
    version: str | None = None
    notes: str = ""
    url: str | None = None
    sha256: str | None = None
