# Roblox Username Webhook Scanner

This project is a **Discord webhook scanner** (not a Discord bot account). It checks Roblox username availability and posts alerts directly to a Discord webhook URL.

## What it does

- Scans random Roblox usernames of length **3-5** continuously.
- Tracks status over time and only alerts when a username flips from **taken → available**.
- Supports a custom watched list (`WATCH_USERNAMES`) for specific usernames (any length).
- Supports one-shot startup checks (`CHECK_USERNAMES`) and sends the results to the webhook.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Environment variables

Required:

- `DISCORD_WEBHOOK_URL`: your Discord webhook URL.

Optional:

- `POLL_INTERVAL_SECONDS`: seconds between scans (default: `120`)
- `DISCOVERY_BATCH_SIZE`: random 3-5 char names per scan (default: `120`)
- `WATCH_USERNAMES`: comma-separated watched usernames (any length)
- `CHECK_USERNAMES`: comma-separated usernames to check once at startup

Example:

```bash
export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."
export POLL_INTERVAL_SECONDS="120"
export DISCOVERY_BATCH_SIZE="150"
export WATCH_USERNAMES="builderman,roblox,testname123"
export CHECK_USERNAMES="abcd,exampleuser"
```

## Run

```bash
python bot.py
```

## Discord webhook setup

1. In Discord, open **Server Settings → Integrations → Webhooks**.
2. Click **New Webhook**.
3. Choose the target channel for alerts.
4. Copy the webhook URL and set `DISCORD_WEBHOOK_URL`.

## Notes

- This is sampling-based discovery for 3-5 character usernames, not exhaustive brute force.
- Roblox does not provide a public reason for why a username became available; this tool only detects transitions.
- State is persisted in `watch_state.json`.
