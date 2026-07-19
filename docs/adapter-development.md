# Adapter development

Destination adapters declare capabilities, retrieve normalized catalog/collection records, and apply already-approved operations. They must not redefine identity. Catalog records are revalidated, deduplicated by destination ID, deterministically ordered, and cached at the core boundary; conflicting identities for one destination ID fail closed. Validate all external responses, use explicit timeouts and bounded retries, redact secrets, classify partial failures, and test with sanitized fixtures without live CI dependencies.

## Adapter contract

Implement `DestinationAdapter` from `card_relay.destinations.base`:

1. Set a stable `destination_name`.
2. Return a complete `DestinationCapabilities` declaration. A capability is a safety boundary, not an aspirational feature flag: set it only when the adapter can execute and verify the operation.
3. Return canonical `DestinationCatalogRecord` and `DestinationCollectionEntry` values. Preserve destination-specific identifiers in `destination_id`; do not replace CardRelay matching or normalization.
4. Accept only an already-approved list of `SyncOperation` values in `apply_operations`. Return one `OperationResult` per operation and accurately report partial failures.
5. Keep transport, authentication, retry, and response validation inside the adapter boundary. Never log credentials or raw private collections.

Use `card-relay destinations --json` to discover the built-in adapter declarations without opening a browser or contacting a service. The registry currently lists the persistent local `mock` adapter, read-only capture-backed `dex` adapter, and `experimental` in-memory Pokémon adapter. The experimental adapter exists solely as a compatibility reference: it supports additions and quantity increases, never decreases or removals, and does not contact a third party.

## Compatibility checklist

- `supported_games` rejects unsupported games before matching or execution.
- Catalog and collection reads are deterministic.
- Dry runs do not mutate destination state.
- Reapplying the same approved safe operation converges to the requested quantity.
- Unsupported, ambiguous, and non-executable operations are reported rather than guessed or applied.
- Tests cover capabilities plus additions/increases and any claimed destructive behavior separately.

