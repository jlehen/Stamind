# Design: Every long run works beside the chat

**Status:** Implemented 2026-10-14, in the four steps of §11 · **Date:** 2026-10-08

**Ruled so far.** 2026-10-08: `workout generate` saves its result, so its last question cannot
run out of time (§4). 2026-10-14: every other choice of §9. None is open.

**Read again on 2026-10-13**, against main at dc6278d. Two things landed since it was written.
The athlete queue now sends from one line (DESIGN_athlete_queue.md §13). And a project rule of
2026-10-09 says that no command started from the chat waits on the athlete (AGENTS.md). The
author added on 2026-10-14: "all the bot's questions should go through the queue, even if this
means adding more features to the queue." §6 is the feature this design adds for it.

In this document a **run** is one execution of a command, never a training run. A **long run**
is a run that asks the week planner, the model call that writes the sessions. It takes from
half a minute to several minutes.

The bot keeps two places per chat (DESIGN_waiting_proposal.md §6.1). The chat's **own place**
holds one command, and the chat is busy while it runs. The **second place** holds one long run,
and the chat stays free while it runs. Today the second place takes only a `workout adapt` or a
`workout tweak` that the athlete started. This design puts the three other long runs there too.

A **proposal** is what the week planner would change, before anything is written. The bot sends
it with the question "Shall I make these changes?" and two buttons, "✅ Change it" and "💪 Keep
it as planned". Nothing is written until the athlete taps (DESIGN_waiting_proposal.md §3).

## 1. The problem

It is Thursday 8 October. At 08:00 the bot starts the morning run, `bot morning`. The
`adapt-first` setting is on, so the run asks the week planner, then the strength planner, before
it writes the morning message. At 08:01 the athlete taps "✅ Done lately". The bot answers "A
command is still running. Use the buttons above, or /cancel." The athlete started no command,
and nothing above says that one runs. At 08:02 the morning message arrives.

Three long runs still hold the chat's own place. The counts come from the bot's journal of both
instances, from 27 August to 13 October.

| Long run | Who starts it | How long it holds the chat | How often |
|---|---|---|---|
| The morning run, `bot morning` | the bot, every morning | 34 s to 3 min 14 s, 1–13 October | daily |
| `workout generate`, from "📅 Plan my next weeks" | the athlete | several minutes, then up to 5 minutes on its last question | never tapped |
| `workout adapt -m`, run inside a goal or constraint edit (§5) | the athlete | about a minute | never happened |

The morning run is the one an athlete meets. The other two have not happened once in seven
weeks. They are here so that no long run is left with a different behaviour.

## 2. The rule

> A long run started from the chat or by the bot runs in the second place. One long run is
> alive at a time.

The long runs are:

- `workout adapt` and `workout tweak`, as today, typed or sent by a button;
- `bot morning`;
- `workout generate --propose`, which the button "📅 Plan my next weeks" sends (§4);
- a tap on a queued answer that starts a long run (§6).

What does not change:

- A run started in a terminal.
- `/workout generate` typed in the chat without `--propose`. It holds the chat and asks on the
  spot, as today. Only the operator types commands, and the typed path is the expert path
  (DESIGN_bot_simple_frontend.md §10, decision of 2026-09-02).
- The bot still waits for both places to be free before it starts the morning run, sends a
  notice about a changed week, or sends the next queued question.
- The morning run prints no wait notice. A long run the athlete starts prints its own, as today
  (DESIGN_output_verbosity.md §8.4).

## 3. The morning run

The bot starts `bot morning` in the second place. On the Thursday of §1, "✅ Done lately" at
08:01 shows the last days at once. The morning message arrives at 08:02, as it does today.

The morning run asks nothing on the spot, so nothing new can wait in the second place.

**The week changed while it was thinking.** A free chat brings one new case. It is Friday
08:00:40. A proposal from Thursday evening about Saturday still waits. The athlete taps "Change
it" while the morning run thinks, and Saturday is rewritten. The morning run read the week
before that tap, so its answer is about a week that no longer exists.

