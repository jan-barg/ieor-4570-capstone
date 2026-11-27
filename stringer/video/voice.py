"""Step 2: the voice reads the whole script once, and its timings become the clock.

The voice gets only each beat's `voice` text (the line with its word marks taken out by shots.voice),
one line per beat, never the `say` text. Code takes the marks out itself, so it knows which letters each
mark covered; the voice sends back when every letter (or word) is spoken; that gives:
  - each word's start and end (captions);
  - each beat's start, on its first word (a shot runs until the next beat starts);
  - each mark's start and end (the animation pinned to those words).

Engines (all return the same narration dict):
  ElevenLabs  the real voice, one "with timestamps" call (key ELEVENLABS_API_KEY in stringer/.env); v4 Turbo,
              which reads the voice director's tags (direct.py)
  MacVoice    the render test's stand-in macOS system voice (free; word starts only)
  Paced       no voice at all: silent audio and evenly paced words (tests and quick layout renders)

Recordings are saved under their text, engine, voice and settings, so the same script is never paid
for twice (paths.PRIVATE/video_cache/voice/).

    n = narrate(beats, ElevenLabs())                 # v4 Turbo (Jan's pick, Nov 26)
    n["beats"][1] -> {"n": 2, "start": 6.12, "end": 13.01, "first_word": 15, "last_word": 31}
    n["marks"][0] -> {"beat": 2, "mark": "place", "text": "Crimea", "start": 10.73, "end": 11.12, ...}
"""
from __future__ import annotations

import base64
import difflib
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from .. import keys, paths, shots

CACHE = paths.PRIVATE / "video_cache" / "voice"
OPENING_MAX = 0.1      # silence before the first word longer than this is cut (a tagged voice can open with 0.3 s)
MAX_TEMPO = 1.12       # the most a recording is sped up to fit the length bar (ffmpeg atempo keeps the pitch)
HOLD = 1.5             # seconds the sources card stays up after the last word
LEAD = 0.05            # a cut lands this long before its beat's first word (inside the pause)
SWIFT = paths.CODE / "render" / "voice" / "tts.swift"


class VoiceError(RuntimeError):
    pass


# ---- the text, with every mark's letters ---------------------------------------------------------------

def voice_spans(say: str) -> tuple[str, list[tuple[str, int, int]]]:
    """The voice text of one line and its marks as (name, first char, end char), computed the same way
    shots.voice() builds the text, letter by letter."""
    chars: list[tuple[str, int | None]] = []
    names, pos = [], 0
    for k, m in enumerate(shots.MARK.finditer(say or "")):
        chars += [(c, None) for c in say[pos:m.start()]]
        chars += [(c, k) for c in m.group(2).strip()]
        names.append(m.group(1))
        pos = m.end()
    chars += [(c, None) for c in (say or "")[pos:]]
    out: list[tuple[str, int | None]] = []
    for c, tag in chars:                                    # runs of whitespace become one space
        if c.isspace():
            if out and out[-1][0] == " ":
                continue
            out.append((" ", None))
        else:
            out.append((c, tag))
    res = [x for i, x in enumerate(out) if not (x[0] == " " and i + 1 < len(out) and out[i + 1][0] in ",.;:!?")]
    while res and res[0][0] == " ":
        res.pop(0)
    while res and res[-1][0] == " ":
        res.pop()
    text = "".join(c for c, _ in res)
    if text != shots.voice(say):
        raise VoiceError(f"voice text mismatch for line {say[:60]!r}")
    spans = []
    for k, name in enumerate(names):
        idx = [i for i, (_, tag) in enumerate(res) if tag == k]
        if idx:
            spans.append((name, idx[0], idx[-1] + 1))
    return text, spans


def script_text(beats: list[dict]) -> tuple[str, list[tuple[int, int]], list[dict]]:
    """The whole text the voice reads (beats joined by a line break), each beat's char range, and every
    mark with its absolute char range."""
    parts, ranges, marks, at = [], [], [], 0
    for i, b in enumerate(beats):
        t, spans = voice_spans(b["say"])
        if t != b["voice"]:
            raise VoiceError(f"beat {b.get('n')}: its voice text is not its line without marks")
        ranges.append((at, at + len(t)))
        marks += [dict(beat=i, mark=name, c0=at + s, c1=at + e) for name, s, e in spans]
        parts.append(t)
        at += len(t) + 1
    text = "\n".join(parts)
    if "[" in text or "]" in text:
        raise VoiceError("a bracket is left in the text for the voice")
    return text, ranges, marks


