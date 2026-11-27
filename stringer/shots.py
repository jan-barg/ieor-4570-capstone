"""The shot catalog and the checks both script modules share (module 7 writes scripts, module 8 draws them).

The catalog is one file, config/shot_catalog.json (settled Nov 26, Jan: "All as recommended"): the 13
shots, their blanks and word marks, the B-roll list, the word budget and the tones. Code here reads
the marks in a narration line, turns a line into what the voice says, counts spoken words (numbers
as they are read aloud: "1,441" is six words), and runs the on-screen check: every number and name on
screen must come from the claims the beat cites, and quoted words must match the quote letter for
letter. Module 7 runs the check so a failure can still be fixed; module 8 runs it again as a last
guard.

    marks("Officials say [count 1,441 homes] flooded.") -> [("count", "1,441 homes")]
    voice(...)         -> "Officials say 1,441 homes flooded."
    spoken_words(...)  -> 10 (officials say one thousand four hundred forty one homes flooded)
    on_screen_problems(texts, allowed, quotes=...) -> ["the number 12 isn't in the cited claims", ...]
"""
from __future__ import annotations

import functools
import json
import re

from . import paths

CATALOG = paths.CODE / "config" / "shot_catalog.json"

MARK = re.compile(r"\[(\w+) ([^\[\]]+)\]")


@functools.lru_cache(maxsize=1)
def catalog() -> dict:
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def limits() -> dict:
    return catalog()["limits"]


def shot_names() -> list[str]:
    return list(catalog()["shots"])


def all_marks() -> list[str]:
    out = []
    for s in catalog()["shots"].values():
        out += [m for m in s["marks"] if m not in out]
    return out


# ---- marks and the voice -----------------------------------------------------------------------------

def marks(text: str) -> list[tuple[str, str]]:
    """The word marks in a line, in order: [(mark name, spoken words)]."""
    return [(m.group(1), m.group(2).strip()) for m in MARK.finditer(text or "")]


def stray_brackets(text: str) -> bool:
    """True when a bracket is left after the well-formed marks are read (a broken or nested mark)."""
    rest = MARK.sub(" ", text or "")
    return "[" in rest or "]" in rest


def voice(text: str) -> str:
    """What the voice says: the marks taken out, their words kept."""
    t = MARK.sub(lambda m: m.group(2).strip(), text or "")
    return re.sub(r"\s+([,.;:!?])", r"\1", re.sub(r"\s+", " ", t)).strip()


def display(text: str) -> str:
    """The line as a reader sees it: quote marks become quotation marks, other marks just their words."""
    t = MARK.sub(lambda m: f"“{m.group(2).strip()}”" if m.group(1) == "quote" else m.group(2).strip(), text or "")
    return re.sub(r"\s+", " ", t).strip()


# ---- spoken words ------------------------------------------------------------------------------------

def _under_100(n: int) -> int:
    return 0 if n == 0 else (2 if n > 20 and n % 10 else 1)      # "forty-one" is two spoken words, "twelve" one


def _under_1000(n: int) -> int:
    w = 0
    if n >= 100:
        w, n = 2, n % 100                      # "four hundred"
    return w + _under_100(n)


