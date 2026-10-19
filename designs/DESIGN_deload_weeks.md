# Design: Deload weeks the plan dates

**Status:** Proposed · **Date:** 2026-10-19 · **Branch:** worktree-deload-weeks-design

A **deload** is a lighter recovery week: it cuts volume much more than intensity, so the
fatigue of the loading weeks before it clears (`stamind/science/periodization.md`). Today a
deload exists only as words. `plan generate` writes it into a mesocycle's name or focus, such
as "2 loading weeks + deload", and the week planner, the model call inside `workout generate`
and `workout adapt` that writes the sessions, follows those words.

This design makes `plan generate` give each deload a first and a last day. The dates are
stored with the mesocycle. Every model call that reads the plan sees them, and the calendar
draws those days in a paler shade of the mesocycle's colour.

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

> `plan generate` gives each mesocycle at most one deload, as a first and a last day inside
> the mesocycle. It places the deload by counting the loading weeks since the athlete's last
> lighter week, across mesocycle boundaries. The dates are stored with the mesocycle. Every
> model call that reads the plan sees them, and the calendar draws those days' strip paler.

With the rule, the same Monday goes differently. The athlete runs `plan generate -f`. It reads
the weekly loads it is already shown and sees no lighter week since mid-September. The
counting rule says a deload is overdue. The new mesocycle started today with nothing trained,
so `plan generate` can date its deload this week or next. The athlete opens the calendar and
sees those seven days in a paler shade.

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
Give each mesocycle at most one deload, as its first and last day, both inside the
mesocycle; a mesocycle without one gives none. Place each deload by counting the loading
weeks since the athlete's last lighter week, read from the weekly load lines in PLANNED vs
ACTUAL and from the deloads the previous plan dated, and carry that count across every
mesocycle boundary.
```

`plan generate` already has the numbers. Its prompt section PLANNED vs ACTUAL shows each
week's planned load beside the load produced, for the mesocycle that finished last and the
one under way. The previous plan's section will show its dated deloads (§4.1).

The response format gives each mesocycle two more keys, named like the columns (§3.4), so
the mesocycle dictionaries reach the database without a mapping step:

```
      "deload_start": "YYYY-MM-DD, the deload's first day, or null when this mesocycle has
        none",
      "deload_end": "YYYY-MM-DD, the deload's last day, or null"
