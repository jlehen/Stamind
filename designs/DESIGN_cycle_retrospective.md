# Design: a retrospective of each mesocycle and each plan

**Status:** Implemented on 2026-10-01 (D46-D49 record what the code had to decide) ·
**Date:** 2026-09-27, brought up to date with `main` on 2026-09-30, revised after two
reviews on 2026-10-01 · **Branch:** `worktree-cycle-retrospective`

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
| Numbers | Stamind | sessions done out of sessions planned, hours, total load planned and produced, fitness at the start and at the end, benchmark changes |
| Record lines | the retrospective writer | what it was for, what happened and why, what came out of it |
| Sentence for the athlete | the retrospective writer | one plain sentence, shown to the athlete |
| The athlete's own words | the athlete | the answer to one question, stored as typed |

The **retrospective writer** is the new model call that writes the record lines and the
sentence. It writes them once.

The record lines are a record and nothing else. They give no advice. Advice depends on the
next goal, and the writer does not know the next goal. The model call inside `plan generate`
does, and it draws its own conclusions. No learning is written from a record either (§15).

The writer states a reason only when its inputs state one. It never guesses why a week came
in low. The athlete's own words about a session are such an input: "I stopped at 12:30 in
the second round, on purpose" says why that session came in short (§5).

The numbers are the values that the first line of a record shows, and no others. They are
stored as exact values and rounded only when shown. The load of each week and the share of
time per intensity zone are not stored. The writer reads both as text (§5), and nothing
prints them from a record.

The writer is asked to keep the record lines within 400 characters for a mesocycle and 600
for a plan.

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

Stamind records a mesocycle when it ends, from the plan that is current on that day. The
record carries its own goal, name and dates. It does not point at a row of a plan version. So
a later version of the plan cannot lose it.

A mesocycle is the same mesocycle across plan versions when its goal and its start date are
the same. Its name plays no part. The model call inside `plan generate` may reword a name
between two versions.

One step creates records, and removes those that became wrong. It is the **date check**: a
database lookup, with no model call. It compares the records with the plan versions that
Stamind keeps. It reads the goals that are not called off. A goal whose date has passed stays
in.

Three moments create a record.

**The end date has passed.** A mesocycle ends on Sunday 25 October. On Monday the date check
runs. It sees that the current plan holds a mesocycle whose end date has passed, and that no
record exists for it. It creates the record. A mesocycle that reached its end date always
gets a record, however short it is.

**`plan generate` drops the mesocycle under way.** A mesocycle is planned from 7 to 27
September. On Friday 18 September the athlete's goal changes, and they run `plan generate`.
The new version starts that day, and it holds no mesocycle that starts on 7 September.
Nothing is recorded at that moment. Stamind keeps the old version, and the time at which it
was replaced. On Saturday the date check looks at each replaced version, and at the mesocycle
that was under way on the day of the replacement. It finds the one that started on
7 September, and it sees that the current plan does not hold it. It records it as cut short,
from 7 to 17 September.

The day of the replacement is read on the athlete's clock. Stamind stores the time of a
replacement in UTC. An athlete in California who runs `plan generate` at 18:00 on Friday is
already on Saturday in UTC. Read in UTC, the record would end one day late, and one day can
decide whether seven days were trained.

When the new version keeps the mesocycle, with the same start date, the current plan still
holds it. Nothing is recorded yet, and the mesocycle ends on 27 September like any other.

A mesocycle cut short gets a record only when at least seven days of it were trained. A
mesocycle dropped after three days gets none. When several replaced versions hold the
mesocycle, the one replaced last gives the end of the record.

**The goal is called off.** `goal rm` archives the goal and keeps its plan. It first runs the
date check for that goal, one last time. Then it records the mesocycle under way as cut
short, up to the day before, if at least seven days of it were trained. It records the plan
as called off too (§6). From then on the date check skips the goal. So the mesocycles that
the plan still holds for later weeks get no record. Calling a goal off is the one action that
writes a record itself, because nothing else stores the day on which it happened.

### A record that became wrong

No command undoes a record. The date check removes a record that the current plan of a live
goal contradicts. A live goal is one that is not called off.

- A mesocycle record is contradicted when that plan holds a mesocycle with the same start
  date, and that mesocycle has not ended.
- A record of a plan that says "called off" is contradicted when that plan has not ended.

Take the mesocycle of 7 to 27 September again. On Friday 18 September `plan generate` drops
it, and on Saturday the date check records it as cut short. On Sunday the athlete runs
`plan rollback`. The mesocycle is in the current plan again, and it ends on 27 September. On
Monday 21 September the next date check removes the record. On Monday 28 September the
mesocycle is recorded like any other.

Now take two runs of `plan generate` on that Friday, then a rollback of one step. The version
that comes back does not hold the mesocycle either. So the record is right, and it stays.

