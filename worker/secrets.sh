#!/usr/bin/env bash
# Keep the bot's keys in the macOS Keychain (encrypted, unlocked by your Mac login).
# Nothing is written to this repo, and values are never printed.
#
#   ./secrets.sh save          ask for every key and store it (Enter on an empty value skips it)
#   ./secrets.sh save NAME     store or replace one key
#   ./secrets.sh list          show which keys are stored (not their values)
#   ./secrets.sh copy NAME     copy one key to the clipboard
#   ./secrets.sh push          send every stored key to the Cloudflare Worker (wrangler secret put)
set -euo pipefail

SERVICE="${VB_KEYCHAIN_SERVICE:-volleyball-bot}"
NAMES=(GITHUB_TOKEN TELEGRAM_BOT_TOKEN ALLOWED_CHAT_ID)
cd "$(dirname "$0")"

have() { security find-generic-password -s "$SERVICE" -a "$1" >/dev/null 2>&1; }
value() { security find-generic-password -s "$SERVICE" -a "$1" -w; }

save_one() {
  echo "$1 — paste it at the prompt (typing is hidden), twice:"
  # -w as the last option makes `security` prompt for the value, so it never
  # appears on a command line or in shell history
  security add-generic-password -U -s "$SERVICE" -a "$1" -l "$SERVICE $1" -w
  echo "  saved $1"
}

case "${1:-}" in
  save)
    if [ -n "${2:-}" ]; then save_one "$2"; else for n in "${NAMES[@]}"; do save_one "$n"; done; fi ;;
  list)
    for n in "${NAMES[@]}"; do
      if have "$n"; then echo "✓ $n"; else echo "✗ $n (missing: ./secrets.sh save $n)"; fi
    done ;;
  copy)
    n="${2:?usage: $0 copy NAME}"
    value "$n" | tr -d '\n' | pbcopy
    echo "$n copied to the clipboard" ;;
  push)
    for n in "${NAMES[@]}"; do
      if have "$n"; then
        value "$n" | tr -d '\n' | npx wrangler@4 secret put "$n"
      else
        echo "skipping $n: not in the Keychain"
      fi
    done ;;
  *)
    sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'
    exit 1 ;;
esac
