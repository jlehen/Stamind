# Design: Steps for endurance sessions

**Status:** Designed 2026-11-02, not built · **Branch:** worktree-endurance-steps-design

A **step** is one phase of an endurance session: a warm-up, a work interval, a steady block, a
cool-down. Today a run, a ride or a swim is written as prose, so nothing checks that its
phases add up to its length. This design makes the week planner, the model call inside
`workout generate` and `workout adapt` that writes the sessions, also write each run, ride
and swim as a list of steps. Stamind checks that the steps fill the session's minutes, prints
them at the top of the description, and works out the planned minutes in each zone from them.
Each target is printed as a share of the athlete's own threshold, with the watts, the heart
rate or the pace in brackets.

Every choice in §8 marked *ruled* was the author's answer in the 2026-11-02 interview.

## 1. The problem

It is Monday 2 November. Wednesday 4 November holds "Deload HIIT — 3 x 5 min", a 75-minute
ride (workout 572, revision 911). Its description says:

> WARM-UP: 15 min easy … WORK: 3 × 5 min at 250–265 W … Take 2.5 min easy between
> intervals. … COOL-DOWN: 10–15 min easy.

That adds up to about 45 to 50 minutes. The athlete reads it on Wednesday morning and does
not know what to do with the other 25 minutes.

The week planner did know. The planned minutes in each power zone it wrote beside the text add
up to exactly 75: 15 in zone 1, 42 in zone 2, 3 in zone 3, 15 in zone 5. So the missing time
is easy zone-2 riding, and the line "Everything outside the intervals stays at 155–175 W"
hints at it. But the text never says where those minutes go, and nothing compared the text
with the zone minutes.

## 2. What the athlete sees

The same Wednesday, written under this design. The athlete's FTP is 236 W, from the test on
7 October.

```
[Deload HIIT — 3 x 5 min]
0:00     WARM-UP    15 min      easy, building to a sweat
                                two 1-min lifts to about 93% FTP
0:15     WORK       3 × 5 min   106–112% FTP (250–264 W), 8/10
                                2.5 min easy after each
0:37:30  STEADY     27.5 min    66–74% FTP (156–175 W), zone 2
1:05     COOL-DOWN  10 min      easy
                    ─────────
         TOTAL      75 min

MORNING CHECK: if resting heart rate is 52 or higher, or sleep scored under 60 with HRV below
about 41 ms, ride 60 min easy instead.

Ride the efforts seated on a Zwift climb, big gear, ERG is fine. Fuel: a bottle with carbs.
```

Each phase starts with the clock time at which it begins, so the athlete can follow the
timer on Zwift or on the watch. The minutes add up to the TOTAL, always. The advice, the
fallback and the fuel stay as prose under the steps. The prose and the short line the chat
shows each morning name a target by zone or as a share of the threshold ("66–74% FTP"), never
as watts, beats or a pace: the absolute numbers live in the steps only, so a new threshold
(§6) never leaves an old number on screen.

The targets read the way each sport speaks:

- **Power:** a percentage of FTP, the watts in brackets: "106–112% FTP (250–264 W)".
- **Heart rate:** a percentage of LTHR (lactate-threshold heart rate), the beats in brackets.
  Piupiu's LTHR is 172 bpm, from her running test on 11 October, so a threshold run of hers
  reads "95–98% LTHR (163–169 bpm)".
- **Running pace:** the pace first, the gap to threshold pace in brackets:
  "4:50–5:00/km (threshold + 10–20 s)".
- **Swimming:** the pace per 100 m first, the gap to CSS (critical swim speed) in brackets,
  and the metres in each step: "10 × 100 m, 1:55/100 m (CSS + 5 s), 20 s rest after each".
  The TOTAL line gives both the metres and the minutes.
- **No threshold on record for that target:** the zone and the effort only, "zone 2, easy,
  3/10". When a test result is recorded later, the next printing gets percentages (§6).

