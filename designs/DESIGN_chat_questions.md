# Design: The last questions the chat asks on the spot

**Status:** Proposed · **Date:** 2026-10-10 · not built

This design stands on revision 4 of the athlete queue (DESIGN_athlete_queue.md §13), which is
built and on main since 2026-10-11. The athlete queue is the stored list of things Stamind
wants to ask or tell the athlete. Revision 4 gives it one line and one
rule for when an item is sent. So this design does not say when a question arrives. It says,
for each question, what it asks, what its answers do, and when it closes itself.

Three neighbouring questions are settled in DESIGN_long_runs_beside_chat.md and are not
designed again here (§7).

## 1. The problem

The author's rule of 2026-10-09: in the chat, every question goes through the athlete queue.
The command saves the question and ends, and a tap answers it whenever the athlete likes
(DESIGN_athlete_queue.md §2). Five questions do not follow it. Each is asked by a command that
then waits. After five minutes without a tap the bot says "No answer, so I stopped there.",
the command ends, and what the athlete wrote is lost.

**The worst case stops the coach before it has started.** It is Friday 16 October 2026,
12:15. Thursday had a 90-minute ride planned, and Garmin recorded one ride of 20 minutes that
day. The athlete writes "I'm tired, can we go easier this weekend?" and puts the phone down.
`workout adapt` first asks "Was that the session, cut short?". At 12:20 nobody has answered.
The run ends. The week planner, the model call that writes the sessions, was never called. No
proposal is made, and the message has to be written again.

| The question | Asked after | By |
|---|---|---|
| "Was that the session, cut short?" | any message to the coach, when an activity is far shorter than the session it is paired with | `workout adapt` |
| "Shall I set that up?" | "I want to run a half marathon on May 10" | `bot capture add_goal` |
| "Shall I make that change?" | "the work trip moved to the 27th" | `bot capture edit_goal`, `edit_constraint` |
| "… OK?" | "message me at 7 instead" | `bot capture change_setting` |
| "… Shall I write it down?" | "the FTP test gave 236 W" | `bot capture test_result` |

A sixth question waits on nobody and is still lost: "Which one did you mean?" (§5).

## 2. The rule

A command started from the chat, or by a run nobody watches, never waits. It saves its
question as a queue item. Then it ends, or it goes on with what it already knows.

Four of the five are **confirmations**: questions that ask the athlete to confirm what the chat
understood from the message they just wrote, before anything is written. Three rules hold for
all of them.

- **A confirmation comes at once**, whatever else is waiting, because the athlete is at the
  screen and has just written about it. It is a reply in the sense of revision 4 (§13.2, rule
  6). While it waits for its tap it stands at the front of the line, with the cut-short
  question (§3). So on a later morning it is sent before the older questions.
- **It lives three days.** It is sent on the day it is asked, and again after the briefing on
  each of the next three mornings. On the fourth morning it is closed without a word. The
  number is a setting, `confirmation-days`, and three is its default (§8, choice 14).
- **It names what it asks about**, with the word the athlete knows the thing by: "this goal",
  "this constraint", "this setting", "this test result". "Shall I set that up?" and "… OK?"
  name nothing.

Three confirmations exist already: "Shall I remember this constraint?", "Shall I log this
signal?" and "Which of today's sessions was that about?" (DESIGN_waiting_proposal.md §6.3,
DESIGN_session_notes.md §3). They come at once today. They take the other two rules as well,
so that every confirmation behaves the same. On 7 October the athlete writes "No training on
November 12th" and never taps. The question is sent that day and on the next three mornings.
On 11 October it is closed, and the constraint is not stored. Today it would be sent each
morning until 12 November.

All of them are drawn bare: no "🙋 Quick question" above, no "Not now" under
(DESIGN_waiting_proposal.md §6.3). What the command prints before its question
today becomes part of the question, in one message, because a question left unanswered is sent
again whole the next morning.

