"""The eval for module 6, the fact check, plugged into the runner (design agreed Nov 25, Jan).

Inputs: the 26 frozen stories with an answer sheet, each with its Story File (module 5's output).
One item per story, and each item checks three copies of that story's Story File:
  clean     the real Story File, as module 5 wrote it
  planted   the same file with about 4 mistakes only the judge can catch, each in its own group of
            fact_check.BATCH claims (fact_check_plant explains them). Groups with no planted claim
            are the same call as in the clean copy, so they are asked once and reused
  code      the same file with 2 mistakes the free paperwork pass must catch (no model call)

Answer keys (private, under stringer_private/):
  fixtures/planted_v1.json                        152 planted mistakes and the right outcome of each
  story_file_design/whosays/whosays_labels.json   12 claims that state a source's words as fact and
                                                  48 that name the source (module 5's hand labels)
  fixtures/fact_check_known_cases.json            the Serbia claim that reverses cause and effect;
                                                  must be dropped (its story id stays private)

Scores:
  planted_right     the main score: share of planted judge mistakes given the right outcome
  critical_misses   planted mistakes that would reach the script as a plain fact or as the outlet's
                    words (confirmed, or said with the outlet's name, or a wrong fact merely attributed)
  code_right        share of the code copy's planted mistakes caught (no model; must be 1.0)
  as_fact_named     of the 12 claims that state a source's words as fact, the share said with a source
  says_who_kept     of the 48 claims that name their source, the share not dropped
  same_twice        claims judged twice (sharing a group with a planted claim) that got the same
                    outcome both times: how steady the judge is
  clean_dropped     share of the real claims dropped (each one is listed in the report to look at;
                    "needs a name" verdicts are counted, not listed: those claims are kept, with a source)
  clean_confirmed   share of the real claims confirmed
  unchecked         real claims left without a usable judge answer (must stay 0)
  step_cost         the fact check's own cost per story (the clean copy only; the planted copy is
                    the eval's extra)
"""
from __future__ import annotations

import json
from pathlib import Path

from .. import fact_check, outlets, paths, story_file
from . import fact_check_plant as fp
from .runner import Item, Step

SHEETS = paths.FIXTURES / "answer_sheets_v2.json"
KEY = paths.FIXTURES / "planted_v1.json"
WHOSAYS = paths.PRIVATE / "story_file_design" / "whosays" / "whosays_labels.json"
HOLDOUT = {5, 10, 15, 20, 25}            # answer sheets kept out of prompt changes
KNOWN = paths.FIXTURES / "fact_check_known_cases.json"


def _serbia() -> tuple[str, str] | None:
    """The Serbia claim that reverses cause and effect, found by hand in the design pass. Read from the
    private fixtures so the public code names no real story; None when the file isn't there."""
    if not KNOWN.exists():
        return None
    d = json.loads(KNOWN.read_text(encoding="utf-8"))["must_drop"][0]
    return d["story"], d["claim"]


SERBIA = _serbia()


def _compact(sf: dict, text: bool = False) -> dict:
    """What a run keeps of a checked Story File: enough to score it and to list what it dropped."""
    rows = []
    for c in sf["claims"]:
        ch = c.get("check") or {}
        r = dict(id=c["id"], status=c.get("status"), sides=c.get("sides"), blindspot=c.get("blindspot"),
                 attribute_to=c.get("attribute_to"),
                 check={k: ch.get(k) for k in ("verdict", "problem", "why", "speaker", "rules", "cards_off",
                                               "against_event", "bad_translations", "number_note", "blindspot_removed")
                        if ch.get(k) not in (None, "", [], {})})
        r["check"].setdefault("rules", [])
        if text:
            r.update(claim=c["claim"], who_says=c.get("who_says"), independent=c.get("independent"), reason=c.get("reason"))
        rows.append(r)
    return dict(claims=rows, fact_check=sf.get("fact_check"))


def _share(a, b):
    return round(a / b, 3) if b else None