A goal brought back is corrected the same way. The athlete calls a goal off on Friday
18 September, and it is brought back on Sunday. The goal is live again, and its plan has not
ended. The next date check removes the "called off" record of the plan, and the cut-short
record of the mesocycle.

The date check removes first, and creates after. It never creates in the same run a record
that it just removed: removing needs the mesocycle in the current plan and not ended, and
creating needs it ended, or absent from the current plan.

### Where the date check runs

- At the start of `plan generate`, of `workout adapt` and of the bot's morning routine. The
  morning routine sends its message once a day, and it tests that first. The date check runs
  after that test, and before the test that keeps the routine silent once the schedule has
  run out.
- Inside `goal_archive`, the service method behind every way of calling a goal off, for that
  goal.

The first place closes a gap. Say a mesocycle ends on Sunday, and nobody runs a command until
Thursday. On Thursday the first command is `plan generate`. The date check at its start
records the finished mesocycle before the new version is saved. Afterwards that mesocycle
would sit in an old version only, and it would be missed.

`plan rollback` does not run the date check, and neither does bringing a goal back. A record
that became wrong stays until the next date check, which is the next morning for an athlete
who uses the bot. Until then `plan show` can still list it. `plan generate` never reads it,
because it runs the date check first.

A plan version that lived ten minutes creates no record of its own: a mesocycle that it
started has no trained day.

## 4. Ask first, write after

It is Sunday 25 October, and a mesocycle ends. On Monday the date check creates the record
and puts one question in the athlete queue, the list of questions that Stamind keeps for the
athlete. On Tuesday the athlete answers. The retrospective writer runs at that moment, with
the athlete's words in hand.

Now the same week, but the athlete does not answer, or taps "Nothing to say". On Sunday
1 November, seven days after the end, the record is due. The next command that runs the
write step (§5) writes it.

**Why wait.** The athlete does the long ride on Saturday, and the watch syncs on Monday
evening. A record written on Sunday morning would say that the ride was skipped. The nightly
`data reflect` already waits until Wednesday for the same reason.

**The rule.** A record is due when seven days have passed since its end. It is due sooner in
one case: it holds the athlete's words and it has no record lines yet. That is an answer
after which the writer failed (§5). The rule reads the record alone. It never looks into the
athlete queue.

An answer does not wait to be due. It runs the writer at once, because the athlete is owed a
reply. "Nothing to say" owes no reply, so that record waits its seven days like one that got
no answer.

**Who is asked.** A question is queued only for a mesocycle or a plan that reached its end
date, and only when that end is less than seven days old. A record cut short or called off
gets no question. A cut by `plan generate` is something the athlete did not see, and a goal
that they called off themselves needs no "how did it go?". Such a record waits its seven
days, and then it is written.

### The question

The question is a new kind in the athlete queue, `retrospective`
(DESIGN_athlete_queue.md §8). Its subject is the record's id. The queue asks about a kind and
subject once, for ever. With the id as subject, a record that was removed and created again
can be asked about. Like every kind, it has two wordings: one for the terminal, and one for
the chat.

| | On the terminal | In the chat |
|---|---|---|
| Mesocycle | How did "Aerobic base 2" (Oct 5 to Oct 25) go for you? | Your last three weeks of training are done. How did they go for you? |
| Plan | Your plan toward "Alpe du Zwift" ended on Dec 22. How did it go? | Your plan toward "Alpe du Zwift" is finished. How did it go for you? |

It offers one answer, "tell me", which asks for typed text. Its drop is "nothing to say". It
has the standard "Not now". The question is the same for an event goal and for a horizon
goal. Stamind never asks "did you reach it?".

The question goes stale when its record is removed, and seven days after the end of its
record. So a question left unanswered for seven days leaves the queue. The operator can still
add the athlete's words afterwards (§9).

### One question at the end of a plan

The last mesocycle of a plan and the plan itself end on the same day. Only the question about
the plan is asked. The last mesocycle gets no question of its own. The answer is stored with
the record of the plan. The record of the last mesocycle is written with it (§5).

## 5. The retrospective writer

The retrospective writer is one model call. It uses the coach's model setting. It gets no
science documents.

For a mesocycle, the user message holds five sections.

| Section | Content |
|---|---|
| `## THE MESOCYCLE` | name, dates, how it ended, and its description in full |
| `## WHAT WAS MEASURED` | the text that the review prints for this mesocycle today |
| `## CONSTRAINTS AND SIGNALS IN THOSE WEEKS` | the constraints and the daily signals stored for those days |
| `## SESSIONS THE ATHLETE SPOKE ABOUT` | each session of those days that carries the athlete's words, printed the way the week planner prints it (DESIGN_session_notes.md §4); present only when there are any |
| `## THE ATHLETE'S WORDS` | the answer to the question; present only when there is one |

