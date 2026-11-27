# Nexus assistant: offline first, models optional

Open a conversation in Nexus Connect, then open Assistant. **Offline** is the
default even when models are configured. Each request explicitly chooses its
processing mode; a failed local model never falls back to an external provider.

## Offline (nothing to install)

- Extractive digest with source-message IDs; quotes are not inferred decisions.
- Keyword-based action candidates for human review.
- Draft reply template; nothing is sent.
- Search of up to 100 recent authorized conversation messages.
- Built-in purchasing, finance and company-access workflow guidance.

This is a bounded, deterministic assistant, **not** a language model. It cannot
translate, search every historical record, or autonomously execute actions.
Nexus's existing workspace search and record forms remain separate tools.

## Optional local model: Ollama

Install Ollama on the **Nexus server machine**, choose a model that fits its RAM,
and download it yourself (for example `ollama pull llama3.2:3b`). Set:

```text
NEXUS_LOCAL_AI_ENDPOINT=http://127.0.0.1:11434/v1/chat/completions
NEXUS_LOCAL_AI_MODEL=llama3.2:3b
```

Restart Nexus and explicitly select Local model in Assistant. Nexus uses Ollama's
OpenAI-compatible endpoint; no new runtime dependency or model download is bundled.
Local mode rejects non-loopback destinations and redirects. Local refers to the
server, not the visiting user's phone or laptop. Render's free web service does
not include Ollama or the memory needed to host typical models; use Offline there.

## Optional external model

Administrators may configure `NEXUS_AI_ENDPOINT`, `NEXUS_AI_MODEL`, and
`NEXUS_AI_API_KEY` privately. Remote endpoints require HTTPS. Configuring them
does not enable automatic external requests: users must select External provider.
The selector discloses the destination and model before submitting.

## Data and safety boundary

All modes use the current org-bound session and conversation authorization.
Only up to 100 recent non-deleted authorized messages are included; attachments
and other conversations are excluded. Context is bounded and model responses
are size-limited. Search and workflow guidance stay deterministic in every mode.
Access is rechecked after processing. Audits record the mode/destination.

No assistant has business-action tools: it cannot transfer money, approve a
request, create a task, or send a message. Model output is untrusted draft text,
rendered escaped in the UI. Normal record forms, RBAC and confirmations remain
the only way to perform those actions. Provider testing uses a local stub; actual
model quality, hardware performance and provider retention policies are not verified.
