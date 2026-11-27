"""The visual report for a step's evals: one self-contained HTML page per step, rebuilt after every
run and every re-score, so each eval comes with a picture of how it went.

    python -m scripts.run_eval report same_story
    -> stringer_private/evals/<step>_report.html   (private: it shows headlines and model reasons)

Runs are only compared on the same stories, so the page has one section per split (tune, holdout,
all). Each section shows:
  quality vs cost      one dot per run: the step's main score against its cost per story
  scores               every headline score as a small bar, plus cost, time and calls
  where mistakes fall  per run, the answer key's label against what the model said
  hard stories         every run's score on every story, hardest stories first
  mistakes             per run, each item it got wrong, with the model's own reason
The last three appear when the step provides them: summary["confusion"] as {"gold->pred": n},
summary["stories"] as {story: score}, and Step.mistakes(). A re-scored run replaces the run it was
re-scored from. Charts are inline SVG and HTML tables; the page loads nothing from the network
except its fonts."""
from __future__ import annotations

import datetime as dt
import html
import json
import math
from pathlib import Path

from .. import paths
from .runner import CODE_PREFIX, Step, _runs_dir, index_rows

SPLITS = {"tune": ("Tune stories", "the stories prompt changes are tried on"),
          "holdout": ("Holdout stories", "kept out of prompt changes, for the final check"),
          "all": ("All stories", "tune and holdout together")}


def report_path(step: Step, out_dir=None) -> Path:
    return Path(out_dir or paths.EVALS) / f"{step.name}_report.html"


def esc(x) -> str:
    return html.escape("" if x is None else str(x), quote=True)


def is_code(r: dict) -> bool:
    return r["model"].startswith(CODE_PREFIX)


def run_name(r: dict) -> str:
    m = r["model"]
    m = f"{m[len(CODE_PREFIX):]} (code)" if m.startswith(CODE_PREFIX) else m
    return f"{m} · {r['version']}"


def usd(v) -> str:
    v = float(v or 0)
    if v == 0:
        return "$0"
    return f"${v:.4f}" if v < 0.01 else (f"${v:.3f}" if v < 1 else f"${v:.2f}")


def plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def secs(v) -> str:
    v = float(v or 0)
    return f"{v:.0f} s" if v < 90 else f"{v / 60:.1f} min"


def num(v, digits=3) -> str:
    if v is None:
        return "–"
    return f"{v:.{digits}f}" if isinstance(v, float) else str(v)


def metric_info(step: Step, key: str) -> tuple[str, str]:
    name, note = (getattr(step, "metric_notes", {}) or {}).get(key, (key.replace("_", " "), ""))
    return name, note


def runs_to_show(rows: list[dict]) -> list[dict]:
    """The latest version of every run: a re-score replaces the run it came from."""
    by_id = {r["run_id"]: r for r in rows}

    def root(r):
        k, seen = r["run_id"], set()
        while k in by_id and by_id[k].get("rescored_from") and k not in seen:
            seen.add(k)
            k = by_id[k]["rescored_from"]
        return k

    latest = {}
    for r in rows:
        k = root(r)
        if k not in latest or r["finished_at"] >= latest[k]["finished_at"]:
            latest[k] = r
    start = {k: (by_id[k] if k in by_id else v)["started_at"] for k, v in latest.items()}
    return [latest[k] for k in sorted(latest, key=lambda k: start[k])]


# ---- scales -------------------------------------------------------------------------------------

def nice_step(span: float, n: int = 5) -> float:
    raw = span / max(n, 1) or 1e-6
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * mag:
            return m * mag
    return 10 * mag


def ticks(lo: float, hi: float, step: float) -> list[float]:
    out, t = [], math.ceil(lo / step - 1e-9) * step
    while t <= hi + 1e-9:
        out.append(round(t, 10))
        t += step
    return out


# ---- the pieces ---------------------------------------------------------------------------------