The cut-short question is not a confirmation. The athlete wrote about something else. It is an
ordinary question, with "Not now" under it, and it stands at the front of the line (§3).

A terminal keeps asking on the spot, because someone sits there.

## 3. "Was that the session, cut short?"

The question exists because the data cannot tell a session cut short from a warm-up. Its
answer is stored, and it is asked once for a given activity and session.

Today the run that asks it waits for the answer before it calls the week planner. A run nobody
watches does not ask. It goes on with the app's own pairing: the activity counts as the
session, partly done, with the minutes it really had.

**After.** Every run that is not typed in a terminal does the same thing. It queues the
question, goes on with the app's own pairing, and calls the week planner. The morning run does
so too, and that is new: today it never asks.

It is Friday 16 October, 08:00. The morning run finds Thursday's pair and queues the question.
The briefing arrives, and the question after it:

> 🙋 Quick question
> Planned: Thu Oct 15 — Endurance Ride, 1h30
> Only matching activity: Zwift ride, 20 min — far short of it.
> Was that the session, cut short? (No = it was something else, e.g. a warm-up to discard)
>
> `[✅ Yes]` `[✖️ No]` `[Not now]`

The words and the two answers are today's.

- **Yes** stores the answer. "Counted as that session, partially performed."
- **No** stores the answer. "Discarded — the session reads as not done." The 20-minute ride is
  then read as something else the athlete did.
- **No answer.** It comes back with the next morning's questions.

At 12:15 the athlete writes "I'm tired, can we go easier this weekend?". Nothing is asked. The
week planner is called at once.

**The question goes to the front of the line.** The line is the waiting questions in the order
the bot sends them, one at a time, the one that became ready first at the head
(DESIGN_athlete_queue.md §13.2). The cut-short question stands before all of them, because
the coach's next run reads its answer and no other waiting question is read that way.

On that Friday a question about the names of Tuesday's gym sets has waited since Wednesday,
and the athlete has left it twice. It is the older one. In the order of the line it would come
first after the briefing. The athlete would leave it a third time, the cut-short question
would not be asked that day, and the 12:15 proposal would rest on the app's own pairing. At
the front, the cut-short question is the one that follows the briefing.

The front is the front of what has not been sent. A question sent earlier that day and not
tapped still holds the cut-short question back, until the tap or the next morning.

Had the short ride been ridden on Friday at 11:00, the 12:15 run would be the one to find it.
It queues the question and calls the week planner with the pairing as it stands. The proposal
arrives at 12:17 and rests on that pairing, wherever the question stands. The question follows
the tap on the proposal, or comes within five minutes when there is no proposal. Both are the
line's doing (DESIGN_athlete_queue.md §13.2, rules 4 and 6).

The question closes without a word when it is no longer open: the athlete answered it in a
terminal, the session was removed, or its day is further back than the days `workout adapt`
looks back over. The check is the one that finds the question in the first place.

**What the answer changes for the week planner.** For a session of a past day, the facts it
reads are the same either way: 20 minutes were ridden and the 90 were not. Only the label
differs. Taken as cut short, the session's line says "[PARTIAL — actually performed: 20m, load
… — locked history, not adaptable]", and the evidence says "Discrepancy in 'Endurance Ride'
vs 'Zwift ride': duration mismatch …". After a "No", the evidence says "Complete Miss! Missed
planned workout 'Endurance Ride' (cycling)." and the 20 minutes stand among the Garmin
activities. For a session of today the answer changes more. Taken as cut short, the line says
"performed so far today: 20m … salvage what remains of it, move the exposure, or write the day
off". After a "No", the session is listed as planned with nothing against it: it is still
ahead of the athlete. Whether the week planner decides differently on the two labels of a past
day was not measured.

## 4. Three confirmations: a new goal, an edit, a setting

Each reads back what a short model call understood, and writes only on "Yes". They become
three bare questions with the same two answers, under the three rules of §2.

