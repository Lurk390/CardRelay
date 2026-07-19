# Architecture

CardRelay uses ports and adapters: source acquisition and parsing produce a canonical collection; matching resolves identities; planning compares desired and actual quantities; policy marks operations executable or blocked; destination adapters apply only approved operations. This keeps future browser-extension delivery and platform transports outside the domain.

The Collectr browser adapter has three ordered acquisition strategies: verified structured responses, embedded response-shaped data, then a fail-closed DOM fallback. Every strategy produces the same versioned sanitized capture envelope before canonical parsing. Network pagination and user-data values stay outside the core domain; only canonical records and non-sensitive completeness evidence reach planning and snapshots.

The browser extension is another delivery mechanism for that browser-source contract. Its loopback companion validates captured web responses with the existing Python parser and stores a normal browser snapshot; extension code never owns canonical identity, matching, planning, or destination policy. See [browser extension architecture](browser-extension.md).

Fingerprint schema `v2` uses a version prefix plus SHA-256 over normalized game, set, collector number, language, finish, edition, grading state/company/grade/certification, promo, signed, and altered state. Quantity is excluded. Schema `v1` did not include certification, signed, or altered state; stored mappings require an explicit migration rather than silent reuse after a version change.

Destination catalogs pass through the same canonical identity validators, reject conflicting duplicate destination IDs, and receive deterministic ordering before matching or caching. Matching first honors confirmed mappings, then exact fingerprints, then a constrained composite score. Scoring requires exact game, set, and collector-number anchors; it never proposes a card-name-only match. Default language and variant gates exclude unsafe candidates before scoring. Probable and ambiguous results are persisted for review but the planner accepts only exact or explicitly confirmed mappings. See [matching and review](matching.md).
