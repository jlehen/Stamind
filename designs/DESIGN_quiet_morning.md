# Design: A quiet morning

**Status:** Implemented 2026-10-18 · **Date:** 2026-10-17

The week planner is the model call inside `workout adapt` that rewrites the sessions ahead. The
morning push is the message the bot sends at the athlete's morning time. With the `adapt-first`
setting on, the push asks the week planner before it renders that message. This design makes the
push ask only when there is something to ask about. A morning with nothing to ask about is a
**quiet morning**.

In this document a **run** is one execution of `workout adapt`, never a training run. **The
picture** is what a run saw when it read its inputs, reduced to a few identifiers and hashes,
and kept so that the next morning can tell what is new.

## 1. The problem

It is Tuesday 13 October. Monday was a gym day. The athlete slept well. At 08:00 the push asks
the week planner, which reads about 61,500 tokens and answers: "This morning is your best in two
weeks. No change." Wednesday, Thursday and Friday go the same way: a session done as planned
the day before, a normal night, a 61,500-token call, "no change".

On other normal mornings the week planner changes something anyway. Saturday 10 October it
removed stale lines about an FTP test. Monday 12 October it added a cue to hold each sprint the
full 30 seconds. Neither change was asked for, and neither night was bad.

The push already has one skip. It does not ask again when a run of this morning had the night's
sleep score in hand and nothing has been trained since (DESIGN_waiting_proposal.md §5). That
skip only ever saves the second call of a morning. The first one is spent every day.

## 2. The rule

> With `adapt-first` on, the morning push asks the week planner when something is new since the
> last run, or when a night since the last one a run had in hand is not normal. Otherwise the
> morning is quiet, and no model is called.

Three kinds of run are never quiet. A run with a message, which is every message to the coach
from the chat and the "Feeling tired" and "Can't today" buttons: the message is new by
definition. A run typed in a terminal: typing it is the request, and there is no `--force` flag
because nothing stands in the way. And `workout tweak`, which is a request too.

A normal night on its own is not a reason to ask. It is Friday. Thursday's ride was done as
planned, the night was normal, nothing else happened. The morning is quiet. It is the next
Friday. The night was normal, but Thursday's ride never happened. The morning runs.

## 3. What is new

Each run takes the picture when it reads its inputs, in the service, where every input the week
planner reads is gathered (`coach/service/adapt.py:workout_adapt`). The picture travels on the
proposal and is written by whichever step persists the run's outcome: applying the proposal,
saving it for a tap, or recording that nothing changed. It replaces the `sleep_seen` mark, which
only remembered the night.

The next morning, the push takes a fresh picture with the same function and compares the two.
Every difference is listed, because the journal names them (§5). The comparison never reads
the sources' timestamps: constraints and goals have no edit time, a removed row leaves no time
behind, and an activity synced a day late carries a start time older than the run that never
saw it.

The picture holds, and a morning runs when:

| Key | What the picture keeps | New when |
|---|---|---|
| `date` | The day the run was evaluated on | — (used by `missed`) |
| `night` | The newest day up to `date` with a sleep score: the mark `sleep_seen` keeps today | See §4 |
| `activities` | The ids of the activities in the lookback window | An id is present now that was not in the picture, and the activity is not clean (below) |
| `missed` | — | A non-rest session dated from `date` to yesterday has the verdict missed |
| `written` | The id of the newest change that wrote a session and is not of kind `adapt`, as the run read it | A newer such change exists: `workout generate`, `workout tweak`, a rollback, a goal stood down or reinstated. A run's own write and a tap on a `workout adapt` proposal are both `adapt`, so neither is news: the week planner wrote them. A tap on a tweak's proposal is `tweak` and is news, as the tweak itself was |
| `constraints` | `sha256` over `plan_inputs.clean_constraints_all` of the constraints the run reads: those overlapping today to the mesocycle's end | The hash differs: one was added, edited, ended early or removed |
| `signals` | The `(id, updated)` pairs of the daily signals in the run's signal window | A pair is present now that was not in the picture |
| `plan` | The active macrocycle's id, the active mesocycle's id and end date | Any of the three differs: a new plan version, or a new mesocycle began |
| `goals` | `plan_inputs.goals_hash` over the upcoming goals | The hash differs |
| `benchmarks` | The largest id in the logbook (`benchmark_results`) | A larger id exists |
| `profile` | A hash of the whole `user_profile` section of config.yaml | The hash differs |
| `science` | A hash of the athlete's science documents (`plan_inputs.athlete_science_documents`) | The hash differs |