def words_of(text: str) -> list[dict]:
    return [dict(w=m.group(0), c0=m.start(), c1=m.end()) for m in re.finditer(r"\S+", text)]


# ---- engines -------------------------------------------------------------------------------------------

def _duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True).stdout.strip()
    return float(out)


class ElevenLabs:
    """One call to ElevenLabs' text-to-speech "with timestamps" endpoint. Returns a time for every letter."""
    engine = "elevenlabs"
    URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice}/with-timestamps?output_format=mp3_44100_128"
    # The models that read [tags] as directions (tried Nov 26: the timestamps call works with all three and
    # times the tag's letters too, which narrate() drops). Flash would say the tag out loud.
    TAG_MODELS = ("eleven_v3", "eleven_v4", "eleven_v4_turbo")

    # Jan, Nov 26, after the A/B: "v4 turbo with expressive tags". Same price per letter as Flash v2.5.
    MODEL = "eleven_v4_turbo"

    def __init__(self, model: str = MODEL, voice: str = "JBFqnCBsd6RMkjVDRZzb", speed: float = 1.0,
                 stability: float = 0.5, similarity: float = 0.75, style: float = 0.0, retries: int = 3):
        self.model, self.voice, self.speed = model, voice, speed
        self.settings = dict(stability=stability, similarity_boost=similarity, style=style, use_speaker_boost=True,
                             speed=speed)
        self.retries = retries

    def key(self) -> dict:
        return dict(engine=self.engine, model=self.model, voice=self.voice, settings=self.settings)

    @property
    def tags(self) -> bool:
        return self.model in self.TAG_MODELS

    def with_speed(self, speed: float) -> "ElevenLabs":
        s = self.settings
        return ElevenLabs(self.model, self.voice, speed, s["stability"], s["similarity_boost"], s["style"], self.retries)

    def speak(self, text: str, out: Path) -> dict:
        body = json.dumps(dict(text=text, model_id=self.model, voice_settings=self.settings)).encode()
        last = None
        for attempt in range(self.retries):
            req = urllib.request.Request(self.URL.format(voice=self.voice), data=body, method="POST",
                                         headers={"xi-api-key": keys.get("elevenlabs_api_key"),
                                                  "content-type": "application/json"})
            t0 = time.time()
            try:
                with urllib.request.urlopen(req, timeout=180) as r:
                    data = json.load(r)
                    cost = r.headers.get("character-cost")
                break
            except urllib.error.HTTPError as e:
                last = f"HTTP {e.code}: {e.read().decode(errors='replace')[:300]}"
                if e.code not in (429, 500, 502, 503, 504):
                    raise VoiceError(f"ElevenLabs refused the call: {last}") from None
            except (urllib.error.URLError, TimeoutError) as e:
                last = str(e)
            time.sleep(2 * (attempt + 1))
        else:
            raise VoiceError(f"ElevenLabs failed {self.retries} times: {last}")
        out.write_bytes(base64.b64decode(data["audio_base64"]))
        al = data.get("alignment") or {}
        chars = list(zip(al.get("characters") or [], al.get("character_start_times_seconds") or [],
                         al.get("character_end_times_seconds") or []))
        return dict(chars=chars, seconds=_duration(out), credits=int(cost) if cost and cost.isdigit() else None,
                    call_seconds=round(time.time() - t0, 2))


class MacVoice:
    """The render test's stand-in: a macOS system voice that reports when each word starts."""
    engine = "macos"

    def __init__(self, voice: str = "Samantha"):
        self.voice = voice

    def key(self) -> dict:
        return dict(engine=self.engine, voice=self.voice)

    def speak(self, text: str, out: Path) -> dict:
        if shutil.which("swift") is None:
            raise VoiceError("the stand-in voice needs macOS (swift)")
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "t.txt").write_text(text, encoding="utf-8")
            subprocess.run(["swift", str(SWIFT), str(d / "t.txt"), str(d / "a.caf"), str(d / "m.json")],
                           check=True, capture_output=True, timeout=300)
            v = json.loads((d / "m.json").read_text(encoding="utf-8"))
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(d / "a.caf"), "-ar", "44100", "-ac", "1",
                            "-b:a", "128k", str(out)], check=True)
        per_second = v["sampleRate"] * (v["bytesPerFrame"] if max(m["offset"] for m in v["marks"]) > v["frames"] * 1.01 else 1)
        units = _utf16_to_index(text)
        starts = [(units.get(m["loc"], None), m["offset"] / per_second) for m in v["marks"]]
        return dict(word_starts=[(i, t) for i, t in starts if i is not None], seconds=_duration(out), credits=0)


