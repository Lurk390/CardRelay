import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const observerSource = readFileSync(
  new URL("../../extension/page-observer.js", import.meta.url),
  "utf8"
);

function runObserver(cache) {
  const accessedKeys = [];
  const listeners = new Map();
  const messages = [];
  const pageWindow = {
    fetch: async () => ({ clone: () => ({ json: async () => ({}) }) }),
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
    URL,
    XMLHttpRequest: FakeXmlHttpRequest,
    localStorage: {
      getItem(key) {
        accessedKeys.push(key);
        return cache.get(key) ?? null;
      }
    },
    location: {
      href: "https://app.getcollectr.com/portfolio/products",
      origin: "https://app.getcollectr.com"
    },
    window: pageWindow
  });
  vm.runInContext(observerSource, context);
  return { accessedKeys, listeners, messages, pageWindow };
}

test("publishes only verified, unexpired Collectr metadata cache entries", () => {
  const cache = new Map([
    [
      "cardConditions",
      JSON.stringify({ value: [{ id: 1, display_name: "Near Mint" }], expiry: "Infinity" })
    ],
    [
      "gradedCardScales",
      JSON.stringify({ value: [{ id: 10, grade: "10.0" }], expiry: 1 })
    ],
    ["accessToken", JSON.stringify({ value: "must-not-be-read", expiry: "Infinity" })]
  ]);

  const observed = runObserver(cache);

  assert.deepEqual(observed.accessedKeys, ["cardConditions", "gradedCardScales"]);
  assert.equal(observed.messages.length, 1);
  assert.equal(observed.messages[0].endpoint, "conditions");
  assert.deepEqual(
    JSON.parse(JSON.stringify(observed.messages[0].payload)),
    [{ id: 1, display_name: "Near Mint" }]
  );
});

test("refreshes verified cache entries when the content script requests lookups", () => {
  const cache = new Map();
  const observed = runObserver(cache);
  cache.set(
    "gradedCardScales",
    JSON.stringify({ value: [{ company: "CGC", grades: [{ id: 10, grade: "10.0" }] }], expiry: "Infinity" })
  );

  observed.listeners.get("message")({
    source: observed.pageWindow,
    origin: "https://app.getcollectr.com",
    data: { channel: "card-relay.collectr.v1", type: "lookup-request" }
  });

  assert.equal(observed.messages.at(-1).endpoint, "grading");
});

test("rejects oversized or malformed cached metadata", () => {
  const cache = new Map([
    ["cardConditions", "x".repeat(512 * 1024 + 1)],
    ["gradedCardScales", "not-json"]
  ]);

  const observed = runObserver(cache);

  assert.deepEqual(observed.messages, []);
});
