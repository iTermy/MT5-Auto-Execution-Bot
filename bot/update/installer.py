import hashlib
import logging
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

import httpx

from bot.update.models import UpdateInfo

logger = logging.getLogger(__name__)

# Swap, then relaunch — robust to two Windows quirks:
#   1. The live exe's image file is locked while we're still running, so `move` is the
#      synchronization primitive: it fails until the old process exits, then succeeds.
#   2. A brand-new one-file exe can fail its first launch (the bootloader's self-extraction
#      races AV/Defender scanning the just-written file: "python3xx.dll … not found"). So we
#      let the swapped file settle, then launch and verify the process actually came up,
#      retrying a few times. `ping` is the console-independent sleep.
_UPDATER_BAT = """@echo off
set "log=%TEMP%\\mt5bot_update.log"
echo [%date% %time%] updater started > "%log%"
set /a tries=0
:wait
ping -n 2 127.0.0.1 >nul
move /Y "{staged}" "{target}" >nul 2>> "%log%"
if not errorlevel 1 goto swapped
set /a tries+=1
if %tries% geq 90 (
    echo [%date% %time%] giving up on swap >> "%log%"
    exit /b 1
)
goto wait
:swapped
echo [%date% %time%] swapped; settling before relaunch >> "%log%"
ping -n 6 127.0.0.1 >nul
set /a launch=0
:launch
echo [%date% %time%] launch attempt %launch% >> "%log%"
start "" "{target}"
ping -n 5 127.0.0.1 >nul
tasklist /FI "IMAGENAME eq {image}" 2>nul | find /I "{image}" >nul
if not errorlevel 1 goto launched
set /a launch+=1
if %launch% lss 4 goto launch
echo [%date% %time%] launch retries exhausted >> "%log%"
:launched
echo [%date% %time%] done >> "%log%"
del "%~f0"
"""

# CREATE_NO_WINDOW keeps a (hidden) console so console commands work; new process group
# detaches it from our Ctrl-C handling. DETACHED_PROCESS would leave it console-less,
# which breaks the batch interpreter's console-dependent commands.
_NO_WINDOW = 0x08000000 | 0x00000200


class UpdateInstaller:
    def _exe_path(self) -> Path:
        if not getattr(sys, "frozen", False):
            raise RuntimeError("Updates only work in the packaged build")
        return Path(sys.executable)

    async def download(self, info: UpdateInfo, progress_cb: Callable[[int], None]) -> Path:
        target = self._exe_path()
        staged = target.with_name(target.stem + ".new" + target.suffix)
        hasher = hashlib.sha256()
        downloaded = 0
        # No overall deadline (a slow link may take minutes), but abort if the connection
        # stalls so a dropped network can't wedge the UI in "Updating" forever.
        timeout = httpx.Timeout(connect=15.0, read=120.0, write=15.0, pool=15.0)
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                async with client.stream("GET", info.url) as resp:
                    resp.raise_for_status()
                    total = int(resp.headers.get("content-length", 0))
                    with staged.open("wb") as f:
                        async for chunk in resp.aiter_bytes(65536):
                            f.write(chunk)
                            hasher.update(chunk)
                            downloaded += len(chunk)
                            if total:
                                progress_cb(int(downloaded * 100 / total))
            if hasher.hexdigest().lower() != info.sha256.lower():
                staged.unlink(missing_ok=True)
                raise RuntimeError("Downloaded file failed integrity check")
        except Exception:
            staged.unlink(missing_ok=True)
            raise
        return staged

    def apply_and_restart(self, staged: Path) -> None:
        target = self._exe_path()
        script = _UPDATER_BAT.format(staged=staged, target=target, image=target.name)
        bat = Path(tempfile.gettempdir()) / "mt5bot_update.bat"
        bat.write_text(script)
        # Strip PyInstaller's one-file bootstrap vars from the child environment. They are
        # inherited through cmd → the relaunched exe, which would then treat itself as a
        # re-exec and look for python3xx.dll in OUR _MEI temp dir — about to be deleted as we
        # exit — instead of extracting fresh ("module could not be found"). Cleared, the new
        # exe does a normal cold-start extraction.
        env = {k: v for k, v in os.environ.items() if not k.startswith(("_MEIPASS", "_PYI"))}
        subprocess.Popen(
            ["cmd", "/c", str(bat)],
            creationflags=_NO_WINDOW,
            close_fds=True,
            env=env,
        )
        logger.info("Update staged — restarting to apply")
