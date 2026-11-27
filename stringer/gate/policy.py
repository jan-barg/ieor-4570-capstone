"""The Gate's content check: is this a story we make? (module 0; rule settled Nov 23, narrowed Nov 26).

The rule (child-4, Jan Nov 26: "Yes, narrower rule"): refuse an event when a young child (under 13) is
killed or badly hurt by someone's violence or abuse and the story is about that child. Allowed: teenagers;
children who come out unhurt; illness, neglect and accidents; a minor as perpetrator or suspect; larger
events where children are among the victims; disasters; trials and inquiries about past killings.
(The Nov 23 rule also refused teens and children put in danger; Jan's label review narrowed it.)

How (decided Nov 26, Jan, decisions page items 1 and 4):
  1. One small model call reads the event's title, summary, category and country. The answer format
     is enforced (JSON schema), the output limit is big, an unusable answer gets one retry, and if
     that fails too the keyword rule below decides (Jan: model JSON must never be unusable).
  2. The keyword rule is also the eval's free baseline: a child word next to a harm word in the
     title refuses, unless the title points at a suspect, a wider toll or a disaster.
  3. The answer is saved per event with a hash of the text it read (gate/core.py), so the check runs
     once per event and again only when the title or summary changes.

Example: "Teen Arrested After Shooting at School" -> allow (child_role perpetrator_or_suspect); "Drone
Strike Kills Boy, 7" -> refuse (victim_central); "Sixteen-year-old hurt in knife attack" -> allow (a teen).

`complete(messages, name=..., **params)` returns an object with .text, the same shape as the eval
runner's ctx.complete; live_complete() wraps models.complete for the site."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field

from .. import calls, models
from .rules import field as ev_field

VERSION = "child-4"         # the default since Nov 26 (Jan's narrower rule; eval: 3 of 3 refusals, 1 open call)
MAX_TOKENS = 8000           # thinking counts toward this on some models; the answer itself is ~120 tokens
CALL_TIMEOUT_S = 120
VERDICTS = ("allow", "refuse")
ROLES = ("none", "victim_central", "victims_among_many", "perpetrator_or_suspect", "disaster_or_accident",
         "other_role")

SCHEMA = {"type": "json_schema", "json_schema": {"name": "content_check", "strict": True, "schema": {
    "type": "object", "additionalProperties": False, "required": ["reason", "child_role", "verdict"],
    "properties": {"reason": {"type": "string"},                       # the reason first
                   "child_role": {"type": "string", "enum": list(ROLES)},
                   "verdict": {"type": "string", "enum": list(VERDICTS)}}}}}

PROMPT_CHILD1 = """You check one news event for a site that turns news events into short explainer videos. Before any video is made, the site applies one content rule:

REFUSE the event when a child (anyone under 18) is the event's central subject as a victim: the story is about a child being hurt, killed, abused, kidnapped or put in danger.

ALLOW everything else, including:
- A minor as the perpetrator or suspect (a teenager arrested for an attack or a plot).
- Larger events where children are among the victims but the story is about the event as a whole (a strike or shelling that kills many people, children among them; a mass shooting; an inquiry into an attack on a school).
- Disasters and accidents, even when most of the dead are children (a building collapse, a fire, a flood, a crash, an earthquake).
- Stories where children appear in other roles: student protests, school or family policy, a court case, a politician's grown-up son or daughter.

