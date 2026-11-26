"""Make the fact check eval's planted mistakes (stringer/evals/fact_check_plant.py explains them).

    python -m scripts.plant_mistakes auto    # the script-made ones + where the hand-made ones go
    python -m scripts.plant_mistakes merge   # script-made + hand-made -> the answer key

Files (private, under stringer_private/fixtures/):
  planted_auto_v1.json    script-made records, and "slots": for each story, which claim groups the
                          hand-made mistakes go in, which kind, and candidate claims
  planted_hand_v1.json    hand-made records (written by Claude)
  planted_v1.json         the answer key the eval reads: every record, checked
"""
from __future__ import annotations

import json
import random
import re
import sys
from pathlib import Path

from stringer import fact_check, paths, story_file
from stringer.evals import fact_check_plant as fp

SEED = "plant-1"
AUTO = paths.FIXTURES / "planted_auto_v1.json"
HAND = paths.FIXTURES / "planted_hand_v1.json"
KEY = paths.FIXTURES / "planted_v1.json"
SHEETS = paths.FIXTURES / "answer_sheets_v2.json"

HINTS = {   # words that make a claim a good place for each hand-made kind
    "attribution dropped": r"\b(said|says|claimed|claims|according to|told|announced|reported|stated|accused)\b",
    "hedge removed": r"\b(may|might|could|suggest\w*|appear\w*|reportedly|allegedly|likely|possibl\w*|believed|purport\w*|expected)\b",
    "actors reversed": r"\b(struck|attacked|accused|defeated|beat|won|hit|fired|sanction\w*|seized|arrested|killed|blamed|sued|captured|shot)\b",
    "place changed": r"\b(in|at|near|from|to) [A-Z][a-z]+",
    "contradicts the event": r".",
}


def stories():
    sheets = json.loads(SHEETS.read_text(encoding="utf-8"))["stories"]
    root = paths.STORIES
    for sh in sorted(sheets, key=lambda s: s["n"]):
        d = next(root.glob(sh["short_id"] + "*"))
        facts, sf = story_file.read(d)
        arts = {json.loads(x)["id"]: json.loads(x) for x in (d / "articles.jsonl").read_text(encoding="utf-8").split("\n") if x.strip()}
        yield sh, sf, facts, arts


def quotes_of(c, fid):
    return [fid[x]["quote"] + " " + (fid[x].get("quote_en") or "") for x in c["facts"] if x in fid]


def words(s):
    return {w for w in re.findall(r"[a-z]{4,}", s.lower())}


def rec(n, story, kind, claim=None, **kw):
    copy_, made_by, _ = fp.KINDS[kind]
    return dict(id=f"P{n:03d}", story=story, copy=copy_, kind=kind, made_by=made_by, claim=claim, **kw)


