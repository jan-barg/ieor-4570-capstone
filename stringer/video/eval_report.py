"""The visual report for module 8's evals (scripts/eval_video.py): one self-contained HTML page, in the same
look as the other steps' reports (stringer/evals/report.py), rebuilt after every run.

    -> stringer_private/evals/video_report.html   (private: it names real stories)

Sections: the scoreboard (every eval against its bar), quality against cost (one dot per video), speed,
broken scripts (what should happen against what did), layout problems by kind, one row per story, and
every problem in plain words. Charts are inline SVG and HTML tables."""
from __future__ import annotations

import datetime as dt
from collections import Counter
from pathlib import Path

from ..evals.report import CSS, JS, esc, nice_step, ticks
from . import evals

EXTRA_CSS = """
.board{background:var(--surface);border:1px solid var(--line);border-radius:8px}
.board td.res{min-width:220px}.board td.num{font-family:var(--mono);font-size:12px;white-space:nowrap}
.pass{background:var(--best-bg);color:var(--best-fg)}.fail{background:var(--warn-bg);color:var(--warn-fg)}
.wait{background:var(--grid);color:var(--muted)}
.bars .lbl{fill:var(--fg);font-size:12px}.bars .val{fill:var(--muted);font-size:11px;font-family:var(--mono)}
.bar-ok{fill:var(--ok)}.bar-miss{fill:var(--miss)}.bar-code{fill:var(--code)}
.rule{stroke:var(--miss);stroke-width:1.5;stroke-dasharray:4 3}
table.stories{background:var(--surface);border:1px solid var(--line);border-radius:8px}
table.stories td.bad{color:var(--warn-fg);font-weight:600}
ul.probs{margin:0;padding-left:18px;font-size:13px;display:flex;flex-direction:column;gap:3px}
ul.probs li span{color:var(--muted)}
"""


def chip(state: str) -> str:
    word = {"pass": "passes", "fail": "misses the bar", "wait": "waiting"}[state]
    return f'<span class="chip {state}">{word}</span>'


def ok_stories(run: dict) -> list[dict]:
    return [s for s in run["stories"] if s.get("status") == "rendered"]


LAYOUT_ACCEPTED = 1      # the flags Jan accepted on Nov 26; more than this is a miss again


def layout_problems(run: dict) -> list[dict]:
    out = []
    for st in run.get("layout") or []:
        for fr in st.get("frames") or []:
            for p in fr.get("problems") or []:
                out.append(dict(p, story=st["id8"], beat=fr.get("beat"), shot=fr.get("shot")))
    return out


def layout_by_story(run: dict) -> dict[str, int]:
    c = Counter(p["story"] for p in layout_problems(run))
    return {st["id8"]: c.get(st["id8"], 0) for st in run.get("layout") or []}


# ---- the scoreboard ------------------------------------------------------------------------------------

