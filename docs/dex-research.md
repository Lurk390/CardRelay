# Dex research checklist

Using only one's own visible authenticated session, document login expiry, catalog identifiers/search, collection reads, add/update/remove behavior, validation errors, rate limits, idempotency, and timeouts. Sanitize fixture URLs, headers, cookies, tokens, user identifiers, and collection data. Do not ship private endpoints or enable writes until contracts and retries are tested.

The initial research harness opens `https://app.dextcg.com/` in a visible persistent local Chromium profile. `card-relay dex inspect` reports response counts and status classes only. It never records URLs, headers, cookies, or bodies. This metadata can establish whether structured responses exist but cannot establish their schema or collection completeness.

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