**One look at the week at a time** (amended 2026-10-20). The morning run used to check for
this before it saved, and to throw its answer away when a session had been written since it
read the week: "I had a change in mind, but your week changed while I was thinking." On
Monday 19 October that threw away the better answer. At 07:59 the athlete wrote "I'm tired,
skip the strength", and `workout tweak` proposed a rest day. At 08:00:00 the morning run
started; its week planner was shown that proposal and answered with a rest day plus the heavy
lift moved to Thursday and the light one to Friday. At 08:00:02 the athlete tapped "Change it"
on the tweak. The morning answer was thrown away, and the next morning moved a gym session
onto that day.

Now nothing writes the week while a run of the week planner looks at it. A lock file beside
the database (`db.week_lock()`) is held:

- by every write of the sessions, since `workout_change` takes it;
- by every run of the week planner, from reading the week, the open proposal included, to
  saving or writing its answer: `workout adapt`, `workout tweak`, `workout generate`, its
  `--strength-only`, and the morning run from its gate on;
- by a tap that answers a proposal or planned weeks, which reads the item again once it has
  the lock.

On that Monday, the tap at 08:00:02 waits and says "The coach is busy with your week right
now. This goes on once it is done." The morning run saves its proposal at 08:03, which closes
the tweak's as replaced. The tap then reads the tweak's closed and answers "That proposal is
out of date, so I left your week as it is."; the morning's proposal, "This replaces my earlier
proposal.", is the one to answer.

The morning run waits without a word, and the bot does not start it while the lock is held:
a run from a terminal counts as busy, like a run in the chat. A terminal run lets go once the
week planner has answered, because it asks a person next, so a question left open in a
terminal never holds the bot. It takes the lock again to write, and writes nothing if a
session was written meanwhile: "Your week changed while I was thinking. Tell me again if you
still want a change." The kernel lets go of the lock of a process that ends, so a run that
dies holds nothing.

Every terminal run checks this the same way: `workout adapt`, `workout tweak`, `workout
generate` and its `--strength-only` (amended 2026-10-30, `heads_up.week_changed`). Before,
`workout generate --strength-only` wrote what it previewed. A tap that moved a gym session
while it asked left that session on two days.

Not handled: a tap that waits for the lock holds the chat's own place while it waits. A
message, or "✅ Done lately", sent in that minute gets "A command is still running."

## 4. `workout generate` from its button

`workout generate` takes a new flag, `--propose`: save the result for a tap, and ask nothing
on the spot. The button "📅 Plan my next weeks" sends it. A run with the flag runs in the second
place. It saves what it would write, sends it with two buttons, and ends.

**Today.** It is Sunday 11 October. The morning message says the schedule runs out on Thursday
and offers "📅 Plan my next weeks". The athlete taps it at 09:00, reads "Writing your sessions —
this usually takes about 3.5 minutes." and puts the phone down. At about 09:05 the proposed
weeks arrive, with the question "Schedule these 12 workouts and push them to Google Calendar?"
and Yes and No. At 09:10 nobody has answered. The bot says "No answer, so I stopped there." The
proposed weeks are gone, and the athlete must tap the button and wait again.

**After.** At 09:01 the athlete taps "✅ Done lately" and gets it at once: the chat is free.
At about 09:05 the proposed sessions arrive as ordinary text, as today. Under them comes a
message of its own: "Shall I schedule these 12 sessions?" with two buttons, "✅ Schedule them"
and "✖️ Leave it". The run has ended. At 11:00 the athlete picks the phone up, reads the weeks
and taps.

- **Schedule them** writes exactly what was shown, and Google Calendar follows. The reply is
  "Done — they're in your schedule. 💪".
- **Leave it** writes nothing. The reply is "Okay — nothing changed."
- **No answer** writes nothing, and nothing reminds the athlete.

When the new sessions would take the place of sessions already planned, the question says so:
"They replace the 5 sessions planned from Mon 12 to Sun 18 October."

**Where it is kept.** The athlete queue is the stored list of things Stamind wants to ask the
athlete (DESIGN_athlete_queue.md). A proposal is one kind of item in it. What `workout generate`
would write becomes a second kind, `schedule`, with a proposal's manners:

- The run sends it itself, at once, whatever else waits. It is in no line of queued questions
  and has no "Not now".
