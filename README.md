# CardRelay

> Sync your trading card collection from one source of truth to every app.

CardRelay is an early open-source trading-card collection synchronization engine. Collectr is the authoritative collection; destinations are reconciled toward it through previewable plans. A Collectr Pro CSV can provide a fast one-time baseline, but it is **not required**: the user-controlled browser source supports both initial and ongoing synchronization for free and Pro users.

## Current status

Milestones 1 through 4 are implemented. The browser source provides a visible persistent Collectr session, verified portfolio discovery, structured response capture, infinite scrolling, embedded-data and DOM fallbacks, completeness diagnostics, sanitized fixtures, CSV equivalence tests, and browser snapshots. Destination catalogs are canonically normalized and cached; constrained probable scoring, ambiguity review, match explanations, confirmed mappings, and multiple rejected candidates persist in SQLite. The extension captures Dex's catalog and current collection into a validated local snapshot for comparison, then supports explicitly confirmed safe additions and quantity increases, plus an opt-in single-managed-card removal test.

The approved Milestone 5–6 safety foundation is in progress: CLI plans include a card-level visual diff, state-bound destructive confirmation code, stale-preview detection, persistent managed destination scope, and automatic pre-destructive recovery snapshots. The extension displays the same Collectr-to-Dex diff and can apply the separately verified Dex add/increase operations with an explicit, state-bound confirmation code. Removals are disabled by default; an explicitly enabled, single-managed-card test mode is available to validate Dex behavior without promoting general destructive synchronization.

Safety defaults matter: every sync is a dry run, writes require explicit application action, ambiguous records are never applied, and decreases/removals remain blocked unless separately enabled with thresholds. Incomplete sources cannot authorize destructive operations.

An ongoing browser observation may contain only part of a portfolio. CardRelay may plan safe additions or quantity increases for cards actually observed, but absence from a partial observation never means zero and cannot authorize a decrease or removal. Browser snapshots are not considered generally safe for destructive reconciliation even when their own completeness checks pass. Reliability criteria must be approved and demonstrated separately before that policy can change. The controlled removal test described below is a bounded exception for one previously managed disposable card; it does not enable bulk reconciliation or quantity decreases.

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

The extension is the recommended ongoing import path for free and Pro Collectr users. It runs inside the normal Chrome tab where the user is already authenticated, avoiding automated Google sign-in. It captures a manual preview and can apply explicitly confirmed safe Dex changes. It cannot reduce quantities, remove unmanaged cards, perform general destructive reconciliation, or write to another destination; the opt-in test mode can zero one managed disposable-card finish.

### 1. Start the local companion

Keep this command running in a terminal at the repository root:

```bash
uv run card-relay extension serve
```

The command binds to `127.0.0.1:8765`, prints a new pairing token, enables preview-confirmed additions and increases, and reports that Dex removals are disabled. The token is intentionally ephemeral: copy it for the current run and never post it in an issue, log, or screenshot. Use a different port when needed:

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

### 4. Capture Collectr

1. Sign in to Collectr normally and open your portfolio.
2. Open CardRelay and select **Capture Collectr**. CardRelay opens the Products view and scrolls while Collectr loads the collection.
3. Reopen CardRelay when capture finishes. Select **Save Collectr capture** when it appears.

The popup shows a short success or attention message instead of pagination internals. The extension workflow retains only Pokémon entries; other TCGs are ignored and reported in the save summary. Every successful scan is retained locally with its timestamp in `card-relay.db`; reopening or refreshing the popup automatically reuses the latest saved scan and shows its age, Pokémon totals, and backup count. Scan again whenever Collectr changes, especially before planning removals. The companion validates the complete untrusted browser payload, discards raw response bodies, and stores only the normalized Pokémon collection and snapshot metadata locally. An incomplete capture can support observed additions, but never removals.

### 5. Capture Dex and sync

1. Open Dex **Dashboard → Collection**, open CardRelay, and select **Capture collection**.
2. Open Dex **Search**, then select **Capture catalog**.
3. When both are ready, select **Save Dex capture**. CardRelay automatically refreshes the sync review.
4. Use the four summary counts to review additions, updates, removals, and records needing attention. Card details stay collapsed unless you open **View card changes**.
5. Resolve **Match review** only when CardRelay cannot safely identify a printing. Select individual rows or use **Select suggested**, verify the proposed Dex identities, then confirm or reject the selected rows together. Ambiguous rows are not selected automatically.
6. For additions and increases, select the single **Sync changes** button. No typed code is required for these non-destructive writes.
7. Capture Dex again after every write attempt to verify the result and unlock the next sync.

CardRelay uses the verified `clients.dextcg.com` routes, preserves every existing Dex quantity key on updates, retries only idempotent PATCH requests, and records each attempt locally. The catalog remains in tab memory; collection capture uses Chrome session storage only across the Collection-to-Search navigation.

### Controlled live removal test

Use a disposable card and first sync it through CardRelay so its Dex printing/finish becomes managed. Recapture Dex and verify the addition. Then remove that same printing/finish from Collectr, complete a fresh Collectr capture, and start the companion with:

```powershell
uv run card-relay extension serve --enable-removal-test --maximum-removal-count 1 --maximum-removal-percent 100
```

Save the new captures and review the red removal. CardRelay automatically expands the card list when an executable removal exists. Type the displayed code under **Approve removals**, keep Dex open, and select **Remove approved cards**. CardRelay stores a recovery backup, preserves unrelated quantity keys, and sets only the managed finish to zero. Capture Dex again immediately to verify the live result.

This mode does not enable quantity decreases, unmanaged deletions, incomplete captures, stale retries, or removals beyond the configured thresholds.

### Troubleshooting the extension

- **CardRelay is not active:** reload the extension first, then reload the Collectr or Dex tab.
- **Connection says Set up:** start the companion, open **Connection**, paste its current token, and save.
- **Capture remains incomplete:** return to the portfolio or Dex collection and run that capture again. CardRelay deliberately does not expose or override failed safety checks.
- **Sync asks for another Dex capture:** recapture Dex to verify the previous attempt before continuing.
- **A match needs review:** compare the complete printing identity. Reject it if any meaningful identity field differs.
- **Google rejects Playwright login:** use the extension in normal Chrome; CardRelay does not weaken browser security.

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

Exact canonical identities match automatically. CardRelay also auto-confirms a sole 100% composite candidate when every compared identity field agrees. A probable candidate must share exact game, set, and collector-number anchors and satisfy the configured language and variant gates, but it still cannot sync until explicitly confirmed. Rounded near-100%, competing, and near-tied candidates are never auto-confirmed.

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
