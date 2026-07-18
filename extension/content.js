(() => {
  "use strict";

  const channel = "card-relay.collectr.v1";
  const sessionKey = "cardRelayCollectrCapture";
  const productPages = new Map();
  const conditionPayloads = [];
  const gradingPayloads = [];
  let exactViewVerified = true;
  let conflictingPageObserved = false;
  let captureRunning = false;
  let captureActive = false;
  let visibleTotalQuantity = null;

  function uniquePayloads(payloads) {
    const unique = [];
    for (const payload of payloads) {
      if (unique.length >= 5) break;
      if (!unique.some(existing => samePayload(existing, payload))) unique.push(payload);
    }
    return unique;
  }

  async function persistSessionState(active) {
    await chrome.storage.session.set({
      [sessionKey]: {
        active,
        visibleTotalQuantity,
        conditionPayloads,
        gradingPayloads
      }
    });
  }

  function rememberLookup(payloads, payload) {
    const next = uniquePayloads([...payloads, payload]);
    payloads.splice(0, payloads.length, ...next);
    void sessionInitialization.then(() => persistSessionState(captureActive));
  }

  function samePayload(left, right) {
    try {
      return JSON.stringify(left) === JSON.stringify(right);
    } catch {
      return false;
    }
  }

  window.addEventListener("message", event => {
    if (event.source !== window || event.origin !== location.origin) return;
    const message = event.data;
    if (!message || message.channel !== channel || message.type !== "response") return;
    if (message.endpoint === "products") {
      if (!Number.isInteger(message.offset) || message.offset < 0 || productPages.size >= 501) return;
      const previous = productPages.get(message.offset);
      if (previous && !samePayload(previous, message.payload)) conflictingPageObserved = true;
      productPages.set(message.offset, message.payload);
      exactViewVerified = exactViewVerified && message.exactView === true;
    } else if (message.endpoint === "conditions") {
      rememberLookup(conditionPayloads, message.payload);
    } else if (message.endpoint === "grading") {
      rememberLookup(gradingPayloads, message.payload);
    }
  });

  function visibleCardTotal() {
    for (const element of document.querySelectorAll("*")) {
      if (element.children.length !== 0) continue;
      const text = (element.textContent || "").trim();
      if (!/^Cards(?:\s*\([^)]*\))?$/i.test(text)) continue;
      const container = element.parentElement?.parentElement || element.parentElement;
      const match = (container?.textContent || "")
        .match(/Cards(?:\s*\([^)]*\))?\D{0,60}([\d,]+)/i);
      if (match) return Number(match[1].replaceAll(",", ""));
    }
    const bodyMatch = (document.body?.innerText || "")
      .match(/(?:^|\n)\s*Cards(?:\s*\([^)]*\))?\s*\n\s*([\d,]+)/im);
    if (bodyMatch) return Number(bodyMatch[1].replaceAll(",", ""));
    return null;
  }

  function resetCapture() {
    productPages.clear();
    exactViewVerified = true;
    conflictingPageObserved = false;
  }

  function orderedPages() {
    return [...productPages.entries()]
      .sort(([left], [right]) => left - right)
      .map(([offset, payload]) => ({ offset, payload }));
  }

  function terminalPageSeen() {
    const pages = orderedPages();
    const finalPayload = pages.at(-1)?.payload;
    return Array.isArray(finalPayload?.data) && finalPayload.data.length === 0;
  }

  function offsetsContiguous() {
    return orderedPages().every((page, index) => page.offset === index * 30);
  }

  function status() {
    return {
      page: location.pathname,
      productPageCount: productPages.size,
      terminalPageSeen: terminalPageSeen(),
      offsetsContiguous: offsetsContiguous(),
      exactViewVerified,
      conflictingPageObserved,
      visibleTotalQuantity,
      conditionLookupCount: conditionPayloads.length,
      gradingLookupCount: gradingPayloads.length,
      captureRunning
    };
  }

  const delay = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));

  async function autoScroll() {
    if (captureRunning || !location.pathname.startsWith("/portfolio/products")) return;
    captureActive = true;
    captureRunning = true;
    let stableIterations = 0;
    let previousCount = -1;
    for (let index = 0; index < 202 && !terminalPageSeen(); index += 1) {
      await delay(1000);
      if (productPages.size === previousCount) stableIterations += 1;
      else stableIterations = 0;
      previousCount = productPages.size;
      if (stableIterations >= 4) break;
      window.scrollTo(0, document.documentElement.scrollHeight);
    }
    captureRunning = false;
    captureActive = false;
    await persistSessionState(false);
  }

  async function prepareCapture() {
    resetCapture();
    captureActive = true;
    const observedTotal = visibleCardTotal();
    if (observedTotal !== null) visibleTotalQuantity = observedTotal;
    await persistSessionState(true);
    return {
      navigateToProducts: !location.pathname.startsWith("/portfolio/products"),
      status: status()
    };
  }

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message?.type === "card-relay-status") {
      sendResponse({ ok: true, status: status() });
      return false;
    }
    if (message?.type === "card-relay-start") {
      prepareCapture().then(result => {
        sendResponse({ ok: true, ...result });
        if (!result.navigateToProducts) void autoScroll();
      }).catch(() => sendResponse({ ok: false, error: "capture_start_failed" }));
      return true;
    }
    if (message?.type === "card-relay-submit") {
      if (
        productPages.size === 0 ||
        conflictingPageObserved ||
        !offsetsContiguous() ||
        !exactViewVerified
      ) {
        sendResponse({ ok: false, error: "capture_not_ready", status: status() });
        return false;
      }
      const capture = {
        contract_version: "collectr-extension-v1",
        product_pages: orderedPages(),
        visible_total_quantity: visibleTotalQuantity,
        condition_payloads: conditionPayloads,
        grading_payloads: gradingPayloads,
        exact_view_verified: exactViewVerified
      };
      chrome.runtime.sendMessage({ type: "card-relay-companion-submit", capture })
        .then(response => {
          if (response?.ok) resetCapture();
          sendResponse(response);
        })
        .catch(() => sendResponse({ ok: false, error: "companion_unavailable" }));
      return true;
    }
    return false;
  });

  const sessionInitialization = chrome.storage.session.get(sessionKey).then(stored => {
    const capture = stored[sessionKey];
    if (!capture) return;
    captureActive = capture.active === true;
    visibleTotalQuantity = Number.isInteger(capture.visibleTotalQuantity)
      ? capture.visibleTotalQuantity
      : null;
    conditionPayloads.push(...uniquePayloads(capture.conditionPayloads || []));
    gradingPayloads.push(...uniquePayloads(capture.gradingPayloads || []));
    if (captureActive && location.pathname.startsWith("/portfolio/products")) {
      void autoScroll();
    }
  });
})();
