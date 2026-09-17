# Strength tracking: reading the sets, naming them, prescribing in kilograms

**Status:** Phase 1 implemented (§11.1) · Phase 2 draft (the watch's guesses in §6–§7, and §8–§10) · **Date:** 2026-09-17 (rev. 15) · **Branch:** worktree-strength-tracking-design

Revision 15 narrows what a failed strength planner call costs. It fails the proposal only
when a session was to be written. When sessions were only to be checked, they are kept, the
week planner's changes go through, and the athlete is told in the preview and the morning
briefing that the kilograms were not rechecked (§9).

Revision 14 takes the rest of what the athlete accepted from that review. A change the
strength planner makes to a session the week planner did not mention holds the day's other
sessions, or adapt's rule for a mentioned day would remove Thursday's intervals over a
kilogram (§9). The not-done lines stop at yesterday, since today's session can still be done,
and a day whose sets are not read yet says so (§8). A light day is one the strength planner
wrote as light and said so, and light days do not count toward an exercise's three days, so
the day to resume from is always on the page (§8, §10). When only the strength planner
changed something, the proposal's reason is its reasons, so the morning briefing says why
Thursday moved (§9). The duration counts, with the brief, as what a session's sets were
written under (§9). The `strength_checks` rows are written when a proposal is applied or
recorded as no change, never when it is proposed, and hold the stamp the history was built
from (§9). The stamp moves only when a read stored sets, and when the pull's reconcile
deletes a strength activity (§5, §9). And the sets follow the lineage: a session that
arrives with its lineage keeps them, which a `workout swap` and a `replace` in `workout
generate` do, and a move across dates in `workout adapt` does not do yet (§9).

Revision 13 takes the first fixes from a review of revision 12. `prescribed_sets` and
`strength_checks` are schema 16, since main reached 15 in the meantime. A session the athlete
added by hand is left out of the sessions to write and of what makes the strength planner
run, until the week planner writes a brief over it (§9). And "brief", a word this design
brought in and used without saying so, joins the names below.

Revision 12 fixes what a review of revision 11 found in phase 2. A session is written as a
rep range at one load, "3×4–6 @ 140": the reps are the athlete's dial and the load the
strength planner's, which is what the `prescribed_sets` rows already said and the rule and
example of §9 and §10 did not (§10). Every session of an exercise is written at the next
one's numbers, and the steps come as the sets come in, so a `workout generate` over five
weeks needs no ladder written ahead (§10). A light week is not a step: the rows remember it,
the history marks the day, and the week after resumes from the day before it (§8, §10). The
history lists what was prescribed and not done, chin-ups never lifted and a Thursday with no
activity, since the strength planner would otherwise write them again blind (§8). The
strength planner remembers per session which evidence it last weighed, so a "keep" is not
asked again the next morning with a fresh draw of randomness (§9). A session the week
planner revised or moved keeps its sets unless the brief or the evidence changed, the way
`workout swap` keeps them (§9). A strength planner call that fails twice fails the proposal,
as a failed week planner call does, so a session with a brief and no sets never exists, and
the one kept session without sets is one written before phase 2 (§9). And the smaller
things: the brief is stored with its blank lines collapsed so the seam holds, the stamp lives
in the settings table, the first question's drop says that the watch's names will not count,
`strength name` makes a waiting first question stale, and discarded days are skipped by an
exercise's last three days too (§5, §7, §8, §9).

Revision 11 aligns the words with the vocabulary sweep on main (AGENTS.md): "mesocycle"
for what earlier revisions called a block, "activity" for what Garmin recorded where earlier
revisions said session or workout, and "group" for consecutive unnamed sets at one load.
Nothing else changes.

Revision 10 moves the writing of a strength session from the week planner to a call of its
own, the strength planner, and fixes what a review of revision 9 found.

Revision 9 had the week planner write the session, "squat 4x4, hip thrust or RDL 4x4 at 8RM
load, press 3x5", and a second call fill in the exercises and the kilograms. That gave the
reps two authors. The week planner fixed them without ever seeing a set the athlete lifted,
since the strength history reaches the second call only, and §10 then asked the second call
to progress by double progression, where reps are one of the two dials it turns. It also
left the session short: the athlete's own September 7 held twelve exercises and forty-two
sets where the prose named four movements, and the accessories that made up the difference
could not be written at all, because the vocabulary the second call was shown had none. Now
the week planner writes a brief for a strength day, what the session is for and what the
plan asks of it, and the strength planner writes the whole session from that brief, the
athlete's recent sets, the athlete's own strength science and the day's equipment (§9).

The names. The **plan** is the periodization, the macrocycle and its mesocycles, written
by `plan generate`; a **mesocycle** is a few weeks of it with one focus. The **week
planner** is the LLM call inside `workout generate` and `workout adapt` that writes the
sessions of the coming weeks, several at a time, inside the mesocycles the plan gives it:
a day, a sport, a duration, an RPE, a load, a title and a description each. The **strength
planner** is the call this design adds: it writes a strength session from the week
planner's brief and the athlete's history. A **brief** is what the week planner writes as
the description of a strength day from phase 2 on: what the session is for and what the plan
asks of it that day, with no exercise, set, rep or load in it (§9). The word is this
design's own, and AGENTS.md gains it when phase 2 lands (§11). A **session** is a planned
workout and an
**activity** is what Garmin recorded, the way the tables already split them; a **strength
activity** is one that returned sets (§3). "The coach" is TrainMate speaking to the
athlete, whichever call wrote the words. The design uses these names and no others for
these things, and "group" for consecutive unnamed sets at one load (§7).

The review's other findings, each fixed where it lives: the watch-guess rules of §6 and §7
are phase 2's first piece and are marked as such, since phase 1 as built freezes an activity
whose only fault is a guess (§11.1); `prescribed_sets` is schema 15, not 14 (§11); the
command that copies a session to another date is `workout swap`, not a `workout edit` that
does not exist, and it copies the sets (§9); the history puts "prescribed" in one place, on
the day, and lists the accessories like any other exercise (§8); the strength planner is
shown each exercise's equipment class, which §4 promised it and §9 forgot (§9); a session
the athlete added by hand is shown for context and never asked about (§9); the reason for
changing a kept session lands in the revision's reason column, so the paths without a
preview keep it (§9); a kept session changes only on new evidence, a stamp the history's
writers bump, which also decides when the strength planner runs (§9); the shipped science
no longer schedules light weeks on its own, since the brief says when a week is light, and
it says how reps in reserve become a load (§10); and the amendment to the queue design's
list of kinds is withdrawn, because that list holds a pointer to §7 and nothing to amend
(§11).

Revisions 1–9 are in the branch history.

## 1. Motivation

TrainMate plans strength sessions but has no idea what happens in them. A completed
strength activity is stored as duration, average heart rate and an RPE for the whole of it
— the same shape as a ride, and about as informative as "went to the gym". The coach
therefore prescribes in relative terms, because relative terms are all it can defend:

> Gym, 65 min. Squat 4x4 and RDL 3x4 at 8RM load, 2–3 min rests, always 3+ reps in
> reserve. Press 3x5, row 3x5, core and mobility 10 min.

"At 8RM load" delegates the only number that matters to the athlete. The session is also
short: the athlete's September 7 held twelve exercises and forty-two sets where the prose
named four movements and "core". Today the athlete fills the gap by hand: a log of past
gym days (exercise, reps, weight — nothing else), pasted into a general-purpose LLM together
with TrainMate's prescription, to get a session with kilograms in it, which then gets
tweaked anyway. That is the athlete doing the coach's job because the coach cannot see the
logbook.

The logbook already exists in a place TrainMate can reach. The Garmin watch records
lifting set by set, Garmin Connect exposes them through the same API TrainMate
already logs into, and the athlete already opens Garmin Connect after training to fix
the numbers the watch got wrong. What is missing is the reading, a vocabulary to read it
into, and a coach that uses it.

## 2. Goals / Non-Goals

Goals:

- Store every recorded set (exercise, reps, load, duration, rest) of every strength
  activity Garmin holds from a configured date on, so that `workout compare` can show
  what was lifted and the coach can see an exercise's recent sets.
- Resolve exercise names with **no guessing**: a name counts only if a person gave it, on
  the watch, in Garmin Connect or in TrainMate. The watch's own guesses are shown, and
  count once the athlete has looked at them (§6).
- Show the strength planner, with no per-athlete configuration, what the athlete recently
  lifted on every exercise.
- Write the whole strength session, exercises, sets, reps and loads in kilograms, from
  those sets and a progression the coach can justify, so the hand-kept log and the outside
  LLM retire.
- Work for strength training in general — barbells, dumbbells, kettlebells, cables,
  machines, bodyweight — and for more than one athlete.

Non-goals:

- Writing back to Garmin. Garmin Connect is where the athlete edits; TrainMate reads.
- Activities from anywhere but Garmin. Every athlete on an instance wears the watch; a
  hand-typed activity or an import from an old log would need a second writer of the
  activities table and a way to keep the pull's deletion reconcile off it, and nobody
  needs either.
- Pushing planned sessions to the watch as guided workouts. Possible later (§12), not now.
- Per-set RPE, velocity, or notes. The athlete's own log never had them; the RPE Garmin
  asks for at the end of an activity is enough for load.
- Progressing accessory work by rule. Curls and lateral raises are written into the
  session from the history, at what the athlete last lifted, and count toward volume and
  fatigue; nothing progresses them (§9, §10).
- A number for an exercise's strength — a training max or an estimated 1RM — and a view
  of how it progresses. Nothing in phase 2 would read it (§12).
- A strength test on the calendar. Nobody on this instance has a strength goal (§12).

## 3. What Garmin actually gives

Verified against the athlete's account on 2026-09-04 with
`garminconnect.Garmin.get_activity_exercise_sets(activity_id)`. A strength activity
returns an ordered `exerciseSets` list alternating `ACTIVE` and `REST` entries. An active
set carries `exercises[0].category` and `.name` (Garmin's own vocabulary, e.g.
`BENCH_PRESS` / `DUMBBELL_FLYE`), `repetitionCount`, `weight` in **grams**, and
`duration` in seconds; a rest entry carries only its duration. Weight and reps are what
the athlete entered or corrected on the watch or in Connect, so they are as good as the
athlete's own log — from the day the athlete started correcting them.

That day is a setting: `strength.sets_since`, a date. Sets are read for strength
activities on or after it and never for earlier ones, which keep their summary row only.
Before that date the athlete did not correct the watch, so a 140 kg "row" that was a
deadlift sits in the record with a confident name, and nothing downstream can tell. The
one sentence for the athlete: "TrainMate reads your sets from this date on, because before
it the names were not checked."

The names are not as good as the numbers. Over the athlete's last 15 strength activities
(2026-06-24 → 2026-09-03, ~390 working sets), 47% of sets came back `UNKNOWN`, and some
named ones were wrong (`SIT_UP` at 100 kg). The pattern behind the noise is structural,
not random: the watch recognises exercises from wrist motion, so **free-weight and
bodyweight movements are usually named and cable or machine movements essentially never
are**. A whole activity on machines — belt squat, inclined leg press, cable row, chest press,
shoulder press, pulldown — comes back as a list of unnamed groups with correct reps and
loads.

After `sets_since`, a name a person picked is trusted, whether it was picked on the watch
or in Connect. That is a decision with a known cost: a wrong pick at a believable load —
"barbell row" tapped on a set that was a deadlift at 80 kg — gets past a glance at Connect
and lands in the barbell row's history. There is no better source of names than Garmin
plus the athlete, so the design accepts this and makes it visible instead, and `strength
name` fixes a wrong one after the fact. A name the watch guessed on its own is another
matter. Garmin reports it apart from a person's pick (§11.1), and it is not trusted until
the athlete says the activity's sets are final (§6).

Two consequences shape everything below. Naming is a permanent step in the workflow, not
a teething problem. And loads are not comparable across exercises: 110 kg on a pulldown
stack and 80 kg on a deadlift bar are both "kg", and the smaller number is the harder
lift. Nothing in this design ranks lifts by load.

A gym visit is not one activity. Garmin has no warm-up activity type, so the athlete
records the warm-up under a copied profile — this athlete picked cardio, another might
pick strength — and TrainMate's sport normalisation folds Garmin's `fitness` and
`indoor_cardio` types into `strength_training`, so a Tuesday at the gym can be two or
three "strength activities". **A strength activity is an activity whose raw Garmin type is
`strength_training` and that returned at least one set.** Sets are fetched for every
activity of that raw type, whatever the sport table folds it into afterwards, and an
activity that returns none is not a strength activity and keeps its summary row. No
duration threshold: in the athlete's record since July every warm-up is typed cardio and
every lifting activity is typed strength, and real strength activities of 15 and 18
minutes exist beside a day split into two lifting activities of 26 and 18. A warm-up
recorded under the strength profile either returns no sets, because nothing on a treadmill
looks like a rep, or returns a few unknown sets at 0 kg, which the first question of §7
shows and its drop or `strength discard` dismisses. **Everything below that
counts strength activities counts days**: a gym visit the watch split in two is one day.

The library also offers `set_activity_exercise_sets` (rewrite names on an activity),
`upload_workout` and `schedule_workout`, and `get_weigh_ins` (the athlete's scale, or a
weight typed into Connect). All four are deliberately unused: the first three by §2, the
last because body weight is not stored (§8).

## 4. Vocabulary: movement patterns and equipment

A shipped, static table maps every exercise TrainMate knows about to one **movement
pattern** and one **equipment** class. It ships with the code, like the zone tables in
`garmin/load.py`; nobody configures it. Garmin's category/name pairs are aliases into it,
and so are the plain-English names the athlete or the coach use.

Garmin's exercise vocabulary is finite and public. The table maps **all of it** at
authoring time (§11.1 says which lists that turned out to be), so "a Garmin name the table
does not know" cannot happen with today's firmware. If a later firmware adds one, the pull
stores the Garmin name in words as the exercise with no pattern, the set counts as volume,
and the pull output says "Garmin exercise names not in the vocabulary" so it gets added by
hand. No model call names an exercise on its own at runtime: that would be a guess nobody
sees. The one model call in the naming path proposes names the athlete confirms (§7).

Patterns are physiology, not preference, and there are nine:

| Pattern | Examples |
|---|---|
| squat | back squat, belt squat, leg press, goblet squat |
| hinge | deadlift, Romanian deadlift, kettlebell swing, hip thrust |
| single_leg | lunge, split squat, step-up |
| push_horizontal | bench press, machine chest press, push-up |
| push_vertical | overhead press, shoulder press machine, dumbbell press |
| pull_horizontal | barbell row, cable row, one-arm row |
| pull_vertical | pull-up, lat pulldown |
| core_carry | plank, sit-up, farmer's carry |
| accessory | curls, triceps extension and pushdown, lateral/front/rear-delt raise, chest fly, leg extension, leg curl, calf raise, hip abduction/adduction, face pull, shrug, back extension |

The accessory pattern is where isolation work lives. The history shows it like any other
exercise (§8), and the strength planner writes it into the session at what the athlete last
lifted, without progressing it (§9, §10); the pattern exists so the science can tell the
work it progresses from the work it carries along.

Equipment is one of `barbell | dumbbell | kettlebell | cable | machine | bodyweight`: the
equipment the exercise usually needs. It is read in two places:

1. **The watch-guess check.** A watch guess of a bodyweight exercise at a heavy load is not
   that exercise (§6).
2. **Substitution.** The strength planner picks exercises the day's equipment allows, and
   it is shown the class beside every name for that (§9). A travel week whose constraint
   says "hotel gym, dumbbells only" gets goblet squats and dumbbell RDLs where the home gym
   had the belt squat and the barbell. This is what makes a session survive a different
   gym.

The class does not say how to read a set's load. The athlete files the pec deck under a
suspension-trainer chest fly, a bodyweight exercise, and logs 60 kg on it (§11.1). The
history shows 60 kg, as recorded, and nothing reinterprets it because of the class.

The pattern says what a part of the session is for; the exercise says what was lifted. A
goblet squat done instead of a back squat does the squat's job in the session, and its sets
stay the goblet squat's: nothing adds them to the back squat's history.

**The load convention** is the athlete's, not Garmin's, because the athlete types or
corrects the weight: **the load is the weight moved in one rep**. Two 30 kg dumbbells
pressed together is 60; one arm at a time is 30; a renegade row is 30, because only one
dumbbell leaves the floor at a time. Reps on a one-sided exercise are per side. Garmin's
entry screen and most lifters write the weight of one dumbbell instead, and nothing in
the data can tell the two apart, so this is a fact about the person: **both athletes on
this instance log the pair.** It is not a setting until an athlete who logs per hand
exists. The convention is stated once, here and in the shipped strength science file
(§10), so the athlete logs and the strength planner writes the same way ("dumbbell bench
3×8 @ 60 (2×30)").

## 5. Data model

One new table:

```sql
CREATE TABLE exercise_sets (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    activity_id   TEXT NOT NULL,        -- completed_activities.activity_id
    seq           INTEGER NOT NULL,     -- position within the activity, rest entries included
    set_type      TEXT NOT NULL,        -- active | rest
    exercise      TEXT,                 -- canonical name from the vocabulary; NULL = unnamed
    garmin_name   TEXT,                 -- what Garmin said, verbatim, for audit
    reps          INTEGER,
    load_kg       REAL,                 -- as recorded; NULL when no weight was entered
    duration_sec  REAL,
    named_by      TEXT,                 -- watch | garmin | athlete; NULL while unnamed
    UNIQUE (activity_id, seq),
    FOREIGN KEY (activity_id) REFERENCES completed_activities(activity_id)
        ON DELETE CASCADE
);
```

Every row hangs off a Garmin activity, so the table needs no idea of where a row came
from. The foreign key is what makes the pull's deletion reconcile and the Garmin data wipe,
which both delete activity rows, take the sets with the activity. The reconcile itself is
untouched.

`load_kg` is stored as Garmin reports it, grams divided by a thousand; a weight of -1 or
none is stored as no load (§11.1). Nothing is rewritten when an unnamed set gets its name.

`named_by` is the no-guessing rule made auditable. `watch` means the watch guessed the name
and nobody has confirmed it. `garmin` means a person picked it, on the watch or in Connect.
`athlete` means the athlete gave or confirmed it in TrainMate. Only a name marked `garmin`
or `athlete` reaches the strength history (§8).

Three columns join `completed_activities`, and the summary upsert, which names its
columns, leaves all three alone on every pull:

- `sets_read_at` — when the sets were last read from Garmin; NULL until the morning after
  the activity (§6), so an activity whose sets are not in yet can say so.
- `sets_final_at` — when the sets were frozen (§6); NULL while the "are the sets final?"
  question waits (§7). From then on no pull touches the rows, and the naming question's
  subject carries this time (§7).
- `discarded` — the athlete ran `strength discard` on it (§7). Set by a person, never by
  the pull. It keeps the sets out of the strength history and the naming answers; the
  activity still counts toward training load, which never reads it.

Neither drop answer of §7 writes a flag: the queue's closed row remembers it.

Phase 2 adds two tables on the planned side, `prescribed_sets` and `strength_checks`, and
one stamp, `strength.history_changed_at`: a row of the `settings` table, written by code and
not a setting the athlete edits, bumped by every write that changes what the strength history
shows: a read that stored sets, a freeze, a name given or cleared, a discard or its undo, and
the pull's reconcile deleting a strength activity (§9).

## 6. The pull path

`garmin/sync.py::_ingest_activities` already iterates the activities in a window and
upserts one summary row each, raw Garmin type included. The sets are a step of their
own, run at the end of every pull, of every refresh a read command makes through
`ensure_data`, and of the morning push before its walk (§11): for each activity whose raw
type is `strength_training` (§3), dated on or after `strength.sets_since`, dated **before
today** and with `sets_read_at` NULL, it fetches the exercise sets, stores them (delete by
`activity_id`, insert the list) and stamps `sets_read_at`. Before today, because the
athlete corrects the watch in Connect the evening of the activity, and the morning after
is the first moment the numbers are usually right. Until then the activity is on record as
its summary row, and `workout compare` and "Done lately" print "sets not read yet" under
the activity line (§7), so an activity whose sets are still to come is never mistaken for
one that returned none.

**An activity's sets are read once and then frozen.** What the read finds decides when:

- Every set named by a person, or no set at all (§3): the activity is final on the spot,
  `sets_final_at` stamped, and nothing asks anything.
- Any set unnamed or only guessed by the watch, and the activity within the last seven
  days: the rows are stored, so they count as volume and `workout compare` shows them,
  and one question is queued (§7): are the sets in Garmin final? "Yes" reads the sets
  again at that moment, so a name fixed in Connect an hour earlier comes in, and freezes
  them. The watch's guesses still standing in that read become the athlete's
  (`named_by = athlete`), because the athlete has just said the names in Garmin are right.
  Then the naming questions are queued for whatever is still unnamed. Until the answer,
  the activity waits with its first read on record and `sets_final_at` NULL.
- Any set unnamed or guessed, and the activity older than seven days: frozen at once, as
  read. The first pull with `sets_since` months back reads hundreds of activities, and
  nobody is going to fix those in Connect. Their guesses stay guesses and their unnamed
  sets stay unnamed; `strength name` is how either gets a name (§7).

Everything these rules say about the watch's guesses is phase 2's first piece (§11). Phase
1 as built reads a guess as a name: an activity whose every set carries one is frozen on the
spot, and nothing lists, confirms or converts a guess (§11.1).

The athlete's Thursday, September 3, has one activity of each kind. The morning activity
at the gym was never checked in Connect: 19 sets, 14 named by the watch alone (barbell
deadlift, bench press, dumbbell flye, pull up, squat, triceps extension) and 5 it could
not name. The evening activity was checked, and two guesses were left standing: "lateral
raise", 12 reps at 16 kg, and "barbell deadlift", 12 reps at 16 kg, in an activity where
nothing weighed more than 16 kg. Under revision 7 that 12 × 16 would have become the
deadlift's most recent activity, and the strength planner would have read a deload that
never happened. Under this rule, on Friday morning, each activity queues its question. The
evening's reads "Thu Sep 3 20:45 gym session: the watch guessed 2 exercises (barbell
deadlift, lateral raise). Are the sets in Garmin final?". The athlete opens Connect,
changes the deadlift to a Romanian deadlift and answers "yes, final": the re-read brings
the fix in, and the lateral raise becomes the athlete's. On this instance the two
activities were in fact read eleven days late, on September 14, so both were frozen
without a question, and their guesses count for nothing until `strength name 2026-09-03`.

After the freeze no pull touches the activity's sets again, whatever window it is given:
the athlete's answers live in those rows, and a re-read that shifted one set would put
every answer after it one position off. A name fixed in Connect after the freeze reaches
TrainMate one way, `strength reset <date>` (§7). It reads the sets again, drops the answers
on them and freezes anew. The guesses still standing become the athlete's, for the same
reason as with "yes": the athlete runs it right after fixing names in Connect. Then it asks
about what is still unnamed. There is no re-fetch window, no carrying of answers by position
and no counting of sets: rev. 6 had all three, and a rep corrected in Connect while a
question waited, or a Garmin name the check below rejected, could lose an answer or a
question through them.

A watch guess gets one check at the read: **a guess whose equipment class is bodyweight,
on a set with a heavy load, is not that exercise**. `SIT_UP` at 100 kg is stored unnamed
with the Garmin name kept in `garmin_name`, and joins the naming question. The threshold is
a constant in the vocabulary, not a setting, and it sits above the 20–40 kg a strong
athlete adds to dips and pull-ups: 50 kg. It reads the weight field as the added load,
which it is (§11.1). A person's pick is never checked: people file loaded machines under
bodyweight names on purpose (§4).

## 7. Naming

The rule, and the one sentence that explains the feature to an athlete:

> TrainMate reads your sets from Garmin. Anything it can't name, it asks you about.

Three sources of names, in order of preference, and nothing else:

1. **Garmin.** Whatever the athlete picked on the watch or corrected in Connect. Since the
   athlete already opens Connect to fix reps and loads, fixing a name is the same gesture in
   the same screen; this is the primary path, before the freeze and, through `strength
   reset`, after it (§6). A name the watch guessed on its own counts once the athlete
   answers "yes, final" (§6).
2. **The athlete, through the queue.** Two questions, both queue kinds, neither asked on
   the spot: an unnamed group changes what TrainMate knows and holds nothing up, the sets
   already count as volume, and that is the case DESIGN_athlete_queue.md §2 sends to the
   queue even when the athlete is watching.

   **The first question, kind `sets_final`, asks whether the sets in Garmin are final.**
   The set-reading step queues it the morning after an activity whose first read found
   unnamed sets or watch guesses (§6), one per activity:

   > Thu Sep 3 09:43 gym session: the watch guessed 6 exercises (barbell deadlift, bench
   > press, dumbbell flye, pull up, squat, triceps extension) and couldn't name 5 groups
   > (sets 4, 12, 16, 18, 19). Are the sets in Garmin final?
   > [1] yes, final [2] no, leave it — the watch's names won't count [3] skip … [6] later …

   An activity with guesses only leaves out the second half of the sentence, one with
   unnamed sets only the first. Its subject is the activity, so it is asked once per
   activity, and `strength reset` freezes without asking. "Yes, final" reads the sets again
   from Garmin, freezes them, makes the guesses still standing the athlete's, and queues
   the naming questions for what is still unnamed; when Garmin cannot be reached the answer
   is not applied and the question stays waiting (§11). "No, leave it", the drop, freezes
   the sets as they were first read and asks no names: the guesses stay guesses, the
   unnamed groups stay unnamed, all of them count as volume, and `strength name` can still
   name them. Its label says what it costs, because "leave it as it is" and "yes, final"
   both read as "it's fine" at breakfast, and the wrong tap would keep six names out of
   the history for good; on an activity with no guesses it reads "no, leave it unnamed". "Not now", the queue's own, is "no, I'll fix them in Connect, ask me
   again": in 1 hour, in 1 day or after the others. The check calls the question stale
   when the activity was frozen by other means (`strength reset`, or `strength name`, which
   freezes an activity it names, §11.1), discarded, or is gone.
   The companion wording: "Thursday's 09:43 gym session has 6 exercises the watch only
   guessed and 5 groups of sets it couldn't name. Are the sets in Garmin final?" Both
   wordings say "gym session", because that is what an athlete calls a visit to the gym;
   the design's own word for the thing is activity.

   **The second question, kind `set_names`, asks what a group was.** It is queued at the
   freeze, one per group. **A group is consecutive unnamed sets at the same load**, reps
   ignored: within one exercise the reps drift (10, 10, 10, 9) while the load holds, and
   when the machine changes the load almost always changes with it. The question shows
   the whole group and offers the athlete's recent exercises:

   > Tue Sep 15 18:10 gym session, sets 5–8: 10, 10, 8, 8 reps @ 60 kg. What was it?
   > [1] leg press [2] belt squat [3] cable row [4] something else…
   > [5] leave it unnamed — drop, never asked again [6] skip … [9] later — after the others

   Choices 5 onward are the queue's own. The kind brings the five things §8 of the queue
   design asks a feature for:

   - **The subject** is the activity, the time its sets were frozen and the group's set
     positions, counted over active sets: `12345678901:2026-09-16T06:05:12Z:5-8`. The
     frozen rows never move, so the same positions are the same group for as long as the
     freeze stands, a group the athlete dropped is never asked about again, and
     `strength reset`, which freezes anew, makes every group of the activity a new subject
     and a new question: the athlete has just edited the activity and a new look is due.
   - **The wording**, written from the payload so it reads the same tomorrow: the date
     and start time, the positions, the reps and the load. The expert form is the line
     above; the companion reads "Tuesday's 18:10 gym session, sets 5–8: 10, 10, 8, 8 reps
     at 60 kg. What was it?". A group at 0 kg says so, which is how a warm-up recorded
     under the strength profile (§3) looks. The start time is always there, so a day with
     two lifting activities (§3) tells them apart even when the second reached Garmin
     after the first was read.
   - **The answers**, fixed when the item is queued: the exercises a person named in the
     athlete's last eight strength days (discarded ones skipped), the ones done on the
     most days first, at most nine, then "Something else…", which takes typed text.
     Names only the watch guessed are left out, so a wrong guess never becomes a one-tap
     answer. Fixed because the queue says so (§3 there): a button tapped tomorrow must mean
     what it meant when it was shown. A warm-up ramp of three groups still costs one tap
     per group, because its exercise is in the list; an exercise the athlete has never done
     before costs a typed answer per group of its first activity and is in the list from
     the next one on.
   - **The drop button** is "Leave it unnamed". It writes nothing: the sets stay unnamed
     and count as volume only, the group is never asked about again, and `strength name`
     can still name it later.
   - **The check** calls the item stale when the group it describes no longer stands: any
     of its sets has a name, the activity is discarded or gone, or it was frozen again by
     `strength reset`. Nothing compares reps or loads,
     because the frozen rows do not change. An answer given through `strength name`, a
     `strength reset` and a `strength discard` all close a waiting question this way, and
     none of them touches the queue.

   An answer names every set of the group with `named_by = athlete` and confirms it:
   "Named sets 5–8: leg press." Undoing it is `strength name` on the same day, where
   "leave it unnamed" clears the name — the reversibility the queue design (§9) asks of
   anything a tap can write.

   **"Something else…" takes free text, and the text goes through a model** — the one
   model call in the naming path. The tap starts the queue's text prompt (queue design
   §6.3), the athlete types "pec deck" or "seated row machine", and the naming call, shown
   the vocabulary, returns up to three candidate names. They come back as a blocking chooser
   with "none of these". The athlete has just typed and is there, and the answer cannot be
   applied without their choice: the one case §2 of the queue design keeps on the spot. A
   candidate chosen names the group. "None of these", Enter, and a timeout in chat write
   nothing and leave the question waiting, because the kind says it did not apply the
   answer and the queue then leaves the item open (§11); "Yes, final" leans on the same
   rule when Garmin is unreachable. Alias matching would not do: what people type does not
   line up with Garmin's names, and no hand-kept alias list covers it. This is not the
   guess §4 forbids, because the athlete sees it and confirms it, the same exception §12
   makes for template proposals. The path is rare: after a few weeks the recent-exercises
   list covers nearly everything the athlete does, and "Something else…" is for a
   genuinely new exercise.

   A group that is two exercises at one load (cable row 50, then pulldown 50) gets one
   name from the queue. Rev. 5 followed every answer with "all 6 sets, or how many?", a
   second question on every tap to catch a rare case, and that is gone. The tail of such
   a group is fixed the way any wrong name is: with `strength name`, which splits, or in
   Connect followed by `strength reset`.

   Alternating exercises cost taps. The athlete on this instance alternates in four
   gym days out of five: belt squat, push press, belt squat, push press. If the watch had
   named nothing in such an activity, every set would be a group of its own, because each
   set's neighbour is the other exercise, and eight sets would ask eight questions for two
   exercises. Asking once per load across the activity would ask two, and would also give
   one name to two machines that happened to share a weight, which is the wrong name this
   design exists to prevent. So the rule stays. Its cost falls on an athlete who neither
   names on the watch nor fixes names in Connect; in the five activities read here, 5 sets
   out of 105 were unnamed, all in the one activity nobody checked (§12).

   Where the athlete meets the questions is the queue design's business, not this one's.
   In Telegram they arrive after the morning briefing, one at a time with their buttons,
   and nothing waits: the athlete can answer at breakfast or in the evening, and "Not now"
   puts one off. In the terminal `tm queue` lists them, `tm queue answer` goes through
   them, and `status` and `workout adapt` say how many are waiting. This feature adds no
   surface of its own. The week of §1 of that design, seen from this side: Tuesday's
   machine activity leaves six unnamed groups. Wednesday's 08:00 push refreshes the last
   days (§11), reads Tuesday's sets for the first time, finds the six groups and queues
   the one question: are the sets final? The walk shows it after the briefing. If the
   athlete taps "Yes, final" at breakfast, the sets are read again and frozen there and
   then, and six naming questions are queued at 08:05. A walk covers only what was waiting
   when it started, so they arrive with Thursday's push, where the athlete names four,
   drops the chest-press warm-up and puts one off. If instead the athlete taps "Not now,
   in 1 day", spends Wednesday evening naming five of the six in Connect, and answers
   "Yes, final" to the reminder at 07:58 on Thursday, the re-read brings the five names
   in, one group is still unnamed, its question is queued at 07:58, and the 08:00 walk
   shows it. The cost of asking first is one morning: rev. 6 asked the names on Wednesday.
   The gain is that nothing done in Connect, before or after answering, can lose an answer
   or a question. 3. **Nothing.** An unnamed group is a legitimate state. It contributes
   to the activity's volume and fatigue and to nothing else.