def scoreboard(run: dict) -> tuple[str, list[str]]:
    st = ok_stories(run)
    n = len(st) or 1
    b = run["bars"]
    rows, misses = [], []

    def row(num, name, bar, result, state):
        if state == "fail":
            misses.append(name)
        rows.append(f'<tr><td class="num">{num}</td><td>{esc(name)}</td><td class="muted">{esc(bar)}</td>'
                    f'<td class="res">{result} {chip(state)}</td></tr>')

    p95 = evals.p95([s["speed"]["total_s"] for s in st])
    row(1, "Speed", f"script to file p95 ≤ {b['speed_p95_s']} s", f"p95 {p95:.0f} s on the Mac; Cloud Run not deployed yet",
        "pass" if p95 <= b["speed_p95_s"] else "fail")
    stopped = [s for s in run["stories"] if s.get("status") == "stopped"]
    missing = [s for s in run["stories"] if s.get("status") not in ("rendered", "stopped")]
    br = run["broken"]["results"]
    crashes = sum(1 for r in br if r["actual"] == "crash")
    handled = sum(1 for r in br if r["actual"] == r["expected"])
    drawn = run["broken"]["drawn"]
    drawn_ok = sum(1 for d in drawn if d["ok"])
    row(2, "Reliability", "≥ 98% finish, no crashes",
        f"{len(st)} of {len(run['stories'])} real scripts made, {len(stopped)} stopped cleanly"
        f"{f', {len(missing)} missing' if missing else ''}; {len(br)} broken scripts: {crashes} crashes, "
        f"{handled} handled as expected; {drawn_ok} of {len(drawn)} drawn without an error",
        "pass" if not crashes and not missing and drawn_ok == len(drawn) else "fail")
    bad = sum(1 for s in st if s["on_screen"])
    row(3, "On-screen facts", "100%", f"{n - bad} of {n} videos clean", "pass" if not bad else "fail")
    bad = sum(1 for s in st if s["required"])
    row(4, "Required parts", "100%", f"{n - bad} of {n} videos have every part", "pass" if not bad else "fail")
    worst = [max(s["sync"][k] for s in st) if st else 0 for k in ("shot_ms", "mark_ms", "caption_ms")]
    sb = b["sync_ms"]
    row(5, "Sync", f"≤ {sb[0]} / {sb[1]} / {sb[2]} ms", f"worst {worst[0]:.0f} / {worst[1]:.0f} / {worst[2]:.0f} ms",
        "pass" if all(w <= x for w, x in zip(worst, sb)) else "fail")
    bad = sum(1 for s in st if s["format"]["problems"])
    lo, hi = b["length_s"]
    row(6, "Format and sound", f"{lo:.0f}–{hi:.0f} s, −14 LUFS ± 1, no flashing", f"{n - bad} of {n} videos clean",
        "pass" if not bad else "fail")
    lp = layout_problems(run)
    frames = sum(len(x.get("frames") or []) for x in run.get("layout") or [])
    if run.get("layout"):
        # Jan, Nov 26, on the one flag left (a timeline date caught in its fade-in): "im happy with what we did"
        accepted = len(lp) <= LAYOUT_ACCEPTED
        row(7, "Layout", "0 problems", f"{len(lp)} problem{'' if len(lp) == 1 else 's'} on {frames} stills"
            + ("; Jan accepted this (Nov 26)" if lp and accepted else ""), "pass" if accepted else "fail")
    else:
        row(7, "Layout", "0 problems", "not run this time", "wait")
    bad = sum(1 for s in st if s["maps"]["problems"])
    mp = sum(s["maps"]["maps"] for s in st)
    row(8, "Maps", "100%", f"{mp} maps in {n} videos; {n - bad} videos clean", "pass" if not bad else "fail")
    row(9, "Frame judge", "Jan's 40 ratings first", "later", "wait")
    row(10, "Voice", "Jan picks", "Jan picked v4 Turbo with the voice director's expressive tags, from 2 stories read 4 ways (Nov 26)", "pass")
    beats = sum(s["shot_choice"]["beats"] for s in st) or 1
    swaps = sum(s["shot_choice"]["swaps"] for s in st)
    triples = sum(len(s["shot_choice"]["triples"]) for s in st)
    row(11, "Shot choice", f"≤ {b['swap_rate_max']:.0%} swaps, no shot 3 times running",
        f"{swaps} swaps in {beats} beats ({swaps / beats:.0%}); {triples} runs of three",
        "pass" if swaps / beats <= b["swap_rate_max"] and not triples else "fail")
    row(12, "Jan's watch", "Jan's call", "he liked the first five (\"the general baseline is great\") and approved all 97 portrait photos; six more on the review page, with portraits", "wait")
    worst_cost = max((s["cost"]["total_usd"] for s in st), default=0)
    row(13, "Cost", f"≤ ${b['cost_max_usd']:.2f} a video", f"at most ${worst_cost:.3f} a video at list prices",
        "pass" if worst_cost <= b["cost_max_usd"] else "fail")
    head = '<thead><tr><th>#</th><th>Eval</th><th>Bar</th><th>Result</th></tr></thead>'
    return f'<div class="scroll"><table class="board">{head}<tbody>{"".join(rows)}</tbody></table></div>', misses


