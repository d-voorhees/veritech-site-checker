# Security hardening

This complements `docs/threat-model.md` (what the system defends against
and why) with concrete configuration and operational hardening — what's
already in place, and what to add before scaling past an MVP.

## Already in place

- **TLS everywhere in production.** Fly terminates TLS at its edge for the
  web/API Machine (`force_https = true` in `fly.toml`); Fly-issued
  certificates are automatic.
- **No unnecessary public surface.** Only the web/API Machine's
  `http_service` is publicly reachable. Scan-runner Machines listen for no
  inbound traffic at all — they're pure outbound (to Postgres and the scan
  target) and are destroyed after one scan (`config.auto_destroy`). The
  database is reached only from within the Fly private network (Fly
  Postgres) or over a TLS connection to an external managed provider — it
  is never exposed to the public internet.
- **`FLY_API_TOKEN` is server-side only.** It's read exclusively by
  `app/services/fly_machines.py` inside the API process; it is never sent
  to the browser and has no `NEXT_PUBLIC_` counterpart.
- **Password hashing** via `bcrypt` (`app/security/passwords.py`), never
  plaintext or reversible encryption.
- **JWT sessions** delivered as `httponly`, `samesite=lax` cookies
  (`secure=true` in production — `app/api/v1/auth.py`), not exposed to
  client-side JavaScript.
- **Ownership checks on every scan-scoped endpoint** — see
  `docs/threat-model.md`'s "User / data isolation" section.
- **Rate limiting on scan creation** (Postgres-backed — see
  `docs/threat-model.md`) to prevent the app being used as a bulk/anonymous
  scanning tool.
- **Duplicate-runner protection.** A scan-runner atomically claims its scan
  before doing any work, so a retried or duplicated Machine invocation
  can't double-process a scan or corrupt its state.
- **Secrets never committed**: `.env` and any `.env.*` files are
  `.gitignore`d; production secrets live only in `flyctl secrets` (which
  Fly stores encrypted and injects as environment variables at runtime —
  see `docs/fly-deployment.md`).

## Recommended before handling real client engagement data

1. **Database backups.** If using Fly's managed Postgres, confirm its
   automatic snapshot/backup policy meets your retention needs before
   storing real client data; if using an external managed Postgres
   provider, use its backup mechanism. See `docs/fly-operations.md`.
2. **Stronger authorization-attestation verification.** The MVP relies on a
   logged self-attestation checkbox. A meaningful next step is a
   domain-ownership challenge (DNS TXT record or well-known file, similar to
   ACME) before a scan against a new domain is allowed to proceed —
   especially if the invite-only boundary is ever loosened.
3. **Secrets rotation.** Rotate `JWT_SECRET`, `FLY_API_TOKEN`, and database
   credentials on a schedule (`flyctl secrets set ...` — see
   `docs/fly-operations.md`'s "Rotating secrets"); a `flyctl secrets set`
   restarts affected Machines automatically to pick up the new value.
4. **Dependency scanning.** Add `pip-audit` / `npm audit` (or Dependabot) to
   CI once CI exists — none is configured yet in this MVP.
5. **Structured audit logging of scan submissions.** `scan_events` already
   gives a per-scan timeline; consider a separate immutable audit log for
   "who submitted a scan against which domain and when" if this product
   needs to answer authorization disputes later.
6. **Multi-factor authentication** for admin accounts once the user base
   grows beyond a small invite list.
7. **Content-Security-Policy on the web app itself.** The Next.js app
   doesn't currently set its own CSP. Given the app has no third-party
   scripts and a small, known API surface, a strict CSP
   (`default-src 'self'`) is a reasonable low-risk addition — track this
   alongside the `missing_csp` rule this product itself flags on *scanned*
   sites (see `docs/rules-engine.md`) for consistency.
8. **Full `robots.txt` enforcement**, if the product's scope ever expands
   beyond "records robots.txt as evidence" — see the explicit non-goal in
   `docs/threat-model.md`.
9. **Fly Machines API token scope.** Use a deploy-scoped or app-scoped Fly
   API token for `FLY_API_TOKEN` (not a full personal/org token) so a
   compromised API process can only manage Machines on this one app.

## Reporting a vulnerability

This is an internal MVP without a public bug bounty. If you find a security
issue in this codebase, report it directly to the maintainers rather than
opening a public GitHub issue.