def _utf16_to_index(text: str) -> dict[int, int]:
    """macOS reports positions in UTF-16 units; map them to Python string indexes."""
    out, u = {}, 0
    for i, ch in enumerate(text):
        out[u] = i
        u += 2 if ord(ch) > 0xFFFF else 1
    return out


class Paced:
    """No voice: silent audio, words evenly paced (2.6 a second by default), a pause between beats."""
    engine = "paced"

    def __init__(self, words_per_second: float | None = None, pause: float = 0.35, audio: bool = True):
        self.wps = words_per_second or shots.limits()["words_per_second"]
        self.pause, self.audio = pause, audio

    def key(self) -> dict:
        return dict(engine=self.engine, wps=self.wps, pause=self.pause)

    def with_speed(self, speed: float) -> "Paced":
        return Paced(self.wps * speed, self.pause, self.audio)

    def speak(self, text: str, out: Path) -> dict:
        t, starts, prev_end = 0.0, [], None
        for m in re.finditer(r"\S+", text):
            if prev_end is not None and "\n" in text[prev_end:m.start()]:
                t += self.pause                              # the pause between beats
            n = max(1, shots.spoken_words(m.group(0)))
            starts.append((m.start(), round(t, 3), round(t + n / self.wps * 0.9, 3)))
            t += n / self.wps
            prev_end = m.end()
        seconds = round(t + 0.3, 3)
        if self.audio:
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
                            "-t", str(seconds), "-b:a", "64k", str(out)], check=True)
        return dict(word_times=starts, seconds=seconds, credits=0)


# ---- timings -------------------------------------------------------------------------------------------

def _char_times(text: str, chars: list[tuple[str, float, float]]) -> list[tuple[float, float] | None]:
    """A (start, end) for every letter of text, from the voice's letters (which may differ slightly)."""
    got = "".join(c for c, _, _ in chars)
    times: list[tuple[float, float] | None] = [None] * len(text)
    if got == text:
        return [(s, e) for _, s, e in chars]
    sm = difflib.SequenceMatcher(None, text, got, autojunk=False)
    for a, b, size in sm.get_matching_blocks():
        for k in range(size):
            _, s, e = chars[b + k]
            times[a + k] = (s, e)
    return times


def word_timings(text: str, spoken: dict) -> list[dict]:
    """Every word of text with its start and end in seconds, from whatever the engine returned."""
    words = words_of(text)
    if "chars" in spoken:
        ct = _char_times(text, spoken["chars"])
        for w in words:
            ts = [t for t in ct[w["c0"]:w["c1"]] if t]
            w["start"], w["end"] = (ts[0][0], ts[-1][1]) if ts else (None, None)
    elif "word_times" in spoken:
        by = {c: (s, e) for c, s, e in spoken["word_times"]}
        for w in words:
            w["start"], w["end"] = by.get(w["c0"], (None, None))
    else:                                                    # word starts only (the macOS voice)
        starts = sorted(spoken["word_starts"])
        for w in words:
            hit = [t for c, t in starts if w["c0"] <= c < w["c1"]]
            w["start"], w["end"] = (hit[0], None) if hit else (None, None)
    for k, w in enumerate(words):                            # a word with no time gets one between its neighbours
        if w["start"] is None:
            prev = next((x["start"] for x in reversed(words[:k]) if x["start"] is not None), None)
            nxt = next((x["start"] for x in words[k + 1:] if x["start"] is not None), None)
            w["start"] = (prev + nxt) / 2 if prev is not None and nxt is not None else (prev + 0.3 if prev is not None else 0.0)
            w["guessed"] = True
    for k, w in enumerate(words):
        nxt = words[k + 1]["start"] if k + 1 < len(words) else spoken["seconds"]
        if w["end"] is None:
            w["end"] = min(nxt, w["start"] + 0.07 * len(re.sub(r"[^\w']", "", w["w"])) + 0.12)
        w["end"] = max(w["end"], w["start"] + 0.04)
    return words


