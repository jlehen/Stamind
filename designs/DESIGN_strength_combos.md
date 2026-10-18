# Strength combos: several movements chained into one set

Status: designed 2026-10-18, red-teamed the same day, not built. Amends
DESIGN_strength_tracking.md §4, §8 and §9, DESIGN_exercise_table.md §4, §8 and §9, and
DESIGN_gym_logger.md §1, §3 and §4. The interview that produced it, the red-team pass on its
decisions and every choice made on the author's behalf are in §8 and the Decisions Log. When the
strength planner swaps one chain for another on a schedule is the matter of
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
One-arm swing → single-arm dumbbell clean → goblet squat 3×5–8/side @ 8 kg
Dead bug 3×8
```

The second line is a chain. In the data it is one row of `prescribed_sets`, whose exercise is the
three keys joined with `>`:
`HIP_SWING/ONE_ARM_SWING>OLYMPIC_LIFT/SINGLE_ARM_DUMBBELL_CLEAN>SQUAT/GOBLET_SQUAT`, 3 sets, reps
5 to 8, 8 kg. Reps are rounds: one swing, one clean, one squat is a round, and a set is five to
eight rounds. The chain is done one side at a time because the swing and the clean are, so the reps
are per side and a set is both sides, as for any one-sided exercise (§3). The range of rounds is
chosen once and kept, the way the rep range of any exercise is (`strength/progression.md`).

At 18:00 she opens the gym logger page from the morning's button. The chain is one card, headed
"One-arm swing → Single-arm dumbbell clean → Goblet squat", with "3×5–8/side @ 8 kg" under it and
three set boxes. She does five rounds, ticks the set, then six and six. She also has an idea: a
swing straight into a halo. Under "+ Add an exercise" she taps "+ Add a chain". The search opens;
she picks the kettlebell swing, then the kettlebell halo, and taps Done. A fourth card appears,
"Kettlebell swing → Kettlebell halo", marked added, with three sets she edits as she goes. She taps
Finish.

The log reaches the bot. Each card is an entry whose `n` is its key, the chain's joined key
included, and each set is rounds, kilograms and seconds, as any set. The ingest stores the sets
under the joined key, the way it stores any key. Thursday morning the pull hands them to Garmin's
activity for Wednesday, as it does every log.

Two weeks later, Wednesday 5 November, the strength planner writes her next one-bell day. The
strength history shows it the chain as an exercise of its own, headed by its key and the tags a
chain has, which are the gear its movements need and whether it is per side:

```
HIP_SWING/ONE_ARM_SWING>OLYMPIC_LIFT/SINGLE_ARM_DUMBBELL_CLEAN>SQUAT/GOBLET_SQUAT (Kettlebells,
Dumbbells; per side)
  Wed Oct 22: 3×5–8/side @ 8: 1×5/side @ 8, 2×6/side @ 8 | RPE 4
HIP_RAISE/KETTLEBELL_SWING>SHOULDER_STABILITY/KETTLEBELL_HALO (Kettlebells; per side)
  Wed Oct 22: 3×8/side @ 8 (not prescribed) | RPE 4
