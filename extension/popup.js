"use strict";

const portInput = document.querySelector("#port");
const tokenInput = document.querySelector("#token");
const statusElement = document.querySelector("#status");
const startButton = document.querySelector("#start");
const catalogButton = document.querySelector("#start-catalog");
const sendButton = document.querySelector("#send");
const diffSummary = document.querySelector("#diff-summary");
const diffList = document.querySelector("#diff-list");
const reviewSummary = document.querySelector("#review-summary");
const reviewList = document.querySelector("#review-list");
const writeResearchSection = document.querySelector("#write-research");
const armWriteResearchButton = document.querySelector("#arm-write-research");
const submitWriteResearchButton = document.querySelector("#submit-write-research");
const writeResearchStatus = document.querySelector("#write-research-status");
const writeResearchResults = document.querySelector("#write-research-results");
const safeWriteSection = document.querySelector("#safe-write");
const safeWriteConfirmation = document.querySelector("#safe-write-confirmation");
const applySafeWriteButton = document.querySelector("#apply-safe-write");
const safeWriteStatus = document.querySelector("#safe-write-status");
const reliabilitySection = document.querySelector("#reliability-evidence");
const startReliabilityButton = document.querySelector("#start-reliability");
const copyReliabilityButton = document.querySelector("#copy-reliability");
const reliabilityStatus = document.querySelector("#reliability-status");
let latestSafeWritePreview = null;
let reliabilitySeries = null;

function reliabilitySummary(series) {
  if (!series?.captures?.length) return "No reliability series is active.";
  const captures = series.captures;
  const first = captures[0];
  const fingerprintsMatch = captures.every(capture => capture.collection_fingerprint === first.collection_fingerprint);
  const complete = captures.every(capture => capture.completeness === "complete" &&
    capture.invalid_record_count === 0 && capture.pagination_complete);
  return [
    `Capture series: ${captures.length}/5`,
    `Canonical fingerprint: ${fingerprintsMatch ? "identical" : "CHANGED"}`,
    `Completeness and diagnostics: ${complete ? "pass" : "needs review"}`,
    `Entries/quantity: ${first.unique_entries}/${first.total_quantity}`,
    captures.length === 5 && fingerprintsMatch && complete
      ? "Repeatability evidence passed locally. Run CSV equivalence separately."
      : "Start another capture from the same unchanged portfolio, then send its preview."
  ].join("\n");
}

function displayReliabilitySeries() {
  reliabilityStatus.textContent = reliabilitySummary(reliabilitySeries);
  copyReliabilityButton.disabled = !reliabilitySeries?.captures?.length;
}

async function recordReliabilityCapture(result) {
  if (!reliabilitySeries || reliabilitySeries.captures.length >= 5) return;
  reliabilitySeries.captures.push({
    collection_fingerprint: result.collection_fingerprint,
    completeness: result.completeness,
    unique_entries: result.unique_entries,
    total_quantity: result.total_quantity,
    pagination_complete: result.pagination_complete,
    invalid_record_count: result.invalid_record_count
  });
  await chrome.storage.local.set({ reliabilitySeries });
  displayReliabilitySeries();
}

async function activeSupportedTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id) throw new Error("Open Collectr or Dex in the active tab.");
  if (tab.url?.startsWith("https://app.getcollectr.com/")) {
    return { tab, service: "collectr" };
  }
  if (tab.url?.startsWith("https://app.dextcg.com/")) {
    return { tab, service: "dex" };
  }
  throw new Error("Open app.getcollectr.com or app.dextcg.com in the active tab.");
}

async function sendToContentScript(tab, service, message) {
  try {
    return await chrome.tabs.sendMessage(tab.id, message);
  } catch {
    const page = service === "dex" ? "Dex" : "Collectr";
    throw new Error(
      `CardRelay is not active in this ${page} tab. Reload the ${page} tab once, then reopen CardRelay.`
    );
  }
}

