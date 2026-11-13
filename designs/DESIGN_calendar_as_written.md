# Design: the calendar against what was written

**Status:** Proposed · **Date:** 2026-11-13 · **Branch:** `worktree-calendar-as-written`

## 1. The problem

It is Friday 13 November. The athlete opens the calendar. Monday 9, Wednesday 11 and Thursday 12
are green, like three sessions done. Only Thursday was written as a rest day. `workout generate`
wrote the heavy gym session for Monday; at the athlete's request that evening Monday became rest
and the gym session went to Friday. It wrote the HIIT ride for Wednesday; the coach made
Wednesday a rest day for a low HRV and moved the ride to Sunday 15. The week before, Friday 6 is
green too, though its light gym session was dropped when the athlete was unwell, and Sunday 8 is
orange: the athlete rode 72 minutes for the 40 the coach asked, though `workout generate` wrote
120 for that ride.

The calendar's tint answers "did I do what the coach asked that day?" (DESIGN_calendar_miniapp.md
§3.2). The athlete also wants it to answer the question the Progress page's Weeks tab answers:
"did I do what `workout generate` wrote?" (DESIGN_week_as_written.md, DESIGN_progress_page.md
§3.2), day by day, and to see where the coach departed from it.

## 2. The rule

Each cell has a fill and, on a day the coach changed, a corner.

**The fill compares with what `workout generate` wrote** (D1). The written version of a session
is the one DESIGN_week_as_written.md §3 finds: the slot walk, then the lineage, so a session that
moved keeps its written version wherever it now stands. The colours are the ones of today:
green within the grader's tolerance, blue less, orange more, the depth by how far
(DESIGN_calendar_miniapp.md §3.2).

- **A session that still stands** is graded against its written version, on the day it stands.
  Sunday 8's ride was written as 120 minutes on Saturday 7; done in 72 minutes on Sunday, it is
  blue. Friday 13's heavy gym session, written for Monday 9, is green once done as written.
- **A day whose written session moved to another day** has no fill for it: Monday 9 and
  Wednesday 11 are plain cards (D2).
- **A day whose written session was dropped is blue**, at full depth (D3): Friday 6, the light gym
  session the coach turned into "Rest Day — Unwell". A drop is never red
  (DESIGN_week_as_written.md D3). A written session the coach replaced with one of another
  sport counts as dropped, as the week grade's "replaced by" does; the session that took its
  place gives no fill. The day turns blue once it is over, as a kept rest day turns green.
- **A written rest day or yoga session that went is never blue**: these are the sports the week
  grade does not grade (`written_week.UNGRADED`). The session that took its place is graded
  against what the coach asked, as an added one. Friday 28 August was written as rest; the coach
  put a threshold ride there and the athlete rode it: the cell is graded as that ride.
- **A written session replaced on its day by another session of the same sport** gives that day
  no colour of its own: Friday 13's light gym session, replaced by the heavy one. The week's
  numbers count it (🏋️ 1 of 2), and the day's sheet says it went.
- **A rest day written and kept** is green once the day is over, as today (D4): Thursday 12.
- **A session the coach added**, with no written version, is graded against what the coach asked.
  A rest day the coach added gives no fill: Monday 9's.
- **A gym session graded by its sets** (DESIGN_strength_planned_vs_done.md §6) has one grade:
  its fill is the grade against what the coach asked, the live session whole. The strength
  planner may rewrite a session's exercises after `workout generate` wrote it, moved or not
  (Monday 2 November: 25 sets written, 27 asked), and the gym logger pairs the sets done with
  the live session's lines (choice 7).
- **A missed session**, one the coach still asks for that nothing was recorded for, keeps the red
  outline.

On a day with two sessions, the order of today holds: a miss wins, then the session furthest from
its plan, then green.