The words about a session leave every other prompt about two weeks after the session
(DESIGN_session_notes.md §4). The record is where a reason in them can outlive that.

For a plan, it holds `## THE PLAN` (goal, dates, how it ended, the strategy text),
`## ITS MESOCYCLES` (their records) and `## THE ATHLETE'S WORDS`.

The system message holds the role line, `## TASK` and `## RESPONSE FORMAT`
(DESIGN_prompt_structure.md §2). The answer is JSON with two fields, `record` and
`athlete_line`. The limits of §2 are a line of `## TASK`. Stamind does not cut a longer
answer.

The call is logged under the label `retrospective_writer`, for a mesocycle and for a plan
alike. So its file in `logs/llm_exchanges/` ends in `_retrospective_writer.md`. The file name
also carries the run id of the command that ran the write step (DESIGN_logging.md §6). On a
morning when `workout adapt` writes a record, that run leaves two files with the same run id:
the writer's, and `workout adapt`'s own.

`## WHAT WAS MEASURED` reuses `mesocycle_report` and `_mesocycle_week_lines`. Nothing new is
rendered. Those two return text, and the load of each week and the zone shares live only
there.

The numbers stored in the record are totals over the mesocycle's own days, from its first
day to its last. The load comes from `activity_load` and `planned_load`, the sessions from
`adherence_verdicts`, and the fitness from the values stored for the first and the last day.

The record of a plan computes nothing again. Its sessions, hours and loads are the sums of
its mesocycle records. Its fitness is the start of the first one and the end of the last
one, and each benchmark is taken the same way: its first value and its last. Days that no
mesocycle record covers are not counted, such as a mesocycle dropped after four days.

### The write step

The write step writes one due record, the oldest first. It refreshes Garmin data for the days
of the record, computes the numbers, calls the writer and stores the result. It runs:

- when the athlete answers the question, for that record;
- at the start of `workout adapt` and `plan generate`, after the date check;
- in the bot's morning routine, right after the date check (§3).

The refresh is `ensure_data`, which fetches only the days that are missing and the last three
days. It matters when the athlete answers. Say the watch syncs Saturday's long ride on Monday
at 18:00, and the athlete answers at 20:00. Answering a question does not refresh Garmin by
itself. Without the refresh, the record would say that the ride was skipped.

A run of the write step writes at most one record. The record of a plan is the one exception:
the write step first writes the records of its mesocycles that are still blank, then the
record of the plan.

### When the writer fails

The command that ran the write step carries on without the record. The next run tries again.
When the failure happens as the athlete answers, their words are stored first, and the reply
is a fixed line of thanks. The stored words make the record due (§4), so the next run of the
write step writes it.

## 6. The end of a plan

A retrospective is about the plan, not about the goal. A plan ends when the end date of its
last mesocycle has passed. The date of the goal plays no part.

**The rule.** When the last mesocycle of a goal's current plan has ended, the date check
creates a record of the plan. It covers the mesocycle records of that goal that end after the
last day of the goal's previous record of a plan, or all of them when there is none. Its
first day is the first day of the earliest one it covers.

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

**A goal called off.** Calling a goal off ends its plan the day before. The record of the
plan says that the goal was called off, and when. It covers the mesocycles recorded until
then. When there is none, the plan gets no record. If the goal is brought back while its plan
has not ended, the date check removes this record (§3).

**A plan deleted.** `plan rm` and `goal rm --purge` delete a plan for good. They delete its
records too. The list they show before asking includes the records. `plan wipe` deletes
every plan, and every record with them.

## 7. What `plan generate` reads

| What | Shown as | Size |
|---|---|---|
| The mesocycle under way | full detail, as today | about 5 KB |
| The mesocycle that finished most recently | full detail, plus its record | about 7.5 KB |
| Earlier mesocycles, of any goal, that no written record of a plan covers | their record | about 0.5 KB each |
| Every plan that has a written record | its record | about 0.7 KB each |

**Finished mesocycles come from the records.** The review no longer reads them from plan
versions. So a mesocycle that lives only in an old version is shown. The mesocycle under way
still comes from the current plan.

**Every goal counts.** The review prints the mesocycle records of every goal, the called-off
ones included, oldest first, under one line that names the goal. It leaves out the records
that a written record of a plan covers, because that record stands for them. Today the review
stops at three goals, and a goal called off is none of them.

It is Saturday 10 October. The athlete calls goal A off, and runs `plan generate` for goal B
the same morning. The record of A's plan is not written yet. So the review prints the records
of A's mesocycles. A week later the record of A's plan is written, and from then on it is
printed in their place.

