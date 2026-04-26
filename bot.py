#!/usr/bin/env python3
"""
Polymarket Copy Trading Bot — Monitor, Logger, Auto-Redeemer & Auto-Resumer
Polls bullpen copy trade executions every 30s, logs all activity to trades.json,
automatically redeems any resolved winning positions so funds stay available,
and auto-resumes any AutoPaused subscriptions after balance is restored.
"""

import json
import subprocess
import time
import os
import sys
from datetime import datetime, timezone

# ── Config ────────────────────────────────────────────────────────────────────
POLL_INTERVAL_SECONDS  = 30
LOG_FILE               = os.path.join(os.path.dirname(__file__), "trades.json")
STATE_FILE             = os.path.join(os.path.dirname(__file__), ".seen_ids.json")
EXECUTIONS_LIMIT       = 50   # how many recent executions to fetch per poll
POSITIONS_TIMEOUT      = 45   # seconds before giving up on positions call
POSITIONS_RETRIES      = 2    # extra retries on timeout
REDEEM_TIMEOUT         = 60   # seconds for the redeem command (can be slow)

# ── Auth monitoring ───────────────────────────────────────────────────────────
AUTH_NOTIFY_COOLDOWN   = 3600  # only send one notification per hour (avoid spam)
_last_auth_notify_at   = 0     # epoch seconds of last notification sent

# ── Tracked traders (for reference / future dashboard use) ───────────────────
TRADERS = {
    "0xc2e7800b5af46e6093872b177b7a5e7f0563be51": "beachboy4",
    "0x2005d16a84ceefa912d4e380cd32e7ff827875ea": "RN1",
    "0xee613b3fc183ee44f9da9c05f53e2da107e3debf": "sovereign2013",
    "0x204f72f35326db932158cba6adff0b9a1da95e14": "swisstony",
    "0xc8075693f48668a264b9fa313b47f52712fcc12b": "texaskid",
    "0x777d9f00c2b4f7b829c9de0049ca3e707db05143": "CarlosMC",
    "0xbddf61af533ff524d27154e589d2d7a81510c684": "Countryside",
    "0x93abbc022ce98d6f45d4444b594791cc4b7a9723": "gatorr",
    "0x6a72f61820b26b1fe4d956e17b6dc2a1ea3033ee": "kch123",
    "0xead152b855effa6b5b5837f53b24c0756830c76a": "elkmonkey",
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def now_utc():
    return datetime.now(timezone.utc).isoformat()

def log(msg: str):
    print(f"[{now_utc()}] {msg}", flush=True)

def is_auth_error(text: str) -> bool:
    """Returns True if the output text indicates an expired/corrupted session."""
    auth_phrases = [
        "failed to decrypt",
        "not logged in",
        "re-authenticate",
        "run `bullpen login`",
        "credentials",
        "token",
        "unauthorized",
        "401",
    ]
    lowered = text.lower()
    return any(phrase in lowered for phrase in auth_phrases)


def notify_auth_expired():
    """Send a macOS system notification telling the user to re-login."""
    global _last_auth_notify_at
    now = time.time()
    if now - _last_auth_notify_at < AUTH_NOTIFY_COOLDOWN:
        return  # already notified recently — don't spam
    _last_auth_notify_at = now

    log("🔔 Sending macOS notification: Bullpen session expired")
    try:
        subprocess.run(
            [
                "osascript", "-e",
                'display notification "Run: bullpen login\\nBot is paused until you re-authenticate." '
                'with title "⚠️ Polymarket Bot — Login Required" '
                'sound name "Basso"',
            ],
            timeout=5,
            capture_output=True,
        )
    except Exception as e:
        log(f"[WARN] Could not send notification: {e}")


def clear_corrupted_credentials():
    """
    If credentials are corrupted (not just expired), wipe the bad files so
    `bullpen login` can start fresh instead of looping on decrypt errors.
    """
    bullpen_dir = os.path.expanduser("~/.bullpen")
    enc_file    = os.path.join(bullpen_dir, "credentials.json.enc")
    keys_dir    = os.path.join(bullpen_dir, "keys")
    cleared     = False

    if os.path.exists(enc_file):
        try:
            os.remove(enc_file)
            log("[AUTH] Removed corrupted credentials.json.enc")
            cleared = True
        except Exception as e:
            log(f"[WARN] Could not remove {enc_file}: {e}")

    if os.path.isdir(keys_dir):
        import shutil
        try:
            shutil.rmtree(keys_dir)
            log("[AUTH] Removed corrupted keys/ directory")
            cleared = True
        except Exception as e:
            log(f"[WARN] Could not remove {keys_dir}: {e}")

    return cleared


def load_seen_ids() -> set:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()

def save_seen_ids(ids: set):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(list(ids), f)
    except Exception as e:
        log(f"[WARN] Could not save seen IDs: {e}")

def load_trade_log() -> list:
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE) as f:
                return json.load(f)
        except Exception:
            return []
    return []

