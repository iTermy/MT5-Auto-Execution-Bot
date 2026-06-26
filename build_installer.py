"""Build the version-agnostic online installer, dist/MT5Bot-Setup.exe.

    python build_installer.py

Reads UPDATE_MANIFEST_URL from .env and compiles installer/MT5Bot.iss with Inno
Setup's ISCC, passing the manifest URL as a /D define so nothing is hardcoded in the
committed script. The resulting installer downloads whatever version latest.json points
at, so you build this ONCE and re-upload it only if the installer logic itself changes —
never per release.

One-time prerequisite: install Inno Setup 6 (https://jrsoftware.org/isdl.php).
"""

import shutil
import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_ENV = _ROOT / ".env"
_ISS = _ROOT / "installer" / "MT5Bot.iss"

_ISCC_CANDIDATES = (
    Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
    Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
)


def _manifest_url() -> str:
    for line in _ENV.read_text().splitlines():
        s = line.strip()
        if s.startswith("UPDATE_MANIFEST_URL=") and not s.startswith("#"):
            return s.split("=", 1)[1].strip()
    raise SystemExit(".env is missing UPDATE_MANIFEST_URL")


def _find_iscc() -> str:
    found = shutil.which("ISCC") or next((str(p) for p in _ISCC_CANDIDATES if p.exists()), None)
    if not found:
        raise SystemExit(
            "ISCC.exe not found — install Inno Setup 6 from https://jrsoftware.org/isdl.php"
        )
    return found


def main() -> None:
    url = _manifest_url()
    iscc = _find_iscc()
    print(f"Building installer (manifest: {url}) ...")
    subprocess.run([iscc, f"/DManifestUrl={url}", str(_ISS)], cwd=_ROOT, check=True)
    print(f"\nBuilt {_ROOT / 'dist' / 'MT5Bot-Setup.exe'}")
    print("Distribute this to new users; upload it to your download page once.")


if __name__ == "__main__":
    main()
