#!/usr/bin/env python3
"""One-command demo startup: `python scripts/dev.py`.

From a clean checkout this creates the backend virtualenv, installs both
dependency sets, seeds the synthetic demo data and runs the API and the UI
together. Stdlib only, so it works before anything is installed.

    python scripts/dev.py             # install what is missing, then run both
    python scripts/dev.py --reset     # additionally wipe and re-seed the demo data
    python scripts/dev.py --check     # install, seed, run tests/lint/build, exit
    python scripts/dev.py --api-only  # backend only
    python scripts/dev.py --ui-only   # frontend only (expects the API elsewhere)

Ctrl-C stops everything.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
API = REPO / "apps" / "api"
WEB = REPO / "apps" / "web"
VENV = API / ".venv"
WINDOWS = platform.system() == "Windows"
PY = VENV / ("Scripts" if WINDOWS else "bin") / ("python.exe" if WINDOWS else "python")
API_URL = "http://127.0.0.1:8000"
UI_URL = "http://localhost:5173"


#: ASCII only — the default Windows console codepage cannot encode much else.
def say(message: str) -> None:
    print(f"[dev] {message}", flush=True)


def run(cmd: list[str], cwd: Path) -> None:
    printable = " ".join(str(c) for c in cmd)
    say(printable)
    result = subprocess.run(cmd, cwd=str(cwd))
    if result.returncode != 0:
        sys.exit(f"failed ({result.returncode}): {printable}")


def npm() -> str:
    """npm is a shell script on POSIX and a .cmd shim on Windows."""
    found = shutil.which("npm.cmd" if WINDOWS else "npm") or shutil.which("npm")
    if not found:
        sys.exit("npm was not found on PATH. Install Node 18+ and try again.")
    return found


def ensure_backend() -> None:
    if not PY.exists():
        say("creating the backend virtualenv")
        run([sys.executable, "-m", "venv", str(VENV)], API)
    marker = VENV / ".deps-installed"
    pyproject = API / "pyproject.toml"
    if not marker.exists() or marker.stat().st_mtime < pyproject.stat().st_mtime:
        say("installing backend dependencies")
        run([str(PY), "-m", "pip", "install", "--quiet", "--upgrade", "pip"], API)
        run([str(PY), "-m", "pip", "install", "--quiet", "-e", ".[dev]"], API)
        marker.write_text("ok", encoding="utf-8")


def ensure_frontend() -> None:
    if not (WEB / "node_modules").exists():
        say("installing frontend dependencies (this takes a minute the first time)")
        run([npm(), "install"], WEB)


def seed(reset: bool) -> None:
    db = API / "var" / "wetstack.db"
    if reset or not db.exists():
        say("seeding synthetic demo data")
        run([str(PY), "-m", "app.seed", "--reset"], API)


def check() -> None:
    say("backend tests")
    run([str(PY), "-m", "pytest", str(REPO / "tests"), "-q"], API)
    say("backend lint")
    run([str(PY), "-m", "ruff", "check", "app", str(REPO / "tests")], API)
    say("frontend type-check")
    run([npm(), "run", "lint"], WEB)
    say("frontend production build")
    run([npm(), "run", "build"], WEB)
    print("\nAll checks passed.")


def wait_for_api(timeout: float = 45.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{API_URL}/api/health", timeout=2) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.5)
    return False


def serve(api_only: bool, ui_only: bool) -> None:
    procs: list[subprocess.Popen] = []
    # New process group so Ctrl-C reaches the children on both platforms.
    kwargs = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if WINDOWS else {}
    try:
        if not ui_only:
            say(f"starting the API on {API_URL}  (docs: {API_URL}/docs)")
            procs.append(
                subprocess.Popen(
                    [str(PY), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000", "--reload"],
                    cwd=str(API),
                    **kwargs,
                )
            )
            if not wait_for_api():
                say("the API did not become healthy in time — see its output above")
        if not api_only:
            say(f"starting the UI on {UI_URL}")
            procs.append(subprocess.Popen([npm(), "run", "dev"], cwd=str(WEB), **kwargs))

        print(f"\nReady.  UI: {UI_URL}   API docs: {API_URL}/docs   (Ctrl-C to stop)\n")
        while procs:
            for proc in list(procs):
                if proc.poll() is not None:
                    say(f"a process exited with code {proc.returncode}; shutting down")
                    return
            time.sleep(0.5)
    except KeyboardInterrupt:
        print()
    finally:
        for proc in procs:
            if proc.poll() is None:
                proc.send_signal(signal.CTRL_BREAK_EVENT if WINDOWS else signal.SIGTERM)
        for proc in procs:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        say("stopped")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reset", action="store_true", help="wipe and re-seed the demo data")
    parser.add_argument("--check", action="store_true", help="run tests, lint and builds, then exit")
    parser.add_argument("--api-only", action="store_true")
    parser.add_argument("--ui-only", action="store_true")
    args = parser.parse_args()

    os.chdir(REPO)
    if not args.ui_only:
        ensure_backend()
    if not args.api_only:
        ensure_frontend()
    if args.check:
        seed(args.reset)
        check()
        return
    if not args.ui_only:
        seed(args.reset)
    serve(args.api_only, args.ui_only)


if __name__ == "__main__":
    main()
