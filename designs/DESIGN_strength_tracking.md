# Strength tracking: reading the sets, naming the blocks, prescribing in kilograms

**Status:** Phase 1 implemented (§11.1) · Phase 2 draft (§8–§10) · **Date:** 2026-09-15 (rev. 9) · **Branch:** worktree-strength-tracking-design

Revision 9 settles a day with two strength workouts. On Thursday September 3 the athlete
lifted at the gym at 09:43 and did 16 kg kettlebell work at 20:45 (§6). Phase 1 already kept
the two apart in the queue, since every question's subject carries the activity, but four
things about such a day were wrong.

The questions gave the start time only on a day with two strength activities, and decided
that when the question was queued. Had the evening session reached Garmin after the
morning's sets were read, the morning's question would have said "Thu Sep 3 gym session"
for good. Every question now gives the start time (§7).

`strength reset` and `strength discard` acted on every activity of the date. Reading the
morning again after a fix in Connect dropped the names given to the evening, and discarding
a warm-up recorded under the strength profile discarded the session beside it. Both now ask
which one when a day has more than one (§7).

Discarding never took a workout out of training load: nothing outside strength tracking
reads the flag, so its duration, RPE and load reach the planner as before, and only its sets
leave the strength history and the naming answers. But the command said the session "no
longer counts", which reads as the work thrown away. It now says what it does (§5, §7).

In phase 2, the history put the sets of an exercise done in two workouts of a day on one
line, with room for one RPE. Goblet squats at 44 kg in the morning and at 16 kg in the
evening would have read as one session that faded, which the prescription answers by holding
the load. Each workout now gets its own line (§8). Asking, after a session that departs from
its prescription, whether it should count is recorded as an open question rather than built
(§12).

Revisions 1–8 are in the branch history.

## 1. Motivation

TrainMate plans strength sessions but has no idea what happens in them. A completed
strength activity is stored as duration, average heart rate and a session RPE — the same
shape as a ride, and about as informative as "went to the gym". The coach therefore
prescribes in relative terms, because relative terms are all it can defend:

> Gym, 65 min. Squat 4x4 and RDL 3x4 at 8RM load, 2–3 min rests, always 3+ reps in
> reserve. Press 3x5, row 3x5, core and mobility 10 min.

"At 8RM load" delegates the only number that matters to the athlete. Today the athlete
fills the gap by hand: a log of past sessions (exercise, reps, weight — nothing else),
pasted into a general-purpose LLM together with TrainMate's prescription, to get a
session with kilograms in it, which then gets tweaked anyway. That is the athlete doing
the coach's job because the coach cannot see the logbook.

The logbook already exists in a place TrainMate can reach. The Garmin watch records
strength sessions set by set, Garmin Connect exposes them through the same API TrainMate
already logs into, and the athlete already opens Garmin Connect after a session to fix
the numbers the watch got wrong. What is missing is the reading, a vocabulary to read it
into, and a coach that uses it.

## 2. Goals / Non-Goals

Goals:

- Store every recorded set (exercise, reps, load, duration, rest) of every strength
  session Garmin holds from a configured date on, so that `workout compare` can show
  what was lifted and the coach can see an exercise's recent sets.
- Resolve exercise names with **no guessing**: a name counts only if a person gave it, on
  the watch, in Garmin Connect or in TrainMate. The watch's own guesses are shown, and
  count once the athlete has looked at them (§6).
- Show the coach, with no per-athlete configuration, what the athlete recently lifted on
  every exercise.
- Let the coach prescribe strength sessions in absolute loads, with a progression it can
  justify from those sets, so the hand-kept log and the outside LLM retire.
- Work for strength training in general — barbells, dumbbells, kettlebells, cables,
  machines, bodyweight — and for more than one athlete.

Non-goals:

- Writing back to Garmin. Garmin Connect is where the athlete edits; TrainMate reads.
- Sessions from anywhere but Garmin. Every athlete on an instance wears the watch; a
  hand-typed session or an import from an old log would need a second writer of the
  activities table and a way to keep the pull's deletion reconcile off it, and nobody
  needs either.
- Pushing planned sessions to the watch as guided workouts. Possible later (§12), not now.
- Per-set RPE, velocity, or notes. The athlete's own log never had them; Garmin's session
  RPE is enough for load.
- Periodizing accessory work. Curls and lateral raises count toward volume and fatigue,
  and the prescription leaves them in the session's prose (§9).
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

The names are not as good as the numbers. Over the athlete's last 15 sessions
(2026-06-24 → 2026-09-03, ~390 working sets), 47% of sets came back `UNKNOWN`, and some
named ones were wrong (`SIT_UP` at 100 kg). The pattern behind the noise is structural,
not random: the watch recognises exercises from wrist motion, so **free-weight and
bodyweight movements are usually named and cable or machine movements essentially never
are**. A whole machine session — belt squat, inclined leg press, cable row, chest press,
shoulder press, pulldown — comes back as a list of unnamed blocks with correct reps and
loads.

After `sets_since`, a name a person picked is trusted, whether it was picked on the watch
or in Connect. That is a decision with a known cost: a wrong pick at a believable load —
"barbell row" tapped on a set that was a deadlift at 80 kg — gets past a glance at Connect
and lands in the barbell row's history. There is no better source of names than Garmin
plus the athlete, so the design accepts this and makes it visible instead, and `strength
name` fixes a wrong one after the fact. A name the watch guessed on its own is another
matter. Garmin reports it apart from a person's pick (§11.1), and it is not trusted until
the athlete says the session's sets are final (§6).

