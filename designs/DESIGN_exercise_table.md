# The exercise table: Garmin's names are the names of exercises

**Status:** Implemented, both steps of §11 · **Date:** 2026-10-03 · **Branch:**
worktree-exercise-table

Stamind keeps one shipped table of strength exercises, `stamind/strength/exercises.tsv`. Today
each line has a name Stamind made up from a Garmin name, and that made-up name is what the
database stores. This design removes the made-up name. An exercise is called what Garmin calls
it, the words a person reads are worked out from that name when they are shown, and the table
says for each exercise which muscles it works and which gear it needs.

## 1. The week

It is Friday 2 October. The athlete squats with a barbell, five reps at 55 kg and three sets at
70, and logs them on the gym page under "back squat". Stamind stores them under `back squat`. In
the table, `back squat` is the line whose only Garmin name is `SANDBAG/BACK_SQUAT`, with
equipment `dumbbell`. The table made that name by dropping Garmin's category, so the word
"sandbag" was lost. The barbell lift is another line, `barbell back squat`. So the history now
holds a 70 kg sandbag squat nobody did.

The same thing has happened to seven more words in this athlete's database: `chest press` (the
band exercise in the table), `glute bridge` at 110 to 140 kg (the band exercise), `chest fly` at
50 to 60 kg (the suspension-trainer exercise), `hamstring curls` and `ab twist` (band exercises),
`hamstring curl` (the suspension-trainer exercise) and `wheel` (the yoga pose). More than a
hundred lines of the table have a name that lost its implement this way.

A second week. The athlete travels, and the hotel gym has dumbbells and a flat bench. The
strength planner, the model call that writes a strength session's exercises, is shown
`incline dumbbell bench press (push_horizontal, dumbbell)`. One word of equipment cannot say
that the bench has to tilt, so the session can hold an exercise the athlete cannot do.

After this design, the first week reads: the athlete picks "Squat: barbell back squat", and
`SQUAT/BARBELL_BACK_SQUAT` is stored. The second week reads: the strength planner is shown
`BENCH_PRESS/INCLINE_DUMBBELL_BENCH_PRESS` with the gear "Adjustable Bench, Dumbbells".

## 2. Words used here

- A **Garmin name** is how Garmin writes an exercise: a category, a slash, a name, as in
  `SQUAT/BARBELL_BACK_SQUAT`. A Garmin name with no slash, such as `ROW`, is a set the athlete
  tagged with a category and no exercise.
- A **class** is one line of the table: the Garmin names whose kilograms compare. `PULL_UP/PULL_UP`
  and `PULL_UP/WEIGHTED_PULL_UP` are one class, because the second is the first with weight added.
- The **key** of a class is the first Garmin name on its line. It is what the database stores.
- An **added exercise** is one Garmin has no name for, such as the pec deck. It gets a name of the
  same shape, written by hand.
- **Gear** is what a gym must have for the exercise to be done as named.
- **The page** is the gym logger, the Telegram Mini App the athlete ticks sets in
  (DESIGN_gym_logger.md).

## 3. The table

### 3.1 A line

Five columns, separated by tabs. Lines starting with `#` are comments.

```
# names	pattern	muscles	gear	photos
SQUAT/BARBELL_BACK_SQUAT	squat	QUADS,GLUTES|HAMSTRINGS	Barbell, Squat Rack	Barbell_Squat
PULL_UP/PULL_UP PULL_UP/WEIGHTED_PULL_UP PULL_UP	pull_vertical	LATS,TRAPS|BICEPS,FOREARM,SHOULDERS	Pull-up Bar
SANDBAG/BACK_SQUAT	squat	QUADS,GLUTES|HAMSTRINGS	Sandbag
POSE/WHEEL			Nothing
+FLYE/PEC_DECK	accessory	CHEST|SHOULDERS	Machine
# nearest Garmin exercise: SQUAT/STEP_UP
+SQUAT/STEP_DOWN	single_leg	QUADS,GLUTES	Box
```

A line may stop after its last filled column. The loader pads what is missing, so an editor that
strips a trailing tab does no harm.

### 3.2 The names: a line is a class

The first column lists the Garmin names of the class, separated by spaces. The first one is the
key. The order on a line is: the plain exercise, then its weighted twin, then the bare category.
The pattern and gear of a line are those of its key: `PLANK/PLANK` needs nothing, even though its
weighted twin needs a plate.

A key never changes once shipped, because stored sets hold it. The table's header comment says
so: the first name of a line is stored, never reorder it. A name Garmin adds later is appended
to its line, or gets a line of its own.

