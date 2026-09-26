# Calendar: a Telegram Mini App and `sm calendar`, both built on one list of days

**Status:** Reviewed draft · **Date:** 2026-09-25 · **Branch:** worktree-calendar-miniapp-design

This design comes out of an interview with the author, then one review pass and one pass that
weighed each review finding against its cost. What was decided is written here as the
contract. What was left out is in §11.

The calendar is read-only. It shows the sessions, the activities Garmin recorded, the goals,
the constraints, the daily signals and the mesocycles. It changes nothing. Editing from the
calendar, and replacing Google Calendar, are later steps (§11).

In this document "the calendar" is the new page and command. Google Calendar, where Stamind
already pushes the sessions, is always named in full.

## 1. What it does

It is Friday 25 September. The companion athlete taps "🗓 Calendar" in the bot's keyboard.
A page opens inside Telegram on this month's grid, with today outlined. Weeks start on
Monday.

The header says "September 2026". Under it is her goal, worded the way "🎯 Goals" words it
in the chat: "🏃 Sylvesterlauf — on 13 Dec (in 11 weeks)". On the right is a small stamp:
"as of Fri 07:02". That stamp is the time the bot built the button, which is the time of the
bot's last message (§5).

Each day cell shows the sport of the session as an icon, and under it a short name the week
planner wrote with the session: "🏃 Easy", "🚴 Hills". Wednesday's ride was done, so its cell
is tinted green. On Tuesday she ran 32 minutes of a planned 50; "✅ Done lately" already
counts that as done, so the calendar tints it green too. Last Saturday's session was
skipped, so its cell is red. Next week's cells have no tint, because those sessions have not
happened yet.

Last Sunday she also went for a two-hour hike that nothing had planned. That day shows a
faded hiking icon next to the planned session's icon. A ten-minute walk to the shops is too
small to count as training, and the companion never mentions those, so it does not appear
anywhere on the page.

Some cells carry a small mark in a corner. A diamond means a constraint covers that day, for
example "away at a wedding, no training". A dot means a signal was recorded that day, for
example two drinks the evening before, or a hot day.

A thin coloured strip runs along the bottom of every cell. Its colour says which mesocycle
the day belongs to. Under the grid, a legend gives each colour its mesocycle's name and
dates.

She taps Tuesday. A sheet slides up with three parts, each made of lines the bot already
writes in the chat:

- **Planned:** the session's line, as "📅 Today" writes it: "🏃 2026-09-22 Tue: Easy run
  — 50 min". Not the full workout text, which does not fit in a button (§8). That text stays
  in the morning message and in "📅 Today": the calendar shows what and when, the chat
  shows how.
- **Done:** that day's lines from "✅ Done lately": "✅ 🏃 Easy run — 50 min (you did 32
  min)", with the lifted sets under a gym session.
- **Signals and constraints:** each one on its own line.

She swipes left and sees October, then early November. The page goes as far as the
snapshot does, 6 November, and no further.

A switch in the header shows the plan view instead of the grid (§3.4).

## 2. Who uses what

- **The page** is for anyone whose bot runs in companion mode. Both instances do today, the
  author's and the companion athlete's. The page speaks only in companion words.
- **`sm calendar`** is the author's month grid in the terminal, in expert words (§7).
- Both are built on one list of days (§4). The list holds facts: which sessions, which
  activities, which grade. Each view words those facts in the voice it already has. The two
  must agree on the facts. They need not use the same words.

Expert mode in Telegram has no reply keyboard, so it has no button. This is the same
situation as the gym logger (DESIGN_gym_logger.md §7). Not handled here.

## 3. What the page shows

### 3.1 The day cell

A phone screen is about 390 pixels wide, so each of the seven columns is about 50 pixels.
A cell holds, from top to bottom:

1. The day number, with the constraint diamond and the signal dot beside it.
2. The sport icon of the session, and its label.
3. The mesocycle strip.

The label is the session's short name (§3.6). A session without one shows its planned
length: "90′" under 100 minutes, "1h40" or "2h" from 100 minutes on. A session with
neither shows its icon alone. A planned rest day shows 🛌. A day with no session shows
nothing.

**A day with two sessions shows two icons and no label.** There is no room for two labels.
This is the one rule, and there is no switch to turn labels on.

The icons come from `SPORT_EMOJI` in `cli/render/session_lines.py`, the same table the
companion's chat messages use.

### 3.2 The tint

