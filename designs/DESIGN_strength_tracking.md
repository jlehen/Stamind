# Strength tracking: reading the sets, naming the blocks, prescribing in kilograms

**Status:** Draft · **Date:** 2026-09-14 (rev. 7) · **Branch:** worktree-strength-tracking-design

Revision 7 reads a session's sets once. The pull reads them the morning after the session,
and from the moment they are final nothing under the athlete's answers moves again: a
session the watch named in full is final at once, a session with unnamed sets is final
when the athlete says so, through a queued question that lets her fix names in Connect
first (§6, §7). `strength reset` reads a session again by hand. That retires rev. 6's
7-day re-fetch, the carrying of answers by set position and the set count in the naming
question's subject, which every review found a way to lose an answer or a question
through. The strength test is out until an athlete with a strength goal exists (§12);
body weight is not stored (§8); the strength call is shown the standing sessions'
prescriptions (§9); a load off by more than a tenth is a deviation (§10); the morning
push refreshes recent data before its walk, and an answer the queue could not apply
leaves its item waiting (§11).

Revisions 1–6 are in the branch history.

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
  what was lifted and the coach can see a lift's history.
- Resolve exercise names with **no guessing**: TrainMate records a name only if Garmin
  reported it or a human confirmed it.
- Derive, with no per-athlete configuration, which lifts are worth progressing and what
  the athlete's current strength on each of them is.
- Let the coach prescribe strength sessions in absolute loads, with a progression it can
  justify from the record, so the hand-kept log and the outside LLM retire.
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
- Periodizing accessory work. Curls and lateral raises count toward volume and fatigue and
  are otherwise left alone.
- A strength test on the calendar. Nobody on this instance has a strength goal, and the
  training max of §8 is the anchor until someone does (§12).

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

After `sets_since`, a Garmin name is trusted. That is a decision with a known cost: a
wrong name at a believable load — a deadlift at 80 kg the watch calls a barbell row —
looks right on the watch, gets past the athlete's glance at Connect, and lands in the
barbell row's history. There is no better source of names than Garmin plus the athlete,
so the design accepts this and makes it visible instead: every set shown to the athlete
says where its name came from (§7), and `strength name` fixes a wrong one after the fact.

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
or returns a few unknown sets at 0 kg, which the first question of §7 shows and "Leave it
unnamed" or `strength discard` dismisses. **Everything below that counts sessions counts
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

Garmin's exercise vocabulary is finite and public — the `exercise_category` and
`exercise_name` enumerations of the FIT file format, a few dozen categories and a few
hundred names. The table maps **all of it** at authoring time, so "a Garmin name the
table does not know" cannot happen with today's firmware. If a later firmware adds one,
the pull stores the Garmin name verbatim as the exercise with no pattern, the set counts
as volume, and the pull output says "new Garmin exercise name X, not in the vocabulary"
so it gets added by hand. No model call names an exercise on its own at runtime: that
would be a guess nobody sees. The one model call in the naming path proposes names the
athlete confirms (§7).

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

The accessory pattern is where isolation work lives. It is never tracked (§8) and never
prescribed by pattern (§9); it exists so the sets count toward volume and fatigue with a
name on them.

Equipment is one of `barbell | dumbbell | kettlebell | cable | machine | bodyweight`, and
it earns its column for three reasons:

1. **Detectability.** Cable and machine exercises are expected to arrive unnamed (§3);
   TrainMate can treat an unnamed block on a machine day as normal rather than as an error.
2. **How progress is measured.** Loaded exercises progress in kilograms. Bodyweight
   exercises progress in reps, then in added load; an estimated 1RM makes no sense for a
   push-up, "max reps at bodyweight" does (§8). The equipment class also says how to read
   the load column (§5): on a bodyweight exercise the recorded load is the *added* load.
3. **Substitution.** The coach prescribes by pattern and picks the exercise from what is
   available. A travel week whose constraint says "hotel gym, dumbbells only" gets goblet
   squats and dumbbell RDLs for the same squat and hinge slots, and adherence still says
   "done" (§10). This is what makes a plan survive a different gym.

The pattern answers *did you do it*; the exercise answers *how strong are you*. Those are
different questions at different granularities, and the design keeps them apart: a goblet
squat done instead of a back squat satisfies the squat pattern and must never feed the
back squat's numbers.

