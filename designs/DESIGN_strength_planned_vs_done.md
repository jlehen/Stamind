# Design: a past strength session, planned against done, and graded by its sets

**Status:** Proposed · **Date:** 2026-09-26 · **Branch:** `worktree-strength-planned-vs-done`

## 1. The problem

It is Friday 25 September. The athlete looks back at Thursday's gym session, "Strength —
Light, Legs Fresh". The strength planner wrote seven exercises for it, in 17 sets. The
athlete lifted it with the gym logger (DESIGN_gym_logger.md) open on the phone.

`workout show` prints the planned exercises, but only inside the description text, between
the brief and the notes. It prints nothing of what was lifted. `workout compare` prints what
was lifted under the activity line, but not what was planned. No screen puts the two side by
side, so the athlete matches seven exercises by eye.

The verdict is wrong too. A session is graded [DONE] or [PARTIAL] on its length and its load
(`_discrepancy_reasons` in `analytics/adherence.py`). A strength activity's load is read off
heart rate unless the athlete entered an RPE, and heart rate under-counts lifting. On
Thursday the athlete lifted everything but a light ab twist. The load came out at 7 against
20 planned, so Thursday is [PARTIAL]. On Monday 21 September the athlete lifted every planned
set and more, in 56 of the 60 minutes. The load came out at 13 against 26, so Monday is
[PARTIAL] as well. That verdict reaches `workout list`, the Calendar marks and
`workout adapt`.

## 2. What the athlete sees

`workout show 439` on Friday draws Thursday as a table under the "Actual:" line:

```
Exercise                       Planned                 Done
barbell push press             1×5 @ 55, 2×4–6 @ 67.5  chest press 1×5 @ 55, 2×7 @ 65  swapped
lat pulldown                   1×6 @ 100, 2×4–6 @ 110  1×6 @ 100, 2×6 @ 110            ✓
seated barbell shoulder press  2×4–6 @ 40              1×6 @ 30, 1×6 @ 40, 1×5 @ 40    ✓
row                            2×4–6 @ 110             1×6 @ 95, 2×6 @ 110             ✓
chest fly                      3×5 @ 55                3×5 @ 50                        ✓
glute bridge                   2×4–6 @ 115             1×6 @ 110, 2×6 @ 115            ✓
ab twist                       2×20 @ 30               1×20 @ 15, 1×20 @ 20            lighter 0/2
plank                                                  1×120                           not planned
15 of 17 planned sets · 6 of 7 exercises
```

One row per planned exercise, in the session's order, then one row per exercise lifted that
the session did not ask for. The Planned cell is the exercise's lines as the description
writes them (`prescription.spec`). The Done cell is the sets as `workout compare` prints them
today (`sets.set_chunks`), with the "(watch)" mark on a name the watch guessed (§4). The last
column is one mark:

- **✓**: every planned set of the exercise counted (§3).
- **swapped**: the athlete swapped another exercise in on the logger page. The Done cell
  starts with its name. A swap short of sets reads "swapped 2/3".
- **lighter 0/2**: enough sets were lifted, but some were too light to count. The numbers
  are the sets that counted and the sets planned.
- **sets 1/2**: fewer sets were lifted than planned.
- **not done**: nothing lifted for it.
- **not planned**: lifted, and not asked for.

The last line counts the planned sets that counted, and the planned exercises with at least
one set that counted.

The companion sees the same comparison as plain text, under the session's line in "Done
lately". It keeps the four glyphs of DESIGN_bot_simple_frontend.md §6 and lists only what
differed. The exercises done as planned share one line:

```
Thu 24 · ✅ 🏋️ Strength — Light, Legs Fresh — 50 min (you did 38 min)
      15 of 17 planned sets · 6 of 7 exercises
      ✅ Lat pulldown, seated barbell shoulder press, row, chest fly, glute bridge
      ✅ Chest press instead of barbell push press
      ❌ Ab twist, lighter: 1×20 at 15, 1×20 at 20 kg (planned 2×20 at 30 kg)
      ➕ Plank 1×120
```

A planned exercise with nothing lifted reads "❌ Hamstring curls, not done". One lifted short
reads "❌ Row, 1 of 2 sets: 1×6 at 110 kg".

## 3. Which sets count

The strength planner often writes one exercise as two lines: a warm-up line and a working
line. On Monday the belt squat was "1×5 @ 110, 2×4–6 @ 125". That is 1 set at 110 kg, then
2 sets at 125 kg. Each lifted set has to count against one of those lines.

