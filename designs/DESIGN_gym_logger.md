# Gym logger: a Telegram Mini App that pushes the session and pulls back what was done

**Status:** Prototype, built to be tried in one gym visit before any design decision ·
**Date:** 2026-09-22 · **Branch:** worktree-gym-logger

This document is the contract the prototype is built against. It is deliberately short.
Every mechanism in it is the simplest one that closes the loop; what a real design would
have to decide is listed in §7 and not decided here.

## 1. What it does

It is Thursday, a gym day. At 07:00 the bot sends the morning message. Under the text
field, the companion keyboard has a new first row: "🏋️ Log today's gym". The button holds
a web address, and the address carries today's session: the exercises, sets, rep ranges
and kilograms the strength planner wrote.

At 18:00 the athlete taps the button in the gym. A page opens inside Telegram and draws
the session as a checklist. The athlete ticks sets, changes reps or kilograms, adds a
fourth set, swaps the belt squat for a leg press, removes the curls, moves the rows around,
appends an exercise the session did not ask for, and types a note. After every tap the
page saves its state on the phone, so a closed Telegram reopens where it left off.

The clock does not run when the page opens. At 17:50, in the changing room, the athlete
sees the leg press is out of order and swaps it before walking in. The header shows a
"Start" button where the timer will be. At 18:00 they tap it, and the timer appears and
counts from there; the log's start time is 18:00. If they forget and tick the first set at
18:04, that tick starts the clock, so the set is stamped at 0 seconds and the log starts at
18:04. "Start over" puts the Start button back.

After the last set the athlete taps "Finish". The page sends one text message of at most
4,096 bytes to the bot and closes. The bot writes the text to a file and runs
`sm strength ingest <file>`. The CLI stores the sets as if Garmin had recorded them with
every set named, and replies with a summary: what was done, and where it departed from
what was written.

Finish stops the clock, and the page keeps the log. In the changing room the athlete
notices a mistyped weight, opens the page again from the same button, fixes it and taps
"Send again". The log goes out with the same start and end, and the bot replaces the
evening's log instead of adding a second; its summary opens with "Updated the log of". A
Finish tapped by mistake halfway through the session is not handled: the sets ticked after
it are stamped at the finish time.

The next morning the pull finds Garmin's activity for that day. Instead of reading
Garmin's sets, half of them unnamed, it hands the logged sets to that activity. Garmin
supplies heart rate, duration and RPE; the log supplies the sets. Nothing is asked.

## 2. Where things live

- `miniapp/` — the page: `index.html`, `app.js`, `style.css`, `exercises.json`. Static,
  no build step, no server. Served by GitHub Pages at
  `https://jlehen.github.io/Stamind/miniapp/` through `.github/workflows/pages.yml`, which
  deploys the folder on every push to the branch; the site root stays free.
  `exercises.json` is the vocabulary as the page searches it, written by
  `miniapp/build_exercises.py`.
- Photos. It is Thursday and the strength planner has written a Romanian deadlift the
  athlete has not done before. Its card has a "Photos" button, and a tap shows two photos of
  the lift under its name. They come from Free Exercise DB, a public-domain set of about 870
  exercises with two photos each, loaded from its GitHub repository; nothing is copied into
  this one. The vocabulary's fifth column holds the entry's id. A row gets one only when the
  entry is the same exercise, so a belt squat, which the set lacks, has no button rather than
  a photo of another squat. The links came from a Gemini Flash and Sonnet comparison of the
  two lists, kept for the main movement patterns and checked by hand; an exercise without
  one is linked by hand when it is wanted.
- `stamind/strength/logger.py` — the two payloads (§3, §4): the session encoded into the
  button's URL, and the log decoded and validated. Pure functions, no database.
- `stamind/cli/strength.py` gains `strength ingest FILE`.
- `stamind/chat/` — the keyboard button and the handler for the page's data message.
- The page's address is built in, as `logger.PAGE_URL`. The `strength-logger` setting, on by
  default, turns the button off for one instance: `sm settings set strength-logger off`.

## 3. The session payload (bot → page)

The URL is `<PAGE_URL>#s=<base64url(JSON)>`. The hash fragment is never sent to the
host serving the page.

```json
{"v": 1, "r": 727, "d": "2026-09-24", "t": "Gym: lower body strength",
 "x": [{"n": "belt squat", "s": 3, "lo": 4, "hi": 6, "kg": 140},
       {"n": "pull up", "s": 3, "lo": 6, "hi": 8, "kg": null}],
 "notes": "Alternate the squat and the pull-ups."}
```