What is explicitly *not* a source: inference. TrainMate does not conclude "the plan said
squat 4×4 and here are four sets of four, so this is squat", nor "most of this activity
matched the machine template so the rest is cable". Garmin's record is too unreliable and
the athlete too free-form (extra exercises, reordered machines) for a partial match to be
evidence, and a wrong name silently corrupts a lift's history. A watch guess is the watch's
own inference, which is why it waits for the athlete (§6). Grouping unnamed sets by
load is the one place the design infers anything, and the question shows every set so the
athlete sees what the answer will name. Template proposals — "this looks like your machine
day, same order?" with a one-tap confirm — remain a possible later convenience because
they still end in a human decision; they are out of this design (§12).

**Where the sets are shown.** `workout compare`, and "Done lately" in the companion, print
the activity's sets under the activity line, one line per exercise, and a line listing the
unnamed sets ("leg press 1×12 @ 65, 1×10 @ 70, 2×12 @ 70", "sets 8–11 unnamed"). A name
only the watch guessed carries `(watch)`, and nothing else is marked, since a name a person
picked is as good as an answer (§11.1). So a wrong guess is seen the morning after:
"barbell deadlift 1×12 @ 16 (watch)" in an evening of 16 kg kettlebell work. An activity
whose sets are not read yet (§6) prints "sets not read yet" in their place, in both
personas.

