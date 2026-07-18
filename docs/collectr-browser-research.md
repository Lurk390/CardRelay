# Collectr browser contract and research record

Verified against the visible Collectr web client on 2026-07-18:

- the official portfolio routes are `/portfolio` and `/portfolio/products`;
- unauthenticated portfolio access redirects to `auth.getcollectr.com`;
- the products view loads 30 records per offset batch through the API's collection-products route;
- the client continues while a response contains records, so the empty terminal response is required pagination evidence;
- the response fields consumed by the client include product and owned-record identifiers, product name, game/category, set/group, card number, subtype/finish, condition identifier, quantity, grading identifier, rarity, language when available, card/product type, and watchlist state;
- the current portfolio bundle uses grade ID `52` as its ungraded sentinel; other non-null grade IDs still require a recognized grading-scale lookup;
- the overview exposes a Cards quantity total; it is not a unique-product count;
- the rendered grid contains set, collector number, condition, finish, and quantity, but not a reliable game field, so DOM fallback must not guess game identity;
- no current `application/json` script containing portfolio records was observed, so embedded parsing remains a bounded fallback rather than the preferred path.

Raw response bodies and account identifiers are never written to fixtures, diagnostics, logs, or snapshots. Tests use only fictional sanitized payloads. Schema fingerprints retain field names, strategy, and contract version but no scalar collection values. Collection extraction fails closed when page discovery, response shape, batch ordering, visible totals, conditions, grading, or card identity cannot be validated.

The browser integration does not bypass sign-in, human-verification challenges, access controls, rate limits, or anti-bot protections. Authentication occurs in a visible user-controlled persistent profile and can be removed with `collectr clear-session`.

Google can reject authentication in Playwright-launched browsers even when credentials are correct. CardRelay does not attempt to disguise or bypass that automation context. The supported development path is the unpacked extension operating in the user's normal authenticated Collectr tab and sending captures to the loopback-only companion.