def append_trade(trade: dict):
    trades = load_trade_log()
    trades.append(trade)
    try:
        with open(LOG_FILE, "w") as f:
            json.dump(trades, f, indent=2)
    except Exception as e:
        log(f"[ERROR] Could not write to {LOG_FILE}: {e}")

def fetch_executions() -> list:
    """Call bullpen CLI and return list of execution dicts."""
    result = subprocess.run(
        ["bullpen", "tracker", "copy", "executions",
         "--output", "json",
         "--limit", str(EXECUTIONS_LIMIT)],
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        err = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"bullpen exited {result.returncode}: {err}")

    raw = json.loads(result.stdout)

    # bullpen returns {"executions": [...]} or a bare list
    if isinstance(raw, dict):
        return raw.get("executions", [])
    if isinstance(raw, list):
        return raw
    return []

def build_log_entry(ex: dict) -> dict:
    """Shape an execution into a clean log record for trades.json."""
    trader_addr = (ex.get("source_trader_address") or "").lower()
    trader_name = (
        ex.get("trader_name")
        or TRADERS.get(trader_addr)
        or trader_addr[:10] + "..."
    )

    return {
        # identity
        "id":               ex.get("id"),
        "subscription_id":  ex.get("subscription_id"),
        "logged_at":        now_utc(),

        # trader
        "trader_name":      trader_name,
        "trader_address":   trader_addr,

        # what they did
        "market_slug":      ex.get("source_market_slug"),
        "market_title":     ex.get("market_title"),
        "event_title":      ex.get("event_title"),
        "outcome":          ex.get("source_outcome"),
        "side":             ex.get("source_side"),       # BUY | SELL
        "source_price":     ex.get("source_price"),
        "source_size_usd":  ex.get("source_size_usd"),

        # what we did
        "copy_amount_usd":  ex.get("copy_amount_usd"),
        "filled_amount":    ex.get("filled_amount"),
        "avg_price":        ex.get("avg_price"),
        "order_id":         ex.get("order_id"),

        # outcome
        "status":           ex.get("status"),           # Completed | Failed | Skipped
        "error_message":    ex.get("error_message"),
        "skip_reason":      ex.get("skip_reason"),

        # timestamps
        "detected_at":      ex.get("detected_at"),
        "executed_at":      ex.get("executed_at"),
        "completed_at":     ex.get("completed_at"),
    }

def pretty_status(entry: dict) -> str:
    status = (entry.get("status") or "").upper()
    icons = {"COMPLETED": "✅", "FAILED": "❌", "SKIPPED": "⏭️", "PENDING": "⏳"}
    icon = icons.get(status, "❓")

    side   = entry.get("side", "?")
    slug   = entry.get("market_slug", "?")
    out    = entry.get("outcome", "?")
    amt    = entry.get("copy_amount_usd", "?")
    trader = entry.get("trader_name", "?")

    line = f"{icon} [{status}] {trader} → {side} {out} on {slug} (${amt})"

    if entry.get("error_message"):
        line += f"\n         ⚠️  {entry['error_message']}"
    if entry.get("skip_reason"):
        line += f"\n         ⏭️  {entry['skip_reason']}"

    return line

# ── Auto-redeem ───────────────────────────────────────────────────────────────

def fetch_positions() -> list:
    """
    Fetch open positions with retries on timeout.
    Returns a list of position dicts, or [] on failure.
    """
    for attempt in range(POSITIONS_RETRIES + 1):
        try:
            r = subprocess.run(
                ["bullpen", "polymarket", "positions", "--output", "json"],
                capture_output=True, text=True, timeout=POSITIONS_TIMEOUT
            )
            if r.returncode != 0:
                log(f"[WARN] positions check failed: {r.stderr.strip()}")
                return []
            raw = json.loads(r.stdout)
            return raw.get("positions", raw) if isinstance(raw, dict) else raw

        except subprocess.TimeoutExpired:
            if attempt < POSITIONS_RETRIES:
                log(f"[WARN] positions timed out (attempt {attempt + 1}/{POSITIONS_RETRIES + 1}) — retrying in 5s...")
                time.sleep(5)
            else:
                log(f"[ERROR] positions timed out after {POSITIONS_RETRIES + 1} attempts — skipping this cycle")
                return []
        except json.JSONDecodeError as e:
            log(f"[ERROR] Could not parse positions response: {e}")
            return []
        except Exception as e:
            log(f"[ERROR] fetch_positions error: {e}")
            return []
    return []