def scatter(step: Step, runs: list[dict]) -> str:
    main = step.headline[0]
    pts = [(r, r["summary"].get(main)) for r in runs]
    pts = [(r, float(y)) for r, y in pts if isinstance(y, (int, float))]
    if not pts:
        return '<p class="empty">No scored runs here yet.</p>'
    W, H, L, R, T, B = 720, 360, 60, 28, 18, 50
    pw, ph = W - L - R, H - T - B
    xs = [float(r.get("cost_per_story_usd") or 0) for r, _ in pts]
    xstep = nice_step(max(xs) * 1.15 if max(xs) > 0 else 0.001)
    xhi = max(xstep, math.ceil(max(xs) * 1.15 / xstep) * xstep)
    ys = [y for _, y in pts]
    if max(ys) <= 1:
        ylo = max(0.0, math.floor((min(ys) - 0.05) * 10) / 10)
        yhi = min(1.0, math.ceil((max(ys) + 0.05) * 10) / 10)
    else:
        ylo, yhi = 0.0, max(ys) * 1.1
    ystep = nice_step(yhi - ylo)
    X = lambda v: L + pw * (v / xhi)
    Y = lambda v: T + ph * (1 - (v - ylo) / ((yhi - ylo) or 1))
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{esc(metric_info(step, main)[0])} against cost per story, one dot per run">']
    for t in ticks(ylo, yhi, ystep):
        out.append(f'<line class="grid" x1="{L}" x2="{W - R}" y1="{Y(t):.1f}" y2="{Y(t):.1f}"/>'
                   f'<text class="tick" x="{L - 8}" y="{Y(t) + 4:.1f}" text-anchor="end">{t:.2f}</text>')
    for t in ticks(0, xhi, xstep):
        out.append(f'<line class="grid" y1="{T}" y2="{T + ph}" x1="{X(t):.1f}" x2="{X(t):.1f}"/>'
                   f'<text class="tick" y="{T + ph + 18}" x="{X(t):.1f}" text-anchor="middle">{esc(usd(t))}</text>')
    out.append(f'<line class="axis" x1="{L}" x2="{W - R}" y1="{T + ph}" y2="{T + ph}"/>')
    out.append(f'<text class="axis-title" x="{L + pw / 2}" y="{H - 8}" text-anchor="middle">'
               f'Cost per story (list price)  →  cheaper is to the left</text>')
    out.append(f'<text class="axis-title" transform="translate(14 {T + ph / 2}) rotate(-90)" text-anchor="middle">'
               f'{esc(metric_info(step, main)[0])}  →  better is higher</text>')
    # labels: right of the dot, or left of it near the right edge; nudged apart vertically
    labels = []
    for (r, y), x in zip(pts, xs):
        px, py = X(x), Y(y)
        side = "end" if px > L + 0.68 * pw else "start"
        labels.append(dict(r=r, px=px, py=py, ly=py + 4, side=side))
    for side in ("start", "end"):
        group = sorted((l for l in labels if l["side"] == side), key=lambda l: l["ly"])
        for a, b in zip(group, group[1:]):
            if b["ly"] - a["ly"] < 15:
                b["ly"] = a["ly"] + 15
    for l in labels:
        r = l["r"]
        tip = (f"{run_name(r)}{' — ' + r['label'] if r.get('label') else ''}\n"
               f"{metric_info(step, main)[0]}: {num(r['summary'].get(main))}\n"
               f"Cost per story: {usd(r.get('cost_per_story_usd'))} · whole run {usd(r.get('cost_usd'))}\n"
               f"Time: {secs(r.get('wall_s'))} · {r.get('stories')} stories · {r.get('status')}")
        cls = "dot code" if is_code(r) else "dot"
        dx = -11 if l["side"] == "end" else 11
        out.append(f'<text class="dot-label" x="{l["px"] + dx:.1f}" y="{l["ly"]:.1f}" text-anchor="{l["side"]}">'
                   f'{esc(run_name(r))}</text>')
        out.append(f'<circle class="hit" cx="{l["px"]:.1f}" cy="{l["py"]:.1f}" r="14" tabindex="0" data-tip="{esc(tip)}"/>'
                   f'<circle class="{cls}" cx="{l["px"]:.1f}" cy="{l["py"]:.1f}" r="6"/>')
    out.append("</svg>")
    legend = ('<div class="legend"><span><i class="key model"></i>model run</span>'
              '<span><i class="key code"></i>plain-code baseline (no model, free)</span></div>')
    return legend + '<div class="scroll">' + "".join(out) + "</div>"


