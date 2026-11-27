"""Build the test set for the Gate's content check (module 0): which events the child-victim rule is
scored on. Private output: stringer_private/fixtures/gate_policy_sample_v1.json.

Groups (decided Nov 26, Jan: "fifteen labels, plus hard cases, and fifty ordinary events"):
  labeled      Jan's Nov 23 labels and the cases the map names (from the drafts file, source jan/map)
  hard         child-word events whose label is a judgment call; drafted by Claude, Jan decides
  child_words  every other qualifying Archive event with a child word in its title or summary
  made_up      invented events that probe the rule's edges (no real event behind them)
  ordinary     50 qualifying events with no child word, picked at random; all should be allowed

The labels themselves are drafts in stringer_private/fixtures/gate_policy_drafts_v1.json (made by
Claude, checked by Jan on the review page); this script only joins them to the Archive's text, adds
the made-up and ordinary events, and splits the set: a third is held out of prompt changes.

    python -m scripts.build_gate_policy_set"""
from __future__ import annotations

import csv
import gzip
import json
import random
import re
from collections import Counter, defaultdict

from stringer import paths
from stringer.gate import rules

DRAFTS = paths.FIXTURES / "gate_policy_drafts_v1.json"
OUT = paths.FIXTURES / "gate_policy_sample_v1.json"
SEED = 20261126
ORDINARY = 50
HOLDOUT = 1 / 3

# Selection only (broad on purpose, so the hard negatives are in): any word that can point at a child.
CHILD_WORDS = re.compile(
    r"\b(child|children|kid|kids|boy|boys|girl|girls|baby|babies|infant|infants|toddler|toddlers|newborn|"
    r"newborns|teen|teens|teenage|teenager|teenagers|minor|minors|pupil|pupils|schoolchild\w*|schoolboy\w*|"
    r"schoolgirl\w*|student|students|youth|youths|juvenile\w*|orphan\w*|daughter|daughters|son|sons|"
    r"year-old|aged \d|school|schools|kindergarten|nursery|paediatric|pediatric|underage)\b", re.I)

# Invented events at the rule's edges. Places are left vague on purpose.
MADE_UP = [
    ("refuse", True, "Toddler Rescued After Two Days Trapped in Village Well",
     "Rescuers freed a two-year-old boy who fell into a 30-metre well in a farming village; he is in hospital in "
     "serious condition.",
     "disaster", "other"),
    ("refuse", False, "Gunman Takes Pupils Hostage at Primary School",
     "An armed man is holding about 20 pupils and two teachers inside a primary school; police have sealed off the area.",
     "conflict", "armed_attack"),
    ("refuse", False, "Girl, 9, Killed by Stray Bullet During Police Raid",
     "A nine-year-old girl was killed in her home by a stray bullet during a police raid on a nearby building; "
     "the interior ministry has opened an inquiry.", "conflict", "armed_attack"),
    ("refuse", False, "Boy, 12, Dies After Beating at Youth Detention Centre",
     "A 12-year-old died in hospital after he was beaten at a state-run youth detention centre; three guards "
     "have been suspended.", "humanitarian", "other"),
    ("refuse", False, "Armed Group Abducts Nine Children From Village School",
     "Gunmen on motorbikes took nine children from a village school; the regional governor says talks for "
     "their release have begun.", "conflict", "kidnapping"),
    ("refuse", False, "Newborn Found Abandoned in Freezing Car Park",
     "A newborn girl was found in a bag in a car park overnight and is being treated for hypothermia; police are "
     "searching for the mother.", "humanitarian", "other"),
    ("refuse", False, "Teenager Stabbed to Death Outside School Gates",
     "A 15-year-old boy was stabbed to death outside his school at the end of the school day; two men were "
     "arrested.", "conflict", "armed_attack"),
    ("refuse", False, "Drone Strike Kills Four-Year-Old Girl, Family Says",
     "A drone strike on a house killed a four-year-old girl, her family and local officials said; the army says "
     "it is checking the report.", "conflict", "drone_strike"),
    ("allow", False, "Teenage Gunman Kills Three at Shopping Centre",
     "Police say a 16-year-old opened fire in a shopping centre, killing three adults, before he was arrested.",
     "conflict", "armed_attack"),
    ("allow", False, "Earthquake Collapses School, Killing 40 Pupils",
     "A magnitude 6.8 earthquake brought down a school building during lessons; at least 40 pupils and three "
     "teachers died.", "disaster", "earthquake"),
    ("allow", False, "Airstrike on Market Kills 25, Including Six Children",
     "An airstrike hit a crowded market on Saturday morning, killing 25 people including six children and "
     "wounding dozens.", "conflict", "airstrike"),
    ("allow", False, "Parliament Raises Age of Criminal Responsibility to 14",
     "Lawmakers voted 210 to 150 to raise the age of criminal responsibility from 10 to 14, after a two-year "
     "campaign by children's rights groups.", "political", "legislation"),
    ("allow", False, "Child Benefit Cut Sparks Mass Protests",
     "Tens of thousands marched in the capital against a government plan to cut child benefit payments by a "
     "third.", "political", "protest"),
    ("allow", False, "Ferry Carrying School Trip Sinks; 60 Dead",
     "A ferry carrying 300 passengers, among them a school trip of 80 pupils, sank in rough seas; at least 60 "
     "people died.", "disaster", "maritime_accident"),
]


