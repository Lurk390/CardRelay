# CardRelay

> Sync your trading card collection from one source of truth to every app.

CardRelay is an early open-source trading-card collection synchronization engine. Collectr is the authoritative collection; destinations are reconciled toward it through previewable plans. A Collectr Pro CSV can provide a fast one-time baseline, but it is **not required**: the user-controlled browser source supports both initial and ongoing synchronization for free and Pro users.

## Current status

Milestones 1 through 4 are implemented. The browser source provides a visible persistent Collectr session, verified portfolio discovery, structured response capture, infinite scrolling, embedded-data and DOM fallbacks, completeness diagnostics, sanitized fixtures, CSV equivalence tests, and browser snapshots. Destination catalogs are canonically normalized and cached; constrained probable scoring, ambiguity review, match explanations, confirmed mappings, and multiple rejected candidates persist in SQLite. The extension captures Dex's catalog and current collection into a validated local snapshot for comparison, then supports explicitly confirmed safe additions and quantity increases only.

The approved Milestone 5–6 safety foundation is in progress: CLI plans include a card-level visual diff, state-bound destructive confirmation code, stale-preview detection, persistent managed destination scope, and automatic pre-destructive recovery snapshots. The extension displays the same Collectr-to-Dex diff and can apply the separately verified Dex add/increase operations with an explicit, state-bound confirmation code. Decreases and removals remain disabled.

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

The extension is the recommended ongoing import path for free and Pro Collectr users. It runs inside the normal Chrome tab where the user is already authenticated, avoiding automated Google sign-in. It captures a manual preview and can apply explicitly confirmed safe Dex changes; it cannot reduce quantities, remove cards, or write to another destination.

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
5. Optionally pin **CardRelay Bridge** from Chrome's extensions menu.

After changing extension source files, select **Reload** on the extension card and reload any already-open Collectr or Dex tabs so the new content scripts are installed. Reloading the extension during a capture clears its in-memory progress.

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

The companion validates the untrusted browser payload with the same Python contract and canonical parser used by the CLI. The popup then reports the snapshot ID, unique-entry count, total quantity, and completeness. Raw response bodies are discarded after validation; SQLite stores the normalized collection and snapshot metadata locally so it can build later diffs, never the extension's raw portfolio responses.

`complete` means the observed schema, 30-record pagination, empty terminal page, condition/grading metadata, and visible quantity total reconciled. Metadata may come from observed read responses or Collectr's two verified expiring cache entries; CardRelay never enumerates other browser storage. `incomplete` is still useful for observed additions and increases, but omitted cards remain unknown and cannot authorize decreases or removals.

### Troubleshooting the extension

- **CardRelay content script is unavailable:** reload the Collectr tab after installing or reloading the extension.
- **Pairing required:** start the companion, copy its current token and port, then save pairing again.
- **Companion unavailable:** confirm the terminal is still running and that the popup port matches it. Only loopback connections are accepted.
- **Capture not ready:** return to the portfolio overview and start a fresh capture. Aggregate views, conflicting pages, or offset gaps are rejected.
- **Invalid capture JSON/contract/source:** the companion reports which validation stage rejected the preview without echoing private card data. Reload the extension and Collectr tab after an extension update; otherwise preserve the status counts and report the stage.
- **Terminal page says no:** wait for capture to become idle and retry. The preview remains incomplete if Collectr never returns its empty terminal batch.
- **Preview is incomplete with entries:** CardRelay retained safe ungraded records but could not resolve every condition or graded-card lookup. Omitted or lossy rows are reported and destructive planning stays blocked.
- **Google rejects Playwright login:** use the extension in normal Chrome. CardRelay does not weaken browser security or disguise automation to bypass that rejection.

### Capture a read-only Dex snapshot

1. Keep `card-relay extension serve` running and use the same saved pairing.
2. Sign in to Dex normally, open **Dashboard → Collection**, open CardRelay, and select **Start Dex collection capture**. Refresh status until collection capture is complete and the active target returns to `none`.
3. Open Dex **Search**, open CardRelay, and select **Start Dex catalog capture**.
4. Keep that Search tab open. CardRelay replays the already-observed paginated read request at a bounded rate; no scrolling is required. Refresh status until every catalog page is present.
5. Select **Send Dex read-only preview**. The extension sends bounded chunks to the loopback companion, which validates pagination, normalizes supported finish labels, caches the catalog, and stores the destination snapshot.
6. After a Collectr capture and Dex capture are stored, select **Build visual diff** to review additions, increases, decreases, removals, and records blocked for mapping review.
7. In **Match review**, compare the complete Collectr and Dex printing identities. Select a candidate and choose **Confirm match** only when they represent the same printing, or choose **Reject candidate** to exclude it. Each decision is revalidated against the latest captures, persisted in local SQLite, and immediately rebuilds the diff.