```

The planner progresses the chain the way it progresses one exercise under HOW TO PROGRESS: the
range stays 5 to 8, she adds rounds inside it, and the load moves up a step the day every set
reaches 8 and a heavier bell is on her equipment list. With one bell the load holds, as a one-bell
goblet squat holds today. The swing-and-halo chain she invented is a "(not prescribed)" line. If
she keeps doing it, it becomes a habit and the planner writes it in, under the habit rule of
DESIGN_strength_tracking.md §9, which does not change. The one-arm swing's own entry in the
history does not mention Wednesday: a set of the chain teaches the planner about the chain, not
about the swing (§5).

## 3. A chain in the data

**The key.** A chain's key is the keys of its movements, in the order they are done, joined with
`>`: `A>B>C`. The sign reads as an order, which a chain is. No key of the exercise table holds a
`>`, so a stored key holding one is a chain and nothing else. The joiner is not `+`, because the
strength history already prints two exercises the athlete alternated as "A + B" and its heading
says so (DESIGN_strength_tracking.md §8); a chain written with the same sign would read as two
exercises taken in turns, and a pair taken in turns could come back as a chain (D9). Order matters:
a clean then a squat is not a squat then a clean, so they are two chains with two histories. A
chain holds two to four movements.

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
with " → ": the key above reads "one-arm swing → single-arm dumbbell clean → goblet squat". The
category is the first half of a key's words, "squat: goblet squat", and three categories in one
line would say nothing a reader wants. A movement that is a bare category, such as `PULL_UP`,
keeps its one word. Dropping the category makes a few chains read alike (§7).

**Per side.** A chain is done one side at a time when any of its movements is. Its reps are then
per side and a set is both sides, printed "3×5/side", exactly as DESIGN_strength_tracking.md §4
says of a one-sided exercise. Whether the athlete does all rounds on the left before the right or
switches every round is theirs to choose; the notes say which.

**Tags.** A chain has no movement pattern and no muscles of its own. Where the planner's list and
the history print a class's tags, a chain prints every gear word any of its movements needs, since
the prompt promises that every item of the gear is needed, and "per side" when it is. In the
planned-against-done table and in the comparison it is one line like any exercise, keyed by the
joined key.

**Progression.** HOW TO PROGRESS applies to a chain as to one exercise: a range of rounds chosen
once and kept, more rounds inside it, then more load. The science says so in one paragraph (§4).

**What reads a key.** Today every reader that asks the exercise table about a key treats an
unknown key as "the key alone": `vocabulary.model_line` prints the bare key, `side_mark` prints
nothing, `implausible` is false, `get` is None. The change is one helper, `vocabulary.parts(key)`,
the list of part keys, one for a plain key, and the readers that need the parts: `words`,
`side_mark`, `model_line`, the planner's check (§4), the log's check (§6) and the merge script.
`vocabulary.similar`, which lists the exercises of a key's category for the `strength name`
command, has nothing to list for a chain and returns none, so the command offers the recent
exercises for a chain line as it does for an unnamed one. Everything else keys on the string and
does not care that it holds a `>`. `strength log` already matches a typed name against a key's
words, so once `words` gives a chain its movements' names, "goblet squat" lists the goblet squat
and every chain holding it with no change to the command.

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
> chain as one exercise whose key is its movements' keys joined with >, in the order they are
> done. Its reps are rounds, in a range kept from one session to the next like any rep range. Its
> load is the one implement, so it is set by the weakest movement. Every movement must be in
> EXERCISES STAMIND KNOWS, and all of them must share one implement; dumbbells and kettlebells
> count as one, and a bodyweight movement fits any. A chain under SESSIONS AS DONE is an exercise
> of its own: progress it as one, and never take its load as any of its movements' own load. In
> the notes, name a chain in words and say how its sides are done.

Four older sentences of the prompt and the science would otherwise say the opposite, and each is
amended in the same change (D14): "Use only exercises from EXERCISES STAMIND KNOWS" gains "or a
chain of them"; "A key is a category, a slash and a name" gains the chain's shape; the response
format's "(the key, exactly as EXERCISES STAMIND KNOWS spells it)" gains "or a chain of keys joined
with >"; and the sentence of `progression.md` that writes an exercise with no movement pattern at
what the athlete last did gains "except a chain, which progresses (A chain)". The response format
changes by that one phrase and nothing else: a chain is a string in `exercise`.

**The science.** `strength/progression.md` gets a section, "A chain": one implement held the whole
time; each movement ends where the next starts, so a swing ends at the hip where a clean starts, and
a clean ends in the rack where a squat and a press start; the load is the weakest movement's; two to
four movements and a range of three to eight rounds a set, kept like a rep range; a chain progresses
as one exercise, rounds then load, and is not a way to progress its movements. This is the model's
taste guided, not a list of allowed chains (D3).

**The check.** `_clean_exercise` in `planner_prompt.py` splits the returned name on `>`, strips
the spaces around each part, and resolves each part with `vocabulary.key_of`, so a Garmin name of
the table that is not a key is taken as its class's key, as today. A chain passes when it has two to
four parts and every part is known, and then on one of two grounds. A chain already on the athlete's
record, among the exercises a person has named in her stored sets (`sets.own_exercises`, passed in
by `planner.py`), passes whatever its gear and whether a movement repeats: what she did is the
proof, and the check guards the chains the planner invents (D10). A chain not on record passes when
no movement repeats and the parts share an implement: among each part's gear words, those that are
loads (`vocabulary.LOADS`) must have one in common, where Dumbbells and Kettlebells are read as one
word, and a part with no load word in its gear is skipped. A chain that fails is dropped from the
session with a line for the preview, as an unknown name is today, and the line says which ground
failed: "its movements share no implement" or "not an exercise Stamind knows".

**The list.** EXERCISES STAMIND KNOWS lists the table's classes and no chain: there is nothing to
list. The history shows the chains the athlete has done (§5), and the comparable session as done
shows the ones written for them.

## 5. The history and the comparison

The strength history groups the stored sets by their exercise string, so a chain is an entry of its
own, headed by its joined key and its tags (§2), with its days under it. The "(not prescribed)" and
NOT DONE lines are keyed by exercise too: a chain prescribed and not done is a NOT DONE line, one
done and not prescribed is marked. The alternation reading, which finds exercises whose sets
interleave, sees a chain as one exercise, and its " + " keeps its meaning (§3). `history.py`
changes nowhere; the tags come from `model_line`.

Nothing lands in the movements' own entries (D4). The load of a chain is the weakest movement's,
so an 8 kg clean done inside a chain says nothing about what the athlete cleans alone, and a
history that showed it would mislead the planner on the clean.

The planned-against-done table (`cli/common.py::strength_table`) and the comparison it is built
on (`strength/comparison.py`) match planned lines to done sets by key and print the words. A
chain is one planned line matched by its joined key. No change beyond `words`.

**The watch.** A chain reaches the record from the page only (D11). The watch names one exercise
per set, and no Garmin name resolves to a chain, so a set read from Garmin never lands on a chain
by itself. The naming question, which asks the athlete what a group of unnamed watch sets was,
offers the exercises of her recent strength days, and a chain she logged from the page is one of
them, so one tap can file a watch set under a chain on purpose. An athlete who trains with the
watch alone cannot record a prescribed chain, and loses it from her sessions after two such weeks
(§7).

## 6. The page

**Drawing a chain.** A chain is one card like any card. `wordsOf` splits the key on `>` and joins
each part's shown name, the one after the category, with " → ". `perSideOf` is true when any part
is. `photosOf` shows the first movement's photos. `patternOf` is null for a chain, so Swap on a
chain card searches every exercise with no pattern filter, and the chosen exercise replaces the
whole chain. Changing one movement of a chain on the page is not handled (§7).

**Adding a chain.** Under "+ Add an exercise" sits "+ Add a chain". It opens the same search sheet
in a chain mode. Each hit tapped is appended to a strip at the top of the sheet, "Kettlebell swing →
Kettlebell halo", and the input clears for the next pick. A tap on the strip removes its last name.
A Done button is enabled from the second pick and is the only move after the fourth. Done adds one
card with the joined key, bodyweight when every part is, with the sets an added exercise gets
today. The page checks nothing about the gear (D7): she is holding it, and a chain she has done
passes the planner's check from then on (D10). The strip and the Done button are the only new
markup; the search, the results and the pattern toggle are the ones Swap and Add use.

**The log.** `n` carries the joined key, and each set is rounds, kilograms and seconds as today.
`parse_log` in `strength/logger.py` checks each part of a key with `vocabulary.get`, so a chain of
known movements passes and a chain holding an unknown one is refused, as an unknown name is. The
payload version stays 2 (DESIGN_gym_logger.md §3): no field changes shape, and a key is still a
key.

**A past log opened from the calendar** shows a chain through the same `wordsOf`. Export to
Markdown prints the chain's shown words on its line.

**Order of going live.** The page goes live when main is pushed, through GitHub Pages, and the
planner's prompt goes live when main moves in the live checkout, because every run is a fresh
subprocess. So the page is built and pushed with the vocabulary, before or with the planner, and a
chain never reaches a page that cannot draw it (D19). No bot restart is needed.

## 7. Not handled

Each is a case a plausible athlete rarely meets, left out on purpose with the behaviour it gets.

- A round with unequal reps per movement, one clean then two squats then one press. The data holds
  rounds; the notes may say "two squats a round", and the page counts rounds.
- Changing one movement of a chain on the page. Swap replaces the chain whole; Add a chain makes a
  new one; Del removes the old.
- A chain done with the watch alone (D11). The record shows the chain as not done and the watch's
  one-exercise sets as not prescribed, at the chain's load. After two such weeks the habit rule
  writes those exercises in place of the chain. Both athletes log from the page today. An export to
  Garmin, not designed (DESIGN_exercise_table.md §12), would have to send each movement.
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
  only. Two different machines share the gear word "Machine" and pass it. A chain the model composes
  badly is a chain the athlete reads before lifting and swaps.
- A chain holding one two-handed movement and one per-side movement is per side as a whole (§3):
  "kettlebell swing → kettlebell halo" at 8 rounds a side is 16 swings a set. The notes say how
  the sides are done, and the athlete who means 8 swings logs 4 a side.
- Two chains of different implements can read alike once the categories are dropped: a band curl
  into a band front raise and the dumbbell pair both read "Curl → Front raise". The stored key
  tells them apart, and the athlete knows what she picked.
- A model that writes a chain as "A + B" has written two alternated exercises, not a chain, and the
  check drops the name as unknown. The paragraph spells the joiner.

## 8. Choices made without you

Every choice below was made by the author of this design, not ruled in the interview. Each is one
line to object to.

1. Two to four movements (§3).
2. Order matters: `A>B` and `B>A` are two chains with two histories (§3).
3. Reps are rounds, one rep of each movement a round, in a range kept like a rep range; a chain
   with no heavier implement holds its load at the top of the range, as a plain exercise does, and
   no rule raises the rounds instead (§2, §3, finding 2).
4. A chain is per side when any movement is; reps per side, a set is both sides (§3, finding 8).
5. A chain's words are its movements' names after their categories, joined with " → ", and the
   few chains that then read alike are accepted (§3, finding 9).
6. The gear check for a chain not on record: the load words of each movement's gear must have one
   in common, Dumbbells and Kettlebells read as one, a movement with no load word skipped, no
   repeated movement; machines and bands pass as any load word (§4, finding 7).
7. A chain's tags are every gear word any movement needs, and "per side"; no pattern and no muscles
   (§3, finding 7).
8. The planner's list does not list chains; the history does (§4).
9. The prompt does not push the planner toward chains: a chain is allowed wherever a plain
   exercise is, under today's rules, and enters a session the way any exercise does (§4).
10. The science paragraph lives in `progression.md`, not in a file of its own; the four older
    sentences are amended rather than trusted to lose to the more specific rule (§4, finding 6).
11. The notes name a chain in words and say how the sides are done (§4).
12. On the page: the button sits under "+ Add an exercise"; Done is enabled from the second pick; a
    tap on the strip removes the last name; Insert has no chain mode, Move does the rest; Swap on a
    chain searches everything and replaces the chain whole; photos are the first movement's (§6).
13. An added chain gets the sets an added exercise gets today (§6).
14. The payload version stays 2 (§6).
15. The merge script renames the parts of a chain key, so a merge never splits a chain's history
    (§3, finding 4).
16. `vocabulary.similar` returns nothing for a chain; `strength log` needs no change (§3, finding
    10).
17. The page ships before or with the planner, and no bot restart is in the order of the work (§6,
    finding 11).
18. No interview state file is written under `designs/`: the one written for the cycle
    retrospective was a stray.

## 9. Where the code goes

- `strength/vocabulary.py`: `CHAIN_MARK`, `parts(key)`, `shared_load(parts)` for the check;
  `words`, `side_mark`, `model_line` and `similar` read the parts.
- `strength/planner_prompt.py`: the paragraph in CHOOSING THE EXERCISES and the three amended
  sentences; `_clean_exercise` resolves and checks a chain, with the keys on record passed in.
- `strength/planner.py`: hands `sets.own_exercises()` to the check.
- `strength/progression.md`: the section "A chain" and the amended no-pattern sentence.
- `strength/logger.py`: `parse_log` checks the parts.
- `scripts/migrate_exercise_names.py`: renames inside a chain key.
- `miniapp/logic.js`: `wordsOf`, `perSideOf`, `photosOf`, `patternOf` read the parts; a chain
  key builder. `miniapp/app.js` and `miniapp/index.html`: the chain mode, the strip, Done.
  Tests in `miniapp/tests/logic.test.mjs`.
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
| D6 | Page | The athlete builds a chain from the search, two to four picks | She can invent a chain at the gym, and a repeated one becomes a habit the planner writes. Declined: read and log only (the author's recommendation); swap one movement | Interview | 2026-10-18 |
| D7 | Gear on the phone | No check on the page | She is holding the gear; the check guards the planner, which cannot see the gym. Declined: narrow the second pick; refuse and say why | Interview | 2026-10-18 |
| D8 | Process | Commit, red team on Opus, commit, two reviewers on Opus and Fable, commit | The author's process preference | Interview | 2026-10-18 |
| D9 | The joiner | `>`, not `+` | The history already prints alternated exercises as "A + B" and says so; a chain with the same sign reads as a pair taken in turns, and a pair as a chain (finding 1). Declined: alternation changes sign; both keep `+` told apart by spaces | Red Team | 2026-10-18 |
| D10 | Habit vs check | A chain on the athlete's record passes the planner's check whatever its gear or a repeated movement | What she did is the proof; the check guards invented chains (finding 3). Declined: the page refuses what the check refuses; leave it with a true message | Red Team | 2026-10-18 |
| D11 | The watch | A chain is recorded from the page only; a watch-only athlete loses a prescribed chain after two weeks, listed in §7 | Both athletes log from the page; a chain offered by the naming question would store the watch's reps as rounds (finding 5). Declined: the naming question offers the day's chain; the naming question never offers a chain | Red Team | 2026-10-18 |
| D12 | Merges | The merge script renames the parts of a chain key | Else a merge splits a chain's history and an old page's log is refused (finding 4); author's resolution | Red Team | 2026-10-18 |
| D13 | Progression | A range of rounds kept like a rep range; the load holds at the top when no heavier implement exists | The §2 story had raised the rounds, which `progression.md` forbids (finding 2); author's resolution | Red Team | 2026-10-18 |
| D14 | Older sentences | The four sentences that said the opposite are amended in the same change | A prompt must not contradict itself (finding 6); author's resolution | Red Team | 2026-10-18 |
| D15 | Tags | Every gear word any movement needs; machines and bands pass the check as any load word | "Every item of the gear is needed" (finding 7); author's resolution | Red Team | 2026-10-18 |
| D16 | Per side | Choice 4 stands; the §2 example is corrected and the two-handed oddity listed in §7 | A rule that fits single-arm complexes (finding 8); author's resolution | Red Team | 2026-10-18 |
| D17 | Alike words | Accepted; the stored key tells chains apart | Brackets for 37 ambiguous names would cost more than they give (finding 9); author's resolution | Red Team | 2026-10-18 |
| D18 | `strength log` and `strength name` | No change to `strength log`; `similar` returns nothing for a chain | The substring match on words already finds a chain; a category list for a chain was wrong (finding 10); author's resolution | Red Team | 2026-10-18 |
| D19 | Going live | The page ships before or with the planner; no bot restart | The prompt is live at the merge, the page at the push; every run is a subprocess (finding 11); author's resolution | Red Team | 2026-10-18 |

## Dependency Graph & Implementation Order

```
vocabulary.parts (1) ──┬──> page: draw and add a chain (2) ──┬──> planner check, prompt, science (3)
                       └──> logger.parse_log (2)             └──> merge script (4)