**Three commands do the surgery.** `strength name <date>` is the only command that asks
on the spot, and the queue's rule allows it that: the operator typed it, and the answer is
the whole of its work. It asks the naming question over any group of that day's activities,
named or not (a named group is consecutive sets with the same name), with the same answers
as the queued question and one more step after the name is picked: "all 6 sets, or how
many?", and the rest are asked again. Keeping the name of a group the watch guessed
confirms it. It is the way to fix a name without going through Connect, the only place a
group is split, and the way to name the backlog: the first pull with `sets_since` months
back freezes hundreds of activities and asks nothing about them (§6). A waiting question
about sets it names is stale from then on. `strength reset <date>` reads that day's
activities' sets again from Garmin, replaces the rows, drops the answers on them, freezes
them anew, makes the guesses still standing the athlete's and queues the naming questions
for what is still unnamed, seven days old or not: it is how a name fixed in Connect after
the freeze comes in, and how an activity read wrong gets read right. `strength discard
<date>` keeps an activity's sets out of the strength history — the hotel gym's leg press, a
warm-up recorded under the strength profile, an activity logged so badly it is not worth
fixing — and `--undo` reverses it. The sets stay stored. A discarded activity is skipped by
the strength history (§8) and by the naming answers, and its waiting questions are stale;
all of those are computed on every read, so the flag is the command's one write. The
activity still counts as training: its duration, RPE and load reach the week planner as
before, because nothing outside strength tracking reads the flag.

