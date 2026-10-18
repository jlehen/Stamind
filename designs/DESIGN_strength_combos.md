# Strength combos: several movements chained into one set

Status: designed 2026-10-18, not built. Amends DESIGN_strength_tracking.md §4, §8 and §9,
DESIGN_exercise_table.md §4 and §8, and DESIGN_gym_logger.md §1, §3 and §4. The interview that
produced it and every choice made on the author's behalf are in §8 and the Decisions Log. When
the strength planner swaps one chain for another on a schedule is the matter of
DESIGN_strength_rotation.md, not of this design (§7).

## 1. The problem

A **combo**, called a **chain** below, is several movements done back to back with one implement
and no rest between them. A kettlebell clean, then a front squat, then a press, is one round. Five
rounds without putting the bell down is one set. The bell is the same for all three movements, so
the load is what the weakest of them can carry, usually the press.

Today a strength session is a flat list of rows, one exercise per row, each with its sets, its rep
range and its kilograms (`prescribed_sets`, DESIGN_strength_tracking.md §9). The strength planner,
the model call that writes those rows, cannot write a chain. It can write three rows and say "do
these three as a chain" in the notes, and then everything downstream reads three exercises. The gym
logger page draws three cards and asks for three ticks per round. The strength history, the text the
planner reads before writing the next session, records a clean, a squat and a press, each at the
press's load. The planned-against-done table counts three lines. The companion athlete's circuits
hold a "single-arm clean and press" only because Garmin happens to have a name for that pair. A
clean, a squat and a press has no name, and neither do the hundreds of other chains one bell allows.

The reason to want chains is variety. The exercise table holds about 1,500 classes of exercise, and
a chain is any two to four of them that flow into each other with one implement. Each chain is a new
shape for a session without a new line in the table.

## 2. The shape, as one week

It is Wednesday 22 October. The companion athlete has one 8 kg kettlebell at home and 15 minutes.
The week planner wrote the brief: "[One-bell flow] Full body, 15 min, light before Thursday's run."
The strength planner writes the session, and the athlete reads it as:

```
Kettlebell swing 2×12 @ 8 kg
One-arm swing → single-arm dumbbell clean → goblet squat 3×5/side @ 8 kg
Dead bug 3×8
```

The second line is a chain. In the data it is one row of `prescribed_sets`, whose exercise is the
three keys joined with `+`:
`HIP_SWING/ONE_ARM_SWING+OLYMPIC_LIFT/SINGLE_ARM_DUMBBELL_CLEAN+SQUAT/GOBLET_SQUAT`, 3 sets, reps
5 to 5, 8 kg. Reps are rounds: one swing, one clean, one squat is a round, and a set is five
rounds. The chain is done one side at a time because the swing and the clean are, so the reps are
per side and a set is both sides, as for any one-sided exercise (§3).

At 18:00 she opens the gym logger page from the morning's button. The chain is one card, headed
"One-arm swing → Single-arm dumbbell clean → Goblet squat", with "3×5/side @ 8 kg" under it and
three set boxes. She does the first set, finds five rounds easy, ticks it, and bumps the second set
to 6. She also has an idea: a swing straight into a halo. Under "+ Add an exercise" she taps
"+ Add a chain". The search opens; she picks the kettlebell swing, then the kettlebell halo, and
taps Done. A fourth card appears, "Kettlebell swing → Kettlebell halo", marked added, with three
sets she edits as she goes. She taps Finish.

The log reaches the bot. Each card is an entry whose `n` is its key, the chain's joined key
included, and each set is rounds, kilograms and seconds, as any set. The ingest stores the sets
under the joined key, the way it stores any key. Thursday morning the pull hands them to Garmin's
activity for Wednesday, as it does every log.

Two weeks later, Wednesday 5 November, the strength planner writes her next one-bell day. The
strength history shows it the chain as an exercise of its own, headed by its key and the tags a
chain has, which are its gear and whether it is per side:

