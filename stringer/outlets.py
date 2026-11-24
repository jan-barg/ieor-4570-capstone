"""Module 3: outlet labels.

The idea: outlets.csv is a hand-checked lookup table, one row per outlet. Code turns a link's
web address into that outlet's labels by looking it up. Nothing is guessed: a link that matches
no row stays unrated.

Example: https://edition.cnn.com/2026/11/05/politics/x -> host edition.cnn.com -> try
edition.cnn.com, then cnn.com -> CNN: Lean Left, reliability 0.66, US, not state media.

Lookup rule (map, module 3): drop www./m./amp., try the whole host, then drop one label at a
time from the left (never below two labels). Path-scoped rows (pbs.org/newshour) win over the
plain host. X posts (x.com/<handle>/status/..) match an outlet's X handle or are flagged as an
X account and stay unrated."""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from . import paths

COLUMNS = ["outlet_id", "name", "domains", "x_handles", "kind", "country", "us_lean",
           "us_lean_opinion", "opinion_paths", "allsides_name", "allsides_date",
           "allsides_confidence", "reliability", "reliability_domain", "state_media",
           "state_media_entity", "state_media_year", "wikidata", "notes"]
KINDS = {"news", "wire", "official", "intergovernmental", "research", "platform"}
LEANS = {"", "Left", "Lean Left", "Center", "Lean Right", "Right", "Mixed"}
STATE_LEVELS = {
    "State-Controlled": "state-controlled",
    "Captured Public": "state-controlled",
    "Captured Private": "state-controlled",
    "Independent Public": "independent public",
    "Independent State-Funded": "independent public",
    "Independent State-Funded and State-Managed": "independent public",
    "Independent State-Managed": "independent public",
}
# Folder names that mark opinion on any outlet. Per-outlet extras live in opinion_paths.
OPINION_FOLDERS = {"opinion", "opinions", "commentisfree", "op-ed", "op-eds", "oped",
                   "editorial", "editorials", "columnist", "columnists"}
STRIP_PREFIXES = ("www.", "m.", "amp.", "mobile.")
X_HOSTS = {"x.com", "twitter.com", "mobile.twitter.com", "mobile.x.com"}
LOW_RELIABILITY = 0.5   # settled Nov 24: flag below 0.5, never drop


@dataclass
class Outlet:
    outlet_id: str
    name: str
    domains: list[str]
    x_handles: list[str]
    kind: str
    country: str
    us_lean: str
    us_lean_opinion: str
    opinion_paths: list[str]
    allsides_name: str
    allsides_date: str
    allsides_confidence: str
    reliability: float | None
    reliability_domain: str
    state_media: str
    state_media_entity: str
    state_media_year: str
    wikidata: str
    notes: str
    raw: dict = field(repr=False, default_factory=dict)

    @classmethod
    def from_row(cls, r: dict) -> "Outlet":
        split = lambda s: [x.strip() for x in (s or "").split(";") if x.strip()]
        rel = (r.get("reliability") or "").strip()
        return cls(
            outlet_id=r["outlet_id"].strip(), name=r["name"].strip(),
            domains=[d.lower() for d in split(r["domains"])], x_handles=split(r["x_handles"]),
            kind=r["kind"].strip(), country=r["country"].strip(),
            us_lean=r["us_lean"].strip(), us_lean_opinion=r["us_lean_opinion"].strip(),
            opinion_paths=[p.lower() for p in split(r["opinion_paths"])],
            allsides_name=r["allsides_name"].strip(), allsides_date=r["allsides_date"].strip(),
            allsides_confidence=r["allsides_confidence"].strip(),
            reliability=float(rel) if rel else None,
            reliability_domain=r["reliability_domain"].strip(),
            state_media=r["state_media"].strip(), state_media_entity=r["state_media_entity"].strip(),
            state_media_year=r["state_media_year"].strip(), wikidata=r["wikidata"].strip(),
            notes=r["notes"].strip(), raw=dict(r))

    @property
    def is_platform(self) -> bool:
        return self.kind == "platform"


def clean_host(host: str) -> str:
    host = (host or "").lower().strip(".")
    changed = True
    while changed:
        changed = False
        for p in STRIP_PREFIXES:
            if host.startswith(p) and host.count(".") >= 2:
                host, changed = host[len(p):], True
    return host


def host_candidates(host: str) -> list[str]:
    """edition.cnn.com -> [edition.cnn.com, cnn.com]. Never below two labels, and never
    drops labels from the right, so reuters.com.evil.net can't reach reuters.com."""
    parts = host.split(".")
    return [".".join(parts[i:]) for i in range(0, max(1, len(parts) - 1))]


def path_folders(path: str) -> list[str]:
    """Folders of a URL path, without the last part (the headline slug or file name)."""
    segs = [s for s in path.split("/") if s]
    return [s.lower() for s in segs[:-1]]


def url_key(url: str) -> str:
    """The URL without query string or fragment, for merging duplicates."""
    p = urlsplit(url.strip())
    host = clean_host(p.hostname or "")
    path = p.path.rstrip("/") or "/"
    return f"{host}{path}"


