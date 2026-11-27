"""Turn Jan's answers from the Gate label review page into the content-check eval's answer key.

The page saves one document per event in its "labels" collection; export them into a folder of JSON
files first (Claude does this with the artifact data tool's list and out_dir), then:

    python -m scripts.gate_policy_labels <export folder>

writes stringer_private/fixtures/gate_policy_labels_v1.json ({short id: {label, note, draft, at}}).
Re-score the saved runs afterwards (free): python -m scripts.run_eval rescore gate_policy <run id>."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from stringer.evals.gate_policy_eval import LABELS


def main(argv=None):
    folder = Path((argv or sys.argv[1:])[0])
    labels = {}
    for p in sorted(folder.rglob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        body = d.get("data", d)
        if body.get("label") in ("allow", "refuse"):
            labels[p.stem] = {k: body.get(k) for k in ("label", "note", "draft", "at")}
    changed = sum(v["label"] != v.get("draft") for v in labels.values())
    LABELS.write_text(json.dumps({"version": "jan-review-1", "labels": labels}, indent=1, ensure_ascii=False) + "\n",
                      encoding="utf-8")
    print(f"wrote {LABELS}: {len(labels)} answers, {changed} differ from Claude's drafts")


if __name__ == "__main__":
    main()
