#!/usr/bin/env python3
"""
Polymarket Trader Rotation — runs every 2 days via LaunchAgent fi.bullpen.rotate
Analyses current trader performance from trades.json, finds high-efficiency
replacements from the weekly leaderboard, removes underperformers, adds better ones.
"""

import json
import subprocess
import sys
import os
from datetime import datetime, timezone

LOG_FILE   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trades.json")
ROTATE_LOG = "/tmp/rotate.log"

# Thresholds
MIN_SIGNALS_TO_JUDGE  = 20    # need at least this many non-skipped signals before judging
UNDERPERFORM_WIN_RATE = 0.25  # below 25% completed rate → candidate for removal
MAX_ROSTER_SIZE       = 12    # never exceed this many subscriptions
MIN_LEADERBOARD_VOL   = 100   # ignore leaderboard traders with < $100 weekly volume
MIN_EFFICIENCY        = 1.5   # require pnl/volume > 1.5x for new additions
MAX_TRADE_SIZE        = 5000  # skip candidates whose median trade size > $5k
MIN_PRICE             = 0.10  # skip candidates who mostly bet on extreme longshots

# Current known bad patterns (spam / extreme-size traders — update as needed)
BLACKLIST = {
    "0x...surfandturf",   # splits single positions into 20+ chunks
    "0x...sportmaster",   # bets at 6-9% odds only
}


def log(msg: str):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(ROTATE_LOG, "a") as f:
        f.write(line + "\n")


