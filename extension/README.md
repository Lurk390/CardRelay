# CardRelay browser bridge

This unpacked Manifest V3 extension captures Collectr source data and Dex destination data from the user's normal authenticated Chrome tabs. It sends sanitized captures only to CardRelay's loopback companion. It does not read passwords, cookies, authorization headers, or unrelated pages. After an explicit preview confirmation it can make only verified Dex additions and quantity increases.

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

Dex catalog pages stay only in the current tab's memory. Sanitized collection pages use session storage so navigation does not discard them. Submission is split into small, ordered loopback requests; the companion rejects gaps, reordered chunks, incomplete pagination, conflicting totals, oversized captures, and changed schemas. A successful preview stores normalized counts and reports unsupported finish labels without exposing card data.

After storing both a Collectr capture and a Dex capture, select **Build visual diff**. The popup groups additions and increases separately from decreases and removals, shows Dex and Collectr quantities for each card, and highlights unresolved or unmanaged records. The companion returns at most 2,000 changes and the popup renders at most 250 at once; summary counts cover the full plan and truncation is explicit.

If every safe change has a verified quantity key and the diff is not stale, the popup shows **Apply safe Dex changes**. Verify the cards and quantities, type the displayed 12-character confirmation code, and apply from an open Dex tab. CardRelay sends additions with `POST https://clients.dextcg.com/api/user/cards`; it updates existing records with an absolute full quantity map using `PATCH https://clients.dextcg.com/api/user/cards/{collectionRecordId}`. PATCH may retry transient failures; POST never retries automatically because a lost response could make the result uncertain. Every attempt requires a new Dex capture before another batch can be prepared. Decreases and removals remain unavailable.

Probable and ambiguous Pokémon matches appear under **Match review**. Compare the card name, set, collector number, finish, score, and highlighted identity differences. Select the intended Dex candidate and choose **Confirm match**, or choose **Reject candidate** to prevent that pairing. The popup renders 50 pending records at a time and refreshes after each decision. Decisions are stored in CardRelay's local SQLite database, not extension storage, and therefore survive browser or companion restarts. Before saving, the companion reruns matching against the latest source and Dex snapshots and accepts only a candidate offered by that current result; a stale popup must rebuild the diff.

## Dex write-contract research

This development-only mode observes schema; it does not perform a write. Open Dex, choose **Arm schema-only observation**, and then manually make one small, reversible collection change in Dex. Reopen CardRelay, verify that the write-observation count increased, and choose **Validate observed schema**. The result shows the method, redacted route template, query-key names, top-level request fields, response status, and response shape.

Arming is explicit and expires on navigation or when another capture starts. At most ten JSON requests are retained in tab memory. The main-world observer discards every scalar value, replaces dynamic route segments and property names, never reads headers other than content type, and never exports a full URL, cookie, authorization value, account identifier, card identifier, quantity, note, or response value. The companion rejects extra fields, scalar values, over-deep structures, oversized structures, and unsanitized routes. Validation does not persist the observation and never authorizes request replay.

After editing extension files, use **Reload** on the extension card at `chrome://extensions` and reload open Collectr or Dex tabs. A content-script-unavailable message almost always means the active tab predates the latest extension load.

The pairing token is ephemeral: restarting the companion produces a new token. Private product response bodies remain in the tab until submission and are not written to extension storage. Bounded condition and grading lookup responses are kept in session storage so navigation cannot discard the metadata needed for safe normalization; Chrome clears that state with the browser session. If the Collectr client already cached those dictionaries, the page observer reads only its verified `cardConditions` and `gradedCardScales` entries, never arbitrary local storage. The companion validates captures with CardRelay's existing Collectr parser and stores the canonical collection plus snapshot metadata in local SQLite for later diff generation; it does not store the raw browser payload.

Rejected previews identify only the safe validation stage (`json`, `contract`, or `source`); CardRelay never returns or logs the offending private payload.

## Expected preview

