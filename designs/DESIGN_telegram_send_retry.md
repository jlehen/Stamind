# Design: retry a Telegram call while Telegram has a bad minute

**Status:** Implemented · **Date:** 2026-09-26 · **Branch:** `worktree-telegram-send-retry`

## 1. The problem

It is Saturday morning. The athlete taps "Today" and the bot starts a CLI command. The
command writes the day's session, the bot sends it as a chat message, and Telegram's
server answers that one request with 502 Bad Gateway. python-telegram-bot raises a
`NetworkError` and does not try again. The message is gone. The bot registers no error
handler, so the library prints the whole traceback to the bot's terminal, and nothing
about it reaches the journal.

A 502 from Telegram lasts seconds, rarely a minute or two. The long poll, which asks
Telegram for new messages, already survives it: the library retries a failed poll on its
own, and since 2026-09-24 the bot logs each failure as one line. Every other call, which
is a message, a photo, a keyboard edit or the typing indicator, failed on the first try.

## 2. What happens now

Every call but the poll goes through one HTTP client that tries again. A 5xx answer, a
connection that could not be opened and a request that timed out are all retried, with a
growing pause between tries: 1, 2, 4 and 8 seconds, then 15 seconds between each try,
until the window in §3 has passed. Then the last failure goes through unchanged. The
message arrives a few seconds late instead of not at all. Each retry is a `debug` line in
the journal, so `logging.level: debug` shows the whole bad minute and the default shows
only how it ended.

The library keeps a separate client for the poll, so the poll keeps the library's own
retry and is not touched.

When the window runs out, the failure ends in the journal, not on the terminal:

- Inside a handler (a tap, a message), the bot's error handler writes one `bot.event`
  line at `warn` and prints one line, the same shape as a failed poll. Any other
  exception in a handler is ours, so it keeps its traceback on the terminal and gets a
  `bot.event` line at `error`.
- Inside the task that streams a CLI command's output into the chat, the failure is
  logged the same way, and the bot does not try to send "Internal error" over the channel
  that just failed. That fallback send is guarded too, so no exception escapes the task.
  This matters because the push loop waits on that task for reminders and for the
  heads-up about changed sessions: before, one bad minute at Telegram could end the push
  loop silently, and mornings would stop until the next restart.
- The push loop also survives any other exception one wake raises: it logs an `error`
  line and wakes again a minute later.

A retried timeout may deliver a message twice, when Telegram had accepted it and only
the answer was lost. A duplicated paragraph in the chat is a mild oddity. A missing
paragraph, or a missing question with buttons, is silently wrong. So timeouts are
retried.

## 3. The knob

`telegram.send_retry_seconds` in config.yaml is how long the bot keeps trying, default
180. `0` turns the retry off. It is an operator knob and not a setting: the athlete has
no reason to change it, and it is read once at startup.

## 4. Not handled

- A morning push that gives up is not re-sent later that day. `bot morning` stamps its
  per-day marker when it runs, and the CLI cannot know whether the bot's send got
  through.
- The athlete is never told a message was lost: telling them needs the channel that just
  failed. The journal warning is the record.
