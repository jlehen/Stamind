# Design: Deload weeks the plan dates

**Status:** Built 2026-10-30, five choices ruled the same day (§7) · **Date:** 2026-10-19 ·
**Branch:** worktree-deload-weeks-design

A **deload** is a lighter recovery week: it cuts volume much more than intensity, so the
fatigue of the loading weeks before it clears (`stamind/science/periodization.md`). Today a
deload exists only as words. `plan generate` writes it into a mesocycle's name or focus, such
as "2 loading weeks + deload", and the week planner, the model call inside `workout generate`
and `workout adapt` that writes the sessions, follows those words.

This design makes `plan generate` give each mesocycle's deload a first day. The deload runs
from that day to the mesocycle's last day. The date is stored with the mesocycle. Every model
call that is shown the plan's mesocycles sees it, and the calendar draws the deload's days
with a dashed strip in the mesocycle's colour.

## 1. The problem

It is Monday 19 October. A new mesocycle starts today: "HIIT Block 1 — Aerobic Capacity (2
loading weeks + deload)", 19 October to 8 November. Its deload is its third week, 2 to 8
November. The athlete looks back for the last light week, and finds 14 September:

| Week of          | Load             | Kind    |
|------------------|------------------|---------|
| 14 Sep           | 243 done         | light   |
| 21 Sep to 12 Oct | 310 to 433 done  | loading |
| 19 Oct, 26 Oct   | 339, 381 planned | loading |
| 2 Nov            | 255 planned      | deload  |

Six loading weeks in a row, in a plan built on two loading weeks to one deload. Each
mesocycle looks right on its own. The one before today ran from 1 to 18 October and had no
deload, because it was short and hosted an FTP re-test. The guideline allows that: "some
mesocycles — typically short, low-volume ones — carry no scheduled deload at all". Nothing
says the loading weeks of that mesocycle count toward the next one's deload. So the count
restarted on 19 October, and the deload landed three weeks later.

Two things went wrong, and this design fixes both:

1. **The count restarts at every mesocycle.** `plan generate` places each deload inside its
   mesocycle, counting from the mesocycle's first day.
2. **Nobody can see where the deloads are.** The athlete found the gap by adding up weekly
   loads. The calendar shows a mesocycle's colour, not its deload. The week planner, writing
   the rest of a mesocycle, has to guess whether its deload already happened from a dip in
   the planned load (DESIGN_mesocycle_progress.md §3.2).

## 2. The rule

> `plan generate` gives each mesocycle at most one deload, and the deload is the mesocycle's
> last days. It is stored as one date, `deload_start`, the deload's first day; the deload runs
> to the mesocycle's last day. `plan generate` places it by counting the loading weeks since
> the athlete's last lighter week, across mesocycle boundaries. When the count brings a
> deload forward, the mesocycle is shortened so that it ends with the deload. Every model
> call that is shown the plan's mesocycles sees the date, and the calendar draws the deload's
> days with a dashed strip.

With the rule, the same Monday goes differently. The athlete runs `plan generate -f`. It reads
the weekly loads of the mesocycle that ended yesterday: two and a half loading weeks and no
deload. The counting rule says a deload is overdue. The new mesocycle starts today with
nothing trained, so `plan generate` writes a shorter first mesocycle that ends with a deload,
this week or next. The athlete opens the calendar and sees those seven days with a dashed strip.

## 3. How `plan generate` places a deload

### 3.1 The counting rule, in the guideline

`stamind/science/periodization.md`, "Mesocycle Loading Progressions", after the sentence
that allows a mesocycle with no deload:

```
The run of loading weeks is counted across mesocycle boundaries, never restarted at a
mesocycle's start. A mesocycle with no deload of its own hands its loading weeks to the next
one, so that mesocycle's deload comes earlier. Count from the last week the athlete actually
trained lighter, whichever mesocycle it fell in. A lighter week that recurs on a fixed
rhythm, where the athlete's guidelines alternate a heavier and a lighter week, is the
microcycle and does not end the run.
```