# ---- charts --------------------------------------------------------------------------------------------

def quality_cost(run: dict) -> str:
    """One dot per video: checks passed (of 7) against cost at list prices."""
    st = ok_stories(run)
    lay = layout_by_story(run)
    pts = []
    for s in st:
        checks = [not s["on_screen"], not s["required"], not s["sync"]["problems"], not s["format"]["problems"],
                  not s["maps"]["problems"], not s["shot_choice"]["triples"] and s["shot_choice"]["swaps"] == 0,
                  lay.get(s["id8"], 0) == 0]
        pts.append((s["cost"]["total_usd"], sum(checks), s))
    if not pts:
        return '<p class="empty">No videos yet.</p>'
    W, H, L_, R, T, B = 720, 300, 56, 20, 16, 44
    xmax = max(p[0] for p in pts) * 1.15 or 0.1
    step = nice_step(xmax, 5)
    xt = ticks(0, xmax, step)
    xmax = xt[-1] if xt else xmax
    X = lambda v: L_ + (W - L_ - R) * v / xmax                       # noqa: E731
    Y = lambda v: T + (H - T - B) * (1 - v / 7)                      # noqa: E731
    g = []
    for v in range(0, 8):
        g.append(f'<line class="grid" x1="{L_}" x2="{W - R}" y1="{Y(v):.1f}" y2="{Y(v):.1f}"/>'
                 f'<text class="tick" x="{L_ - 8}" y="{Y(v) + 4:.1f}" text-anchor="end">{v}</text>')
    for v in xt:
        g.append(f'<text class="tick" x="{X(v):.1f}" y="{H - B + 18}" text-anchor="middle">${v:.2f}</text>')
    g.append(f'<line class="axis" x1="{L_}" x2="{W - R}" y1="{H - B}" y2="{H - B}"/>')
    bar = run["bars"]["cost_max_usd"]
    if bar <= xmax:
        g.append(f'<line class="rule" x1="{X(bar):.1f}" x2="{X(bar):.1f}" y1="{T}" y2="{H - B}"/>')
    # dots at the same spot are spread a little so each stays hoverable
    seen = Counter()
    for c, k, s in pts:
        key = (round(c, 3), k)
        dx = (seen[key] % 5 - 2) * 7
        seen[key] += 1
        tip = (f"{s['title']}\n{k} of 7 checks pass\n${c:.3f} a video (voice ${s['cost']['voice_usd']:.3f}, "
               f"render ${s['cost']['render_usd']:.3f})")
        g.append(f'<circle class="dot" cx="{X(c) + dx:.1f}" cy="{Y(k):.1f}" r="5"/>'
                 f'<circle class="hit" cx="{X(c) + dx:.1f}" cy="{Y(k):.1f}" r="11" tabindex="0" data-tip="{esc(tip)}"/>')
    g.append(f'<text class="axis-title" x="{(L_ + W - R) / 2}" y="{H - 6}" text-anchor="middle">cost a video at list prices</text>'
             f'<text class="axis-title" x="14" y="{(T + H - B) / 2}" text-anchor="middle" '
             f'transform="rotate(-90 14 {(T + H - B) / 2})">checks passed (of 7)</text>')
    return f'<div class="scroll"><svg viewBox="0 0 {W} {H}" role="img" aria-label="Checks passed against cost, one dot per video">{"".join(g)}</svg></div>'