**On a day with two strength activities, `strength reset` and `strength discard` ask which
one**, offering each by its start time, then "all of them" and "none", the default. Take
September 3 (§6): the athlete fixes a name in Connect on the 09:43 activity and resets the
day. Acting on every activity of the date would also read the 20:45 activity again and drop
the names given to it, and discarding a warm-up recorded under the strength profile would
discard the activity beside it. The date stays the argument, because it is what the athlete
remembers: Garmin's activity number is eleven digits that no TrainMate screen shows.
`strength name` does not ask: it goes through every activity of the day, each under its
start time, and "keep it as it is" leaves a group alone.

## 8. The strength history

The strength planner cannot write kilograms without last time's kilograms. The **strength
history** gives it those: a text built on read from `exercise_sets`, one entry per
exercise, shown to the strength planner (§9) and to nothing else. Nothing is stored for it,
and it holds no computed number.

**Which exercises.** Every exercise that a person named (§5) in the athlete's last eight
strength days, discarded activities skipped, accessories included. Strength activities are
counted by day (§3). Each entry then shows that exercise's last three days, discarded ones skipped
again and light ones not counted, however far back they go from `sets_since` on. A light day
(§10) is shown when it falls after the oldest of the three, and is not one of them: an
athlete who lifts three times a week comes out of a light week with three light days on
record, and the day to resume from has to be on the page. The eight days decide which exercises appear, not how
much of each is shown. Accessories are in because the strength planner writes them into the
session (§9) and cannot write curls at 20 kg from a count of accessory sets; they cost a
line each.

Revision 7 showed "tracked" exercises instead: the ones done on three of the last eight
days, or named in a planned session. On this athlete's record that is one exercise. Four
strength days hold 23 exercises outside the accessory pattern. The goblet squat is on
three days; the Romanian deadlift and the one-arm row are on two; the other twenty are on
one, among them the belt squat, the lat pulldown and the push press the athlete does at
the gym every week. A strength planner shown one exercise prescribes the belt squat blind.
The planned half of the rule could not rescue it either, because the week planner only
names in a session what it was shown. Eight days of this athlete's lifting give about
forty entries with the accessories, some 2,000 tokens, which a call of its own can afford.

**What an entry shows.** The exercise with its pattern and equipment class from the
vocabulary. Then one line per day, newest first: the day, what was prescribed for that
exercise when a strength session planned that day had prescribed sets (§9), sets, rep range
and load, marked "(light)" when the session was a light week's (§10), then the sets as the
athlete did them with equal consecutive sets collapsed, and the activity's RPE. The
prescription sits on the day because it belongs to the planned session, not to an activity,
and when two strength sessions were planned that day each is listed with its title. The
sets of one exercise are listed together even when the athlete alternated it with another,
the way `workout compare` lists them (§11.1). From the athlete's record, as it stands on
September 14, when nothing had prescribed sets yet:

