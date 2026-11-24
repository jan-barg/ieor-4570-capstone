"""API keys come from stringer/.env (git-ignored), one UPPER_CASE name per line, e.g.
ANTHROPIC_API_KEY=... (see .env.example). A real environment variable of the same name wins
over the file (Cloud Run later). The macOS Keychain is a fallback for keys stored there before
Nov 24. Values are never printed or logged."""
import functools
import os
import subprocess
from pathlib import Path

from dotenv import load_dotenv

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(ENV_FILE, override=False)


class MissingKey(RuntimeError):
    pass


@functools.lru_cache(maxsize=None)
def get(service: str) -> str:
    env = os.environ.get(service.upper())
    if env:
        return env
    r = subprocess.run(["security", "find-generic-password", "-s", service, "-w"],
                       capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        raise MissingKey(f"{service.upper()} not set: add it to {ENV_FILE}")
    return r.stdout.strip()


def has(service: str) -> bool:
    try:
        get(service)
        return True
    except MissingKey:
        return False
