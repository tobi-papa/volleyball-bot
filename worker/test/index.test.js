import { test } from "node:test";
import assert from "node:assert/strict";
import worker, { parseCommand, handleUpdate, dispatch } from "../src/index.js";

const GITHUB_URL = "https://api.github.com/repos/tobi-papa/volleyball-bot/actions/workflows/scan.yml/dispatches";
const TG_URL = "https://api.telegram.org/bottgtok/sendMessage";

function makeEnv() {
  const kv = new Map();
  return {
    ALLOWED_CHAT_ID: "-100123",
    BOT_USERNAME: "volley_bot",
    GITHUB_REPO: "tobi-papa/volleyball-bot",
    GITHUB_TOKEN: "ghtok",
    TELEGRAM_BOT_TOKEN: "tgtok",
    WEBHOOK_SECRET: "s3cret",
    STATE: {
      get: async (k) => (kv.has(k) ? kv.get(k) : null),
      put: async (k, v) => { kv.set(k, v); },
      _map: kv,
    },
  };
}

function fakeFetch(githubStatus = 204) {
  const calls = [];
  const impl = async (url, init = {}) => {
    calls.push({ url, init, body: init.body ? JSON.parse(init.body) : undefined });
    if (url.startsWith("https://api.github.com/")) return new Response(null, { status: githubStatus });
    return new Response(JSON.stringify({ ok: true }), { status: 200 });
  };
  impl.calls = calls;
  return impl;
}

const msg = (text, chatId = -100123) => ({ update_id: 1, message: { message_id: 5, chat: { id: chatId }, text } });

function webhook(body, secret = "s3cret") {
  const headers = { "content-type": "application/json" };
  if (secret !== null) headers["X-Telegram-Bot-Api-Secret-Token"] = secret;
  return new Request("https://w.example/telegram", { method: "POST", headers, body: JSON.stringify(body) });
}

test("parseCommand", () => {
  assert.equal(parseCommand("/list", "volley_bot"), "list");
  assert.equal(parseCommand("/list@volley_bot", "volley_bot"), "list");
  assert.equal(parseCommand("/LIST please", "volley_bot"), "list");
  assert.equal(parseCommand("/list@OtherBot", "volley_bot"), null);
  assert.equal(parseCommand("hello", "volley_bot"), null);
  assert.equal(parseCommand(undefined, "volley_bot"), null);
  assert.equal(parseCommand("/start", "volley_bot"), "help");
  assert.equal(parseCommand("/help@volley_bot", "volley_bot"), "help");
});

test("webhook without or with wrong secret is rejected", async () => {
  for (const secret of [null, "nope"]) {
    const f = fakeFetch();
    globalThis.fetch = f;
    const res = await worker.fetch(webhook(msg("/list"), secret), makeEnv(), {});
    assert.equal(res.status, 403);
    assert.equal(f.calls.length, 0);
  }
});

test("/list from another chat is ignored", async () => {
  const f = fakeFetch();
  globalThis.fetch = f;
  const res = await worker.fetch(webhook(msg("/list", -100999)), makeEnv(), {});
  assert.equal(res.status, 200);
  assert.equal(f.calls.length, 0);
});

test("edited messages are ignored", async () => {
  const f = fakeFetch();
  await handleUpdate({ update_id: 2, edited_message: msg("/list").message }, makeEnv(), { fetchImpl: f, now: 1000 });
  assert.equal(f.calls.length, 0);
});

test("valid /list dispatches a list run and acknowledges", async () => {
  const env = makeEnv();
  const f = fakeFetch();
  await handleUpdate(msg("/list"), env, { fetchImpl: f, now: 1_000_000 });
  assert.equal(f.calls.length, 2);
  const [gh, tg] = f.calls;
  assert.equal(gh.url, GITHUB_URL);
  assert.equal(gh.init.method, "POST");
  assert.deepEqual(gh.body, { ref: "main", inputs: { mode: "list" } });
  assert.equal(gh.init.headers.Authorization, "Bearer ghtok");
  assert.equal(tg.url, TG_URL);
  assert.equal(tg.body.chat_id, "-100123");
  assert.equal(tg.body.text, "⏳ Checking the portal, the full list arrives in about a minute.");
  assert.equal(env.STATE._map.get("last_list_at"), "1000000");
});

test("/list cooldown of 3 minutes", async () => {
  const env = makeEnv();
  await handleUpdate(msg("/list"), env, { fetchImpl: fakeFetch(), now: 0 });
  const f = fakeFetch();
  await handleUpdate(msg("/list"), env, { fetchImpl: f, now: 60_000 });
  assert.equal(f.calls.length, 1);
  assert.equal(f.calls[0].url, TG_URL);
  assert.equal(f.calls[0].body.text, "⏳ A list is already on its way.");
  const g = fakeFetch();
  await handleUpdate(msg("/list"), env, { fetchImpl: g, now: 181_000 });
  assert.equal(g.calls[0].url, GITHUB_URL);
});

test("GitHub error is reported and does not start the cooldown", async () => {
  const env = makeEnv();
  const f = fakeFetch(401);
  globalThis.fetch = f;
  const res = await worker.fetch(webhook(msg("/list")), env, {});
  assert.equal(res.status, 200);
  assert.equal(f.calls[1].body.text, "⚠️ Could not start the check (GitHub error 401).");
  assert.equal(env.STATE._map.has("last_list_at"), false);
});

test("/help replies with the commands", async () => {
  const f = fakeFetch();
  await handleUpdate(msg("/help"), makeEnv(), { fetchImpl: f, now: 0 });
  assert.equal(f.calls.length, 1);
  assert.match(f.calls[0].body.text, /\/list/);
});

test("scheduled dispatches a scan run", async () => {
  const f = fakeFetch();
  globalThis.fetch = f;
  const pending = [];
  await worker.scheduled({}, makeEnv(), { waitUntil: (p) => pending.push(p) });
  await Promise.all(pending);
  assert.equal(f.calls.length, 1);
  assert.deepEqual(f.calls[0].body, { ref: "main", inputs: { mode: "scan" } });
});

test("dispatch returns the HTTP status", async () => {
  assert.equal(await dispatch(makeEnv(), "scan", fakeFetch(204)), 204);
  assert.equal(await dispatch(makeEnv(), "scan", fakeFetch(422)), 422);
});

test("health check and unknown paths", async () => {
  const ok = await worker.fetch(new Request("https://w.example/"), makeEnv(), {});
  assert.equal(ok.status, 200);
  assert.equal(await ok.text(), "ok");
  const nf = await worker.fetch(new Request("https://w.example/other"), makeEnv(), {});
  assert.equal(nf.status, 404);
});
