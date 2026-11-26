"""Code renders the Story File as a readable one-page brief, for people and for debugging (module 5:
no model-written prose overview). Every value is escaped; quotes come from facts.jsonl.

    page([(facts, story_file, problems), ...], title) -> one HTML page, a story picker on top
"""
from __future__ import annotations

import html

STATUS_NOTE = {"blindspot": "missing from the other side", "reported": "the other side reports it",
               "told differently": "the other side tells it differently", "unclear": "unclear",
               "unchecked": "the judge gave no answer", "not checked": "not checked"}


def e(x) -> str:
    return html.escape("" if x is None else str(x), quote=True)


def _link(url, text) -> str:
    return f'<a href="{e(url)}" rel="noopener">{e(text)}</a>' if str(url or "").startswith("https://") else e(text)


def _side_of(sf: dict) -> dict:
    s = sf.get("sides") or {}
    return {s[g]["side_id"]: (g, s[g]["label"]) for g in ("A", "B") if g in s}


def _chip(text, cls="") -> str:
    return f'<span class="chip {cls}">{e(text)}</span>'


def story(facts: list[dict], sf: dict, problems: list[str]) -> str:
    ev, sides = sf.get("event") or {}, _side_of(sf)
    fid = {f["id"]: f for f in facts}
    src = {s["id"]: s for s in sf.get("sources") or []}
    cid = {c["id"]: c for c in sf.get("claims") or []}
    outlet = lambda a: (src.get(a) or {}).get("outlet_name") or (src.get(a) or {}).get("outlet") or a
    sideclass = lambda sid: "sa" if sides.get(sid, ("",))[0] == "A" else "sb" if sides.get(sid, ("",))[0] == "B" else "sn"
    out = [f'<header class="sh"><p class="eyebrow">{e(ev.get("category"))} · {e(ev.get("subtype"))} · severity '
           f'{e(ev.get("severity"))} · confidence {e(ev.get("confidence"))} · {e((ev.get("start") or "")[:16].replace("T", " "))} UTC</p>'
           f'<h2>{e(ev.get("title"))}</h2><p class="muted">{e(ev.get("location_name"))}</p><p>{e(ev.get("summary"))}</p>']
    if problems:
        out.append('<p class="bad">Problems: ' + "; ".join(e(p) for p in problems[:8]) + "</p>")
    fl = sf.get("flags") or []
    if fl:
        out.append('<div class="chips">' + "".join(_chip(f"{f['code']}: {f['detail']}", "flag") for f in fl) + "</div>")
    out.append("</header>")

    s = sf.get("sides") or {}
    if s.get("kind") == "two sides":
        out.append('<div class="sides">' + "".join(
            f'<div class="side {("sa", "sb")[i]}"><b>{e(s[g]["label"])}</b><span>{e(s[g]["articles"])} articles read</span></div>'
            for i, g in enumerate(("A", "B")) if g in s) + "</div>")
    else:
        out.append(f'<p class="muted">No real divide{": " + e(s.get("reason")) if s.get("reason") else ""}.</p>')

    c = sf.get("counts") or {}
    out.append('<div class="nums">' + "".join(
        f'<div><b>{e(v)}</b><span>{e(k)}</span></div>' for k, v in (
            ("articles read", c.get("articles_read")), ("facts", c.get("facts")), ("claims", c.get("claims")),
            ("conflicts", c.get("conflicts")), ("blindspots", f"{c.get('blindspots_central', 0)} + {c.get('blindspots_detail', 0)}"),
            ("side points", c.get("perspective_points")))) + "</div>")

    persp = sf.get("perspectives") or []
    if persp or sf.get("perspectives_skipped"):
        out.append("<h3>How each side tells it</h3>")
        for p in persp:
            out.append(f'<div class="card {sideclass(p["side_id"])}"><h4>{e(p["label"])}</h4><ul>')
            for pt in p["points"]:
                qs = "; ".join(f'{e(q["outlet"])}: “{e(q["words"])}”' + (f' <i>({e(q["words_en"])})</i>' if q["words_en"] else "")
                               for q in pt["quotes"])
                out.append(f'<li><span class="kind">{e(pt["kind"])}</span> {e(pt["point"])}<div class="q">{qs}</div></li>')
            out.append("</ul></div>")
        for k in sf.get("perspectives_skipped") or []:
            out.append(f'<p class="muted">Skipped: {e(k.get("label") or "")} {e(k.get("reason"))}.</p>')

    if sf.get("blindspots"):
        out.append("<h3>Blindspots</h3>")
        for b in sf["blindspots"]:
            lab = sides.get(b["silent_side"], ("", b.get("label")))[1]
            out.append(f'<div class="card"><h4>Missing from {e(lab)}</h4><p class="muted">{e(b["checked"])} of '
                       f'{e(b["candidates"])} candidates checked by the judge.</p><ul>')
            for kind in ("central", "detail"):
                for x in b[kind]:
                    out.append(f'<li><span class="kind">{kind}</span> <code>{e(x)}</code> {e(cid[x]["claim"]) if x in cid else ""}</li>')
            if not b["central"] and not b["detail"]:
                out.append("<li class='muted'>None confirmed.</li>")
            out.append("</ul></div>")

    out.append(f'<h3>Claims ({len(cid)})</h3><div class="claims">')
    for cl in sf.get("claims") or []:
        tags = [_chip(cl["kind"])]
        if cl.get("who_says") and cl["who_says"] != "the outlet":
            tags.append(_chip(f"says: {cl['who_says']}"))
        for sid in cl.get("sides") or []:
            tags.append(_chip(sides.get(sid, ("", sid))[1], sideclass(sid)))
        if cl.get("neither"):
            tags.append(_chip(f"{cl['neither']} on neither side", "sn"))
        tags.append(_chip(f"{cl.get('independent')} independent"))
        if cl.get("conflicts_with"):
            tags.append(_chip("conflicts with " + ", ".join(cl["conflicts_with"]), "warn"))
        b = cl.get("blindspot")
        if b:
            tags.append(_chip(f"{STATUS_NOTE.get(b['status'], b['status'])}" + (f" ({b['matters']})" if b.get("matters") and b["status"] == "blindspot" else ""),
                              "blind" if b["status"] == "blindspot" else ""))
        tags += [_chip(f, "flag") for f in cl.get("flags") or []]
        quotes = "".join(
            f'<li>{_link((src.get(fid[x]["article"]) or {}).get("url"), outlet(fid[x]["article"]))}: “{e(fid[x]["quote"])}”'
            + (f' <i>({e(fid[x]["quote_en"])})</i>' if fid[x].get("quote_en") else "") + "</li>"
            for x in cl["facts"] if x in fid)
        out.append(f'<details class="claim"><summary><code>{e(cl["id"])}</code> {e(cl["claim"])}'
                   f'<div class="chips">{"".join(tags)}</div></summary><ul class="q">{quotes}</ul></details>')
    out.append("</div>")

    if sf.get("updates"):
        out.append("<h3>Updates (a count that rose between reports)</h3><ul>" + "".join(
            f'<li><code>{e(u["a"])}</code> → <code>{e(u["b"])}</code> {e(u.get("why"))}</li>' for u in sf["updates"]) + "</ul>")

    out.append(f'<h3>Sources ({len(src)})</h3><div class="scroll"><table><thead><tr><th>Outlet</th><th>Side</th>'
               '<th>Headline</th><th>Reliability</th><th>Read</th></tr></thead><tbody>')
    for so in sf.get("sources") or []:
        sd = sides.get(so.get("side"), ("", so.get("group")))[1] if so.get("side") else so.get("group")
        rel = "unrated" if so.get("reliability") is None else f"{so['reliability']:.2f}"
        out.append(f'<tr><td>{e(so.get("outlet_name") or so.get("outlet"))}</td><td class="{sideclass(so.get("side"))}">'
                   f'{e(sd)}</td><td>{_link(so.get("url"), so.get("headline"))}</td><td>{e(rel)}</td>'
                   f'<td>{"yes" if so.get("read") else "no"}</td></tr>')
    out.append("</tbody></table></div>")

    m = sf.get("meta") or {}
    steps = "; ".join(f"{k} {v.get('version')} ({v.get('model')})" for k, v in (m.get("steps") or {}).items())
    cost = (m.get("cost_usd") or {}).get("total")
    out.append(f'<p class="note">Steps: {e(steps)}. Cost: {"$" + format(cost, ".4f") if cost is not None else "see the eval runs"}. '
               f'Built {e(m.get("created_at"))}. {e(sf.get("attribution") or "Events by Monitor the Situation.")}</p>')
    return "\n".join(out)


