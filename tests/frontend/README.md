# tests/frontend

No frontend test runner is configured yet for `apps/web`. `make test` runs
`npm run test --if-present` in the web container, which no-ops safely today.

The frontend is currently verified via:

- `npm run build` (production build, including Next's own type checking)
- `npm run lint` (eslint)
- `npx tsc --noEmit` (strict TypeScript)
- Manual verification of the golden path (sign in → new scan → status
  polling → report → finding detail → HTML export) against a running API.

The required backend-side guarantees (SSRF protection, crawl limits, rules
engine, scan ownership, partial-completion handling, etc.) are covered in
`tests/backend/` — see the root README's Testing section.

If component-level frontend tests are added later, Vitest + React Testing
Library is a natural fit given this is a Next.js App Router + TanStack Query
codebase; add it here with a `vitest.config.ts` and wire `npm run test` in
`apps/web/package.json` to actually run it.
