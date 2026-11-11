# Design: a week against its sessions as written

**Status:** Proposed · **Date:** 2026-11-10 · **Branch:** `worktree-plan-delivery-design`

## 1. The problem

It is Tuesday 10 November. The athlete looks back at the deload week of 2–8 November. When
the week began, the schedule held seven days: gym on Monday, an easy ride on Tuesday, short
intervals on Wednesday, yoga on Thursday, a light gym session on Friday, a 2 h gravel ride on
Saturday and yoga on Sunday. Wednesday the athlete felt tired, so the coach swapped the
intervals with Thursday's yoga. Friday the athlete was sick, so the light gym session became a
rest day. Saturday's ride shrank to an optional hour, moved to Sunday on the athlete's request,
and shrank again to 40 minutes on Sunday morning. The athlete rode 72 minutes on Sunday.

`workout compare` prints every day as done or rest respected. Its one flag is Sunday's ride,
which ran 72 minutes against the 40 asked. In the chat, the same days end with "All 6 sessions
done — brilliant 🎉". Both are true: the athlete did what the coach asked on each day. They
answer the question "did I do what the coach asked?". The athlete is asking another one: "did
the week get what `workout generate` wrote for it?". The answer is "most of the riding and half
of the gym": 156 of 190 ride load, 1 of 2 gym sessions.

No screen answers that second question. Worse, four readers that look like they do answer the
first one instead, because each takes "planned" from the schedule as it stands now
(`get_workouts`, the newest version of each day). A session the coach dropped is gone from it,
and a session the coach shortened plans less load than before:

- `workout compare`, in the terminal and in the chat.
- `sm progress`: its weekly bars and percentages, and the chart.
- The week lines ("planned X, actual Y") that `workout generate`'s week planner, `plan
  generate`'s strategy prompt and the retrospective writer read
  (`MesocycleContextMixin._mesocycle_week_lines`).
- The numbers of a mesocycle record (`sessions_planned`, `load_planned`, `sessions_done`,
  DESIGN_cycle_retrospective.md §5).

HIIT Block 1 ended on Sunday 8 November. Its record is due on 15 November. It will read the
deload week as "planned 167, actual 221": 132%, a week in which the athlete looks like they did
more than asked, when they were sick and skipped a gym session. If tired weeks become a
pattern, `plan generate` never learns of it, because every one of them looks complete.

Dropping the sessions was right. The mesocycle's own text puts the recovery floor above every
session. So the day verdicts stay as they are, and nothing here marks a drop as a miss.

## 2. The rule

Two questions, two answers, each on its own line:

- **Each day** is checked against the schedule as it stands now, as today. Unchanged.
- **Each week** is checked against its **written week**: its sessions as `workout generate`
  wrote them (§3). Only a week that has ended is graded: on Monday, last week is; the week
  under way never is.

A week is graded **per sport**. A sport gets a line when the written week holds a session of
it; a sport with nothing written that week is not graded.

- **Strength training is counted in sessions.** Its planned load says little: a light gym
  session is planned at 15, a long ride at 80. A done session is an activity of that sport
  lasting at least `garmin.min_activity_minutes` (15), so the 7-minute warm-up Garmin files
  under strength is not a second session.
- **Yoga and rest are not graded.** They are recovery, and a missed yoga session is not a
  shortfall.
- **Every other sport is added up by load**, hiit included (D4): the planned load of the
  written week's sessions of that sport, against the load of every activity of that sport in
  the week, planned or not.

Because it is a sum, one session makes up for another of the same sport in the same week. A
ride that ran 30 load over covers a ride that was cut by 30. A long ride never covers a gym
session: they are two sports.

A sport is **short** when:

- added up by load, the load done is under the planned load by more than the tolerance
  `compare` already allows one session of that planned load (`_adherence_tolerance`,
  `coach.adherence_tolerance`): 15% from a planned load of 100 up, wider below, 50% at 20;
- counted, fewer sessions were done than were written.

The percentage shown is rounded down, so a week that is short never reads 85%.

Under a short sport, and only there, its sessions of the written week that are no longer as
written are listed, each with the day the coach last changed it and the reason stored with
that change (§5).

The athlete's weeks, numbers from the database on 10 November:

| Week | Rides: written → done | Gym: written → done | Short |
|---|---|---|---|
| 7 Sep | 449 → 381.5 (84%) | 2 → 2 | rides: 15.03% under, just past the 15% tolerance |
| 14 Sep | 348 → 205.8 (59%) | 2 → 1 | rides and gym |
| 2 Nov | 190 → 156.3 (82%) | 2 → 1 | rides and gym |

In the chat, the difference between the two lines fits in one sentence: the ✅ and ❌ lines
check each day against the schedule as it is now, and the week line checks the whole week
against the sessions as they were written.

## 3. The written version of a session

A session keeps one identity across all its versions, even when it moves to another day: its
lineage (`lineage_id`, DESIGN_workout_revisions.md §4). A **slot** is one date and one sport;
the live session of a slot is the newest version written there.

The written week is found slot by slot, because `workout rollback` undoes slot by slot
(`rollback_to_change`). For each slot with a version dated in the week, walk its versions
oldest first, whatever their lineage, and keep what `workout generate` left in the slot:

| Version written by | What `workout generate` left in the slot becomes |
|---|---|
| `workout generate` | this version (a void: nothing) |
| `workout rollback`, a goal reinstate, a reprint: a copy of an earlier version of the slot (`restored_from`), a void copied back included | what it was just after that earlier version was written |
| a void written by a goal stand-down, or by `workout rollback` for a slot that held nothing before (no `restored_from`) | nothing |
| `workout adapt`, `workout tweak` | unchanged |

The version a slot's walk ends on is the **written version** of a session of the written week.
When two slots of one week end on the same lineage, the newer version counts. A session that
`workout adapt` or `workout tweak` created is not part of the written week, but an activity done
on it still counts as load done.

One exception: when `workout adapt` or `workout tweak` writes into a range that held no session
at all, its change is stored as a `workout generate` (D5). It is Sunday evening. `plan generate`
has started a new mesocycle, and its `workout generate` proposal waits in the chat. Before
answering it, the athlete asks the coach for a change, and `workout adapt` writes the five weeks
itself. Those sessions are the schedule as written, so they are stored as written by `workout
generate`, and the slot walk reads them as written.

Two stories show why the walk goes by slot and not by session. On Wednesday 4 November at
08:00 the coach moves the intervals to Thursday, and at 08:30 the athlete runs `workout
rollback`. Wednesday's ride slot holds the version `workout generate` wrote, the coach's void,
and the rollback's copy of the first: the intervals, on Wednesday. Thursday's ride slot holds
the coach's version and then the rollback's void, because that slot held nothing before:
nothing. Walking the intervals' own versions instead would end on that void and lose them from
the week. In the second story, `workout generate` writes a ride on a day whose slot held a
void, which starts a new lineage (DESIGN_workout_revisions.md §4); the athlete dislikes it and
rolls it back. The slot then holds the old void, the new ride and the rollback's copy of the
old void, so it goes back to what it held before the ride.

The walk reads only the order of versions, never clock times. Every writer the table reads
starts at today (`workout generate`, `workout rollback`, a stand-down, a reinstate, a reprint),
so an ended week's written sessions never change afterwards. Only the operator writes into a
past day, with `workout adapt --date` or by hand (the tweak of 31 October that re-recorded 30
October as hiit), and an adapt or a tweak leaves the written week alone. The one case that
does change an ended week is D5 on a past day (choice 17). It is Tuesday, and the operator runs
`workout adapt --date` for last Thursday, when no session stands from that Thursday to the end
of the mesocycle. The change is stored as a `workout generate`, so last week gains written
sessions after it ended.

Against its written version stands the session's **now**: its lineage's live version that is
not a void, the rule `_speaking` already applies (`db/workouts.py`). On Friday 6 November the
light gym session's lineage holds a live void in the strength slot and a live rest day; the
rest day is its now. The session is:

- **dropped** when it has no now, or its now is of another sport (a rest day included). Its
  line says "dropped" when it has no now, and names the now when it has one: "replaced by
  Rest Day — Unwell";
- **moved out** when its now falls in another week;
- **cut** when its now plans less load than its written version (sports added up by load
  only).

A session moved within its week with the same load is none of these.

## 4. What changes where

**One read decides "planned".** `graded_workouts(dbh, start, end, today)` returns, for the days
before `today`'s Monday, the written versions dated there; from that Monday on, the live
sessions, as `get_workouts` returns them. The rows are `Workout`s (`id` is the lineage,
`revision_id` the version), built with `hydrate_revisions`, so every reader keeps its code and
changes only where it fetches. Readers that change:

- `sm progress` (`timeline_rows.build_timeline_payload`): a past week's bar and percentage, and
  the dashboard's progress image, which reads the same payload. The zone tables read planned
  zones only for weeks ahead, so they do not change. The fitness projection reads only today
  and later, so it is unchanged.
- The week lines (`_mesocycle_week_lines`, both callers) and the planned time in zone of the
  mesocycle report (`fetch_workouts`, both callers).
- The record's numbers (`_retrospective_numbers`) read `written_week(dbh, start, end)` (§9),
  because all the mesocycle's days are over when it is written, even when it ended on a
  Wednesday and is written that Sunday. `sessions_planned` and `load_planned` come from the
  written versions. `sessions_done` is the count made today, the live sessions with a done or
  partial verdict, capped for each sport at the number of sessions written of that sport (rest
  is left out on both sides). A session the coach moved within the mesocycle and the athlete
  did still counts. A gym session the coach turned into yoga on a tired Thursday is not a gym
  session done, although the yoga carries its lineage (`revision_apply.py`). A lift the coach
  moved by turning Wednesday's lift into rest and Thursday's ride into a lift (16–17 September)
  counts once. A session the coach added counts in place of a missed one of the same sport, as
  its load already does.

Readers that do not change:

- The fitness-test lines of `workout generate`'s prompt keep `get_workouts`: a test the coach
  dropped was not run, and reading it as written would tell the week planner the test had
  happened. They share one fetch with the week lines today; that fetch splits in two.
- Every day verdict (`adherence_window`, `workout list`, the Calendar tags, the calendar mini
  app), the `workout adapt` prompt's view of its own days, and the dashboard's compare tab.

**The week grade** is a new pure function over one ended week: `week_grade(sessions,
activities)`, the written week's sessions, each with its written version and its now, and the
week's activities. It sums each sport's load over the written versions and over the activities
with `_load_by_sport`, the helper `weekly_aggregates` uses (§9 says where it lives). It
returns, per graded sport: how it is measured, written, done, short or not, and the dropped,
moved-out and cut sessions. One renderer turns it into the text lines the terminal and the
prompts share; the chat puts its own head sentence in front.

**The per-sport note goes** (choice 7). `_week_sport_gap_note` (DESIGN_mesocycle_progress.md
§3.3) adds a sport line to a week whose sports disagree. For an ended week, the grade's
per-sport lines replace it. What this leaves for the week under way is in choice 7's Review
column.

## 5. What the athlete sees

### `workout compare`

The day lines are unchanged. When no day has a discrepancy, the closing green line loses "Great
adherence!" and reads "No discrepancies found.", because the week below it can be short. Then
each week that has ended and overlaps the window is graded whole, even when the window starts
mid-week. The terminal prints the grade's lines, the ones the prompts read, under a week
heading of its own; a short sport's line is yellow. A reason is printed whole, through
`wrap_text`, in the terminal and in the prompts; the examples here cut it with "…".

```
=== WEEKS AS WRITTEN ===
Week of Mon 02 Nov
    cycling: written 190, done 156 (82%), short
      Sat 07 Nov Easy Gravel Ride (Deload): cut from 120 to 40 min, moved to Sun 08 Nov,
      changed Sun 08 Nov: "Your resting heart rate is raised after Friday's illness …"
    strength: written 2 sessions, done 1, short
      Fri 06 Nov Full-Body Strength (Deload, Light): replaced by Rest Day — Unwell,
      changed Fri 06 Nov: "Rest because you were sick today and did not train. …"
