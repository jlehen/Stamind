# Strength combos: several movements chained into one set

Status: designed 2026-10-18, red-teamed and reviewed the same day, amended 2026-10-19 after a
mock-up of the page (D20, D21), built 2026-10-19. Amends DESIGN_strength_tracking.md §4, §8 and §9,
DESIGN_exercise_table.md §4, §8 and §9, and DESIGN_gym_logger.md §1, §3 and §4. The interview
that produced it, the red-team pass on its decisions, the two review passes and every choice made
on the author's behalf are in §8 and the Decisions Log. When the strength planner swaps one chain
for another on a schedule is the matter of DESIGN_strength_rotation.md, not of this design (§7).

## 1. The problem

A **combo**, called a **chain** below, is several movements done back to back with one implement
and no rest between them. A kettlebell clean, then a front squat, then a press, is one round. Five
rounds without putting the bell down is one set. The bell is the same for all three movements, so
the load is what the weakest of them can carry, usually the press.

Today a strength session is a flat list of rows, one exercise per row, each with its sets, its rep
range and its kilograms (`prescribed_sets`, DESIGN_strength_tracking.md §9). The strength planner,
the model call that writes those rows, cannot write a chain. It can write three rows and say "do
these three as a chain" in the notes, and then everything downstream reads three exercises. The gym
logger page draws three cards and asks for three ticks per round. The strength history, the text
the strength planner reads before writing the next session, records a clean, a squat and a press,
each at the press's load. The planned-against-done table counts three lines. The companion
athlete's circuits hold a "single-arm clean and press" only because Garmin happens to have a name
for that pair. A clean, a squat and a press has no name, and neither do the hundreds of other
chains one bell allows.

The reason to want chains is variety. The exercise table holds about 1,500 classes of exercise, and
a chain is any two or more of them that flow into each other with one implement. Each chain is a new
shape for a session without a new line in the table.

## 2. The shape, as one week

It is Wednesday 22 October. The companion athlete has one 8 kg kettlebell at home and 15 minutes.
The week planner wrote the brief: "[One-bell flow] Full body, 15 min, light before Thursday's run."
The strength planner writes the session, and the athlete reads it as:

```
Hip raise: kettlebell swing 2×12 @ 8 kg
One arm swing → single arm dumbbell clean → goblet squat 3×5–8/side @ 8 kg
Hip stability: dead bug 3×8/side
```

The second line is a chain. In the data it is one row of `prescribed_sets`, whose exercise is the
three keys joined with `>`:
`HIP_SWING/ONE_ARM_SWING>OLYMPIC_LIFT/SINGLE_ARM_DUMBBELL_CLEAN>SQUAT/GOBLET_SQUAT`, 3 sets, reps
5 to 8, 8 kg. Reps are rounds: one swing, one clean, one squat is a round, and a set is five to
eight rounds. The chain is done one side at a time because the swing and the clean are, so the reps
are per side and a set is both sides, as for any one-sided exercise (§3). The range of rounds is
chosen once and kept, the way the rep range of any exercise is (`strength/progression.md`).

At 18:00 she opens the gym logger page from the morning's button. The chain is one card, its title
opening with the chain mark ⛓ and then "One arm swing → Single arm dumbbell clean → Goblet squat",
each name a small rounded chip, with "3×5–8/side @ 8 kg" under it and three set boxes. She does
five rounds, ticks the set, then six and six. She also has an idea: a swing straight into a halo.
She taps "+ Add an exercise" and picks the kettlebell swing, as today. The new card's title is one
chip, "[Hip raise] Kettlebell swing". She taps it, and a box opens around it holding three
buttons: Replace, Remove, Insert after. She taps Insert after; the search opens as "Insert in
chain after [Hip raise] Kettlebell swing", she picks the kettlebell halo, and the card now reads
"⛓ Kettlebell swing → Kettlebell halo", marked added, with the three sets it had, eight at 20 kg,
its reps box now saying "/side". She sets 8 kg, does three sets of eight rounds a side, ticking
each, and taps Finish.