A set is **near** a line when it is no more than 10% under the line's load. A heavier set is
always near. A machine often cannot be set to the exact load, and 10% covers the step
between two plates or two pins. A line with no load (a bodyweight exercise) is near every
set.

The rule: take the exercise's sets heaviest first. Each set counts on the heaviest line it
is near that still has room. A set that fits no line is an extra. It is shown in the Done
cell but does not count.

On Monday the athlete lifted the belt squat at 110, 130 and 130 kg. The two sets at 130 kg
are heavier than 125, so they fill the working line. The set at 110 kg is not near the
working line, because 10% under 125 kg is 112.5 kg. It falls to the warm-up line, where 110
matches 110. The belt squat counts 3 of 3.

On Thursday the row had one line, 2 sets at 110 kg. The athlete lifted 95, 110 and 110. The
two sets at 110 fill the line. The set at 95 kg is not near 110 (the limit is 99), and no
lighter line is left, so it is an extra. The row counts 2 of 2. The mark is still ✓: an
extra set is never marked, because it is almost always a warm-up the strength planner did
not write.

The ab twist was planned as 2 sets at 30 kg. The athlete lifted 15 and 20 kg, both under
27 kg, so neither counts: "lighter 0/2". The chest fly was planned at 55 kg and lifted at 50,
which is 9% under, so all three sets count.

Reps are shown and not counted. A set near the load counts whatever its reps.

## 4. Where the names come from

On a day the athlete used the gym logger, the sets are the log's. The morning read hands the
log to Garmin's activity and never asks Garmin for that activity's sets
(DESIGN_gym_logger.md §5), so Garmin's exercise names never reach the comparison. On a day
with no log, the sets are Garmin's, with the names the watch recorded or the athlete picked
on the watch.

Either way the comparison pairs a lifted exercise with a planned one by its name. The log
adds one thing: the swap. Each card on the logger page stands for one planned line, and a
swap keeps the line it replaced. On Thursday the athlete swapped the chest press in for the
push press. The log says "chest press, for planned lines 1 and 2", and the comparison reads
the swap from there. The swapped exercise's sets count against the planned exercise's sets,
up to their number, and their load is not checked: a chest press load says nothing about a
push press load. The row is marked "swapped" so the swap stays visible. A swap is the
athlete's own word on the page, not a guess, and it happens for ordinary reasons: the
machine is taken, or the session named the wrong exercise, as it did on Thursday.

A day with no log has no swaps, only names, and a name the athlete picked on the watch is
not always the name in the session. On Monday 21 September the session asked for "chest
fly", "hamstring curls", "seated barbell shoulder press", "glute bridge" and "barbell push
press". On the watch the athlete picked "flye", "leg curl", "shoulder press", "barbell hip
thrust with bench" and "bench press":

```
Exercise                       Planned                 Done
belt squat                     1×5 @ 110, 2×4–6 @ 125  1×5 @ 110, 2×6 @ 130          ✓
barbell push press             1×5 @ 55, 2×4–6 @ 67.5                                not done
glute bridge                   3×4–6 @ 115                                           not done
lat pulldown                   1×6 @ 100, 2×4–6 @ 110  1×6 @ 100, 2×6 @ 110          ✓
hamstring curls                2×5–6 @ 55                                            not done
row                            2×4–6 @ 110             2×6 @ 110                     ✓
seated barbell shoulder press  2×4–6 @ 40                                            not done
chest fly                      3×5 @ 55                                              not done
bench press                                            1×5 @ 55, 1×6 @ 65, 1×7 @ 65  not planned
barbell hip thrust with bench                          1×5 @ 105, 2×6 @ 115          not planned
leg curl                                               2×6 @ 55                      not planned
shoulder press                                         1×5 @ 40, 1×6 @ 40            not planned
leg press                                              2×12 @ 60                     not planned
flye                                                   3×6 @ 50                      not planned
farmers carry                                          2×2 @ 36                      not planned
calf raise                                             2×24 @ 14                     not planned
8 of 21 planned sets · 3 of 8 exercises
```

That is what the record says, and the code does not second-guess it (AGENTS.md: never infer
a fact from noisy data). The athlete puts it right with `strength name`: once "flye" is
"chest fly" and so on, Monday counts 21 of 21. A day logged with the gym logger never has
this problem, because the athlete logs against the session's own exercises.

Sets no one has named yet print as today's "sets 5–7 unnamed" row, and count for nothing.

## 5. The verdict