**A new goal.** The athlete writes "I want to run a half marathon on May 10".

> Here's what I've got:
> 🏃 Half marathon — on Mon May 10 (in 7 months)
> Shall I set up this goal?
>
> `[✅ Yes]` `[✖️ No]`

"Yes" adds the goal, as today. "No" answers "Okay — nothing set up." Today the question is
"Shall I set that up?".

**An edit.** The athlete has a constraint "Away for work", from Monday 26 to Wednesday 28
October. They write "the work trip moved to the 27th".

> Your constraint “Away for work” — Mon Oct 26 to Wed Oct 28
> → make it Tue Oct 27 to Thu Oct 29
> Shall I change this constraint?
>
> `[✅ Yes]` `[✖️ No]`

"Yes" makes the change. "No" answers "Okay — nothing changed." and, when other constraints
exist, asks "Which constraint should I change?" (§5). For a goal the two questions say "this
goal" and "Which goal". Today they are "Shall I make that change?" and "Which one should I
change?". The first line is drawn from the stored constraint each time the question is sent,
so it always shows the constraint as it is. The question also closes without a word, before
its three days, when the constraint or goal is gone or already reads as asked.

**A setting.** The athlete writes "message me at 7 instead".

> I'll open your day at 07:00 from tomorrow. Shall I change this setting?
>
> `[✅ Yes]` `[✖️ No]`

"Yes" stores it: "Done — that's set 👍", as today. "No" answers "Okay — I've left it as it
was." Today the question ends with "OK?". The first sentence is written each time the
question is sent, so "from tomorrow" is true on the morning it is sent again. The question
also closes without a word when the setting already has that value.

**A newer question closes an older one only when both would change the same thing.** Suppose
the question above had moved the first day only: "→ make it Tue Oct 27 to Wed Oct 28". The
athlete does not tap "No". They write "the work trip is now the 27th to the 29th". The second
question closes the first, because both would change the dates of the same constraint.

Every other waiting question stays. One about another constraint stays: a question about
"Family visit" is not touched. One about a goal, a setting or a test stays. And one about
another part of the same constraint stays: the first asks to move "Away for work" by a day,
and the athlete then writes "call it Berlin trip". Both wait, and each "Yes" writes its own
part. A goal or a constraint has three parts here: its dates, its name and its note.

The rule in full: a newer question closes an older one when it would change every part the
older one would change. An older question about the dates and the name is not closed by a
newer one about the name alone, because its dates would be lost.

The same holds for two questions about one setting, or about the result of one test.

## 5. "Which one did you mean?"

The athlete has two constraints, "Away for work" and "Family visit". They write "push my trip
back a day". The command cannot tell which one, and asks:

> Which constraint did you mean?
> • Away for work — Mon Oct 26 to Wed Oct 28
> • Family visit — Sat Oct 31 to Sun Nov 1
>
> `[Away for work]` `[Family visit]` `[✖️ None of these]`

Today these buttons are not a queue item. The bot keeps one row of such buttons per chat, in
memory. The next row sent to the chat retires it, the morning message included, and so does a
restart of the bot. A tap then answers "That offer expired — just send it again."

It becomes a confirmation like the others (§2), with one answer per goal or constraint. A tap on
one reads the athlete's words again with that one named, which takes about two seconds, and
sends the edit question of §4. "None of these" answers "No problem — tell me again in your own
words 💬". Today the question is "Which one did you mean?". It also closes without a word when
none of the goals or constraints it lists is left.

## 6. The test result

Two questions are about a test result, and one is already in the queue.

It is Thursday 15 October, 08:00. Wednesday's FTP test is done and the logbook holds no result
for it. The briefing is followed by a queued question: "How did Wednesday's “FTP Test” go?
Tell me the number it gave you and I'll write it down." The athlete taps "Tell me the number"
and types "236".

Today the command that reads "236" asks for the confirmation and waits five minutes for a tap.