def run(cmd: list, timeout: int = 30) -> tuple[int, str, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", f"timed out after {timeout}s"
    except Exception as e:
        return -1, "", str(e)


def bullpen_json(cmd: list, timeout: int = 30):
    rc, out, err = run(cmd + ["--output", "json"], timeout=timeout)
    if rc != 0:
        log(f"[ERROR] {' '.join(cmd)}: {err or out}")
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        log(f"[ERROR] Could not parse JSON from: {' '.join(cmd)}")
        return None


# ── 1. Load trades.json and compute per-trader stats ────────────────────────

def load_trader_stats() -> dict:
    """Returns {address: {name, completed, failed, skipped, win_rate}}"""
    try:
        with open(LOG_FILE) as f:
            trades = json.load(f)
    except Exception as e:
        log(f"[ERROR] Could not read trades.json: {e}")
        return {}

    stats = {}
    for t in trades:
        addr = t.get("trader_address", "").lower()
        name = t.get("trader_name", addr[:10])
        status = t.get("status", "")
        if addr not in stats:
            stats[addr] = {"name": name, "completed": 0, "failed": 0, "skipped": 0}
        if status == "Completed":
            stats[addr]["completed"] += 1
        elif status == "Failed":
            stats[addr]["failed"] += 1
        elif status == "Skipped":
            stats[addr]["skipped"] += 1

    for addr, s in stats.items():
        judged = s["completed"] + s["failed"]
        s["judged"] = judged
        s["win_rate"] = s["completed"] / judged if judged > 0 else None

    return stats


# ── 2. Get current subscriptions ────────────────────────────────────────────

def get_subscriptions() -> list:
    data = bullpen_json(["bullpen", "tracker", "copy", "list"])
    if data is None:
        return []
    # Handle both list and dict responses
    if isinstance(data, dict):
        data = data.get("subscriptions", data.get("items", []))
    return data if isinstance(data, list) else []


# ── 3. Get weekly leaderboard ────────────────────────────────────────────────

def get_leaderboard(limit: int = 50) -> list:
    data = bullpen_json(
        ["bullpen", "polymarket", "data", "leaderboard", "--period", "week", "--limit", str(limit)],
        timeout=40,
    )
    if data is None:
        return []
    if isinstance(data, dict):
        data = data.get("traders", data.get("items", []))
    return data if isinstance(data, list) else []


# ── 4. Vet a candidate trader via recent executions ──────────────────────────

def vet_candidate(address: str) -> tuple[bool, str]:
    """
    Returns (ok, reason).
    Checks recent executions for red flags: huge trade sizes, extreme low prices.
    """
    data = bullpen_json(
        ["bullpen", "tracker", "copy", "executions", "--address", address, "--limit", "20"],
        timeout=30,
    )
    if data is None:
        return True, "no execution data — accepting on leaderboard merit"

    execs = data if isinstance(data, list) else data.get("executions", data.get("items", []))
    if not execs:
        return True, "no recent executions found — accepting"

    sizes  = []
    prices = []
    for e in execs:
        sz = e.get("source_size_usd") or e.get("size_usd") or e.get("amount")
        pr = e.get("source_price") or e.get("price")
        if sz:
            try:
                sizes.append(float(sz))
            except (ValueError, TypeError):
                pass
        if pr:
            try:
                prices.append(float(pr))
            except (ValueError, TypeError):
                pass

    if sizes:
        median_size = sorted(sizes)[len(sizes) // 2]
        if median_size > MAX_TRADE_SIZE:
            return False, f"median trade size ${median_size:,.0f} too large (>${MAX_TRADE_SIZE:,} threshold)"

    if prices:
        avg_price = sum(prices) / len(prices)
        if avg_price < MIN_PRICE:
            return False, f"avg price {avg_price:.2%} too low — likely extreme longshot trader"

    return True, "passed vetting"


# ── 5. Remove a trader ───────────────────────────────────────────────────────

def remove_trader(address: str, name: str, reason: str):
    log(f"  ❌ Removing {name} ({address[:10]}…) — {reason}")
    rc, out, err = run(
        ["bullpen", "tracker", "copy", "delete", address, "--confirm"],
        timeout=20,
    )
    if rc == 0:
        log(f"     ✅ Removed {name}")
    else:
        log(f"     ⚠️  Could not remove {name}: {err or out}")


# ── 6. Add a trader ──────────────────────────────────────────────────────────

def add_trader(address: str, name: str):
    log(f"  ➕ Adding {name} ({address[:10]}…)")
    rc, out, err = run(
        [
            "bullpen", "tracker", "copy", "start", address,
            "--amount", "1",
            "--execution-mode", "auto",
            "--exit-behavior", "mirror_sells",
            "--price-range-min", "0.05",
            "--price-range-max", "0.95",
            "--max-trade-size", "100000",
            "--slippage", "3",
            "--nickname", name,
        ],
        timeout=30,
    )
    if rc == 0:
        log(f"     ✅ Added {name}")
    else:
        log(f"     ⚠️  Could not add {name}: {err or out}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    log("=" * 60)
    log("🔄 Trader rotation scan starting")
    log("=" * 60)

    # 1. Load stats
    stats = load_trader_stats()
    if not stats:
        log("[ABORT] No trade data — skipping rotation")
        return

    # 2. Current subscriptions
    subs = get_subscriptions()
    if not subs:
        log("[ABORT] Could not fetch subscriptions — skipping rotation")
        return

    subscribed_addrs = {
        s.get("followed_address", "").lower(): s.get("nickname") or s.get("followed_address", "")[:10]
        for s in subs
    }
    log(f"📋 Active subscriptions: {len(subscribed_addrs)}")
    for addr, name in subscribed_addrs.items():
        s = stats.get(addr)
        if s and s["judged"] >= MIN_SIGNALS_TO_JUDGE:
            log(f"   {name}: {s['completed']}/{s['judged']} completed ({s['win_rate']:.0%} win rate)")
        elif s:
            log(f"   {name}: {s.get('judged',0)} signals (too few to judge)")
        else:
            log(f"   {name}: no trade history yet")

    # 3. Identify underperformers
    to_remove = []
    for addr, name in subscribed_addrs.items():
        s = stats.get(addr)
        if s and s["judged"] >= MIN_SIGNALS_TO_JUDGE and s["win_rate"] is not None:
            if s["win_rate"] < UNDERPERFORM_WIN_RATE:
                to_remove.append((addr, name, s["win_rate"], s["judged"]))

    if to_remove:
        log(f"\n⚠️  Found {len(to_remove)} underperformer(s) (< {UNDERPERFORM_WIN_RATE:.0%} win rate):")
        for addr, name, wr, judged in to_remove:
            log(f"   {name}: {wr:.0%} from {judged} signals")
    else:
        log("\n✅ All traders above performance threshold — no removals needed")

    # 4. Get leaderboard for replacements
    replacements_needed = len(to_remove)
    roster_slots = MAX_ROSTER_SIZE - len(subscribed_addrs) + replacements_needed

    if roster_slots <= 0 and not to_remove:
        log("ℹ️  Roster full and no underperformers — done")
        log("=" * 60)
        return

    log(f"\n🔍 Fetching weekly leaderboard (need {roster_slots} slot(s))…")
    leaderboard = get_leaderboard(limit=60)

    candidates = []
    for entry in leaderboard:
        addr = entry.get("address", "").lower()
        name = entry.get("username") or addr[:10]
        if addr in subscribed_addrs:
            continue
        if addr in BLACKLIST:
            continue
        pnl_str = entry.get("pnl", "0") or "0"
        vol_str = entry.get("volume", "0") or "0"
        try:
            pnl = float(pnl_str)
            vol = float(vol_str)
        except (ValueError, TypeError):
            continue
        if vol < MIN_LEADERBOARD_VOL:
            continue
        efficiency = pnl / vol if vol > 0 else 0
        if efficiency < MIN_EFFICIENCY:
            continue
        candidates.append({
            "address": addr,
            "name": name,
            "pnl": pnl,
            "volume": vol,
            "efficiency": efficiency,
        })

    candidates.sort(key=lambda x: x["efficiency"], reverse=True)
    log(f"   {len(candidates)} leaderboard candidate(s) above efficiency threshold ({MIN_EFFICIENCY}x)")

    # 5. Vet top candidates
    vetted = []
    for c in candidates[:roster_slots * 3]:  # check 3× more than needed in case some fail vetting
        ok, reason = vet_candidate(c["address"])
        if ok:
            log(f"   ✅ {c['name']} — {c['efficiency']:.1f}x efficiency — {reason}")
            vetted.append(c)
            if len(vetted) >= roster_slots:
                break
        else:
            log(f"   ⛔ {c['name']} — REJECTED: {reason}")

    # 6. Execute removals
    if to_remove:
        log(f"\n🗑  Removing {len(to_remove)} underperformer(s)…")
        for addr, name, wr, judged in to_remove:
            remove_trader(addr, name, f"{wr:.0%} win rate from {judged} signals")

    # 7. Execute additions
    if vetted:
        log(f"\n✨ Adding {len(vetted)} new trader(s)…")
        for c in vetted:
            add_trader(c["address"], c["name"])
    elif replacements_needed > 0:
        log(f"\n⚠️  Could not find {replacements_needed} vetted replacement(s) — roster may be smaller temporarily")

    # 8. Final summary
    log("\n📊 Rotation complete. Run `bullpen tracker copy list` to verify.")
    log("=" * 60)


if __name__ == "__main__":
    main()
