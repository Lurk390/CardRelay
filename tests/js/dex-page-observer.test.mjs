import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const observerSource = readFileSync(
  new URL("../../extension/dex-page-observer.js", import.meta.url),
  "utf8"
);

function responseFor(payload) {
  return {
    ok: true,
    status: 200,
    headers: { get: name => name === "content-type" ? "application/json" : null },
    clone: () => ({ text: async () => JSON.stringify(payload) })
  };
}

function runObserver(payload, options = {}) {
  const listeners = new Map();
  const messages = [];
  const fetchCalls = [];
  const payloads = Array.isArray(payload) ? [...payload] : [payload];
  class FakeRequest {
    constructor(input, init = {}) {
      if (input instanceof FakeRequest && !init.__cloning) {
        if (input.bodyUsed) throw new TypeError("Request body is already used");
        input.bodyUsed = true;
      }
      this.url = input instanceof FakeRequest ? input.url : String(input);
      this.method = init.method || (input instanceof FakeRequest ? input.method : "GET");
      this.body = init.body ?? (input instanceof FakeRequest ? input.body : "");
      this.bodyUsed = false;
      const headers = init.headers || (input instanceof FakeRequest ? input.rawHeaders : {});
      this.rawHeaders = headers;
      this.headers = {
        get: name => Object.entries(headers).find(
          ([key]) => key.toLowerCase() === name.toLowerCase()
        )?.[1] || null
      };
    }
    clone() {
      if (this.bodyUsed) throw new TypeError("Request body is already used");
      return new FakeRequest(this, {
        __cloning: true,
        body: this.body,
        headers: this.rawHeaders
      });
    }
    async text() {
      return String(this.body || "");
    }
  }
  const pageWindow = {
    fetch: async (input, init) => {
      fetchCalls.push({ input, init });
      if (input instanceof FakeRequest && input.bodyUsed) {
        throw new TypeError("Dex received a consumed Request body");
      }
      if (options.fetchImpl) return options.fetchImpl(input, init, fetchCalls.length);
      return responseFor(payloads.length > 1 ? payloads.shift() : payloads[0]);
    },
    addEventListener(type, listener) {
      listeners.set(type, listener);
    },
    postMessage(message) {
      messages.push(message);
    }
  };
  function FakeXmlHttpRequest() {}
  FakeXmlHttpRequest.prototype.open = function () {};
  FakeXmlHttpRequest.prototype.addEventListener = function () {};
  FakeXmlHttpRequest.prototype.send = function () {};
  const context = vm.createContext({
    AbortController,
    JSON,
    Request: FakeRequest,
    URL,
    XMLHttpRequest: FakeXmlHttpRequest,
    clearTimeout,
    location: { origin: "https://app.dextcg.com" },
    setTimeout,
    window: pageWindow
  });
  const source = observerSource
    .replace(
      "const paginationDelayMilliseconds = 200;",
      `const paginationDelayMilliseconds = ${options.paginationDelay ?? 200};`
    )
    .replace(
      "const catalogRequestTimeoutMilliseconds = 15000;",
      `const catalogRequestTimeoutMilliseconds = ${options.requestTimeout ?? 15000};`
    )
    .replace(
      "const catalogDiscoveryTimeoutMilliseconds = 10000;",
      `const catalogDiscoveryTimeoutMilliseconds = ${options.discoveryTimeout ?? 10000};`
    );
  vm.runInContext(source, context);
  return { FakeRequest, fetchCalls, listeners, messages, pageWindow };
}

function arm(observed, target) {
  observed.listeners.get("message")({
    source: observed.pageWindow,
    origin: "https://app.dextcg.com",
    data: { channel: "card-relay.dex.v1", type: "capture-control", target }
  });
}

const card = {
  cardId: "private-card-id",
  name: "Private Card",
  number: "001",
  setId: "private-relational-set-id",
  set: { id: "private-row-id", name: "Private Set", setId: "public-set-code" },
  variants: [{
    type: "default",
    imageUrl: "https://private.invalid/image",
    variant: { name: "Holo", secret: "must-not-cross-boundary" }
  }],
  markets: [{ url: "https://private.invalid/market" }]
};

test("Dex observer keeps sanitized current-page data dormant until manually armed", async () => {
  const observed = runObserver({ page: 1, pageSize: 20, result: [card], totalItems: 1, totalPages: 1 });

  await observed.pageWindow.fetch("https://private.invalid");
  await new Promise(resolve => setTimeout(resolve, 0));

  assert.deepEqual(observed.messages, []);

  arm(observed, "catalog");

  assert.equal(observed.messages.length, 1);
  assert.equal(observed.messages[0].target, "catalog");
});