**The latest one keeps its detail.** The mesocycle that finished most recently keeps its full
detail and its record, even when a written record of a plan covers it. A plan ends on
30 September, and its record is written on 2 October. On 5 October the athlete runs
`plan generate` for the next goal. The prompt holds the record of the plan, and under it the
full detail of the last mesocycle, 21 to 30 September. The first mesocycle of the new plan
is built on that detail.

**A record not written yet.** A finished mesocycle whose record has no lines yet is shown in
full detail, as today. So nothing is missing while a question is open.

**Where they go in the prompt.** The records of mesocycles are printed inside
`## PRIOR TRAINING REVIEW`. The records of plans are printed in a new section,
`## RETROSPECTIVES OF PAST PLANS`, oldest first, with no limit on their number. The
introduction of the review says that a record was written once, when the mesocycle ended, and
that the quoted line is the athlete's own.

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

### In the chat

The bot speaks in one voice, the companion's, since its expert persona was removed
(DESIGN_bot_simple_frontend.md §3). For the athlete, in one sentence: when a stretch of
training is done, the coach asks how it went, and then says what it saw.

It is Monday 26 October. The morning message arrives, and after it the question: "Your last
three weeks of training are done. How did they go for you?" Under it: `[Tell me]`
`[Nothing to say]` `[🕐 Not now]`. The athlete taps the first button and types "felt fresh
all the way, the long rides got easier". The reply is the sentence written for them: "You
kept your training steady these three weeks, and your long rides grew."

The sentence is written after the answer, so it never contradicts what the athlete just
said.

When the athlete taps "Nothing to say", the chat sends no sentence. The record is written
seven days after the end of the mesocycle (§4).

The athlete sees the sentence once, as this reply. No view of the plan shows it (§15).

The sentence follows four rules. It uses plain words. It holds no numbers. It holds nothing
private, because it can appear on a lock screen. It never opens with a miss
(DESIGN_bot_simple_frontend.md).

### On the terminal

The question appears in `sm queue answer`, in the terminal's wording. The reply is the same
sentence as in the chat.

`plan show` prints the records of the goal under their own heading, oldest first, one line
each: its id, its name, its dates, and how it ended or that it is not written yet.
`plan show -v` prints each record in full: its numbers, its lines, the sentence and the
athlete's words. This is the rule `plan show` already follows for the strategy: short by
default, the long text under `-v` (DESIGN_output_verbosity.md §5).

## 9. Correcting a record

A record is read as fact by every later `plan generate`. So a wrong one must have a way out.
One command gives it, and it does not delete the record.

| Command | What it does |
|---|---|
| `plan retro redo ID` | computes the numbers again and calls the writer at once. The new lines and the new sentence replace the old ones. The athlete's words are kept, and the athlete is not asked again. |
| `plan retro redo ID --words "text"` | replaces the athlete's words first, then does the same. `--clear-words` removes them. |

`redo` serves three cases: a record that is wrong, a writer prompt that was improved, and
words that were corrected. `--words` serves the athlete who typed an answer meant for another
conversation, and the answer that came after the question left the queue.

When the writer fails, the record keeps what it held.

## 10. The history from before

Nothing special runs on the day this feature is deployed. The first date check does what it
does every day. It records every mesocycle that has already ended in the current plans, and
every plan that has ended. It queues no question for those whose end is seven days old or
more. The write step then writes them over its next runs.

In the author's database that gives three mesocycles and one plan, for the goal of
30 September.

A mesocycle that finished inside a version replaced before that day is not recorded (§15). In
the author's database that is "Restoration, Recovery and Re-entry", 31 July to 10 August. A
program cannot tell which mesocycles of old versions were trained. One plan version of that
database lived for ten minutes, and it holds a mesocycle that was never trained.

