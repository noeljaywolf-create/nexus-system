# NEXUS — Business management system

This is an early local business application with a Python HTTP server, persistent SQLite database and browser interface. Production readiness and trust have not been established. See PRODUCTION-COMPARISON.md for documented gaps against production products.

Create your own empty workspace, or choose Explore demo at sign-in. Administrators can also open a separate seeded Meridian Group workspace from Settings. Demo records persist separately from your organization. No default passwords are supplied. Guest demo access is local-only and can be disabled with NEXUS_DISABLE_DEMO=1.

## Start

Requires Python 3.11 or later. No Python package installation is required. The browser includes a pinned Mozilla PDF.js distribution; see THIRD_PARTY_NOTICES.md.

On Windows, double-click **Start Nexus.cmd**. Keep the server window open while using the system. The launcher opens **http://127.0.0.1:4180** once the server is listening. If Nexus is already running there, it opens that instance.

Alternatively:

```text
python launcher.py
```

Create a workspace using your name, email, organization and a password of at least 12 characters. A first administrator is created. Invite a second administrator or manager from People to review purchase requests: self-approval is intentionally prohibited.

Stop the server with Ctrl+C. Restarting it preserves records. The default database is `data/nexus.sqlite3`, relative to this application directory. You can override it with `NEXUS_DB`.

## Working capabilities

| Area | Implemented behavior |
|---|---|
| Identity | Workspace registration, password hashing, login/logout, expiring sessions, CSRF protection, role checks, single-use team invitations, multiple workspace memberships and switching |
| Organization | Branch and department directory, people directory, roles and departments, active-session presence |
| Projects | Budgets, due dates, private membership, status changes, owner control, automatic project conversation |
| Tasks | Assignment, priorities, due dates, status changes, source-message references and inherited source permissions |
| Connect | Workspace channels, private direct conversations, project conversations, replies, reactions, pins, mentions, search, unread counts, read receipts, edit history, removal tombstones and file attachments |
| Purchasing | Editable drafts, message extraction, submission, independent review, rejection and resubmission, recorded purchase orders linked to suppliers |
| CRM | Customer/contact directory, relationship stages and notes |
| Operations | Supplier directory, product catalog, integer-quantity stock adjustments and recorded movement reasons, negative-stock prevention |
| Finance | Invoice drafts, invoice issue, full-payment records, void reversals, immutable journal entries and lines, balanced double-entry postings and account balances |
| Assets | Equipment/device register, asset tags, acquisition values, assignees, project context and maintenance/retirement status |
| Contracts | Counterparties, values, date ranges, project context, internal status tracking and notes |
| Documents | Multi-file upload, notes, folders, tags, search, grid/list, immutable file versions, PDF/image/text preview, downloads, archive/restore and linked-record access |
| Meetings | Scheduling, timezone-aware times, agendas/notes, attendee invitations and RSVP |
| Intelligence | Live rule-based workspace signals; reviewable text extraction; optional provider-backed conversation summary, action-item extraction, reply drafting and translation |
| Industry packages | Activatable construction cost entries and professional-services time entries, validated through a versioned extension contract |
| Audit | Append-only event log, actor and decision history, JSON exports |

Messages refresh every five seconds while Connect is active. This is polling, not WebSocket transport. The latest 300 matching messages are returned per request; search queries match the full authorized conversation history.

Attachments are limited to 5 MB per file, stored in the database, authorized at download time, and served as downloads. Attachments are not malware-scanned. Removed messages block their attachment downloads. Original message content is retained in history. The default editing/removal window is 15 minutes. This retention model does not implement jurisdiction-specific deletion or legal-hold policies.

The dashboard derives values from saved records. Posted revenue uses issued invoices less reversals; it is not a profit or cash-flow measure. Monetary values use integer minor units. Workspace currencies supported here are USD, ZAR, EUR and GBP; there is no foreign-exchange conversion.

## Roles and access

