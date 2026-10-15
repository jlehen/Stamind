# Design: The last questions the chat asks on the spot

**Status:** Proposed · **Date:** 2026-10-10 · not built

This design stands on revision 4 of the athlete queue (DESIGN_athlete_queue.md §13), which is
built and on main, with the author's rulings of 2026-10-13 on its choices (§13.5 there). The
athlete queue is the stored list of things Stamind wants to ask or tell the athlete. Revision
4 gives it one line and one rule for when an item is sent. So this design does not say when a
question arrives. It says, for each question, what it asks, what its answers do, and when it
closes itself.

It also stands on DESIGN_long_runs_beside_chat.md, built on 2026-10-14. That build gave the
queue two things this design needs. A kind of question can be marked a confirmation: its
questions stand first in the line and close after the `confirmation-days` mornings (§2). And a
tap on an answer can start one of the coach's runs, which take minutes, beside the chat: the
chat stays free while the coach thinks. Three neighbouring questions are settled in that design
and are not designed again here (§7).

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

A sixth question waits on nobody and is still lost: "Which one did you mean?" (§5). So are
two offers, rows of buttons the bot keeps in memory: "🔄 Adjust my week around it" and "📨
Send it to your coach as written" (§4). The next row of buttons, or a restart of the bot,
retires them, and a tap then gets "That offer expired — just send it again."

## 2. The rule

A command started from the chat, or by a run nobody watches, never waits. It saves its
question as a queue item. Then it ends, or it goes on with what it already knows.

Four of the five are **confirmations**: questions that ask the athlete to confirm what the chat
understood from the message they just wrote, before anything is written. Three rules hold for
all of them.

- **A confirmation comes at once**, whatever else is waiting, because the athlete is at the
  screen and has just written about it. It is a reply in the sense of revision 4 (§13.2, rule
  6): the run that queues it sends it, and no wake of the bot is waited for. While it waits
  for its tap it stands at the front of the line, with the cut-short question (§3). So on a
  later morning it is sent before the older questions.
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
morning until 12 November. Two more confirmations were built with DESIGN_long_runs_beside_chat.md
and follow all three rules already: "Shall I pass it to your coach?" and "Shall I plan these
weeks?" (§7).

All of them are drawn bare: no "🙋 Quick question" above, no "Not now" under
(DESIGN_waiting_proposal.md §6.3). What the command prints before its question
today becomes part of the question, in one message, because a question left unanswered is sent
again whole the next morning.

The cut-short question is not a confirmation. The athlete wrote about something else. It is an
ordinary question, with "Not now" under it. But it takes a confirmation's place and life: it
stands at the front of the line, and it closes after the `confirmation-days` mornings (§3,
choice 18).

A terminal keeps asking on the spot, because someone sits there.

**A row of buttons under a view is not a question, and stays a row.** A view is what the
athlete reads on screen. "👍 All good" and "🗑 Remove one" stand under the constraints, "🗑 Call
one off" under the goals, a row under the morning message, "📅 Plan my next weeks" under the
week, and a mesocycle's button under the plan. Each acts on what is on screen and asks nothing,
and showing the view again brings it back. An offer the bot makes after an answer or a message
is a question, and goes through the queue (§4). Ruled 2026-10-15, and made a design rule of the
app (AGENTS.md, Design).

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
- **No answer.** It comes back first on each of the next three mornings, as a confirmation
  does. On the fourth it is closed (choice 18).

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
arrives at 12:17 and rests on that pairing, wherever the question stands.

A run the athlete started sends the question itself, as it sends its confirmations, and after
them. With a proposal, the question follows the tap on it. With none, it follows the coach's
answer at once. It is not left to the bot's next wake, which can be five minutes away. The
author's condition on the queue is that what is put at the front because the athlete has just
done something is asked immediately (DESIGN_athlete_queue.md §13.5, choice 15). The morning
run leaves the question to the line, where it stands first and follows the briefing.