def scores_table(step: Step, runs: list[dict]) -> str:
    main = step.headline[0]
    order = sorted(runs, key=lambda r: (r["summary"].get(main) is None, -(r["summary"].get(main) or 0)))
    fracs = {k for k in step.headline
             if all(isinstance(r["summary"].get(k), float) or r["summary"].get(k) is None for r in runs)
             and any(isinstance(r["summary"].get(k), float) for r in runs)}
    best = {k: max((r["summary"][k] for r in runs if isinstance(r["summary"].get(k), float)), default=None)
            for k in fracs}
    head = ["Run"] + [metric_info(step, k)[0] for k in step.headline] + ["Cost per story", "Whole run", "Time", "Calls"]
    tips = [""] + [metric_info(step, k)[1] for k in step.headline] + [
        "What the model calls cost per story, at list price (cached calls counted too, so runs compare fairly)",
        "Whole run at list price; new money actually spent is in the tooltip on the dot",
        "Wall-clock time for the run", "Model calls (from cache)"]
    out = ['<div class="scroll"><table class="scores"><thead><tr>']
    for h, t in zip(head, tips):
        out.append(f'<th{" data-tip=" + chr(34) + esc(t) + chr(34) if t else ""}>{esc(h)}</th>')
    out.append("</tr></thead><tbody>")
    for i, r in enumerate(order):
        s = r["summary"]
        chips = "".join(f'<span class="chip {c}">{esc(t)}</span>' for c, t in (
            ("best", "best") if i == 0 and s.get(main) is not None and not is_code(r) else ("", ""),
            ("warn", r["status"]) if r["status"] != "done" else ("", "")) if t)
        label = f'<div class="sub">{esc(r["label"])}</div>' if r.get("label") else ""
        out.append(f'<tr><th class="run" scope="row"><span class="{"code-name" if is_code(r) else ""}">'
                   f'{esc(run_name(r))}</span>{chips}{label}</th>')
        for k in step.headline:
            v = s.get(k)
            if k in fracs and isinstance(v, float):
                top = " top" if best.get(k) is not None and abs(v - best[k]) < 1e-9 and len(runs) > 1 else ""
                out.append(f'<td class="bar{top}"><span class="fill" style="--wn:{max(0.0, min(1.0, v)):.3f}"></span>'
                           f'<span class="v">{num(v)}</span></td>')
            else:
                out.append(f'<td class="n">{esc(num(v))}</td>')
        out.append(f'<td class="n">{esc(usd(r.get("cost_per_story_usd")))}</td><td class="n">{esc(usd(r.get("cost_usd")))}</td>'
                   f'<td class="n">{esc(secs(r.get("wall_s")))}</td>'
                   f'<td class="n">{r.get("calls", 0)} <span class="muted">({r.get("cache_hits", 0)})</span></td></tr>')
    out.append("</tbody></table></div>")
    return "".join(out)


def score_notes(step: Step) -> str:
    rows = "".join(f"<dt>{esc(metric_info(step, k)[0])}</dt><dd>{esc(metric_info(step, k)[1])}</dd>"
                   for k in step.headline if metric_info(step, k)[1])
    return f'<details class="notes"><summary>What each score means</summary><dl>{rows}</dl></details>' if rows else ""


def _conf(summary: dict) -> dict[tuple[str, str], int]:
    out = {}
    for k, n in (summary.get("confusion") or {}).items():
        if "->" in k:
            g, p = k.split("->", 1)
            out[(g, p)] = int(n)
    return out


