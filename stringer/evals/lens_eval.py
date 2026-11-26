"""The eval for choosing a story's sides (module 4, stringer/lens.py), plugged into the shared runner.

Inputs: the event of each frozen test story (its gather.json), nothing else; the step runs before
any search. Answer key: stringer_private/fixtures/lens_key_v1.csv, the hand-made lens file
(fixture_lenses_v1.csv) with one change Jan made on Nov 26: the FAA ground stop is "no split".
Splits: "tune" is the 26 pipeline stories (prompt changes are tried on them); "holdout" is the 14
follow-up stories, which share their parent's sides and check that tuning didn't overfit.

Two modes (--opt mode=menu|cold):
  menu  every ready-made side list is shown, as in live use today. Easy on these stories, because
        their lists were made for them: the plain-code rule gets most of them.
  cold  the story's own two lists are hidden, so a world story's sides must be built from the
        outlet table, the way most new world stories need. The deciding score (Jan, Nov 26).

Scores (all plain code):
  right        the whole answer is right: the kind, and for a world story both sides (at least half
               of each side's outlets match, scored as F1 under the better pairing of the two sides),
               and for a no-split story the local-press country
  kind_right   US / world / no split right
  sides_right  of the world stories, the share with both sides right
  side_f1      of the world stories called world, the average outlet F1 of the two sides
  split_found  of the no-split stories, the share called no split
  false_split  of the stories with sides, the share wrongly called no split
  local_right  of the no-split stories called no split, the share with the right local-press country
  fallbacks    stories where the model's answer was unusable twice and the code rule chose"""
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

from .. import lens, paths
from ..events import from_dict
from ..gather.sides import side_lists
from ..outlets import OutletTable
from .runner import Item, Step

KEY = paths.FIXTURES / "lens_key_v1.csv"
SIDE_OK = 0.5
MODES = ("menu", "cold")


def f1(pred: set, gold: set) -> float:
    if not pred or not gold:
        return 0.0
    tp = len(pred & gold)
    return 0.0 if not tp else 2 * tp / (len(pred) + len(gold))


def side_match(pred: list[set], gold: list[set]) -> tuple[float, float]:
    """The two sides' F1 under the better of the two pairings (side order doesn't matter)."""
    if len(pred) < 2 or len(gold) < 2:
        return 0.0, 0.0
    a = (f1(pred[0], gold[0]), f1(pred[1], gold[1]))
    b = (f1(pred[0], gold[1]), f1(pred[1], gold[0]))
    return max(a, b, key=lambda x: (sum(x), min(x)))