function displayCollectrStatus(status) {
  const ready = status.productPageCount > 0 &&
    status.offsetsContiguous &&
    status.exactViewVerified &&
    !status.conflictingPageObserved;
  sendButton.disabled = !ready || status.captureRunning;
  statusElement.textContent = [
    `Pages observed: ${status.productPageCount}`,
    `Terminal page: ${status.terminalPageSeen ? "yes" : "no"}`,
    `Condition lookups: ${status.conditionLookupCount}`,
    `Grading lookups: ${status.gradingLookupCount}`,
    `Visible card total: ${status.visibleTotalQuantity ?? "not observed"}`,
    status.captureRunning ? "Capture is scrolling…" : "Capture is idle."
  ].join("\n");
}

function displayDexStatus(status) {
  sendButton.disabled = !status.collectionComplete || !status.catalogComplete;
  submitWriteResearchButton.disabled = !status.writeObservationCount;
  const collectionCount = status.collectionTotalPages
    ? `${status.collectionPageCount}/${status.collectionTotalPages}`
    : String(status.collectionPageCount);
  const catalogCount = status.catalogTotalPages
    ? `${status.catalogPageCount}/${status.catalogTotalPages}`
    : String(status.catalogPageCount);
  statusElement.textContent = [
    `Active Dex capture: ${status.activeTarget || "none"}`,
    `Collection pages: ${collectionCount} (${status.collectionComplete ? "complete" : "incomplete"})`,
    `Catalog pages: ${catalogCount} (${status.catalogComplete ? "complete" : "incomplete"})`,
    `Write observations: ${status.writeObservationCount || 0}${status.writeResearchArmed ? " (armed)" : ""}`,
    status.collectionConflict || status.catalogConflict
      ? "Conflicting repeated page detected; restart that capture."
      : "Catalog pages load gradually; manual browsing remains available."
  ].join("\n");
}

function configureForService(service) {
  const isDex = service === "dex";
  startButton.textContent = isDex ? "Start Dex collection capture" : "Start portfolio capture";
  catalogButton.hidden = !isDex;
  writeResearchSection.hidden = !isDex;
  sendButton.textContent = isDex ? "Send Dex read-only preview" : "Send preview to CardRelay";
  reliabilitySection.hidden = isDex;
}

startReliabilityButton.addEventListener("click", async () => {
  try {
    const { service } = await activeSupportedTab();
    if (service !== "collectr") throw new Error("Open the Collectr portfolio before starting a series.");
    reliabilitySeries = { version: 1, captures: [] };
    await chrome.storage.local.set({ reliabilitySeries });
    displayReliabilitySeries();
  } catch (error) {
    reliabilityStatus.textContent = error.message;
  }
});

copyReliabilityButton.addEventListener("click", async () => {
  if (!reliabilitySeries?.captures?.length) return;
  const report = {
    report: "CardRelay Milestone 6 browser repeatability evidence",
    captures: reliabilitySeries.captures,
    result: reliabilitySummary(reliabilitySeries)
  };
  try {
    await navigator.clipboard.writeText(JSON.stringify(report, null, 2));
    reliabilityStatus.textContent = `${reliabilitySummary(reliabilitySeries)}\nEvidence summary copied.`;
  } catch {
    reliabilityStatus.textContent = "Unable to copy the evidence summary. Keep the popup open and retry.";
  }
});

armWriteResearchButton.addEventListener("click", async () => {
  try {
    const { tab, service } = await activeSupportedTab();
    if (service !== "dex") throw new Error("Open Dex before arming write research.");
    const response = await sendToContentScript(tab, service, {
      type: "card-relay-dex-start",
      target: "write-research"
    });
    if (!response?.ok) throw new Error("Unable to arm Dex write research.");
    writeResearchResults.replaceChildren();
    writeResearchStatus.textContent = [
      "Schema-only observation is armed.",
      "Manually make one small, reversible collection change in Dex, then reopen CardRelay."
    ].join(" ");
    displayDexStatus(response.status);
  } catch (error) {
    writeResearchStatus.textContent = error.message;
  }
});

function topLevelFields(shape) {
  return shape?.kind === "object" ? Object.keys(shape.fields || {}).sort().join(", ") : shape?.kind;
}