```
STRENGTH HISTORY (exercises a person named in the last 8 strength days; loads in kg as
recorded, per exercise, not comparable across exercises)
  belt squat (squat, machine)
    Mon Sep 7: 1×5 @ 120, 3×5 @ 140 | RPE 6
  goblet squat (squat, dumbbell)
    Thu Sep 10: 1×10 @ 36, 2×10 @ 44 | RPE 6
    Sun Sep 6: 4×12 @ 16 | RPE 2
    Thu Sep 3: 2×12 @ 16 | RPE 2
  romanian deadlift (hinge, barbell)
    Sun Sep 6: 3×12 @ 16, 1×13 @ 16 | RPE 2
    Thu Sep 3: 1×15 @ 16, 1×12 @ 12 | RPE 2
  glute bridge (hinge, cable)
    Mon Sep 7: 4×5 @ 130 | RPE 6
  barbell push press (push_vertical, barbell)
    Mon Sep 7: 1×5 @ 60, 1×4 @ 70, 1×6 @ 75, 1×5 @ 75 | RPE 6
  lat pulldown (pull_vertical, cable)
    Mon Sep 7: 1×6 @ 110, 1×6 @ 120, 2×5 @ 120 | RPE 6
  row (pull_horizontal, barbell)
    Mon Sep 7: 3×6 @ 120 | RPE 6
  ...
```

The hamstring curls, chest fly and calf raises of September 7 are entries like these, further
down. The row shows three sets where the athlete did four: the fourth is a watch guess nobody
has confirmed (§6). The morning of September 3 is missing altogether, deadlifts at 80 kg
included, because every name in it is a guess. Once a day has prescribed sets its line reads
"Mon Sep 14, prescribed 3×4–6 @ 75: 2×5 @ 75, 1×3 @ 75 | RPE 7", and in a light week
"Mon Sep 28, prescribed 2×4–6 @ 67.5 (light): 2×6 @ 67.5 | RPE 5".

**A day with two activities shows each on its own line.** Days still decide what is counted,
the eight days and each exercise's last three, but the sets of an exercise done in two
activities of one day are not merged. Say that on Tuesday September 22 the athlete does the
prescribed goblet squats at the gym at 09:00, and goblet squats again at 16 kg in an evening
activity at 20:10:

```
  goblet squat (squat, dumbbell)
    Tue Sep 22, prescribed 3×8–10 @ 44:
      09:00: 3×10 @ 44 | RPE 6
      20:10: 3×12 @ 16 | RPE 2
```

Merged into "Tue Sep 22: 3×10 @ 44, 3×12 @ 16", the evening reads as the morning's work
fading, which the strength planner answers by holding the load (§9), and the line has room
for one of the two RPEs. A gym visit the watch recorded as two activities (§3) shows as two
lines too, which is what happened. A day with one activity keeps its one line.

**What was prescribed and not done is listed too.** An entry shows an exercise only when
the athlete did it, so Monday's chin-ups, prescribed and never lifted, would appear nowhere,
and the strength planner would write them every Monday without knowing. After the entries
comes one line per day, from yesterday back to the oldest of the eight, for each day that had
a strength session with prescribed sets and did not do all of it: the exercises with no named set that
day, with what was prescribed, or the whole session when the day has no strength activity:

```
NOT DONE
  Mon Sep 14: chin up 3×3–5
  Thu Sep 17: no strength activity (belt squat 3×4–6 @ 145, glute bridge 4×4–6 @ 130, ...)
```

An exercise done and left unnamed is on the list too, since no named set matches it, which
is one more reason to answer the naming questions. A day where everything prescribed was
done gets no line. Today is never on the list: a session planned for today can still be
done, whatever the hour. A day whose activity's sets are not read yet (§6) reads "sets not
read yet", not "not done".

The loads are the weight field as recorded. On a pull-up that is the added load. Body
weight is not stored, and Garmin's weigh-ins are not read (§3). "pull up: 4×8, 2×6 @ 10" is
what the strength planner needs to write the next pull-up session. A number that puts body
weight and added load on one scale belongs to the progress view this phase does not build.

Two things revision 7 put in the entries are left out:

- **A number per exercise.** Revision 7 put a training max beside each entry: the Epley
  estimate of the day's best set. The prescription is written from the sets, as
  revision 7 already said, and on this record the estimate is noise for half the entries.
  It gives a farmer's walk 74 kg from one length carrying 72 kg, and a suitcase squat 17 kg
  from a set of two. It belongs to a progress view (§12).
- **The title of a constraint.** Revision 7 marked an activity that fell inside a
  constraint's dates with that constraint's title, so that a hotel gym's leg press would
  not be read as the home gym's. On this record every September activity would carry "No
  20-minute sustained climb available near home", a cycling constraint that runs from
  August 26 to September 30. Constraints are prose about anything, and most say nothing
  about the gym. An activity done on other equipment shows it in its loads, and one not
  worth reading is discarded (§7).

The history lives in `trainmate/strength/history.py`.

## 9. The strength planner

**The week planner writes a brief, not a session.** Today `workout generate` and
`workout adapt` write a strength session as its date, duration, RPE and load, and a
description that names the movements, the sets and the reps. Monday September 14, as the
week planner really wrote it:

> Gym, 70 min. Squat 4x4, hip thrust or RDL 4x4 at 8RM load, 2–3 min rests, 24–30
> lower-body reps and always 3+ reps in reserve. Press 3x5, chin-up 3x4, core 5 min.

From phase 2 on, the description of a strength day is a brief: what the session is for in
the plan, its character, and what the plan asks of it that day. The same Monday:

> [Full-Body Strength (Heavy, Non-Failure)]
> Heavy full-body strength, second week of the build, non-failure. 70 min at the gym. Keep
> the legs fresh for Saturday's long ride.

No exercise, no sets, no reps, no loads. The week planner has never seen a set the athlete
lifted, since the history reaches the strength planner only, and the rep range is chosen from
that history and the science (§10), so a rep count from the week planner would fix a number
it cannot read. The date, duration, RPE and load stay the week planner's: they are the week's
budget and the fit against the endurance days, and nothing about them changes. When the
week is a light one, the brief says so, because the plan's mesocycle says so; the
strength planner reads it there and nowhere else (§10). This is one instruction in the
week planner's TASK, for strength sessions only, one prompt region with one test beside the
regions `tests/test_prompt_gates.py` already pins. The reply schema does not change.

**The strength planner writes the session.** It is labelled `strength_planner` and runs
once per proposal, in the service, after the week planner's reply is parsed and before the
proposal is built: in `workout_generate` before the `GenerateProposal`, and in
`workout_adapt` after `structure_revision` and before the revisions are paired. So every
path that writes strength sessions gets it: the two commands with their previews, and
`replan` and the morning adapt, which apply without one. The precedent is
`_plan_reshape_verdict`, a small call of its own; this is the first one that carries science.

Two things follow from its place in `workout_adapt`. Adapt reads a date the proposal
mentions as holding only the sessions named for it, and removes the rest
(DESIGN_workout_revisions.md §9.1). The week planner knows that and names what it keeps. The
strength planner's change to Thursday's gym arrives after the week planner has spoken, on a
day it may not have mentioned. So when the strength planner changes a session the week
planner did not mention, code holds that date's other sessions, the way a keep marker does,
or Thursday's intervals would be removed because the belt squat went up 5 kg. And when the
week planner changed nothing, the proposal's reason, which is what the morning briefing
prints, is the strength planner's reasons, one sentence per session it changed, in place of
"No adaptation needed.".

**What it is given.**

- The shipped strength science (§10).
- The athlete's own science files, whole, the way every coaching call gets them today. This
  is where "3+ reps in reserve" and the athlete's preferences for how a session is built
  live, and where a household's second athlete says what she wants a gym day to look like.
  Revision 9 had them reach the second call through the week planner's prose, and the brief
  carries none of it. For this athlete that is three files, some 7,000 tokens; the science
  trim's tags are what cuts it later (§10).
- The vocabulary: every exercise outside the accessory pattern, 692 names, plus the
  accessory exercises in the athlete's history, each name with its pattern and equipment
  class: about 4,500 tokens. The class is what substitution reads (§4). The full accessory
  list would double the region with names nobody on the instance does.
- The strength history (§8).
- For each date it writes: the equipment the athlete profile lists for that weekday and in
  general, two lists in the profile, and the prose of the constraints active that day, which
  is where "hotel gym, dumbbells only" would be written. Equipment is not a constraint type,
  so these two places are all there is.
- The sessions to write: every strength session in the span that has no prescribed sets
  and is not the athlete's own, with its title, duration, RPE and brief. That is every new
  session the week planner wrote in this proposal, and a kept session written before phase
  2, whose old prose stands in for the brief.
- The sessions to check: every other strength session in the span that has prescribed sets,
  whether the week planner kept or revised it or it arrived from another date with its
  lineage (below), with the brief it has now and those sets.
- A session the athlete added with `workout add` is the athlete's own, and the code knows it
  by its source, "manual". It is shown as context only: never asked about, never written,
  and never a reason to run. The week planner may still revise it
  (DESIGN_plan_change_continuity.md §4.5), and when it does it writes a brief over the
  athlete's text, as for any strength day. In that proposal the session is a session to
  write like any other, and from then on it has prescribed sets and is checked like any
  other.

**What it returns.** For each session to write, its exercises in order: the name, the number
of sets, the lowest and highest reps, and the load in kilograms, or no load for a bodyweight
exercise with nothing added. Several entries may share an exercise, because a warm-up ramp
and the working sets are one exercise at several loads. With them come the session's notes:
the rests, the warm-up, a cue where one is due, and the starting point for anything with no
history, and whether it wrote the session as a light one, which the rows keep (§10). For each
session to check, it returns either "keep", or new exercises and notes with a reason.

**An exercise with no history gets a starting point, not a blank.** The load is one the
strength planner can defend from the equipment listed: the lightest bell at home, the empty
bar, a band, bodyweight. The notes name it as a starting point and say what reserve to
adjust it by. Only when nothing in the equipment supports a number, a machine at a gym
described as "full featured", does the exercise get no load and a note saying what to pick
one by. An athlete who follows the session to the letter should never meet a blank where a
number belongs.