Two things, and only these, put two Garmin names on one line:

- **A weighted twin.** Garmin has `X` and `WEIGHTED_X` for about 360 bodyweight exercises. The
  load of the class is the added load. Garmin drops a leading underscore after `WEIGHTED_`: the
  twin of `PLANK/_45_DEGREE_PLANK` is `PLANK/WEIGHTED_45_DEGREE_PLANK`. Four `WEIGHTED_` names
  have no plain exercise in Garmin's lists, and each has a line of its own.
- **A bare category.** `BENCH_PRESS/BENCH_PRESS` and the bare `BENCH_PRESS` are the same generic
  bench press.

So every name on a line has the same category, and the words of §4 always say the category Garmin
gave. Today 37 lines hold names from more than one category, and each is split, one line per
category:

- **30 lines hold more than one implement.** 28 mix a plain exercise with a band, sandbag,
  suspension-trainer, sled or battle-rope one: `OLYMPIC_LIFT/CLEAN` and `SANDBAG/CLEAN` share the
  line `clean`, so a 20 kg sandbag clean sits in the barbell clean's history. The other two hold
  implements only: `glute bridge` is a band and a suspension-trainer exercise, and `chest press`
  a band, a sled and a suspension-trainer one.
- **7 lines hold one exercise Garmin files under two categories**, such as
  `LATERAL_RAISE/ARM_CIRCLES` and `WARM_UP/ARM_CIRCLES`. Kept together, the line has one key, and
  the other filing takes its words and its pattern: arm circles done as a warm-up would read
  "Lateral raise: arm circles" and count as isolation work. Split, an athlete who logs arm
  circles under both filings has two histories of a movement with no load.

The table goes from 1,487 lines with a Garmin name to 1,532. The splits add 52 lines. Seven
lines go: each held a weighted twin apart from its exercise, and the twin joins that exercise's
line.

Both of Garmin's lists stay in the table: the 1,531 names of Garmin Connect's catalog and the 356
names only the FIT SDK has, which are 352 exercises and four bare categories (`BIKE`,
`INDOOR_ROW`, `MOVE`, `POSE`). The FIT SDK alone lacks 37 Connect names, among them
`SQUAT/BELT_SQUAT`, which the athlete logs every week.

### 3.3 An added exercise

An added exercise is written `+CATEGORY/NAME`. The category is one of Garmin's, chosen by hand,
and it is the exercise's Garmin mapping: a set can be sent to Garmin under the category alone.
The `+` is a mark in the file. The key is `SQUAT/STEP_DOWN`. A set read from Garmin never lands
on an added exercise.

When a Garmin exercise comes close, a comment line above the exercise names it:
`# nearest Garmin exercise: SQUAT/STEP_UP`. Nothing reads it. It is recorded so that an export to
Garmin, when one is designed, finds a target beside every added exercise (§12).

The table starts with 23 added exercises. Their pattern, muscles and gear were set by hand and
not reviewed.

