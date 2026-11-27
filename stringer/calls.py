"""Two small helpers every model step shares.

    text, error = calls.call(complete, messages, params, name)    # one call; a failed call is an empty answer
    complete = calls.live_complete("lens", trace_id=tid)          # models.complete bound to a step

`complete(messages, name=..., **params)` returns an object with .text: models.complete with its step
bound (live_complete), or an eval runner's ctx.complete. Each step keeps its own way of reading the
answer and its own retry note; what they share is that a failed call (a timeout, a provider error)
counts as an empty answer, so the step's one retry follows, while a cost cap's error goes through.

Before Nov 27 this was written out three times (brief_read, lens, gate/policy), and live_complete twice."""
from __future__ import annotations

from . import models


def call(complete, messages, params, name) -> tuple[str, str | None]:
    """(the answer's text, None), or ("", why) when the call failed. An error named BudgetExceeded is the
    one that must stop a run (an eval's cost cap, a story's spend cap), so it is raised."""
    try:
        return complete(messages, name=name, **params).text or "", None
    except Exception as e:
        if type(e).__name__ == "BudgetExceeded":
            raise
        return "", f"{type(e).__name__}: {e}"[:300]


def live_complete(step: str, trace_id=None, metadata=None, model: str | None = None):
    """A `complete` for live runs: models.complete with the model config/models.toml names for the step
    (or `model`, an alias, instead)."""
    def complete(messages, name=None, **params):
        return models.complete(step, messages, model=model, trace_id=trace_id, name=name, metadata=metadata,
                               **params)
    return complete
