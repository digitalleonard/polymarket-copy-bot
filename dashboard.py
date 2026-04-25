#!/usr/bin/env python3
"""
Polymarket Copy Trading Dashboard — Flask backend
Run with: python3 dashboard.py
Then open: http://localhost:5050
"""

import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from flask import Flask, jsonify, render_template, request

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
TRADES_LOG = os.path.join(BASE_DIR, "trades.json")
PID_FILE   = os.path.join(BASE_DIR, ".bot.pid")
BOT_SCRIPT = os.path.join(BASE_DIR, "bot.py")
BOT_LOG    = os.path.join(BASE_DIR, "bot.log")

app = Flask(__name__)

# ── Period helper ──────────────────────────────────────────────────────────────

def period_start(period: str):
    """Return UTC datetime for the start of the requested period, or None = all time."""
    now = datetime.now(timezone.utc)
    return {
        "today": now.replace(hour=0, minute=0, second=0, microsecond=0),
        "7d":    now - timedelta(days=7),
        "30d":   now - timedelta(days=30),
        "90d":   now - timedelta(days=90),
    }.get(period)          # None → all time

def parse_ts(raw: str):
    """Parse an ISO-ish timestamp into an aware datetime, or None."""
    if not raw:
        return None
    try:
        raw = raw.strip().replace(" UTC", "+00:00")
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        return datetime.fromisoformat(raw)
    except Exception:
        return None

def filter_by_period(items: list, ts_key: str, period: str) -> list:
    since = period_start(period)
    if since is None:
        return items
    result = []
    for item in items:
        ts = parse_ts(item.get(ts_key) or "")
        if ts and ts >= since:
            result.append(item)
    return result

# ── Helpers ───────────────────────────────────────────────────────────────────

def load_trades() -> list:
    if not os.path.exists(TRADES_LOG):
        return []
    try:
        with open(TRADES_LOG) as f:
            return json.load(f)
    except Exception:
        return []

def is_bot_running() -> bool:
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE) as f:
                pid = int(f.read().strip())
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, ValueError, OSError):
            os.remove(PID_FILE)
    try:
        result = subprocess.run(["pgrep", "-f", "bot.py"], capture_output=True, text=True)
        if result.returncode == 0:
            for pid in [int(p) for p in result.stdout.strip().split() if p.isdigit()]:
                if pid != os.getpid():
                    return True
    except Exception:
        pass
    return False

def compute_stats(trades: list, period: str = "all") -> dict:
    filtered   = filter_by_period(trades, "detected_at", period)
    total      = len(filtered)
    completed  = [t for t in filtered if (t.get("status") or "").lower() == "completed"]
    failed     = [t for t in filtered if (t.get("status") or "").lower() == "failed"]
    skipped    = [t for t in filtered if (t.get("status") or "").lower() == "skipped"]
    deployed   = sum(float(t.get("copy_amount_usd") or 0) for t in completed)
    decisive   = len(completed) + len(failed)
    win_rate   = round(len(completed) / decisive * 100, 1) if decisive > 0 else 0

    trader_counts: dict = {}
    for t in filtered:
        name = t.get("trader_name") or "Unknown"
        trader_counts[name] = trader_counts.get(name, 0) + 1
    trader_counts = dict(sorted(trader_counts.items(), key=lambda x: x[1], reverse=True))

    daily: dict = {}
    for t in filtered:
        raw  = t.get("detected_at") or t.get("logged_at") or ""
        date = raw[:10] if raw else "unknown"
        daily[date] = daily.get(date, 0) + 1
    daily = dict(sorted(daily.items()))

    buys  = sum(1 for t in filtered if (t.get("side") or "").upper() == "BUY")
    sells = sum(1 for t in filtered if (t.get("side") or "").upper() == "SELL")

    return {
        "total": total, "completed": len(completed), "failed": len(failed),
        "skipped": len(skipped), "deployed": round(deployed, 2),
        "win_rate": win_rate, "trader_counts": trader_counts, "daily": daily,
        "buys": buys, "sells": sells, "bot_running": is_bot_running(),
        "last_updated": datetime.now(timezone.utc).strftime("%H:%M:%S UTC"),
        "period": period,
    }

