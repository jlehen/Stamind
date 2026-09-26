# Design: a past strength session, planned against done, and graded by its sets

**Status:** Implemented · **Date:** 2026-09-26 · **Branch:** `worktree-strength-planned-vs-done`

## 1. The problem

It is Saturday 26 September. The athlete looks back at the week's two gym sessions. Monday
21 September, "Strength — Consolidation Volume", asked for 8 exercises in 21 sets, and the
watch alone recorded it. Thursday 24 September, "Strength — Light, Legs Fresh", asked for 7
exercises in 17 sets. The watch recorded it, and the athlete also logged it with the gym
logger (DESIGN_gym_logger.md) open on the phone.

**The screens.** `workout show` prints the planned exercises, but only inside the
description text, between the brief and the notes. It prints nothing of what was lifted.
`workout compare` prints what was lifted under the activity line, but not what was
planned. No screen puts the two side by side, so the athlete matches seven exercises by eye.

**The verdict.** Today a session is [DONE] when the activity paired with it ran within a
tolerance of the planned minutes and cost within the same tolerance of the planned load,
and [PARTIAL] otherwise (`_discrepancy_reasons` in `analytics/adherence.py`). The
tolerance is wide for an easy session, 50% at a planned load of 20, and narrower for a hard
one. For a gym session the load is the heart-rate number, unless heart rate covered less
than half of the session or the athlete's RPE implies clearly more. Then the load is
computed from the RPE and the minutes (`activity_load` in `analytics/load.py`).

Heart rate under-counts lifting, so the verdict is right only when the athlete entered an
RPE. On Monday the athlete lifted every planned set and more, in 56 of the 60 minutes, and
entered no RPE. Heart rate covered enough of the session to be used, and gave a load of 13
against 26 planned, so Monday is [PARTIAL]. Thursday went through both states in one day.
On Saturday morning it had no RPE yet. Heart rate covered only 45% of it, and with no RPE to
fall back on, its load was the heart-rate number: 7 against 20, [PARTIAL]. Later that day
the athlete entered an RPE of 3. The load became 19, computed from the RPE and the 38
minutes, and Thursday turned [DONE]. Nothing about the lifting changed; a number typed two
days later did.

This athlete enters an RPE for most sessions, 15 of the last 16, so today's verdict is
usually right. It has two limits. It depends on a number the athlete must remember to type.
And it cannot tell whether the work was done: a 60-minute session at RPE 5 with half its
exercises skipped is [DONE]. The sets can say both, but only when they can be trusted. A log
can: the athlete ticks each set against the session's own exercises. The watch's exercise
names cannot (§4). So a session the athlete logged is graded by its sets, and a session the
watch recorded alone keeps today's verdict. For the companion, in one sentence: a gym
session you logged is graded by what you logged; one the watch recorded alone is graded by
its time and effort.

## 2. What the athlete sees

`workout show 439` draws Thursday as a table under the "Actual:" line:

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
today (`sets.set_chunks`), with the "(watch)" mark on a name the watch guessed. The last
column is one mark:

- **✓**: every planned set of the exercise counted (§3).
- **swapped**: on the logger page the athlete put another exercise on the planned lines. The
  Done cell starts with its name. A swap short of sets reads "swapped 2/3".
- **lighter 0/2**: enough sets were lifted, but some were too light to count. The numbers
  are the sets that counted and the sets planned.
- **sets 1/2**: fewer sets were lifted than planned.
- **not done**: nothing lifted for it.
- **not planned**: lifted, and not asked for.

The last line counts the planned sets that counted, and the planned exercises with at least
one set that counted. On a session the watch recorded alone it ends with "· graded by time
and load", so a [DONE] beside "8 of 21" does not read as a contradiction (§4).

The companion sees the same comparison as plain text, under the session's line in "Done
lately". It keeps the four glyphs of DESIGN_bot_simple_frontend.md §6 and the spelling of the
table, and lists only what differed. The exercises done as planned share one line:

```
Thu 24 · ✅ 🏋️ Strength — Light, Legs Fresh — 50 min (you did 38 min)
      15 of 17 planned sets · 6 of 7 exercises
      ✅ Lat pulldown, seated barbell shoulder press, row, chest fly, glute bridge
      ✅ Chest press instead of barbell push press
      ❌ Ab twist, lighter: 1×20 @ 15, 1×20 @ 20 (planned 2×20 @ 30)
      ➕ Plank 1×120
```

A planned exercise with nothing lifted reads "❌ Hamstring curls, not done". One lifted short
reads "❌ Row, 1 of 2 sets: 1×6 @ 110".

## 3. Which sets count

A set is **near** a planned line when it is no more than 10% under the line's load. A
heavier set is always near. A machine often cannot be set to the exact load, and the 10%
absorbs that. A line with no load (a bodyweight exercise) is near every set, and so is a set
with no load recorded: its load is unknown, not light. Reps are shown and not counted: a set
near the load counts whatever its reps. The `light` flag on a planned line changes nothing
here.

