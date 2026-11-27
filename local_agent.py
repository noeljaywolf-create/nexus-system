"""Offline, read-only assistance over permission-checked conversation data.

This is deterministic extraction, not a language model or an autonomous actor.
It never loads records, executes instructions in messages, or makes network calls.
"""
import re


def respond(messages, action, query=''):
    rows = messages[-100:]
    def quote(row):
        return f'[{row["id"]}] {row["author_name"]}: {row["body"][:600]}'
    if action == 'summary':
        return 'Offline extractive digest (quotes, not inferred decisions):\n\n' + '\n\n'.join(quote(r) for r in rows[-12:])
    if action == 'actions':
        candidates = [r for r in rows if re.search(r'\b(need|please|todo|must|due|should|will|follow up)\b', r['body'], re.I)]
        return ('Possible action items — quoted for human review; no tasks were created.\n'
                + '\n\n'.join(quote(r) for r in candidates[-15:])) if candidates else 'No action-item keywords found. Review the conversation manually; this does not prove there are no action items.'
    if action == 'reply':
        return ('Draft template — edit before sending; nothing was sent.\n\n'
                'Thank you for the update. I will review the details and confirm the next steps.\n\n'
                'Latest source:\n' + quote(rows[-1]))
    if action == 'search':
        terms = query.casefold().split()
        hits = [r for r in rows if all(term in r['body'].casefold() for term in terms)]
        return ('Offline search of up to 100 recent accessible messages:\n\n' + '\n\n'.join(quote(r) for r in hits[-20:])) if hits else 'No matches in the recent authorized conversation context. Older messages and attachments were not searched.'
    if action == 'help':
        return ('Workflow guidance (not an authorization grant):\n'
                '- Purchasing: draft → submit → independent review → purchase order. Requesters cannot approve their own requests.\n'
                '- Finance: draft → issue → record full payment, or void an unpaid issued invoice. Payment recording does not send money.\n'
                '- Access: roles belong to a company membership. Switch workspace explicitly; another company is never included automatically.\n'
                'Open the corresponding Nexus section to prepare an action; its normal permissions and confirmations still apply.')
    raise ValueError('Offline mode cannot translate. Choose an explicitly configured local model or external provider.')
