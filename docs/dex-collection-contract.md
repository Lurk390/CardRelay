# Dex read-only contract

This contract was established through schema-only inspection and a user-controlled live validation on 2026-07-18. No live response, account identifier, card name, token, URL containing user data, or real collection fixture is committed.

## Verified workflow

Dex Collection and Search return paginated objects containing `page`, `pageSize`, `result`, `totalItems`, and `totalPages`. CardRelay captures them only after the user manually arms the relevant target in the extension. The observer derives a pagination request template from a request Dex already made and replays only its page parameter at a 200 ms interval. It does not guess or hard-code an undocumented endpoint.

The live catalog completed at its visible 457-page total without scrolling. The extension retained the catalog in tab memory and transferred it to the loopback companion in ordered chunks of at most eight pages. The companion validated the complete page sequence and stored a read-only destination snapshot and catalog cache. Writes remained disabled.

## Sanitized boundary model

Only these fields cross from Dex into the companion:

- page number, page size, total items, and total pages;
- card identifier, name, collector number, relational set identifier, and nested set name/public code;
- outer variant role and nested variant finish name;
- collection card identifier and non-negative integer quantity map.

The observer strips account identifiers, timestamps, images, market data, URLs, and unrelated nested metadata. Collection pages use Chrome session storage only to survive navigation to Search. Catalog pages are never placed in extension storage.

Dex uses `card.setId` as a relational identifier and nested `card.set.setId` as the public set code; equality between them is neither expected nor required. CardRelay uses the nested public code for canonical identity. Likewise, variant outer `type` values such as layout roles are not finish labels. CardRelay normalizes the nested variant name and reports unknown labels rather than guessing.

## Completeness and persistence

A capture is accepted only when every page from one through `totalPages` is present, page metadata is consistent, and the summed result count equals `totalItems`. Chunk identifiers, counts, and ordering must also be consistent. The aggregate upload is capped at 16 MiB.

Supported finish labels become canonical destination catalog records. Unsupported catalog labels or collection quantity keys are returned as non-sensitive diagnostics and set `normalization_complete=false`; the stored destination snapshot is then incomplete. Zero quantities do not create collection records. A successful capture replaces the prior Dex read snapshot and refreshes the persistent Dex catalog cache.

The fictional integration fixture is `tests/fixtures/dex/extension_capture.json`. It contains no live account or card data.

## Known limits

- Dex authentication remains entirely user-controlled in normal Chrome.
- The extension is an unpacked development build.
- Language, condition, edition, grading, and every possible finish label are not yet proven by the live sample. Unknown distinctions fail closed.
- The destination adapter is read-only. Additions, increases, retries, confirmations, audit logs, and idempotent writes belong to Milestone 5 and require a separately verified write contract and design approval.
- Quantity decreases and removals remain disabled regardless of capture completeness.