**A logged set counts on its card's line.** The logger page draws one card per planned line,
and the athlete ticks each set on a card. On Thursday the row had one line, 2 sets at 110 kg,
and one card. On it the athlete ticked 95, 110 and 110. The two sets at 110 fill the line.
The set at 95 kg is not near 110 (the limit is 99), so it is an extra: shown in the Done
cell, not counted. The row counts 2 of 2. Its mark is still ✓. An extra set is never marked,
because it is almost always a warm-up the strength planner did not write.

A card the athlete swapped to another exercise counts on its line too, up to the line's
number of sets, with no load check: a chest press load says nothing about a push press
load. On Thursday the athlete swapped the chest press in on both push press cards, a warm-up
line and a working line, so the push press counts 3 of 3 and is marked "swapped". A swap is
the athlete's own word on the page, not a guess. It happens for ordinary reasons: the
machine is taken, or the session named the wrong exercise, as it did on Thursday.

**A set with no card counts by name.** That is a card the athlete added on the page, and
every set of a session the watch recorded alone. Take the exercise's sets heaviest first.
Each set counts on the heaviest planned line of the same exercise that it is near and that
still has room. A set that fits no line is an extra. On Monday the belt squat was planned as
"1×5 @ 110, 2×4–6 @ 125", and the watch recorded 110, 130 and 130 kg. The two sets at 130 kg
fill the working line. The set at 110 kg is not near it, since 10% under 125 kg is 112.5 kg,
so it falls to the warm-up line, where 110 matches 110. The belt squat counts 3 of 3.

When the session was rewritten after the athlete opened the page, the cards point at lines
of an older revision (`gym_logs.revision_id` is not the graded revision). Then every set of
the day counts by name.

On Thursday the ab twist was planned as 2 sets at 30 kg, and the athlete lifted 15 and 20 kg.
Both are under 27 kg, so neither counts: "lighter 0/2". The chest fly was planned at 55 kg
and lifted at 50, which is 9% under, so all three sets count. Thursday counts 15 of 17.

## 4. Where the names come from

On a day the athlete used the gym logger, the sets are the log's. The log is handed to
Garmin's activity for the day, and Garmin is never asked for that activity's sets
(DESIGN_gym_logger.md §5), so the watch's exercise names never reach the comparison. On a
day with no log, the sets are Garmin's, with the names the watch guessed or the athlete
picked on the watch.

