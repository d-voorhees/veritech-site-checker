# @veritech-scan/shared

Cross-cutting TypeScript constants and types shared across Veritech Scan's
TypeScript apps (currently `apps/web`; a future admin or CLI tool would use
it too). This is the designated seam for anything that must stay in sync
with the backend contract defined in `apps/api/app/schemas/` and
`apps/api/app/models/` — severities, confidence levels, scan statuses,
evidence categories, and the exact authorization acknowledgment text.

## Current consumption

`apps/web` builds and runs standalone (`npm ci && npm run build` inside
`apps/web/`, per the `web-builder` stage in the root `Dockerfile`) and does
not currently import this package through an npm workspace symlink, to keep
that build self-contained and already-validated. The handful of values it
needs (the authorization text, max-page options) are duplicated locally in
`apps/web/src/lib` and `apps/web/src/app/scans/new/page.tsx` with comments
pointing back here.

## Intended follow-up

Wire this package into `apps/web` properly via npm workspaces:

1. Add a root `package.json` with `"workspaces": ["apps/web", "packages/shared"]`.
2. Update the `Dockerfile`'s `web-builder` stage to run `npm ci` /
   `npm run build` from the repo root instead of `apps/web`, so the
   workspace symlink resolves.
3. Replace the duplicated constants in `apps/web` with
   `import { AUTHORIZATION_ACKNOWLEDGMENT_TEXT } from "@veritech-scan/shared"`.

Once the backend generates an OpenAPI-derived TypeScript client (e.g. via
`openapi-typescript`), the request/response types in `apps/web/src/lib/api.ts`
should move here too, so both API route changes and frontend types are
reviewed together.
