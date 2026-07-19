"use strict";

void chrome.storage.session.setAccessLevel({
  accessLevel: "TRUSTED_AND_UNTRUSTED_CONTEXTS"
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type !== "card-relay-companion-submit") return false;
  chrome.storage.local.get(["companionPort", "pairingToken"]).then(async settings => {
    const port = Number(settings.companionPort || 8765);
    const token = String(settings.pairingToken || "");
    if (!Number.isInteger(port) || port < 1024 || port > 65535 || !token) {
      sendResponse({ ok: false, error: "pairing_required" });
      return;
    }
    try {
      const isDexChunk = message.capture?.contract_version === "dex-extension-chunk-v1";
      const isDex = message.capture?.contract_version === "dex-extension-v1";
      const capturePath = isDexChunk
        ? "/v1/dex/capture-chunks"
        : (isDex ? "/v1/dex/captures" : "/v1/collectr/captures");
      const response = await fetch(`http://127.0.0.1:${port}${capturePath}`, {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${token}`,
          "Content-Type": "application/json"
        },
        body: JSON.stringify(message.capture),
        cache: "no-store"
      });
      const payload = await response.json();
      sendResponse(response.ok
        ? { ok: true, result: payload }
        : { ok: false, error: payload.error || `http_${response.status}` });
    } catch {
      sendResponse({ ok: false, error: "companion_unavailable" });
    }
  });
  return true;
});
