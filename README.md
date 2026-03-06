# Roblox Username Discord Bot

Discord bot that checks Roblox usernames and monitors watched names for a **taken → available** transition.

## Features

- `!check <name>`: checks if a Roblox username is currently available (any length; must be alphanumeric).
- `!watch <name>`: adds a username (1-4 chars) to a channel-specific watchlist.
- `!unwatch <name>`: removes username from watchlist.
- `!watchlist`: lists watched usernames for the current channel.
- Background polling alerts when a watched name flips from taken to available.
- Automatic discovery scanner checks random 3-5 character usernames and pings configured Discord channels when previously taken names become available.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Set environment variables:

- `DISCORD_TOKEN`: Discord bot token (required)
- `POLL_INTERVAL_SECONDS`: watchlist polling interval seconds (optional, default: 300)
- `DISCOVERY_INTERVAL_SECONDS`: auto-scanner interval seconds (optional, default: 120)
- `DISCOVERY_BATCH_SIZE`: usernames sampled per scan tick (optional, default: 120)
- `AUTO_PING_CHANNEL_IDS`: comma-separated Discord channel IDs for automatic 3-5 char availability pings

Example:

```bash
export DISCORD_TOKEN="your-token"
export AUTO_PING_CHANNEL_IDS="123456789012345678,234567890123456789"
export DISCOVERY_INTERVAL_SECONDS="120"
export DISCOVERY_BATCH_SIZE="150"
```

## Run

```bash
python bot.py
```

## Add the bot to your Discord server

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications) and click **New Application**.
2. Open your app, then go to **Bot** in the left sidebar.
3. Click **Reset Token** (or **Copy**) and save it as your `DISCORD_TOKEN` environment variable.
4. In **Privileged Gateway Intents**, enable:
   - **Message Content Intent**
5. Go to **OAuth2** → **URL Generator** and select scopes:
   - `bot`
   - `applications.commands`
6. In **Bot Permissions**, select at least:
   - `View Channels`
   - `Send Messages`
   - `Read Message History`
   - `Mention Everyone` (optional, needed if you want `@here` to notify)
7. Copy the generated URL, open it in your browser, and invite the bot to your server.

## Notes

- Roblox does not provide a direct public reason code saying exactly why a username became available; the bot detects availability transitions over time.
- Automatic discovery is sampling-based (random 3-5 character candidates), not exhaustive.
- State is stored in `watch_state.json` in the current working directory.