def confusion(step: Step, runs: list[dict]) -> str:
    runs = [r for r in runs if _conf(r["summary"])]
    if not runs:
        return ""
    names = getattr(step, "class_names", {}) or {}
    order = list(names) or []
    blocks = []
    for r in runs:
        c = _conf(r["summary"])
        seen_g = {g for g, _ in c}
        seen_p = {p for _, p in c}
        golds = [x for x in order if x in seen_g] + sorted(seen_g - set(order))
        preds = [x for x in order if x in seen_p or x in seen_g] + sorted(seen_p - set(order) - seen_g)
        t = [f'<figure class="conf"><figcaption>{esc(run_name(r))}</figcaption><table><thead><tr>'
             f'<th class="corner">answer key ↓ · model →</th>']
        t += [f"<th>{esc(names.get(p, p))}</th>" for p in preds]
        t.append("</tr></thead><tbody>")
        for g in golds:
            total = sum(n for (gg, _), n in c.items() if gg == g)
            t.append(f'<tr><th scope="row">{esc(names.get(g, g))} <span class="muted">{total}</span></th>')
            for p in preds:
                n = c.get((g, p), 0)
                share = n / total if total else 0
                cls = ("hit" if g == p else "miss") + (" strong" if share > 0.55 else "")
                tip = (f"Answer key: {names.get(g, g)} · model said: {names.get(p, p)}\n"
                       f"{n} of {total} ({share:.0%})")
                t.append(f'<td class="{cls}" style="--p:{share * 100:.0f}%" data-tip="{esc(tip)}">{n or ""}</td>')
            t.append("</tr>")
        t.append("</tbody></table></figure>")
        blocks.append("".join(t))
    return ('<div class="legend"><span><i class="key hitk"></i>right (darker = more of that row)</span>'
            '<span><i class="key missk"></i>wrong</span></div><div class="confs">' + "".join(blocks) + "</div>")


def hard_stories(step: Step, runs: list[dict]) -> str:
    runs = [r for r in runs if r["summary"].get("stories")]
    if not runs:
        return ""
    names = step.story_names() or {}
    sids = sorted({s for r in runs for s, v in r["summary"]["stories"].items() if v is not None})
    if not sids:
        return ""
    def mean(sid):
        v = [r["summary"]["stories"].get(sid) for r in runs if not is_code(r)]
        v = [x for x in v if x is not None] or [r["summary"]["stories"].get(sid) for r in runs]
        v = [x for x in v if x is not None]
        return sum(v) / len(v) if v else 1.0
    sids.sort(key=lambda s: (mean(s), s))
    # A step's per-story number is a share (0 to 1: same-story accuracy, coverage) or a count (blindspots,
    # framing points, flagged claims). A count used to be printed as a percent too: 76 points read "7600".
    vals = [v for r in runs for v in r["summary"]["stories"].values() if isinstance(v, (int, float))]
    shares = all(0 <= v <= 1 for v in vals)
    top = max(vals, default=0) or 1

    def shown(v) -> tuple[float, str]:
        """(how full the cell is drawn, 0-100; the text in it)"""
        return (v * 100, f"{v * 100:.0f}") if shares else (v / top * 100, f"{v:g}")
    out = ['<div class="scroll"><table class="heat"><thead><tr><th class="story">Story</th>']
    out += [f'<th><span class="{"code-name" if is_code(r) else ""}">{esc(r["model"].removeprefix(CODE_PREFIX))}</span>'
            f'<span class="sub">{esc(r["version"])}</span></th>' for r in runs]
    out.append('<th>Average<span class="sub">model runs</span></th></tr></thead><tbody>')
    for sid in sids:
        title = names.get(sid, "")
        out.append(f'<tr><th scope="row" class="story" data-tip="{esc(title)}"><span class="sid">{esc(sid)}</span> '
                   f'{esc(title[:60] + ("…" if len(title) > 60 else ""))}</th>')
        for r in runs:
            v = r["summary"]["stories"].get(sid)
            if v is None:
                out.append('<td class="none" data-tip="not in this run">·</td>')
                continue
            fill, text = shown(v)
            tip = (f"{run_name(r)}\n{sid} {title}\n" +
                   (f"{v:.0%} of its labeled items right" if shares else f"{v:g} in this story (a count, not a share)"))
            out.append(f'<td class="cell{" strong" if fill > 55 else ""}" style="--p:{fill:.0f}%" '
                       f'data-tip="{esc(tip)}">{text}</td>')
        fill, text = shown(mean(sid))
        out.append(f'<td class="cell avg{" strong" if fill > 55 else ""}" style="--p:{fill:.0f}%">'
                   f'{text if shares else f"{mean(sid):.1f}"}</td></tr>')
    out.append("</tbody></table></div>")
    return "".join(out)


