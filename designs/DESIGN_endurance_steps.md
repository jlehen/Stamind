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
0:00     WARM-UP    15 min      easy, building to a sweat
                                two 1-min lifts to about 93% FTP (219 W)
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
fallback and the fuel stay as prose under the steps.

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

Other sports, hiit and gym days included, keep their descriptions as today.

## 3. What the week planner writes

Each running, cycling and swimming entry in the week planner's answer gets a `steps` list. The
description it writes holds only the prose: why the session is there, the morning check, the
advice. Wednesday's steps:

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
  the session's budget, decided top-down.
- **`repeat`** with a **`recovery`** is one interval set: work, then the recovery, N times. The
  recovery follows every repetition, the last one included. There is no deeper nesting.
- **`zone`** is the zone in the sport's zone type (power or heart rate), the one Stamind already
  picks per sport from the athlete's recordings (`_planning_zone_currencies`). Required on a
  run or a ride whose sport has a zone type; absent on a swim.
- **`target`** names one of the athlete's thresholds and a range. For `ftp` and `lthr` the range
  is in percent. For `threshold_pace` and `css` it is seconds slower than threshold, per km
  or per 100 m, and a negative number is faster. Optional: an easy step can carry only an
  effort.
- **`metres`** is on a swim step only, and the seconds beside it are the week planner's
  estimate of how long the metres take.
- **`effort`** and **`note`** are short words printed on the step's line and the line below it.

The week planner already sees the athlete's thresholds in the profile of both prompts, the
same values `effective_thresholds()` returns. It writes the percentages, and Stamind works out
the watts. So the week planner never does that arithmetic and never writes a watt into a step.

The prompt section PRESCRIBING INTENSITY (`coach/engine/sessions.py:planned_zone_task`)
becomes WRITING AN ENDURANCE SESSION: the fields above, the rule that the steps fill the
duration, the rule that the description holds no step, and the zone type per sport. Its old
"planned_zone_sec" field stays only for the sports with a zone type and no steps: on the two
instances today that is strength training, yoga and e-bike rides, which get heart-rate zone
minutes.

## 4. Checking the answer, and asking once more

Stamind checks every running, cycling and swimming entry as soon as the week planner answers,
before anything is saved or put in a waiting proposal. An entry fails when:

1. it has no steps, or a step lacks its phase or its seconds;
2. it has two `"remainder"` steps;
3. it has no remainder step and its steps do not add up to `duration_minutes`;
4. it has a remainder step and less than 5 minutes are left for it, or nothing at all;
5. a run or a ride step lacks its zone, or names a zone its zone type does not have.

When any entry fails, Stamind asks the week planner once more. It sends the same prompt with
two sections added at the end: YOUR LAST ANSWER, quoting the answer verbatim, and WHAT TO FIX,
one line per failed entry, for example "Wed 2026-11-04 cycling: the steps without the remainder
take 80 of the 75 minutes". The second answer replaces the first as a whole.

If an entry of the second answer still fails, Stamind saves that entry with its prose and
without steps, and the journal records which check it failed. Its zone minutes are then
missing too.

A step that names a threshold the athlete has no value for does not fail. It prints as zone
and effort (§2), the same printing a deleted threshold falls back to (§6).

**The story.** It is Sunday evening, and `workout generate` writes the coming week. Wednesday's
steps add up to 80 minutes against a 75-minute budget, and Saturday's long run has two
remainder steps. Stamind sends the answer back with those two lines. The week planner
answers again, with a warm-up of 10 minutes on Wednesday and one remainder on Saturday. Both
pass, and the week is saved. The athlete in the chat waits for one more "Writing your
sessions" while this happens.

## 5. Printing and storing

**Printing.** Once an entry passes, Stamind fills in the remainder's seconds, prints the steps
as in §2, and puts the printed block above the week planner's prose, with one blank line
between them. The block itself never holds a blank line, so the first blank line of the
description is the seam between the steps and the prose, the same seam a gym day uses between
its brief and its sets (`strength/prescription.py`). Stamind also adds up the seconds per zone
and puts them in the entry's `planned_zone_currency` and `planned_zone_sec`, the fields the
week planner wrote itself until now. From there the entry is a normal one: the waiting
proposal, the chat's short line, the calendar and Google Calendar read its description and
its zone minutes as before.

Wednesday's zone minutes, worked out from the steps: zone 1 = 15 + 3 × 2.5 + 10 = 32.5 min,
zone 2 = 27.5 min, zone 5 = 15 min. Together 75 minutes.

Rounding is for the screen only. The stored percentages and seconds are exact. Watts and beats
are printed to the unit, paces to the second, and a clock time shows seconds only when it has
some ("0:37:30").

**Storing.** One new column on `workouts`:

| Column  | Type | Notes |
|---------|------|-------|
| `steps` | TEXT | The steps as JSON, the remainder resolved to its seconds. NULL on every sport but running, cycling and swimming, on a session written before this column, and on an entry whose steps failed twice (§4). |

`change.append(steps=...)` takes the steps as given, the way it takes the description, and
never carries them forward from the live revision: the printed block in the description must
always match them. `restore` copies them with the rest of the row. `steps` joins the fields
that decide a revision changed something (`PRESCRIPTION_FIELDS`). Sessions already written
keep their prose and get steps the next time the week planner writes them; there is no
backfill.