class LensEval(Step):
    name = "lens"
    model_step = "lens"
    headline = ("right", "right_tune", "right_holdout", "kind_right", "sides_right", "side_f1", "split_found", "false_split", "local_right",
                "fallbacks", "flags")
    report_title = "Choosing a story's sides: evals"
    report_intro = ("Before any search, this step reads a new event and decides which two camps of outlets the video "
                    "compares (US left against right, or a world story's two sides) or that the story has no real "
                    "split, and which country's press to search. Each run is scored against the hand-made sides of "
                    "the test stories. In cold mode the story's own ready-made side lists are hidden, so the model "
                    "has to build the sides from the outlet table, as it must for most new world stories.")
    metric_notes = {
        "right": ("Right", "The main score: share of stories where the whole answer is right (the kind, both sides "
                           "of a world story, the local-press country of a no-split story)."),
        "right_tune": ("Right, tune", "Right on the 26 test stories, the ones prompt changes are tried on."),
        "right_holdout": ("Right, follow-ups", "Right on the 14 follow-up stories, kept out of prompt changes."),
        "kind_right": ("Kind right", "Share of stories with the right kind: US, world or no split."),
        "sides_right": ("Sides right", "Of the world stories, the share where both sides match the key "
                                       "(at least half of each side's outlets)."),
        "side_f1": ("Side overlap", "Of the world stories it called world, how closely its two outlet lists match "
                                    "the key's, from 0 to 1."),
        "split_found": ("No split found", "Of the stories with no real split, the share it called no split."),
        "false_split": ("Sides lost", "Of the stories that do have sides, the share it wrongly called no split. "
                                      "Lower is better."),
        "local_right": ("Local press right", "Of the no-split stories it called no split, the share with the right "
                                             "country to search."),
        "fallbacks": ("Fallbacks", "Stories where the model's answer was unusable twice and the code rule decided."),
        "flags": ("Flags", "Warnings code raised while checking the answers (dropped ids, a side with nothing on "
                           "file). Not wrong by themselves."),
    }
    class_names = {"us": "US left/right", "world": "world sides", "none": "no split"}

    def __init__(self, mode=None, prompt=None, key=None, stories_dir=None, lists=None):
        self.mode = mode or "cold"
        if self.mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        self.prompt = prompt or lens.VERSION
        if self.prompt not in lens.PROMPTS:
            raise ValueError(f"unknown prompt {self.prompt!r}; have {sorted(lens.PROMPTS)}")
        self.version = f"{self.prompt}-{self.mode}"
        self.key_path = Path(key or KEY)
        self.stories_dir = Path(stories_dir or paths.STORIES)
        self.lists_path = Path(lists) if lists else None
        self._t = None

    # -- inputs ---------------------------------------------------------------------------------
    @property
    def t(self) -> OutletTable:
        if self._t is None:
            self._t = OutletTable.load()
        return self._t

    def _key_rows(self) -> list[dict]:
        with open(self.key_path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def _dirs(self) -> dict[str, Path]:
        return {d.name[:8]: d for d in sorted(self.stories_dir.iterdir()) if (d / "gather.json").exists()}

    def load(self, only=None, split="tune") -> list[Item]:
        dirs = self._dirs()
        items = []
        for r in self._key_rows():
            sid = r["event"]
            if sid not in dirs:
                continue
            sp = "tune" if r["set"] == "pipeline" else "holdout"
            hide = [x for x in (r["side_a"], r["side_b"]) if x and r["lens"] == "world"] if self.mode == "cold" else []
            items.append(Item(id=f"lens:{sid}", story=sid, data={"dir": str(dirs[sid]), "hide": hide}, split=sp))
        if only:
            items = [i for i in items if i.story in set(only)]
        if split != "all":
            items = [i for i in items if i.split == split]
        return items

    def load_key(self) -> dict:
        return {r["event"]: r for r in self._key_rows()}

    def key_version(self) -> str:
        rows = self._key_rows() if self.key_path.exists() else []
        return f"{self.key_path.name} ({len(rows)} stories)"

    def _event(self, item: Item):
        meta = json.loads((Path(item.data["dir"]) / "gather.json").read_text(encoding="utf-8"))
        return from_dict(meta["event"])

    def _lists(self, item: Item):
        return lens.ready_lists(self.t, hide=item.data.get("hide") or (), path=self.lists_path)

    # -- running --------------------------------------------------------------------------------
    def run(self, item: Item, ctx):
        ev, lists = self._event(item), self._lists(item)
        if ctx.is_code:
            _, rec = lens.choose(ev, self.t, None, lists=lists)
        else:
            _, rec = lens.choose(ev, self.t, ctx.complete, model=ctx.model, lists=lists, prompt=self.prompt)
        rec["hidden_lists"] = item.data.get("hide") or []
        return rec

    def plan(self, item: Item, model: str) -> list[dict]:
        ev, lists = self._event(item), self._lists(item)
        return [{"messages": lens.messages_for(ev, self.t, lists, self.prompt), "params": lens.params_for(model),
                 "expect_output": 260}]

    # -- scoring --------------------------------------------------------------------------------
    def _gold_sides(self, k: dict) -> list[set]:
        sl = side_lists(self.t, self.lists_path) if self.lists_path else side_lists(self.t)
        return [set(sl[x].outlet_ids) for x in (k["side_a"], k["side_b"]) if x]

    def score(self, item: Item, output, key: dict) -> dict:
        k = key.get(item.story)
        if not k:
            return {}
        gold, pred = k["lens"], output.get("kind")
        out = dict(gold=gold, pred=pred, kind_right=gold == pred, fallback=bool(output.get("fallback")),
                   flags=len(output.get("flags") or []), sides_right=None, side_f1=None, local_right=None,
                   gold_local=k["local_press"], pred_local=output.get("local_code") or "")
        checks = [out["kind_right"]]
        if gold == "world":
            if pred == "world":
                a, b = side_match([set(s["outlet_ids"]) for s in output.get("sides") or []], self._gold_sides(k))
                out["side_f1"] = round((a + b) / 2, 3)
                out["side_f1_each"] = [round(a, 3), round(b, 3)]
                out["sides_right"] = min(a, b) >= SIDE_OK
            else:
                out["sides_right"] = False
            checks.append(out["sides_right"])
        if gold == "none" and pred == "none":
            out["local_right"] = out["pred_local"].upper() == k["local_press"].upper()
            checks.append(out["local_right"])
        elif gold == "none":
            checks.append(False)
        out["right"] = all(checks)
        out["share"] = round(sum(bool(c) for c in checks) / len(checks), 3)
        return out

    def summarize(self, items: list[Item], scores: list[dict]) -> dict:
        s = [x for x in scores if x]
        if not s:
            return {}
        share = lambda xs: round(sum(bool(x) for x in xs) / len(xs), 3) if xs else None
        world = [x for x in s if x["gold"] == "world"]
        none = [x for x in s if x["gold"] == "none"]
        sided = [x for x in s if x["gold"] != "none"]
        f1s = [x["side_f1"] for x in world if x["side_f1"] is not None]
        by_split = lambda sp: share([x["right"] for it, x in zip(items, scores) if x and it.split == sp])
        return dict(
            scored=len(s), right=share([x["right"] for x in s]), right_tune=by_split("tune"),
            right_holdout=by_split("holdout"), kind_right=share([x["kind_right"] for x in s]),
            sides_right=share([x["sides_right"] for x in world]),
            side_f1=round(sum(f1s) / len(f1s), 3) if f1s else None,
            split_found=share([x["pred"] == "none" for x in none]),
            false_split=share([x["pred"] == "none" for x in sided]),
            local_right=share([x["local_right"] for x in none if x["local_right"] is not None]),
            fallbacks=sum(x["fallback"] for x in s), flags=sum(x["flags"] for x in s),
            gold=dict(Counter(x["gold"] for x in s)),
            confusion=dict(sorted(Counter(f"{x['gold']}->{x['pred'] or 'none'}" for x in s).items())),
            stories={it.story: x["share"] for it, x in zip(items, scores) if x})

    # -- report ---------------------------------------------------------------------------------
    def story_names(self) -> dict[str, str]:
        out = {}
        for sid, d in self._dirs().items():
            try:
                out[sid] = json.loads((d / "gather.json").read_text(encoding="utf-8"))["event"]["title"]
            except (OSError, KeyError, json.JSONDecodeError):
                pass
        return out

    def _describe_key(self, k: dict) -> str:
        if k["lens"] == "world":
            return f"world: {k['side_a']} vs {k['side_b']}"
        if k["lens"] == "none":
            return f"no split, local press {k['local_press'] or '(none)'}"
        return "US left/right"

    @staticmethod
    def _describe_out(o: dict) -> str:
        if o.get("kind") == "world":
            sides = o.get("sides") or []
            return "world: " + " vs ".join(f"{s['side_id']} ({len(s['outlet_ids'])})" for s in sides)
        if o.get("kind") == "none":
            return f"no split, local press {o.get('local_code') or '(none)'}"
        return "US left/right" if o.get("kind") == "us" else str(o.get("kind"))

    def mistakes(self, rec: dict) -> list[dict]:
        key, names, out = self.load_key(), self.story_names(), []
        for row in rec.get("items_detail") or []:
            sc, o = row.get("scores") or {}, row.get("output") or {}
            if not sc or sc.get("right"):
                continue
            k = key.get(row["story"], {})
            why = o.get("reason") or ""
            if sc.get("side_f1_each"):
                why += f" [side overlap {sc['side_f1_each'][0]:.2f} / {sc['side_f1_each'][1]:.2f}]"
            if o.get("flags"):
                why += " [flags: " + "; ".join(o["flags"][:3]) + "]"
            out.append(dict(story=row["story"], kind="story", title=names.get(row["story"], row["story"]), url=None,
                            gold=sc.get("gold"), pred=sc.get("pred") or "none", source="key",
                            reason=f"key {self._describe_key(k)}; answer {self._describe_out(o)}. {why}"))
        return out
