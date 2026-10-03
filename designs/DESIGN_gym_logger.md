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

Each card has an "Insert" button. It puts the new exercise right after that card, so a
face pull added after the rows does not have to climb up from the bottom one tap at a time.
The button that puts another exercise in a card's place is "⇆ Swap". "❐ Dup" puts a copy
of the card right after it: the same exercise, its sets with the reps and kilograms they
show now, none ticked. Like an inserted card, the copy stands for no line of the session.
The card's eight buttons (↶, + Set, − Set, Swap, Insert, Dup, Del, Pic) sit in two rows of
four, so their labels stay short. Each number box says what it holds, "reps" or "kg", under
the number.

A warm-up has its own card. The strength planner writes it as a lighter entry of the same
exercise ahead of the main sets (`stamind/strength/progression.md`), and the page draws one
card per entry. A line at the top of the page says so, and each card carries a tag,
"Warm-up" or "Main", that a tap switches. Here is an example. It is Thursday, and the
session holds "Belt squat 1×5 @ 120, 3×4–6 @ 140" and a leg press at 200 kg. The 120 kg
card opens as "Warm-up", because a heavier belt squat card exists; the other two open as
"Main". The athlete wants a warm-up on the leg press too. They tap Dup on it, lower the
copy to 100 kg, move it up, and tap its tag to make it "Warm-up". The tag stays on the page
and in the Markdown export: the log does not carry it, since the comparison already shows a
light set that fits no written line as an extra, never as a miss
(DESIGN_strength_planned_vs_done.md §3).

A tap can be taken back. The header's "Undo" takes back the last change anywhere on the
page, one step per tap, up to the last 50. Each card also has its own ↶ among its
buttons, which takes back only the last change made to that card. Here is an example: the
athlete ticks the third squat set, then raises the pull-up weight. The squat card's ↶
unticks the set and leaves the pull-up weight alone. A removed card has no ↶ left, so only
the header's Undo brings it back.
Undo never takes back a Finish: once a log is sent, the fix is an edit and "Send again".
The undo history is saved on the phone with the rest, so a reopened page can still undo.

The clock does not run when the page opens. At 17:50, in the changing room, the athlete
sees the leg press is out of order and swaps it before walking in. The header shows a
"Start" button where the timer will be. At 18:00 they tap it, and the timer appears and
counts from there; the log's start time is 18:00. If they forget and tick the first set at
18:04, that tick starts the clock, so the set is stamped at 0 seconds and the log starts at
18:04.

The header also has "Reset timer", shown while the clock runs. It puts the Start button
back and keeps every ticked set ticked. Here is an example: the athlete taps Start at 17:50
by mistake, ticks a set at 18:05, then taps "Reset timer" and taps Start again at 18:10.
The 18:05 set came before the new start, so it counts as 0 seconds; a set ticked at 18:12
counts as 2 minutes. A reset after Finish also clears the Finish, so the next
Finish sends a log with the new start and end, and the bot replaces the one it had.
"Start over", also in the header, goes back to the session as written and puts the Start
button back; Undo brings back what it threw away.

After the last set the athlete taps "Finish". The page sends one text message of at most
4,096 bytes to the bot and closes. The bot writes the text to a file and runs
`sm strength ingest <file>`. The CLI stores the sets as if Garmin had recorded them with
every set named, and replies with a summary: what was done, and where it departed from
what was written.

When Telegram takes the log it closes the page. A page still open two seconds after Finish
shows the log with a "Retry" button and a "Copy" button, and says the log may not have
reached the bot. A slow phone can still be closing, so the log may well have arrived; a
second send is safe, because the bot keeps the last one. A log copied from the sheet and
pasted in the chat reaches the bot the same way as a sent one (§6).

Finish stops the clock, and the page keeps the log. In the changing room the athlete
notices a mistyped weight, opens the page again from the same button, fixes it and taps
"Send again". The log goes out with the same start and end, and the bot replaces the
evening's log instead of adding a second; its summary opens with "Updated the log of". A
Finish tapped by mistake halfway through the session is not handled: the sets ticked after
it are stamped at the finish time.

The athlete also keeps their own training notes in a text file. Under "Add an exercise" is
"Export to Markdown", which copies the session to the clipboard as a few lines of Markdown:
a `### 2026-09-24 [Gym: lower body strength]` heading, the clock times, the coach's note,
then one line per exercise such as "- Belt squat: 1x5 (120 kg), 2x6 (140 kg)", with the
exercise's note after a dash and the session note last. Before any set is ticked it copies
the session as the page holds it, so the athlete can paste the day's workout ahead of time;
once a set is ticked it copies only the ticked sets, the way the log does. A phone that
refuses the clipboard gets the same sheet the log uses, with the text to select by hand.

The next morning the pull finds Garmin's activity for that day. Instead of reading
Garmin's sets, half of them unnamed, it hands the logged sets to that activity. Garmin
supplies heart rate, duration and RPE; the log supplies the sets. Nothing is asked.

## 2. Where things live

- `miniapp/` — the page: `index.html`, `app.js`, `style.css`, `exercises.json`. Static,
  no build step, no server. Served by GitHub Pages at
  `https://jlehen.github.io/Stamind/miniapp/` through `.github/workflows/pages.yml`, which
  deploys the folder on every push to the branch; the site root stays free. The page names
  its files with `?v=dev`, and the deploy replaces `dev` with the commit. Telegram keeps a
  file for ten minutes, so without this a phone could run the old `app.js` under the new
  `index.html`, and the new header buttons would have no style and do nothing.
  `exercises.json` is the vocabulary as the page searches it, written by
  `miniapp/build_exercises.py`.
