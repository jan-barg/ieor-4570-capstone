# Stringer: code

Stringer turns a Monitor the Situation event into a sourced, balance-checked 60-second explainer.
This folder is code only. Every piece of data (the Archive, outlets.csv, article text, API
responses, logs) lives in `../stringer_private/` (or wherever `STRINGER_PRIVATE` points), which must
never go into a public repo: Monitor the Situation's terms forbid republishing its data.
Events by Monitor the Situation (monitor-the-situation.com).

The design is in `../STRINGER_SYSTEM_MAP.md`. Built so far: module 1 (Gather), module 3 (Outlet
labels) and the shared model layer.

## Setup

```bash
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest -q          # offline, no keys needed except outlets.csv in stringer_private
```

Keys go in `.env` (git-ignored; copy `.env.example`): `TAVILY_API_KEY`, `GUARDIAN_API_KEY`,
`ANTHROPIC_API_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` (optional `LANGFUSE_HOST`).
A real environment variable wins over the file; the macOS Keychain is a fallback. Vertex models use Application Default
Credentials on project `agentic-ai-msds` (global endpoint, `x-goog-user-project` header).

## Layout

| Path | What it is |
|---|---|
| `stringer/outlets.py` | Module 3: a link → outlet, lean (AllSides), reliability (Lin et al.), kind, country, state-media level, news or opinion |
| `build/` | Builds `outlets.csv`, `side_lists.csv` and `REVIEW.md` from the hand seed plus AllSides, Lin et al., Wikidata and the State Media Monitor |
| `config/models.toml` | Which model each step uses, and every model's prices |
| `stringer/models.py` | One `complete()` for every model (LiteLLM), with prompt-cache marks, token and cost accounting |
| `stringer/tracing.py` | Logs every call to Langfuse (when keys exist) and to `runs/calls-*.jsonl` (no prompt text) |
| `stringer/events.py` | Loads events from the Archive and the fixture list |
| `stringer/gather/` | Module 1: the query plan (`plan.py`), query writing (`queries.py`), Tavily and Guardian clients with a credit budget (`clients.py`), merging and dating (`merge.py`), the frozen layout and shared article cache (`store.py`), one event end to end (`run.py`) |
| `scripts/smoke_models.py` | Checks every shortlisted model answers and reports cached tokens |
| `scripts/freeze_fixtures.py` | Runs Gather on the 40 test stories, with a credit check and a hard cap |
| `scripts/coverage_report.py` | Module 3's eval and module 1's proxy measures on the frozen stories |
| `stringer/pick.py`, `scripts/pick_articles.py` | Picks the (at most) 10 balanced articles the later steps read; writes `picked.json` per story |
| `stringer/same_story.py`, `scripts/filter_articles.py` | Module 2: marks each article same story / follow-up / different (pick skips "different"); writes `verdict` into `articles.jsonl` and `same_story.json` per story |
| `stringer/evals/` | The shared eval runner: runs a step on the frozen stories with a chosen model, scores it against an answer key, caches every model answer, hard cost cap, one Langfuse trace per run, a visual report per step (`report.py`). Module 2's plug-in is `same_story_eval.py` |
| `scripts/run_eval.py` | The eval runner's command: `estimate`, `run`, `rescore`, `compare`, `report` |
| `scripts/build_same_story_sample.py`, `scripts/same_story_labels.py` | Module 2's answer key: the sample to label, then the labels file from the review page plus Claude's drafts and later fixes |

## Common commands

```bash
.venv/bin/python -m scripts.smoke_models                       # costs a few cents
.venv/bin/python -m scripts.freeze_fixtures --dry-run          # plan and credit estimate, free
.venv/bin/python -m scripts.freeze_fixtures --writer model     # the real run (cap: 400 credits)
.venv/bin/python -m scripts.remerge_frozen                     # rebuild frozen stories with current code, free
.venv/bin/python -m scripts.remerge_frozen --only <id> --new-searches   # also run searches added since (cap 30 credits)
.venv/bin/python -m scripts.pick_articles                      # pick 10 balanced articles per frozen story, free
.venv/bin/python -m scripts.run_eval estimate same_story --model haiku-5-5      # tokens and $ for an eval run, free
.venv/bin/python -m scripts.run_eval run same_story --model deepseek-v4.1-flash --cap 1.00   # costs money; hard cap
.venv/bin/python -m scripts.run_eval run same_story --model code:keywords      # the plain-code baseline, free
.venv/bin/python -m scripts.run_eval report same_story          # rebuild the visual report (also automatic after runs)
.venv/bin/python -m scripts.filter_articles --model deepseek-v4.1-flash --cap 0.30   # apply module 2 to every story
.venv/bin/python -m scripts.filter_articles --reapply           # after remerge_frozen: put the verdicts back, free
.venv/bin/python -m scripts.coverage_report
.venv/bin/python build/build_outlets.py --force                # rebuild outlets.csv from the seed
```

Every Tavily and Guardian response is saved under `stringer_private/frozen/raw/`, so re-running a
story, or resuming a run that stopped, only pays for what is missing.

Eval results, the model-answer cache and the reports are in `stringer_private/evals/`. A model call
already made in an eval is free the next time, so applying the chosen setup to all stories after
its eval costs nothing. `remerge_frozen` rewrites `articles.jsonl`, so run
`filter_articles --reapply` and then `pick_articles` after it.

## Credits

Media bias ratings by AllSides.com (CC BY-NC 4.0). State Media Monitor 2026, MJRC (CC BY 4.0).
Domain reliability from Lin et al. 2023, PNAS Nexus. Events by Monitor the Situation.
