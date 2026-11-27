# Nexus

Nexus is a local-first business management system with a Python HTTP server, a SQLite database by default, and a browser-based workspace UI. It covers core business workflows (projects, tasks, procurement, finance, documents, people, meetings, audit) with tenant isolation, role-based access control, and append-only audit/ledger records.

> **Status:** working local application / engineering MVP. It is not a certified, hosted, or fully hardened enterprise SaaS. See [PRODUCTION-COMPARISON.md](PRODUCTION-COMPARISON.md) and [VERIFICATION.md](VERIFICATION.md).

## What Nexus Does

| Area | Capability |
|---|---|
| Identity & RBAC | Workspace registration, password hashing (PBKDF2-SHA256), expiring sessions, CSRF/origin checks, invitations, multi-workspace membership, per-org roles (`admin`, `manager`, `finance`, `member`, `viewer`) |
| Tenant isolation | Session-bound `org_id`; org-scoped queries; membership/role resolved per request; cross-org access denied |
| Projects & Tasks | Shared/private projects, membership, task assignment/status/priority/due dates, source-message traceability |
| Procurement | Draft → submit → independent review → purchase order; requester cannot self-approve; duplicate/order transitions guarded |
| Finance | Draft/issue/payment/void invoice lifecycle; balanced double-entry ledger; immutable ledger entries/lines; no duplicate posting |
| Documents | Upload, versioning, preview/download, metadata, linked records, archive/restore; optional upload scan hook |
| Connect | Channels, direct/project conversations, replies, reactions, pins, mentions, read receipts, edit/remove window, attachments |
| Audit & Integrity | Append-only audit log, immutable ledger/document/workflow history, request IDs in responses and audit details |
| Operations | Customers, suppliers, products, stock movements, assets, contracts, meetings, notifications |
| AI (optional) | Provider adapter for chat-completion-compatible endpoint; no provider contacted by default; scoped context disclosure |

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11+, standard library HTTP server (`ThreadingHTTPServer`, `BaseHTTPRequestHandler`) |
| Default DB | SQLite (WAL, foreign keys, busy timeout, `BEGIN IMMEDIATE` for writes) |
| RDBMS target | PostgreSQL 17+ via `db.py` abstraction; `schema.postgres.sql`; `psycopg`/`psycopg2` driver |
| Frontend | Vanilla HTML/CSS/JS (`web/`), accessibility-oriented UI, PDF.js vendor bundle for preview |
| Auth/Security | PBKDF2-SHA256 passwords, HttpOnly SameSite=Strict session cookie, CSRF token, origin/Sec-Fetch-Site checks, CSP/security headers, rate limiting, idempotency keys |
| Tests | `unittest` integration tests against real HTTP server + temp SQLite/Postgres DBs; security/fuzz/concurrency tests |

## Repository Layout

```text
.
├── server.py                     # HTTP API, auth, dispatch, business endpoints
├── db.py                         # SQLite/Postgres abstraction, tx/placeholder compatibility
├── business.py                   # Shared business rules/helpers
├── workflows.py                  # Automation/workflow engine
├── document_store.py             # Document upload/versioning/authorization
├── ai_gateway.py                 # Optional AI provider adapter
├── demo_data.py / exports.py     # Demo seed and CSV exports
├── manage.py                     # check/backup utilities
├── migrate_sqlite_to_postgres.py # SQLite -> Postgres migration + fidelity verification
├── schema.sql                    # SQLite schema (default)
├── schema.postgres.sql           # PostgreSQL schema (migration target)
├── test_matrix.py                # Run test suite on SQLite and/or Postgres
├── tests/                        # Integration + security/concurrency tests
├── web/                          # Browser UI (index, app, styles, vendor/pdfjs)
├── planning/                     # Product/spec planning docs
└── PRODUCTION-COMPARISON.md      # Known gaps vs production systems
```

## Quick Start (SQLite, default)

### Prerequisites
- Python 3.11+
- No Python package install required for SQLite mode

### Run

```powershell
python launcher.py
```

Or on Windows, double-click `Start Nexus.cmd`.

- Default URL: `http://127.0.0.1:4180`
- Default DB: `data/nexus.sqlite3` (override with `NEXUS_DB`)
- Create a workspace on first run. No default passwords.

### PostgreSQL mode

```powershell
pip install "psycopg[binary]"
$env:NEXUS_DATABASE_URL="postgresql://user:pass@localhost:5432/nexus"
python server.py --host 127.0.0.1 --port 4180
```

Postgres settings: `NEXUS_DATABASE_URL` / `NEXUS_DB_URL`, `NEXUS_PG_CONNECT_TIMEOUT`, `NEXUS_PG_STATEMENT_TIMEOUT_MS`, `NEXUS_PG_LOCK_TIMEOUT_MS`, `NEXUS_PG_IDLE_TX_TIMEOUT_MS`, `NEXUS_PG_APPNAME`.

## Engineering & Security Design

### Offline-first assistant

Nexus includes deterministic conversation digests, action candidates, draft reply
templates, recent-message search and workflow guidance with **no LLM required**.
Optional Ollama/local models and external providers are explicitly selected, never
automatic fallbacks. All modes retain company/conversation access checks and have
no business-action execution tools. See [Assistant setup and boundaries](docs/ASSISTANT.md).

For a disposable hosted test, see [Render free-plan setup](docs/RENDER.md).
Free-service SQLite storage is ephemeral: use synthetic data only.