# ── P&L helpers ───────────────────────────────────────────────────────────────

_positions_cache: dict = {"ts": 0, "data": None}
_redemptions_cache: dict = {"ts": 0, "data": None}
CACHE_TTL = 60

def fetch_positions() -> dict:
    """Fetch live open positions from bullpen → {slug: position_dict}"""
    now = time.time()
    if _positions_cache["data"] is not None and now - _positions_cache["ts"] < CACHE_TTL:
        return _positions_cache["data"]

    positions = {}
    try:
        r = subprocess.run(
            ["bullpen", "polymarket", "positions", "--output", "json"],
            capture_output=True, text=True, timeout=15
        )
        if r.returncode == 0:
            raw = json.loads(r.stdout)
            items = raw.get("positions", raw) if isinstance(raw, dict) else raw
            for p in items:
                slug = p.get("slug")
                if slug:
                    positions[slug] = {
                        "unrealized_pnl": float(p.get("unrealized_pnl") or 0),
                        "pnl_percent":    float(p.get("pnl_percent") or 0),
                        "current_value":  float(p.get("current_value") or 0),
                        "invested_usd":   float(p.get("invested_usd") or 0),
                        "outcome":        p.get("outcome", ""),
                        "redeemable":     bool(p.get("redeemable", False)),
                    }
    except Exception:
        pass

    _positions_cache["ts"]   = now
    _positions_cache["data"] = positions
    return positions

def fetch_redemptions() -> list:
    """
    Fetch all redemption activity from bullpen.
    Each item: {slug, usdc_size, timestamp, title}
    Caches for CACHE_TTL seconds.
    """
    now = time.time()
    if _redemptions_cache["data"] is not None and now - _redemptions_cache["ts"] < CACHE_TTL:
        return _redemptions_cache["data"]

    redemptions = []
    try:
        r = subprocess.run(
            ["bullpen", "polymarket", "activity",
             "--type", "redeem", "--output", "json", "--limit", "200"],
            capture_output=True, text=True, timeout=20
        )
        if r.returncode == 0:
            raw = json.loads(r.stdout)
            items = raw if isinstance(raw, list) else raw.get("activity", [])
            for item in items:
                redemptions.append({
                    "slug":       item.get("slug", ""),
                    "title":      item.get("title", ""),
                    "usdc_size":  float(item.get("usdc_size") or 0),
                    "timestamp":  item.get("timestamp", ""),
                })
    except Exception:
        pass

    _redemptions_cache["ts"]   = now
    _redemptions_cache["data"] = redemptions
    return redemptions

def compute_realized_pnl(period: str, trades: list) -> dict:
    """
    Compute realized P&L for the period from redemption activity.
    Returns {total_redeemed, total_cost, realized_pnl, count, items[]}
    """
    redemptions = fetch_redemptions()
    filtered    = filter_by_period(redemptions, "timestamp", period)

    # Build cost-basis map: slug → total invested (from completed trades)
    cost_map: dict = {}
    for t in trades:
        if (t.get("status") or "").lower() == "completed":
            slug = t.get("market_slug") or ""
            cost_map[slug] = cost_map.get(slug, 0) + float(t.get("copy_amount_usd") or 0)

    total_redeemed = 0.0
    total_cost     = 0.0
    items          = []

    for r in filtered:
        slug   = r["slug"]
        payout = r["usdc_size"]

        # Match cost: exact slug, or trade slug that starts with redemption slug
        cost = cost_map.get(slug, 0)
        if cost == 0:
            for t_slug, t_cost in cost_map.items():
                if t_slug.startswith(slug) or slug.startswith(t_slug.rsplit("-", 1)[0]):
                    cost += t_cost

        total_redeemed += payout
        total_cost     += cost
        items.append({
            "slug":       slug,
            "title":      r["title"],
            "payout":     round(payout, 4),
            "cost":       round(cost, 4),
            "pnl":        round(payout - cost, 4),
            "timestamp":  r["timestamp"],
        })

    return {
        "total_redeemed": round(total_redeemed, 4),
        "total_cost":     round(total_cost, 4),
        "realized_pnl":   round(total_redeemed - total_cost, 4),
        "count":          len(items),
        "items":          items,
    }