- While it waits for its tap, the other queued questions wait behind it, until the tap or the
  next morning (DESIGN_athlete_queue.md §13.2, rules 3 and 6).
- It is not sent again.

One waits at a time: a second `workout generate --propose` closes the item of the first. It
waits beside a proposal, and neither closes the other.

**A tap that comes too late.** Saving the weeks for later has a risk: the schedule can change
between the moment they are made and the tap. Writing them after such a change could undo it.
So the item is out of date when one of these is true:

1. A later change wrote a session on one of its days, from the first day it writes to the last.
2. The first day it writes is over.
3. It writes today, and an activity recorded today started after it was made.

A tap on it then writes nothing and answers "That proposal is out of date, so I left your week
as it is."

Rules 2 and 3 are a proposal's own (DESIGN_waiting_proposal.md §4). Rule 1 is narrower: for a
proposal, any later change counts. On the Sunday above, the proposed weeks run from Friday 16
to Thursday 29 October, and they hold a long ride on Saturday 17. At 10:00 the athlete writes
that their knee hurts, and the coach moves that ride to Sunday 18. At 11:00 they tap "Schedule
them". The weeks were written before the knee message, so writing them would put the ride back
on Saturday 17 without a word. Rule 1 stops that tap. Had the athlete eased today's ride
instead, on Sunday 11, the tap would write the weeks: no day of theirs changed. Ruled
2026-10-14 (§9, choice 2b).

**The schedule changed while it was thinking.** Before it saves, the run applies rule 1 to
itself. When a session was written on one of its days since it read the schedule, it saves
nothing and says "Your week changed while I was thinking. Tell me again if you still want a
change.", the line a chat run of `workout adapt` already uses.

**When sessions already stand in those days.** A terminal run asks "…Regenerate?" first. It
warns that accepting the result archives those sessions, and it guards the minutes the planners
take. A run with `--propose` saves that question and ends, before any planner is called:

> You already have 5 sessions planned from Mon 12 to Sun 18 October. New weeks would replace
> them if you accept them. Shall I plan these weeks?
>
> `[✅ Plan them]` `[✖️ Leave it]`

- **Plan them** starts the same `workout generate --propose` for the same days, with this
  question answered. It runs beside the chat (§6), and its result is saved and sent as above.
- **Leave it** writes nothing: "Okay — nothing changed."
- **No answer.** It closes without a word after three more mornings, or sooner when its first
  day is over (rule 2 above). A session written on its days does not close it: "Plan them"
  reads the schedule as it then stands, and the weeks it saves have rule 1 of their own.
  Ruled 2026-10-15; until then rule 1 closed it too.

It is a confirmation: a question about what the athlete just did, under the three rules of
DESIGN_chat_questions.md §2. It is sent at once, it stands at the front of the line while it
waits, and it comes back after the morning message on each of the next mornings, as many as the
setting `confirmation-days` says, three by default. It is drawn bare. Its kind is
`replace_sessions`.

**When the plan is out of date.** A terminal run asks "…Proceed anyway?" when the plan, the
periodization, changed since it was built. It is Sunday. On Friday the athlete moved their race
from 1 to 15 November. Nobody has run `plan generate` since, so the plan still aims at 1
November. A run with `--propose` asks nothing, calls no planner and writes nothing. It says:

> I can't plan your next weeks yet: your training plan needs rebuilding first, and ⟨operator⟩
> takes care of that from the computer.

The check runs again when "Plan them" is tapped.

A run started in a terminal is unchanged: it asks its questions, shows the sessions and asks.
`--force` writes without asking, wherever it was typed.

## 5. The hand-off from a goal or constraint edit

It is Thursday. The athlete writes "make my long run shorter". The bot reads the message as a
change to a goal and starts `bot capture edit_goal`. That command finds no goal that fits, but
a session that does: Saturday's run. Today it asks "I don't see a goal for that — it sounds like
Saturday's run. Shall I pass it to your coach?" with Yes and No, and waits. On "Yes" it runs
`workout adapt -m` inside itself, so the week planner thinks in the chat's own place.

After, the command saves the question and ends. The words and the two answers stay.

