# ADR 0004: Controlled Collectr-authoritative destructive synchronization

Accepted on 2026-07-19 by explicit user approval.

Collectr is the master collection. A full synchronization may therefore propose additions, quantity increases, quantity decreases, and complete removals from Dex. Destructive synchronization is never the default and may execute only when all of these conditions hold:

- the source snapshot is complete and approved for destructive planning;
- the destination record is in CardRelay's persistent managed sync scope;
- matching is exact or user-confirmed;
- configured removal count, percentage, and collection-drop thresholds pass;
- the destination has not changed since the preview;
- the user supplies the state-specific destructive confirmation code;
- a pre-sync destination recovery snapshot has been stored.

Safe and destructive changes use separate approvals. `--yes` may skip the safe-write prompt but never supplies destructive approval. Destination-only records outside the managed scope become manual-review items instead of removals. Partial source observations cannot authorize decreases or removals.

The browser extension presents a card-level Collectr-to-Dex diff before write approval is available. Dex writes remain disabled until user-controlled observations establish validated addition, increase, decrease, and removal contracts. Read-after-write verification and per-operation audit results are required before those capabilities can be enabled.