The log reaches the bot. Each card is an entry whose `n` is its key, the chain's joined key
included, and each set is rounds, kilograms and seconds, as any set. The ingest stores the sets
under the joined key, the way it stores any key. Thursday morning the pull hands them to Garmin's
activity for Wednesday, as it does every log.

Two weeks later, Wednesday 5 November, the strength planner writes her next one-bell day. The
strength history shows it the chain as an exercise of its own, headed by its key, with "/side" on
every line of reps as for any one-sided exercise:

```
HIP_SWING/ONE_ARM_SWING>OLYMPIC_LIFT/SINGLE_ARM_DUMBBELL_CLEAN>SQUAT/GOBLET_SQUAT
  Wed Oct 22, prescribed 3×5–8/side @ 8: 1×5/side @ 8, 2×6/side @ 8 | RPE 4
HIP_RAISE/KETTLEBELL_SWING>SHOULDER_STABILITY/KETTLEBELL_HALO
  Wed Oct 22: 3×8/side @ 8 | RPE 4
```

The strength planner progresses the chain the way it progresses one exercise under HOW TO
PROGRESS: the range stays 5 to 8, she adds rounds inside it, and the load moves up a step the day
every set reaches 8 and a heavier bell is on her equipment list. With one bell the load holds, as
a one-bell goblet squat holds today. The swing-and-halo chain she invented carries the "(not
prescribed)" mark on Wednesday's line under SESSIONS AS DONE, the part of the history that shows
each session whole. If she keeps doing it, it becomes a habit and the strength planner writes it
in, under the habit rule of DESIGN_strength_tracking.md §9, which does not change. The one-arm
swing's own entry in the history does not mention Wednesday: a set of the chain teaches the
strength planner about the chain, not about the swing (§5).

## 3. A chain in the data

**The key.** A chain's key is the keys of its movements, in the order they are done, joined with
`>`: `A>B>C`. The sign reads as an order, which a chain is. No key of the exercise table holds a
`>`, so a stored key holding one is a chain and nothing else. The joiner is not `+`, because the
strength history already prints two exercises the athlete alternated as "A + B" and its heading
says so (DESIGN_strength_tracking.md §8); a chain written with the same sign would read as two
exercises taken in turns, and a pair taken in turns could come back as a chain (D9). Order matters:
a clean then a squat is not a squat then a clean, so they are two chains with two histories. A
chain holds two or more movements. There is no cap (D20): the science says what a usual one holds
(§4), and a long one costs only what §7 lists.

Nothing new is stored anywhere. `prescribed_sets.exercise` and `exercise_sets.exercise` are text
and hold the joined key as they hold any key. The exercise table does not list chains: a chain is
composed, not looked up. There is no schema change. One script learns about chains: when two
table lines are merged, `scripts/migrate_exercise_names.py` renames the stored keys that stopped
being keys (DESIGN_exercise_table.md §3.2, §9), and it renames them inside a chain key too, so the
chain keeps one history under its new key (D12).

**Reps are rounds.** One round is one rep of each movement. A row's `reps_low` and `reps_high`
count rounds, so "3×5–8" is three sets of five to eight rounds. A round with two squats and one
press cannot be written (§7).

**One load.** `load_kg` is the one implement the chain is done with. A chain of bodyweight
movements has none.

**Words.** A person reads a chain as its movements' words with their categories left out, joined
with " → ": the key above reads "one arm swing → single arm dumbbell clean → goblet squat". Each
movement gives the words after its category, or all of them when it has none, which is what the
page's `nameAfterCategory` already does. The category is the first half of a key's words, "squat:
goblet squat", and three categories in one line would say nothing a reader wants. A movement
keeps its category when its bare name belongs to more than one class of the table (D23): a chain
holding the cable face pull reads "row: face pull → …", because the band one is a face pull too.
The table holds 37 such names. The set of shared names is read from the table once, in Python
and on the page alike.