Two consequences shape everything below. Naming is a permanent step in the workflow, not
a teething problem. And loads are not comparable across exercises: 110 kg on a pulldown
stack and 80 kg on a deadlift bar are both "kg", and the smaller number is the harder
lift. Nothing in this design ranks lifts by load.

A gym visit is not one activity. Garmin has no warm-up activity type, so the athlete
records the warm-up under a copied profile — this athlete picked cardio, another might
pick strength — and TrainMate's sport normalisation folds Garmin's `fitness` and
`indoor_cardio` types into `strength_training`, so a Tuesday at the gym can be two or
three "strength activities". **A strength session is an activity whose raw Garmin type is
`strength_training` and that returned at least one set.** Sets are fetched for every
activity of that raw type, whatever the sport table folds it into afterwards, and an
activity that returns none is not a session and keeps its summary row. No duration
threshold: in the athlete's record since July every warm-up is typed cardio and every
lifting activity is typed strength, and real sessions of 15 and 18 minutes exist beside
a day split into two lifting activities of 26 and 18. A warm-up recorded under the
strength profile either returns no sets, because nothing on a treadmill looks like a rep,
or returns a few unknown sets at 0 kg, which the first question of §7 shows and "leave it
as it is" or `strength discard` dismisses. **Everything below that counts sessions counts
days**: a split session is one session.

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

The accessory pattern is where isolation work lives. It is left out of the strength history
(§8), and the prescription leaves it in the session's prose (§9); it exists so the sets
count toward volume and fatigue with a name on them.

Equipment is one of `barbell | dumbbell | kettlebell | cable | machine | bodyweight`: the
equipment the exercise usually needs. It is read in two places:

1. **The watch-guess check.** A watch guess of a bodyweight exercise at a heavy load is not
   that exercise (§6).
