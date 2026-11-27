"""Who writes the extra queries: the reworded core query, one query per side, and the
background query. The core query is always the event title.

Two writers, same output:
  template_queries  code only: title keywords, title for the sides, entity words for background
  model_queries     one call to the query_writer model (config/models.toml), which can also write
                    a side's query in that side's language (Portuguese for Brazilian outlets).
                    A story's local press (sides.local_press) gets a query the same way, saved
                    under its id in `sides` (e.g. "local_pl"), though it is never a side.

The model's answer is never unusable (Jan's rule for model JSON): its shape is enforced, the call has
a time limit, a failed or unreadable answer is asked again once in plain JSON mode, and if that fails
too the template writer's queries are used and the story says so (writer "template (fallback)").

The queries used are saved with every story, so a frozen fixture shows exactly what was searched."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field

from .. import models
from ..events import Event
from ..outlets import OutletTable
from .sides import Lens

CALL_TIMEOUT_S = 20      # a normal answer takes about 2 s
MAX_TOKENS = 4000        # thinking counts toward this on some models; the answer itself is ~150 tokens
RETRY_NOTE = ("Your last answer could not be used. Answer again with one JSON object with the keys "
              "\"reworded\", \"background\" and \"sides\" (one query per side id), and nothing else.")

STOP = set("the a an of in on at to for and or with from by after before over as its is are was were "
           "be been has have had it this that these those than into amid about against during per "
           "says said say new day second first both us".split())


@dataclass
class QuerySet:
    core: str
    reworded: str
    background: str
    sides: dict[str, str] = field(default_factory=dict)
    writer: str = "template"
    model: str | None = None
    cost_usd: float = 0.0
    errors: list = field(default_factory=list)   # why the model's answer wasn't used (fallback only)

    def as_dict(self):
        return asdict(self)


def terms(text: str, min_len=4) -> list[str]:
    words = re.findall(r"[A-Za-zÀ-ÿ0-9'-]+", text)
    out = []
    for w in words:
        k = w.lower().strip("'-")
        if len(k) >= min_len and k not in STOP and k not in out:
            out.append(k)
    return out


def entities(text: str) -> list[str]:
    """Capitalised words that aren't sentence starts: a cheap stand-in for names and places."""
    out = []
    for sent in re.split(r"(?<=[.!?])\s+", text):
        for i, w in enumerate(re.findall(r"[A-Za-zÀ-ÿ0-9'-]+", sent)):
            w = re.sub(r"['’]s$", "", w)
            if i > 0 and w[:1].isupper() and w.lower() not in STOP and w not in out and len(w) > 2:
                out.append(w)
    return out


def template_queries(ev: Event, lens: Lens) -> QuerySet:
    title_terms = terms(ev.title)
    extra = [e for e in entities(ev.summary) if e.lower() not in title_terms][:4]
    reworded = " ".join(title_terms[:7] + extra)
    bg_words = list(dict.fromkeys([e for e in entities(ev.title + ". " + ev.summary)][:6]))
    background = " ".join(bg_words) or " ".join(title_terms[:5])
    return QuerySet(core=ev.title, reworded=reworded, background=background,
                    sides={s.side_id: ev.title for s in lens.sides}, writer="template")


PROMPT = """You write web-search queries for a news research tool. The tool searches news outlets for
coverage of one event. The first search always uses the event's title. You write the others.

Return one JSON object with these keys:
- "reworded": 5 to 10 search keywords in English that describe the same event with different words
  than the title: the names, places, organisations and numbers from the summary, and synonyms for the
  title's verbs. No quotation marks, no boolean operators.
- "background": 4 to 8 keywords in English for the situation BEFORE this event: the earlier stage of
  the story, the conflict or the issue it belongs to. Leave out words that only describe this event's
  outcome, since the search is limited to articles published before the event started.
- "sides": an object with one query per side id given below. Each is a short headline-style query
  (5 to 10 words) for the same event, written in the language most of that side's outlets publish in
  (look at their web addresses: .br sites in Portuguese, .rs in Serbian (Latin script), .pl in Polish,
  .fr in French, .ru in Russian, .es in Spanish; English-language sites in English). Name the event
  the way that side's outlets would, without loaded words. Use only facts in the title and summary:
  don't add reactions, accusations or consequences they don't mention, or the search will look for
  a story that may not exist.

Example. Event title: "Ukrainian strike brings down a road span of the Kerch Strait bridge".
Sides: ukraine (kyivindependent.com, ukrinform.net), russia (tass.com, ria.ru, rg.ru).
{"reworded": "Crimean bridge Kerch road arch collapse drone missile strike traffic suspended",
 "background": "Kerch Strait Crimean bridge earlier attacks 2022 2023 Crimea supply route",
 "sides": {"ukraine": "Ukraine strikes Crimean bridge, road span destroyed",
           "russia": "Атака на Крымский мост, движение перекрыто"}}

Answer with the JSON object only."""


