"""Smoke test for the model layer: every shortlisted model answers through LiteLLM, and the
second of two calls with the same long prefix reports how many input tokens came from the cache.

    .venv/bin/python scripts/smoke_models.py            # all shortlisted models
    .venv/bin/python scripts/smoke_models.py glm-5.2    # some of them

Costs well under a cent per model. Claude models are skipped when the Keychain has no
anthropic_api_key. Results go to stringer_private/runs/smoke_models.json and the call log."""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from stringer import keys, models, paths, tracing  # noqa: E402

# A stable prefix of ~1,600 tokens: long enough for every provider's cache minimum
# (Claude 5.5 models: 512 tokens). No timestamps or ids before the cache mark.
RULES = "\n".join(
    f"Rule {i}: when a news report gives a number, keep the number and say who reported it; "
    f"never round casualty figures, and keep the source's own unit (rule set A{i})."
    for i in range(1, 41))
PREFIX = ("You are a careful assistant for a news-explainer project. Read the rules, then answer "
          "the question in one short sentence.\n\n" + RULES + "\n\n" + RULES.replace("set A", "set B"))
QUESTIONS = ["Which rule number comes first? Answer with the number only.",
             "How many rule sets are there? Answer with the number only."]


def run(alias: str, trace_id: str) -> dict:
    m = models.spec(alias)
    if m["provider"] == "anthropic" and not keys.has(models.config()["anthropic"]["keychain_item"]):
        return dict(model=alias, status="skipped: no anthropic_api_key in Keychain")
    out = dict(model=alias, litellm=m["litellm"], calls=[])
    for q in QUESTIONS:
        msgs = [{"role": "user", "content": [models.cache_block(PREFIX), models.text_block(q)]}]
        try:
            r = models.complete(model=alias, messages=msgs, trace_id=trace_id,
                                name=f"smoke:{alias}", max_tokens=1500)
        except Exception as e:  # report and move on to the next model
            out["calls"].append(dict(error=repr(e)[:300]))
            out["status"] = "error"
            return out
        out["calls"].append(dict(answer=r.text.strip()[:80], latency_s=r.latency_s, **r.usage,
                                 cost_usd=r.cost["total"]))
        time.sleep(2)   # let the first call's cache entry land
    second = out["calls"][-1]
    out["answers"] = bool(all(c.get("answer") for c in out["calls"]))
    out["cached_tokens_call2"] = second["cached"]
    out["prompt_tokens_call2"] = second["prompt"]
    out["status"] = "ok" if out["answers"] else "empty answer"
    return out


def main(aliases):
    t = tracing.tracer()
    tid = t.new_trace("smoke_models", {"models": aliases})
    results = [run(a, tid) for a in aliases]
    t.flush()
    paths.RUNS.mkdir(parents=True, exist_ok=True)
    (paths.RUNS / "smoke_models.json").write_text(json.dumps(results, indent=1))
    print(f"{'model':24} {'status':12} {'cached/prompt (call 2)':>24} {'cost $':>9}  answer")
    for r in results:
        if not r.get("calls"):
            print(f"{r['model']:24} {r['status']}")
            continue
        c = r["calls"][-1]
        cost = sum(x.get("cost_usd", 0) for x in r["calls"])
        print(f"{r['model']:24} {r['status']:12} {c.get('cached', '-'):>11}/{c.get('prompt', '-'):<12} "
              f"{cost:9.5f}  {c.get('answer', c.get('error', ''))[:40]!r}")
    print("Langfuse:", "on" if tracing.langfuse_on() else "off (no keys in Keychain); local log only")
    return results


if __name__ == "__main__":
    main(sys.argv[1:] or models.shortlist())
