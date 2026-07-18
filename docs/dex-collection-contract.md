# Dex collection read contract

This provisional contract is derived from a schema-only inspection of a user-controlled Dex
collection page on 2026-07-17. The inspection retained property names, JSON types, and coarse array
cardinality only. It did not retain URLs, response bodies, scalar values, account identifiers, or
card data.

The fictional fixtures are:

- `tests/fixtures/dex/collection_page_empty.json`
- `tests/fixtures/dex/collection_page_one_card.json`

## Observed structure

The response is a paginated object with `page`, `pageSize`, `result`, `totalItems`, and
`totalPages`. A collection entry contains nested `card` catalog data, `cardId`, timestamps, an
entry `id`, `userId`, and a `quantities` object. The observed single entry used a numeric `holo`
quantity. Card catalog structure included card and set identifiers, collector number, variants,
artist, rarity and regulation references, images, markets, and related catalog metadata.

## Unresolved contract questions

- The endpoint path and transport contract remain intentionally unrecorded.
- Collection completeness and pagination behavior are not verified.
- Only one populated entry and one `holo` quantity key were observed.
- Other finishes, quantity keys, languages, conditions, editions, grading states, and games are
  unverified.
- Nested `market`, `region`, and `variant` object fields were beyond the bounded schema depth and
  remain empty in the fictional fixture rather than being invented.
- No response validation model or parser exists yet.
- No Dex write contract is known or enabled.

These fixtures are research contracts only. They must not authorize destructive planning or
collection completeness claims.
