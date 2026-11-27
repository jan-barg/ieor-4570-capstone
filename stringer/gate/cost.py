"""What a video will cost, worked out before the money is spent (Jan, Nov 26: the $5 cap should be
"pre-computed instead of just wasting five dollars and not yielding a video").

The idea: every step's token use on the test stories is known (config/gate.toml, the 95th
percentile per story), and every step's model has a price (config/models.toml). Multiply and add,
plus searches and the voice. The Gate asks twice:
  1. at the click, with the usual number of articles ("start");
  2. after the searches, the same-story filter and the pick, with the number of articles that will be
     read ("after_gather"), before the steps that cost most. Too dear here means the video stops having
     spent only a few cents of searching.

Example: with today's models a video estimates at $0.66 at the click. A real video cost $0.12 to $0.22
on the four live runs of Nov 27, so the estimate is well on the safe side (its script row alone assumes
ten times the tokens the writer used). Switching the script writer to Opus would raise it. The second
check cannot stop a video today: the pick reads at most 10 articles, and the estimate would need far
more to reach $5. It is there for a dearer model or a bigger pick."""
from __future__ import annotations

from .. import models
from . import rules


def step_usd(step: str, tokens_in: float, tokens_out: float) -> float:
    try:
        alias = models.model_for(step)
        m = models.spec(alias)
    except KeyError:                                  # a step not in models.toml: price it like the dearest
        m = max((models.spec(a) for a in models.config()["models"]), key=lambda s: s["output"])
    return (tokens_in * m["input"] + tokens_out * m["output"]) / 1e6


def estimate(stage: str = "start", n_articles: int | None = None, cfg: dict | None = None) -> dict:
    """{"usd": total, "parts": {name: usd}} for the steps still to run at `stage`.
    stage "start": the whole video; "after_gather": everything after the searches."""
    c = (cfg or rules.config())["cost"]
    per_article = set(c.get("per_article", {}).get("steps", []))
    scale = (n_articles / c["articles_p95"]) if (n_articles is not None and c["articles_p95"]) else 1.0
    parts = {}
    for step, (tin, tout, when) in c["steps"].items():
        if stage == "after_gather" and when == "start":
            continue
        k = scale if step in per_article else 1.0
        parts[step] = step_usd(step, tin * k, tout * k)
    if stage == "start":
        parts["searches"] = c["tavily_credits"] * c["tavily_usd_per_credit"]
    parts["voice_and_render"] = c["voice_and_render_usd"]
    return {"usd": round(sum(parts.values()), 4), "parts": {k: round(v, 5) for k, v in parts.items()},
            "stage": stage, "n_articles": n_articles}