```

Every graded sport gets its line. With `--sport`, only that sport is graded, taken through
`canonical_sport`. Nothing is red.

### "✅ Done lately" in the chat

The day lines and the closing count are unchanged. A week line follows only when a sport is
short. Its head sentence is the chat's own, in the tone rule of DESIGN_bot_simple_frontend.md
§6: what was done first, the gap as a plain number after it. Under it, each session line puts
the chat's date and `simple_session_line` name in front of the grade's words for what happened
and why.

```
Week of 2 Nov, against the week as it was written: you did 82% of its riding and 1 of its 2
gym sessions.
Fri 06 · 🏋️ Light gym: replaced by Rest Day — Unwell, changed Fri 06 Nov: "Rest because you
were sick today and did not train. …"
Sat 07 · 🚴 Easy gravel ride: cut from 120 to 40 min, moved to Sun 08 Nov, changed Sun 08
Nov: "Your resting heart rate is raised after Friday's illness …"
```

A week with nothing short adds nothing. The calendar mini app reuses `simple_compare_lines`
for its day sheet, so the week line is a separate function and does not reach it.

### The prompts

The week line keeps its form, and for an ended week its planned figure is the written week's.
Under an ended week, the grade's lines follow:

```
- week of 2026-11-02: planned 237, actual 221 (93%)
    cycling: written 190, done 156 (82%), short
      Sat 07 Nov Easy Gravel Ride (Deload): cut from 120 to 40 min, moved to Sun 08 Nov,
      changed Sun 08 Nov: "Your resting heart rate is raised after Friday's illness …"
    strength: written 2 sessions, done 1, short
      Fri 06 Nov Full-Body Strength (Deload, Light): replaced by Rest Day — Unwell, …
