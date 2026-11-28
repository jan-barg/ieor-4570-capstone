"""What the three model steps of the custom animation read: the storyboard's instructions, the drawing guide (the
kit's whole API and the rules), the cue placer's instructions, and the JSON shape each answer must take.

The texts come from the Nov 27 test rounds (stringer_private/animation_test/, rounds 2-6) with round 6's open
problems fixed (Nov 28):
  - an effect is drawn right after the thing it happens to, before the people in front of it (round 6 drew a flash
    and smoke over a crowd's heads, which read as a blast in the crowd);
  - a table seats up to 20, in two rows past 9 (a claim said 15 judges; the kit stopped at 9);
  - a podium draws its own speaker, of any kind (a court's president at the podium wore a suit);
  - nothing holds still after a cut (one drawing was static for its last seconds); Nov 28's first build run
    still ended on a held frame and showed a whole room with the judges as a thin strip, so the storyboard may no
    longer plan a hold, the last camera move runs to the end, and the main subject is framed big; a later run
    paused its push at a cue and put the podium on the bench, so the camera may not pause at all and each piece
    gets its own place;
  - the first full A/B listed claims its picture did not show (a strike played under a line about the crew's
    safe evacuation), so the storyboard lists only the claims the moment itself shows;
  - the first full A/B drew a cause one side disputes (the storyboard's own avoid named it) and smoke no account
    reported, so avoid is written before show, may not be drawn by either step, and binds the drawing even where
    the storyboard's show contradicts it;
  - cue words come from the finished script, and the drawing has until the voice is recorded (it outlasted the
    writer twice in round 5);
  - planned beside the writer, the storyboard guessed which moment the script would tell, and in the final A/B 2 of
    4 stories had no beat citing its claims (the script told another fire, or the same strike from other sources'
    claims). So the storyboard now starts once the script is checked, reads the beats a window fits under, picks
    one, and plans what that beat's sentence tells (fix 2, Nov 28). Its first run picked a line on killings and
    people fleeing and drew soldiers pointing at civilians on a sunny meadow, so it may not pick violence done to
    people.
"""
from __future__ import annotations

from . import library

# ---- the hard rule for disputed results (round 2: without it, 3 of 3 drawings showed a disputed collapse) ----

HARD_RULE = """

HARD RULE FOR DISPUTED RESULTS: if any account in the file disputes what the attack or event did (how much damage, whether something collapsed, broke or sank, how many died), the animation stops before the result. It shows the approach and the hit, then a flash and smoke that hide the target until the end. Never draw a break, gap, collapse, fall, sinking or ruin that any account disputes."""

# ---- 1. the storyboard (Haiku, low effort): the moment, its cues, and what it needs from the library ----

STORYBOARD_SYSTEM = """You plan one custom animation for a 60-second vertical news video. Read the checked research file and the script's beats listed after it. The animation plays in a window inside one of those beats, under its words, while its sentence is spoken. Pick the beat whose sentence tells the story's most important moment that can be seen (an event, an action, a place; not a disagreement between accounts, and not a count on its own). Never pick a moment of violence done to people (killing, wounding, sexual violence, abuse, people driven from their homes): cartoon figures make light of it. Pick another beat, or show the institution, place or thing involved instead of the act. Then describe a short animation of what that sentence tells (6 to 10 seconds, flat paper-cutout shapes, no words or numbers). Another model will draw it, so make it concrete.

Answer with JSON:
- beat: the number of the beat you pick.
- agreed: what every account in the file agrees on about this moment.
- avoid: what is disputed and must not be drawn as settled ("" if nothing).
- show: one or two sentences: what the animation shows, in order. Only what the beat's sentence tells and the claims it cites state, nothing from before or after it. Nothing in show or cues may draw what avoid names: a disputed cause gets no picture at all (no device, person, group or company shown doing it or failing), and nothing hints at fire, smoke, damage or injury that no account reports.
- cues: 1 to 3 moments in the motion that will be timed to words of the beat's sentence, in the order they happen: {name (one lowercase word), what happens}.
The picture keeps moving gently until the end (a slow camera push, people breathing, smoke drifting): never plan a moment where it "holds", "freezes" or the camera "pauses"; a cue is marked by something in the scene moving (a lean, a raised arm, a light), never by the camera stopping. Plan it close: the window is small on a phone, so the people or thing the moment is about fill it, not a wide room around them.
- needs: see the picture library below.

The facts: only what the claims state. When accounts disagree (the file marks "conflicts with", and the flags may say claims disagree with the event summary), the animation shows only what they agree on, or keeps the disputed part unclear.""" + HARD_RULE + """

THE PICTURE LIBRARY. The animation is drawn from these pieces (name: what it looks like):
""" + library.text() + """
Prefer a moment the library can show, when it is just as true and as important. Fill "needs": every thing the animation shows (people, objects, buildings, settings, effects), each with the library piece a viewer would accept as it, or "none". Same thing under another name counts ("UAV" is drone); a generic stand-in of the same kind counts; a different kind does not (a passenger plane is not a fighter jet). Anything "none" will be drawn by hand."""


