---
name: polymarket-copy-bot
description: "Use when the user asks about their Polymarket copy trading bot — checking if it's running, fixing issues, checking performance, managing subscriptions, reviewing P&L, restarting services, or upgrading. Activate for any question about the bot, dashboard, trades, balance, or copy trading system in this project."
license: MIT
metadata:
  author: digitalleonard
  version: "1.0.0"
  tags: [polymarket, copy-trading, prediction-markets, bullpen, trading-bot]
  docs-url: https://cli.bullpen.fi
---

# Polymarket Copy Bot

An automated Polymarket copy trading system. Monitors 10 elite traders, copies their trades at $1 each, auto-redeems winning positions, auto-resumes paused subscriptions, and displays everything on a local dashboard.

## System Architecture

| Component | Details |
|---|---|
| **Bot** | `bot.py` — polls every 30s, logs trades, auto-redeems, auto-resumes |
| **Dashboard** | `dashboard.py` (Flask) — http://localhost:5050 |
| **Frontend** | `templates/index.html` — dark mode, Chart.js, period filters |
| **Bot log** | `/tmp/bot2.log` |
| **Dashboard log** | `/tmp/dashboard.log` |
| **Trade log** | `trades.json` |
| **Bot LaunchAgent** | `fi.bullpen.bot2` |
| **Dashboard LaunchAgent** | `fi.bullpen.dashboard` |

## Checking Status

```bash
# Full health check
launchctl list fi.bullpen.bot2        # Bot LaunchAgent (look for PID)
launchctl list fi.bullpen.dashboard   # Dashboard LaunchAgent (look for PID)
tail -20 /tmp/bot2.log               # Recent bot activity
curl http://localhost:5050/api/stats  # Dashboard API check
bullpen tracker copy list --output json  # Subscription statuses
bullpen portfolio balances            # Wallet balance
```

## Common Issues & Fixes

### Bot not picking up new trades
1. Check `tail -20 /tmp/bot2.log` — look for "bullpen exited 1"
2. If auth error → run `bullpen login`
3. Check subscriptions: `bullpen tracker copy list --output json` — any "AutoPaused"?
4. Resume paused subs: `bullpen tracker copy resume <address>`

### Dashboard not loading (http://localhost:5050)
```bash
launchctl unload ~/Library/LaunchAgents/fi.bullpen.dashboard.plist
sleep 2
launchctl load ~/Library/LaunchAgents/fi.bullpen.dashboard.plist
```

### Subscriptions AutoPaused (insufficient balance)
- Bot auto-resumes them every 30s cycle
- Check balance: `bullpen portfolio balances`
- Manually resume all: run the resume loop in traders_subscriptions.md

### All bullpen commands failing ("exited 1")
```bash
bullpen login   # Re-authenticate — takes 30 seconds
```

## Restarting Services

```bash
# Restart bot
launchctl unload ~/Library/LaunchAgents/fi.bullpen.bot2.plist
launchctl load ~/Library/LaunchAgents/fi.bullpen.bot2.plist

# Restart dashboard
launchctl unload ~/Library/LaunchAgents/fi.bullpen.dashboard.plist
launchctl load ~/Library/LaunchAgents/fi.bullpen.dashboard.plist
```

## Tracked Traders (10)

| Nickname | Wallet |
|---|---|
| elkmonkey | 0xead152b855effa6b5b5837f53b24c0756830c76a |
| swisstony | 0x204f72f35326db932158cba6adff0b9a1da95e14 |
| RN1 | 0x2005d16a84ceefa912d4e380cd32e7ff827875ea |
| sovereign2013 | 0xee613b3fc183ee44f9da9c05f53e2da107e3debf |
| kch123 | 0x6a72f61820b26b1fe4d956e17b6dc2a1ea3033ee |
| texaskid | 0xc8075693f48668a264b9fa313b47f52712fcc12b |
| CarlosMC | 0x777d9f00c2b4f7b829c9de0049ca3e707db05143 |
| gatorr | 0x93abbc022ce98d6f45d4444b594791cc4b7a9723 |
| Countryside | 0xbddf61af533ff524d27154e589d2d7a81510c684 |
| beachboy4 | 0xc2e7800b5af46e6093872b177b7a5e7f0563be51 |

## Subscription Config
- $1 fixed per trade, Auto execution, MirrorSells exit
- Price range: 5¢–95¢ (skips near-certain outcomes)
- Max trade size filter: $100,000 (no effective cap)

## Changing Copy Amount or Traders

Edit in `bot.py`:
```python
# Top of file — change $1 to any amount per trade
# (also update each subscription via bullpen tracker copy edit)
```

Add a new trader:
```bash
bullpen tracker copy start <ADDRESS> --amount 1 --execution-mode auto \
  --exit-behavior mirror-sells --price-min 0.05 --price-max 0.95 \
  --max-trade-size 100000 --slippage 3 --nickname "TraderName"
```

Remove a trader:
```bash
bullpen tracker copy delete <ADDRESS> --yes
```

## P&L Notes
- **Realized P&L**: computed from `bullpen polymarket activity --type redeem` (redemption payouts minus cost basis)
- **Unrealized P&L**: live from `bullpen polymarket positions`
- **`bullpen portfolio pnl` returns $0** — known Bullpen API bug, do not use

## Upgrading Bullpen
```bash
bullpen upgrade   # updates CLI + auto-updates skill files
```
