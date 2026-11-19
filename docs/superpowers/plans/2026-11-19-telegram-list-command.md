# /list command and Cloudflare launcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Telegram `/list` command that posts the full current availability to the group within ~1–2 minutes, and make the bot really run every 10 minutes, via a Cloudflare Worker that triggers the existing GitHub workflow.

**Architecture:** A Cloudflare Worker (plain JS, no deps) receives Telegram webhooks and has a Cron Trigger; both call GitHub's `workflow_dispatch` on `scan.yml` with `mode=scan|list`. The Python bot gains `--mode list`, which reads the portal and always posts a full list (🆕 / "Taken since the last /list" against a separate `list_state.json`).

**Tech Stack:** Python 3.9-compatible (`from __future__ import annotations`), pytest; Cloudflare Workers (ES modules) + Workers KV, `node --test` (Node 24, already installed), `wrangler` via `npx`.

**Spec:** `docs/superpowers/specs/2026-11-19-telegram-list-command-design.md` (base design: `docs/design.md`).

## Global Constraints

- Repo is public: no token, chat id or webhook secret in code, `wrangler.toml`, logs or error texts.
- Worker secrets: `TELEGRAM_BOT_TOKEN`, `GITHUB_TOKEN`, `WEBHOOK_SECRET`, `ALLOWED_CHAT_ID`. Worker vars in `wrangler.toml`: `GITHUB_REPO = "tobi-papa/volleyball-bot"`, `BOT_USERNAME`.
- Worker cron: `*/10 22-23,0-14 * * *` (UTC = 7:00–23:50 JST).
- Dispatch: `POST https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/scan.yml/dispatches`, body `{"ref":"main","inputs":{"mode":"scan"|"list"}}`, headers `Authorization: Bearer <GITHUB_TOKEN>`, `Accept: application/vnd.github+json`, `X-GitHub-Api-Version: 2022-11-28`, `User-Agent: volleyball-bot-worker`; success = HTTP 204.
- `/list` cooldown: 3 minutes, KV key `last_list_at` (epoch ms) in KV binding `STATE`.
- Message texts (English, exact):
  - Worker ack: `⏳ Checking the portal, the full list arrives in about a minute.`
  - Worker cooldown: `⏳ A list is already on its way.`
  - Worker dispatch error: `⚠️ Could not start the check (GitHub error <status>).`
  - Bot list header: `📋 Free now at <gyms> (<n>) · checked <H:MM> JST`
  - Bot list error: `⚠️ Could not read the portal: <error>`
  - Bot maintenance: `🔧 The portal is in maintenance, try again later.`
  - Taken section title: `Taken since the last /list (<n>):`
- 🆕 and "Taken" compare against the previous `/list` only (`list_state.json`); on the first `/list` neither appears.
- `--mode scan` behaviour must stay exactly as today (all existing tests unchanged and green).
- GitHub `schedule` trigger stays as a fallback.

## Review Focus

1. **Forged or foreign webhook**: request without/with wrong `X-Telegram-Bot-Api-Secret-Token`, or `/list` from a chat ≠ `ALLOWED_CHAT_ID` → no dispatch, no reply (403 resp. 200). Tests in Task 3.
2. **Command addressed to another bot** in the group (`/list@OtherBot`) and edited messages → ignored. Tests in Task 3.
3. **`/list` spam** (two within 3 minutes) → one dispatch, second gets the cooldown reply. Test in Task 3.
4. **Expired GitHub token** (dispatch returns 401) → group gets `⚠️ Could not start the check (GitHub error 401).`, webhook still answers 200, cooldown not set. Test in Task 3.
5. **Portal down during `/list`** → immediate `⚠️ Could not read the portal: …`, scan state and list state unchanged, run exit 0. Test in Task 2.

---

### Task 1: List message and list state

**Files:**
- Modify: `bot/messages.py`, `bot/state.py`
- Test: `tests/test_messages.py`, `tests/test_state.py`

**Interfaces:**
- Produces:
  - `list_message(slots: Sequence[Slot], new_keys: Collection[tuple], taken: Sequence[Slot], checked_at: datetime, gyms: Sequence[str]) -> str` (`gyms` = configured Japanese names, shown in English in the header) in `bot/messages.py`.
  - `list_error_message(err: str) -> str`, `maintenance_message() -> str` in `bot/messages.py`.
  - `load_listed(path) -> Optional[List[Slot]]`, `save_listed(slots: Sequence[Slot], path) -> None` in `bot/state.py` (file `{"slots": [...]}`; missing/corrupt → `None`).

