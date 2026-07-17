# Dex research checklist

Using only one's own visible authenticated session, document login expiry, catalog identifiers/search, collection reads, add/update/remove behavior, validation errors, rate limits, idempotency, and timeouts. Sanitize fixture URLs, headers, cookies, tokens, user identifiers, and collection data. Do not ship private endpoints or enable writes until contracts and retries are tested.

The initial research harness opens `https://app.dextcg.com/` in a visible persistent local Chromium profile. `card-relay dex inspect` reports response counts and status classes only. It never records URLs, headers, cookies, or bodies. This metadata can establish whether structured responses exist but cannot establish their schema or collection completeness.
