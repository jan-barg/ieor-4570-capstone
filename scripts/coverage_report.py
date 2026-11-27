"""Coverage report on the frozen fixtures: module 3's eval, plus module 1's proxy measures.

    python -m scripts.coverage_report                 # report on every frozen story
    python -m scripts.coverage_report --write-labels  # also rewrite the labels in articles.jsonl

Labels are recomputed from the current outlets.csv, so the report reflects edits made after the
freeze (and --write-labels stores them). This report predates module 2 (the same-story filter, stringer/same_story.py)
and still approximates "same-story" two ways: every new-coverage article, and the subset that passes a
keyword check against the event title (which misses most non-English articles).

Targets (map, module 3): lean on >= 90% of articles on US-lens stories, reliability on >= 95%,
a country for every rated outlet. Platforms and unmatched X accounts are left out, as in the
November 24 baseline (91% lean, 99% reliability, 97% country on 242 articles)."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
from collections import Counter, defaultdict

from stringer import paths
from stringer.events import ATTRIBUTION, fixture_rows
from stringer.gather import store
from stringer.gather.queries import terms
from stringer.outlets import OutletTable

REPORTS = paths.PRIVATE / "reports"


def on_topic(a: dict, key_terms: list[str]) -> bool:
    if not key_terms:
        return True
    hay = (a.get("title", "") + " " + (a.get("text") or "")[:4000]).lower()
    hits = sum(1 for w in key_terms if w in hay)
    return hits >= min(2, len(key_terms)) or hits / len(key_terms) >= 0.5


def countable(a: dict) -> bool:
    """Articles module 3 is judged on: from a known outlet that isn't a platform. X posts from
    accounts that aren't an outlet's are unrated leads by design, so they're left out too."""
    lab = a["labels"]
    return lab["outlet_id"] is not None and lab["kind"] != "platform"


def side_stats(arts: list[dict], lens: str) -> dict:
    """Side searches are written in the side's language, so no keyword filter here. Undated
    results count (many non-US outlets give Tavily no date); ones dated before the start don't."""
    keep = [a for a in arts if a["role"] != "background" and countable(a)]
    s = {"articles": len(keep), "undated": sum(a["role"] == "unclear" for a in keep),
         "outlets": sorted({a["outlet"] for a in keep})}
    if lens == "us":
        s["lean_pct"] = round(100 * sum(bool(a["labels"]["us_lean"]) for a in keep) / len(keep), 1) if keep else None
    return s


def shares(arts: list[dict]) -> dict:
    c = [a for a in arts if countable(a)]
    n = len(c)
    pct = lambda k: round(100 * k / n, 1) if n else None
    return {"articles": len(arts), "countable": n,
            "unmatched": sum(a["labels"]["matched_by"] == "none" for a in arts),
            "platform": sum(a["labels"]["kind"] == "platform" for a in arts),
            "x_unrated": sum(a["labels"]["outlet_id"] is None and a["labels"]["matched_by"] == "x_account" for a in arts),
            "lean_pct": pct(sum(bool(a["labels"]["us_lean"]) for a in c)),
            "reliability_pct": pct(sum(a["labels"]["reliability"] is not None for a in c)),
            "country_pct": pct(sum(bool(a["labels"]["country"]) for a in c)),
            "state_media": sum(bool(a["labels"]["state_media"]) for a in c),
            "opinion": sum(a["labels"]["section"] == "opinion" for a in c),
            "outlets": len({a["outlet"] for a in c})}