test("Dex collection capture strips account and unrelated catalog metadata", async () => {
  const payload = {
    page: 1,
    pageSize: 20,
    result: [{
      id: "private-collection-record-id",
      cardId: "private-card-id",
      card,
      quantities: { holo: 2 },
      userId: "must-not-cross-boundary",
      createdAt: "private-timestamp"
    }],
    totalItems: 1,
    totalPages: 1
  };
  const observed = runObserver(payload);
  arm(observed, "collection");

  await observed.pageWindow.fetch("https://private.invalid");
  await new Promise(resolve => setTimeout(resolve, 0));

  assert.equal(observed.messages.length, 1);
  const serialized = JSON.stringify(observed.messages[0]);
  assert.ok(!serialized.includes("userId"));
  assert.ok(!serialized.includes("createdAt"));
  assert.ok(!serialized.includes("markets"));
  assert.ok(!serialized.includes("imageUrl"));
  assert.ok(!serialized.includes("secret"));
  assert.equal(observed.messages[0].payload.result[0].card.variants[0].name, "Holo");
  assert.deepEqual(
    JSON.parse(JSON.stringify(observed.messages[0].payload.result[0].quantities)),
    { holo: 2 }
  );
});

test("Dex observer rejects structurally ambiguous empty first pages", async () => {
  const observed = runObserver({ page: 1, pageSize: 20, result: [], totalItems: 0, totalPages: 1 });
  arm(observed, "collection");

  await observed.pageWindow.fetch("https://private.invalid");
  await new Promise(resolve => setTimeout(resolve, 0));

  assert.deepEqual(observed.messages, []);
});

test("Dex observer keeps separate card streams from overwriting the largest catalog", async () => {
  const small = { page: 1, pageSize: 20, result: [card], totalItems: 1, totalPages: 1 };
  const large = { page: 1, pageSize: 20, result: [{ ...card, cardId: "large-card" }], totalItems: 100, totalPages: 1 };
  const observed = runObserver([small, large]);

  await observed.pageWindow.fetch("https://clients.invalid/recent?page=1");
  await observed.pageWindow.fetch("https://clients.invalid/cards?page=1");
  await new Promise(resolve => setTimeout(resolve, 0));
  arm(observed, "catalog");

  assert.equal(observed.messages.length, 1);
  assert.equal(observed.messages[0].payload.totalItems, 100);
  assert.equal(observed.messages[0].payload.result[0].cardId, "large-card");
});

test("Dex catalog pagination reports and stops a stalled request", async () => {
  const firstPage = {
    page: 1,
    pageSize: 20,
    result: [card],
    totalItems: 40,
    totalPages: 2
  };
  const observed = runObserver(firstPage, {
    paginationDelay: 0,
    requestTimeout: 10,
    discoveryTimeout: 100,
    fetchImpl: (_input, _init, callCount) => callCount === 1
      ? responseFor(firstPage)
      : new Promise(() => {})
  });
  arm(observed, "catalog");

  await observed.pageWindow.fetch("https://clients.invalid/cards?page=1");
  await new Promise(resolve => setTimeout(resolve, 40));

  const error = observed.messages.find(message => message.type === "capture-error");
  assert.equal(error?.target, "catalog");
  assert.equal(error?.reason, "catalog_request_timeout");
});

test("Dex catalog capture reports when Search never loads a catalog request", async () => {
  const observed = runObserver({}, { discoveryTimeout: 10 });
  arm(observed, "catalog");

  await new Promise(resolve => setTimeout(resolve, 30));

  assert.deepEqual(
    JSON.parse(JSON.stringify(observed.messages)),
    [{
      channel: "card-relay.dex.v1",
      type: "capture-error",
      target: "catalog",
      reason: "catalog_request_not_observed"
    }]
  );
});
test("Dex write research emits schema only after explicit arming", async () => {
  const observed = runObserver({
    updated: true,
    cardId: "response-private-card-id"
  });
  const request = {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      cardId: "2f709ce8-f1c4-4ac7-a614-79d640f5dd8a",
      quantities: { reverse_holo: 7 },
      note: "private collection note"
    })
  };

  await observed.pageWindow.fetch(
    "https://api.dextcg.com/api/collections/private-user-id/cards/2f709ce8-f1c4-4ac7-a614-79d640f5dd8a?account=private-account",
    request
  );
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.deepEqual(observed.messages, []);

  arm(observed, "write-research");
  await observed.pageWindow.fetch(
    "https://api.dextcg.com/api/collections/private-user-id/cards/2f709ce8-f1c4-4ac7-a614-79d640f5dd8a?account=private-account",
    request
  );
  await new Promise(resolve => setTimeout(resolve, 0));

  assert.equal(observed.messages.length, 1);
  const observation = observed.messages[0].payload;
  assert.equal(observation.method, "PATCH");
  assert.equal(observation.origin_host, "api.dextcg.com");
  assert.equal(observation.route_template, "/api/collections/{segment}/cards/{segment}");
  assert.deepEqual(
    JSON.parse(JSON.stringify(observation.path_parameter_bindings)),
    [{ segment_index: 4, source: "request.cardId" }]
  );
  assert.deepEqual(
    JSON.parse(JSON.stringify(observation.query_keys)),
    ["account"]
  );
  assert.equal(observation.request_shape.fields.cardId.kind, "string");
  assert.equal(observation.request_shape.fields.quantities.fields.reverse_holo.kind, "integer");
  assert.equal(observation.response_shape.fields.updated.kind, "boolean");
  const serialized = JSON.stringify(observed.messages[0]);
  for (const privateValue of [
    "private-user-id",
    "2f709ce8-f1c4-4ac7-a614-79d640f5dd8a",
    "private-account",
    "private collection note",
    "response-private-card-id"
  ]) {
    assert.ok(!serialized.includes(privateValue));
  }

  await observed.pageWindow.fetch(
    "https://rum.dextcg.com/v1/events",
    { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }
  );
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(observed.messages.length, 1);
});