The cut-short rule of §3 does read those old versions, like any replaced version. In the
author's database it records nothing: the most that was trained of a mesocycle before its
version was replaced is four days.

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
    ended_by TEXT NOT NULL,          -- 'finished' | 'replaced' | 'called_off'
    intent TEXT NOT NULL,            -- the description, or the strategy, as it stood
    numbers TEXT,                    -- JSON, exact values; NULL until written
    body TEXT,                       -- the record lines; NULL until written
    athlete_line TEXT,               -- the sentence for the athlete
    athlete_words TEXT,              -- as typed
    created_at TEXT NOT NULL,
    written_at TEXT,
    UNIQUE(objective_id, level, start_date),
    FOREIGN KEY (objective_id) REFERENCES objectives(id) ON DELETE CASCADE
)
```

`name` and `intent` are copied when the record is created. The writer may run a week later,
and by then the plan version that held them may have been replaced. `name` is shown, and it
is not part of the key (§3).

`UNIQUE` makes the date check safe to run twice. It inserts with `INSERT OR IGNORE`, so the
morning routine and a typed command cannot create the same record twice.

`goal rm --purge` removes the records through the foreign key. `plan rm` deletes a plan and
keeps the goal, so `delete_macrocycle_for_objective` deletes the goal's records itself.
`plan wipe` keeps the goals too, so `wipe_plans` empties the table itself.

A new table needs no hand-written `ALTER`. `SCHEMA_VERSION` takes the next free number when
this lands, and `_init_db` creates the table.

## 12. Privacy and safety

The athlete's words go into prompts as typed. Constraints and plan feedback already do. The
athlete owns the instance they write to, so this opens no new door.

A record travels to the model provider inside the `plan generate` prompt, like the rest of
the training data. Prompts are logged under `logs/llm_exchanges/`, as today.

The sentence for the athlete can appear on a lock screen. §8 gives its rules.

The operator can clear the athlete's words with `plan retro redo ID --clear-words`.
`goal rm --purge` deletes every record of a goal.

## 13. Touch points

| File | Change |
|---|---|
| `stamind/db/schema.py` | the `retrospectives` table; `SCHEMA_VERSION` |
| `stamind/db/retrospectives.py` (new) | create, list, write and remove records, as a mixin |
| `stamind/db/__init__.py`, `stamind/coach/service/__init__.py`, `stamind/coach/engine/__init__.py` | the new mixins in the three class lists |
| `stamind/db/periodization.py` | `delete_macrocycle_for_objective` also deletes the goal's records |
| `stamind/db/wipes.py` | `wipe_plans` also empties the table |
| `stamind/cycle_records.py` (new) | the date check: the three moments that create a record, and the removal of a record that became wrong |
| `stamind/coach/service/goals_constraints.py` | `goal_archive` runs the date check for its goal, then records the call-off. It reads the goal's own current version, because the goal already shows as called off when it runs |
| `stamind/coach/engine/retrospective.py` (new) | the writer's prompt and its call, as a mixin of `CoachEngine`; the sessions the athlete spoke about, printed with the week planner's formatter in `stamind/coach/formatting.py` |
| `stamind/coach/service/retrospective.py` (new) | the write step, as a mixin of `CoachService`; it reads the sessions of the record's days with `get_workouts` and keeps those with `athlete_notes` |
| `stamind/retrospective_question.py` (new) | the `retrospective` kind: its terminal and chat wordings, stale check, answer, drop |
| `stamind/athlete_queue.py` | the kind in `KINDS` |
| `stamind/coach/service/history_context.py` | finished mesocycles come from records, of every goal; a record stands in for the detail |
| `stamind/coach/engine/planning.py` | `## RETROSPECTIVES OF PAST PLANS`; the review's introduction |
| `stamind/cli/plans/retro.py` (new), `stamind/cli/plans/parser.py` | `plan retro redo` |
| `stamind/cli/plans/show.py`, `stamind/cli/common.py` | `plan show` prints one line per record, and the full record under `-v`; `print_plan_cascade` counts them |
| `stamind/cli/workouts/adapt.py`, `stamind/cli/plans/generate.py`, `stamind/cli/bot/views.py` | the date check, then the write step, at the start of `run_workout_adapt` and of `plan generate`, and in the morning routine after its once-a-day test |
| `docs/ARCHITECTURE.md` | the table, the writer, the two steps |

These implemented designs are amended when the code lands.

| Design | What changes |
|---|---|
| `DESIGN_backward_evaluation.md` §6 | the review reads stored records; "nothing is written" no longer holds for `plan generate` |
| `DESIGN_athlete_queue.md` §8 | one more kind |
| `DESIGN_session_notes.md` §5 | the retrospective writer reads the athlete's words about the sessions of a mesocycle, so a reason in them can outlive the two-week look back, inside the record |
| `DESIGN_plan_rollback.md` §6.1 | the review reads finished mesocycles from records, not from its walk over plan versions |
| `DESIGN_bot_simple_frontend.md` §4 | the morning routine runs the date check and the write step after its once-a-day test |
| `DESIGN_runway_nudge.md` §6 | the two steps run before the test that keeps the morning routine silent |
| `DESIGN_prompt_structure.md` §4 | the new section of `plan generate`, and the writer's sections |
| `DESIGN_plan_feedback.md` §2 | the answers are one more channel from the athlete |

This design reads nothing from `mesocycles.summary`, the one-line description that the
calendar mini app added to each mesocycle. That line says what a mesocycle is for. A record
says how it went.

## 14. Tests

All tests use `unittest`. The writer is stubbed by patching
`stamind.coach.engine.openrouter_client`.

