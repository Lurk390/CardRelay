# CardRelay browser bridge

This unpacked Manifest V3 extension captures Collectr source data and Dex destination data from the user's normal authenticated Chrome tabs. It sends sanitized captures only to CardRelay's loopback companion. It does not read passwords, cookies, authorization headers, or unrelated pages. After an explicit preview confirmation it can make verified Dex additions and quantity increases. A separately enabled controlled test can set one previously managed disposable card finish to zero so the removal behavior can be validated safely.

## Load and run locally

1. Open `chrome://extensions`.
2. Enable **Developer mode**.
3. Select **Load unpacked** and choose this `extension` directory.
4. Start the companion from the repository:

   ```powershell
   .\.venv\Scripts\card-relay.exe extension serve
   ```

5. Copy the displayed pairing token into the extension popup and save it. The default port is `8765`.
6. Open the Collectr portfolio overview in the active tab and select **Capture Collectr**.
7. The extension opens the Products view and scrolls while Collectr loads batches. Reopen the popup and select **Save Collectr capture** when it is ready.

## Everyday sync workflow

1. Open Collectr and select **Capture Collectr**. Reopen CardRelay when it finishes and select **Save Collectr capture**. On later popup refreshes, CardRelay automatically reuses this timestamped local scan until you save a newer one.
2. Open Dex Collection and select **Capture collection**.
3. Open Dex Search and select **Capture catalog**. Select **Save Dex capture** when it appears.
4. CardRelay automatically loads the sync summary. The four counts show additions, updates, removals, and records needing review; the card list is collapsed by default.
5. Resolve a match only when CardRelay asks. Select rows individually or use **Select suggested**, verify the chosen Dex printing, then confirm or reject the selected rows as one batch. Ambiguous rows are never selected automatically.
6. Select **Sync changes** for additions and increases. This is the single explicit approval for non-destructive writes; the popup supplies the state-bound backend code automatically.
7. Capture Dex again after every write attempt before continuing.

The connection form collapses after pairing. Capture messages describe only the next useful action; pagination, schema, and internal diagnostics stay out of the normal popup. Each validated normalized Collectr scan remains in the local SQLite database as a timestamped backup. The popup shows which saved scan is in use and rebuilds the sync preview from it when reopened; scan again whenever the source collection changes. Raw Collectr responses remain in memory only until validation. Dex catalog pages stay in tab memory, and sanitized collection pages use Chrome session storage across navigation.

## Controlled removal test

Start the companion with `--enable-removal-test` and conservative count/percentage thresholds. Only complete Collectr and Dex captures can produce an executable removal, and only destination IDs previously synchronized by CardRelay are managed. The popup automatically expands removal changes and requires the displayed destructive code under **Approve removals**. CardRelay writes a local recovery backup before setting the managed finish quantity to zero, preserves unrelated raw quantity keys, and requires an immediate Dex recapture.

This is contract-validation mode, not bulk destructive reconciliation. Quantity decreases, unmanaged cards, stale snapshots, incomplete captures, and operations outside the configured thresholds remain blocked.

## Privacy and validation

The companion binds only to loopback and requires the ephemeral pairing token. It validates captures with CardRelay's canonical parsers and never stores raw browser payloads. The extension does not read passwords, cookies, authorization headers, or unrelated pages. Detailed research and milestone-evidence controls are intentionally not exposed in the production-facing popup; those checks remain covered by fixtures, automated tests, and engineering documentation.

## Troubleshooting

- If CardRelay says it is not active in a Collectr or Dex tab, the unpacked extension was likely reloaded after that page loaded. Reload the site tab once, then reopen CardRelay. When updating local extension code, always reload CardRelay first and the site tab second.

- **Pairing required:** copy the current token from the running companion and save it again.
- **Companion unavailable:** keep `extension serve` running and verify the port. Restarting it creates a new token that must be saved again.
- **Capture not ready:** restart from Collectr's portfolio overview; aggregate and conflicting pages are rejected.
- **Invalid or rejected capture:** reload Collectr and start a fresh capture. CardRelay deliberately fails closed rather than guessing through a changed schema.
- **Dex capture not ready:** complete the Collection step first, then keep one Search tab open until all catalog pages are captured.
- **Dex normalization incomplete:** pagination succeeded, but one or more finish labels are not mapped. The snapshot remains read-only and incomplete; report the non-sensitive label diagnostics rather than guessing.
- **Mapping unchanged / stale:** the source capture, Dex capture, or prior mapping changed after the popup loaded. Select **Review** and review the current candidate again.

## Current limits

- The extension is an unpacked development build; it is not packaged or published.
- Capture is manual; the latest saved scan and preview reload automatically. Periodic checks and notifications are not implemented.
- A complete capture requires contiguous 30-record pages, the empty terminal page, exact/unstacked records, recognized condition and grading metadata, and a visible-total match.
- Browser snapshots cannot authorize general decreases or removals at this stage. The explicit companion removal-test flag permits only a complete-capture, threshold-bounded removal of a previously managed disposable card.
- Mapping confirmations only resolve identity; they do not approve a write or destructive operation.
- Additions and quantity increases use one explicit **Sync changes** action. Controlled removal testing keeps a separate destructive code and section.
- The popup cannot decrease quantities, remove unmanaged cards, exceed configured removal-test thresholds, or write to any destination other than Dex.