- **Yes** starts `workout adapt -m` with the athlete's own words, beside the chat (§6). From
  there it is any message to the coach, and a proposal comes back.
- **No** writes nothing: "Okay — I'll leave it.", as today.
- **No answer.** It closes without a word after three more mornings, or sooner when the day of
  the session it names is over.

It is a confirmation like the question of §4, under the same three rules. Its kind is
`pass_to_coach`. The answer calls `_hand_off_to_coach`, which no longer runs inside the capture.

Amended 2026-10-15 (DESIGN_chat_questions.md §4): the same kind now replaces the button "📨 Send
it to your coach as written". A capture that finds nothing asks "I'm not sure what to do with
that one 🤔 — but I don't want to lose it. Shall I pass it to your coach?". A preference with no
end date gets the question after the sentence that says where a preference belongs. Neither
names a session, so only the `confirmation-days` mornings close it.

## 6. A tap that starts a long run

Today a tap on a queued question runs `bot queue` in the chat's own place. That command checks
the item, applies the answer, and sends the next question. An answer that asks the week planner
would hold the chat while it thinks.

A kind of queued question can now name the answer that starts a long run. When a tap on that
answer arrives, the bot reads the item's kind and runs the tap in the second place. The item is
checked and closed as for any answer, and the long run goes on in the same command. Three kinds
name one: "Plan them" of `replace_sessions` (§4), "Yes" of `pass_to_coach` (§5), and "Yes" of
`adjust_week` (amended 2026-10-15, DESIGN_chat_questions.md §4).

While another long run is alive, the tap is kept and run when that run ends (§7).

## 7. One long run at a time

While a long run is alive, the chat takes everything else at once: the keyboard buttons, a
question about a goal, a tap on a proposal, a gym log. It never starts a second long run beside
the first: two runs would each read the same week and propose changes to a week the other is
about to change.

A second long run is kept instead, and started when the first one ends. That is a message to
the coach, "😴 Feeling tired", "🕐 Can't today", "📅 Plan my next weeks", or a tap of §6. Today a
message to the coach is refused and must be sent again (DESIGN_waiting_proposal.md §6.2).

It is 08:01 and the morning run thinks. The athlete writes "I'm tired". The bot answers at once:

> I'm preparing your morning message — I'll pass this on right after.

At 08:02 the morning message arrives, and the message to the coach starts. Its proposal follows
a minute later. Had the athlete written again at 08:01:30, that message would wait behind the
first, and start when it ends. Each run is shown the proposal the run before it made, and its
own replaces it (DESIGN_waiting_proposal.md §6.2, "A proposal waits").

The sentence names the run that is alive:

| The run that is alive | The sentence |
|---|---|
| a message to the coach, typed, sent by a button or by a tap of §5 | "I'm still working on your last message — I'll pass this one on right after." |
| the morning run | "I'm preparing your morning message — I'll pass this on right after." |
| `workout generate --propose` | "I'm still planning your next weeks — I'll pass this on right after." |

A run that waits on a question of its own keeps today's sentence: "I asked you something above.
Answer it, then send that again." Nothing is kept then: the answer decides what the run does.
Today that is `workout adapt` asking "Was that the session, cut short?".

## 8. The Stop button

The ✋ Stop button was built on 9 September (DESIGN_bot_stop_button.md). It hangs under a wait
notice and ends the run that printed it. It was built for an athlete who sends "move tomorrow's
run to Friday", sees at once that they meant Saturday, and must wait 40 seconds for an answer
they do not want while the chat is held.

Three facts have changed since.

- **A wrong answer writes nothing.** Since 3 October a run started from the chat saves a
  proposal and waits for a tap (DESIGN_waiting_proposal.md §2). The wrong answer is a proposal
  the athlete does not tap.
- **The chat is not held.** After this design, no long run holds it.
- **The button has never been shown.** The bot writes a line in its journal each time it
  attaches one. There is no such line on any day from 9 September to 13 October, on either
  instance. The likely cause, not confirmed: the bot sends the notice with the bottom keyboard,
  then adds the button by editing that message, and Telegram does not let a bot edit a message
  sent with that keyboard.