The tint is the glyph "✅ Done lately" would give the day (`simple_compare_lines` in
`cli/render/session_lines.py`, DESIGN_bot_simple_frontend.md §6):

- **green** for ✅: the session was done, fully or in part (`SIMPLE_DONE_STATUSES`), or a
  planned rest day was kept;
- **red** for ❌: the session was missed, or a rest day was trained through;
- **no tint** for a day still ahead.

A kept rest day turns green only once the day is over; a rest day trained through is red at
once. A day with two sessions is red if either one is red, otherwise green if either one is
green: a gym session done in the morning and a run still ahead make a green day. There is
no amber, and the page never
shows the grader's reasons. Those are expert detail, and the companion views leave them
out on purpose.

### 3.3 Activities nobody planned

`unplanned_kind` in `analytics/adherence.py` sorts an activity that matched no session into
three kinds: minor, unplanned or off-plan. An unplanned or off-plan activity shows as its
sport icon, faded, next to whatever the day planned. In the sheet it is the "➕" line
"✅ Done lately" writes. A minor one appears nowhere on the page.

### 3.4 The plan view

The plan view is one list, top to bottom, from the first mesocycle in the snapshot to the
last goal:

- one row per mesocycle, with its colour, its name and its dates;
- one row per goal, at its date, in the words of §1's header;
- a "Today" line between the rows where today falls.

Its rows are not links. It shows no mesocycle focus text. Reading why the plan is shaped
this way stays with "🧭 My plan", which already answers it in the chat.

### 3.5 Goals

Every goal that is not archived is marked 🎯 on its date, in the grid and in the plan view.
The header shows the nearest goal still ahead, through `simple_goal_line` in
`cli/render/plan_lines.py`. That function already says "on 13 Dec" for an event, a day
something happens, and "by ~22 Dec" for a horizon, a date the training aims at. So the
header needs no rule of its own for the two kinds.

### 3.6 The short name

A session gets a new field, `short_name`: at most five characters that say what kind of
session it is. The week planner writes it with the title, in the same answer, so it is
never guessed from the title afterwards. Nothing else sets it.

It is Monday. `workout generate` writes Thursday's run as "Hill repeats, 6×90 s" with the
short name "Hills". On Tuesday she says Thursday is short on time, and `workout adapt`
writes the run again as "Short hill repeats, 4×90 s". The new version of the session
carries the short name the week planner gave it in that answer, "Hills" again.

The rules:

- **The week planner writes it** in `workout generate`, `workout adapt` and `workout
  tweak`. The prompt asks for at most five characters and gives examples: "Easy", "Long",
  "Hills", "Tempo", "Z2", "VO2", "Gym". The value is stored as written. The cell cuts
  anything past its width.
- **It is taken as given, like the title.** `WorkoutChange.append` takes `short_name` as
  it takes `title`: a caller that omits it writes none, and it never carries forward from
  the previous version. So a recovery spin that replaces a "VO2" session never inherits
  "VO2". The strength planner's `_write`, which builds some rows by hand from the live
  session, copies it from that session. Rollback and restore copy it with every other
  column.
- **It alone is not a change.** A new version of a session is saved only when one of the
  prescription fields changes (`PRESCRIPTION_FIELDS` in `db/workout_change.py`), and
  `short_name` is not one of them. A rewrite whose only difference is the short name is
  dropped, like a restated session. `prescription_matches` in `coach/revisions.py`, which
  mirrors that rule for the preview, stays without it too. Google Calendar never shows it,
  so it is not among the fields that make an event stale.
- **A rest day has none**, and its cell shows 🛌 alone.
- **A session written before the field existed** has none, and shows its length. It gets a
  short name only when a later `workout generate` or `workout adapt` changes it, because a
  rewrite that differs only in the short name is dropped (the rule above). New sessions
  get one from the start. So on the day this ships, most cells ahead show lengths; they turn
  into short names as the weeks are written, and within the 6-week window ahead that takes
  about six weeks. No model call fills the old ones in.

**The migration.** A one-off script adds the column, `ALTER TABLE workouts ADD COLUMN
short_name TEXT`, whenever the column is missing, whatever version the database is stamped
with. `SCHEMA_VERSION` moves from 19 to 20. The script runs on the author's and the
companion's databases before either bot is restarted on the new code, because
`_init_db` only creates tables and never adds a column.

## 4. One list of days

A new module, `stamind/calendar_days.py`, gathers the facts for a range of dates. It reads
the database and returns one `Day` per date. It writes nothing and never pulls from Garmin.