And one source is asked live rather than remembered: the strength planner. It is the model call
that writes a gym session's exercises, sets, reps and kilograms, and it runs inside every
`workout adapt`. Today it decides on its own whether it has work: a strength session ahead with
no sets, or one whose kilograms were checked before the strength history last changed
(`strength/planner.py:run`, DESIGN_strength_tracking.md §9). That history changes on answers
that create no activity: naming a set the watch guessed, "yes, final", a discard. The decision
reads only the database, so it is split out of `run` and the push asks it. If it says there is
work, the morning runs. This also covers a strength day with a brief and no exercises, which
`workout generate` normally never leaves behind.

**A clean activity is not new.** An activity is clean when the coach has nothing to look at in
it: it matched no session and its load is below `coach.minor_activity_load_threshold`, the
cut `unplanned_kind` uses to grey an activity out in `status`; or it matched a planned session
with the verdict done and no reason attached, so no load mismatch, not cut short, not "felt
harder than measured". A matched activity is never minor: a 60-minute run stopped after 12
minutes with a tight calf has a small load and the verdict partial, and it is new. It is
Thursday 15 October. Wednesday's 85-minute ride matched its session and was done. The morning
is quiet. It is Friday 9 October. Thursday's three-hour hike broke a planned rest day. The
morning runs.

**A missed session is new.** Both rules read one call,
`analytics.compare.adherence_verdicts(db, date, today, today)`, the function the push already
uses to grade today's sessions for the briefing. Over that window a session dated before today
with no activity is missed, and today's untrained sessions are pending, not missed. The
evaluation date is included because that day's session was still pending when the run looked
at it. A session done that day is not counted again: it is clean. A new activity is clean
when it is the one a verdict in that window graded done. An activity dated before `date` is
outside the window, so the gate sees it as unmatched: new unless it is minor. A late-synced
ride runs the morning it appears; a late-synced 15-minute walk does not. A swim at 06:00 that
matched today's session is done, so clean.

**What is not new.** Learnings rewritten by `data reflect`, a changed setting, a proposal the
athlete has not answered (§5), a Garmin re-pull of an activity already in the picture, an
answer to "Was that the session, cut short?" (§8), and a session note: its only writer is a
run with a message, which read the words as the message (`cli/candidates.py:keep_note`), so a
note is never news to the next run.

## 4. The night

A night is graded by the three verdicts `analytics/baselines.py` already gives to colour `status`
and `data show-metrics`: HRV is suppressed below the 28-day mean minus one standard deviation,
resting HR is elevated above the mean plus one standard deviation with a floor of 3 bpm, and
sleep is poor below a score of 60. No new threshold and no new setting.

The push grades the days after `night`, up to today, that have a sleep score, on all three
verdicts. With no `night` yet, because no day up to `date` had a sleep score, it grades every
day up to today that has one, which is none until the first arrives. A quiet streak grades the
same normal nights again each morning; that is a few rows of the metrics cache. A night is
not normal when any verdict is suppressed, elevated or poor. One such night makes the morning
run. A day without a sleep score is unknown, even when resting HR is already in, because
Garmin's daily summary fills before the sleep is scored; a reading the baseline cannot grade
yet is unknown too. Unknown is quiet.

