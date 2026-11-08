"""Register (or update) the Webex messages/created webhooks for this bot.

Usage:
    WEBEX_BOT_TOKEN=... python scripts/register_webhooks.py https://example.trycloudflare.com

It finds the rooms named "IPA2026" and "IPA2026 Exam Room" that the bot has
joined, removes this script's previous webhooks and creates one webhook per
room whose targetUrl ends in /webhook. Run it again whenever the tunnel URL
changes.
"""

import os
import sys

import requests

API = "https://webexapis.com/v1"
ROOM_TITLES = ("IPA2026", "IPA2026 Exam Room")
WEBHOOK_NAME_PREFIX = "ipa2026-bot"


def main(base_url):
    token = os.environ.get("WEBEX_BOT_TOKEN")
    if not token:
        sys.exit("WEBEX_BOT_TOKEN is not set")
    headers = {"Authorization": f"Bearer {token}"}
    target = base_url.rstrip("/")
    if not target.endswith("/webhook"):
        target += "/webhook"

    def call(method, path, **kwargs):
        response = requests.request(
            method, f"{API}{path}", headers=headers, timeout=10, **kwargs
        )
        response.raise_for_status()
        return response.json() if response.content else {}

    for hook in call("GET", "/webhooks")["items"]:
        if hook["name"].startswith(WEBHOOK_NAME_PREFIX):
            call("DELETE", f"/webhooks/{hook['id']}")

    rooms = [r for r in call("GET", "/rooms")["items"] if r["title"] in ROOM_TITLES]
    if not rooms:
        sys.exit("bot is not a member of the IPA2026 rooms")
    for room in rooms:
        call(
            "POST",
            "/webhooks",
            json={
                "name": f"{WEBHOOK_NAME_PREFIX}-{room['title']}",
                "targetUrl": target,
                "resource": "messages",
                "event": "created",
                "filter": f"roomId={room['id']}",
            },
        )
        print(f"registered {room['title']} -> {target}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
