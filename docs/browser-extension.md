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

Dex follows the same local trust boundary: a main-world observer sanitizes manually armed Collection and Search responses, an isolated content script validates page continuity, and the service worker sends bounded chunks to the same loopback companion. Collection pages may use session storage across the Collection-to-Search navigation; the much larger catalog remains only in the active tab's memory.

The main-world observer is necessary because Manifest V3 `webRequest` cannot read response bodies. It wraps `fetch` and `XMLHttpRequest` at `document_start`, clones only responses from the verified Collectr collection-products, card-condition, and grading endpoints, and leaves the application's original response untouched. When the client serves condition or grading metadata from its own cache instead of making those requests, the observer reads only the verified `cardConditions` and `gradedCardScales` cache entries. It validates their expiration wrapper, applies a 512 KiB limit, and never enumerates local storage. It never forwards request headers, cookies, tokens, URLs containing collection identifiers, profile data, or responses from unrelated endpoints.

The isolated content script accepts messages only from the same page window and origin. It retains private product responses in memory, requires the exact/unstacked view, orders pages by verified offsets, detects conflicting repeated pages, and drives user-initiated infinite scrolling. It preserves only bounded condition and grading lookup responses in session storage across the overview-to-products navigation. The Collectr page remains an untrusted external boundary: the Python companion validates every payload again with Pydantic and the existing canonical parser.

The service worker is the only extension component allowed to contact `http://127.0.0.1`. The companion binds only to IPv4 loopback, validates the Host header, limits each body and the aggregate Dex upload to 16 MiB, requires a high-entropy ephemeral bearer token, disables access logging, and returns counts and diagnostics rather than card data. Dex chunks must be contiguous, use one upload identifier, and carry collection pages only in the first chunk. A separate research endpoint accepts only explicitly armed, schema-only write observations with no scalar values or full URLs; it cannot replay a request and is not a destination-write endpoint.

Partial previews are first-class results. A missing condition lookup does not discard an otherwise valid ungraded holding: its condition becomes unknown, the row is counted as lossy, and completeness remains incomplete. A non-null graded identifier other than Collectr's verified ungraded sentinel still requires a recognized grading lookup and is omitted when that identity cannot be proven.

The companion persists the normalized Collectr collection locally so it can build a card-level diff against the latest Dex read snapshot. The popup renders quantities and change categories with DOM `textContent`, never HTML from card data. Preview generation updates mapping-review records and keeps unmanaged destination-only cards blocked. A separate confirmation-bound endpoint prepares at most 50 verified safe operations: additions use `POST /api/user/cards`; updates use `PATCH /api/user/cards/{collectionRecordId}` with a complete preserved quantity map. The main-world executor accepts only those two fixed routes on `https://clients.dextcg.com`, never sees credentials, retries only idempotent PATCH requests, and reports a bounded status-only result. Preparing a batch records a local attempt barrier, so a new Dex capture is required after every execution attempt.

The preview reports non-sensitive invalid-record reason counts—capture errors, aggregate-view records, missing identity, unsupported finish, unresolved condition or grading, non-positive quantity, and conflicting conditions. These counts make contract drift diagnosable without exposing card names or raw responses.

Permissions are intentionally narrow:

- `https://app.getcollectr.com/*` and `https://app.dextcg.com/*` for the response observers and popup orchestration;
- `http://127.0.0.1/*` for the companion request;
- `storage` for pairing settings and navigation state;
- `activeTab` for the user-initiated transition from portfolio overview to Products;

No broad browsing-history, debugger, cookies, downloads, or all-sites permission is requested.

This is the initial manual-preview slice of Milestone 8, intentionally brought forward to unblock Milestone 2 authentication. Periodic checks, notifications, packaged distribution, secure update delivery, and destructive synchronization remain out of scope. The only Dex writes in scope are explicitly confirmed additions and quantity increases.