**The corner compares with what the coach asked that day** (D5). It is a small triangle in the
top right corner, coloured as the tint of today would colour the whole cell: green, blue or
orange. It appears on every day the coach changed, so the athlete sees each departure from what
was written (choice 1): a day whose written session moved away or was dropped, a day a session
moved to, a session the coach cut or lengthened, and a session the coach added. A change counts
when the live version's day, sport or load (`planned_load`) differs from the written version's;
a version that only rewords the session is not a change, nor a session moved and moved back
(Tuesday 10's easy ride). A corner appears once its day has a grade: a changed day still ahead,
or today before its session is recorded, has none yet. On a changed day whose session was
missed, the corner is red, the colour of the outline.

The two weeks, as the cells read with the rule:

| Day | Written | Now | Done | Fill | Corner |
|---|---|---|---|---|---|
| Wed 4 | HIIT ride | yoga, from Thu 5 | yoga | green (the yoga, as written) | green |
| Thu 5 | yoga | HIIT ride, from Wed 4 | HIIT ride | green | green |
| Fri 6 | light gym | rest (unwell) | rest | blue, full | green |
| Sat 7 | gravel ride, 120 min | yoga, from Sun 8 | yoga | green | green |
| Sun 8 | yoga | the ride, cut to 40 min | 72 min | blue, full: the load done under half the 80 written | orange, 72 for 40 |
| Mon 9 | heavy gym | rest, at the athlete's request | rest | none | green |
| Tue 10 | easy ride, 60 min | the same | 84 min | orange, as today | none |
| Wed 11 | HIIT ride | rest | rest | none | green |
| Thu 12 | rest | rest | rest | green | none |
| Fri 13 | light gym | heavy gym, from Mon 9 | heavy gym | green | green |

**The week's numbers** stand in an eighth, narrow column at the end of each week's row (D6): each
graded sport of a week that has ended, as the Progress page's Weeks tab gives it, such as
"🚴 82%" and "🏋️ 1/2", a short sport in amber. The week under way and a week with nothing written
show nothing. The numbers are `graded_weeks`' (`analytics/written_week.py`), so the calendar,
the Weeks tab and `sm progress weeks` agree.

In the chat's one sentence: the colour says how the day went against what was written, the corner
how it went against what the coach asked.

## 3. The day's sheet

A written session the coach changed adds one line to the sheet of the day it was written for.
The line is `changed_words`' when the grade has words for it: dropped, replaced, cut
(DESIGN_week_as_written.md §5). Otherwise it is "moved to Fri 13 Nov" and the reason of the
change. A session that moved in adds no line: its Planned part already shows it. A lengthened
or added session adds none. The line is appended to the sheet's Planned part. Friday 13:
"Full-Body Strength (Light): dropped, changed Mon 9 Nov: "As asked, today is rest and the easy
ride moves to Tuesday. I kept the heavy lift instead of the light one…"". Monday 9: "Full-Body
Strength (Heavy): moved to Fri 13 Nov, changed Mon 9 Nov: …". The lines are unwrapped, and
written only in the month files, as the workout text is (`sheet(..., texts=True)`): they quote
the reason whole, up to 400 characters, and would push the far days' sheets out of the address.

## 4. The terminal

`sm calendar` draws the same days, from the same list (D7). Its marks follow the fill: ✓ within
tolerance, ½ off it, ✗ missed, and – for a written session dropped. A changed day carries `*`.
On a day with two sessions: one mark per standing session in order, then one – per dropped
written session, then one `*` for the day. Both follow the page's timing (§2). Under an ended
week, a gray line gives its numbers as `sm progress weeks` lists them (`week_line`), in the
style of the line the grid already prints under a week a mesocycle starts in (choice 2, D9).

## 5. What does not change

- Google Calendar's events keep their tag ([Done], [Partial], [Missed]) against what the coach
  asked: each event is the coach's current session, and a moved session has one event, on its
  new day (D7).
- "✅ Done lately" in the chat stays the days against what the coach asked
  (DESIGN_progress_page.md D4).
- The Progress page.

## 6. Code

- **`stamind/calendar_days.py`**: `gather` reads `written_week` from the Monday of its first
  day's week, so a session moved into the first days keeps its written version. Each result of
  a `Day` gains `fill`: a result of the same shape with `planned` swapped for the written
  version and its own `status`; the result itself for a gym session graded by its sets and for
  a session with no written version (§2); None where §2 gives no fill. So `glyph`, `gap_ratio`
  and the terminal's `MARKS` work on it unchanged. `Day` gains the changed entries of the
  sessions written for it and a `changed` flag. `Calendar` gains the week numbers
  (`graded_weeks`).
  Measured on the author's copy: `gather` 35 ms over the bot's window, `written_week` 21 ms and
  `graded_weeks` 14 ms more, so each message the bot sends pays about 35 ms more
  (`chat/app.py:_page_buttons`). Accepted.
- **`stamind/analytics/written_week.py`**: one small public function giving a changed
  session's words, "moved to …" with its reason when `_what` has none; `_what` keeps saying
  nothing of a move inside the week, which the week grade relies on.
- **`stamind/cli/render/calendar_page.py`**: `_marks` writes the fill's grade per session, and
  on a changed day the coach's grade beside it; a dropped written session is one more fill
  grade. The page runs its one `tint` on each list, so the order of §2 has one home; a day with
  no coach's grade has no corner. The week numbers are a dict by Monday, each sport as text
  ready to show (`["🚴", "82%", 1]`, the last for short), built from `SportGrade` with
  `percent` and `sport_emoji`, not from `progress_page._sport`, whose long lines the address
  cannot afford and whose module imports this one. Each month file carries the numbers of
  every week touching its month; the address those of its window; the index file none. The
  sheet's changed lines, in the month files only.
- **`miniapp/calendar_logic.js`**, **`calendar.js`**, **`calendar.css`**: the corner, the eighth
  column, `withMonth` merging a file's weeks into those it holds (one spread), and
  the key under the grid: "Colour: against what was written. Corner: the coach changed this
  day; its colour is against what the coach asked."
- **`stamind/cli/render/calendar_grid.py`**: the marks of §4 and the week's line under it;
  **`stamind/cli/calendar.py`**: the help text names the new marks.
- **Docs**: DESIGN_calendar_miniapp.md §3.2 points here; `docs/ARCHITECTURE.md` (§17, the
  `calendar` row).

The packed address grows by the corners and the numbers. Today it uses 4,525 of its 4,864 bytes
(DESIGN_miniapp_storage.md §8), so it holds fewer day sheets; where the pages are published the
files carry them anyway. Measured before landing.

## 7. Choices made without asking

The author rules on each. A review may object in the last column; it may not remove or change
a choice.

| # | Choice | Why | Chosen over | Review |
|---|---|---|---|---|
| 1 | A corner on every day the coach changed, coloured as today's tint, even when it has the colour of the fill (Thursday 5, the ride moved from Wednesday and done: green fill, green corner) (§2) | The author kept the green corner "because it clearly indicates there was a deviation from `workout generate`"; a corner only where the colours differ would hide a move done as written | A corner only where the coach's ask gives another colour than the fill (mock-up 6) | Kept by the author over B, after both mock-ups (D8) |
| 2 | `sm calendar` prints an ended week's numbers on a line under it, `week_line`'s words (§4) | The grid fills 77 of 80 columns, and a line under a week already exists for a mesocycle's start | Numbers after the row, past 80 columns | Changed by the author to the reviewers' proposal (D9) |
| 3 | A dropped written session is blue at full depth (§2) | Nothing of it was done that day; the deepest blue is "half the plan or less" | A pale blue | |
| 4 | A rest day the coach added gives no fill, and a training session the coach added is graded against the coach's ask (§2) | There is no written version to compare with | Grading an added rest day green | |
| 5 | A written session replaced by another of its sport on its day gives no colour; the week's numbers and the sheet show it (§2) | The athlete's own reading: "the heavy strength is still present in the week, the light one went" | Blue for the light session on Friday 13 | |
| 6 | The terminal's marks: – for a dropped session, `*` for a changed day (§4) | The terminal has no corner; ✗ is a miss, and a drop is never one | A coloured mark | |
| 7 | A gym session graded by its sets has one grade, against what the coach asked (§2) | The gym logger pairs the sets done with the live session's lines, and the strength planner may rewrite a session's exercises after it was written, moved or not | Its sets against the written version's | Revised during the review: the first reason, that the strength planner rewrites a moved session's sets, was wrong (`strength/planner.py:171-177`) (thorough) |

## 8. Not handled

- A session written in a week before the first week read has no written version there: its day
  is graded against the coach's ask. A move across weeks did not happen once in the author's 146
  written sessions.
- A session re-recorded under another sport after it was written reads as dropped
  (DESIGN_week_as_written.md §7), so its day is blue though it went as asked: the kettlebell
  video of Friday 30 October, written as strength and re-recorded as hiit.
- A chain of swaps that hands a lineage to another session can grade a day against the wrong
  written version; the week's numbers are not affected.

## 9. Tests

- `calendar_days.gather` on the two weeks of §2: each row of the table, fill and corner; and
  rows for a changed day still ahead (Saturday 14), a missed session on a changed day, a training
  session added on an empty day, a written rest day replaced by a ride (28 August), and a
  two-session day with one written session dropped.
- The sheet's line for a moved session, and none for a session that moved in.
- The week numbers equal `graded_weeks`' for the same weeks; none for the week under way.
- `sm calendar`: the marks of §4, the week's line under an ended week.
- The page's logic under node: the fill's order on a two-session day, the corner, a dropped
  entry, the eighth column; a month file's weeks added to the address's, a week only the address
  holds kept.

## 10. After landing

The step after a command rebuilds only the months the window touches, so on each instance
`sm data publish` writes the older months again with their corners and numbers. Both bots are
restarted, since the bot builds the button's address.

## Decisions Log

| # | Topic | Decision | Why | Source | Date |
|---|---|---|---|---|---|
| D1 | What the fill compares with | The version `workout generate` wrote for each session | "Fill = written" (mock-up 5) | Athlete | 2026-11-13 |
| D2 | A day whose written session moved away | No fill | The rule of mock-up 6, "this looks okay" | Athlete | 2026-11-13 |
| D3 | A written session dropped or eased | Blue | "If the session was eased or deleted compared to what was generated, maybe show in blue" | Athlete | 2026-11-13 |
| D4 | A rest day written and kept | Green, as today | His answer | Athlete | 2026-11-13 |
| D5 | The coach's ask | A corner, green ones kept | "It clearly indicates there was a deviation from `workout generate`" | Athlete | 2026-11-13 |
| D6 | The week's grade | Numbers in an eighth column (mock-up 3) | His pick over a line under the row | Athlete | 2026-11-13 |
| D7 | Which views follow | The page and `sm calendar`; Google Calendar's tags stay against the coach's ask | His pick | Athlete | 2026-11-13 |
| D8 | Where a corner goes | On every day the coach changed, even when it has the fill's colour | Choice 1, mock-up A over B | Athlete | 2026-11-13 |
| D9 | The week's numbers in the terminal | A gray line under each ended week, `week_line`'s words | Both reviewers: the numbers after the row wrap on an 80-column terminal | Athlete | 2026-11-13 |