**Per side.** A chain is done one side at a time when any of its movements is. Its reps are then
per side and a set is both sides, printed "3×5/side", exactly as DESIGN_strength_tracking.md §4
says of a one-sided exercise. Whether the athlete does all rounds on the left before the right or
switches every round is theirs to choose; the notes say which.

**Tags.** A chain has none. `model_line`, which prints a key with its pattern, muscles and gear
in brackets for the strength planner, prints a chain's key alone, as it prints any key the table
lacks. Its reps carry "/side" wherever they are printed, and each movement's gear is in EXERCISES
STAMIND KNOWS. In the planned-against-done table and in the comparison a chain is one line like
any exercise, keyed by the joined key.

**Progression.** HOW TO PROGRESS applies to a chain as to one exercise: a range of rounds chosen
once and kept, more rounds inside it, then more load. The science says so (§4).

**What reads a key.** Today every reader that asks the exercise table about a key treats an
unknown key as "the key alone": `vocabulary.model_line` prints the bare key, `side_mark` prints
nothing, `implausible` is false, `get` is None. The change is one helper, `vocabulary.parts(key)`,
the list of part keys, one for a plain key, and the readers that need the parts: `words`,
`side_mark`, the strength planner's check (§4), the log's check (§6) and the merge script.
Everything else keys on the string and does not care that it holds a `>`. `strength log` already
matches a typed name against a key's words, so once `words` gives a chain its movements' names,
"goblet squat" lists the goblet squat and every chain holding it with no change to the command.

## 4. The strength planner

**What it may write.** A chain is allowed wherever a plain exercise is, under the rules that
already hold: the comparable session as done, the brief, the day's equipment and HOW TO PROGRESS.
The prompt does not push the strength planner toward chains. A session copied from a comparable
one keeps the plain exercises that one had, and a chain enters a session the way any exercise
does: the brief asks for a flow, the preferences name one, the athlete made a habit of one, or a
new session with no history is written from the brief, the equipment and the guidelines alone.
One paragraph joins CHOOSING THE EXERCISES in `planner_prompt.py`:

> A chain is two or more exercises done back to back with one implement and no rest between them.
> Write a chain as one exercise whose key is its movements' keys joined with >, in the order they
> are done. Its reps are rounds, one of each movement a round, in a range kept from one session to
> the next like any rep range. A chain holding a movement marked per side is per side as a whole:
> its rounds are per side and a set is both sides, as One side at a time in HOW TO PROGRESS says.
> Every movement must be in EXERCISES STAMIND KNOWS, and all of them must share one implement;
> dumbbells and kettlebells count as one, and a bodyweight movement fits any. In the notes, name a
> chain in words and say how its sides are done.

Three older sentences of the prompt and the science would otherwise say the opposite, and each is
amended in the same change (D14): "Use only exercises from EXERCISES STAMIND KNOWS" gains "or a
chain of them"; the response format's "(the key, exactly as EXERCISES STAMIND KNOWS spells it)"
gains "or a chain of keys joined with >"; and the sentence of `progression.md` that writes an
exercise with no movement pattern at what the athlete last did gains "except a chain, which
progresses (A chain)". The response format changes by that one phrase and nothing else: a chain is
a string in `exercise`.

**The science.** `strength/progression.md` gets a section, "A chain": one implement held the whole
time; usually three or four movements; each movement ends where the next starts, so a swing ends
at the hip where a clean starts, and a clean ends in the rack where a squat and a press start; the
load is the weakest movement's, so a chain on record is an exercise of its own and its load says
nothing about any movement's own load; a chain progresses as one exercise, rounds then load, and
is not a way to progress its movements. The range of rounds is the strength planner's to choose
from the brief and the duration, as any rep range is. This is the model's taste guided, not a list
of allowed chains (D3).