The columns line up in the terminal, where the block's lines stay under 80 columns and
`wrap_text` leaves a short line alone. Elsewhere they do not (§7). Other sports, hiit and gym
days included, keep their descriptions as today.

## 3. What the week planner writes

Each running, cycling and swimming entry in the week planner's answer gets a `steps` list.
These are the canonical sports (`stamind/sports.py`), so a virtual ride or a trail run counts.
The description it writes holds only the "[Title]" line and the prose: why the session is
there, the morning check, the advice. Wednesday's steps:

```json
"steps": [
  {"phase": "warm-up", "seconds": 900, "zone": 1, "effort": "easy, building to a sweat",
   "note": "two 1-min lifts to about 93% FTP"},
  {"phase": "work", "repeat": 3, "seconds": 300, "zone": 5,
   "target": {"anchor": "ftp", "low": 106, "high": 112}, "effort": "8/10",
   "recovery": {"seconds": 150, "zone": 1, "effort": "easy"}},
  {"phase": "steady", "seconds": "remainder", "zone": 2,
   "target": {"anchor": "ftp", "low": 66, "high": 74}},
  {"phase": "cool-down", "seconds": 600, "zone": 1, "effort": "easy"}
]
```

- **`phase`** is one of `warm-up`, `work`, `steady`, `cool-down`.
- **`seconds`** is one exact number. A range like "10–15 min" cannot be written. Seconds,
  because a swim rest is 20 seconds and the zone columns are already in seconds.
- **`"remainder"`** may stand in for the seconds of at most one step. It means "whatever is
  left of the session's duration". The week planner keeps writing `duration_minutes`; it is
  the session's budget, decided top-down. The remainder is a plain step: no `repeat`, and
  never a recovery. A swim has no remainder, because its metres would be unknown; its steps
  add up to the duration.
- **`repeat`** with a **`recovery`** is one interval set: work, then the recovery, N times. The
  recovery follows every repetition, the last one included. There is no deeper nesting.
- **`zone`** is the zone in the sport's zone type (power or heart rate), the one Stamind already
  picks per sport from the athlete's recordings (`_planning_zone_currencies`). Required on a
  step whose sport has a zone type; absent on a swim and on a sport with no zone type yet.
- **`target`** names one of the athlete's thresholds and a range. For `ftp` and `lthr` the range
  is in percent. For `threshold_pace` and `css` it is seconds slower than threshold, per km
  or per 100 m, and a negative number is faster. Optional: an easy step can carry only an
  effort.
- **`metres`** is on a swim step only, and the seconds beside it are the week planner's
  estimate of how long the metres take.
- **`effort`** and **`note`** are short words, printed as written on the step's line and the
  line below it. Stamind computes no number inside them.

The week planner already sees the athlete's thresholds in the profile of both prompts, the
same values `effective_thresholds()` returns. It writes the percentages, and Stamind works out
the watts. So the week planner never does that arithmetic and never writes a watt into a step.

The prompt section PRESCRIBING INTENSITY (`coach/engine/sessions.py:planned_zone_task`)
becomes WRITING AN ENDURANCE SESSION: the fields above, the rule that the steps fill the
duration, the rule that the description holds no step, the rule that the prose and the
`summary` give no watts, beats or pace (§2), and the zone type per sport. Its old
"planned_zone_sec" field stays only for the sports with a zone type and no steps: on the two
instances today that is strength training and yoga, and an e-bike ride when one is planned.

## 4. Checking the answer, and asking once more

Stamind checks every running, cycling and swimming entry that writes a session, as soon as the
week planner answers, before anything is saved or put in a waiting proposal. An answer that
only keeps or drops a session already on the schedule (`keep`, `drop`) writes no session and
is not checked. An entry fails one of three checks:

1. **Shape.** Every step has a phase, and every step and every recovery a positive number of
   seconds, except at most one plain step (no `repeat`, not on a swim) whose seconds are
   `"remainder"`.
