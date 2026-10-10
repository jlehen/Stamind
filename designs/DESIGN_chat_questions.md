# Design: The last questions the chat asks on the spot

**Status:** Proposed · **Date:** 2026-10-10 · not built

This design stands on revision 4 of the athlete queue (DESIGN_athlete_queue.md §13), which is
designed and not built. The athlete queue is the stored list of things Stamind wants to ask or
tell the athlete. Revision 4 gives it one line and one rule for when an item is sent. So this
design does not say when a question arrives. It says, for each question, what it asks, what
its answers do, and when it closes itself.

Two neighbouring questions are settled in DESIGN_long_runs_beside_chat.md and are not designed
again here (§7).

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

Four of the five are **replies**: questions about what the athlete just wrote. Revision 4
sends a reply at once, whatever else is waiting, and the line waits for its answer (§13.2,
rule 6). They are drawn bare, like "Shall I remember this constraint?": no "🙋 Quick question"
above, no "Not now" under (DESIGN_waiting_proposal.md §6.3). What the command prints before
its question today becomes part of the question, in one message, because a question left
unanswered is sent again whole the next morning.

The cut-short question is not a reply. The athlete wrote about something else. It is an
ordinary question, and it takes its turn in the line.

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
> Was that the session, cut short?
>
> `[✅ Yes, cut short]` `[✖️ No, something else]` `[Not now]`

- **Yes, cut short** stores the answer. "Counted as that session, partially performed."
- **No, something else** stores the answer. "Discarded — the session reads as not done." The
  20-minute ride is then read as something else the athlete did.
- **No answer.** It comes back with the next morning's questions.

At 12:15 the athlete writes "I'm tired, can we go easier this weekend?". Nothing is asked. The
week planner is called at once.

Had the short ride been ridden on Friday at 11:00, the 12:15 run would be the one to find it.
It queues the question and calls the week planner with the pairing as it stands. The proposal
arrives at 12:17. The question follows the tap on the proposal, or comes within five minutes
when there is no proposal. Both are the line's doing (§13.2, rules 4 and 6, and §13.5,
choice 4, which the author has not ruled on).

The question closes without a word when it is no longer open: the athlete answered it in a
terminal, the session was removed, or its day is further back than the days `workout adapt`
looks back over. The check is the one that finds the question in the first place.

## 4. The three read-backs: a new goal, an edit, a setting

Each reads back what a short model call understood, and writes only on "Yes". They become
three bare questions with the same two answers.

**A new goal.** The athlete writes "I want to run a half marathon on May 10".

> Here's what I've got:
> 🏃 Half marathon — on Mon May 10 (in 7 months)
> Shall I set that up?
>
> `[✅ Yes]` `[✖️ No]`

"Yes" adds the goal, as today. "No" answers "Okay — nothing set up." The question closes
without a word once the goal's date is behind.

**An edit.** The athlete has a constraint "Away for work", from Monday 26 to Wednesday 28
October. They write "the work trip moved to the 27th".

> Your constraint “Away for work” — Mon Oct 26 to Wed Oct 28
> → make it Tue Oct 27 to Thu Oct 29
> Shall I make that change?
>
> `[✅ Yes]` `[✖️ No]`

"Yes" makes the change. "No" answers "Okay — nothing changed." and, when other constraints
exist, asks "Which one should I change?" (§5). The first line is drawn from the stored
constraint each time the question is sent, so it always shows the constraint as it is. The
question closes without a word when the constraint or goal is gone, or already reads as asked.

**A setting.** The athlete writes "message me at 7 instead".

> I'll open your day at 07:00 from tomorrow. OK?
>
> `[✅ Yes]` `[✖️ No]`

"No" answers "Okay — I've left it as it was." "Yes" stores it, and the reply says the effect
again as it stands at the tap. It is Monday 21:00 when the athlete writes, and Tuesday 12:00
when they tap "Yes" on Monday's question. The reply is "Done — I'll open your day at 07:00 from
tomorrow.", which now means Wednesday. Today the reply is "Done — that's set 👍", because the
question was read seconds before. The question closes without a word when the setting already
has that value.