```
HIP_SWING/ONE_ARM_SWING+OLYMPIC_LIFT/SINGLE_ARM_DUMBBELL_CLEAN+SQUAT/GOBLET_SQUAT (Kettlebells;
per side)
  Wed Oct 22: 3×5/side @ 8: 1×5/side @ 8, 2×6/side @ 8 | RPE 4
HIP_RAISE/KETTLEBELL_SWING+SHOULDER_STABILITY/KETTLEBELL_HALO (Kettlebells)
  Wed Oct 22: 3×8 @ 8 (not prescribed) | RPE 4
```

The planner progresses the chain the way it progresses one exercise under HOW TO PROGRESS: her
rounds reached 6, so it writes 3×6/side at 8 kg, and a heavier bell the day she has one. The
swing-and-halo chain she invented is a "(not prescribed)" line. If she keeps doing it, it becomes a
habit and the planner writes it in, under the habit rule of DESIGN_strength_tracking.md §9, which
does not change. The one-arm swing's own entry in the history does not mention Wednesday: a set of
the chain teaches the planner about the chain, not about the swing (§5).

## 3. A chain in the data

**The key.** A chain's key is the keys of its movements, in the order they are done, joined with
`+`: `A+B+C`. No key of the exercise table holds a `+`. The `+` at the start of a table line marks
an added exercise and is never stored (DESIGN_exercise_table.md §3.3), so a stored key holding a
`+` is a chain and nothing else. Order matters: a clean then a squat is not a squat then a clean,
so they are two chains with two histories. A chain holds two to four movements.

Nothing new is stored anywhere. `prescribed_sets.exercise` and `exercise_sets.exercise` are text
and hold the joined key as they hold any key. The exercise table does not list chains: a chain is
composed, not looked up. There is no schema change and no migration.

**Reps are rounds.** One round is one rep of each movement. A row's `reps_low` and `reps_high`
count rounds, so "3×5" is three sets of five rounds. A round with two squats and one press cannot be
written (§7).

**One load.** `load_kg` is the one implement the chain is done with. A chain of bodyweight
movements has none.

**Words.** A person reads a chain as its movements' words with their categories left out, joined
with " → ": the key above reads "one-arm swing → single-arm dumbbell clean → goblet squat". The
category is the first half of a key's words, "squat: goblet squat", and three categories in one
line would say nothing a reader wants. A movement that is a bare category, such as `PULL_UP`,
keeps its one word.

**Per side.** A chain is done one side at a time when any of its movements is. Its reps are then
per side and a set is both sides, printed "3×5/side", exactly as DESIGN_strength_tracking.md §4
says of a one-sided exercise. Whether the athlete does all rounds on the left before the right or
switches every round is theirs to choose; the notes may say which.

**Tags.** A chain has no movement pattern and no muscles of its own. Where the planner's list and
the history print a class's tags, a chain prints the gear its movements share and "per side" when it
is. In the planned-against-done table and in the comparison it is one line like any exercise, keyed
by the joined key.

**Progression.** HOW TO PROGRESS applies to a chain as to one exercise: more rounds inside the rep
range, then more load. The science says so in one paragraph (§4).

**What reads a key.** Today every reader that asks the exercise table about a key treats an
unknown key as "the key alone": `vocabulary.model_line` prints the bare key, `side_mark` prints
nothing, `implausible` is false, `get` is None. The change is one helper, `vocabulary.parts(key)`,
the list of part keys, one for a plain key, and the readers that need the parts: `words`,
`side_mark`, `model_line`, the planner's check (§4) and the log's check (§6). Everything else keys
on the string and does not care that it holds a `+`.

## 4. The strength planner

**What it may write.** A chain is allowed wherever a plain exercise is, under the rules that
already hold: the comparable session as done, the brief, the day's equipment and HOW TO PROGRESS.
The prompt does not push the planner toward chains. A session copied from a comparable one keeps
the plain exercises that one had, and a chain enters a session the way any exercise does: the brief
asks for a flow, the preferences name one, the athlete made a habit of one, or a new session with no
history is written from the brief, the equipment and the guidelines alone. One paragraph joins
CHOOSING THE EXERCISES in `planner_prompt.py`:

> A chain is two to four exercises done back to back with one implement and no rest between them:
> a clean, then a front squat, then a press, is one round, and a set is several rounds. Write a
> chain as one exercise whose key is its movements' keys joined with +, in the order they are
> done. Its reps are rounds. Its load is the one implement, so it is set by the weakest movement.
> Every movement must be in EXERCISES STAMIND KNOWS, and all of them must share one implement;
> dumbbells and kettlebells count as one, and a bodyweight movement fits any. A chain under
> SESSIONS AS DONE is an exercise of its own: progress it as one, and never take its load as any of
> its movements' own load. In the notes, name a chain in words and say how its sides are done.

**The science.** `strength/progression.md` gets a section, "A chain": one implement held the whole
time; each movement ends where the next starts, so a swing ends at the hip where a clean starts, and
a clean ends in the rack where a squat and a press start; the load is the weakest movement's; two to
four movements and three to six rounds a set; a chain progresses as one exercise, rounds then load,
and is not a way to progress its movements. This is the model's taste guided, not a list of allowed
chains (D3).

**The check.** `_clean_exercise` in `planner_prompt.py` splits the returned name on `+` and
resolves each part with `vocabulary.key_of`, so a Garmin name of the table that is not a key is
taken as its class's key, as today. A chain passes when it has two to four parts, every part is
known, no part repeats, and the parts share an implement: among each part's gear words, those that
are loads (`vocabulary.LOADS`) must have one in common, where Dumbbells and Kettlebells are read as
one word, and a part with no load word in its gear is skipped. A chain that fails is dropped from
the session with a line for the preview, as an unknown name is today. The response format does not
change: a chain is a string in `exercise`.

**The list.** EXERCISES STAMIND KNOWS lists the table's classes and no chain: there is nothing to
list. The history shows the chains the athlete has done (§5), and the comparable session as done
shows the ones written for them.

## 5. The history and the comparison

The strength history groups the stored sets by their exercise string, so a chain is an entry of its
own, headed by its joined key and its tags (§2), with its days under it. The "(not prescribed)" and
NOT DONE lines are keyed by exercise too: a chain prescribed and not done is a NOT DONE line, one
done and not prescribed is marked. The alternation reading, which finds exercises whose sets
interleave, sees a chain as one exercise. `history.py` changes nowhere; the tags come from
`model_line`.

Nothing lands in the movements' own entries (D4). The load of a chain is the weakest movement's,
so an 8 kg clean done inside a chain says nothing about what the athlete cleans alone, and a
history that showed it would mislead the planner on the clean.

The planned-against-done table (`cli/common.py::strength_table`) and the comparison it is built
on (`strength/comparison.py`) match planned lines to done sets by key and print the words. A
chain is one planned line matched by its joined key. No change beyond `words`.

`strength log` shows what is on record for one exercise, matched against what the athlete typed.
A chain must be found by the words of any of its movements, so "goblet squat" lists the goblet
squat and every chain holding it. `strength exercises` lists the table's classes and no chain.

## 6. The page

**Drawing a chain.** A chain is one card like any card. `wordsOf` splits the key on `+` and joins
each part's shown name, the one after the category, with " → ". `perSideOf` is true when any part
is. `photosOf` shows the first movement's photos. `patternOf` is null for a chain, so Swap on a
chain card searches every exercise with no pattern filter, and the chosen exercise replaces the
whole chain. Changing one movement of a chain on the page is not handled (§7).

**Adding a chain.** Under "+ Add an exercise" sits "+ Add a chain". It opens the same search sheet
in a chain mode. Each hit tapped is appended to a strip at the top of the sheet, "Kettlebell swing →
Kettlebell halo", and the input clears for the next pick. A tap on the strip removes its last name.
A Done button is enabled from the second pick and is the only move after the fourth. Done adds one
card with the joined key, bodyweight when every part is, with the sets an added exercise gets
today. The page checks nothing about the gear (D7): she is holding it. The strip and the Done
button are the only new markup; the search, the results and the pattern toggle are the ones Swap
and Add use.

**The log.** `n` carries the joined key, and each set is rounds, kilograms and seconds as today.
`parse_log` in `strength/logger.py` checks each part of a key with `vocabulary.get`, so a chain of
known movements passes and a chain holding an unknown one is refused, as an unknown name is. The
payload version stays 2 (DESIGN_gym_logger.md §3): no field changes shape, a key is still a key,
and a page from before this change that meets a chain shows the key as it is, `wordsOf`'s fallback,
and logs it unchanged.

