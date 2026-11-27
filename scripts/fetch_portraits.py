"""Finds and downloads one photo for each person on the approved portrait list (decision 7; Jan, Nov 26: "ok
download the portrait photos").

    python scripts/fetch_portraits.py            # -> people/photos/<slug>.<ext> and people/people.json

For each person: the main photo of their English Wikipedia article (for living people that is almost always a
free photo on Wikimedia Commons), its license and author from Commons, and an 800 px wide copy. Every entry is
written with "approved": false; Jan approves them one by one, and only approved photos reach a video
(stringer/video/people.py). A photo that isn't on Commons (likely not free) is flagged, not used.

Reads people/shortlist.json; writes people/people.json (kept: an existing entry's approval and any photo Jan
chose by hand, "pinned": true).
"""
from __future__ import annotations

import html
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stringer import paths  # noqa: E402

FOLDER = paths.PRIVATE / "video_assets" / "people"
PHOTOS = FOLDER / "photos"
WIDTH = 960          # one of Wikimedia's standard thumbnail sizes (others are rate limited hard)
PAUSE = 1.5          # seconds between people
UA = "StringerClassProject/0.1 (portrait list for a student video project; python-urllib)"
WIKI = "https://en.wikipedia.org/w/api.php"
COMMONS = "https://commons.wikimedia.org/w/api.php"

# Article titles where the plain name is ambiguous or differs.
TITLES = {
    "King Charles III": "Charles III",
    "Mike Rogers": "Mike Rogers (Michigan politician)",
    "Mike Johnson": "Mike Johnson",
    "Stephen Miller": "Stephen Miller (political advisor)",
    "John Ratcliffe": "John Ratcliffe (American politician)",
    "Lula da Silva": "Luiz Inácio Lula da Silva",
    "Ferdinand Marcos Jr.": "Bongbong Marcos",
    "Tamim bin Hamad Al Thani": "Tamim bin Hamad Al Thani",
    "Mohamed bin Zayed": "Mohamed bin Zayed Al Nahyan",
    "Péter Magyar": "Péter Magyar",
    "Ali Khamenei": "Ali Khamenei",
}
# Extra names a script may use for a person (people.py matches them, ignoring case and accents).
ALIASES = {
    "Volodymyr Zelensky": ["Volodymyr Zelenskyy", "Zelenskyy", "Zelensky"],
    "Recep Tayyip Erdogan": ["Recep Tayyip Erdoğan", "Erdogan", "Erdoğan"],
    "Kim Jong Un": ["Kim Jong-un"],
    "Lee Jae-myung": ["Lee Jae Myung"],
    "Lula da Silva": ["Luiz Inácio Lula da Silva", "Lula"],
    "JD Vance": ["J.D. Vance", "J. D. Vance", "Vance"],
    "Viktor Orbán": ["Orbán"],
    "Alexander Lukashenko": ["Lukashenko"],
}


def _open(req: urllib.request.Request, timeout: int):
    """urlopen that waits out Wikimedia's rate limit (HTTP 429: Retry-After, else 20 s, 40 s, ...)."""
    for attempt in range(6):
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            if e.code not in (429, 503) or attempt == 5:
                raise
            wait = int(e.headers.get("Retry-After") or 0) or 20 * (attempt + 1)
            print(f"    rate limited, waiting {wait} s", flush=True)
            time.sleep(min(wait, 180))
        except urllib.error.URLError:
            if attempt == 5:
                raise
            time.sleep(5 * (attempt + 1))
    raise RuntimeError("unreachable")


def get(url: str, params: dict) -> dict:
    q = url + "?" + urllib.parse.urlencode(dict(params, format="json", formatversion=2))
    with _open(urllib.request.Request(q, headers={"User-Agent": UA}), 30) as r:
        return json.load(r)