**One question waits per thing.** The athlete writes "the work trip moved to the 27th", reads
the question and sees it is wrong. They do not tap "No". They write "the work trip is the 27th
to the 30th". The second question closes the first. The same holds for two questions about one
goal, one setting or one test.

## 5. "Which one did you mean?"

The athlete has two constraints, "Away for work" and "Family visit". They write "push my trip
back a day". The command cannot tell which one, and asks:

> Which one did you mean?
> • Away for work — Mon Oct 26 to Wed Oct 28
> • Family visit — Sat Oct 31 to Sun Nov 1
>
> `[Away for work]` `[Family visit]` `[✖️ None of these]`

Today these buttons are not a queue item. The bot keeps one row of such buttons per chat, in
memory. The next row sent to the chat retires it, the morning message included, and so does a
restart of the bot. A tap then answers "That offer expired — just send it again."

It becomes a bare question, with one answer per goal or constraint. A tap on one reads the
athlete's words again with that one named, which takes about two seconds, and sends the edit
question of §4. "None of these" answers "No problem — tell me again in your own words 💬". The
question closes without a word when none of the things it lists is left.

## 6. The test result

Two questions are about a test result, and one is already in the queue.

It is Thursday 15 October, 08:00. Wednesday's FTP test is done and the logbook holds no result
for it. The briefing is followed by a queued question: "How did Wednesday's “FTP Test” go?
Tell me the number it gave you and I'll write it down." The athlete taps "Tell me the number"
and types "236".

Today the command that reads "236" asks the read-back and waits five minutes for a tap.

**After.** That command queues the read-back, sends it, and ends:

> Your FTP from the test on Wednesday, “FTP Test”: 236 W, up from 235 W (+1 W). Shall I write
> it down?
>
> `[✅ Yes]` `[✖️ No]`

It also puts the first question off until the next morning, as "⏰ Ask me tomorrow" would.

- **Yes**, at 13:00: "Written down 💪". On Friday morning the first question finds a result in
  the logbook and closes without a word.
- **No**: "Okay — nothing written down." On Friday the briefing is followed by "How did
  Wednesday's “FTP Test” go?" again.
- **No answer.** On Friday the read-back comes back first. The first question stands behind
  it, and what happens to it depends on the tap.

Nothing links the two questions. The first one already closes when the logbook holds a result,
and the line already orders them by the time each became ready.

A result the athlete writes unasked, "the FTP test gave 236 W", gets the same read-back as a
reply.

The read-back compares with the latest result when it is sent, so "up from 235 W" is true
each time. It closes without a word when the logbook already holds a result for that test. A
typed answer with no number in it is treated as today: "I didn't catch the number…", and the
first question waits.

## 7. Settled elsewhere

DESIGN_long_runs_beside_chat.md, proposed on 2026-10-08, holds two more:

- The question after `workout generate` thinks, "Schedule these 12 workouts…?", becomes a saved
  item with two buttons (§4 there).
- "Shall I pass it to your coach?", asked when a message about a session lands on the goal or
  constraint lane, becomes the button "📨 Send it to your coach as written" (§5 there).

That design keeps one question on the spot: "…Proceed anyway?", asked seconds after the tap on
"📅 Plan my next weeks" when the plan, the periodization, is out of date. It was written the
day before the rule of §1.

## 8. Choices made without the author

1. **The cut-short question no longer comes before the week planner's call** (§3). Today the
   athlete answers "No, it was a warm-up" at 12:15 and the proposal of 12:17 knows Thursday's
   ride was not done. After, that proposal reads 20 of the 90 minutes as done, and the answer
   reaches the next run. The other way keeps the question first and the run waiting, which is
   the problem of §1.
2. **The morning run queues the cut-short question too** (§3). Today it is asked only when the
   athlete happens to write to the coach, days later or never. The other way leaves the
   morning run as it is, and the question still arrives behind a proposal built on the guess.
   **Ruled 2026-10-10: ok.**
3. **"No, something else" offers nothing more.** The next run reads the answer. The other way
   adds the button "Adjust my week around it" under the reply, as "Shall I remember this
   constraint?" does, for the athlete who accepted a proposal built on the guess.
