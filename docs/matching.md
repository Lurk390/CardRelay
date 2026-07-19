# Matching and persistent review

CardRelay resolves a Collectr identity to a destination catalog record in a deterministic order:

1. A user-confirmed persistent mapping whose destination ID still exists in the current catalog.
2. One exact canonical fingerprint match.
3. A constrained probable match requiring human confirmation.
4. An ambiguous, rejected, or unmatched review result.

Only the first two outcomes are represented as `exact` and can reach normal sync planning. `probable` and `ambiguous` always produce a blocked `manual_review_required` operation. Confirming a probable candidate turns that source fingerprint and destination ID into a persistent exact mapping on the next run.

## Catalog normalization and cache

Destination identities use the same Unicode, whitespace, case, collector-number, language, finish, edition, grading, and special-flag normalization as source identities. Duplicate catalog rows with the same destination ID and identity collapse deterministically. Reusing one destination ID for conflicting identities rejects the catalog instead of guessing.

Every CLI match, plan, or sync refreshes the normalized catalog cache in one SQLite transaction. The previous cache is replaced only when the new catalog validates. Inspect it with:

```bash
uv run card-relay catalog cache-status --destination mock --json
```

The cache contains catalog metadata, not authentication state or Collectr quantities.

## Probable scoring

A candidate is not scored at all unless game, set, and collector number are exact anchors. When both sides have set codes, those codes must match; otherwise normalized set names must match. By default, language and the complete variant tuple must also match before scoring. The tuple includes finish, edition, grading state/company/grade/certification, promo, signed, and altered flags.

Eligible candidates receive a deterministic weighted score: game `0.10`, set `0.20`, collector number `0.25`, card name `0.20`, language `0.05`, finish `0.08`, edition `0.03`, grading `0.06`, and special flags `0.03`. Only normalized card names use bounded similarity; every other field is an exact comparison. The default probable threshold is `0.92`. Candidates within `0.02` of the best score are ambiguous. Candidate ordering uses descending score followed by destination ID, so network or input order cannot change a result.

The settings are configurable:

```yaml
matching:
  minimum_probable_score: 0.92
  ambiguity_score_margin: 0.02
  allow_fuzzy_matching: true
  require_variant_match: true
  require_language_match: true
```

Disabling the language or variant gates broadens only the review queue. It never enables automatic writes for probable matches.

## Review workflow

Generate matches and include per-candidate explanations:

```bash
uv run card-relay match --csv path/to/export.csv --destination mock --details --json
uv run card-relay mappings review --destination mock --json
```

Each pending item includes the normalized source identity, status, score, matched and mismatched fields, reasons, candidate IDs, and candidate-specific explanations. Review the identity and destination record outside CardRelay before deciding:

```bash
uv run card-relay mappings confirm SOURCE_FINGERPRINT DESTINATION_ID --destination mock
uv run card-relay mappings reject SOURCE_FINGERPRINT DESTINATION_ID --destination mock
```

Multiple rejected destination IDs are retained for one source fingerprint and excluded from later matching. A confirmed mapping is unique per source fingerprint and destination. On every run, its current catalog record must still satisfy the exact game, set, and collector-number anchors; a missing or reused destination ID becomes unresolved instead of silently applying the old decision. Confirming a previously rejected candidate removes that rejection; rejecting the active confirmed candidate removes the confirmation. A partial browser observation updates review rows only for identities it actually contains, so it does not erase pending decisions for omitted cards.

Confirmed mappings remain bound to fingerprint schema `v2`. If a future fingerprint schema changes, mappings require an explicit migration rather than silent reuse.