def storyboard_schema(beats: list[str]) -> dict:
    """beats: the numbers of the beats it may pick (as strings), so its answer is always one of them."""
    s = {"type": "string"}
    obj = lambda props: {"type": "object", "additionalProperties": False, "required": list(props), "properties": props}  # noqa: E731
    return {"type": "json_schema", "json_schema": {"name": "storyboard", "strict": True, "schema": obj({
        "beat": {"type": "string", "enum": list(beats)}, "agreed": s, "avoid": s, "show": s,   # avoid is written before show
        "cues": {"type": "array", "items": obj({"name": s, "what": s})},
        "needs": {"type": "array", "items": obj({"thing": s, "piece": {"type": "string", "enum": library.pieces()}})}})}}


# ---- 2. the drawing (Sonnet): the kit and the rules ----

KIT_DOC = """THE DRAWING
Write JavaScript: one function, `function draw(k, p, cues) { ... }`, that draws ONE frame of the animation. It is called for every frame (30 a second) with p going from 0 (the beat starts) to 1 (it ends). The beat lasts about 5 to 12 seconds. Every call draws the whole frame from scratch. Helper functions and constants may sit inside draw or above it.
- k.ctx: a 2D canvas context. The window is k.W x k.H = 900 x 600 (origin top left). All kit sizes are in these pixels.
- cues: {name: 0..1}, when each cue's word is spoken within the beat, in the order the storyboard gives them. Time the key motions to them, e.g. k.seg(p, cues.impact - 0.05, cues.impact + 0.1). Always give a fallback (cues.impact ?? 0.55).
- k.seg(p, a, b): 0..1 progress of p from a to b, clamped. k.ease.in / out / inOut(t). k.lerp(a, b, t). k.clamp01(t). k.rng(seed): seeded random (never Math.random).
- k.pal: paper, paperDeep, ink, cobalt, vermilion, mustard, sea, land, sky, smoke, white.
- k.stipple(alpha): paper grain over the window; call it last, alpha about 0.4.

EFFECTS (k.fx), all in window pixels:
- k.fx.camera(x, y, zoom): put scene point x, y at the window's centre, zoomed. Use between k.ctx.save() and k.ctx.restore(). k.fx.mixView(a, b, t) blends two views {x, y, zoom}, for a slow push-in.
- k.fx.curve(a, b, bend) -> points from a to b ({x, y}), bowed sideways (bend about -0.3..0.3). k.fx.trail(points, t, {tail, color, width, dash}) draws the path up to t and returns the head {x, y, angle}; tail 0..1 keeps only the last part behind the head. k.fx.along(points, t) -> {x, y, angle} without drawing.
- k.fx.flash(x, y, t, {size}): a cut-paper explosion flash over t 0..1 (blooms fast, shrinks away).
- k.fx.pulse(x, y, t, {size, color}): an expanding ring over t 0..1.
- k.fx.smoke(x, y, t, {size, time, seed, drift}): a column of paper smoke rising from x, y; t 0..1 grows it, time (pass p * 8) keeps it moving once grown. It is dense at its base, so it hides whatever is at x, y. size is its final width (200 to 320 hides a bridge arch).
- k.fx.fire(x, y, size, {time, t}): paper flames, base at x, y, about 1.3 x size high; t 0..1 grows them.
- k.fx.shake(t, amount) -> {x, y}: a decaying shake over t 0..1 (zero outside it); translate by it.
- k.fx.whiteout(alpha): a paper-white flash over the whole window.
- k.fx.cutout(fn): runs fn() with a paper-cutout drop shadow under whatever it draws (for your own shapes).

THE SCENE KIT: finished paper-cutout pieces. Use them for everything they cover and do not redraw them. People are faceless by design: never draw faces, and never try to make a person look like a real one.
Settings (draw one first; each fills the window):
- k.scene.room({floor, backdrop: 'panel' | 'curtain' | 'windows' | null}) -> {floor}: indoors; 'panel' is a press-conference wall. floor about 0.82 * H.
- k.scene.street({ground, time}) -> {ground, road}: a city street with buildings; people stand at ground.
- k.scene.ground({ground, kind: 'grass' | 'plaza' | 'sand', time}) -> {ground}: open ground under a sky, for a building, base, refinery or airport standing on its own; ground (the horizon) about 0.6 * H.
- by the sea: k.scene.sky({horizon, time}), k.scene.sea({horizon, time}), k.scene.shore({side: 'left' | 'right', horizon}).
People (feet at x, y; h = height in px, 150 to 320; time: p * 8; seed varies hair and clothes):
- k.scene.person(kind, x, y, h, {facing: 1 | -1, time, seed, gesture, walk, color, sign}): kind 'politician', 'police', 'soldier', 'protester' (holds up a blank sign; sign: false for none), 'judge' (a robe), 'diplomat' (carries a briefcase), 'lawyer' (holds a folder) or 'person'. gesture 0..1 raises the arm on the facing side (talking: 0.4 + 0.3 * Math.sin(time * 2.5)); walk: true steps in place.
- k.scene.crowd(x0, x1, y, h, {kind, count, rows, time, seed, facing, walk}): a crowd of one kind along y.
Things:
- k.scene.podium(x, floorY, size, {speaker, gesture, time, seed, mics}) -> {speaker: {x, y}, top}: a lectern with microphones, size = its height (120 to 180). speaker: the kind of person speaking ('judge' for a court's president, 'politician', 'police', 'soldier', 'diplomat', 'lawyer', 'person'); the kit draws them behind the lectern, talking. Leave speaker out for an empty podium.
- k.scene.microphone(x, y, size, {angle, arm, seed}): a reporter's microphone, head at x, y, pointing along angle (-Math.PI / 2 = up); arm: true adds a sleeve reaching in from beyond it (place the arm's end off the window's edge).
- k.scene.table(x, floorY, width, {seats, kind, time, seed, speaker}) -> {top, seats: [{x, y}]}: a table from the front, people seated behind it. seats 1 to 20, as the claims say (past 9, the kit seats them in two rows); kind 'politician' (suits, the default), 'judge' (robed judges behind a wooden bench: a court), 'soldier', 'police', 'diplomat' or 'person'; speaker = the index of the one talking (or -1). Width 600 to 860 for a full bench. Its top edge is at floorY - 0.2 * width and the heads sit just above it (two rows reach about 0.15 * width higher), so a camera on the people aims near floorY - 0.27 * width and lets the table's front run off the bottom.
- k.scene.government(x, groundY, width, {dome, columns, wings}) -> {top, door, dome, roof, front}: a classical stone government building (parliament, ministry, court); width 300 to 500. roof: {x, y, w} along its roof line; front: {x, y, w, h}, its facade (y its middle); windows: [{x, y}], the wings' windows (where flames show from inside).
- k.scene.building(x, groundY, width, height, {kind: 'office' | 'apartment' | 'house', seed, lit}) -> {top, left, right, door, roof, front}: one ordinary building, centred on x; height null for its usual shape. roof: {x, y, w}; front: {x, y, w, h}.
- k.scene.refinery(x, groundY, width, {time, flare}) -> {flare: {x, y}, tanks, top}: an oil refinery; width 300 to 500.
- k.scene.airport(x, groundY, width, {time, plane}) -> {tower, gate, apron, top}: terminal, control tower, apron with a parked airliner; width 500 to 700.
- k.scene.militaryBase(x, groundY, width, {time, open}) -> {hangar, tower, gate, top}: hangar, barracks, watchtower, radar dome, fence; open 0..1 lifts the gate barrier.
- k.scene.computer(x, y, size, {kind: 'laptop' | 'desktop' | 'server', time}) -> {screen: {x, y, w, h}, top}: on a desk at y (a server rack stands on the floor at y); screens are blank.
- k.scene.ambulance(x, groundY, size, {time, lights, moving, facing}): side view, size = length (150 to 260).
- k.scene.fighterJet(x, y, size, {angle, flip, time, afterburner}), k.scene.airliner(x, y, size, {angle, flip, time, gear}): side views, nose along angle (0 = right; flip: true faces left); size = length.
- k.scene.warship(x, waterY, size, {time, flip}) -> {gun, mast, deck}: a grey navy warship on the sea; size = length.
- k.scene.bridge, k.scene.drone, k.scene.missile, k.scene.ship: a long arch bridge, a generic drone, a generic missile, a cargo ship.
- k.prop(name, x, y, size, {rotate, alpha}): small drawings: ballot box, document, flag (plain, no country's design), plane, train, computer chip, cargo ship.

DRAW IN THIS ORDER: camera (optional) -> setting -> each building or thing from back to front, with ITS OWN effects drawn right after it (a building's fire, smoke and flash right after the building) -> the people and things in front of it -> restore -> k.stipple.

Rules:
- The look: a calm explainer graphic for the news. One clear thing happens, readable on a phone, with gentle motion and a slow camera push toward the action. No clutter.
- Never hold still: every second something moves. Pass time: p * 8 to every piece that takes it (people breathe, smoke drifts, lights blink). The camera never stops, not even for a moment around a cue (no flat stretch between two moves): one slow push of at least 10% more zoom, or a slow pan, runs from p = 0 all the way to p = 1 (ease it gently, k.ease.inOut over the whole run at most), so the final frames still move.
- Frame it big: the window is shown about 840 x 560 pixels on a phone. In every view the people or thing the line is about fill at least half the window's height; zoom in (1.3 to 2) on a bench, a crowd or a building rather than showing a whole room with empty walls. A wide view may open the animation, never close it.
- An effect happens to one thing: fire, smoke, a flash or a pulse sits on that thing, at a point it returns (roof, front, door, top), never on people unless the claims say it happened to them. People in front of that thing stay in front of its effects, so a crowd outside a burning building is never under the flash: draw the effect before the crowd, and keep it above their heads or beside them.
- Count what the claims count: 15 judges means seats: 15.
- No words, letters or numbers anywhere (signs and papers stay blank; the box drops any text). No faces, blood or bodies. No real country's flag.
- Only k.ctx and the k helpers. Never use Math.random, Date, performance, timers, fetch, document, window, self, imports or eval, not even inside a string: the code runs in a locked box and is refused if it names them.
- Fast: each frame under 20 ms.
- Buildings, bases, refineries and airports stand on ground (k.scene.ground, k.scene.street, or the land of k.scene.shore), never on the sea or in the sky. Ships sit on the sea.
- Keep the heads in: when the moment is about people, the camera aims at their faces and shoulders, not at the furniture or floor in front of them, and every head stays inside the window with room above it in every frame, at the closest zoom too.
- Nothing covers a person's head: papers, signs and props go beside people, in their hands or on tables, never in front of a head.
- Give each piece its own place: a podium stands clear of a table, a person clear of someone else's furniture, an arm never reaches across another piece. When two things share a spot, one is plainly behind the other (smaller or higher, drawn first).
- The facts: show only what the claims you illustrate state. When accounts disagree, show only what they agree on, or keep the disputed part unclear; never draw one side's account as settled.
- The storyboard's avoid binds you too: draw nothing it names, even where its show asks for it (then leave that part out): no disputed cause (no device, person or company shown doing it or failing), and no fire, smoke, damage or injury that no account reports."""