function shapePaths(shape, prefix = "", paths = []) {
  if (!shape || paths.length >= 50) return paths;
  if (shape.kind === "object") {
    for (const [field, child] of Object.entries(shape.fields || {}).sort()) {
      shapePaths(child, prefix ? `${prefix}.${field}` : field, paths);
    }
    return paths;
  }
  if (shape.kind === "array") {
    for (const child of shape.items || []) shapePaths(child, `${prefix}[]`, paths);
    return paths;
  }
  paths.push(`${prefix || "body"}:${shape.kind}${shape.format ? `(${shape.format})` : ""}`);
  return paths;
}

submitWriteResearchButton.addEventListener("click", async () => {
  submitWriteResearchButton.disabled = true;
  writeResearchStatus.textContent = "Validating the schema-only observation…";
  try {
    const { tab, service } = await activeSupportedTab();
    if (service !== "dex") throw new Error("Open Dex before submitting write research.");
    const response = await sendToContentScript(tab, service, {
      type: "card-relay-dex-write-research-submit"
    });
    if (!response?.ok) {
      const issues = (response?.issues || [])
        .map(issue => `${issue.location || "capture"}: ${issue.type || "invalid"}`)
        .join(", ");
      throw new Error(
        `Observation rejected: ${response?.error || "unknown error"}${issues ? ` (${issues})` : ""}`
      );
    }
    const result = response.result;
    writeResearchStatus.textContent = [
      `${result.observation_count} schema-only observation${result.observation_count === 1 ? "" : "s"} validated.`,
      result.warning
    ].join(" ");
    writeResearchResults.replaceChildren();
    for (const observation of result.observations || []) {
      const item = document.createElement("div");
      item.className = "research-result";
      item.textContent = [
        `${observation.method} ${observation.route_template} → ${observation.response_status}`,
        `Origin host: ${observation.origin_host}`,
        `Query keys: ${(observation.query_keys || []).join(", ") || "none"}`,
        `Path bindings: ${(observation.path_parameter_bindings || [])
          .map(binding => `${binding.segment_index}=${binding.source}`).join(", ") || "none"}`,
        `Request fields: ${topLevelFields(observation.request_shape) || "none"}`,
        `Request schema: ${shapePaths(observation.request_shape).join(", ") || "empty"}`,
        `Response shape: ${topLevelFields(observation.response_shape) || "empty"}`
      ].join("\n");
      writeResearchResults.append(item);
    }
  } catch (error) {
    writeResearchStatus.textContent = error.message;
  }
});

async function refreshStatus() {
  try {
    const { tab, service } = await activeSupportedTab();
    configureForService(service);
    const type = service === "dex" ? "card-relay-dex-status" : "card-relay-status";
    const response = await sendToContentScript(tab, service, { type });
    if (!response?.ok) throw new Error("CardRelay content script is unavailable. Reload the tab.");
    if (service === "dex") displayDexStatus(response.status);
    else displayCollectrStatus(response.status);
  } catch (error) {
    sendButton.disabled = true;
    statusElement.textContent = error.message;
  }
}

document.querySelector("#save").addEventListener("click", async () => {
  const port = Number(portInput.value);
  const pairingToken = tokenInput.value.trim();
  if (!Number.isInteger(port) || port < 1024 || port > 65535 || !pairingToken) {
    statusElement.textContent = "Enter the companion port and pairing token.";
    return;
  }
  await chrome.storage.local.set({ companionPort: port, pairingToken });
  statusElement.textContent = "Pairing saved locally in this extension profile.";
});

startButton.addEventListener("click", async () => {
  try {
    const { tab, service } = await activeSupportedTab();
    if (service === "dex") {
      const response = await sendToContentScript(tab, service, {
        type: "card-relay-dex-start",
        target: "collection"
      });
      if (!response?.ok) throw new Error("Unable to start Dex collection capture.");
      displayDexStatus(response.status);
      return;
    }
    const response = await sendToContentScript(tab, service, { type: "card-relay-start" });
    if (!response?.ok) throw new Error("Unable to start capture. Reload Collectr and retry.");
    if (response.navigateToProducts) {
      await chrome.tabs.update(tab.id, { url: "https://app.getcollectr.com/portfolio/products" });
      window.close();
      return;
    }
    displayCollectrStatus(response.status);
  } catch (error) {
    statusElement.textContent = error.message;
  }
});