**The button is removed** (ruled 2026-10-14). `/cancel` stays, and ends the command in both
places, as today. What goes: the button, its tap, the "Stopped." and "That's already finished"
lines, and the mark on a flush that says whether a wait follows. The bot keeps listening to
Telegram while a command computes (DESIGN_bot_stop_button.md §5): `/cancel` and the second
place both need it.

## 9. Choices made for you

Each one can be overruled without touching the others. The numbers are the ones the author was
given them under.

1. **The sentence when the bot cannot start a second long run at once** (§7). **Ruled
   2026-10-14: B,** today's sentence when the athlete sent a message, and its own sentence for
   the morning run.
   - **1a. A third sentence, for `workout generate`.** **Ruled 2026-10-14: as designed.**
   - **1b. Keep the second long run instead of refusing it.** **Ruled 2026-10-14: keep it.**
   - **1c. The three sentences, reworded to fit 1b.** As ruled in 1 and 1a they ended "send that
     again in a minute", which is false once the message is kept. They now end "I'll pass this
     on right after". The other way: no sentence at all. The athlete gets the ordinary echo,
     "→ passing that on to your coach", and the run starts later without a word. **Ruled
     2026-10-14: as designed.**
2. **`workout generate` saves its result** (§4). **Ruled 2026-10-08.**
   - **2a. It waits beside a proposal.** **Ruled 2026-10-14: as designed.**
   - **2b. Which changes spoil the saved weeks** (§4, "A tap that comes too late"). Only a
     session written inside the weeks' own days spoils them. The other way: any change to any
     session does, as for a proposal. Then easing today's ride makes the athlete tap "📅 Plan my
     next weeks" again and wait about five minutes again. **Ruled 2026-10-14: as designed.**
   - **2c. "…Regenerate?"** **Ruled 2026-10-14: a saved question whose answer starts the
     planning** (§4, §6).
   - **2d. The words.** **Ruled 2026-10-14: as designed.**
   - **2e. On an out-of-date plan, a chat run stops and says so.** **Ruled 2026-10-14: as
     designed.**
   - **2f. How the saved "…Regenerate?" reads and how long it lives** (§4). **Ruled 2026-10-14:**
     like the other confirmations, three more mornings by `confirmation-days`. **Ruled
     2026-10-15, after the code review:** a session written on its days no longer closes it;
     only its first day being over does. The author's words: "drop it".
3. **The hand-off** (§5). **Ruled 2026-10-14: a saved Yes/No question.** The author's words:
   "I really think all the bot's questions should go through the queue, even if this means
   adding more features to the queue. That is a general principle."
   - **3a. How long the hand-off question lives** (§5). **Ruled 2026-10-14:** like the other
     confirmations, and sooner when the day of the session it names is over.
4. **The morning run says so when the week changed under it** (§3). **Ruled 2026-10-14: B,** one
   line: "I had a change in mind, but your week changed while I was thinking." **Replaced
   2026-10-20** on the author's ask by the week lock (§3): the week no longer changes under it.
5. **`/workout generate` typed in the chat** (§2, §4). **Ruled 2026-10-14: B,** it keeps today's
   behaviour. So the button sends a flag the typed command does not have, `--propose`.
6. **The Stop button** (§8). **Ruled 2026-10-14: removed.**

## 10. Not handled

- A tap on "Schedule them" writes sessions. That puts a proposal that still waits out of date,
  whatever its days (DESIGN_waiting_proposal.md §4, rule 1).
- When sessions already stand in the days to write, the weeks take two taps: "Plan them", then
  "Schedule them".
- The morning message can arrive in the middle of an exchange the athlete began during the
  morning run. A proposal from the coach's run already can.
- What the bot keeps (§7) lives in its memory. A restart of the bot loses it, and `/cancel`
  drops it.
- `/cancel` ends both places. Typed during the morning run, it ends that run too, and the day
  has no morning message.
- The morning run, a notice about a changed week and the next queued question wait while
  `workout generate` thinks, which can be several minutes.
- `plan generate`, `data pull` and `/workout generate` without `--propose`, typed with a slash,
  still hold the chat. Only the operator types them.
- Two long runs started in the same few milliseconds both run.

## 11. Build order

Each step works on its own.

