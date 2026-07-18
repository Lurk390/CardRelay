# Browser source reliability gates

Milestone 2 implements browser acquisition, parsing, diagnostics, equivalence fixtures, and snapshots. That implementation milestone does not by itself authorize destructive synchronization. Every browser snapshot continues to set `trusted_for_destructive_planning=false` until all gates below are demonstrated and the user explicitly approves changing the policy.

## Promotion gates

1. **Complete captures:** at least three distinct, user-controlled portfolios—including one free account path and one large portfolio of at least 1,000 holdings—produce zero invalid/lossy records, contiguous pagination with an empty terminal page, and an exact visible-total comparison.
2. **Repeatability:** each qualifying portfolio produces the same canonical collection fingerprint in five consecutive captures without account edits.
3. **CSV equivalence:** at least two fresh Collectr Pro exports match browser captures at canonical identity, quantity, condition, finish, language, edition, and grading dimensions. Documented source limitations must be zero or explicitly approved.
4. **Variant coverage:** sanitized fixtures and at least one user-controlled capture cover supported conditions, finishes, languages, editions, ungraded cards, and graded cards. Unknown identifiers fail closed with reason-specific diagnostics.
5. **Boundary behavior:** automated tests cover empty collections, watchlist-only rows, non-card products, large pagination, repeated/conflicting pages, missing offsets, interrupted scrolling, expired authentication, missing metadata, malformed responses, and schema changes.
6. **Privacy and security:** captures retain no credentials, headers, cookies, account identifiers, or raw private responses; only bounded metadata crosses navigation; loopback requests remain token authenticated and destination writes remain unavailable from the capture endpoint.
7. **Operational review:** CI passes on the release commit, the browser contract date and sanitized fixtures are current, recovery/session-clearing documentation is verified, and the user reviews the evidence and explicitly authorizes any destructive-policy change.

## Current status

The gates are **not yet met**. Fixture, failure-mode, privacy, pagination, and CSV-equivalence coverage exists, but the required multi-portfolio live evidence and repeated-capture record have not been completed. This status is intentionally independent from Milestone 2 implementation completion.
