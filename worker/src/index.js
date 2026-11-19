// Cloudflare Worker: the always-on "doorbell" for the volleyball bot.
//
// - Cron Trigger (every 10 min, 7:00–23:50 JST): asks GitHub to run the scan workflow.
// - Telegram webhook (POST /telegram): `/list` in the group asks GitHub for a list run.
//
// It never reads the portal and keeps no slot data: the bot on GitHub Actions does the work.
// Secrets (wrangler secret put): TELEGRAM_BOT_TOKEN, GITHUB_TOKEN, WEBHOOK_SECRET, ALLOWED_CHAT_ID.
// Vars (wrangler.toml): GITHUB_REPO, BOT_USERNAME. KV binding: STATE.

const COOLDOWN_MS = 3 * 60 * 1000;

export const TEXT = {
  ack: "⏳ Checking the portal, the full list arrives in about a minute.",
  cooldown: "⏳ A list is already on its way.",
  dispatchError: (status) => `⚠️ Could not start the check (GitHub error ${status}).`,
  startError: "⚠️ Could not start the check, please try again in a minute.",
  help: "🏐 Volleyball bot\n\n/list – full list of free courts right now (arrives in about a minute)\n/help – this message\n\nNew slots are also posted here automatically.",
};

export function parseCommand(text, botUsername) {
  if (typeof text !== "string") return null;
  const first = text.trim().split(/\s+/)[0] || "";
  const m = /^\/([a-z]+)(?:@(\w+))?$/i.exec(first);
  if (!m) return null;
  if (m[2] && m[2].toLowerCase() !== String(botUsername || "").toLowerCase()) return null;
  const cmd = m[1].toLowerCase();
  if (cmd === "list") return "list";
  if (cmd === "help" || cmd === "start") return "help";
  return null;
}

export async function dispatch(env, mode, fetchImpl = fetch) {
  const url = `https://api.github.com/repos/${env.GITHUB_REPO}/actions/workflows/scan.yml/dispatches`;
  const res = await fetchImpl(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "volleyball-bot-worker",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ ref: "main", inputs: { mode } }),
  });
  return res.status;
}

export async function sendTelegram(env, chatId, text, fetchImpl = fetch) {
  const res = await fetchImpl(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chat_id: String(chatId), text, disable_web_page_preview: true }),
  });
  if (res.status !== 200) console.error(`Telegram sendMessage failed with HTTP ${res.status}`);
}

export async function handleUpdate(update, env, { fetchImpl = fetch, now = Date.now() } = {}) {
  const message = update && update.message;
  if (!message || !message.chat) return;
  const chatId = String(message.chat.id);
  if (chatId !== String(env.ALLOWED_CHAT_ID)) {
    if (message.migrate_to_chat_id) console.log(`chat ${chatId} migrated to ${message.migrate_to_chat_id}`);
    return;
  }
  if (message.migrate_to_chat_id) {
    console.log(`Group migrated to supergroup ${message.migrate_to_chat_id}: update ALLOWED_CHAT_ID and TELEGRAM_CHAT_ID`);
    return;
  }

  const command = parseCommand(message.text, env.BOT_USERNAME);
  if (command === "help") return sendTelegram(env, chatId, TEXT.help, fetchImpl);
  if (command !== "list") return;

  let status;
  try {
    const last = await env.STATE.get("last_list_at");
    if (last !== null && now - Number(last) < COOLDOWN_MS) return sendTelegram(env, chatId, TEXT.cooldown, fetchImpl);
    status = await dispatch(env, "list", fetchImpl);
  } catch (err) {
    // never leave a /list without an answer
    console.error(`starting the list run failed: ${err && err.name}: ${err && err.message}`);
    return sendTelegram(env, chatId, TEXT.startError, fetchImpl);
  }
  if (status !== 204) {
    console.error(`workflow_dispatch(list) failed with HTTP ${status}`);
    return sendTelegram(env, chatId, TEXT.dispatchError(status), fetchImpl);
  }
  await env.STATE.put("last_list_at", String(now));
  return sendTelegram(env, chatId, TEXT.ack, fetchImpl);
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/") return new Response("ok");
    if (request.method !== "POST" || url.pathname !== "/telegram") return new Response("not found", { status: 404 });

    if (!env.WEBHOOK_SECRET || request.headers.get("X-Telegram-Bot-Api-Secret-Token") !== env.WEBHOOK_SECRET) {
      return new Response("forbidden", { status: 403 });
    }
    try {
      await handleUpdate(await request.json(), env, { fetchImpl: globalThis.fetch, now: Date.now() });
    } catch (err) {
      console.error(`update failed: ${err && err.name}: ${err && err.message}`);
    }
    return new Response("ok"); // always 200, otherwise Telegram retries the same update
  },

  async scheduled(event, env, ctx) {
    ctx.waitUntil(
      dispatch(env, "scan", globalThis.fetch).then((status) => {
        if (status !== 204) console.error(`workflow_dispatch(scan) failed with HTTP ${status}`);
      }),
    );
  },
};
