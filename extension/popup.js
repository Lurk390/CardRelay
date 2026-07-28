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
const safeWriteSection = document.querySelector("#safe-write");
const applySafeWriteButton = document.querySelector("#apply-safe-write");
const safeWriteStatus = document.querySelector("#safe-write-status");
const removalSection = document.querySelector("#removal-write");
const removalConfirmation = document.querySelector("#removal-confirmation");
const applyRemovalButton = document.querySelector("#apply-removal");
const removalStatus = document.querySelector("#removal-status");
const captureIssues = document.querySelector("#capture-issues");
const connectionSettings = document.querySelector("#connection-settings");
const connectionState = document.querySelector("#connection-state");
const serviceLabel = document.querySelector("#service-label");
const actionTitle = document.querySelector("#action-title");
const syncStats = document.querySelector("#sync-stats");
const statAdds = document.querySelector("#stat-adds");
const statUpdates = document.querySelector("#stat-updates");
const statRemovals = document.querySelector("#stat-removals");
const statReview = document.querySelector("#stat-review");
const changeDetails = document.querySelector("#change-details");
const changeSummary = document.querySelector("#change-summary");
const reviewSection = document.querySelector("#review-section");
const captureIssuesList = document.querySelector("#capture-issues-list");
const savedCapture = document.querySelector("#saved-capture");
const reviewToolbar = document.querySelector("#review-toolbar");
const selectSuggestedButton = document.querySelector("#select-suggested");
const reviewSelectedCount = document.querySelector("#review-selected-count");
const confirmSelectedButton = document.querySelector("#confirm-selected");
const rejectSelectedButton = document.querySelector("#reject-selected");
let latestSafeWritePreview = null;
let latestRemovalPreview = null;
let statusRefreshTimer = null;
let statusRefreshInFlight = false;
const visibleMappingReviews = new Map();

function displayCaptureIssues(issues) {
  captureIssuesList.replaceChildren();
  const visible = (issues || []).slice(0, 10);
  captureIssues.hidden = visible.length === 0;
  for (const issue of visible) {
    const item = document.createElement("div");
    item.className = "capture-issue";
    item.textContent = `${issue.reason}: ${issue.card_name} · ${issue.set_name || "Unknown set"}${issue.collector_number ? ` #${issue.collector_number}` : ""}\n${issue.guidance}`;
    captureIssuesList.append(item);
  }
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
  sendButton.hidden = !ready || status.captureRunning;
  sendButton.disabled = !ready || status.captureRunning;
  startButton.textContent = status.productPageCount > 0 ? "Recapture Collectr" : "Capture Collectr";
  if (status.captureRunning) {
    statusElement.textContent = "Capturing Collectr… Keep this tab open until it finishes.";
  } else if (ready) {
    statusElement.textContent = "Collectr is ready. Save this capture to continue.";
  } else if (status.productPageCount > 0) {
    statusElement.textContent = "The capture is incomplete. Run it again before syncing.";
  } else {
    statusElement.textContent = "Capture your current Collectr portfolio to begin.";
  }
}
function displayDexStatus(status) {
  const ready = status.collectionComplete && status.catalogComplete;
  sendButton.hidden = !ready;
  sendButton.disabled = !ready;
  startButton.textContent = status.collectionComplete ? "Recapture collection" : "Capture collection";
  catalogButton.textContent = status.catalogComplete ? "Recapture catalog" : "Capture catalog";
  if (ready) {
    statusElement.textContent = "Dex is ready. Save this capture to review your sync.";
  } else if (status.catalogError === "catalog_request_not_observed") {
    statusElement.textContent = "Dex Search did not load the catalog. Refresh the Search page, then retry.";
  } else if (status.catalogError === "catalog_request_timeout") {
    statusElement.textContent = "Dex stopped responding while loading the catalog. Retry the capture.";
  } else if (status.catalogError) {
    statusElement.textContent = "Dex could not finish loading the catalog. Refresh Search, then retry.";
  } else if (status.activeTarget === "catalog") {
    statusElement.textContent = status.catalogTotalPages
      ? `Capturing Dex catalog… ${status.catalogPageCount} of ${status.catalogTotalPages} pages.`
      : "Starting Dex catalog capture…";
  } else if (status.activeTarget === "collection") {
    statusElement.textContent = status.collectionTotalPages
      ? `Capturing Dex collection… ${status.collectionPageCount} of ${status.collectionTotalPages} pages.`
      : "Starting Dex collection capture…";
  } else if (status.collectionComplete) {
    statusElement.textContent = "Collection captured. Open Dex Search, then capture the catalog.";
  } else {
    statusElement.textContent = "Start with your Dex collection, then capture the catalog from Search.";
  }
  scheduleStatusRefresh(status.activeTarget);
}

