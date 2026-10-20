# NEXUS — production-product comparison and readiness assessment

Assessment date: October 19, 2026. Scope: the local application in this directory, compared with published product documentation. This is not a hands-on evaluation of paid competitor deployments, an independent security audit, or a certification.

**Overall conclusion: production readiness is not established.** The application now provides working connected workflows and the requested seeded experience, document uploads and usability changes. Those capabilities do not establish enterprise reliability, accounting suitability, regulatory compliance or competitive superiority. The earlier description of this application as a trusted enterprise system was overstated and is withdrawn.

## Product benchmarks

| Workflow | Documented production-product reference | NEXUS implementation and evidence | Assessment |
|---|---|---|---|
| Document library | Odoo Documents describes file organization, previews, versions and access rights. [Odoo Documents](https://www.odoo.com/documentation/19.0/applications/productivity/documents.html) | Uploaded files have folders, tags, grid/list views, filename/tag search, metadata, authorized downloads, PDF/image/text previews, version history and archive/restore. Automated tests cover uploads, immutable versions and access revocation. | A working subset. Flat folder labels are less capable than a hierarchical document-management system. No collaborative Office editing or OCR. |
| Attachments on business records | Business Central documents attachments, notes and links associated with records. [Microsoft record attachments](https://learn.microsoft.com/en-us/dynamics365/business-central/ui-how-add-link-to-record) | Uploads can link to projects, customers, tasks, purchase requests, assets, invoices and contracts. Linked-record permissions are checked on listing, preview and download. | Implemented core attachment flow; no mail ingestion or document-exchange network. |
| Reviewed purchasing | Business Central documents approval requests and workflows for business records. [Microsoft approval workflows](https://learn.microsoft.com/en-us/dynamics365/business-central/across-use-workflows) | Draft, submission, independent approval/rejection and purchase-order recording work transactionally. Self-approval and duplicate ordering are rejected. | Narrow, fixed purchasing workflow. No configurable multistage approval graph, delegation, escalation or policy thresholds. |
| Conversation-to-task | Zoho Cliq documents task actions from messages and project integration. [Zoho Tasks in Cliq](https://help.zoho.com/portal/en/kb/zoho-cliq/user-guides/home-page/navigation-sidebar/articles/tasks-in-cliq) | Messages become reviewed task or requisition drafts with a source reference and inherited access. | This is existing market functionality, not a validated competitive differentiator. |
| Working with business lists | Reference production workflows require users to locate and act on records, not only view a dashboard. This row is an assessment of NEXUS behavior, not a claim about a competitor’s complete UI. | Tables now provide filtering, keyboard-accessible column sorting, pagination, page size and CSV export. Status changes update the export cache. | Useful local behavior. Filtering and pagination are client-side; very large datasets require server-side queries and pagination. |
| Financial operations | No claim of accounting parity is made from the narrow source set above. | Invoice issue, full-payment recording and void reversals produce balanced integer-minor-unit entries. Tests exercise duplicate transitions and immutable journal lines. | Not a production accounting suite: taxes, bank reconciliation, partial payments, exchange conversion, payroll and statutory reporting are absent. |
| Generative assistance | No live model or competitor AI evaluation was performed. | An optional configured provider can receive selected authorized conversation context. Generated output cannot execute business transactions. Provider transport/access tests use a local stub. | Provider integration exists. No live model is configured; answer accuracy and model safety have not been evaluated. |

The comparison establishes feature gaps. It does not establish that NEXUS outperforms Odoo, Zoho or Dynamics, and it does not imply their whole product scope was tested.

## Requested improvements and acceptance evidence

| Request | Delivered behavior | Verification |
|---|---|---|
| Seed data | Separate Meridian Group demo workspace, clearly labeled. Initial fixtures include 9 people, 6 projects, 30 tasks, 12 customers, 8 suppliers, 15 products, 9 purchase requests, 18 invoices, 8 assets, 6 contracts, 8 uploaded documents, 4 meetings and both industry packages. | Seed tests check the populated workspace, financial balance, tenant separation and repeat-call idempotency. Existing business organizations are not populated or overwritten. |
| Upload documents | Multiple files, actual per-file upload states, 20 MiB limit, PDF/DOCX/XLSX/PPTX/TXT/CSV/MD/PNG/JPEG support, filename/format validation, record links and authorized downloads. | HTTP integration tests plus browser upload using synthetic files. Macro-containing Office packages are rejected; this is not a malware scanner. |
| File versions | New uploads append immutable versions; old versions remain downloadable. Identical concurrent retries do not create duplicate versions. | Version, content, concurrency and database-trigger tests. |
| Show password | Eye control reveals or masks the password currently being typed, with an accessible label and pressed state. | Browser verification checked that Show password changed the entered input to text and exposed the Hide password control. Stored passwords remain hashes and cannot be revealed. |
| Visual consistency | Colored vector icons, a coherent sidebar, dashboard signals, ledger-derived revenue chart, improved authentication layout and a document-management workspace. | Browser layout review. A visual refresh is not evidence of security or product maturity. |
| Usability | Clear create actions, visible upload errors, read-only roles, searchable lists, sortable headers, record counts and reversible document archive. | Browser checks and workflow tests; no external usability study has been conducted. |

## Security and operational gates

OWASP ASVS provides a basis for evaluating application security controls. The checks below are a project-specific gap assessment, **not an ASVS verification or conformance claim**. [OWASP Application Security Verification Standard](https://owasp.org/projects/asvs)

| Gate | Current evidence | Unmet requirement |
|---|---|---|
| Authentication | Salted PBKDF2 hashes, session expiry, HttpOnly/SameSite cookies and login attempt limits are implemented. | Independent review, MFA, SSO, account recovery, account lifecycle and credential-rotation procedures. |
| Authorization | Tenant scoping, workspace roles, private projects, direct conversations, source-derived permissions and document-record checks have targeted tests. | Independent adversarial review and a comprehensive authorization matrix across all operations. |
| Upload security | Size bounds, file-type checks, immutable versions, download authorization and content-disposition handling are implemented. | Malware scanning, robust content disarm where required, storage quotas, regulated retention and deletion/legal-hold policies. |
| Finance | Application-level transaction tests and balanced posting checks pass. | Qualified accounting review, reconciliations, reporting validation and jurisdiction-specific requirements. |
| Reliability | Persistent local transactions, constrained state transitions and retry protection exist for key flows. | Sustained multi-user/load testing, failure injection, capacity targets and service-level objectives. |
| Recovery | A consistent backup and integrity check have been exercised. | Scheduled protected backups, off-device retention and timed disaster-recovery drills with documented recovery objectives. |
| Deployment | A local loopback server is available. | An audited production serving stack, HTTPS configuration, monitoring, alerting, secrets management, patching and incident procedures. |
| Privacy/compliance | Record access boundaries exist. | Data mapping, lawful retention/deletion, legal review, vendor assessment and any sector-specific certifications. |
| Product fit | Several workflows can be exercised on connected sample data. | Customer interviews, pilot use, support ownership and measured comparison of time-to-completion and error rates. |

## What would justify a stronger claim

A production claim should follow evidence gathered against a defined customer, deployment and workload. At minimum: a reviewed threat model; independent security findings and remediation; verified restore/recovery drills; load and failure tests against agreed targets; an operational owner; domain review of purchasing and accounting; and real users completing representative scenarios. Production readiness is a decision supported by those results, not a label earned by elapsed coding time or the number of tests.

## Automation update — 20 October 2026

[Odoo automation documentation](https://www.odoo.com/documentation/19.0/applications/studio/automated_actions.html) and [Microsoft workflow documentation](https://learn.microsoft.com/en-us/dynamics365/business-central/across-use-workflows) describe configurable automation and approval workflows. NEXUS 2.1 now supplies three bounded trigger templates, explicit draft/simulate/activate/run/pause controls, immutable versions, configuration rollback, daily local evaluation and durable execution/effect records. It remains a subset: there is no arbitrary graph designer, approval-stage configuration, delegation, escalation, general event-trigger engine or external integration runner. Developer tests and the synthetic browser flow support the implemented subset; no competitor environment was operated hands-on.
