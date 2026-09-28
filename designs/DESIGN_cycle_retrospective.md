# Design: a retrospective of each mesocycle and each plan

**Status:** Draft · **Date:** 2026-09-27 · **Branch:** `worktree-cycle-retrospective`

When a mesocycle or a plan is finished, Stamind keeps a short record of what it was for and
what came out of it. The model call inside `plan generate` reads that record, this season and
in later ones. The goal is long memory. A smaller prompt is a side effect that grows with the
history.

## 1. The problem

It is 18 September. The athlete runs `plan generate`. Stamind rebuilds the story of every
mesocycle that has started, from raw data, and puts it in the prompt. The prompt section is
called PRIOR TRAINING REVIEW. Nothing of it is saved. The next run rebuilds it from scratch.

Here is that real prompt, measured.

| Part of the prompt | Size |
|---|---|
| Science documents | 54.5 KB |
| The plan being replaced: strategy text | 9.3 KB |
| The plan being replaced: four mesocycles, all in the future | 11.4 KB |
| Review: introduction | 1.1 KB |
| Review: the finished mesocycle, 17 August to 6 September | 7.0 KB |
| Review: the mesocycle under way since 7 September | 4.7 KB |
| History written by `data bootstrap` and `data reflect` | 9.5 KB |

The review has three holes.

**Reach.** The review covers three plans: the plan being replaced, the plan the athlete trains
under, and the plan of the goal before, if that goal is less than 90 days old. Nothing further
back is shown. A plan written next spring does not know what an August mesocycle was for, or
whether it delivered.

**Versions.** Each `plan generate` saves a new version of the plan, and writes every mesocycle
of that version as a new row. A new version starts today, so it does not hold the mesocycles
that are already finished. Those stay behind in the old version. The review reads only the
current version. In the author's database, the mesocycle "Restoration, Recovery and Re-entry"
ran from 31 July to 10 August. It was trained. It exists only in the first two versions of the
plan, and the review never shows it.

**The athlete.** Nothing asks the athlete how a mesocycle went. The numbers say that load was
low in one week. They do not say that the athlete was travelling.

## 2. What is kept

One record per mesocycle, and one per plan. A record has four parts, each with one author.

| Part | Author | What it holds |
|---|---|---|
| Numbers | Stamind | sessions done out of sessions planned, hours, load planned and produced per week, fitness at the start and at the end, benchmark changes, share of time per intensity zone |
| Record lines | the retrospective writer | what it was for, what happened and why, what came out of it |
| Sentence for the athlete | the retrospective writer | one plain sentence, shown to the athlete |
| The athlete's own words | the athlete | the answer to one question, stored as typed |

The **retrospective writer** is the new model call that writes the record lines and the
sentence. It writes them once.

The record lines are a record and nothing else. They give no advice. Advice depends on the
next goal, and the writer does not know the next goal. The model call inside `plan generate`
does, and it draws its own conclusions. No learning is written from a record either (§15).

The writer states a reason only when its inputs state one. It never guesses why a week came
in low.

The numbers are stored as exact values and rounded only when shown. The record lines hold at
most 400 characters for a mesocycle and 600 for a plan.

This is how one record reads in a prompt. Every value is invented, to show the shape.

```
Aerobic base 2 (2026-10-05..2026-10-25), finished
  Sessions 11 of 12 · load 880 of 900 TSS · 21h40 · fitness 52 -> 57 · no test
  For: build easy volume before the first threshold work.
  Happened: load on target in weeks 1 and 3. Week 2 came in low: the athlete was away
  (constraint "Work trip", 12 to 15 October). Easy rides stayed easy.
  Came out: fitness rose. The long ride grew from 2h00 to 2h45.
  Athlete: "felt fresh all the way, the long rides got easier"
```

That is about 0.5 KB. Today the same mesocycle takes about 7 KB in the review.

## 3. When a record is created

Stamind records a mesocycle at the moment it ends, from the plan that is current on that day.
The record carries its own goal, name and dates. It does not point at a row of a plan
version. So a later version of the plan cannot lose it.

A mesocycle is the same mesocycle across plan versions when its goal, its name and its start
date are the same.

Three moments create a record.

