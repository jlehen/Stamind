# Design: `workout tweak`, and the end of the four hand-edit commands

**Status:** Implemented (rev. 3), not reviewed · **Date:** 2026-09-18 (rev. 3)

Revision 3 changes §4 after a first review comment. The week planner no longer quotes the
athlete's message at the end of the brief. It writes what the athlete asked for into the
brief, in its own words, and only the part that concerns that session.

Revision 2 adds `workout swap` and `workout restore` to the commands that go. That changes
one thing in the design: a tweak may now touch more than one day, because moving a session
is a tweak (§3.1). Revision 1 was written and then built without a review. Revision 3 is
now built on top of it, in the worktree `workout-tweak`. §9 says what the build found.

## 1. The problem

Today the athlete can change their schedule in two ways.

The first way is to tell the coach. `workout adapt -m "knee is sore"` gives the message to
the week planner, the model call that writes the sessions. The week planner answers with a
changed schedule. The athlete sees a preview and says yes or no.

The second way is to edit the schedule by hand, with no model call. There are four commands:

- `workout add 2026-09-26 hiking "Hike with friends" --duration 240` writes a session exactly
  as typed.
- `workout rm 42 "work dinner"` cancels session 42.
- `workout restore 42` brings a cancelled session back.
- `workout swap 2026-09-24 2026-09-25 "rain"` exchanges two days.

The second way costs code that the first does not need.

**A session typed by hand is not the coach's.** So TrainMate has to remember that it is the
athlete's own, everywhere:

- The database derives a field, `source`, that says "manual" for such a session.
- `workout generate` must answer for every manual session in its span, even far outside the
  days it has committed to. It prints a notice when it replaces one.
- A coach session that takes a manual session's place may not continue its history, or it
  would show `[Manual]` on the Calendar.
- The Calendar keeps the event of a removed manual session when it would tear down any other.
- The strength planner is the model call that writes a strength session's exercises, sets
  and kilograms. It shows a manual strength session "as context" and never writes it. So a
  strength day added by hand has no exercises and no loads.
- The projection of future load, and the nudge that says "your schedule runs out soon", both
  skip manual sessions when they look for the last planned day.

**A swap needs its own safety checks.** `workout swap` has no coach behind it, so it carries
a small copy of the coach's judgement: three consecutive hard days, a weekly load that jumps
by 30 %, a session that crosses into another mesocycle. It warns and asks.

**`workout restore` exists for `workout rm`.** Its help text has to say that it is not
`workout rollback`. `workout rollback` has to say that it is not `workout restore`. A
caveat repeated on both sides means one of the two commands is wrong.

Neither database uses much of this. The author's has one `swap` on record, and no `add`,
`rm` or `restore`. The companion's has one `rm`, which was a repair.

## 2. The decision

There is one author: the coach. The athlete changes the schedule by asking.

- `workout add`, `workout rm`, `workout restore` and `workout swap` are removed. There is no
  deprecation period: the author runs every instance.
- `workout adapt -m` stays what it is. The athlete says how things are. The coach decides
  what to change, anywhere from today to the end of the mesocycle.
- A new command, `workout tweak`, is for when the athlete has decided. They say what they
  want, and the coach writes it.
- `workout rollback` stays. It is the only undo.

The difference, in one sentence: with `workout adapt` the coach decides what changes, and
with `workout tweak` the athlete decides and the coach writes it.

## 3. `workout tweak`

### 3.1 The command

```
workout tweak "Saturday: a 4 hour hike with friends instead of the ride"
workout tweak "swap Thursday and Friday, it rains on Thursday"
workout tweak "put Tuesday's run back"
workout tweak -d +1d "I can't train, drop it"
workout tweak "Friday: step-ups instead of belt squats, the machine is broken"
```

The message is required. `-y` applies without asking. `--no-pull` and the LLM debug flags
work as on `workout adapt`.

**Which days a tweak may change.** Only the days the request is about. "Saturday: a hike"
is about Saturday. "Swap Thursday and Friday" is about Thursday and Friday. Every other day
stays exactly as it is, whatever the metrics say.

The week planner reads the days off the message and returns them as `tweak_dates`.
`-d DATE` is for a message that names no day ("make it shorter"). It may be given more than
once.

Revision 1 allowed one day only. That was enough while `workout swap` existed. Without it,
"move Thursday's ride to Friday" has to be a tweak, and it touches two days.

Adding, removing and bringing back all work the same way as changing. A free day holds a
rest-day row, so "add a swim on Sunday" is a change to Sunday. "Drop Thursday" turns
Thursday into a rest day.

"Put Tuesday's run back" needs one addition. Today the adapt prompt lists a cancelled
session only when the athlete called its goal off. The tweak prompt lists every cancelled
session in its range, whoever cancelled it, with its title, duration and load. The week
planner then writes the run again from that line. When the whole change was a mistake,
`workout rollback` is the better tool, and the command's help says so.

