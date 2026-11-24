"""Who writes the extra queries: the reworded core query, one query per side, and the
background query. The core query is always the event title.

Two writers, same output:
  template_queries  code only: title keywords, title for the sides, entity words for background
  model_queries     one call to the query_writer model (config/models.toml), which can also write
                    a side's query in that side's language (Portuguese for Brazilian outlets)

The queries used are saved with every story, so a frozen fixture shows exactly what was searched."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field

from .. import models
from ..events import Event
from ..outlets import OutletTable
from .sides import Lens

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


def model_queries(ev: Event, lens: Lens, t: OutletTable, trace_id=None, step="query_writer") -> QuerySet:
    side_lines = "\n".join(_side_line(t, s) for s in lens.sides) or "(no sides: return \"sides\": {})"
    event = (f"Event title: {ev.title}\nSummary: {ev.summary}\nCountry: {ev.country}\n"
             f"Started: {ev.start:%Y-%m-%d %H:%M} UTC\n\nSides:\n{side_lines}")
    msgs = [{"role": "user", "content": [models.cache_block(PROMPT), models.text_block(event)]}]
    r = models.complete(step, msgs, trace_id=trace_id, name=f"query_writer:{ev.short}",
                        metadata={"event": ev.id}, max_tokens=2000,
                        response_format={"type": "json_object"})
    data = _parse_json(r.text)
    sides = data.get("sides") or {}
    qs = QuerySet(core=ev.title, reworded=str(data.get("reworded") or "").strip(),
                  background=str(data.get("background") or "").strip(),
                  sides={s.side_id: str(sides.get(s.side_id) or ev.title).strip() for s in lens.sides},
                  writer="model", model=r.model, cost_usd=r.cost["total"])
    fallback = template_queries(ev, lens)   # never search with an empty query
    qs.reworded = qs.reworded or fallback.reworded
    qs.background = qs.background or fallback.background
    return qs


def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, flags=re.S)
        return json.loads(m.group(0)) if m else {}