| File | What it proves |
|---|---|
| `tests/test_cycle_records.py` (new) | a mesocycle that reached its end gets a record, however short; a dropped mesocycle gets a cut-short record at the next date check when seven days of it were trained, and none below that; a kept mesocycle creates none; a second run creates nothing; a called-off goal gets no later record; the date check removes a record that the current plan contradicts, and keeps one that it does not; a "called off" record of a plan goes when the goal is live again; a version replaced at 00:30 on the athlete's clock counts for that day |
| `tests/test_retrospective_writer.py` (new) | a record is due seven days after its end, and sooner when it holds the athlete's words and no lines; a dropped question does not make it due; the numbers of a plan are the sums of its mesocycle records; one record per run; a failed write is tried again on the next run; the record of a plan first writes its blank mesocycle records; the prompt follows the section rules; a session with the athlete's words in the record's days reaches the prompt |
| `tests/test_athlete_queue.py` | the kind's terminal and chat wordings; the answer stores the words and returns the sentence; a record cut short queues no question; the question goes stale seven days after the end of its record |
| `tests/test_analysis_prior_training.py` | finished mesocycles come from records, of every goal; the latest keeps its detail, also when a written record of a plan covers it; a record without lines falls back to the detail; a written record of a plan stands for its mesocycles; the plans section |
| `tests/test_cli_plans.py` | `plan retro redo` with and without `--words`, `plan show` with and without `-v`, `plan rm`, `plan wipe` |
| `tests/test_cli_bot.py` | the morning routine runs the date check and the write step after its once-a-day test and before the test that keeps it silent |

No test reads the source for an invariant. One function creates and removes records, and its
tests call it directly.

## 15. Not handled

- **Advice and learnings.** No learning is written from a record, and `data reflect` does not
  read records. A learning expires after 21 to 180 days without a week that confirms it, and
  a lesson from a whole mesocycle cannot be confirmed weekly. To look at again once real
  records exist.
- **The week planner.** It does not read records. The sessions of a new mesocycle are usually
  written before the old one ends, so it sees the old one in full.
- **A mesocycle cut short after fewer than seven days.** It gets no record.
- **Two plans that overlap in time.** Plans for different goals are expected to follow each
  other. When they overlap, the mesocycles of both get records. One way to get there: a goal
  is called off, another goal is planned over its days, and the first goal is brought back.
- **A plan or a goal that comes back late.** A rollback, or a goal brought back, after the
  mesocycle it interrupted has ended. Stamind does not remember that a version was away. So
  two records can share days, or a mesocycle trained in part is called finished. A rollback
  more than a week after `plan generate` does it too. On 10 September `plan generate` writes
  a version whose first mesocycle starts that day, and on 19 September the athlete rolls
  back. The version that was left is a replaced version like any other, so its mesocycle is
  recorded as cut short, 10 to 18 September. The mesocycle that came back gets its own record
  when it ends, and the two share nine days.
- **A recorded mesocycle made longer by a rollback.** `plan generate` shortens a mesocycle,
  it ends and is recorded, and a rollback brings the longer one back. The record and the
  athlete's answer are removed, and the athlete is asked again.
- **An answer after seven days.** The question has left the queue. The operator adds the
  words with `plan retro redo ID --words`.
- **A silent week.** When no command runs for more than seven days after a mesocycle ends, the
  athlete is not asked, and the record is written without their words. When no command runs
  between the day a goal is brought back and the end of its mesocycle, the "called off"
  records stay. The same holds after a rollback: when no command runs between the rollback
  and the end of the mesocycle that came back, its cut-short record stays.
- **A write that always fails.** The write step takes the oldest due record first, so a
  record that the writer can never write holds back the newer ones. That is a bug in the
  writer's prompt, and it is fixed there.
- **The history in old versions.** A mesocycle that finished inside a version replaced before
  the first date check gets no record (§10).