**After.** That command queues the confirmation, sends it, and ends:

> Your FTP from the test on Wednesday, “FTP Test”: 236 W, up from 235 W (+1 W). Shall I write
> down this test result?
>
> `[✅ Yes]` `[✖️ No]`

Today it ends with "Shall I write it down?". It is a confirmation under the three rules of §2.

That command also puts the first question off until the next morning. The queue already does
that with an answer it could not apply (DESIGN_athlete_queue.md §13.5, choice 14).

- **Yes**, at 13:00: "Written down 💪". On Friday morning the first question finds a result in
  the logbook and closes without a word.
- **No**: "Okay — nothing written down." On Friday the briefing is followed by "How did
  Wednesday's “FTP Test” go?" again, under "⏰ You asked me to come back to this:", as every
  question put off comes back.
- **No answer.** On Friday, Saturday and Sunday the confirmation comes back first, and the first
  question waits behind it. On Monday the confirmation is closed without a word, and "How did
  Wednesday's “FTP Test” go?" is asked again.

Nothing links the two questions. The first one already closes when the logbook holds a result,
and the line already orders them by the time each became ready.

A result the athlete writes unasked, "the FTP test gave 236 W", gets the same confirmation as a
reply.

The confirmation compares with the latest result when it is sent, so "up from 235 W" is true
each time. It also closes without a word when the logbook already holds a result for that
test. A
typed answer with no number in it is treated as today: "I didn't catch the number…", and the
first question waits.

## 7. Settled elsewhere

DESIGN_long_runs_beside_chat.md, proposed on 2026-10-08 and ruled on 2026-10-14, holds three
more:

- The question after `workout generate` thinks, "Schedule these 12 workouts…?", becomes a saved
  item with two buttons (§4 there).
- "…Regenerate?", asked before `workout generate` thinks when sessions already stand in the
  days it would write, becomes a saved question. Its "Plan them" starts the planning (§4 and
  §6 there).
- "Shall I pass it to your coach?", asked when a message about a session lands on the goal or
  constraint lane, becomes a saved question. Its "Yes" passes the athlete's words to the coach
  (§5 and §6 there).

The last two are confirmations under the three rules of §2. "…Proceed anyway?", asked when the
plan, the periodization, is out of date, is no longer asked in the chat: the run stops and says
why (§4 there).

## 8. Choices made without the author

The numbers are the ones the author was given them under. All are ruled.

1. **The cut-short question no longer comes before the week planner's call** (§3). Today the
   athlete answers "No, it was a warm-up" at 12:15 and the proposal of 12:17 knows Thursday's
   ride was not done. After, that proposal reads 20 of the 90 minutes as done, and the answer
   reaches the next run. The other way keeps the question first and the run waiting, which is
   the problem of §1. **Ruled 2026-10-11.** The author asked whether the queue could put the
   question at the front, and said yes to it: the question stands first in the line (§3). With
   choice 2 it is then asked right after the briefing, before the athlete writes. A proposal
   made by the very run that finds the short activity still rests on the app's own pairing.
2. **The morning run queues the cut-short question too** (§3). Today it is asked only when the
   athlete happens to write to the coach, days later or never. The other way leaves the
   morning run as it is, and the question still arrives behind a proposal built on the guess.
   **Ruled 2026-10-10: ok.**
3. **A setting keeps its question.** The other way changes it at once and says so: "Done — I'll
   open your day at 07:00 from tomorrow." A misread then shows the next morning, when the
   message comes at the wrong hour or not at all. **Ruled 2026-10-11: ack.**
4. **A newer question closes an older one about the same thing** (§4). The other way lets both
   wait. The first then comes back the next morning and offers the dates the athlete already
   corrected. **Ruled 2026-10-11: fine.** The author then asked whether an unrelated question
   would be closed as well. It is not. Added the same day: "the same thing" is
   the same part of the same goal or constraint, and the newer question must change every
   part the older one would. As first written, a question to rename a constraint would have
   closed one that waited to move its dates, and the dates would have been lost without a
   word. **Ruled 2026-10-13: ack.**