**The end date has passed.** A mesocycle ends on Sunday 25 October. On Monday the date check
runs. It sees that the current plan holds a mesocycle whose end date has passed, and that no
record exists for it. It creates the record.

**`plan generate` drops the mesocycle under way.** A mesocycle is planned from 7 to 27
September. On Friday 18 September the athlete's goal changes, and they run `plan generate`.
The new version starts that day and does not keep the old mesocycle. Stamind records it as cut
short. The record covers 7 to 17 September, and it notes the planned end of 27 September.
When the new version keeps the mesocycle, with the same name and start date, nothing is
recorded yet. The mesocycle ends on 27 September like any other.

**The goal is called off.** `goal rm` archives the goal and keeps its plan. Stamind records
the mesocycle under way as cut short on that day, and the plan as ended on that day (§6).

A record is created only when its days hold at least one full week, Monday to Sunday. The
numbers are computed on full weeks, so a shorter span has none.

### The date check

The date check is the step that creates records. It is a database lookup, with no model
call. It runs in three places.

- At the start of the three service methods that change which plan is current: `plan_apply`,
  `plan_rollback` and `goal_archive`.
- At the start of `plan generate`, before it reads the records.
- In the commands run daily: `workout adapt`, `status`, and the bot's morning routine. In the
  morning routine it runs first, before the test that keeps the routine silent once the
  schedule has run out.

The first place closes a gap. Say a mesocycle ends on Sunday, and nobody runs a command until
Thursday. On Thursday the first command is `plan generate`. It saves a version that starts on
Thursday. Had the date check run only afterwards, the finished mesocycle would already sit in
an old version, and it would be missed.

A plan version that lived ten minutes creates no record. A record appears only when an end
date passes while that version is the current plan.

### Undoing

`plan rollback` restores an earlier version of the plan. Say `plan generate` dropped the
mesocycle under way, and ten minutes later the athlete rolls back. The mesocycle is under way
again, so the record that calls it cut short is wrong. `plan rollback` removes that record and
its question. `goal_reinstate`, which brings a called-off goal back, does the same. Both
remove only records whose planned end is today or later.

## 4. Ask first, write after

It is Sunday 25 October, and a mesocycle ends. On Monday the date check creates the record
and puts one question in the athlete queue, the list of questions that Stamind keeps for the
athlete. On Tuesday the athlete answers. The retrospective writer runs at that moment, with
the athlete's words in hand.

Now the same week, but the athlete does not answer. On Sunday 1 November, seven days after
the end, the record is due anyway. The next command that runs the write step (§5) writes it.

**Why wait.** The athlete does the long ride on Saturday, and the watch syncs on Monday
evening. A record written on Sunday morning would say that the ride was skipped. The nightly
`data reflect` already waits until Wednesday for the same reason.

**The rule.** A record is due when its question is closed, or when seven days have passed
since its end. A question is closed when the athlete has answered it or dropped it. A record
for which no question was queued is due at once.

A question is queued only for a record whose end is at most seven days old. A record created
later than that gets no question.

### The question

The question is a new kind in the athlete queue, `retrospective`
(DESIGN_athlete_queue.md §8). Its subject is the record.

| | Expert voice | Companion voice |
|---|---|---|
| Mesocycle | How did "Aerobic base 2" (Oct 5 to Oct 25) go for you? | Your last three weeks of training are done. How did they go for you? |
| Plan | Your plan toward "Alpe du Zwift" ended on Dec 22. How did it go? | Your plan toward "Alpe du Zwift" is finished. How did it go for you? |

It offers one answer, "tell me", which asks for typed text. Its drop is "nothing to say". It
has the standard "Not now". The question is the same for an event goal and for a horizon
goal. Stamind never asks "did you reach it?".

The question goes stale when its record is removed, and once its record is written. So a
question left unanswered for seven days leaves the queue. The operator can still add the
athlete's words afterwards (§9).

### One question at the end of a plan

The last mesocycle of a plan and the plan itself end on the same day. Only the question about
the plan is asked. Both records wait for it. The answer is stored with the record of the plan.

## 5. The retrospective writer

The retrospective writer is one model call. It uses the coach's model setting. It gets no
science documents.

For a mesocycle, the user message holds four sections.

