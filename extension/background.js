"use strict";

void chrome.storage.session.setAccessLevel({
  accessLevel: "TRUSTED_AND_UNTRUSTED_CONTEXTS"
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (!["card-relay-companion-submit", "card-relay-sync-preview", "card-relay-mapping-decision",
    "card-relay-safe-write-prepare", "card-relay-safe-write-report"]
    .includes(message?.type)) {
    return false;
  }
  chrome.storage.local.get(["companionPort", "pairingToken"]).then(async settings => {
    const port = Number(settings.companionPort || 8765);
    const token = String(settings.pairingToken || "");
    if (!Number.isInteger(port) || port < 1024 || port > 65535 || !token) {
      sendResponse({ ok: false, error: "pairing_required" });
      return;
    }
    try {
      const isPreview = message.type === "card-relay-sync-preview";
      const isMappingDecision = message.type === "card-relay-mapping-decision";
      const isSafeWritePrepare = message.type === "card-relay-safe-write-prepare";
      const isSafeWriteReport = message.type === "card-relay-safe-write-report";
      const isDexWriteObservation = message.capture?.contract_version ===
        "dex-write-observation-v1";
      const isDexChunk = message.capture?.contract_version === "dex-extension-chunk-v1";
      const isDex = message.capture?.contract_version === "dex-extension-v1";
      let capturePath = "/v1/collectr/captures";
      if (isPreview) capturePath = "/v1/sync/previews";
      else if (isMappingDecision) capturePath = "/v1/mappings/decisions";
      else if (isSafeWritePrepare) capturePath = "/v1/dex/safe-write-batches";
      else if (isSafeWriteReport) capturePath = "/v1/dex/safe-write-reports";
      else if (isDexWriteObservation) capturePath = "/v1/dex/write-observations";
      else if (isDexChunk) capturePath = "/v1/dex/capture-chunks";
      else if (isDex) capturePath = "/v1/dex/captures";
      const response = await fetch(`http://127.0.0.1:${port}${capturePath}`, {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${token}`,
          "Content-Type": "application/json"
        },
        body: JSON.stringify(
          isMappingDecision ? message.decision
            : ((isSafeWritePrepare || isSafeWriteReport) ? message.payload : (message.capture || {}))
        ),
        cache: "no-store"
      });
      const payload = await response.json();
      if (response.ok && message.reliabilityCapture === true) {
        const existing = settings.reliabilitySeries;
        if (existing?.version === 1 && Array.isArray(existing.captures)) {
          existing.captures.push({
            collection_fingerprint: payload.collection_fingerprint,
            completeness: payload.completeness,
            unique_entries: payload.unique_entries,
            total_quantity: payload.total_quantity,
            pagination_complete: payload.pagination_complete,
            invalid_record_count: payload.invalid_record_count
          });
          await chrome.storage.local.set({ reliabilitySeries: existing });
        }
      }
      sendResponse(response.ok
        ? { ok: true, result: payload }
        : {
          ok: false,
          error: payload.reason || payload.error || `http_${response.status}`,
          issues: Array.isArray(payload.issues) ? payload.issues.slice(0, 20) : []
        });
    } catch {
      sendResponse({ ok: false, error: "companion_unavailable" });
    }
  });
  return true;
});