Grading every night since the last one in hand keeps today's skip and closes a hole. It is
Thursday, HRV is suppressed. At 07:05 the athlete writes "rough night"; the run reads the night
and saves a proposal. At 07:10 she taps "Keep it as planned". At 08:00 the push finds that the
last run had Thursday's night in hand, and nothing else is new: quiet, as today. It is
Saturday. She sleeps until 09:30, the watch is not synced at 08:00, and Saturday's morning is
quiet. At 09:45 the watch syncs: sleep 41. Sunday 08:00: Saturday's night is after the last
one in hand and it is poor. The morning runs.

The order inside the push matters. Its own Garmin refresh is throttled to `refresh_minutes`,
so at 08:00 the sleep score is often not in yet. The push keeps its forced pull when the sleep
score is missing (DESIGN_bot_simple_frontend.md §4.2) and grades the night after it, never
before.

## 5. The quiet morning

In the chat, a quiet morning looks exactly like a morning whose run changed nothing. Today such
a run prints no line about the coach, so the briefing shows the schedule and its usual buttons
either way. The strength planner's notice is not printed, since it did not run.

The journal records one `note` at info level naming the reason: "Quiet morning: the night is
normal and nothing is new since Thursday 08:00", or "Quiet morning: nothing is new since Friday
07:05 and no night since has a reading". When the morning runs, the note says why: "Asking the
week planner: Thursday's ride is missed; a constraint changed". DESIGN_logging.md §4.2 is not
amended, because `note` is the general sentence it already allows.

A quiet morning writes no change row, so `workout batches` shows nothing for it; the journal
is its only trace. Today a run that changes nothing writes a row that `workout batches` lists
as `(held)`.

A proposal the athlete has not answered stands. It is Thursday 21:00. She writes to the coach
about Saturday, the week planner proposes a change, and she does not answer. Friday 08:00: the
night is normal and nothing else is new. Thursday's proposal keeps its two buttons, Friday's
briefing has its usual row, and a tap on either works as today. Nothing new happened, so the
coach has nothing new to say.

A tap on "Change it" writes no picture, and its change is of kind `adapt`, the week planner's
own, so the next morning does not count it (§3). It is Thursday 07:05, HRV is suppressed. She
writes "rough night"; the run saves a proposal and writes its picture. At 07:10 she taps
"Change it". At 08:00 the stored picture is the 07:05 one, the tap's change does not count,
nothing else is new, and Thursday's night is in hand: quiet, as today's skip would be.

## 6. The gate fails open

A gate that breaks must not look like a quiet morning. No picture stored yet, a picture that
will not parse, a key missing from an older picture, or any exception inside the comparison:
each asks the week planner, and the journal says so at warn level. The gate has its own `try`,
apart from the one around the week planner's run, so the push still renders the stored schedule
when the planner fails, as today.

Only a run evaluated on today writes the picture. `workout adapt --date` on another day writes
nothing, so a preview of next Saturday cannot make next week's mornings quiet.

The picture is JSON in one settings row; its lists are compared as sets.

## 7. What goes away

- `_adapted_this_morning` in `cli/bot/views.py`, with `saw_the_night_on` in
  `cli/workouts/proposal.py`. The gate subsumes them. `trained_since` stays: a proposal's
  out-of-date rule 3 still uses it. `newest_adapt` in `db/workout_history.py` stays too:
  `cli/bot/hand_off.py:_coach_looked` reads it to tell whether the coach looked after a goal
  or constraint edit from the chat. A quiet morning writes no `adapt` row, so after one the
  hand-off still says the coach has not looked, which is true; and such an edit changes the
  goals or constraints hash, so that morning is never quiet.