function scheduleStatusRefresh(activeTarget) {
  if (statusRefreshTimer !== null) clearTimeout(statusRefreshTimer);
  statusRefreshTimer = null;
  if (!activeTarget) return;
  statusRefreshTimer = setTimeout(() => {
    statusRefreshTimer = null;
    void refreshStatus();
  }, 750);
}

function configureForService(service) {
  const isDex = service === "dex";
  serviceLabel.textContent = isDex ? "Dex" : "Collectr";
  actionTitle.textContent = isDex ? "Capture destination" : "Capture source";
  startButton.textContent = isDex ? "Capture collection" : "Capture Collectr";
  catalogButton.hidden = !isDex;
  sendButton.textContent = isDex ? "Save Dex capture" : "Save Collectr capture";
}
async function refreshStatus() {
  if (statusRefreshInFlight) return;
  statusRefreshInFlight = true;
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
  } finally {
    statusRefreshInFlight = false;
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
  connectionState.textContent = "Saved";
  connectionSettings.open = false;
  await Promise.all([loadSavedCapture(), loadSyncPreview(false)]);
  statusElement.textContent = "Connection saved. Open Collectr or Dex to continue.";
});

async function startCapture() {
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
  const response = await sendToContentScript(tab, service, {
    type: "card-relay-start"
  });
  if (!response?.ok) throw new Error("Unable to start capture. Reload Collectr and retry.");
  if (response.navigateToProducts) {
    await chrome.tabs.update(tab.id, { url: "https://app.getcollectr.com/portfolio/products" });
    window.close();
    return;
  }
  displayCollectrStatus(response.status);
}