1. **The morning run** (§3, §7): `bot morning` in the second place, the check on a week that
   changed and its line, the sentences.
2. **A tap that starts a long run, and the hand-off** (§5, §6).
3. **`workout generate --propose`** (§4): the flag and the button, the second place, the saved
   result, the saved "…Regenerate?", the stop on an out-of-date plan.
4. **The Stop button** (§8).

## 12. Touch points

| Where | What |
|---|---|
| `stamind/chat/routing.py` | the test that picks the second place names the long runs of §2 |
| `stamind/chat/runner.py`, `stamind/chat/app.py` | the second place is named for what it holds, a long run; a second long run is kept and started when the first ends; the sentences of §7 |
| `stamind/chat/callbacks.py` | a tap on an answer that starts a long run runs in the second place, or is kept |
| `stamind/settings.py` | the setting `confirmation-days`, unless DESIGN_chat_questions.md has added it first |
| `stamind/queue_kind.py`, `stamind/athlete_queue.py` | a kind can name the answer that starts a long run; three kinds join the list: `schedule`, `replace_sessions`, `pass_to_coach` |
| `stamind/cli/bot/views.py` | the morning run saves and writes nothing when a session was written since it read the week, and prints the line of §3 |
| `stamind/cli/bot/edit.py` | the hand-off is queued; its "Yes" calls `_hand_off_to_coach` |
| `stamind/coach/proposals.py` | what a tap on a `schedule` item writes, to and from JSON: the fields `workout_generate_apply` reads |
| `stamind/cli/workouts/proposal.py` | the `schedule` and `replace_sessions` kinds: their words, their rules, what each answer does. Rules 2 and 3 are shared with `proposal` |
| `stamind/db/workout_history.py` | one read: whether a change after a given one wrote a session between two days |
| `stamind/cli/workouts/generate.py`, `parser.py` | `--propose`: asks nothing, stops on an out-of-date plan, queues "…Regenerate?", checks rule 1 before it saves, then saves and sends in place of its last question |
| `stamind/cli/runway.py` | the button sends `--propose` |
| `stamind/cli/render/` | the sentence for an out-of-date plan, the line of §3, and the words of the new questions |
| `stamind/chat/replies.py`, `callbacks.py`, `keyboards.py`, `runner.py`, `stamind/sentinels.py` | the Stop button and the flush mark go |
| `docs/ARCHITECTURE.md` | the bot section, the list of kinds |

Implemented designs amended as each step lands: DESIGN_waiting_proposal.md §6.1 (its last
paragraph) and §8 (its last item); DESIGN_bot_simple_frontend.md §12.4 (the hand-off);
DESIGN_runway_nudge.md §6 (the button sends `--propose`, and its result is saved);
DESIGN_athlete_queue.md §8 and §13.2 (the new kinds, and an answer that starts a long run);
DESIGN_bot_stop_button.md (removed, §5 kept); DESIGN_output_verbosity.md §7.3 and §8.4 (no Stop
button to mention).

Designs still in progress are not edited, but for one correction the author asked for on
2026-10-14: DESIGN_chat_questions.md now describes this design as it stands (its opening, §7
and §9).

Tests, one per rule: a tap on a keyboard button during the morning run is answered; a message
to the coach during the morning run gets its sentence and starts when the morning run ends; two
kept messages start one after the other, in the order they came; the morning run writes nothing
when a session was written while it thought, and says so; a second long run is kept while
`workout generate --propose` is alive, with its sentence; a tap on "Yes" of the hand-off runs
`workout adapt -m` with the athlete's words beside the chat, and is kept while another long run
is alive; "No" writes nothing; both saved questions close after `confirmation-days` mornings.
For the saved result: a run with `--propose` writes nothing and ends with its item sent;
"Schedule them" writes what was saved and not what asking again would return; each of the three
rules refuses the tap and writes nothing; a change outside its days leaves it open; saving one
leaves a waiting proposal open, and the other way round; with sessions in its days it queues
"…Regenerate?" and calls no planner, and "Plan them" starts the planning; on an out-of-date plan
it calls no planner, saves nothing and says its sentence; typed without the flag, and in a
terminal, it still asks.