2. **Fit.** Without a remainder, the steps add up to `duration_minutes`. With one, at least 5
   minutes are left for it.
3. **Zone.** Every step has a zone of its sport's zone type, when the sport has one.

When any entry fails, Stamind asks the week planner once more, the way the strength planner
already gets two attempts (`strength/planner.py`, `MAX_ATTEMPTS`). It sends the same system
prompt, and the same user content with two sections added at the end: `## YOUR LAST ANSWER`,
quoting the answer, and `## WHAT TO FIX`, one line per failed entry, for example "Wed
2026-11-04 cycling: the steps without the remainder take 80 of the 75 minutes". The second
answer replaces the first as a whole.

If an entry of the second answer still fails, Stamind stores its steps as written and no
zone minutes, and the journal records the check it failed. It prints the steps when each has
its seconds, so the athlete reads the workout: a remainder that gets no time prints as
nothing, and the TOTAL shows what the steps add up to. A step list that cannot be printed is
not stored, and the session keeps its prose alone.

A step that names a threshold the athlete has no value for does not fail. It prints as zone
and effort (§2), the same printing a deleted threshold falls back to (§6).

**The story.** It is Sunday evening, and `workout generate` writes the coming week. Wednesday's
steps add up to 80 minutes against a 75-minute budget, and Saturday's long run has two
remainder steps. Stamind sends the answer back with those two lines. The week planner
answers again, with a warm-up of 10 minutes on Wednesday and one remainder on Saturday. Both
pass, and the week is saved. The athlete in the chat waits for one more "Writing your
sessions" while this happens. The week lock, which lets one thing at a time look at the week,
is held through both calls, so a tap in the chat waits for the second answer.

## 5. Printing and storing

**Printing.** Once an entry passes, Stamind works out the remainder's seconds from the
duration and prints the description in this order: the "[Title]" line, the step block, one
blank line, the week planner's prose. The block holds no blank line, so the first blank line
is the seam that splits the description, as on a gym day. On a gym day the week planner's
words sit above the seam; here they sit below it, so `coach/steps.py` splits the text
itself and takes only `title_line` from `strength/prescription.py`. Stamind also adds up the
seconds per zone and puts them in the entry's `planned_zone_currency` and `planned_zone_sec`,
the fields the week planner wrote itself until now. From there the entry is a normal one:
the waiting proposal, the chat's short line and Google Calendar read its description and its
zone minutes as before.

Wednesday's zone minutes, worked out from the steps: zone 1 = 15 + 3 × 2.5 + 10 = 32.5 min,
zone 2 = 27.5 min, zone 5 = 15 min. Together 75 minutes.

Rounding is for the screen only. The stored percentages and seconds are exact. Watts and beats
are printed to the unit, paces to the second, and a clock time shows seconds only when it has
some ("0:37:30").

**What the week planner is shown.** When a later `workout adapt` lists Wednesday, the week
planner reads its title, its prose, and its `steps` as JSON on one line: the shape
it wrote and writes again (`coach/formatting.py:_for_the_week_planner`). It never sees the
printed watts, the way it never sees a gym day's kilograms.

**Storing.** One new column on `workouts`:

| Column  | Type | Notes |
|---------|------|-------|
| `steps` | TEXT | The steps as JSON, as the week planner wrote them, `"remainder"` included: Stamind works it out from the row's `duration_minutes` each time it prints. NULL on every sport but running, cycling and swimming, on a session written before this column, and on an entry whose steps failed twice and cannot be printed (§4). |

`change.append(steps=...)` takes the steps as given, the way it takes the description, and
never carries them forward from the live revision: the printed block in the description must
always match them. `steps` joins `REVISION_COLUMNS`, the list `restore` and `void` copy. It
does not join the fields that decide a revision changed something (`PRESCRIPTION_FIELDS`):
the steps are printed into the description, so the description already tells. Sessions
already written keep their prose and get steps the next time the week planner writes them;
there is no backfill.