def side_of(a: dict, side_ids: list[str]) -> list[str]:
    out = []
    for fb in a["found_by"]:
        m = re.match(r"tavily_search:q3[a-z0-9]_side_(.+)_(news|general)(?:__retry\d)?$", fb)
        if m and m.group(1) in side_ids:
            out.append(m.group(1))
    if any(fb.startswith("tavily_search:q5_right_tail") for fb in a["found_by"]):
        out.append("us_right")
    return sorted(set(out))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-labels", action="store_true")
    a = ap.parse_args(argv)
    t = OutletTable.load()
    rows = {r["id"][:8]: r for r in fixture_rows()}
    stories = sorted(p.name for p in paths.STORIES.iterdir() if (p / "articles.jsonl").exists()) \
        if paths.STORIES.exists() else []
    if not stories:
        raise SystemExit("no frozen stories yet")

    per_event, unrated_outlets, unmatched_hosts, no_reliability = [], Counter(), Counter(), Counter()
    pooled = defaultdict(list)
    gather = []
    for eid in stories:
        arts, meta = store.read_articles(eid), store.read_meta(eid)
        for x in arts:
            x["labels"] = {k: v for k, v in t.label(x["url"]).items() if k != "url"}
            x["outlet"], x["outlet_name"] = x["labels"]["outlet_id"], x["labels"]["outlet_name"]
        if a.write_labels:
            store.write_story(eid, arts, meta)
        ev = meta["event"]
        short = eid[:8]
        lens = meta["lens"]["kind"]
        key_terms = terms(ev["title"])
        new = [x for x in arts if x["role"] == "new_coverage"]
        topic = [x for x in new if on_topic(x, key_terms)]
        side_ids = [s["side_id"] for s in meta["lens"]["sides"]]
        by_side = {s: side_stats([x for x in arts if s in side_of(x, side_ids)], lens) for s in side_ids}
        rec = {"event": short, "set": rows.get(short, {}).get("set"), "title": ev["title"], "lens": lens,
               "all": shares(arts), "new": shares(new), "on_topic": shares(topic), "sides": by_side}
        per_event.append(rec)
        for x in topic:
            pooled[(lens, "on-topic new coverage")].append(x)
            if countable(x) and not x["labels"]["us_lean"] and lens == "us":
                unrated_outlets[x["outlet"]] += 1
        for x in new:
            pooled[(lens, "all new coverage")].append(x)
            if countable(x) and x["labels"]["reliability"] is None:
                no_reliability[x["outlet"]] += 1
        for x in arts:
            if x["labels"]["matched_by"] == "none":
                unmatched_hosts[re.sub(r"^www\.", "", x["url_key"].split("/")[0])] += 1
        times = [p for p in (x["published_at"] for x in new) if p]
        gather.append({"event": short, "lens": lens, "articles": len(arts), "new": len(new),
                       "background": sum(x["role"] == "background" for x in arts),
                       "unclear": sum(x["role"] == "unclear" for x in arts),
                       "after_start_pct": round(100 * len(new) / max(1, len(new) + sum(
                           x["role"] == "background" for x in arts if "q9_background" not in " ".join(x["found_by"]))), 1),
                       "full_text_pct": round(100 * sum(x["text_status"] == "full" for x in new) / max(1, len(new)), 1),
                       "outlets_new": len({x["outlet"] for x in new if countable(x)}),
                       "own_with_text": sum(x["own_source"] and x["text_status"] == "full" for x in arts),
                       "own": sum(x["own_source"] for x in arts),
                       "credits": meta["credits_this_run"], "seconds": meta["seconds"],
                       "query_cost_usd": meta["queries"].get("cost_usd")})

    pooled_s = {f"{lens} / {which}": shares(v) for (lens, which), v in sorted(pooled.items())}
    now = dt.datetime.now(dt.timezone.utc)
    os.makedirs(REPORTS, exist_ok=True)
    base = REPORTS / f"coverage_{now:%Y-%m-%d}"
    with open(str(base) + ".json", "w", encoding="utf-8") as f:
        json.dump({"attribution": ATTRIBUTION, "made_at": now.isoformat(timespec="seconds"),
                   "pooled": pooled_s, "events": per_event, "gather": gather,
                   "unrated_outlets_us_lens": unrated_outlets.most_common(),
                   "no_reliability": no_reliability.most_common(),
                   "unmatched_hosts": unmatched_hosts.most_common()}, f, indent=1, ensure_ascii=False)

    L = [f"# Coverage report ({now:%Y-%m-%d})", "",
         f"{len(stories)} frozen stories. Labels recomputed from the current outlets.csv. "
         f"{ATTRIBUTION}.", "",
         "## Module 3: label coverage", "",
         "Articles from a known outlet; platforms and X posts from non-outlet accounts are left out. "
         "\"On-topic\" is an English keyword check against the title (it drops most non-English articles, "
         "which are also the ones without a US lean), so both sets are shown.", "",
         "| Lens / set | Articles | Lean | Reliability | Country | Outlets |", "|---|---|---|---|---|---|"]
    for k, s in pooled_s.items():
        L.append(f"| {k} | {s['countable']} | {s['lean_pct']}% | {s['reliability_pct']}% | {s['country_pct']}% | {s['outlets']} |")
    L += ["", "Targets: lean >= 90% on US-lens stories, reliability >= 95%, country 100% of rated outlets. "
          "The US lean only applies to US-lens stories.", "",
          "### Per event (on-topic new coverage)", "",
          "| Event | Set | Lens | Articles | Lean | Rel. | Country | Per side, not dated before the start: articles (undated) outlets |",
          "|---|---|---|---|---|---|---|---|"]
    for r in per_event:
        s = r["on_topic"]
        side_txt = "; ".join(f"{k}: {v['articles']} ({v['undated']}) {len(v['outlets'])}"
                             + (f", lean {v['lean_pct']}%" if "lean_pct" in v else "")
                             for k, v in r["sides"].items())
        L.append(f"| {r['event']} {r['title'][:40]} | {r['set']} | {r['lens']} | {s['countable']} | {s['lean_pct']}% | "
                 f"{s['reliability_pct']}% | {s['country_pct']}% | {side_txt} |")
    L += ["", "### Outlets without a lean on US-lens stories (on-topic)", ""]
    L += [f"- {o}: {n}" for o, n in unrated_outlets.most_common(30)] or ["- none"]
    L += ["", "### Outlets without a reliability score (all new coverage)", ""]
    L += [f"- {o}: {n}" for o, n in no_reliability.most_common(30)] or ["- none"]
    L += ["", "### Hosts with no row in outlets.csv (all articles, top 40)", ""]
    L += [f"- {h}: {n}" for h, n in unmatched_hosts.most_common(40)] or ["- none"]
    L += ["", "## Module 1: Gather proxies", "",
          "| Event | Lens | Articles | New | Background | Unclear | New, full text | Outlets (new) | Own links with text | Credits | Seconds |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for g in gather:
        L.append(f"| {g['event']} | {g['lens']} | {g['articles']} | {g['new']} | {g['background']} | {g['unclear']} | "
                 f"{g['full_text_pct']}% | {g['outlets_new']} | {g['own_with_text']}/{g['own']} | {g['credits']} | {g['seconds']} |")
    tot = lambda k: sum(g[k] or 0 for g in gather)
    L += ["", f"Totals: {tot('articles')} articles, {tot('new')} new coverage, {tot('credits'):.0f} credits, "
          f"query writing ${tot('query_cost_usd'):.4f}."]
    with open(str(base) + ".md", "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print("\n".join(L[:12]))
    print(f"... written to {base}.md and .json")


if __name__ == "__main__":
    main()