- **Administrator:** workspace settings, invitations, roles, all projects including private projects, procurement review, finance, industry activation and audit. Administrators do not automatically gain access to other users’ direct conversations.
- **Manager:** ordinary business records, inventory, assets, contracts, purchase review and order issuance; private projects still require membership.
- **Finance:** ordinary business records, suppliers, contracts and invoice/ledger processing; private project access is not automatic.
- **Member:** shared project creation, tasks, conversations, customer records, purchase requests, documents, meetings and enabled industry entries.
- **Viewer:** read-only business access; may mark conversations read and respond to personal meeting invitations.

Project owners and administrators manage private project membership. Authorization is rechecked on every API request. Changes to workspace roles apply to existing sessions immediately. Tasks and requisitions derived from messages preserve the source conversation’s access rules; direct-message contents do not become organization-wide records merely through conversion.

An invitation link is generated for an exact email, expires after 24 hours and can be accepted once. Share it privately with the intended teammate. Nexus does not send invitation emails. The local loopback URL is reachable only on the same computer; use a properly deployed shared server for teammates on other devices.

## Purchase workflow

1. Create a project and open its conversation.
2. Send a message such as “We need 40 fire extinguishers for the new site.”
3. Select Requisition. Review the extracted fields and enter the estimated price.
4. Save the draft, then submit it from Procurement.
5. A different authorized manager or administrator reviews it.
6. After approval, select an existing supplier to record the purchase order.

Text extraction is a deterministic parser and is labeled accordingly. No model is required for this workflow. Creating a draft never submits it. Mentioning a purchase never issues an order. Duplicate order issuance is blocked transactionally. Purchase orders are internal records; no supplier transmission or payment is performed.

## Invoice ledger

Issuing an invoice debits Accounts receivable and credits Revenue. Recording full payment debits Cash and credits Accounts receivable. Voiding an unpaid issued invoice reverses its original entry while preserving the original posting. Repeating a transition cannot post a duplicate entry. Journal lines and entries reject updates and deletes through database triggers.

This release is **single-currency, tax-exclusive invoicing**, with full-payment recording. It does not calculate tax, payroll, depreciation, inventory valuation, statutory reports, partial payments, refunds or bank reconciliation. It does not connect to payment rails. Contract status tracking is not electronic signing.

## Optional AI connection

No external provider is contacted by default. The application contains a real adapter for a chat-completion-compatible HTTP service; it does not bundle a language model, model credentials or inference infrastructure.

Set these server environment variables before launch:

```text
NEXUS_AI_ENDPOINT=https://YOUR-PROVIDER/chat/completions
NEXUS_AI_MODEL=YOUR-MODEL-NAME
NEXUS_AI_API_KEY=YOUR-PROVIDER-KEY
```

`NEXUS_AI_API_KEY` is optional for an unauthenticated local model server. HTTP is permitted only on loopback; remote services require HTTPS. Redirects are rejected. Keep keys in the environment or your secret manager, not in application files, source control or `.openai/hosting.json`.

Connect → Assistant discloses the provider destination before submission. It sends up to 100 recent messages from the selected authorized conversation, bounded to 60,000 context characters. No other conversation or attachment is included. Generated output is treated as a draft, cites source-message IDs when the model follows instructions, and has no business-action tools. Access is rechecked before returning the response. Requests have a 25-second timeout and a limit of ten per user per minute. Provider availability and output quality depend on your configured service. Integration tests use a local stub to verify the adapter and access boundary; no live model has been configured or evaluated here.

## Industry extension contract

`packages.json` defines contract version 1, package identities, field types and allowed enum values. Only packages in that server-owned registry may be activated. Administrators activate packages per organization. Extension records occupy their own namespace, require an authorized project, and validate money, dates, integer ranges and required values before saving. Generic extension forms render from the same definitions. New compatible data-entry packages can be added without modifying core entity tables.

The available packages are construction cost recording and professional-services timesheets. These are operational records; entries do not automatically post to the financial ledger, invoice customers or reserve inventory. Healthcare, banking, insurance, clinical integrations and other regulated workflows are not supplied or certified by this system.

## Tests

```text
python -m unittest discover -s tests -v
node --check web/app.js
```