| Section | Content |
|---|---|
| `## THE MESOCYCLE` | name, dates, how it ended, and its description in full |
| `## WHAT WAS MEASURED` | the text that the review prints for this mesocycle today |
| `## CONSTRAINTS AND SIGNALS IN THOSE WEEKS` | the constraints and the daily signals stored for those days |
| `## THE ATHLETE'S WORDS` | present only when there are any |

For a plan, it holds `## THE PLAN` (goal, dates, how it ended, the strategy text),
`## ITS MESOCYCLES` (their records) and `## THE ATHLETE'S WORDS`.

The system message holds the role line, `## TASK` and `## RESPONSE FORMAT`
(DESIGN_prompt_structure.md §2). The answer is JSON with two fields, `record` and
`athlete_line`.

`## WHAT WAS MEASURED` reuses `mesocycle_report` and `_mesocycle_week_lines`. Nothing new is
rendered. The numbers stored in the record come from the same functions and from
`adherence_verdicts`.

### The write step

The write step writes one due record, the oldest first. It refreshes Garmin data for the days
of the record, computes the numbers, calls the writer and stores the result. It runs:

- when the athlete answers the question, for that record;
- at the start of `workout adapt` and `plan generate`;
- in the bot's morning routine, after the date check.

A run of the write step writes at most one record. The answer to a plan's question is the one
exception: it writes the record of the last mesocycle, then the record of the plan.

### When the writer fails

The command that ran the write step carries on without the record. Stamind notes the time of
the failure, and does not try that record again for one day. When the failure happens as the
athlete answers, their words are stored first, and the reply is a fixed line of thanks.

## 6. The end of a plan

A retrospective is about the plan, not about the goal. A plan ends when the end date of its
last mesocycle has passed. The date of the goal plays no part.

**The rule.** When the last mesocycle of a goal's current plan has ended, a record of the plan
is due. It covers the mesocycle records of that goal that no earlier record of a plan covers.

`plan generate` cannot make a plan longer. It writes a plan from a start date to the date of
the goal. Once the date of a goal has passed, it refuses for that goal. So each plan that was
trained to its end gets its own record, and that record is never rewritten because a date
moved.

Here is the one case where a goal gets two. A plan runs from 1 October to 22 December. Its
record is written in late December. On 2 January the athlete moves the goal to 20 January and
runs `plan generate`. Stamind writes a new version of the plan, from 2 to 20 January. After
20 January a second record is written. It covers the mesocycles of January only. The first
record stays as it is.

**A goal's date changed, plan untouched.** Nothing happens here. `status` and `plan show`
already say that the plan is out of date (DESIGN_plan_staleness.md).

**A plan replaced half-way.** A new version for the same goal is not an end. The plan of that
goal carries on, and no record of the plan is due.

**A goal called off.** `goal rm` ends the plan that day. The record of the plan says that the
goal was called off, and on which date. It covers the mesocycles trained until then.

**A plan deleted.** `plan rm` and `goal rm --purge` delete a plan for good. They delete its
records too. The list they show before asking includes the records.

## 7. What `plan generate` reads

| What | Shown as | Size |
|---|---|---|
| The mesocycle under way | full detail, as today | about 5 KB |
| The mesocycle that finished most recently | full detail, plus its record | about 7.5 KB |
| Earlier finished mesocycles of the goals in the review | their record | about 0.5 KB each |
| Every finished plan | its record | about 0.7 KB each |

The goals in the review are the three that the review covers today: the goal being planned,
the goal whose plan the athlete trains under, and the goal before, if it is less than 90 days
old.

**Finished mesocycles come from the records.** The review no longer reads them from plan
versions. So a mesocycle that lives only in an old version is shown. The mesocycle under way
still comes from the current plan.

**A record not written yet.** A finished mesocycle whose record has no lines yet is shown in
full detail, as today. So nothing is missing while a question is open.

**Where they go in the prompt.** The records of mesocycles are printed inside
`## PRIOR TRAINING REVIEW`. The records of plans are printed in a new section,
`## RETROSPECTIVES OF PAST PLANS`, oldest first, with no limit on their number. The
introduction of the review says that a record was written once, when the mesocycle ended, and
that the quoted line is the athlete's own.