**The check.** `_clean_exercise` in `planner_prompt.py` splits the returned name on `>`, strips
the spaces around each part, resolves each part with `vocabulary.key_of`, so a Garmin name of the
table that is not a key is taken as its class's key as today, and joins the keys back. A chain
passes when it has two or more parts, every part is known, and the parts share an implement: among
the parts whose gear holds a load word (`vocabulary.LOADS`), those words have one in common, with
Dumbbells and Kettlebells read as one; a chain whose parts hold no load word at all, bodyweight
through and through, passes. A chain that fails the gear test still passes when its resolved
joined key is on the athlete's record, among the exercises a person has named in her stored sets
(`sets.own_exercises`), which `_clean_exercise` reads only then; the page composes a chain from
the same keys, so the two spellings meet. What she did is the proof, and the gear test guards the
chains the strength planner invents (D10). A chain that fails is dropped from the
session as an unknown name is today, and the one preview line is reworded so it is true for both:
"'{name}' is not an exercise Stamind knows or a chain it accepts, left out".

**The list.** EXERCISES STAMIND KNOWS lists the table's classes and no chain: there is nothing to
list. The history shows the chains the athlete has done (§5), and the comparable session as done
shows the ones written for them.

## 5. The history and the comparison

The strength history groups the stored sets by their exercise string, so a chain is an entry of its
own, headed by its joined key, with its days under it. The "(not prescribed)" and NOT DONE lines
are keyed by exercise too: a chain prescribed and not done is a NOT DONE line, one done and not
prescribed is marked. The alternation reading, which finds exercises whose sets interleave, sees a
chain as one exercise, and its " + " keeps its meaning (§3). `history.py` changes nowhere.

Nothing lands in the movements' own entries (D4). The load of a chain is the weakest movement's,
so an 8 kg clean done inside a chain says nothing about what the athlete cleans alone, and a
history that showed it would mislead the strength planner on the clean.

The planned-against-done table (`cli/common.py::strength_table`) and the comparison it is built
on (`strength/comparison.py`) match planned lines to done sets by key and print the words. A
chain is one planned line matched by its joined key. No change beyond `words`.

**The watch.** A chain reaches the record from the page only (D11). The watch names one exercise
per set, and no Garmin name resolves to a chain, so a set read from Garmin never lands on a chain
by itself. An athlete who trains with the watch alone cannot record a prescribed chain, and loses
it from her sessions after two such weeks (§7).

## 6. The page

**Drawing a chain.** A chain is one card like any card. Every card's title is chips. A plain
exercise's title is one chip that reads as its card reads today, "[Squat] Goblet squat", category
and all. A chain's title opens with the chain mark ⛓ and holds one chip per movement, each the
words after the category as a chain's words are everywhere (§3), with " → " between them; a
movement whose bare name is shared keeps its brackets, "[Row] Face pull" (D23).
`wordsOf` splits the key on `>` for the chips and for every other place the words are printed.
`perSideOf` is true when any part is, so the reps boxes say "/side" as for any one-sided
exercise. `photosOf` shows the first movement's photos. `patternOf` is already null for any key
the catalog lacks, a chain's included, so Swap on a chain card searches every exercise with no
pattern filter and needs no change. Swap, Del and Dup act on the whole card, as today.

**Building and changing a chain.** Nothing is added to the card's eight buttons and nothing to the
footer (D21). A tap on a chip opens a rounded box around that movement holding three buttons,
Replace, Remove and Insert after, so it is plain which movement they act on; a second tap on the
chip closes the box. Replace and Insert after open the search sheet titled after the chip as it
reads, "Replace [Squat] Goblet squat" or "Insert in chain after Goblet squat", the words "in
chain" telling it from the sheet the card's own Insert opens, which adds a card. Replace puts the
pick in that movement's place; its search keeps the replaced movement's pattern as its filter,
with the box that lifts it, as Swap's does. Remove drops the movement. Insert after puts the pick
after that movement; its search covers every exercise, as Insert's does. On a plain exercise,
Insert after is how a chain starts. Each edit works out the card's new key and hands it
to `swapExercise`, recorded on the card as Swap is: the sets stay, ticked or not, with their reps
and kilograms; the written load leaves the card's line, as after a swap; and the card's ↶ takes
the edit back. On a one-chip title, Replace does what Swap does and Remove does what Del does,
in Del's colour, and only the header's Undo brings a removed card back. The page checks nothing
about the gear (D7): she is holding it, and a chain she has done passes the strength planner's
check from then on (D10). Every edit gives the card a new key, so an edited chain is a new chain
for the record and the strength planner, as a swapped exercise is today. The chips, the box with
its three buttons and the ⛓ mark are the only new markup, the three buttons being pills of the
page's tap size; the search, the results and the pattern toggle are the ones Swap and Add use.