It is the app's guideline, so it holds for every athlete and every loading-to-recovery ratio.
The ratio stays a plan choice, as the guideline already says. The last sentence is the
heavier-and-lighter clause the week planner's prompt carries today (§4.2), moved to where
the counting now happens.

### 3.2 The task and the response

In `plan generate`'s TASK (`coach/engine/planning.py::_plan_generate_strategy`), after the
paragraph about aligning a deload week with a long trip:

```
Give each mesocycle at most one deload, as its last days: give the deload's first day as
deload_start, and it runs to the mesocycle's end date. Place each deload by counting the
loading weeks since the athlete's last lighter week, read from the weekly load lines in
PRIOR TRAINING REVIEW and the deloads in PREVIOUS PERIODIZATION STRATEGY, and carry that
count across every mesocycle boundary. When the count brings a deload forward, shorten the
mesocycle so that it ends with the deload.
```

The sentence names only the sections the prompt holds: a first plan has neither section, and
`--fresh` withholds the previous plan.

`plan generate` already has the numbers. Its prompt section PRIOR TRAINING REVIEW shows each
week's planned load beside the load produced, for the mesocycle that finished last and the
one under way. An older mesocycle appears there only as a short record with no weeks (§6).
The previous plan's section will show its dated deloads (§4.2).

Lining a deload up with a trip, which the TASK already allows, becomes ending the mesocycle
on the trip's last day. A recovery week straight after a race becomes a short mesocycle whose
deload starts on its first day.

The response format gives each mesocycle one more key, named like the column (§4.1), so the
mesocycle dictionaries reach `save_macrocycle` with no renaming; it reads the key with
`.get`:

```
      "deload_start": "YYYY-MM-DD, the first day of the deload that closes this mesocycle
        (it runs to end_date), or null when this mesocycle has none"
```

### 3.3 The mesocycle already under way

When a replan runs mid-mesocycle, the section titled THE MESOCYCLE ALREADY UNDER WAY quotes
the mesocycle with its dates and focus, and asks the model to keep its name, dates and focus
unchanged or to discard it. That section gains a line `Deload: from 2026-11-02`, or
`Deload: none`, and these sentences:

```
Its deload follows one rule. A deload whose first day is on or before today stays as it is:
the athlete is in it. If its deload has not started, or it has none, give this mesocycle its
deload by the counting rule, starting today or later. To bring its deload forward, end this
mesocycle on the deload's last day, earlier than its original end date. Its start date, name
and focus stay unchanged, and your next mesocycle starts the day after.
```

The bullet of that section that asks for "its original end date" gains "unless you end it
earlier to bring its deload forward". The start date is the part that must not move:
mesocycles own their sessions by the dates they contain, keyed on the start
(DESIGN_mesocycle_progress.md §7). It is Thursday 22 October, and HIIT Block 1, 19 October
to 8 November, has no deload date. The count says a deload is overdue. The model ends HIIT
Block 1 on Sunday 1 November with its deload from Monday 26 October, and the next mesocycle
starts on 2 November. Without the earlier end, the only deload the model could give it would
run from today to 8 November, eighteen days, or start a week late.

It is Wednesday 4 November, 09:00, and the deload runs from Monday 2 to Sunday 8 November.
The athlete edits a goal and runs `plan generate`, which keeps the mesocycle. The deload has
started, so it stays. Without the rule, the model could move it or drop it, and Monday and
Tuesday would have been light for nothing. A deload that is over cannot be moved: it ended
with its mesocycle, which is then no longer under way.

`plan_generate` (`coach/service/planning.py`) holds the first half in code, because this is
the one place where a wrong answer rewrites the past. When the model returns a mesocycle
with the start date of the mesocycle under way, and that mesocycle's stored deload has
started, the stored `deload_start` and `end_date` are copied onto it, whatever the model
returned: a started deload stays as it is only if its mesocycle's last day stays too. If the
model's next mesocycle then overlaps, the repair pass of §3.4 moves its start, with its usual
note. "Today" is `clock.today_str()`, the athlete's day in the instance's time zone. The copy
happens before the preview, so the preview shows what will be saved.