def mistakes(step: Step, runs: list[dict], out_dir=None) -> str:
    names = getattr(step, "class_names", {}) or {}
    story = step.story_names() or {}
    blocks = []
    for r in runs:
        try:
            rec = json.loads((_runs_dir(out_dir) / r["file"]).read_text(encoding="utf-8"))
            rows = step.mistakes(rec)
        except Exception:
            continue
        if not rows:
            continue
        rows.sort(key=lambda m: (m.get("gold", ""), m.get("pred", ""), m.get("story", "")))
        t = [f'<details class="mist"><summary>{esc(run_name(r))} <span class="muted">· {len(rows)} wrong</span></summary>'
             '<div class="scroll"><table><thead><tr><th>Story</th><th>Item</th><th>Answer key</th><th>Model said</th>'
             "<th>Model's reason</th></tr></thead><tbody>"]
        for m in rows:
            title = esc(m.get("title") or "")
            url = m.get("url") or ""
            item = f'<a href="{esc(url)}" target="_blank" rel="noopener">{title}</a>' if url.startswith("https://") else title
            src = f' <span class="muted">({esc(m["source"])})</span>' if m.get("source") else ""
            sid = m.get("story", "")
            t.append(f'<tr><td data-tip="{esc(story.get(sid, ""))}"><span class="sid">{esc(sid)}</span></td>'
                     f'<td class="item"><span class="muted">{esc(m.get("kind", ""))}</span> {item}</td>'
                     f'<td>{esc(names.get(m.get("gold"), m.get("gold")))}{src}</td>'
                     f'<td class="said">{esc(names.get(m.get("pred"), m.get("pred")))}</td>'
                     f'<td class="reason">{esc(m.get("reason") or "")}</td></tr>')
        t.append("</tbody></table></div></details>")
        blocks.append("".join(t))
    return "".join(blocks)


def headline_sentence(step: Step, runs: list[dict]) -> str:
    main = step.headline[0]
    mname = metric_info(step, main)[0]
    scored = [r for r in runs if isinstance(r["summary"].get(main), (int, float))]
    model = [r for r in scored if not is_code(r)]
    code = [r for r in scored if is_code(r)]
    parts = []
    if model:
        b = max(model, key=lambda r: r["summary"][main])
        parts.append(f"Best model run: <b>{esc(run_name(b))}</b>, {esc(mname)} <b>{num(b['summary'][main])}</b> "
                     f"at {esc(usd(b.get('cost_per_story_usd')))} per story")
    if code:
        c = max(code, key=lambda r: r["summary"][main])
        parts.append(f"plain-code baseline {esc(run_name(c))}: {num(c['summary'][main])}")
    return f'<p class="lede">{"; ".join(parts)}.</p>' if parts else ""


# ---- the page -----------------------------------------------------------------------------------

