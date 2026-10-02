# Design: A proposal that waits for the athlete's answer

**Status:** Proposed, not implemented · **Date:** 2026-10-02

The week planner is the model call inside `workout adapt` and `workout tweak` that writes the
sessions. A **proposal** is what it would change, before anything is written. Today a proposal
lives only inside the command that asked for it. This design saves it in the database, so the
athlete can answer it with a tap whenever they like, and the chat is free in the meantime.

In this document a **run** is one execution of a command, never a training run.

## 1. The problem

It is Thursday 8 October. A 90-minute ride with intervals is planned. The athlete slept badly.

**The morning message writes without asking.** At 08:00 the morning message arrives. The
`adapt-first` setting is on, so the push has already asked the week planner and already written
its answer. The message shows a 60-minute easy ride and the line "Eased today — rough night."
The athlete feels fine and wants the 90 minutes. No button brings them back. The only undo is
to type the command `/workout rollback`.

**A proposal asked for in chat dies after five minutes.** On another Thursday the athlete writes
"I'm tired" at 07:05. `workout adapt -m` runs for about a minute, then shows what it would change
and asks "Shall I make these changes?". The athlete is in the shower. At 07:11 the bot says
"Prompt timed out — command cancelled." The proposal is gone, and the week planner's answer was
paid for.

**The chat is held the whole time.** From 07:05 to 07:11 the bot answers everything with "A
command is still running. Use the buttons above, or /cancel." It refuses "show my week". It
also refuses "move Saturday's ride to Sunday", and those words reach nobody.

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
- what a tap writes, as the run resolved it, so a tap writes exactly what was shown. What only
  drew the preview is not saved, and neither are the rule and signal candidates, which the run
  asks about itself (§6.1);
- the days it changes;
- the newest change that wrote a session, at the moment the run read the week (§4, rule 1);
- when it was made, and whether the run had last night's sleep score.

**How it is sent.** The reason and the preview go out as ordinary text, which the bot already
cuts into several messages when it is long. A proposal that rewrites four sessions can pass
Telegram's limit for one message. Then comes the item's own message: "Shall I make these
changes?" with its two answers, **✅ Change it** and **💪 Keep it as planned**.

**One proposal is open at a time.** A proposal is open when it waits for an answer and is not
out of date (§4). Saving a proposal closes every other proposal that still waits.

A proposal **stands alone**, which is new for the queue and is one property of the kind:

- It is sent the moment it is saved, as a message of its own. The queue sends its other items
  in a round that the morning message opens, oldest first, one at a time (the queue design
  calls a round a "walk"). A proposal about today cannot sit behind three questions about
  Tuesday's gym sets.
- It is in no round, in the chat or in a terminal, and the terminal's hint "1 question is
  waiting" does not count it. `sm queue list` shows it and `sm queue answer <id>` answers it.
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

1. A later change wrote a session. A run that changes nothing also records a change, with no
   session in it. That one does not count.
2. A day it changes is over.
3. It changes today, and an activity recorded today started after it was made. This is the test
   the push already uses to decide whether a morning adaptation still stands
   (DESIGN_bot_simple_frontend.md §4.2).

A tap on it then writes nothing and answers "That proposal is out of date, so I left your week
as it is." A tap on a proposal that is already closed gets the same line, whatever closed it.

It is Thursday, the proposal came at 08:00, the athlete rode the 90 minutes at noon and taps
"Change it" at 15:00: rule 3 stops the tap from rewriting a ride already done.

Rule 3 needs the noon ride to be in the database, and a tap reads the database only. So
"Change it" on a proposal that changes today first pulls today's activities from Garmin, even
inside the two hours during which Stamind normally does not pull again. If Garmin cannot be
reached, it uses what is stored. "Keep it as planned" pulls nothing and answers at once.

## 5. The morning push

With `adapt-first` on, the push asks the week planner as it does today. Then:

- **Nothing to change.** As today.
- **Only kilograms moved.** Written at once, with its sentence in the briefing, as today (§7).
- **A session would change.** Nothing is written. The briefing shows today as planned, with no
  reason line. The proposal follows as its own message. Then the round of queued questions
  starts, as today.

On the Thursday of §1 the athlete reads the 90-minute ride, then: "Rough night. Here's what I'd
change: 60 easy minutes." They tap **Keep it as planned** and ride the 90 minutes.

The briefing keeps its row of buttons, "👍 Got it" included. "Got it" answers the briefing and
"Keep it as planned" answers the proposal. An athlete who taps only "Got it" has not answered
the proposal, and the week stays as planned.