A strength session is [DONE] when at least 80% of its planned sets counted, and [PARTIAL]
otherwise. That one rule replaces the length and load comparison for the session. There is
no separate rule for load: a set too light to be near its line already fails to count, so
one light exercise costs its own sets and nothing more. Thursday counts 15 of 17, which is
88%, so it is [DONE]. Monday counts 8 of 21, which is 38%, so it stays [PARTIAL] until the
athlete renames its sets.

The 10% and the 80% are constants beside the comparison, not settings.

The rule applies when the session has planned lines and the activity it matched has its sets
read. Otherwise the session keeps today's verdict. That covers a session written before the
strength planner wrote lines, an activity dated before the `strength-sets-since` setting,
and a watch-only session on its own evening, before the morning read fetches its sets. In
one sentence for the companion: a gym session is graded by its sets once they are in, and
by its time and effort until then.

A [PARTIAL] session carries one reason, in place of the duration and load reasons:

```
sets: 8 of 21 planned sets lifted near their load (38%, below 80%)
```

It is the "Discrepancy:" line under `workout list -vv`, and the reason `workout adapt` reads
among the week's evidence.

The verdict reaches everything `classify_adherence` already feeds: the markers in
`workout list`, `workout compare`, the Calendar marks, the dashboard badge and
`workout adapt`. A Calendar event already marked keeps its old tag until a
`workout compare` over its day marks it again. `_duration_shortfall`, which decides whether a
session cut short is still open to `workout adapt` and whether to ask the athlete about a
short activity, still reads the duration. It asks whether the athlete is still in the gym,
not how the session went.

## 6. Where it is drawn

- **`workout show` and `workout list -vv`**: the table, under the "Actual:" line of a past
  strength session with planned lines. The "Discrepancy:" line follows it as today.
- **`workout compare`**: the table replaces the set lines under the ACTUAL line of a planned
  strength session. An activity with no planned session keeps its set lines.
- **Expert mode in Telegram** shows the terminal output as monospace text, so it gets the
  same table.
- **Companion "Done lately"** (`simple_compare_lines`): the companion lines of §2 replace the
  set lines under a planned strength session. An unplanned activity keeps its set lines.
- **`strength ingest`**, the summary the bot sends when the athlete taps Finish on the logger
  page: the companion lines of §2 under its head line, in place of its own "written" and
  "not done" lines. The athlete in the gym and the athlete looking back on Friday read one
  comparison.

## 7. Code

- **`stamind/strength/comparison.py`**, new. One pure function takes the planned lines
  (`prescribed_sets` rows), the lifted sets (`exercise_sets` rows) and the log's swaps, and
  returns one result per exercise (planned lines, sets, counted, planned, mark) and the two
  totals. It knows nothing of the database or of any screen. `sets_line_reason` builds the
  §5 reason from its totals.
- **The swaps** come from the `gym_logs` row of the activity: every card whose name differs
  from the planned line it stands for. A small read beside `gym_log_for_day` in
  `db/strength.py`.
- **The activities every caller reads** carry their sets. `get_completed_activities`
  attaches the active set rows and the swaps to a strength activity whose sets are read, so
  `analyze_adherence` stays pure of the database and every caller (`workout compare`, the
  dashboard, the Calendar marking, `workout adapt`, the activity matching questions) grades
  the same way.
- **`_discrepancy_reasons`** in `analytics/adherence.py` calls the comparison for a strength
  session with planned lines and an activity with sets, and returns its one reason or none.
  It is already the single source of both the verdict and the discrepancy lines.
- **The renderers**: the terminal table in `cli/common.py`, called by `workout list -vv` and
  `workout compare`; the companion lines in `cli/render/session_lines.py`, called by
  `simple_compare_lines` and by `strength ingest`. `_written` and `_not_done` in
  `cli/strength_ingest.py` go.
- **docs/ARCHITECTURE.md**: the strength section says where the comparison lives and that it
  grades strength sessions.

## 8. Not handled

- A log sent after the morning read already stored Garmin's sets for that day. Garmin's sets
  stay (DESIGN_gym_logger.md §7), and the day is compared by Garmin's names.
- The table is wider than a phone. Expert mode in Telegram wraps it.
- The strength planner's own view of what was done (DESIGN_strength_tracking.md §8) still
  pairs by name and does not read the log's swaps.
- The dashboard shows the new verdict but not the table.
- An exercise that appears twice in the session, on two separate lines far apart, is one
  row: its lines and sets are pooled.