### Tenant Isolation & RBAC
- Every authenticated request resolves identity from session + active membership in the same org.
- Service layer binds `org_id`, `user_id`, `role`; queries are org-scoped.
- Membership is composite `(org_id, user_id)` with per-org role and `active` flag.
- Workspace switch requires active membership and creates a new org-bound session.
- Deactivation revokes org sessions and blocks access immediately.

### Concurrency & Data Integrity
- **SQLite:** WAL, `busy_timeout`, `BEGIN IMMEDIATE` for writes, status guards, CAS-style `rowcount==1` checks, UNIQUE constraints, immutable triggers.
- **Postgres:** transaction wrapper + `SELECT ... FOR UPDATE` on contended invoice/requisition flows, UNIQUE constraints, trigger-based immutability.
- **Idempotency:** `Idempotency-Key` header supported for mutating requests; scoped by org+user+key; same endpoint+payload replays stored response; different endpoint/payload conflicts. UI sends stable per-action intent keys for key flows.
- **Ledger:** balanced double-entry lines; immutable entries/lines; invoice transitions guarded against duplicate posting.

### Security Controls
- CSRF token required for mutating requests + origin/Sec-Fetch-Site checks.
- Security headers: CSP, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Cache-Control`, `Permissions-Policy`, COOP/CORP, HSTS when secure cookie enabled.
- Request ID (`X-Request-ID`) returned and included in audit details for correlation.
- Auth throttling and process-local API rate limits (`NEXUS_RATE_GET`, `NEXUS_RATE_MUTATE`).
- Optional upload scan hook: `NEXUS_UPLOAD_SCAN_CMD`.

## Testing

Run SQLite (default):

```powershell
python -m unittest discover -s tests -v
```

Run SQLite + Postgres matrix:

```powershell
python test_matrix.py --postgres-url "postgresql://postgres:postgres@127.0.0.1:5432/postgres"
```

Current suite includes integration, RBAC/tenant isolation, concurrency races, idempotency, security headers, fuzz/input-boundary, and workflow tests.

## Migration: SQLite -> PostgreSQL

```powershell
python migrate_sqlite_to_postgres.py --sqlite data/nexus.sqlite3 --postgres postgresql://user:pass@localhost:5432/nexus --report migration-report.json
```

The migration script imports in FK-safe order, preserves IDs/money cents/blob data, resets sequences, and verifies row/field/blob/hash fidelity and immutability spot checks.

## Challenges Faced & Solutions

| Challenge | What was happening | Solution implemented |
|---|---|---|
| **Concurrent same-action requests** (double approve/pay/issue) | Two users could race on the same record; stale UI could resubmit | Added DB write serialization/CAS guards, `SELECT ... FOR UPDATE` on Postgres critical paths, UNIQUE constraints, and UI in-flight + conflict refresh handling |
| **Duplicate request retries** | Network retries or double-clicks could create duplicate side effects | Added `Idempotency-Key` storage/replay with org+user+key scope, payload fingerprint conflict detection, and stable UI intent keys per action |
| **Tenant/RBAC data mixing risk** | Any missing org filter could leak data across workspaces | Enforced session-bound org identity, per-request membership/role resolution, org-scoped service queries, and adversarial cross-org tests |
| **Deactivated member still appeared active** | Membership patch didn’t fully revoke access semantics | Extended `PATCH /api/people/:id` to support `active`, revoke org sessions on deactivation, block inactive identity, and audit changes |
| **SQLite/Postgres parity** | SQLite-specific SQL/types/tx behavior blocked portability | Added `db.py` abstraction, placeholder/row normalization, Postgres schema, migration script, and dual-backend test harness |
| **Operational visibility** | Hard to correlate failing requests/audit events | Added `X-Request-ID` propagation and request ID in error/audit details |
| **Abuse & upload risk** | Basic auth throttling existed; uploads lacked scan hook | Added configurable rate limits, auth throttling improvements, and optional upload scan command hook |

## Configuration Reference

| Variable | Purpose | Default |
|---|---|---|
| `NEXUS_DB` | SQLite DB path | `data/nexus.sqlite3` |
| `NEXUS_DATABASE_URL` / `NEXUS_DB_URL` | PostgreSQL connection URL | unset (SQLite) |
| `NEXUS_RATE_GET` / `NEXUS_RATE_MUTATE` | Per-IP API rate limits/min | `1200` / `600` |
| `NEXUS_IDEMPOTENCY_TTL_HOURS` | Prune old idempotency keys | `72` |
| `NEXUS_UPLOAD_SCAN_CMD` | Optional upload scan command (`{file}` placeholder) | unset |
| `NEXUS_UPLOAD_SCAN_TIMEOUT` | Upload scan timeout seconds | `20` |
| `NEXUS_SECURE_COOKIE` | Set `Secure` cookie + HSTS | unset |
| `NEXUS_ALLOWED_HOSTS` | Allowed hostnames for deployment | localhost only |
| `NEXUS_DISABLE_DEMO` | Disable demo workspace creation | unset |
| `NEXUS_AI_ENDPOINT` / `NEXUS_AI_MODEL` / `NEXUS_AI_API_KEY` | Optional AI provider | unset |

## Known Boundaries / Next Hardening

- No MFA/SSO/password reset/email verification.
- Process-local rate limiting; multi-instance deployments should use shared store (Redis/Postgres).
- Upload scan is hook-based; no built-in malware scanner.
- Vendored `pdfjs-dist` should be reviewed/updated on a CVE cadence.
- CSP is strict but not nonce-based; external pentest/browser XSS audit still recommended before production exposure.
- SQLite is suitable for local/single-node use; Postgres is the path for multi-node/high write concurrency.

## License / Notices

See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for bundled third-party notices (including PDF.js). Add a project license file if/when you are ready to publish under a specific license.
