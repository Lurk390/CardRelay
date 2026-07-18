# ADR 0002: Collectr source strategy

Accepted. CSV is an optional one-time baseline path when available because it is local, fast, and testable. It is not the ongoing synchronization mechanism and is not required: a complete browser extraction can also establish the initial baseline, and free users need browser ingestion.

After bootstrap, browser ingestion may produce either a complete portfolio snapshot or an explicitly partial observation. Partial observations contain authoritative positive facts only for the records actually observed. They may support safe additions and quantity increases, but an omitted record is unknown rather than absent and must never be interpreted as quantity zero.

CSV rows that are watchlist-only and have no held quantity are excluded explicitly. A held row that lacks a safe identity field such as collector number, or uses an unverified finish, is reported and skipped, and the resulting baseline is marked incomplete rather than silently treated as authoritative. Duplicate quantities across different conditions may be aggregated only with an explicit `mixed` condition marker, warning, and incomplete status until the canonical holding model can preserve condition-level quantity breakdowns.

Authentication remains in a visible user-controlled local browser and state stays local. Prefer structured responses over embedded data and DOM. CSV and browser paths converge on the same canonical source contract, with extraction completeness carried alongside the records.

