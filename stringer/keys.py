"""API keys come only from the macOS Keychain (or an environment variable of the same
name in upper case, for Cloud Run later). Values are never printed or logged."""
import functools
import os
import subprocess


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
        raise MissingKey(f"Keychain item '{service}' not found")
    return r.stdout.strip()


def has(service: str) -> bool:
    try:
        get(service)
        return True
    except MissingKey:
        return False
