# chat_requests (legacy archive)

Historical V1 package layout only — **not installed** by `kotenai-zeus-client` 2.x.

## Do not commit Zeus-generated catalogs

Full `chat_request_*.json` snapshots (system prompts, verb schemas, cost/masq
tables, stamped contracts) are **Zeus Engine / Hub artifacts**. They must not
live in this client repository.

Obtain catalogs at runtime:

1. Sync from a live Zeus/Hub stamp into `~/.config/zeus_client/chat_requests/`, or
2. Use the minimal fixtures under `tests/fixtures/` for offline unit tests only.

Never invent production `contract_hash` values — Hub stamp only.

## Pipeline / verb authoring

Authoritative verb and pipeline rules live in Zeus platform docs and the stamped
catalog from Hub — not in this archive folder.