The match queue displays 50 records at a time and refreshes after every decision; summary counts cover the complete queue. Confirmations and rejections survive browser and companion restarts, but stale decisions and destination IDs not offered by the current matcher are rejected. The catalog remains only in the active Dex tab until submission; collection pages use Chrome session storage only so they survive the Collection-to-Search navigation. Missing or unknown finish labels are reported and mark normalization incomplete.

When the preview offers **Apply safe Dex changes**, verify the highlighted diff, type its displayed 12-character confirmation code, and apply the batch from an open Dex tab. CardRelay can only create cards or raise quantities. It uses the verified `clients.dextcg.com` collection routes, preserves every existing Dex quantity key on updates, retries only idempotent `PATCH` requests, and records each attempt locally. After any attempt—including a partial or uncertain failure—capture Dex again before preparing another batch. This prevents a stale preview from replaying an addition.

The popup also includes an explicitly armed **Dex write-contract research** mode for development. After arming it, the user manually makes one small, reversible Dex collection change and then validates the observation. CardRelay captures only the HTTP method, a route template with dynamic segments removed, query-key names, bounded JSON type/property shapes, and response status. Scalar values, full URLs, headers, cookies, tokens, identifiers, and card data are discarded in the page; the request is never replayed and destination writes remain disabled.

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

## Matching review

Exact canonical identities match automatically. A probable candidate must share exact game, set, and collector-number anchors and satisfy the configured language and variant gates. It still cannot sync until explicitly confirmed. Near-tied candidates are ambiguous and are never guessed.

```bash
uv run card-relay match --csv tests/fixtures/collectr/plausible_export.csv --destination mock --details --json
uv run card-relay mappings review --destination mock --json
uv run card-relay mappings confirm SOURCE_FINGERPRINT DESTINATION_ID --destination mock
uv run card-relay mappings reject SOURCE_FINGERPRINT DESTINATION_ID --destination mock
uv run card-relay catalog cache-status --destination mock --json
```

Match output explains scores, matched and mismatched fields, and alternatives. Rejections remain excluded on later runs; confirmations become exact persistent mappings. See [matching and persistent review](docs/matching.md) for the scoring weights, configuration, safety behavior, and SQLite cache semantics.

An explicit local mock write remains limited to additions and quantity increases unless destructive policy flags, thresholds, and the state-specific confirmation code are supplied:

```bash
uv run card-relay sync --csv tests/fixtures/collectr/plausible_export.csv --destination mock --apply
```

For a controlled destructive mock run, generate the plan first and review every item in `changes`:

```powershell
uv run card-relay plan --csv collection.csv --destination mock --allow-quantity-decreases --allow-removals --maximum-removal-count 10 --maximum-removal-percent 5 --json
uv run card-relay sync --csv collection.csv --destination mock --apply --yes --allow-quantity-decreases --allow-removals --maximum-removal-count 10 --maximum-removal-percent 5 --confirm-destructive CODE_FROM_PLAN --json
```

`--yes` skips only the safe-write prompt. The destructive code changes whenever the source, destination state, or operations change. A destructive run stores a local destination backup first. Destination-only records that CardRelay has never managed are shown for manual review rather than deleted.

The browser source keeps private product payloads in memory only long enough to validate and normalize them. The extension preserves only bounded condition/grading metadata and sanitized Dex collection pages in browser-session storage across navigation. Large Dex catalog pages remain tab-memory-only and cross the loopback boundary in bounded chunks. It requests no undocumented write operation, does not bypass login, CAPTCHA, access-control, or rate-limit behavior, and fails closed when completeness evidence is insufficient.

## Architecture

`Collectr source → canonical collection → identity matching → sync plan/policy → destination adapter`. The core never depends on CSV, Playwright, browser-extension APIs, Dex, or UI details. See [architecture](docs/architecture.md), [integrations](docs/integrations.md), and [adapter guidance](docs/adapter-development.md).

Local snapshots may contain private collection metadata. Authentication state is never placed in snapshots and browser profiles remain local and ignored. Users are responsible for complying with each platform's terms; CardRelay does not bypass access controls, anti-bot systems, or rate limits.

Run `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, and `uv run mypy src`. Contributions follow [CONTRIBUTING.md](CONTRIBUTING.md). Use `card-relay destinations --json` to inspect the shipped adapter capabilities. Roadmap: controlled destructive sync after browser reliability gates are met, and later extension automation.