A `Day` holds:

- `results`: the day's pairing of each live session with its activity, as
  `adherence_window` and `compare_days` in `analytics/compare.py` return it, with each
  session's grade from `classify_adherence`.
- `unplanned`: each activity that matched no session, with its kind from `unplanned_kind`.
- `constraints` and `signals`: the rows that cover the day.

Beside the days, it returns the mesocycles and the goals:

- **Mesocycles** are what `get_governing_mesocycles(start, end)` in `db/mesocycles.py`
  returns, in date order. That call returns the mesocycles of every plan that governs a
  day in the range. It is Friday 25 September on the author's instance. One plan ends on
  30 September and the next starts on 1 October, and the list holds the mesocycles of
  both. The strip colours are numbered along that one list.
- **Goals** are every goal that is not archived, in date order.

The `Day` holds no text. The page's words and the terminal's words are each written by
that view (§5, §7).

## 5. The snapshot (bot → page)

The page has no server behind it, like the gym logger. The bot packs the calendar into the
button's web address, after `#c=`. A browser never sends that part to the host serving the
page. Telegram adds its own launch parameters to the part after the `#`, so the page reads
`c=` with the same regular expression the gym page uses for `s=` (`miniapp/logic.js`).

**The window** is 4 weeks back and 6 weeks ahead of today. On 25 September that is 28
August to 6 November. The mesocycles and goals run further, to the last goal, so the plan
view can show them (§3.4).

**The shape**, before packing:

```json
{"v": 1, "at": "2026-09-25T07:02", "today": "2026-09-25",
 "from": "2026-08-28", "to": "2026-11-06",
 "goal": "🏃 Sylvesterlauf — on 13 Dec (in 11 weeks)",
 "goals": [{"t": "🏃 Sylvesterlauf — on 13 Dec (in 11 weeks)", "d": "2026-12-13"}],
 "meso": [{"n": "Aerobic base", "s": "2026-10-01", "e": "2026-10-18"}],
 "end": "2026-10-25", "fit": ["2026-09-11", "2026-10-16"],
 "days": {"2026-09-22": {
    "x": [{"i": "🏃", "l": "Easy", "g": "ok"}],
    "u": [], "c": 0, "s": 1,
    "sheet": [["Planned", ["🏃 2026-09-22 Tue: Easy run — 50 min", "Easy run in zone 2…"]],
              ["Done", ["✅ 🏃 Easy run — 50 min (you did 32 min)"]],
              ["Signals and constraints", ["alcohol: 2"]]]}}}
```

- `x` is the day's sessions: icon, label and glyph, `ok` (green), `miss` (red) or `ahead`.
- `u` is the faded icons, and `c` and `s` whether the day has a constraint or a signal.
- `sheet` is the day's sheet as heading and lines. The page prints the lines and lets the
  browser wrap them.
- `end` is the last day of the written schedule, when it falls inside the window. The page
  prints `SIMPLE_END_NOTE`, "That's the end of the current schedule.", under the grid from
  that day on. Without it, the blank days after it would read as rest (DESIGN_runway_nudge.md
  §6).
- `fit` is the first and last day whose sheet made it in (§5, the budget rule), or null.
  It is what tells a day whose details did not fit from a day that has nothing to show.
- `at` comes from `clock.now()`, in the athlete's time zone. It is what the stamp shows.
- The page works out each day's mesocycle from the dates in `meso`.

**Where the lines come from.** A new renderer, `cli/render/calendar_page.py`, builds the
snapshot from the list of days. It writes no new wording. Each line comes from a function
the companion already uses:

- Planned: `simple_day_lines` for that day, called without grades, so the sheet does not
  say "done" twice, and without descriptions (§8). On a day inside the schedule with no
  session, it returns its rest line, as the chat does.
- Done: the lines `simple_compare_lines` writes for that day, which use
  `simple_activity_line` and `simple_set_lines`.
- Signals: `simple_metric_words` for the metric, then the value, then the signal's text.
  Constraints: the title, then the description.
- The goal: `simple_goal_line`.

**The packing.** The JSON is compressed with zlib, then written in base64url. The page opens
it with the browser's own `DecompressionStream("deflate")`. A Telegram built on a browser
too old for that is not handled.

**The size.** Measured on the author's database on 2026-09-25, this window holds 75
sessions, 38 activities, 10 signals and 4 constraints. Packed with the full workout text, it is
about 47 KB, and most of that is the session descriptions, about 790 characters each. The grid
marks alone are about 2 KB. Telegram does not publish a limit on a button's address, so
step 0 (§8) measures it.

