# syntax=docker/dockerfile:1
# Veritech Scan — two production images for Fly.io, built from one
# Dockerfile (see scripts/entrypoint.sh for the runtime role dispatch):
#
#   web          Chromium-free. Next.js + FastAPI, autostop/autostart on
#                Fly. This is the DEFAULT build target (last stage in this
#                file) — `fly deploy` / `docker build` with no --target
#                builds this one. Cold-start latency on this Machine is
#                user-facing, so it's kept as small/simple as possible.
#   scan-runner  Adds Playwright/Chromium on top of the same base. One-off
#                Fly Machine per scan, created via the Fly Machines API —
#                see apps/api/app/services/fly_machines.py. Built with
#                `--build-target scan-runner` (scripts/deploy-fly.sh does
#                this after the default web build) and referenced
#                explicitly by tag in scan_orchestrator.py's
#                _current_image_ref() — it is NOT the image the web
#                Machine runs, so it can't be picked up via FLY_IMAGE_REF.
#
# Both images share one requirements.txt (installing the small `playwright`
# pip package everywhere is cheap — see the runtime-base stage comment
# below); only the `scan-runner` stage pays for the actual Chromium
# download and its OS-level shared-library dependencies.
#
# Built via `fly deploy --remote-only` (scripts/deploy-fly.sh) — no local
# Docker required. All base images have official linux/amd64 and
# linux/arm64 variants, and `playwright install --with-deps chromium`
# supports arm64.

# ---------------------------------------------------------------------------
# Stage 1: build the Next.js frontend (standalone output)
# ---------------------------------------------------------------------------
FROM node:22-bookworm-slim AS web-builder
WORKDIR /build/web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web ./
# next.config.mjs's rewrites() (which proxies /api/* and /health to the API
# process) is resolved ONCE at build time and frozen into
# .next/routes-manifest.json — Next.js does not re-read next.config.mjs at
# server start. This must be set here, at build time, matching the value
# scripts/entrypoint.sh sets at runtime (both processes always share one
# Machine, so this is a fixed value, not a real per-deploy secret).
ENV API_INTERNAL_URL=http://127.0.0.1:8000
RUN npm run build

# ---------------------------------------------------------------------------
# Stage 2: runtime-base — Python + Node.js runtime (for the standalone
# Next.js server), everything both the `web` and `scan-runner` images need.
# Deliberately Chromium-free: that's added only in the `scan-runner` stage
# below, which FROMs this one. `browser_render.py`/`worker_check.py` (the
# only modules that actually import Playwright) are never imported by the
# web app's code path (app.main), so a Chromium-free web image needs no
# code changes — see the collectors/ import graph if you're re-verifying
# this after a refactor.
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime-base

# Node.js runtime (only the binary is needed — the standalone Next.js build
# already bundles its own pruned node_modules, so no npm install here).
# git is needed below to resolve the private veritech-scan-rules dependency
# (a git+https:// URL in requirements.txt) — not present in the base image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates gnupg git \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY apps/api/requirements.txt ./apps/api/requirements.txt
# requirements.txt pulls in the private veritech-scan-rules package over
# plain https:// (no credential in the URL, safe in a public repo — see
# docs/rules-engine.md). Resolving it here needs a token, supplied only as
# a BuildKit secret (`fly deploy --build-secret rules_token=...` /
# `docker build --secret id=rules_token,env=RULES_REPO_TOKEN`) so it's
# never written into an image layer. The git-config rewrite and its
# `--unset` both happen inside this one RUN, so even though `git config
# --global` touches a real file (~/.gitconfig, not the secret's tmpfs
# mount), that file is back to having no credential in it by the time this
# layer is committed.
RUN --mount=type=secret,id=rules_token \
    git config --global url."https://x-access-token:$(cat /run/secrets/rules_token)@github.com/".insteadOf "https://github.com/" \
    && pip install --no-cache-dir -r apps/api/requirements.txt \
    && git config --global --unset url."https://x-access-token:$(cat /run/secrets/rules_token)@github.com/".insteadOf

COPY apps/api ./apps/api

# Next.js standalone output: server.js + a pruned node_modules, then static
# assets and public/ layered back on top (standalone output excludes them
# by design — see Next.js docs on `output: "standalone"`).
COPY --from=web-builder /build/web/.next/standalone ./apps/web
COPY --from=web-builder /build/web/.next/static ./apps/web/.next/static
COPY --from=web-builder /build/web/public ./apps/web/public

COPY scripts/entrypoint.sh ./scripts/entrypoint.sh
RUN chmod +x ./scripts/entrypoint.sh

ENV PYTHONPATH=/app/apps/api
ENV APP_ENV=production
ENV PORT=8080

EXPOSE 8080

ENTRYPOINT ["/app/scripts/entrypoint.sh"]
CMD ["web"]

# ---------------------------------------------------------------------------
# Stage 3: scan-runner — adds Chromium on top of runtime-base. Not the
# default build target; built explicitly (see top-of-file comment).
#
# Deliberately installed directly in the image that runs it, not copied in
# from elsewhere: `playwright install --with-deps` apt-installs Chromium's
# shared-library dependencies (libnss3, libatk-bridge2.0-0, libgtk-3-0,
# libasound2, ...) system-wide (/usr/lib, /lib), not just under
# /usr/local — a COPY --from would silently miss those and Chromium would
# fail to launch at runtime.
# ---------------------------------------------------------------------------
FROM runtime-base AS scan-runner

RUN python -m playwright install --with-deps chromium

# Fail the build loudly if Chromium can't launch on this image, rather than
# discovering it at first scan.
RUN cd apps/api && python -m app.worker_check --startup-only

CMD ["scan-runner"]

# ---------------------------------------------------------------------------
# Stage 4: web — the default build target (see top-of-file comment). No
# additional layers of its own: runtime-base is already Chromium-free and
# ready to serve; this stage exists only so plain `fly deploy` / `docker
# build` (no --target) lands on the lean image rather than needing every
# caller to know to pass one.
# ---------------------------------------------------------------------------
FROM runtime-base AS web
