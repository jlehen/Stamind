# Design: The morning message waits for the night

**Status:** Designed, not built · **Date:** 2026-11-14

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

> The morning message waits for the night. Until it has gone out, "📅 Today" sends it as soon
> as the night is in. The bot also looks on its own: from `earliest-morning` when that setting
> is on, else from `morning-time`. Two hours after `morning-time`, the message goes out without
> the night.

The rule does not depend on `adapt-first` (the athlete's ruling, 2026-11-14: that setting keeps
its one meaning). With it off, the message does not read the night, but it waits for it all the
same, so one rule holds for every athlete. With the push off there is no morning message, and
"📅 Today" stays the view it is now.

`earliest-morning` is off by default, because watches differ in what closes the night (§6). On
a watch that closes it when the athlete dismisses its morning report, the night being in means
the athlete is up, and the setting is safe. On a watch that closes it on its own, the message
could wake an athlete who still sleeps. The athlete's ruling, 2026-11-14: his is set to 05:00;
piupiu's stays off until her watch is known.

## 3. A week

`morning-time` is 08:00 and `earliest-morning` is off, so the bot looks on its own from 08:00,
and the message goes out at 10:00 at the latest.

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
- **Wednesday.** After his 06:10 tap, the line says the bot will send the message once Garmin
  has the night. The watch syncs at 06:12, and the 06:15 look sends it. He does not tap again.
- **Thursday and Friday** go as above, with the looks starting at 05:00. On Thursday the 09:00
  look is still the first to find the night. On Friday none does.

## 4. "📅 Today" while the message waits

While the morning message has not gone out and the night is not in, "📅 Today" shows today's
sessions as it does now, with one line under them. Before the bot looks on its own, the line
asks for another tap:

> Garmin does not have your night yet. Your morning message waits for it, until 10:00 at the
> latest. Once your watch has synced, tap 📅 Today again.

Once the bot looks on its own, from `earliest-morning` or `morning-time` (§2), it says the bot
will send it:

> Garmin does not have your night yet. I'll send your morning message as soon as it does, by
> 10:00 at the latest.

The time is `morning-time` plus two hours. Once the message has gone out, "📅 Today" is the
view it is now.

Typing "what's on today?" runs the same command as the button, so it does the same.

## 5. Inside the bot

- **The wait sits in `bot morning`**, after its once-a-day test and the silence of a schedule
  that has run out (DESIGN_runway_nudge.md §6), before its first line. Before the two-hour
  mark, with no sleep score stored for today, it asks Garmin for today's sleep alone: one call.
  If Garmin has no score either, `bot morning` prints nothing, leaves the "sent today" marker
  (`push_morning_last`) alone, and ends. If it has one, the message runs as today. The forced
  pull it already makes before it asks the week planner (DESIGN_bot_simple_frontend.md §4.2),
  now made whether or not it asks, stores the night, and the quiet-morning gate grades a night
  it can see.
- **Why one call.** A forced pull re-fetches the last three days: their activities, and each
  day's stats, sleep and HRV, and it syncs the Calendar signals. That is some 10 to 15 Garmin
  calls. A broken-watch day with looks from 05:00 to 10:00 makes about 20 looks: some 20 calls
  this way, some 250 with a forced pull each time.
- **The scheduler** opens the morning message's window at `earliest-morning` when it is on,
  else at `morning-time` as today. It counts the message as sent when the marker says today,
  not when it started `bot morning`. A try that ended without sending is made again after
  `garmin.poll_minutes` (15 by default), and once more at the two-hour mark.
- **The queue waits for the message.** While the message waits, the bot sends no queued
  question, as before 08:00 today. The morning message stays the first thing of the day.
- **"📅 Today" and the `show_today` intent** run a new hidden `bot today`: the morning message
  while it has not gone out, else the view.
- **`earliest-morning`** is a setting (DESIGN_settings.md), seeded from
  `telegram.push.earliest_morning`: an hour, or `off`, the default. An hour at or after
  `morning-time` changes nothing, because the bot then looks from `morning-time`.
- **`bot morning --force`**, typed in a terminal, skips the wait as it skips the marker.

## 6. Not handled

- With `earliest-morning` off, a night that lands after a tap waits for the next tap or for
  `morning-time`.
- An athlete who never sleeps with the watch gets the message two hours after `morning-time`
  every day. Neither instance's athlete is in that case.
- Watches differ in what closes the night: on some it is the athlete dismissing the watch's
  morning report, on others the end of the sleep schedule or the athlete moving. Stamind does
  not know which, and reads only whether the sleep score is in. With `earliest-morning` on, a
  watch that closes the night while the athlete still sleeps sends the message to a sleeping
  athlete, which is why the setting is off by default. With it off, such a watch gets the
  message at `morning-time`, as today.
- Sleeping past the two-hour mark: the message goes out without the night, as at 08:00 today,
  and the night is read the next morning.

## 7. Choices made without asking

Each is listed so it can be overruled.

1. The message goes out without the night two hours after `morning-time`. This is a constant,
   not a setting, and it moves with the athlete's own morning time.
2. No "Go on without my night" button under the Today view on a broken-watch day. The
   two-hour mark covers that day, and the line says when the message comes.
3. The bot looks every `garmin.poll_minutes`, the Garmin check's existing knob, not a new one,
   before `morning-time` as after it.
4. Queued questions wait for the morning message, even when it goes out at 10:00.
5. The night is in when Garmin has today's sleep score, the same test the quiet-morning gate
   uses (DESIGN_quiet_morning.md §4). Resting HR or HRV alone does not count.
6. A tap on "📅 Today" sends the morning message whenever it has not gone out, even in the
   afternoon of a day the bot was down all morning.
7. The two lines' wording, and which one shows: picked by whether the bot looks on its own
   yet, not by the setting (§4).
8. `earliest-morning` is set from the terminal only, not from the chat: whether it is safe
   depends on the watch, which the operator checks.
9. An `earliest-morning` at or after `morning-time` is accepted and changes nothing, rather
   than refused: the check would compare two settings, and no athlete gains from it.

## 8. Touch points

| Where | What |
|---|---|
| `stamind/cli/bot/views.py` | The wait in `run_bot_morning`; `run_bot_today`; the two lines |
| `stamind/cli/bot/parser.py` | The hidden `bot today` |
| `stamind/chat/keyboards.py`, `routing.py` | "📅 Today" and `show_today` run `bot today` |
| `stamind/chat/scheduler.py` | `scheduler_wake`: the window, sent means the marker, the retry |
| `stamind/garmin/client.py` | Today's sleep score alone, in one call |
| `stamind/settings.py`, `config_template.yaml`, `config_template_full.yaml` | `earliest-morning` |
| `docs/ARCHITECTURE.md` | The morning push line, `telegram.push.*`, the keyboard, `bot today` |
| DESIGN_bot_simple_frontend.md §4.3, DESIGN_quiet_morning.md §8 | One line each, pointing here |
| Tests | §3's week both ways; the retry; one call per empty look; "📅 Today" after the message |
