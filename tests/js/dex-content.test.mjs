import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const contentSource = readFileSync(
  new URL("../../extension/dex-content.js", import.meta.url),
  "utf8"
);

function runContent() {
  const pageMessages = [];
  let pageListener = null;
  let runtimeListener = null;
  let stored = {};
  const pageWindow = {
    addEventListener(type, listener) {
      if (type === "message") pageListener = listener;
    },
    postMessage(message) {
      pageMessages.push(message);
    }
  };
  const chrome = {
    runtime: {
      onMessage: {
        addListener(listener) {
          runtimeListener = listener;
        }
      },
      sendMessage: async () => ({ ok: true })
    },
    storage: {
      session: {
        async get(key) {
          return { [key]: stored[key] };
        },
        async set(value) {
          stored = { ...stored, ...value };
        }
      }
    }
  };
  const context = vm.createContext({
    JSON,
    Map,
    chrome,
    crypto,
    location: { origin: "https://app.dextcg.com", pathname: "/search" },
    setTimeout,
    window: pageWindow
  });
  vm.runInContext(contentSource, context);
  return {
    pageMessages,
    pageWindow,
    postFromPage(message) {
      pageListener({
        source: pageWindow,
        origin: "https://app.dextcg.com",
        data: message
      });
    },
    sendRuntime(message) {
      return new Promise(resolve => runtimeListener(message, {}, resolve));
    }
  };
}

const channel = "card-relay.dex.v1";

test("Dex content capture clears the active catalog target when all pages arrive", async () => {
  const observed = runContent();
  await observed.sendRuntime({ type: "card-relay-dex-start", target: "catalog" });
  observed.postFromPage({
    channel,
    type: "response",
    target: "catalog",
    payload: { page: 1, totalPages: 1, totalItems: 1, result: [] }
  });

  const response = await observed.sendRuntime({ type: "card-relay-dex-status" });

  assert.equal(response.status.catalogComplete, true);
  assert.equal(response.status.activeTarget, null);
  assert.ok(observed.pageMessages.some(message =>
    message.type === "capture-control" && message.target === null
  ));
});

test("Dex content capture exposes a retryable catalog failure and clears active state", async () => {
  const observed = runContent();
  await observed.sendRuntime({ type: "card-relay-dex-start", target: "catalog" });
  observed.postFromPage({
    channel,
    type: "capture-error",
    target: "catalog",
    reason: "catalog_request_timeout"
  });

  const response = await observed.sendRuntime({ type: "card-relay-dex-status" });

  assert.equal(response.status.catalogError, "catalog_request_timeout");
  assert.equal(response.status.activeTarget, null);
});