def archive_rows() -> list[dict]:
    csv.field_size_limit(10 ** 9)
    with gzip.open(paths.ARCHIVE_GZ, "rt", encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if not r.get("merged_into") and rules.eligible(r)]


def event_of(r: dict) -> dict:
    keep = ("id", "title", "summary", "category", "subtype", "country", "severity", "confidence", "report_count")
    return {k: r[k] for k in keep}


def split(items: list[dict], rng: random.Random) -> None:
    by = defaultdict(list)
    for it in items:
        by[(it["group"], it["draft"])].append(it)
    for _, group in sorted(by.items()):
        rng.shuffle(group)
        n = round(len(group) * HOLDOUT)
        for i, it in enumerate(group):
            it["split"] = "holdout" if i < n else "tune"


def main():
    drafts = json.loads(DRAFTS.read_text(encoding="utf-8"))
    by_id = {d["id"]: d for d in drafts["items"]}
    rows = archive_rows()
    hits = [r for r in rows if CHILD_WORDS.search(r["title"]) or CHILD_WORDS.search(r["summary"])]
    missing = sorted(set(by_id) - {r["id"] for r in hits})
    undrafted = sorted({r["id"] for r in hits} - set(by_id))
    if missing or undrafted:
        print(f"note: drafts not among the hits: {len(missing)}; hits without a draft: {len(undrafted)}")
    items = []
    for r in hits:
        d = by_id.get(r["id"]) or dict(group="child_words", draft="allow", source="claude-draft",
                                       reason="No draft yet.")
        items.append(dict(id=r["id"], short=r["id"][:8], group=d["group"], draft=d["draft"], source=d["source"],
                          reason=d["reason"], your_call=d["group"] == "hard", event=event_of(r)))
    rng = random.Random(SEED)
    plain = [r for r in rows if not (CHILD_WORDS.search(r["title"]) or CHILD_WORDS.search(r["summary"]))]
    for r in rng.sample(plain, ORDINARY):
        items.append(dict(id=r["id"], short=r["id"][:8], group="ordinary", draft="allow", source="claude-draft",
                          reason="An ordinary event: no child word in the title or summary.", your_call=False,
                          event=event_of(r)))
    for i, (lab, call, title, summary, cat, sub) in enumerate(MADE_UP, 1):
        sid = f"madeup{i:02d}"
        items.append(dict(id=sid, short=sid, group="made_up", draft=lab, source="claude-draft",
                          reason=("Your call: an accident, which the rule allows, but one child in danger is "
                                  "the whole story." if call else "Invented to test an edge of the rule."),
                          your_call=call,
                          event=dict(id=sid, title=title, summary=summary, category=cat, subtype=sub,
                                     country="", severity="3", confidence="85", report_count="12")))
    split(items, rng)
    OUT.write_text(json.dumps({"version": "gate-set-1", "seed": SEED, "drafts": drafts["version"],
                               "items": items}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT}: {len(items)} events")
    print(Counter((i["group"], i["draft"], i["split"]) for i in items))


if __name__ == "__main__":
    main()
