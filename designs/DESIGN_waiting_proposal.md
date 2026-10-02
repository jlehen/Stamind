# Design: A proposal that waits for the athlete's answer

**Status:** Proposed, not implemented · **Date:** 2026-10-02

The week planner is the model call inside `workout adapt` and `workout tweak` that writes the
sessions. A **proposal** is what it would change, before anything is written. Today a proposal
lives only inside the command that asked for it. This design saves it in the database, so the
athlete can answer it with a tap whenever they like, and the chat is free in the meantime.

## 1. The problem

It is Thursday 8 October. A 90-minute ride with intervals is planned. The athlete slept badly.

**The morning message writes without asking.** At 08:00 the morning message arrives. The
`adapt-first` setting is on, so the push has already asked the week planner and already written
its answer. The message shows a 60-minute easy ride and the line "Eased today — rough night."
The athlete feels fine and wants the 90 minutes. No button brings them back. The only undo is
`workout rollback`, typed in a terminal.

**A proposal asked for in chat dies after five minutes.** On another Thursday the athlete writes
"I'm tired" at 07:05. `workout adapt -m` runs for about a minute, then shows what it would change
and asks "Shall I make these changes?". The athlete is in the shower. At 07:11 the bot says
"Prompt timed out — command cancelled." The proposal is gone, and the week planner's answer was
paid for.

**A second message is thrown away.** At 07:06, while the coach is still thinking, the athlete
adds "move Saturday's ride to Sunday". The bot answers "A command is still running. Use the
buttons above, or /cancel." Those words reach nobody.

The three have one cause. A proposal exists only in the memory of a running command, so the
command must either write it at once or hold the chat until the athlete answers.

## 2. The rule

> A run started from the chat or by the morning push never changes what a session asks for on
> its own, and never waits for the answer. It saves its proposal, sends it with two buttons, and
> ends.

A run started in a terminal is unchanged: it shows the preview and asks, because someone is
sitting there. `-y` is unchanged too: it writes without asking, wherever it was typed.

One kind of change is still written without asking: the kilograms of a gym session (§7).

## 3. The saved proposal

A proposal is saved as an item of the athlete queue, the stored list of things Stamind wants to
ask the athlete (DESIGN_athlete_queue.md). The queue already gives what a proposal needs: a row
that survives a bot restart, buttons that carry the item they belong to, a check that runs
before a tap is applied, and `sm queue` to see and answer it from a terminal.

The new kind is `proposal`. Its item holds:

- the text the athlete is shown: the coach's reason, then the preview the chat already prints
  under "Here's what I'd change:";
- the proposal itself, as the run resolved it, so a tap writes exactly what was shown;
- the newest change to the week at the moment the run read the week;
- when it was made, and whether the run had last night's sleep score;
- the athlete's messages it answers, with their times.

Its two answers are **✅ Change it** and **💪 Keep it as planned**.

A proposal **stands alone**, which is new for the queue and is one property of the kind:

- It is sent the moment it is saved, as a message of its own. The queue sends its other items
  in a round that the morning message opens, oldest first, one at a time (the queue design
  calls a round a "walk"). A proposal about today cannot sit behind three questions about
  Tuesday's gym sets.
- It is left out of those rounds.
- It has no "🕐 Not now". Not answering already means "not now", and "in 1 day" would bring back
  a proposal that is out of date.

## 4. What the athlete can do with it

**Change it.** The saved proposal is written under one change, and Google Calendar follows. The
reply is "Done — your week is updated. 💪". The athlete watched it happen, so no heads-up line
waits for them (DESIGN_change_heads_up.md §6). `workout rollback` undoes it, as it undoes any
change.

**Keep it as planned.** The item is closed. Nothing is written. The reply is "Okay — nothing
changed."

**No answer.** The week stays as planned. Nothing reminds the athlete.

**A tap that comes too late.** A proposal is out of date when one of these is true:

1. Something else changed the week after it was made.
2. A day it changes is over.
3. An activity recorded today started after it was made. This is the test the push already uses
   to decide whether a morning adaptation still stands (DESIGN_bot_simple_frontend.md §4.2).

A tap on it then writes nothing and answers "That proposal is out of date, so I left your week
as it is." It is Thursday, the proposal came at 08:00, the athlete rode the 90 minutes at noon
and taps "Change it" at 15:00: rule 3 stops the tap from rewriting a ride already done.

## 5. The morning push

With `adapt-first` on, the push asks the week planner as it does today. Then:

- **Nothing to change.** As today.
- **Only kilograms moved.** Written at once, with its sentence in the briefing, as today (§7).
- **A session would change.** Nothing is written. The briefing shows today as planned, with no
  reason line. The proposal follows as its own message. Then the round of queued questions
  starts, as today.

On the Thursday of §1 the athlete reads the 90-minute ride, then: "Rough night. Here's what I'd
change: 60 easy minutes." They tap **Keep it as planned** and ride the 90 minutes.

On a morning with a proposal the briefing's row loses "👍 Got it". The athlete could not tell it
from "Keep it as planned": both leave the week alone. "😴 Feeling tired" and "🕐 Can't today"
stay, because the proposal may be about something else than today's fatigue.

**Once a morning.** The push skips the week planner when it already ran this morning with the
night's sleep score. Today it reads that from the newest adaptation written to the week. A
saved proposal is not written to the week, so the push also counts an `adapt` proposal saved
this morning with the sleep score, whatever its answer. A declined proposal then no longer
makes the push ask again, which DESIGN_bot_simple_frontend.md §4.2 lists as not handled.

## 6. A message to the coach from the chat

Two kinds of message reach the coach: how the athlete is (`workout adapt -m`) and a change they
decided (`workout tweak`). The buttons that send a fixed sentence to the coach, such as
"Feeling tired", are the same thing.

### 6.1 The run works beside the chat

The bot keeps one running command per chat, and the chat is busy while it runs. It gets a
second place per chat, for the coach's run only. While the coach thinks, the chat is free: "show
my week" answers at once, and shows the week as it stands.

The run itself changes little:

- The echo ("→ passing that on to your coach") and the wait notice with its ✋ Stop button stay.
  Stop and `/cancel` end the run as today.
- The two questions asked before the week planner is called stay, with their buttons: "Was that
  the session, cut short?" and "Which session is this about?". The chat is free while they wait.
- When the week planner answers, the proposal is saved and sent (§3). This replaces "Shall I
  make these changes?".
- The questions about a rule or a signal found in the message ("Shall I remember…?") come after
  the proposal. Today they come before the preview (DESIGN_constraints.md §8). A question nobody
  answers must not hold the proposal back.
- When the week planner changes nothing, the athlete is told so, as today.

The morning push, a reminder and a heads-up wait while the coach is thinking, the way they
already wait for a busy chat.

### 6.2 Everything said since the last answer, in one proposal

One proposal about the week is open at a time. The coach answers everything the athlete has
said since they last accepted or declined one.

**A message while the coach is thinking.** It is Thursday. 07:05: "I'm tired". 07:06: "move
Saturday's ride to Sunday". The run that started at 07:05 knows only the first message, so its
answer is already out of date. The bot stops it and starts one run with both messages, oldest
first, each on its own line. At about 07:07 one proposal arrives that eases today and moves
Saturday. The joined run is a `workout adapt` when any of the messages was one, and a `workout
tweak` only when all of them were: an adaptation may change the whole week, a tweak only the
days it names.

**A message while a proposal waits.** At 07:07 the coach proposes to skip today's ride. The
athlete does not tap. At 07:30 they write "no, shorten it instead". The new run finds the open
proposal. The week planner is shown it in one prompt section: what the athlete had said, the
proposal as the athlete read it, that it was not accepted, and that its answer replaces it. When
the new proposal is saved, the old one is closed. The new one opens with "This replaces my
earlier proposal." This is also how the earlier messages travel: they are part of the proposal
being replaced.

A run that proposes nothing leaves the open proposal open. Writing "what's tomorrow's swim
about?" must not withdraw the offer to ease today.

The morning push follows the same rule. A proposal from Thursday evening about Saturday is
still open on Friday at 08:00. The morning run is shown it, and its proposal replaces it.

**The week changed while the coach was thinking.** The run compares the newest change to the
week when it started and when it is about to save. If they differ, it saves nothing and says
"Your week changed while I was thinking. Tell me again if you still want a change." This is
rule 1 of §4, checked one step earlier.

## 7. Gym sessions

The strength planner is the model call that writes a gym session's exercises and kilograms. It
runs inside `workout adapt`, after the week planner, and its rows join the same proposal.

- **The week planner changed nothing, the kilograms moved.** Written at once, and the athlete is
  told in one sentence, as the morning push does today. The strength planner follows what the
  athlete lifted; it is not a judgment about how they feel. Asking would also mean a question
  on most mornings after a gym day.