The section exists only for a mesocycle that started before today. On Monday 19 October the
new mesocycle starts that day, so nothing is under way and §3.2 alone applies. The same
story told on Tuesday 20 October or later goes through this section: the mesocycle under way
has no deload date, since its plan was written before this design, and the counting rule
gives it one.

### 3.4 Checking what came back

`plan_apply` already repairs the mesocycle dates the model returned
(`db/periodization.py::repair_mesocycle_contiguity`) and prints a note for each repair.

When the pass moves a mesocycle's start later, a deload whose first day the new start
overtook moves to the new start, and the move's note says so. The race is on Sunday 25
October. The model writes a Recovery mesocycle from that same Sunday, with its deload from
25 October. The pass moves Recovery's start to Monday 26 October, and the deload's first day
moves with it, so the week after the race stays a deload.

The pass then drops a deload whose first day is not a `YYYY-MM-DD` date inside its mesocycle,
and prints a note in the same form:

```
Note: mesocycle dates repaired — dropped the deload of 'HIIT Block 1' (from 2026-11-10): it
starts after the mesocycle, which ends 2026-11-08.
```

A first day the model itself wrote outside its mesocycle is not moved. It is a guess about
the model's intent, and a mistyped year must not turn a whole loading mesocycle into a
deload. The note lets the athlete run `plan generate` again.

## 4. Where the date lives and who reads it

### 4.1 The table

`mesocycles` gains one column, `deload_start`, TEXT `YYYY-MM-DD`. NULL means the mesocycle
has no deload. Otherwise the deload runs from `deload_start` to the mesocycle's `end_date`.

The schema is CREATE-only (ARCHITECTURE.md §5), so `SCHEMA_VERSION` goes to 30, and the
column reaches an existing database through the one-off `scripts/migrate_calendar_columns.py`.
Its `COLUMNS` list already adds `mesocycles.summary`, and gains `mesocycles.deload_start`. It
adds only the columns that are missing, ignores the version stamp and calls no model.

The author runs the script on both instances right after the merge, before the bot restart.
Readers take the date with `.get`, as they take `summary`.

Nothing is backfilled: a plan written before this design has no deload date. Reading one out
of a mesocycle's name would be a guess. `plan generate -f` writes it; a plain `plan generate`
reuses a plan whose inputs did not change (§9, step 7).

`plan rollback` copies no rows: it makes an older version active again, and the column
travels with that version's mesocycles.

### 4.2 The model calls

Four places write a mesocycle into a prompt with the same line, "name (start to end):
focus". One function in `coach/formatting.py`, `mesocycle_text(m)`, writes that line and
ends it with `Deload 2026-11-02 to 2026-11-08.` when the mesocycle has one. The four places
call it:

- `coach/service/athlete_context.py`, twice: the plan `workout generate` is shown, built from
  the mesocycles its span falls in, and the plan of the goal ahead, which `workout adapt`
  and `workout tweak` are shown.
- `coach/engine/planning.py`, twice: the previous plan `plan generate` reads, and the plan
  the staleness verdict call reads.

The mesocycle under way has a layout of its own, and gets its own `Deload:` line (§3.3). The
strength planner, the call that writes a strength session, reads the mesocycle's name, dates
and week number but not its deload. It learns of a deload from the brief, as it already
learns of any light week. The retrospective writer, which writes the record of a finished
mesocycle, reads its name, dates and focus only.

**`workout generate`'s TASK** today says "incorporate any deload weeks or exceptions for the
athlete's active constraints in accordance with the science guidelines". It becomes:

```
write each mesocycle's deload on the dates the plan gives it; a mesocycle the plan gives no
deload date has no deload, whatever its name or focus says. Incorporate any exceptions for
the athlete's active constraints in accordance with the science guidelines.
```