`r` is the revision id of the session (`workouts.id`), `d` its date, `t` its title, `x` the
`prescribed_sets` rows in position order (`n` the vocabulary name, `s` the number of sets,
`lo`/`hi` the rep range, `kg` the load or null), and `notes` the text under the exercise
lines of the description, cut to 300 characters. The brief is left out: the page is for
the gym, not for reading.

## 4. The log payload (page → bot)

Sent through `Telegram.WebApp.sendData`, so it is at most 4,096 bytes. Reference by name
and position, never by copying the prescription back.

```json
{"v": 1, "r": 727, "d": "2026-09-24", "st": "18:02", "en": "19:05",
 "x": [{"n": "belt squat", "p": 1, "sets": [[5, 120, 40], [6, 140, 210], [5, 140, 390]]},
       {"n": "leg press", "p": 2, "sets": [[8, 200, 600]], "note": "swapped, squat rack busy"},
       {"n": "barbell biceps curl", "sets": [[10, 30, 900], [10, 30, 990]]}],
 "note": "left knee felt off on the squat"}
```

Each set is `[reps, kg, seconds since the session started]`; `kg` is null for a
bodyweight exercise. `p` is the position of the prescribed row this exercise stands for;
an added exercise has no `p`, a swapped one keeps the `p` of the row it replaced. A
prescribed exercise not done is simply absent. `st` and `en` are local clock times, and
`d` is the day the athlete lifted, from the phone's clock at the first Finish: a session
done a day early or late is logged on the day it happened, and `r` still says which session
it was. A log sent again after an edit carries the same `d`, `st` and `en`, so it lands on
the same day's placeholder (§5). Forty-two sets of twelve exercises take about 1 KB.

## 5. The ingest

`sm strength ingest FILE` reads the log, refuses an exercise name the vocabulary does not
know (the page offers vocabulary names only, so that is a bug, not an athlete's typo), and
then:

1. Upserts a placeholder activity in `completed_activities`: `activity_id = "log:<date>"`,
   `activity_type = strength_training`, `start_time` and `duration_sec` from `st`/`en`,
   `activity_name = "Logged gym session"`. Ingesting the same day twice replaces the
   earlier log.
2. Stores the sets through `store_exercise_sets`, read and frozen at once, one active row
   per logged set with `named_by = athlete`, and a rest row between two sets when the
   timestamps give one. The strength history, the habit count in the strength planner and
   `workout compare` read these rows unchanged.
3. Keeps the raw log in `gym_logs` (`activity_id`, `revision_id`, `received_at`,
   `payload`), so a later grading step has the departures without re-deriving them.
4. Prints the summary: one line per exercise, "Belt squat 5 @ 120, 6 @ 140, 5 @ 140
   (written 3×4–6 @ 140)", then the prescribed exercises not done and the exercises added.

**The takeover.** `sets.read_new_activities` runs before every pull reads Garmin's sets.
For a strength activity dated on a day that has a placeholder, it moves the placeholder's
rows and `gym_logs` row onto the Garmin activity, deletes the placeholder, stamps the
activity read and frozen, and never calls Garmin for its sets. A day the watch split in two
gives the log to the longer activity; the other is read as usual.

The pull ends by deleting every local activity Garmin did not return in the pulled range.
Garmin never returns a placeholder, so that reconcile skips the `log:` ids; without that,
an evening pull would delete the log before the next morning's takeover.

## 6. The bot

- The companion keyboard is rebuilt on every send. When the `strength-logger` setting is on and
  a live strength session with prescribed sets exists today, or else within the next seven
  days, the first row is the gym button, labelled with the day ("🏋️ Log today's gym",
  "🏋️ Log Thursday's gym"), a `KeyboardButton(text, web_app=WebAppInfo(url))`. Otherwise
  the keyboard is what it is today. Expert mode has no reply keyboard and therefore no
  button; not handled in the prototype.
- A `MessageHandler(filters.StatusUpdate.WEB_APP_DATA, ...)` receives the log. It checks
  the chat is allowed, writes the data to `<data_dir>/gym_logs/<date>-<hhmmss>.json`, and
  runs `strength ingest <file>` through `_start_command`, so the summary reaches the chat
  the way every command's output does.

## 7. Not decided here

- Whether the log or Garmin wins on a day with both, beyond the takeover rule above.
- Grading a session set by set, and what the strength planner is shown of a log.
- A rest timer that alerts: the page cannot notify while the phone is locked.
- Expert mode, which has no reply keyboard to hold the button.
- Refreshing the button after a `workout adapt` run from the terminal; the log carries the
  revision id, so a stale button costs nothing but a mismatch in the summary.
- A log sent again after the morning pull handed it to Garmin's activity: it lands on a
  fresh placeholder, and the activity keeps the sets of the first send.
