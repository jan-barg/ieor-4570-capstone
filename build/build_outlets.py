"""One-time build of outlets.csv and side_lists.csv, plus REVIEW.md.

    python build/build_outlets.py            # refuses to overwrite a hand-edited outlets.csv
    python build/build_outlets.py --force    # rebuild from the seed (loses hand edits)

Joins onto the hand seed (outlet_seed.py):
  AllSides  outlet_labels_tests/allsides_2026-11-24.csv  (read in Jan's Chrome, Nov 24)
  Lin et al. 2023  outlet_labels_tests/lin2023_domain_pc1.csv
  Wikidata  outlet_labels_tests/wikidata_matches.csv  (item id only)
  State Media Monitor 2026  outlet_labels_tests/smm_2026.csv  (level by entity id)"""
import csv
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from stringer import paths  # noqa: E402
from stringer.outlets import COLUMNS, OPINION_FOLDERS  # noqa: E402
import outlet_seed  # noqa: E402
import side_seed  # noqa: E402

SRC = paths.OUTLET_SOURCES
SMM_LEVEL = {"SC": "State-Controlled", "CaPu": "Captured Public", "CaPr": "Captured Private",
             "IP": "Independent Public", "ISF": "Independent State-Funded",
             "ISFM": "Independent State-Funded and State-Managed", "ISM": "Independent State-Managed"}
ALLSIDES_DATE = "2026-11-24"