**The description is built by code, not by a call.** The title in brackets, the brief, a
blank line, then one line per exercise rendered from the entries, then the notes. The blank
line is a seam code relies on: when the week planner is shown a strength session that has
prescribed sets, as a standing session in `workout generate` or a planned one in `workout
adapt`, it sees the title and the brief and nothing below the seam. It never meets a
kilogram, so it never copies one into a revision, and the strength planner is the only
author of loads. The brief is stored with its blank lines collapsed, so the first blank line
is the seam whatever paragraphing the week planner gave it. A kept session written before
phase 2 has the old prose above the seam, naming sets and reps that the lines below replace,
so when the strength planner writes it only its title line is kept up there. The kilograms the athlete reads and the kilograms stored as data cannot
disagree, because both are rendered from the same rows. Monday September 14 after the
strength planner, shown the history of §8 with its accessories and Monday's "full featured
gym":

```
[Full-Body Strength (Heavy, Non-Failure)]
Heavy full-body strength, second week of the build, non-failure. 70 min at the gym. Keep
the legs fresh for Saturday's long ride.

Belt squat 1×5 @ 120, 3×4–6 @ 140 kg
Glute bridge 4×4–6 @ 130 kg
Barbell push press 3×4–6 @ 75 kg
Lat pulldown 3×4–6 @ 120 kg
Chin up 3×3–5
Hamstring curl 2×12 @ 45 kg
Calf raise 2×15 @ 60 kg
2–3 min rests on the first four, 3+ reps in reserve throughout. Chin-ups start at
bodyweight; add 5 kg once 3×5 is clean.
```

The belt squat, the glute bridge, the pulldown and the push press are there because they
are what the history holds for a Monday at the gym, at the loads they hold: September 7's
belt squat, 3×5 at 140, did not reach the top of a 4–6 range, so 140 stands (§10). The
accessories are there at what the athlete last lifted. The chin-up has no load and a starting point: the history has no
chin-up a person named. Wednesday September 16 is at home, where the profile lists
kettlebells up to 24 kg, and the brief reads "moderate full-body strength at home, 45 min,
easy enough to be fresh for Thursday's intervals". The strength planner writes the goblet
squat at 48 kg, the heaviest pair of bells at home, the one-arm row at 24 kg, and a
kettlebell floor press at 2×16 as a starting point, because no press done at home is in the
history.

**Checking a kept session.** A kept session's kilograms go stale when the athlete lifts. Say
Monday's belt squat goes 6, 6 and 6 at 140 kg: every set at the top of its range. Tuesday
morning the pull reads Monday's sets. Thursday September 17 holds two sessions, the intervals
and the gym, and the gym session, written on Sunday, holds "belt squat 3×4–6 @ 140",
Monday's numbers, since nothing is written ahead as a ladder (§10). On Tuesday `workout adapt` runs, and the week planner keeps
Thursday. The strength planner is shown Thursday with its prescribed sets, and the history,
which now says "Mon Sep 14, prescribed 3×4–6 @ 140: 3×6 @ 140 | RPE 7". It answers with
Thursday's exercises, the belt squat at 145 kg, and the reason "Monday's sets all reached 6
at 140; add 5". Had Monday gone 5, 5 and 3, the answer would be "keep": a set under the
bottom of the range holds the load. The preview shows a change like any other revision of a
committed session.
The reason lands in the revision's `reason` column, the one the no-op rule ignores
(DESIGN_workout_revisions.md §9), so `replan` and the morning adapt, which apply without a
preview, keep it where adapt's per-session reasons go, `workout batches`. The morning
briefing prints the proposal's reason, which is the strength planner's when only it changed
something (above).

Code decides whether an answer changes a session, from the sets and not from the words.
The exercises returned are compared with the stored prescribed sets as a list. When they
match, a kept session is kept and nothing is appended, whatever the notes say, and a session
the week planner revised gets its revision with the sets copied under the new brief. So
wording alone never touches the kilograms.

**The sets follow the lineage.** A session that arrives on a date with its lineage
(DESIGN_workout_revisions.md §4) is the same session, so it is a session to check and keeps
its sets and its `strength_checks` row. A `workout swap` does that, and so does a `replace`
in `workout generate`, which names the date a session came from. `workout adapt` cannot say
that yet: a week planner that moves Thursday's gym to Friday for the rain returns a rest day
on Thursday and a gym session on Friday, two unrelated changes to TrainMate, so Friday starts
a lineage and is written anew, at the next one's numbers like every session (§10).
DESIGN_plan_change_continuity.md already notes that adapt may adopt `replaces`; the day it
does, Friday keeps Thursday's sets with nothing to change here.

**A session's sets change on new evidence only.** A kept session is one the week planner
promised would not change, and inside the committed days the athlete has planned around it
(DESIGN_plan_change_continuity.md). The strength planner's answer has the randomness of any
model call, so without a rule a kept Thursday could come back at 142.5 where it stood at 145,
for no reason anyone can defend. The evidence is a stamp, `strength.history_changed_at` (§5),
bumped by every write that changes what the history shows: the set-reading step when it
stored at least one activity's sets, and not on the mornings it finds nothing to read, a
freeze, a name given or cleared, a discard or its undo, and the pull's reconcile when it
deletes a strength activity that had sets. The stamp is one for the whole history: naming
a lat pulldown group from two weeks ago is new evidence for every session in the span. What
the strength planner has weighed is remembered per session, in a small table:

```sql
CREATE TABLE strength_checks (
    lineage_id       INTEGER PRIMARY KEY,   -- workouts.lineage_id: the session
    checked_against  TEXT NOT NULL          -- the stamp when its sets were last written or checked
);
```

Writing a session's sets and checking them both set its row, to the value the stamp had
when the history shown to the strength planner was built and not to the clock: sets read
while a preview waits were not weighed. The rows are written when the proposal is applied,
and when it is recorded as no change, in the same transaction. Proposing writes nothing, as
everywhere in TrainMate, so a proposal declined at the preview leaves no row and the next
adapt asks again. A change to a session to check is applied when the stamp is later than its
row, or when the brief or the duration is not the one its sets were written under: a
Thursday the week planner cut from 70 to 40 minutes gets its four exercises in place of
seven even when the brief's words stand. Otherwise the answer is dropped and the sets
stand. The row is what keeps a "keep" from being asked again: Monday's sets are read on
Tuesday, Tuesday's adapt weighs Thursday against them and keeps it, and Wednesday's adapt,
with the stamp where it was, does not ask, so the randomness gets no second draw. A revision
the week planner made with the brief and the duration unchanged keeps its sets for the same
reason, and so does a session that arrived with its lineage, which the row follows.

The same stamp says when the strength planner runs at all: when the week planner wrote or
revised at least one strength session, when a strength session in the span has no prescribed
sets and is not the athlete's own, or when the stamp is later than the row of a strength
session in the span. Otherwise
there is nothing new to write from, and a morning adapt in a week with no lifting costs no
call. An adapt whose week planner changed nothing still becomes a proposal when the strength
planner updates a kept session.

**Checking the output.** Every exercise name is looked up in the vocabulary. Sets and reps
must be whole numbers above zero, with the lowest reps not above the highest, and a load
must not be negative. An entry that fails is dropped with a line in the preview — "Mon Sep
21: 'Nordic curl' is not an exercise TrainMate knows, left out" — and the rest of the
session is written. A session to write whose every entry fails counts as a failed call, and
a session to check whose every entry fails is a "keep". When the strength planner's call
fails it is tried once more. What a second failure costs depends on what was asked.

With a session to write in the proposal, the proposal fails, the week planner's changes with
it, the way it does today when the week planner's call fails: nothing is written, the command
says so in the terminal, and the morning push renders the schedule as stored, the error a
terminal aside (DESIGN_bot_simple_frontend.md), and tries again the next morning. A strength
day with a brief and no exercises is worse than yesterday's schedule, so a session with a
brief and no sets never exists. The kept sessions without prescribed sets are the ones
written before phase 2 and the athlete's own.

With only sessions to check, the failure is a "keep" for all of them. Their sets stand, the
week planner's changes are applied, and no `strength_checks` row is written, so the next
adapt asks again. Say that on Tuesday September 15 the week planner eases today's intervals
to an easy hour after a bad night, and the strength planner, asked about Thursday, times out
twice: the easing reaches the athlete, because nothing about Thursday's belt squat needed
deciding before Thursday. The athlete is told, in one sentence the proposal carries as a
notice: "I could not recheck Thursday's kilograms this morning. They stand as written, and I
will look again tomorrow." The preview prints it, and the morning briefing's note includes
it whether or not anything else changed, which covers the morning of the gym day itself. It
does not go into the session's description: that text is rendered from the stored rows, so a
line added to it would be a new revision of a session whose content did not change, and one
more the next morning to take it out.

**Where the prescribed sets live.** A new table, schema 16:

```sql
CREATE TABLE prescribed_sets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    workout_id  INTEGER NOT NULL,   -- workouts.id: the revision these sets belong to
    position    INTEGER NOT NULL,   -- order in the session, from 1
    exercise    TEXT NOT NULL,      -- vocabulary name
    sets        INTEGER NOT NULL,
    reps_low    INTEGER NOT NULL,
    reps_high   INTEGER NOT NULL,
    load_kg     REAL,               -- NULL: no load
    light       INTEGER NOT NULL DEFAULT 0,  -- 1 on every row of a light week's session (§10)
    UNIQUE (workout_id, position),
    FOREIGN KEY (workout_id) REFERENCES workouts(id) ON DELETE CASCADE
);
```

Planned sessions are append-only: every change to a session is a new row in `workouts`, and
no row is ever updated (DESIGN_workout_revisions.md). The prescribed sets belong to one row,
so they inherit that rule. `WorkoutChange.append` takes them and writes them in the same
transaction as the row. When the rule against no-op revisions suppresses the row, the sets
are not written either, and the live row's sets stand. That is always right, because the
description is rendered from the sets: different kilograms make a different description.
`WorkoutChange.restore`, which `workout restore`, rollback and goal reinstate use to bring
back an earlier revision, copies the sets of the revision it restores. `workout swap`, which
moves a session to another date by appending a copy of it, copies the sets with it, or the
moved session would carry kilograms in its text with no rows behind them. `workout add`
starts a new lineage and has none. A void has none. The cascade is there for the wipes, the
only code that deletes planned sessions. Revision 7 also stored the pattern; the vocabulary
gives it from the exercise, so the column is gone.