- [ ] **Step 1: Write failing tests**
  - `test_list_message_groups_by_day`: slots A (Mon 30 Nov 7:30–9:00 Gym 1 A), B (Mon 30 Nov 13:00–15:00 Gym 1 B), C (Tue 1 Dec 7:30–9:00 Gym 1 full), `new_keys={C.key}`, `taken=[]`, `checked_at=datetime(2026,11,19,5,5,tzinfo=utc)` → first line `"📋 Free now at Kohoku (3) · checked 14:05 JST"`; contains a line `"Mon 30 Nov 2026"` followed by `"  7:30–9:00 · Gym 1 A (half)"` and `"  13:00–15:00 · Gym 1 B (half)"`; contains `"  🆕 7:30–9:00 · Gym 1 (full)"` under `"Tue 1 Dec 2026"`; no `"Taken since"`; last line contains `PORTAL_URL`.
  - `test_list_message_taken_section`: `taken=[B]` → contains `"Taken since the last /list (1):"` and `"  Mon 30 Nov 2026 · 13:00–15:00 · Kohoku · Gym 1 B (half)"`.
  - `test_list_message_empty`: no slots → contains `"No free slots right now."` and header count `(0)`.
  - `test_list_message_multi_gym_shows_gym`: two gyms → each slot line includes the English gym name.
  - `test_list_error_and_maintenance`: exact texts from Global Constraints.
  - `test_listed_roundtrip` / `test_listed_missing_or_corrupt` in `tests/test_state.py`.
- [ ] **Step 2:** `.venv/bin/python -m pytest tests/test_messages.py tests/test_state.py -q` → FAIL (ImportError).
- [ ] **Step 3: Implement.** Header gym names = `", ".join(gym_en(g) for g in gyms)`. Hour in JST from `checked_at`. Slot lines omit the gym when `len(gyms) == 1`. Long lists are split later by `send()`. Tests pass `gyms=("港北スポーツセンター",)` (two gyms in the multi-gym test).
- [ ] **Step 4:** run → PASS; full suite green.
- [ ] **Step 5: Commit** `feat: full availability list message and list state`.

### Task 2: `--mode list` in the bot

**Files:**
- Modify: `bot/main.py`
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: Task 1 functions; existing `fetch_slots`, `apply_rules`, `load_state`/`save_state`, `diff`.
- Produces: `run_list(config: Config, state_path: Path, listed_path: Path, *, fetch=fetch_slots, notify, now: datetime) -> int`; CLI `--mode {scan,list}` (default `scan`) and `--list-state` (default `list_state.json`).

Behaviour of `run_list`:
1. `prev = load_listed(listed_path)`; fetch + rules.
2. `SiteClosed` → `notify(maintenance_message())`, return 0, nothing saved.
3. Other exception → `notify(list_error_message(f"{type(e).__name__}: {e}"))`, return 0 (1 if that notify fails), nothing saved.
4. Success → `new_keys = set()` if `prev is None` else keys of slots not in `prev`; `taken = [] if prev is None else diff(prev, slots)[1]`; `notify(list_message(...))`; on notify failure return 1 and save nothing.
5. After a successful send: `save_listed(slots, listed_path)`; load scan state and save it with **only `slots` replaced** (keep `fail_count`, `alerted`, `last_error_alert`), so the next scan does not re-announce slots already shown.

- [ ] **Step 1: Write failing tests** (reuse helpers in `tests/test_main.py`):
  - `test_list_first_time_no_marks`: no files → 1 message starting `"📋 Free now at Kohoku (2)"`, no `"🆕"`, no `"Taken"`; `list_state.json` holds [A, B]; scan state slots [A, B].
  - `test_list_marks_new_and_taken`: listed [A], fetch [B] → message has `"🆕 13:00–15:00"` and `"Taken since the last /list (1):"` with A.
  - `test_list_then_scan_is_silent`: after `run_list` with [A, B], `run(...)` with [A, B] sends nothing.
  - `test_list_keeps_failure_fields`: scan state `State(slots=[A], fail_count=3, alerted=True, last_error_alert=NOW)` → after `run_list` success, those three fields unchanged, slots updated.
  - `test_list_portal_error_reports_immediately`: fetch raises `PortalError("boom")` → exit 0, 1 message `"⚠️ Could not read the portal: PortalError: boom"`, both state files unchanged/absent.
  - `test_list_site_closed`: → `"🔧 The portal is in maintenance, try again later."`, exit 0.
  - `test_list_telegram_failure_saves_nothing`: notify raises → exit 1, `list_state.json` absent.
  - `test_main_mode_list_dry_run`: `main(["--dry-run","--mode","list","--state",…,"--list-state",…])` with patched fetch → exit 0, stdout contains `"📋 Free now"`.
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3: Implement** `run_list` and the CLI flags; `main` dispatches on `--mode`.
- [ ] **Step 4:** full suite → PASS (all old tests untouched).
- [ ] **Step 5: Live dry run:** `.venv/bin/python -m bot --dry-run --mode list --state <scratch>/s.json --list-state <scratch>/l.json` → prints the Kohoku list; delete the scratch files.
- [ ] **Step 6: Commit** `feat: --mode list posts the full availability`.

