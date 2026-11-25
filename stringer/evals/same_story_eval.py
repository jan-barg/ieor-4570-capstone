"""The same-story filter's eval (module 2), plugged into the shared runner.

Inputs: the frozen stories. Each story is run the way the filter runs for real (its whole pool,
in batches), and only the articles Jan labeled by hand are scored. A second kind of item compares
whole events (for grouping follow-up events on the front page).

Answer key: stringer_private/fixtures/same_story_labels_v1.json, made by hand by Jan on the review
page; the sample it labels is fixtures/same_story_sample_v1.json (scripts/build_same_story_sample.py).
"Can't tell" labels are skipped when scoring.

Scores (the filter's main job is to drop off-topic articles, so "different" is the positive class):
  drop_precision  of the articles it marks "different", the share Jan also marked "different"
                  (low = it throws away real coverage)
  drop_recall     of the articles Jan marked "different", the share it caught
                  (low = off-topic articles reach the news brief)
  drop_f1         the two combined
  accuracy        all three verdicts exactly right
  follow_up_*     the same for "follow_up"
  events_accuracy event-vs-event pairs, all three verdicts
  no_verdict      labeled articles the model returned nothing for
  *_jan           the same scores on Jan's own labels only (the rest were drafted by Claude, blind
                  to Jan's; a Claude model that shines only on those would show a gap here)"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from .. import paths, same_story
from .runner import Item, Step

SAMPLE = paths.FIXTURES / "same_story_sample_v1.json"
LABELS = paths.FIXTURES / "same_story_labels_v1.json"


class SameStoryEval(Step):
    name = "same_story"
    model_step = "same_story"
    headline = ("drop_f1", "drop_precision", "drop_recall", "accuracy", "follow_up_f1", "events_accuracy",
                "drop_f1_jan", "accuracy_jan", "labeled", "labeled_jan", "no_verdict", "side_drop_flags")
    report_title = "Same-story filter evals"
    report_intro = ("The same-story filter reads every article a search found for a story and says whether it "
                    "covers the same event, a follow-up, or a different event; pick skips the different ones. "
                    "Each run is scored against hand-checked labels: 4 articles per story (some labeled by Jan, "
                    "the rest drafted by Claude without seeing his) plus pairs of events.")
    metric_notes = {
        "drop_f1": ("Drop F1", "The main score: how well it finds the off-topic articles to drop. It balances "
                               "the next two scores; 1 is perfect."),
        "drop_precision": ("Drop precision", "Of the articles it dropped, the share that really were off-topic. "
                                             "Low means it throws away real coverage."),
        "drop_recall": ("Drop recall", "Of the off-topic articles, the share it caught. Low means junk reaches "
                                       "the news brief."),
        "accuracy": ("Accuracy", "Share of labeled articles where its verdict (same, follow-up or different) "
                                 "matches the answer key exactly."),
        "follow_up_f1": ("Follow-up F1", "How well it spots follow-up articles (later developments of the story)."),
        "events_accuracy": ("Event pairs", "Share of event-against-event pairs judged right; used to group "
                                           "follow-up events on the front page."),
        "drop_f1_jan": ("Drop F1, Jan's labels", "Drop F1 on Jan's own labels only. A big gap from Drop F1 "
                                                 "would mean the Claude-drafted labels flatter some models."),
        "accuracy_jan": ("Accuracy, Jan's labels", "Accuracy on Jan's own labels only."),
        "labeled": ("Articles scored", "Labeled articles in this run."),
        "labeled_jan": ("By Jan", "Of those, the ones Jan labeled himself."),
        "no_verdict": ("No answer", "Labeled articles the model returned no verdict for."),
        "side_drop_flags": ("Side warnings", "Stories where it dropped far more of one side's coverage than the "
                                             "other's: a warning sign of bias, worth a look."),
    }
    class_names = {"same": "same", "follow_up": "follow-up", "different": "different", "none": "no answer"}

    def __init__(self, batch=None, all_stories=None, stories_dir=None, sample=None, labels=None, prompt=None):
        self.batch = int(batch or same_story.BATCH)
        self.all_stories = bool(all_stories)
        self.stories_dir = Path(stories_dir or paths.STORIES)
        self.sample_path = Path(sample or SAMPLE)
        self.labels_path = Path(labels or LABELS)
        self.prompt = prompt or same_story.VERSION
        if self.prompt not in same_story.PROMPTS:
            raise ValueError(f"unknown prompt {self.prompt!r}; have {sorted(same_story.PROMPTS)}")
        self.version = self.prompt + ("" if self.batch == same_story.BATCH else f"-b{self.batch}")

    # -- inputs ---------------------------------------------------------------------------------
    def _sample(self) -> dict:
        return json.loads(self.sample_path.read_text(encoding="utf-8"))

    def _dirs(self) -> dict[str, Path]:
        return {d.name[:8]: d for d in sorted(self.stories_dir.iterdir()) if (d / "gather.json").exists()}

    def load(self, only=None, split="tune") -> list[Item]:
        s = self._sample()
        split_of = {sid: sp for sp, ids in s["splits"].items() for sid in ids}
        dirs = self._dirs()
        sampled = {i["story"] for i in s["items"]}
        stories = sorted(dirs) if self.all_stories else sorted(sid for sid in dirs if sid in sampled)
        pairs = {}
        for i in s["items"]:
            if i["kind"] == "event_pair":
                pairs.setdefault(i["story"], []).append(i["other"]["short"])
        items = [Item(id=f"articles:{sid}", story=sid, data={"dir": str(dirs[sid])}, split=split_of.get(sid, "tune"))
                 for sid in stories]
        items += [Item(id=f"events:{a}", story=a, data={"dir": str(dirs[a]), "others": [str(dirs[b]) for b in bs]},
                       split=split_of.get(a, "tune")) for a, bs in sorted(pairs.items()) if a in dirs]
        if only:
            items = [i for i in items if i.story in set(only)]
        if split != "all":
            items = [i for i in items if i.split == split]
        return items

    def load_key(self) -> dict:
        """{item id: {"label", "source"}}. source "jan" = labeled by Jan on the review page,
        "claude" = drafted by Claude (blind to Jan's labels; see the labels file's notes)."""
        if not self.labels_path.exists():
            return {}
        d = json.loads(self.labels_path.read_text(encoding="utf-8"))
        # a label fixed after the review page keeps the set it came from (Jan's or Claude's)
        src = lambda v: v.get("source_before_fix", "claude") if v.get("source") == "fix" else v.get("source", "jan")
        return {k: {"label": v["label"], "source": src(v)} for k, v in d["labels"].items()}

    def key_version(self) -> str:
        if not self.labels_path.exists():
            return "no labels yet"
        d = json.loads(self.labels_path.read_text(encoding="utf-8"))
        return f"{d.get('version', '?')} ({len(d['labels'])} labels)"

    # -- running --------------------------------------------------------------------------------
    @staticmethod
    def _read(d: str) -> tuple[dict, list[dict]]:
        p = Path(d)
        meta = json.loads((p / "gather.json").read_text(encoding="utf-8"))
        arts = [json.loads(line) for line in (p / "articles.jsonl").read_text(encoding="utf-8").split("\n") if line.strip()]
        return meta, arts

    def run(self, item: Item, ctx):
        meta, arts = self._read(item.data["dir"])
        if item.id.startswith("articles:"):
            if ctx.is_code:
                return same_story.keyword_story(meta["event"], arts, meta.get("lens"))
            return same_story.filter_story(meta["event"], arts, ctx.complete, lens=meta.get("lens"), batch=self.batch,
                                           prompt=self.prompt)
        others = [self._read(d)[0]["event"] for d in item.data["others"]]
        if ctx.is_code:
            return same_story.keyword_events(meta["event"], others)
        return same_story.compare_events(meta["event"], others, ctx.complete, prompt=self.prompt)

    def plan(self, item: Item, model: str) -> list[dict]:
        meta, arts = self._read(item.data["dir"])
        if item.id.startswith("articles:"):
            return same_story.plan_story(meta["event"], arts, self.batch, self.prompt)
        others = [self._read(d)[0]["event"] for d in item.data["others"]]
        start = same_story.parse_ts(meta["event"]["start"])
        packets = [same_story.event_packet(o, start, f"E{i + 1}") for i, o in enumerate(others)]
        return [{"messages": same_story.messages_for(meta["event"], packets, "events", prompt=self.prompt),
                 "params": {"max_tokens": same_story.MAX_TOKENS}, "expect_output": 35 * len(others) + 30}]

    # -- report ---------------------------------------------------------------------------------
    def story_names(self) -> dict[str, str]:
        try:
            return {sid: e.get("title", "") for sid, e in self._sample()["events"].items()}
        except FileNotFoundError:
            return {}

    def mistakes(self, rec: dict) -> list[dict]:
        sample = {i["id"]: i for i in self._sample()["items"]}
        out = []
        for row in rec.get("items_detail") or []:
            verdicts = (row.get("output") or {}).get("verdicts") or {}
            for k, gold, pred, src in (row.get("scores") or {}).get("pairs") or []:
                if gold == pred:
                    continue
                it = sample.get(k) or {}
                target = k.split(":", 2)[2]
                if k.startswith("a:"):
                    thing, kind = it.get("article") or {}, "article"
                else:
                    target = next((o for o in verdicts if o.startswith(target)), target)
                    thing, kind = it.get("other") or {}, "event"
                v = verdicts.get(target) or {}
                out.append(dict(story=row["story"], kind=kind, title=thing.get("title") or target,
                                url=thing.get("url"), gold=gold, pred=pred, source=src,
                                reason=v.get("reason") or ""))
        return out

    # -- scoring --------------------------------------------------------------------------------
    def score(self, item: Item, output, key: dict) -> dict:
        kind = "articles" if item.id.startswith("articles:") else "events"
        prefix = f"a:{item.story}:" if kind == "articles" else f"e:{item.story}:"
        pairs = []
        for k, lab in key.items():
            gold = lab["label"]
            if not k.startswith(prefix) or gold not in same_story.VERDICTS:
                continue
            target = k[len(prefix):]
            if kind == "events":
                target = next((oid for oid in output["verdicts"] if oid.startswith(target)), target)
            pred = (output["verdicts"].get(target) or {}).get("verdict")
            pairs.append([k, gold, pred or "none", lab["source"]])
        right = sum(p[1] == p[2] for p in pairs)
        return dict(kind=kind, pairs=pairs, labeled=len(pairs), correct=right,
                    accuracy=round(right / len(pairs), 3) if pairs else None,
                    flags=len(output.get("flags") or []),
                    side_drop=sum(f.startswith("side drop") for f in output.get("flags") or []))

    def summarize(self, items: list[Item], scores: list[dict]) -> dict:
        art = [p for s in scores if s["kind"] == "articles" for p in s["pairs"]]
        evs = [p for s in scores if s["kind"] == "events" for p in s["pairs"]]
        out = dict(labeled=len(art), events_labeled=len(evs))
        out.update(metrics(art))
        ev = metrics(evs)
        out["events_accuracy"] = ev.get("accuracy")
        out["events_confusion"] = ev.get("confusion")
        out["side_drop_flags"] = sum(s.get("side_drop", 0) for s in scores if s["kind"] == "articles")
        # the same scores on Jan's own labels only: a model that does well only on the labels
        # Claude drafted would show a gap here
        jan = metrics([p for p in art if p[3] == "jan"])
        for k in ("accuracy", "drop_precision", "drop_recall", "drop_f1", "follow_up_f1"):
            out[f"{k}_jan"] = jan.get(k)
        out["labeled_jan"] = sum(p[3] == "jan" for p in art)
        out["stories"] = {s_item.story: s["accuracy"] for s_item, s in zip(items, scores) if s["kind"] == "articles"}
        return out


def _prf(pairs, cls):
    tp = sum(x[1] == cls and x[2] == cls for x in pairs)
    fp = sum(x[1] != cls and x[2] == cls for x in pairs)
    fn = sum(x[1] == cls and x[2] != cls for x in pairs)
    prec = tp / (tp + fp) if tp + fp else None
    rec = tp / (tp + fn) if tp + fn else None
    f1 = 2 * prec * rec / (prec + rec) if prec and rec else (0.0 if prec is not None and rec is not None else None)
    r = lambda x: None if x is None else round(x, 3)
    return r(prec), r(rec), r(f1)


def metrics(pairs: list[list]) -> dict:
    """Scores from [item id, gold, predicted, (label source)] rows."""
    if not pairs:
        return {}
    conf = Counter(f"{x[1]}->{x[2]}" for x in pairs)
    dp, dr, df = _prf(pairs, "different")
    fp, fr, ff = _prf(pairs, "follow_up")
    sp, sr, sf = _prf(pairs, "same")
    return dict(accuracy=round(sum(x[1] == x[2] for x in pairs) / len(pairs), 3),
                drop_precision=dp, drop_recall=dr, drop_f1=df,
                follow_up_precision=fp, follow_up_recall=fr, follow_up_f1=ff,
                same_precision=sp, same_recall=sr,
                no_verdict=sum(x[2] == "none" for x in pairs),
                gold=dict(Counter(x[1] for x in pairs)), confusion=dict(sorted(conf.items())))
