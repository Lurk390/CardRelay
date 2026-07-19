# Integrations

CSV is the fastest verified local baseline workflow when a user has an export, not a product requirement or the ongoing synchronization mechanism. Browser ingestion is available for free users and subsequent synchronization through the unpacked extension in a normal authenticated Collectr tab; the earlier Playwright profile remains an experimental diagnostic path because Google authentication may reject automated browsers. A browser observation may be complete or explicitly partial; partial observations can contribute additions and increases but cannot establish that an omitted card was removed. Structured responses are preferred, then embedded data, with DOM extraction last. Dex has a manually verified read-only extension workflow; all Dex writes remain disabled.

The CSV adapter recognizes both the compact fictional schemas used in tests and the verified Collectr portfolio headings such as `Category`, `Product Name`, `Card Number`, `Variance`, `Grade`, `Card Condition`, `Quantity`, and `Watchlist`. Watchlist-only rows without held quantity are excluded explicitly. Unsupported held rows are reported by row number without private card values; if such a row cannot be identified safely, the resulting source is incomplete and cannot authorize destructive planning.

Collectr remains the multi-game source of truth. Game filtering is destination-specific: Dex declares Pokémon as its only supported game, so non-Pokémon source records appear as non-executable unsupported operations in a Dex plan and are never written or treated as removal candidates. They remain available for future destination adapters.

## Collectr browser contract

The verified web client uses `/portfolio` for overview totals and `/portfolio/products` for holdings. It requests portfolio products from the Collectr API in 30-record offset batches and performs one terminal request that returns an empty `data` list. CardRelay captures only those product responses, validates required fields, orders offsets from zero without gaps, and discards raw responses after normalization. Condition and grading identifiers must resolve through metadata responses observed in the same local session or the client's two verified, expiring metadata-cache entries; unknown identifiers are skipped and force an incomplete source.

Completeness requires recognized schema, consecutive batches, an observed empty terminal page, no invalid card records, and equality between normalized card quantity and the visible Cards total. An optional unique-record total must also agree when available. A DOM fallback never guesses a game or missing identity field, and embedded data is treated as partial unless separate end-of-pagination evidence exists.

Even a complete browser snapshot has `trusted_for_destructive_planning=false`. The measurable promotion gates and their current status are maintained in [browser source reliability](browser-source-reliability.md). Decreases and removals remain disabled for browser extraction until every gate is met and the user explicitly approves the policy change.

Users must comply with platform terms. No integration may bypass access controls, CAPTCHAs, rate limits, or anti-bot protections.

## Dex read-only contract

The extension captures only manually armed responses from Dex Collection and Search pages. It sanitizes identity, pagination, finish-label, and quantity fields in the page, retains the large catalog only in tab memory, and submits ordered chunks to the loopback companion. The companion validates complete pagination before replacing the Dex destination snapshot and catalog cache.

Dex distinguishes a card's relational `setId` from the nested set's public `setId`; CardRelay uses the nested public value as the canonical set code. Variant outer types describe layout roles, while the nested variant name carries the finish label. Unknown labels are surfaced, not guessed, and make the destination snapshot incomplete. No endpoint, payload, or capability for writes is implemented.

