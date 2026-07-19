"use strict";

const portInput = document.querySelector("#port");
const tokenInput = document.querySelector("#token");
const statusElement = document.querySelector("#status");
const startButton = document.querySelector("#start");
const catalogButton = document.querySelector("#start-catalog");
const sendButton = document.querySelector("#send");
const diffSummary = document.querySelector("#diff-summary");
const diffList = document.querySelector("#diff-list");

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
    status.collectionConflict || status.catalogConflict
      ? "Conflicting repeated page detected; restart that capture."
      : "Catalog pages load gradually; manual browsing remains available."
  ].join("\n");
}

function configureForService(service) {
  const isDex = service === "dex";
  startButton.textContent = isDex ? "Start Dex collection capture" : "Start portfolio capture";
  catalogButton.hidden = !isDex;
  sendButton.textContent = isDex ? "Send Dex read-only preview" : "Send preview to CardRelay";
}

async function refreshStatus() {
  try {
    const { tab, service } = await activeSupportedTab();
    configureForService(service);
    const type = service === "dex" ? "card-relay-dex-status" : "card-relay-status";
    const response = await chrome.tabs.sendMessage(tab.id, { type });
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
      const response = await chrome.tabs.sendMessage(tab.id, {
        type: "card-relay-dex-start",
        target: "collection"
      });
      if (!response?.ok) throw new Error("Unable to start Dex collection capture.");
      displayDexStatus(response.status);
      return;
    }
    const response = await chrome.tabs.sendMessage(tab.id, { type: "card-relay-start" });
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
    const response = await chrome.tabs.sendMessage(tab.id, {
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
    result.truncated ? "The displayed list is truncated." : "All changes are displayed.",
    "Writes are disabled until the Dex write contract is separately verified."
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
    const response = await chrome.tabs.sendMessage(tab.id, { type });
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
void refreshStatus();
