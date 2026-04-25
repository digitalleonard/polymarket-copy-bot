# 🤖 Polymarket Copy Bot

Automatically copy the trades of 10 top-performing Polymarket prediction market traders — $1 per trade, fully automated, with a live local dashboard.

Built on [Bullpen CLI](https://cli.bullpen.fi) • Runs on macOS • Manages itself 24/7

---

## What It Does

- **Copies trades** from 10 elite Polymarket traders the moment they trade
- **Auto-redeems** winning positions so your balance is always available
- **Auto-resumes** subscriptions if they pause due to low balance
- **Local dashboard** at `http://localhost:5050` — live P&L, win rate, trade history
- **Runs in the background** — survives Mac restarts via macOS LaunchAgents
- **Claude Code integration** — open this folder in Claude Code and get AI-powered help managing everything

---

## Step-by-Step Setup Guide

Follow these steps in order. The whole process takes about 10 minutes.

---

### Step 1 — Create a Bullpen Account

Bullpen is the trading platform that powers the copy trading. You need a free account.

1. Go to **[https://bullpen.fi/@digitalleonard](https://bullpen.fi/@digitalleonard)** to sign up
2. Connect your wallet or create a new one — Bullpen will set up a Polymarket-compatible wallet for you
3. Complete any verification steps required

> 💡 Using the link above supports the creator of this bot at no cost to you.

---

### Step 2 — Install Homebrew (if you don't have it)

Homebrew is a package manager for macOS. Skip this step if you already have it.

1. Open **Terminal** (press `Cmd + Space`, type `Terminal`, hit Enter)
2. Paste this command and press Enter:
```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```
3. Follow the on-screen instructions (it may ask for your Mac password)
4. When it's done, close and reopen Terminal

---

### Step 3 — Install Python 3

1. In Terminal, run:
```bash
brew install python3
```
2. Wait for it to finish, then confirm it worked:
```bash
python3 --version
```
You should see something like `Python 3.x.x`

---

### Step 4 — Install Bullpen CLI

1. In Terminal, run:
```bash
brew install BullpenFi/tap/bullpen
```
2. Confirm it installed:
```bash
bullpen --version
```
You should see `bullpen 0.1.x`

---

### Step 5 — Install Claude Code (optional but recommended)

Claude Code is an AI coding assistant that gives you a built-in helper for managing this bot. It's free to try.

1. Install it:
```bash
brew install claude-code
```
2. Or download it from [claude.ai/code](https://claude.ai/code)

> 💡 With Claude Code, you can just ask *"Is the bot running?"* or *"Why aren't trades showing?"* and it will diagnose and fix things for you automatically.

---

### Step 6 — Clone and Install the Bot

1. In Terminal, run these commands one by one:
```bash
git clone https://github.com/digitalleonard/polymarket-copy-bot
cd polymarket-copy-bot
bash setup.sh
```

2. The setup script will:
   - ✅ Check all dependencies
   - ✅ Install Flask (the dashboard framework)
   - ✅ Create the background service files
   - ✅ Start the bot and dashboard automatically
   - ✅ Walk you through logging into Bullpen

3. When the script asks you to log in to Bullpen, it will show you a **code** and a **URL**:
   - Open the URL in your browser
   - Enter the code
   - Done — you're authenticated

---

### Step 7 — Fund Your Wallet

The bot copies trades at **$1 per trade**. You need USDC.e (USD Coin) in your Polymarket wallet to place copy trades.

1. Find your wallet address:
```bash
bullpen portfolio balances
```
2. Copy the **Polymarket wallet address** shown
3. Go to [polymarket.com](https://polymarket.com) → deposit funds to that address
4. A starting balance of **$50–$100** is recommended (covers 50–100 copy trades before needing a top-up)

> 💡 The bot automatically redeems your winning positions back into USDC so your balance replenishes itself over time.

---

### Step 8 — Open the Dashboard

1. Open your browser and go to: **[http://localhost:5050](http://localhost:5050)**
2. You should see the live dashboard with:
   - Bot status (green dot = running)
   - Trade history
   - P&L tracking
   - Charts and filters

That's it — the bot is now running 24/7, copying trades automatically. 🎉

---

## Dashboard Overview

| Card | What It Shows |
|---|---|
| Total Trades | All copy signals received |
| Completed | Successfully copied trades |
| Win Rate | Completed vs failed (excluding skipped) |
| Capital Deployed | Total USDC spent on copies |
| Unrealized P&L | Live value of open positions |
| Realized P&L | USDC returned from won/redeemed positions |

Filter by: **Today / Last 7 Days / Last 30 Days / Last 90 Days / All Time**

The **Stop/Start button** controls the bot directly. When the bot is running you'll see a pulsing green dot.

---

## Tracked Traders

These 10 traders were selected based on weekly PnL performance and verified activity on Polymarket:

| Trader | Markets |
|---|---|
| elkmonkey | Sports, politics, crypto |
| swisstony | Sports (very active) |
| RN1 | Mixed |
| sovereign2013 | Mixed |
| kch123 | Mixed |
| texaskid | Sports |
| CarlosMC | Mixed |
| gatorr | Sports |
| Countryside | Mixed |
| beachboy4 | Mixed |

To swap out traders, see [Customising Traders](#customising-traders) below.

---

## Customising Traders

**Add a new trader:**
```bash
bullpen tracker copy start <WALLET_ADDRESS> \
  --amount 1 \
  --execution-mode auto \
  --exit-behavior mirror-sells \
  --price-min 0.05 --price-max 0.95 \
  --max-trade-size 100000 \
  --slippage 3 \
  --nickname "TraderName"
```

**Remove a trader:**
```bash
bullpen tracker copy delete <WALLET_ADDRESS> --yes
```

**Change copy amount** (e.g. $2 per trade):
```bash
bullpen tracker copy edit <WALLET_ADDRESS> --fixed-amount 2
```

**Find top traders to copy this week:**
```bash
bullpen polymarket data leaderboard --period week --limit 20
```

---

## How to Check Everything Is Working

```bash
# Is the bot running?
launchctl list fi.bullpen.bot2

# Is the dashboard running?
launchctl list fi.bullpen.dashboard

# What has the bot been doing?
tail -30 /tmp/bot2.log

# What's my wallet balance?
bullpen portfolio balances

# Are all subscriptions active?
bullpen tracker copy list
```

---

## Troubleshooting

### Bot stopped copying trades
Run `tail -20 /tmp/bot2.log`. If you see `bullpen exited 1`:
```bash
bullpen login   # re-authenticate (token expires periodically, takes 30 seconds)
```

### Subscriptions show "AutoPaused"
Your wallet balance hit $0. The bot auto-resumes them after the next winning redemption. To manually fix right now:
```bash
bullpen tracker copy list                  # see which are paused
bullpen tracker copy resume <ADDRESS>      # resume each paused one
```

### Dashboard not loading at http://localhost:5050
```bash
launchctl unload ~/Library/LaunchAgents/fi.bullpen.dashboard.plist
sleep 2
launchctl load ~/Library/LaunchAgents/fi.bullpen.dashboard.plist
```

### How much USDC do I need?
The bot copies at $1 per trade. With 10 active traders you can see 10–50+ signals per day. A starting balance of **$50–$100** gives comfortable headroom. Winning positions are automatically redeemed back into your balance. Top up anytime via [polymarket.com](https://polymarket.com).

### The bot is running but I see mostly "Failed" trades
This usually means your balance is low. Check:
```bash
bullpen portfolio balances
```
Deposit more USDC.e to your Polymarket wallet to resume completing trades.

---

## Upgrading Bullpen CLI

```bash
bullpen upgrade   # updates the CLI and all skill files automatically
```

---

## Uninstalling

```bash
bash uninstall.sh
```

This stops the bot and dashboard, removes the background services, and cleans up. Your `trades.json` history file stays in the folder.

---

## Using with Claude Code

Open this folder in Claude Code — it includes a built-in AI skill that already knows the entire system. Just ask naturally:

> *"Check if the bot is running"*
> *"Why aren't new trades showing up?"*
> *"Show me my P&L for this week"*
> *"Resume any paused subscriptions"*
> *"Which traders are performing best?"*

Claude will diagnose issues, run the right commands, and fix things automatically.

---

## License

MIT — use freely, modify as you like.

---

Built with [Bullpen CLI](https://cli.bullpen.fi) • [Discord](https://discord.com/invite/bullpen)
