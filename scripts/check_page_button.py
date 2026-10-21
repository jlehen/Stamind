"""Step 0 of DESIGN_short_messages.md (§15): does a button under a message open a page in the
bot's chat, with the page's address intact after the `#`?

Sends one message to the first allowed chat of the instance STAMIND_CONFIG names, through
that instance's bot, with two buttons under it. Both open the Calendar page, which draws
nothing unless it can read the snapshot after its `#`. One carries the Calendar's whole
address, as the keyboard does (up to 5 KB); the other a short one, the size a "Tell me more"
button needs. Tap both on the phone: a Calendar with this week in it means the check passed.

    STAMIND_CONFIG=config.proto.yaml venv/bin/python scripts/check_page_button.py

Reads the database and writes nothing.
"""
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stamind import calendar_days, clock, runtime  # noqa: E402
from stamind.cli.render import calendar_page  # noqa: E402
from stamind.config import config  # noqa: E402
from stamind.page_files import sync as page_files  # noqa: E402

# About what a "Tell me more" button carries after the page's own address (§15).
SHORT_BYTES = 150


def addresses():
    """The Calendar's whole address and a short one, as the keyboard would build them now."""
    today = clock.today_str()
    start, end = calendar_page.window(today)
    cal = calendar_days.gather(runtime.db, start, end, today)
    now = clock.now()
    storage = page_files.button_params(runtime.db)
    whole = calendar_page.calendar_url(cal, now, storage)
    payload, sheets = calendar_page.snapshot(cal, now)
    short = f"{calendar_page.PAGE_URL}#c={calendar_page.fit(payload, sheets, SHORT_BYTES)}"
    return whole, short


def send(token, chat_id, text, buttons):
    """sendMessage with one button per row, each opening a page. Telegram's answer."""
    body = {
        "chat_id": chat_id, "text": text,
        "reply_markup": {"inline_keyboard": [
            [{"text": label, "web_app": {"url": url}}] for label, url in buttons
        ]},
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


def main():
    token = config.telegram_bot_token
    chats = config.telegram_allowed_chat_ids
    if not token or not chats:
        sys.exit("No bot token or no allowed chat in this config.")
    whole, short = addresses()
    print(f"Whole address: {len(whole)} characters. Short address: {len(short)} characters.")
    text = (
        "Step 0 of the short messages: tap each button below. Each should open the Calendar "
        "with this week in it."
    )
    answer = send(token, chats[0], text, [
        (f"📅 Whole address ({len(whole)})", whole),
        (f"📅 Short address ({len(short)})", short),
    ])
    if answer.get("ok"):
        print("Sent. Tap both buttons on the phone.")
        return
    # The whole address may be what Telegram refuses; the short one is what the design needs.
    print(f"Telegram refused the two together: {answer.get('description')}")
    answer = send(token, chats[0], text, [(f"📅 Short address ({len(short)})", short)])
    print(f"The short address alone: {'sent' if answer.get('ok') else answer.get('description')}")


if __name__ == "__main__":
    main()