- The `sleep_seen` field of the saved proposal's payload and `RevisionProposal.sleep_seen`. The
  picture is one row of the `settings` table, key `adapt_last_seen`, like the morning marker
  `push_morning_last`: no column, no migration, one home. The `sleep_seen` column of
  `workout_changes` leaves the CREATE text, so a fresh database has none; the two live
  databases keep it as a dead column nothing reads or writes, because the schema is
  CREATE-only and cannot drop one. The INSERT in `db/workout_change.py` stops naming it.
  The schema stamp moves to 28 because the CREATE text changed; a live database re-runs
  the `CREATE IF NOT EXISTS` statements once, which changes nothing in it.

## 8. Not handled

- A slow drift across clean days. Rides at the right load but in the wrong zones for a week, or
  fitness sliding while every day is done as planned, wait for the next morning that runs: a
  bad night, a missed session, a message, a mismatch, a new mesocycle.
- A night that arrives after the quiet decision on the same morning is graded the next morning,
  not that day. Today's push runs blind in that case and then never looks again either.
- A constraint that ends makes one morning run, because it leaves the hash. A removed daily
  signal or a removed logbook row does not count as new.
- An answer to "Was that the session, cut short?" waits for the next morning that runs. It is
  Monday, the ride stopped at 12 minutes. Tuesday runs anyway, on the new activity. The
  question goes out after the briefing and she answers "No" at 08:30. Wednesday is quiet if
  nothing else is new, and the week planner reads Monday as missed rather than partial the
  next morning that runs.
- Two runs that overlap, a message at 07:58 and the push at 08:00, write the picture in the
  order they finish. When the older one wins, the next morning may run once more.
- An athlete whose watch rarely syncs before the morning time gets quiet mornings and a
  graded night the morning after, every day. There is no setting to run blind instead.
- A night whose HRV was scored but whose sleep was not is unknown: `night` and the grading
  follow the sleep score alone.
- An unanswered proposal in a week with a gym session and new lifted sets makes the mornings
  run until it is answered or a run changes nothing. A saved proposal records no strength
  checks, so the strength planner's test keeps finding work. Not a regression: today every
  morning runs.
- The companion instance has `adapt-first` off. Nothing changes there.

## 9. Choices made without asking

Each is listed so it can be overruled.

1. The picture lives in the `settings` table under `adapt_last_seen`, not in a column of
   `workout_changes` and a field of the saved proposal. One home, no migration, nothing can
   disagree with itself.
2. `workout tweak` writes no picture: `workout_adapt` fills it only when `not tweak`. A tweak's
   prompt leaves out the fatigue-reading sections (DESIGN_workout_tweak.md §3.2), so it did not
   weigh the night, and today's skip already ignores a tweak (`newest_adapt` reads `adapt` rows
   only). A tweak at 07:00 does not make the 08:00 push quiet.
3. `written` leaves out every change of kind `adapt`, so a run never counts its own write, and
   a tap on a proposal writes no picture. The last writer wins when two runs overlap (§8).
4. The constraints hash covers every constraint the run reads, those overlapping today to the
   mesocycle's end, not only the plan-shaping ones `plan_inputs.constraints_hash` covers,
   because the week planner reads all of them.
5. "Clean" uses the verdict's reasons as they stand, so a session the adherence analysis flags
   for a 15 % load mismatch is not clean. The tolerance is `_adherence_tolerance`'s, unchanged.
6. The journal line is a `note`, not a new event name.
7. The picture is taken by one function, called by the run to remember and by the push to
   compare. It reads the database only.

## 10. Build order

One step. It works on its own and removes what it replaces.

1. The picture (§3) and the night grading (§4), the gate in the push (§2, §5, §6), the strength
   planner's work test split out of `run`, and the removals of §7, with the tests below.

## 11. Touch points