catalogButton.addEventListener("click", async () => {
  try {
    const { tab, service } = await activeSupportedTab();
    if (service !== "dex") throw new Error("Open Dex before starting a catalog capture.");
    const response = await sendToContentScript(tab, service, {
      type: "card-relay-dex-start",
      target: "catalog"
    });
    if (!response?.ok) throw new Error("Unable to start Dex catalog capture.");
    displayDexStatus(response.status);
  } catch (error) {
    statusElement.textContent = error.message;
  }
});

document.querySelector("#refresh").addEventListener("click", refreshStatus);

function displaySyncPreview(result) {
  const counts = result.change_counts || {};
  const visibleChanges = (result.changes || []).filter(change => change.change !== "no_change");
  diffSummary.textContent = [
    `Adds: ${counts.add_card || 0} · Increases: ${counts.increase_quantity || 0}`,
    `Decreases: ${counts.decrease_quantity || 0} · Removals: ${counts.remove_card || 0}`,
    `Review/blocked: ${(counts.manual_review_required || 0) + (counts.unsupported_operation || 0)}`,
    result.truncated || visibleChanges.length > 250
      ? "The displayed diff list is truncated."
      : "All changes are displayed.",
    result.destination_writes_enabled
      ? "Safe Dex writes are ready for explicit confirmation below."
      : "Safe Dex writes are unavailable for this preview."
  ].join("\n");
  diffList.replaceChildren();
  for (const change of visibleChanges.slice(0, 250)) {
    const item = document.createElement("div");
    const destructive = ["decrease_quantity", "remove_card"].includes(change.change);
    const safe = ["add_card", "increase_quantity"].includes(change.change);
    item.className = `diff-item ${destructive ? "destructive" : (safe ? "safe" : "blocked")}`;
    const title = document.createElement("div");
    title.className = "diff-title";
    title.textContent = `${change.card} · ${change.set || change.set_code || "Unknown set"} #${change.collector_number}`;
    const detail = document.createElement("div");
    detail.className = "diff-detail";
    detail.textContent = `${change.change.replaceAll("_", " ")}: Dex ${change.current_quantity} → Collectr ${change.collectr_quantity}`;
    item.append(title, detail);
    diffList.append(item);
  }
  latestSafeWritePreview = result.destination_writes_enabled ? {
    confirmationCode: result.safe_write_confirmation_code,
    operationIds: result.safe_write_operation_ids || []
  } : null;
  safeWriteSection.hidden = !latestSafeWritePreview;
  safeWriteConfirmation.value = "";
  applySafeWriteButton.disabled = true;
  safeWriteStatus.textContent = latestSafeWritePreview
    ? `${result.safe_write_count} safe change${result.safe_write_count === 1 ? "" : "s"} ready. Type ${result.safe_write_confirmation_code} to enable the button.`
    : (result.safe_write_block_reason === "dex_recapture_required_after_write_attempt"
      ? "A Dex write was attempted from this snapshot. Capture Dex again before another attempt."
      : "No safe Dex writes are available from this preview.");
  displayMappingReviews(result);
}

safeWriteConfirmation.addEventListener("input", () => {
  const typed = safeWriteConfirmation.value.trim().toUpperCase();
  applySafeWriteButton.disabled = !latestSafeWritePreview || typed !== latestSafeWritePreview.confirmationCode;
});

