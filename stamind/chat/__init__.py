"""The Telegram front-end: the bot, and everything it needs to answer a chat.

`stamind_bot.py` stays a script at the repo root because `sm-bot` launches it directly;
everything it does is here. `app` holds `ChatBot`, the process and the state its parts
share. Around it: `runner` starts a CLI subprocess for a chat and reads it to the end,
`replies` sends what that subprocess produced back into the chat, `messages` answers what
the athlete typed, `callbacks` answers what they tapped, and `scheduler` is what fires
without being asked. `routing` says what one chat message means and `keyboards` says what
the bot draws and how it reads a tap back; both are data and pure functions, which is why
`sm bot route` can read the router's intent table without a chat front-end appearing on a
command line.

This file stays a docstring on purpose. Importing `stamind.chat.routing` runs it, so
assembling `ChatBot` here would put the whole front-end on the path of every `sm bot
route` the bot spawns.

`telegram_api` is the only module that names python-telegram-bot, and it imports the
library inside each function rather than at module scope. So importing anything in this
package — this file included — loads no telegram code at all, and every part of the
front-end is unit-testable without the library. `tests/test_layering.py` holds that rule.
"""