| Where | What |
|---|---|
| `stamind/coach/picture.py` (new) | Takes the picture from the database; compares two and names each difference; grades the nights since the last one in hand with `analytics/baselines.py`. Reads only the database and config. Under 150 lines; it is a concept of its own |
| `stamind/coach/service/adapt.py` | `workout_adapt` takes the picture where it reads its inputs and puts it on the proposal in place of `sleep_seen`, when `not tweak` |
| `stamind/coach/proposals.py` | `RevisionProposal.seen` replaces `sleep_seen`. The saved proposal's payload does not carry it, and a tap writes no picture |
| `stamind/coach/service/revision_apply.py` | `workout_revision_apply` and `workout_revision_record_no_change` write the picture to `adapt_last_seen` when the run was evaluated on today and the proposal carries one |
| `stamind/cli/workouts/proposal.py` | `save` writes the picture from the live proposal; `saw_the_night_on` and the payload's `sleep_seen` go |
| `stamind/strength/planner.py` | The "anything to write or recheck" decision of `run` becomes a function the push can call without a proposal; `run` calls it |
| `stamind/cli/bot/views.py` | `_morning_adaptation`: forced pull, then the gate in its own `try`, then the run; the journal note; `_adapted_this_morning` goes |
| `stamind/db/workout_change.py`, `db/schema.py` | The INSERT stops naming `sleep_seen`; the column leaves the CREATE text |
| `stamind/db/workout_history.py` | A sibling of `newest_change_with_sessions` that leaves out kind `adapt`; `newest_adapt` stays |
| `stamind/settings.py` | The `adapt_last_seen` key beside `MORNING_MARKER` |
| `docs/ARCHITECTURE.md` | The adaptation flow, the `workout_changes` table, the `adapt_first` row of the config table, the settings-table markers (the "guarded DDL" sentence under `athlete_metrics_cache` this row once named was already gone) |
| `docs/DOMAIN_MODEL.md` | The `sleep_seen` row |

Implemented designs amended when it lands: DESIGN_waiting_proposal.md §3 (the saved proposal
no longer carries "whether the run had last night's sleep score") and §5 ("Once a morning" is
now this document); DESIGN_bot_simple_frontend.md §4.2 (the skip and the forced pull);
DESIGN_strength_tracking.md §9 (the work test is also asked by the push).

Existing tests that change: the `sleep_seen` skip tests in `tests/test_cli_bot.py` (lines 380
to 450) are replaced by the gate's; `tests/test_waiting_proposal.py` asserts on
`newest_adapt()["sleep_seen"]` at line 162 and on `newest_adapt()` at line 306, and the first
goes.

Tests, one per rule: a normal night with nothing new is quiet; a missed session runs; an
activity done as planned is quiet and a partial one runs, a cut-short one under the minor
threshold included; an unmatched minor activity is quiet; an activity this morning that
matched today's session is clean; an activity synced late runs the morning it appears, a
minor one does not; a tweak writes no picture and its change is news; a tap writes no picture
and the morning after a same-day tap is quiet; each hashed source runs when it changes
(constraint ended early, goal edited, profile edited, science edited, benchmark logged) and
not when it is merely re-read; a new mesocycle runs; a
suppressed night after the last one in hand runs, a night the last run had in hand does not,
and an unknown night is quiet; the strength planner's work test alone runs the morning; a
`--date` run writes no picture; no picture, a broken picture and an exception in the gate all
run and journal a warning; the forced pull happens before the night is graded; a terminal run
and a `-m` run are never gated; a quiet morning writes no picture and the next morning compares
with the last run's; after an apply the run's own change is not new.

## Decisions Log