def _side_line(t: OutletTable, s) -> str:
    hosts = t.hosts(set(s.outlet_ids), kinds=None)[:12]
    return f"- {s.side_id} ({s.label}): {', '.join(hosts)}"


def schema(side_ids: list[str]) -> dict:
    """The answer's enforced shape: the two queries, plus one per side id when the story has any."""
    props = {"reworded": {"type": "string"}, "background": {"type": "string"}}
    required = ["reworded", "background"]
    if side_ids:
        props["sides"] = {"type": "object", "additionalProperties": False, "required": list(side_ids),
                          "properties": {i: {"type": "string"} for i in side_ids}}
        required.append("sides")
    return {"type": "json_schema", "json_schema": {"name": "search_queries", "strict": True, "schema": {
        "type": "object", "additionalProperties": False, "required": required, "properties": props}}}


def model_queries(ev: Event, lens: Lens, t: OutletTable, trace_id=None, step="query_writer") -> QuerySet:
    groups = lens.sides + ([lens.local] if lens.local else [])
    ids = [s.side_id for s in groups]
    side_lines = "\n".join(_side_line(t, s) for s in groups) or "(no sides: return \"sides\": {})"
    event = (f"Event title: {ev.title}\nSummary: {ev.summary}\nCountry: {ev.country}\n"
             f"Started: {ev.start:%Y-%m-%d %H:%M} UTC\n\nSides:\n{side_lines}")
    msgs = [{"role": "user", "content": [models.cache_block(PROMPT), models.text_block(event)]}]
    fallback = template_queries(ev, lens)   # never search with an empty query
    errors, cost, model = [], 0.0, None
    # first the enforced shape; then once more in plain JSON mode, the form this call used until Nov 27
    for fmt, note in ((schema(ids), None), ({"type": "json_object"}, RETRY_NOTE)):
        m = msgs if note is None else msgs + [{"role": "user", "content": note}]
        try:
            r = models.complete(step, m, trace_id=trace_id, name=f"query_writer:{ev.short}",
                                metadata={"event": ev.id}, max_tokens=MAX_TOKENS, response_format=fmt,
                                timeout=CALL_TIMEOUT_S)
        except Exception as e:
            if type(e).__name__ == "BudgetExceeded":      # an eval's or a run's cost cap must stop the run
                raise
            errors.append(f"{type(e).__name__}: {e}"[:300])
            continue
        cost += float((r.cost or {}).get("total") or 0.0)
        model = r.model
        data = _parse_json(r.text)
        sides = data.get("sides") if isinstance(data, dict) and isinstance(data.get("sides"), dict) else {}
        text = lambda k: str(data.get(k) or "").strip() if isinstance(data, dict) else ""
        if text("reworded") or text("background") or any(str(v or "").strip() for v in sides.values()):
            return QuerySet(core=ev.title, reworded=text("reworded") or fallback.reworded,
                            background=text("background") or fallback.background,
                            sides={i: str(sides.get(i) or ev.title).strip() for i in ids},
                            writer="model", model=model, cost_usd=round(cost, 8))
        errors.append("the answer was not a JSON object with queries in it")
    fallback.sides = {i: fallback.sides.get(i, ev.title) for i in ids}
    fallback.writer, fallback.model, fallback.cost_usd, fallback.errors = "template (fallback)", model, round(cost, 8), errors
    return fallback


def _parse_json(text: str) -> dict | None:
    """The answer as a dict, or None when it can't be read as one (never raises)."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    for cand in (text, (re.search(r"\{.*\}", text, flags=re.S) or [None])[0]):
        if not cand:
            continue
        try:
            d = json.loads(cand)
        except json.JSONDecodeError:
            continue
        if isinstance(d, dict):
            return d
    return None
