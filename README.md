# Stringer: code

Stringer turns a Monitor the Situation event into a sourced, balance-checked 60-second explainer.
This folder is code only. Every piece of data (the Archive, outlets.csv, article text, API
responses, logs) lives in `../stringer_private/` (or wherever `STRINGER_PRIVATE` points), which must
never go into a public repo: Monitor the Situation's terms forbid republishing its data.
Events by Monitor the Situation (monitor-the-situation.com).

The design is in `../STRINGER_SYSTEM_MAP.md`. Built so far: module 0 (the Gate), modules 1 to 8 (Gather
through the finished video), the one-event runner, the shared model layer, the shared eval runner and a
test website on Cloud Run. Still to build: module 9 (the real front page and gallery).

## Setup

```bash
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest -q          # offline (tests/conftest.py turns Langfuse and the call log off); needs outlets.csv in stringer_private
cd render && npm ci && cd ..           # module 8's drawing code (Remotion, headless Chrome); also needs ffmpeg
```

Module 8 also needs its private assets in `stringer_private/video_assets/`: the map shapes (`geo/`),
the music bed (`music/`) and the portrait photos (`people/`).

Keys go in `.env` (git-ignored; copy `.env.example`, which lists every name): `MTS_API_KEY` (the event
feed), `TAVILY_API_KEY`, `GUARDIAN_API_KEY`, `ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY` (the script writer
runs on it, so every video needs it), `ELEVENLABS_API_KEY` (module 8's narrator), `LANGFUSE_PUBLIC_KEY`,
`LANGFUSE_SECRET_KEY` (optional `LANGFUSE_HOST`). A real environment variable wins over the file; the macOS
Keychain is a fallback on a Mac. Vertex models use Application Default Credentials: project
`agentic-ai-msds` on the Mac, and on Cloud Run the project `STRINGER_VERTEX_PROJECT` names.

## Layout

| Path | What it is |
|---|---|
| `stringer/outlets.py` | Module 3: a link → outlet, lean (AllSides), reliability (Lin et al.), kind, country, state-media level, news or opinion |
| `build/` | Builds `outlets.csv`, `side_lists.csv` and `REVIEW.md` from the hand seed plus AllSides, Lin et al., Wikidata and the State Media Monitor |
| `config/models.toml` | Which model each step uses, and every model's prices |
| `stringer/models.py` | One `complete()` for every model (LiteLLM), with prompt-cache marks, token and cost accounting |
| `stringer/tracing.py` | Logs every call to Langfuse (when keys exist) and to `runs/calls-*.jsonl` (no prompt text) |
| `stringer/events.py`, `stringer/feed.py` | Events from the Archive, the fixture list and the live `/v1/events` feed |
| `stringer/gate/`, `config/gate.toml`, `scripts/gate_admin.py` | Module 0, the Gate: which events may become videos (`rules.py`, `policy.py`), whether one can start now (limits, Tavily and voice credits, a cost estimate: `core.py`, `cost.py`, `credits.py`), the shared records (`store.py`), reports and take-downs, and Jan's admin commands |
| `stringer/pipeline.py`, `scripts/run_event.py` | One live event end to end: modules 1 to 8 with each step timed, charged to the Gate's ticket and traced as one Langfuse trace |
| `web/server.py`, `scripts/run_job.py`, `stringer/cloud.py` | The test website, the Cloud Run job that makes one video per click, and the Cloud Storage and job calls they use |
| `stringer/gather/` | Module 1: the query plan (`plan.py`), query writing (`queries.py`), Tavily and Guardian clients with a credit budget (`clients.py`), merging and dating (`merge.py`), the frozen layout and shared article cache (`store.py`), one event end to end (`run.py`) |
| `scripts/smoke_models.py` | Checks every shortlisted model answers and reports cached tokens |
| `scripts/freeze_fixtures.py` | Runs Gather on the 40 test stories, with a credit check and a hard cap |
| `scripts/coverage_report.py` | Module 3's eval and module 1's proxy measures on the frozen stories |
| `stringer/pick.py`, `scripts/pick_articles.py` | Picks the (at most) 10 balanced articles the later steps read; writes `picked.json` per story |
| `stringer/same_story.py`, `scripts/filter_articles.py` | Module 2: marks each article same story / follow-up / different (pick skips "different"); writes `verdict` into `articles.jsonl` and `same_story.json` per story |
| `stringer/lens.py`, `stringer/balance.py`, `scripts/gather_live.py`, `scripts/balance_followup.py` | Module 4: chooses a live story's two sides (or none), then runs one follow-up search round when a side comes up short |
| `stringer/clean.py` | Strips site menus from article text by code, and spots wire copies (8-word runs) |
| `stringer/brief_read.py`, `brief_merge.py`, `brief_sides.py`, `brief_blind.py`, `brief_framing.py`, `story_file.py`, `story_brief.py`, `scripts/build_story_files.py` | Module 5: the Story File (news brief). Reads each article into fact cards, merges them into claims, adds sides, blindspots and flags, and says how each side tells it. `brief_onecall.py` is the one-call baseline it beats |
| `stringer/fact_check.py`, `scripts/check_story_files.py` | Module 6: the fact check. Gives every claim a verdict and writes `checked_story_file.json` |
| `stringer/script_writer.py`, `stringer/shots.py`, `config/shot_catalog.json`, `scripts/write_scripts.py` | Module 7: the 60-second script, beat by beat, every line citing its claims. `shots.py` holds the shot catalog and the checks modules 7 and 8 share |
| `stringer/video/`, `scripts/make_videos.py` | Module 8: a script in, a vertical MP4 out. Checks the script, adds voice directions, records the ElevenLabs voice with its timings, finds places and portraits, builds the render plan, renders, then sets loudness and writes the poster and captions (`make.py` runs the steps in order) |
| `render/` | Module 8's drawing code (Remotion): every shot kind, the maps and the props. `render.mjs` draws a render plan into an MP4 |
| `scripts/eval_video.py`, `stringer/video/evals.py` | Module 8's evals and their visual report |
| `stringer/animation/`, `render/anim/`, `render/src/anim.js`, `scripts/animation_ab.py` | The custom animation, off by default: one beat gets a short paper-cutout animation drawn by a model with the scene kit, in a window under its words. The model's code runs in a locked box (its own headless Chrome, no network, no eval, no page) that hands back JPEG frames. `animation_ab.py` makes A/B videos and their report |
| `scripts/build_video_places.py`, `scripts/count_people.py`, `scripts/fetch_portraits.py` | One-time builds for module 8: the place index from the map files, the list of people to draw, and their photos |
| `stringer/evals/` | The shared eval runner: runs a step on the frozen stories with a chosen model, scores it against an answer key, caches every model answer, hard cost cap, one Langfuse trace per run, a visual report per step (`report.py`). One plug-in per step, listed in `steps.py` |
| `tests/` | Offline tests on made-up data |
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
# build/build_outlets.py --force rebuilds outlets.csv and side_lists.csv from the seed. Don't run it for now:
# the seed predates the Nov 24 hand review, so it would undo that review on 13 outlets and one side list.
.venv/bin/python -m scripts.gather_live --list                 # live events with 5+ reports, free
.venv/bin/python -m scripts.gather_live --event <id> --dry-run # the sides plus a credit estimate, a fraction of a cent
.venv/bin/python -m scripts.build_story_files live --only <id> --cap <usd>   # module 5 on one story, paid
.venv/bin/python -m scripts.check_story_files run --only <id> --cap <usd>    # module 6, paid
.venv/bin/python -m scripts.write_scripts estimate --only <id>               # module 7's cost, free
.venv/bin/python -m scripts.write_scripts run --only <id> --cap <usd>        # module 7, paid
.venv/bin/python scripts/make_videos.py <id8>                  # module 8: ElevenLabs credits, video in the story's video/
.venv/bin/python scripts/make_videos.py --voice paced --plan-only   # every story, silent stand-in voice, plans only, free
.venv/bin/python scripts/eval_video.py --no-layout --broken-renders 0   # module 8's code checks, about a minute
```

Every Tavily and Guardian response is saved under `stringer_private/frozen/raw/`, so re-running a
story, or resuming a run that stopped, only pays for what is missing.

Eval results, the model-answer cache and the reports are in `stringer_private/evals/`. A model call
already made in an eval is free the next time, so applying the chosen setup to all stories after
its eval costs nothing. `remerge_frozen` rewrites `articles.jsonl`, so run
`filter_articles --reapply` and then `pick_articles` after it.

## The custom animation (off by default)

With `STRINGER_ANIMATION=1` in the environment, module 8 gives one beat of each video a model-drawn animation
(design: the Nov 27 test rounds). Once the script is checked, its storyboard (Haiku) reads the beats a window fits
under, picks one and plans what that beat's sentence tells; the drawing (Sonnet) and a small call tying each cue to
a spoken word run beside the voice, and once the voice is recorded the drawing's code runs in the box at the beat's
exact length. The writer's prompt never changes. Anything that goes wrong (no beat a window fits under, no
storyboard, refused or failing or slow code, a drawing not ready 40 s after the voice) leaves the beat its normal
shot, and `video/animation.json` says why. `STRINGER_ANIMATION_FRAME=card` (default) or `plate` picks the window's
look. About 4-9 cents a video; with no beat a window fits under, nothing is paid.

```bash
STRINGER_ANIMATION=1 .venv/bin/python scripts/make_videos.py <id8>     # one video with the animation (paid)
.venv/bin/python scripts/animation_ab.py <id8> ... --out <folder> --judge   # A/B videos, side by side, report page (paid once, then cached)
```

## Transitions between beats (on by default)

Module 8 draws the mix (`stringer/video/transitions.py`; Jan's OK, Nov 28): a tear out of the hook, a sheet
sliding in for the sides card, a push from map to map, a dissolve where a map and a card meet and into the sources
card, and cuts between cards. Each change starts a third of its length before the next line's first word. Free: code
decides, the renderer draws it. `STRINGER_TRANSITIONS=off` makes every change a cut, as before; a kind's name
(`dissolve`, `slide`, `push`, `tear`, `wipe`) puts that kind at every change.

```bash
STRINGER_TRANSITIONS=off .venv/bin/python scripts/make_videos.py <id8>     # cuts only
.venv/bin/python scripts/transitions_demo.py --ab <A/B folder> --out <folder> --stories <id8>,... --kinds-story <id8>   # saved videos drawn again, nothing paid
```

## One live event, end to end

`stringer/pipeline.py` runs modules 1–8 for one event after the Gate says go, timing each step and
charging every model call, Tavily credit and ElevenLabs credit to the Gate's ticket (the cost check
runs after the searches). The whole video is one Langfuse trace, with one span per step. After the merge
call the last Story File calls and the fact check's model run side by side. A run ends as done, as
"no video" (a judgment about the story, final), or as failed (a crash or a model that gave no answer,
which a later click may try again). `scripts/run_event.py` is its command:

```bash
.venv/bin/python -m scripts.run_event --list          # eligible events in the live feed now, free
.venv/bin/python -m scripts.run_event <id8>           # the Gate, then modules 1-8; $0.12-0.22 on Nov 27 (the Gate's estimate is $0.66)
```

## Deploy (Cloud Run, agentic-ai-capstone-jgb2170)

One image (`Dockerfile`) serves two things: the website (`web/server.py`; for now a test page, to be
replaced by module 9) and the Cloud Run job that makes one video per click (`scripts/run_job.py`).
A push to `main` runs `cloudbuild.yaml` through a Cloud Build trigger: it copies the private files from
the private bucket, builds the image, and points the website and the job at it. Finished videos and
posters go to a private video bucket (`videos/<event>/<ticket>/`), and the website streams them to
signed-in Columbia accounts at `/media/...`. Each event's story files go to the private bucket at
`stories/<event>/` after every run, also a failed or "no video" one; a later run of the same event
overwrites them. The Gate's records are in the private bucket too (`GATE_STORE=gs://<private bucket>/gate`).
Keys come from Secret Manager as environment variables. `cloudbuild.yaml` only swaps the image: the
website's and the job's own settings were made by hand with the commands below.

Set up once (done Nov 27):

```bash
gcloud storage cp -r <the private files> gs://agentic-ai-capstone-jgb2170-private/deploy/   # outlets/, video_assets/{geo,music,people}
.venv/bin/python -m scripts.push_secrets      # the keys into Secret Manager; prints names only
gcloud run deploy stringer-web ... --min-instances 1 --set-env-vars ... --set-secrets ...   # the website
gcloud run jobs create stringer-make ... --command python,-m,scripts.run_job --cpu 8 --memory 16Gi --task-timeout 25m --max-retries 0
```

Both get the same settings: `GATE_STORE`, `STRINGER_PROJECT`, `STRINGER_REGION`, `STRINGER_JOB`,
`STRINGER_VIDEO_BUCKET`, `STRINGER_PRIVATE_BUCKET`, `STRINGER_VERTEX_PROJECT`, and every key as a
secret. A build from this folder without the trigger: `gcloud builds submit --config cloudbuild.yaml
--substitutions COMMIT_SHA=$(git rev-parse HEAD)` (`.gcloudignore` keeps `.env` and data out).

## Credits

Media bias ratings by AllSides.com (CC BY-NC 4.0). State Media Monitor 2026, MJRC (CC BY 4.0).
Domain reliability from Lin et al. 2023, PNAS Nexus. Events by Monitor the Situation.
Maps from Natural Earth (public domain) and GeoNames (CC BY 4.0). Portrait photos from Wikimedia
Commons, each credited on the video's sources card. Fonts: Inter and Source Serif 4 (SIL OFL,
licenses in `render/public/fonts/`).
