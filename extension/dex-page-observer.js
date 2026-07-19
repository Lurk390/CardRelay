(() => {
  "use strict";

  const channel = "card-relay.dex.v1";
  const maximumResponseBytes = 2 * 1024 * 1024;
  const paginationDelayMilliseconds = 200;
  const recognizedTargets = new Set();
  const cachedPages = {
    collection: new Map(),
    catalog: new Map()
  };
  let captureTarget = null;
  let catalogRequestTemplate = null;
  let catalogStreamKey = null;
  let catalogStreamSize = -1;
  let catalogPaginationRunning = false;

  function isObject(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
  }

  function isPage(payload) {
    return isObject(payload) &&
      Number.isInteger(payload.page) &&
      Number.isInteger(payload.pageSize) &&
      Number.isInteger(payload.totalItems) &&
      Number.isInteger(payload.totalPages) &&
      Array.isArray(payload.result);
  }

  function isCollectionItem(item) {
    return isObject(item) && isObject(item.card) && isObject(item.quantities) &&
      typeof item.cardId === "string";
  }

  function isCatalogCard(item) {
    return isObject(item) && typeof item.cardId === "string" &&
      typeof item.name === "string" && typeof item.number === "string" &&
      typeof item.setId === "string" && isObject(item.set) && Array.isArray(item.variants);
  }

  function sanitizeCard(card) {
    return {
      cardId: card.cardId,
      name: card.name,
      number: card.number,
      setId: card.setId,
      set: {
        id: card.set?.id,
        name: card.set?.name,
        setId: card.set?.setId
      },
      variants: Array.isArray(card.variants)
        ? card.variants.map(variant => ({
          type: variant?.type,
          name: variant?.variant?.name
        }))
        : []
    };
  }

  function sanitizePage(payload, target) {
    if (!isPage(payload)) return null;
    if (payload.result.length === 0 && !recognizedTargets.has(target)) return null;
    if (payload.result.length > 0) {
      const matches = target === "collection" ? isCollectionItem : isCatalogCard;
      if (!payload.result.every(matches)) return null;
      recognizedTargets.add(target);
    }
    const result = target === "collection"
      ? payload.result.map(item => ({
        cardId: item.cardId,
        card: sanitizeCard(item.card),
        quantities: item.quantities
      }))
      : payload.result.map(sanitizeCard);
    return {
      page: payload.page,
      pageSize: payload.pageSize,
      result,
      totalItems: payload.totalItems,
      totalPages: payload.totalPages
    };
  }

  function publish(target, sanitized) {
    if (captureTarget !== target) return;
    window.postMessage({
      channel,
      type: "response",
      target,
      payload: sanitized
    }, location.origin);
  }

  function catalogRequestDetails(args, payload) {
    if (!args || typeof Request !== "function") return null;
    try {
      const request = new Request(args[0], args[1]);
      const url = new URL(request.url);
      if (request.method !== "GET" || url.protocol !== "https:") return null;
      if (Number(url.searchParams.get("page")) !== payload.page) return null;
      url.searchParams.delete("page");
      return { request, streamKey: url.toString() };
    } catch {
      return null;
    }
  }

  function acceptCatalogStream(requestArgs, payload) {
    const details = catalogRequestDetails(requestArgs, payload);
    if (!details) return catalogStreamKey === null;
    if (catalogStreamKey === details.streamKey) return true;
    if (payload.totalItems <= catalogStreamSize) return false;
    catalogStreamKey = details.streamKey;
    catalogStreamSize = payload.totalItems;
    catalogRequestTemplate = details.request;
    cachedPages.catalog.clear();
    if (captureTarget === "catalog") {
      window.postMessage({ channel, type: "stream-reset", target: "catalog" }, location.origin);
    }
    return true;
  }

  function inspectPayload(payload, requestArgs) {
    const recognized = [];
    for (const target of ["collection", "catalog"]) {
      const sanitized = sanitizePage(payload, target);
      if (!sanitized) continue;
      if (target === "catalog" && !acceptCatalogStream(requestArgs, sanitized)) continue;
      cachedPages[target].set(sanitized.page, sanitized);
      publish(target, sanitized);
      recognized.push(target);
    }
    return recognized;
  }

  function rememberCatalogRequest(args, payload) {
    const details = catalogRequestDetails(args, payload);
    if (details?.streamKey === catalogStreamKey) catalogRequestTemplate = details.request;
  }

  function waitForPaginationDelay() {
    return new Promise(resolve => setTimeout(resolve, paginationDelayMilliseconds));
  }

  async function captureRemainingCatalogPages() {
    if (catalogPaginationRunning || !catalogRequestTemplate || captureTarget !== "catalog") return;
    const firstPage = [...cachedPages.catalog.values()][0];
    if (!firstPage || firstPage.totalPages < 1 || firstPage.totalPages > 1000) return;
    catalogPaginationRunning = true;
    try {
      for (let page = 1; page <= firstPage.totalPages; page += 1) {
        if (captureTarget !== "catalog") break;
        if (cachedPages.catalog.has(page)) continue;
        await waitForPaginationDelay();
        const url = new URL(catalogRequestTemplate.url);
        url.searchParams.set("page", String(page));
        const request = new Request(url, catalogRequestTemplate);
        const response = await Reflect.apply(originalFetch, window, [request]);
        if (!response.ok) break;
        await inspectResponse(response, [request]);
      }
    } catch {
      // A manual browse remains available when Dex rejects automated pagination.
    } finally {
      catalogPaginationRunning = false;
    }
  }

  async function inspectResponse(response, requestArgs = null) {
    const declaredLength = Number(response.headers?.get?.("content-length") || "0");
    if (declaredLength > maximumResponseBytes) return;
    const contentType = (response.headers?.get?.("content-type") || "").toLowerCase();
    if (contentType && !contentType.includes("json")) return;
    try {
      const text = await response.clone().text();
      if (text.length === 0 || text.length > maximumResponseBytes) return;
      const payload = JSON.parse(text);
      const recognized = inspectPayload(payload, requestArgs);
      if (recognized.includes("catalog") && requestArgs) {
        rememberCatalogRequest(requestArgs, payload);
        if (captureTarget === "catalog") void captureRemainingCatalogPages();
      }
    } catch {}
  }

  window.addEventListener("message", event => {
    if (event.source !== window || event.origin !== location.origin) return;
    const message = event.data;
    if (!message || message.channel !== channel || message.type !== "capture-control") return;
    captureTarget = ["collection", "catalog"].includes(message.target)
      ? message.target
      : null;
    if (captureTarget) {
      for (const page of [...cachedPages[captureTarget].values()]
        .sort((left, right) => left.page - right.page)) {
        publish(captureTarget, page);
      }
      if (captureTarget === "catalog") void captureRemainingCatalogPages();
    }
  });

  const originalFetch = window.fetch;
  window.fetch = async function (...args) {
    const response = await Reflect.apply(originalFetch, this, args);
    void inspectResponse(response, args);
    return response;
  };

  const originalOpen = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function (method, url, ...rest) {
    this.addEventListener("load", () => {
      try {
        const text = this.responseType === "json" ? JSON.stringify(this.response) : this.responseText;
        if (text.length === 0 || text.length > maximumResponseBytes) return;
        inspectPayload(JSON.parse(text));
      } catch {}
    }, { once: true });
    return Reflect.apply(originalOpen, this, [method, url, ...rest]);
  };
})();
