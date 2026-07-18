# CardRelay

> Sync your trading card collection from one source of truth to every app.

CardRelay is an early open-source trading-card collection synchronization engine. Collectr is the authoritative collection; destinations are reconciled toward it through previewable plans. A Collectr Pro CSV can provide a fast one-time baseline, but it is **not required**: the user-controlled browser source supports both initial and ongoing synchronization for free and Pro users.

## Current status

Milestone 1 is complete. Milestone 2 provides a visible persistent Collectr session, verified portfolio discovery, structured response capture, infinite scrolling, embedded-data and DOM fallbacks, completeness diagnostics, sanitized fixtures, CSV equivalence tests, and browser snapshots. Browser extraction remains experimental: it can drive additions and quantity increases, but its reliability gate deliberately prevents decreases and removals. Dex remains scaffolded for later milestones.

Safety defaults matter: every sync is a dry run, writes require explicit application action, ambiguous records are never applied, and decreases/removals remain blocked unless separately enabled with thresholds. Incomplete sources cannot authorize destructive operations.

An ongoing browser observation may contain only part of a portfolio. CardRelay may plan safe additions or quantity increases for cards actually observed, but absence from a partial observation never means zero and cannot authorize a decrease or removal. Browser snapshots are not considered safe for destructive reconciliation even when their own completeness checks pass. Reliability criteria must be approved and demonstrated separately before that policy can change.

## Requirements

- Python 3.12 or newer;
- [uv](https://docs.astral.sh/uv/) for the Python environment;
- Google Chrome for the development extension workflow;
- a locally authenticated Collectr account for browser capture.

## Project installation

From the repository root:

```bash
uv sync --all-extras --dev
uv run card-relay doctor
```

`doctor` should report a writable data directory and an available browser integration. Playwright is retained for fixture research and diagnostics; install its browser only when working on that experimental path:

```bash
uv run playwright install chromium
```

## Recommended browser-extension workflow

The extension is the recommended ongoing import path for free and Pro Collectr users. It runs inside the normal Chrome tab where the user is already authenticated, avoiding automated Google sign-in. It captures a manual preview only; it cannot write to Dex or another destination.

### 1. Start the local companion

Keep this command running in a terminal at the repository root:

```bash
uv run card-relay extension serve
```

The command binds to `127.0.0.1:8765`, prints a new pairing token, and reports that destination writes are disabled. The token is intentionally ephemeral: copy it for the current run and never post it in an issue, log, or screenshot. Use a different port when needed:

```bash
uv run card-relay extension serve --port 8877
```

### 2. Load the unpacked extension

1. Open `chrome://extensions` in Google Chrome.
2. Enable **Developer mode**.
3. Select **Load unpacked**.
4. Choose the repository's `extension` directory—the directory containing `manifest.json`, not the repository root.
5. Optionally pin **CardRelay Collectr Bridge** from Chrome's extensions menu.

After changing extension source files, select **Reload** on the extension card and reload any already-open Collectr tabs so the new content scripts are installed.

### 3. Pair CardRelay

1. Select the CardRelay extension icon.
2. Leave the companion port at `8765`, unless the server was started with another port.
3. Paste the token printed by `extension serve` into **Pairing token**.
4. Select **Save pairing**.

The token is stored only in this local Chrome extension profile. Restarting the companion invalidates it and requires saving the newly printed token.

### 4. Capture and preview Collectr

1. Sign in to Collectr normally and open `https://app.getcollectr.com/portfolio`.
2. Open the CardRelay popup and select **Start portfolio capture**.
3. CardRelay records the visible Cards total, opens the Products view, and scrolls while Collectr loads its portfolio batches.
4. Reopen the popup and select **Refresh status**. Wait for **Capture is idle**. A complete observation should show contiguous pages and a terminal page.
5. Select **Send preview to CardRelay**.

The companion validates the untrusted browser payload with the same Python contract and canonical parser used by the CLI. The popup then reports the snapshot ID, unique-entry count, total quantity, and completeness. Raw response bodies are discarded after validation; SQLite stores snapshot metadata, not the extension's raw portfolio responses.

`complete` means the observed schema, 30-record pagination, empty terminal page, condition/grading metadata, and visible quantity total reconciled. `incomplete` is still useful for observed additions and increases, but omitted cards remain unknown and cannot authorize decreases or removals.

### Troubleshooting the extension

- **CardRelay content script is unavailable:** reload the Collectr tab after installing or reloading the extension.
- **Pairing required:** start the companion, copy its current token and port, then save pairing again.
- **Companion unavailable:** confirm the terminal is still running and that the popup port matches it. Only loopback connections are accepted.
- **Capture not ready:** return to the portfolio overview and start a fresh capture. Aggregate views, conflicting pages, or offset gaps are rejected.
- **Terminal page says no:** wait for capture to become idle and retry. The preview remains incomplete if Collectr never returns its empty terminal batch.
- **Preview is incomplete with entries:** CardRelay retained safe ungraded records but could not resolve every condition or graded-card lookup. Omitted or lossy rows are reported and destructive planning stays blocked.
- **Google rejects Playwright login:** use the extension in normal Chrome. CardRelay does not weaken browser security or disguise automation to bypass that rejection.

See the focused [extension guide](extension/README.md), [security and architecture details](docs/browser-extension.md), and [Collectr web contract](docs/collectr-browser-research.md).

## CSV workflow

Collectr Pro CSV remains the fastest optimized baseline, but it is not required:

```bash
uv run card-relay collectr validate --csv tests/fixtures/collectr/plausible_export.csv
uv run card-relay collectr import --csv tests/fixtures/collectr/plausible_export.csv
uv run card-relay collectr snapshot --csv tests/fixtures/collectr/plausible_export.csv
uv run card-relay match --csv tests/fixtures/collectr/plausible_export.csv --destination mock
uv run card-relay plan --csv tests/fixtures/collectr/plausible_export.csv --destination mock
uv run card-relay sync --csv tests/fixtures/collectr/plausible_export.csv --destination mock
```

An explicit local mock write remains limited to additions and quantity increases:

```bash
uv run card-relay sync --csv tests/fixtures/collectr/plausible_export.csv --destination mock --apply
```

The browser source keeps private product payloads in memory only long enough to validate and normalize them. The extension preserves only bounded condition and grading lookup metadata in browser-session storage across navigation. It requests no undocumented write operation, does not bypass login, CAPTCHA, access-control, or rate-limit behavior, and fails closed when completeness evidence is insufficient. Dex transport remains disabled pending its read-only milestone.

## Architecture

`Collectr source → canonical collection → identity matching → sync plan/policy → destination adapter`. The core never depends on CSV, Playwright, browser-extension APIs, Dex, or UI details. See [architecture](docs/architecture.md), [integrations](docs/integrations.md), and [adapter guidance](docs/adapter-development.md).

Local snapshots may contain private collection metadata. Authentication state is never placed in snapshots and browser profiles remain local and ignored. Users are responsible for complying with each platform's terms; CardRelay does not bypass access controls, anti-bot systems, or rate limits.

Run `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, and `uv run mypy src`. Contributions follow [CONTRIBUTING.md](CONTRIBUTING.md). Roadmap: finish browser-extension capture reliability, persistent matching review, researched Dex read-only support, safe writes, controlled destructive sync, then more adapters and extension automation.