**One paragraph is deleted.** The CONTINUING A MESOCYCLE ALREADY UNDER WAY section
(`coach/engine/generate.py::_mesocycle_progress_task`) guesses whether the mesocycle already
had its deload:

```
If one elapsed week's planned load dips clearly below the weeks around it, that week WAS this
mesocycle's deload — do not schedule a second one; if no such dip has happened yet and the
mesocycle's design calls for one, it still belongs in the weeks you are writing. A dip that
recurs on a fixed rhythm — every other week, where the athlete's guidelines alternate a
heavier and a lighter week — is the microcycle, not the deload: the deload is the one-off dip
below that rhythm.
```

The date now says where the deload is, so the guess goes. The sentence before it, "carry the
ramp on from where the last completed week left it", still reads right: the deload is a
mesocycle's last days, so a mesocycle still under way has only loading weeks behind it.

**`workout adapt` gets no new text.** `training_load.md` already tells it a low load in a
planned deload is not a fault to correct. The date now tells it which week is planned.

**Benchmark placement does not change.** BENCHMARK PLACEMENT, the part of `workout
generate`'s TASK that places fitness tests, puts a test in a mesocycle's last week, and the
warning for a boundary week without a test looks there too. The deload is a mesocycle's last
days, so the test lands at the deload's end, which `benchmarks.md` names as the best slot.

## 5. What the athlete sees

### 5.1 The calendar page

It is Wednesday 4 November. The athlete opens the calendar. Every cell from Monday 2 to
Sunday 8 November has its strip in the mesocycle's colour, dashed where the days around it
are solid. Under the grid, the legend shows the mesocycle's row, and under it a row with a
striped swatch of the same colour: "Deload · 2 Nov – 8 Nov". The cells' background tint does
not change: it still shows how each session went against its plan.

- **The snapshot**, the packed data the calendar button carries to the page, gives a
  mesocycle with a deload one more key, `"d": "2026-11-02"`. `header`, in
  `cli/render/calendar_page.py`, builds both the button's snapshot and the index file in the
  bucket, so both carry `d`. The snapshot version stays 1: a page that does not know the key
  ignores it. The key costs about 18 bytes per mesocycle with a deload, and `fit` keeps the
  snapshot inside the 5 KB budget, as it does today.
- **The page** (`miniapp/calendar_logic.js`) counts a day as a deload day when it falls from
  `d` to `e`, the mesocycle's last day, the way it already finds the day's mesocycle. `calendar.js`
  adds the class `deload` to that day's strip and to the legend's swatch, and `calendar.css`
  cuts it into dashes with a mask, whichever of the six colours it has.
- **The legend** gives a deload that touches the month its own row, under its mesocycle's.

The page is published through the Pages deploy, which needs a push the author approves.

### 5.2 The terminal

- **`sm calendar`** prints `── Deload Mon 2 Nov to Sun 8 Nov` under the week the deload
  starts in, the way it already prints `── <name> starts Thu 1 Oct`
  (`cli/render/calendar_grid.py`).
- **`plan generate`'s preview and `plan show`** print a `Deload` line with the dates and the
  length in days under the mesocycle's head, `Deload Mon 2 Nov to Sun 8 Nov (7 days)`
  (`cli/plans/generate.py`, `cli/plans/show.py`). The athlete accepts a plan after seeing
  where its deloads fall, and a `deload_start` written two weeks early shows as a 21-day
  deload. The preview prints `Deload: none` under a mesocycle without one, so a model that
  ignores the key is noticed before the plan is accepted.