## 6. A new threshold reprints the sessions ahead

It is Saturday 7 November. The athlete does an FTP test and records 245 W with
`benchmark record`. Wednesday 11 November was written last week and says "106–112% FTP
(250–264 W)".

Right after the result is saved, Stamind reprints every session from today on that has steps.
It reads each session's stored steps and its prose under the seam, and prints the block again
with today's thresholds. No model call is made. Wednesday now says "106–112% FTP (260–274 W)".
The new revisions go under one change of a new kind, `reprint`, with the reason "Your FTP is
now 245 W." Closing that change updates Google Calendar, as every change does. A session whose
targets do not use FTP prints the same text, so no revision is written for it. The record
confirmation adds one line: "4 sessions ahead now use it."

`benchmark rm` reprints the same way, because deleting the newest result changes the threshold
in use. If no value is left, the steps that used it print as zone and effort.

Only the four thresholds a step can name reprint: `ftp`, `lthr`, `threshold_pace`, `css`.

## 7. Not handled

- **A proposal waiting for a tap when a new threshold is recorded.** It was printed with the
  old one. A tap writes the old watts, and the next week planner pass prints the new ones.
  It takes a test result on the very day a proposal waits.
- **Alternatives in the prose.** The steps hold the main path only (*ruled*). "Ride 60 min easy
  instead" and "OUTDOORS / INDOORS" stay in the prose, with no steps of their own.
- **Sending the steps to the watch, to Zwift, or comparing each interval with Garmin's laps.**
  Not asked for. The installed `garminconnect` 0.3.5 can upload a running, cycling or swimming
  workout and put it on a date, if that is wanted later.
- **A recovery that is skipped after the last repetition.** The recovery follows every
  repetition. Two and a half easy minutes before an easy steady block cost nothing.

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
    little high. The other way, a threshold per sport, changes that function, the prompt's profile
    and `benchmark list`, for everyone.
13. **The steps are a JSON column, not a table** like a gym day's `prescribed_sets`. A table
    pays off when code reads single steps, such as comparing each interval with a Garmin lap,
    and that is out of scope (choice 1).
14. **A remainder under 5 minutes fails the check.** Less than that is not a block anyone
    rides as one.
15. **The second ask resends the whole prompt,** with the first answer and the fixes at the
    end, and replaces the whole answer. A smaller call that rewrites only the failed session
    would be cheaper, but it would be a second way to write a session, outside the week
    planner's view of the week.
16. **The old zone-minutes field stays for sports without steps,** so strength, yoga and
    e-bike sessions keep their zone minutes.
17. **Durations are written in seconds**, so a swim rest of 20 s is exact.
18. **A reprint is a change of its own kind, `reprint`,** so `workout batches` lists it apart from
    the week planner's changes, and `workout rollback` can undo it.

## 9. Amendments to other documents

- **DESIGN_intensity_distribution.md §9.8:** for running, cycling and swimming, Stamind works
  out the planned zone minutes from the steps; the week planner writes them only for the
  other sports. §10's "Parsing planned interval structure out of `description`" stays
  rejected: the steps are structured data the week planner writes, not prose parsed back.
- **docs/ARCHITECTURE.md:** the `steps` column, the `reprint` change kind, the new module, the
  check and the second ask in the `workout generate` and `workout adapt` data flows, and the
  reprint in `benchmark record` and `benchmark rm`.

## 10. Build order

1. **Steps module** `stamind/coach/steps.py`: the check (§4), resolving the remainder,
   working out the zone minutes, printing (§2, §5), and the reprint (§6). The seam functions
   of `strength/prescription.py` move where both modules can use them.
2. **Schema 31:** the `steps` column, `append(steps=...)`, `PRESCRIPTION_FIELDS`, the
   `reprint` change kind. A one-off `ALTER TABLE` on each instance.
3. **Prompt:** WRITING AN ENDURANCE SESSION and the `steps` field in place of PRESCRIBING
   INTENSITY for the three sports, in both prompts.
4. **The ask:** one function in `coach/engine/sessions.py` that calls the week planner through
   `_eng.openrouter_client`, checks, asks once more if needed, and prints. The three call sites
   (`workout generate`, `workout adapt`, `workout tweak`) call it in place of `complete`. Both
   save paths (`coach/service/generate.py`, `coach/service/revision_apply.py`) pass `steps`
   to `append`.
5. **Reprint** after `benchmark record` and `benchmark rm`, and the confirmation line.

## 11. Tests

- The check: each of the five failures in §4 fails, Wednesday's steps pass, and its remainder
  resolves to 1,650 seconds.
- The ask: a stubbed week planner that fails once and then passes is called twice and its
  second answer is saved; one that fails twice is called twice and the entry is saved
  without steps.
- Printing: Wednesday prints as in §2 with FTP 236 W; an LTHR target, a pace target, a swim
  and a step with no threshold on record each print their form; the zone minutes add up to
  the duration.
- Reprint: recording FTP 245 W rewrites Wednesday under one `reprint` change and leaves a
  heart-rate session unwritten; deleting the only FTP prints zone and effort.