| Key | Nearest Garmin exercise | Pattern | Gear |
|---|---|---|---|
| `BENCH_PRESS/MACHINE_CHEST_PRESS` | `BENCH_PRESS/BENCH_PRESS` | push_horizontal | Machine |
| `BENCH_PRESS/INCLINE_MACHINE_CHEST_PRESS` | `BENCH_PRESS/INCLINE_SMITH_MACHINE_BENCH_PRESS` | push_horizontal | Machine |
| `SHOULDER_PRESS/MACHINE_SHOULDER_PRESS` | the category | push_vertical | Machine |
| `ROW/MACHINE_ROW` | `ROW/ROW` | pull_horizontal | Machine |
| `FLYE/PEC_DECK` | the category | accessory | Machine |
| `FLYE/REVERSE_PEC_DECK` | `FLYE/INCLINE_REVERSE_FLYE` | accessory | Machine |
| `PULL_UP/DUMBBELL_PULLOVER` | `PULL_UP/EZ_BAR_PULLOVER` | accessory | Bench, Dumbbells |
| `SQUAT/LEG_EXTENSION` | `BANDED_EXERCISES/LEG_EXTENSION` | accessory | Machine |
| `SQUAT/MACHINE_HACK_SQUAT` | `SQUAT/BARBELL_HACK_SQUAT` | squat | Machine |
| `SQUAT/SMITH_MACHINE_SQUAT` | `SQUAT/BARBELL_BACK_SQUAT` | squat | Smith Machine |
| `SQUAT/SINGLE_LEG_LEG_PRESS` | `SQUAT/LEG_PRESS` | single_leg | Machine |
| `SQUAT/STEP_DOWN` | `SQUAT/STEP_UP` | single_leg | Box |
| `HIP_RAISE/HIP_THRUST_MACHINE` | `HIP_RAISE/BARBELL_HIP_THRUST_WITH_BENCH` | hinge | Machine |
| `HIP_RAISE/CABLE_GLUTE_KICKBACK` | `BANDED_EXERCISES/HIP_EXTENSION` | accessory | Cable Machine, Cable Attachment |
| `HIP_STABILITY/HIP_ABDUCTION_MACHINE` | `BANDED_EXERCISES/LEG_ABDUCTION` | accessory | Machine |
| `HIP_STABILITY/HIP_ADDUCTION_MACHINE` | `BANDED_EXERCISES/LEG_ADDUCTION` | accessory | Machine |
| `LEG_CURL/LYING_LEG_CURL` | `LEG_CURL/LEG_CURL` | accessory | Machine |
| `LEG_CURL/SEATED_LEG_CURL` | `LEG_CURL/LEG_CURL` | accessory | Machine |
| `LEG_CURL/NORDIC_HAMSTRING_CURL` | `LEG_CURL/LEG_CURL` | accessory | Nothing |
| `LEG_CURL/GLUTE_HAM_RAISE` | `LEG_CURL/LEG_CURL` | accessory | Roman Chair |
| `CARRY/SUITCASE_CARRY` | the category | core_carry | Dumbbells |
| `PLANK/PLANK_KETTLEBELL_DRAG` | the category | core_carry | Kettlebells |
| `PLANK/PLANK_DUMBBELL_DRAG` | the category | core_carry | Dumbbells |

Seven of them are the machines the table holds today with no Garmin name, the leg extension
among them: its line today claims `BANDED_EXERCISES/LEG_EXTENSION`, which is the band exercise
and becomes a line of its own. The hip thrust machine is what the athlete lifts under "glute
bridge" (§9). The suitcase carry and the two plank drags were added on 2 October in a worktree
that was never committed, together with one fix this design also takes:
`SANDBAG/PLANK_PULL_THROUGH` is `core_carry`, not `hinge`. The other twelve are common gym
exercises Garmin lacks, picked by the athlete.

A kettlebell press is not added. It is `SHOULDER_PRESS/DUMBBELL_SHOULDER_PRESS` done with
kettlebells (§7). A kettlebell clean and press is not added either. Garmin has
`OLYMPIC_LIFT/DUMBBELL_POWER_CLEAN_AND_STRICT_PRESS` and
`OLYMPIC_LIFT/DUMBBELL_POWER_CLEAN_AND_PUSH_PRESS`, and it is one of those done with kettlebells.

### 3.4 Pattern

The pattern says what job an exercise does in a session: `squat`, `hinge`, `single_leg`,
`push_horizontal`, `push_vertical`, `pull_horizontal`, `pull_vertical`, `core_carry` or
`accessory` (DESIGN_strength_tracking.md §4). It is how the strength planner knows what can
replace what. It never decides a load: kilograms compare inside one class only, so a 24 kg goblet
squat says nothing about a 140 kg belt squat.

`accessory` means isolation work, such as a curl. Today it is also where every yoga pose, Pilates
move, cardio drill, warm-up and conditioning drill landed. The lines of twenty Garmin categories
get no pattern: `POSE`, `MOVE`, `CARDIO`, `WARM_UP`, `RUN`, `RUN_INDOOR`, `BIKE`, `BIKE_OUTDOOR`,
`INDOOR_BIKE`, `INDOOR_ROW`, `ELLIPTICAL`, `FLOOR_CLIMB`, `STAIR_STEPPER`, `PLYO`, `BATTLE_ROPE`,
`TOTAL_BODY`, `LADDER`, `SLED`, `TIRE` and `SLEDGE_HAMMER`. That is 441 classes.

No code asks whether an exercise is progressed by rule. The rule is prose the strength planner
reads, under "Accessories" in `strength/progression.md`: an accessory is written at what the
athlete last did. That section gains one sentence: an exercise with no pattern is written the
same way. Without it, a cardio drill written into a strength session, such as the squat jacks
the companion athlete does every week, would fall under the rule that adds load.

Not handled: the patterns of the other lines are not reviewed.

### 3.5 Muscles