2. **Substitution.** The prescription picks exercises the day's equipment allows (§9). A
   travel week whose constraint says "hotel gym, dumbbells only" gets goblet squats and
   dumbbell RDLs for the squat and the hinge the planner asked for. This is what makes a
   session survive a different gym.

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
(§10), so the athlete logs and the coach prescribes the same way ("dumbbell bench 3×8 @ 60
(2×30)").

## 5. Data model

One new table:

```sql
CREATE TABLE exercise_sets (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    activity_id   TEXT NOT NULL,        -- completed_activities.activity_id
    seq           INTEGER NOT NULL,     -- position within the session, rest entries included
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
  the session (§6), so a session whose sets are not in yet can say so.
- `sets_final_at` — when the sets were frozen (§6); NULL while the "are the sets final?"
  question waits (§7). From then on no pull touches the rows, and the naming question's
  subject carries this time (§7).
- `discarded` — the athlete ran `strength discard` on it (§7). Set by a person, never by
  the pull. It keeps the sets out of the strength history and the naming answers; the
  activity still counts toward training load, which never reads it.

Neither drop answer of §7 writes a flag: the queue's closed row remembers it.

Phase 2 adds one table on the planned side, `prescribed_sets` (§9).

## 6. The pull path

`garmin/sync.py::_ingest_activities` already iterates the activities in a window and
upserts one summary row each, raw Garmin type included. The sets are a step of their
own, run at the end of every pull, of every refresh a read command makes through
`ensure_data`, and of the morning push before its walk (§11): for each activity whose raw
type is `strength_training` (§3), dated on or after `strength.sets_since`, dated **before
today** and with `sets_read_at` NULL, it fetches the exercise sets, stores them (delete by
`activity_id`, insert the list) and stamps `sets_read_at`. Before today, because the
athlete corrects the watch in Connect the evening of the session, and the morning after
is the first moment the numbers are usually right. Until then the session is on record as
its summary row, and `workout compare` and "Done lately" print "sets not read yet" under
the activity line (§7), so a session whose sets are still to come is never mistaken for
one that returned none.

**A session's sets are read once and then frozen.** What the read finds decides when:

- Every set named by a person, or no set at all (§3): the session is final on the spot,
  `sets_final_at` stamped, and nothing asks anything.
- Any set unnamed or only guessed by the watch, and the session within the last seven
  days: the rows are stored, so they count as volume and `workout compare` shows them,
  and one question is queued (§7): are the sets in Garmin final? "Yes" reads the sets
  again at that moment, so a name fixed in Connect an hour earlier comes in, and freezes
  them. The watch's guesses still standing in that read become the athlete's
  (`named_by = athlete`), because the athlete has just said the names in Garmin are right.
  Then the naming questions are queued for whatever is still unnamed. Until the answer,
  the session waits with its first read on record and `sets_final_at` NULL.
- Any set unnamed or guessed, and the session older than seven days: frozen at once, as
  read. The first pull with `sets_since` months back reads hundreds of sessions, and
  nobody is going to fix those in Connect. Their guesses stay guesses and their unnamed
  sets stay unnamed; `strength name` is how either gets a name (§7).

The athlete's Thursday, September 3, has one session of each kind. The morning session at
the gym was never checked in Connect: 19 sets, 14 named by the watch alone (barbell
deadlift, bench press, dumbbell flye, pull up, squat, triceps extension) and 5 it could not
name. The evening session was checked, and two guesses were left standing: "lateral raise",
12 reps at 16 kg, and "barbell deadlift", 12 reps at 16 kg, in a session where nothing
weighed more than 16 kg. Under revision 7 that 12 × 16 would have become the deadlift's
most recent session, and the coach would have read a deload that never happened. Under
this rule, on Friday morning, each session queues its question. The evening's reads "Thu
Sep 3 20:45 gym session: the watch guessed 2 exercises (barbell deadlift, lateral raise).
Are the sets in Garmin final?". The athlete opens Connect, changes the deadlift to a
Romanian deadlift and answers "yes, final": the re-read brings the fix in, and the lateral
raise becomes the athlete's. On this instance the two sessions were in fact read eleven
days late, on September 14, so both were frozen without a question, and their guesses count
for nothing until `strength name 2026-09-03`.

After the freeze no pull touches the session's sets again, whatever window it is given:
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
   the spot: an unnamed block changes what TrainMate knows and holds nothing up, the sets
   already count as volume, and that is the case DESIGN_athlete_queue.md §2 sends to the
   queue even when the athlete is watching.

   **The first question, kind `sets_final`, asks whether the sets in Garmin are final.**
   The set-reading step queues it the morning after a session whose first read found
   unnamed sets or watch guesses (§6), one per session:

   > Thu Sep 3 09:43 gym session: the watch guessed 6 exercises (barbell deadlift, bench
   > press, dumbbell flye, pull up, squat, triceps extension) and couldn't name 5 blocks
   > (sets 4, 12, 16, 18, 19). Are the sets in Garmin final?
   > [1] yes, final [2] leave it as it is — drop, never asked again [3] skip … [6] later …

   A session with guesses only leaves out the second half of the sentence, one with
   unnamed sets only the first. Its subject is the activity, so it is asked once per
   session, and `strength reset` freezes without asking. "Yes, final" reads the sets again
   from Garmin, freezes them, makes the guesses still standing the athlete's, and queues
   the naming questions for what is still unnamed; when Garmin cannot be reached the answer
   is not applied and the question stays waiting (§11). "Leave it as it is", the drop,
   freezes the sets as they were first read and asks no names: the guesses stay guesses,
   the unnamed blocks stay unnamed, all of them count as volume, and `strength name` can
   still name them. "Not now", the queue's own, is "no, I'll fix them in Connect, ask me
   again": in 1 hour, in 1 day or after the others. The check calls the question stale
   when the session was frozen by other means (`strength reset`), discarded, or is gone.
   The companion wording: "Thursday's 09:43 gym session has 6 exercises the watch only
   guessed and 5 groups of sets it couldn't name. Are the sets in Garmin final?"

   **The second question, kind `set_names`, asks what a block was.** It is queued at the
   freeze, one per block. **Blocks are consecutive unnamed sets at the same load**, reps
   ignored: within one exercise the reps drift (10, 10, 10, 9) while the load holds, and
   when the machine changes the load almost always changes with it. The question shows
   the whole block and offers the athlete's recent exercises:

   > Tue Sep 15 18:10 gym session, sets 5–8: 10, 10, 8, 8 reps @ 60 kg. What was it?
   > [1] leg press [2] belt squat [3] cable row [4] something else…
   > [5] leave it unnamed — drop, never asked again [6] skip … [9] later — after the others

   Choices 5 onward are the queue's own. The kind brings the five things §8 of the queue
   design asks a feature for:

   - **The subject** is the activity, the time its sets were frozen and the block's set
     positions, counted over active sets: `12345678901:2026-09-16T06:05:12Z:5-8`. The
     frozen rows never move, so the same positions are the same block for as long as the
     freeze stands, a block the athlete dropped is never asked about again, and
     `strength reset`, which freezes anew, makes every block of the session a new subject
     and a new question: the athlete has just edited the session and a new look is due.
   - **The wording**, written from the payload so it reads the same tomorrow: the date
     and start time, the positions, the reps and the load. The expert form is the line
     above; the companion reads "Tuesday's 18:10 gym session, sets 5–8: 10, 10, 8, 8 reps
     at 60 kg. What was it?". A block at 0 kg says so, which is how a warm-up recorded
     under the strength profile (§3) looks. The start time is always there, so a day with
     two lifting activities (§3) tells them apart even when the second reached Garmin
     after the first was read.
   - **The answers**, fixed when the item is queued: the exercises a person named in the
     athlete's last eight sessions (by day, discarded ones skipped), the ones done in the
     most sessions first, at most nine, then "Something else…", which takes typed text.
     Names only the watch guessed are left out, so a wrong guess never becomes a one-tap
     answer. Fixed because the queue says so (§3 there): a button tapped tomorrow must mean
     what it meant when it was shown. A warm-up ramp of three blocks still costs one tap
     per block, because its exercise is in the list; an exercise the athlete has never done
     before costs a typed answer per block of its first session and is in the list from
     the next one on.
   - **The drop button** is "Leave it unnamed". It writes nothing: the sets stay unnamed
     and count as volume only, the block is never asked about again, and `strength name`
     can still name it later.
   - **The check** calls the item stale when the block it describes no longer stands: any
     of its sets has a name, the session is discarded, the activity is gone, or the
     session was frozen again by `strength reset`. Nothing compares reps or loads,
     because the frozen rows do not change. An answer given through `strength name`, a
     `strength reset` and a `strength discard` all close a waiting question this way, and
     none of them touches the queue.

   An answer names every set of the block with `named_by = athlete` and confirms it:
   "Named sets 5–8: leg press." Undoing it is `strength name` on the same day, where
   "leave it unnamed" clears the name — the reversibility the queue design (§9) asks of
   anything a tap can write.

   **"Something else…" takes free text, and the text goes through a model** — the one
   model call in the naming path. The tap starts the queue's text prompt (queue design
   §6.3), the athlete types "pec deck" or "seated row machine", and the call, shown the
   vocabulary, returns up to three candidate names. They come back as a blocking chooser
   with "none of these". The athlete has just typed and is there, and the answer cannot be
   applied without their choice: the one case §2 of the queue design keeps on the spot. A
   candidate chosen names the block. "None of these", Enter, and a timeout in chat write
   nothing and leave the question waiting, because the kind says it did not apply the
   answer and the queue then leaves the item open (§11); "Yes, final" leans on the same
   rule when Garmin is unreachable. Alias matching would not do: what people type does not
   line up with Garmin's names, and no hand-kept alias list covers it. This is not the
   guess §4 forbids, because the athlete sees it and confirms it, the same exception §12
   makes for template proposals. The path is rare: after a few weeks the recent-exercises
   list covers nearly everything the athlete does, and "Something else…" is for a
   genuinely new exercise.

   A block that is two exercises at one load (cable row 50, then pulldown 50) gets one
   name from the queue. Rev. 5 followed every answer with "all 6 sets, or how many?", a
   second question on every tap to catch a rare case, and that is gone. The tail of such
   a block is fixed the way any wrong name is: with `strength name`, which splits, or in
   Connect followed by `strength reset`.

   Alternating exercises cost taps. The athlete on this instance alternates in four
   sessions out of five: belt squat, push press, belt squat, push press. If the watch had
   named nothing in such a session, every set would be a block of its own, because each
   set's neighbour is the other exercise, and eight sets would ask eight questions for two
   exercises. Asking once per load across the session would ask two, and would also give
   one name to two machines that happened to share a weight, which is the wrong name this
   design exists to prevent. So the rule stays. Its cost falls on an athlete who neither
   names on the watch nor fixes names in Connect; in the five sessions read here, 5 sets
   out of 105 were unnamed, all in the one session nobody checked (§12).

   Where the athlete meets the questions is the queue design's business, not this one's.
   In Telegram they arrive after the morning briefing, one at a time with their buttons,
   and nothing waits: the athlete can answer at breakfast or in the evening, and "Not now"
   puts one off. In the terminal `tm queue` lists them, `tm queue answer` goes through
   them, and `status` and `workout adapt` say how many are waiting. This feature adds no
   surface of its own. The week of §1 of that design, seen from this side: Tuesday's
   machine session leaves six unnamed blocks. Wednesday's 08:00 push refreshes the last
   days (§11), reads Tuesday's sets for the first time, finds the six blocks and queues
   the one question: are the sets final? The walk shows it after the briefing. If the
   athlete taps "Yes, final" at breakfast, the sets are read again and frozen there and
   then, and six naming questions are queued at 08:05. A walk covers only what was waiting
   when it started, so they arrive with Thursday's push, where the athlete names four,
   drops the chest-press warm-up and puts one off. If instead the athlete taps "Not now,
   in 1 day", spends Wednesday evening naming five of the six in Connect, and answers "Yes,
   final" to the reminder at 07:58 on Thursday, the re-read brings the five names in, one
   block is still unnamed, its question is queued at 07:58, and the 08:00 walk shows it.
   The cost of asking first is one morning: rev. 6 asked the names on Wednesday. The gain
   is that nothing done in Connect, before or after answering, can lose an answer or a
   question.
3. **Nothing.** An unnamed block is a legitimate state. It contributes to session volume
   and fatigue and to nothing else.

What is explicitly *not* a source: inference. TrainMate does not conclude "the plan said
squat 4×4 and here are four sets of four, so this is squat", nor "most of this session
matched the machine template so the rest is cable". Garmin's record is too unreliable and
the athlete too free-form (extra exercises, reordered machines) for a partial match to be
evidence, and a wrong name silently corrupts a lift's history. A watch guess is the watch's
own inference, which is why it waits for the athlete (§6). Grouping sets into blocks by
load is the one place the design infers anything, and the question shows every set so the
athlete sees what the answer will name. Template proposals — "this looks like your machine
session, same order?" with a one-tap confirm — remain a possible later convenience because
they still end in a human decision; they are out of this design (§12).

**Where the sets are shown.** `workout compare`, and "Done lately" in the companion, print
the session's sets under the activity line, one line per exercise, and a line listing the
unnamed sets ("leg press 1×12 @ 65, 1×10 @ 70, 2×12 @ 70", "sets 8–11 unnamed"). A name
only the watch guessed carries `(watch)`, and nothing else is marked, since a name a person
picked is as good as an answer (§11.1). So a wrong guess is seen the morning after:
"barbell deadlift 1×12 @ 16 (watch)" in an evening of 16 kg kettlebell work. A session
whose sets are not read yet (§6) prints "sets not read yet" in their place, in both
personas.

**Three commands do the surgery.** `strength name <date>` is the only command that asks
on the spot, and the queue's rule allows it that: the operator typed it, and the answer is
the whole of its work. It asks the naming question over any block of that day's session,
named or not (a named block is consecutive sets with the same name), with the same answers
as the queued question and one more step after the name is picked: "all 6 sets, or how
many?", and the rest are asked again. Keeping the name of a block the watch guessed
confirms it. It is the way to fix a name without going through Connect, the only place a
block is split, and the way to name the backlog: the first pull with `sets_since` months
back freezes hundreds of sessions and asks nothing about them (§6). A waiting question
about sets it names is stale from then on. `strength reset <date>` reads that day's
sessions' sets again from Garmin, replaces the rows, drops the answers on them, freezes
them anew, makes the guesses still standing the athlete's and queues the naming questions
for what is still unnamed, seven days old or not: it is how a name fixed in Connect after
the freeze comes in, and how a session read wrong gets read right. `strength discard
<date>` keeps a session's sets out of weight planning — the hotel gym's leg press, a
warm-up recorded under the strength profile, a session logged so badly it is not worth
fixing — and `--undo` reverses it. The sets stay stored. A discarded session is skipped by
the strength history (§8) and by the naming answers, and its waiting questions are stale;
all of those are computed on every read, so the flag is the command's one write. The
workout still counts as training: its duration, RPE and load reach the planner as before,
because nothing outside strength tracking reads the flag.

**On a day with two strength activities, `strength reset` and `strength discard` ask which
one**, offering each by its start time, then "all of them" and "none", the default. Take
September 3 (§6): the athlete fixes a name in Connect on the 09:43 session and resets the
day. Acting on every activity of the date would also read the 20:45 session again and drop
the names given to it, and discarding a warm-up recorded under the strength profile would
discard the session beside it. The date stays the argument, because it is what the athlete
remembers: Garmin's activity number is eleven digits that no TrainMate screen shows.
`strength name` does not ask: it goes through every session of the day, each under its
start time, and "keep it as it is" leaves a block alone.

## 8. The strength history

The coach cannot prescribe kilograms without last time's kilograms. The **strength
history** gives it those: a block of text built on read from `exercise_sets`, one entry per
exercise, shown to the prescription call (§9) and to nothing else. Nothing is stored for
it, and it holds no computed number.

**Which exercises.** Every exercise that a person named (§5) in the athlete's last eight
strength session days, discarded sessions skipped, accessories left out. Sessions are
counted by day (§3). Each entry then shows that exercise's last three sessions, however far
back they go from `sets_since` on. The eight days decide which exercises appear, not how
much of each is shown.

Revision 7 showed "tracked" exercises instead: the ones done in three of the last eight
sessions, or named in a planned session. On this athlete's record that is one exercise.
Four session days hold 23 exercises outside the accessory pattern. The goblet squat is on
three days; the Romanian deadlift and the one-arm row are on two; the other twenty are on
one, among them the belt squat, the lat pulldown and the push press the athlete does at the
gym every week. A coach shown one exercise prescribes the belt squat blind. The planned half
of the rule could not rescue it either, because the coach only names in a session what it
was shown. Eight days of this athlete's sessions give about thirty entries, some 1,500
tokens, which a call of its own can afford.

**What an entry shows.** The exercise with its pattern and equipment class from the
vocabulary. Then one line per session, newest first: the day, the sets as the athlete did
them with equal consecutive sets collapsed, the session RPE, and what was prescribed for
that exercise when the strength session planned that day had prescribed sets (§9). The sets
of one exercise are listed together even when the athlete alternated it with another, the
way `workout compare` lists them (§11.1). From the athlete's record, as it stands on
September 14:

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
  accessories on the same days: 10 sets (hamstring curls, chest fly, calf raise)
```

The row shows three sets where the athlete did four: the fourth is a watch guess nobody has
confirmed (§6). The morning of September 3 is missing altogether, deadlifts at 80 kg
included, because every name in it is a guess.

**A day with two workouts shows each on its own line.** Days still decide what is counted,
the eight days and each exercise's last three, but the sets of an exercise done in two
workouts of one day are not merged. Say that on Tuesday September 22 the athlete does the
prescribed goblet squats at the gym at 09:00, and goblet squats again at 16 kg in an evening
workout at 20:10:

```
  goblet squat (squat, dumbbell)
    Tue Sep 22, prescribed 3×10 @ 44:
      09:00: 3×10 @ 44 | RPE 6
      20:10: 3×12 @ 16 | RPE 2
```

Merged into "Tue Sep 22: 3×10 @ 44, 3×12 @ 16", the evening reads as the morning's session
fading, which the prescription call answers by holding the load (§9), and the line has room
for one of the two RPEs. A session the watch recorded as two activities (§3) shows as two
lines too, which is what happened. A day with one workout keeps its one line.

The loads are the weight field as recorded. On a pull-up that is the added load. Body
weight is not stored, and Garmin's weigh-ins are not read (§3). "pull up: 4×8, 2×6 @ 10" is
what the coach needs to prescribe the next pull-up session. A number that puts body weight
and added load on one scale belongs to the progress view this phase does not build.

Two things revision 7 put in the entries are left out:

- **A number per exercise.** Revision 7 put a training max beside each entry: the Epley
  estimate of the session's best set. The prescription is written from the sets, as
  revision 7 already said, and on this record the estimate is noise for half the entries.
  It gives a farmer's walk 74 kg from one length carrying 72 kg, and a suitcase squat 17 kg
  from a set of two. It belongs to a progress view (§12).
- **The title of a constraint.** Revision 7 marked a session that fell inside a
  constraint's dates with that constraint's title, so that a hotel gym's leg press would
  not be read as the home gym's. On this record every September session would carry "No
  20-minute sustained climb available near home", a cycling constraint that runs from
  August 26 to September 30. Constraints are prose about anything, and most say nothing
  about the gym. A session done on other equipment shows it in its loads, and one not
  worth reading is discarded (§7).

The history lives in `trainmate/strength/history.py`.

## 9. The prescription

**The planner does not change.** `workout generate` and `workout adapt` keep writing a
strength session the way they do today: its date, duration, RPE and load, and a description
in prose that says what the session is for and what it holds. Monday September 14, as the
planner really wrote it:

> Gym, 70 min. Squat 4x4, hip thrust or RDL 4x4 at 8RM load, 2–3 min rests, 24–30
> lower-body reps and always 3+ reps in reserve. Press 3x5, chin-up 3x4, core 5 min.

Revision 7 had the planner name each strength session's movement patterns in a new field of
its reply. The prose already carries them, and the call that reads it is a language model.
A new field would change the planner's reply schema and the prompt regions the tests pin
one by one, for something the call can read, so it is gone.

**One more call writes the kilograms.** It is labelled `strength_prescribe` and runs once
per proposal, in the service, after the planner's reply is parsed and before the proposal is
built: in `workout_generate` before the `GenerateProposal`, whose report of standing
sessions compares descriptions, and in `workout_adapt` after `structure_revision` and before
the revisions are paired. So every path that writes strength sessions gets it: the two
commands with their previews, and `replan` and the morning adapt, which apply without one.
The precedent is `_plan_reshape_verdict`, a small call of its own; this is the first one
that carries science.

**What it is given.**

- The strength science (§10).
- The exercise names of the vocabulary, grouped by pattern, accessories left out: 692
  names, about 3,700 tokens. The full vocabulary is twice that, mostly accessory, yoga and
  Pilates variants.
- The strength history (§8).
- For each date it writes: the equipment the athlete profile lists for that weekday and in
  general, and the prose of the constraints active that day, which is where "hotel gym,
  dumbbells only" would be written. Equipment is not a constraint type, so these two places
  are all there is.
- The sessions to write: every strength session the planner wrote in this proposal — new,
  revised or moved — with its title, duration, RPE and description.
- The sessions to check: every strength session in the same span that the planner kept,
  with its description and its prescribed sets. A session the athlete added by hand is
  shown to the call and never rewritten.

The athlete's own strength science is not given. It reaches every planner prompt today,
and what it says reaches the call through the planner's prose: "3+ reps in reserve", "2–3
min rests".

**What it returns.** For each session to write, its exercises in order: the name, the
number of sets, the lowest and highest reps, and the load in kilograms, or no load for a
bodyweight exercise with nothing added. Several entries may share an exercise, because a
warm-up ramp and the working sets are one exercise at several loads. With them come the
session's notes: its description with the exercises taken out and every other instruction
kept as written. For each session to check, it returns either "keep", or new exercises and
notes with a reason.

The description is built by code, not by the call: the title in brackets, the notes, then
one line per exercise rendered from the entries. So the kilograms the athlete reads and the
kilograms stored as data cannot disagree. Monday September 14 after the call, shown the
history of §8 and Monday's "full featured gym":

```
[Full-Body Strength (Heavy, Non-Failure)]
Gym, 70 min. 2–3 min rests, 24–30 lower-body reps and always 3+ reps in reserve. Core 5 min.

Belt squat 1×5 @ 120, 4×4 @ 145 kg
Glute bridge 4×4 @ 135 kg
Barbell push press 3×5 @ 75 kg
Chin up 3×4
```

The planner's "squat" became the belt squat, and "hip thrust or RDL" became the glute
bridge, the athlete's name for the hip-thrust machine, because those are what the history
holds for a Monday at the gym. The chin-up has no load: the history has no chin-up a person
named. Wednesday September 16 is at home, where the profile lists kettlebells up to 24 kg,
and the planner wrote "goblet or front squat 4x4 at RPE 6 with 3–4 reps in reserve, press
2x5, row 2x5, 2 min trunk". The call writes the goblet squat at 48 kg, the heaviest pair of
bells at home, and the one-arm row at 24 kg. It writes a kettlebell chest press with no
load, because no press done at home is in the history, and its notes say to pick a load
that leaves 3–4 reps in reserve.

**Checking a kept session.** A kept session's kilograms go stale when the athlete lifts.
Say Monday's push press stops at 5, 5 and 3 reps at 75 kg. Tuesday morning the pull reads
Monday's sets. Thursday September 17 is at the gym, and its prescription, written on
Sunday, holds "barbell push press 2×5 @ 77.5": the next step of a ladder Monday did not
climb. On Tuesday `workout adapt` runs, and the planner keeps Thursday. The call is shown
Thursday with its prescribed sets, and the history, which now says "Mon Sep 14: 2×5 @ 75,
1×3 @ 75 | RPE 7 | prescribed 3×5 @ 75". It answers with Thursday's exercises, the push
press back at 75 kg, and the reason "Monday's third set stopped at 3 of 5; repeat 75 before
adding load". The preview shows it like any other revision of a committed session.

Code decides whether an answer changes a kept session, from the sets and not from the
words. The call's exercises are compared with the stored prescribed sets, entry by entry.
When they match, the session is kept and nothing is appended, whatever the notes say. So
wording alone never touches a committed session.

**When the call runs.** When the planner wrote at least one strength session, or when the
athlete's sets were read after the prescription of one of the kept strength sessions was
written. Otherwise there is nothing new to write from, and a morning adapt in a week with
no lifting costs no call. An adapt whose planner changed nothing still becomes a proposal
when the call updates a kept session.

**Checking the output.** Every exercise name is looked up in the vocabulary. Sets and reps
must be whole numbers above zero, with the lowest reps not above the highest, and a load
must not be negative. An entry that fails is dropped with a line in the preview — "Mon Sep
21: 'Nordic curl' is not an exercise TrainMate knows, left out" — and the rest of the
session is written. A session whose every entry fails, and every session when the call
itself fails, keeps the planner's text and has no prescribed sets. That is exactly today's
output, with a warning.

**Where the prescribed sets live.** A new table:

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
`WorkoutChange.restore`, which rollback and `workout edit` use to bring back an earlier
version of a session, copies the sets of the version it restores. A void has none. The
cascade is there for the wipes, the only code that deletes planned sessions. Revision 7 also
stored the pattern; the vocabulary gives it from the exercise, so the column is gone.

**The preview shows the kilograms.** `workout generate`'s preview prints one line per
session today, without the description, so kilograms written before it would be accepted
unseen. Phase 2 prints the exercise lines under each strength session, in both personas.
`workout adapt`'s preview already shows how a description changed.

**Cost.** About 3,700 tokens of names, 1,500 of history, 1,000 of science, and 200 to 300
per session. A `workout generate` over a five-week block with ten strength sessions sends
about 9,000 tokens and gets about 1,500 back: a fifth of one `workout adapt` prompt. It uses
the same model as every other call, since TrainMate picks one model per process.

**What adherence becomes.** Revision 7 compared prescribed and done sets in code. It had
three deviations and two thresholds, a load more than 10% off and reps more than half the
range away, and it gave the planner a line per session so the planner would know to revise
a kept session whose numbers had gone stale. The call now checks the kept sessions itself,
from the history, which prints what was prescribed beside what was done. The planner learns
nothing new about strength: it keeps reading the session's duration, load and RPE, as it
does today. Substitution needs no rule either. On September 7 the planner asked for back
squat, Romanian deadlift, pull-ups or rows and overhead press. The athlete did the belt
squat, the glute bridge machine, the lat pulldown, the row and the push press. The history
shows what was done, and the call writes the next Monday from that.

## 10. The strength science

The call is told how to progress by a file that ships with the app,
`trainmate/strength/progression.md`, and only the call reads it. It does not go in
`trainmate/science/`: the science loader sends every file there, whole, to every coaching
prompt, and will until the science trim lands (TODO §PROMPT). A progression rule is of no
use to the endurance planner, whose adapt prompt is already about 50,000 tokens. When the
trim lands, the file can move there with a tag for this call. Phase 2 does not wait for it.

Its content is double progression, stated so the coach can defend a number. Each exercise
keeps a fixed rep range (say 8–10 for four sets). Reps go up until every set reaches the top
of the range with the reserve intact. Then the load goes up by the smallest step the
equipment allows (2.5 kg for the upper body, 5 kg for the lower, whatever a stack or a set
of kettlebells offers), and the reps drop to the bottom of the range. One dial moves per
session, never both. A session that missed the bottom of the range is repeated, not
progressed. A lighter week comes every fourth to sixth week, with the load down a tenth and
one set removed.

Two rules replace revision 7's "start from the sets, never from the training max". A new
rep range starts from the heaviest recent set in that range; when there is none, from a
recent set converted with the Epley formula (load × (1 + reps/30)), with a tenth taken off.
An exercise with no history gets no load, and the notes say what reserve to pick one with.
The load convention of §4 is in the same file.

## 11. Phasing

**Phase 1 — data, no prompt changes.** The vocabulary table with the full Garmin mapping,
`exercise_sets` and the three activity columns, the `sets_since` setting, the set-reading
step with its one-night wait and its freeze (§6), the `sets_final` and `set_names` queue
kinds with the model-backed "Something else…", `strength name`, `strength reset` and
`strength discard`, and sets shown in `workout compare` / "Done lately" with their name
source and the "sets not read yet" line — both of which rendered a strength session as
duration, load and RPE only (`cli/common.py::format_actual`,
`cli/render.py::simple_compare_lines`). At the end of it TrainMate knows what the athlete
lifts and the coach does not use it yet. Deliberately boring, so it can be checked against
reality before anything depends on it.

It amended two implemented designs. DESIGN_athlete_queue.md: its list of kinds (§8) gained
`sets_final` and `set_names`, and its §4 the rule that an answer whose kind did not apply it
leaves the item waiting. DESIGN_bot_simple_frontend.md: the morning push runs the
recent-data refresh a read command runs, whatever the adapt-first setting says and whether
or not a session is planned today, then the set-reading step, then its walk.

**Phase 2 — the coach.** Six pieces, in this order, each usable before the next:

1. The watch's guesses (§6, §7). A guess does not make a session final on its own; the
   first question lists the guesses and its drop is "leave it as it is"; "yes, final" and
   `strength reset` make the guesses still standing the athlete's; keeping a guess in
   `strength name` confirms it; and the naming answers come from names a person gave.
2. The strength history, `trainmate/strength/history.py` (§8).
3. `prescribed_sets` (schema 14), with `WorkoutChange.append` and `restore` carrying the
   sets (§9).
4. The strength science, `trainmate/strength/progression.md` (§10).
5. The prescription call, `trainmate/strength/prescription.py`: its prompt, the checks on
   its output, the comparison that keeps a kept session, and its place in
   `workout_generate` and `workout_adapt` (§9).
6. The exercise lines in the `workout generate` preview (§9).

Two implemented designs are amended when it lands. DESIGN_athlete_queue.md: the wording and
the drop label of `sets_final` in its list of kinds. DESIGN_workout_revisions.md: a revision
can carry prescribed sets, written with it and copied by a restore.

**The science trim** no longer comes between the phases (§10). It is still worth doing for
its own sake: about 15,000 of the adapt prompt's 50,000 tokens are science files sent whole
to every command.

### 11.1 Phase 1 as built

The two facts were checked on 2026-09-14 against nine of the athlete's sessions from
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
order the exercises first came, it is 12 lines, one per exercise; unnamed sets, when a
session has any, share one line listing their positions.

**`strength name` on a session still waiting for "are the sets final?" freezes it first.**
Otherwise a later "yes, final" would read the sets again and drop the names just given.

**`tm st` is still `status`.** `strength` shares the prefix, so `st` became an alias, the
way `s` already was.

The first read on the athlete's instance, on September 14 with `strength-sets-since` at
2026-09-03, read the five sessions from September 3 to 10: 105 sets, every session older
than seven days and so frozen without a question.

Not verified: whether a session's first read the morning after already has the athlete's
Connect corrections. The four sessions since the athlete started correcting came back with
every set named, a few of them by the watch alone, but they were read days later.

## 12. Decisions and open questions

Decided:

- Read-only toward Garmin; Connect is the editing surface. Every session comes from
  Garmin; there is no manual session and no import.
- Sets are read from `strength.sets_since` on; earlier sessions keep their summary row.
  After that date a name a person picked is trusted, and a wrong one is made visible, not
  caught.
- A strength session is an activity whose raw Garmin type is strength training and that
  returned at least one set; sessions are counted by day; no duration threshold.
- A session's sets are read once, the morning after the session, and frozen: at once when
  every set has a name a person gave or the session is over a week old, otherwise when the
  athlete answers "yes, final" to a queued question, which reads them again first. Until
  they are read the session says "sets not read yet". After the freeze no pull touches
  them; `strength reset` reads them again by hand. No re-fetch window, no carrying of
  answers by position, no set count anywhere.
- No inferred names, ever. A watch guess counts once the athlete answers "yes, final",
  runs `strength reset`, or keeps it in `strength name`; until then it is volume. A watch
  guess of a bodyweight exercise at more than 50 kg is not a name. Templates, if they come,
  are proposals with a human tap; the free-text path is a model proposal with a human tap.
- Two queue kinds, neither asked on the spot, both naming the session by its day and start
  time. `sets_final`, one per session with unnamed sets or guesses, subject the activity, "leave it as it is" freezing as read, "Not now"
  meaning "I'll fix them in Connect". `set_names`, one per block at the freeze, blocks
  being consecutive unnamed sets at one load, subject the activity, the freeze time and the
  positions; answers the exercises a person named recently, fixed when queued, plus a typed
  "Something else…" confirmed through a model proposal; "Leave it unnamed" the drop; a
  block whose sets are named, discarded or frozen again is stale. `strength name` is the
  only command that asks on the spot and the only place a block is split.
- Three commands: `strength name <date>`, `strength reset <date>` and
  `strength discard <date> [--undo]`. On a day with two strength activities, reset and
  discard ask which one, "none" by default. A discarded session's sets leave the history
  and the naming answers; the workout still counts as training.
- Body weight is not stored; loads are shown as recorded.
- The strength history shows every exercise a person named in the last eight strength
  days, each with its last three sessions, built on read; a day with two workouts shows
  each on its own line with its start time and RPE. No tracked-lift rule, and no stored or
  computed number per exercise.
- The benchmark logbook is untouched: no modeled rows, no exercise column, and `e1rm`
  stays one lift, as `benchmark record` says.
- The planner's reply does not change. One prescription call per proposal writes the new
  strength sessions and checks the kept ones, shown the history, the vocabulary without
  accessories, and each day's equipment and constraints. The planner learns nothing new
  about strength.
- The call's exercises land in `prescribed_sets`, one row per group of sets with a rep
  range, keyed by the revision and copied by a restore. The description is rendered from
  them. An unknown name drops that exercise, not the session. A kept session changes only
  when its sets do.
- The strength science ships beside the call, as double progression, read by that call
  only.
- The load is the weight moved in one rep; reps on one-sided exercises are per side; both
  athletes on this instance log the pair.

Open:

- The eight strength days behind the history are a first guess, like the eight sessions
  behind the naming answers.
- Whether prescriptions in kilograms get followed. On September 7 and 10 the athlete did
  other exercises than the planner's prose named, and on the 10th did sets of 10 where 4
  were written and kettlebell swings where "no swings" was. The call is shown what was
  prescribed beside what was done, so the next prescription starts from what the athlete
  actually does. Whether kilograms change what the athlete does is what phase 2 finds out.
- A question instead of `strength discard`. An athlete who only uses the chat bot has no
  way to keep a session out of weight planning. Asking after every session that departs
  from its prescription is not the answer: most departures are what the next prescription
  has to learn from, a push press that stopped at 3 of 5 reps or a belt squat done where a
  back squat was written, so the answer would nearly always be yes and soon be tapped
  through, and deciding what departs would bring back the thresholds revision 8 removed.
  Whether a question is needed, and what triggers it, waits until phase 2 shows how often
  sessions depart from what was prescribed.
- An unnamed circuit asks one question per set (§7). If an athlete who does not fix names
  in Connect lifts in circuits, asking once per load across the session is the change, at
  the cost of a wrong name whenever two machines share a weight.
- The naming questions arrive one walk after "yes, final", because a walk covers only
  what was waiting when it started. If that morning turns out to matter, the queue could
  let an answer add items to the running walk; that is a queue change.
- A progress view. When someone wants to see an exercise's strength over months, revision
  7's training max is the starting point: the Epley estimate of the session's best set of 12
  reps or fewer, named as the floor it is, and never competing with a tested max. It needs a
  home of its own, because the benchmark logbook assumes one number per kind of test in
  about ten places.
- The strength test. When an athlete has a strength goal, a block's boundary week has to
  choose between the FTP test and a strength test, and the shipped benchmark science's
  strength entry ("1RM test, or e1RM from a set near failure") needs a protocol the watch
  can read. Rev. 6 §8.2 in the branch history has a rule ("a block's test measures the
  nearest goal's sport") and a protocol (one set of five to eight reps, one short of
  failure, on the goal's lifts, read by the pull from a flagged `prescribed_sets` row);
  neither is built until that athlete exists.
- Pushing the prescription to the watch (`upload_workout` + `schedule_workout`) would
  make the watch name the exercises itself, which removes §7 for an athlete who follows
  the plan exactly and adds friction for one who improvises. Garmin's strength-workout
  payload is the least documented corner of the API; verify the format before promising it.

## 13. Out of scope

Velocity-based training, per-set RPE, exercise technique notes, and any third-party
lifting app (Hevy, Strong) as a source.