class OutletTable:
    def __init__(self, outlets: list[Outlet]):
        self.outlets = outlets
        self.by_id = {o.outlet_id: o for o in outlets}
        self.by_host: dict[str, Outlet] = {}
        self.by_host_path: dict[str, list[tuple[list[str], Outlet]]] = {}
        self.by_x: dict[str, Outlet] = {}
        for o in outlets:
            for d in o.domains:
                if "/" in d:
                    host, _, pref = d.partition("/")
                    self.by_host_path.setdefault(host, []).append(
                        ([s for s in pref.split("/") if s], o))
                else:
                    self.by_host[d] = o
            for h in o.x_handles:
                self.by_x[h.lower()] = o
        for host in self.by_host_path:   # longest path prefix first
            self.by_host_path[host].sort(key=lambda t: -len(t[0]))

    @classmethod
    def load(cls, path: Path | str = paths.OUTLETS_CSV) -> "OutletTable":
        with open(path, newline="", encoding="utf-8") as f:
            return cls([Outlet.from_row(r) for r in csv.DictReader(f)])

    # -- lookup ---------------------------------------------------------------
    def match_domain(self, url: str) -> tuple[Outlet | None, str]:
        p = urlsplit(url.strip())
        host = clean_host(p.hostname or "")
        segs = [s.lower() for s in p.path.split("/") if s]
        for cand in host_candidates(host):
            for pref, o in self.by_host_path.get(cand, []):
                if segs[:len(pref)] == [s.lower() for s in pref]:
                    return o, cand + "/" + "/".join(pref)
            if cand in self.by_host:
                return self.by_host[cand], cand
        return None, ""

    def is_opinion(self, o: Outlet | None, url: str) -> bool:
        folders = path_folders(urlsplit(url).path)
        extra = set(o.opinion_paths) if o else set()
        if "*" in extra:   # every page is opinion except the listed !folders (National Review)
            negated = {e[1:] for e in extra if e.startswith("!")}
            return not any(f in negated for f in folders)
        marks = OPINION_FOLDERS | {e for e in extra if not e.startswith("!")}
        return any(f in marks for f in folders)

    def label(self, url: str) -> dict:
        """Everything module 3 says about one link. Keys are stable; values None when unknown."""
        p = urlsplit(url.strip())
        host = clean_host(p.hostname or "")
        out = dict(url=url, outlet_id=None, outlet_name=None, matched_by="none", matched_key=None,
                   kind=None, rated=False, is_wire=False, country=None, section="news",
                   us_lean=None, us_lean_basis=None, allsides_name=None,
                   allsides_confidence=None, reliability=None, reliability_low=False,
                   state_media=None, state_media_group=None, x_account=None)
        if host in X_HOSTS:
            segs = [s for s in p.path.split("/") if s]
            handle = segs[0] if segs else ""
            if handle and handle.lower() not in {"i", "home", "search", "hashtag", "intent"}:
                out["x_account"] = handle
                o = self.by_x.get(handle.lower())
                if o is None:
                    out.update(matched_by="x_account", kind="x_account")
                    return out
                return self._fill(out, o, "x_account", "@" + handle, url, x_post=True)
        o, key = self.match_domain(url)
        if o is None:
            return out
        return self._fill(out, o, "domain", key, url)

    def _fill(self, out, o: Outlet, how, key, url, x_post=False) -> dict:
        out.update(outlet_id=o.outlet_id, outlet_name=o.name, matched_by=how, matched_key=key,
                   kind=o.kind, country=o.country or None)
        if o.is_platform:
            return out   # platforms are never rated
        opinion = (not x_post) and self.is_opinion(o, url)
        out["section"] = "opinion" if opinion else "news"
        if opinion and o.us_lean_opinion:
            lean, basis = o.us_lean_opinion, "opinion rating"
        elif o.us_lean:
            lean, basis = o.us_lean, ("news rating (no separate opinion rating)" if opinion
                                      else "news rating")
        else:
            lean, basis = None, None
        out.update(rated=True, is_wire=o.kind == "wire", us_lean=lean, us_lean_basis=basis,
                   allsides_name=o.allsides_name or None,
                   allsides_confidence=o.allsides_confidence or None,
                   reliability=o.reliability,
                   reliability_low=o.reliability is not None and o.reliability < LOW_RELIABILITY,
                   state_media=o.state_media or None,
                   state_media_group=STATE_LEVELS.get(o.state_media))
        return out

    # -- lists for Gather -----------------------------------------------------
    def hosts(self, outlet_ids=None, kinds=("news", "wire")) -> list[str]:
        """Plain hosts (path scopes dropped) for include_domains, in file order, deduped."""
        seen, out = set(), []
        for o in self.outlets:
            if outlet_ids is not None and o.outlet_id not in outlet_ids:
                continue
            if kinds and o.kind not in kinds:
                continue
            for d in o.domains:
                h = d.split("/")[0]
                if h not in seen:
                    seen.add(h)
                    out.append(h)
        return out

    def core_domains(self) -> list[str]:
        return self.hosts()


_TABLE: OutletTable | None = None


def table() -> OutletTable:
    global _TABLE
    if _TABLE is None:
        _TABLE = OutletTable.load()
    return _TABLE


def label(url: str) -> dict:
    return table().label(url)
