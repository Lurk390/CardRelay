# CardRelay browser bridge

This unpacked Manifest V3 extension captures Collectr source data and Dex read-only destination data from the user's normal authenticated Chrome tabs. It sends sanitized captures only to CardRelay's loopback companion. It does not read passwords, cookies, authorization headers, or unrelated pages. Destination writes are disabled.

## Load and run locally

1. Open `chrome://extensions`.
2. Enable **Developer mode**.
3. Select **Load unpacked** and choose this `extension` directory.
4. Start the companion from the repository:

   ```powershell
   .\.venv\Scripts\card-relay.exe extension serve
   ```

5. Copy the displayed pairing token into the extension popup and save it. The default port is `8765`.
6. Open the Collectr portfolio overview in the active tab and select **Start portfolio capture**.
7. The extension opens the Products view and scrolls while Collectr loads batches. Reopen the popup to inspect progress and send the preview.

## Dex read-only workflow

1. Open Dex **Collection**, then select **Start Dex collection capture** in CardRelay.
2. Refresh status until collection pages are complete and `Active Dex capture` is `none`.
3. Navigate to Dex **Search** and select **Start Dex catalog capture**.
4. Keep the tab open while CardRelay loads the verified pagination sequence at a 200 ms interval. You do not need to scroll the catalog.
5. Refresh status until the captured and expected page counts match, then select **Send Dex read-only preview**.

Dex catalog pages stay only in the current tab's memory. Sanitized collection pages use session storage so navigation does not discard them. Submission is split into small, ordered loopback requests; the companion rejects gaps, reordered chunks, incomplete pagination, conflicting totals, oversized captures, and changed schemas. A successful preview stores normalized counts and reports unsupported finish labels without exposing card data. Dex writes remain disabled.

After storing both a Collectr capture and a Dex capture, select **Build visual diff**. The popup groups additions and increases separately from decreases and removals, shows Dex and Collectr quantities for each card, and highlights unresolved or unmanaged records. The companion returns at most 2,000 changes and the popup renders at most 250 at once; summary counts cover the full plan and truncation is explicit. This view is informational while Dex writes remain disabled.

Probable and ambiguous Pokémon matches appear under **Match review**. Compare the card name, set, collector number, finish, score, and highlighted identity differences. Select the intended Dex candidate and choose **Confirm match**, or choose **Reject candidate** to prevent that pairing. The popup renders 50 pending records at a time and refreshes after each decision. Decisions are stored in CardRelay's local SQLite database, not extension storage, and therefore survive browser or companion restarts. Before saving, the companion reruns matching against the latest source and Dex snapshots and accepts only a candidate offered by that current result; a stale popup must rebuild the diff.

After editing extension files, use **Reload** on the extension card at `chrome://extensions` and reload open Collectr or Dex tabs. A content-script-unavailable message almost always means the active tab predates the latest extension load.

The pairing token is ephemeral: restarting the companion produces a new token. Private product response bodies remain in the tab until submission and are not written to extension storage. Bounded condition and grading lookup responses are kept in session storage so navigation cannot discard the metadata needed for safe normalization; Chrome clears that state with the browser session. If the Collectr client already cached those dictionaries, the page observer reads only its verified `cardConditions` and `gradedCardScales` entries, never arbitrary local storage. The companion validates captures with CardRelay's existing Collectr parser and stores the canonical collection plus snapshot metadata in local SQLite for later diff generation; it does not store the raw browser payload.

Rejected previews identify only the safe validation stage (`json`, `contract`, or `source`); CardRelay never returns or logs the offending private payload.

## Expected preview

The popup reports page progress while the Products view scrolls. When capture is idle, select **Send preview to CardRelay**. A successful response includes the snapshot ID, unique entries, quantity, and completeness. `complete` requires the visible Cards quantity to match the normalized response total and requires contiguous 30-record pages ending in an empty terminal page. An `incomplete` preview cannot imply that an omitted card was removed.

If Collectr neither requests nor has a valid cached condition or grading lookup during the capture, CardRelay keeps otherwise valid ungraded rows with an unknown condition and counts them as lossy. Graded rows without a recognized grading lookup are omitted rather than guessed. The popup reports reason-specific counts; the resulting preview is intentionally incomplete and cannot authorize destructive planning.

## Troubleshooting

- **Pairing required:** copy the current token from the running companion and save it again.
- **Companion unavailable:** keep `extension serve` running and verify the port. Restarting it creates a new token that must be saved again.
- **Capture not ready:** restart from Collectr's portfolio overview; aggregate and conflicting pages are rejected.
- **Terminal page missing:** wait for scrolling to become idle, then refresh the popup status.
- **Invalid or rejected capture:** reload Collectr and start a fresh capture. CardRelay deliberately fails closed rather than guessing through a changed schema.
- **Dex capture not ready:** complete the Collection step first, then keep one Search tab open until all catalog pages are captured.
- **Dex normalization incomplete:** pagination succeeded, but one or more finish labels are not mapped. The snapshot remains read-only and incomplete; report the non-sensitive label diagnostics rather than guessing.
- **Mapping unchanged / stale:** the source capture, Dex capture, or prior mapping changed after the popup loaded. Select **Build visual diff** and review the current candidate again.

## Current limits

- The extension is an unpacked development build; it is not packaged or published.
- Capture and preview are manual. Periodic checks and notifications are not implemented.
- A complete capture requires contiguous 30-record pages, the empty terminal page, exact/unstacked records, recognized condition and grading metadata, and a visible-total match.
- Browser snapshots can never authorize decreases or removals at this stage.
- Mapping confirmations only resolve identity; they do not approve a write or destructive operation.
- The visual diff has no write-confirmation control until all Dex write contracts and read-after-write checks are verified.
- The popup cannot write to Dex or any other destination.