CSS = """
:root{--bg:#f4f4f5;--card:#fff;--line:#e4e4e7;--ink:#18181b;--muted:#52525b;--faint:#71717a;--soft:#f4f4f5;
--a:#3d6a96;--a-bg:#e7eef5;--b:#a8506b;--b-bg:#f6e6ec;--n:#71717a;--warn:#8a5a12;--warn-bg:#fbf1dc;--bad:#b42318;
--sans:"Geist",ui-sans-serif,-apple-system,"Segoe UI",Roboto,Arial,sans-serif;--mono:"Geist Mono",ui-monospace,Menlo,monospace}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#0f0f11;--card:#1a1a1d;--line:#2a2a2f;--ink:#f4f4f5;
--muted:#a1a1aa;--faint:#8b8b94;--soft:#232327;--a:#7ea6cf;--a-bg:#1b2633;--b:#d98aa3;--b-bg:#331c25;--n:#a1a1aa;
--warn:#e9b65a;--warn-bg:#33270f;--bad:#f97066;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#0f0f11;--card:#1a1a1d;--line:#2a2a2f;--ink:#f4f4f5;--muted:#a1a1aa;--faint:#8b8b94;
--soft:#232327;--a:#7ea6cf;--a-bg:#1b2633;--b:#d98aa3;--b-bg:#331c25;--n:#a1a1aa;--warn:#e9b65a;--warn-bg:#33270f;--bad:#f97066;color-scheme:dark}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 var(--sans);padding:32px max(16px,env(safe-area-inset-left)) 64px}
.wrap{max-width:960px;margin:0 auto}h1{font-size:30px;margin:0 0 6px;letter-spacing:-.02em}h2{font-size:24px;margin:4px 0;letter-spacing:-.01em}
h3{font-size:17px;margin:28px 0 10px}h4{margin:0 0 6px;font-size:15px}p{margin:6px 0}.muted{color:var(--muted)}.note{color:var(--faint);font-size:13px;margin-top:24px}
.eyebrow{font:12px var(--mono);color:var(--faint);text-transform:uppercase;letter-spacing:.04em;margin:0}
.bad{color:var(--bad);font-weight:500}code{font:12.5px var(--mono)}a{color:inherit;text-underline-offset:2px}
.pick{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:16px 0 24px}select{font:14px var(--sans);padding:6px 8px;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--ink);max-width:100%}
.story{display:none;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:22px}.story.on{display:block}
.chips{display:flex;flex-wrap:wrap;gap:5px;margin-top:6px}.chip{font:11.5px var(--mono);padding:1px 7px;border-radius:999px;background:var(--soft);color:var(--muted);border:1px solid var(--line)}
.chip.sa{background:var(--a-bg);color:var(--a);border-color:transparent}.chip.sb{background:var(--b-bg);color:var(--b);border-color:transparent}
.chip.flag,.chip.warn{background:var(--warn-bg);color:var(--warn);border-color:transparent}.chip.blind{background:var(--ink);color:var(--bg);border-color:transparent}
.sides{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:14px 0}.side{padding:10px 12px;border-radius:8px;display:flex;flex-direction:column}
.side.sa{background:var(--a-bg);color:var(--a)}.side.sb{background:var(--b-bg);color:var(--b)}.side span{font-size:13px}
.nums{display:grid;grid-template-columns:repeat(6,1fr);gap:8px;margin:12px 0}.nums div{border:1px solid var(--line);border-radius:8px;padding:8px}
.nums b{display:block;font-size:20px}.nums span{font-size:12px;color:var(--faint)}
.card{border:1px solid var(--line);border-radius:8px;padding:12px 14px;margin:8px 0}.card.sa{border-left:4px solid var(--a)}.card.sb{border-left:4px solid var(--b)}
.card ul{margin:0;padding-left:18px}.card li{margin:6px 0}.kind{font:11.5px var(--mono);color:var(--faint);text-transform:uppercase}
.q{color:var(--muted);font-size:13.5px}ul.q{margin:6px 0 4px;padding-left:20px}
.claim{border-top:1px solid var(--line);padding:8px 0}.claim summary{cursor:pointer;list-style:none}.claim summary::-webkit-details-marker{display:none}
.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:13.5px}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{font:12px var(--mono);color:var(--faint);text-transform:uppercase}td.sa{color:var(--a)}td.sb{color:var(--b)}td.sn{color:var(--n)}
.sum td,.sum th{white-space:nowrap}.sum tr{cursor:pointer}.sum tr:hover td{background:var(--soft)}
@media (max-width:640px){.sides{grid-template-columns:1fr}.nums{grid-template-columns:repeat(3,1fr)}}
"""