def hbars(items: list[tuple[str, float, str]], unit: str, rule: float | None = None, rule_label: str = "") -> str:
    """Horizontal bars, one per item (label, value, tooltip), biggest first."""
    if not items:
        return '<p class="empty">Nothing to show.</p>'
    items = sorted(items, key=lambda x: -x[1])
    W, row, L_, R, T = 720, 22, 230, 70, 6
    H = T + row * len(items) + 24
    vmax = max([v for _, v, _ in items] + ([rule] if rule else [])) * 1.08 or 1
    X = lambda v: L_ + (W - L_ - R) * v / vmax                       # noqa: E731
    g = []
    for i, (lab, v, tip) in enumerate(items):
        y = T + i * row
        w = max(2, X(v) - L_)
        g.append(f'<text class="lbl" x="{L_ - 8}" y="{y + 14}" text-anchor="end">{esc(lab[:34])}</text>'
                 f'<rect class="bar-ok" x="{L_}" y="{y + 5}" width="{w:.1f}" height="12" rx="2"/>'
                 f'<text class="val" x="{L_ + w + 6:.1f}" y="{y + 15}">{v:g}{unit}</text>'
                 f'<rect class="hit" x="0" y="{y}" width="{W}" height="{row}" tabindex="0" data-tip="{esc(tip)}"/>')
    if rule:
        g.append(f'<line class="rule" x1="{X(rule):.1f}" x2="{X(rule):.1f}" y1="{T}" y2="{H - 20}"/>'
                 f'<text class="val" x="{X(rule):.1f}" y="{H - 6}" text-anchor="middle">{esc(rule_label)}</text>')
    return f'<div class="scroll"><svg class="bars" viewBox="0 0 {W} {H}" role="img">{"".join(g)}</svg></div>'


def broken_grid(run: dict) -> str:
    m = run["broken"]["confusion"]
    outs = evals.OUTCOMES
    words = {"ok": "drawn as is", "skip": "picture left out", "swap": "headline card", "stop": "no video", "crash": "crash"}
    head = "".join(f"<th>{esc(words[o])}</th>" for o in outs)
    body = []
    for e in m:
        tot = sum(m[e].values()) or 1
        cells = []
        for a in outs:
            v = m[e][a]
            cls = "hit" if a == e else "miss"
            p = int(100 * v / tot) if v else 0
            strong = " strong" if p >= 55 else ""
            cells.append(f'<td class="{cls}{strong}" style="--p:{p}%" data-tip="{esc(f"{v} scripts expected {words[e]}, got {words[a]}")}">{v or ""}</td>')
        body.append(f'<tr><th>{esc(words[e])}</th>{"".join(cells)}</tr>')
    return (f'<figure class="conf"><figcaption>Broken scripts: what should happen (rows) against what did (columns)</figcaption>'
            f'<table><thead><tr><th class="corner">should ↓ / did →</th>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></figure>')


def broken_kinds(run: dict) -> str:
    by = {}
    for r in run["broken"]["results"]:
        by.setdefault(r["kind"], []).append(r)
    rows = []
    for kind, rs in by.items():
        exp = rs[0]["expected"]
        got = Counter(r["actual"] for r in rs)
        right = got.get(exp, 0)
        cls = "" if right == len(rs) else ' class="bad"'
        odd = [r for r in rs if r["actual"] != exp]
        why = esc("; ".join(f"{r['story']}: {r['actual']} ({r['detail'][:90]})" for r in odd[:3]))
        rows.append(f'<tr><td>{esc(kind)}</td><td>{esc(exp)}</td><td class="n">{len(rs)}</td><td{cls}>{right} of {len(rs)}</td>'
                    f'<td class="muted">{why}</td></tr>')
    return ('<div class="scroll"><table class="stories"><thead><tr><th>Breakage</th><th>Should</th><th>Scripts</th>'
            f'<th>As expected</th><th>Otherwise</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>')