applySafeWriteButton.addEventListener("click", async () => {
  if (!latestSafeWritePreview) return;
  applySafeWriteButton.disabled = true;
  safeWriteStatus.textContent = "Preparing the confirmed Dex batch…";
  try {
    const prepared = await chrome.runtime.sendMessage({
      type: "card-relay-safe-write-prepare",
      payload: {
        confirmation_code: latestSafeWritePreview.confirmationCode,
        operation_ids: latestSafeWritePreview.operationIds
      }
    });
    if (!prepared?.ok) throw new Error(prepared?.error || "safe_write_prepare_failed");
    const { tab, service } = await activeSupportedTab();
    if (service !== "dex") throw new Error("Open Dex before applying the confirmed batch.");
    safeWriteStatus.textContent = "Applying the confirmed Dex batch…";
    const execution = await sendToContentScript(tab, service, {
      type: "card-relay-dex-safe-write-execute",
      batch: prepared.result
    });
    if (!execution?.ok) throw new Error("Dex did not return a complete execution report.");
    const reported = await chrome.runtime.sendMessage({
      type: "card-relay-safe-write-report",
      payload: {
        contract_version: "dex-safe-write-report-v1",
        plan_id: prepared.result.plan_id,
        confirmation_code: prepared.result.confirmation_code,
        results: execution.results
      }
    });
    if (!reported?.ok) throw new Error(reported?.error || "safe_write_report_failed");
    const summary = reported.result;
    latestSafeWritePreview = null;
    safeWriteSection.hidden = true;
    safeWriteStatus.textContent = `${summary.succeeded} succeeded, ${summary.failed} failed. Capture Dex again before any further sync.`;
    diffSummary.textContent = "Dex write attempt recorded. Capture Dex again before building the next diff.";
  } catch (error) {
    safeWriteStatus.textContent = `Write attempt was not completed: ${error.message}. Capture Dex again before retrying.`;
  }
});

function identityLabel(identity) {
  const set = identity.set_name || identity.set_code || "Unknown set";
  const finish = identity.finish && identity.finish !== "unknown" ? ` · ${identity.finish}` : "";
  return `${identity.card_name} · ${set} #${identity.collector_number}${finish}`;
}

function fieldLabels(fields) {
  return (fields || []).map(field => field.replaceAll("_", " ")).join(", ");
}

async function submitMappingDecision(review, action, destinationId) {
  reviewSummary.textContent = `${action === "confirm" ? "Confirming" : "Rejecting"} mapping…`;
  for (const button of reviewList.querySelectorAll("button")) button.disabled = true;
  try {
    const response = await chrome.runtime.sendMessage({
      type: "card-relay-mapping-decision",
      decision: {
        action,
        source_fingerprint: review.source_fingerprint,
        destination_id: destinationId
      }
    });
    if (!response?.ok) {
      reviewSummary.textContent = `Mapping unchanged: ${response?.error || "unknown error"}`;
      for (const button of reviewList.querySelectorAll("button")) button.disabled = false;
      return;
    }
    displaySyncPreview(response.result);
  } catch {
    reviewSummary.textContent = "Mapping unchanged: companion unavailable";
    for (const button of reviewList.querySelectorAll("button")) button.disabled = false;
  }
}

function displayMappingReviews(result) {
  const reviews = result.mapping_reviews || [];
  const total = result.mapping_review_count || 0;
  reviewList.replaceChildren();
  if (!total) {
    reviewSummary.textContent = "No probable or ambiguous matches are waiting for review.";
    return;
  }
  const visibleReviews = reviews.slice(0, 50);
  reviewSummary.textContent = [
    `${total} match${total === 1 ? "" : "es"} waiting for review.`,
    total > visibleReviews.length || result.mapping_reviews_truncated
      ? `Showing the first ${visibleReviews.length}; decisions refresh the queue.`
      : "Every pending match is shown."
  ].join(" ");
  for (const review of visibleReviews) {
    const item = document.createElement("div");
    item.className = "review-item";

    const source = document.createElement("div");
    source.className = "review-source";
    source.textContent = `Collectr: ${identityLabel(review.source_identity)}`;
    const reason = document.createElement("div");
    reason.className = "review-reason";
    reason.textContent = `${review.status}: ${(review.reasons || []).join("; ")}`;
    item.append(source, reason);

    const radioName = `mapping-${review.source_fingerprint}`;
    for (const [index, candidate] of (review.candidates || []).entries()) {
      const label = document.createElement("label");
      label.className = "mapping-candidate";
      const radio = document.createElement("input");
      radio.type = "radio";
      radio.name = radioName;
      radio.value = candidate.destination_id;
      radio.checked = index === 0;
      const candidateTitle = document.createElement("span");
      candidateTitle.textContent = `Dex: ${identityLabel(candidate.identity)}`;
      const detail = document.createElement("span");
      detail.className = "candidate-detail";
      const mismatches = fieldLabels(candidate.mismatched_fields);
      detail.textContent = [
        `Score ${Math.round(candidate.score * 100)}%.`,
        mismatches ? `Different: ${mismatches}.` : "All compared identity fields agree.",
        ...(candidate.reasons || [])
      ].join(" ");
      label.append(radio, candidateTitle, detail);
      item.append(label);
    }

    const actions = document.createElement("div");
    actions.className = "review-actions";
    const confirm = document.createElement("button");
    confirm.textContent = "Confirm match";
    const reject = document.createElement("button");
    reject.className = "reject";
    reject.textContent = "Reject candidate";
    const decide = action => {
      const selected = item.querySelector(`input[name="${radioName}"]:checked`);
      if (!selected) {
        reviewSummary.textContent = "Select a Dex candidate first.";
        return;
      }
      void submitMappingDecision(review, action, selected.value);
    };
    confirm.addEventListener("click", () => decide("confirm"));
    reject.addEventListener("click", () => decide("reject"));
    actions.append(confirm, reject);
    item.append(actions);
    reviewList.append(item);
  }
}

