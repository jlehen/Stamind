"""Step 0 of DESIGN_short_messages.md (§15): does a button under a message open a page in the
bot's chat, with the page's address intact after the `#`?

Sends one message to the first allowed chat of the instance STAMIND_CONFIG names, through
that instance's bot, with one button under it. The button opens the Calendar page, which
draws nothing unless it can read the snapshot after its `#`. The snapshot comes from a
throwaway empty database, so no athlete's database is opened; the address is about the size
a "Tell me more" button carries. Tap it on the phone: a Calendar grid of this month means
the check passed, a blank page or an error that it failed.

    STAMIND_CONFIG=config.proto.yaml venv/bin/python scripts/check_page_button.py
"""
import json
import os
import sys
import tempfile
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stamind import calendar_days, clock, runtime  # noqa: E402
from stamind.cli.render import calendar_page  # noqa: E402
from stamind.config import config  # noqa: E402
from stamind.db import Database  # noqa: E402


def address() -> str:
    """The Calendar's address as the keyboard would build it, over an empty database. Bound
    as `runtime.db` too, so nothing opens the instance's own (the clock reads it)."""
    with tempfile.TemporaryDirectory() as scratch:
        runtime.db = Database(db_path=os.path.join(scratch, "empty.db"))
        today = clock.today_str()
        start, end = calendar_page.window(today)
        cal = calendar_days.gather(runtime.db, start, end, today)
        return calendar_page.calendar_url(cal, clock.now())


def send(token: str, chat_id: int, text: str, label: str, url: str) -> dict:
    """sendMessage with one button under it that opens a page. Telegram's answer."""
    body = {
        "chat_id": chat_id, "text": text,
        "reply_markup": {"inline_keyboard": [[{"text": label, "web_app": {"url": url}}]]},
    }
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=json.dumps(body).encode(), headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as reply:
            return json.load(reply)
    except urllib.error.HTTPError as e:
        return json.load(e)


def main() -> None:
    token = config.telegram_bot_token
    chats = config.telegram_allowed_chat_ids
    if not token or not chats:
        sys.exit("No bot token or no allowed chat in this config.")
    url = address()
    print(f"The address: {len(url)} characters.")
    answer = send(
        token, chats[0],
        "Step 0 of the short messages: tap the button below. It should open the Calendar "
        "with this month's grid.",
        "📅 Open the Calendar", url,
    )
    if answer.get("ok"):
        print("Sent. Tap the button on the phone.")
        return
    print(f"Telegram refused it: {answer.get('description')}")


if __name__ == "__main__":
    main()
