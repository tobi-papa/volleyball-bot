"""One bot run: read the portal, compare with last time, message Telegram."""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional

from bot import messages
from bot.config import Config, load_config
from bot.portal import SiteClosed, fetch_slots
from bot.slots import apply_rules
from bot.state import State, diff, load_state, save_state, should_alert
from bot.telegram import send

ALERT_AFTER_FAILURES = 2   # a single timeout does not ping anyone


def _run_url() -> Optional[str]:
    server, repo, run_id = (os.environ.get(k) for k in ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID"))
    return f"{server}/{repo}/actions/runs/{run_id}" if server and repo and run_id else None


def run(config: Config, state_path: Path, *, fetch=fetch_slots,
        notify: Callable[[str], None], now: datetime) -> int:
    state = load_state(state_path)
    try:
        slots = apply_rules(fetch(config.purpose, config.gyms, now=now), config.rules)
    except SiteClosed:
        print("Portal is in maintenance: skipping this run.")
        return 0
    except Exception as e:
        # Handled here: the Telegram alert is the channel, so the run itself stays green
        # (a red run would also send a GitHub email every 10 minutes during an outage).
        err = f"{type(e).__name__}: {e}"
        print(f"::warning::Run failed: {err}")
        state.fail_count += 1
        code = 0
        if state.fail_count >= ALERT_AFTER_FAILURES and should_alert(state, now, config.error_alert_every_hours):
            try:
                notify(messages.error_message(err, _run_url()))
                state.last_error_alert = now
                state.alerted = True
            except Exception as send_err:
                print(f"Could not send the error alert: {send_err}", file=sys.stderr)
                code = 1   # Telegram is broken too: let GitHub tell the user
        save_state(state, state_path)
        return code

    out: List[str] = []
    if state.alerted:
        out.append(messages.recovered_message())
    if state.slots is None:
        out.append(messages.baseline_message(slots))
    else:
        new, gone = diff(state.slots, slots)
        gone = gone if config.notify_gone else []
        if new or gone:
            out.append(messages.new_slots_message(new, gone))
        elif config.notify_no_change:
            out.append(messages.no_change_message(slots))

    try:
        for text in out:
            notify(text)
    except Exception as e:
        print(f"Could not send to Telegram, state not saved: {e}", file=sys.stderr)
        return 1

    save_state(State(slots=slots, last_error_alert=state.last_error_alert), state_path)
    print(f"{len(slots)} matching free slot(s); {len(out)} message(s) sent.")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m bot", description="Volleyball court availability bot")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--state", default="state.json")
    ap.add_argument("--dry-run", action="store_true", help="print messages instead of sending them")
    args = ap.parse_args(argv)

    if args.dry_run:
        def notify(text: str) -> None:
            print(text, end="\n\n")
    else:
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
        if not token or not chat_id:
            raise SystemExit("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set (or use --dry-run)")

        def notify(text: str) -> None:
            send(text, token, chat_id)

    return run(load_config(args.config), Path(args.state), fetch=fetch_slots,
               notify=notify, now=datetime.now(timezone.utc))
