# NEXUS 2030 — requirements, architecture and delivery baseline

Date: 20 October 2026. Status: proposed product baseline, grounded in the original brief and the current code. This document supplies the fifteen requested first deliverables retrospectively; it does not pretend they preceded the existing implementation. Requirements are commitments to verify, not statements of completed functionality.

## 1. Competitive differentiation analysis

Published Odoo Studio documentation describes configuration and automation; Microsoft Business Central documents event/condition/response approval workflows. Conversation-to-task and record-linked documents are already established market functionality. NEXUS cannot claim differentiation merely by combining them.

References: [Odoo Studio](https://www.odoo.com/documentation/19.0/applications/studio.html), [Odoo automation](https://www.odoo.com/documentation/19.0/applications/studio/automated_actions.html), [Business Central workflows](https://learn.microsoft.com/en-us/dynamics365/business-central/across-use-workflows). See ../PRODUCTION-COMPARISON.md for the existing document/communication comparison.

Differentiation hypotheses: (a) reduce the time from a purchase need in chat to a correctly contextualized reviewed requisition; (b) explain cash exposure using linked receivables, commitments and project dates; (c) recover past decisions with authorized evidence. None is customer-validated. Proposed research: observe ten organizations across at least three industries, interview employees and approvers separately, record baseline completion time/error rate, then compare the same tasks in a pilot. Target hypotheses: 30% shorter reviewed requisition preparation, 50% shorter historical-decision retrieval, zero unauthorized evidence disclosures. Do not report these targets as achieved results.

## 2. Universal software requirements specification

Tenant is the primary security boundary. Organization units model branches and departments. Users may have memberships in several tenants; employees are separate workforce records, not synonyms for login identities. Customers/suppliers are tenant-scoped counterparties. Core resource types include products/services, projects/tasks, assets/contracts, documents/versions, conversations/messages, approvals, workflows and transactions.

Functional requirements and current position:

| ID | Requirement | Current state / acceptance |
|---|---|---|
| ID-01 | Identity, membership, sessions, invitation and revocation | Local implementation exists; require MFA, OIDC, recovery and lifecycle tests before shared deployment. |
| AUTH-01 | Tenant, role, record and field permissions | Tenant/role and selected record checks exist. Full attribute/field policy engine absent. Every new endpoint must have cross-tenant negative tests. |
| COM-01 | Private/group/context chat, threads, search, attachments, presence | Core subset exists. Delivery uses polling; voice, availability preferences and real-time transport remain open. |
| DOC-01 | Authorized file versions, previews, record links and retention | Local file workflow exists; quotas, malware scanning, OCR and regulated retention remain open. |
| WF-01 | Configurable conditions, simulation, version activation, execution and logs | Bounded rule engine added in release 2.1. Arbitrary branching, approval stages and escalations remain open. |
| SALES-01 | Lead to quotation, order, delivery, invoice and returns | Customer directory and narrow invoicing exist. Complete sales lifecycle absent. |
| FIN-01 | Financial integrity and jurisdiction-specific accounting | Narrow single-currency ledger exists. Reconciliation, taxes, partial payments and statutory reporting absent. |
| WORK-01 | Workforce, leave, resource capacity and payroll | People directory exists; HR/payroll not delivered. |
| BRAIN-01 | Permission-aware evidence retrieval, inference and human-controlled proposals | Selected conversation provider adapter exists. Enterprise retrieval, knowledge graph and predictive evaluation absent. |
| EXT-01 | Versioned custom applications and industry adapters | Two fixed extensions exist. Universal application builder absent. |
| EXTERNAL-01 | Scoped guest spaces and audited revocation | External collaboration not delivered. Workspace viewers are not a substitute for external guests. |
| OPS-01 | Imports, export, backup, observability and resilient mobile use | Exports/manual backup exist. Bulk imports, production telemetry, DR and low-bandwidth qualification absent. |

Nonfunctional acceptance targets, not measured results: accessible critical flows against WCAG 2.2 AA; 99.9% monthly availability for a future hosted pilot; p95 simple reads below 500 ms at a declared dataset/concurrency; no duplicate financial transitions under retries; transactional workflow outputs; recoverable backup within an agreed RPO/RTO. Establish workload and recovery budgets with pilot customers before committing to SLAs.

## 3. System architecture blueprint

Target modular monolith: Next.js/React TypeScript UI; TypeScript domain/application modules behind NestJS HTTP and WebSocket adapters; PostgreSQL authoritative store; Redis only for ephemeral cache/presence/rate limits; durable jobs backed by transactional outbox and a queue; object storage for files; independent model gateway; OIDC identity adapter; OpenTelemetry traces/metrics/logs. Docker deployment and CI gates are required before hosted use. Split services only after measured bottlenecks justify ownership and failure-boundary costs.

Modules: Identity/Policy; Organization/Workforce; Counterparties/CRM; Sales; Procurement; Inventory; Projects/Resources; Finance; Assets/Contracts; Collaboration; Knowledge; Workflow/Apps; Insights/AI; Integrations. Each module owns writes to its aggregates. Cross-module writes use application commands, never arbitrary extension SQL. A shared policy adapter enforces record access in API, background jobs, search and AI retrieval.

Actual deployment remains Python/SQLite plus JavaScript and a new TypeScript-authored automation UI. This is architectural debt against the brief. Migration sequence: freeze behavioral contracts with tests; create TypeScript shared schemas and policy tests; build PostgreSQL migration/reconciliation tooling; port identity and one vertical business flow; run shadow read comparisons; execute a reversible data migration in a separate copy; switch only after parity/security/recovery validation. Do not run two independently writable ledgers or overwrite the current database to claim a migration.

## 4. Core database entity relationship model

Organization 1—many Membership many—1 User. Organization 1—many Unit; Unit may parent another Unit. Organization 1—many Employee, with optional User link. Organization 1—many Counterparty, with customer/supplier roles. Organization 1—many Project; Project many—many Membership through ProjectAccess; Project 1—many Task. Conversation optionally links an authorized typed RecordReference; Conversation 1—many Message; Message optionally replies to Message; Message 1—many AttachmentVersion. Document 1—many immutable FileVersion; Document optionally links Project and RecordReference. Requisition 1—many ApprovalDecision; approved Requisition 0—1 PurchaseOrder. Customer 1—many Invoice; Invoice 1—many JournalEntry; JournalEntry 1—many JournalLine. WorkflowRule 1—many immutable WorkflowVersion; WorkflowVersion 1—many WorkflowRun; WorkflowRun produces typed effects. CustomRecord belongs to a versioned CustomSchema. ExternalSpace 1—many explicitly shared RecordReference and scoped GuestGrant.

Every tenant resource has tenant_id and unique (tenant_id,id). Cross-resource foreign keys include tenant_id. Monetary amounts use minor units plus currency, never binary floats. Journal entries balance per currency and cannot be edited after posting; corrections are reversing entries. Identity email uniqueness is a global login concern; business identifiers are tenant-scoped. Tenant-aware indexes support lists and lookup. Schema changes require versioned, reversible migrations and backfill verification. The current schema.sql implements only the subset marked in the requirements table.

## 5. Multi-tenant security architecture

Authenticate identity; resolve selected active membership; authorize command and each referenced record; validate fields; execute in transaction; append audit and domain events. Never trust tenant IDs supplied in payloads. Policy inputs include tenant, role, membership status, record ownership, project membership, source confidentiality and explicit external grants. Background jobs re-resolve permissions at execution time; revocation must affect search results, queued commands, previews and AI context.

Target PostgreSQL RLS is defense in depth alongside application checks; tenant context must be transaction-local and reset safely under pooling. Object keys are tenant-prefixed with opaque IDs; signed URLs have short expiry after an authorized request. Secrets live outside source archives. MFA enrollment/recovery uses audited step-up checks. Field restrictions cover payroll, bank details and sensitive HR/clinical fields. Regulated modules require separate expert review and cannot be enabled solely through a general industry label.

Current SQLite isolation is application-enforced. No RLS, MFA, SSO or field policy certification is claimed. Threat review must include IDOR, source-derived record leakage, uploads, session theft, privilege change during async work, prompt injection, extension escape, export leaks and operator access.

## 6. Real-time chat architecture

Target authenticated WebSocket sessions join tenant/user rooms only after server authorization. Join/rejoin each record channel through policy checks; revalidate after membership change. Persist message and outbox event in one transaction, acknowledge persisted ID to sender, publish asynchronously, deduplicate client delivery by event ID, and reconcile reconnect using sequence cursors. Delivery acknowledgment, read receipt and online presence are separate facts. Presence TTL in Redis never becomes proof of delivery.

Use bounded attachments, scanning quarantine and authorized retrieval. Retention policies apply to edits, tombstones, backups and exports. Voice requires explicit browser capture and codec/size bounds. Recording/transcription requires consent and retention design. The existing five-second poller is retained until this subsystem is implemented and tested; it is not called real-time delivery.

## 7. AI intelligence and organizational memory architecture

Ingestion extracts text from approved clean files and authorized messages. Store source ID, tenant, version, timestamps, classification and access dependencies beside each chunk. Search first applies permissions, then ranks; access is rechecked before response and citation delivery. An embedding hit is not authorization. Treat documents and chat as untrusted data, never tool instructions.

Evidence bundles separate record facts, explicit assumptions, calculations and generated interpretation. Summaries cite source IDs and versions; missing evidence is stated. Relationship edges start with actual foreign keys and typed record references. Add inferred edges only with confidence/provenance and review. AI commands create proposals, not direct money movements or approvals. Use scoped tool allowlists, idempotency, approval expiry and audit of the approved payload. Test retrieval precision, citation faithfulness, hallucination, tenant separation and revoked-access behavior with a curated evaluation set before enabling live organizational memory.

Digital twin begins as deterministic cash timing scenarios with visible assumptions, not an unvalidated prediction model. Health scores must disclose component weights, freshness, missing dimensions and source records. No universal score is presented as objective truth.

## 8. Module integration and event model

Target event envelope: event_id, tenant_id, aggregate_type/id, aggregate_version, event_type, schema_version, occurred_at, actor_id, correlation_id, causation_id and minimal payload. Candidate events: task.created.v1, invoice.issued.v1, invoice.payment_recorded.v1, requisition.submitted.v1, requisition.decided.v1, inventory.adjusted.v1, contract.updated.v1, document.version_added.v1 and membership.revoked.v1.

Write aggregate, audit and outbox atomically. Consumers use inbox uniqueness to deduplicate; retry transient failures with bounded backoff and expose dead letters to operators. Event payloads avoid document contents or sensitive payroll data. Delivery does not grant access. Replays must not resend notifications or post financial entries without matching idempotency keys. Current automation uses durable rule versions, effect uniqueness and atomic database transactions; it does not yet supply a general event bus or outbox.

## 9. Role and permission matrix

| Capability | Admin | Manager | Finance | Member | Viewer | External guest (target) |
|---|---|---|---|---|---|---|
| Membership/security/configuration | Manage | No | No | No | No | No |
| Private project | All locally | Explicit membership | Explicit membership | Explicit membership | Explicit membership | Explicit shared grant only |
| Shared task/customer work | Write | Write | Write | Write | Read | Explicit shared scope only |
| Invoice and ledger | Write | No | Write | No | No | Never internal ledger |
| Purchase review | Independent | Independent | No locally | No | No | Explicit request response only |
| Documents/messages | Record policy | Record policy | Record policy | Record policy | Read policy | Explicit grant only |
| Direct messages | Participants only, including admin | Participants | Participants | Participants | Read if participant | Space policy |
| Automation configuration | Manage | No locally | No locally | No | No | No |
| Payroll/clinical | Separate target policy, no implementation | Separate target policy | Separate target policy | Separate target policy | No | No |

Roles do not override source confidentiality except the explicitly declared administrator project policy. Future ABAC and field rules refine this matrix. External guests, payroll and clinical policies are specifications, not current features.

## 10. UI/UX screen architecture

Target navigation: Home, Workspace, Chat, Customers, Operations, Finance, Projects, People, Analytics, AI Brain, Apps and Settings. Existing navigation is transitional. Home presents role-relevant assigned work and evidence-linked signals. Workspace contains saved views and personal dashboard preferences. Chat has persistent context and reviewed action drafts. Customer detail groups timeline, sales, files and authorized finance links. Operations separates purchasing, stock locations, fulfillment and assets. Finance separates receivables, payables, journals, reconciliation and reports. Apps contains workflows and custom applications. Settings governs identity, policies, integrations and tenant configuration.

Every list needs server pagination/filtering, preserved query state, accessible keyboard interactions and explicit error/empty/loading states. Detail screens show permissions and source context without exposing forbidden records. Commands show consequences before irreversible action. Global search and command access use the same authorization as detail views. Low-bandwidth mode reduces previews/polling and supports resumable drafts, not offline financial posting. User studies must test employee, approver and administrator tasks, not only dashboard appearance.

## 11. SaaS pricing and packaging hypothesis

Starter: CRM/tasks/chat/basic documents. Growth: inventory/procurement/finance/workflow templates. Enterprise: governed multi-entity operations, SSO, policy controls, advanced integrations and supported SLAs. Industry Editions add separately validated domain packages. Pricing amounts remain unvalidated until customer research and hosting/model cost measurements; do not invent a market-tested price. Meter expensive services transparently (AI token/provider costs, retained storage and communications) with budgets, caps and explicit opt-in. All tiers retain export rights. Security isolation and basic backup are not upsell gates.

## 12. Prioritized product roadmap

P0: reconcile requirements and acceptance matrix; architecture migration plan; automated authorization regression; recovery evidence. P1: identity/MFA/session lifecycle and role policies; typed domain/data migration; real-time durable chat. P2: complete CRM/sales/inventory/accounting vertical slices with domain expert review; controlled workflow automation. P3: search/memory evaluation; custom schema/form/view builder. P4: secure external collaboration and measured industry pilots. P5: predictive/strategic capabilities only after trustworthy history and evaluation. Do not activate clinical/payroll/banking packages ahead of their expert requirements and acceptance evidence.

## 13. Milestones and acceptance criteria

| Brief stage | Exit demonstration | Current status |
|---|---|---|
| 1 Research | Interviews, observed baseline, competitor task comparison | Documentation comparison only; customer validation pending |
| 2 Model/architecture | Reviewed domain, tenant boundaries, typed contracts, migration rehearsal | Written baseline supplied; review and TypeScript backend pending |
| 3 Identity/design | Registration/revocation, MFA recovery, field/record tests, accessible forms | Local subset; major security controls pending |
| 4 Connect | Persist/send/reconnect under failure, source access revocation | Polling subset; real-time failure tests pending |
| 5 CRM/docs/workflows | Contextual customer-to-file-to-task; simulate/activate/run/rollback rule | Local subset and bounded automation implemented; extended acceptance pending |
| 6 Commercial flows | Quote/order/stock/invoice/reconciliation with balanced journal | Partial procurement/invoice/stock flow only |
| 7 Brain | Authorized retrieval with citations and measured eval results | Not delivered |
| 8 Designers | Configure schema/view and branching approval process without source edits | Bounded rule form only; full designers pending |
| 9 Extensions/external | Restricted external project collaboration and domain-specific validation | Two internal extensions only |
| 10 Assurance/pilot | Independent findings resolved, load/recovery evidence, observed pilot outcomes | Not delivered |

Each stage needs a recorded scenario, versioned fixtures, positive/negative permissions, failure/retry evidence and owner sign-off. A green developer test suite is necessary evidence for narrow behavior, not a substitute for a stage exit review.

## 14. Risk assessment and mitigation

Architecture divergence: preserve current data; migrate in reversible tested slices. Scope overload: select complete business journeys and explicitly track missing capabilities. Security leakage: shared policies and negative tests across search, jobs, exports and AI. Accounting errors: qualified review and reconciliation fixtures before real financial reliance. Upload threats: quarantine/scanning/quotas and safe rendering. AI misrepresentation: provenance, evals, human proposals and no autonomous financial commands. Reliability: durable transactions/jobs, bounded workloads, monitored errors and recovery drills. Commercial risk: validate willingness to pay and task improvements before claiming superiority. Regulated-industry risk: defer unsafe packages until domain experts approve the exact workflow and jurisdiction.

## 15. Pilot scope and strategy

Pilot scope is a connected team workflow, not the entire universal platform: organization identity, project chat, reviewed purchase need, independent decision, supplier order, stock record, attached document and traceable follow-up. Add CRM-to-invoice only with an accounting reviewer. Exclude payroll, clinical care, bank transfers and statutory filing until their requirements are separately fulfilled.

Start on synthetic data, then a controlled noncritical internal pilot with explicit access scope and recoverable imports. Recruit several organizations only after security/recovery gates. Measure completion time, data correction rate, missed approvals, access failures, duplicate actions, recovery time and user task success. Record feedback and stop criteria. Do not call a commercial pilot validated before actual participants and outcomes exist.