Tests start a real HTTP server against a separate temporary database inside `.test-runs`. They cover authentication, CSRF/origin rejection, tenant boundaries, private-record revocation, direct-message privacy, derived-record privacy, roles, invitations, concurrent approvals and reads, purchase state transitions, inventory constraints, balanced finance postings, immutable audit/journals, attachments, meetings, industry entries and provider-context boundaries. No test sends data to an external AI provider.

## Backups and health checks

```text
python manage.py check
python manage.py backup
python manage.py backup --output backups/my-backup.sqlite3
```

Backups use SQLite’s online backup API and verify integrity. The tool refuses to overwrite existing files. A backup includes business data, attachments, password hashes and sessions; store it as sensitive organizational data. Test restoring a backup before relying on it. To verify a restore without replacing the live database, stop another test instance, set `NEXUS_DB` to the backup’s absolute path, and run `python manage.py check`.

## Deployment boundary

The default server is intentionally bound to `127.0.0.1`; it is a working local application, not a hosted enterprise service. For shared deployment, use a managed process and an HTTPS reverse proxy, explicitly set `NEXUS_ALLOWED_HOSTS` to the expected hostname, set `NEXUS_SECURE_COOKIE=1`, and keep the internal Python port inaccessible to untrusted networks. The current standard-library HTTP server is suitable for local operation and integration testing; high-load internet service requires an audited application-server deployment, load tests and operational hardening.

SQLite provides persistent transactional storage for a single application instance. Multi-instance scale, high availability and geographically distributed operation require a database and event architecture appropriate to that workload. Filesystem/database administrators remain trusted; append-only triggers are not tamper-proof against an operator who can alter the schema or database file.

Not included: SSO/MFA and self-service password recovery; email/push delivery; WebSockets; voice notes and audio/video calls; recording/transcription consent workflows; searchable attachment content; configurable approval-policy graphs; advanced HR/payroll; disaster-recovery automation; regulated-industry integrations and certifications. No claim of full enterprise readiness, regulatory compliance, competitive validation or support for every industry is made.

No hosted deployment or external source upload is included in this local build.

## Updated document and interface workflows

Documents accept PDF, DOCX, XLSX, PPTX, PNG, JPEG, TXT, CSV and Markdown, up to 20 MiB each. Office files download for external editing. File validation checks signatures and Office structure; it does not replace malware scanning. Password fields have accessible show/hide controls. Tables provide filtering, sorting, pagination and authenticated CSV downloads of selected accessible rows (maximum 1,000). CSV exports escape spreadsheet formula prefixes. The dashboard derives revenue trends and operational summaries from stored records.

The seeded workspace includes six projects, thirty tasks, customer and supplier directories, eighteen invoices, inventory, documents, meetings, assets, contracts and sample colleagues. All names, records and email addresses are synthetic.

## Release 2.1 — configurable automation and specification

Read planning/NEXUS-2030-SPECIFICATION.md for the fifteen required planning deliverables, an explicit implementation-gap matrix and the TypeScript/PostgreSQL migration plan. These are not completed-stage or customer-validation claims.

Administrators can open Automations, choose an overdue-invoice, low-stock or contract-expiry rule, save an immutable draft, simulate it, activate a version, run it and inspect execution counts. Saving a new version does not change the active version. Activate an earlier version to roll back configuration; existing business actions remain. Pause stops future execution. Only task creation and internal notifications are supported, assigned to the rule's administrator owner. Tasks inherit source confidentiality, including finance access. The action limit is 250 matching records per rule, with at most 100 rules per workspace.

Daily rules run on a 60-second local server poll, once per UTC day while the server is running. One action per rule/source/day is enforced across all versions. An open condition may create another task the next UTC day. Missed days are not replayed. Scheduled permission failures produce a blocked execution entry and retry on the next day; transient database failures retry on the next poll. The owner must remain an active administrator. This is a bounded automation engine, not the complete drag-and-drop branching/approval designer from the brief.

The new automation interface is authored in src/automation.ts and typechecked with TypeScript 5.9.3. A compiled web/automation.js is included, so starting the application needs no build. For development, install the pinned development dependency and run npm run build or npm run typecheck. The server and other modules remain Python/JavaScript; the TypeScript-first platform migration is unfinished.