```

1. **The vocabulary** (`vocabulary.py`): `parts`, `shared_load`, and `words`, `side_mark`,
   `model_line`, `similar` reading the parts. Tests by shape in the vocabulary tests: a plain key
   is one part and reads as today. Nothing writes a chain yet, and every reader is ready for one.
2. **The page and the log** (`logic.js`, `app.js`, `index.html`, `logger.py`): the readers, the
   chain mode, the strip, Done; `parse_log` accepts a chain of known parts. Node tests for
   `wordsOf`, `perSideOf` and the key builder; one Python test. Pushed before or with step 3, so a
   chain never reaches a page that cannot draw it (D19). From here the athlete can build and log a
   chain, and the history shows it back.
3. **The planner** (`planner_prompt.py`, `planner.py`, `progression.md`): the paragraph, the
   amended sentences, the section, the check with the keys on record. From here the planner writes
   chains.
4. **The merge script** (`scripts/migrate_exercise_names.py`): renames inside a chain key. Needed
   before the next table merge, not before the feature.
5. **Docs.**

## Checklist

- [ ] `vocabulary.py`: `CHAIN_MARK`, `parts`, `shared_load`; `words`, `side_mark`, `model_line`,
      `similar`
- [ ] `miniapp/logic.js`, `app.js`, `index.html`: readers, chain mode, strip, Done; node tests
- [ ] `logger.py`: `parse_log` on a chain
- [ ] `planner_prompt.py`: the paragraph, the three amended sentences, `_clean_exercise` on a
      chain with the keys on record; `planner.py` passes them
- [ ] `progression.md`: "A chain", the amended no-pattern sentence
- [ ] `scripts/migrate_exercise_names.py`: parts of a chain key
- [ ] `docs/ARCHITECTURE.md`, the three amended designs