def story_table(run: dict) -> str:
    lay = layout_by_story(run)
    rows = []
    for s in run["stories"]:
        if s.get("status") != "rendered":
            rows.append(f'<tr><td><span class="sid">{esc(s["id8"])}</span> {esc(s["title"])}</td>'
                        f'<td colspan="9" class="muted">{esc(s["status"])}: {esc(s.get("why"))}</td></tr>')
            continue
        f, sy, c = s["format"], s["sync"], s["cost"]
        def cell(v, bad):                                              # noqa: E306
            return f'<td class="n{" bad" if bad else ""}">{v}</td>'
        rows.append(f'<tr><td><span class="sid">{esc(s["id8"])}</span> {esc(s["title"])}</td>'
                    + cell(f'{f.get("seconds") or 0:.1f} s', bool(f["problems"]))
                    + cell(f'{s["speed"]["total_s"] or 0:.0f} s', False)
                    + cell(f'${c["total_usd"]:.3f}', False)
                    + cell(len(s["on_screen"]), bool(s["on_screen"]))
                    + cell(len(s["required"]), bool(s["required"]))
                    + cell(f'{max(sy["shot_ms"], sy["mark_ms"], sy["caption_ms"]):.0f} ms', bool(sy["problems"]))
                    + cell(f'{s["maps"]["maps"]} / {len(s["maps"]["problems"])}', bool(s["maps"]["problems"]))
                    + cell(s["shot_choice"]["swaps"], bool(s["shot_choice"]["swaps"]))
                    + cell(lay.get(s["id8"], "–"), bool(lay.get(s["id8"]))) + '</tr>')
    head = ('<tr><th>Story</th><th>Length</th><th>Made in</th><th>Cost</th><th>On-screen</th><th>Required</th>'
            '<th>Worst sync</th><th>Maps / problems</th><th>Swaps</th><th>Layout</th></tr>')
    return f'<div class="scroll"><table class="stories"><thead>{head}</thead><tbody>{"".join(rows)}</tbody></table></div>'


def problem_list(run: dict) -> str:
    items = []
    for s in ok_stories(run):
        for key, name in (("on_screen", "on-screen"), ("required", "required")):
            items += [(name, s["id8"], p) for p in s[key]]
        items += [("sync", s["id8"], p) for p in s["sync"]["problems"]]
        items += [("format", s["id8"], p) for p in s["format"]["problems"]]
        items += [("maps", s["id8"], p) for p in s["maps"]["problems"]]
        items += [("shot choice", s["id8"], f"beat {x['beat']} ({x['shot']}) became a headline card: {x['why']}")
                  for x in s["shot_choice"]["swapped"]]
        items += [("shot choice", s["id8"], f"the same shot three times from beat {i}") for i in s["shot_choice"]["triples"]]
    for d in run["broken"]["drawn"]:
        items += [("broken, drawn", d["story"], f"{d['kind']}: {e}") for e in d["errors"]]
    for r in run["broken"]["results"]:
        if r["actual"] == "crash":
            items.append(("broken", r["story"], f"{r['kind']} crashed: {r['detail']}"))
    if not items:
        return '<p class="muted">None.</p>'
    li = "".join(f'<li><b>{esc(k)}</b> <span class="sid">{esc(sid)}</span> {esc(p)}</li>' for k, sid, p in items)
    return f'<ul class="probs">{li}</ul>'


def layout_detail(run: dict) -> str:
    lp = layout_problems(run)
    if not run.get("layout"):
        return '<p class="muted">Not run this time.</p>'
    kinds = Counter(p["kind"] for p in lp)
    words = {"small": "text under 24 px", "low contrast": "contrast under 4.5:1 (3:1 for large text)",
             "outside safe area": "outside the safe area", "overlap": "two texts overlapping", "cut off": "cut off at the frame's edge",
             "face over text": "a portrait's face over words", "face under captions": "a portrait's face under the captions",
             "portrait left out": "a person left out (no room for their portrait)",
             "face outside safe area": "a portrait's face under TikTok's bar or buttons"}
    bars = hbars([(words.get(k, k), v, f"{v} texts: {words.get(k, k)}") for k, v in kinds.items()], "")
    texts = Counter((p["kind"], p["text"].split(" at ")[0]) for p in lp)
    top = "".join(f'<tr><td>{esc(words.get(k, k))}</td><td>{esc(t)}</td><td class="n">{v}</td></tr>'
                  for (k, t), v in texts.most_common(14))
    return (bars + '<p class="what">The texts behind most of them (the same text on many stills):</p>'
            f'<div class="scroll"><table class="stories"><thead><tr><th>Problem</th><th>Text</th><th>Stills</th></tr></thead>'
            f'<tbody>{top}</tbody></table></div>')


