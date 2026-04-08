import asyncio
import json
import logging
import os
import random
import string
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

import aiohttp


logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger("roblox-username-webhook")

ROBLOX_USERNAMES_ENDPOINT = "https://users.roblox.com/v1/usernames/users"
STATE_FILE = Path("watch_state.json")
ALPHABET = string.ascii_lowercase + string.digits


@dataclass
class UsernameStatus:
    username: str
    available: bool


class WatchStateStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> Dict[str, Dict[str, str]]:
        if not self.path.exists():
            return {"watched": {}, "scanner": {}}

        with self.path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        data.setdefault("watched", {})
        data.setdefault("scanner", {})
        return data

    def save(self, state: Dict[str, Dict[str, str]]) -> None:
        with self.path.open("w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)


class RobloxWebhookScanner:
    def __init__(self) -> None:
        self.webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
        if not self.webhook_url:
            raise RuntimeError("DISCORD_WEBHOOK_URL is required")

        self.poll_interval_seconds = int(os.getenv("POLL_INTERVAL_SECONDS", "120"))
        self.discovery_batch_size = int(os.getenv("DISCOVERY_BATCH_SIZE", "120"))
        self.watched_usernames = self._parse_csv_env("WATCH_USERNAMES")
        self.manual_check_usernames = self._parse_csv_env("CHECK_USERNAMES")

        self.store = WatchStateStore(STATE_FILE)
        self.state = self.store.load()
        self.session: aiohttp.ClientSession | None = None

    @staticmethod
    def _parse_csv_env(env_key: str) -> List[str]:
        raw = os.getenv(env_key, "")
        return [v.strip() for v in raw.split(",") if v.strip()]

    async def check_usernames(self, usernames: List[str]) -> List[UsernameStatus]:
        if not usernames:
            return []

        payload = {
            "usernames": usernames,
            "excludeBannedUsers": False,
        }

        assert self.session is not None
        async with self.session.post(ROBLOX_USERNAMES_ENDPOINT, json=payload, timeout=20) as response:
            response.raise_for_status()
            data = await response.json()

        taken_map: Dict[str, bool] = {}
        for entry in data.get("data", []):
            requested = (entry.get("requestedUsername") or entry.get("name") or "").strip()
            if not requested:
                continue
            taken_map[requested.lower()] = bool(entry.get("id"))

        statuses: List[UsernameStatus] = []
        for username in usernames:
            is_taken = taken_map.get(username.lower(), False)
            statuses.append(UsernameStatus(username=username, available=not is_taken))
        return statuses

    def _random_candidate(self) -> str:
        length = random.choice([3, 4, 5])
        return "".join(random.choices(ALPHABET, k=length))

    async def _send_webhook(self, content: str) -> None:
        assert self.session is not None
        payload = {"content": content}
        async with self.session.post(self.webhook_url, json=payload, timeout=15) as response:
            response.raise_for_status()

    async def run_manual_checks(self) -> None:
        if not self.manual_check_usernames:
            return

        statuses = await self.check_usernames(self.manual_check_usernames)
        lines = [
            f"`{s.username}`: {'AVAILABLE ✅' if s.available else 'TAKEN ❌'}"
            for s in statuses
        ]
        await self._send_webhook("Manual username check results:\n" + "\n".join(lines))

    async def scan_once(self) -> None:
        scanner_state = self.state["scanner"]
        watched_state = self.state["watched"]

        # Always scan random 3-5 character usernames.
        random_candidates: List[str] = []
        while len(random_candidates) < self.discovery_batch_size:
            candidate = self._random_candidate()
            if candidate not in random_candidates:
                random_candidates.append(candidate)

        # Include explicitly watched usernames (any length).
        combined = list(dict.fromkeys(random_candidates + self.watched_usernames))
        statuses = await self.check_usernames(combined)

        watched_keys = {w.lower() for w in self.watched_usernames}
        newly_available_random: List[str] = []
        newly_available_watched: List[str] = []

        for status in statuses:
            current = "available" if status.available else "taken"
            key = status.username.lower()

            if key in watched_keys:
                previous = watched_state.get(key)
                if previous == "taken" and current == "available":
                    newly_available_watched.append(status.username)
                watched_state[key] = current
            else:
                previous = scanner_state.get(key)
                if previous == "taken" and current == "available":
                    newly_available_random.append(status.username)
                scanner_state[key] = current

        if newly_available_watched or newly_available_random:
            now = datetime.now(timezone.utc).isoformat()
            parts = [f"@here 🚨 Newly available Roblox usernames detected ({now})"]

            if newly_available_watched:
                parts.append("Watched list: " + ", ".join(f"`{u}`" for u in sorted(set(newly_available_watched))))

            if newly_available_random:
                parts.append("Random 3-5 char scan: " + ", ".join(f"`{u}`" for u in sorted(set(newly_available_random))))

            await self._send_webhook("\n".join(parts))

        self.store.save(self.state)

    async def run_forever(self) -> None:
        async with aiohttp.ClientSession() as session:
            self.session = session
            await self.run_manual_checks()
            LOGGER.info("Webhook scanner started. Poll interval: %s sec", self.poll_interval_seconds)

            while True:
                try:
                    await self.scan_once()
                except Exception as exc:  # noqa: BLE001
                    LOGGER.exception("Scan failed: %s", exc)
                await asyncio.sleep(self.poll_interval_seconds)


async def main() -> None:
    scanner = RobloxWebhookScanner()
    await scanner.run_forever()


if __name__ == "__main__":
    asyncio.run(main())