**The rule when it does not fit.** Everything but the sheets always goes in: the grid
marks, the mesocycles and the goals. Then the sheets go in one day at a time, starting
from today and moving outward (today, tomorrow, yesterday, the day after, two days ago…),
until the next sheet would pass the budget that step 0 sets. It is Friday, and the budget
fits five weeks of sheets. Tapping a day from late August then shows: "This day's details
did not fit. Days from 11 Sep to 16 Oct have them."

This is the only rule, and it applies whatever the budget is. A month with long
descriptions just keeps fewer days of sheets.

**Freshness.** The bot builds the keyboard again with every message it sends
(DESIGN_gym_logger.md §6), so the button always carries the snapshot of the bot's last
message. It is Friday afternoon. The morning message went out at 07:02, and she ran at
noon. The calendar still shows the run as not done yet, and the stamp says "as of Fri
07:02". Any message to the bot brings a fresh button. A refresh button on the page is not
handled.

## 6. The button

The calendar takes the place of "🗓 My week" in the companion keyboard, as "🗓 Calendar".
Both answer "what does my week look like"; keeping both would give the athlete two buttons
whose difference takes more than one sentence to explain. The other buttons stay as they
are. "📅 Today" and "✅ Done lately" answer in the chat, which works when the page cannot
load.

"🗓 My week" also carried the offer to plan the next weeks when the schedule runs out
(DESIGN_runway_nudge.md §6). After the swap, that offer comes from the morning push, which
repeats it every morning until she acts, and from "my week" typed in her own words, which
the router still sends to `workout list` (`show_week` in `chat/routing.py`).

The button is a `(label, url)` cell, built in `simple_keyboard_rows` the way the gym cell is,
and turned into a `KeyboardButton` with a `WebAppInfo` by `reply_keyboard` in
`chat/telegram_api.py`. The "🗓 My week" entry leaves `SIMPLE_KEYBOARD`, and the calendar
cell takes its place in the layout. `SIMPLE_KEYBOARD` keeps its shape of label and
command. The companion card, which teaches the keyboard label by label, gets the new label.

**When building or sending fails.** Two things could lose a reply today: an exception while
building the calendar button, and a keyboard Telegram refuses as too long. Both would reach
the athlete as "Internal error", and her answer would be gone. So a keyboard that fails to
build is left off, and a send Telegram refuses ("Bad Request") goes again without the
keyboard. The phone keeps the keyboard it already has, and the error goes to the journal.
Any other failure, such as a timeout, is not retried: the text may already have arrived,
and sending it again would show it twice.

The page lives beside the gym logger: `miniapp/calendar.html`, `miniapp/calendar.js` and
`miniapp/calendar.css`. The Pages deploy already copies `miniapp/` and stamps every
`miniapp/*.html` and `miniapp/*.js` with the commit, so it needs no change for files at
that level. The page's address is built in, like the gym logger's `PAGE_URL`.

## 7. `sm calendar`

```
sm calendar [DATE] [--no-pull]
```

It prints the month holding DATE (today by default) as a grid of seven columns, Monday
first, eleven characters each. First it refreshes the Garmin data over the month's days up
to today, the way `workout list` does, with the same `ensure_data` call, so the grades are
current; `--no-pull` skips that, as it does for `workout list`. A cell has two lines:

```
 25 ◆•       26
 🚴 Hills ✓  +🥾
```

The first line is the day number, then ◆ for a constraint and • for a signal. The second is
the icon and the label (§3.1), then the grade in expert marks: ✓ done, ½ partial, ✗ missed.
A kept rest day has no mark. An activity nobody planned is its icon after a "+", and when
the cell has no room for it the label goes first. Two sessions show two icons and no
label, as on the page. When a mesocycle starts inside the month, a line under that week
says "── <name> starts Thu 1 Oct". The header gives the month and the nearest goal ahead.

A day's detail in the terminal is `workout list -d <date> -vv`, which already prints the
description, what Garmin recorded, the grade and its reasons. `sm calendar` does not repeat
it.

The command lives in `stamind/cli/calendar.py` and is registered in `stamind_cli.py`. A
command module never imports `cli/render/`, so the grid itself is
`cli/render/calendar_grid.py`, printed through `ExpertRenderer.calendar_month`.

## 8. Step 0: measure the limit

Before the budget is set, the author measures what a button can carry:

