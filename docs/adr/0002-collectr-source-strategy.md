# ADR 0002: Collectr source strategy

Accepted. CSV is preferred when available because it is local, fast, and testable, but optional because free users need browser ingestion. Authentication remains in a visible user-controlled local browser and state stays local. Prefer structured responses over embedded data and DOM. Both paths satisfy one source contract.