- **After a plan is applied**, `plan generate` names the command that rewrites the sessions
  already written. It is Monday 26 October, the schedule is written to Sunday 15 November,
  and a replan dates a deload from 26 October to 1 November. The calendar draws that week
  dashed at once, over the intervals the old plan wrote. A bare `workout generate` starts the
  day after the written schedule ends (`cli/workouts/generate.py::_resolve_span`), so it
  would never reach that week. When sessions are written past today
  (`cli/runway.py::schedule_coverage`), the closing line becomes: "Sessions are written up to
  Sun 15 Nov under the old plan. Run `workout generate -d today..2026-11-15` to rewrite them
  under this one." The range ends on the last day written, so the call rewrites those days
  and no more; `-g` would also write every day from 16 November to the goal's date. With no
  session written past today, the line stays as it is today. The two lines that repeat the
  bare command after a replan, in `cli/constraints.py::_run_replan_flow` and
  `cli/plans/feedback.py::_feedback_replan`, are deleted: the closing line already prints
  whenever a plan is applied.
- **`plan diff`** reports a deload added, removed or moved as a field change of that
  mesocycle: the column joins the field list `plan_versions.py::_diff_mesocycle_pair`
  compares.

## 6. Not handled

- **Rolling back to a plan written before this design.** Its mesocycles have no deload date,
  so the week planner writes no deload in them, whatever their names say. Run `plan generate`
  instead.
- **A deload trained through, or a week lost to illness or travel**, does not move the dated
  deload. The next `plan generate` counts from what was trained.
- **A run of loading weeks older than the mesocycle that finished last.** `plan generate`
  sees it only as a short record, so the count can come out short and the deload lands a
  week late.
- **A later goal's plan.** Its weeks are not trained yet. Only a goal with no plan of its own
  yet is shown the plan before it, in PREVIOUS PERIODIZATION STRATEGY; a replan of it sees
  its own previous version, so its count starts on its own first day. After a race, the
  taper was the lighter week, so nothing is lost. After a training horizon, which ends with
  no taper, the count restarts at the later goal's first day.

## 7. Choices made without asking

The author ruled on choices 2, 4, 5, 11 and 12 on 2026-10-30, and each says so. The others
stand as written until the author says otherwise.

1. **At most one deload per mesocycle.** This matches the usual definition: a mesocycle is a
   run of loading weeks closed by its recovery week. A long base phase with two deloads
   becomes two mesocycles. The other way is a list of deloads per mesocycle, which costs a
   little more in every place that reads the dates.
2. **One date column, `deload_start`, and the deload runs to the mesocycle's last day.**
   *Ruled by the author: one date.*
   *Changed by the review:* the first version stored a first and a last day, which could also
   hold a deload in the middle of a mesocycle. Choices 1 and 11 already ask for the deload at
   the end, and one column makes that the only shape the data can hold. It removes a column,
   three of the four cases the check in §3.4 had to catch, the clip-or-drop question of
   choice 4 for a deload that overran its mesocycle's end, and a sentence about where the
   ramp resumes. What the athlete loses: a six-week
   mesocycle with its deload in week 3 becomes two three-week mesocycles, with the same
   sessions and two strip colours, and one more "how did it go?" question, since each
   finished mesocycle but the plan's last gets one (`cycle_records.py`), and one more
   boundary week for BENCHMARK PLACEMENT to weigh. Both versions keep the deload out of a
   per-week flag, which would need the code to decide what a week is: the mesocycle before
   today started on a Thursday.
3. **Only `plan generate` writes the date.** No code guesses a deload from the load or from a
   mesocycle's name, and old plans are not backfilled.
4. **A deload whose first day the model wrote outside its mesocycle is dropped with a note,
   and one the date repair overtook moves with the new start** (§3.4). *Ruled by the author:
   the objection is taken.* The first version dropped both. The repair pass can move a
   mesocycle's start past its deload's first day. A Recovery mesocycle written from Sunday 25
   October, the race mesocycle's last day, has its start moved to Monday 26 October, and its
   deload from 25 October would be dropped: the week after the race would be told it has no
   deload. Moving the first day costs one assignment in the branch of the repair pass that
   moves a start. Only a first day the repair pass overtook moves, so a mistyped date cannot
   turn a whole loading mesocycle into a deload. An earlier objection proposed clipping a
   deload that overran its mesocycle. With one column a deload cannot overrun its
   mesocycle's end, so there is nothing to clip.