**The log.** `n` carries the joined key, and each set is rounds, kilograms and seconds as today.
`parse_log` in `strength/logger.py` checks each part of a key with `vocabulary.get`, so a chain of
known movements passes and a chain holding an unknown one is refused, as an unknown name is. The
payload version stays 2 (DESIGN_gym_logger.md §3): no field changes shape, and a key is still a
key.

**A past log opened from the calendar** shows a chain through the same `wordsOf`. Export to
Markdown prints the chain's shown words on its line.

**Order of going live.** Steps 1, 2a and 3 of the order below land as one branch, merged and
pushed in the same sitting, no bot restart (D19): a page older than the prompt shows a chain as
its raw key with no "/side", and an athlete who logs 5 rounds in total on it has 5 per side
stored.

## 7. Not handled

Each is a case a plausible athlete rarely meets, left out on purpose with the behaviour it gets.

- A round with unequal reps per movement, one clean then two squats then one press. The data holds
  rounds; the notes may say "two squats a round", and the page counts rounds.
- A chain done with the watch alone (D11). The record shows the chain as not done and the watch's
  one-exercise sets as not prescribed, at the chain's load. After two such weeks the habit rule
  writes those exercises in place of the chain. A chain she did before is among the naming
  question's answers like any recent exercise, and a watch set filed under it keeps the watch's
  rep count as rounds. Both athletes log from the page today.
- When a chain is rotated in or out is DESIGN_strength_rotation.md's matter (D5). As written
  there, nothing without a movement pattern rotates, a chain included.
- A chain's key is long, and nothing caps it (D20). Four keys joined run about 100 characters in
  the page's address, where a plain key runs about 25, so a session of many long chains meets the
  keyboard size limit of DESIGN_exercise_table.md §8 sooner, and a long title wraps over several
  lines of its card. The behaviour there is unchanged.
- The page offers no check that two picks flow into each other, and the strength planner's check
  reads gear only. Two different machines share the gear word "Machine" and pass it, and a chain
  the strength planner writes as "clean → press → clean" passes too. A chain the model composes
  badly is a chain the athlete reads before lifting and swaps.
- Chaining a card with ticked sets makes those sets rounds of the chain, as a swap renames them.
  To keep them as they were, Dup the card and chain the copy.
- A chain holding one two-handed movement and one per-side movement is per side as a whole (§3):
  "kettlebell swing → kettlebell halo" at 8 rounds a side is 16 swings a set. The notes say how
  the sides are done, and the athlete who means 8 swings logs 4 a side.

## 8. Choices made without you

D12 to D19 of the Decisions Log are the author's resolutions of red-team findings, not rulings;
rule on each there. The choices below have no row of their own. Each is one line to object to.

1. Order matters: `A>B` and `B>A` are two chains with two histories (§3).
2. The prompt does not push the strength planner toward chains: a chain is allowed wherever a plain
   exercise is, under today's rules, and enters a session the way any exercise does. The week
   planner is not told about chains; a brief that says "a one-bell flow" is prose the strength
   planner reads, as any brief is (§4).
3. The notes name a chain in words and say how the sides are done (§4).
4. Inside the page shape you chose (D21): a plain exercise's one chip keeps its category in
   brackets while a chain's chips drop theirs unless the bare name is shared (D23); the chain's
   search sheet is titled "Insert in chain after …", so it is not confused with the sheet the
   card's own Insert opens, which adds a card; Replace and Remove on a one-chip title are Swap
   and Del; photos are the first movement's (§6). The rest of §6 follows from reusing Swap and
   Insert and is not a choice.
5. The strength planner's list does not list chains; the history does (§4). Both pragmatic
   reviews say this follows from D3 and is not a choice.