```

No section is added (DESIGN_prompt_structure.md): the lines sit where the week lines already sit.

### The day and the reason shown

The day shown is the athlete's day of the change (`clock.local_day` of
`workout_changes.created_at`, which is stored in UTC).

The reason is the one stored with the newest version dated in the week that changed the
session's day, its sport or its load, or removed it. A version that only reworded the session
is skipped: the coach often rewrites a session's text on a later morning, and that text says
nothing about the cut. For a session moved out, that version is the void the move left in the
week, which carries the move's reason (`revision_apply.py`).

A session that lost its day to another session has no now, and its void carries the reason of
the whole change, which may start with another day. It is shown in the same form as every
other: `dropped, changed Mon 09 Nov: "As asked, today is rest and the easy ride moves to
Tuesday. I kept the heavy lift instead of the light one…"`. The day of the change in front of
the quote says which day "today" is.

## 6. Choices made without asking

The author rules on each. A review may object in the last column; it may not remove or change
a choice.

| # | Choice | Why | Chosen over | Review |
|---|---|---|---|---|
| 1 | Strength training is counted in sessions, yoga and rest are not graded, every other sport is added up by load (§2) | A gym session's planned load (15) says little next to a ride's (80); a missed yoga session is recovery, not a shortfall | Everything by load; every sport graded | Ruled for hiit: by load (D4) |
| 2 | A counted session needs an activity of at least `garmin.min_activity_minutes` (§2) | Garmin files a 7-minute warm-up under strength | Counting every strength activity | Objection (thorough): the setting is documented as the floor for claims about missing effort data (`config.py`, `min_activity_minutes`), so this ties gym counting to the RPE reminder. Not applied: the author rules |
| 3 | "Short" reuses the per-session tolerance at the week's planned load (§2) | Planned loads are estimates; no new setting | A fixed 10% or a new setting | Note (thorough): from a planned load of 100 up this is a flat 15%; the week of 7 Sep is 15.03% under and is short. Hole closed: the percentage is rounded down, so it reads 84% and not "85% SHORT" |
| 4 | Only a week that has ended is graded (§2) | A session moved from Monday to Friday is not missing on Tuesday | Grading the week so far | |
| 5 | Sessions are listed only under a short sport (§2) | A change that was made up for is the athlete's rule of D2 | Listing every change | |
| 6 | The prompts read the same lines as the terminal, "short" included (§5) | One renderer; "short" is arithmetic, not a judgement | Numbers without the flag, as said in the brainstorm | |
| 7 | `_week_sport_gap_note` goes; the grade's per-sport lines replace it (§4) | Two per-sport mechanisms for one question | Keeping both | Objection (thorough): the note was built for the week under way, which is never graded; `workout generate`'s prompt reads the week's activities, not verdicts (`engine/generate.py`, "ACTUAL COMPLETED GARMIN ACTIVITIES IN WINDOW"), so a Sunday run sees the week under way as one blended figure again, the 30 August case. Keep the note for the week under way only, or accept that case as not handled. Not applied: the author rules |
| 8 | "Great adherence!" goes from `compare`'s closing line (§5) | The week below it can be short | Keeping it | |
| 9 | A cut or a move quotes the reason of the last change only (§5) | One reason per line; Saturday's ride was cut on Friday, moved on Saturday and cut again on Sunday, and only Sunday's reason is shown | Every change's reason | Holes closed: a later version that only reworded the session is skipped (thorough); only versions dated in the week are read (pragmatic) |
| 10 | A surplus is never flagged | The question is whether the week got what was written | Flagging a big surplus | |
| 11 | `compare` grades every week that ended and overlaps its window, whole (§5) | The grade is about a whole week | Only weeks wholly inside the window | |
| 12 | The record's `sessions_done` caps each sport at the number of sessions written, over the whole mesocycle (§4): an extra gym session in week 3 makes up for one missed in week 1, and a session the coach added counts in place of a missed one of the same sport | One rule gets the yoga week and 16–17 September right, and it totals like `load_done` | Counting the written sessions that were not dropped, which lost the 16–17 September lift | Made during the review (pragmatic) |
| 13 | Two build steps, the record's numbers first (§8) | The original motivation lands without waiting on the wording rulings | One build | Made during the review (pragmatic) |
| 14 | The terminal prints the prompts' lines, with no columns (§5) | One renderer | A column layout with SHORT on the right | Made during the review (pragmatic) |
| 15 | Every quoted reason has the same lead-in, "changed <day>:" (§5) | The day in front tells which day "today" means in the quote | A special lead-in for a reason written about another day | Made during the review (pragmatic) |
| 16 | D5 covers `workout tweak` as well as `workout adapt` (§3) | Both go through the same apply, so the one test is "the range held no session" | `workout adapt` only | |
| 17 | D5 applies to a past day too: an operator's `workout adapt --date` into a past range with no session changes an ended week's written sessions (§3) | No extra condition in apply; the sessions it writes are the only schedule those days ever had | D5 only when the range starts today or later | Made during the consistency review |
| 18 | A record already written keeps its numbers; `plan retro redo` writes one again, and §11 names the two worth it (199, and 65 on the companion instance) | The older records were read and answered by the athlete with the numbers they show | Writing every record again after landing | Made during the consistency review |