**Once a morning.** The push skips the week planner when it already ran this morning with the
night's sleep score. Today it reads that from the newest change that `workout adapt`
recorded, whether it wrote a session or not. A saved proposal records no change, so the push
also counts an `adapt` proposal saved this morning with the sleep score, whatever its answer. A
declined proposal then no longer makes the push ask again, which
DESIGN_bot_simple_frontend.md §4.2 lists as not handled.

What a tap writes is saved without the mark that the sleep score was seen, so a tap's change
never carries it. It is Thursday 21:00 and a proposal about Saturday is made, with Thursday's
sleep score. The athlete taps "Change it" on Friday at 07:00. If the tap's change carried the
mark, the 08:00 push would believe Friday's night was already read, and skip it.

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
  Stop ends the coach's run. `/cancel` and `/restart` end the command in both places.
- The two questions asked before the week planner is called stay where they are, with their
  buttons: "Was that the session, cut short?" and "Which session is this about?". The chat is
  free while they wait.
- When the week planner answers, the proposal is saved and sent (§3). The saved item replaces
  the confirm that holds the chat today.
- In the chat, the questions about a rule or a signal found in the message ("Shall I
  remember…?") come after the proposal. Today they come before the preview
  (DESIGN_constraints.md §8). A question nobody answers must not hold the proposal back. A tap
  on "Change it" runs in the chat's own place, so it works while such a question still waits.
- A question left unanswered for five minutes ends the run, as today. The line changes from
  "Prompt timed out — command cancelled." to "No answer, so I stopped there.", which is true
  whether or not a proposal waits above it.
- When the week planner changes nothing, the athlete is told so, as today.

The morning push, a reminder and a heads-up wait while the coach is thinking, the way they
already wait for a busy chat. The reverse holds too: while the morning push runs, a message to
the coach gets the busy line.

### 6.2 The next message to the coach

What happens to a message to the coach depends on what the coach's run is doing.

**No run.** The run starts.

**The coach is thinking.** The coach is thinking from the moment the week planner is asked
until the run has saved a proposal or said that nothing changes. A message to the coach in
that time is not taken. It is Thursday. 07:05: "I'm tired". 07:06: "move Saturday's ride to
Sunday". The bot answers "I'm still working on your last message — send that again in a
minute." At about 07:07 a proposal arrives that eases today. The athlete sends the Saturday
message again. At about 07:08 one proposal replaces the first and covers both, as the next
paragraphs explain.

**The run waits on a question.** The question is dropped with its line, "No answer, so I
stopped there.", the run ends, and the new message starts its own run. At 07:07 the proposal
arrives, then "Shall I remember that you sleep badly before a race?". At 07:30 the athlete
writes "no, shorten it instead" and ignores the question.

**A proposal waits.** At 07:07 the coach proposes to skip today's ride. The athlete does not
tap. At 07:30 they write "no, shorten it instead". The new run looks for the open proposal
(§3). A proposal that still waits but is out of date is closed on the way, and the week planner
is not shown it. The open one is shown to the week planner the way the athlete's note is: the
data in a section of its own, and how to read it in a sub-section of `## TASK`
(DESIGN_prompt_structure.md). The data is the proposal as the athlete read it. The sub-section
says that it was not accepted and that the answer replaces it. When the new proposal is saved,
the old one is closed (§3). The new one opens with "This replaces my earlier proposal."

A run that proposes nothing leaves the open proposal open. Writing "what's tomorrow's swim
about?" must not withdraw the offer to ease today.

Every run is shown the open proposal: a chat run, the morning push and a terminal run. A
proposal from Thursday evening about Saturday is still open on Friday at 08:00. The morning run
is shown it, and its proposal replaces it. A terminal run asks and writes as before, and what
it writes puts the open proposal out of date by rule 1 of §4.

**The week changed while the coach was thinking.** The run compares the newest change that
wrote a session when it started and when it is about to save. If they differ, it saves nothing
and says "Your week changed while I was thinking. Tell me again if you still want a change."
This is rule 1 of §4, checked one step earlier. The second place makes it needed: at 07:30 the
athlete writes "also move Saturday's ride", and at 07:30:30, while that run thinks, they tap
"Change it" on the 07:07 proposal. Without the check, the 07:31 proposal would arrive already
out of date.

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
- A kilograms-only update (§7) is a change that wrote a session. It puts an open proposal out of
  date by rule 1 of §4, and the athlete asks again.
- When a proposal is declined or not answered, a gym session in it keeps the kilograms it had
  until the next run. Writing those kilograms at once would be a second way to apply half a
  proposal.
- On later days the week planner is not told that the athlete declined. It sees what was
  trained.
- A message to the coach sent while the coach is thinking is not kept. The athlete is asked to
  send it again (§6.2).
- A question asked before the week planner is called still ends the run when nobody answers
  it for five minutes, or when another message to the coach arrives. The first message is then
  lost. Nothing was asked of the week planner yet.
- Only a message to the coach runs beside the chat. The morning push, `workout generate` from
  its button, and the adaptation after a goal or rule edit still hold the chat while they run.
  Freeing them is a later design, which reuses the second place.
- Only `workout adapt` and `workout tweak` save their proposal. Every other confirm in the chat
  still times out after five minutes.

## 9. Build order

Each step works on its own.

1. **The morning proposal** (§3, §4, §5, and §7 for the push): the `proposal` kind, the
   stand-alone property, the push. Until step 2, a chat run started while the morning proposal
   is open asks and writes as today, and the proposal goes out of date by rule 1.
2. **Chat runs save their proposal** (§6.1's saved proposal, §6.2's open proposal, and §7 for
   chat runs). There is still one place per chat, so the rule and signal questions stay before
   the preview, as today: a run parked on "Shall I remember…?" would make the bot refuse the
   tap on "Change it". The chat is busy while the week planner thinks and while a question
   waits. The five-minute death of the final confirm is gone. A run whose "Shall I remember…?"
   gets no answer for five minutes still ends before its proposal is saved, as today. Step 3
   removes this.
3. **The run works beside the chat** (the rest of §6): the second place per chat, the rule and
   signal questions moved after the proposal, the line for a message sent while the coach
   thinks, and the check before saving.

## 10. Touch points

No table and no column are added: a proposal is a row of `athlete_queue`.

| Where | What |
|---|---|
| `stamind/queue_kind.py` | `Kind` gains the stand-alone property and its own line for a tap that comes too late |
| `stamind/athlete_queue.py`, `stamind/cli/queue.py` | a stand-alone item is sent when queued, by a function the push and `workout adapt` call; it is in no round and not counted in the terminal's hint; it is drawn without the "🙋 Quick question" lead and without "Not now"; a tap on a closed one prints the kind's own line |
| `stamind/cli/workouts/proposal.py` (new) | the `proposal` kind and nothing that sends: wording, the three out-of-date rules, what each answer does with the Garmin pull in "Change it", finding the open one. It must not import `cli/queue.py`, which imports the list of kinds. The item's subject, the key the queue uses to refuse a duplicate, is the instant it was saved, as for the `message` kind |
| `stamind/coach/proposals.py` | whether the week planner changed a session; what a tap writes, to and from JSON, without the sleep mark |
| `stamind/coach/service/adapt.py`, `stamind/coach/engine/adapt.py` | the open proposal as a data section and a sub-section of `## TASK` (DESIGN_prompt_structure.md) |
| `stamind/cli/workouts/adapt.py` | a chat run saves and sends in place of the confirm; in the chat the rule and signal questions move after it; the check before saving |
| `stamind/cli/bot/views.py` | the push saves a proposal when a session would change; the once-a-morning read, whose test on today's activities rule 3 shares |
| `stamind/chat/` | the second place per chat for the coach's run, prompt and Stop taps found by the run that raised them, `/cancel` and `/restart` over both places, the three cases of §6.2 for a message to the coach, the scheduler's busy test, the time-out line |
| `docs/ARCHITECTURE.md` | the bot section and the adaptation flow |

Implemented designs amended when each step lands: DESIGN_athlete_queue.md §2 (its example
"Apply this proposal?" no longer blocks in chat), §3 and §8 (the stand-alone property, the new
kind); DESIGN_bot_simple_frontend.md §4.1 and §4.2 (the push proposes);
DESIGN_change_heads_up.md §7 (the push no longer writes a session change);
DESIGN_constraints.md §8 (in chat the rule question comes after the proposal);
DESIGN_bot_stop_button.md §5 ("show my week" no longer gets the busy line) and §7 (Stop finds
the coach's run).

Tests, one per rule: each out-of-date rule refuses the tap and writes nothing; accept writes
what was saved and not what asking the week planner again would return; the push writes nothing
when a session would change and writes at once when only kilograms moved; a stand-alone item is
in no round and has no "Not now"; a message sent while the coach thinks gets its line and
starts nothing, and one sent while the run waits on a question ends that run and starts its
own; a run started with a proposal open replaces it, and a run that proposes nothing leaves it
open; a run that changes nothing does not put an open proposal out of date; saving a proposal
closes the others that wait.