def fetch_pnl_data(period: str = "all", trades: list = None) -> dict:
    if trades is None:
        trades = load_trades()

    positions = fetch_positions()
    realized  = compute_realized_pnl(period, trades)

    # Unrealized is always current (live market data — no period filter)
    total_unrealized = sum(p["unrealized_pnl"] for p in positions.values())

    return {
        "total_realized":   realized["realized_pnl"],
        "total_unrealized": round(total_unrealized, 4),
        "positions":        positions,
        "realized_detail":  realized,
    }

# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/stats")
def api_stats():
    period = request.args.get("period", "all")
    trades = load_trades()
    return jsonify(compute_stats(trades, period))

@app.route("/api/trades")
def api_trades():
    period = request.args.get("period", "all")
    trades = load_trades()
    filtered = filter_by_period(trades, "detected_at", period)
    return jsonify(list(reversed(filtered)))

@app.route("/api/pnl")
def api_pnl():
    period = request.args.get("period", "all")
    trades = load_trades()
    return jsonify(fetch_pnl_data(period, trades))

LAUNCHAGENT_LABEL = "fi.bullpen.bot2"

def launchctl_bot(action: str) -> tuple[bool, str]:
    """Run launchctl stop/start for the bot LaunchAgent. Returns (ok, message)."""
    try:
        r = subprocess.run(
            ["launchctl", action, LAUNCHAGENT_LABEL],
            capture_output=True, text=True, timeout=10
        )
        if r.returncode == 0:
            return True, f"Bot {action}ped via LaunchAgent"
        # launchctl stop returns non-zero if already stopped — treat as OK
        err = r.stderr.strip() or r.stdout.strip()
        return True, f"Bot {action}: {err}"
    except Exception as e:
        return False, str(e)

@app.route("/api/bot/start", methods=["POST"])
def bot_start():
    if is_bot_running():
        return jsonify({"ok": True, "message": "Bot already running"})
    ok, message = launchctl_bot("start")
    # Give it a moment to spin up, then verify
    time.sleep(2)
    if ok and is_bot_running():
        return jsonify({"ok": True, "message": message})
    # Fallback: launch directly if launchctl start didn't work
    try:
        log_f = open(BOT_LOG, "a")
        proc  = subprocess.Popen(
            [sys.executable, BOT_SCRIPT],
            stdout=log_f, stderr=log_f, start_new_session=True
        )
        with open(PID_FILE, "w") as f:
            f.write(str(proc.pid))
        return jsonify({"ok": True, "message": f"Bot started directly (PID {proc.pid})"})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500

@app.route("/api/bot/stop", methods=["POST"])
def bot_stop():
    if not is_bot_running():
        return jsonify({"ok": True, "message": "Bot was not running"})
    # Stop via LaunchAgent first (it will restart automatically on next start)
    ok, message = launchctl_bot("stop")
    # Also clean up any direct PID file
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE) as f:
                pid = int(f.read().strip())
            os.kill(pid, signal.SIGTERM)
            os.remove(PID_FILE)
        except Exception:
            pass
    time.sleep(1)
    return jsonify({"ok": ok, "message": message})

@app.route("/api/bot/status")
def bot_status():
    return jsonify({"running": is_bot_running()})

# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("━" * 50)
    print("  🤖 Polymarket Copy Trading Dashboard")
    print("  Open → http://localhost:5050")
    print("━" * 50)
    app.run(host="127.0.0.1", port=5050, debug=False)
