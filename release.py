"""One-command release build for the shipped MT5Bot.exe.

    python release.py [VERSION] [--notes "..."]

Bakes SUPABASE_DSN, LICENSE_API_URL and UPDATE_MANIFEST_URL from .env into
bot/config/constants.py, builds the frontend and the one-file exe, then restores
constants.py to blank secrets (keeping the version) — even if the build fails. Outputs:

    dist/MT5Bot.exe                  distribute this to users (version-agnostic name)
    dist/releases/MT5Bot-<ver>.exe   upload to the Supabase `releases` bucket
    dist/releases/latest.json        upload to the bucket *last*

One-time prerequisites: fill .env, and `cd frontend && npm install`.
"""

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_CONSTANTS = _ROOT / "bot" / "config" / "constants.py"
_ENV = _ROOT / ".env"
_DIST = _ROOT / "dist"
_RELEASES = _DIST / "releases"
_MIN_SUPPORTED = "1.0.0"


def _load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for line in _ENV.read_text().splitlines():
        s = line.strip()
        if "=" in s and not s.startswith("#"):
            k, v = s.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def _set_constant(text: str, name: str, value: str) -> str:
    # Function replacement so backslashes/`\g` in the value aren't treated as group refs.
    return re.sub(rf"{name}: str = .*", lambda _m: f'{name}: str = "{value}"', text)


def _blank_secrets(text: str) -> str:
    for name in ("_PRODUCTION_DSN", "_PRODUCTION_LICENSE_URL", "_PRODUCTION_UPDATE_MANIFEST_URL"):
        text = _set_constant(text, name, "")
    return text


def main() -> None:
    ap = argparse.ArgumentParser(description="Build a distributable MT5Bot release.")
    ap.add_argument("version", nargs="?", help="New version, e.g. 1.3.3 (default: keep current)")
    ap.add_argument("--notes", default="", help="Release notes shown in the update prompt")
    args = ap.parse_args()

    env = _load_env()
    missing = [k for k in ("SUPABASE_DSN", "UPDATE_MANIFEST_URL") if not env.get(k)]
    if missing:
        raise SystemExit(f".env is missing required key(s): {', '.join(missing)}")
    manifest_url = env["UPDATE_MANIFEST_URL"]

    text = _CONSTANTS.read_text()
    if args.version:
        text = _set_constant(text, "BOT_VERSION", args.version)
        _CONSTANTS.write_text(text)
    match = re.search(r'BOT_VERSION: str = "([^"]+)"', text)
    if match is None:
        raise SystemExit("BOT_VERSION not found in constants.py")
    version = match.group(1)
    notes = args.notes or f"Update to {version}."
    exe_url = f"{manifest_url.rsplit('/', 1)[0]}/MT5Bot-{version}.exe"

    print(f"Building MT5Bot {version} ...")
    try:
        baked = _set_constant(text, "_PRODUCTION_DSN", env["SUPABASE_DSN"])
        baked = _set_constant(baked, "_PRODUCTION_LICENSE_URL", env.get("LICENSE_API_URL", ""))
        baked = _set_constant(baked, "_PRODUCTION_UPDATE_MANIFEST_URL", manifest_url)
        _CONSTANTS.write_text(baked)

        subprocess.run("npm run build", cwd=_ROOT / "frontend", shell=True, check=True)
        subprocess.run(
            [sys.executable, "-m", "PyInstaller", "--noconfirm", "bot.spec"],
            cwd=_ROOT,
            check=True,
        )

        _RELEASES.mkdir(parents=True, exist_ok=True)
        dist_exe = _DIST / "MT5Bot.exe"
        release_exe = _RELEASES / f"MT5Bot-{version}.exe"
        release_exe.write_bytes(dist_exe.read_bytes())
        sha = hashlib.sha256(release_exe.read_bytes()).hexdigest()
        manifest = {
            "version": version,
            "url": exe_url,
            "sha256": sha,
            "notes": notes,
            "min_supported": _MIN_SUPPORTED,
        }
        (_RELEASES / "latest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    finally:
        _CONSTANTS.write_text(_blank_secrets(_CONSTANTS.read_text()))
        for pyc in (_ROOT / "bot").rglob("*.pyc"):
            pyc.unlink(missing_ok=True)

    print(f"\nBuilt {version}  sha256={sha}")
    print(f"  distribute : {dist_exe}")
    print(f"  upload     : {release_exe}")
    print(f"  upload     : {_RELEASES / 'latest.json'}  (upload this LAST)")
    print("Commit the version bump in constants.py - secrets are already blanked back out.")


if __name__ == "__main__":
    main()
