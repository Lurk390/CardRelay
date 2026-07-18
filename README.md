# CardRelay

> Sync your trading card collection from one source of truth to every app.

CardRelay is an early open-source trading-card collection synchronization engine. Collectr is the authoritative collection; destinations are reconciled toward it through previewable plans. A Collectr Pro CSV can provide a fast one-time baseline, but it is **not required**: a user-controlled browser ingestion path for free users is scaffolded for Milestone 2 and will support both initial and ongoing synchronization.

## Current status

Milestone 1 is complete: it provides canonical models, configurable CSV ingestion, exact variant-sensitive matching, safe planning, a mock destination, SQLite snapshots/mappings, a CLI, fail-closed browser fixture boundaries, CI, and documentation. Collectr browser and Dex integrations remain experimental scaffolds and perform no undocumented live calls.

Safety defaults matter: every sync is a dry run, writes require explicit application action, ambiguous records are never applied, and decreases/removals remain blocked unless separately enabled with thresholds. Incomplete sources cannot authorize destructive operations.

An ongoing browser observation may contain only part of a portfolio. CardRelay may plan safe additions or quantity increases for cards actually observed, but absence from a partial observation never means zero and cannot authorize a decrease or removal. Only a separately validated complete snapshot can be considered for destructive reconciliation.

## Install and use

```bash
uv sync --all-extras --dev
uv run card-relay doctor
uv run card-relay collectr validate --csv tests/fixtures/collectr/plausible_export.csv
uv run card-relay collectr import --csv tests/fixtures/collectr/plausible_export.csv
uv run card-relay collectr snapshot --csv tests/fixtures/collectr/plausible_export.csv
uv run card-relay match --csv tests/fixtures/collectr/plausible_export.csv --destination mock
uv run card-relay plan --csv tests/fixtures/collectr/plausible_export.csv --destination mock
uv run card-relay sync --csv tests/fixtures/collectr/plausible_export.csv --destination mock
# Explicit local mock write, still limited to safe operations:
uv run card-relay sync --csv tests/fixtures/collectr/plausible_export.csv --destination mock --apply
```

Browser commands (`collectr login`, `inspect`, and related session commands) fail closed until Milestone 2. Dex transport is likewise disabled pending documented research.
The current Collectr browser research harness can open a visible, persistent local browser but does not yet claim that authentication or extraction succeeded. Install Chromium with `uv run playwright install chromium`, then use `uv run card-relay collectr login`. An explicit `--url` may be supplied during authorized research because no official Collectr web-portfolio URL has been verified.

## Architecture

`Collectr source → canonical collection → identity matching → sync plan/policy → destination adapter`. The core never depends on CSV, Playwright, Dex, or UI details. See [architecture](docs/architecture.md), [integrations](docs/integrations.md), and [adapter guidance](docs/adapter-development.md).

Local snapshots may contain private collection metadata. Authentication state is never placed in snapshots and browser profiles remain local and ignored. Users are responsible for complying with each platform's terms; CardRelay does not bypass access controls, anti-bot systems, or rate limits.

Run `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, and `uv run mypy src`. Contributions follow [CONTRIBUTING.md](CONTRIBUTING.md). Roadmap: browser fixture ingestion, persistent matching review, researched Dex read-only support, safe writes, controlled destructive sync, more adapters, then a browser extension.
