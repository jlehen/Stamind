# Strength tracking: reading the sets, naming the blocks, prescribing in kilograms

**Status:** Draft · **Date:** 2026-09-10 (rev. 4) · **Branch:** worktree-strength-tracking-design

Revision 4 folds in the review of 2026-09-10. Every session comes from Garmin, so the
manual quick-log, the Google Doc import and the `source` column are gone (§5). Sets are
read from a configured start date, because before it the athlete did not correct what
the watch guessed (§3). The naming question is a blocking chooser, so it works in the
terminal and in both bot personae, and it can be declined (§7). The top set is the set
with the highest Epley estimate; a modeled row is written only from a narrow rep window,
only when it stays within a band of the recent rows, and it replaces any earlier row
for the same session (§8). The block's test follows the nearest goal's sport (§8.2). The
prescription is one call per proposal, returns structured sets that are stored beside the
workout revision, and reads a shipped strength science file (§9). Revisions 1–3 are in
the branch history.

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

Two consequences shape everything below. Naming is a permanent step in the workflow, not
a teething problem. And loads are not comparable across exercises: 110 kg on a pulldown
stack and 80 kg on a deadlift bar are both "kg", and the smaller number is the harder
lift. Nothing in this design ranks lifts by load.

A gym visit is not one activity. The athlete records the warm-up and the post-session
mobility as separate watch activities, and TrainMate's sport normalisation folds Garmin's
`fitness` and `indoor_cardio` types into `strength_training`, so a Tuesday at the gym can
be two or three "strength activities". **The session is the highest-load strength
activity of the day**, the same one the adherence matcher already pairs with the planned
session; the others keep their summary rows and get no sets fetched. Everything below
that counts sessions counts those.