CSS = """
:root{--bg:#fafafa;--surface:#ffffff;--fg:#18181b;--muted:#52525b;--faint:#a1a1aa;--line:#e4e4e7;--grid:#efeff1;
--ok:#2a78d6;--miss:#eb6834;--code:#71717a;--on-strong:#ffffff;--warn-bg:#fdf1e7;--warn-fg:#9a3412;--best-bg:#e8f1fc;--best-fg:#1c5cab;
--sans:"Geist",ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;--mono:"Geist Mono",ui-monospace,"SF Mono",Menlo,monospace}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#0f0f11;--surface:#18181b;--fg:#f4f4f5;--muted:#a1a1aa;
--faint:#71717a;--line:#2c2c31;--grid:#222226;--ok:#3987e5;--miss:#d95926;--code:#a1a1aa;--warn-bg:#3a2213;--warn-fg:#fdba8c;
--best-bg:#16294a;--best-fg:#9ec5f4;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#0f0f11;--surface:#18181b;--fg:#f4f4f5;--muted:#a1a1aa;--faint:#71717a;--line:#2c2c31;--grid:#222226;
--ok:#3987e5;--miss:#d95926;--code:#a1a1aa;--warn-bg:#3a2213;--warn-fg:#fdba8c;--best-bg:#16294a;--best-fg:#9ec5f4;color-scheme:dark}
body{background:var(--bg);color:var(--fg);font:14px/1.5 var(--sans);font-variant-numeric:tabular-nums}
.page{max-width:1080px;margin:0 auto;padding-block:28px 64px;padding-left:max(16px,env(safe-area-inset-left,0px));
padding-right:max(16px,env(safe-area-inset-right,0px));display:flex;flex-direction:column;gap:28px}
header{display:flex;flex-direction:column;gap:6px}
h1{font-size:26px;line-height:1.2;margin:0;font-weight:600;letter-spacing:-.01em;text-wrap:balance}
h2{font-size:18px;margin:0;font-weight:600;letter-spacing:-.005em}
h3{font-size:14px;margin:0;font-weight:600}
p{margin:0;max-width:72ch}.muted{color:var(--muted)}.intro{color:var(--muted)}
.meta{font:12px/1.5 var(--mono);color:var(--muted)}
section.split{display:flex;flex-direction:column;gap:22px;border-top:1px solid var(--line);padding-top:24px}
.block{display:flex;flex-direction:column;gap:10px;min-width:0}
.block>p.what{color:var(--muted);font-size:13px}
.lede{font-size:15px}
.scroll{overflow-x:auto;min-width:0}
svg{display:block;width:100%;min-width:560px;max-width:820px;height:auto}
svg text{font-family:var(--sans)}
.grid{stroke:var(--grid);stroke-width:1}.axis{stroke:var(--faint);stroke-width:1}
.tick{fill:var(--muted);font-size:11px;font-family:var(--mono)!important}
.axis-title{fill:var(--muted);font-size:12px}
.dot{fill:var(--ok);stroke:var(--surface);stroke-width:2}.dot.code{fill:var(--code)}
.hit{fill:transparent;cursor:default;outline:none}.hit:focus-visible{stroke:var(--fg);stroke-width:1.5}
.dot-label{fill:var(--fg);font-size:12px}
.legend{display:flex;flex-wrap:wrap;gap:6px 18px;font-size:12px;color:var(--muted)}
.legend span{display:inline-flex;align-items:center;gap:6px}
.key{display:inline-block;width:10px;height:10px;border-radius:50%}.key.model{background:var(--ok)}.key.code{background:var(--code)}
.key.hitk{border-radius:2px;background:var(--ok)}.key.missk{border-radius:2px;background:var(--miss)}
table{border-collapse:separate;border-spacing:0;font-size:13px}
th,td{padding:6px 10px;text-align:left;vertical-align:top;border-bottom:1px solid var(--line)}
thead th{font-weight:500;color:var(--muted);font-size:12px;white-space:nowrap;vertical-align:bottom}
thead th[data-tip]{text-decoration:underline dotted var(--faint);text-underline-offset:3px}
table.scores{background:var(--surface);border:1px solid var(--line);border-radius:8px}
table.scores tbody tr:last-child>*{border-bottom:0}
th.run{font-weight:500;min-width:200px}.sub{display:block;font-size:12px;color:var(--muted);font-weight:400}
.code-name{color:var(--muted)}
td.n{text-align:right;font-family:var(--mono);font-size:12px;white-space:nowrap}
td.bar{position:relative;min-width:78px;font-family:var(--mono);font-size:12px}
td.bar .fill{position:absolute;left:10px;bottom:5px;height:3px;width:calc((100% - 20px) * var(--wn,0));
background:var(--ok);border-radius:2px;opacity:.55}
td.bar.top .v{font-weight:600}
.chip{display:inline-block;margin-left:6px;padding:0 6px;border-radius:999px;font-size:11px;line-height:18px;font-weight:500}
.chip.best{background:var(--best-bg);color:var(--best-fg)}.chip.warn{background:var(--warn-bg);color:var(--warn-fg)}
details.notes summary,details.mist summary{cursor:pointer;color:var(--muted);font-size:13px}
details.notes dl{display:grid;grid-template-columns:minmax(120px,max-content) 1fr;gap:4px 16px;margin:10px 0 0;font-size:13px}
details.notes dt{font-weight:500}details.notes dd{margin:0;color:var(--muted)}
.confs{display:flex;flex-wrap:wrap;gap:18px}
figure.conf{margin:0;display:flex;flex-direction:column;gap:6px}
figure.conf figcaption{font-size:13px;font-weight:500}
figure.conf table td,figure.conf table th{border:0;padding:0}
figure.conf table{border-spacing:2px}
figure.conf thead th{padding:0 4px 4px;font-size:11px;text-align:center}
figure.conf th.corner{text-align:left;color:var(--faint);font-weight:400}
figure.conf tbody th{font-size:12px;font-weight:500;padding-right:8px;white-space:nowrap;vertical-align:middle}
figure.conf td{width:54px;height:34px;text-align:center;vertical-align:middle;font-family:var(--mono);font-size:12px;border-radius:4px;
background:var(--grid)}
figure.conf td.hit{background:color-mix(in oklab,var(--ok) var(--p),var(--surface))}
figure.conf td.miss{background:color-mix(in oklab,var(--miss) var(--p),var(--surface))}
td.strong{color:var(--on-strong)}
table.heat{border-spacing:2px}
table.heat th,table.heat td{border:0;padding:0}
table.heat thead th{padding:0 4px 6px;text-align:center;font-size:11px;min-width:64px}
table.heat th.story{text-align:left;font-weight:400;font-size:12px;padding-right:12px;white-space:nowrap;max-width:420px;
overflow:hidden;text-overflow:ellipsis;vertical-align:middle}
table.heat td{height:24px;text-align:center;vertical-align:middle;font-family:var(--mono);font-size:11px;border-radius:3px}
table.heat td.cell{background:color-mix(in oklab,var(--ok) var(--p),var(--surface))}
table.heat td.avg{outline:1px solid var(--line)}
table.heat td.none{color:var(--faint)}
.sid{font-family:var(--mono);font-size:11px;color:var(--muted)}
details.mist table{margin-top:8px;background:var(--surface);border:1px solid var(--line);border-radius:8px}
details.mist td.item{min-width:260px;max-width:440px}details.mist td.reason{min-width:200px;max-width:340px;color:var(--muted)}
details.mist td.said{font-weight:500}
a{color:var(--best-fg)}
.empty{color:var(--muted)}
ul.partial{margin:0;padding-left:18px;color:var(--muted);font-size:13px}
#tip{position:fixed;z-index:20;pointer-events:none;max-width:340px;padding:8px 10px;border-radius:6px;background:var(--fg);
color:var(--bg);font-size:12px;line-height:1.45;white-space:pre-line;box-shadow:0 4px 16px rgb(0 0 0/.18)}
@media (max-width:560px){h1{font-size:22px}}
"""

