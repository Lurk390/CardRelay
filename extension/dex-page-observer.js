(() => {
  "use strict";

  const channel = "card-relay.dex.v1";
  const maximumResponseBytes = 2 * 1024 * 1024;
  const maximumWriteBodyBytes = 128 * 1024;
  const maximumWriteObservations = 10;
  const paginationDelayMilliseconds = 200;
  const safeRouteSegments = new Set([
    "api", "v1", "v2", "card", "cards", "collection", "collections",
    "portfolio", "quantity", "quantities", "user", "users", "me"
  ]);
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
  let writeResearchArmed = false;
  let writeObservationCount = 0;
  const xhrWriteRequests = new WeakMap();

  function isObject(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
  }

  function sanitizedKey(key) {
    if (!/^[A-Za-z][A-Za-z0-9_-]{0,63}$/.test(key)) return "{dynamic_key}";
    if (/^[0-9a-f]{8}-[0-9a-f-]{27,}$/i.test(key)) return "{dynamic_key}";
    if (key.length >= 24 && /^[A-Za-z0-9_-]+$/.test(key)) return "{dynamic_key}";
    return key;
  }

  function stringFormat(value) {
    if (/^[0-9a-f]{8}-[0-9a-f-]{27,}$/i.test(value)) return "uuid";
    if (/^https?:\/\//i.test(value)) return "url";
    if (value.length > 64 || /^[A-Za-z0-9_-]{24,}$/.test(value)) return "opaque";
    return "text";
  }

  function jsonShape(value, depth = 0) {
    if (depth >= 6) return { kind: "truncated" };
    if (value === null) return { kind: "null" };
    if (Array.isArray(value)) {
      return {
        kind: "array",
        items: value.slice(0, 10).map(item => jsonShape(item, depth + 1))
      };
    }
    if (isObject(value)) {
      const fields = {};
      for (const [key, child] of Object.entries(value).slice(0, 50)) {
        fields[sanitizedKey(key)] = jsonShape(child, depth + 1);
      }
      return { kind: "object", fields };
    }
    if (typeof value === "string") return { kind: "string", format: stringFormat(value) };
    if (typeof value === "number") {
      return { kind: Number.isInteger(value) ? "integer" : "number" };
    }
    if (typeof value === "boolean") return { kind: "boolean" };
    return { kind: "unsupported" };
  }

  function sanitizedRoute(rawUrl) {
    try {
      const url = new URL(rawUrl, location.origin);
      if (url.protocol !== "https:" ||
        (url.hostname !== "dextcg.com" && !url.hostname.endsWith(".dextcg.com"))) return null;
      const rawSegments = url.pathname.split("/").filter(Boolean);
      const segments = rawSegments.map(segment => {
        const normalized = segment.toLowerCase();
        return safeRouteSegments.has(normalized) ? normalized : "{segment}";
      });
      if (segments[0] !== "api") return null;
      return {
        origin_host: url.hostname,
        route_template: `/${segments.join("/")}`,
        query_keys: [...new Set([...url.searchParams.keys()].map(sanitizedKey))].sort(),
        rawSegments,
        sanitizedSegments: segments
      };
    } catch {
      return null;
    }
  }

  function scalarPaths(value, prefix, depth = 0) {
    if (depth >= 6 || value === null) return [];
    if (["string", "number", "boolean"].includes(typeof value)) {
      return [{ source: prefix, value: String(value) }];
    }
    if (!isObject(value)) return [];
    const paths = [];
    for (const [key, child] of Object.entries(value).slice(0, 50)) {
      if (!/^[A-Za-z][A-Za-z0-9_-]{0,63}$/.test(key)) continue;
      paths.push(...scalarPaths(child, `${prefix}.${key}`, depth + 1));
    }
    return paths;
  }

  function pathBindings(route, payload, prefix) {
    if (payload === null) return [];
    const candidates = scalarPaths(payload, prefix);
    const bindings = [];
    for (const [segmentIndex, segment] of route.rawSegments.entries()) {
      if (route.sanitizedSegments[segmentIndex] !== "{segment}") continue;
      for (const candidate of candidates) {
        if (candidate.value === segment) {
          bindings.push({ segment_index: segmentIndex, source: candidate.source });
        }
      }
    }
    return bindings;
  }

  function writeRequestObservation(method, rawUrl, bodyText) {
    const normalizedMethod = String(method || "GET").toUpperCase();
    if (!["POST", "PUT", "PATCH", "DELETE"].includes(normalizedMethod)) return null;
    if (typeof bodyText !== "string" || bodyText.length > maximumWriteBodyBytes) return null;
    const route = sanitizedRoute(rawUrl);
    if (!route) return null;
    try {
      const payload = bodyText.length === 0 ? null : JSON.parse(bodyText);
      const { rawSegments: _rawSegments, sanitizedSegments: _sanitizedSegments, ...publicRoute } = route;
      return {
        public: {
          method: normalizedMethod,
          ...publicRoute,
          request_shape: jsonShape(payload)
        },
        route,
        requestPayload: payload
      };
    } catch {
      return null;
    }
  }

  async function prepareFetchWriteObservation(args) {
    if (!writeResearchArmed || writeObservationCount >= maximumWriteObservations ||
      typeof Request !== "function") return null;
    try {
      const input = args[0] instanceof Request ? args[0].clone() : args[0];
      const request = new Request(input, args[1]);
      const contentType = (request.headers?.get?.("content-type") || "").toLowerCase();
      if (contentType && !contentType.includes("json")) return null;
      const bodyText = await request.clone().text();
      return writeRequestObservation(request.method, request.url, bodyText);
    } catch {
      return null;
    }
  }

  async function responseObservation(response) {
    const declaredLength = Number(response.headers?.get?.("content-length") || "0");
    if (declaredLength > maximumWriteBodyBytes || response.status === 204) {
      return { shape: null, payload: null };
    }
    const contentType = (response.headers?.get?.("content-type") || "").toLowerCase();
    if (contentType && !contentType.includes("json")) return { shape: null, payload: null };
    try {
      const text = await response.clone().text();
      if (text.length === 0 || text.length > maximumWriteBodyBytes) {
        return { shape: null, payload: null };
      }
      const payload = JSON.parse(text);
      return { shape: jsonShape(payload), payload };
    } catch {
      return { shape: null, payload: null };
    }
  }

  async function publishWriteObservation(requestPromise, responseStatus, shapePromise) {
    const request = await requestPromise;
    if (!request || !writeResearchArmed || writeObservationCount >= maximumWriteObservations) return;
    const response = await shapePromise;
    const bindings = [
      ...pathBindings(request.route, request.requestPayload, "request"),
      ...pathBindings(request.route, response.payload, "response")
    ];
    writeObservationCount += 1;
    window.postMessage({
      channel,
      type: "write-observation",
      target: "write-research",
      payload: {
        ...request.public,
        path_parameter_bindings: bindings,
        response_status: responseStatus,
        response_shape: response.shape
      }
    }, location.origin);
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
      typeof item.id === "string" && typeof item.cardId === "string";
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
        id: item.id,
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

  function validSafeWriteCommand(command) {
    if (!command || typeof command !== "object") return false;
    if (!["POST", "PATCH"].includes(command.method)) return false;
    if (command.origin !== "https://clients.dextcg.com") return false;
    if (command.method === "POST" && command.path !== "/api/user/cards") return false;
    if (command.method === "PATCH" && !/^\/api\/user\/cards\/[A-Za-z0-9_-]{1,256}$/.test(command.path)) {
      return false;
    }
    const body = command.body;
    if (!body || typeof body !== "object" || typeof body.cardId !== "string" ||
      body.cardId.length === 0 || body.cardId.length > 256 || !body.quantities ||
      typeof body.quantities !== "object" || Array.isArray(body.quantities)) return false;
    const entries = Object.entries(body.quantities);
    return entries.length > 0 && entries.length <= 50 && entries.every(([key, value]) =>
      /^[A-Za-z][A-Za-z0-9]*$/.test(key) && Number.isInteger(value) && value >= 0 && value <= 1000000
    );
  }

  function retryableStatus(status) {
    return status === 429 || status >= 500;
  }

  async function executeSafeWrite(command) {
    if (!validSafeWriteCommand(command)) {
      return { operation_id: command?.operation_id || "invalid", succeeded: false,
        outcome: "invalid_response", status: null, attempts: 1 };
    }
    const maximumAttempts = command.method === "PATCH" ? 3 : 1;
    for (let attempt = 1; attempt <= maximumAttempts; attempt += 1) {
      try {
        const response = await Reflect.apply(originalFetch, window, [`${command.origin}${command.path}`, {
          method: command.method,
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(command.body),
          cache: "no-store"
        }]);
        if (response.ok) {
          return { operation_id: command.operation_id, succeeded: true, outcome: "succeeded",
            status: response.status, attempts: attempt };
        }
        if (attempt < maximumAttempts && retryableStatus(response.status)) {
          await new Promise(resolve => setTimeout(resolve, attempt * 250));
          continue;
        }
        return { operation_id: command.operation_id, succeeded: false, outcome: "http_error",
          status: response.status, attempts: attempt };
      } catch {
        if (attempt < maximumAttempts) {
          await new Promise(resolve => setTimeout(resolve, attempt * 250));
          continue;
        }
        return { operation_id: command.operation_id, succeeded: false,
          outcome: command.method === "POST" ? "uncertain_addition" : "network_error",
          status: null, attempts: attempt };
      }
    }
    return { operation_id: command.operation_id, succeeded: false, outcome: "network_error",
      status: null, attempts: maximumAttempts };
  }

  async function executeSafeWriteBatch(batch) {
    if (!batch || batch.contract_version !== "dex-safe-write-batch-v1" ||
      !Array.isArray(batch.commands) || batch.commands.length === 0 || batch.commands.length > 50) {
      return [];
    }
    const results = [];
    for (const command of batch.commands) results.push(await executeSafeWrite(command));
    return results;
  }

  window.addEventListener("message", event => {
    if (event.source !== window || event.origin !== location.origin) return;
    const message = event.data;
    if (!message || message.channel !== channel) return;
    if (message.type === "safe-write-execute") {
      void executeSafeWriteBatch(message.batch).then(results => {
        window.postMessage({ channel, type: "safe-write-result", requestId: message.requestId, results }, location.origin);
      });
      return;
    }
    if (message.type !== "capture-control") return;
    writeResearchArmed = message.target === "write-research";
    if (writeResearchArmed) writeObservationCount = 0;
    captureTarget = ["collection", "catalog"].includes(message.target) ? message.target : null;
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
    const writeRequest = prepareFetchWriteObservation(args);
    const response = await Reflect.apply(originalFetch, this, args);
    if (writeResearchArmed) {
      void publishWriteObservation(writeRequest, response.status, responseObservation(response));
    }
    void inspectResponse(response, args);
    return response;
  };

  const originalOpen = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function (method, url, ...rest) {
    xhrWriteRequests.set(this, { method, url });
    this.addEventListener("load", () => {
      try {
        const text = this.responseType === "json" ? JSON.stringify(this.response) : this.responseText;
        if (text.length === 0 || text.length > maximumResponseBytes) return;
        inspectPayload(JSON.parse(text));
      } catch {}
    }, { once: true });
    return Reflect.apply(originalOpen, this, [method, url, ...rest]);
  };

  const originalSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.send = function (body) {
    const details = xhrWriteRequests.get(this);
    if (writeResearchArmed && details && (typeof body === "string" || body == null)) {
      const request = Promise.resolve(
        writeRequestObservation(details.method, details.url, body == null ? "" : body)
      );
      this.addEventListener("load", () => {
        let response = { shape: null, payload: null };
        try {
          const text = this.responseType === "json"
            ? JSON.stringify(this.response)
            : this.responseText;
          if (text.length > 0 && text.length <= maximumWriteBodyBytes) {
            const payload = JSON.parse(text);
            response = { shape: jsonShape(payload), payload };
          }
        } catch {}
        void publishWriteObservation(request, this.status, Promise.resolve(response));
      }, { once: true });
    }
    return Reflect.apply(originalSend, this, [body]);
  };
})();