The library also offers `set_activity_exercise_sets` (rewrite names on an activity),
`upload_workout` and `schedule_workout`, and `get_weigh_ins` (the athlete's scale, or a
weight typed into Connect). The first three are deliberately unused (§2); the last is
noted in §8 for the day a bodyweight lift needs a body weight.

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
so it gets added by hand. No model call names an exercise at runtime: that would be a
guess nobody sees.

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
dumbbell leaves the floor at a time. Reps on a one-sided exercise are per side. The
convention is stated once, here and in the shipped strength science file (§9), so the
athlete logs and the coach prescribes the same way ("dumbbell bench 3×8 @ 60 (2×30)").

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
    UNIQUE (activity_id, seq)
);
```

Every row hangs off a Garmin activity, so the table needs no idea of where a row came
from, and the pull's deletion reconcile — which drops local activities Garmin no longer
returns — cascades to the sets and is otherwise untouched.

`load_kg` is stored as Garmin reports it, grams divided by a thousand, and carries no
meaning of its own. What a zero means is decided at read time from the vocabulary: on a
bodyweight exercise it is "nothing added", on a loaded one it is a zero. Nothing is
rewritten when an unnamed set gets its name.

`named_by` is the no-guessing rule made auditable: every named row can say whether the
name came from Garmin or from a person. Nothing else ever sets it. A session the athlete
has declined to name (§7) is recorded on the activity — one flag, `sets_declined`, on
`completed_activities` — so the question is never asked about it again.

## 6. The pull path

`garmin/sync.py::_ingest_activities` already iterates the activities in a window and
upserts one summary row each. For each day's strength session (§3: the highest-load
strength activity of the day, dated on or after `strength.sets_since`) it additionally
fetches exercise sets and replaces that activity's rows wholesale (delete by
`activity_id`, insert the fresh list). Replace-not-merge because the athlete edits in
Connect and the corrected version must win. Because the fetch lives in ingest, anything
that re-ingests an activity refreshes its sets: `data pull -d 30d` re-fetches every set in
that range, and no `--force` is needed.

That edit happens *after* the session, often after TrainMate's first pull of it. The code
has a related shape: `garmin_mutable_days` (default 3) is the trailing zone that read
commands re-pull in full through `ensure_data` because Garmin finalises late. Sets need a
longer reach and a lighter touch, so they get their own step rather than a wider zone: on
every pull, and on every `ensure_data` refresh, the strength sessions of the last **7
days** have their sets re-fetched and replaced, whatever window was asked for — one API
call per session, two or three per pull, and nothing else about those days is re-pulled.
Seven rather than three because a Connect edit is a human remembering, not a server
settling. Older than 7 days is considered settled unless a selector reaches back to it.

Athlete-confirmed names (§7) live in the same rows, so a re-fetch must not erase them.
**A name a person gave is never overwritten by a re-fetch**, Garmin's later opinion
included. The replace step carries `exercise`/`named_by = athlete` forward by `seq` when
the re-fetched session has the same number of sets as before. When the count changed —
the athlete deleted a phantom set in Connect, or added one — positions have shifted and
the names would land one set off, so nothing is carried forward, the session is marked
unnamed again, and the question is asked again. Correcting a load or a rep count leaves
the count unchanged, so names survive the common edit.

A Garmin name is accepted as given, with one check: **a name whose equipment class is
bodyweight, on a set with a heavy load, is not that exercise**. `SIT_UP` at 100 kg is
stored unnamed with the Garmin name kept in `garmin_name`, and joins the naming question.
The threshold is "any load at all above the bodyweight class's added-load ceiling", a
constant in the vocabulary, not a setting.

## 7. Naming

The rule, and the one sentence that explains the feature to an athlete:

> TrainMate reads your sets from Garmin. Anything it can't name, it asks you about.

Three sources of names, in order of preference, and nothing else:

1. **Garmin.** Whatever the watch detected or the athlete corrected in Connect. Since the
   athlete already opens Connect to fix reps and loads, fixing a name is the same gesture in
   the same screen; this is the primary path.
2. **The athlete, via Telegram or CLI.** After a pull leaves unnamed sets in the last 7
   days, the command asks. **Blocks are consecutive unnamed sets at the same load**, reps
   ignored: within one exercise the reps drift (10, 10, 10, 9) while the load holds, and
   when the machine changes the load almost always changes with it. The question shows the
   whole block, one line per set, and offers the athlete's recent exercises:

   > Sep 1, sets 1–4: 10, 10, 10, 9 reps @ 100 kg. What was it?
   > [1] lat pulldown [2] leg press [3] cable row [4] other… [5] leave it unnamed

   The answer is written with `named_by = athlete`. "Other…" takes free text, which also
   serves the rare block that is two exercises at one load: "first 3 leg press" names
   three sets and the rest are asked again. "Leave it unnamed" sets `sets_declined` on
   the activity and the question is never asked about that session again; the sets stay
   unnamed and count as volume only, and `strength name` still works on them later. No
   answer — Enter in the terminal, the bot's prompt timeout — means "skip for now", and
   the question returns with the next pull.

   The mechanism is the blocking chooser (`runtime.prompt.choose`), the one that asks
   "which one did you mean?" today. In a terminal it prints a numbered list and waits; in
   the bot it sends inline buttons and waits up to `telegram.prompt_timeout`. So the
   question works in the expert CLI, in the expert bot and in the companion, from the
   same code. The non-blocking button row (`TM-BUTTONS`) is the wrong tool here: it prints
   as a raw sentinel in a terminal, and the bot keeps one row per chat, which the morning
   push already uses. Because the chooser blocks, the naming step runs **last** in the
   commands that carry it — `data pull`, `bot morning` after its pull, `workout compare`
   when "Done lately" runs it — after everything else has printed. One block per question,
   the next asked when the last is answered.
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

## 8. Tracked lifts, the training max, and the strength test

Nobody configures a list of lifts. The set of **tracked** exercises is derived from two
sources, unioned:

- **Prescribed:** any exercise the coach named in a planned strength session in the
  current macrocycle (read from the structured prescription, §9).
- **Habitual:** any exercise the athlete did in at least 3 of their last 8 strength
  sessions.

Frequency, never load (§3). For an athlete who follows the plan exactly, the tracked set
is the plan's lifts. For one who adds a push/pull block to every session, those lifts
join automatically and lateral raises never do. A lift that stops being done ages out.
Accessory-pattern exercises are never tracked.

For each tracked exercise TrainMate keeps a rolling **strength state**:

- the last three sessions' working sets (`sets × reps @ kg`, plus session RPE);
- a **training max** from the session's **top set** — the set with the highest Epley
  estimate (`load × (1 + reps/30)`), computed only over sets with reps ≤ 12 because the
  formula drifts past that;
- for bodyweight exercises, the best set's reps at bodyweight (or reps at added load)
  instead of a training max.

Top set by estimate, not by volume: a session's rows mix warm-ups, back-off sets and
light variants, and the set that moved the most total weight is usually a high-rep
back-off set that says least about the maximum. The athlete's named deadlifts range from
12×16 kg to 4×80 kg in one fortnight; 4×4 @ 80 gives 91 kg, 3×10 @ 60 gives 80, and 91
is the number. The training max is stored per exercise, never per pattern (§4).

**Why "training max" and not "e1RM".** Working sets are stopped with reps in reserve, and
reps in reserve are not recorded (§2). Epley on 4×4 @ 80 kg with three left in the tank
says 91 kg when the true max is nearer 100. So every number derived from ordinary sessions
is a floor, and a consistent floor as long as the athlete keeps a similar reserve *and a
similar rep range*: the same strength gives 80 from 4×10 @ 60, 91 from 4×4 @ 80 and 63
from a deload's 3×8 @ 50. The coach is told exactly that, and prescribes from the sets,
not from the number: "4×10 @ 107.5, +2.5 from last Tuesday's 4×10 @ 105 with two in
reserve". The training max is a progress summary — the timeline, the block report — never
the input to a load.

Body weight is not in the profile today, so "reps at bodyweight" is a rep count and
nothing more. When a bodyweight lift is tracked and someone wants added or assisted load
on the same scale, Garmin's weigh-ins (§3) are one fetch away and a profile weight is the
fallback; the effective load is then body weight plus added load, computed at read time.
Not built until that day.

### 8.1 The logbook

The existing `benchmark_results` table already has an `e1rm` anchor kind (kg) that
`benchmark record --e1rm` warns is single-lift because the logbook has "no per-exercise
field". It gains an `exercise` column and `benchmark record` gains `--exercise`
(required with `--e1rm`). The strength state writes a `source = modeled` row per tracked
exercise, which makes it the first code path to write a modeled row: today the enum value
exists and nothing produces one. Three rules keep that series honest:

- **Only from a narrow rep window.** A modeled row comes from a top set of 3–6 reps and
  from nothing else. Epley's error moves with reps, so the same strength in a 10-rep block
  and a 4-rep block gives two different "maxes", and a series that mixes them is the
  sawtooth rev. 3 removed, rebuilt inside the modeled rows. A block that never visits the
  window writes no rows; a timeline with gaps beats one that lies.
- **Within a band of the recent rows.** A value more than `strength.modeled_guard_pct`
  (default 15) away, in either direction, from the modeled rows of the last
  `strength.modeled_guard_weeks` (default 8) is not written, and the pull output says so:
  "leg press modeled max 253 kg is 35% above the recent 187 kg, not recorded". If there
  are no rows in the window, the value is accepted. The guard catches a mistyped 400 for
  40, and it catches the hotel gym's leg press, a different machine whose 190 kg is not
  strength (§9). It applies to modeled rows only; a tested value is what it is, even
  when it is a disappointment. The cost is that a genuine fast jump, strength returning
  after a layoff, is held back until the values settle — and since no load is prescribed
  from the number, the athlete sees no difference.
- **One row per session and exercise.** The 7-day re-fetch (§6) re-reads a session after
  the athlete corrects it in Connect, and the corrected top set gives a new value. The
  write is an upsert keyed on `(activity, exercise)`: the row for that session is
  replaced, never joined by a second one dated the same day. The same rule covers the
  self-read test row (§8.2). `benchmark_results` gains a nullable `activity_id` for it.

**A tested max and a training max never compete.** They measure different things — a
set taken to one rep short of failure, and a floor guessed from sets that were not — and
a rule that picks the newest of the two produces a sawtooth: tested 155 in August,
modeled 140 in September, 145 in October, and a reader concludes the athlete got weaker
in August. So for `e1rm` nothing ever asks for "the current value". Two readers today
would: the drift check that triggers a replan, which already skips `e1rm`
(`prompt.py::_threshold_reasons`, `test_e1rm_never_invalidates_a_periodization`), and the
ANCHORS ON RECORD line, which lists the newest row per anchor kind and would otherwise
show whichever lift was modeled last as "the athlete's 1RM". That line
(`context.py::_anchor_history_text`) and the effective-threshold lookup behind the plan
snapshot (`db/benchmarks.py::latest_thresholds`) both skip `e1rm`; for strength the line
gives way to the strength state block, which shows both numbers side by side with the
test's date (§9). Strength numbers feed the prescription, never a replan.

### 8.2 The strength test

The benchmark machinery (DESIGN_benchmark_workouts.md §4.1) asks for one test in each
block's final week, preceded by an opener day so the athlete is fresh, and its post-check
counts a benchmark of any sport. Two tests in one week therefore collide twice: two
openers in a seven-day week that also holds the block's last hard sessions, and — since
the same-day collision rule is per sport — nothing stops a near-failure leg session
landing two days before the FTP test and lowering the number that scales the whole next
block.

The rule that resolves it is general, and one sentence long:

> **A block's test measures what the block is for.** One test per boundary week, of the
> kind that belongs to the sport of the **nearest upcoming goal**. Supporting sports get
> no boundary test; their anchors are read wherever they can be read without a session.

The nearest goal, because the goals table holds several and each has its own sport: a
gran fondo in October and "squat 140 by December" is a plan whose September boundary
week tests FTP and whose November one tests the squat. For a cyclist who lifts, every
seam holds the FTP test and no strength test is ever placed: strength is a training max
from working sets, and the collision cannot happen because only one test exists. For a
runner who lifts, the same with threshold pace. The placement text in
`coach/engine/workouts.py` says "the nearest goal's sport's test" instead of "a fitness
test of the appropriate kind", and the strength entry in `science/benchmarks.md` changes
from "1RM test, or e1RM from a set near failure" to the protocol below. The planner
already reads the goals, so it knows the sport.

**The protocol.** After the warm-up, on each lift the goal names — "squat 140" names one,
a meet names three — one set at a load good for five to eight reps, stopped one short of
failure; then the usual back-off work. The goal's lifts, not the tracked set: five rep
maxes on every tracked lift in one session is a full-body max day, and Epley on a lat
pulldown estimates nothing an athlete cares about. Not a 1RM attempt: a true single is
dangerous without a spotter, costs a week of recovery, and buys nothing a five-rep max
does not, while Epley is accurate in the 3–8 rep range and safe to repeat on the block
cadence. The planner places the slot with `benchmark_type = e1rm` exactly as it places
every other benchmark — boundary week, opener before it — and the strength call (§9)
fills it with that protocol.

**The test reads itself.** The watch records the reps and load of the near-failure set, so
unlike an FTP test, which needs `benchmark record` because Zwift shows a number the app
cannot recompute, this one captures its own result. On the pull, the day's strength
session on the date of a planned session flagged `e1rm` — the same date-and-sport link
the adherence matcher already makes — has its top set per goal lift run through Epley
and written as a `source = test` row with the exercise name, upserted on `(activity,
exercise)` like a modeled row. A lift whose top set that day is unnamed gets no row until
the naming question (§7) is answered; no guessing, same rule as everywhere else.
`benchmark record --e1rm --exercise` remains the other way to write a test row, for a
test done without the watch.

## 9. Coach consumption

The coach gets a compact **strength state** block, one line per tracked exercise, plus a
one-line summary of untracked volume:

```
STRENGTH STATE (tracked lifts; loads are per exercise and not comparable across them;
                training max is a floor estimated from working sets not taken to failure)
  deadlift (barbell, hinge)        tmax 91 kg                 last: 4x4@80 RPE6 | 5x5@55 | 3x10@60
  belt squat (machine, squat)     tmax 140 kg  tested 155 Aug 12   last: 4x10@105 | 4x10@100 | 4x10@100
  bench press (barbell, push_h)    tmax 61 kg                 last: 3x5@52 | 5x5@50 | 5x5@48
  leg press (machine, squat)      tmax 187 kg                 last: 4x10@190 (Sep 2, hotel gym) | 4x10@140 | 4x10@140
  pull-up (bodyweight, pull_v)    best 8 reps                 last: 4x6 | 3x8 | 4x5
  untracked: ~12 sets/session of core, flyes, triceps; adds ~20 min