def read(name):
    with open(SRC / name, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main(force=False):
    out_dir = paths.OUTLETS_CSV.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    if paths.OUTLETS_CSV.exists() and not force:
        sys.exit(f"{paths.OUTLETS_CSV} exists (hand-edited?). Use --force to rebuild from the seed.")

    allsides = read("allsides_2026-11-24.csv")
    as_news = {r["allsides_name"]: r for r in allsides if r["section"] == "news"}
    as_opinion = [r for r in allsides if r["section"] == "opinion"]
    lin = {r["domain"]: float(r["pc1"]) for r in read("lin2023_domain_pc1.csv")}
    wd = {r["domain"]: r for r in read("wikidata_matches.csv")}
    smm = {r["smm_id"]: r for r in read("smm_2026.csv")}

    rows, review, used_as = [], [], set()
    for s in outlet_seed.rows():
        domains = [d for d in s["domains"].split(";") if d]
        hosts = [d.split("/")[0] for d in domains]
        handles = [h for h in s["x_handles"].split(";") if h]
        r = {c: "" for c in COLUMNS}
        r.update(outlet_id=s["outlet_id"], name=s["name"], domains=";".join(domains),
                 kind=s["kind"], country=s["country"], notes=s["notes"])
        opinion_paths = [p for p in s["opinion_paths"].split(";") if p]
        names = []
        if s["allsides"]:
            a = as_news.get(s["allsides"])
            if a is None:
                raise SystemExit(f"{s['outlet_id']}: AllSides entry '{s['allsides']}' not found")
            used_as.add(a["allsides_name"])
            names.append(a["allsides_name"])
            r["us_lean"] = "" if a["rating"] == "Not Rated" else a["rating"]
            r["allsides_confidence"] = a["confidence"]
            r["allsides_date"] = ALLSIDES_DATE
            if a["x_handle"]:
                handles.append(a["x_handle"])
            # opinion entries on the same site (and the same path scope, if any)
            for o in as_opinion:
                if o["domain"] in hosts and not any(d.startswith(o["domain"] + "/") for d in domains):
                    used_as.add(o["allsides_name"])
                    names.append(o["allsides_name"])
                    r["us_lean_opinion"] = o["rating"]
                    if o["x_handle"]:
                        handles.append(o["x_handle"])
                    folder = [p for p in o["path"].split("/") if p][-1:] if o["path"] else []
                    for f_ in folder:
                        if f_.lower() not in OPINION_FOLDERS and f_ not in opinion_paths:
                            opinion_paths.append(f_)
        r["allsides_name"] = "; ".join(names)
        r["opinion_paths"] = ";".join(opinion_paths)
        seen, xh = set(), []
        for h in handles:
            if h.lower() not in seen:
                seen.add(h.lower())
                xh.append(h)
        r["x_handles"] = ";".join(xh)
        if s["kind"] != "platform":
            rd = s["rel_domain"] or next((h for h in hosts if h in lin), "")
            if rd and rd in lin:
                r["reliability"] = f"{lin[rd]:.3f}"
                r["reliability_domain"] = rd
                others = {h: lin[h] for h in hosts if h in lin and h != rd
                          and abs(lin[h] - lin[rd]) >= 0.1}
                if others and not s["review"]:
                    s["review"] = "Lin domain choice: " + ", ".join(f"{h} {v:.2f}" for h, v in others.items())
        qid = next((wd[h]["qid"] for h in hosts if h in wd and wd[h]["qid"]), "")
        r["wikidata"] = qid
        if s["smm_id"]:
            e = smm[s["smm_id"]]
            code = e["class_2026"]
            r["state_media"] = SMM_LEVEL[code]
            r["state_media_entity"] = f"{e['entity']} ({s['smm_id']})"
            r["state_media_year"] = "2026"
        rows.append(r)
        if s["review"]:
            review.append((r, s["review"]))

    unused = [n for n in as_news if n not in used_as] + \
             [o["allsides_name"] for o in as_opinion if o["allsides_name"] not in used_as]
    with open(paths.OUTLETS_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)

    with open(paths.SIDE_LISTS_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["side_id", "label", "outlet_ids"])
        w.writeheader()
        w.writerows(side_seed.sides())

    write_review(rows, review, unused)
    kinds = Counter(r["kind"] for r in rows)
    print(f"outlets.csv: {len(rows)} rows {dict(kinds)}; review flags: {len(review)}; "
          f"AllSides entries unused: {unused}")


def short(r):
    lean = r["us_lean"] or "-"
    if r["us_lean_opinion"]:
        lean += f" (opinion {r['us_lean_opinion']})"
    sm = r["state_media"] or "-"
    return (f"`{r['outlet_id']}` {r['name']} | {r['domains']} | {r['country'] or '-'} | {r['kind']} | "
            f"{lean} | {r['reliability'] or '-'} | {sm}")


def write_review(rows, review, unused):
    by_country = {}
    for r in rows:
        by_country.setdefault(r["country"] or "(platforms)", []).append(r)
    L = ["# outlets.csv: review list (built Nov 24)", "",
         "Every row needs one human check. Start with the flagged rows, then skim the table by "
         "country. Edit outlets.csv directly; it is the source of truth from now on.", "",
         f"{len(rows)} rows. Columns below: id, name | domains | country (point of view) | kind | "
         "AllSides lean | Lin reliability | State Media Monitor level.", "",
         "## 1. Rows with a judgment call", ""]
    for r, why in review:
        L.append(f"- **{why}** — {short(r)}")
    L += ["", "## 2. State Media Monitor matches (entity chosen by hand from smm_2026.csv)", ""]
    for r in rows:
        if r["state_media"]:
            L.append(f"- `{r['outlet_id']}` {r['name']} → {r['state_media_entity']}: {r['state_media']}")
    L += ["", "## 3. AllSides", "",
          "Every lean comes from the 79 pages read on Nov 24; each page lists the outlet's website, "
          "and all name-to-domain matches were confirmed against it then. Not used for any row: "
          + (", ".join(unused) or "none") + ".", "",
          "## 4. Side lists for the test stories (side_lists.csv)", "",
          "From the drafted sides in answer_sheets_v1.md, taken as they are. US lens sides are "
          "derived in code from country US + AllSides lean.", ""]
    for s in side_seed.sides():
        L.append(f"- `{s['side_id']}` {s['label']}: {s['outlet_ids'].replace(';', ', ')}")
    L += ["", "## 5. Every row, by country", ""]
    for c in sorted(by_country):
        L.append(f"### {c}")
        for r in by_country[c]:
            L.append(f"- {short(r)}")
        L.append("")
    (paths.OUTLETS_CSV.parent / "REVIEW.md").write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    main(force="--force" in sys.argv)
