# Browser extension architecture

CardRelay uses an unpacked Chrome Manifest V3 extension to operate inside the user's normal authenticated Collectr session. This replaces automated Google authentication while preserving the existing source boundary:

```text
Collectr page
  -> main-world response observer
  -> isolated content-script capture buffer
  -> extension service worker
  -> token-authenticated 127.0.0.1 companion
  -> existing Collectr web-contract parser
  -> canonical collection and source snapshot
```

The main-world observer is necessary because Manifest V3 `webRequest` cannot read response bodies. It wraps `fetch` and `XMLHttpRequest` at `document_start`, clones only responses from the verified Collectr collection-products, card-condition, and grading endpoints, and leaves the application's original response untouched. When the client serves condition or grading metadata from its own cache instead of making those requests, the observer reads only the verified `cardConditions` and `gradedCardScales` cache entries. It validates their expiration wrapper, applies a 512 KiB limit, and never enumerates local storage. It never forwards request headers, cookies, tokens, URLs containing collection identifiers, profile data, or responses from unrelated endpoints.

The isolated content script accepts messages only from the same page window and origin. It retains private product responses in memory, requires the exact/unstacked view, orders pages by verified offsets, detects conflicting repeated pages, and drives user-initiated infinite scrolling. It preserves only bounded condition and grading lookup responses in session storage across the overview-to-products navigation. The Collectr page remains an untrusted external boundary: the Python companion validates every payload again with Pydantic and the existing canonical parser.

The service worker is the only extension component allowed to contact `http://127.0.0.1`. The companion binds only to IPv4 loopback, validates the Host header, limits request bodies to 16 MiB, requires a high-entropy ephemeral bearer token, disables access logging, and returns counts and diagnostics rather than card data. It has no destination-write endpoint.

Partial previews are first-class results. A missing condition lookup does not discard an otherwise valid ungraded holding: its condition becomes unknown, the row is counted as lossy, and completeness remains incomplete. A non-null graded identifier other than Collectr's verified ungraded sentinel still requires a recognized grading lookup and is omitted when that identity cannot be proven.

The preview reports non-sensitive invalid-record reason counts—capture errors, aggregate-view records, missing identity, unsupported finish, unresolved condition or grading, non-positive quantity, and conflicting conditions. These counts make contract drift diagnosable without exposing card names or raw responses.

Permissions are intentionally narrow:

- `https://app.getcollectr.com/*` for the response observer and popup orchestration;
- `http://127.0.0.1/*` for the companion request;
- `storage` for pairing settings and navigation state;
- `activeTab` for the user-initiated transition from portfolio overview to Products;

No broad browsing-history, debugger, cookies, downloads, or all-sites permission is requested.

This is the initial manual-preview slice of Milestone 8, intentionally brought forward to unblock Milestone 2 authentication. Periodic checks, notifications, packaged distribution, secure update delivery, Dex writes, and any destructive synchronization remain out of scope.
