"use strict";

const portInput = document.querySelector("#port");
const tokenInput = document.querySelector("#token");
const statusElement = document.querySelector("#status");
const sendButton = document.querySelector("#send");

async function activeCollectrTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id || !tab.url?.startsWith("https://app.getcollectr.com/")) {
    throw new Error("Open app.getcollectr.com in the active tab.");
  }
  return tab;
}

function displayStatus(status) {
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

async function refreshStatus() {
  try {
    const tab = await activeCollectrTab();
    const response = await chrome.tabs.sendMessage(tab.id, { type: "card-relay-status" });
    if (!response?.ok) throw new Error("CardRelay content script is unavailable. Reload Collectr.");
    displayStatus(response.status);
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

document.querySelector("#start").addEventListener("click", async () => {
  try {
    const tab = await activeCollectrTab();
    const response = await chrome.tabs.sendMessage(tab.id, { type: "card-relay-start" });
    if (!response?.ok) throw new Error("Unable to start capture. Reload Collectr and retry.");
    if (response.navigateToProducts) {
      await chrome.tabs.update(tab.id, { url: "https://app.getcollectr.com/portfolio/products" });
      window.close();
      return;
    }
    displayStatus(response.status);
  } catch (error) {
    statusElement.textContent = error.message;
  }
});

document.querySelector("#refresh").addEventListener("click", refreshStatus);

document.querySelector("#send").addEventListener("click", async () => {
  sendButton.disabled = true;
  statusElement.textContent = "Validating preview in CardRelay…";
  try {
    const tab = await activeCollectrTab();
    const response = await chrome.tabs.sendMessage(tab.id, { type: "card-relay-submit" });
    if (!response?.ok) throw new Error(`Preview rejected: ${response?.error || "unknown error"}`);
    const result = response.result;
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