The popup reports page progress while the Products view scrolls. When capture is idle, select **Send preview to CardRelay**. A successful response includes the snapshot ID, unique entries, quantity, and completeness. `complete` requires the visible Cards quantity to match the normalized response total and requires contiguous 30-record pages ending in an empty terminal page. An `incomplete` preview cannot imply that an omitted card was removed.

If Collectr neither requests nor has a valid cached condition or grading lookup during the capture, CardRelay keeps otherwise valid ungraded rows with an unknown condition and counts them as lossy. Graded rows without a recognized grading lookup are omitted rather than guessed. The popup reports reason-specific counts; the resulting preview is intentionally incomplete and cannot authorize destructive planning.

## Milestone 6 reliability evidence

The extension automates the repeatability portion of the reliability gates without collecting private card details. On a Collectr portfolio, select **Start 5-capture series**, then perform and submit five complete captures without changing that portfolio. The popup stores only each capture's canonical fingerprint, entry and quantity counts, completeness, pagination result, and invalid-record count in local extension storage. It reports whether all five fingerprints match and enables **Copy evidence summary** when at least one capture has completed.

Run one series for each of three distinct, user-controlled portfolios, including the free-account path and one portfolio with at least 1,000 holdings. The series intentionally does not log in, switch portfolios, manipulate browser accounts, or treat a partial capture as evidence. Start a new series whenever you switch portfolios.

The series is only one promotion gate. For two Pro portfolios, also produce a fresh CSV export without editing the portfolio between export and browser capture, and compare the canonical identity and quantity results. Finally, use **Dex write-contract research** to observe one manually performed, reversible decrease and one removal on a disposable test card. Copy the privacy-safe summaries and record the CSV comparison outcomes before asking to promote destructive-sync policy.

## Troubleshooting

- If CardRelay says it is not active in a Collectr or Dex tab, the unpacked extension was likely reloaded after that page loaded. Reload the site tab once, then reopen CardRelay. When updating local extension code, always reload CardRelay first and the site tab second.

- **Pairing required:** copy the current token from the running companion and save it again.
- **Companion unavailable:** keep `extension serve` running and verify the port. Restarting it creates a new token that must be saved again.
- **Capture not ready:** restart from Collectr's portfolio overview; aggregate and conflicting pages are rejected.
- **Terminal page missing:** wait for scrolling to become idle, then refresh the popup status.
- **Invalid or rejected capture:** reload Collectr and start a fresh capture. CardRelay deliberately fails closed rather than guessing through a changed schema.
- **Dex capture not ready:** complete the Collection step first, then keep one Search tab open until all catalog pages are captured.
- **Dex normalization incomplete:** pagination succeeded, but one or more finish labels are not mapped. The snapshot remains read-only and incomplete; report the non-sensitive label diagnostics rather than guessing.
- **Mapping unchanged / stale:** the source capture, Dex capture, or prior mapping changed after the popup loaded. Select **Build visual diff** and review the current candidate again.
- **No write observation:** arm research immediately before manually changing a single collection quantity. Navigation and extension reloads intentionally clear the in-memory research state.

## Current limits

- The extension is an unpacked development build; it is not packaged or published.
- Capture and preview are manual. Periodic checks and notifications are not implemented.
- The reliability series automates local repeatability comparison; it does not replace the required multi-portfolio, CSV-equivalence, Dex-contract, or human operational review gates.
- A complete capture requires contiguous 30-record pages, the empty terminal page, exact/unstacked records, recognized condition and grading metadata, and a visible-total match.
- Browser snapshots can never authorize decreases or removals at this stage.
- Mapping confirmations only resolve identity; they do not approve a write or destructive operation.
- Write-contract research is schema-only, in-memory, explicitly armed, and cannot replay a request.
- The visual diff can apply only additions and quantity increases after the displayed confirmation code is typed.
- The popup cannot decrease quantities, remove cards, or write to any destination other than Dex.
