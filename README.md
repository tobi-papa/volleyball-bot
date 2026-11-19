# volleyball-bot

Every 10 minutes (7:00–23:50 Japan time) this bot checks free courts on the
[Yokohama facility booking portal](https://www.shisetsu.city.yokohama.lg.jp/user/Home)
and sends a Telegram message **only when a new slot appears**. Write `/list`
in the chat to get the full availability at any time.

- Runs on GitHub Actions: your computer can stay off.
- No login on the portal and no browser: it reads availability like a visitor,
  with plain HTTP requests (one run takes about 20 seconds).
- What to watch (gyms, times, weekdays) is set in `config.yaml`.

Based on [jeremynata/volleyball-bot](https://github.com/jeremynata/volleyball-bot).
How the portal works and the design decisions are in [docs/design.md](docs/design.md) (Italian).

## Setup

1. **Create the Telegram bot.** In Telegram, message @BotFather, send `/newbot`
   and follow the steps. At the end you get a **token** (like `123456:ABC...`).
2. **Find your chat_id.** Send any message to your new bot, then open
   `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser (with your
   token instead of `<TOKEN>`). The number in `"chat":{"id": ...}` is your
   **chat_id**.
3. **Add the secrets on GitHub.** In the repo: Settings → Secrets and variables
   → Actions → New repository secret. Create:
   - `TELEGRAM_BOT_TOKEN` = the token
   - `TELEGRAM_CHAT_ID` = the chat_id
4. **Turn it on.** Actions tab → enable workflows if asked → "Scan volley"
   → Run workflow. The first run sends one message with the slots that are
   free right now; after that, only new ones.

## Telegram commands

Write these in the chat the bot posts to (`TELEGRAM_CHAT_ID`); messages from
any other chat are ignored.

- `/list` – the full list of free courts right now, grouped by day. The bot
  answers `⏳ Checking the portal…` at once and the list arrives in about a
  minute. Slots that were not in the previous `/list` are marked 🆕, and
  "Taken since the last /list" shows what has been booked since. One `/list`
  every 3 minutes at most.
- `/help` – the list of commands.

If you add other bots to the group, write `/list@<this_bot>`: with Telegram's
privacy mode a bot only receives a bare `/list` when it was the last bot to
post in the group (or turn privacy off for this bot in @BotFather →
`/setprivacy`).

## Cloudflare Worker (launcher)

GitHub runs scheduled workflows on free repos far less often than asked (in
practice about every 8 hours), and it cannot receive Telegram commands. A
small [Cloudflare Worker](worker/) fixes both, for free:

- every 10 minutes (7:00–23:50 JST) it starts "Scan volley" through the
  GitHub API;
- it receives Telegram updates (webhook) and starts a `list` run on `/list`.

It never reads the portal; the bot itself still runs on GitHub Actions. The
GitHub `schedule` stays in `scan.yml` as a fallback.

### Setup (once)

1. Create a free account at [cloudflare.com](https://dash.cloudflare.com/sign-up),
   then in a terminal: `cd worker && npx wrangler@4 login`.
2. **GitHub token**: GitHub → Settings → Developer settings → Personal access
   tokens → Fine-grained tokens → Generate new token. Repository access: *Only
   select repositories* → this repo. Permissions → Repository → **Actions:
   Read and write** (nothing else). Expiration: 1 year. Copy the token.
3. Create the KV store and put its id in `worker/wrangler.toml`
   (`[[kv_namespaces]] id`): `npx wrangler@4 kv namespace create STATE`.
4. Add the secrets (each command asks for the value; paste it there, never in
   a file or chat):

   ```bash
   npx wrangler@4 secret put GITHUB_TOKEN
   npx wrangler@4 secret put TELEGRAM_BOT_TOKEN
   npx wrangler@4 secret put ALLOWED_CHAT_ID    # same value as the GitHub secret TELEGRAM_CHAT_ID
   ```

5. Deploy: `npx wrangler@4 deploy`. It prints the Worker URL
   (`https://volleyball-bot-worker.<you>.workers.dev`); opening it shows `ok`.
6. Connect Telegram: `./setup-webhook.sh https://volleyball-bot-worker.<you>.workers.dev`.
   It asks for the bot token, prints the bot's username (put it in
   `wrangler.toml` as `BOT_USERNAME` and deploy again), creates the
   `WEBHOOK_SECRET` and registers the webhook.

### Good to know

- Once the webhook is set, `https://api.telegram.org/bot<TOKEN>/getUpdates`
  no longer works. To find a chat id again, look at the Worker log
  (`npx wrangler@4 tail`) while writing in the chat.
- If Telegram upgrades the group to a supergroup, its id changes (a new
  `-100…` number, also shown in the Worker log). Update both the GitHub secret
  `TELEGRAM_CHAT_ID` and the Worker secret `ALLOWED_CHAT_ID`.
- The GitHub token expires after a year: `/list` then answers
  `⚠️ Could not start the check (GitHub error 401).` Create a new token and run
  `npx wrangler@4 secret put GITHUB_TOKEN` again.

## Changing what it watches

Edit `config.yaml` (you can do it right on the GitHub website) and commit.
Example: only Saturday and Sunday from 13:00, full court.

```yaml
gyms:
  - 港北スポーツセンター
rules:
  - weekdays: [Sat, Sun]
    time_from: "13:00"
    rooms: [第一体育室（全面）]
```

With several rules, a slot is reported if it matches at least one of them.

## Running it by hand

- **On GitHub:** Actions → Scan volley → Run workflow.
- **Locally, without sending anything:**

  ```bash
  python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
  .venv/bin/python -m bot --dry-run
  ```

- **Tests:** `.venv/bin/python -m pytest`

## When something goes wrong

- If the portal fails on two runs in a row you get `⚠️ Volleyball bot failed`
  (at most once every 6 hours) with a link to the run; when it works again you
  get `✅ Volleyball bot is working again.`. A single isolated error sends
  nothing. Those runs keep the last portal response in the `debug` artifact.
- These portal errors keep the run green (otherwise GitHub would email you
  every 10 minutes). A run turns red, and GitHub emails you, only when it
  cannot send to Telegram or when `config.yaml` has an error.
- While the portal is in maintenance, the bot silently skips the run.
- Once a month the "Keepalive" workflow pushes an empty commit: GitHub turns
  off scheduled workflows after 60 days without repository activity. If it
  happens anyway, re-enable it from Actions → Scan volley.
- **Starting over** (for example after a big config change): Actions →
  Caches → delete the `bot-state-*` entries. The next run sends the full list
  of free slots again.