Those names are often not the session's. On Monday the session asked for "chest fly",
"hamstring curls", "seated barbell shoulder press", "glute bridge" and "barbell push press".
On the watch the athlete picked "flye", "leg curl", "shoulder press", "barbell hip thrust
with bench" and "bench press". Each is an exercise of its own in the vocabulary, not a typo.
Monday's table shows the record as it stands:

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
8 of 21 planned sets · 3 of 8 exercises · graded by time and load
```

The code does not second-guess the names (AGENTS.md: never infer a fact from noisy data).
That is why a day like this one keeps today's verdict: grading it by these names would tell
`workout adapt` that 13 of the 21 planned sets were skipped, when all were lifted. The table
is there so the athlete sees what the record says. `strength name` corrects it, and the
verdict does not depend on it. Sets no one has named yet print as today's "sets 5–7
unnamed" row.

## 5. Which activity is the session

A logged day has two activities for one session until they are merged. `strength ingest`
stores the log at once as a placeholder activity, `log:<date>`, with no heart rate and so a
load of 0. Garmin's own activity lands at the next pull. Today the merge waits for the next
morning's read of the sets (`read_new_activities` handles activities dated before today),
and the session pairs with the day's heaviest activity (`analyze_adherence`).

It is Thursday. The athlete logs the session at 10:41, and the bot shows the comparison. At
20:00 "Done lately" pulls Garmin, and Garmin's activity arrives with a load of 19. It beats
the placeholder's 0, so the session pairs with an activity whose sets are not read: no table
and today's verdict. The log sits under the day as an effort the plan did not ask for, until
Saturday morning's read merges the two.

Two changes fix it:

- **The merge runs on the day itself.** It only moves rows inside the database and never
  calls Garmin, so it does not have to wait for the sets to be final. `take_over_logs` gets
  every unread strength activity up to today; the read from Garmin keeps "before today". On
  Thursday evening, Garmin's activity takes the log as soon as it lands.
- **An activity carrying a gym log pairs first, whatever its load.** On a day the athlete
  forgot to start the watch, there is no Garmin strength activity to merge into. The day
  can still hold a short warm-up recorded as indoor cardio, which counts as strength when
  pairing (`sports.py`); this athlete records one of 5 to 11 minutes before every gym
  session. Its load is 0.3 and the placeholder's is 0, so without this rule the warm-up
  would be graded as the session, and the log never would.

An activity carrying a gym log is also never "ambiguous" (`is_ambiguous_match`): the
athlete tapped Finish on it, so Stamind does not ask whether it was the session, however
short it ran.

## 6. The verdict

A logged strength session is [DONE] when at least 80% of its planned sets counted, and
[PARTIAL] otherwise. That one rule replaces the minutes and load comparison for the session.
There is no separate rule for load: a set too light to be near its line already fails to
count, so one light exercise costs its own sets and nothing more. Thursday counts 15 of 17,
which is 88%, so it is [DONE].

The 10% and the 80% are constants beside the comparison, not settings.

The rule applies when the session has planned lines and the activity it paired with carries
a gym log. Every other strength session keeps today's verdict: one the watch recorded alone,
and one written before the strength planner wrote lines.

A [PARTIAL] logged session carries one reason, in place of the minutes and load reasons. It
gives the sets lifted as well as the sets that counted, so a light day does not read as a
skipped one:

```
sets: 0 of 17 planned sets near their load (0%, below 80%); 17 lifted
```

It is the "Discrepancy:" line under `workout list -vv`, and the reason `workout adapt` reads
among the week's evidence. The adapt prompt's TASK lists the discrepancies it weighs as
"misses, workload/duration differences, rest violations"; it adds "sets short".

The verdict reaches everything `classify_adherence` already feeds: the markers in
`workout list`, `workout compare`, the Calendar marks, the dashboard badge and
`workout adapt`. A Calendar event already marked keeps its old tag until its day is marked
again, by `workout compare` or by the marking pass that follows a pull.
`_duration_shortfall`, which decides whether a session cut short is still open to
`workout adapt`, still reads the minutes. It asks whether the athlete is still in the gym,
not how the session went.

## 7. Where it is drawn

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
  "not done" lines. The athlete in the gym and the athlete looking back read one comparison.

## 8. Code

- **`stamind/strength/comparison.py`**, new. One pure function takes the planned lines
  (`prescribed_sets` rows) and the lifted sets, each with the position of its card's planned
  line or none. It returns one result per exercise (planned lines, sets, counted, planned,
  mark) and the totals. It knows nothing of the database or of any screen. The §6 reason is
  built from its totals.
- **The lifted sets.** `get_completed_activities` attaches them to a strength activity whose
  sets are read. For an activity carrying a gym log they come from the log's cards
  (`gym_logs.payload`), with each card's position when `gym_logs.revision_id` is the session
  it is graded against. Otherwise they are the `exercise_sets` rows, with no position.
  `analyze_adherence` stays pure of the database, and every caller (`workout compare`, the
  dashboard, the Calendar marking, `workout adapt`, the pairing questions) sees the same.
- **`analyze_adherence`** sorts a day's activities with the one carrying a gym log first,
  then by load. `is_ambiguous_match` returns False for an activity carrying a gym log.
- **`take_over_logs`** is fed unread strength activities up to and including today.
- **`_discrepancy_reasons`** calls the comparison for a strength session with planned lines
  paired with an activity carrying a gym log, and returns its one reason or none. It is
  already the single source of both the verdict and the discrepancy lines.
- **`coach/engine/adapt.py`**: "sets short" in the TASK's list of discrepancies.
- **The renderers**: the terminal table in `cli/common.py`, called by `workout list -vv` and
  `workout compare`; the companion lines in `cli/render/session_lines.py`, called by
  `simple_compare_lines` and by `strength ingest`. Both reuse `prescription.spec` and
  `sets.set_chunks`. `_written` and `_not_done` in `cli/strength_ingest.py` go.
- **docs/ARCHITECTURE.md**: the strength section says where the comparison lives, that it
  grades logged strength sessions, and that a logged activity pairs first.

## 9. Not handled

- A log sent after the morning read already stored Garmin's sets for that day. Garmin's sets
  stay (DESIGN_gym_logger.md §7).
- A session logged a day late: the log lands on the day it was sent. Thursday is missed, and
  Friday's log is an effort the plan did not ask for.
- A day the watch split into two activities, and a day with two planned strength sessions.
  The log goes to the longer activity; the session pairs with the logged one.
- Below about 50 kg one pin or dumbbell step can be more than 10%: 25 kg against a planned 30
  does not count. The strength planner writes loads the athlete has already lifted, so it
  rarely names a load the machine cannot be set to.
- The table is wider than a phone. Expert mode in Telegram draws it as one record per
  exercise, as it draws every table on a narrow client (`render_table`).
- The strength planner's own view of what was done (DESIGN_strength_tracking.md §8) still
  pairs by name and does not read the log's cards.
- The dashboard shows the new verdict but not the table.
- An exercise that appears twice in the session, on two lines far apart, is one row: its
  lines and sets are pooled.
- A discarded activity (`strength discard`) gets the table like any other; its "discarded"
  line stays under it.