**The preview shows the kilograms.** `workout generate`'s preview prints one line per
session today, without the description, so kilograms written before it would be accepted
unseen. Phase 2 prints the exercise lines under each strength session, in both personas.
`workout adapt`'s preview already shows how a description changed.

**Cost.** About 4,500 tokens of names, 2,000 of history, 1,000 of shipped science, the
athlete's own science files, 7,000 for this athlete and nothing for one without them, and
200 to 300 per session. A `workout generate` over a five-week mesocycle with ten strength
sessions sends about 17,000 tokens and gets about 2,500 back: a third of one `workout adapt`
prompt. It uses the same model as every other call, since TrainMate picks one model per
process.

**What adherence becomes.** Revision 7 compared prescribed and done sets in code. It had
three deviations and two thresholds, a load more than 10% off and reps more than half the
range away, and it gave the week planner a line per session so the week planner would know
to revise a kept session whose numbers had gone stale. The strength planner now checks the
kept sessions itself, from the history, which prints what was prescribed beside what was
done. The week planner learns nothing new about strength: it keeps reading the session's
duration, load and RPE, as it does today. Substitution needs no rule either. On September 7
the week planner asked for back squat, Romanian deadlift, pull-ups or rows and overhead
press, and the athlete did the belt squat, the glute bridge machine, the lat pulldown, the
row and the push press. Now the week planner asks for nothing by name, the history shows
what was done, and the strength planner writes the next Monday from that.

## 10. The strength science

The strength planner is told how to progress by a file that ships with the app,
`trainmate/strength/progression.md`, and only the strength planner reads it. It does not go
in `trainmate/science/`: the science loader sends every file there, whole, to every coaching
prompt, and will until the science trim lands (TODO §PROMPT). A progression rule is of no
use to the week planner, whose adapt prompt is already about 50,000 tokens. When the trim
lands, the file can move there with a tag for this call, and the same tags are what will
keep the athlete's own files, which the strength planner reads whole today (§9), down to
the ones about strength. Phase 2 does not wait for it.

Its content is double progression, stated so the strength planner can defend a number.
Each exercise is written as a rep range at one load, "3×4–6 @ 140". The range is the
strength planner's choice from the brief and the athlete's own science, a heavy day in a low
range, a moderate one higher, and it stays the same from one session to the next. The
athlete lifts as many reps in the range as the reserve allows, so the reps are the athlete's
dial. The load is the strength planner's, and it goes up by the smallest step the equipment
allows (2.5 kg for the upper body, 5 kg for the lower, whatever a stack or a set of
kettlebells offers) in the session after every set reached the top of the range with the
reserve intact. Otherwise it holds: a set under the bottom of the range holds it with a note,
and a second such day in a row takes one step off. A new load always comes with the same
range, so the two dials never move together.

**Every session of an exercise is written at the next one's numbers.** A `workout generate`
writes ten strength sessions from one history, and a step depends on reps not yet lifted, so
nothing is written ahead as a ladder: the belt squat is 3×4–6 @ 140 on every Monday of the
mesocycle, a light week's reduction apart. The steps come as the sets come in, through the
check of §9, which rewrites the sessions in the span from the history as it stands, and a
session outside the span is checked when it comes into one.

**The plan decides when a week is light; the file says how much.** The plan holds no field
for a light week: a mesocycle is a name, two dates and a focus in prose, and the week planner
carries "light week" from there into the brief (§9). When the brief says the week is light,
the strength planner brings the load down a tenth, rounded to the equipment's step, removes
one set, and says in its answer that it wrote the session as a light one. **That answer is
what a light day is**: a day whose session's rows carry `light`, which the history prints as
"(light)" (§8). It records what the strength planner did to the numbers, in the call that
did it, so the mark and the numbers cannot disagree, and nothing reads the brief a second
time to find out. A day the athlete lifted less on their own is not a light day: it is a day
under its range, and it holds the load. A light
week is not a step: the week after resumes from the last day that was not light, at its
load, plus a step if that day's sets all reached the top. The file never counts weeks: the
strength planner sees one proposal and three days per exercise, and the plan's mesocycles
are where a light week is decided.

**Reps in reserve are reps not done.** The athlete's own science says how many reps to keep
in reserve, and the week planner's prose no longer carries it, so the file states how it
enters the number. The load for a range whose top is n reps, with r in reserve, is the load
for n + r reps: a 4–6 range with 3 in reserve is written at a 9-rep load. A new rep range starts from the heaviest
recent set in that range; when there is none, from a recent set converted with the Epley
formula (load × (1 + reps/30)), with a tenth taken off, and the reps in reserve the session
asked for added to the reps done before converting, since a set of 5 at 140 stopped with 3 in
reserve was an 8-rep set. The activity's RPE is the one reading of how hard a day was: an
activity at RPE 8 where 3 in reserve were asked was harder than asked, and the next one holds
the load.

Accessories are written at the reps and load the athlete last did them, and nothing
progresses them (§2). The athlete moves them in the gym, Connect records it, and the history
follows.

An exercise with no history gets a starting point from the equipment (§9). The load
convention of §4 is in the same file. Where the athlete's own science and this file
disagree, the athlete's wins, the way the shipped and the athlete's science regions are
already ranked in every coaching prompt.

## 11. Phasing

**Phase 1 — data, no prompt changes.** The vocabulary table with the full Garmin mapping,
`exercise_sets` and the three activity columns, the `sets_since` setting, the set-reading
step with its one-night wait and its freeze (§6), the `sets_final` and `set_names` queue
kinds with the model-backed "Something else…", `strength name`, `strength reset` and
`strength discard`, and sets shown in `workout compare` / "Done lately" with their name
source and the "sets not read yet" line — both of which rendered a strength activity as
duration, load and RPE only (`cli/common.py::format_actual`,
`cli/render.py::simple_compare_lines`). At the end of it TrainMate knows what the athlete
lifts and the coach does not use it yet. Deliberately boring, so it can be checked against
reality before anything depends on it.

It amended two implemented designs. DESIGN_athlete_queue.md: its list of kinds (§8) gained
`sets_final` and `set_names`, and its §4 the rule that an answer whose kind did not apply it
leaves the item waiting. DESIGN_bot_simple_frontend.md: the morning push runs the
recent-data refresh a read command runs, whatever the adapt-first setting says and whether
or not a session is planned today, then the set-reading step, then its walk.

**Phase 2 — the strength planner.** Six pieces, in this order, each usable before the next:

1. The watch's guesses (§6, §7). A guess does not make an activity final on its own; the
   first question lists the guesses and its drop is "no, leave it — the watch's names won't
   count"; "yes, final" and
   `strength reset` make the guesses still standing the athlete's; keeping a guess in
   `strength name` confirms it; and the naming answers come from names a person gave.
2. The strength history, `trainmate/strength/history.py`, accessories and the not-done
   lines included (§8), and the `strength.history_changed_at` stamp its writers bump (§5).
3. `prescribed_sets` and `strength_checks` (schema 16), with `WorkoutChange.append`,
   `restore` and `workout swap` carrying the sets, and the description split at its seam when a strength session is
   shown to the week planner (§9).
4. The strength science, `trainmate/strength/progression.md` (§10).
5. The strength planner, `trainmate/strength/planner.py`: the brief instruction in the week
   planner's TASK, its own prompt, the checks on its output, the comparison and the evidence
   rule for a kept session, and its place in `workout_generate` and `workout_adapt` (§9).
6. The exercise lines in the `workout generate` preview (§9).

Three implemented designs are amended when it lands. DESIGN_workout_revisions.md: a revision
can carry prescribed sets, written with it and copied by a restore and a swap.
DESIGN_plan_change_continuity.md: a standing strength session with prescribed sets is shown
to the week planner as its title and brief, not its full description.
DESIGN_bot_simple_frontend.md: the morning adapt's note includes a proposal's notice, even
when the proposal changed nothing. AGENTS.md's list of words gains "brief". The queue design's
list of kinds needs nothing: it points at §7 for both kinds and holds no wording of its own.

**The science trim** no longer comes between the phases (§10). It is still worth doing for
its own sake: about 15,000 of the adapt prompt's 50,000 tokens are science files sent whole
to every command.

### 11.1 Phase 1 as built

The two facts were checked on 2026-09-14 against nine of the athlete's activities from
August 20 to September 10, read from the sets endpoint. Both came back usable, and the same
reading turned up three things the design did not expect.

**What the weight field carries on a bodyweight exercise.** The added load, never body
weight. Pull-ups come back at 0, a dead bug at -1, an ab twist with no weight at all. So the
50 kg check ships, and -1 or no weight is stored as "no load".

**Whether Garmin says who named a set.** It does. A name a person picked, on the watch or
in Connect, comes back as one candidate at 100%. A name the watch guessed comes back as up to
three candidates with their probabilities: barbell deadlift 69%, unknown 30%. So `named_by`
has three values: `watch`, `garmin` for a person's pick in Garmin, and `athlete` for an
answer given in TrainMate. The lines under the activity mark the watch's guesses with
`(watch)`, and nothing else is marked: a name a person picked is as good as an answer.

**The 50 kg check applies to the watch's guesses only.** The athlete picks the nearest name
Connect offers, even from the wrong category. On September 7 the pec deck at 60 kg is filed
as the suspension trainer's chest fly, and a hip-thrust machine at 130 kg as the banded glute
bridge. Checked against the athlete's pick, the rule would erase names a person chose.
Checked against the watch, it still catches the case it was written for: on September 1 the
watch guessed "sit-up" at 100 kg, and that set is stored unnamed with Garmin's guess kept.