How to decide: ask what the story is about.
- If you would sum it up as "a child was hurt, killed or endangered", refuse. This includes attacks aimed at a place or event meant for children (a shooting at a school, an attack on a children's game) where children are the victims.
- If you would sum it up as "an attack, disaster, protest or court case", with children as part of the toll or the cast, allow.
- When the headline itself makes a child victim the news (for example "Shell kills boy, 10"), the child is the central subject: refuse, even in a war.
- University students are adults. Youth movements and protests are allowed.

Answer with JSON only:
- reason: one or two sentences saying who the story is about and why the rule does or doesn't apply;
- child_role: none, victim_central, victims_among_many, perpetrator_or_suspect, disaster_or_accident or other_role;
- verdict: allow or refuse.

Made-up examples:
- "Man drives car into crowd outside a kindergarten, injuring five children" -> victim_central, refuse.
- "Shelling of residential district kills 14, among them three children" -> victims_among_many, allow.
- "Teenager charged over arson attack on mosque" -> perpetrator_or_suspect, allow.
- "Floods sweep away school bus; 22 pupils dead" -> disaster_or_accident, allow.
- "Five-year-old shot dead by police during traffic stop" -> victim_central, refuse.
- "Students occupy university buildings over budget cuts" -> other_role, allow.
- "Central bank raises interest rates by half a point" -> none, allow."""

# child-2 (Nov 26): two clarifications after round 1, where Haiku let through an attack outside a high school
# ("students among the wounded") and a shooting with a small child in the car. Written on the tune events;
# Haiku then made no mistakes on tune (132) or holdout (68), against 2 misses with child-1.
PROMPT_CHILD2 = PROMPT_CHILD1.replace(
    "- When the headline itself makes a child victim the news",
    "- An attack at or right outside a school (not a university) where pupils are among the people hurt counts as "
    "aimed at children: refuse, even if adults were hurt too.\n"
    "- A child caught in the danger counts as put in danger: when the headline names a child who was there when "
    "people were shot or attacked (for example in the car or the room), refuse, even if the child was not hurt.\n"
    "- When the headline itself makes a child victim the news")

# child-3 (Nov 26, Jan: "Yes, narrower rule"): after Jan's label review ("teens are not kids", "kid is safe",
# "not killed", "sad but not violent attack"), the rule covers only young children killed or badly hurt by
# someone's violence. Teens, children who come out unhurt, illness, neglect and accidents are allowed.
PROMPT_CHILD3 = """You check one news event for a site that turns news events into short explainer videos. Before any video is made, the site applies one content rule:

REFUSE the event when a young child (under 13) is killed or badly hurt by someone's violence or abuse (a shooting, a stabbing, a beating, a strike or bomb, a vehicle driven into people) and the story is about that child or those children.

ALLOW everything else, including:
- Teenagers (13 to 17) as victims: a teenager stabbed, a teen hurt at a protest, high-school students wounded. Teens are not treated as children here.
- Children who come out unhurt: rescued, found, freed, hostages released, a child who was there when someone else was shot but was not hurt.
- Illness, neglect and accidents with no attacker: a disease death, an abandoned baby, a fall, a drowning.
- A minor as the perpetrator or suspect (a teenager arrested for an attack or a plot).
- Larger events where children are among the victims but the story is about the event as a whole (a strike or shelling that kills many people, children among them; a mass shooting; an inquiry into an attack on a school).
- Disasters, even when most of the dead are children (a building collapse, a fire, a flood, a crash, an earthquake).
- Stories where children appear in other roles: student protests, school or family policy, a court case, a politician's grown-up son or daughter.

How to decide:
- Ask what the story is about. If you would sum it up as "a young child was killed or badly hurt by someone", refuse. That holds in a war too, when the headline makes the child the news (for example "Shell kills boy, 6"), and when adults were hurt as well but the child is the headline.
- Age: use any age the title or summary gives. Without an age, "child", "boy", "girl", "toddler", "baby" and primary-school pupils count as young; "teen", "teenager", "student", "high school" and "youth" count as teenagers.
- Hurt: refuse only when the child was killed or badly hurt. If the child is reported safe, unhurt or not hurt, or no child is reported hurt, allow.

Answer with JSON only:
- reason: one or two sentences saying who the story is about, the child's age group if any, and why the rule does or doesn't apply;
- child_role: none, victim_central, victims_among_many, perpetrator_or_suspect, disaster_or_accident or other_role;
- verdict: allow or refuse.

Made-up examples:
- "Man drives car into crowd outside a kindergarten, injuring five children" -> victim_central, refuse.
- "Girl, 8, stabbed to death in park; man arrested" -> victim_central, refuse.
- "Shelling of residential district kills 14, among them three children" -> victims_among_many, allow.
- "Sixteen-year-old seriously hurt in corridor knife attack" -> other_role, allow (a teenager).
- "Children led out unhurt after armed man enters nursery" -> other_role, allow (no child hurt).
- "Teenager charged over arson attack on mosque" -> perpetrator_or_suspect, allow.
- "Floods sweep away school bus; 22 pupils dead" -> disaster_or_accident, allow.
- "Central bank raises interest rates by half a point" -> none, allow."""

# child-4 (Nov 26): child-3 refused a cult leader's sentencing for killing children (Jan: allow), which child-1
# allowed. One line says a trial, sentencing, inquiry or report about past killings is about the case.
PROMPT_CHILD4 = PROMPT_CHILD3.replace(
    "- Age: use any age",
    "- A trial, sentencing, inquiry or report about past killings or abuse is about the case, not the children: "
    "allow, even when the victims were young children.\n"
    "- Age: use any age")

PROMPTS = {"child-1": PROMPT_CHILD1, "child-2": PROMPT_CHILD2, "child-3": PROMPT_CHILD3, "child-4": PROMPT_CHILD4}

RETRY_NOTE = ("Your answer couldn't be used: {why}. Answer again with only the JSON object, with the fields "
              "reason, child_role and verdict (allow or refuse).")


@dataclass
class Verdict:
    verdict: str                     # allow | refuse
    reason: str
    child_role: str = ""
    by: str = ""                     # "model", "code:keywords" or "code:keywords (fallback)"
    model: str | None = None
    prompt: str = VERSION
    calls: int = 0
    retried: bool = False
    fallback: bool = False
    errors: list = field(default_factory=list)

    @property
    def allowed(self) -> bool:
        return self.verdict == "allow"

    def as_dict(self) -> dict:
        return asdict(self)


# ---- what the model reads --------------------------------------------------------------------------

def text_of(event) -> dict:
    g = lambda k: str(ev_field(event, k) or "").strip()
    return {"title": g("title"), "summary": g("summary"), "category": g("category"), "subtype": g("subtype"),
            "country": g("country")}


def text_hash(event) -> str:
    """Changes when anything the check reads changes (Monitor the Situation edits titles and summaries)."""
    return hashlib.sha256(json.dumps(text_of(event), sort_keys=True).encode()).hexdigest()[:16]


def packet(event) -> str:
    t = text_of(event)
    kind = t["category"] + (f" / {t['subtype'].replace('_', ' ')}" if t["subtype"] else "")
    lines = [f"Title: {t['title']}", f"Summary: {t['summary'] or '(none)'}", f"Kind: {kind or '(unknown)'}"]
    if t["country"]:
        lines.append(f"Country: {t['country']}")
    return "\n".join(lines)


def messages_for(event, prompt: str = VERSION) -> list[dict]:
    return [{"role": "system", "content": PROMPTS[prompt]},
            {"role": "user", "content": "The event:\n" + packet(event)}]


def params_for(model: str = "") -> dict:
    p = dict(max_tokens=MAX_TOKENS, response_format=SCHEMA, timeout=CALL_TIMEOUT_S)
    if model.startswith("gpt-oss"):
        p["reasoning_effort"] = "low"
    return p


# ---- reading the answer ----------------------------------------------------------------------------

def parse(text: str) -> dict | None:
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        d = json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", t, flags=re.S)
        try:
            d = json.loads(m.group(0)) if m else None
        except json.JSONDecodeError:
            d = None
    return d if isinstance(d, dict) else None


def problem(d: dict | None) -> str:
    """Why an answer can't be used ("" when it can)."""
    if d is None:
        return "not a JSON object"
    if str(d.get("verdict", "")).strip().lower() not in VERDICTS:
        return "verdict must be allow or refuse"
    return ""


# ---- the keyword rule (fallback and eval baseline) -------------------------------------------------

CHILD = re.compile(r"\b(child|children|kid|kids|boy|boys|girl|girls|baby|babies|infant|infants|toddler|toddlers|"
                   r"newborn|newborns|teen|teens|teenage|teenager|teenagers|minor|minors|pupil|pupils|"
                   r"schoolchild\w*|schoolboy\w*|schoolgirl\w*|schoolkids|students?)\b", re.I)
CHILD_PLACE = re.compile(r"\b(elementary|primary|middle|high|nursery) schools?\b|\b(kindergarten|preschool|daycare|"
                         r"youth (soccer|football|camp|game|match))\b", re.I)
AGE = re.compile(r"\b(\d{1,2})[- ]year[- ]olds?\b", re.I)
HARM = re.compile(r"\b(kill\w*|dies|died|death|deaths|dead|murder\w*|shot|shoots|shooting|shooter|gunman|gunfire|"
                  r"stabb\w*|wound\w*|injur\w*|hurt|attack\w*|abduct\w*|kidnap\w*|missing|abus\w*|assault\w*|"
                  r"rap(e|ed)|loses|lost|hostage\w*|drown\w*|beaten|beating|explosion|blast|plows?|ramm\w*)\b", re.I)
SUSPECT = re.compile(r"\b(arrest\w*|suspect\w*|charged|convicted|sentenced|plot\w*|detained|accused|jailed|"
                     r"identified as|gunman, \d{2})\b", re.I)
AMONG = re.compile(r"\b(including|among|incl\.)\b", re.I)
DISASTER = re.compile(r"\b(collaps\w*|(?<!open )(?<!opens )(?<!opened )fire|blaze|flood\w*|earthquake|quake|landslide|crash\w*|derail\w*|capsiz\w*|"
                      r"sinks?|sank|stampede|storm|typhoon|cyclone|hurricane|accident\w*|outbreak|epidemic)\b", re.I)


def keyword_verdict(event, *, by: str = "code:keywords") -> Verdict:
    t = text_of(event)
    title = t["title"]
    minors = [int(a) for a in AGE.findall(title)]
    child = bool(CHILD.search(title) or CHILD_PLACE.search(title) or any(n < 18 for n in minors))
    harm = bool(HARM.search(title))
    if not (child and harm):
        return Verdict("allow", "No child victim in the headline (keyword rule).", "none", by=by)
    if SUSPECT.search(title):
        return Verdict("allow", "A child word next to a suspect word: a minor as suspect (keyword rule).",
                       "perpetrator_or_suspect", by=by)
    if AMONG.search(title):
        return Verdict("allow", "Children among a wider toll (keyword rule).", "victims_among_many", by=by)
    if t["category"].lower() == "disaster" or DISASTER.search(title):
        return Verdict("allow", "A disaster or accident (keyword rule).", "disaster_or_accident", by=by)
    return Verdict("refuse", "A child word next to a harm word in the headline (keyword rule).", "victim_central",
                   by=by)


# ---- the check -------------------------------------------------------------------------------------

_call = calls.call      # one call; a failed call counts as an empty answer (stringer/calls.py)


def judge(event, complete=None, *, model: str = "", prompt: str = VERSION, name: str = "gate_policy") -> Verdict:
    """The verdict for one event. With complete=None the keyword rule decides (no model call)."""
    if complete is None:
        return keyword_verdict(event)
    msgs = messages_for(event, prompt)
    params = params_for(model)
    errors = []
    text, err = _call(complete, msgs, params, name)
    calls, retried = 1, False
    d = parse(text)
    why = f"call failed: {err}" if err else problem(d)
    if err:
        errors.append(err)
    if why:
        retried = True
        again = msgs + ([{"role": "assistant", "content": text}] if text else []) + \
            [{"role": "user", "content": RETRY_NOTE.format(why=why)}]
        text2, err2 = _call(complete, again, params, f"{name} retry")
        calls = 2
        if err2:
            errors.append(err2)
        d = parse(text2)
        why = f"call failed: {err2}" if err2 else problem(d)
    if why:
        v = keyword_verdict(event, by="code:keywords (fallback)")
        v.reason = f"Model answer unusable after one retry ({why}); {v.reason}"
        v.model, v.prompt, v.calls, v.retried, v.fallback, v.errors = model or None, prompt, calls, retried, True, errors
        return v
    role = str(d.get("child_role") or "").strip()
    return Verdict(str(d["verdict"]).strip().lower(), str(d.get("reason") or "").strip()[:600],
                   role if role in ROLES else "", by="model", model=model or None, prompt=prompt, calls=calls,
                   retried=retried, fallback=False, errors=errors)


def live_complete(step: str = "gate_policy", trace_id=None, metadata=None, model: str | None = None):
    """A `complete` for live runs of this step (calls.live_complete with this module's step as the default)."""
    return calls.live_complete(step, trace_id=trace_id, metadata=metadata, model=model)