- **The week planner changed a session.** The whole proposal waits, kilograms included. Accepted,
  all of it is written. Declined or unanswered, none of it is, and the next run weighs the
  kilograms again, which is what a declined proposal already does today
  (DESIGN_strength_tracking.md §9).

The proposal therefore says whether the week planner changed a session. That is the one new
fact a proposal carries.

## 8. Not handled

- An athlete who is tired and does not read the message trains the planned session. Silence
  used to mean the eased one. There is no setting to bring the old behaviour back.
- A terminal run is not shown the open proposal. If it writes, the proposal is out of date.
- Rule 3 of §4 is strict. A proposal made on Thursday evening about Saturday is out of date
  after Friday morning's run, though it does not touch Friday. The athlete asks again.
- A bot restart while the coach is thinking loses the message, as a restart loses a running
  command today. A saved proposal survives it.
- On a day with two sessions, a second message within the minute restarts the run, and "Which
  session is this about?" is asked again.
- A replaced proposal keeps its buttons in the chat. A tap on them gets the line of §4.
- On later days the week planner is not told that the athlete declined. It sees what was
  trained.
- The morning push itself still holds the chat for the minute it runs.
- The other commands that ask before they write (a new goal, a rule, a test result) still hold
  the chat for their one confirm. They take seconds: none of them waits for the week planner.

## 9. Open questions

1. **Kilograms on a declined or unanswered proposal (§7).** A gym session today keeps the
   kilograms it had until the next run. The alternative is to split the proposal and write the
   kilograms of the sessions the week planner left alone at once. It is more faithful, and it is
   a second way to apply half a proposal. Left out until a real week shows the gap.
2. **Should a kilograms-only update ask too?** §7 says no.
3. **"Got it" on a proposal morning (§5).** Dropped here. Keeping it is harmless and one button
   more.

## 10. Build order

Each step works on its own.

1. **The morning proposal** (§3, §4, §5, §7): the `proposal` kind, the stand-alone property, the
   push. Until step 2, a chat run started while the morning proposal is open asks and writes as
   today, and the proposal goes out of date by rule 1.
2. **Chat runs save their proposal** (§6.1 without the second place, §6.2's open proposal). The
   chat is busy only while the week planner thinks. The five-minute death of §1 is gone.
3. **The run works beside the chat** (the rest of §6): the second place per chat, and the stop
   and restart with joined messages.

## 11. Touch points

No table and no column are added: a proposal is a row of `athlete_queue`.

| Where | What |
|---|---|
| `stamind/queue_kind.py` | `Kind` gains the stand-alone property and its own line for a tap that comes too late |
| `stamind/athlete_queue.py`, `stamind/cli/queue.py` | a stand-alone item is sent when queued, left out of rounds, and drawn without "Not now" |
| `stamind/cli/workouts/proposal.py` (new) | the `proposal` kind: wording, the three out-of-date rules, what each answer does; saving and sending; finding the open one |
| `stamind/coach/proposals.py` | whether the week planner changed a session; `RevisionProposal` to and from JSON |
| `stamind/coach/service/adapt.py`, `stamind/coach/engine/adapt.py` | the open proposal as one prompt section (DESIGN_prompt_structure.md) |
| `stamind/cli/workouts/adapt.py` | a chat run saves and sends in place of the confirm; the rule and signal questions move after it; the check before saving |
| `stamind/cli/bot/views.py` | the push saves a proposal when a session would change; the briefing's row; the once-a-morning read |
| `stamind/chat/` | the second place per chat, stop and restart with joined messages, prompt and Stop taps found by the run that raised them, the scheduler's busy test |
| `docs/ARCHITECTURE.md` | the bot section and the adaptation flow |

Implemented designs amended when each step lands: DESIGN_athlete_queue.md §2 (its example
"Apply this proposal?" no longer blocks in chat), §3 and §8 (the stand-alone property, the new
kind); DESIGN_bot_simple_frontend.md §4.1 and §4.2 (the push proposes);
DESIGN_bot_stop_button.md §7 (Stop finds the coach's run).

Tests, one per rule: each out-of-date rule refuses the tap and writes nothing; accept writes
what was saved and not what asking the week planner again would return; the push writes nothing
when a session would change and writes at once when only kilograms moved; a stand-alone item is
in no round and has no "Not now"; a second message stops the run and the next one carries both;
a run started with a proposal open replaces it, and a run that proposes nothing leaves it open.