def timeline(beats: list[dict], spoken: dict, text: str, ranges: list[tuple[int, int]], marks: list[dict]) -> dict:
    words = word_timings(text, spoken)
    for w in words:
        w["beat"] = next(i for i, (a, b) in enumerate(ranges) if a <= w["c0"] < b + 1)
    bt = []
    for i, b in enumerate(beats):
        idx = [k for k, w in enumerate(words) if w["beat"] == i]
        if not idx:
            raise VoiceError(f"beat {b.get('n')} has no spoken words")
        bt.append(dict(n=b.get("n", i + 1), first_word=idx[0], last_word=idx[-1]))
    for i, x in enumerate(bt):
        if i == 0:
            x["start"] = 0.0
        else:
            prev_end = words[bt[i - 1]["last_word"]]["end"]
            x["start"] = max(prev_end, words[x["first_word"]]["start"] - LEAD)
    for i, x in enumerate(bt):
        x["end"] = bt[i + 1]["start"] if i + 1 < len(bt) else spoken["seconds"] + HOLD
    mk = []
    for m in marks:
        ws = [k for k, w in enumerate(words) if w["c0"] < m["c1"] and w["c1"] > m["c0"]]
        mk.append(dict(beat=m["beat"], n=bt[m["beat"]]["n"], mark=m["mark"], text=text[m["c0"]:m["c1"]],
                       first_word=ws[0], last_word=ws[-1], start=words[ws[0]]["start"], end=words[ws[-1]]["end"]))
    r3 = lambda v: round(v, 3)
    return dict(words=[dict(w=w["w"], beat=w["beat"], start=r3(w["start"]), end=r3(w["end"]),
                            **({"guessed": True} if w.get("guessed") else {})) for w in words],
                beats=[dict(x, start=r3(x["start"]), end=r3(x["end"])) for x in bt],
                marks=[dict(m, start=r3(m["start"]), end=r3(m["end"])) for m in mk],
                seconds=r3(spoken["seconds"]), duration=r3(spoken["seconds"] + HOLD))


# ---- the whole step ------------------------------------------------------------------------------------

def scaled(spoken: dict, tempo: float) -> dict:
    """A take's timings when its audio plays tempo times faster (every time divided by tempo)."""
    f = 1.0 / tempo
    out = dict(spoken, seconds=round(spoken["seconds"] * f, 3))
    if "chars" in spoken:
        out["chars"] = [[c, round(a * f, 4), round(b * f, 4)] for c, a, b in spoken["chars"]]
    if "word_times" in spoken:
        out["word_times"] = [[c, round(a * f, 4), round(b * f, 4)] for c, a, b in spoken["word_times"]]
    if "word_starts" in spoken:
        out["word_starts"] = [[c, round(t * f, 4)] for c, t in spoken["word_starts"]]
    return out


def shifted(spoken: dict, cut: float) -> dict:
    """A take's timings once its first cut seconds are trimmed off (times before the cut become 0)."""
    sub = lambda t: round(max(0.0, t - cut), 4)  # noqa: E731
    out = dict(spoken, seconds=round(max(0.0, spoken["seconds"] - cut), 3))
    if "chars" in spoken:
        out["chars"] = [[c, sub(a), sub(b)] for c, a, b in spoken["chars"]]
    if "word_times" in spoken:
        out["word_times"] = [[c, sub(a), sub(b)] for c, a, b in spoken["word_times"]]
    if "word_starts" in spoken:
        out["word_starts"] = [[c, sub(t)] for c, t in spoken["word_starts"]]
    return out


def trim(audio: Path, cut: float, out: Path) -> None:
    """The recording without its first cut seconds (free, no new voice call)."""
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(audio), "-af",
                    f"atrim=start={cut:.3f},asetpts=PTS-STARTPTS", "-b:a", "128k", str(out)], check=True)