**The load convention** is the athlete's, not Garmin's, because the athlete types or
corrects the weight: **the load is the weight moved in one rep**. Two 30 kg dumbbells
pressed together is 60; one arm at a time is 30; a renegade row is 30, because only one
dumbbell leaves the floor at a time. Reps on a one-sided exercise are per side. Garmin's
entry screen and most lifters write the weight of one dumbbell instead, and nothing in
the data can tell the two apart, so this is a fact about the person: **both athletes on
this instance log the pair.** It is not a setting until an athlete who logs per hand
exists. The convention is stated once, here and in the shipped strength science file
(§9), so the athlete logs and the coach prescribes the same way ("dumbbell bench 3×8 @ 60
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
    load_kg       REAL,                 -- as recorded; on a bodyweight exercise, the added load
    duration_sec  REAL,
    named_by      TEXT,                 -- garmin | athlete | NULL while unnamed
    UNIQUE (activity_id, seq),
    FOREIGN KEY (activity_id) REFERENCES completed_activities(activity_id)
        ON DELETE CASCADE
);
```

Every row hangs off a Garmin activity, so the table needs no idea of where a row came
from. The foreign key is what makes the pull's deletion reconcile — which drops local
activities Garmin no longer returns, row by row, and cascades to nothing today — take the
sets with the activity; the logbook rows that carry an activity id (§8.1) get the same
clause, and the Garmin data wipe lists the table. The reconcile itself is untouched.

`load_kg` is stored as Garmin reports it, grams divided by a thousand, and carries no
meaning of its own. What a zero means is decided at read time from the vocabulary: on a
bodyweight exercise it is "nothing added", on a loaded one it is a zero. Nothing is
rewritten when an unnamed set gets its name.

`named_by` is the no-guessing rule made auditable: every named row can say whether the
name came from Garmin or from a person. Nothing else ever sets it.

Three columns join `completed_activities`, and the summary upsert, which names its
columns, leaves all three alone on every pull:

- `sets_read_at` — when the sets were last read from Garmin; NULL until the morning after
  the session (§6), so a session whose sets are not in yet can say so.
- `sets_final_at` — when the sets were frozen (§6); NULL while the "are the sets final?"
  question waits (§7). From then on no pull touches the rows, and the naming question's
  subject carries this time (§7).
- `discarded` — the athlete ran `strength discard` on it (§7). Set by a person, never by
  the pull.

"Leave it unnamed" writes no flag: the queue's closed row remembers it (§7).

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

- Every set named, or no set at all (§3): the session is final on the spot,
  `sets_final_at` stamped, and nothing asks anything.
- Any set unnamed, and the session within the last seven days: the rows are stored, so
  they count as volume and `workout compare` shows them, and one question is queued (§7):
  are the sets in Garmin final? "Yes" reads the sets again at that moment, so a name
  fixed in Connect an hour earlier comes in, freezes them, and queues the naming
  questions for whatever is still unnamed. Until then the session waits with its first
  read on record and `sets_final_at` NULL.
- Any set unnamed, and the session older than seven days: frozen at once, unnamed sets
  and all. The first pull with `sets_since` months back reads hundreds of sessions, and
  nobody is going to fix those in Connect; `strength name` is how they get named (§7).

After the freeze no pull touches the session's sets again, whatever window it is given:
the athlete's answers live in those rows, and a re-read that shifted one set would put
every answer after it one position off. A name fixed in Connect after the freeze reaches
TrainMate one way, `strength reset <date>` (§7), which reads the sets again, drops the
answers on them, freezes anew and asks about what is still unnamed. There is no re-fetch
window, no carrying of answers by position and no counting of sets: rev. 6 had all three,
and a rep corrected in Connect while a question waited, or a Garmin name the check below
rejected, could lose an answer or a question through them.

A Garmin name is accepted as given, with one check: **a name whose equipment class is
bodyweight, on a set with a heavy load, is not that exercise**. `SIT_UP` at 100 kg is
stored unnamed with the Garmin name kept in `garmin_name`, and joins the naming question.
The threshold is a constant in the vocabulary, not a setting, and it sits above the
20–40 kg a strong athlete adds to dips and pull-ups: 50 kg. It assumes the weight field
carries the added load. Phase 1 checks that on this athlete's push-up and pull-up rows
before the rule ships, because some Garmin flows fill the field with body weight; if they
do here, the check is dropped rather than made to subtract a body weight TrainMate does
not store (§8), and a sit-up at 100 kg is fixed after the fact like any other wrong name
(§7).

## 7. Naming

The rule, and the one sentence that explains the feature to an athlete:

> TrainMate reads your sets from Garmin. Anything it can't name, it asks you about.

Three sources of names, in order of preference, and nothing else:

1. **Garmin.** Whatever the watch detected or the athlete corrected in Connect. Since the
   athlete already opens Connect to fix reps and loads, fixing a name is the same gesture in
   the same screen; this is the primary path, before the freeze and, through `strength
   reset`, after it (§6).
2. **The athlete, through the queue.** Two questions, both queue kinds, neither asked on
   the spot: an unnamed block changes what TrainMate knows and holds nothing up, the sets
   already count as volume, and that is the case DESIGN_athlete_queue.md §2 sends to the
   queue even when the athlete is watching.

   **The first question, kind `sets_final`, asks whether the sets in Garmin are final.**
   The set-reading step queues it the morning after a session whose first read found
   unnamed sets (§6), one per session:

   > Tue Sep 15 gym session: 4 blocks the watch couldn't name (sets 5–8, 9–12, 13–16,
   > 17–20). Are the sets in Garmin final?
   > [1] yes, final [2] leave it unnamed — drop, never asked again [3] skip … [6] later …

   Its subject is the activity, so it is asked once per session, and `strength reset`
   freezes without asking. "Yes, final" reads the sets again from Garmin, freezes them and
   queues the naming questions for what is still unnamed; when Garmin cannot be reached
   the answer is not applied and the question stays waiting (§11). "Leave it unnamed",
   the drop, freezes the sets as they were first read and asks no names: the blocks count
   as volume, and `strength name` can still name them. "Not now", the queue's own, is
   "no, I'll fix them in Connect, ask me again": in 1 hour, in 1 day or after the others.
   The check calls the question stale when the session was frozen by other means
   (`strength reset`), discarded, or is gone. The companion wording: "Tuesday's gym
   session has 4 groups of sets the watch couldn't name. Are the sets in Garmin final?"

   **The second question, kind `set_names`, asks what a block was.** It is queued at the
   freeze, one per block. **Blocks are consecutive unnamed sets at the same load**, reps
   ignored: within one exercise the reps drift (10, 10, 10, 9) while the load holds, and
   when the machine changes the load almost always changes with it. The question shows
   the whole block and offers the athlete's recent exercises:

   > Tue Sep 15 gym session, sets 5–8: 10, 10, 8, 8 reps @ 60 kg. What was it?
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
   - **The wording**, written from the payload so it reads the same tomorrow: the date,
     the positions, the reps and the load. The expert form is the line above; the
     companion reads "Tuesday's gym session, sets 5–8: 10, 10, 8, 8 reps at 60 kg. What
     was it?". A block at 0 kg says so, which is how a warm-up recorded under the
     strength profile (§3) looks. A day with two lifting activities (§3) carries the
     start time in both questions, "Tue Sep 15 18:10 gym session", so they are told apart.
   - **The answers**, fixed when the item is queued: the exercises named in the athlete's
     last eight sessions (by day, discarded ones skipped), the ones done in the most
     sessions first, at most nine, then "Something else…", which takes typed text. Fixed
     because the queue says so (§3 there): a button tapped tomorrow must mean what it
     meant when it was shown. A warm-up ramp of three blocks still costs one tap per
     block, because its exercise is in the list; an exercise the athlete has never done
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
   with "none of these". She has just typed, so she is there, and the answer cannot be
   applied without her choice: the one case §2 of the queue design keeps on the spot. A
   candidate chosen names the block. "None of these", Enter, and a timeout in chat write
   nothing and leave the question waiting. That is not how the queue behaves today: it
   closes an item as answered whatever its kind's apply returned, and only an empty typed
   text, caught before apply runs, leaves an item waiting. So apply says whether it
   applied, and the queue closes the item only when it did (§11); "Yes, final" leans on
   the same change when Garmin is unreachable. Alias matching would not do:
   what people type does not line up with Garmin's few hundred names, and no hand-kept
   alias list covers it. This is not the guess §4 forbids, because the athlete sees it
   and confirms it, the same exception §12 makes for template proposals. The path is
   rare: after a few weeks the recent-exercises list covers nearly everything the athlete
   does, and "Something else…" is for a genuinely new exercise.

   A block that is two exercises at one load (cable row 50, then pulldown 50) gets one
   name from the queue. Rev. 5 followed every answer with "all 6 sets, or how many?", a
   second question on every tap to catch a rare case, and that is gone. The tail of such
   a block is fixed the way any wrong name is: with `strength name`, which splits, or in
   Connect followed by `strength reset`.

   Where she meets the questions is the queue design's business, not this one's. In
   Telegram they arrive after the morning briefing, one at a time with their buttons,
   and nothing waits: she can answer at breakfast or in the evening, and "Not now" puts
   one off. In the terminal `tm queue` lists them, `tm queue answer` goes through them,
   and `status` and `workout adapt` say how many are waiting. This feature adds no
   surface of its own. The week of §1 of that design, seen from this side: Tuesday's
   machine session leaves six unnamed blocks. Wednesday's 08:00 push refreshes the last
   days (§11), reads Tuesday's sets for the first time, finds the six blocks and queues
   the one question: are the sets final? The walk shows it after the briefing. If she
   taps "Yes, final" at breakfast, the sets are read again and frozen there and then, and
   six naming questions are queued at 08:05. A walk covers only what was waiting when it
   started, so they arrive with Thursday's push, where she names four, drops the
   chest-press warm-up and puts one off. If instead she taps "Not now, in 1 day", spends
   Wednesday evening naming five of the six in Connect, and answers "Yes, final" to the
   reminder at 07:58 on Thursday, the re-read brings the five names in, one block is
   still unnamed, its question is queued at 07:58, and the 08:00 walk shows it. The cost
   of asking first is one morning: rev. 6 asked the names on Wednesday. The gain is that
   nothing she does in Connect, before or after answering, can lose an answer or a
   question.
3. **Nothing.** An unnamed block is a legitimate state. It contributes to session volume
   and fatigue (§9) and to nothing else.

What is explicitly *not* a source: inference. TrainMate does not conclude "the plan said
squat 4×4 and here are four sets of four, so this is squat", nor "most of this session
matched the machine template so the rest is cable". Garmin's record is too unreliable and
the athlete too free-form (extra exercises, reordered machines) for a partial match to be
evidence, and a wrong name silently corrupts a lift's history. Grouping sets into blocks
by load is the one place the design infers anything, and the question shows every set so
the athlete sees what the answer will name. Template proposals — "this looks like your
machine session, same order?" with a one-tap confirm — remain a possible later
convenience because they still end in a human decision; they are out of the first
version (§11).

**Where the sets are shown.** `workout compare`, and "Done lately" in the companion, print
the session's sets under the activity line, consecutive equal sets collapsed
("leg press 4×10 @ 140, cable row 3×12 @ 50, sets 8–11 unnamed"), and every named
exercise carries a mark for where the name came from — `(g)` for Garmin, nothing for the
athlete — so a wrong Garmin name is seen the morning after: "barbell row 4×4 @ 80 (g)"
on a day the athlete deadlifted. A session whose sets are not read yet (§6) prints "sets
not read yet" in their place, in both personas.

**Three commands do the surgery.** `strength name <date>` is the only command that asks
on the spot, and the queue's rule allows it that: the operator typed it, and the answer is
the whole of its work. It asks the naming question over any block of that day's session,
named or not (a named block is consecutive sets with the same name), with the same answers
as the queued question and one more step after the name is picked: "all 6 sets, or how
many?", and the rest are asked again. It is the way to fix a name without going through
Connect, the only place a block is split, and the way to name the backlog: the first pull
with `sets_since` months back freezes hundreds of sessions with unnamed blocks and asks
nothing about them (§6), and until the older sessions are named through this command
nothing on a machine day is habitual (§8). A waiting question about sets it names is
stale from then on. `strength reset <date>` reads that day's sessions' sets again from
Garmin, replaces the rows, drops the answers on them, freezes them anew and queues the
naming questions for what is still unnamed, seven days old or not: it is how a name
fixed in Connect after the freeze comes in, and how a session read wrong gets read right.
`strength discard <date>` marks that day's session as one that should not count — the
hotel gym's leg press, a warm-up recorded under the strength profile, a session logged so
badly it is not worth fixing — and `--undo` reverses it. The sets stay stored. A discarded
session is skipped by the tracked-lift rule, by the state block and by the logbook, and
its waiting questions are stale; since all of those are computed on every read, the flag
is enough, and the command's one write is to recompute the session's modeled rows
(§8.1), which undo does again.

## 8. Tracked lifts, the training max, and the strength test

Nobody configures a list of lifts. The set of **tracked** exercises is derived from two
sources, unioned:

- **Prescribed:** any exercise the coach named in a planned strength session in the
  current macrocycle (read from the structured prescription, §9).
- **Habitual:** any exercise the athlete did in at least 3 of their last 8 strength
  sessions, sessions counted by day (§3), discarded ones skipped.

Frequency, never load (§3). For an athlete who follows the plan exactly, the tracked set
is the plan's lifts. For one who adds a push/pull block to every session, those lifts
join automatically and lateral raises never do. A lift that stops being done ages out.
Accessory-pattern exercises are never tracked.

For each tracked exercise TrainMate keeps a rolling **strength state**:

- the last three sessions' sets, consecutive equal sets collapsed (`5@40 3@60 4x4@80`),
  plus the session RPE;
- a **training max** from the session's **top set** — the set with the highest Epley
  estimate (`load × (1 + reps/30)`), computed over sets with reps ≤ 12 because the formula
  drifts past that;
- for bodyweight exercises, the best set's reps at bodyweight (or reps at added load)
  instead of a training max.

Top set by estimate, not by volume: a session's rows mix warm-ups, back-off sets and
light variants, and the set that moved the most total weight is usually a high-rep
back-off set that says least about the maximum. The athlete's named deadlifts range from
12×16 kg to 4×80 kg in one fortnight; 4×4 @ 80 gives 91 kg, 3×10 @ 60 gives 80, and 91
is the number. Volume is also wrong for double progression (§9): the session where the
load steps up and the reps drop back, 8×105 after 10×100, moves less total weight and
is the session where the athlete got stronger. The training max is stored per exercise,
never per pattern (§4). **This is the one rule**; the state block and the logbook (§8.1)
show the same number from the same set.

**Why "training max" and not "e1RM".** Working sets are stopped with reps in reserve, and
reps in reserve are not recorded (§2). Epley on 4×4 @ 80 kg with three left in the tank
says 91 kg when the true max is nearer 100. So every number derived from ordinary sessions
is a floor, and a consistent floor as long as the athlete keeps a similar reserve *and a
similar rep range*: the same strength gives 80 from 4×10 @ 60, 91 from 4×4 @ 80 and 63
from a deload's 3×8 @ 50. The coach is told exactly that, and prescribes from the sets,
not from the number: "4×10 @ 107.5, +2.5 from last Tuesday's 4×10 @ 105 with two in
reserve". The training max is a progress summary — the timeline, the block report — never
the input to a load.

Body weight is not stored, and Garmin's weigh-ins (§3) are not read: the assumption is
that it does not change enough to matter, so a bodyweight lift is tracked by reps, and a
set with added load by reps at that load, read straight from the weight field. A tracked
bodyweight lift whose progress needs the two on one scale is the day that changes, and
not before.

### 8.1 The logbook

The existing `benchmark_results` table already has an `e1rm` anchor kind (kg) whose
`benchmark record --e1rm` help calls it single-lift because the logbook has "no
per-exercise field". It gains an `exercise` column, a nullable `activity_id` with the
same delete cascade as the sets (§5), and a unique index on `(activity_id, exercise)`,
since the table has no key of its own today; `benchmark record` gains `--exercise`
(required with `--e1rm`). TrainMate writes a `source = modeled` row per named exercise
and session, which makes it the first code path to write a modeled row: today the enum
value exists and nothing produces one.

The row is the training max of §8, from the session's top set, with the set it came from
in two nullable columns, `reps` and `load_kg`, so the timeline can show "91 (4×80)" next
to "80 (3×10 @ 60)" and a reader sees the rep range change, not a loss of strength. A
session in which the lift has no set of 12 reps or fewer has no top set and writes no
row. That is the whole rule. Rev. 4 had two more, a rep window and a guard band, and both
are gone: the window made the state block and the timeline disagree about the same
session, and the guard compared each new value against the rows it had already accepted,
so a hotel-gym leg press accepted into an empty window kept the home gym's honest 145 out
of the timeline until the window emptied two months later. A wrong session is now removed
by a person with `strength discard` (§7), and a typo is fixed in Connect and read again
with `strength reset`.

The rows are derived, never edited: whenever a session's sets or names change — the
freeze, an answer to the naming question, `strength name`, `strength reset`, `strength
discard` and its undo — its modeled rows are recomputed from the frozen sets and upserted
on the unique index. Every named non-accessory exercise gets a row, tracked or not, so
that the tracked set decides what is shown and never what is stored: a lift's timeline
reaches back to its first session, not to the session in which it became habitual, and a
lift that is tracked next month has its history waiting.

**A tested max and a training max never compete.** A tested `e1rm`, recorded by hand with
`benchmark record --e1rm --exercise` after a set taken to one rep short of failure, and a
modeled floor guessed from sets that were not, measure different things, and a rule that
picks the newest of the two produces a sawtooth: tested 155 in August, modeled 140 in
September, 145 in October, and a reader concludes the athlete got weaker in August. So
for `e1rm` nothing ever asks for "the current value". Three readers would. The drift
check that triggers a replan already skips `e1rm`
(`coach/service/prompt.py::_threshold_reasons`,
`test_e1rm_never_invalidates_a_periodization`). The other two do not yet, and phase 2
makes them: the ANCHORS ON RECORD line (`coach/service/context.py::_anchor_history_text`),
which lists the newest row per anchor kind and would otherwise show whichever lift was
modeled last as "the athlete's 1RM", and the effective-threshold lookup behind the plan
snapshot (`db/benchmarks.py::latest_thresholds`), which also feeds the profile every
prompt sees, so the last assertion of that test, that `e1rm` still reaches it, flips.
For strength the line gives way to the strength state block (§9). Strength numbers feed
the prescription, never a replan.

## 9. Coach consumption

The strength call (below) gets a compact **strength state** block, one line per tracked
exercise, plus a one-line summary of untracked volume:

```
STRENGTH STATE (tracked lifts; loads are per exercise and not comparable across them;
                training max is a floor estimated from working sets not taken to failure)
  deadlift (barbell, hinge)        tmax 91 kg                 last: 5@40 3@60 4x4@80 RPE6 | 5x5@55 | 3x10@60
  belt squat (machine, squat)     tmax 140 kg  tested 155 Aug 12   last: 4x10@105 | 4x10@100 | 4x10@100
  bench press (barbell, push_h)    tmax 61 kg                 last: 3x5@52 | 5x5@50 | 5x5@48
  leg press (machine, squat)      tmax 253 kg                 last: 4x10@190 (Sep 2, hotel gym) | 4x10@140 | 4x10@140
  pull-up (bodyweight, pull_v)    best 8 reps                 last: 4x6 | 3x8 | 4x5
  untracked: ~12 sets/session of core, flyes, triceps; adds ~20 min