## 7. Not handled

- A surplus in one week does not cover a cut in the next: Sunday 13 September's long ride and
  the trim of the next Wednesday's intervals fall in two weeks.
- Load equal, purpose not. A ride's load weighs its intensity, so 30 load of easy riding and 30
  load of intervals cost the same, but they do not train the same thing. A week can reach its
  ride load without its intervals. The time in zone of the mesocycle report, which also reads
  the written versions (§4), shows that side.
- If choice 7 stands: the week under way has no per-sport line in `workout generate`'s prompt,
  so a Sunday run reads only the blended figure, the case of 30 August
  (DESIGN_mesocycle_progress.md §3.3).
- A session re-recorded under another sport after it was written reads as dropped. The
  kettlebell circuit of 30 October was written as a gym session and re-recorded as hiit the next
  day, so the week of 26 October reads gym 1 of 2.
- A session `workout generate` keeps as it stands gets no new version
  (DESIGN_workout_revisions.md §7.1), so an easing that a later `workout generate` kept still
  reads as a cut.
- `workout generate --strength-only` is a `workout generate` (D1), so a strength session it
  rewrites becomes written on the day it then stands. When `workout adapt` had moved that
  session onto another gym session's day, the week loses a written gym session and the drop is
  not listed: the heavy session moved on Mon 9 November onto Friday's light one, then a
  `--strength-only` run on Tue 10 November, leaves the week of 9 November with 1 gym session
  written instead of 2.
- The retrospective writer's text shows the last week of a mesocycle that ended mid-week as "in
  progress" when it is written that same week, as it does today; only the record's numbers read
  that week as written.
- A week only part of which has written sessions (the first or last week of a plan, a gap
  between two plans) is graded on what was written, against the whole week's activities.
- A session the coach moves from a Sunday to the Monday after, which a later `workout
  generate` then writes again on that Monday, is written in both weeks, so a mesocycle's
  record counts it twice in `sessions_planned`. Neither database holds such a case; the three
  piupiu sessions that end on two slots each moved within one week.
- D5 needs the whole range empty. It is Sunday evening again, but one rest day of the old
  schedule still stands on that Sunday. `workout adapt` writes the five weeks, its change stays
  an adapt, and those weeks have nothing written, so they are not graded. The fix is the one of
  §11: relabel the change by hand.

## 8. Build order

1. **The written week as "planned".** `get_slot_history`, the slot walk, `written_week`'s
   written versions, `graded_workouts`, the swaps of §4, the record's numbers and the change
   kind of D5. No screen gains a line. The per-sport note keeps running, on the written
   figures. This is the original motivation, and it can land alone.