4. **The four read-backs are replies** (§2). The athlete writes "message me at 7" while this
   morning's question about a test is still unanswered. "…OK?" arrives at once. In one strict
   line it would stand behind the test question and not be asked that day. This is the choice
   the author made for the constraint question (DESIGN_waiting_proposal.md §6.3, choice 1).
5. **A setting keeps its question.** The other way changes it at once and says so: "Done — I'll
   open your day at 07:00 from tomorrow." A misread then shows the next morning, when the
   message comes at the wrong hour or not at all.
6. **"Which one did you mean?" becomes a queued question** (§5). The other way leaves it as
   buttons that the next row of buttons retires.
7. **One question waits per thing** (§4). The other way lets both wait. The first then comes
   back the next morning and offers the dates the athlete already corrected.
8. **A typed test number puts the first question off until the next morning** (§6). The other
   way closes it at once. Then a "No" on the read-back leaves nothing that asks again, and the
   test stays without a result.
9. **A goal question never answered comes back each morning until the goal's date.** So does
   an edit question, with no date at all. It is what revision 4 does with every unanswered
   item (§13.2, rule 5). The other way gives these replies a few days to live.
10. **The cut-short question's answers are named**: "Yes, cut short" and "No, something else".
    Today they are "Yes" and "No", with "(No = it was something else, e.g. a warm-up to
    discard)" in the question.
11. **The reply to a setting's "Yes" says the effect again** (§4), because the tap can come a
    day after the question.

## 9. Not handled

- A typed "yes". Today the chat answers that it is busy. After, the command has ended, so the
  word is read as a new message and nothing knows what it answers. The constraint question
  has behaved so since 2026-10-09.
- Two replies can be open at once: the athlete writes "message me at 7", then names a goal
  before tapping. Each tap lands on its own question.
- A proposal made at 12:17 on the app's own pairing is not made again when the cut-short
  question is answered "No".
- "…Proceed anyway?" still waits on the spot (§7).

## 10. Touch points

It is built after revision 4, one question at a time. Each of the six is independent of the
others. What it needs from revision 4: a run sends its own replies; a kind can make an item
ready the next morning; a kind's own check runs before a send and on a tap.

| Where | What |
|---|---|
| `stamind/cli/workouts/adapt.py` | the cut-short question is asked on the spot only in a terminal with someone there; every other run queues it and goes on |
| `stamind/coach/service/matching.py` | unchanged: `pending_match_questions` finds the question and is its check, `record_match_decision` stores the answer |
| `stamind/cli/bot/capture.py`, `edit.py`, `test_result.py` | a chat run queues its question and sends it, in place of the confirm; "No" on an edit and several candidates queue the picker; the buttons with the athlete's words in them go |
| `stamind/cli/benchmarks.py` | `benchmark record` takes the answer already given, as `--yes` does |
| `stamind/athlete_queue.py` | six kinds join the list: the cut-short question, the new goal, the edit, the picker, the setting, the read-back of a test |
| `stamind/cli/render/` | the answers' labels; the cut-short question without its parenthesis |
| `docs/ARCHITECTURE.md` | the bot's capture lanes, the matching section, the list of kinds |

Sections amended when it lands: DESIGN_athlete_queue.md §2 (the list of questions that do not
follow the rule) and §8; DESIGN_bot_simple_frontend.md §12.2, §12.4, §12.5 and §12.7;
DESIGN_benchmark_from_chat.md §3 and §4; ARCHITECTURE.md §15. Designs still in progress are
not edited.

Tests, one per behaviour: a chat run of `workout adapt` with a short activity calls the week
planner and leaves the question waiting; the morning run queues it; each answer stores the
decision, and an answer given in a terminal closes the item; a terminal still asks on the
spot; each read-back writes on "Yes" and nothing on "No", and its text holds the preview; an
edit question shows the constraint as it is when sent, and closes when the constraint is gone;
a second question about the same thing closes the first; the picker's tap sends the edit
question, and "None of these" writes nothing; a typed test number sends the read-back and puts
the first question off, "Yes" closes the first question the next morning, "No" leaves it;
a setting's reply says the effect as it stands at the tap.