The main muscles, then a `|`, then the secondary ones, in Garmin's words: `ABDUCTORS`, `ABS`,
`ADDUCTORS`, `BICEPS`, `CALVES`, `CHEST`, `FOREARM`, `GLUTES`, `HAMSTRINGS`, `HIPS`, `LATS`,
`LOWER_BACK`, `OBLIQUES`, `QUADS`, `SHOULDERS`, `TRAPS`, `TRICEPS`. They are copied from Garmin
Connect's catalog, which gives them for 1,496 of its 1,531 exercises. A class takes the muscles of
its key, or of its first name that has any. A FIT-only name has none and the column stays empty.
Two of the catalog's lists repeat a muscle, and the table writes it once.

Muscles tell apart what `accessory` lumps together. A dumbbell fly, a cable crossover and the pec
deck all have `CHEST`, and a curl has `BICEPS`. They do not replace the pattern: a pull-up and a
row are both `LATS,TRAPS`.

### 3.6 Gear

A list of words from a fixed set, separated by a comma and a space. Every word in the list is
needed; the list is never a set of alternatives. `Nothing` means no gear.

The 46 words: Nothing, Bench, Adjustable Bench, Decline Bench, Preacher Bench, Roman Chair, Box,
Mat, Pull-up Bar, Dip Device, Parallettes, Rings, Suspension Trainer, Anchor, Squat Rack, Blocks,
Swiss Ball, Sliding Discs, Foam Roller, Balance Trainer, Jump Rope, Agility Ladder, Ab Wheel,
Climbing Rope, Pole, Cable Attachment, and the loads: Barbell, EZ Bar, Trap Bar, Safety Squat
Bar, Body Bar, Dumbbells, Kettlebells, Weight Plates, Medicine Ball, Sandbag, Ruck, Band, Cable
Machine, Machine, Smith Machine, Landmine, Sled, Tire, Sledge Hammer, Battle Rope.

"Machine" is the dedicated machine the exercise is named after. "Anchor" is a fixed point to tie
a band to. "Bench" means a flat bench is enough.

Where each list comes from:

| Source | Classes |
|---|---|
| Garmin's own lists, from its exercise pages (`~/garmin_exercises.tsv`) | 144 |
| A review by two model personas, a gym-floor coach and a minimal-kit trainer, on two different models, looping until they agreed (`~/garmin_gear_review.tsv`) | 1,150 |
| Today's equipment word, carried over: yoga, Pilates and pure cardio, which the review skipped | 218 |
| Today's equipment word, carried over: exercises the reviewers did not recognise | 10 |
| Set by hand: the added exercises (§3.3) | 23 |

The review was run with the 30 implement lines already split. It also took the seven weighted
twins of §3.2 as classes of their own. They now sit on their exercise's line and take its list,
so the counts above leave them out. The ten classes that come from splitting an exercise Garmin
files twice take the list of the class they were split from: `POSE/PLANK` takes the plain
plank's. That makes 1,555 classes in all.

Carried over means `barbell` becomes Barbell, `dumbbell` Dumbbells, `kettlebell` Kettlebells,
`cable` "Cable Machine, Cable Attachment", `machine` Machine and `bodyweight` Nothing. Three of
Garmin's own lists are made more exact: the two incline dumbbell exercises say Adjustable Bench
where Garmin says Bench, and `SQUAT/BACK_SQUAT_WITH_BODY_BAR` says Body Bar where Garmin says
Barbell. Garmin's words have no Smith machine and no EZ bar, so two more lists are corrected:
`SHOULDER_PRESS/SMITH_MACHINE_OVERHEAD_PRESS` says "Smith Machine, Bench" where Garmin says
"Squat Rack, Bench", and `TRICEPS_EXTENSION/EZ_BAR_OVERHEAD_TRICEPS_EXTENSION` says "EZ Bar"
where Garmin says "Cable Attachment". Left as Garmin wrote it: `CURL/DEAD_HANG_BICEPS_CURL`,
"Cable Attachment, Bench", which the rule below reads as bodyweight.

**Bodyweight.** Today the word `bodyweight` in the equipment column answers a second question:
is the load of this exercise a weight added to the body? Two places ask it. A pull reads a watch
guess of a bodyweight exercise at more than 50 kg as not that exercise
(DESIGN_strength_tracking.md §6), and the page gives a card added for a bodyweight exercise no
load. After this design an exercise is bodyweight when none of its gear is a load. A pull-up needs
a Pull-up Bar, which is not a load, so it is bodyweight. A leg curl needs a Machine, so it is not.
The rule gives another answer than today's word for 135 of the 1,532 classes. Two of those are
exercises the athletes do: the plain calf raise was `machine` and needs nothing, and the leg curl
was `bodyweight` and needs a Machine, which is right, since it is lifted at 55 to 65 kg.