startButton.addEventListener("click", async () => {
  try {
    await startCapture();
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

document.querySelector("#refresh").addEventListener("click", async () => {
  await Promise.all([refreshStatus(), loadSavedCapture(), loadSyncPreview(false)]);
});

function displaySyncPreview(result) {
  const counts = result.change_counts || {};
  const adds = counts.add_card || 0;
  const updates = (counts.increase_quantity || 0) + (counts.decrease_quantity || 0);
  const removals = counts.remove_card || 0;
  const reviews = (counts.manual_review_required || 0) +
    (counts.unsupported_operation || 0) + (counts.blocked_by_safety_policy || 0);
  const visibleChanges = (result.changes || []).filter(change => change.change !== "no_change");
  const totalChanges = Object.entries(counts)
    .filter(([kind]) => kind !== "no_change")
    .reduce((total, [, count]) => total + count, 0);

  syncStats.hidden = false;
  statAdds.textContent = String(adds);
  statUpdates.textContent = String(updates);
  statRemovals.textContent = String(removals);
  statReview.textContent = String(reviews);
  changeDetails.hidden = totalChanges === 0;
  changeDetails.open = Boolean(result.removal_writes_enabled);
  changeSummary.textContent = `View ${totalChanges} card change${totalChanges === 1 ? "" : "s"}`;

  if (totalChanges === 0) {
    diffSummary.textContent = "Collectr and Dex are in sync.";
  } else if (result.mapping_review_count) {
    diffSummary.textContent = `${totalChanges} changes found. Resolve ${result.mapping_review_count} match${result.mapping_review_count === 1 ? "" : "es"} below.`;
  } else if (result.destination_writes_enabled || result.removal_writes_enabled) {
    diffSummary.textContent = `${totalChanges} changes found. Review them, then sync when ready.`;
  } else if (result.safe_write_block_reason === "dex_recapture_required_after_write_attempt" ||
      result.removal_block_reason === "dex_recapture_required_after_write_attempt") {
    diffSummary.textContent = "Capture Dex again to verify the last sync.";
  } else {
    diffSummary.textContent = `${totalChanges} changes found, but none are ready to apply.`;
  }

  diffList.replaceChildren();
  for (const change of visibleChanges.slice(0, 60)) {
    const item = document.createElement("div");
    const destructive = ["decrease_quantity", "remove_card"].includes(change.change);
    const safe = ["add_card", "increase_quantity"].includes(change.change);
    item.className = `diff-item ${destructive ? "destructive" : (safe ? "safe" : "blocked")}`;
    const title = document.createElement("div");
    title.className = "diff-title";
    title.textContent = `${change.card} · ${change.set || change.set_code || "Unknown set"} #${change.collector_number}`;
    const detail = document.createElement("div");
    detail.className = "diff-detail";
    detail.textContent = `Dex ${change.current_quantity} → Collectr ${change.collectr_quantity}`;
    item.append(title, detail);
    diffList.append(item);
  }
  if (visibleChanges.length > 60) {
    const item = document.createElement("div");
    item.className = "diff-item";
    item.textContent = `${visibleChanges.length - 60} more changes are included in the summary.`;
    diffList.append(item);
  }

  latestSafeWritePreview = result.destination_writes_enabled ? {
    confirmationCode: result.safe_write_confirmation_code,
    operationIds: result.safe_write_operation_ids || []
  } : null;
  safeWriteSection.hidden = !latestSafeWritePreview;
  applySafeWriteButton.disabled = !latestSafeWritePreview;
  if (latestSafeWritePreview) {
    applySafeWriteButton.textContent = `Sync ${result.safe_write_count} change${result.safe_write_count === 1 ? "" : "s"}`;
    safeWriteStatus.textContent = `${result.safe_write_count} non-destructive change${result.safe_write_count === 1 ? " is" : "s are"} ready.`;
  }

  latestRemovalPreview = result.removal_writes_enabled ? {
    confirmationCode: result.destructive_confirmation_code,
    operationIds: result.removal_operation_ids || []
  } : null;
  removalSection.hidden = !latestRemovalPreview;
  removalConfirmation.value = "";
  applyRemovalButton.disabled = true;
  if (latestRemovalPreview) {
    removalStatus.textContent = `${result.removal_count} managed removal${result.removal_count === 1 ? "" : "s"}. Approval code: ${result.destructive_confirmation_code}`;
  }
  displayMappingReviews(result);
}
applySafeWriteButton.addEventListener("click", async () => {
  if (!latestSafeWritePreview) return;
  applySafeWriteButton.disabled = true;
  safeWriteStatus.textContent = "Preparing sync…";
  latestRemovalPreview = null;
  removalSection.hidden = true;
  try {
    const { tab, service } = await activeSupportedTab();
    if (service !== "dex") throw new Error("Open Dex to sync these changes.");
    const prepared = await chrome.runtime.sendMessage({
      type: "card-relay-safe-write-prepare",
      payload: {
        confirmation_code: latestSafeWritePreview.confirmationCode,
        operation_ids: latestSafeWritePreview.operationIds
      }
    });
    if (!prepared?.ok) throw new Error(prepared?.error || "safe_write_prepare_failed");
    safeWriteStatus.textContent = "Syncing with Dex…";
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
    safeWriteStatus.textContent = `${summary.succeeded} synced, ${summary.failed} failed. Capture Dex again to verify.`;
    diffSummary.textContent = "Sync sent. Capture Dex again to verify the result.";
  } catch (error) {
    safeWriteStatus.textContent = `Sync stopped: ${error.message}. Capture Dex again before retrying.`;
  }
});

removalConfirmation.addEventListener("input", () => {
  const typed = removalConfirmation.value.trim().toUpperCase();
  applyRemovalButton.disabled = !latestRemovalPreview ||
    typed !== latestRemovalPreview.confirmationCode;
});

applyRemovalButton.addEventListener("click", async () => {
  if (!latestRemovalPreview) return;
  applyRemovalButton.disabled = true;
  removalStatus.textContent = "Creating a recovery backup…";
  latestSafeWritePreview = null;
  safeWriteSection.hidden = true;
  try {
    const { tab, service } = await activeSupportedTab();
    if (service !== "dex") throw new Error("Open Dex before removing approved cards.");
    const prepared = await chrome.runtime.sendMessage({
      type: "card-relay-removal-prepare",
      payload: {
        confirmation_code: latestRemovalPreview.confirmationCode,
        operation_ids: latestRemovalPreview.operationIds
      }
    });
    if (!prepared?.ok) throw new Error(prepared?.error || "removal_prepare_failed");
    removalStatus.textContent = "Removing approved cards from Dex…";
    const execution = await sendToContentScript(tab, service, {
      type: "card-relay-dex-safe-write-execute",
      batch: prepared.result
    });
    if (!execution?.ok) throw new Error("Dex did not return a complete removal report.");
    const reported = await chrome.runtime.sendMessage({
      type: "card-relay-removal-report",
      payload: {
        contract_version: "dex-removal-report-v1",
        plan_id: prepared.result.plan_id,
        confirmation_code: prepared.result.confirmation_code,
        backup_snapshot_id: prepared.result.backup_snapshot_id,
        results: execution.results
      }
    });
    if (!reported?.ok) throw new Error(reported?.error || "removal_report_failed");
    const summary = reported.result;
    latestRemovalPreview = null;
    removalSection.hidden = true;
    removalStatus.textContent = [
      `${summary.succeeded} succeeded, ${summary.failed} failed.`,
      `Recovery backup: ${summary.backup_snapshot_id}.`,
      "Capture Dex again now to verify the result before any further sync."
    ].join(" ");
    diffSummary.textContent = "Dex removal attempt recorded. Capture Dex again to verify it.";
  } catch (error) {
    removalStatus.textContent = [
      `Removal attempt was not completed: ${error.message}.`,
      "Capture Dex again before retrying; a prepared attempt may already have reached Dex."
    ].join(" ");
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

function updateBulkReviewControls() {
  const selected = reviewList.querySelectorAll(".review-select:checked").length;
  reviewSelectedCount.textContent = `${selected} selected`;
  confirmSelectedButton.disabled = selected === 0;
  rejectSelectedButton.disabled = selected === 0;
  confirmSelectedButton.textContent = selected ? `Confirm selected (${selected})` : "Confirm selected";
}

function selectedMappingDecisions(action) {
  const decisions = [];
  for (const checkbox of reviewList.querySelectorAll(".review-select:checked")) {
    const item = checkbox.closest(".review-item");
    const review = visibleMappingReviews.get(item?.dataset.sourceFingerprint || "");
    const selected = item?.querySelector('input[type="radio"]:checked');
    if (review && selected) {
      decisions.push({
        action,
        source_fingerprint: review.source_fingerprint,
        destination_id: selected.value
      });
    }
  }
  return decisions;
}

async function submitMappingDecisions(action) {
  const decisions = selectedMappingDecisions(action);
  if (!decisions.length) return;
  reviewSummary.textContent = `${action === "confirm" ? "Confirming" : "Rejecting"} ${decisions.length} selected match${decisions.length === 1 ? "" : "es"}…`;
  for (const control of reviewSection.querySelectorAll("button, input")) control.disabled = true;
  try {
    const response = await chrome.runtime.sendMessage({
      type: "card-relay-mapping-decisions",
      decisions
    });
    if (!response?.ok) {
      reviewSummary.textContent = response?.error === "companion_update_required"
        ? "Restart the CardRelay companion, save its new pairing token, then retry."
        : `Mappings unchanged: ${response?.error || "unknown error"}`;
      for (const control of reviewSection.querySelectorAll("button, input")) control.disabled = false;
      updateBulkReviewControls();
      return;
    }
    displaySyncPreview(response.result);
  } catch {
    reviewSummary.textContent = "Mappings unchanged: companion unavailable";
    for (const control of reviewSection.querySelectorAll("button, input")) control.disabled = false;
    updateBulkReviewControls();
  }
}

function displayMappingReviews(result) {
  const reviews = result.mapping_reviews || [];
  const total = result.mapping_review_count || 0;
  reviewList.replaceChildren();
  visibleMappingReviews.clear();
  reviewSection.hidden = total === 0;
  reviewToolbar.hidden = total === 0;
  if (!total) {
    reviewSummary.textContent = "No probable or ambiguous matches are waiting for review.";
    return;
  }
  const visibleReviews = reviews.slice(0, 50);
  reviewSummary.textContent = [
    `${total} match${total === 1 ? "" : "es"} waiting for review.`,
    total > visibleReviews.length || result.mapping_reviews_truncated
      ? `Showing the first ${visibleReviews.length}; bulk decisions refresh the queue.`
      : "Select rows, verify the suggested Dex card, then confirm or reject them together."
  ].join(" ");
  for (const review of visibleReviews) {
    visibleMappingReviews.set(review.source_fingerprint, review);
    const item = document.createElement("div");
    item.className = "review-item";
    item.dataset.sourceFingerprint = review.source_fingerprint;
    item.dataset.reviewStatus = review.status;

    const heading = document.createElement("div");
    heading.className = "review-heading";
    const select = document.createElement("input");
    select.type = "checkbox";
    select.className = "review-select";
    select.setAttribute("aria-label", `Select ${identityLabel(review.source_identity)}`);
    select.addEventListener("change", updateBulkReviewControls);
    const source = document.createElement("div");
    source.className = "review-source";
    source.textContent = `Collectr: ${identityLabel(review.source_identity)}`;
    heading.append(select, source);
    const reason = document.createElement("div");
    reason.className = "review-reason";
    reason.textContent = `${review.status}: ${(review.reasons || []).join("; ")}`;
    item.append(heading, reason);

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
    confirm.textContent = "Confirm";
    const reject = document.createElement("button");
    reject.className = "reject";
    reject.textContent = "Reject";
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
  updateBulkReviewControls();
}

selectSuggestedButton.addEventListener("click", () => {
  for (const item of reviewList.querySelectorAll(".review-item")) {
    const checkbox = item.querySelector(".review-select");
    checkbox.checked = item.dataset.reviewStatus === "probable";
  }
  updateBulkReviewControls();
});
confirmSelectedButton.addEventListener("click", () => void submitMappingDecisions("confirm"));
rejectSelectedButton.addEventListener("click", () => void submitMappingDecisions("reject"));

function displaySavedCollectrBackup(result) {
  const latest = result?.latest;
  savedCapture.hidden = !latest;
  if (!latest) return;
  const captured = new Date(latest.captured_at);
  const timestamp = Number.isNaN(captured.getTime())
    ? "saved previously"
    : captured.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
  const backups = Number(result.backup_count || 0);
  savedCapture.textContent = `Using saved Collectr scan · ${timestamp} · ${latest.unique_entries} Pokémon cards / ${latest.total_quantity} total · ${backups} backup${backups === 1 ? "" : "s"}`;
}

async function loadSavedCollectrBackup() {
  try {
    const response = await chrome.runtime.sendMessage({ type: "card-relay-collectr-backup-status" });
    if (!response?.ok) return false;
    displaySavedCollectrBackup(response.result);
    return Boolean(response.result.latest);
  } catch {
    return false;
  }
}
function displaySavedDexBackup(result) {
  const latest = result?.latest;
  savedCapture.hidden = !latest;
  if (!latest) return;
  const captured = new Date(latest.captured_at);
  const timestamp = Number.isNaN(captured.getTime())
    ? "saved previously"
    : captured.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
  const backups = Number(result.backup_count || 0);
  savedCapture.textContent = `Using saved Dex snapshot · ${timestamp} · ${latest.unique_entries} cards / ${latest.total_quantity} total · ${backups} backup${backups === 1 ? "" : "s"}`;
}

async function loadSavedDexBackup() {
  try {
    const response = await chrome.runtime.sendMessage({ type: "card-relay-dex-backup-status" });
    if (!response?.ok) {
      if (response?.error === "companion_update_required") {
        savedCapture.hidden = false;
        savedCapture.textContent = "Restart the CardRelay companion to enable saved Dex snapshots.";
      }
      return false;
    }
    displaySavedDexBackup(response.result);
    return Boolean(response.result.latest);
  } catch {
    return false;
  }
}

async function loadSavedCapture() {
  try {
    const { service } = await activeSupportedTab();
    return service === "dex" ? await loadSavedDexBackup() : await loadSavedCollectrBackup();
  } catch {
    savedCapture.hidden = true;
    return false;
  }
}
async function loadSyncPreview(showErrors = false) {
  try {
    const response = await chrome.runtime.sendMessage({ type: "card-relay-sync-preview" });
    if (!response?.ok) {
      if (showErrors) diffSummary.textContent = "Capture both Collectr and Dex before reviewing your sync.";
      return false;
    }
    displaySyncPreview(response.result);
    return true;
  } catch {
    if (showErrors) diffSummary.textContent = "CardRelay companion is unavailable.";
    return false;
  }
}

document.querySelector("#build-diff").addEventListener("click", async event => {
  const button = event.currentTarget;
  button.disabled = true;
  button.textContent = "Reviewing…";
  diffSummary.textContent = "Comparing Collectr and Dex…";
  diffList.replaceChildren();
  await loadSyncPreview(true);
  button.disabled = false;
  button.textContent = "Review";
});
sendButton.addEventListener("click", async () => {
  sendButton.disabled = true;
  statusElement.textContent = "Saving capture…";
  try {
    const { tab, service } = await activeSupportedTab();
    const type = service === "dex" ? "card-relay-dex-submit" : "card-relay-submit";
    const response = await sendToContentScript(tab, service, { type });
    if (!response?.ok) throw new Error("Capture could not be saved. Run it again.");
    const result = response.result;
    if (service === "dex") {
      statusElement.textContent = result.normalization_complete
        ? "Dex saved. Your sync review is ready below."
        : "Dex saved, but some card finishes need attention before syncing.";
    } else {
      displayCaptureIssues(result.capture_issues);
      const ignored = result.filtered_non_pokemon_count || 0;
      statusElement.textContent = result.completeness === "complete"
        ? `Collectr saved · ${result.unique_entries} Pokémon cards${ignored ? ` · ${ignored} other TCG ignored` : ""}`
        : "Collectr saved, but the capture is incomplete. Run it again before removals.";
    }
    await loadSavedCapture();
    await loadSyncPreview(false);
  } catch (error) {
    statusElement.textContent = error.message;
    sendButton.disabled = false;
  }
});
async function initializePopup() {
  const settings = await chrome.storage.local.get(["companionPort", "pairingToken"]);
  portInput.value = settings.companionPort || 8765;
  tokenInput.value = settings.pairingToken || "";
  const connected = Boolean(settings.pairingToken);
  connectionState.textContent = connected ? "Saved" : "Set up";
  connectionSettings.open = !connected;
  await Promise.all([refreshStatus(), loadSavedCapture(), loadSyncPreview(false)]);
}
void initializePopup();