test("Dex write research records bodyless deletes without exposing route identifiers", async () => {
  const observed = runObserver({ deleted: true });
  arm(observed, "write-research");

  await observed.pageWindow.fetch(
    "https://api.dextcg.com/api/collections/private-user-id/cards/private-card-id",
    { method: "DELETE" }
  );
  await new Promise(resolve => setTimeout(resolve, 0));

  assert.equal(observed.messages.length, 1);
  const observation = observed.messages[0].payload;
  assert.equal(observation.method, "DELETE");
  assert.equal(observation.route_template, "/api/collections/{segment}/cards/{segment}");
  assert.equal(observation.request_shape.kind, "null");
  const serialized = JSON.stringify(observation);
  assert.ok(!serialized.includes("private-user-id"));
  assert.ok(!serialized.includes("private-card-id"));
});

test("Dex write research never consumes Dex's original Request body", async () => {
  const observed = runObserver({ updated: true });
  arm(observed, "write-research");
  const request = new observed.FakeRequest(
    "https://api.dextcg.com/api/collections/private/cards/private",
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ quantities: { normal: 2 } })
    }
  );

  await observed.pageWindow.fetch(request);
  await new Promise(resolve => setTimeout(resolve, 0));

  assert.equal(observed.messages.length, 1);
  assert.equal(observed.messages[0].payload.method, "PATCH");
});


test("Dex executor applies a controlled removal as a full quantity-map PATCH", async () => {
  const observed = runObserver({ updated: true });
  observed.listeners.get("message")({
    source: observed.pageWindow,
    origin: "https://app.dextcg.com",
    data: {
      channel: "card-relay.dex.v1",
      type: "safe-write-execute",
      requestId: "controlled-removal-1",
      batch: {
        contract_version: "dex-removal-batch-v1",
        commands: [{
          operation_id: "remove-managed-holo",
          method: "PATCH",
          origin: "https://clients.dextcg.com",
          path: "/api/user/cards/managed-record-1",
          body: {
            cardId: "managed-card-1",
            quantities: { holo: 0, reverseHolo: 3 }
          }
        }]
      }
    }
  });
  await new Promise(resolve => setTimeout(resolve, 0));

  const result = observed.messages.find(message => message.type === "safe-write-result");
  assert.ok(result);
  assert.equal(result.requestId, "controlled-removal-1");
  assert.equal(result.results[0].succeeded, true);
  const call = observed.fetchCalls.at(-1);
  assert.equal(call.input, "https://clients.dextcg.com/api/user/cards/managed-record-1");
  assert.equal(call.init.method, "PATCH");
  assert.deepEqual(JSON.parse(call.init.body), {
    cardId: "managed-card-1",
    quantities: { holo: 0, reverseHolo: 3 }
  });
});

test("Dex executor accepts more than fifty safe writes", async () => {
  const observed = runObserver({ created: true });
  const commands = Array.from({ length: 51 }, (_unused, index) => ({
    operation_id: `large-addition-${String(index).padStart(3, "0")}`,
    method: "POST",
    origin: "https://clients.dextcg.com",
    path: "/api/user/cards",
    body: {
      cardId: `card-${index}`,
      quantities: { normal: 1 }
    }
  }));

  observed.listeners.get("message")({
    source: observed.pageWindow,
    origin: "https://app.dextcg.com",
    data: {
      channel: "card-relay.dex.v1",
      type: "safe-write-execute",
      requestId: "large-addition-batch",
      batch: {
        contract_version: "dex-safe-write-batch-v1",
        commands
      }
    }
  });

  let result;
  for (let attempt = 0; attempt < 20 && !result; attempt += 1) {
    await new Promise(resolve => setTimeout(resolve, 0));
    result = observed.messages.find(message => message.type === "safe-write-result");
  }

  assert.ok(result);
  assert.equal(result.requestId, "large-addition-batch");
  assert.equal(result.results.length, 51);
  assert.ok(result.results.every(item => item.succeeded));
  assert.equal(observed.fetchCalls.length, 51);
});
