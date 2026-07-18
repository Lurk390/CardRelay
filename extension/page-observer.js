(() => {
  "use strict";

  const channel = "card-relay.collectr.v1";
  const apiHost = "api-v2.getcollectr.com";
  const productsPath = /^\/collections\/[^/]+\/products\/?$/;
  const metadataPaths = new Map([
    ["/data/card-conditions", "conditions"],
    ["/data/grading-scales", "grading"]
  ]);
  const cachedMetadata = new Map([
    ["cardConditions", "conditions"],
    ["gradedCardScales", "grading"]
  ]);
  const maximumCachedLookupBytes = 512 * 1024;

  function describeEndpoint(rawUrl) {
    let url;
    try {
      url = new URL(rawUrl, window.location.href);
    } catch {
      return null;
    }
    if (url.hostname !== apiHost) return null;
    if (productsPath.test(url.pathname)) {
      const offset = Number(url.searchParams.get("offset") || "0");
      const limit = Number(url.searchParams.get("limit") || "30");
      const unstacked = (url.searchParams.get("unstackedView") || "").toLowerCase();
      if (!Number.isInteger(offset) || offset < 0 || limit !== 30) return null;
      return {
        endpoint: "products",
        offset,
        exactView: unstacked === "true" || unstacked === "1"
      };
    }
    const endpoint = metadataPaths.get(url.pathname);
    return endpoint ? { endpoint } : null;
  }

  function publish(rawUrl, payload) {
    const descriptor = describeEndpoint(rawUrl);
    if (!descriptor || payload === null || typeof payload !== "object") return;
    window.postMessage({ channel, type: "response", ...descriptor, payload }, location.origin);
  }

  function publishLookup(endpoint, payload) {
    if (payload === null || typeof payload !== "object") return;
    window.postMessage({ channel, type: "response", endpoint, payload }, location.origin);
  }

  function readCachedLookup(key) {
    try {
      const raw = localStorage.getItem(key);
      if (!raw || raw.length > maximumCachedLookupBytes) return null;
      const cached = JSON.parse(raw);
      if (!cached || typeof cached !== "object" || !("value" in cached)) return null;
      const expiry = cached.expiry === "Infinity" ? Infinity : Number(cached.expiry);
      if (!Number.isFinite(expiry) && expiry !== Infinity) return null;
      if (expiry !== Infinity && Date.now() > expiry) return null;
      return cached.value;
    } catch {
      return null;
    }
  }

  function publishCachedLookups() {
    for (const [key, endpoint] of cachedMetadata) {
      const payload = readCachedLookup(key);
      if (payload !== null) publishLookup(endpoint, payload);
    }
  }

  window.addEventListener("message", event => {
    if (event.source !== window || event.origin !== location.origin) return;
    const message = event.data;
    if (!message || message.channel !== channel || message.type !== "lookup-request") return;
    publishCachedLookups();
  });

  const originalFetch = window.fetch;
  window.fetch = async function (...args) {
    const response = await Reflect.apply(originalFetch, this, args);
    const rawUrl = response.url || String(args[0] || "");
    if (describeEndpoint(rawUrl)) {
      response.clone().json().then(payload => publish(rawUrl, payload)).catch(() => {});
    }
    return response;
  };

  const originalOpen = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function (method, url, ...rest) {
    this.__cardRelayUrl = String(url);
    this.addEventListener("load", () => {
      if (!describeEndpoint(this.responseURL || this.__cardRelayUrl)) return;
      try {
        const payload = this.responseType === "json" ? this.response : JSON.parse(this.responseText);
        publish(this.responseURL || this.__cardRelayUrl, payload);
      } catch {}
    }, { once: true });
    return Reflect.apply(originalOpen, this, [method, url, ...rest]);
  };

  publishCachedLookups();
})();