## 6. A new threshold reprints the sessions ahead

It is Saturday 7 November. The athlete does an FTP test at 10:00 and records 245 W with
`benchmark record` at 11:00. Wednesday 11 November was written last week and says "106–112%
FTP (250–264 W)".

Right after the result is saved, Stamind reprints every session from today on that has
steps, today included, so a threshold ride later the same day gets the new watts. For each
session, Stamind reads its stored steps and its prose under the seam, and prints the block
again with the thresholds now in use. No model call is made. Wednesday now says "106–112% FTP
(260–274 W)".

Each new revision is a copy of the live one, written by `WorkoutChange.restore` with the new
description: `restored_from` points at the live revision, and nothing else changes. So the
session keeps its reason, its short line and the kind it reads as: a session the athlete
asked to move still reads `[TWEAKED]` in `workout list` and keeps its `Reason:` line on
Google Calendar, and a heads-up line not yet told still stands (DESIGN_change_heads_up.md
§6).

The copies go under one change of a new kind, `reprint`, whose summary "Your FTP is now
245 W." is what `workout batches` lists. Closing it updates Google Calendar, as every change
does. The reprint holds the week lock from the moment it reads the live sessions until it
writes the copies: a `workout adapt` writing in between would otherwise be undone by a copy
of the revision it replaced. It prints every session first and opens the change only when
some text changed, so recording an e1RM writes no change.

A reprint that writes a revision is a newer change than any proposal waiting in the chat, so
that proposal closes as out of date (DESIGN_waiting_proposal.md §4), and the athlete asks
again.

`benchmark rm` and `benchmark wipe` reprint the same way, because deleting a result can change
the threshold in use. If no value is left, the steps that used it print as zone and effort.

## 7. Not handled

- **A proposal waiting when a test is recorded** closes as out of date when the reprint
  writes anything (DESIGN_waiting_proposal.md §4). Otherwise it keeps the numbers it was
  printed with until the week planner writes that session again.
- **`workout rollback` to a change before a reprint** undoes the reprint with it, because the
  undo goes back to a point in time (DESIGN_workout_revisions.md §10). The old watts come back
  until the week planner writes those sessions again. Rollbacks are rare.
- **Fonts.** The block lines up in the terminal only. Google Calendar, the chat and the two
  pages draw it in their own proportional font, so the gaps between columns are uneven. A
  fixed-width font would not help on a phone (choice 22).
- **Sending the steps to the watch, to Zwift, or comparing each interval with Garmin's laps.**
  Not asked for. The installed `garminconnect` 0.3.5 has functions to upload a running,
  cycling or swimming workout and put it on a date, if that is wanted later.

## 8. Choices

The author ruled on these in the interview:

1. *Ruled:* the steps are for cleaner text. Not for the watch, the calendar picture, or
   planned-against-done intervals.
2. *Ruled:* the week planner writes the steps, in its same answer. No new model call writes
   them, unlike a gym day's sets.
3. *Ruled:* the steps hold the main path only.
4. *Ruled:* running, cycling and swimming. A swim step holds its metres and an estimate of its
   time.
5. *Ruled:* the duration is the week planner's budget, and one step may be "the remainder".
6. *Ruled:* when the steps do not fit, ask the week planner once more; if they still do not
   fit, save the session without steps (§4).
7. *Ruled:* the zone minutes are worked out from the steps.
8. *Ruled:* aligned lines, a clock time at the start of each phase, a TOTAL line, the prose
   under the steps.
9. *Ruled:* a target is a percentage of the threshold with the absolute value in brackets;
   pace first for runs and swims.
10. *Ruled:* a new threshold reprints the sessions ahead.
11. *Ruled:* no threshold on record means zone and effort.

Made without asking; each stands until the author says otherwise:

12. **One threshold per kind, whatever sport it was tested in.** This is what Stamind does
    today: `latest_thresholds()` returns the newest LTHR whatever its sport, so the week
    planner already sees Piupiu's running LTHR of 172 bpm as her LTHR for every sport. Heart
    rate on a bike usually sits a few beats lower than on foot, so her ride targets may read a
    little high. The other way, a threshold per sport, changes that function, the prompt's
    profile and `benchmark list`, for everyone.
13. **The steps are a JSON column, not a table** like a gym day's `prescribed_sets`. A table
    pays off when code reads single steps, such as comparing each interval with a Garmin lap,
    and that is out of scope (choice 1).
14. **A remainder under 5 minutes fails the check.** Less than that is not a block anyone
    rides as one. *Objection by the review:* a 45-minute run of 10 min warm-up, 4 × (4 + 2)
    min and 8 min cool-down leaves 3 minutes of steady; the floor sends the whole prompt to
    the week planner again, a minute of "Writing your sessions" and twice the price, to
    remove a 3-minute easy block the athlete would simply run. Without the floor, check 2
    asks only that the remainder gets some time.
15. **The second ask resends the whole prompt,** with the first answer and the fixes at the
    end, and replaces the whole answer. A smaller call that rewrites only the failed session
    would be cheaper, but it would be a second way to write a session, outside the week
    planner's view of the week.
16. **The old zone-minutes field stays for sports without steps,** so strength and yoga
    sessions keep their zone minutes. *The review calls this forced:* nobody would drop them.
17. **Durations are written in seconds**, so a swim rest of 20 s is exact. *The review calls
    this a repeat of §3's `seconds` bullet.*
18. **A reprint is a change of its own kind, `reprint`,** so `workout batches` lists it apart
    from the week planner's changes, and `workout rollback` can undo it. *Changed by the
    review:* each session keeps its own reason and the kind it reads as (§6); "Your FTP is
    now 245 W." is the change's summary, not every session's reason.

Added by the review; each stands until the author says otherwise:

19. **The prose and the chat's short line give no watts, beats or pace** (§2). This is the
    cheapest way to meet choice 10: a reprint changes the step block, and the week planner's
    own words cannot be reprinted. The cost: the morning message reads "ride 66–74% FTP"
    rather than "ride 156–175 W". The other way keeps the numbers there, and after a new FTP
    they disagree with the block until the week planner writes the session again.
20. **A swim has no remainder step** (narrows choice 5). Its metres would be unknown, and the
    TOTAL line gives metres.
21. **The reprint starts today.** *Changed by the second review pass;* the first had it start
    tomorrow, so that a test already ridden keeps its text and its Google Calendar event is
    not pushed again. The story against it: the athlete tests on Friday at 19:00, the chat
    holds the result question overnight, they answer it Saturday at 07:00, and Saturday's
    09:00 threshold ride would keep the old watts. From today, the test ridden this morning
    shows the new watts in its text and its event is pushed once more; nobody rides it again.
    The day sheet and the details page show a past day as its short line, so the rewritten
    text is met on Google Calendar and in `workout show -d` only. If the author minds that,
    the cheapest shape with neither failure skips a test dated today: one condition.
22. **Choice 8's columns line up in the terminal only.** *Changed by the second review pass;*
    the first drew the block in a fixed-width font on the two pages, but on a phone about 41
    characters fit across, and Wednesday's 63-character WORK line wraps to column 0 anyway
    (§7). If the author wants the columns on the phone, the block must first fit about 40
    characters, for example with the target on the line under the phase.
23. **Steps that fail twice are stored as written and printed; their zone minutes are not
    stored** (narrows choice 6, which said "save the session without steps"). The story
    against "prose only": the week planner keeps the steps out of the prose, so on Wednesday
    the athlete would read the morning check and the fuel and no warm-up and no intervals,
    which is worse than today. The story against "printed but not stored", which the review
    tried first: nothing in the row would tell that session from one written before this
    design, so the week planner would be shown the printed watts, and Saturday's new FTP
    would never reach Wednesday's block. Storing the steps adds no state: every printed block
    has its steps behind it.
