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
  (DESIGN_week_as_written.md D3).
- **A written session replaced on its day by another session of the same sport** gives that day
  no colour of its own: Friday 13's light gym session, replaced by the heavy one. The week's
  numbers count it (🏋️ 1 of 2), and the day's sheet says it went.
- **A rest day written and kept** is green once the day is over, as today (D4): Thursday 12.
- **A session the coach added**, with no written version, is graded against what the coach asked.
  A rest day the coach added gives no fill: Monday 9's.
- **A gym session graded by its sets** (DESIGN_strength_planned_vs_done.md §6) compares the sets
  done with the sets the coach asked for, inside its written version: the strength planner
  rewrites them when the session moves, so Monday's sets would read Friday 13's heavy session as
  blue (choice 7).
- **A missed session**, one the coach still asks for that nothing was recorded for, keeps the red
  outline.

On a day with two sessions, the order of today holds: a miss wins, then the session furthest from
its plan, then green.

**The corner compares with what the coach asked that day** (D5). It is a small triangle in the
top right corner, coloured as the tint of today would colour the whole cell: green, blue or
orange. It appears on every day the coach changed, so the athlete sees each departure from what
was written (choice 1): a day whose written session moved away or was dropped, a day a session
moved to, a session the coach cut or lengthened, and a session the coach added. A change counts
when the day, the sport or the load differs from the written version, the test the week grade
uses (`written_week._changes`); a version that only rewords the session is not a change.

The two weeks, as the cells read with the rule:

| Day | Written | Now | Done | Fill | Corner |
|---|---|---|---|---|---|
| Wed 4 | HIIT ride | yoga, from Thu 5 | yoga | green (the yoga, as written) | green |
| Thu 5 | yoga | HIIT ride, from Wed 4 | HIIT ride | green | green |
| Fri 6 | light gym | rest (unwell) | rest | blue, full | green |
| Sat 7 | gravel ride, 120 min | yoga, from Sun 8 | yoga | green | green |
| Sun 8 | yoga | the ride, cut to 40 min | 72 min | blue, 72 of 120 | orange, 72 for 40 |
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

A tap on a changed day opens its sheet as today, with one more line per written session the
coach changed: the grade's words, which say what happened and why (DESIGN_week_as_written.md
§5). Friday 13: "Full-Body Strength (Light): dropped, changed Mon 9 Nov: "As asked, today is rest
and the easy ride moves to Tuesday. I kept the heavy lift instead of the light one…"".
Sunday 8: "Easy Gravel Ride: cut from 120 to 40 min, moved to Sun 8 Nov, changed Sun 8 Nov: …".
The line is the one `changed_words` builds, unwrapped as every page file is.

## 4. The terminal

`sm calendar` draws the same days, from the same list (D7). Its marks follow the fill: ✓ within
tolerance, ½ off it, ✗ missed, and – for a written session dropped. A changed day carries `*`
after its mark. A week's numbers follow its row, past the seven cells, since the grid already
fills 77 of 80 columns (choice 2).

## 5. What does not change

- Google Calendar's events keep their tag ([Done], [Partial], [Missed]) against what the coach
  asked: each event is the coach's current session, and a moved session has one event, on its
  new day (D7).
- "✅ Done lately" in the chat stays the days against what the coach asked
  (DESIGN_progress_page.md D4).
- The Progress page.

## 6. Code

- **`stamind/calendar_days.py`**: `gather` reads `written_week` over its window, and each `Day`
  gains the fill's grades (each session against its written version, a dropped written session,
  the days with nothing written left), whether the coach changed it, and the corner's grade (the
  grade of today). `Calendar` gains the week numbers (`graded_weeks` over the window).
- **`stamind/cli/render/calendar_page.py`**: `_marks` writes the fill's grades, the dropped
  entry and the corner; the month files and the address carry each week's numbers; the sheet's
  changed lines.
- **`miniapp/calendar_logic.js`**, **`calendar.js`**, **`calendar.css`**: the corner, the eighth
  column, the key under the grid (the corner, and blue for a dropped session).
- **`stamind/cli/render/calendar_grid.py`**: the marks of §4 and the numbers after each row.
- **Docs**: DESIGN_calendar_miniapp.md §3.2 points here; `docs/ARCHITECTURE.md` (§17, the
  `calendar` row).

The packed address grows by the corners and the numbers. Its budget is fixed
(DESIGN_miniapp_storage.md §8), so it holds fewer day sheets; where the pages are published the
files carry them anyway. Measured before landing.

## 7. Choices made without asking

The author rules on each. A review may object in the last column; it may not remove or change
a choice.

| # | Choice | Why | Chosen over | Review |
|---|---|---|---|---|
| 1 | A corner on every day the coach changed, coloured as today's tint, even when it has the colour of the fill (Thursday 5, the ride moved from Wednesday and done: green fill, green corner) (§2) | The author kept the green corner "because it clearly indicates there was a deviation from `workout generate`"; a corner only where the colours differ would hide a move done as written | A corner only where the coach's ask gives another colour than the fill (mock-up 6) || Kept by the author over B, after both mock-ups (D8) |
| 2 | `sm calendar` prints a week's numbers after its row, past 80 columns (§4) | The seven cells take 77 columns | An eighth column of 2 characters; numbers on a line under the row | |
| 3 | A dropped written session is blue at full depth (§2) | Nothing of it was done that day; the deepest blue is "half the plan or less" | A pale blue | |
| 4 | A rest day the coach added gives no fill, and a training session the coach added is graded against the coach's ask (§2) | There is no written version to compare with | Grading an added rest day green | |
| 5 | A written session replaced by another of its sport on its day gives no colour; the week's numbers and the sheet show it (§2) | The athlete's own reading: "the heavy strength is still present in the week, the light one went" | Blue for the light session on Friday 13 | |
| 6 | The terminal's marks: – for a dropped session, `*` for a changed day (§4) | The terminal has no corner; ✗ is a miss, and a drop is never one | A coloured mark | |
| 7 | A gym session graded by its sets takes the coach's sets (§2) | Found by a prototype on the author's data: Friday 13's heavy session, done as asked, read blue against Monday's sets | The written version's sets | |

## 8. Not handled

- A session that moved out of the window the calendar reads has no written version there: its
  new day is graded against the coach's ask.
- A session re-recorded under another sport after it was written reads as dropped
  (DESIGN_week_as_written.md §7).
- A chain of swaps that hands a lineage to another session can grade a day against the wrong
  written version; the week's numbers are not affected.

## 9. Tests

- `calendar_days.gather` on the two weeks of §2: each row of the table, fill and corner.
- The week numbers equal `graded_weeks`' for the same weeks; none for the week under way.
- `sm calendar`: the marks of §4, the numbers after the row.
- The page's logic under node: the fill's order on a two-session day, the corner, a dropped
  entry, the eighth column.
- The packed address stays within its budget.

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
