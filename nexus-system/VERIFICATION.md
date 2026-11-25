# Verification record

Verified locally on October 19, 2026, using Python 3.14.5 and a Chromium-based browser.

## Automated integration checks

**32 tests passed** against a real HTTP server and an isolated SQLite database. Test source: `tests/test_system.py`.

Coverage includes authentication and password hashing; CSRF, origin and host rejection; tenant isolation; private-project membership and revocation; project ownership; message replies, reactions, read receipts, pins, editing and retained history; private direct messages; attachments and revoked downloads; message-derived tasks and requisitions; source-message context lookup; private derived-record access; role changes in existing sessions; single-use invitations; viewer/finance restrictions; self-approval rejection; rejection/edit/resubmission; purchase-order state transitions and duplicate protection; simultaneous approval requests; parallel reads; stock constraints; balanced invoice posting, payment and reversal; immutable journals/audit; documents, meetings, notifications; asset/contract/unit records; extension validation; protected financial-record conversations; and optional AI adapter/context boundaries.

AI tests use a local deterministic provider stub to verify transport and access control. No live inference provider, model quality, translation quality or external service was tested.

## Browser verification

Using a separate verification organization and database:

1. Created an organization through registration and signed in.
2. Created Riverside Site and verified the linked project conversation.
3. Sent a message requesting 40 fire extinguishers.
4. Extracted its item and quantity into an editable requisition and saved the priced draft.
5. Restarted the server and verified the records remained present.
6. Created a workspace-wide task and verified it appeared on the dashboard.
7. Created a customer and opened its contextual record conversation.
8. Created a draft invoice, explicitly issued it, and verified equal $4,800 receivables-debit and revenue-credit entries in the ledger.

Browser verification found and corrected an optional-project form constraint and duplicate hidden form IDs. The application script passes `node --check web/app.js`.

## Operations verification

Database integrity checks, foreign-key checks and journal balance checks passed. A consistent online backup of the verification database was created and independently checked successfully. The main application database contains no verification accounts or business records.

## Limits

This is verification of the implemented local release, not a penetration test, load test, accessibility certification, disaster-recovery certification, regulatory assessment or proof of enterprise scalability. See README.md for the exact operating scope and remaining capabilities.