| ID | Topic | Decision | Rationale | Source | Date |
|---|---|---|---|---|---|
| D1 | One rule | A normal night skips only when nothing else is new | A missed ride must not wait for a bad night | Interview | 2026-10-16 |
| D2 | Rare sources | Profile, science, benchmark and goal edits count as new; learnings and settings do not | The week planner reads the first four directly | Interview | 2026-10-16 |
| D3 | Thresholds | The verdicts in `analytics/baselines.py`, no knob | One bar for the colours and the skip; DESIGN_settings.md §1 keeps thresholds out of settings | Interview | 2026-10-17 |
| D4 | Unknown night | A night that cannot be graded is quiet | A missing sync is not a bad night; a blind run cannot judge it | Interview | 2026-10-17 |
| D5 | Quiet morning in chat | Looks like a no-change morning; the journal names the reason | A no-change run already prints nothing about the coach | Interview | 2026-10-17 |
| D6 | Terminal | A typed run always runs, no `--force` | Typing it is the request | Interview | 2026-10-17 |
| D7 | Open proposal | Stands with its buttons; not new | Nothing new happened, so nothing new to say | Interview | 2026-10-17 |
| D8 | Strength planner | Its own work test is a source the push asks | Naming answers move the strength history without an activity; "I will look again tomorrow" relies on the next run | Red Team | 2026-10-17 |
| D9 | Clean days | An activity done as planned, or minor, is not new | Otherwise only the morning after an empty day could be quiet: none of the last four | Red Team | 2026-10-17 |
| D10 | Forced pull first | The night is graded after the forced pull | The push's refresh is throttled; the score is often not in at 08:00 | Red Team | 2026-10-17 |
| D11 | Fail open | No picture or any gate error asks the week planner | A broken gate must not look like a quiet morning | Red Team | 2026-10-17 |
| D12 | No timestamps | Hashes and identifier lists, never times | Constraints and goals have no edit time; late syncs carry an old start time | Red Team | 2026-10-17 |
| D13 | Nights since | Every night after the last one in hand is graded | Keeps today's once-a-morning skip; grades a night synced after a lie-in | Red Team | 2026-10-17 |
| D14 | Storage | One `settings` row, `adapt_last_seen`; `sleep_seen` dropped | No migration on two instances, one home | Red Team | 2026-10-17 |
| D15 | Picture at read time | Taken when the run reads its inputs; `--date` runs write none | The inputs are the ones the week planner read; a preview of next week cannot quiet it | Red Team | 2026-10-17 |
| D16 | Two more sources | Cut-short answers and the plan version count as new | One identifier each; both change what the week planner reads | Red Team | 2026-10-17 |
| D17 | Tweak | `workout tweak` writes no picture | Its prompt leaves out the fatigue sections; today's skip already ignores a tweak | Review | 2026-10-18 |
| D18 | Session notes | Not a source | Their only writer is a run with a message that read the words | Review | 2026-10-18 |
| D19 | Minor means unmatched | A matched activity is never minor; one `adherence_verdicts` call over `[date, today]` | A cut-short session has a small load and must run the morning | Review | 2026-10-18 |
| D20 | Which picture wins | Superseded by D22 | — | Review | 2026-10-18 |
| D21 | Dead column | `sleep_seen` stays in the live databases; `newest_adapt` stays | The schema is CREATE-only; the hand-off question reads `newest_adapt` | Review | 2026-10-18 |
| D22 | `written` | Leaves out kind `adapt`; a tap writes no picture; the last writer wins | A run's own write and a tap are the week planner's own; one query replaces `taken`, a tap rule and an apply rule | Review | 2026-10-18 |
| D23 | Cut-short answers | Not a source; replaces the first half of D16 | The morning after the short ride runs anyway; the answer is a one-word correction to a day already reacted to | Review | 2026-10-18 |

## Dependency Graph & Implementation Order

Each step depends on the ones before it.

1. `coach/picture.py`: take, compare, grade the nights. Pure reads; tests on a test database.
2. `workout_adapt` takes the picture when `not tweak`; `RevisionProposal.seen`; the three
   writers: `proposal.save`, `workout_revision_apply`, `workout_revision_record_no_change`.
3. The strength planner's work test, split out of `run`.
4. The gate in `_morning_adaptation`, with the forced pull first and its own `try`.
5. The removals of §7, the CREATE text, the docs and the amended designs.
