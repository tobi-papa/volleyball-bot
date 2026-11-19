#!/usr/bin/env bash
# Connect the Telegram bot to the deployed Worker.
# Usage (from worker/): ./setup-webhook.sh https://volleyball-bot-worker.<you>.workers.dev
# Asks for the bot token, prints the bot username (for BOT_USERNAME in wrangler.toml),
# creates WEBHOOK_SECRET as a Worker secret and registers the webhook with it.
# The token and the secret stay in this shell: nothing is written to disk.
set -euo pipefail

URL="${1:?usage: $0 <worker-url>}"
URL="${URL%/}"

read -r -s -p "Telegram bot token: " TG
echo

USERNAME=$(curl -fsS "https://api.telegram.org/bot${TG}/getMe" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["result"]["username"])')
echo "Bot username: ${USERNAME}  (put it in wrangler.toml as BOT_USERNAME)"

SECRET=$(openssl rand -hex 32)
printf '%s' "$SECRET" | npx wrangler@4 secret put WEBHOOK_SECRET

curl -fsS "https://api.telegram.org/bot${TG}/setWebhook" \
  --data-urlencode "url=${URL}/telegram" \
  --data-urlencode "secret_token=${SECRET}" \
  --data-urlencode 'allowed_updates=["message"]' \
  --data-urlencode "drop_pending_updates=true"
echo
curl -fsS "https://api.telegram.org/bot${TG}/getWebhookInfo"
echo