```

With that in front of it the coach writes "belt squat 4×10 @ 110 (+5 from last week,
keep 3 in reserve)" instead of "at 8RM load", and can defend the number. The `tested`
column appears only when a test row exists for the lift; for a strength-goal athlete it is
the anchor and leads the line, for a cyclist it is usually absent. A session that fell
inside a constraint window carries the constraint's title on its entry, as the leg press
line shows: machine loads do not travel between gyms, and a human coach reading "hotel
gym" does not progress from it. The number beside it is protected by the guard (§8.1);
the sets are the coach's to read.

**The prescription is a separate LLM call, one per proposal.** The main planner
(`workout generate` / `workout adapt`) decides that Tuesday is a 65-minute non-failure
strength session, which patterns it covers, and what fatigue it may cost the Thursday
intervals — the slot and its purpose. A second, small call receives the strength science,
the strength state, the equipment for each day, and **every strength slot in the
proposal with its purpose**, and returns the exercise list with sets, reps and loads for
each. One call for all of them, because progression runs *through* the proposal: Friday's
107.5 exists only if the call that writes it knows Tuesday said 105. Equipment is not a
constraint type — the constraints table is dates, prose and a `rest` flag — so the call
reads the two places it lives: the profile's general and per-weekday equipment lists
(`coach/engine/prompt.py::_format_athlete_profile`) and the prose of the constraints
active on each date, where "hotel gym, dumbbells only" would be written. The precedent
for the call is `planning.py::_plan_reshape_verdict`, "a small call on purpose": this is
the first second call that carries science. The reasons for splitting here and only here:

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
the workout revision: one row per exercise with pattern, sets, reps and load, plus a
rendered line in the workout's `description` for the athlete. The exercise names in the
call's output are **validated against the vocabulary** before anything is written; a
name that does not resolve fails the call, which falls back as below.

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
- A slot flagged `benchmark_type = e1rm` (§8.2) is filled by the same call with the
  rep-max protocol on the goal's lifts, plus back-off work sized to the slot. The planner
  only ever places that slot for a strength goal, so the strength call never has to know
  the athlete's goal sport itself.

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
some exercise in that pattern, at roughly the prescribed sets × reps, at a load within a
band of the prescribed one when the exercise is the prescribed one. The prescribed side is
read from `prescribed_sets` (§9), the recorded side from `exercise_sets`. Extras are
neutral — information for §9, never a deviation. Two things are deviations worth flagging:

- a prescribed pattern with no exercise in it (skipped the hinge);
- a tracked lift done at a very different rep scheme from the prescription (4×10 where
  4×4 was asked), because that is a different stimulus, not a substitution.

Substitution within a pattern (goblet squat for back squat, pulldown for pull-up) is
adherence, with the note that the numbers landed on a different exercise. The one-line
strength summary the planner reads inside the commitment window (§9) is this pass's
output, rendered per session.

A strength test session (§8.2) is done when every goal lift has a named top set in the
5–8 rep range; a lift whose top set is unnamed is "test pending your answer", not a
deviation, and becomes a test row when the block is named. Here substitution is not
adherence: a goblet squat top set says nothing about the back squat's max, so the lift
counts as skipped and its previous test row stands.

## 11. Phasing, and the science trim

**Phase 1 — data, no prompt changes.** The vocabulary table with the full Garmin mapping,
`exercise_sets`, `strength.sets_since`, the pull with the 7-day set re-fetch, the naming
question through the chooser, and sets shown in `workout compare` / "Done lately" — both
of which today render a strength session as duration, load and RPE only
(`cli/common.py::format_actual`, `cli/render.py::simple_compare_lines`). At the end of it
TrainMate knows what the athlete lifts and the coach does not use it yet. Deliberately
boring, so it can be checked against reality — do Connect edits come through, is 7 days
enough, does the load-only block split ask sensible questions — before anything depends
on it.

**Phase 2 — the coach.** Tracked-lift derivation, strength state, the `benchmark_results`
extension with its three rules, `prescribed_sets`, the one-call prescription, strength
adherence with its one-line summary to the planner, the shipped strength science file,
and the two one-line changes that carry the nearest-goal rule (§8.2): the placement text
and the strength entry in `science/benchmarks.md`. Built as a second call from the start:
bolting a lift-history block onto the existing prompt and splitting later is a detour
through the direction the prompt is trying to leave.

**Deferred until an athlete with a strength goal exists:** the self-capturing test (§8.2)
and the test-session adherence rule (§10). Neither runs on an instance whose goals are
endurance, because the planner never places the slot there. The rule and the shape are
decided now so the schema and the prompt do not close the door; the code is written for
the first instance that opens it. Body weight from Garmin's weigh-ins (§8) waits for the
first tracked bodyweight lift the same way.

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
- No inferred names, ever. Templates, if they come, are proposals with a human tap. A name
  a person gave is never overwritten; a Garmin name on a bodyweight exercise at a heavy
  load is not a name.
- The naming question is the blocking chooser, asked last in the command, one block per
  question, blocks split by load, with "leave it unnamed" as an answer.
- The session is the day's highest-load strength activity; warm-up and mobility
  activities are not sessions.
- Tracked lifts by frequency and prescription, never by load, never by config.
- A training max per exercise from the set with the highest Epley estimate, named as
  the floor it is; patterns for adherence only. Modeled rows only from 3–6 rep top sets,
  only within the guard band, one per session and exercise.
- A tested max and a training max never compete for a current value; the strength state
  shows both. The ANCHORS ON RECORD line and the plan snapshot skip `e1rm`.
- A block's test measures the nearest goal's sport, on the goal's lifts. A cyclist's
  boundary week holds the FTP test and nothing else, because a second test would cost an
  opener day and could land a near-failure leg session before the ride that calibrates
  the next block.
- Strength prescription is one LLM call per proposal, with structured output in
  `prescribed_sets`, validated against the vocabulary; the endurance planner stays one
  call and reads a one-line strength adherence summary.
- The load is the weight moved in one rep; reps on one-sided exercises are per side.
- Progression science is shipped, as double progression.

Open:

- The habitual threshold (3 of the last 8 sessions) is a first guess; revisit once the
  table has two months of rows. It interacts with the split: on a push/pull/legs
  rotation each lift lands in about 2.7 of 8 sessions and flickers in and out of the
  tracked set, so the fix, if one is needed, is a longer window.
- The rep window for modeled rows (3–6) and the guard's defaults (15%, 8 weeks) are
  first guesses too. A block that never visits 3–6 reps writes no modeled rows, which is
  accepted; if the timeline turns out too sparse, widen the window before loosening the
  guard.
- Whether a supporting-sport athlete ever misses a tested max. The strength call could
  write "top set: 5+ reps at 105, one short of failure" into an ordinary mid-block
  session and the pull could read that set as a test because the prescription said it
  was one — inside the strength call, touching no planner rule. Wait for phase 2 to show
  whether the floor is missed before building it.
- Pushing the prescription to the watch (`upload_workout` + `schedule_workout`) would
  make the watch name the exercises itself, which removes §7 for an athlete who follows
  the plan exactly and adds friction for one who improvises. Garmin's strength-workout
  payload is the least documented corner of the API; verify the format before promising it.

## 13. Out of scope

Velocity-based training, per-set RPE, exercise technique notes, and any third-party
lifting app (Hevy, Strong) as a source.