5. **After a "No" on the cut-short question, the chat offers nothing more.** Until
   the athlete answers, the app takes the short activity for the planned session, cut short.
   A "No" says the session was not done at all. By then a run of the coach has read the week
   the first way: the morning run that queued the question, at the least. It is Friday 08:00.
   The morning run reads Thursday's 20 minutes as the 90-minute ride cut short, and proposes a
   change or leaves the week alone. Then the question arrives and the athlete answers "No". As
   designed, the chat confirms and stops, and the next run reads the answer: Saturday
   morning's, or sooner if the athlete writes to the coach. The other way adds the button
   "🔄 Adjust my week around it" under that line, which makes the coach look at the
   week again at once. **Ruled 2026-10-13: as designed.** The author's reason: on Friday the
   20 minutes are the past either way, and the 90-minute ride will not be done.
6. **The confirmations come at once** (§2). The athlete writes "message me at 7" while this
   morning's question about a test is still unanswered. The question about the setting arrives
   at once. In one strict line it would stand behind the test question and not be asked that
   day. **Ruled 2026-10-11:** they come at once and are put at the front of the question
   queue, because the athlete is at the screen and has just written about it. They also use
   the agreed words: constraint, signal, goal and so on. So a confirmation stands at the front of
   the line while it waits, and names what it asks about (choice 13).
7. **"Which one did you mean?" becomes a queued question** (§5). The other way leaves it as
   buttons that the next row of buttons retires. **Ruled 2026-10-11: as designed.**
8. **A typed test number puts the first question off until the next morning** (§6). The other
   way closes it at once. Then a "No" on the confirmation leaves nothing that asks again, and the
   test stays without a result. **Ruled 2026-10-11: as designed.**
9. **How long an unanswered confirmation lives.** First designed with no limit: sent again each
   morning until the goal's date, and for an edit with no date at all. **Ruled 2026-10-11:**
   "Lives for a few days and then closes without a word." (§2).
10. **The cut-short question keeps today's words and answers** (§3). First designed with the
    answers "Yes, cut short" and "No, something else", and without the parenthesis. **Ruled
    2026-10-11: leave as is.**
11. **The reply to a setting's "Yes" stays "Done — that's set 👍"** (§4). First designed to say
    the effect again, because the tap can come a day after the question. **Ruled 2026-10-11:
    leave as is.**
12. **"A few days" is three.** The athlete names a goal on Monday and never taps.
    The question is sent on Monday, and again after the briefing on Tuesday, Wednesday and
    Thursday. On Friday it is closed. The other ways are two days or a week. **Ruled
    2026-10-13: ack**, and with choice 14 the number became a key in `config.yaml`.
13. **The words of each question.** The author asked for the agreed words, and these are the
    sentences that follow from it. **Ruled 2026-10-13: ack.**

    | Today | After |
    |---|---|
    | "Shall I set that up?" | "Shall I set up this goal?" |
    | "Shall I make that change?" | "Shall I change this goal?", "Shall I change this constraint?" |
    | "… OK?" | "… Shall I change this setting?" |
    | "… Shall I write it down?" | "… Shall I write down this test result?" |
    | "Which one did you mean?" | "Which goal did you mean?", "Which constraint did you mean?" |
    | "Which one should I change?" | "Which goal should I change?", "Which constraint should I change?" |

14. **The three confirmations that exist already take the same rules** (§2). First designed
    unchanged: they stood in the line by their age and lived until their own date, a constraint
    question until the constraint's last day. **Ruled 2026-10-13:** the same rule for all, with
    the number of days as a parameter. The author named it `confirmation_days` and preferred a
    setting to a key read from the file alone. So it is the setting `confirmation-days`: its
    default of three can be set in `config.yaml` as `telegram.confirmation_days`, and `sm
    settings set confirmation-days 5` overrides it for one instance. A message in the chat
    cannot change it. This design called these questions read-backs until then; it now uses
    the setting's word.

