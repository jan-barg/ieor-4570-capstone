"""What is left on the metered services a video needs, asked from the services themselves (free calls).

    voice_credits_left()  -> 80000      # ElevenLabs characters left in this billing period, or None

None means "could not find out" (no key, a network error, an answer in another shape). The Gate treats
None as unknown: it does not pause new videos on it, since a broken meter should not close the site.

Why the Gate asks at all: the voice is the last paid step of a video. With the plan used up, every video
would fail there, after its searches and model calls were already paid (Nov 27 review). Tavily's own
check, tavily_credits_left(), is in core.py."""
from __future__ import annotations

import json
import urllib.request

from .. import keys

ELEVENLABS_SUBSCRIPTION = "https://api.elevenlabs.io/v1/user/subscription"


def voice_credits_left(timeout: float = 10.0) -> int | None:
    """ElevenLabs credits (characters) left: the plan's limit minus what this period has used."""
    return _ask_elevenlabs(timeout)


def _ask_elevenlabs(timeout: float = 10.0) -> int | None:
    try:
        req = urllib.request.Request(ELEVENLABS_SUBSCRIPTION, headers={"xi-api-key": keys.get("elevenlabs_api_key")})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.load(r)
        return int(d["character_limit"]) - int(d.get("character_count") or 0)
    except Exception:
        return None