```

With that in front of it the call writes "belt squat 4×10 @ 110 (+5 from last week,
keep 3 in reserve)" instead of "at 8RM load", and can defend the number. The `tested`
column appears only when a hand-recorded test row exists for the lift (§8.1), which on
this instance is rare. A session that fell inside a constraint window carries the
constraint's title on its entry, as the leg press line shows: machine loads do not travel
between gyms, and a human coach reading "hotel gym" does not progress from it. The sets
are the call's to read; the number beside them is the athlete's to discard (§7).

**The prescription is a separate LLM call, one per proposal.** The main planner
(`workout generate` / `workout adapt`) decides that Tuesday is a 65-minute non-failure
strength session, which patterns it covers, and what fatigue it may cost the Thursday
intervals — the slot and its purpose. A second, small call receives the strength science,
the strength state, the vocabulary's exercise names, the equipment for each day, **every
strength slot in the proposal with its purpose**, and, read-only, the prescription already
standing on every strength session in the span that the planner kept, and returns the
exercise list with sets, reps and loads for each slot it fills. One call for all of them,
and the kept sessions shown, because progression runs *through* the week: on a Sunday
adapt Tuesday is committed and kept at 105 and Friday is new, and Friday's 107.5 exists
only if the call that writes it sees Tuesday's 105, which the state block, last recorded
session 100, cannot tell it. Equipment is not a constraint type — the constraints table is dates,
prose and a `rest` flag — so the call reads the two places it lives: the profile's general
and per-weekday equipment lists (`coach/engine/prompt.py::_format_athlete_profile`) and
the prose of the constraints active on each date, where "hotel gym, dumbbells only" would
be written. The precedent for the call is `planning.py::_plan_reshape_verdict`, "a small
call on purpose": this is the first second call that carries science. The reasons for
splitting here and only here:

- the strength call's inputs (set history, equipment) are of no use to the endurance
  decisions, and the strength science leaves the endurance prompt entirely;
- each prompt has one job, which is where accuracy comes from as prompts grow (§11);
- the endurance planner's own decisions are coupled — moving Thursday's intervals moves
  Saturday's long ride — and splitting *coupled* decisions across calls is where
  multi-call designs fail. It stays one call.

**The prescription has a structured form**, and it is decided now because two phase 2
features read it as data: the tracked-lift rule counts the exercises the coach named, and
adherence (§10) compares prescribed exercises, sets, reps and loads with the recorded
ones. Parsing them back out of prose is fragile, `workouts` has no JSON column, and the
precedent is typed rows, so the call's output lands in a `prescribed_sets` table keyed by
the workout revision: one row per group of sets — the exercise, its pattern, the number
of sets, the lowest and highest reps of the range, the load and the position in the
session — plus a rendered line in the workout's `description` for the athlete. A range,
because double progression prescribes one ("4×8–10") and adherence (§10) measures against
it; several rows per exercise, because a warm-up ramp and a top set with its back-off
work are one exercise at several loads. The
exercise names in the call's output are **validated against the vocabulary** before
anything is written. The call is shown the vocabulary, so a miss is rare; when one
happens — the coach wrote "Nordic curl" and the table has no such row — that exercise is
dropped from the output with a line in the preview, and the rest of the session is
written. One unknown name does not cost the week its kilograms.

The contract between the two is the planned workout row: the planner writes the slot
(title, duration, patterns, purpose, RPE budget) and the strength call fills the
`description` and the `prescribed_sets` rows. Three facts about that row fix where the
call runs:

- `workouts` is append-only, enforced by triggers (DESIGN_workout_revisions.md). A
  description cannot be patched after the fact, so the strength call runs on the propose
  side, inside `workout_generate` / `workout_adapt` before the preview, and the operator
  sees the kilograms before accepting. `description` is one of the two fields `append`
  always takes as given, so a new prescription is a real revision with the old one in
  History, and its `prescribed_sets` rows follow the revision.
- Inside the commitment window (DESIGN_plan_change_continuity.md §4) the planner answers
  keep / revise / replace / drop for every standing session and is shown the full
  description of each committed one. A kept strength session appends nothing, so its
  kilograms stand; only a revised or replaced strength session gets a fresh strength call.
  The planner never sees set data, so it needs a reason to revise a strength session
  whose numbers went stale: the adherence pass (§10) gives it one line per completed
  strength session in the window — "Tue deadlift: 4×4 @ 80, prescribed 90; belt squat
  done as prescribed" — the same way it already reads a missed ride. Wording alone is
  never a reason to touch a kept session.
- If the strength call fails, the row keeps the planner's pattern-level text and no
  `prescribed_sets` rows, which is exactly today's output.

**The strength science ships with the app**, as `trainmate/science/strength.md` beside
`benchmarks.md`, because a progression rule is general sports science, not one athlete's
preference; the athlete's own `science/` folder keeps what is personal (the
strength-integration file, the two-sessions-a-week rule). The science trim (§11) tags it
for the strength call only. Its content is double progression, stated so the coach can
defend a number: a fixed rep range per lift (say 8–10 for four sets); reps go up until
every set hits the top of the range with the reserve intact; then the load goes up by the
smallest step the equipment allows (2.5 kg upper, 5 kg lower, whatever the stack offers)
and reps drop to the bottom; one dial per session, never both; a session that missed the
bottom of the range is repeated, not progressed; a lighter week every fourth to sixth,
load down a tenth and a set removed; a new rep range restarts the ladder from a load read
off the sets in the state block, never off the training max. The load convention of §4 is
in the same file.

Untracked volume matters to the planner for one thing: fatigue. An athlete who habitually
adds 20 minutes of upper-body accessories to a leg day makes every strength session
heavier than planned; that is the shape of a coach learning ("adds ~20 min accessories
to strength sessions") and the existing learnings machinery is the right home for it —
the planner then budgets 85 minutes for a 65-minute prescription, or trims the
prescription, and stops being surprised. Learnings are authored only by the analysis path
(`data reflect`, bootstrap), so this one appears when reflect is shown the set history,
not from `workout generate`, which stays read-only toward learnings.

## 10. Adherence

"Did you do it" for a strength session means: every prescribed *pattern* was covered by
some exercise in that pattern, at roughly the prescribed sets × reps, at a load within
10% of the prescribed one when the exercise is the prescribed one. The prescribed side is
read from `prescribed_sets` (§9), the recorded side from `exercise_sets`. Extras are
neutral — information for §9, never a deviation. Three things are deviations, and each is
reported to the planner:

- a prescribed pattern with no exercise in it (skipped the hinge);
- a tracked lift done at a very different rep scheme from the prescription — the recorded
  reps per set are more than half the prescribed range away from it, 4×10 where 4×4 was
  asked — because that is a different stimulus, not a substitution;
- the prescribed exercise done at a load more than 10% off the prescribed one, "deadlift
  4×4 @ 80, prescribed 90", because that is what the planner needs to see to revise a
  kept session whose numbers went stale (§9).

All three numbers are first guesses (§12). Substitution within a pattern (goblet squat
for back squat, pulldown for pull-up) is adherence, with the note that the numbers landed
on a different exercise. The one-line strength summary the planner reads inside the
commitment window (§9) is this pass's output, rendered per session.

## 11. Phasing, and the science trim

**Phase 1 — data, no prompt changes.** The vocabulary table with the full Garmin mapping,
`exercise_sets` and the three activity columns, the `sets_since` setting, the set-reading
step with its one-night wait and its freeze (§6), the `sets_final` and `set_names` queue
kinds with the model-backed "Something else…", `strength name`, `strength reset` and
`strength discard`, and sets shown in `workout compare` / "Done lately" with their name
source and the "sets not read yet" line — both of which today render a strength session
as duration, load and RPE only (`cli/common.py::format_actual`,
`cli/render.py::simple_compare_lines`). At the end of it TrainMate knows what the athlete
lifts and the coach does not use it yet. Deliberately boring, so it can be checked against
reality — is the morning after enough for the numbers to be right, does the "final?"
question get answered or put off, does the load-only block split ask sensible questions —
before anything depends on it.

Two implemented designs are amended when this lands. DESIGN_athlete_queue.md: its list
of kinds (§8) gains `sets_final` and `set_names`, and its §4 gains the rule that an
answer whose kind did not apply it leaves the item waiting — a change in
`athlete_queue.act`, which today closes the item whatever apply returned; the empty typed
text, caught before apply, is the one case that already behaves so. DESIGN_bot_simple_frontend.md:
the morning push runs the recent-data refresh a read command runs, whatever the
adapt-first setting says and whether or not a session is planned today, then the
set-reading step, then its walk. Today the push pulls Garmin only with adapt-first on, or
for today's date when a workout is planned, so on a rest-day morning Tuesday's session
would not be on record and nothing would be asked; the companion runs no other command,
so the push is the whole delivery path.

Two facts to verify against the account in this phase, because a rule depends on each:
what the weight field carries on a bodyweight exercise, which decides whether the 50 kg
check ships (§6), and whether the sets endpoint says if a name was watch-detected or
user-edited — if it does, `named_by` records the difference and `workout compare` can
mark a watch guess apart from an athlete's correction.

**Phase 2 — the coach.** Tracked-lift derivation, strength state, the `benchmark_results`
extension with the modeled rows recomputed on every change, the two `e1rm` skips (§8.1),
`prescribed_sets`, the one-call prescription shown the kept sessions, strength adherence
with its one-line summary to the planner, and the shipped strength science file. Built
as a second call from the start: bolting a lift-history block onto the existing prompt
and splitting later is a detour through the direction the prompt is trying to leave.

**Between them, the science trim** (TODO §PROMPT). The adapt prompt is ~50k tokens; ~15k
is science, split evenly between shipped and athlete files and sent whole to every
command (`coach/formatting.py::_load_science_guidelines` reads every `*.md` in both
directories, in name order, with no tagging). Tagging files by command and sport and
including only matches is independent of strength and should land before phase 2, so that
when the strength call appears the endurance prompt has already shed the strength science
and the two-call shape is visible rather than buried. The shipped strength file (§9) is
the first file the tags exist for; the athlete's strength science is the kind of file
`science.samples/cycling_and_strength/strength_integration.md` is, and the samples come as
two sets there, so the tags have a worked example in each.

## 12. Decisions and open questions

Decided:

- Read-only toward Garmin; Connect is the editing surface. Every session comes from
  Garmin; there is no manual session and no import.
- Sets are read from `strength.sets_since` on; earlier sessions keep their summary row.
  After that date a Garmin name is trusted, and a wrong one is made visible, not caught.
- A strength session is an activity whose raw Garmin type is strength training and that
  returned at least one set; sessions are counted by day; no duration threshold.
- A session's sets are read once, the morning after the session, and frozen: at once
  when every set is named or the session is over a week old, otherwise when the athlete
  answers "yes, final" to a queued question, which reads them again first. Until they are
  read the session says "sets not read yet". After the freeze no pull touches them;
  `strength reset` reads them again by hand. No re-fetch window, no carrying of answers
  by position, no set count anywhere.
- No inferred names, ever. Templates, if they come, are proposals with a human tap; the
  free-text path is a model proposal with a human tap. A Garmin name on a bodyweight
  exercise at a heavy load is not a name, if the weight field turns out to carry the
  added load; otherwise the check is dropped.
- Two queue kinds, neither asked on the spot. `sets_final`, one per session with unnamed
  sets, subject the activity, "Leave it unnamed" freezing as read, "Not now" meaning
  "I'll fix them in Connect". `set_names`, one per block at the freeze, blocks split by
  load, subject the activity, the freeze time and the positions; answers the recent
  exercises, fixed when queued, plus a typed "Something else…" confirmed through a model
  proposal; "Leave it unnamed" the drop; a block whose sets are named, discarded or frozen
  again is stale. `strength name` is the only command that asks on the spot and the only
  place a block is split.
- Three commands: `strength name <date>`, `strength reset <date>` and
  `strength discard <date> [--undo]`.
- Body weight is not stored; bodyweight lifts are tracked by reps.
- Tracked lifts by frequency and prescription, never by load, never by config.
- One training max rule: the set with the highest Epley estimate over sets of 12 reps or
  fewer, per exercise, named as the floor it is, shown in the state block and written to
  the logbook with its reps and load for every named non-accessory exercise of every
  session, recomputed whenever the session's sets or names change. No rep window, no
  guard; a wrong session is discarded by a person.
- A tested max and a training max never compete for a current value; the strength state
  shows both. The ANCHORS ON RECORD line and the plan snapshot skip `e1rm` (phase 2).
- No strength test on the calendar until an athlete with a strength goal exists.
- Strength prescription is one LLM call per proposal, shown the vocabulary and the kept
  sessions' prescriptions, with structured output in `prescribed_sets`, one row per group
  of sets with a rep range; an unknown name drops that exercise, not the call; the
  endurance planner stays one call and reads a one-line strength adherence summary.
- Three adherence deviations: a pattern skipped, a rep scheme far off, a load more than
  10% off on the prescribed exercise.
- The load is the weight moved in one rep; reps on one-sided exercises are per side; both
  athletes on this instance log the pair.
- Progression science is shipped, as double progression.

Open:

- The habitual threshold (3 of the last 8 sessions) is a first guess; revisit once the
  table has two months of rows. It interacts with the split: on a push/pull/legs
  rotation each lift lands in about 2.7 of 8 sessions and flickers in and out of the
  tracked set, so the fix, if one is needed, is a longer window.
- The adherence bands (§10) — load within 10%, reps more than half the prescribed range
  away — and the bodyweight ceiling (§6, 50 kg added) are first guesses too.
- The naming questions arrive one walk after "yes, final", because a walk covers only
  what was waiting when it started. If that morning turns out to matter, the queue could
  let an answer add items to the running walk; that is a queue change, and phase 1 will
  show whether it is wanted.
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