# ---- the page ------------------------------------------------------------------------------------------

def build(run: dict) -> str:
    st = ok_stories(run)
    board, misses = scoreboard(run)
    when = dt.datetime.strptime(run["run"], "%Y%m%dT%H%M%SZ").strftime("%Y-%m-%d %H:%M UTC")
    lede = (f"{len(st)} videos checked. " + (f"Misses the bar on: {', '.join(misses)}." if misses else "Every eval that can run now passes."))
    speed = hbars([(s["title"], round(s["speed"]["total_s"] or 0, 1),
                    f"{s['title']}\nvoice {s['speed']['voice_s']} s{' (saved recording)' if s['speed']['voice_reused'] else ''}\n"
                    f"render {s['speed']['render_s']} s\nfiles {s['speed']['files_s']} s") for s in st],
                  " s", rule=run["bars"]["speed_p95_s"], rule_label="bar")
    body = [
        '<header><h1>Making the video: evals</h1>'
        '<p class="intro">Module 8 turns a script into a finished video with code and one voice service. These checks '
        'read what it made for every frozen story: the render plan, the render record and the video file. A second set '
        'feeds it scripts broken on purpose, to see that it never crashes and handles each breakage the right way. No '
        'model judges anything here.</p>'
        f'<p class="meta">run {esc(run["run"])} · {when} · {run["seconds"]:.0f} s</p></header>',
        f'<section class="split"><div class="block"><h2>Scoreboard</h2><p class="lede">{esc(lede)}</p>{board}</div></section>',
        '<section class="split"><div class="block"><h3>Quality against cost</h3><p class="what">One dot per video. Up '
        'is more of the 7 code checks passed (on-screen facts, required parts, sync, format, maps, no swaps, layout); '
        'left is cheaper. Cost is the voice at ElevenLabs\' list price plus the render on Cloud Run, estimated from the '
        'Stage B timings. The dashed line is the $0.25 bar. Hover a dot for its story.</p>' + quality_cost(run) + '</div>'
        '<div class="block"><h3>Speed on the Mac</h3><p class="what">Script to finished file, per video. A saved '
        'recording skips the voice call. Hover for the steps.</p>' + speed + '</div></section>',
        '<section class="split"><div class="block"><h2>Broken scripts</h2><p class="what">Copies of the real scripts, '
        'each broken in one way. The row is what module 8 should do with that breakage; the column is what it did. '
        'Everything on the diagonal is right.</p>' + broken_grid(run) + broken_kinds(run) + '</div></section>',
        '<section class="split"><div class="block"><h2>Layout</h2><p class="what">One still per beat, drawn with every '
        'text box logged: inside the safe area (clear of TikTok\'s buttons and caption), not cut off, at least 24 px, '
        'contrast against what is behind it, and no two texts on top of each other.</p>' + layout_detail(run) + '</div></section>',
        '<section class="split"><div class="block"><h2>Every video</h2><p class="what">Counts are problems found; a '
        'highlighted cell missed its bar.</p>' + story_table(run) + '</div>'
        '<div class="block"><h3>Every problem, in words</h3>' + problem_list(run) + '</div></section>',
    ]
    return ("<title>Video Evals</title>\n"
            '<meta name="claude:viewport-fit-sides" content="cover">\n'
            '<link rel="preconnect" href="https://fonts.googleapis.com">'
            '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
            '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600&'
            'family=Geist+Mono:wght@400;500&display=swap">\n'
            f"<style>{CSS}{EXTRA_CSS}</style>\n"
            f'<div class="page">{"".join(body)}</div><div id="tip" role="tooltip" hidden></div>\n'
            f"<script>{JS}</script>\n")


def write(run: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build(run), encoding="utf-8")
    return path
