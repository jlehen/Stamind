# Design: The morning message waits for the night

**Status:** Built, in the three steps of §8 · **Date:** 2026-11-14

The morning message is what the bot sends each morning: today's sessions, their buttons, and
the first question of the athlete queue (`sm bot morning`, DESIGN_bot_simple_frontend.md §4).
With the `adapt-first` setting on, it first asks the week planner, the model call inside
`workout adapt`, whether last night calls for a change (DESIGN_quiet_morning.md). In this
document **the night is in** when Garmin has today's sleep score. Garmin has it once the watch
has synced the night to the phone, which is some time after the athlete wakes.

## 1. The problem

It is Saturday 14 November. The athlete wakes at 06:15. He opens the chat and taps "📅 Today".
He sees Saturday's sessions as they are stored. The coach has not read his night yet: that
happens at 08:00, the `morning-time`, when the morning message goes out. If the night was bad,
the 08:00 message proposes to ease the day he already read at 06:15.

The other end of the morning has the opposite problem. It is Sunday. He sleeps until 08:45. At
08:00 Garmin has no night. The quiet-morning gate counts a night it cannot see as nothing to
act on, and the message goes out without it. Sunday's night is read on Monday morning
(DESIGN_quiet_morning.md §8).

So the message comes at one fixed time, and whether the night is in by then is luck.

## 2. The rule

> Until the morning message has gone out, "📅 Today" sends it. With `adapt-first` on, the
> message waits for the night: a tap sends it once the night is in, and the bot also looks on
> its own, from `earliest-morning` when that setting is on, else from `morning-time`. Two hours
> after `morning-time`, it goes out without the night.