**The plan being replaced.** In `## PREVIOUS PERIODIZATION STRATEGY`, a mesocycle that has a
written record is listed by name and dates only. Today its description is printed there and
again in the review, when a plan is replaced half-way.

**The text from `data reflect` stays.** `plan generate` keeps replaying the history written by
`data bootstrap` and `data reflect`. That text is about how the body responded. A record is
about the plan.

**The saving.** On the prompt of 18 September there is none: one mesocycle is finished and
keeps its detail. Take late December instead, with a plan of four finished mesocycles. Today
the review would print all four in full, about 30 KB. With records it prints about 10 KB.
Both figures are estimates.

No other model call reads a record. The week planner, the model call inside `workout adapt`
and `data reflect` stay as they are.

## 8. What the athlete sees

### In companion mode

For the companion athlete, in one sentence: when a stretch of training is done, the coach asks
how it went, and then says what it saw.

It is Monday 26 October. The morning message arrives, and after it the question: "Your last
three weeks of training are done. How did they go for you?" Under it: `[Tell me]`
`[Nothing to say]` `[🕐 Not now]`. The athlete taps the first button and types "felt fresh
all the way, the long rides got easier". The reply is the sentence written for them: "You
kept your training steady these three weeks, and your long rides grew."

The sentence is written after the answer, so it never contradicts what the athlete just
said.

When the athlete taps "Nothing to say", the chat sends no sentence. The record is written by
the next run of the write step.

The plan view shows the sentence under each finished mesocycle, below the tick and the name.
The sentence about a whole plan is shown as a reply only. Once the next goal is planned, the
plan view shows the new plan.

The sentence follows four rules. It uses plain words. It holds no numbers. It holds nothing
private, because it can appear on a lock screen. It never opens with a miss
(DESIGN_bot_simple_frontend.md).

### In expert mode

The question appears in `sm queue answer` on the terminal, and in the chat when the athlete
types `queue answer`. The reply is the same sentence.

`plan show` prints the records of the goal under their own heading, oldest first. Each one
shows its id, its numbers, its lines and the athlete's words.

## 9. Correcting a record

A record is read as fact by every later `plan generate`. So a wrong one must have a way out.
Two commands give it, and neither deletes a record.

| Command | What it does |
|---|---|
| `plan retro redo ID` | blanks the numbers, the lines and the sentence. The write step writes them again on its next run. The athlete's words are kept, and the athlete is not asked again. |
| `plan retro words ID "text"` | replaces the athlete's words. With `--clear` it removes them. |

`redo` serves three cases: a record that is wrong, a writer prompt that was improved, and
words that were corrected. `words` serves the athlete who typed an answer meant for another
conversation.

## 10. The history from before

Records are created from the day this feature is deployed. The mesocycles trained before that
day are repaired once, by a script: `scripts/backfill_retrospectives.py`. It runs once per
instance.

The script lists the mesocycles it finds in all versions of all plans, one line per goal,
name and start date. For each one the operator says whether it was trained, and on which day
it really ended. The script creates those records and writes them. It queues no question,
because those mesocycles ended long ago. It then does the same for the plans that ended.

The operator decides because a program cannot. In the author's database, one plan version
lived for ten minutes and holds a mesocycle that was never trained. And a rollback erases the
time at which a version was replaced, so that time cannot be used either.

## 11. Data

One new table holds both kinds of record.

```sql
CREATE TABLE IF NOT EXISTS retrospectives (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    objective_id INTEGER NOT NULL,
    level TEXT NOT NULL,             -- 'mesocycle' | 'plan'
    name TEXT NOT NULL,              -- the mesocycle's name; the goal's title for a plan
    start_date TEXT NOT NULL,        -- first day covered
    end_date TEXT NOT NULL,          -- last day trained
    planned_end_date TEXT NOT NULL,  -- equals end_date unless it stopped early
    ended_by TEXT NOT NULL,          -- 'finished' | 'replaced' | 'called_off'
    intent TEXT NOT NULL,            -- the description, or the strategy, as it stood
    question_subject TEXT,           -- subject of the queued question; NULL when none
    numbers TEXT,                    -- JSON, exact values; NULL until written
    body TEXT,                       -- the record lines; NULL until written
    athlete_line TEXT,               -- the sentence for the athlete
    athlete_words TEXT,              -- as typed
    created_at TEXT NOT NULL,
    written_at TEXT,
    failed_at TEXT,                  -- last failed attempt; NULL after a success
    UNIQUE(objective_id, level, name, start_date),
    FOREIGN KEY (objective_id) REFERENCES objectives(id) ON DELETE CASCADE
)
```