def int_words(n: int) -> int:
    """Words in an integer read aloud: 1441 -> "one thousand four hundred forty one" -> 6."""
    if n == 0:
        return 1
    w = 0
    for scale in (10 ** 12, 10 ** 9, 10 ** 6, 1000):
        if n >= scale:
            w += int_words(n // scale) + 1
            n %= scale
    return w + (_under_1000(n) if n else 0)


_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _number_words(s: str) -> int:
    whole, _, dec = s.replace(",", "").partition(".")
    if not whole:
        return 0
    n = int(whole)
    if not dec and "," not in s and len(whole) == 4 and 1100 <= n <= 2099 and not 2000 <= n <= 2009:
        w = _under_100(n // 100) + (_under_100(n % 100) if n % 100 else 1)   # a year: "twenty twenty-six", "nineteen hundred"
    else:
        w = int_words(n)
    return w + (1 + len(dec) if dec else 0)                     # "two point five"


def spoken_words(text: str) -> int:
    """Spoken words in a line's voice text, numbers read aloud ("$474" is "four hundred seventy-four
    dollars", "50%" is "fifty percent")."""
    n = 0
    for tok in voice(text).split():
        if not re.search(r"\d", tok):
            if re.search(r"\w", tok):
                n += 1
            continue
        n += sum(_number_words(x) for x in _NUMBER.findall(tok))
        n += tok.count("%") + tok.count("$") + tok.count("€") + tok.count("£")
        n += sum(1 for piece in re.split(r"[-–/]", _NUMBER.sub("", tok)) if re.fullmatch(r"[A-Za-z]{3,}\W*", piece or ""))
    return n


def seconds(words: int) -> float:
    return round(words / limits()["words_per_second"], 1)


# ---- the on-screen check -----------------------------------------------------------------------------

_DIGITS = re.compile(r"\d[\d,.]*\d|\d")
_WORD_NUMS = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8",
              "nine": "9", "ten": "10", "eleven": "11", "twelve": "12", "dozen": "12", "thirteen": "13", "fourteen": "14",
              "fifteen": "15", "sixteen": "16", "seventeen": "17", "eighteen": "18", "nineteen": "19",
              "hundred": "100", "thousand": "1000", "million": "1000000", "billion": "1000000000"}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_ONES = {w: int(v) for w, v in _WORD_NUMS.items() if int(v) < 10}


def numbers(text: str) -> set[str]:
    """Numbers in a text, digits or number words, without commas ("1,441" and "1441" are the same;
    "sixteen" is 16, "twenty-one" is 21)."""
    out = {n.replace(",", "").rstrip(".") for n in _DIGITS.findall(text or "")}
    out |= {n.split(".")[0] for n in out if "." in n}
    low = (text or "").lower()
    out |= {v for w, v in _WORD_NUMS.items() if re.search(rf"\b{w}\b", low)}
    for tens, one in re.findall(rf"\b({'|'.join(_TENS)})(?:[- ]({'|'.join(_ONES)}))?\b", low):
        out.add(str(_TENS[tens] + (_ONES[one] if one else 0)))
    return out


def _digits_only(text: str) -> set[str]:
    out = {n.replace(",", "").rstrip(".") for n in _DIGITS.findall(text or "")}
    return out | {n.split(".")[0] for n in out if "." in n}


# Capitalised words that aren't names (sentence starts and the like). On-screen text is written in
# sentence case, so the other capitalised words are names.
NOT_NAMES = set("""a an the and or but nor of in on at to for from by with without after before over under
up down into onto off out as is are was were be been it its this that these those he she they we you i his her
their our who what when where why how no not yes all some many most more less few new old first last next
one two three four five six seven eight nine ten than then there here now today tonight yesterday tomorrow
says said say reports reported report calls called call also still only just about around nearly almost
later earlier overnight afterwards afterward soon recently previously initially finally meanwhile since until
week month year day night morning evening monday tuesday wednesday thursday friday saturday sunday
january february march april may june july august september october november december
mr mrs ms dr st per via vs""".split())


def _stem(w: str) -> str:
    w = re.sub(r"(['’]s|['’])$", "", w.lower())
    return w[:5] if len(w) > 5 else w          # "Russian" matches "Russia", "Ukrainian" matches "Ukraine"


def name_words(text: str) -> list[str]:
    """Capitalised words in on-screen text that should be names, as written."""
    out = []
    for w in re.findall(r"[A-Z][\w'’.-]*", text or ""):
        w = w.rstrip(".'’-")
        if len(w) < 2 or w.lower() in NOT_NAMES or re.sub(r"['’]s$", "", w).lower() in NOT_NAMES:
            continue
        if w not in out:
            out.append(w)
    return out


def _norm_quote(s: str) -> str:
    s = (s or "").translate(str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "«": '"', "»": '"',
                                           "–": "-", "—": "-", " ": " "}))
    return re.sub(r"\s+", " ", s).strip(" \t.,;:!?\"'").casefold()


def quote_matches(words: str, quote: str) -> bool:
    """The marked words are the quote, or one unbroken stretch of it, letter for letter (typography and
    letter case aside)."""
    w, q = _norm_quote(words), _norm_quote(quote)
    return bool(w) and len(w.split()) >= 3 and w in q


# Words that may be capitalised in on-screen labels without being names from the file: titles, offices
# and plain descriptions ("US President", "House Democratic Leader", "Left-leaning outlets").
COMMON = set("""president vice prime minister ministry secretary house senate congress parliament leader ceo chief
director general governor mayor chair chairman chairwoman spokesperson spokesman spokeswoman ambassador envoy
commander deputy acting former senior top head official officials government army military police court supreme
federal national state interior foreign defense defence health transport transportation justice finance
company board manager democratic democrat democrats republican republicans left right centre center leaning
outlets outlet media press agency""".split())
_US = re.compile(r"(?<!\w)(US|U\.S\.?|USA|United States|America|American|Americans|Washington)(?!\w)")
_US_WORDS = {"US", "U.S", "USA", "United", "States", "America", "American", "Americans"}


def _stem_set(text: str) -> set[str]:
    """Stems of a text's words, hyphenated words whole and in their parts ("Al-Maren": al-ma, al, maren)."""
    out = set()
    for w in re.findall(r"[\w'’-]+", text or ""):
        out.add(_stem(w))
        out |= {_stem(x) for x in re.split(r"[-.]", w) if x}
    return out


def on_screen_problems(texts: list[str], allowed: str, *, quotes: list[tuple[str, str]] = (), names: str = "") -> list[str]:
    """texts: what the beat puts on screen (titles, labels, values, names). allowed: the cited claims'
    text (and the names the file gives with them): every number must be there. names: the rest of the
    story's text (every kept claim, the event, the side labels, the speakers): a name may come from
    there too, or be a title or office (COMMON). quotes: (marked words, the quote they must match).
    Returns the problems in plain words; empty when the beat passes."""
    probs = []
    have_nums = numbers(allowed)
    stems = _stem_set(allowed) | _stem_set(names) | {_stem(w) for w in COMMON}
    us = bool(_US.search(f"{allowed} {names}"))
    for t in texts:
        if not t:
            continue
        for n in sorted(_digits_only(t)):
            if n not in have_nums:
                probs.append(f"the number {n} on screen (\"{t}\") isn't in the cited claims")
        for w in name_words(t):
            if us and w in _US_WORDS:
                continue
            parts = [p for p in re.split(r"[-.]", w) if p and not p[0].isdigit() and not p.islower()]
            if _stem(w) not in stems and not all(_stem(p) in stems for p in parts):
                probs.append(f"the name \"{w}\" on screen (\"{t}\") isn't in the story's claims")
    for words, quote in quotes:
        if not quote_matches(words, quote):
            probs.append(f"the quoted words \"{words}\" don't match the quote letter for letter")
    return probs