6. The payload version stays 2 (§6). Both pragmatic reviews call this a fact, not a choice.
7. No interview state file is written under `designs/`: the one written for the cycle
   retrospective was a stray. Both pragmatic reviews say this is about a file the design does not
   write.
8. The gear test for a chain the strength planner invents: the load words of each movement's
   gear must have one in common, Dumbbells and Kettlebells read as one, a movement with no load
   word skipped, a chain with none passes; machines and bands pass as any load word; no rule
   against a repeated movement (§4). The pragmatic review cut the no-repeat rule.
9. The science paragraph lives in `progression.md`, not in a file of its own (§4).

## 9. Where the code goes

- `strength/vocabulary.py`: `CHAIN_JOINER`, the `>`; `parts(key)`, `shared_load(parts)` for the
  check; `shared_names()`, the bare names that belong to more than one class, read from the
  table once; `words` and `side_mark` read the parts.
- `strength/logger.py`: `parse_log` checks the parts.
- `strength/planner_prompt.py`: the paragraph in CHOOSING THE EXERCISES and the two amended
  sentences; `_clean_exercise` resolves and checks a chain, reading `sets.own_exercises` on a
  gear failure; the one preview line reworded, with the copy DESIGN_strength_tracking.md §9
  quotes and the test that pins it.
- `strength/progression.md`: the section "A chain" and the amended no-pattern sentence.
- `miniapp/logic.js`: `wordsOf`, `perSideOf`, `photosOf` read the parts, and `chipsOf` gives
  the chips their names, one per part, which `wordsOf` joins, keeping the brackets on a shared
  name from a set built from the catalog once; `replacePart`, `removePart` and
  `chainAfter`, pure functions from a key and a pick to the new key, handed to `swapExercise`.
  `miniapp/app.js`: the chips and the ⛓ mark in the card head, the three buttons
  under a tapped chip, the two search modes. `miniapp/style.css`: the chip, the mark and the row
  of three pills. `index.html` does not change. Tests in `miniapp/tests/logic.test.mjs`.
- `scripts/migrate_exercise_names.py`: renames inside a chain key.
- Docs: the recipe lines of `docs/ARCHITECTURE.md`; DESIGN_strength_tracking.md §4, §8, §9;
  DESIGN_exercise_table.md §4, §8, §9; DESIGN_gym_logger.md §1, §3, §4, each pointing here.
- No schema change, no migration to run now, no setting.

## Decisions Log