- **A limit on the records of plans.** None. Ten years of goals is about 15 KB.
- **Prompt size.** The science documents take 54.5 KB. That is a separate design.
- **The sentence outside the reply.** The athlete sees the sentence once, as the reply to
  their answer. The chat's plan view does not show it, and neither does the Goals & plan page
  of the calendar mini app. A finished mesocycle's sheet on that page says what the mesocycle
  was for, not how it went. The plan file that the page reads from a bucket
  (DESIGN_miniapp_storage.md §4) could carry the sentence. To look at again once real
  records exist.

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
| D8 | Cut short | A mesocycle dropped half-way gets a record over the days trained, with at least one full week. Refined by D33 | No hole in the long memory | Interview | 2026-09-27 |
| D9 | Plan level | A record of the plan stands for older plans | The history grows by about 0.7 KB per plan, not 6.5 KB per year | Interview | 2026-09-27 |
| D10 | Asking | One question after each mesocycle and one at the end of a plan. The athlete can decline | How it felt can only come from the athlete | Interview | 2026-09-27 |
| D11 | Companion athlete | One plain sentence for the athlete. The interviewer recommended the question alone | The athlete gets something back for answering | Interview | 2026-09-27 |
| D12 | Correction | The operator has a record written again | A wrong record steers later plans, and the writer's prompt will improve | Interview | 2026-09-27 |
| D13 | Identity | A record is created when the mesocycle ends, keyed by goal, name and start date, free of plan versions. Refined by D31 | Each `plan generate` rewrites the mesocycles as new rows | Red Team | 2026-09-27 |
| D14 | Order | Ask first, write after: on the answer, on a decline, or after seven days. The decline is changed by D41 | Garmin data settles late, and the sentence must not contradict the answer | Red Team | 2026-09-27 |
| D15 | End of a plan | A retrospective is about the plan, not the goal. One record per plan trained to its end | The athlete's own rule. `plan generate` cannot make a plan longer | Red Team | 2026-09-27 |
| D16 | Goal called off | `goal rm` ends the plan that day. Refined by D34 | The season that was called off is the one the next plan most needs | Red Team | 2026-09-27 |
| D17 | History and failures | A one-off script with the operator's confirmation. The date check runs before the plan changes. One record per run. One day between retries. The script is replaced by D38, the retry by D37, and the date check before the plan changes by D32 | A program cannot tell which old mesocycles were trained, and commands must stay fast | Red Team | 2026-09-27 |
| D18 | Text from `data reflect` | `plan generate` keeps replaying it. The goal of this design is long memory | It is about how the body responded, which a record does not hold | Red Team | 2026-09-27 |
| D19 | Week planner as a reader | Cut. Only `plan generate` reads records | Sessions are written before the mesocycle ends. It also conflicted with DESIGN_plan_feedback.md §7 | Red Team | 2026-09-27 |
| D20 | The athlete's words | Stored in their own field. The operator can replace or clear them | A message typed by mistake must not stay in every later prompt | Red Team | 2026-09-27 |
| D21 | Operator's view | `plan show` prints the records on the terminal. Refined by D28 | The operator must see a record to correct it | Red Team | 2026-09-27 |
| D22 | Calendar mini app | This design reads nothing from `mesocycles.summary` | The two lines say different things: what it is for, and how it went | Red Team | 2026-09-27 |
| D23 | Questions at the end of a plan | One question, about the plan | Two questions about the same days would arrive on one morning | Red Team | 2026-09-27 |
| D24 | Sentence about a plan | Shown as a reply only, not in the plan view. Since D37 this holds for every sentence | The plan view shows the new plan within days | Red Team | 2026-09-27 |
| D25 | Where this document lives | `designs/DESIGN_cycle_retrospective.md` | Every design document lives under `designs/` | Interview | 2026-09-27 |
| D26 | One voice in the bot | The question has a wording for the terminal and one for the chat. §8 is split by place, not by mode | The bot's expert persona was removed on 28 September | Rebase on `main` | 2026-09-30 |
| D27 | The athlete's words about sessions | The writer reads them for the mesocycle's days | They leave every other prompt after two weeks, and they state reasons that the numbers cannot | Rebase on `main` | 2026-09-30 |
| D28 | `plan show` | One line per record. The full record under `-v` | `plan show` became short by default on 28 September | Rebase on `main` | 2026-09-30 |
| D29 | `plan wipe` | It empties the records too | The same rule as `plan rm`: a record goes with its plan | Rebase on `main` | 2026-09-30 |
| D30 | Log label | The writer's call is logged as `retrospective_writer`, one label for both kinds of record | It is not a command, so it is named after what it does, like `strength_planner`. The first section of the prompt already says which kind it is | Discussion | 2026-10-01 |
| D31 | Identity | A mesocycle is the same across versions when its goal and its start date are the same. The name leaves the key | The model call inside `plan generate` may reword a name, and the athlete may rename a goal | Review | 2026-10-01 |
| D32 | Cut short, and undone | No command records a dropped mesocycle, and no command undoes a record. The date check works the cut out from the replaced versions, and removes a record that the current plan contradicts. It replaces the undo in `plan rollback` and `goal_reinstate` | The undo removed a right record after two runs of `plan generate` and a rollback. One rule in one place needs no command to remember anything | Review | 2026-10-01 |
| D33 | How short | A mesocycle that reached its end date always gets a record. One cut short needs seven trained days | The numbers are counted from the mesocycle's own start, not on calendar weeks. A six-day race week must not vanish | Review | 2026-10-01 |
| D34 | Called-off goals | The date check skips them. The plan ends the day before the call-off. A "called off" record of a plan is removed when the goal is live again and its plan has not ended | A called-off plan kept producing "finished" records. A goal brought back kept a false record that later prompts would read | Review | 2026-10-01 |
| D35 | Who is asked | Only a mesocycle or a plan that reached its end date gets a question. Its subject is the record's id. A record without a question waits seven days | For the athlete nothing ended when `plan generate` cut a mesocycle | Review | 2026-10-01 |
| D36 | Reach of the review | The mesocycle records of every goal, unless a written record of a plan covers them. It replaces the three goals for finished mesocycles | A season called off that morning was missing from the prompt | Review | 2026-10-01 |
| D37 | Cut | The one-day retry and `failed_at`, `question_subject`, `planned_end_date`, the date check in `status` and in `plan_apply`, the shorter listing of the plan being replaced, the sentence in the chat's plan view, and `plan retro words` as a command of its own | None of them served a week that a plausible athlete has | Review | 2026-10-01 |
| D38 | History | No script. The first date check records what has ended in the current plans | The script rescued one mesocycle of eleven days in the author's database | Review | 2026-10-01 |
| D39 | Kept against the review | The record of a whole plan, the cut-short record, and the Garmin refresh in the write step | The author's rule (D15). A replan after a week or more is a plausible week. The refresh is what lets an evening answer see an afternoon sync | Review | 2026-10-01 |
| D40 | Detail at the end of a plan | The mesocycle that finished most recently keeps its full detail and its record, even when a written record of a plan covers it | §7 gave two answers for that mesocycle. The first mesocycle of the next plan is built on full evidence (D6) | Fourth review | 2026-10-01 |
| D41 | When a record is due | Seven days after its end, or sooner when it holds the athlete's words and no lines yet. The rule reads the record alone. After "Nothing to say" the record waits its seven days. It changes the decline of D14 | The queue has no lookup by subject, and it closes a stale question only when a walk meets it. A decline owes no reply, so nothing is lost by letting the Garmin data settle | Fourth review | 2026-10-01 |
| D42 | Stored numbers | Only the values of a record's first line. The load of each week and the zone shares are not stored. The numbers of a plan are the sums of its mesocycle records, with fitness and each benchmark taken as first and last value | Nothing printed those two from a record. The weekly figures start on Monday, and a mesocycle is counted from its own start (D33) | Fourth review | 2026-10-01 |
| D43 | Date check after a rollback | Cut. A rollback and a goal brought back both wait for the next date check | It only made `plan show` right a day sooner, and a goal brought back had no such step. `plan generate` runs the date check before it reads a record | Fourth review | 2026-10-01 |
| D44 | Day of a replacement | Read on the athlete's clock | The time is stored in UTC, and one day decides whether seven days were trained | Fourth review | 2026-10-01 |
| D45 | Old versions on the first day | The cut-short rule reads the versions replaced before the first date check too. What is lost is a mesocycle that finished inside one. It makes D38 exact | §10 said less than the rule of §3 does. In both live databases the rule records nothing there | Fourth review | 2026-10-01 |
| D46 | A mesocycle that ended inside the version replaced last | It gets no cut-short record. When several replaced versions hold a mesocycle, the one replaced last decides alone: if the mesocycle had already ended on the day that version was replaced, nothing is recorded | An older version would otherwise call a mesocycle "cut short" that a later version let finish. It is the case §10 says is not recorded | Implementation | 2026-10-01 |
| D47 | The write step under `--show-llm-prompt-only` | It writes nothing. The date check still runs | The writer would print its own prompt and exit before the prompt that the command was asked to show | Implementation | 2026-10-01 |
| D48 | `plan retro redo` on the command line | `plan retro` takes the action as a word, with `redo` as its one value, then the ID | The command tree has two levels everywhere. `bot capture` takes its intent the same way | Implementation | 2026-10-01 |
| D49 | A blank record in `plan show` | Its line says how it ended and "not written yet", both | A record cut short and not written yet would otherwise look like one that reached its end | Implementation | 2026-10-01 |

## Dependency Graph & Implementation Order

```
1 Records --> 2 Writer --+--> 3 Question --+--> 5 Plans
                         |                 +--> 6 Views
                         +--> 4 Reader
```

Each step is one commit. Each step updates `docs/ARCHITECTURE.md` and the designs it amends
(§13).

1. **Records.** The table, `stamind/db/retrospectives.py`, the date check with its three
   moments and its removal rule, the deletes. No model call yet, and nothing reads the
   records.
2. **Writer.** The numbers, the writer's prompt, the write step. Until step 3 no question
   exists, so every record is written seven days after its end.
3. **Question.** The `retrospective` kind, the answer that runs the writer, the sentence as
   the reply.
4. **Reader.** The review built from the records of every goal, the latest mesocycle in full,
   the fallback to the detail.
5. **Plans.** The record of a plan, its call-off and its removal, one question at the end of
   a plan, `## RETROSPECTIVES OF PAST PLANS`.
6. **Views.** `plan show`, `plan retro redo`.