DRAW_INTRO = ("You draw one custom animation for a 60-second vertical news video. A storyboard says what it shows; the "
              "checked research file below it is for the facts. It plays in a window inside one beat of the video, under "
              "that beat's text, while the beat's sentence is spoken.\n\n")
DRAW_OUTRO = "\n\nAnswer with JSON: plan (at most 40 words: how the motion goes) and code (the JavaScript)."


def missing_note(missing: list[str]) -> str:
    """The pieces the library lacks, for the drawing model to draw itself (Jan's fallback, Nov 27)."""
    if not missing:
        return ""
    return ("\n\nNOT IN THE KIT: " + "; ".join(missing) + ". Draw these yourself so they sit with the kit's pieces: flat shapes in "
            "k.pal colours, wrapped in k.fx.cutout(() => { ... }) for the paper shadow, simple and bold like a paper cutout. "
            "Everything else comes from the kit.")


def draw_system(missing: list[str]) -> str:
    return DRAW_INTRO + KIT_DOC + missing_note(missing) + HARD_RULE + DRAW_OUTRO


DRAW_SCHEMA = {"type": "json_schema", "json_schema": {"name": "animation", "strict": True, "schema": {
    "type": "object", "additionalProperties": False, "required": ["plan", "code"],
    "properties": {"plan": {"type": "string"}, "code": {"type": "string"}}}}}

# ---- 3. the cue placer (Haiku, low effort): which spoken word each cue fires on ----

CUES_SYSTEM = """You time a short news animation to its narration. The animation plays in a window while one sentence is spoken, and a few moments in it (cues) must land on spoken words.

For each cue, pick the one word of the line that is spoken when that moment should happen: the word that names it, or the closest word that leads into it. The cues happen in the order given, so pick their words in that order too, each a different word, spread through the line rather than bunched on one word. Pick from the numbered words exactly as given.

Answer with JSON: one field per cue name, each a numbered word from the list."""


def cues_schema(names: list[str], words: list[str]) -> dict:
    """One field per cue, each an enum of the line's numbered words ("03 flames"), so the answer is always a word
    of this line and code can tell repeated words apart."""
    tokens = numbered(words)
    props = {n: {"type": "string", "enum": tokens} for n in names}
    return {"type": "json_schema", "json_schema": {"name": "cue_words", "strict": True, "schema": {
        "type": "object", "additionalProperties": False, "required": list(props), "properties": props}}}


def numbered(words: list[str]) -> list[str]:
    return [f"{i:02d} {w}" for i, w in enumerate(words)]