def page(stories: list[tuple], title: str = "Story Files", intro: str = "") -> str:
    """stories: [(facts, story_file, problems)]."""
    opts, secs, rows = [], [], []
    for i, (facts, sf, probs) in enumerate(stories):
        ev, c = sf.get("event") or {}, sf.get("counts") or {}
        sid = f"s{i}"
        opts.append(f'<option value="{sid}">{e((ev.get("id") or "")[:8])} · {e(ev.get("title"))}</option>')
        secs.append(f'<section class="story{" on" if i == 0 else ""}" id="{sid}">{story(facts, sf, probs)}</section>')
        kind = "two sides" if (sf.get("sides") or {}).get("kind") == "two sides" else "no divide"
        rows.append(f'<tr data-s="{sid}"><td><code>{e((ev.get("id") or "")[:8])}</code></td><td>{e((ev.get("title") or "")[:60])}</td>'
                    f'<td>{e(kind)}</td><td>{e(c.get("claims"))}</td><td>{e(c.get("facts"))}</td><td>{e(c.get("conflicts"))}</td>'
                    f'<td>{e(c.get("blindspots_central", 0))} + {e(c.get("blindspots_detail", 0))}</td><td>{e(c.get("perspective_points"))}</td>'
                    f'<td>{e(len(sf.get("flags") or []))}</td><td>{"ok" if not probs else e(len(probs))}</td></tr>')
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600&family=Geist+Mono&display=swap">
<style>{CSS}</style></head><body><div class="wrap">
<h1>{e(title)}</h1><p class="muted">{e(intro)}</p>
<div class="scroll"><table class="sum"><thead><tr><th>Story</th><th>Title</th><th>Sides</th><th>Claims</th><th>Facts</th>
<th>Conflicts</th><th>Blindspots</th><th>Side points</th><th>Flags</th><th>Checks</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>
<div class="pick"><label for="pick">Story</label><select id="pick">{"".join(opts)}</select></div>
{"".join(secs)}
</div><script>
const pick=document.getElementById('pick');
function show(id){{document.querySelectorAll('.story').forEach(s=>s.classList.toggle('on',s.id===id));pick.value=id;}}
pick.addEventListener('change',()=>show(pick.value));
document.querySelectorAll('.sum tr[data-s]').forEach(r=>r.addEventListener('click',()=>{{show(r.dataset.s);pick.scrollIntoView({{behavior:'smooth'}});}}));
</script></body></html>"""