**A past log opened from the calendar** shows a chain through the same `wordsOf`. Export to
Markdown prints the chain's shown words on its line.

## 7. Not handled

Each is a case a plausible athlete rarely meets, left out on purpose with the behaviour it gets.

- A round with unequal reps per movement, one clean then two squats then one press. The data holds
  rounds; the notes may say "two squats a round", and the page counts rounds.
- Changing one movement of a chain on the page. Swap replaces the chain whole; Add a chain makes a
  new one; Del removes the old.
- A set read from Garmin never lands on a chain: the watch names one exercise per set, and no Garmin
  name resolves to a joined key. The naming question offers the table's classes only, so a watch set
  cannot be named as a chain. An export to Garmin, not designed (DESIGN_exercise_table.md §12),
  would have to send each movement.
- The movements' own histories learn nothing from a chain (D4). An athlete who only ever cleans
  inside a chain has no clean entry.
- When a chain is swapped for another on a schedule, and whether a rotation may bring a chain in or
  take one out, is DESIGN_strength_rotation.md's matter (D5). As that design stands, an exercise
  with no movement pattern is never rotated, and a chain has none, so under it a chain is never
  rotated out and never brought in. That design decides whether to change that.
- The week planner is not told about chains. A brief that says "a one-bell flow" is prose the
  strength planner reads, as any brief is.
- A chain's key is long. Four keys joined run about 100 characters in the page's address, where a
  plain key runs about 25, so a session of many chains meets the keyboard size limit of
  DESIGN_exercise_table.md §8 sooner. The behaviour there is unchanged.
- The page offers no check that two picks flow into each other, and the planner's check reads gear
  only. A chain the model composes badly is a chain the athlete reads before lifting and swaps.

## 8. Choices made without you

Every choice below was made by the author of this design, not ruled in the interview. Each is one
line to object to.

1. `+` is the joiner, chosen because it reads as "swing + clean + squat" and no stored key holds it
   (§3).
2. Two to four movements (§3).
3. Order matters: `A+B` and `B+A` are two chains with two histories (§3).
4. Reps are rounds, one rep of each movement a round (§3).
5. A chain is per side when any movement is; reps per side, a set is both sides (§3).
6. A chain's words are its movements' names after their categories, joined with " → " (§3).
7. The gear check: the load words of each movement's gear must have one in common, Dumbbells and
   Kettlebells read as one, a movement with no load word skipped; no repeated movement (§4).
8. A chain's tags are gear and "per side" only, no pattern and no muscles (§3).
9. The planner's list does not list chains; the history does (§4).
10. The prompt does not push the planner toward chains: a chain is allowed wherever a plain
    exercise is, under today's rules, and enters a session the way any exercise does (§4).
11. The science paragraph lives in `progression.md`, not in a file of its own (§4).
12. The notes name a chain in words and say how the sides are done (§4).
13. On the page: the button sits under "+ Add an exercise"; Done is enabled from the second pick; a
    tap on the strip removes the last name; Insert has no chain mode, Move does the rest; Swap on a
    chain searches everything and replaces the chain whole; photos are the first movement's (§6).
14. An added chain gets the sets an added exercise gets today (§6).
15. The payload version stays 2 (§6).
16. `strength log` finds a chain by the words of any of its movements (§5).
17. No interview state file is written under `designs/`: the one written for the cycle
    retrospective was a stray.

## 9. Where the code goes

- `strength/vocabulary.py`: `CHAIN_MARK`, `parts(key)`, `shared_load(parts)` for the check;
  `words`, `side_mark` and `model_line` read the parts.
- `strength/planner_prompt.py`: the paragraph in CHOOSING THE EXERCISES; `_clean_exercise`
  resolves and checks a chain.
- `strength/progression.md`: the section "A chain".
- `strength/logger.py`: `parse_log` checks the parts.
- `cli/strength_log.py`: matching a typed name against a chain's movements.
- `miniapp/logic.js`: `wordsOf`, `perSideOf`, `photosOf`, `patternOf` read the parts; a chain
  key builder. `miniapp/app.js` and `miniapp/index.html`: the chain mode, the strip, Done.
  Tests in `miniapp/tests/logic.test.mjs`.