### 3.2 It is `workout adapt` with a narrower job

`workout tweak` runs the same code path as `workout adapt`. It pulls Garmin data, builds the
same context, makes the same week planner call, shows the same preview, and applies through
the same function. Two things differ.

**The TASK section of the prompt.** `workout adapt` asks "does the athlete's state call for
a change?". `workout tweak` says:

- The athlete asks for a change. Find the days it is about, and return them as
  `tweak_dates`.
- Change only those days. Every other date stays as planned.
- Do what the athlete asks. It is the athlete's call. If the request looks unwise, do it and
  say so in one sentence. Three hard days in a row after a swap is that kind of sentence.
  Refuse only what is clearly unsafe given the recovery metrics.
- Write the request into each changed session's `change_reason`: "On request: hike with
  friends in place of the long ride."

The sections of the adapt TASK that are about reading fatigue are left out. They answer a
question this run does not ask. The rest is shared: what may not be touched (a session
already trained), how to write a strength day, how to move a session, the benchmark rule,
the intensity target, and the two "second jobs" that turn a message into a constraint or a
daily signal to confirm.

**What TrainMate enforces after the reply.** The model is told which days it may change,
and TrainMate does not take its word for it:

- The days are the ones given with `-d`, else `tweak_dates`. When the reply changes sessions
  and names no usable day, the run stops and says: name the day with `-d`.
- Every day must lie between today and the end of the current mesocycle. That is as far as
  `workout adapt` reaches (DESIGN_mesocycle_boundary.md §1). Past that, the command refuses.
- Every proposed session on another date is dropped. So is a move whose other end is on
  another date.
- The strength planner runs over those days only.
- A tweak marks no constraint as honoured. That mark means "a coach pass had authority over
  every remaining day of this constraint", and a tweak has authority over a few days.

### 3.3 What a tweak leaves behind

A tweak is recorded as a change of kind `tweak`. It appears in `workout batches`, and
`workout rollback` undoes it like any other change.

The kind is its own, rather than `adapt`, because `adapt` means "the coach eased this
because of how you were doing". Two things read that meaning:

- The Calendar title `[Adapted]`. A tweaked session shows a plain title with its `Reason:`
  line, and "Changed on request" in its History.
- The count of easings, which stops the coach from cutting an already-cut session twice. A
  ride the athlete shortened for a dinner is not an easing. A tweak also resets that count,
  the way `workout generate` does: the session has been written again, so earlier easings no
  longer describe it.

A moved session keeps its id, its history and, for a strength day, its kilograms. This is
what a move in `workout adapt` already does.

**How a later run knows the athlete asked for it.** It is Monday 21 September. The athlete
runs `workout tweak "Saturday: a 4 hour hike with friends instead of the ride"`. Saturday
now holds a hike whose reason reads "On request: hike with friends in place of the long
ride." On Tuesday morning `workout adapt` runs. The week planner is shown every planned
session with its reason. It reads that line beside Saturday's hike, and leaves the hike
alone unless the metrics really call for a change. This is how a change made through
`workout adapt -m` has always been remembered. No tag and no `source` are needed.

`workout generate` rewrites its whole span, except the days inside the commitment window.
A tweak three weeks out does not survive it. A wish that must survive is a constraint, and
the tweak offers to save one. The message goes through the same extraction as
`workout adapt -m`, so "hike with friends on 10 October" comes back as a constraint to
confirm.

### 3.4 The bot

The router is the small model call that sorts a chat message into an intent. It gets one
more intent:

- `tweak_session`: the athlete asks for a change to sessions they name. Make one shorter,
  longer, easier or harder. Another sport instead. Other exercises. Drop it, add one, move
  it, or swap two days.

It maps to `workout tweak <the message>`. The router still fills no slots, which is why the
days are read off the message (§3.1). The echo is "asking your coach to change that".

`coach_message` keeps everything about the athlete's state and availability: tired, sore,
travelling, no bike this week. When the router picks the wrong one of the two, the athlete
still gets a preview to accept or refuse.

## 4. How a message reaches the strength planner

Two model calls write a strength day. The week planner writes the **brief**: what the
session is for and what the plan asks of it, with no exercise, set, rep or load in it. The
strength planner then writes the exercises, sets, reps and kilograms under that brief, from
the sets the athlete actually lifted (DESIGN_strength_tracking.md §9).