The question closes without a word when it is no longer open: the athlete answered it in a
terminal, the session was removed, or its day is further back than the days `workout adapt`
looks back over. The check is the one that finds the question in the first place.

It also closes on the fourth morning, like a confirmation (choice 18). It is Friday 16
October. The athlete leaves the question unanswered on Friday, Saturday, Sunday and Monday. On
Tuesday morning it is closed without a word. No answer is stored, so Thursday's ride stays
counted as the session, cut short, with its 20 minutes. It is not asked again: the queue keeps
one item per question, even a closed one.

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

## 4. Confirmations: a new goal, an edit, a setting, and two offers

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

**The offer to adjust the week.** The athlete writes "I can't train on the 24th". The chat
asks "Shall I remember this constraint?" and they tap "Yes". Today the reply is "Noted — I'll
work around that 👍", with one button under it, "🔄 Adjust my week around it". A "Yes" on
"Shall I log this signal?" brings the same button after "Logged — thanks for telling me 👍".

After, the button is a question of its own, sent right after the reply, as the next question
of the same tap:

> Shall I adjust your week around this constraint?
>
> `[✅ Yes]` `[✖️ No]`

For a signal it says "this signal". It is asked where the button is offered today: after a
constraint the coach can reach, which starts before the end of the mesocycle under way, and
after a signal, in a chat run that is not the coach's own.

- **Yes** starts `workout adapt` beside the chat, as the button does today, and a proposal
  comes back (DESIGN_long_runs_beside_chat.md §6, a tap that starts a long run).
- **No** answers "Okay — I'll leave your week as it is."
- It also closes without a word once the coach has looked at the week since it was asked:
  the morning run, or any message to the coach. That run read it already.

Its kind is `adjust_week`.

**The offer to pass a message to the coach.** The athlete writes something the chat cannot
store as a constraint or a signal. Today it answers "I'm not sure what to do with that one 🤔
— but I don't want to lose it." with one button under it, "📨 Send it to your coach as
written". The same button follows a preference with no end date, after the chat has said
where a preference belongs.

After, the same first line comes with a question, the one DESIGN_long_runs_beside_chat.md §5
asks when a message about a session lands on the goal or constraint lane:

> I'm not sure what to do with that one 🤔 — but I don't want to lose it. Shall I pass it to
> your coach?
>
> `[✅ Yes]` `[✖️ No]`

"Yes" passes the athlete's words to the coach, beside the chat. "No" answers "Okay — I'll
leave it.". It is the kind `pass_to_coach` of that design, with this first line. After a
preference, the question follows the sentence that says where a preference belongs. That kind
also closes once the day of the session it names is over. A miss names no session, so only the
`confirmation-days` mornings close it.

Both offers are confirmations under the three rules of §2.

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

That command also puts the first question off until the next morning, as a tap on "⏰ Ask me
tomorrow" would. The answer does this itself. Left alone, the queue would ask the first
question again at once, as it does after an answer it could not apply
(DESIGN_athlete_queue.md §13.5, choice 14).

- **Yes**, at 13:00: "Written down 💪". On Friday morning the first question finds a result in
  the logbook and closes without a word.
- **No**: "Okay — nothing written down." On Friday the briefing is followed by "How did
  Wednesday's “FTP Test” go?" again, under "⏰ Back to this one:", as every question put off
  comes back.
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
typed answer the chat cannot use is treated like any answer that could not be applied. The
athlete types "it went fine". The chat answers "What did the test give for FTP, in W? Tell me
again with the number and I'll write it down.", then "Nothing recorded.", and the first
question arrives again at once with its buttons.

## 7. Settled elsewhere

DESIGN_long_runs_beside_chat.md, ruled and built on 2026-10-14, holds three more. In the chat
each is now a saved question:

- The question after `workout generate` thinks, "Schedule these 12 workouts…?", is "Shall I
  schedule these 12 sessions?", with "✅ Schedule them" and "✖️ Leave it" (§4 there).