2. **The grade**: the now and the dropped, moved-out and cut tests of §3, the reason, and the
   lines in `compare`, the chat and the prompts, with choices 7 and 8. The three share one
   renderer and the same rulings, so they land together.

## 9. Code

- **`db/workout_history.py`**: `get_slot_history(start, end)`, every version dated in the
  window (all of them with no window), oldest first, with its change's kind and time, plus the live
  version that is not a void of each of their lineages. Two queries, whatever the size of the
  window.
- **`analytics/written_week.py`**, new, pure like `analytics/compare.py`:
  - the slot walk of §3;
  - `written_week(dbh, start, end)`: each written session dated in the window, with its written
    version and, from step 2, its now and whether it is dropped (§3). The window is walked
    week by week, Monday to Sunday: two slots that end on the same lineage are one session only
    inside one week (§3, §7). Handed the handle, as `adherence_window` is;
  - `graded_workouts(dbh, start, end, today)` (§4);
  - `week_grade(sessions, activities)` (§2, §3) and `week_grade_lines(grade)`, the text the
    terminal and the prompts share.
- **`analytics/progression.py`**: `_load_by_sport` becomes `load_by_sport`, so the grade
  reuses it; if choice 7 stands, the grade is its only caller and it moves into
  `written_week.py`. **`analytics/adherence.py`**: `_adherence_tolerance` becomes
  `adherence_tolerance`, so the grade reuses it.
- **The readers of §4** swap `get_workouts` for `graded_workouts`: `timeline_rows.py`,
  `mesocycle_context.py` (the week lines and `fetch_workouts`, not the test lines: the one
  fetch in `_mesocycle_progress_context`, "Fetched once and handed to both renderers", splits
  in two, and its comment goes), `history_context.py` (`_mesocycle_review`, both fetches).
  `retrospective.py` (`_retrospective_numbers`) reads `written_week`.
- **`mesocycle_context.py`**: `_mesocycle_week_lines` appends `week_grade_lines` under an ended
  week. If choice 7 stands, `_week_sport_gap_note` is deleted, and with it its only readers'
  inputs in `progression.py`: `week_plan_denom_by_sport` and the `planned_load_by_sport`,
  `planned_load_elapsed_by_sport` and `actual_load_by_sport` fields of `weekly_aggregates`; also
  `tests/test_context_sport_gap.py` and those cases of `tests/test_progression.py`.
- **`cli/workouts/compare.py`**: `run_workout_compare` grades the ended weeks that overlap the
  window, reading their sessions and activities from Monday to Sunday and not only inside the
  window, and hands them to the renderer; `print_workout_compare` prints them after the count.
  `print_workout_compare` returns early today when the window has no day to show (`if not
  days`); the weeks are printed even then. The same test in `run_workout_compare` only skips
  the Calendar marking and stays.
- **`cli/render/expert.py` and `cli/render/companion.py`**: `workout_compare` takes the graded
  weeks.
- **`cli/render/session_lines.py`**: the chat's week line, a function of its own printed after
  `simple_compare_lines`.
- **`coach/service/revision_apply.py`**: `workout_revision_apply` opens its change as
  `generate` when `existing_workouts`, the range's sessions read before the change opens, is
  empty (D5). Every reader of the kind then sees a `generate`. Two decide something. The quiet
  morning counts it as a newly written schedule (`picture.py`, `written`), so the next
  morning's push runs `workout adapt` once. The chat's hand-off question
  (`hand_off._coach_looked`) is still met by the proposal the chat saved before the apply. The
  others only print it: the sessions carry no `[ADAPTED]` or `[TWEAKED]` marker, their Calendar
  history reads "Planned", and the unsent-change question and the `workout rollback` list name
  the change "generate".
- **docs/ARCHITECTURE.md**: the module line for `written_week.py`; the rule that an ended week
  is planned from its written week, everywhere a week is compared; the `workout_changes.kind`
  line: an adapt or a tweak written into a range with no session is stored as `generate`; the
  `workout compare` row of the command table; §15's "Nothing new grades anything" gains the
  week grade as the one other grader.
- **DESIGN_mesocycle_progress.md §3.3**: a line saying it is replaced by this design, if choice 7
  stands.

## 10. Tests