document.querySelector("#build-diff").addEventListener("click", async () => {
  diffSummary.textContent = "Building the Collectr → Dex diff…";
  diffList.replaceChildren();
  try {
    const response = await chrome.runtime.sendMessage({ type: "card-relay-sync-preview" });
    if (!response?.ok) {
      diffSummary.textContent = `Diff unavailable: ${response?.error || "unknown error"}`;
      return;
    }
    displaySyncPreview(response.result);
  } catch {
    diffSummary.textContent = "Diff unavailable: companion unavailable";
  }
});

sendButton.addEventListener("click", async () => {
  sendButton.disabled = true;
  statusElement.textContent = "Validating preview in CardRelay…";
  try {
    const { tab, service } = await activeSupportedTab();
    const type = service === "dex" ? "card-relay-dex-submit" : "card-relay-submit";
    const response = await sendToContentScript(tab, service, { type });
    if (!response?.ok) throw new Error(`Preview rejected: ${response?.error || "unknown error"}`);
    const result = response.result;
    if (service === "dex") {
      statusElement.textContent = [
        `Dex catalog records: ${result.catalog_records}`,
        `Dex collection records: ${result.collection_records}`,
        `Dex quantity: ${result.total_quantity}`,
        `Pagination complete: ${result.pagination_complete ? "yes" : "no"}`,
        `Normalization complete: ${result.normalization_complete ? "yes" : "no"}`,
        `Unsupported labels: ${(result.unsupported_catalog_variants?.length || 0) +
          (result.unsupported_collection_quantities?.length || 0)}`,
        result.normalization_complete
          ? "Read-only snapshot stored. Destination writes remain disabled."
          : "Incomplete read-only snapshot stored; review diagnostics before comparison."
      ].join("\n");
      return;
    }
    await recordReliabilityCapture(result);
    const invalidReasons = Object.entries(result.invalid_record_reasons || {})
      .filter(([, count]) => count > 0)
      .map(([reason, count]) => `  ${reason.replaceAll("_", " ")}: ${count}`);
    statusElement.textContent = [
      `Snapshot stored: ${result.snapshot_id}`,
      `Entries: ${result.unique_entries}`,
      `Quantity: ${result.total_quantity}`,
      `Completeness: ${result.completeness}`,
      `Invalid/lossy rows: ${result.invalid_record_count}`,
      ...invalidReasons,
      `Skipped non-cards: ${result.skipped_non_card_count}`,
      "Destination writes remain disabled."
    ].join("\n");
  } catch (error) {
    statusElement.textContent = error.message;
  }
});

chrome.storage.local.get(["companionPort", "pairingToken"]).then(settings => {
  portInput.value = settings.companionPort || 8765;
  tokenInput.value = settings.pairingToken || "";
});
chrome.storage.local.get(["reliabilitySeries"]).then(settings => {
  const series = settings.reliabilitySeries;
  if (series?.version === 1 && Array.isArray(series.captures)) reliabilitySeries = series;
  displayReliabilitySeries();
});
void refreshStatus();
