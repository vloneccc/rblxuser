import asyncio
import json
import logging
import os
import random
import string
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import aiohttp
import discord
from discord.ext import commands, tasks


logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger("roblox-username-bot")

ROBLOX_USERNAMES_ENDPOINT = "https://users.roblox.com/v1/usernames/users"
STATE_FILE = Path("watch_state.json")
ALPHABET = string.ascii_lowercase + string.digits


@dataclass
class UsernameStatus:
    username: str
    available: bool
    reason: str


class RobloxUsernameChecker:
    def __init__(self, session: aiohttp.ClientSession):
        self.session = session

    async def check_username(self, username: str) -> UsernameStatus:
        payload = {
            "usernames": [username],
            "excludeBannedUsers": False,
        }

        async with self.session.post(ROBLOX_USERNAMES_ENDPOINT, json=payload, timeout=15) as response:
            response.raise_for_status()
            data = await response.json()

        user_data = data.get("data", [])
        if not user_data:
            return UsernameStatus(username=username, available=True, reason="No account found")

        entry = user_data[0]
        if entry.get("id"):
            return UsernameStatus(username=username, available=False, reason="Username in use")

        return UsernameStatus(username=username, available=True, reason=entry.get("name", "Available"))

    async def bulk_check(self, usernames: List[str]) -> List[UsernameStatus]:
        usernames = [u for u in usernames if u]
        if not usernames:
            return []

        payload = {
            "usernames": usernames,
            "excludeBannedUsers": False,
        }

        async with self.session.post(ROBLOX_USERNAMES_ENDPOINT, json=payload, timeout=20) as response:
            response.raise_for_status()
            data = await response.json()

        results: Dict[str, UsernameStatus] = {}
        for entry in data.get("data", []):
            name = entry.get("requestedUsername") or entry.get("name") or ""
            if not name:
                continue
            if entry.get("id"):
                results[name.lower()] = UsernameStatus(username=name, available=False, reason="Username in use")
            else:
                results[name.lower()] = UsernameStatus(username=name, available=True, reason="No account found")

        output: List[UsernameStatus] = []
        for username in usernames:
            lower = username.lower()
            output.append(results.get(lower, UsernameStatus(username=username, available=True, reason="No account found")))

        return output


class WatchStateStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> Dict[str, Dict[str, Dict[str, str]]]:
        if not self.path.exists():
            return {"watch_channels": {}, "scanner": {}}

        with self.path.open("r", encoding="utf-8") as f:
            raw = json.load(f)

        # Backward-compatible load from old format (channel_id -> username state)
        if "watch_channels" not in raw:
            return {
                "watch_channels": raw,
                "scanner": {},
            }

        raw.setdefault("watch_channels", {})
        raw.setdefault("scanner", {})
        return raw

    def save(self, state: Dict[str, Dict[str, Dict[str, str]]]) -> None:
        with self.path.open("w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)


intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
store = WatchStateStore(STATE_FILE)


class UsernameWatchCog(commands.Cog):
    def __init__(self, discord_bot: commands.Bot):
        self.bot = discord_bot
        self.state = store.load()
        self.session: Optional[aiohttp.ClientSession] = None
        self.checker: Optional[RobloxUsernameChecker] = None
        self.poll_interval_seconds = int(os.getenv("POLL_INTERVAL_SECONDS", "300"))
        self.discovery_interval_seconds = int(os.getenv("DISCOVERY_INTERVAL_SECONDS", "120"))
        self.discovery_batch_size = int(os.getenv("DISCOVERY_BATCH_SIZE", "120"))
        self.auto_ping_channels = [
            c.strip() for c in os.getenv("AUTO_PING_CHANNEL_IDS", "").split(",") if c.strip()
        ]

    async def cog_load(self) -> None:
        self.session = aiohttp.ClientSession()
        self.checker = RobloxUsernameChecker(self.session)

        self.poll_watched_names.change_interval(seconds=self.poll_interval_seconds)
        self.poll_watched_names.start()

        self.scan_newly_available_names.change_interval(seconds=self.discovery_interval_seconds)
        self.scan_newly_available_names.start()

    async def cog_unload(self) -> None:
        self.poll_watched_names.cancel()
        self.scan_newly_available_names.cancel()
        if self.session:
            await self.session.close()

    def _validate_basic_username(self, username: str) -> Tuple[bool, str]:
        username = username.strip()
        if len(username) < 1:
            return False, "Username cannot be empty."
        if not username.isalnum():
            return False, "Usernames must be alphanumeric."
        return True, ""

    def _validate_short_watch_username(self, username: str) -> Tuple[bool, str]:
        username = username.strip()
        if len(username) < 1 or len(username) > 4:
            return False, "Watchlist supports 1-4 character usernames."
        if not username.isalnum():
            return False, "Usernames must be alphanumeric."
        return True, ""

    def _scanner_state(self) -> Dict[str, str]:
        return self.state.setdefault("scanner", {})

    def _watch_channels(self) -> Dict[str, Dict[str, str]]:
        return self.state.setdefault("watch_channels", {})

    def _random_candidate(self) -> str:
        name_len = random.choice([3, 4, 5])
        return "".join(random.choices(ALPHABET, k=name_len))

    @commands.command(name="check")
    async def check(self, ctx: commands.Context, username: str) -> None:
        valid, message = self._validate_basic_username(username)
        if not valid:
            await ctx.send(message)
            return

        assert self.checker is not None
        status = await self.checker.check_username(username)
        emoji = "✅" if status.available else "❌"
        await ctx.send(f"{emoji} `{status.username}` => {'available' if status.available else 'taken'} ({status.reason})")

    @commands.command(name="watch")
    async def watch(self, ctx: commands.Context, username: str) -> None:
        valid, message = self._validate_short_watch_username(username)
        if not valid:
            await ctx.send(message)
            return

        channel_id = str(ctx.channel.id)
        username_key = username.lower()
        channels = self._watch_channels()
        channel_watch = channels.setdefault(channel_id, {})

        if username_key in channel_watch:
            await ctx.send(f"Already watching `{username}` in this channel.")
            return

        channel_watch[username_key] = "unknown"
        store.save(self.state)
        await ctx.send(f"👀 Now watching `{username}`. I will alert when it flips from taken to available.")

    @commands.command(name="unwatch")
    async def unwatch(self, ctx: commands.Context, username: str) -> None:
        channel_id = str(ctx.channel.id)
        username_key = username.lower()
        channels = self._watch_channels()
        channel_watch = channels.get(channel_id, {})

        if username_key not in channel_watch:
            await ctx.send(f"`{username}` is not being watched here.")
            return

        del channel_watch[username_key]
        if not channel_watch:
            channels.pop(channel_id, None)
        store.save(self.state)
        await ctx.send(f"Stopped watching `{username}`.")

    @commands.command(name="watchlist")
    async def watchlist(self, ctx: commands.Context) -> None:
        channel_id = str(ctx.channel.id)
        channel_watch = self._watch_channels().get(channel_id, {})
        if not channel_watch:
            await ctx.send("No usernames are being watched in this channel.")
            return

        names = ", ".join(sorted(channel_watch.keys()))
        await ctx.send(f"Watching: {names}")

    @tasks.loop(seconds=300)
    async def poll_watched_names(self) -> None:
        if not self._watch_channels() or not self.checker:
            return

        channels = self._watch_channels()
        for channel_id, usernames in list(channels.items()):
            if not usernames:
                continue
            channel = self.bot.get_channel(int(channel_id))
            if channel is None:
                continue

            for username, previous in list(usernames.items()):
                status = await self.checker.check_username(username)
                current = "available" if status.available else "taken"

                if previous == "taken" and current == "available":
                    now = datetime.now(timezone.utc).isoformat()
                    await channel.send(
                        f"🚨 `{username}` just became available! ({now})\n"
                        "This can happen when accounts are deleted or banned/renamed."
                    )

                usernames[username] = current

        store.save(self.state)

    @tasks.loop(seconds=120)
    async def scan_newly_available_names(self) -> None:
        if not self.checker or not self.auto_ping_channels:
            return

        scanner = self._scanner_state()
        candidates: List[str] = []
        while len(candidates) < self.discovery_batch_size:
            candidate = self._random_candidate()
            if candidate not in candidates:
                candidates.append(candidate)

        statuses = await self.checker.bulk_check(candidates)
        flipped_available: List[str] = []

        for status in statuses:
            username = status.username.lower()
            current = "available" if status.available else "taken"
            previous = scanner.get(username)
            if previous == "taken" and current == "available":
                flipped_available.append(status.username)
            scanner[username] = current

        if flipped_available:
            message = (
                "@here 🚨 Newly available Roblox usernames detected (3-5 chars): "
                + ", ".join(f"`{u}`" for u in sorted(set(flipped_available)))
            )
            for channel_id in self.auto_ping_channels:
                channel = self.bot.get_channel(int(channel_id))
                if channel is not None:
                    await channel.send(message)

        store.save(self.state)

    @poll_watched_names.before_loop
    async def before_poll(self) -> None:
        await self.bot.wait_until_ready()

    @scan_newly_available_names.before_loop
    async def before_scan(self) -> None:
        await self.bot.wait_until_ready()


@bot.event
async def on_ready() -> None:
    LOGGER.info("Logged in as %s", bot.user)


async def main() -> None:
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN env var is required")

    await bot.add_cog(UsernameWatchCog(bot))
    await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())