- `tests/test_written_week.py` (new):
  - the slot walk: a `workout generate` version, an adapt that drops, a move, a rollback of an
    adapt that moved a ride to a day with no ride before, a rollback of a `workout generate`
    that wrote a session where a void stood, a rollback that copies back a void `workout
    adapt` wrote, a stand-down, a session an adapt created;
  - the now: a cross-sport swap leaving a live void and a live copy;
  - the grade: a ride over covering a ride cut in the same week; a long ride not covering a
    gym session; hiit added up by load; a 7-minute strength activity not counted; a session
    turned into a rest day counted as dropped; a session moved into the next week listed as
    moved out; the tolerance at a planned load of 20 and of 190; 15.03% under reading 84% and
    short; the week under way not graded;
  - the reason: a later rewording skipped; a session moved out quoting the void it left in the
    week;
  - `graded_workouts` switching from the written versions to the live sessions at this week's
    Monday.
- `compare`: a short sport lists its changed sessions; a sport that is not short lists none;
  `--sport` grades only that sport; the chat adds nothing for a week with nothing short.
- The record: `sessions_planned` and `load_planned` from the written versions, for a mesocycle
  that ended on a Wednesday and is written that Sunday; a session moved within the mesocycle
  and done counted; a gym session turned into yoga and done not counted as gym; a lift moved by
  two sport changes counted once; more done sessions of a sport than were written capped at the
  number written.
- The week lines: an ended week's planned figure is the written week's; a test the coach
  dropped stays out of the test lines.
- Apply: an adapt over a range with no session is stored as a `generate`, and the slot walk
  reads its sessions as written; so is a tweak; an adapt over a range holding one session stays
  an `adapt`.

## 11. After landing

Nothing to migrate: the written versions are read from the history already stored. If step 1
lands before the HIIT Block 1 record (id 199) is written on 15 November, the record is right the
first time. Otherwise run `plan retro redo 199` on the author's instance, so it is written again
with these numbers.

One row to fix on the companion instance (`piupiu/stamind.db`). On Sunday 25 October its new
mesocycle had no sessions yet, and the `workout generate` proposal for it waited unanswered in
the chat. The athlete added a holiday constraint and said yes to "Shall I adjust your week
around this constraint?", so `workout adapt` wrote all 25 sessions of the five weeks, as change
29. A `workout generate` on 4 November (change 39) was rolled back (change 40), which put change
29's sessions back. Because change 29 is an adapt, the slot walk finds no written session in the
week of 26 October and almost no written run after it. Change 29 is the case D5 now stores as
a `workout generate`, so it is relabelled by hand, once:

```
UPDATE workout_changes SET kind = 'generate' WHERE id = 29;
```

The sessions it wrote then lose their `[ADAPTED]` marker, and their Calendar history reads
"Planned" instead of "Adapted". Nothing else reads a change that old.

The companion's record 65 ("Race-Specific Sharpening", 25 October to 3 November) was written on
5 November, and every session of its span came from change 29. After the relabel, run `plan
retro redo 65` on the companion instance, so its numbers are the written week's. The other
records already written keep their numbers (choice 18).

## Decisions Log

| # | Topic | Decision | Why | Source | Date |
|---|---|---|---|---|---|
| D1 | What "planned" means for a week | The week as `workout generate` wrote it, not the week as it stood on Monday, Sunday or Saturday morning | Since 5 October the four give the same numbers on the athlete's weeks; a weekend cutoff needs an extra rule for a weekend `workout generate` (20 September), and once that rule exists the cutoff adds nothing | Brainstorm | 2026-11-10 |
| D2 | When a change is flagged | Only when nothing of the same sport in the same week made up for it | The athlete's own rule: a trim balanced by a bigger session is expected | Athlete | 2026-11-10 |
| D3 | How a drop is shown | Never as a miss; neutral lines, only under a short sport | A red drop would teach the athlete to stop telling the coach they are tired | Brainstorm | 2026-11-10 |
| D4 | Hiit | Added up by load, not counted in sessions | The athlete's ruling on choice 1 | Athlete | 2026-11-10 |
| D5 | A `workout adapt` or a `workout tweak` that writes into a range with no session | Its change is stored as a `workout generate` | It did a `workout generate`'s work; stored as an adapt, its weeks have nothing written and go ungraded (piupiu, 25 October). Chosen over fixing such a change by hand each time, and over `workout adapt` refusing until the athlete answers the waiting proposal | Athlete | 2026-11-11 |