### Task 3: Cloudflare Worker

**Files:**
- Create: `worker/src/index.js`, `worker/test/index.test.js`, `worker/wrangler.toml`, `worker/package.json`, `worker/.gitignore` (`node_modules/`, `.wrangler/`)

**Interfaces:**
- Produces (named exports from `worker/src/index.js`, plus `export default { fetch, scheduled }`):
  - `parseCommand(text: string | undefined, botUsername: string) -> "list" | "help" | null` — first word only, case-insensitive; `/list`, `/list@<botUsername>` → `"list"`; `/help`, `/start` (with optional `@<botUsername>`) → `"help"`; `@OtherBot` suffix → `null`.
  - `dispatch(env, mode: "scan"|"list", fetchImpl = fetch) -> Promise<number>` — returns HTTP status.
  - `sendTelegram(env, chatId, text, fetchImpl = fetch) -> Promise<void>`.
  - `handleUpdate(update, env, { fetchImpl, now }) -> Promise<void>` — the `/list` / `/help` logic.
  - `fetch(request, env, ctx)`: `GET /` → 200 `ok`; `POST /telegram` → secret header check (403 if wrong), parse JSON, `await handleUpdate`, always 200 `ok` (even on internal errors, logged with `console.error`, no token in the log); anything else → 404.
  - `scheduled(event, env, ctx)` → `ctx.waitUntil(dispatch(env, "scan"))`, logging non-204 statuses.

`handleUpdate` rules: only `update.message` (ignore `edited_message`, `channel_post`, …); `String(message.chat.id) === env.ALLOWED_CHAT_ID`; command via `parseCommand`. `help` → one message listing `/list`. `list` → read `STATE.get("last_list_at")`; if `now - last < 180000` → cooldown reply; else `dispatch(env,"list")`; on 204 → `STATE.put("last_list_at", String(now))` and ack reply; otherwise error reply with the status. If `message.migrate_to_chat_id` is present, `console.log` the new id (no reply).

- [ ] **Step 1: Write failing tests** with `node:test` + `node:assert`, a fake `fetchImpl` recording calls and returning `new Response(null,{status})`, and a fake KV (`Map` with async `get`/`put`). Env: `{ALLOWED_CHAT_ID:"-100123", BOT_USERNAME:"volley_bot", GITHUB_REPO:"tobi-papa/volleyball-bot", GITHUB_TOKEN:"ghtok", TELEGRAM_BOT_TOKEN:"tgtok", WEBHOOK_SECRET:"s3cret", STATE}`:
  - `parseCommand`: `"/list"`, `"/list@volley_bot"`, `"/LIST please"` → `"list"`; `"/list@OtherBot"`, `"hello"`, `undefined` → `null`; `"/start"` → `"help"`.
  - webhook without header / wrong header → 403 and zero fetch calls.
  - `/list` from chat `-100999` → 200, zero fetch calls.
  - `edited_message` with `/list` → zero fetch calls.
  - valid `/list` → first call is POST to `https://api.github.com/repos/tobi-papa/volleyball-bot/actions/workflows/scan.yml/dispatches` with body `{"ref":"main","inputs":{"mode":"list"}}` and `Authorization: Bearer ghtok`; second call is `https://api.telegram.org/bottgtok/sendMessage` with the ack text and `chat_id` `-100123`; KV has `last_list_at`.
  - second `/list` 60 s later → no dispatch, cooldown reply; 181 s later → dispatch again.
  - dispatch returns 401 → reply `⚠️ Could not start the check (GitHub error 401).`, KV not set, response 200.
  - `scheduled` → one dispatch with `mode":"scan"`.
  - `GET /` → 200 `ok`; `GET /other` → 404.
- [ ] **Step 2:** `cd worker && npm test` → FAIL (module not found).
- [ ] **Step 3: Implement** `worker/src/index.js`; `package.json` with `"type":"module"`, `"scripts":{"test":"node --test test/","deploy":"npx wrangler@4 deploy"}`, no dependencies; `wrangler.toml`: `name = "volleyball-bot-worker"`, `main = "src/index.js"`, `compatibility_date = "2026-11-01"`, `[triggers] crons = ["*/10 22-23,0-14 * * *"]`, `[vars] GITHUB_REPO`, `BOT_USERNAME = ""` (filled at deploy), `[[kv_namespaces]] binding = "STATE"`, `id = ""` (filled at deploy).
- [ ] **Step 4:** `npm test` → all pass.
- [ ] **Step 5: Commit** `feat: Cloudflare Worker for /list and 10-minute launches`.

