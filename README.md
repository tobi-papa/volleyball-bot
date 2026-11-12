# volleyball-bot

Every 10 minutes (7:00–23:50 Japan time) this bot checks free courts on the
[Yokohama facility booking portal](https://www.shisetsu.city.yokohama.lg.jp/user/Home)
and sends a Telegram message **only when a new slot appears**.

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