def plant_code(kind, sf, facts, fid, rng, story, n):
    cl = sf["claims"]
    two = sf["sides"].get("kind") == "two sides"
    read = [s for s in sf["sources"] if s.get("read")]
    if kind == "no card":
        c = rng.choice(cl)
        return rec(n, story, kind, c["id"], set=dict(facts=[]), original=dict(facts=c["facts"]), expect={})
    if kind in ("unknown article", "quote changed"):
        c = rng.choice([c for c in cl if c["facts"]])
        f = fid[rng.choice(c["facts"])]
        new = dict(f, id=f["id"] + "-planted")
        if kind == "unknown article":
            new["article"] = "a_planted0000"
        else:
            q = fp.swap_words(f["quote"], rng)
            if not q:
                return None
            new["quote"] = q
        facts_new = [new["id"] if x == f["id"] else x for x in c["facts"]]
        return rec(n, story, kind, c["id"], set=dict(facts=facts_new), new_facts=[new],
                   original=dict(facts=c["facts"], quote=f["quote"], article=f["article"]),
                   expect=dict(cards_off=[new["id"]]))
    if kind in ("look-alike address", "early date"):
        s = rng.choice(read)
        ch = dict(url=fp.lookalike_url(s["url"])) if kind == "look-alike address" else dict(published_at=fp.early(sf["event"]["start"]))
        cards = [x for c in cl for x in c["facts"] if fid.get(x, {}).get("article") == s["id"]]
        return rec(n, story, kind, None, sources={s["id"]: ch}, original={k: s.get(k) for k in ch},
                   expect=dict(cards_off=sorted(set(cards)), source=s["id"]))
    if kind == "wrong sides" and two:
        A, B = sf["sides"]["A"]["side_id"], sf["sides"]["B"]["side_id"]
        if n % 2 == 0:
            c = rng.choice([c for c in cl if len(c["sides"]) < 2])
            return rec(n, story, kind, c["id"], set=dict(sides=[A, B]), original=dict(sides=c["sides"]),
                       expect=dict(sides=c["sides"]), note="marked as reported by both sides")
        one = [c for c in cl if len(c["sides"]) == 1]
        if one:
            c = rng.choice(one)
            bs = dict(silent_side=c["sides"][0], status="blindspot", matters="central", why="planted", evidence=None)
            return rec(n, story, kind, c["id"], set=dict(blindspot=bs), original=dict(blindspot=c.get("blindspot")),
                       expect=dict(sides=c["sides"], blindspot_removed=True), note="a blindspot against the side that reports it")
    return None


def plant_judge(kind, c, sf, fid, rng, story, n, used_batches):
    q = quotes_of(c, fid)
    if kind == "number changed":
        r = fp.change_number(c["claim"], q)
        if r:
            return rec(n, story, kind, c["id"], set=dict(claim=r[0]), original=dict(claim=c["claim"]), note=f"{r[1]} -> {r[2]}")
    if kind == "date changed":
        r = fp.change_date(c["claim"])
        if r and r[2] not in " ".join(q):
            return rec(n, story, kind, c["id"], set=dict(claim=r[0]), original=dict(claim=c["claim"]), note=f"{r[1]} -> {r[2]}")
    if kind == "swapped cards":
        size = fact_check.BATCH
        pos = {x["id"]: i for i, x in enumerate(sf["claims"])}
        cands = [o for o in sf["claims"] if pos[o["id"]] // size != pos[c["id"]] // size and o["facts"]
                 and not set(o["articles"]) & set(c["articles"]) and len(words(o["claim"]) & words(c["claim"])) <= 1]
        if cands:
            o = rng.choice(cands)
            fields = ("facts", "articles", "sides", "neither", "independent", "independent_groups", "flags")
            return rec(n, story, kind, c["id"], set={k: o[k] for k in fields}, original={k: c[k] for k in fields},
                       note=f"cards of {o['id']}: {o['claim'][:90]}")
    return None