5. **The deload of the mesocycle under way can be re-dated by a replan only before it
   starts** (§3.3), even though its name, start date and focus are kept. *Ruled by the
   author: both rules, the started deload stays and the mesocycle may end earlier.*
   *Narrowed by the review:* the first version let a replan move a deload that had already
   started, which could erase half a deload the athlete was in. A started deload stays, in
   the prompt and in code. *Changed by the second review:* a kept mesocycle may end earlier
   than its original end date to bring its deload forward. With one date column this is the
   only way a replan can bring the deload of the mesocycle under way forward.
6. **A dashed strip in the mesocycle's colour, not a new tint.** *Ruled by the author on
   2026-10-30, after seeing it built.* The first version was a paler strip at 40% opacity,
   because the author had asked for a colour. A paler strip looks like a tint: the first
   strip's blue is the very colour of the "Less than planned" tint, and pale orange is nearly
   "More than planned". The other way is a solid strip, darker in a light theme and brighter
   in a dark one. In a dark theme it turns orange to yellow and grey to nearly white, and it
   can vanish where Telegram's theme differs from the phone's. The dashes look the same in
   both themes, and colour-blind readers can tell them apart too.
7. **The legend gives each deload its own row.** The other way is one fixed key line, "dashed
   strip: deload week", which the reader has to match to the cells.
8. **The calendar only, on the companion side.** The "Goals & plan" page, the chat's plan
   view, `sm status`, the web dashboard's plan page and the retrospective records show no
   deload. Each could later take the same date. The web dashboard's plan diff shows a moved
   deload already, since it prints changed fields as they come.
9. **A week cut short by illness is not drawn as a deload.** It was not planned, and its blue
   tint already says the athlete trained less than planned.
10. **The heavier-and-lighter clause moves into the guideline** (§3.1), since the counting now
    happens in `plan generate` and the week planner's guess is deleted.
11. **A deload closes its mesocycle** (§2): when the count brings a deload forward, the count
    moves the boundary, not the deload. *Settled by the author's ruling on choice 2:* one date
    can hold no other shape. Added by the review. The other way is to allow a deload anywhere
    and move the boundary fitness test to the deload's last day. That changes BENCHMARK
    PLACEMENT, the warning for a boundary week without a test, DESIGN_benchmark_workouts.md and
    DESIGN_mesocycle_progress.md §4.1.
12. **A past deload keeps its dashed strip only while the plan version that dated it is
    active.** *Ruled by the author: left out of this design.* The other way below fixes every
    past strip, so it would be a small change of its own. Added by the second review. The
    calendar draws only active plan versions
    (`db/mesocycles.py::_get_covering_mesocycles`), so every `plan generate`, step 7 on the
    build day included, takes the strip off the days before the new plan, as it does for
    every strip today. When the replan keeps the mesocycle under way, the strip goes up to the
    day before that mesocycle, which is where the previous mesocycle's deload was. It is
    Friday 13 November, the athlete replanned on Thursday, and the deload of 26 October to 1
    November no longer shows. The other way: each mesocycle's retrospective record also keeps
    its `deload_start`, and the calendar draws the days before the active plan from the
    records. That costs a column on `retrospectives`, the field in both record writers, a
    past list in `calendar_days.gather`, and keeping the strip colours of the calendar and the
    "Goals & plan" page in step. It brings back every past strip, deload or not.

## 8. Amendments to other documents

Applied in the build commit, so no document describes behaviour the code does not have yet.