- Docs: the recipe lines of `docs/ARCHITECTURE.md`; DESIGN_strength_tracking.md §4, §8, §9;
  DESIGN_exercise_table.md §4, §8; DESIGN_gym_logger.md §1, §3, §4, each pointing here.
- No schema change, no migration, no setting.

## Decisions Log

| ID | Topic | Decision | Rationale | Source | Date |
|---|---|---|---|---|---|
| D1 | Definition | A chain inside one set: one implement, no rest, several movements a round | Two exercises taken in turns already live in the notes and keep their own loads. Declined: alternated pairs as data; both shapes | Interview | 2026-10-18 |
| D2 | Data shape | One `prescribed_sets` row, the keys joined with `+`, reps are rounds | No new table or column; the row renders and logs like any. Declined: one row per movement sharing a group; a table line per chain | Interview | 2026-10-18 |
| D3 | Who composes | The strength planner composes; the science says what a good chain is; code checks known keys and shared gear | Most variety, the model's taste decides. Declined: a shipped list of chains; only chains written in preferences | Interview | 2026-10-18 |
| D4 | History | A chain is its own exercise in the history; nothing lands under its movements | The load is the weakest movement's, so it says nothing about the others. Declined: under both with a marker; under the movements only | Interview | 2026-10-18 |
| D5 | Variety | Handed to DESIGN_strength_rotation.md; the strength planner acts on what the brief asks, as for a requested exercise | A strength variability design is under way in the `strength-rotation` worktree. Declined here: new mesocycle (the author's recommendation); every session | Interview | 2026-10-18 |
| D6 | Page | The athlete builds a chain from the search, two to four picks | She can invent a chain at the gym, and a repeated one becomes a habit the planner writes. Declined: read and log only (the author's recommendation); swap one movement | Interview | 2026-10-18 |
| D7 | Gear on the phone | No check on the page | She is holding the gear; the check guards the planner, which cannot see the gym. Declined: narrow the second pick; refuse and say why | Interview | 2026-10-18 |
| D8 | Process | Commit, red team on Opus, commit, two reviewers on Opus and Fable, commit | The author's process preference | Interview | 2026-10-18 |

## Dependency Graph & Implementation Order

```
vocabulary.parts (1) ──┬──> planner check, prompt, science (2)
                       ├──> logger.parse_log (3) ──> page: draw and add a chain (4)
                       └──> strength log matching (5)
```

1. **The vocabulary** (`vocabulary.py`): `parts`, `shared_load`, and `words`, `side_mark`,
   `model_line` reading the parts. Tests by shape in the vocabulary tests: a plain key is one
   part and reads as today. Nothing writes a chain yet, and every reader is ready for one.
2. **The planner** (`planner_prompt.py`, `progression.md`): the paragraph, the section, the
   check. From here the planner can write a chain, and the history shows it back. A page from
   before step 4 shows the key as it is and logs it unchanged, so steps 1 and 2 can live alone.
3. **The log** (`logger.py`): `parse_log` accepts a chain of known parts. One test.
4. **The page** (`logic.js`, `app.js`, `index.html`): the readers, the chain mode, the strip,
   Done. Node tests for `wordsOf`, `perSideOf` and the key builder; the deploy through GitHub
   Pages as for any page change.
5. **`strength log`** (`cli/strength_log.py`): a chain found by any movement's words.
6. **Docs**, then a bot restart on each instance so the planner's prompt is the new one.

## Checklist

- [ ] `vocabulary.py`: `CHAIN_MARK`, `parts`, `shared_load`; `words`, `side_mark`, `model_line`
- [ ] `planner_prompt.py`: CHOOSING THE EXERCISES paragraph; `_clean_exercise` on a chain
- [ ] `progression.md`: "A chain"
- [ ] `logger.py`: `parse_log` on a chain
- [ ] `miniapp/logic.js`, `app.js`, `index.html`: readers, chain mode, strip, Done; node tests
- [ ] `cli/strength_log.py`: match by any movement's words
- [ ] `docs/ARCHITECTURE.md`, the three amended designs
- [ ] Both bots restarted
