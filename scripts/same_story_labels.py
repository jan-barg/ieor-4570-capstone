"""Write the same-story answer key from Jan's labels on the review page, plus Claude's drafts for the
items Jan left open (Jan's call, Nov 24: Claude labels most of them, blind, and Jan checks).

    python -m scripts.same_story_labels --page <dir of the page's saved docs> --claude a.json b.json

  --page    the review page's database docs, saved with ArtifactData (collection "labels")
  --claude  Claude's draft labels, made without seeing Jan's: {"labels": {item: {label, confidence, reason}}}

Rules: Jan's label wins wherever he gave one. His "can't tell" labels were articles in languages he
doesn't read, and he asked Claude to check those, so they take Claude's draft. Every other item
takes Claude's draft too, marked source "claude". Claude's draft is kept next to Jan's label
on every item, and the agreement between the two on the items both labeled is written to the file,
so anyone can see how far the drafts can be trusted. Fixes made after the page
(fixtures/same_story_label_fixes.json: label, who, why) are applied last and marked on the item.
Writes fixtures/same_story_labels_v1.json."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections import Counter
from pathlib import Path

from stringer import paths

OUT = paths.FIXTURES / "same_story_labels_v1.json"
SAMPLE = paths.FIXTURES / "same_story_sample_v1.json"
FIXES = paths.FIXTURES / "same_story_label_fixes.json"
VALID = {"same", "follow_up", "different", "unsure"}


def read_page(d: Path) -> dict:
    out = {}
    for f in sorted(Path(d).rglob("*.json")):
        doc = json.loads(f.read_text(encoding="utf-8"))
        doc = doc.get("data", doc)
        for a in (doc.get("answers") or {}).values():
            if a.get("item") and a.get("v") in VALID:
                out[a["item"]] = {"label": a["v"], "note": (a.get("note") or "").strip()}
    return out


def agreement(jan: dict, claude: dict) -> dict:
    both = [k for k in jan if k in claude and jan[k]["label"] != "unsure" and claude[k]["label"] != "unsure"]
    same = [k for k in both if jan[k]["label"] == claude[k]["label"]]
    conf = Counter(f"jan {jan[k]['label']} / claude {claude[k]['label']}" for k in both if k not in same)
    drop = [k for k in both if (jan[k]["label"] == "different") != (claude[k]["label"] == "different")]
    hi = [k for k in both if claude[k].get("confidence") == "high"]
    return dict(both_labeled=len(both), agree=len(same), rate=round(len(same) / len(both), 3) if both else None,
                agree_on_keep_vs_drop=round(1 - len(drop) / len(both), 3) if both else None,
                rate_when_claude_high=round(sum(k in same for k in hi) / len(hi), 3) if hi else None,
                disagreements=dict(conf.most_common()), disagreeing_items=sorted(set(both) - set(same)))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--page", required=True)
    ap.add_argument("--claude", nargs="+", required=True)
    a = ap.parse_args(argv)
    items = [i["id"] for i in json.loads(SAMPLE.read_text(encoding="utf-8"))["items"]]
    jan = read_page(Path(a.page))
    claude = {}
    for f in a.claude:
        claude.update(json.loads(Path(f).read_text(encoding="utf-8"))["labels"])
    missing = [i for i in items if i not in claude and i not in jan]
    if missing:
        print(f"{len(missing)} items have no label at all, e.g. {missing[:3]}")
    labels = {}
    for i in items:
        c = claude.get(i)
        if i in jan and not (jan[i]["label"] == "unsure" and c):
            labels[i] = dict(label=jan[i]["label"], source="jan", note=jan[i]["note"], claude=c)
        elif c:
            # Jan's "can't tell" were articles in languages he doesn't read; he asked Claude to check them
            note = f"Jan: can't tell. {jan[i]['note']}".strip() if i in jan else ""
            labels[i] = dict(label=c["label"], source="claude", note=note, claude=c)
    fixes = json.loads(FIXES.read_text(encoding="utf-8"))["fixes"] if FIXES.exists() else {}
    for i, f in fixes.items():
        if i in labels:
            old = labels[i]
            labels[i] = dict(old, label=f["label"], source="fix", note=f"{f['why']} ({f['by']})",
                             label_before_fix=old["label"], source_before_fix=old["source"])
    ag = agreement(jan, claude)
    out = dict(version=f"same-story-labels-v1 ({dt.date.today().isoformat()}, {len(fixes)} fixes)",
               notes="Jan labeled what he chose on the review page; Claude drafted labels for every item "
                     "without seeing Jan's (two separate labeling agents, the page's definitions, the "
                     "headline plus about 1,500 characters of each article). Jan's label wins where he gave "
                     "one. Scores are reported on all labels and on Jan's alone (*_jan). Fixed labels have source "
                     "'fix' and count as Jan's when Jan had labeled the item.",
               sources=dict(Counter(v["source"] for v in labels.values())),
               counts=dict(Counter(v["label"] for v in labels.values())),
               agreement_jan_vs_claude=ag, labels=labels)
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT}: {out['sources']} {out['counts']}")
    print(json.dumps({k: v for k, v in ag.items() if k != "disagreeing_items"}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