Today the athlete's message goes to the week planner only. The strength planner never sees
it. "Knee is sore" still works, because the week planner rewrites the brief ("keep knee
flexion shallow"), and a changed brief makes the strength planner write the session again.
But "step-ups instead of belt squats" has no way through. The week planner may not name an
exercise, and the strength planner never hears the request.

**The rule.** The week planner writes the request into the brief. When the athlete's message
asks for something inside a strength session, the week planner rewrites that session's
brief so that it says what the athlete wants, in the week planner's own words: "Lower-body
strength, heavy and low in volume. Step-ups take the place of belt squats, as requested:
the machine is broken." It takes only the part of the message that is about that session.
It writes no set, rep or load.

The brief says "as requested", never "as you asked". On a companion instance the request
may come from the athlete's human coach, and the athlete reads the brief on the Calendar.
"As requested" is true whoever asked, and it tells a later week planner which part of the
brief to keep.

This is the one case where a brief may name an exercise: the athlete named it first. The
strength planner is told that when a brief names an exercise, the athlete asked for it, and
that it does what the brief says unless the day's equipment rules it out.

A message that is not about the inside of a strength session leaves every brief as it was.
An unchanged brief means the strength planner has nothing to write again.

This holds for `workout adapt -m` and `workout tweak` alike, and for the bot.

**A real week.** It is Monday 21 September. Friday holds a 70-minute gym session: belt
squat 3×4–6 @ 140, push press, hamstring curl, pulldown. The athlete runs `workout tweak
"Friday: step-ups instead of belt squats, the machine is broken. And make Thursday's ride
45 minutes"`.

1. The week planner shortens Thursday's ride. It returns Friday's strength session with the
   same date, duration and load, and a brief that now says step-ups take the place of belt
   squats. Thursday's ride is not mentioned in Friday's brief.
2. The brief changed, so the strength planner is asked to write Friday again. It keeps the
   push press, the curl and the pulldown as they were. It puts step-ups where the belt squat
   was, picks a starting load, and says so in the notes.
3. The preview shows Friday's exercise lines before and after. The athlete says yes.
4. Friday's Calendar event opens with the new brief. It reads as the coach explaining the
   session, not as a quote of the athlete's message.
5. On Thursday morning, after Wednesday's lifting is on record, `workout adapt` checks
   Friday's kilograms again. The brief still names step-ups, so the strength planner does
   not put the belt squat back. If the week planner rewrites Friday's brief for another
   reason, it keeps what the brief says the athlete asked for.

The request is tied to Friday's session only. The next gym day is written from the athlete's
habits as before. An athlete who never wants belt squats again writes it in their own
strength guidelines.

**Why the request lives in the brief.** Step 5 is the reason. The strength planner writes a
session from the athlete's habits, and the habit here is belt squats. Anything that makes
it write Friday again would bring belt squats back, unless the request is still written
somewhere that the strength planner reads. The brief is the only text that stays with the
session and that the strength planner reads every time. The other place would be a new
column on the session, copied forward at each revision. That is more to build, for a line
the athlete may as well see.

**Considered and not taken: a small call that reads the message first.** The idea was a
small model call, like the one that says whether a changed input reshapes the periodization
(DESIGN_plan_staleness.md §10). It would decide whether the message concerns the
strength planner, and what to pass on. It is not taken, for two reasons.

- That verdict call exists because no other model call runs at that moment. Here the week
  planner already reads the message and already writes the brief, in the same reply. A
  second reader adds a wait and a prompt to maintain, and decides nothing new.
- It does not remove the need for the brief. What it passes on must still be remembered for
  step 5, so it would end up in the brief anyway.

It becomes worth another look if the week planner proves unreliable at this: if it quotes
unrelated parts of the message into a brief, or drops the request.

## 5. What goes away

**With `workout add` and `workout rm`:**

| Where | What is removed |
|---|---|
| `cli/workouts/parser.py`, `edit.py` | The two sub-commands and their handlers. |
| `coach/service/editing.py` | `workout_add` and `_replaced_header`. |
| `db/workout_change.py` | The `add` and `rm` change kinds. `_lineage_is_manual`. The two lineage rules "an `add` starts a new lineage" and "a `generate` over a manual session starts a new lineage". `replaced_manual`. The hydrated `source` field. |
| `types.py` | `Workout.source`. |
| `coach/revisions.py` | `carried_lineage`: a replacement always continues the session it replaces. |
| `coach/service/workouts.py` | Manual sessions as standing sessions outside the commitment window. The manual clause of the voids. The notice "Replaced the session you added". |
| `coach/formatting.py` | The `[ADDED BY THE ATHLETE]` and `[athlete-added]` tags. |
| `coach/engine/adapt.py` | The "[athlete-added]" paragraph of the adapt TASK. |
| `strength/planner.py` | Sessions "shown as context": every strength session is written or checked. |
| `gcal/reconcile.py` | The manual clause of `leaves_trace`. |
| `gcal/event.py` | The `[Manual]` title tag. `add` as a reason to say `[Deleted]`. |
| `gcal/history.py` | The labels "Added by hand", "Replaced by hand" and `rm`'s "Cancelled". |
| `cli/workouts/_helpers.py` | The `[MANUAL]` and `[REPLACED]` markers. |
| `cli/workouts/generate.py` | "N added by hand" in the question `workout generate` asks. |
| `analytics/runway.py` | `coverage_end`. Without manual sessions it is the same function as `plan_end`. |
| `static/` | The manual badge and the two commands in the help text. |
| `workout adapt` | Its alias `a`. With `add` gone, the prefix `a` already means `adapt`. |

**With `workout swap`:**

| Where | What is removed |
|---|---|
| `cli/workouts/parser.py`, `edit.py`, `_helpers.py` | The sub-command, its handler and `_resolve_swap_ops`. |
| `coach/service/editing.py` | The whole file: `workout_swap_validate`, `workout_swap_apply` and their helpers. `WorkoutEditMixin` leaves `CoachService`. |
| `db/workout_change.py` | The `swap` change kind. |
| `gcal/history.py`, `_helpers.py`, `static/` | The labels "Moved" and "Moved away", the `[SWAPPED]` marker and its badge. |

What stays: a session can still stand in a slot other than the one it started in, because
`workout adapt` and `workout tweak` move sessions. So the lineage rule for a move, and the
read that hides the stale half of a moved session, both stay.

**With `workout restore`:**

| Where | What is removed |
|---|---|
| `cli/workouts/parser.py`, `edit.py` | The sub-command and its handler. |
| `db/workout_change.py` | The `restore` change kind and `revision_before_live_void`. |
| `workout rollback`'s help | The sentence saying it is not `workout restore`. |
| `workout list --removed` | The flag. Its help says it exists "to find their ID for restoring". |

What stays: `WorkoutChange.restore`, the method that copies an earlier revision forward.
`workout rollback` and reinstating a goal both use it.

## 6. What stays

- The void kind `stand-down` is still "the athlete's own decision". Calling a goal off keeps
  the Calendar events, retitled `[Deleted]`. The adapt prompt still lists those sessions as
  deliberately removed. `ATHLETE_VOID_KINDS` now holds that one kind.
- `workout push`, `workout wipe` and `workout prune-calendar` stay. They do not edit a
  session.

## 7. Migration

One step, schema 18: change rows of kind `add`, `rm`, `swap` or `restore` become kind
`tweak`. That is two rows in all: the author's swap and the companion's repair. Both are in
the past.

## 8. Not handled

- **A tweak past the end of the current mesocycle.** `workout adapt` does not reach there
  either. The athlete adds a constraint, or waits for the mesocycle to start.
- **A session with exact numbers the athlete typed.** The coach writes the session. The
  athlete who wants "exactly 52 minutes" says so in the message.
- **An edit with no model call.** Every change to a session now costs one week planner call,
  and waits for it. A swap that took a second takes as long as `workout adapt`.
- **The bot's "Move it", "Shorten it" and "Skip it" buttons** still run `workout adapt -m`.
  They are about today and how the athlete is, which is what `workout adapt` is for.

## 9. What the build found

Revision 3 is built in the worktree `workout-tweak`. Three things needed more than the
sections above say.

**A dropped session was invisible to the tweak prompt.** It is Monday. The athlete ran
`workout tweak "drop Saturday"`, and Saturday's long ride became a rest day. On Tuesday they
ask "put Saturday's ride back". The rest day continues the ride's history, so the read that
lists removed sessions hides the ride: to that read, the ride is still live, as a rest day.
Widening the filter of §3.1 therefore listed nothing. The tweak prompt now uses a read of
its own: every day in the range where a session was cancelled, unless that session only
moved to another day and still stands there.

**Two rides could not swap days.** "Swap Thursday and Friday" with a ride on each day comes
back as two moves. The move check refused both, because each lands on a day that holds a
ride. It now lets a move land there when the ride standing there is moving away in the same
reply. `workout adapt` gains the same swap.

**One warning could no longer fire.** The progress timeline warned about "workouts beyond
plan end". Only a manual session could stand past the plan's last day, so the warning is
removed with `coverage_end`.

## 10. Tests

- `workout tweak` end to end: the days from `-d`, the days from `tweak_dates`, no usable
  day, a day past the mesocycle, sessions on other dates dropped, a swap of two named days
  kept, kind `tweak` recorded, rollback.
- The tweak prompt: the request section and its TASK text appear together, and the
  fatigue-reading sections are absent.
- The strength planner rewrites a session whose brief now names the exercise the athlete
  asked for, and a message about another day leaves the brief as it was.
- The router table and the bot's argv table hold `tweak_session`.
- The migration relabels the four kinds.
