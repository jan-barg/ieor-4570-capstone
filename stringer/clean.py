"""Strip site menus from an article's text, by code (decided Nov 25, Jan).

Fetched pages come back as markdown: the article plus menus, "read more" links, share buttons and
teasers for other stories. Menus are lines made almost entirely of links, so one generic rule drops
them, with no per-outlet list. The rule only chooses which lines to keep and never rewrites a line,
so every quote still matches the stored article word for word.

The rule leans toward keeping: when unsure, a line stays (Jan, Nov 25: better some junk than a lost
fact). Tested on the 384 picked articles of the 40 frozen stories against Haiku 5.5, gpt-oss-120b and
Jev: it lost the least article text (mostly photo captions and bylines), at no cost.

    kept_lines(text) -> indices of the lines to keep
    clean(text)      -> the kept lines joined back together
    runs(text)       -> the cleaned text's overlapping 8-word runs (for the wire-copy check)
"""
from __future__ import annotations

import re

LINK = re.compile(r"!?\[([^\]]*)\]\(([^)]*)\)")
BARE_URL = re.compile(r"^\s*<?https?://\S+>?\s*$")
MARKS = re.compile(r"[#*_>|`\-\s]+")
STARTS_WITH_LINK = re.compile(r"^[\s#*>\-]*!?\[")
LINK_SHARE = 0.6          # a line whose visible text is at least this share link text is a menu line
SENTENCE_WORDS = 12       # ...unless it is a sentence of this many words that merely contains a link
SENTENCE_END = (".", "!", "?", '"', "”")


def _visible(s: str) -> str:
    return MARKS.sub(" ", s).strip()


def is_menu(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    if BARE_URL.match(s):
        return True
    links = list(LINK.finditer(s))
    if not links:
        return False
    no_images = LINK.sub(lambda m: "" if m.group(0).startswith("!") else m.group(1), s)
    shown = _visible(no_images)
    if not shown:
        return True                                   # only images or empty links
    # A sentence with a link inside it ("The [majority of cases](...) remain in Congo.") is
    # article text; a teaser is a link on its own ("[Other story](...)" or "* [Other story](...)").
    if (not STARTS_WITH_LINK.match(s) and len(shown.split()) >= SENTENCE_WORDS
            and shown.rstrip().endswith(SENTENCE_END)):
        return False
    in_links = sum(len(_visible(m.group(1))) for m in links if not m.group(0).startswith("!"))
    return in_links / len(shown) >= LINK_SHARE


def kept_lines(text: str) -> list[int]:
    return [i for i, line in enumerate((text or "").split("\n")) if not is_menu(line)]


def clean(text: str) -> str:
    lines = (text or "").split("\n")
    return "\n".join(lines[i] for i in kept_lines(text))


def runs(text: str, k: int = 8) -> set[str]:
    """Overlapping k-word runs of the cleaned text, link markup reduced to the link's words."""
    words = re.findall(r"\w+", LINK.sub(lambda m: m.group(1), clean(text)).lower())
    return {" ".join(words[i:i + k]) for i in range(len(words) - k + 1)}