**A set can name a category and no exercise.** On September 7 the athlete tagged three sets
at 120 kg as "Row" and chose no row. Such a set takes the category's own generic exercise,
"row", which Garmin's catalog also lists.

**The vocabulary is Garmin Connect's catalog, not the FIT file format's lists.** Connect
uses names the FIT SDK lacks (`BELT_SQUAT`, which the athlete logs weekly), and it publishes
its exercise catalog with a bodyweight flag per exercise
(`connect.garmin.com/web-data/exercises/Exercises.json`, 1,531 names). The shipped table is
that catalog, the FIT SDK names it lacks (mostly yoga, Pilates and wheelchair variants), and
seven gym machines neither has, such as the pec deck and the machine chest press: 1,493
exercises and 1,934 Garmin names in `trainmate/strength/exercises.tsv`. A weighted variant
of a bodyweight exercise is the same exercise, so a weighted pull-up adds to the pull-up's
history, its load read as the added load.

**The lines under the activity group by exercise, not by consecutive sets.** The athlete
alternates two exercises: belt squat, push press, belt squat, push press. Collapsing
consecutive equal sets turned September 7 into 42 one-set lines. Grouped by exercise, in the
order the exercises first came, it is 12 lines, one per exercise; unnamed sets, when an
activity has any, share one line listing their positions.

**`strength name` on an activity still waiting for "are the sets final?" freezes it first.**
Otherwise a later "yes, final" would read the sets again and drop the names just given.

**`tm st` is still `status`.** `strength` shares the prefix, so `st` became an alias, the
way `s` already was.

**The watch's guesses are stored and shown, and nothing else yet.** A set the watch named on
its own is stored with `named_by = watch` and marked `(watch)` under the activity, and that
is the whole of phase 1's handling. An activity whose every set carries a name is frozen on
the spot, guesses included; the first question lists the unnamed groups only and drops with
"leave it unnamed"; "yes, final" and `strength reset` read the sets again and store what
Garmin says, so a guess comes back a guess; "keep it as it is" in `strength name` writes
nothing; and the naming answers are drawn from every named set, guesses among them. What §6
and §7 say about guesses beyond this is phase 2's first piece.

The first read on the athlete's instance, on September 14 with `strength-sets-since` at
2026-09-03, read the five activities from September 3 to 10: 105 sets, every one older
than seven days and so frozen without a question.

Not verified: whether an activity's first read the morning after already has the athlete's
Connect corrections. The four activities since the athlete started correcting came back with
every set named, a few of them by the watch alone, but they were read days later.

## 12. Decisions and open questions

Decided:

- Read-only toward Garmin; Connect is the editing surface. Every activity comes from
  Garmin; there is no manual activity and no import.
- Sets are read from `strength.sets_since` on; earlier activities keep their summary row.
  After that date a name a person picked is trusted, and a wrong one is made visible, not
  caught.
- A strength activity is an activity whose raw Garmin type is strength training and that
  returned at least one set; they are counted by day; no duration threshold.
- An activity's sets are read once, the morning after it, and frozen: at once when
  every set has a name a person gave or the activity is over a week old, otherwise when the
  athlete answers "yes, final" to a queued question, which reads them again first. Until
  they are read the activity says "sets not read yet". After the freeze no pull touches
  them; `strength reset` reads them again by hand. No re-fetch window, no carrying of
  answers by position, no set count anywhere.
- No inferred names, ever. A watch guess counts once the athlete answers "yes, final",
  runs `strength reset`, or keeps it in `strength name`; until then it is volume. A watch
  guess of a bodyweight exercise at more than 50 kg is not a name. Templates, if they come,
  are proposals with a human tap; the free-text path is a model proposal with a human tap.
- Two queue kinds, neither asked on the spot, both naming the activity by its day and start
  time. `sets_final`, one per activity with unnamed sets or guesses, subject the activity, "no, leave it" freezing as read, "Not now"
  meaning "I'll fix them in Connect". `set_names`, one per group at the freeze, a group
  being consecutive unnamed sets at one load, subject the activity, the freeze time and the
  positions; answers the exercises a person named recently, fixed when queued, plus a typed
  "Something else…" confirmed through a model proposal; "Leave it unnamed" the drop; a
  group whose sets are named, discarded or frozen again is stale. `strength name` is the
  only command that asks on the spot and the only place a group is split.
- Three commands: `strength name <date>`, `strength reset <date>` and
  `strength discard <date> [--undo]`. On a day with two strength activities, reset and
  discard ask which one, "none" by default. A discarded activity's sets leave the history
  and the naming answers; the activity still counts as training.
- Body weight is not stored; loads are shown as recorded.
- The strength history shows every exercise a person named in the last eight strength
  days, accessories included, each with its last three days, built on read; a day with
  two activities shows each on its own line with its start time and RPE, and "prescribed"
  sits on the day, with its rep range and "(light)" when the week was; what was prescribed
  and not done is listed after the entries. No tracked-lift rule, and no stored or computed
  number per exercise.
- The benchmark logbook is untouched: no modeled rows, no exercise column, and `e1rm`
  stays one lift, as `benchmark record` says.
- The words are main's (AGENTS.md): the plan is the periodization, a mesocycle is a few
  weeks of it, the week planner is the call that writes the sessions, the strength planner
  is the call that writes a strength session, a session is planned where an activity is
  recorded, a strength activity is one that returned sets, and a group is consecutive
  unnamed sets at one load. One word is this design's own: a brief is the week planner's
  description of a strength day, its purpose and no exercise, set, rep or load.
- The week planner's reply schema does not change; its TASK gains one instruction, to write
  a brief for a strength day and no exercises, sets, reps or loads. The week planner learns
  nothing new about strength and is never shown a kilogram.
- One strength planner call per proposal writes the whole strength session, accessories
  included, from the brief, the history, the shipped and the athlete's own strength science,
  the vocabulary with each name's class, and each day's equipment and constraints, and
  checks the kept sessions.
- The strength planner's exercises land in `prescribed_sets`, one row per group of sets
  with a rep range, keyed by the revision and copied by a restore and a swap. The
  description is rendered from them, brief above the seam and session below. An unknown
  name drops that exercise, not the session. A call that fails twice fails the proposal
  when a session was to be written; when sessions were only to be checked they are kept,
  the week planner's changes apply, and the preview and the morning briefing say the
  kilograms were not rechecked. A session's sets change only when the returned sets differ and only on new
  evidence, the `strength.history_changed_at` stamp being later than the session's last
  check in `strength_checks`, or when its brief or duration changed. The sets follow the
  lineage: a swapped session keeps them, and one `workout adapt` moves across dates is
  written anew until adapt can name where a session came from.
- The strength science ships beside the strength planner, read by that call only: double
  progression over a rep range at one load, the reps the athlete's dial and the load the
  strength planner's, with reps in reserve read as reps not done; every session of an
  exercise written at the next one's numbers; the plan decides when a week is light, the
  file how much comes off, the rows remember it, and the week after resumes from the day
  before the light one.
- The load is the weight moved in one rep; reps on one-sided exercises are per side; both
  athletes on this instance log the pair.

Open:

- The eight strength days behind the history are a first guess, like the eight days behind
  the naming answers. - Whether sessions written in kilograms get followed. On September 7
  and 10 the athlete did other exercises than the week planner's prose named, and on the
  10th did sets of 10 where 4 were written and kettlebell swings where "no swings" was.
  The strength planner is shown what was prescribed beside what was done, so the next
  session starts from what the athlete actually does. Whether a complete session in
  kilograms changes what the athlete does is what phase 2 finds out. - A question instead
  of `strength discard`. An athlete who only uses the chat bot has no way to keep an
  activity out of the strength history. Asking after every activity that departs from its
  prescription is not the answer: most departures are what the next prescription has to
  learn from, a push press that stopped at 3 of 5 reps or a belt squat done where a back
  squat was written, so the answer would nearly always be yes and soon be tapped through,
  and deciding what departs would bring back the thresholds revision 8 removed. Whether a
  question is needed, and what triggers it, waits until phase 2 shows how often activities
  depart from what was prescribed. - An unnamed circuit asks one question per set (§7). If
  an athlete who does not fix names in Connect lifts in circuits, asking once per load
  across the activity is the change, at the cost of a wrong name whenever two machines
  share a weight. - The naming questions arrive one walk after "yes, final", because a
  walk covers only what was waiting when it started. If that morning turns out to matter,
  the queue could let an answer add items to the running walk; that is a queue change. - A
  progress view. When someone wants to see an exercise's strength over months, revision
  7's training max is the starting point: the Epley estimate of the day's best set of 12
  reps or fewer, named as the floor it is, and never competing with a tested max. It needs
  a home of its own, because the benchmark logbook assumes one number per kind of test in
  about ten places. - The strength test. When an athlete has a strength goal, a
  mesocycle's boundary week has to choose between the FTP test and a strength test, and
  the shipped benchmark science's strength entry ("1RM test, or e1RM from a set near
  failure") needs a protocol the watch can read. Rev. 6 §8.2 in the branch history has a
  rule ("a mesocycle's test measures the nearest goal's sport") and a protocol (one set of
  five to eight reps, one short of failure, on the goal's lifts, read by the pull from a
  flagged `prescribed_sets` row); neither is built until that athlete exists. - Pushing
  the prescription to the watch (`upload_workout` + `schedule_workout`) would make the
  watch name the exercises itself, which removes §7 for an athlete who follows the plan
  exactly and adds friction for one who improvises. Garmin's strength-workout payload is
  the least documented corner of the API; verify the format before promising it.

## 13. Out of scope

Velocity-based training, per-set RPE, exercise technique notes, and any third-party
lifting app (Hevy, Strong) as a source.