- "…Regenerate?", asked before `workout generate` thinks when sessions already stand in the
  days it would write, is "Shall I plan these weeks?". Its "Plan them" starts the planning
  beside the chat (§4 and §6 there).
- "Shall I pass it to your coach?" is asked when a message about a session lands on the goal or
  constraint lane. Its "Yes" passes the athlete's words to the coach beside the chat (§5 and §6
  there).

The last two are confirmations under the three rules of §2, and are built so. "…Proceed
anyway?", asked when the plan, the periodization, is out of date, is no longer asked in the
chat: the run stops and says why (§4 there).

## 8. Choices made without the author

The numbers are the ones the author was given them under. All are ruled. Choice 18 came with
the rebase onto the build of the long runs.

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
   test stays without a result. **Ruled 2026-10-11: as designed.** Since 2026-10-13 the queue
   asks a question again at once after an answer it could not apply, so this answer has to
   put its own question off (§6).
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
15. **A run the athlete started sends the cut-short question itself** (§3). It is Friday
    12:15. The athlete writes "I'm tired", and the run finds this morning's short
    ride. The coach answers that nothing needs to change. As designed, the question arrives
    right under that answer. The other way leaves it to the bot's next wake: it arrives up to
    five minutes later, when the athlete may have put the phone down. It follows from the
    author's condition on the queue (DESIGN_athlete_queue.md §13.5, choice 15), which was
    given for the questions about what the athlete wrote. **Ruled 2026-10-14: as designed.**
16. **The offer to adjust the week becomes a question** (§4). **Ruled 2026-10-14**, in the
    author's words: "Everything goes through the queue." The details were mine: the words
    "Shall I adjust your week around this constraint?", the reply "Okay — I'll leave your week
    as it is.", and that it closes once the coach has looked at the week again. The other way
    for the last one is the three days alone: a question about Saturday's constraint could
    then come back on Sunday morning, after the morning run has already worked around it.
    **Ruled 2026-10-15: as designed.**
17. **The offer to pass a message to the coach becomes the question of the hand-off** (§4).
    **Ruled 2026-10-14**, in the same words. That one kind, `pass_to_coach`, serves both
    places, with the first line of each.
18. **The cut-short question closes after the `confirmation-days` mornings** (§2, §3). The
    build of the long runs made the front of the line part of being a confirmation: one mark
    on a kind puts its questions first and closes them after three mornings. As now written,
    the cut-short question takes that mark. It is Friday 16 October. The morning run queues
    the question about Thursday's short ride, and the athlete never taps it. It comes first on
    Friday, Saturday, Sunday and Monday. On Tuesday morning it is closed without a word, and
    Thursday's ride stays counted as the session, cut short. The other way gives the cut-short
    question a mark of its own, which puts it first without closing it. It then comes first
    every morning until its day is more than 15 days back (`coach.metrics_lookback_days`),
    here until Thursday 29 October. While it is out and not tapped, no other question is sent
    that day. So an athlete who leaves it sees no other question for two weeks. As written,
    that lasts three mornings, as for any confirmation, and the queue needs no new mark.
    **Ruled 2026-10-15: as written.**

## 9. Not handled

- A typed "yes". Today the chat answers that it is busy. After, the command has ended, so the
  word is read as a new message and nothing knows what it answers. The constraint question
  has behaved so since 2026-10-09.
- Two replies can be open at once: the athlete writes "message me at 7", then names a goal
  before tapping. Each tap lands on its own question.
- A proposal made at 12:17 on the app's own pairing is not made again when the cut-short
  question is answered "No".

## 10. Touch points

It is built one question at a time. Each of the eight, the six questions and the two offers,
is independent of the others. The queue already gives most of what they need. From revision 4:
a run sends its own replies, and a kind's own check runs before a send and on a tap. From the
build of the long runs: a kind marked a confirmation stands first and closes after the
`confirmation-days` mornings, an answer can start a run of the coach beside the chat, and the
kind `pass_to_coach` exists. One thing is new in the queue: an answer that puts its own
question off until the next morning.

