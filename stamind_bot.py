"""Stamind Telegram front-end — the launcher.

A chat shim over the existing CLI: each incoming message becomes a Stamind command
line, run through ``stamind_cli.py`` as a subprocess. A message that starts with a
slash is that command line as typed; a keyboard label runs a fixed one, and any other
text goes through the intent router (DESIGN_bot_simple_frontend.md). Driving the real
CLI keeps the bot in permanent parity with every command/flag the CLI gains, and
isolates each invocation.

Interactive commands work over chat because the CLI is launched with
``STAMIND_FRONTEND=json``: its prompt broker (``stamind.prompt``) emits a
sentinel-framed JSON request instead of blocking on ``input()``, and the bot renders it
as an inline keyboard and writes the answer back to stdin. One in-flight command per
chat, state in ``stamind.chat.runner.Session``, a per-prompt ``nonce`` against stale
taps.

This file is only the entry point ``sm-bot`` runs. The bot itself is ``ChatBot`` in
``stamind/chat/app.py``, and the rest of ``stamind/chat/`` holds what one message
means, what the bot draws, what it sends back, and when the scheduler fires. The telegram
library is named in one file there, ``chat/telegram_api.py``, and imported only when it is
called.

``sm-bot`` supervises this process and relaunches it on
``stamind.chat.runner.RESTART_EXIT_CODE``, which is what ``/restart`` exits with.

Run with: ``./sm-bot`` (or ``venv/bin/python stamind_bot.py``). Configure the token +
allowlist under a ``telegram:`` section in config.yaml (see config_template.yaml).
"""
from stamind.chat.app import ChatBot


def main() -> None:
    """Starts the long-polling Telegram bot. Runs until interrupted."""
    ChatBot().run()


if __name__ == "__main__":
    main()