| ID | Topic | Decision | Rationale | Source | Date |
|---|---|---|---|---|---|
| D1 | Definition | A chain inside one set: one implement, no rest, several movements a round | Two exercises taken in turns already live in the notes and keep their own loads. Declined: alternated pairs as data; both shapes | Interview | 2026-10-18 |
| D2 | Data shape | One `prescribed_sets` row, the keys joined, reps are rounds | No new table or column; the row renders and logs like any. Declined: one row per movement sharing a group; a table line per chain | Interview | 2026-10-18 |
| D3 | Who composes | The strength planner composes; the science says what a good chain is; code checks known keys and shared gear | Most variety, the model's taste decides. Declined: a shipped list of chains; only chains written in preferences | Interview | 2026-10-18 |
| D4 | History | A chain is its own exercise in the history; nothing lands under its movements | The load is the weakest movement's, so it says nothing about the others. Declined: under both with a marker; under the movements only | Interview | 2026-10-18 |
| D5 | Variety | Handed to DESIGN_strength_rotation.md; the strength planner acts on what the brief asks, as for a requested exercise | A strength variability design is under way in the `strength-rotation` worktree. Declined here: new mesocycle (the author's recommendation); every session | Interview | 2026-10-18 |
| D6 | Page | The athlete builds a chain from the search | She can invent a chain at the gym, and a repeated one becomes a habit the strength planner writes. Declined: read and log only (the author's recommendation); swap one movement, which D21 later brought back as part of the chips | Interview | 2026-10-18 |
| D7 | Gear on the phone | No check on the page | She is holding the gear; the check guards the strength planner, which cannot see the gym. Declined: narrow the second pick; refuse and say why | Interview | 2026-10-18 |
| D8 | Process | Commit, red team on Opus, commit, two reviewers on Opus and Fable, commit | The author's process preference | Interview | 2026-10-18 |
| D9 | The joiner | `>`, not `+` | The history already prints alternated exercises as "A + B" and says so; a chain with the same sign reads as a pair taken in turns, and a pair as a chain (finding 1). Declined: alternation changes sign; both keep `+` told apart by spaces | Red Team | 2026-10-18 |
| D10 | Habit vs check | A chain on the athlete's record passes the strength planner's check whatever its gear or a repeated movement | What she did is the proof; the check guards invented chains (finding 3). Built as: `_clean_exercise` reads the record only on a gear failure, and the preview keeps one line, reworded to be true for a chain; the pragmatic review cut the "which ground failed" plumbing and the no-repeat rule, and the author agreed. Declined: the page refuses what the check refuses; leave it with a true message | Red Team | 2026-10-18 |
| D11 | The watch | A chain is recorded from the page only; a watch-only athlete loses a prescribed chain after two weeks, listed in §7 | Both athletes log from the page; a chain offered by the naming question would store the watch's reps as rounds (finding 5). Declined: the naming question offers the day's chain; the naming question never offers a chain | Red Team | 2026-10-18 |
| D12 | Merges | The merge script renames the parts of a chain key | Else a merge splits a chain's history and an old page's log is refused (finding 4); author's resolution | Red Team | 2026-10-18 |
| D13 | Progression | A range of rounds kept like a rep range; the load holds at the top when no heavier implement exists; the range is the strength planner's to choose, no number in the science | The §2 story had raised the rounds, which `progression.md` forbids (finding 2); author's resolution; the pragmatic review cut the "three to eight" the author had written | Red Team | 2026-10-18 |
| D14 | Older sentences | Three sentences that said the opposite are amended in the same change | A prompt must not contradict itself (finding 6); author's resolution; the thorough review added the per-side hint and the pragmatic review cut it and the "a key is a category…" amendment as second homes of rules the paragraph already states | Red Team | 2026-10-18 |
| D15 | Tags | A chain has none; `model_line` prints its key alone | The author had written the union of the movements' gear; the pragmatic review showed that "every item of the gear is needed" would then tell the strength planner a one-bell home lacks the gear for its own chain (finding 7, review); author's resolution | Red Team | 2026-10-18 |
| D16 | Per side | Choice 4 of the first version stands: per side when any movement is; the §2 example is corrected and the two-handed oddity listed in §7; the prompt says so in one sentence | A rule that fits single-arm complexes (finding 8); the model's rounds must mean what the page prints (thorough review finding 1); author's resolution | Red Team | 2026-10-18 |
| D17 | Alike words | Accepted at first; the stored key tells chains apart. Reversed by D23 | Brackets for 37 ambiguous names would cost more than they give (finding 9); author's resolution, overruled on 2026-10-19 | Red Team | 2026-10-18 |
| D18 | `strength log` and `strength name` | No change to either; `similar` is left as it is | The substring match on words already finds a chain (finding 10); on a chain line `strength name` offers the first movement's category, which nobody meets in a normal week, so the guard the author had written was cut by the pragmatic review; author's resolution | Red Team | 2026-10-18 |
| D19 | Going live | Steps 1, 2a and 3 land as one branch, merged and pushed in the same sitting; no bot restart; the chips follow as a branch of their own | The prompt is live at the merge, the page at the push, and a page in between stores rounds as per side (finding 11); author's resolution, collapsed to one line by the pragmatic review | Red Team | 2026-10-18 |
| D20 | No cap | A chain holds two or more movements; no cap in the check or on the page; the science says usually three or four | Nothing technical needs a number: the key is text, the page composes what she taps, and a session full of long chains is already listed under not handled. The author had written two to four. Declined: a generous cap of six | Interview | 2026-10-19 |
| D21 | The page | Every title is chips, one per movement, a chain marked ⛓; a tap on a chip opens a box around that movement holding Replace, Remove and Insert after; no new card button, no footer button, no Done | Chosen from a mock-up of three shapes: the sheet with a second footer button (the design as reviewed), a ninth "Chain" button on each card (the pragmatic review's proposal), and the chips. The chain is edited where the chain is, and a chain starts from a plain exercise. The box and the name "Insert after" are the user's, after seeing both drawn; the thorough review's "Chain after" was declined, the sheet title "Insert in chain after …" keeping the two Inserts apart. Declined: the sheet; the pill | Interview | 2026-10-19 |
| D22 | Ticked sets | A card edited by its chips keeps its sets, ticked or not, as a swapped card does; the written load leaves its line | The user wants to be able to tweak what was done, even after the fact. Declined: a card with ticked sets is left alone and a copy is chained | Interview | 2026-10-19 |
| D23 | Shared names | In a chain's words, a movement whose bare name belongs to more than one class keeps its category; the rest drop it | On the screen a bare "Face pull" cannot be told from the band one, though the stored key can. Declined: the category on every chip; the full name only when the chip is tapped; accepting it (D17) | Interview | 2026-10-19 |

## Dependency Graph & Implementation Order

```
vocabulary.parts + parse_log (1) ──> page readers (2a) ──> strength planner (3) ──> chips (2b)
                                                                       └──> merge script (4)
```

1. **The vocabulary and the log** (`vocabulary.py`, `logger.py`): `parts`, `shared_load`, and
   `words` and `side_mark` reading the parts; `parse_log` accepts a chain of known parts. Tests by
   shape in the vocabulary tests, a plain key being one part that reads as today, and one test on
   the log. Nothing writes a chain yet, and every reader is ready for one.
2a. **The page's readers** (`logic.js`): `wordsOf`, `chipsOf`, `perSideOf` and `photosOf`
   reading the parts. Node tests for `wordsOf` and `perSideOf` on a chain. They land with steps 1
   and 3 as one branch (D19). From here a chain the strength planner wrote is drawn and logged
   right.
2b. **The chips** (`logic.js`, `app.js`, `style.css`): the tappable title and the ⛓ mark, the
   three buttons under a tapped chip, the two search modes, the three key edits with three
   asserts. A branch of its own after the first, with no prompt change in it, so a bug in the
   chips cannot be confused with one in the strength planner. From here the athlete can build
   and change a chain.
3. **The strength planner** (`planner_prompt.py`, `progression.md`): the paragraph, the amended
   sentences, the section, the check, with tests on the §2 chain (passes: Kettlebells and
   Dumbbells read as one), a barbell clean into a kettlebell swing (dropped), a bodyweight chain
   (passes), a dropped chain that is on record (passes), and the reworded preview line in
   `tests/test_strength_planner.py`. From here the strength planner writes chains. Steps 1, 2a
   and 3 land as one branch, merged and pushed in the same sitting (D19).
4. **The merge script** (`scripts/migrate_exercise_names.py`): renames inside a chain key. Needed
   before the next table merge, not before the feature.
5. **Docs.**

## Checklist

- [x] `vocabulary.py`: `CHAIN_JOINER`, `parts`, `shared_load`, `shared_names`; `words`,
      `side_mark`
- [x] `logger.py`: `parse_log` on a chain
- [x] `miniapp/logic.js`: the readers, `chipsOf`; node tests (branch one)
- [x] `miniapp/logic.js`, `app.js`, `style.css`: chips and the ⛓ mark, the three buttons under a
      tapped chip, the two search modes, the three key edits; node tests (branch two)
- [x] `planner_prompt.py`: the paragraph, the two amended sentences, `_clean_exercise` on a
      chain and its tests, the preview line and its two tests
- [x] `progression.md`: "A chain", the amended no-pattern sentence
- [x] `scripts/migrate_exercise_names.py`: parts of a chain key
- [x] `docs/ARCHITECTURE.md`, the three amended designs