`intent` is copied when the record is created. The writer may run a week later, and by then
the plan version that held the description may have been replaced.

`UNIQUE` makes the date check safe to run twice. It inserts with `INSERT OR IGNORE`, so the
morning routine and a typed command cannot create the same record twice.

`question_subject` is shared by the last mesocycle of a plan and by the plan, because one
question serves both (§4).

`goal rm --purge` removes the records through the foreign key. `plan rm` deletes a plan and
keeps the goal, so `delete_macrocycle_for_objective` deletes the goal's records itself.

A new table needs no hand-written `ALTER`. `SCHEMA_VERSION` takes the next free number when
this lands, and `_init_db` creates the table.

## 12. Privacy and safety

The athlete's words go into prompts as typed. Constraints and plan feedback already do. The
athlete owns the instance they write to, so this opens no new door.

A record travels to the model provider inside the `plan generate` prompt, like the rest of
the training data. Prompts are logged under `logs/llm_exchanges/`, as today.

The sentence for the athlete can appear on a lock screen. §8 gives its rules.

The operator can clear the athlete's words with `plan retro words ID --clear`.
`goal rm --purge` deletes every record of a goal.

## 13. Touch points

| File | Change |
|---|---|
| `stamind/db/schema.py` | the `retrospectives` table; `SCHEMA_VERSION` |
| `stamind/db/retrospectives.py` (new) | create, list, write, blank and remove records |
| `stamind/db/periodization.py` | `delete_macrocycle_for_objective` also deletes the goal's records |
| `stamind/cycle_records.py` (new) | the date check, the cut-short case, the call-off, the undo |
| `stamind/coach/service/planning.py` | `plan_generate` and `plan_apply` run the date check; `plan_apply` records a dropped mesocycle; `plan_rollback` runs the undo |
| `stamind/coach/service/goals_constraints.py` | `goal_archive` ends the plan; `goal_reinstate` runs the undo |
| `stamind/coach/engine/retrospective.py` (new) | the writer's prompt and its call, as a mixin of `CoachEngine` |
| `stamind/coach/service/retrospective.py` (new) | the write step, as a mixin of `CoachService` |
| `stamind/retrospective_question.py` (new) | the `retrospective` kind: wording in both voices, stale check, answer, drop |
| `stamind/athlete_queue.py` | the kind in `KINDS` |
| `stamind/coach/service/history_context.py` | finished mesocycles come from records; a record stands in for the detail |
| `stamind/coach/engine/planning.py` | `## RETROSPECTIVES OF PAST PLANS`; the review's introduction; name and dates only in `## PREVIOUS PERIODIZATION STRATEGY` |
| `stamind/cli/plans/retro.py` (new), `stamind/cli/plans/parser.py` | `plan retro redo`, `plan retro words` |
| `stamind/cli/plans/show.py`, `stamind/cli/common.py` | `plan show` prints the records; `print_plan_cascade` counts them |
| `stamind/cli/render/plan_lines.py` | the sentence under a finished mesocycle in `simple_plan_lines` |
| `stamind/cli/workouts/adapt.py`, `stamind/cli/plans/generate.py`, `stamind/cli/bot/views.py` | the date check and the write step |
| `stamind/cli/status.py` | the date check |
| `scripts/backfill_retrospectives.py` (new) | the one-off script of §10 |
| `docs/ARCHITECTURE.md` | the table, the writer, the two steps |

These implemented designs are amended when the code lands.