def stretch(audio: Path, tempo: float, out: Path) -> None:
    """The recording played tempo times faster at the same pitch (ffmpeg atempo); free, no new voice call."""
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(audio), "-filter:a", f"atempo={tempo:.4f}",
                    "-b:a", "128k", str(out)], check=True)


def _cache_key(engine, text: str) -> str:
    return hashlib.sha256(json.dumps(dict(engine.key(), text=text), sort_keys=True).encode()).hexdigest()[:24]


def directed_text(beats: list[dict], text: str, directed: list[str]) -> tuple[str, list[int]]:
    """The text the voice reads when the lines carry delivery tags (direct.py), and for every letter of the
    plain text, its index in that tagged text. A tagged line whose words differ is read plain."""
    from .direct import untag
    if len(directed) != len(beats):
        raise VoiceError(f"{len(directed)} directed lines for {len(beats)} beats")
    parts, keep, at = [], [], 0
    for i, (b, t) in enumerate(zip(beats, directed)):
        plain, k = untag(t or "")
        if plain != b["voice"]:
            t, k = b["voice"], list(range(len(b["voice"])))
        keep += [at + j for j in k]
        parts.append(t)
        at += len(t)
        if i + 1 < len(beats):
            keep.append(at)                                  # the line break between beats
            at += 1
    spoken = "\n".join(parts)
    if "".join(spoken[i] for i in keep) != text:
        raise VoiceError("the directed lines don't give back the script's words")
    return spoken, keep


def narrate(beats: list[dict], engine, *, cache_dir: Path | None = None, directed: list[str] | None = None,
            tempo: float = 1.0, trim_opening: bool = False) -> dict:
    """The narration for the checked beats: audio file, every word, beat and mark with its times.
    A recording already made for the same text and voice is reused for free.
    directed: each beat's line with delivery tags (direct.py), used only by a voice that reads tags.
    tempo: play the recording this much faster (stretch(); same recording, so no new credits).
    trim_opening: cut the silence before the first word down to LEAD (trim(); free)."""
    text, ranges, marks = script_text(beats)
    spoken_text, keep = text, None
    if directed and getattr(engine, "tags", False):
        spoken_text, keep = directed_text(beats, text, directed)
        if spoken_text == text:
            keep = None
    cache = Path(cache_dir or CACHE)
    cache.mkdir(parents=True, exist_ok=True)
    key = _cache_key(engine, spoken_text)
    audio, meta = cache / f"{key}.mp3", cache / f"{key}.json"
    reused = audio.exists() and meta.exists()
    if reused:
        spoken = json.loads(meta.read_text(encoding="utf-8"))
        spoken["credits_now"] = 0
    else:
        spoken = engine.speak(spoken_text, audio)
        meta.write_text(json.dumps(spoken, ensure_ascii=False), encoding="utf-8")
        spoken["credits_now"] = spoken.get("credits")
    if abs(tempo - 1.0) > 1e-3:
        fast = cache / f"{key}-x{tempo:.3f}.mp3"
        if not fast.exists():
            stretch(audio, tempo, fast)
        spoken, audio = scaled(spoken, tempo), fast
    if keep is not None and "chars" in spoken:
        ch = spoken["chars"]                                 # the tags' letters are timed too: drop them
        if len(ch) == len(spoken_text):
            spoken = dict(spoken, chars=[ch[i] for i in keep])
        # otherwise the letters are matched to the plain text one by one (_char_times), tags left unmatched
    if trim_opening:
        opening = word_timings(text, spoken)[0]["start"]
        if opening > OPENING_MAX:
            cut = round(opening - LEAD, 3)
            short = cache / f"{Path(audio).stem}-s{cut:.3f}.mp3"
            if not short.exists():
                trim(Path(audio), cut, short)
            spoken, audio = shifted(spoken, cut), short
    tl = timeline(beats, spoken, text, ranges, marks)
    spoken_words = sum(shots.spoken_words(b["say"]) for b in beats)
    return dict(tl, audio=str(audio), text=text, chars=len(spoken_text), voice=engine.key(), reused=reused,
                tempo=round(tempo, 3),
                spoken_text=spoken_text if keep is not None else None,
                credits=spoken.get("credits"), credits_now=spoken["credits_now"], call_seconds=spoken.get("call_seconds"),
                words_per_second=round(spoken_words / spoken["seconds"], 2) if spoken["seconds"] else None)
