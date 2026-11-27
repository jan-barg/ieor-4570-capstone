# Stringer on Cloud Run: one image for the test website and the per-video job (decided Nov 27, Jan).
# Python 3.12 runs the pipeline; Node 22 + headless Chrome run module 8's Remotion render; ffmpeg sets
# loudness and writes the poster. The private files the code needs (outlet table, map shapes, music,
# portrait photos) are NOT in this public repo: Cloud Build copies them from the private bucket into
# private/ before `docker build` (cloudbuild.yaml), and the image keeps them at /private.
FROM node:22-bookworm-slim AS node

FROM python:3.12-slim-bookworm

# Node from the official image (npm and npx included).
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

# Libraries headless Chrome needs on Debian (Remotion's Docker guide, as in the render test), plus ffmpeg.
RUN apt-get update && apt-get install -y --no-install-recommends \
      libnss3 libdbus-1-3 libatk1.0-0 libgbm-dev libasound2 libxrandr2 libxkbcommon-dev \
      libxfixes3 libxcomposite1 libxdamage1 libatk-bridge2.0-0 libpango-1.0-0 libcairo2 libcups2 \
      ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
# LITELLM_LOCAL_MODEL_COST_MAP: LiteLLM uses its built-in price list instead of fetching one from GitHub
# when it is first loaded (a network call in every video's first seconds). Prices come from config/models.toml.
ENV PYTHONUNBUFFERED=1 STRINGER_PRIVATE=/private LITELLM_LOCAL_MODEL_COST_MAP=True

# Dependencies first, so a code change doesn't reinstall them.
COPY render/package.json render/package-lock.json render/
RUN cd render && npm ci --no-audit --no-fund && npx remotion browser ensure
# The list comes from pyproject.toml itself, so a dependency added there reaches the image (it used to be
# repeated here by hand, and the package below is installed with --no-deps).
COPY pyproject.toml ./
RUN python -c "import tomllib; print(*tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies'], sep=chr(10))" > /tmp/requirements.txt \
 && pip install --no-cache-dir -r /tmp/requirements.txt

COPY render render
# Bundle the drawing code once here, so each video job skips it (render.mjs reuses a bundle whose files match).
RUN cd render && node render.mjs bundle
COPY stringer stringer
COPY scripts scripts
COPY config config
COPY web web
RUN pip install --no-cache-dir --no-deps -e .
COPY private /private

# Cloud Run sets PORT for the website; the job overrides the command (see cloudbuild.yaml).
CMD ["sh", "-c", "exec python -m web.server --port ${PORT:-8080}"]