## 9. Not handled

- A typed "yes". Today the chat answers that it is busy. After, the command has ended, so the
  word is read as a new message and nothing knows what it answers. The constraint question
  has behaved so since 2026-10-09.
- Two replies can be open at once: the athlete writes "message me at 7", then names a goal
  before tapping. Each tap lands on its own question.
- A proposal made at 12:17 on the app's own pairing is not made again when the cut-short
  question is answered "No".

## 10. Touch points

It is built on revision 4, one question at a time. Each of the six is independent of the
others. Revision 4 already gives what they need but one thing: a run sends its own replies, an
answer that could not be applied puts its item off until the next morning, and a kind's own
check runs before a send and on a tap. The one new thing is a kind whose items stand first in
the line.

| Where | What |
|---|---|
| `stamind/cli/workouts/adapt.py` | the cut-short question is asked on the spot only in a terminal with someone there; every other run queues it and goes on |
| `stamind/coach/service/matching.py` | unchanged: `pending_match_questions` finds the question and is its check, `record_match_decision` stores the answer |
| `stamind/cli/bot/capture.py`, `edit.py`, `test_result.py` | a chat run queues its question and sends it, in place of the confirm; "No" on an edit and several candidates queue the picker; the buttons with the athlete's words in them go |
| `stamind/cli/benchmarks.py` | `benchmark record` takes the answer already given, as `--yes` does |
| `stamind/athlete_queue.py` | six kinds join the list: the cut-short question, the new goal, the edit, the picker, the setting, the confirmation of a test; the line puts the items of a kind marked first before the others; a confirmation's check closes it on the fourth morning |
| `stamind/queue_kind.py` | a kind can be marked first: the cut-short question and every confirmation are |
| `stamind/cli/candidates.py` | the constraint, signal and session-note questions are marked first, and their checks also close them on the fourth morning |
| `stamind/settings.py`, `config_template_full.yaml` | the setting `confirmation-days`, a number of days, seeded by `telegram.confirmation_days`, default 3; not among the settings a chat message may change |
| `stamind/cli/render/` | the new words of the confirmations (§8, choice 13) |
| `docs/ARCHITECTURE.md` | the bot's capture lanes, the matching section, the list of kinds |

Sections amended when it lands: DESIGN_athlete_queue.md §2 (the list of questions that do not
follow the rule), §8 and §13.2, rule 2 (the order of the line); DESIGN_bot_simple_frontend.md
§12.2, §12.4, §12.5 and §12.7; DESIGN_benchmark_from_chat.md §3 and §4; DESIGN_waiting_proposal.md
§6.3 and DESIGN_session_notes.md §3 (where a confirmation stands and how long it lives);
ARCHITECTURE.md §15. Designs still in progress are not edited.

Tests, one per behaviour: a chat run of `workout adapt` with a short activity calls the week
planner and leaves the question waiting; the morning run queues it; it is sent before an
older question that waits, and not before one that is out; each answer stores the
decision, and an answer given in a terminal closes the item; a terminal still asks on the
spot; each confirmation writes on "Yes" and nothing on "No", and its text holds the preview; an
edit question shows the constraint as it is when sent, and closes when the constraint is gone;
a second question about the same part of the same constraint closes the first, and one about
another constraint, or about only some of the parts the first would change, does not; the
picker's tap sends the edit
question, and "None of these" writes nothing; a typed test number sends the confirmation and puts
the first question off, "Yes" closes the first question the next morning, "No" leaves it; a
confirmation left unanswered is sent before an older question on each of the next three mornings
and is closed on the fourth, the constraint question included, and the number of mornings
follows the `confirmation-days` setting; each confirmation's question names a goal, a constraint, a
setting or a test result.
