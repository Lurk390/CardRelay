(() => {
  "use strict";

  const channel = "card-relay.dex.v1";
  const maximumPages = 1000;
  const catalogPagesPerChunk = 8;
  const maximumWriteObservations = 10;
  const maximumWriteObservationBytes = 256 * 1024;
  const storageKey = "cardRelayDexCaptureV1";
  const pages = {
    collection: new Map(),
    catalog: new Map()
  };
  const conflicts = { collection: false, catalog: false };
  const writeObservations = [];
  const safeWriteRequests = new Map();
  let activeTarget = null;

  function serializedState() {
    return {
      activeTarget: ["collection", "catalog"].includes(activeTarget) ? activeTarget : null,
      conflicts: { ...conflicts },
      collectionPages: ordered("collection"),
      // The full Dex catalog can exceed extension storage quotas. It remains
      // sanitized in this tab's memory and is never persisted by Chrome.
      catalogPages: []
    };
  }

  async function persist() {
    await chrome.storage.session.set({ [storageKey]: serializedState() });
  }

  async function restore() {
    const stored = (await chrome.storage.session.get(storageKey))[storageKey];
    if (!stored || typeof stored !== "object") return;
    for (const [target, key] of [
      ["collection", "collectionPages"],
      ["catalog", "catalogPages"]
    ]) {
      const storedPages = Array.isArray(stored[key]) ? stored[key] : [];
      for (const page of storedPages.slice(0, maximumPages)) {
        if (Number.isInteger(page?.page) && page.page >= 1) pages[target].set(page.page, page);
      }
      conflicts[target] = stored.conflicts?.[target] === true;
    }
    activeTarget = ["collection", "catalog"].includes(stored.activeTarget)
      ? stored.activeTarget
      : null;
    if (activeTarget) {
      window.postMessage({ channel, type: "capture-control", target: activeTarget }, location.origin);
    }
  }

  const ready = restore();

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
    if (!message || message.channel !== channel) return;
    if (message.type === "write-observation" && message.target === "write-research") {
      if (writeObservations.length < maximumWriteObservations &&
        message.payload && typeof message.payload === "object" &&
        JSON.stringify(message.payload).length <= maximumWriteObservationBytes) {
        writeObservations.push(message.payload);
      }
      return;
    }
    if (message.type === "safe-write-result" && typeof message.requestId === "string") {
      const settle = safeWriteRequests.get(message.requestId);
      if (settle) {
        safeWriteRequests.delete(message.requestId);
        settle(Array.isArray(message.results) ? message.results : []);
      }
      return;
    }
    if (!["collection", "catalog"].includes(message.target)) return;
    if (message.type === "stream-reset") {
      pages[message.target].clear();
      conflicts[message.target] = false;
      if (message.target === "collection") void persist();
      return;
    }
    if (message.type !== "response") return;
    const payload = message.payload;
    if (!Number.isInteger(payload?.page) || payload.page < 1) return;
    const targetPages = pages[message.target];
    if (!targetPages.has(payload.page) && targetPages.size >= maximumPages) return;
    const previous = targetPages.get(payload.page);
    if (previous && !samePayload(previous, payload)) conflicts[message.target] = true;
    targetPages.set(payload.page, payload);
    if (message.target === "collection") {
      if (complete("collection")) {
        activeTarget = null;
        window.postMessage({ channel, type: "capture-control", target: null }, location.origin);
      }
      void persist();
    }
  });

  function ordered(target) {
    return [...pages[target].values()].sort((left, right) => left.page - right.page);
  }

  function complete(target) {
    const captured = ordered(target);
    if (captured.length === 0 || conflicts[target]) return false;
    const totalPages = captured[0].totalPages;
    return Number.isInteger(totalPages) && totalPages >= 1 &&
      captured.length === totalPages &&
      captured.every((page, index) => page.page === index + 1 && page.totalPages === totalPages);
  }

  function status() {
    const collectionPages = ordered("collection");
    const catalogPages = ordered("catalog");
    return {
      page: location.pathname,
      activeTarget,
      collectionPageCount: pages.collection.size,
      catalogPageCount: pages.catalog.size,
      collectionTotalPages: collectionPages[0]?.totalPages ?? null,
      catalogTotalPages: catalogPages[0]?.totalPages ?? null,
      collectionComplete: complete("collection"),
      catalogComplete: complete("catalog"),
      collectionConflict: conflicts.collection,
      catalogConflict: conflicts.catalog,
      writeResearchArmed: activeTarget === "write-research",
      writeObservationCount: writeObservations.length
    };
  }

  async function start(target) {
    if (!["collection", "catalog", "write-research"].includes(target)) {
      return { ok: false, error: "invalid_capture_target" };
    }
    if (target === "write-research") {
      writeObservations.length = 0;
      activeTarget = target;
      window.postMessage({ channel, type: "capture-control", target }, location.origin);
      return { ok: true, status: status() };
    }
    writeObservations.length = 0;
    pages[target].clear();
    conflicts[target] = false;
    activeTarget = target;
    window.postMessage({ channel, type: "capture-control", target }, location.origin);
    await persist();
    return { ok: true, status: status() };
  }

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message?.type === "card-relay-dex-status") {
      ready.then(() => sendResponse({ ok: true, status: status() }));
      return true;
    }
    if (message?.type === "card-relay-dex-start") {
      ready.then(() => start(message.target)).then(sendResponse);
      return true;
    }
    if (message?.type === "card-relay-dex-submit") {
      ready.then(async () => {
        if (!complete("collection") || !complete("catalog")) {
          return { ok: false, error: "capture_not_ready", status: status() };
        }
        activeTarget = null;
        window.postMessage({ channel, type: "capture-control", target: null }, location.origin);
        await persist();
        const catalogPages = ordered("catalog");
        const chunkCount = Math.ceil(catalogPages.length / catalogPagesPerChunk);
        const uploadId = crypto.randomUUID();
        let response = null;
        for (let chunkIndex = 0; chunkIndex < chunkCount; chunkIndex += 1) {
          const capture = {
            contract_version: "dex-extension-chunk-v1",
            upload_id: uploadId,
            chunk_index: chunkIndex,
            chunk_count: chunkCount,
            collection_pages: chunkIndex === 0 ? ordered("collection") : [],
            catalog_pages: catalogPages.slice(
              chunkIndex * catalogPagesPerChunk,
              (chunkIndex + 1) * catalogPagesPerChunk
            )
          };
          response = await chrome.runtime.sendMessage({
            type: "card-relay-companion-submit",
            capture
          });
          if (!response?.ok) return response;
        }
        return response;
      }).then(sendResponse)
        .catch(() => sendResponse({ ok: false, error: "companion_unavailable" }));
      return true;
    }
    if (message?.type === "card-relay-dex-write-research-submit") {
      ready.then(async () => {
        if (writeObservations.length === 0) {
          return { ok: false, error: "write_observation_required", status: status() };
        }
        activeTarget = null;
        window.postMessage({ channel, type: "capture-control", target: null }, location.origin);
        const response = await chrome.runtime.sendMessage({
          type: "card-relay-companion-submit",
          capture: {
            contract_version: "dex-write-observation-v1",
            observations: writeObservations
          }
        });
        if (response?.ok) writeObservations.length = 0;
        return response;
      }).then(sendResponse)
        .catch(() => sendResponse({ ok: false, error: "companion_unavailable" }));
      return true;
    }
    if (message?.type === "card-relay-dex-safe-write-execute") {
      const requestId = crypto.randomUUID();
      new Promise(resolve => {
        safeWriteRequests.set(requestId, resolve);
        window.postMessage({
          channel,
          type: "safe-write-execute",
          requestId,
          batch: message.batch
        }, location.origin);
        setTimeout(() => {
          const settle = safeWriteRequests.get(requestId);
          if (settle) {
            safeWriteRequests.delete(requestId);
            settle([]);
          }
        }, 30000);
      }).then(results => sendResponse({ ok: results.length > 0, results }));
      return true;
    }
    return false;
  });
})();