- Photos. It is Thursday and the strength planner has written a Romanian deadlift the
  athlete has not done before. Its card has a "📷 Pic" button, and a tap shows two photos of
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

**A log sent again after the takeover.** It is Saturday, and Thursday's log has been on
Garmin's activity since Thursday evening. The athlete fixes a weight and sends the log
again, from the page reopened or from the calendar (§8). The ingest finds the Garmin
activity that holds Thursday's log and replaces the sets and the raw log there. Garmin's
start time and length stay, and no placeholder is made, so the day never holds two gym
activities. The summary opens with "Updated the log of", as for any second send.

## 6. The bot

- The companion keyboard is rebuilt on every send. When the `strength-logger` setting is on and
  a live strength session with prescribed sets exists today, or else within the next seven
  days, the first row is the gym button, labelled with the day ("🏋️ Log today's gym",
  "🏋️ Log Thursday's gym"), a `KeyboardButton(text, web_app=WebAppInfo(url))`. Otherwise
  the keyboard is what it is today.
- A `MessageHandler(filters.StatusUpdate.WEB_APP_DATA, ...)` receives the log. It checks
  the chat is allowed, writes the data to `logs/gym_logs/<date>-<hhmmss>.json`, and
  runs `strength ingest <file>` through `_start_command`, so the summary reaches the chat
  the way every command's output does.
- A typed message that starts with `{` is a log the athlete copied from the page and
  pasted (§1). It goes the same way as the page's own message. A broken paste gets the
  ingest's own error in the chat.

## 7. Not decided here

- Whether the log or Garmin wins on a day with both, beyond the takeover rule above.
- Grading a session set by set: DESIGN_strength_planned_vs_done.md.
- What the strength planner is shown of a log.
- A rest timer that alerts: the page cannot notify while the phone is locked.
- Refreshing the button after a `workout adapt` run from the terminal; the log carries the
  revision id, so a stale button costs nothing but a mismatch in the summary.

## 8. A past log, opened from the calendar

It is Saturday 3 October. The athlete opens the calendar and taps Thursday 24 September, a
gym day. The sheet's "Done" part names the five exercises done as written on one line, so
it does not say how many reps and kilograms each set had. Under the sheet is a button,
"🏋️ Open the gym log". A tap opens the gym logger in the same window, on Thursday's log.

The page draws one card per exercise, in the order the log holds them. Each set shows its
reps and kilograms, ticked. A written set that was not done follows the done ones on its
card, unticked. A written exercise that was not done at all comes after the last logged
card, unticked. The header shows the session's length, "38:00 in total".

The page opens locked. The steppers, the ticks, the card buttons and the notes are out of
reach, and there is no button to send. The header has two buttons. "‹ Calendar" goes back
to the calendar. "✏️ Edit" unlocks the page: it then works as it does in the gym, and the
button to send reads "Send again". The athlete raises one set from 55 to 57.5 kg and taps
it. Telegram closes the page, and the bot answers "Updated the log of 2026-09-24 Thu…"
(§5). "🔒 Lock" locks the page again without sending.

**Where the log comes from.** The calendar's month file carries, on each day that has a
gym log, `gym`: `{"s": …, "l": …}`, the session as §3 writes it and the log as §4 stored
it (DESIGN_miniapp_storage.md §4). The button's address is `index.html#s=…&l=…`, each part
base64url of its JSON, like `s=` alone in the gym. The calendar button's own data carries
no log: a log with its session is about 1.5 KB, and that button has 5 KB for ten weeks of
days. So "🏋️ Open the gym log" shows once the month's file has arrived, and an instance
with no bucket does not have it.

**The bot's log wins.** An opened log is drawn from the address. The page does not read
the state it saved on the phone during the session, and it saves nothing on the phone. A
change that is not sent is lost when the page closes.

**The day and the clock times stay.** A log sent again from here carries the `d`, `st` and
`en` it was opened with, so it replaces that day's log. "Reset timer" and "Start over" are
not offered on an opened log: both restart the clock, and the next send would be dated
today. A set ticked here is stamped at the session's end, like any set ticked after Finish.

**The "Warm-up" tags** are the ones the page gives a session it opens for the first time
(§1), since the log does not carry them.

Not handled:

- A session the watch recorded alone has no log, so its day has no button.
- A log written against another revision than the session the calendar shows on that day
  has no button. It is Thursday. The athlete logs from a button built before a
  `workout adapt` run rewrote the session. The log's positions point at lines the calendar's
  session does not have, so the page would have nothing to hang the cards on.
- A log in a month the calendar's window no longer touches. A send from there is stored,
  but that month's file is built again only by `sm data publish`
  (DESIGN_miniapp_storage.md §4), so the calendar keeps showing the earlier log.
- Not verified on a phone: `sendData` from a page reached by a link inside the Mini App.
  The page was opened from the calendar's keyboard button, which is what `sendData` asks
  for, and Telegram's script keeps its launch parameters across the link. The browser test
  drives the same path with a stub in Telegram's place.