| Design | What changes |
|---|---|
| `DESIGN_backward_evaluation.md` §6 | the review reads stored records; "nothing is written" no longer holds for `plan generate` |
| `DESIGN_athlete_queue.md` §8 | one more kind |
| `DESIGN_bot_simple_frontend.md` | a finished mesocycle in the plan view carries a sentence |
| `DESIGN_plan_rollback.md` §6.1 | a rollback removes the record of a mesocycle that is under way again |
| `DESIGN_prompt_structure.md` §4 | the new sections of `plan generate`, and the writer's sections |
| `DESIGN_plan_feedback.md` §2 | the answers are one more channel from the athlete |

This design reads nothing from `mesocycles.summary`, the one-line description that the
calendar mini app added to each mesocycle. That line says what a mesocycle is for. A record
says how it went.

## 14. Tests

All tests use `unittest`. The writer is stubbed by patching
`stamind.coach.engine.openrouter_client`.

| File | What it proves |
|---|---|
| `tests/test_cycle_records.py` (new) | each of the three moments creates a record; a kept mesocycle creates none; a span without a full week creates none; a second run creates nothing; a rollback and a reinstated goal remove what they must |
| `tests/test_retrospective_writer.py` (new) | a record is due on a closed question, after seven days, or with no question; one record per run; a failure waits a day; a plan's answer writes two; the prompt follows the section rules |
| `tests/test_athlete_queue.py` | the kind's wording in both voices; the answer stores the words and returns the sentence; the question goes stale once the record is written |
| `tests/test_analysis_prior_training.py` | finished mesocycles come from records; the latest keeps its detail; a record without lines falls back to the detail; the plans section |
| `tests/test_cli_plans.py`, `tests/test_simple_render_plan.py` | `plan retro redo`, `plan retro words`, `plan show`, `plan rm`; the sentence in the companion plan view |

No test reads the source for an invariant. Each entry point that changes the current plan has
its own test, which checks that the record exists after the call.

## 15. Not handled

- **Advice and learnings.** No learning is written from a record, and `data reflect` does not
  read records. A learning expires after 21 to 180 days without a week that confirms it, and
  a lesson from a whole mesocycle cannot be confirmed weekly. To look at again once real
  records exist.
- **The week planner.** It does not read records. The sessions of a new mesocycle are usually
  written before the old one ends, so it sees the old one in full.
- **A mesocycle without a full week.** A five-day taper gets no record.
- **A kept mesocycle under a new name.** When `plan generate` keeps the mesocycle under way
  and changes its name, Stamind sees one mesocycle dropped and one new.
- **Two plans that overlap in time.** Plans for different goals are expected to follow each
  other.
- **An answer after seven days.** The question has left the queue. The operator adds the
  words with `plan retro words`.
- **A silent week.** When no command runs for more than seven days after a mesocycle ends, the
  athlete is not asked, and the record is written without their words.
- **A limit on the records of plans.** None. Ten years of goals is about 15 KB.
- **Prompt size.** The science documents take 54.5 KB. That is a separate design.
- **The Goals & plan page of the calendar mini app.** It does not show the sentence for the
  athlete. That page landed on `main` while this design was written.

## Decisions Log

