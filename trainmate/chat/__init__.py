"""The Telegram front-end's own code, apart from the process that runs it.

`trainmate_bot.py` stays a script at the repo root because `tm-bot` launches it directly;
what can be read without that process is here. `routing` says what one chat message
means, `keyboards` says what the bot draws and how it reads a tap back, and `scheduler`
says when the morning push and the nightly reflect are due.

Nothing in this package imports the telegram library, so all of it is unit-testable, and
`tm bot route` can read the router's intent table out of `routing` without a chat
front-end appearing on a command line.
"""