JS = """
(()=>{const tip=document.getElementById('tip');let cur=null;
function show(t,x,y){tip.textContent=t;tip.hidden=false;place(x,y)}
function place(x,y){const p=14,w=tip.offsetWidth,h=tip.offsetHeight;let a=x+p,b=y+p;
if(a+w>innerWidth-8)a=Math.max(8,x-w-p);if(b+h>innerHeight-8)b=Math.max(8,y-h-p);tip.style.left=a+'px';tip.style.top=b+'px'}
document.addEventListener('pointerover',e=>{const t=e.target.closest('[data-tip]');cur=t;if(!t||!t.dataset.tip){tip.hidden=true;return}show(t.dataset.tip,e.clientX,e.clientY)});
document.addEventListener('pointermove',e=>{if(!tip.hidden)place(e.clientX,e.clientY)});
document.addEventListener('focusin',e=>{const t=e.target.closest('[data-tip]');if(!t){tip.hidden=true;return}const r=t.getBoundingClientRect();show(t.dataset.tip,r.right,r.top)});
document.addEventListener('focusout',()=>{tip.hidden=true});document.addEventListener('scroll',()=>{tip.hidden=true},{passive:true});})();
"""


def build(step: Step, out_dir=None, rows: list[dict] | None = None) -> str:
    rows = rows if rows is not None else index_rows(step.name, out_dir)
    runs = runs_to_show(rows)
    title = getattr(step, "report_title", "") or f"{step.name.replace('_', ' ').capitalize()} evals"
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    splits = [s for s in SPLITS if any(r.get("split") == s for r in runs)]
    splits += sorted({r.get("split") for r in runs} - set(SPLITS) - {None})
    body = [f'<header><h1>{esc(title)}</h1>']
    if getattr(step, "report_intro", ""):
        body.append(f'<p class="intro">{esc(step.report_intro)}</p>')
    body.append(f'<p class="meta">answer key {esc(step.key_version())} · {plural(len(runs), "run")} · updated {now}</p></header>')
    if not runs:
        body.append('<p class="empty">No runs yet. Start one with python -m scripts.run_eval run '
                    f'{esc(step.name)} --model &lt;alias&gt;.</p>')
    main_name = metric_info(step, step.headline[0])[0] if step.headline else ""
    for s in splits:
        rs = [r for r in runs if r.get("split") == s]
        name, note = SPLITS.get(s, (s, ""))
        n_st = max((r.get("stories") or 0) for r in rs)
        partial = [r for r in rs if (r.get("stories") or 0) < n_st]      # e.g. one-story smoke tests
        rs = [r for r in rs if r not in partial]
        body.append(f'<section class="split"><div class="block"><h2>{esc(name)} <span class="muted">· {n_st} stories, '
                    f'{plural(len(rs), "run")}</span></h2><p class="what">{esc(note)}</p>{headline_sentence(step, rs)}</div>')
        if step.headline:
            body.append(f'<div class="block"><h3>Quality against cost</h3><p class="what">One dot per run. Up is a '
                        f'better {esc(main_name)}; left is cheaper. Hover a dot for its numbers.</p>{scatter(step, rs)}</div>')
            body.append(f'<div class="block"><h3>Scores</h3><p class="what">Best run first. The bar under each score '
                        f'runs from 0 to 1; the best value in a column is bold.</p>{scores_table(step, rs)}'
                        f'{score_notes(step)}</div>')
        c = confusion(step, rs)
        if c:
            body.append(f'<div class="block"><h3>Where the mistakes fall</h3><p class="what">Each grid is one run. '
                        f'Rows are the answer key, columns what the model said; the number is how many labeled '
                        f'items landed there.</p>{c}</div>')
        h = hard_stories(step, rs)
        if h:
            body.append(f'<div class="block"><h3>Which stories are hard</h3><p class="what">Each cell is the share of '
                        f'a story\'s labeled items a run got right, in percent; hardest stories on top.</p>{h}</div>')
        m = mistakes(step, [r for r in rs if not is_code(r)], out_dir)
        if m:
            body.append(f'<div class="block"><h3>Every mistake, with the model\'s reason</h3>{m}</div>')
        if partial:
            items = "".join(f"<li>{esc(run_name(r))} on {plural(r.get('stories') or 0, 'story', 'stories')}"
                            f"{' (' + esc(r['label']) + ')' if r.get('label') else ''}: {esc(r['status'])}, "
                            f"{esc(usd(r.get('cost_usd')))}</li>" for r in partial)
            body.append(f'<div class="block"><h3>Partial runs</h3><p class="what">Runs on fewer stories than the rest '
                        f'(smoke tests, single stories). Left out of the comparison above.</p><ul class="partial">'
                        f'{items}</ul></div>')
        body.append("</section>")
    return (f"<title>{esc(title)}</title>\n"
            '<meta name="claude:viewport-fit-sides" content="cover">\n'
            '<link rel="preconnect" href="https://fonts.googleapis.com">'
            '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
            '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600&'
            'family=Geist+Mono:wght@400;500&display=swap">\n'
            f"<style>{CSS}</style>\n"
            f'<div class="page">{"".join(body)}</div><div id="tip" role="tooltip" hidden></div>\n'
            f"<script>{JS}</script>\n")


def write(step: Step, out_dir=None) -> Path:
    p = report_path(step, out_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(build(step, out_dir), encoding="utf-8")
    return p