| ID | Topic | Decision | Rationale | Source | Date |
|---|---|---|---|---|---|
| D1 | Main problem | Long memory, and a smaller prompt | The athlete ranked both. Measurement later showed that the saving is small today (D18) | Interview | 2026-09-27 |
| D2 | Author | One model call writes the record once, next to numbers computed by Stamind and the athlete's own words | A reason known when the mesocycle ends is lost months later | Interview | 2026-09-27 |
| D3 | Content | A record, with no advice | Advice depends on the next goal, which the writer does not know | Interview | 2026-09-27 |
| D4 | Link to learnings | None for now. The first answer was "advice becomes a learning"; after the discussion it became none | A learning expires without weekly confirmation, and learnings have one writer by design | Interview | 2026-09-27 |
| D5 | When it is written, first answer | By the first command that needs it, plus the bot's morning routine. Replaced by D14 | It needed no scheduler | Interview | 2026-09-27 |
| D6 | Detail kept in `plan generate` | The mesocycle that finished most recently keeps full detail plus its record. Earlier ones show the record only | The first mesocycle of a new plan is built on full evidence | Interview | 2026-09-27 |
| D7 | Week planner as a reader, first answer | `workout generate` reads the latest record. Reversed by D19 | It closed a gap on the first week of a mesocycle | Interview | 2026-09-27 |
| D8 | Cut short | A mesocycle dropped half-way gets a record over the days trained, with at least one full week | No hole in the long memory | Interview | 2026-09-27 |
| D9 | Plan level | A record of the plan stands for older plans | The history grows by about 0.7 KB per plan, not 6.5 KB per year | Interview | 2026-09-27 |
| D10 | Asking | One question after each mesocycle and one at the end of a plan. The athlete can decline | How it felt can only come from the athlete | Interview | 2026-09-27 |
| D11 | Companion athlete | One plain sentence for the athlete. The interviewer recommended the question alone | The athlete gets something back for answering | Interview | 2026-09-27 |
| D12 | Correction | The operator has a record written again | A wrong record steers later plans, and the writer's prompt will improve | Interview | 2026-09-27 |
| D13 | Identity | A record is created when the mesocycle ends, keyed by goal, name and start date, free of plan versions | Each `plan generate` rewrites the mesocycles as new rows | Red Team | 2026-09-27 |
| D14 | Order | Ask first, write after: on the answer, on a decline, or after seven days | Garmin data settles late, and the sentence must not contradict the answer | Red Team | 2026-09-27 |
| D15 | End of a plan | A retrospective is about the plan, not the goal. One record per plan trained to its end | The athlete's own rule. `plan generate` cannot make a plan longer | Red Team | 2026-09-27 |
| D16 | Goal called off | `goal rm` ends the plan that day | The season that was called off is the one the next plan most needs | Red Team | 2026-09-27 |
| D17 | History and failures | A one-off script with the operator's confirmation. The date check runs before the plan changes. One record per run. One day between retries | A program cannot tell which old mesocycles were trained, and commands must stay fast | Red Team | 2026-09-27 |
| D18 | Text from `data reflect` | `plan generate` keeps replaying it. The goal of this design is long memory | It is about how the body responded, which a record does not hold | Red Team | 2026-09-27 |
| D19 | Week planner as a reader | Cut. Only `plan generate` reads records | Sessions are written before the mesocycle ends. It also conflicted with DESIGN_plan_feedback.md §7 | Red Team | 2026-09-27 |
| D20 | The athlete's words | Stored in their own field. The operator can replace or clear them | A message typed by mistake must not stay in every later prompt | Red Team | 2026-09-27 |
| D21 | Operator's view | `plan show` prints the records in expert mode | The operator must see a record to correct it | Red Team | 2026-09-27 |
| D22 | Calendar mini app | This design reads nothing from `mesocycles.summary` | The two lines say different things: what it is for, and how it went | Red Team | 2026-09-27 |
| D23 | Questions at the end of a plan | One question, about the plan | Two questions about the same days would arrive on one morning | Red Team | 2026-09-27 |
| D24 | Sentence about a plan | Shown as a reply only, not in the plan view | The plan view shows the new plan within days | Red Team | 2026-09-27 |
| D25 | Where this document lives | `designs/DESIGN_cycle_retrospective.md` | Every design document lives under `designs/` | Interview | 2026-09-27 |

## Dependency Graph & Implementation Order

```
1 Records --> 2 Writer --+--> 3 Question --+--> 5 Plans --> 7 History
                         |                 +--> 6 Views
                         +--> 4 Reader
```

Each step is one commit. Each step updates `docs/ARCHITECTURE.md` and the designs it amends
(§13).

1. **Records.** The table, `stamind/db/retrospectives.py`, the date check, the cut-short
   case, the undo, the deletes. No model call yet, and nothing reads the records.
2. **Writer.** The numbers, the writer's prompt, the write step and its failure rule. Until
   step 3 no question exists, so every record is due at once.
3. **Question.** The `retrospective` kind, the answer that runs the writer, the sentence as
   the reply, the seven-day rule.
4. **Reader.** The review built from records, the latest mesocycle in full, the fallback to
   the detail, name and dates only in the plan being replaced.
5. **Plans.** The record of a plan, the call-off, one question at the end of a plan,
   `## RETROSPECTIVES OF PAST PLANS`.
6. **Views.** `plan show`, the companion plan view, `plan retro redo`, `plan retro words`.
7. **History.** `scripts/backfill_retrospectives.py`, run once on each instance.