### Task 4: Workflow inputs, tests CI, README

**Files:**
- Modify: `.github/workflows/scan.yml`, `.github/workflows/test.yml`, `README.md`, `docs/design.md` (one paragraph pointing to the new spec)

- [ ] **Step 1: `scan.yml`:**
  - `workflow_dispatch.inputs.mode`: `type: choice`, options `scan`, `list`, default `scan`.
  - `concurrency.group: scan-volley-${{ inputs.mode || 'scan' }}`.
  - Run step: `python -m bot --mode "${{ inputs.mode || 'scan' }}"`.
  - State cache key becomes `bot-state-${{ github.run_id }}-${{ github.run_attempt }}` (restore prefix unchanged).
  - New restore step for `list_state.json` (key `bot-list-${{ github.run_id }}-${{ github.run_attempt }}`, restore-keys `bot-list-`) and save step with `if: always() && inputs.mode == 'list' && hashFiles('list_state.json') != ''`.
  - Keep `schedule` as is (fallback).
- [ ] **Step 2: `test.yml`:** add a `worker` job: `actions/setup-node@v6` (Node 24) + `cd worker && npm test`. Verify the action's latest major with `gh api repos/actions/setup-node/releases/latest`.
- [ ] **Step 3:** validate YAML: `.venv/bin/python -c "import yaml,sys;[yaml.safe_load(open(f)) for f in sys.argv[1:]]" .github/workflows/*.yml`; `.gitignore` gains `list_state.json`.
- [ ] **Step 4: README (English):** new sections "Telegram commands" (`/list`, `/help`; reply ~1 min; 3-min cooldown; marks) and "Cloudflare Worker" (why: GitHub runs schedules only every ~8 h; setup: Cloudflare account, `npx wrangler login`, KV namespace, the 4 secrets, fine-grained GitHub token with Actions read/write on this repo only, 1-year expiry and renewal, `setWebhook` with `secret_token` and `allowed_updates=["message"]`; note that `getUpdates` stops working after a webhook is set — to find a chat id again use `deleteWebhook` temporarily or the Worker log; supergroup ID change → update both `TELEGRAM_CHAT_ID` and `ALLOWED_CHAT_ID`).
- [ ] **Step 5:** full Python suite + `npm test` green.
- [ ] **Step 6: Commit** `ci: list mode inputs, worker tests; docs for /list and the Worker`.

### Task 5: Deploy and go live (with the user)

- [ ] **Step 1:** Push `main`; Tests workflow green (Python + worker jobs).
- [ ] **Step 2 (user):** create Cloudflare account; Claude runs `npx wrangler@4 login` in the user's terminal (browser approval by the user).
- [ ] **Step 3 (user):** create the fine-grained GitHub token (repo `tobi-papa/volleyball-bot`, Actions: Read and write, 1 year).
- [ ] **Step 4:** `npx wrangler@4 kv namespace create STATE` → put the id in `wrangler.toml`. The user types `GITHUB_TOKEN`, `TELEGRAM_BOT_TOKEN`, `ALLOWED_CHAT_ID` at the prompts of `npx wrangler@4 secret put <NAME>` in their terminal (never in chat).
- [ ] **Step 4b: `worker/setup-webhook.sh`** (created in this step, committed): asks for the bot token with `read -s`, calls `getMe` and prints the username (Claude puts it in `wrangler.toml` `BOT_USERNAME`), generates `S=$(openssl rand -hex 32)`, pipes it into `npx wrangler@4 secret put WEBHOOK_SECRET`, and calls `setWebhook` with `url=$1/telegram`, `secret_token=$S`, `allowed_updates=["message"]`, then prints `getWebhookInfo`. The secret never leaves the shell. Run it after Step 5's deploy (it needs the Worker URL as `$1`).
- [ ] **Step 5:** `npx wrangler@4 deploy`; `curl https://<worker>.workers.dev/` → `ok`.
- [ ] **Step 6:** `setWebhook` (url `https://<worker>.workers.dev/telegram`, `secret_token`, `allowed_updates=["message"]`); `getWebhookInfo` shows the url and no `last_error_message`.
- [ ] **Step 7: Verify live:** `/list` in the group → ack within seconds, list within ~2 min; a `Scan volley` run with event `workflow_dispatch` appears every ~10 min (check after 30 min: ≥ 2 such runs).
- [ ] **Step 8:** commit `wrangler.toml` with the KV id and bot username (not secret); update memory.
