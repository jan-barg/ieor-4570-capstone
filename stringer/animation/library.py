"""The picture library's catalogue: every piece the scene kit draws (render/anim/kit/), with what it looks like.

The storyboard model matches each thing its animation needs to one of these names, or "none", through the JSON
schema (an enum of these names): code never compares words (Jan, Nov 27). A thing matched to "none" is drawn by
the drawing model itself, in the kit's style. The 39 pieces were grown in three batches from the things past
events needed most (stringer_private/analysis/props/; 84% of mentions covered on Nov 27).
"""
from __future__ import annotations

CATALOGUE = {
    "drone": "a generic fixed-wing military drone (drawn)",
    "missile": "a generic cruise missile in flight (drawn)",
    "bridge": "a long road-and-rail bridge over water with a steel arch (drawn)",
    "cargo ship": "a container cargo ship (drawn)",
    "plane": "a passenger airliner: side view, flying, taking off or parked (drawn), or seen from above (small drawing)",
    "train": "a train seen from the front (small drawing)",
    "document": "a sheet of paper with lines of text and a seal (small drawing)",
    "ballot box": "a ballot box with a paper going in (small drawing)",
    "flag": "a plain flag with no country's design (small drawing)",
    "computer chip": "a computer chip (small drawing)",
    "smoke": "a rising column of grey smoke (effect)",
    "explosion": "a cut-paper explosion flash (effect)",
    "sea": "open sea with waves (setting)",
    "sky": "sky with clouds (setting)",
    "shore": "a low green coastline seen from the sea (setting)",
    "politician": "a person in a suit and tie, no face; can gesture while speaking (drawn)",
    "police officer": "a person in a dark police uniform and peaked cap, no face (drawn)",
    "soldier": "a person in olive fatigues, vest and helmet, no face (drawn)",
    "protester": "a person in casual clothes holding up a blank sign; also a crowd of them (drawn)",
    "judge": "a person in a black judge's robe, no face; also a row of judges behind a wooden bench (drawn)",
    "person": "an ordinary person in casual clothes, no face (drawn)",
    "podium": "a lectern with a cluster of microphones and a speaker of any kind behind it (drawn)",
    "microphone": "a reporter's handheld microphone, or several held out by reporters (drawn)",
    "meeting table": "a long table with people seated behind it, up to 20 in two rows (suits, or judges, soldiers, "
                     "police, plain people), name cards and water (drawn)",
    "government building": "a classical stone building with columns, steps and a dome: a parliament, ministry or court (drawn)",
    "fire": "paper flames (effect)",
    "room": "an indoor room, wall and floor, with a press backdrop, a curtain or windows (setting)",
    "street": "a city street: a row of buildings with windows, a pavement and a road (setting)",
    "fighter jet": "a generic grey military fighter jet in flight, side view, afterburner lit (drawn)",
    "building": "one ordinary building: an office tower, an apartment block or a house (drawn)",
    "oil refinery": "an oil refinery: storage tanks, distillation towers, pipes and a burning flare stack (drawn)",
    "computer": "a laptop, a desktop computer, or a server rack with blinking lights; screens blank (drawn)",
    "airport": "an airport: terminal, control tower, and an apron with a parked airliner (drawn)",
    "military base": "a military base: arched hangar, barracks, watchtower, radar dome, fence and gate (drawn)",
    "warship": "a generic grey navy warship with a gun and a radar mast (drawn)",
    "diplomat": "a person in a suit carrying a briefcase, no face (drawn)",
    "lawyer": "a person in a suit holding a folder, no face (drawn)",
    "ambulance": "a white ambulance van with a flashing light bar and a checkered stripe, no emblem (drawn)",
    "ground": "open ground under a sky: grass, a paved plaza or sand, for buildings standing alone (setting)",
}

NONE = "none"


def pieces() -> list[str]:
    """The names the storyboard may answer with: every piece, then "none"."""
    return list(CATALOGUE) + [NONE]


def text() -> str:
    """The catalogue as the storyboard model reads it, one piece a line."""
    return "\n".join(f"- {k}: {v}" for k, v in CATALOGUE.items())