def auto():
    out, slots, n = [], [], 1
    for i, (sh, sf, facts, arts) in enumerate(stories()):
        sid = sh["short_id"]
        rng = random.Random(f"{SEED}:{sid}")
        fid = {f["id"]: f for f in facts}
        # code copy: two kinds a story, in turn (wrong sides only where the story has two sides)
        kinds = [fp.CODE_KINDS[(2 * i + k) % len(fp.CODE_KINDS)] for k in range(2)]
        for kind in kinds:
            r = plant_code(kind, sf, facts, fid, rng, sid, n) or plant_code("no card" if kind != "no card" else "quote changed", sf, facts, fid, rng, sid, n)
            if r:
                out.append(r)
                n += 1
        # judge copy: even groups for the hand-made kinds, odd groups for the script-made ones
        groups = fact_check.batches(sf["claims"])
        hand_groups = [g for g in range(len(groups)) if g % 2 == 0][:2]
        script_groups = [g for g in range(len(groups)) if g % 2 == 1][:2]
        for k, g in enumerate(script_groups):
            order = [fp.JUDGE_SCRIPT_KINDS[(2 * i + k + j) % 3] for j in range(3)]
            done = False
            for kind in order:
                for c in rng.sample(groups[g], len(groups[g])):
                    if not c["facts"]:
                        continue
                    r = plant_judge(kind, c, sf, fid, rng, sid, n, None)
                    if r:
                        r["group"] = g
                        out.append(r)
                        n += 1
                        done = True
                        break
                if done:
                    break
        for k, g in enumerate(hand_groups):
            kind = fp.HAND_KINDS[(2 * i + k) % len(fp.HAND_KINDS)]
            pat = re.compile(HINTS[kind])
            cands = [c for c in groups[g] if c["facts"] and pat.search(c["claim"])]
            slots.append(dict(story=sid, n=sh["n"], group=g, kind=kind, event=sf["event"]["title"],
                              summary=sf["event"]["summary"],
                              candidates=[dict(id=c["id"], claim=c["claim"], who_says=c["who_says"], independent=c["independent"],
                                               quotes=[fid[x]["quote"][:220] + (f" | EN: {fid[x]['quote_en'][:200]}" if fid[x].get("quote_en") else "")
                                                       for x in c["facts"][:2]]) for c in cands[:14]]))
    AUTO.write_text(json.dumps(dict(version="planted-auto-1", seed=SEED, records=out, slots=slots), ensure_ascii=False, indent=1),
                    encoding="utf-8")
    by = {}
    for r in out:
        by[r["kind"]] = by.get(r["kind"], 0) + 1
    print(f"{len(out)} script-made records, {len(slots)} hand slots -> {AUTO}")
    print(json.dumps(by, indent=1))


def check(records, sfs):
    """Each record points to a real claim, judge-copy claims sit in different groups, and the change changes something."""
    bad = []
    for r in records:
        sf = sfs[r["story"]]
        ids = {c["id"]: i for i, c in enumerate(sf["claims"])}
        if r.get("claim") and r["claim"] not in ids:
            bad.append(f"{r['id']}: no claim {r['claim']}")
            continue
        if r["copy"] == "judge":
            cur = next(c for c in sf["claims"] if c["id"] == r["claim"])
            if all(cur.get(k) == v for k, v in (r.get("set") or {}).items()):
                bad.append(f"{r['id']}: the change changes nothing")
    for story in {r["story"] for r in records}:
        gs = [next(i for i, c in enumerate(sfs[story]["claims"]) if c["id"] == r["claim"]) // fact_check.BATCH
              for r in records if r["story"] == story and r["copy"] == "judge"]
        if len(gs) != len(set(gs)):
            bad.append(f"{story}: two planted claims in one group")
    return bad


def merge():
    auto_ = json.loads(AUTO.read_text(encoding="utf-8"))
    hand = json.loads(HAND.read_text(encoding="utf-8"))
    sfs = {sh["short_id"]: sf for sh, sf, _, _ in stories()}
    n = max(int(r["id"][1:]) for r in auto_["records"]) + 1
    records = list(auto_["records"])
    for r in hand["records"]:
        copy_, made_by, _ = fp.KINDS[r["kind"]]
        cur = next(c for c in sfs[r["story"]]["claims"] if c["id"] == r["claim"])
        records.append(dict(id=f"P{n:03d}", story=r["story"], copy=copy_, kind=r["kind"], made_by=made_by, claim=r["claim"],
                            set=r["set"], original={k: cur.get(k) for k in r["set"]}, note=r.get("note", ""),
                            **({"expect": {"speaker": r["speaker"]}} if r.get("speaker") else {})))
        n += 1
    bad = check(records, sfs)
    if bad:
        print("\n".join(bad))
        sys.exit(1)
    by = {}
    for r in records:
        by[r["kind"]] = by.get(r["kind"], 0) + 1
    KEY.write_text(json.dumps(dict(version="planted-1", made="2026-11-25", seed=SEED, kinds={k: dict(zip(("copy", "made_by", "expect"), v))
                                                                                           for k, v in fp.KINDS.items()},
                                   counts=by, records=records), ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(records)} records -> {KEY}")
    print(json.dumps(by, indent=1))


if __name__ == "__main__":
    {"auto": auto, "merge": merge}[sys.argv[1]]()
