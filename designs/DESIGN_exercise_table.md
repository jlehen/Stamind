# The exercise table: Garmin's names are the names of exercises

**Status:** Draft · **Date:** 2026-10-03 · **Branch:** worktree-exercise-table

Stamind keeps one shipped table of strength exercises, `stamind/strength/exercises.tsv`. Today
each line has a name Stamind made up from a Garmin name, and that made-up name is what the
database stores. This design removes the made-up name. An exercise is called what Garmin calls
it, the words a person reads are worked out from that name when they are shown, and the table
says for each exercise which muscles it works and which gear it needs.

## 1. The week

It is Friday 2 October. The athlete squats with a barbell, five reps at 55, 60, 65 and 70 kg, and
names the four sets "back squat" in the chat. Stamind stores them under `back squat`. In the
table, `back squat` is the line whose only Garmin name is `SANDBAG/BACK_SQUAT`, with equipment
`dumbbell`. The table made that name by dropping Garmin's category, so the word "sandbag" was
lost. The barbell lift is another line, `barbell back squat`. So the history now holds a 70 kg
sandbag squat nobody did.

The same thing has happened five more times in this athlete's database: `chest press` (the band
exercise in the table), `glute bridge` at 110 to 140 kg (the band exercise), `chest fly` at 50 to
60 kg (the suspension-trainer exercise), `hamstring curls` (the band exercise) and `wheel` (the
yoga pose). 110 lines of the table have a name that lost its implement this way.

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
names	pattern	muscles	gear	photos
SQUAT/BARBELL_BACK_SQUAT	squat	QUADS,GLUTES|HAMSTRINGS	Barbell, Squat Rack	Barbell_Squat
PULL_UP/PULL_UP PULL_UP/WEIGHTED_PULL_UP PULL_UP	pull_vertical	LATS,TRAPS|BICEPS,FOREARM,SHOULDERS	Pull-up Bar
SANDBAG/BACK_SQUAT	squat	QUADS,GLUTES	Sandbag
POSE/WHEEL			Nothing
+FLYE/PEC_DECK	accessory	CHEST|SHOULDERS	Machine
+SQUAT/STEP_DOWN~SQUAT/STEP_UP	single_leg	QUADS,GLUTES	Box
```

A line may stop after its last filled column. The loader pads what is missing, so an editor that
strips a trailing tab does no harm.

### 3.2 The names: a line is a class

The first column lists the Garmin names of the class, separated by spaces. The first one is the
key. The order on a line is: the plain exercise, then its weighted twin, then any other name,
then the bare category. A key never changes once shipped, because stored sets hold it. A name
Garmin adds later is appended to its line, or gets a line of its own.

Three things, and only these, put two Garmin names on one line:

- **A weighted twin.** Garmin has `X` and `WEIGHTED_X` for about 360 bodyweight exercises. The
  load of the class is the added load.
- **A bare category.** `BENCH_PRESS/BENCH_PRESS` and the bare `BENCH_PRESS` are the same generic
  bench press.
- **One exercise Garmin files twice.** `LATERAL_RAISE/ARM_CIRCLES` and `WARM_UP/ARM_CIRCLES`.

Two implements are never one class. Today 28 lines mix a plain exercise with a band, sandbag,
suspension-trainer, sled or battle-rope one: `OLYMPIC_LIFT/CLEAN` and `SANDBAG/CLEAN` share the
line `clean`, so a 20 kg sandbag clean sits in the barbell clean's history. Each such line is
split, one line per implement category. The table goes from 1,487 lines with a Garmin name to
1,529.

Both of Garmin's lists stay in the table: the 1,531 names of Garmin Connect's catalog and the 352
names only the FIT SDK has. The FIT SDK alone lacks 37 Connect names, among them
`SQUAT/BELT_SQUAT`, which the athlete logs every week.

### 3.3 An added exercise

An added exercise is written `+CATEGORY/NAME`. The category is one of Garmin's, chosen by hand,
and it is the exercise's Garmin mapping: a set can be sent to Garmin under the category alone.
When a Garmin exercise comes close, it follows after a `~`: `+SQUAT/STEP_DOWN~SQUAT/STEP_UP`.
The `+` and what follows the `~` are marks in the file. The key is `SQUAT/STEP_DOWN`.

A set read from Garmin never lands on an added exercise, and the name after `~` is not a member
of the class. Nothing reads the mapping today. It is recorded so that an export to Garmin, when
one is built, has a target for every exercise (§12).

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
kettlebells (§7).

### 3.4 Pattern

The pattern says what job an exercise does in a session: `squat`, `hinge`, `single_leg`,
`push_horizontal`, `push_vertical`, `pull_horizontal`, `pull_vertical`, `core_carry` or
`accessory` (DESIGN_strength_tracking.md §4). It is how the strength planner knows what can
replace what. It never decides a load: kilograms compare inside one class only, so a 24 kg goblet
squat says nothing about a 140 kg belt squat.

`accessory` means isolation work, such as a curl. Today it is also where every yoga pose, Pilates
move, cardio drill and warm-up landed: 341 lines in Garmin's categories `POSE`, `MOVE`, `CARDIO`,
`WARM_UP`, `RUN`, `RUN_INDOOR`, `BIKE`, `BIKE_OUTDOOR`, `INDOOR_BIKE`, `INDOOR_ROW`, `ELLIPTICAL`,
`FLOOR_CLIMB` and `STAIR_STEPPER`. Those lines get no pattern. Code that asks "is this progressed
by rule?" treats no pattern as it treats `accessory`: not progressed.

Not handled: the 86 conditioning lines (`PLYO`, `BATTLE_ROPE`, `TOTAL_BODY`, `LADDER`, `SLED`,
`TIRE`, `SLEDGE_HAMMER`) keep `accessory`, and the patterns of the other lines are not reviewed.

### 3.5 Muscles

The main muscles, then a `|`, then the secondary ones, in Garmin's words: `ABDUCTORS`, `ABS`,
`ADDUCTORS`, `BICEPS`, `CALVES`, `CHEST`, `FOREARM`, `GLUTES`, `HAMSTRINGS`, `HIPS`, `LATS`,
`LOWER_BACK`, `OBLIQUES`, `QUADS`, `SHOULDERS`, `TRAPS`, `TRICEPS`. They are copied from Garmin
Connect's catalog, which gives them for 1,496 of its 1,531 exercises. A class takes the muscles of
its key, or of its first name that has any. A FIT-only name has none and the column stays empty.

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
| A review by two model personas, a gym-floor coach and a minimal-kit trainer, on two different models, looping until they agreed (`~/garmin_gear_review.tsv`) | 1,154 |
| Today's equipment word, carried over: yoga, Pilates and pure cardio, which the review skipped | 218 |
| Today's equipment word, carried over: exercises the reviewers did not recognise | 13 |
| Set by hand: the added exercises (§3.3) | 23 |

Carried over means `barbell` becomes Barbell, `dumbbell` Dumbbells, `kettlebell` Kettlebells,
`cable` "Cable Machine, Cable Attachment", `machine` Machine and `bodyweight` Nothing. Three of
Garmin's own lists are made more exact: the two incline dumbbell exercises say Adjustable Bench
where Garmin says Bench, and `SQUAT/BACK_SQUAT_WITH_BODY_BAR` says Body Bar where Garmin says
Barbell.

**Bodyweight.** Today the word `bodyweight` in the equipment column answers a second question:
is the load of this exercise a weight added to the body? Two places ask it. A pull reads a watch
guess of a bodyweight exercise at more than 50 kg as not that exercise
(DESIGN_strength_tracking.md §6), and the page gives a card added for a bodyweight exercise no
load. After this design an exercise is bodyweight when none of its gear is a load. A pull-up needs
a Pull-up Bar, which is not a load, so it is bodyweight. A leg curl needs a Machine, so it is not.

### 3.7 Photos

Unchanged: the id of the same exercise in Free Exercise DB, for the lines that have one
(DESIGN_gym_logger.md §2).

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

## 5. Where a name lives

| Place | Holds after this design |
|---|---|
| `exercise_sets.exercise` | The key, or nothing while the set is unnamed |
| `exercise_sets.garmin_name` | What Garmin said. Unchanged |
| `prescribed_sets.exercise` | The key |
| `gym_logs.payload`, the page's log kept as sent | Keys, in each entry's `n` |
| `athlete_queue.payload` of a waiting question about sets | Keys (§8) |
| `athlete_queue.payload` of a waiting proposal | Keys in its sessions' prescribed sets |
| `workouts.description` | Words. Written once and never rewritten |

No column is added or removed, so `SCHEMA_VERSION` stays at 26. A version stamp would not guard
the conversion of §9 anyway: opening an older database stamps it with the new version and changes
nothing else (`db/schema.py`, `_init_db`).

A session's description is frozen text. A session written before the conversion keeps "Belt squat
3×4–6 @ 140 kg", and one written after it reads "Squat: belt squat 3×4–6 @ 140 kg". The step that
brings the upcoming sessions to the new words is in §9.

## 6. Reading sets from Garmin

A set comes from Garmin tagged `SUSPENSION/CHEST_FLY`. Stamind finds the line that holds that
name and stores its key. A weighted twin stores the key of its class, and the load says the rest.

A name the table lacks, from a later firmware, is stored as it came: the Garmin name is its own
key. It has no pattern, muscles or gear, its words are worked out like any other, and the pull
still prints the line that asks for it to be added to the table. Today such a set is stored under
made-up words that match nothing.

A set in Garmin's `UNKNOWN` category stays unnamed, as today.

## 7. What changes for the athlete and for the model calls

**The athlete.** Every place that prints an exercise prints its words: the terminal's strength
commands, the chat, the session's description, the page. `strength log` and `strength exercises`
match what is typed against the words, and accept a key. Lists sort by the words.

The page's search lists one entry per class, under the words of its key, and searches those
words. "Pull up" is one entry. Nothing is hidden: the yoga poses are in the list.

**Buttons.** When the athlete types an exercise in the chat, Stamind offers up to three names as
buttons. Today each button carries the name itself, and Telegram allows a button 64 bytes. 65
Garmin names do not fit. The buttons carry the position of the choice, as the queue's buttons
already do.

**The strength planner.** It is shown every class, one per line, as the key, then the pattern,
the main muscles and the gear:

```
SQUAT/BELT_SQUAT (squat; QUADS, GLUTES; Machine)
POSE/WHEEL (Nothing)
```

That is about 1,550 lines where it is shown about 700 today. Today the list leaves out the
accessory exercises the athlete has never done; the athlete chose to be offered everything. The
model answers with keys, and a key the table lacks is dropped from the session as an unknown name
is today. The history it reads names each exercise by its key.

It is told one new rule: an exercise whose gear holds Dumbbells can be done with kettlebells of
the same weight, and the reverse. The exercise keeps its key and its history. This is why no
kettlebell line is added for a dumbbell exercise.

**The naming question.** The model call that proposes names for what the athlete typed
(`strength/questions.py`) is given every key with its words and answers with keys.

**The week planner** writes no exercise into a brief and is given no list. Unchanged.

## 8. The page and the questions in the queue

**The page.** Both payloads keep their shape (DESIGN_gym_logger.md §3, §4) and go to version 2:
`n` holds a key. `miniapp/exercises.json` gives the page, for each class, the key, the words,
the pattern, the gear and whether it is bodyweight, with the photos id when there is one. The page
shows and searches the words and sends the key. The state the page saves on the phone changes its
version too, so a state saved under the old names is not read.

A nine-exercise session's address grows from about 1,140 to about 1,240 characters, and a 36-set
log from about 810 to about 890 bytes of the 4,096 allowed.

The page is deployed when main is pushed, and the bot runs the code it was restarted on. A log
from a page still on version 1 is refused with a line that says to reload the page.

The page's notes are the text under the exercise lines of the description. Today they are found
by comparing each stored line with the line a fresh render would give. A session written before
the conversion would fail that comparison and show its old exercise lines as notes. They are found
by counting instead: as many lines are dropped as the session has exercises.

**The queue.** A waiting "are the sets final?" question holds the watch's guesses, and a waiting
"what was this?" question holds its answers. Both hold keys. An answer carries the key to store
and is shown as its words. Today the label is both.

## 9. The one-off conversion

`scripts/migrate_exercise_names.py`, run once per athlete with the bots stopped, on the instance
named by `STAMIND_CONFIG`. Every Stamind instance is operated by the author, so there is no
compatibility code: the new code reads keys only.

For each old name it knows the key of the line that name became. The table's builder (§10) writes
that list, old name beside key, into `scripts/exercise_name_migration.tsv`.

What it rewrites:

1. `exercise_sets.exercise`. A set that carries a `garmin_name` and was named by Garmin or the
   watch takes the key of the class holding that Garmin name, which is exact where a line was
   split. Any other set takes the key its old name maps to.
2. `prescribed_sets.exercise`, by the old name.
3. The `n` of every entry in `gym_logs.payload`.
4. The payloads of the queue items still waiting (§5).

It leaves `workouts.description` alone, and it prints every name it could not map, which is a
set stored under a Garmin name the old table lacked.

**The athlete's own answers.** Where the athlete named sets with a word the table gave another
meaning, only the athlete knows what was lifted. The script takes renames on the command line,
`--rename "back squat=SQUAT/BARBELL_BACK_SQUAT"`, and a rename wins over everything else for the
sets and prescribed sets stored under that word. The main athlete answered on 2026-10-03:

| Stored under | Lifted | Key |
|---|---|---|
| `back squat` | Barbell back squat | `SQUAT/BARBELL_BACK_SQUAT` |
| `chest press` | Machine chest press | `BENCH_PRESS/MACHINE_CHEST_PRESS` |
| `glute bridge` | Hip thrust machine | `HIP_RAISE/HIP_THRUST_MACHINE` |
| `chest fly` | Cable crossover | `FLYE/CABLE_CROSSOVER` |
| `hamstring curls` | Leg curl machine | `LEG_CURL/LEG_CURL` |
| `ab twist` | Russian twists | `CORE/RUSSIAN_TWIST` |
| `wheel` | Ab wheel rollout | `CORE/KNEELING_AB_WHEEL` |

The companion athlete's names need none.

**The steps for the operator**, in order:

1. Push main, so the page is deployed with the new payload.
2. Stop both bots.
3. Back up both databases, then run the script once per instance, the main one with the seven
   renames.
4. Run `sm workout generate --strength-only` once per instance. It writes the upcoming strength
   sessions again, so their descriptions and the calendar hold the new words.
5. Start the bots.

Not handled:

- A description written before the conversion keeps its old words for good. That matters only
  for past sessions.
- A proposal waiting in the queue keeps its preview text.
- New code started on a database that was not converted reads every old name as an exercise it
  does not know. Nothing is lost, and the script can still be run then.

## 10. Building the table

`scripts/build_exercise_table.py` writes the new `exercises.tsv` and the migration list once. It
reads today's table, Garmin Connect's catalog (`~/garmin_connect_exercises.json`, a copy of
`connect.garmin.com/web-data/exercises/Exercises.json`), Garmin's own gear lists
(`~/garmin_exercises.tsv`) and the review (`~/garmin_gear_review.tsv`), each given as an argument.
Those three files stay outside the repository: the table is the record, and after this build it is
edited by hand, as today.

## 11. The order of the work

**Step 1: the table and what is stored.** The table in its new shape, with its muscles and gear.
The vocabulary module reads it and gives, for a key, the class, pattern, muscles, gear, photos and
words, and for any Garmin name its key. Everything that stores, compares or validates a name works
on keys, and everything that prints one prints its words (§4). The page's two payloads and its
catalog carry keys (§8). The conversion script and the builder. The tests' fixtures move to keys.

**Step 2: what is offered.** The strength planner's list of every class with muscles and gear, its
answer in keys and the dumbbell and kettlebell rule; the naming question; the terminal's exercise
listing showing muscles and gear (§7).

Tests that read the table check four things: a Garmin name is on one line only, a `~` name is a
Garmin name of the table, every gear word is one of the 46, and no two classes show the same
words.

When the code lands, `docs/ARCHITECTURE.md` is updated, and the passages of
DESIGN_strength_tracking.md (§4, §11.1) and DESIGN_gym_logger.md (§2 to §4) that describe the old
table are replaced by a pointer here.

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
- **The words of §4 land in step 1**, not with the rest of what the athlete sees, because a key
  cannot be stored before something can show it.
- **The `+` is not stored.** If Garmin later adds the same name, the line drops its mark and
  nothing stored changes.