class FactCheckEval(Step):
    name = "fact_check"
    model_step = "fact_check"
    version = fact_check.VERSION
    headline = ("planted_right", "critical_misses", "code_right", "as_fact_named", "says_who_kept", "same_twice",
                "clean_dropped", "clean_confirmed", "unchecked", "step_cost", "json_retries", "claims")
    report_title = "Fact check (module 6)"
    report_intro = ("The fact check reads each story's research file and checks every claim against the article "
                    "quotes it rests on: confirmed, say with source, or dropped. Runs are scored on mistakes planted "
                    "in copies of the 26 test stories (the right outcome of each is known), on module 5's who-says "
                    "labels, and on the real files, where every drop is listed below to look at.")
    metric_notes = {
        "planted_right": ("Planted, right", "The main score: share of the planted mistakes the judge must catch that got the right outcome."),
        "critical_misses": ("Critical misses", "Planted mistakes that would reach the script as a plain fact or as the outlet's words. Should be 0."),
        "code_right": ("Paperwork caught", "Share of the planted paperwork mistakes (bad cards, look-alike addresses, early dates, wrong sides) caught by code. Must be 1."),
        "as_fact_named": ("Source added", "Of 12 real claims that state a source's words as fact, the share said with a source."),
        "says_who_kept": ("Named, kept", "Of 48 real claims that name their source, the share not dropped."),
        "same_twice": ("Same twice", "Real claims judged twice (once next to a planted one) that got the same outcome both times."),
        "clean_dropped": ("Real dropped", "Share of the real claims dropped. Each is listed under mistakes to look at."),
        "clean_confirmed": ("Real confirmed", "Share of the real claims confirmed (said plainly in the script)."),
        "unchecked": ("Unchecked", "Real claims left without a usable judge answer. Must be 0."),
        "step_cost": ("Step cost / story", "The fact check's own cost per story, in dollars (the planted copy is the eval's extra)."),
        "json_retries": ("Extra calls", "Calls beyond one per group: retries for unusable answers or left-out claims."),
        "claims": ("Claims", "Real claims checked."),
    }
    class_names = {"dropped": "Dropped", "named the speaker": "Named the speaker", "named the outlet": "Named the outlet",
                   "confirmed": "Confirmed", "unchecked": "Unchecked"}

    def __init__(self, stories_dir=None, sheets=None, key=None, workers=None):
        self.stories_dir = Path(stories_dir or paths.STORIES)
        self.sheets_path = Path(sheets or SHEETS)
        self.key_path = Path(key or KEY)
        self.workers = int(workers or 1)          # judge calls side by side within a story
        self._table = None
        self._key = None

    # -- inputs ---------------------------------------------------------------------------------
    def _sheets(self) -> dict:
        return {s["short_id"]: s for s in json.loads(self.sheets_path.read_text(encoding="utf-8"))["stories"]}

    def load(self, only=None, split="tune") -> list[Item]:
        dirs = {d.name[:8]: d for d in sorted(self.stories_dir.iterdir()) if (d / "story_file.json").exists()}
        items = [Item(id=f"story:{sid}", story=sid, data={"dir": str(dirs[sid]), "n": sh["n"]},
                      split="holdout" if sh["n"] in HOLDOUT else "tune")
                 for sid, sh in sorted(self._sheets().items(), key=lambda kv: kv[1]["n"]) if sid in dirs]
        if only:
            items = [i for i in items if i.story in set(only)]
        if split != "all":
            items = [i for i in items if i.split == split]
        return items

    def load_key(self) -> dict:
        if self._key is None:
            planted = json.loads(self.key_path.read_text(encoding="utf-8"))
            by = {}
            for r in planted["records"]:
                by.setdefault(r["story"], []).append(r)
            ws = json.loads(WHOSAYS.read_text(encoding="utf-8")) if WHOSAYS.exists() else {"stories": {}}
            self._key = dict(planted=by, version=planted["version"], n=len(planted["records"]),
                             whosays={sid: dict(as_fact=v.get("as_fact", []) + v.get("field_only", []), says_who=v.get("says_who", []))
                                      for sid, v in ws["stories"].items()},
                             whosays_version=ws.get("version"))
        return self._key

    def key_version(self) -> str:
        k = self.load_key()
        return f"{k['version']} ({k['n']} planted mistakes) + {k['whosays_version']} + Serbia C64"

    def table(self):
        if self._table is None:
            self._table = outlets.table()
        return self._table

    def _story(self, item: Item):
        d = Path(item.data["dir"])
        facts, sf = story_file.read(d)
        arts = {}
        for x in (d / "articles.jsonl").read_text(encoding="utf-8").split("\n"):
            if x.strip():
                a = json.loads(x)
                arts[a["id"]] = a
        return sf, facts, arts

    def _copies(self, item: Item, sf, facts):
        recs = self.load_key()["planted"].get(item.story, [])
        judge_recs = [r for r in recs if r["copy"] == "judge"]
        code_recs = [r for r in recs if r["copy"] == "code"]
        return fp.apply(sf, facts, judge_recs), fp.apply(sf, facts, code_recs)

    # -- running --------------------------------------------------------------------------------
    def run(self, item: Item, ctx):
        sf, facts, arts = self._story(item)
        (sf_p, facts_p), (sf_q, facts_q) = self._copies(item, sf, facts)
        memo = {}

        def complete(messages, name=None, **params):     # the planted copy reuses the clean copy's answers
            k = json.dumps([messages, params], sort_keys=True, ensure_ascii=False)
            if k not in memo:
                memo[k] = ctx.complete(messages, name=name, **params)
            return memo[k]

        model_fn = None if ctx.is_code else complete
        kw = dict(model=ctx.model, table=self.table(), workers=self.workers)
        c0 = ctx.stats.cost_usd
        _, clean = fact_check.check_story(sf, facts, arts, model_fn, **kw)
        step_cost = ctx.stats.cost_usd - c0
        _, planted = fact_check.check_story(sf_p, facts_p, arts, model_fn, **kw)
        _, code = fact_check.check_story(sf_q, facts_q, arts, None, **kw)
        groups = len(list(fact_check._batch_calls(sf, facts, fact_check.paperwork(sf, facts, arts, self.table()), ctx.model,
                                                  fact_check.BATCH)))
        return dict(clean=_compact(clean, text=True), planted=_compact(planted), code=_compact(code),
                    groups=groups, step_cost_usd=round(step_cost, 6))

    def plan(self, item: Item, model: str) -> list[dict]:
        sf, facts, arts = self._story(item)
        (sf_p, facts_p), _ = self._copies(item, sf, facts)
        seen, calls = set(), []
        for s, f in ((sf, facts), (sf_p, facts_p)):
            pw = fact_check.paperwork(s, f, arts, self.table())
            for c in fact_check.judge_plan(s, f, pw, model):
                k = json.dumps([c["messages"], c["params"]], sort_keys=True, ensure_ascii=False)
                if k not in seen:
                    seen.add(k)
                    calls.append(c)
        return calls

    # -- scoring --------------------------------------------------------------------------------
    def score(self, item: Item, output, key: dict) -> dict:
        recs = key["planted"].get(item.story, [])
        clean, planted, code = output["clean"], output["planted"], output["code"]
        res = []
        for r in recs:
            s = fp.score_record(r, planted if r["copy"] == "judge" else code)
            res.append(dict(id=r["id"], copy=r["copy"], claim=r.get("claim"), **s))
        judge = [x for x in res if x["copy"] == "judge"]
        codes = [x for x in res if x["copy"] == "code"]
        # judged twice: real claims sharing a group with a planted claim
        pos = {c["id"]: i // fact_check.BATCH for i, c in enumerate(clean["claims"])}
        hot = {pos[r["claim"]] for r in recs if r["copy"] == "judge"}
        planted_ids = {r["claim"] for r in recs if r["copy"] == "judge"}
        pc = {c["id"]: c for c in planted["claims"]}
        twice = [(fp.outcome(c), fp.outcome(pc[c["id"]])) for c in clean["claims"]
                 if pos[c["id"]] in hot and c["id"] not in planted_ids and (c.get("check") or {}).get("verdict")]
        st = {k: sum(c.get("status") == k for c in clean["claims"]) for k in fact_check.STATUSES}
        cc = {c["id"]: c for c in clean["claims"]}
        ws = key["whosays"].get(item.story) or {}
        as_fact = [cc[x]["status"] == "say with source" for x in ws.get("as_fact", []) if x in cc]
        says_who = [cc[x]["status"] != "dropped" for x in ws.get("says_who", []) if x in cc]
        fc = clean.get("fact_check") or {}
        conf = {}
        for x in judge:
            k = f"{x['expect']}->{x['got']}"
            conf[k] = conf.get(k, 0) + 1
        return dict(
            planted=len(judge), planted_ok=sum(x["right"] for x in judge), critical=sum(x["critical"] for x in judge),
            code=len(codes), code_ok=sum(x["right"] for x in codes), records=res, confusion=conf,
            planted_right=_share(sum(x["right"] for x in judge), len(judge)),
            twice=len(twice), twice_same=sum(a == b for a, b in twice),
            claims=len(clean["claims"]), **{k.replace(" ", "_"): v for k, v in st.items()},
            needs_name=sum((c.get("check") or {}).get("verdict") == "needs a name" for c in clean["claims"]),
            as_fact=len(as_fact), as_fact_ok=sum(as_fact), says_who=len(says_who), says_who_ok=sum(says_who),
            serbia_c64=(cc[SERBIA[1]]["status"] == "dropped") if SERBIA and item.story == SERBIA[0] and SERBIA[1] in cc else None,
            calls=fc.get("calls") or 0, groups=output.get("groups") or 0, errors=len(fc.get("errors") or []),
            step_cost_usd=output.get("step_cost_usd") or 0.0)

    def summarize(self, items: list[Item], scores: list[dict]) -> dict:
        tot = lambda k: sum(s.get(k) or 0 for s in scores)
        by_kind, conf = {}, {}
        for s in scores:
            for x in s.get("records") or []:
                b = by_kind.setdefault(x["kind"], dict(copy=x["copy"], n=0, right=0, critical=0, got={}))
                b["n"] += 1
                b["right"] += x["right"]
                b["critical"] += x["critical"]
                b["got"][x["got"]] = b["got"].get(x["got"], 0) + 1
            for k, n in (s.get("confusion") or {}).items():
                conf[k] = conf.get(k, 0) + n
        claims = tot("claims")
        serbia = [s["serbia_c64"] for s in scores if s.get("serbia_c64") is not None]
        return dict(
            planted_right=_share(tot("planted_ok"), tot("planted")), critical_misses=tot("critical"),
            code_right=_share(tot("code_ok"), tot("code")),
            as_fact_named=_share(tot("as_fact_ok"), tot("as_fact")), says_who_kept=_share(tot("says_who_ok"), tot("says_who")),
            same_twice=_share(tot("twice_same"), tot("twice")),
            clean_dropped=_share(tot("dropped"), claims), clean_confirmed=_share(tot("confirmed"), claims),
            clean_say_with_source=_share(tot("say_with_source"), claims),
            unchecked=tot("unchecked"), needs_name=tot("needs_name"), claims=claims,
            step_cost=round(tot("step_cost_usd") / len(scores), 4) if scores else None,
            json_retries=tot("calls") - tot("groups"), call_errors=tot("errors"),
            serbia_c64_dropped=serbia[0] if serbia else None,
            planted=tot("planted"), code_planted=tot("code"), by_kind=by_kind, confusion=conf,
            stories={i.story: s.get("planted_right") for i, s in zip(items, scores)})

    # -- report ---------------------------------------------------------------------------------
    def story_names(self) -> dict[str, str]:
        return {sid: sh["title"] for sid, sh in self._sheets().items()}

    def mistakes(self, rec: dict) -> list[dict]:
        key = self.load_key()
        by_id = {r["id"]: r for rs in key["planted"].values() for r in rs}
        out = []
        for row in rec.get("items_detail") or []:
            sc, o = row.get("scores") or {}, row.get("output") or {}
            pc = {c["id"]: c for c in (o.get("planted") or {}).get("claims", [])}
            for x in sc.get("records") or []:
                if x["right"]:
                    continue
                r = by_id.get(x["id"]) or {}
                said = (r.get("set") or {}).get("claim") or r.get("note") or x["kind"]
                why = ((pc.get(x.get("claim")) or {}).get("check") or {}).get("why", "") if x["copy"] == "judge" else ""
                out.append(dict(story=row["story"], kind=f"planted: {x['kind']}" + (" (critical)" if x["critical"] else ""),
                                title=said, url=None, gold=x["expect"], pred=x["got"], reason=why or r.get("note", ""),
                                source="planted"))
            for c in (o.get("clean") or {}).get("claims", []):
                ch = c.get("check") or {}
                if c.get("status") == "dropped" and ch.get("verdict") == "not backed":
                    out.append(dict(story=row["story"], kind=f"real claim dropped: {ch.get('problem', '')}",
                                    title=f"{c['id']}: {c.get('claim', '')}", url=None, gold="look at it", pred="dropped",
                                    reason=ch.get("why", ""), source="real file"))
        return out