- **DESIGN_mesocycle_progress.md.** §3.2 "No deload label" gets an amendment: "Amendment,
  2026-10-19. The plan now dates each mesocycle's deload (DESIGN_deload_weeks.md). The week
  planner reads the date, so the dip rule above and its fixed-rhythm clause are gone from the
  prompt. The fixed-rhythm clause now sits in `periodization.md`'s counting rule, where `plan
  generate` reads it." §4 asks for two things instead of three: the sentence "treat a clear
  dip in an elapsed week as the deload already taken" goes, with a pointer to this design.
- **DESIGN_mesocycle_progress.md** §7 gets an amendment too: "Amendment, 2026-10-19. A kept
  mesocycle may now end earlier than its original end date, when `plan generate` brings its
  deload forward (DESIGN_deload_weeks.md §3.3). Its start date, which everything in this
  section keys off, stays."
- **DESIGN_calendar_miniapp.md.** §1's strip paragraph and §3.1's third item say a deload day's
  strip is dashed and the legend gives the deload its own row. §5's snapshot shape shows `d`,
  with one bullet: "`d` is the first day of the mesocycle's deload, which runs to `e`, when
  the plan dates one." §7 gives the `── Deload` line.
- **docs/DOMAIN_MODEL.md.** The mesocycle field table gains `deload_start`, and "five
  meaningful columns" loses its number, which is already wrong. The list "Enforced by the
  code" gains: "A deload's first day lies inside its mesocycle, and the deload runs to the
  mesocycle's end; `plan_apply` moves a first day the date repair overtook, drops any other
  that does not fit, and prints a note." The sentence
  "There is no stored load target, no weekly hours, no intensity distribution, no deload
  flag" loses "no deload flag", and the next one says a mesocycle states what it is for and,
  when it has one, the first day of its deload. The line that says the alternation is one
  "the mesocycle-progress deload rule knows about" points at the counting rule in
  `periodization.md` instead.
- **docs/ARCHITECTURE.md.** The mesocycles table gains the column's line, pointing here.

Four designs use the word "deload" only in passing and need nothing:
DESIGN_benchmark_workouts.md, DESIGN_bot_simple_frontend.md, DESIGN_strength_tracking.md and
DESIGN_plan_change_continuity.md.

## 9. Build order

1. The column: `db/schema.py`, `types.py::Mesocycle`, `save_macrocycle`, the entry in
   `scripts/migrate_calendar_columns.py`.
2. `plan generate`: the guideline rule (§3.1), the TASK sentences and the response key
   (§3.2), the mesocycle under way and the copy-back in `plan_generate` (§3.3), the check
   (§3.4), the preview's `Deload` line, where the author checks this step's output, and the
   line printed after the plan is applied (§5.2).
3. The model calls: `mesocycle_text` and its four callers, `workout generate`'s TASK wording,
   the deleted paragraph (§4.2).
4. The terminal: `plan show`, `plan diff`, `sm calendar` (§5.2).
5. The page: the snapshot key, the logic, the strip, the legend (§5.1).
6. The amendments (§8).
7. On each instance, by the author, right after the merge: the migration script; then `sm
   plan generate -f -g ..N`, where N is the last upcoming goal, so that every upcoming goal's
   plan is written again, one strategy call each; then, once, the `workout generate` command
   that `plan generate` names after applying the plans (§5.2); a bot restart; and the Pages
   deploy.

## 10. Tests

- The repair pass moves a deload's first day when it moves the mesocycle's start past it, and
  says so in its note. It drops a first day the model wrote outside its mesocycle, or one that
  is not a `YYYY-MM-DD` date, and names it in its note.
- `save_macrocycle` stores the date, and the mesocycle reads back with it.
- `plan_generate` copies a started deload's first day and its mesocycle's end date back onto
  the kept mesocycle, and leaves a deload still ahead as the model returned it.
- `plan generate` names `workout generate -d today..<last day written>` after applying a plan
  when sessions are written past today, and the bare command otherwise.
- `mesocycle_text` ends its line with the deload when there is one, and not otherwise.
- The guessing paragraph is gone from the CONTINUING A MESOCYCLE section. The
  `assertIn("deload", task)` in `tests/test_mesocycle_progress.py` goes with it.
- `plan diff` reports a moved deload as a change of its mesocycle.
- `sm calendar` prints the `── Deload` line under the week the deload starts in.
- `miniapp/tests/calendar.test.mjs`: a day from `d` to the mesocycle's last day is a deload
  day and a day before `d` is not, and the legend gives a deload in the month its own row.