def slug(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def plain(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", text or ""))).strip()


def _batches(items: list, n: int = 50):
    for i in range(0, len(items), n):
        yield items[i:i + n]


def _resolver(d: dict) -> dict[str, str]:
    """requested title -> final title, through the API's 'normalized' and 'redirects' lists."""
    q = d.get("query", {})
    step = {x["from"]: x["to"] for x in q.get("normalized", []) + q.get("redirects", [])}

    def final(t: str) -> str:
        seen = set()
        while t in step and t not in seen:
            seen.add(t)
            t = step[t]
        return t
    return final


PAGE = dict(action="query", redirects=1, prop="pageimages|pageprops|info", piprop="name", inprop="url")


def articles(want: dict[str, str]) -> dict[str, dict]:
    """name -> its article (title, URL, main image), asking 50 titles at a time."""
    out = {}
    for part in _batches(list(want.items())):
        d = get(WIKI, dict(PAGE, titles="|".join(t for _, t in part)))
        final = _resolver(d)
        pages = {p["title"]: p for p in d.get("query", {}).get("pages", [])}
        for name, title in part:
            p = pages.get(final(title))
            if p and not p.get("missing") and "disambiguation" not in (p.get("pageprops") or {}):
                out[name] = p
        time.sleep(PAUSE)
    return out


def search(name: str, role: str) -> dict | None:
    """Fallback for a missing or ambiguous title: the first search hit for the name and role."""
    d = get(WIKI, dict(action="query", list="search", srsearch=f"{name} {role}", srlimit=1))
    hits = d.get("query", {}).get("search") or []
    if not hits:
        return None
    d = get(WIKI, dict(PAGE, titles=hits[0]["title"]))
    page = (d.get("query", {}).get("pages") or [{}])[0]
    return None if page.get("missing") else page


def _thumb(url: str, fname: str, width: int | None, thumburl: str | None = None) -> str:
    """The standard-size thumbnail URL for a Commons original (the original itself when it is small)."""
    url = url.split("?", 1)[0]                                         # Commons adds ?utm_... tracking
    if not width or width <= WIDTH or "/commons/" not in url:
        return url
    if thumburl:
        return thumburl.split("?", 1)[0]
    base = url.replace("/commons/", "/commons/thumb/", 1)
    return f"{base}/{WIDTH}px-{url.rsplit('/', 1)[1]}"


def files_info(fnames: list[str]) -> dict[str, dict]:
    """file name -> license, author and a thumbnail URL, from Commons (50 files a call); files missing there are
    looked up on English Wikipedia and marked not on Commons."""
    out = {}
    for api, on_commons in ((COMMONS, True), (WIKI, False)):
        todo = [f for f in fnames if f not in out]
        for part in _batches(todo):
            d = get(api, dict(action="query", titles="|".join(f"File:{f}" for f in part), prop="imageinfo",
                              iiprop="url|extmetadata|size|mime", iiurlwidth=WIDTH))
            final = _resolver(d)
            pages = {p["title"]: p for p in d.get("query", {}).get("pages", [])}
            for fname in part:
                p = pages.get(final(f"File:{fname}")) or {}
                ii = (p.get("imageinfo") or [None])[0]
                if not ii:
                    continue
                m = ii.get("extmetadata") or {}
                val = lambda k: plain((m.get(k) or {}).get("value", ""))  # noqa: E731
                out[fname] = dict(on_commons=on_commons, url=_thumb(ii["url"], fname, ii.get("width"), ii.get("thumburl")),
                                  page=ii.get("descriptionurl"), mime=ii.get("mime"), width=ii.get("width"),
                                  height=ii.get("height"), license=val("LicenseShortName"),
                                  license_url=val("LicenseUrl"), author=val("Artist"), credit=val("Credit"),
                                  non_free=val("NonFree"), date=val("DateTimeOriginal")[:40])
            time.sleep(PAUSE)
    return out


def download(url: str, dest: Path) -> int:
    if dest.is_file() and dest.stat().st_size > 2000:          # kept from an earlier run
        return dest.stat().st_size
    with _open(urllib.request.Request(url, headers={"User-Agent": UA}), 60) as r:
        data = r.read()
    dest.write_bytes(data)
    time.sleep(PAUSE)
    return len(data)


def save(out_f: Path, rows: list[dict]) -> None:
    out_f.write_text(json.dumps(dict(version="people-1", note="Photos for the portrait list. Only entries with "
                                     "approved: true are drawn (stringer/video/people.py).", people=rows),
                                ensure_ascii=False, indent=1), encoding="utf-8")


def main() -> None:
    people = json.loads((FOLDER / "shortlist.json").read_text(encoding="utf-8"))["people"]
    out_f = FOLDER / "people.json"
    old = {p["name"]: p for p in json.loads(out_f.read_text(encoding="utf-8")).get("people", [])} if out_f.exists() else {}
    PHOTOS.mkdir(parents=True, exist_ok=True)

    def done(name: str) -> bool:                                       # finished in an earlier run, or chosen by hand
        p = old.get(name, {})
        return bool(p.get("pinned") or (p.get("file") and not p.get("problem") and (FOLDER / p["file"]).is_file()))

    todo = [p for p in people if not done(p["name"])]
    print(f"{len(people) - len(todo)} done before, {len(todo)} to look up", flush=True)
    pages = articles({p["name"]: TITLES.get(p["name"], p["name"]) for p in todo})
    for p in todo:
        if p["name"] not in pages:
            hit = search(p["name"], p["role"])
            print(f"    searched for {p['name']}: {hit.get('title') if hit else 'nothing'}", flush=True)
            if hit:
                pages[p["name"]] = hit
            time.sleep(PAUSE)
    info = files_info(sorted({pg["pageimage"] for pg in pages.values() if pg.get("pageimage")}))

    new = {}
    for i, p in enumerate(todo, 1):
        name = p["name"]
        plain_matches = [m for m in p.get("match", []) if m != name and not re.search(r"[\\()\[\]|?*+^$]", m)]
        row = dict(name=name, role=p["role"], group=p["group"],
                   aliases=list(dict.fromkeys(plain_matches + ALIASES.get(name, []))), approved=False)
        page = pages.get(name)
        try:
            if not page:
                row["problem"] = "no Wikipedia article found"
            elif not page.get("pageimage"):
                row.update(wiki=page.get("fullurl"), problem="the article has no main photo")
            else:
                fi = info.get(page["pageimage"], {})
                row.update(wiki=page.get("fullurl"), wiki_title=page.get("title"), source_file=page["pageimage"],
                           photo=fi.get("page"), license=fi.get("license"), license_url=fi.get("license_url"),
                           author=fi.get("author"), credit=fi.get("credit"), date=fi.get("date"),
                           original_size=[fi.get("width"), fi.get("height")])
                if not fi:
                    row["problem"] = "the photo's details could not be found"
                elif not fi.get("on_commons") or fi.get("non_free"):
                    row["problem"] = "not a free photo (not on Commons)"
                elif not (fi.get("mime") or "").startswith("image/") or fi.get("mime") == "image/svg+xml":
                    row["problem"] = f"not a photo ({fi.get('mime')})"
                else:
                    ext = ".png" if fi["mime"] == "image/png" else ".jpg"
                    dest = PHOTOS / f"{slug(name)}{ext}"
                    row.update(file=f"photos/{dest.name}", bytes=download(fi["url"], dest))
        except Exception as e:                                         # noqa: BLE001 - recorded, run goes on
            row["problem"] = f"{type(e).__name__}: {str(e)[:200]}"
        prev = old.get(name, {})
        if prev.get("approved") and prev.get("source_file") == row.get("source_file"):
            row["approved"] = True
        new[name] = row
        save(out_f, [new.get(q["name"]) or old[q["name"]] for q in people if q["name"] in new or q["name"] in old])
        print(f"{i:3} {name:<28} {row.get('license') or '':<16} {row.get('problem') or row.get('file')}", flush=True)
    rows = [new.get(q["name"]) or old[q["name"]] for q in people]
    save(out_f, rows)
    got = [r for r in rows if r.get("file") and not r.get("problem")]
    print(f"{len(got)} of {len(rows)} photos, {sum(r.get('bytes', 0) for r in got) / 1e6:.1f} MB -> {PHOTOS}")


if __name__ == "__main__":
    main()
