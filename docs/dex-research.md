# Dex research checklist

Using only one's own visible authenticated session, document login expiry, catalog identifiers/search, collection reads, add/update/remove behavior, validation errors, rate limits, idempotency, and timeouts. Sanitize fixture URLs, headers, cookies, tokens, user identifiers, and collection data. Do not ship private endpoints or enable writes until contracts and retries are tested.

## Extension write-schema observation

The unpacked extension provides the preferred research boundary for write contracts because it runs in the user's normal authenticated Chrome session without reading credentials. The user must explicitly arm **Dex write-contract research** and manually perform one small, reversible collection change. CardRelay does not initiate or replay that request.

Before an observation leaves the page, CardRelay removes all scalar values and records only a bounded JSON shape, HTTP method, response status, the validated Dex service hostname, query-key names, and an origin-free route template whose unknown segments are replaced with `{segment}`. When exact equality is observed, it may also record a value-free relationship such as `segment 3 = request.cardId`; the identifier value itself remains private. Dynamic property names become `{dynamic_key}`. Only HTTPS `/api/...` requests to `dextcg.com` or its subdomains are eligible, so analytics and performance telemetry are ignored even when Dex routes it through a Dex-owned host. Full URLs, non-Dex hosts, headers other than a transient content-type check, cookies, tokens, account/card identifiers, quantities, notes, and response values never cross the page boundary. The companion validates that schema-only contract and echoes it for local inspection without persisting it.

## Verified safe-write contract

The observed Dex host is `clients.dextcg.com`. Adding a collection card uses `POST /api/user/cards` with `cardId` and a `quantities` object, returning `201`. Updating an existing collection record uses `PATCH /api/user/cards/{collectionRecordId}` with the card ID and the **complete** quantities object, returning `200`; the path value corresponds to `response.id`, not the catalog card ID. Both response shapes include `cardId`, `id`, `quantities`, timestamps, and `userId`.

CardRelay uses only these two verified operations, only after a state-bound visual preview and typed confirmation code. It preserves all raw Dex quantity keys when PATCHing, retries PATCH only for transient failures, and does not automatically retry POST. It never enables quantity decreases or removals. A Dex recapture is required after every write attempt, including an uncertain one.

The initial research harness opens `https://app.dextcg.com/` in a visible persistent local Chromium profile. `card-relay dex inspect` reports response counts and status classes only. It never records URLs, headers, cookies, or bodies. This metadata can establish whether structured responses exist but cannot establish their schema or collection completeness.

Schema research is a separate, explicitly acknowledged mode. `card-relay dex inspect-schema`
attaches only to a loopback CDP browser, reloads the currently open page, and transiently parses
structured responses in memory. It emits property names, JSON types, coarse array cardinality, and
status classes only. Scalar values are discarded immediately; dynamic-looking property names are
redacted; response bodies, URLs, headers, cookies, tokens, identifiers, and card values are never
written or emitted. Capture is bounded by response count, declared response size, object width,
and nesting depth. Chunked responses are read only after `requestfinished`, when Playwright can
report their completed body size; responses over the same size limit are skipped. Some cached or
service-worker responses report an unknown completed size. Under the acknowledged expanded
boundary, at most three such already-finished structured responses are parsed per run. Because
some structured sync responses may be mislabeled, at most ten completed Fetch/XHR responses with
other content types are also probed as JSON. Whole-document failures receive a bounded generic
newline-delimited JSON and `data:` event-line probe; invalid bodies are counted and discarded. Tab
URLs are compared transiently to the already-known official Dex hostname solely to select a Dex
tab; they are never retained or emitted. When multiple Dex tabs exist, the inspector prefers the
tab whose document reports the content-free `visibilityState = "visible"` signal. The command does
not enable writes or establish collection completeness.

Run it only against a dedicated browser profile after reviewing this expanded boundary:

```powershell
uv run card-relay dex inspect-schema `
  --cdp-url http://127.0.0.1:9222 `
  --acknowledge-schema-inspection `
  --json
```

## Headless server with a Windows browser

Chrome 136 and later require remote debugging to use a non-default user-data directory. Start a dedicated Chrome instance from Windows PowerShell:

```powershell
& "$env:ProgramFiles\Google\Chrome\Application\chrome.exe" `
  --remote-debugging-address=127.0.0.1 `
  --remote-debugging-port=9222 `
  --user-data-dir="$env:LOCALAPPDATA\CardRelay\ChromeProfile"
```

Create the SSH connection from Windows with a reverse tunnel:

```powershell
ssh -R 127.0.0.1:9222:127.0.0.1:9222 USER@SERVER
```

On the server, verify only that `curl --fail http://127.0.0.1:9222/json/version` succeeds; do not share its output because it includes a WebSocket debugger URL. Then run:

```bash
uv run card-relay dex login --cdp-url http://127.0.0.1:9222
uv run card-relay dex inspect --cdp-url http://127.0.0.1:9222 --json
```

CDP grants control over the dedicated browser profile. Keep it bound to Windows loopback, carry it only through SSH, close Chrome when finished, and never use a normal daily-browsing profile.
