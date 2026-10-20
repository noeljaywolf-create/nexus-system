# Verification record

Local verification performed on October 19, 2026. This is developer verification of an early local application, not independent assurance.

## Automated checks

The integration suite exercises the real HTTP server with an isolated SQLite database. It covers authentication, CSRF/origin/host checks, tenant and private-record access, role changes, invitations, conversations, message history and attachments, purchasing decisions and concurrent approval, stock constraints, balanced invoice issue/payment/reversal, append-only audit/journals, meetings, assets, contracts, extensions and the optional AI transport boundary.

Added coverage includes document signature/format validation, immutable versions and concurrent retry protection, download permissions after revocation, linked finance records, archive/restore, canonical record IDs, malformed field types, isolated/idempotent seed data and authenticated CSV export with formula escaping. See tests/test_system.py and the final run result below.

## Browser evidence

Checked a separate synthetic Meridian Group workspace: real dashboard data; document grid/folders; simultaneous PDF and CSV uploads; a second PDF version and saved revision note; local PDF.js page rendering; archive and restore; task pagination and text filtering; a saved task status change; and a real server-backed CSV download event. Show password revealed a synthetic entered value. Desktop layout was checked and the temporary viewport override reset.

The supplied real workspace was preserved. Browser verification created additional synthetic documents only in the demo workspace. No invitations or emails were sent.

## Scope and limits

Database integrity, foreign keys and journal balance checks pass on the current local database. Earlier backup verification is described in the production comparison; a scheduled recovery service has not been established.

AI transport tests use a deterministic stub, not a live inference service. Production-product comparison uses official documentation, not hands-on paid environments. No independent penetration test, sustained load test, accessibility certification, accounting/compliance sign-off or production deployment has been completed. Read PRODUCTION-COMPARISON.md before evaluating real business use.

## Final run

43 integration tests passed in 105.447 seconds on the final regression run. JavaScript syntax checks and Python compilation checks passed. An earlier overlapping run hit a 20-second demo-creation client timeout; the test client now allows 60 seconds for password hashing and seeded workspace creation. This timing sensitivity reinforces that performance remains unqualified.

## Release 2.1 regression — 20 October 2026

48 integration tests passed in 90.787 seconds. Five new tests cover workflow simulation without writes, explicit activation and pause, repeat-run deduplication, immutable versions and rollback, tenant/role rejection, malformed input, source confidentiality on generated tasks and exports, restart-safe daily scheduling and revoked owner blocking. TypeScript strict compilation, JavaScript syntax checks and Python compilation passed. These are developer checks, not independent assurance.

Browser verification on 20 October: created an overdue-invoice automation in a separate newly seeded synthetic workspace, saved version 1, simulated one matching invoice, activated version 1 and ran it. First execution created one task; repeating the execution created zero and reported one already handled. Browser evidence saved alongside the outputs as Automation-Execution-Proof.jpg. The rule is manual, so it does not run automatically.
