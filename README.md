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

Keys come from the macOS Keychain (or an upper-case environment variable of the same name):
`tavily_api_key`, `guardian_api_key`, `anthropic_api_key`, `langfuse_public_key`,
`langfuse_secret_key` (optional `langfuse_host`). Vertex models use Application Default
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

## Common commands

```bash
.venv/bin/python -m scripts.smoke_models                       # costs a few cents
.venv/bin/python -m scripts.freeze_fixtures --dry-run          # plan and credit estimate, free
.venv/bin/python -m scripts.freeze_fixtures --writer model     # the real run (cap: 400 credits)
.venv/bin/python -m scripts.coverage_report
.venv/bin/python build/build_outlets.py --force                # rebuild outlets.csv from the seed
```

Every Tavily and Guardian response is saved under `stringer_private/frozen/raw/`, so re-running a
story, or resuming a run that stopped, only pays for what is missing.

## Credits

Media bias ratings by AllSides.com (CC BY-NC 4.0). State Media Monitor 2026, MJRC (CC BY 4.0).
Domain reliability from Lin et al. 2023, PNAS Nexus. Events by Monitor the Situation.
