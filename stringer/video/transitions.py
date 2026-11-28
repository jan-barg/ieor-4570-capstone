"""How one beat's picture gives way to the next: the mix is on by default (Jan's OK, Nov 28).

The switch: STRINGER_TRANSITIONS in the environment, or transitions= for make.make (plan.build and make.prepare
take it from make.make and draw cuts unless given one).
  unset, "on", "1", "mix"   the mix (mix() below): motion where the story changes section or kind of picture, cuts
                            elsewhere;
  "off", "0"                every change is a cut and the plan carries no "enter" at all, as before transitions;
  a kind's name             that kind at every change, to see one kind across a whole video.

A beat that does not open on a cut gets "enter": {"kind", "frames", "pre"}. The change starts "pre" frames before the
beat's first frame (in the pause before its first word; the beat shows its first frame until then) and lasts
"frames"; the outgoing beat plays to its end, then holds its last frame until the change is over.
render/src/transitions.js draws each kind:
  dissolve  the new picture fades in over the old;
  slide     a new sheet slides in from the right over the old, which drifts left a little;
  push      both move left together, as if the camera travelled along one long sheet;
  tear      the old sheet is torn away to the left along a ragged edge, the new one underneath;
  wipe      a vermilion band sweeps left to right, the new picture behind it.
"""
from __future__ import annotations

import os

KINDS = {"dissolve": 9, "slide": 12, "push": 12, "tear": 16, "wipe": 14}     # frames, at 30 a second
PRE = 1 / 3                # the share of a change that comes before the first word
MIN_FRAMES = 45            # a beat under 1.5 s on either side of a change gets a cut: no room to move
MAPS = ("map_locate", "map_link", "map_spread")
STYLES = ("off", "mix") + tuple(KINDS)


def style(value: str | None = None) -> str:
    """The switch: an explicit value wins; otherwise STRINGER_TRANSITIONS. Unset or unknown is the mix."""
    v = (value if value is not None else os.environ.get("STRINGER_TRANSITIONS", "")).strip().lower()
    if v in ("0", "off", "false", "no", "cut", "cuts"):
        return "off"
    return v if v in KINDS else "mix"


def mix(a: dict, b: dict) -> str | None:
    """The mix: the kind for the change from beat a to beat b, or None for a cut.
    Motion marks where the story turns a page; within a run of facts on cards, cuts keep the pace."""
    if a["shot"] == "hook":
        return "tear"              # the cover is torn open: the story starts
    if b["shot"] == "sides":
        return "slide"             # a new sheet: how each side tells it
    if b["shot"] == "sources":
        return "dissolve"          # a quiet close
    if a["shot"] in MAPS and b["shot"] in MAPS:
        return "push"              # on to the next place
    if (a["shot"] in MAPS) != (b["shot"] in MAPS):
        return "dissolve"          # the picture changes kind: a map gives way to a card, or a card to a map
    return None                    # card to card: a cut


def choose(beats: list[dict], how: str = "off") -> list[str | None]:
    """The kind each beat enters with (None: a cut), in order. beats: the plan's beats (shot, frames)."""
    how = style(how)
    out: list[str | None] = [None] * len(beats)
    if how == "off":
        return out
    for i in range(1, len(beats)):
        a, b = beats[i - 1], beats[i]
        if min(a["frames"], b["frames"]) < MIN_FRAMES:
            continue
        out[i] = mix(a, b) if how == "mix" else how
    return out


def add(beats: list[dict], how: str = "off") -> dict:
    """Marks each beat that does not open on a cut with "enter" (in place). Returns the plan's note:
    {"style", "kinds": [one per change, "cut" for a cut]}, or {} with the switch off."""
    how = style(how)
    if how == "off":
        return {}
    kinds = choose(beats, how)
    for b, k in zip(beats, kinds):
        if k:
            b["enter"] = dict(kind=k, frames=KINDS[k], pre=int(KINDS[k] * PRE))
    return dict(style=how, kinds=[k or "cut" for k in kinds[1:]])