The wait follows `adapt-first` (the author's ruling, 2026-11-14). With it on, the message asks
the week planner, which reads the night, so the night is worth waiting for. With it off, the
message does not read the night: it goes out at `morning-time` as today, a tap before that
sends it at once, and `earliest-morning` changes nothing. With the push off there is no
morning message, and "📅 Today" stays the view it is now.

`earliest-morning` is off by default, because watches differ in what closes the night (§6). On
a watch that closes it when the athlete dismisses its morning report, the night being in means
the athlete is up, and the setting is safe. On a watch that closes it on its own, the message
could wake an athlete who still sleeps. The author's ruling, 2026-11-14: his is set to 05:00;
piupiu's stays off until her watch is known.

## 3. A week

`morning-time` is 08:00, `adapt-first` is on and `earliest-morning` is off, so the bot looks on
its own from 08:00, and the message goes out at 10:00 at the latest.

- **Tuesday 17 November, the night is in.** He wakes at 05:40 and taps "📅 Today" at 05:50. The
  bot asks Garmin and finds the sleep score. He gets the whole morning message: the sessions,
  then the proposal if the night calls for a change, then the queue's first question. At 08:00
  nothing more comes.
- **Wednesday 18 November, the night is not in yet.** He taps at 06:10. The watch has not
  synced. He sees today's sessions as stored, with one line under them (§4). He opens Garmin
  Connect, the watch syncs, and he taps "📅 Today" again at 06:15. The message comes. Had he not
  tapped again, the bot's own look at 08:00 would have found the night and sent it then.
- **Thursday 19 November, he sleeps longer.** He wakes at 08:45. At 08:00 the bot asks Garmin
  and finds no night. It looks again every 15 minutes. The watch syncs at 08:50, and the 09:00
  look finds the night. The message goes out at 09:00, with the night read.
- **Friday 20 November, the watch is broken.** Or it stayed on the charger overnight: either
  way Garmin will have no night today. He taps at 06:30 and reads the line, which says the
  message comes by 10:00. The looks from 08:00 on find nothing. At 10:00 the message goes out
  without the night. The week planner treats the night as unknown, as it does today: the
  morning is quiet unless something else is new. Between 06:30 and 10:00 he can still write to
  the coach with "💬 Talk to me".

The same week with `earliest-morning` at 05:00. The bot looks at 05:00, 05:15, 05:30, and so on.

- **Tuesday.** He dismisses the watch's morning report at 05:40, and the phone syncs at 05:42.
  The 05:45 look finds the night, and the message comes without a tap.
- **Wednesday.** He taps at 06:10 and reads the line. The watch syncs at 06:12, and the 06:15
  look sends the message, whether he taps again or not.

## 4. "📅 Today" while the message waits

While the morning message has not gone out and the night is not in, "📅 Today" shows today's
sessions as it does now, with one line under them:

> Garmin does not have your night yet. Once your watch has synced, tap 📅 Today again.
> Otherwise your morning message comes by 10:00 at the latest.

The line is true before the bot looks on its own and after. The time is `morning-time` plus two
hours. Once the message has gone out, "📅 Today" is the
view it is now.

Typing "what's on today?" runs the same command as the button, so it does the same.

## 5. Inside the bot

- **The wait sits in `bot morning`**, with `adapt-first` on, after its once-a-day test and the
  silence of a schedule that has run out (DESIGN_runway_nudge.md §6), before its first line.
  Before the two-hour mark, with no sleep score stored for today, it asks Garmin for today's
  sleep alone: one data call after the login. If Garmin has no score, `bot morning` ends and
  leaves the "sent today" marker (`push_morning_last`) alone. If it has one, the forced pull the
  message already makes before it asks the week planner (DESIGN_bot_simple_frontend.md §4.2)
  stores the night. A pull that fails after the look found a score sends the message
  without the night, as a failed pull does today. Otherwise the message runs as today, and the
  quiet-morning gate grades a night it can see.
- **A try that ends without sending says nothing in the chat.** A look that fails counts as no
  night, and the journal says so at warn level (`_warn_quietly`). The try drops its journal
  run, as the Garmin check does (`journal.drop_run()`). With no Garmin credentials there is no
  wait.
- **Why one call.** A forced pull is a dozen Garmin calls plus about three per activity. Twenty
  looks on a broken-watch day are some 60 requests this way, logins included, and some 500
  with a forced pull each time.
- **The marker holds the moment the message went out**, not only its day:
  `2026-11-17T05:50:06+01:00`, on the athlete's clock, where it held `2026-11-17`. Its readers
  compare the first ten characters with today, so a value written before this change still
  reads right. It is written as the message starts, so a message that breaks half-way is not
  tried again, and a second message the same day (`--force`) keeps the first moment.
- **The changes to the week go first.** Before its first line, the message sends the changes
  the athlete was not told about yet, each as a message of its own, as a tap does
  (DESIGN_change_heads_up.md §4). The scheduler sends them from `morning-time` only, so a
  message that goes out earlier would otherwise come before them.
- **The queue's day turns at an early morning message.** Today, at `morning-time` nothing
  counts as out any more, "out" meaning sent and not yet tapped (DESIGN_athlete_queue.md §13.2,
  rule 5). The day now turns at today's morning message or at `morning-time`, whichever comes
  first. Before today's turn, the last turn is yesterday's, read the same way: the marker still
  holds yesterday's moment until today's message goes out. It is Tuesday. Monday evening's
  unanswered question comes back with the 05:50 message. The question that message asks is
  still out at 08:00: it is not sent again, and an asked-once question is not closed two hours
  after it was asked. A confirmation on its last morning closes at the same turn. The marker
  is written before the message sends from the queue, as it is today.
- **The scheduler** opens the morning message's window at `earliest-morning` when it is on,
  else at `morning-time` as today, and closes it at the later of `morning-deadline` and ten
  minutes after the two-hour mark, so the try at the mark has a wake to start on. It counts the
  message as sent when the marker says today, not when it started `bot morning`. It starts a
  try `garmin.poll_minutes` after the last one started (15 by default; its wakes come every one
  to five minutes, so about every 15 minutes), and once more at the two-hour mark. At 0, it
  tries only when the window opens and at the two-hour mark.
- **The queue waits for the message**, as it does today between `morning-time` and the
  message: while the window is open and the message has not gone out, a scheduler wake sends
  nothing from the queue, even when the athlete has just tapped. The wait is now longer, up to
  the two-hour mark. Before the window opens, the queue behaves as today: with
  `earliest-morning` off, a tap at 06:10 can still bring a queued question ahead of the message.
- **"📅 Today" and the `show_today` intent** (`ROUTER_INTENT_ARGV`) run a new hidden `bot
  today`, in the chat's own place like any view. It is the morning message while that has not
  gone out, else the view. With the push off it is always the view, and so it is on a day the
  morning message sends nothing because the schedule has run out (DESIGN_runway_nudge.md §6).
  With `adapt-first` on, when it is about to send the morning message, it first says one line
  and sends it at once: "Your night is in. Preparing your morning message…". The chat is then
  busy for the minute the message takes, as for any command. With it off, the message comes in
  seconds and has no such line.
- **A tap while the bot's own try runs.** The scheduler starts `bot morning` beside the chat,
  as a long run (DESIGN_long_runs_beside_chat.md §2), and the marker is written only at its
  end. While that run is alive, "📅 Today" and a typed "what's on today?" show the view as they
  do now, and the message follows on its own. Otherwise a tap at 06:15:20, during the try
  started at 06:15:00, would send a second morning message.
- **`earliest-morning`** is a setting (DESIGN_settings.md), seeded from
  `telegram.push.earliest_morning`: an hour, or `off`, the default. An hour at or after
  `morning-time` changes nothing, because the bot then looks from `morning-time`. With
  `adapt-first` off it changes nothing either, since the message does not wait then.
- **`bot morning --force`**, typed in a terminal, skips the wait as it skips the marker.

## 6. Not handled

- With `earliest-morning` off, a night that lands after a tap waits for the next tap or for
  `morning-time`.
- An athlete with `adapt-first` on who never sleeps with the watch gets the message two hours
  after `morning-time` every day. Neither instance's athlete is in that case.
- Stamind does not know what closes the night on a given watch (§2).
- Sleeping past the two-hour mark: the message goes out without the night, as at 08:00 today,
  and the night is read the next morning.
- A tap at 00:30, before bed: the date has turned, so he sees the new day's sessions and the
  first line of §4.
- "Ask me tomorrow", and an answer that puts its question off, still mean `morning-time`. It
  is Monday, and he taps "Ask me tomorrow". Tuesday's message goes out at 05:45 without that
  question, which comes on its own after 08:00.
- A tap and the bot's own try that start within the same instant both send the message. The
  chat checks for the try after its last wait on Telegram, which leaves the time it takes to
  start a process.

## 7. Choices made without asking

Each was listed so it could be overruled. The author ruled on 2026-11-14: each stands as
written, except 7 (one line) and 11 (folded into 4).

1. The message goes out without the night two hours after `morning-time`. This is a constant,
   not a setting, and it moves with the athlete's own morning time.
2. No "Go on without my night" button under the Today view on a broken-watch day. The
   two-hour mark covers that day, and the line says when the message comes.
3. The bot looks every `garmin.poll_minutes`, the Garmin check's existing knob, not a new one,
   before `morning-time` as after it.
4. Queued questions wait for the morning message, even when it goes out at 10:00. The wait
   starts when the window opens, not at midnight: before it, a tap can still bring a queued
   question ahead of the message, as today (§5).
5. The night is in when Garmin has today's sleep score, the same test the quiet-morning gate
   uses (DESIGN_quiet_morning.md §4). Resting HR or HRV alone does not count.
6. A tap on "📅 Today" sends the morning message whenever it has not gone out, even in the
   afternoon of a day the bot was down all morning. The thorough review objected: once the
   window has closed, "📅 Today" should be the view. The pragmatic review sided with the
   choice, which keeps the rule one sentence. Ruled: kept.
7. One line under "📅 Today" while the night is not in, true before and after the bot looks on
   its own (§4). Ruled: the line both reviews proposed, in place of two wordings picked by
   the time of day.
8. `earliest-morning` is set from the terminal only, not from the chat: whether it is safe
   depends on the watch, which the operator checks.
9. An `earliest-morning` at or after `morning-time` is accepted and changes nothing, rather
   than refused: the check would compare two settings, and no athlete gains from it.
10. A tap while the bot's own try runs shows the view, and the message follows on its own. The
    tap does not wait for the try (§5).
11. Folded into choice 4: both reviews found it described today's behaviour.
12. The line said before a tapped morning message: "Your night is in. Preparing your morning
    message…" (§5). With `adapt-first` off the message comes in seconds and has no line.
13. The window stays open until the later of `morning-deadline` and ten minutes after the
    two-hour mark, so an early deadline cannot leave a broken-watch day without its message
    (§5). The ten minutes were added in the thorough review (pass 2): the scheduler wakes
    every one to five minutes, so the try at the mark needs a wake inside the window.
14. When today's message went out before `morning-time`, the queue's day turns at that moment.
    This amends DESIGN_athlete_queue.md §13.2 rule 5 (§5).

Made while building it, 2026-11-14, not ruled yet:

15. A tap that sends the message without the night, past the two-hour mark or with no Garmin
    login configured, says "Preparing your morning message…" alone. "Your night is in." would
    be false there.
16. The retry also holds with `adapt-first` off, but only a try that sent nothing is tried
    again. A message is marked sent as it starts, so one that crashes half-way is not tried
    again, even after a restart. Ruled 2026-11-14 on the code review: the athlete would
    otherwise get the half message and the error every 15 minutes until the window closes.
17. `bot morning` runs the retrospectives step after the wait, so a try that waits writes no
    record. On a day the schedule has run out it still runs it.
18. The marker, the two-hour mark and the window live in a new module,
    `stamind/morning_message.py`, because four files read them.
19. `settings.py` (499 lines) and `cli/bot/views.py` (497 lines) were trimmed rather than
    split. The next setting, or the next few lines in the views, forces the split: the morning
    message would be its own file, `cli/bot/morning.py`.

## 8. Build order

Each step ships alone, one commit each.

1. **The wait**, with `adapt-first` on. The look, the wait in `bot morning`, the scheduler's
   retry, sent meaning the marker, and the window's end. This fixes the Sunday of §1. It needs
   no change to the queue, `messages.py` or the keyboard, because the message never goes out
   before `morning-time`.
2. **The tap.** `bot today`, the marker as a moment, the queue's turn, the check in
   `messages.py`, and the line. This fixes the Saturday of §1.
3. **`earliest-morning`.** It needs step 2's turn of the queue's day.

## 9. Touch points

| Where | What |
|---|---|
| `stamind/cli/bot/views.py` | The wait in `run_bot_morning`, the marker's moment, `run_bot_today` |
| `stamind/cli/bot/parser.py` | The hidden `bot today` |
| `stamind/cli/bot/setting.py` | `_push_lands_today` reads the marker's day |
| `stamind/chat/keyboards.py`, `routing.py` | "📅 Today" and `show_today` run `bot today` |
| `stamind/chat/messages.py` | `bot today`, by button or router, during the bot's try: the view |
| `stamind/chat/scheduler.py` | `scheduler_wake`: the window, sent means the marker, retry, hold |
| `stamind/athlete_queue.py` | `is_out`: the day turns at an early morning message |
| `stamind/garmin/client.py` | Today's sleep score alone, in one call |
| `stamind/settings.py`, `config_template.yaml`, `config_template_full.yaml` | `earliest-morning` |
| `stamind/settings.py` | 494 lines: trim what restates DESIGN_settings.md, split if not enough |
| `docs/ARCHITECTURE.md` | The morning push line, `telegram.push.*`, the keyboard, `bot today` |
| DESIGN_bot_simple_frontend.md §4.3 | One line pointing here |
| DESIGN_quiet_morning.md §8, DESIGN_athlete_queue.md §13.2 | One line each, pointing here |
| Tests | §3's week both ways; `adapt-first` off; the retry; an empty look; a tap during a try |
| Tests | The 08:00 turn of the queue's day after an early message |
