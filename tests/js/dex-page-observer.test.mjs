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
    headers: { get: name => name === "content-type" ? "application/json" : null },
    clone: () => ({ text: async () => JSON.stringify(payload) })
  };
}

function runObserver(payload) {
  const listeners = new Map();
  const messages = [];
  const payloads = Array.isArray(payload) ? [...payload] : [payload];
  class FakeRequest {
    constructor(input, init = {}) {
      this.url = input instanceof FakeRequest ? input.url : String(input);
      this.method = init.method || (input instanceof FakeRequest ? input.method : "GET");
    }
  }
  const pageWindow = {
    fetch: async () => responseFor(payloads.shift() ?? payloads.at(-1)),
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
  const context = vm.createContext({
    JSON,
    Request: FakeRequest,
    URL,
    XMLHttpRequest: FakeXmlHttpRequest,
    location: { origin: "https://app.dextcg.com" },
    window: pageWindow
  });
  vm.runInContext(observerSource, context);
  return { listeners, messages, pageWindow };
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