Not handled: the rule misreads an exercise whose gear holds a load that is not the thing lifted,
such as an inverted row under a racked barbell.

### 3.7 Photos

The id of the same exercise in Free Exercise DB, for the lines that have one
(DESIGN_gym_logger.md §2). Where a line is split, the id stays with the plain exercise. Three ids
were given through a name that had lost its implement, and are dropped: those of today's `kneeling
crunch`, `chest press` and `back squat`.

## 4. What is stored, and what is shown

**Stored: the key.** Everywhere the database holds an exercise today, it holds the key of the
class. The athlete does weighted pull-ups on Monday and plain ones on Thursday. Both days store
`PULL_UP/PULL_UP`, with 10 kg and with no load, and they are one history.

Which exact Garmin name a set had is not lost. A set read from Garmin keeps what Garmin said in
`exercise_sets.garmin_name`, as today. For any other set it follows from the load: a class with a
weighted twin and a load above zero is the twin.

**Shown: the words.** The words are worked out from the key each time they are shown, by one
function, and never stored as an identifier:

- The category, a colon, the name, in lower case with spaces: `SQUAT/BELT_SQUAT` is
  "squat: belt squat".
- A name equal to its category shows once: `DEADLIFT/DEADLIFT` is "deadlift". So does a bare
  category: `ROW` is "row".
- A leading underscore is dropped: `PULL_UP/_30_DEGREE_LAT_PULLDOWN` is
  "pull up: 30 degree lat pulldown".
- The first letter is a capital where a line starts with the exercise, as today:
  "Squat: belt squat 3×4–6 @ 140 kg".

The category is Garmin's filing, in Garmin's words, so some read oddly: "pull up: lat pulldown",
"squat: leg press", "banded exercises: glute bridge". That is accepted. In exchange no two
classes can show the same words, and the band glute bridge can no longer pass for a barbell one.

The words hold a colon, and two places put them in a line that has its own punctuation. The
page's Markdown export reads "- Squat: belt squat: 1x5 (120 kg)". The line that lists a past
session's exercises joined them with commas; it joins them with semicolons: "✅ Pull up: lat
pulldown; shoulder press: seated barbell shoulder press; row".

## 5. Where a name lives

| Place | Holds after this design |
|---|---|
| `exercise_sets.exercise` | The key, or nothing while the set is unnamed |
| `exercise_sets.garmin_name` | What Garmin said. Unchanged |
| `prescribed_sets.exercise` | The key |
| `gym_logs.payload`, the page's log kept as sent | Keys, in each entry's `n` |
| A logged day's `gym` in the calendar's month files (DESIGN_gym_logger.md §8) | Keys. It is the session and the stored log, built again from the two places above |
| `athlete_queue.payload` of a question about sets, or of a proposal | Keys, once written by the new code. None is converted (§9) |
| `workouts.description` | Words. Written once and never rewritten |

No column is added or removed, so `SCHEMA_VERSION` stays at 26. A version stamp would not guard
the conversion of §9 anyway: opening an older database stamps it with the new version and changes
nothing else (`db/schema.py`, `_init_db`).

A session's description is frozen text. A session written before the conversion keeps "Belt squat
3×4–6 @ 140 kg" in its description, in the chat's Today and on the calendar, until its sets next
change. The page and `workout list` read the prescribed sets, so they show the new words at once.

## 6. Reading sets from Garmin

A set comes from Garmin tagged `SUSPENSION/CHEST_FLY`. Stamind finds the line that holds that
name and stores its key. A weighted twin stores the key of its class, and the load says the rest.

A name the table lacks, from a later firmware, is stored as it came: the Garmin name is its own
key. It has no pattern, muscles or gear, its words are worked out like any other, and the pull
still prints the line that asks for it to be added to the table. Today such a set is stored under
made-up words that match nothing.

A set in Garmin's `UNKNOWN` category stays unnamed, as today.

Not handled:

- On a day recorded by the watch alone, a set lands on the Garmin name the athlete picked in
  Garmin Connect. The athlete who files the hip thrust machine under the band glute bridge there
  gets the band glute bridge, and moves it with `strength name`.
- A set stored under a new Garmin name before the table knew that name keeps it. If the name is
  later appended to another line, those sets are renamed by hand.

## 7. What changes for the athlete and for the model calls

**The athlete.** Every place that prints an exercise prints its words: the terminal's strength
commands, the chat, the session's description, the page. `strength log` and `strength exercises`
match what is typed against the words the way they match the names today: the exact words, or
else every exercise whose words contain it. "leg press" still finds "squat: leg press". Lists
sort by the words. The heading of `strength log NAME` gives the lift's pattern and its gear. The
index of `strength exercises` gains a group for the lines with no pattern.

The page's search lists one entry per class, under the words of its key, and searches those
words. "Pull up" is one entry. Nothing is hidden: the yoga poses are in the list. The search
leaves the word "weighted" out of what is typed, so "weighted pull up" finds "pull up": a weighted
twin is its class with a load.

**Buttons.** When the athlete types an exercise in the chat, Stamind offers up to three names as
buttons. Today each button carries the name itself, and Telegram allows a button 64 bytes. 65
Garmin names do not fit. The buttons carry the position of the choice, as the queue's buttons
already do.

**The strength planner.** Everything it is shown names an exercise by its key: its list, the
history, and the lines that say how a session is written now. Its list holds one class per line,
as the key, then the pattern, the main muscles and the gear:

```
SQUAT/BELT_SQUAT (squat; QUADS, GLUTES; Machine)
POSE/WHEEL (Nothing)
```

It answers with keys. A Garmin name of the table that is not a key, such as
`PULL_UP/WEIGHTED_PULL_UP`, is taken as the key of its class. A name the table lacks is dropped
from the session, as an unknown name is today. The notes it writes under a session name the
exercises in plain words, as today.

Today the list leaves out the accessory exercises the athlete has never done: about 690 lines
and 31 kB. The athlete chose to be offered everything. The full list is 1,555 lines and
97 kB, three times the size, because each line is also longer.

It is told one new rule: an exercise whose gear holds Dumbbells can be done with kettlebells of
the same weight, and the reverse. The exercise keeps its key and its history. This is why no
kettlebell line is added for a dumbbell exercise.

**The naming question.** The model call that proposes names for what the athlete typed
(`strength/questions.py`) is given the key of every class and answers with keys, checked as the
strength planner's are. The buttons show the words. Its list goes from 32 kB to 46 kB.

**The week planner** writes no exercise into a brief and is given no list. Unchanged.

## 8. The page and the questions in the queue

**The page.** Both payloads keep their shape (DESIGN_gym_logger.md §3, §4) and go to version 2:
`n` holds a key. `miniapp/exercises.json` gives the page, for each class, the key, the words,
the pattern, the gear and whether it is bodyweight, with the photos id when there is one. The page
shows and searches the words and sends the key. The state the page saves on the phone changes its
version too, so a state saved under the old names is not read.

The page draws a session only when it is version 2. A button drawn before the conversion still
sits in the chat with the old names in its address, and the keyboard is redrawn only when the bot
next sends a message. A tap on such a button opens the page on: "This button is out of date. Send
your coach any message and tap the new one." Without the check the page would draw the old names,
save them on the phone, and have its log refused at Finish.

The page's files are named with the commit, so a phone never mixes two versions
(DESIGN_gym_logger.md §2). `exercises.json` is fetched without that mark today. It gets it, since
its shape changes here for the first time.

The main athlete's longest session, 16 lines on 9 October, has an address of 1,722 characters
today and 1,927 with keys. Telegram allows the whole keyboard about 9.9 kB, shared with the
calendar and the plan buttons, and it fits with about 500 bytes left. The largest log goes from
1,395 to 1,561 bytes of the 4,096 allowed.

In general a line costs about 84 characters where it costs 71 today, so the keyboard holds a
session of about 22 lines where it holds about 26 today. Not handled: a longer session makes
Telegram refuse the keyboard, and the message goes out without it, as today.

A log from a page still on version 1 is refused, as a log of a version the bot does not know is
today.

**A past log opened from the calendar** (DESIGN_gym_logger.md §8). The calendar hands the page a
day's session beside its stored log. The session is built when the month's file is built, so it
is version 2 and holds keys, and the page checks its version like any session's. The stored log
holds keys once the conversion of §9 has run. The page does not read the log's own version. It
takes the log's entries, its day and its two clock times, shows each key's words, and the log it
sends again is a new one of version 2. A month's file built before the conversion carries a
version 1 session and the old names, so the page does not draw its gym logs until the file is
built again (§9). The athlete came from a day of the calendar and not from a button, so the page
says "This log is out of date and cannot be opened." and shows one button, "‹ Calendar", which
goes back.

The page's notes are the text under the exercise lines of the description. Today they are found
by comparing each stored line with the line a fresh render would give. A session written before
the conversion would fail that comparison and show its old exercise lines as notes. They are found
by counting instead: as many lines are dropped as the session has exercises.

Not handled: a session open on the page across the conversion cannot be sent, and a reload starts
it from the session as written. The refused log is still in `logs/gym_logs/`.

**The queue.** A waiting "are the sets final?" question holds the watch's guesses, and a waiting
"what was this?" question holds its answers. Both hold keys when the new code wrote them. An
answer carries the key to store and is shown as its words. Today the label is both.

## 9. The one-off conversion

`scripts/migrate_exercise_names.py`, run once per athlete on the instance named by
`STAMIND_CONFIG`. Every Stamind instance is operated by the author, so there is no compatibility
code: the new code reads keys only.

The script rewrites three places: `exercise_sets.exercise`, `prescribed_sets.exercise`, and the
`n` of every entry in `gym_logs.payload`. It leaves `workouts.description` alone. It also leaves
a stored log's `v` at 1. Nothing reads it: a past log opened from the calendar is drawn from its
entries, and the version the page checks is the session's (§8).

**It stops before anything while a "what was this?" question or a proposal waits in the queue**,
and lists each with its id. A tap on either would write the old names into the database. Step 1
below settles them before main is landed; this stop catches one that was missed. A missed
proposal is answered with `sm queue answer ID` as usual: its rows are converted by the next run.
A missed question is answered through "something else…" or left unnamed, since its listed
answers have no key. A waiting "are
the sets final?" question is left alone: its names are only shown, and "yes, final" reads the
sets from Garmin again.

**It changes a value only while that value is still an old name.** Old names are lower case and
keys are upper case, so a second run changes nothing.

`scripts/exercise_name_migration.tsv` gives, for each old name, the keys of the classes its line
became: one key when the line was not split, several when it was (§10). `leg extension` has two
keys in the list: the band exercise its line claimed, and the added machine. For each stored old
name, the first of these that applies:

1. **A rename given on the command line** (below). It wins in all three places.
2. **One key in the list:** that key.
3. **Several keys:** the key of the class holding the set's own `garmin_name`, when it is one of
   them. A set Garmin tagged `SANDBAG/CLEAN` goes to the sandbag clean.
4. **Otherwise the name is not settled**, and the script never picks one of several classes
   itself.

The script prints every distinct stored name with the key it becomes, its number of sets and its
loads. A name is settled only when every stored occurrence of it is. One that is not has no key
there. If one is left, the script writes nothing and stops, and the operator gives a rename for
each. Otherwise it writes after a yes.

**The athlete's own answers.** Where a stored word can mean several exercises, or the table gave
it another meaning than the athlete's, only the athlete knows what was lifted. A rename is given
as `--rename "back squat=SQUAT/BARBELL_BACK_SQUAT"`. Its key must be a key of the new table, or
the script stops. The main athlete answered on 2026-10-03:

| Stored under | Lifted | Key |
|---|---|---|
| `back squat` | Barbell back squat | `SQUAT/BARBELL_BACK_SQUAT` |
| `chest press` | Machine chest press | `BENCH_PRESS/MACHINE_CHEST_PRESS` |
| `glute bridge` | Hip thrust machine | `HIP_RAISE/HIP_THRUST_MACHINE` |
| `chest fly` | Cable crossover | `FLYE/CABLE_CROSSOVER` |
| `hamstring curls` | Leg curl machine | `LEG_CURL/LEG_CURL` |
| `hamstring curl` | A warm-up set on the same leg curl machine | `LEG_CURL/LEG_CURL` |
| `ab twist` | Russian twists | `CORE/RUSSIAN_TWIST` |
| `wheel` | Ab wheel rollout | `CORE/KNEELING_AB_WHEEL` |
| `plank` | The plain plank | `PLANK/PLANK` |
| `row` | Seated cable row | `ROW/SEATED_CABLE_ROW` |
| `clean and press` | A plain clean and press, for the sessions to come | `OLYMPIC_LIFT/CLEAN_AND_PRESS` |

The companion athlete's two words were answered the same day:

| Stored under | Lifted | Key |
|---|---|---|
| `push up` | The ordinary push-up | `PUSH_UP/PUSH_UP` |
| `arm circles` | The warm-up drill | `WARM_UP/ARM_CIRCLES` |

`clean and press` has two answers. The sets the main athlete did, on 10 and 17 September, were
strict presses with kettlebells, which is `OLYMPIC_LIFT/DUMBBELL_POWER_CLEAN_AND_STRICT_PRESS`
(§3.3). The sessions to come stay as they are written, a plain clean and press, since the press
varies by session. A rename gives a word one key, so the rename sends the word to the plain
clean and press. After the conversion, `sm strength name 2026-09-10` and
`sm strength name 2026-09-17` move the sets done to the strict press. The sets done and the
sessions to come are then two exercises, with two histories.

**The steps for the operator.** They run when step 1 of §11 lands; step 2 needs no conversion.

1. Pick an evening when nobody trains. First run `sm queue` on each instance. A waiting "what
   was this?" question or proposal is answered now, in the chat or in the terminal, while the
   old code still runs. A proposal, and a question put off until later, are
   in no walk of the queue: `sm queue answer ID` answers them.
   Once main is landed, a listed answer of an old question has no key and cannot be applied.
   Then stop both bots: every command a bot starts is a fresh process read
   from the checkout, so the new code runs as soon as main is landed there.
2. Land the branch on main in the live checkout and push it. Wait until the page's deployment is
   done.
3. Copy each database file, and its `-wal` file if it is not empty. Then run the script once per
   instance, with its renames. Then run `sm data publish` on each instance that has a bucket: it
   builds every month's file again, so no logged day keeps the old names (§8).
4. Start the bots. The next morning's message redraws each keyboard.

Not handled: new code started on a database that was not converted reads every old name as an
exercise it does not know. Nothing is lost, and the script can still be run then.

## 10. Building the table

The new `exercises.tsv` and `scripts/exercise_name_migration.tsv` are built once, by a script
that is not kept. It reads today's table, Garmin Connect's catalog
(`~/garmin_connect_exercises.json`, a copy of
`connect.garmin.com/web-data/exercises/Exercises.json`), Garmin's own gear lists
(`~/garmin_exercises.tsv`) and the review (`~/garmin_gear_review.tsv`). The table is the record,
and after this build it is edited by hand, as today.

## 11. The order of the work

**Step 1: the table and what is stored.** The table in its new shape, with its muscles and gear.
The vocabulary module reads it and gives, for a key, the class, pattern, muscles, gear, photos and
words, and for any Garmin name its key. Everything that stores, compares or validates a name works
on keys, and everything that prints one prints its words (§4). Both model calls change with it,
since their answers are validated: each is shown keys and answers keys (§7). The strength
planner's line takes the new form with today's selection of lines: an accessory the athlete has
never done is left out, and a line with no pattern is left out the same way. The page's two
payloads and its catalog carry keys (§8). The sentence on exercises with no pattern (§3.4). The
conversion script. The tests' fixtures move to keys.

**Step 2: what is offered.** The strength planner is shown every class and told the dumbbell and
kettlebell rule, and the terminal's exercise listing shows muscles and gear (§7).

Tests that read the table check five things: a Garmin name is on one line only, the names of a
line share one category, a weighted twin sits on the line of its exercise, every gear word is
one of the 46, and no two classes show the same words.

When the code lands, `docs/ARCHITECTURE.md` is updated, and the passages that describe the old
table are replaced by a pointer here: DESIGN_strength_tracking.md §4, §6 (the bodyweight check),
§8 (the heading of a history entry), §9 (the list and its accessory filter) and §11.1, and
DESIGN_gym_logger.md §2 to §4.

## 12. Not built

- **Export to Garmin.** The table holds what an export needs: a Garmin name for every class, the
  twin rule of §4, and a mapping for every added exercise. Whether Garmin accepts a workout step
  with a category and no exercise is not verified.
- **A link to Garmin's page for an exercise.** `connect.garmin.com/modern/exercises/...` sends a
  reader who is not signed in to Garmin's sign-in page, so the page does not link to it.
- **Which machines a gym has.** "Machine" does not say which one. The strength planner reads the
  athlete's equipment as free text, as today.

## 13. Decisions taken while writing this

- **The key is stored, never the weighted twin.** The athlete was told "the weighted name is
  stored when a load is entered". Storing the key and reading the twin off the load gives the same
  answer for an export, and leaves every comparison in the code a comparison of two stored names,
  as today. Storing the twin would make about twenty of them compare classes instead.
- **A line never holds two categories.** The athlete asked for the implements to be split. The
  seven lines that hold one exercise under two of Garmin's categories are split as well (§3.2),
  so that a warm-up keeps Garmin's warm-up category in its words and in its pattern.
- **The `+` is not stored.** If Garmin later adds the same name, the line drops its mark and
  nothing stored changes.