- A probe page, `miniapp/probe.html`, prints how many bytes it received after `#`. It is
  published through the Pages deploy, which needs a push the author approves, and deleted
  after the measurement.
- The prototype bot (`STAMIND_CONFIG=config.proto.yaml ./sm-bot`) sends one keyboard with
  four buttons, whose addresses carry 16, 32, 64 and 128 KB of filler. `config.proto.yaml`
  is copied from the gym-logger worktree, where it lives outside git.
- The author taps each button on the phone and in Telegram Desktop, and writes down whether
  the bot could send the keyboard at all, and the largest size that opened with every byte
  intact.

**The result, 2026-09-26.** The Bot API refuses a reply keyboard with "reply markup is too
long" once the whole keyboard passes about 9.9 KB: it took 9,921 bytes of address and
refused 9,984. The limit counts the whole keyboard, so the gym button's address and the
labels share it with the calendar. The budget is therefore 6 KB.

With the full workout text in each sheet, only five days fit in 6 KB: the grid marks for
the ten weeks take 1.5 KB and each sheet about 900 bytes. The author chose to drop the
workout text from the sheets instead. Without it, the whole window packs into 5.5 KB on the
author's database, so every day in it has its sheet. The budget rule of §5 stays, for a
month with more to say.

## 9. Where things live

- `stamind/calendar_days.py` — the list of days (§4).
- `stamind/cli/render/calendar_page.py` — the page's words, the snapshot, its packing and
  the budget rule (§5).
- `stamind/cli/calendar.py` — `sm calendar` (§7), registered in `stamind_cli.py`.
- `stamind/chat/keyboards.py`, `stamind/chat/app.py`, `stamind/chat/replies.py` — the
  button and the send guard (§6).
- `miniapp/calendar.*` — the page, with node tests beside the gym logger's in
  `miniapp/tests/`. `miniapp/probe.html` for step 0.
- The short name (§3.6), everywhere a session's fields are listed by hand:
  - the week planner's answer format: `## RESPONSE FORMAT` in `coach/engine/generate.py`,
    `schema_members` in `coach/engine/adapt.py`, and the "write each session in full"
    line of the tweak task in `coach/engine/notes.py`;
  - `structure_revision` in `coach/revisions.py`, and the `change.append(...)` calls in
    `coach/service/generate.py` and `coach/service/revision_apply.py`;
  - the rows the strength planner builds in `strength/planner.py` `_write`;
  - `WorkoutChange.append` and `REVISION_COLUMNS` in `db/workout_change.py`, `_hydrated`
    in `db/workouts.py`, and the `Workout` type in `types.py`;
  - the `workouts` table in `db/schema.py`, and the one-off migration script under
    `scripts/`.
- `docs/ARCHITECTURE.md` — the new modules, `sm calendar` in the command table, the
  `short_name` column, and the calendar in the row on who reads the adherence grade.

## 10. Tests

The shapes worth pinning: the snapshot's packing survives a round trip; the budget rule
keeps the sheets nearest today; the list of days on a fixed week, including a day with two
sessions and one with an unplanned activity; the keyboard with the calendar cell in place of
"🗓 My week"; the send guard sending the text again when the keyboard fails; `append`
taking `short_name` as given and never counting it as a change; the migration adding the
column once. On the page, the node tests cover reading `c=` next to Telegram's own
parameters, the tint, and the two-session rule.

## 11. Not handled, not decided

- **The full workout text of a day other than today.** It is not in the sheet (§8). A
  "Full session" link that asks the bot for it in the chat is not handled.

- **Editing** from the calendar: moving or dropping a session, or adding a constraint on a
  tapped day. The first edit will need the page to send data back, as the gym logger does.
- **Replacing Google Calendar.** The daily signals are read from Google Calendar events
  (DESIGN_calendar_signal_ingest.md), so replacing it means a new way to record them first.
- **Offline.** The data is in the address, but the page's files come from GitHub Pages.
  With no connection, the page opens only while Telegram still holds its files. Google
  Calendar stays the offline view.
- **Expert mode in Telegram** has no keyboard, so no button (§2).
- **A long constraint** marks every day it covers. A five-week "no long climb nearby" puts
  a diamond on 35 days. It is true on each of them, so it stays.
- **A terminal that draws an emoji one column wide** shifts that row of the grid. If it
  bothers, the fix is letters in the terminal grid.
- **The web dashboard** (`stamind_web.py`) could use the same list of days. Not in this
  design.