24. **The confirmation line after `benchmark record` stays as today.** The first pass added
    "4 sessions ahead now use it."; the day sheet showing 260–274 W is the proof, and the line
    would need a count and two renderers.

## 9. Amendments to other documents

- **DESIGN_intensity_distribution.md §9.8:** for running, cycling and swimming, Stamind works
  out the planned zone minutes from the steps; the week planner writes them only for the
  other sports. §10's "Parsing planned interval structure out of `description`" stays
  rejected: the steps are structured data the week planner writes, not prose parsed back.
- **DESIGN_prompt_structure.md §4:** `## YOUR LAST ANSWER` and `## WHAT TO FIX` at the end of
  the user content of `workout generate`, `workout adapt` and `workout tweak`, on the second
  ask only.
- **docs/ARCHITECTURE.md:** the `steps` column, the `reprint` change kind, the new module, the
  check and the second ask in the `workout generate` and `workout adapt` data flows, and the
  reprint in `benchmark record`, `benchmark rm` and `benchmark wipe`, and the `restored_from`
  row of the `workouts` table, which a `reprint` copy now carries too.
- **DESIGN_workout_revisions.md §3:** the same `restored_from` row.

## 10. Build order

1. **Steps module** `stamind/coach/steps.py`: the check (§4), resolving the remainder,
   working out the zone minutes, printing (§2, §5), splitting a description at its seam, and
   the reprint (§6).
2. **Schema 31:** the `steps` column, `append(steps=...)`, `REVISION_COLUMNS`, the `reprint`
   change kind with its label in `gcal/history.py:_KIND_LABELS`, and an optional
   `description` on `WorkoutChange.restore`. A one-off `ALTER TABLE` on each instance.
3. **Prompt:** WRITING AN ENDURANCE SESSION and the `steps` field in place of PRESCRIBING
   INTENSITY for the three sports, in both prompts; `_for_the_week_planner` shows the prose
   and the steps JSON. The `summary` example in both prompts (`coach/engine/generate.py`,
   `coach/engine/adapt.py`), "Ride easy at 155-175 W on a flat route. Ease off past 178 W.",
   becomes "Ride 66–74% FTP on a flat route." (choice 19).
4. **The ask:** one function in `coach/engine/sessions.py` that calls the week planner through
   `_eng.openrouter_client`, checks, asks once more if needed, and prints. The three call sites
   (`workout generate`, `workout adapt`, `workout tweak`) call it in place of `complete`. Both
   save paths (`coach/service/generate.py`, `coach/service/revision_apply.py`) pass `steps`
   to `append`.
5. **Reprint** after `benchmark record`, `benchmark rm` and `benchmark wipe`. Steps 1–4 can
   ship alone; meanwhile, after a test, the sessions already written keep the old watts until
   the week planner writes them again.

## 11. Tests

- The check: each of the three checks in §4 fails on its case, Wednesday's steps pass, its
  remainder resolves to 1,650 seconds, and a `keep` or `drop` answer is not checked.
- The ask: a stubbed week planner that fails once and then passes is called twice and its
  second answer is saved; one that fails twice is called twice and the entry is saved with
  its steps stored and printed and no zone minutes.
- Printing: Wednesday prints as in §2 with FTP 236 W; an LTHR target, a pace target, a swim
  and a step with no threshold on record each print their form; the zone minutes add up to
  the duration; `_for_the_week_planner` shows no watt.
- Reprint: recording FTP 245 W rewrites Wednesday under one `reprint` change as a copy that
  keeps its reason and its short line, and leaves a heart-rate session unwritten; recording
  an e1RM writes no change; deleting the only FTP prints zone and effort.