def check_and_redeem() -> bool:
    """
    Fetches open positions, finds any that are redeemable (market resolved in
    our favour), and redeems them automatically so the USDC comes back for
    new trades.

    Returns True if at least one redemption succeeded (caller should then
    check for paused subscriptions to resume).
    """
    positions  = fetch_positions()
    redeemable = [p for p in positions if p.get("redeemable")]

    if not redeemable:
        return False  # nothing to do — stay silent

    log(f"💰 {len(redeemable)} redeemable position(s) found — redeeming now...")
    for p in redeemable:
        market  = p.get("market") or p.get("slug") or "unknown market"
        outcome = p.get("outcome", "")
        value   = p.get("current_value", "?")
        log(f"   ↳ {market} | {outcome} | ~${value}")

    try:
        redeem = subprocess.run(
            ["bullpen", "polymarket", "redeem", "--yes"],
            capture_output=True, text=True, timeout=REDEEM_TIMEOUT
        )
        output = (redeem.stdout or "") + (redeem.stderr or "")

        if redeem.returncode == 0:
            log(f"✅ Redemption successful — USDC returned to wallet")
            return True
        else:
            # Partial success: bullpen exits non-zero but some positions may
            # have redeemed. Log the full output and return True so we still
            # attempt to resume paused subscriptions.
            log(f"[WARN] Redemption returned non-zero exit — output:")
            for line in output.strip().splitlines():
                log(f"   {line}")
            # If any "redeemed" line appears in stdout it was at least partial
            return "redeemed" in output.lower()

    except subprocess.TimeoutExpired:
        log(f"[ERROR] Redeem command timed out after {REDEEM_TIMEOUT}s")
        return False
    except Exception as e:
        log(f"[ERROR] Redemption error: {e}")
        return False


# ── Auto-resume paused subscriptions ─────────────────────────────────────────

def check_and_resume_paused_subs():
    """
    Fetches copy subscriptions, finds any that are AutoPaused (typically due
    to insufficient balance), and resumes them so we don't miss new signals.
    Called after every successful redemption and once per cycle as a safety net.
    """
    try:
        r = subprocess.run(
            ["bullpen", "tracker", "copy", "list", "--output", "json"],
            capture_output=True, text=True, timeout=20
        )
        if r.returncode != 0:
            log(f"[WARN] copy list failed: {r.stderr.strip()}")
            return

        subs   = json.loads(r.stdout)
        paused = [s for s in subs if s.get("status") == "AutoPaused"]

        if not paused:
            return  # all good — stay silent

        log(f"⚠️  {len(paused)} AutoPaused subscription(s) found — resuming...")

        resumed = 0
        for sub in paused:
            addr = sub.get("followed_address", "")
            nick = sub.get("nickname") or addr[:10]
            if not addr:
                continue

            result = subprocess.run(
                ["bullpen", "tracker", "copy", "resume", addr],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode == 0:
                log(f"   ✅ Resumed {nick}")
                resumed += 1
            else:
                err = result.stderr.strip() or result.stdout.strip()
                log(f"   ❌ Could not resume {nick}: {err}")

        if resumed:
            log(f"   → {resumed}/{len(paused)} subscription(s) resumed and active again")

    except json.JSONDecodeError as e:
        log(f"[ERROR] Could not parse copy list response: {e}")
    except Exception as e:
        log(f"[ERROR] Auto-resume error: {e}")


# ── Main loop ─────────────────────────────────────────────────────────────────

def main():
    log("🚀 Polymarket copy trading bot started")
    log(f"   Polling every {POLL_INTERVAL_SECONDS}s | Log → {LOG_FILE}")
    log(f"   Tracking {len(TRADERS)} traders")
    log(f"   Auto-redeem:  ON ✅  (timeout {POSITIONS_TIMEOUT}s, {POSITIONS_RETRIES} retries)")
    log(f"   Auto-resume:  ON ✅  (resumes AutoPaused subs after redemption)")
    print()

    seen_ids = load_seen_ids()
    log(f"   Loaded {len(seen_ids)} previously seen execution IDs")
    print()

    while True:
        try:
            executions = fetch_executions()
            new_count  = 0

            for ex in executions:
                ex_id = ex.get("id")
                if not ex_id or ex_id in seen_ids:
                    continue

                # new execution — process it
                seen_ids.add(ex_id)
                entry = build_log_entry(ex)
                append_trade(entry)
                new_count += 1

                log(pretty_status(entry))

            save_seen_ids(seen_ids)

            if new_count == 0:
                log(f"— no new executions (checked {len(executions)} recent)")
            else:
                log(f"— logged {new_count} new execution(s) to {LOG_FILE}")

            # ── Auto-redeem resolved positions ─────────────────────────────
            redeemed = check_and_redeem()

            # ── Auto-resume paused subscriptions ───────────────────────────
            # Always check (balance may have been restored by the redemption
            # above, or by a manual deposit, or by a previous cycle that logged
            # an error before it could resume).
            check_and_resume_paused_subs()

        except json.JSONDecodeError as e:
            log(f"[ERROR] Could not parse bullpen output: {e} — retrying in {POLL_INTERVAL_SECONDS}s")
        except RuntimeError as e:
            err_str = str(e)
            log(f"[ERROR] bullpen CLI error: {err_str} — retrying in {POLL_INTERVAL_SECONDS}s")
            if is_auth_error(err_str):
                if "corrupted" in err_str.lower():
                    log("[AUTH] Credentials corrupted — clearing bad files for clean re-login")
                    clear_corrupted_credentials()
                notify_auth_expired()
        except KeyboardInterrupt:
            log("👋 Bot stopped by user. Goodbye.")
            sys.exit(0)
        except Exception as e:
            log(f"[ERROR] Unexpected error: {e} — retrying in {POLL_INTERVAL_SECONDS}s")

        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
