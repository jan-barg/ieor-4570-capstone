"""Copies the API keys into Secret Manager, one secret per name, for the Cloud Run website and job.

    .venv/bin/python -m scripts.push_secrets            # project agentic-ai-capstone-jgb2170
    .venv/bin/python -m scripts.push_secrets --dry-run  # only says which keys it found

Each key is read the way the code reads it (a real environment variable, then stringer/.env, then
the macOS Keychain; the MTS key also under its older Keychain name). A secret that exists gets a new
version, so running it again after changing a key is fine. Prints names only, never a value."""
from __future__ import annotations

import argparse
import subprocess

from stringer import feed, keys

PROJECT = "agentic-ai-capstone-jgb2170"
NAMES = ("ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "TAVILY_API_KEY", "GUARDIAN_API_KEY",
         "ELEVENLABS_API_KEY", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST")


def value(name: str) -> str | None:
    try:
        return feed.api_key() if name == "MTS_API_KEY" else keys.get(name.lower())
    except Exception:
        return None


def gcloud(args: list[str], data: str | None = None) -> bool:
    r = subprocess.run(["gcloud", *args], input=data, capture_output=True, text=True)
    return r.returncode == 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=PROJECT)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    for name in (*NAMES, "MTS_API_KEY"):
        v = value(name)
        if not v:
            print(f"  skip     {name} (not found)")
            continue
        if a.dry_run:
            print(f"  found    {name}")
            continue
        if gcloud(["secrets", "describe", name, "--project", a.project]):
            ok, what = gcloud(["secrets", "versions", "add", name, "--project", a.project, "--data-file=-"], v), "updated"
        else:
            ok, what = gcloud(["secrets", "create", name, "--project", a.project, "--replication-policy=automatic",
                               "--data-file=-"], v), "created"
        print(f"  {what if ok else 'FAILED':8} {name}")


if __name__ == "__main__":
    main()