```

### 3.3 The mesocycle already under way

When a replan runs mid-mesocycle, the section titled THE MESOCYCLE ALREADY UNDER WAY quotes
the mesocycle with its dates and focus, and asks the model to keep its name, dates and focus
unchanged or to discard it. That section gains a `Deload:` line with the mesocycle's deload
dates, or "none", and one sentence:

```
Its deload dates are not part of what "unchanged" keeps: place its deload by the counting
rule, like any other mesocycle's.
```

This is what fixes the athlete's Monday: the mesocycle under way has no deload dates, since
its plan was written before this design, and the counting rule gives it one.

### 3.4 Checking what came back

`plan_apply` already repairs the mesocycle dates the model returned
(`db/periodization.py::repair_mesocycle_contiguity`) and prints a note for each repair. The
same pass clears a deload that does not fit, and prints a note in the same form: a deload
with one date missing, a last day before its first, or a day outside its mesocycle once the
mesocycle's dates are repaired.

```
Note: mesocycle dates repaired — dropped the deload of 'HIIT Block 1' (2026-11-02 to
2026-11-10): it ends after the mesocycle, which ends 2026-11-08.
```

A dropped deload is not moved or clipped. A deload the model put in the wrong place is a
guess about the model's intent, and the note lets the athlete run `plan generate` again.

## 4. Where the dates live and who reads them

### 4.1 The table

`mesocycles` gains two columns, `deload_start` and `deload_end`, TEXT `YYYY-MM-DD`, both set
or both NULL. NULL means the mesocycle has no deload.

The schema is CREATE-only (ARCHITECTURE.md §5), so `SCHEMA_VERSION` goes to 29 and a one-off
script, `scripts/migrate_deload_columns.py`, adds the two columns with plain `sqlite3` on each
instance before the bots restart. It follows `scripts/backfill_plan_summaries.py`. It
backfills nothing: a plan written before this design has no deload dates. Reading them out of
a mesocycle's name would be a guess, and the athlete's next `plan generate` writes them.

`plan rollback` copies no rows: it makes an older version active again, and the columns
travel with that version's mesocycles.

### 4.2 The model calls

Five places write a mesocycle into a prompt with the same line, "name (start to end):
focus". One function in `coach/formatting.py`, `mesocycle_text(m)`, writes that line and
ends it with `Deload 2026-11-02 to 2026-11-08.` when the mesocycle has one. The five places
call it:

- `coach/service/athlete_context.py`, twice: the plan `workout generate` is shown, built from
  the mesocycles its span falls in, and the plan of the goal ahead, which `workout adapt`
  and the other calls that name a goal are shown.
- `coach/engine/planning.py`, three times: the previous plan `plan generate` reads, the
  mesocycle under way (§3.3), and the plan the staleness verdict call reads.

**`workout generate`'s TASK** today says "incorporate any deload weeks or exceptions for the
athlete's active constraints in accordance with the science guidelines". It becomes "write
each mesocycle's deload on the dates the plan gives it, and incorporate any exceptions for
the athlete's active constraints in accordance with the science guidelines". A mesocycle
with no dates has no deload.

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

The dates now say whether the deload is behind or ahead, so the guess goes.

**`workout adapt` gets no new text.** `training_load.md` already tells it a low load in a
planned deload is not a fault to correct. The dates now tell it which week is planned.

**Benchmark placement does not change.** `benchmarks.md` already names the end of a deload
week as the best slot for a test. The dates make that slot exact.

## 5. What the athlete sees

### 5.1 The calendar page

It is Wednesday 4 November. The athlete opens the calendar. Every cell from Monday 2 to
Sunday 8 November has its strip in the mesocycle's colour, paler than the days around it.
Under the grid, the legend shows the mesocycle's row, and under it a row with a paler swatch
of the same colour: "Deload · 2 Nov – 8 Nov". The cells' background tint does not change:
it still shows how each session went against its plan.

- **The snapshot** (`cli/render/calendar_page.py::header`) gives a mesocycle with a deload one
  more key, `"d": ["2026-11-02", "2026-11-08"]`. The snapshot version stays 1: a page that
  does not know the key ignores it. It costs about 32 bytes per mesocycle with a deload,
  against the 6 KB budget the author's window fills to 5.5 KB (DESIGN_calendar_miniapp.md §8).
- **The page** (`miniapp/calendar_logic.js`) answers whether a day falls in a deload, from
  `d`, the way it already finds the day's mesocycle. `calendar.js` adds the class `deload` to
  that day's strip and to the legend's swatch, and `calendar.css` draws it at 40% opacity.
- **The legend** gives a deload that touches the month its own row, under its mesocycle's.

The page is published through the Pages deploy, which needs a push the author approves.

### 5.2 The terminal

- **`sm calendar`** prints `── Deload Mon 2 Nov to Sun 8 Nov` under the week the deload
  starts in, the way it already prints `── <name> starts Thu 1 Oct`
  (`cli/render/calendar_grid.py`).
- **`plan generate`'s preview and `plan show`** print a `Deload` line with the dates under the
  mesocycle's head (`cli/plans/generate.py`, `cli/plans/show.py`). The athlete accepts a plan
  after seeing where its deloads fall.
- **`plan diff`** reports a deload added, removed or moved as a field change of that
  mesocycle: the two columns join the field list `plan_versions.py::_diff_mesocycle_pair`
  compares.

## 6. Not handled

- **A deload across a mesocycle boundary.** A deload lies inside one mesocycle. The TASK
  already lets `plan generate` move a boundary by a few days to align it with a recovery week.
- **Rolling back to a plan written before this design.** Its mesocycles have no deload dates,
  so the week planner writes no deload in them, whatever their names say. Run `plan generate`
  instead.
- **A planned deload the athlete trained through.** The plan's dates stay where they were.
  The next `plan generate` counts from the weeks the athlete actually trained lighter.
- **A check of the loading-to-recovery ratio in code.** The ratio is a plan choice, so the
  code has nothing to check it against.

## 7. Choices made without asking

1. **At most one deload per mesocycle.** This matches the usual definition: a mesocycle is a
   run of loading weeks closed by its recovery week. A long base phase with two deloads
   becomes two mesocycles. The other way is a list of deloads per mesocycle, which costs a
   little more in every place that reads the dates.
2. **Two date columns, not a deload flag on each week.** A week flag would need the code to
   decide what a week is. A mesocycle's first day is not always a Monday: the one before
   today started on a Thursday.
3. **Only `plan generate` writes the dates.** No code guesses a deload from the load or from a
   mesocycle's name, and old plans are not backfilled.
4. **A deload that does not fit is dropped with a note**, not moved or clipped (§3.4).
5. **The deload of the mesocycle under way can be re-dated** by a replan (§3.3), even though
   its name, dates and focus are kept.
6. **A paler strip, at 40% opacity, not a new tint.** The tint already means "how did this
   session go". A dashed strip would be easier for colour-blind readers, but the author asked
   for a colour.
7. **The legend gives each deload its own row.** The other way is one fixed key line, "pale
   strip: deload week", which the reader has to match to the cells.
8. **The calendar only, on the companion side.** The "Goals & plan" page, the chat's plan view
   and `sm status` show no deload. Each could later take the same dates.
9. **A week cut short by illness is not drawn as a deload.** It was not planned, and its blue
   tint already says the athlete trained less than planned.
10. **The heavier-and-lighter clause moves into the guideline** (§3.1), since the counting now
    happens in `plan generate` and the week planner's guess is deleted.

## 8. Amendments to other documents

Applied in the build commit, so no document describes behaviour the code does not have yet.

- **DESIGN_mesocycle_progress.md.** §3.2 "No deload label" gets an amendment: "Amendment,
  2026-10-19. The plan now dates each mesocycle's deload (DESIGN_deload_weeks.md). The week
  planner reads the dates, so the dip rule above and its fixed-rhythm clause are gone from the
  prompt. The fixed-rhythm clause now sits in `periodization.md`'s counting rule, where `plan
  generate` reads it." §4 asks for two things instead of three: the sentence "treat a clear
  dip in an elapsed week as the deload already taken" goes, with a pointer to this design.
- **DESIGN_calendar_miniapp.md.** §1's strip paragraph and §3.1's third item say a deload day's
  strip is paler and the legend gives the deload its own row. §5's snapshot shape shows `d`,
  with one bullet: "`d` is the mesocycle's deload, its first and last day, when the plan dates
  one." §7 gives the `── Deload` line.
- **docs/DOMAIN_MODEL.md.** The mesocycle field table gains `deload_start` and `deload_end`,
  and "five meaningful columns" becomes seven. The sentence "There is no stored load target,
  no weekly hours, no intensity distribution, no deload flag" loses "no deload flag", and the
  next one says a mesocycle states what it is for and, when it has one, its deload dates. The
  line that says the alternation is one "the mesocycle-progress deload rule knows about" points
  at the counting rule in `periodization.md` instead.
- **docs/ARCHITECTURE.md.** The mesocycles table gains the two column lines, each pointing
  here.

Four designs use the word "deload" only in passing and need nothing:
DESIGN_benchmark_workouts.md, DESIGN_bot_simple_frontend.md, DESIGN_strength_tracking.md and
DESIGN_plan_change_continuity.md.

## 9. Build order

1. The columns: `db/schema.py`, `types.py::Mesocycle`, `save_macrocycle`, the migration script.
2. `plan generate`: the guideline rule (§3.1), the TASK sentence and the response keys (§3.2),
   the mesocycle under way (§3.3), the check (§3.4).
3. The model calls: `mesocycle_text` and its five callers, `workout generate`'s TASK wording,
   the deleted paragraph (§4.2).
4. The terminal: `plan generate`'s preview, `plan show`, `plan diff`, `sm calendar` (§5.2).
5. The page: the snapshot key, the logic, the strip, the legend (§5.1).
6. The amendments (§8).
7. On each instance, by the author: the migration script, `sm plan generate -f`, then `sm
   workout generate -g` to rewrite the sessions, a bot restart, and the Pages deploy.

## 10. Tests

- The repair pass drops a deload outside its mesocycle, or with one date missing, and names it
  in its note.
- `save_macrocycle` stores the two dates, and the mesocycle reads back with them.
- `mesocycle_text` ends its line with the deload when there is one, and not otherwise.
- The deleted paragraph is gone from the CONTINUING A MESOCYCLE section.
- `plan diff` reports a moved deload as a change of its mesocycle.
- `sm calendar` prints the `── Deload` line under the week the deload starts in.
- `miniapp/tests/calendar.test.mjs`: a day inside `d` is a deload day and a day outside it is
  not, and the legend gives a deload in the month its own row.