| Where | What |
|---|---|
| `stamind/cli/workouts/adapt.py` | the cut-short question is asked on the spot only in a terminal with someone there; every other run queues it and goes on |
| `stamind/coach/service/matching.py` | unchanged: `pending_match_questions` finds the question and is its check, `record_match_decision` stores the answer |
| `stamind/cli/bot/capture.py`, `edit.py`, `test_result.py` | a chat run queues its question and sends it, in place of the confirm; "No" on an edit and several candidates queue the picker; the buttons with the athlete's words in them go |
| `stamind/cli/benchmarks.py` | `benchmark record` takes the answer already given, as `--yes` does |
| `stamind/athlete_queue.py` | seven kinds join the list: the cut-short question, the new goal, the edit, the picker, the setting, the confirmation of a test, and `adjust_week`; each is marked a confirmation, the cut-short question by choice 18 |
| `stamind/queue_kind.py` | an answer can say its question waits until the next morning; the note on the confirmation mark names the cut-short question too (choice 18) |
| `stamind/cli/candidates.py` | the constraint, signal and session-note kinds are marked confirmations; a "Yes" queues and sends the `adjust_week` question where it emitted the button; that question's check reads the newest pass of the week planner (`newest_adapt`) and the waiting proposal |
| `stamind/cli/queue_commands.py` | `adjust_week` joins `GOES_ON`: its "Yes" runs `workout adapt` with no message, as the button does today |
| `stamind/cli/bot/capture.py`, `extraction.py`, `hand_off.py` | in the chat, a miss and a preference with no end date queue and send the `pass_to_coach` question where they emitted the button, with the miss's first line; such a question names no session, so only its mornings close it |
| `stamind/cli/render/` | the new words of the confirmations (§8, choice 13) |
| `docs/ARCHITECTURE.md` | the bot's capture lanes, the matching section, the list of kinds |

Sections amended when it lands: DESIGN_athlete_queue.md §2 (the list of questions that do not
follow the rule) and §8 (the list of kinds); DESIGN_bot_simple_frontend.md §12.2, §12.3, §12.4,
§12.5 and §12.7; DESIGN_benchmark_from_chat.md §3 and §4; DESIGN_waiting_proposal.md §6.3
(where a confirmation stands, how long it lives, and the offer to adjust the week);
DESIGN_session_notes.md §3; DESIGN_long_runs_beside_chat.md §5 (the hand-off after a miss,
which names no session); ARCHITECTURE.md §15. Designs still in progress are not edited.

Tests, one per behaviour: a chat run of `workout adapt` with a short activity calls the week
planner and leaves the question waiting; the morning run queues it; it is sent before an older
question that waits, and is closed on the fourth morning and not queued again; a chat run sends
it after its proposal's tap, and at once when it has no proposal; each answer stores the
decision, and an answer given in a terminal closes the item; a terminal still asks on the spot;
each confirmation writes on "Yes" and nothing on "No", and its text holds the preview; an edit
question shows the constraint as it is when sent, and closes when the constraint is gone; a
second question about the same part of the same constraint closes the first, and one about
another constraint, or about only some of the parts the first would change, does not; the
picker's tap sends the edit question, and "None of these" writes nothing; a typed test number
sends the confirmation and puts the first question off, "Yes" closes the first question the next
morning, "No" leaves it; a confirmation of this design left unanswered is sent before an older
question and is closed on the fourth morning, the constraint question included; each
confirmation's question names a goal, a constraint, a setting or a test result; a "Yes" on a
constraint the coach can reach, and on a signal, sends "Shall I adjust your week around …?", and
none follows a constraint after the end of the mesocycle under way; its "Yes" starts the coach
beside the chat; it closes once the coach has looked at the week since; a miss sends "Shall I
pass it to your coach?" and no row of buttons, and that question closes only after its mornings.
