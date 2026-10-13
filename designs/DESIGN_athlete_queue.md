# Design: The queue of things Stamind wants to tell or ask the athlete

**Status:** Implemented · **Date:** 2026-09-14 (rev. 3) · rev. 4, 2026-10-10 (§13)

Revision 4 replaces the round the morning message opens with one line that the bot sends from
on its own, in the order items become ready. It is §13. Sections 1 to 12 keep their text, and
each one that the line changes ends with a note dated 2026-10-10 that says what.

Revision 3 settles the terminal command: a bare `sm queue` lists, `sm queue answer` goes
through the items, and `sm queue tell` leaves a message, which is also the first thing that
can put an item in the queue (§5). It says when the terminal reads the queue (§5.2). "In 1
day" comes back two minutes before the time of day the item was shown (§4), and the
scheduler sends reminders before the morning push (§6.5). The check that closes an item is
the feature's own, and the queue knows nothing about it (§3). Designs that are already
implemented get the edits this change needs; designs still in progress are not touched.

Revision 2 built the queue and nothing else, added the three "later" choices, and extended
the rule for what is queued to runs nobody is watching.

## 1. The problem

Two designs in progress each need to ask the athlete something that no command is waiting
on. They illustrate the need; each will adopt the queue in its own design.

DESIGN_strength_tracking.md needs names for the sets the watch could not recognise. As
written today, it asks with the blocking chooser: the numbered list in a terminal, or the
row of buttons in the bot, that a command shows and then waits on until the athlete
answers. DESIGN_learning_doubt_nudge.md needs the athlete to say whether something the coach
learned about her still holds, after a scheduled `data reflect` doubts it. As written today,
it rides the morning push, only on a morning with no other buttons, one question per
morning, with its own settings entry to remember what it already asked.

Here is what that looks like in a real week, for the companion athlete.

It is Tuesday 15 September. She does a machine session in the evening: belt squat, leg
press, cable row, chest press, shoulder press, pulldown. The watch recognises none of them.
That is normal: the strength design measured 47% of sets coming back unnamed, and machine
sets are essentially never named. So Tuesday leaves six blocks of unnamed sets.

On Wednesday at 05:00 the weekly `data reflect` runs on a schedule. It reads two weeks in
which she did not absorb back-to-back hard days, and it files a doubt about the learning
that says she does.

On Wednesday at 08:00 the morning push runs. It pulls Garmin, stores Tuesday's sets, and
briefs her on today's easy run with its three buttons: Got it, Feeling tired, Can't today.
Then it asks the first naming question and waits. While it waits, the chat is busy. She
taps "Feeling tired" and the bot answers "One moment — still finishing the last thing." She
types a message and gets "A command is still running. Use the buttons above, or /cancel."
After five minutes the question times out and the bot says "Prompt timed out — command
cancelled." The other five blocks were never asked.

The learning question does not come on Wednesday at all. Wednesday has a session, so the
push has buttons, and the question only comes on a morning without them. It waits for the
next rest day.

So one question holds up the chat at the one moment of the day she most needs it. The other
waits days for a free slot and keeps its own record of what it asked. Both problems have
the same cause: Stamind has no place to put a question that can wait.

## 2. The rule: what goes in the queue

> A question is asked on the spot only when someone is watching the command and the command
> cannot go on without the answer. Every other question goes to the queue.

"Apply this proposal?" and "Did you mean this goal or that one?" stop a command that the
athlete just typed or tapped. She is there, and the command cannot continue without her.
Those stay blocking questions, exactly as today.

Amended 2026-10-03 (DESIGN_waiting_proposal.md §2): "Apply this proposal?" no longer stops
a `workout adapt` or a `workout tweak` started from the chat. Such a run saves its proposal
as a queue item, sends it and ends, and she answers it with a tap whenever she likes. In a
terminal the question still blocks.

Amended 2026-10-08 (DESIGN_waiting_proposal.md §6.3): "Shall I remember this constraint?" and
"Shall I log this signal?" ask before what was found in her message is stored. A run started
from the chat could always go on without their answer, so it now queues them and ends. In a
terminal they still block.

Amended 2026-10-09: **in the chat, every question goes through the queue.** The rule above
lets a command ask on the spot when it cannot go on without the answer. For a command the
chat starts, that exception is withdrawn. Such a command saves its question and ends, or goes
on with a default and queues the question for the next time. A question asked on the spot
holds the chat and is lost after five minutes; a queued one waits for a tap. When a question
needs another look or another moment than "🙋 Quick question", its kind says so: the proposal
stands alone, and the constraint question is drawn bare (DESIGN_waiting_proposal.md §3,
§6.3). A terminal keeps the rule above, because someone sits there.

These questions do not follow it yet. Each still holds the chat for up to five minutes:

- "Was that the session, cut short?", which `workout adapt -m` asks before it calls the week
  planner.
- "Shall I set that up?", after a message that names a new goal.
- "Shall I make that change?", after a message that changes a goal or a constraint, and the
  question that offers to pass such a message on to the coach.
- The "… OK?" that reads back a change of setting.
- The question that reads back a test result.
- The question `workout generate` asks when its button started it.

A typed answer is not one of them (§6.3): the bot waits for it only after a tap, and an answer
that never comes leaves the item waiting.

"What was that block of sets?" changes what the app knows, but nothing is stuck while the
answer is missing: an unnamed set still counts as volume. That goes to the queue, even when
she is watching.

A run that nobody is watching never asks on the spot, because nobody would answer. The
morning push is such a run, and so is anything cron starts. `data reflect` is the clearest
case: the companion has no way to start it, so any question it has for her comes from a
scheduled run and can only reach her through the queue. When such a run meets a question it
would have needed, it goes on without the answer, the way an unattended `workout adapt`
already skips the "is this activity that session?" question and trusts the matcher. Whether
it also queues the question, so the answer is there next time, is the feature's choice.

The queue holds two shapes. A **question** has answers. A **message** has nothing to
answer; it only needs to be read.

## 3. What a queued item is

One table:

```sql
CREATE TABLE athlete_queue (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    kind       TEXT NOT NULL,   -- the feature that asks: message, and later others
    subject    TEXT NOT NULL,   -- what it asks about, in that feature's own terms
    payload    TEXT NOT NULL,   -- JSON the feature wrote when it queued the item
    queued_at  TEXT NOT NULL,   -- the order of the queue; "after the others" sets it to now
    remind_at  TEXT,            -- set by "in 1 hour" or "in 1 day"; hidden until then
    closed_at  TEXT,            -- NULL while the item waits
    outcome    TEXT,            -- answered | dropped | stale
    UNIQUE (kind, subject)
);
```

Four rules come with it.

**The order is the order things were queued.** The head of the queue is the waiting item
with the oldest `queued_at`. There are no priorities. When a feature queues six items in the
same second, they keep the order of their ids, which is the order it queued them in. An
item is dated by the start of the command that queued it, not by the moment of the write,
so the questions the morning push queues while it runs are waiting when the walk it opens
at its end starts (§4).

**A subject is queued once, ever.** Queuing an item whose kind and subject already exist
does nothing, whether the existing item is still waiting or was closed long ago. That is
how the queue remembers a drop. A feature that wants to ask again for a new reason puts that
reason in the subject. For example, a feature that may ask about the same learning after
each weekly reflect run can put the date that run read up to in the subject: each run is a
new subject, so the question can come back once per run and no more often.

**An item is written complete.** The payload holds everything needed to show the item and
to act on its answer: the facts to show and the list of answers offered. The answers are
fixed when the item is queued and never recomputed. A button tapped tomorrow must mean what
it meant when it was shown. Suppose a feature offered "your recent exercises" as answers and
rebuilt that list at tap time: answering one question with a new exercise could reorder the
list under the next question's buttons, and its second button would name a different
exercise than the one she read.

**An item is checked before it is shown, when it is tapped, and before a reminder is
sent.** The check asks whether the item is still worth asking. The queue does not know what
makes an item stale: it calls the item's kind, and each kind brings its own check. A kind
that asks for set names would call its item stale once Garmin has a name for those sets. A
kind that asks about a learning would call it stale once the operator settled the doubt from
the terminal. The operator's message of §5.1 is never stale. A stale item is closed with
outcome `stale` without being shown, and a tap on one replies "Already settled — thanks!"
and moves on. A check reads the database only; whatever pull ran before it has already
refreshed the data.

Amended 2026-10-03 (DESIGN_waiting_proposal.md §3, §4): a kind may **stand alone**. Its
item is sent the moment it is queued: its text as ordinary messages, then a message of its
own that asks and carries the answers. It is in no walk, in the chat or in a terminal, and
the terminal's hint of §5.2 does not count it. It has no "Not now". `sm queue list` shows it
and `sm queue answer <id>` answers it. A tap on it ends there, the way a tap on a reminder
does, unless the morning message sent it ahead of its walk (DESIGN_waiting_proposal.md §5). A
tap on a closed item of such a kind gets the kind's own line in place of "Already
settled — thanks!".

Amended 2026-10-10 (§13.2): the table has two more columns and one less. `ready_at` is the
time from which the item may be sent. It starts as `queued_at` and is never empty. `sent_at`
is when the item was last put in front of the athlete. `remind_at` is gone, and `queued_at`
is never rewritten. The order is no longer the order things were queued. The line is the
waiting items whose `ready_at` has passed, the earliest first, and items with the same
`ready_at` keep the order of their ids. The check runs before an item is sent and when it is
tapped. No reminder is sent any more, so the third moment is gone.

## 4. The actions

For a **question**:

- **Answer.** The kind applies the answer, the item closes as `answered`, and the next item
  is shown. Amended 2026-09-14 (DESIGN_strength_tracking.md §7): when the kind could not
  apply the answer, because Garmin was out of reach or she chose none of the proposed names,
  the item stays waiting and the kind's line says why, as an empty typed text already did.
- **Drop.** Nothing is applied. The item closes as `dropped` and is never asked again, unless
  its feature later queues a new subject. The next item is shown.
- **Skip.** Nothing is written. The item keeps its place, so it is the first thing shown
  next time. The next item is shown now.
- **Later**, with a choice of when it comes back. The next item is shown now.
  - **In 1 hour.** The item keeps its place in the line but is hidden until an hour after
    the tap. Then Stamind sends it again on its own, as a reminder (§6.5).
  - **In 1 day.** The same, but hidden until tomorrow, two minutes before the time the walk
    that showed it started. A walk starts when the command that began it starts, so the
    morning push's walk starts at 08:00, and anything put off from it comes back at 07:58
    the next day, just ahead of the next push. That holds whichever item of the walk it was
    and whenever she tapped. The time is taken from the walk, not from when the item was
    queued, because the two can be hours apart: a scheduled reflect run queues its question
    at 05:00, and a reminder taken from that time would arrive at 04:58.
  - **After the others.** The item's `queued_at` becomes now, which puts it behind
    everything waiting. No reminder is sent; it comes up in a later walk.

Amended 2026-09-14 (DESIGN_learning_doubt_nudge.md §4): a question kind may have no drop,
when every one of its answers settles it. It then shows no drop button and no drop choice,
and a drop sent anyway writes nothing.

For a **message**:

- **Acknowledge.** The item closes as `answered`. For a message, acknowledging and dropping
  are the same thing, so a message has no drop.
- **Tell me again next time.** The same as skip.
- **Remind me later.** The same three choices as later.

Both shapes run on the same operations. A message is a question whose only answer is "Got
it".

**A walk goes through each item once.** Showing an item, acting on it and showing the next
one is a walk. A walk only covers the items that were waiting when it started. It leaves out
items hidden until a reminder time, items put after the others during the walk, and items
queued while it was going on. Without that rule, "after the others" would loop. Take three
waiting items A, B and C. Putting A after the others moves it behind C, so after C the walk
would show A again. With A alone in the queue, it would come straight back, forever. A walk
ends with "That's all for now — thanks!". A walk that finds nothing to show sends nothing.

"Next time" means the next walk. The morning push starts one every day it runs, or leaves it
to the answer to its proposal (§6.1), and `sm queue answer` starts one (§5.1).

**A reminder brings back one item on its own.** Acting on it ends there: it does not
continue into the rest of the queue, which waits for the next walk. For "in 1 day", a
reminder counts as a walk of one that started when it was sent. If a walk reaches the item
after its time has passed but before the reminder went out, for instance because the bot was
down, the walk shows it in its place and no reminder follows. On an instance without a bot
nothing can send a reminder, so the item simply shows up again in the terminal once its time
has passed.

Amended 2026-10-10 (§13.2, §13.5): there is no walk and no reminder. One item is out at a
time, and the tap on it sends the next. **In 1 hour** makes the item ready one hour after the
tap. **In 1 day** is now **tomorrow**: the item is ready at the athlete's morning time on the
next day. **After the others** makes it ready now, which puts it last in the line. In each
case the item takes its turn in the line once its time has passed. It is not sent on its own
ahead of the others. **Skip** still writes nothing. An answer the kind could not apply leaves
the item in the line, so it is asked again at once (§13.5, choice 14).

## 5. The terminal

### 5.1 The command

`sm queue` is a command group with three sub-commands. A bare `sm queue` runs `sm queue
list`. That is the exception DESIGN_cli_noargs.md §a3 already makes for `settings`: a group
may act bare when it has one read-only view that shows its whole state, and its other
sub-commands are addressed through that view. `sm queue answer <id>` takes its id from the
list, as `settings set` takes a name from `settings list`.

```
$ sm queue
=== QUEUE ===

  #13  question  Wed Sep 16 08:00  Tue Sep 15 18:10 gym session, sets 1–4: 10, 10, 10, 9 reps @ 100 kg
  #14  question  Wed Sep 16 08:00  Tue Sep 15 18:10 gym session, sets 5–8: 10, 10, 8, 8 reps @ 60 kg
  #15  question  Wed Sep 16 08:00  Tue Sep 15 18:10 gym session, sets 9–12: 12, 12, 12, 10 reps @ 30 kg
  #12  question  Wed Sep 16 05:00  Your coach doubts a learning  · hidden until Thu 07:58
  #19  message   Wed Sep 16 21:10  Charge your watch tonight — long ride tomorrow.

4 waiting, 1 hidden. Go through them with 'queue answer', or one with 'queue answer <id>'.
```

The questions in these examples come from features that do not exist yet; they show the
shape. Hidden items are listed after the waiting ones, with the time they come back.

`sm queue list --closed` lists the closed items instead, in the order they closed. Each line
shows when the item closed and, at its end, how: answered, dropped, or stale. `-d` picks the
days they closed on, in the athlete's timezone and in the range grammar every filtering
command shares (DESIGN_cli_selectors.md §1). With no `-d` it shows the last 7 days. `-d`
without `--closed` is refused with a one-line hint, because the waiting list is the whole
queue and has no days to pick. The queue records when an item closed, not when the bot sent
it: a message sent on Tuesday morning and acknowledged that evening shows the evening.

```
$ sm queue list --closed
=== QUEUE · CLOSED 2026-09-10 Thu .. 2026-09-16 Wed ===

  #13  question  2026-09-16 Wed 08:04  Tue Sep 15 18:10 gym session, sets 1–4: …  · answered
  #11  message   2026-09-16 Wed 08:05  Charge your watch tonight — long ride tomorrow.  · answered
  #14  question  2026-09-16 Wed 21:10  Tue Sep 15 18:10 gym session, sets 5–8: …  · dropped

3 closed: 2 answered, 1 dropped.
```

`sm queue answer` walks the waiting items with the blocking chooser, one at a time:

```
$ sm queue answer

Question 1 of 4 · #13 · queued Wed Sep 16 08:00
Tue Sep 15 18:10 gym session, sets 1–4: 10, 10, 10, 9 reps @ 100 kg. What was it?
  [1] belt squat
  [2] leg press
  [3] cable row
  [4] something else…
  [5] leave it unnamed — drop, never asked again
  [6] skip — first in line next time (default)
  [7] later — in 1 hour (22:12)
  [8] later — in 1 day (Thu 21:10)
  [9] later — after the others
Choice: 2
Named sets 1–4: leg press.

Question 2 of 4 · #14 · queued Wed Sep 16 08:00
Tue Sep 15 18:10 gym session, sets 5–8: 10, 10, 8, 8 reps @ 60 kg. What was it?
  ...
Choice: 9
#14 moved behind the others.

...

Message 4 of 4 · #19 · queued Wed Sep 16 21:10
Charge your watch tonight — long ride tomorrow.
  [1] got it
  [2] tell me again next time (default)
  [3] remind me in 1 hour (22:12)
  [4] remind me in 1 day (Thu 21:10)
  [5] remind me after the others
Choice: 1

That's all for now — thanks!
```

The "later" choices show the time they mean. The walk above started at 21:12, so "in 1 day"
is Thursday 21:10.

Enter skips. To leave a walk, press Enter through it or Ctrl-C; every answer already given is
already written. On piped input or under cron, the chooser's end-of-input rule picks the
default, so a walk there skips everything and writes nothing. `sm queue answer 19` shows item
19 alone, whatever its place, and ends after it. An answer can be typed text, like
"something else…": the chooser asks for the text on the spot, and the kind applies it.

`sm queue tell "<text>"` queues a message:

```
$ sm queue tell "Charge your watch tonight — long ride tomorrow."
Queued #19. It goes out with the next morning message, or with 'queue answer'.
```

On an instance run for a companion athlete, this is how the operator leaves her a note, and
it is the only kind in this change: the `message` kind, whose subject is the time it was
queued (so the same words told twice are two messages), whose payload is the text, and
which is never stale. It is also what makes the queue checkable by hand before any feature
adopts it. A message the operator regrets is closed with `sm queue answer <id>` and "got
it".

In Telegram, the expert persona types the same commands. `queue list` and `queue tell`
answer in text. `queue answer` sends the first item as a message with buttons (§6.2) rather
than waiting on a chooser.

Amended 2026-09-28: the expert persona is removed (DESIGN_bot_simple_frontend.md §3). The
same commands still work in the chat when typed with a leading `/`, and `queue answer`
sends the item in the companion's words.

Amended 2026-10-10 (§13.4): `sm queue answer` goes through the line, each item once. Its later
choices read "later — in 1 hour (22:12)", "later — tomorrow (Thu 08:00)" and "later — after
the others". An item shown here counts as sent, so the bot does not send it again the same
day. In the listing, an item is hidden while its ready time is ahead. `sm queue tell` answers
"Queued #19. It goes out when its turn comes: within minutes between 08:00 and 21:00, and at
08:00 otherwise."

### 5.2 When the terminal reads the queue

The terminal shows the queue in four places and never starts a walk on its own.

`sm queue` and `sm queue list` show everything. `sm queue answer` goes through it.

`status` and `workout adapt` print a two-line hint whenever something is waiting, in the
same place and the same yellow as the end-of-schedule hint of DESIGN_runway_nudge.md §4.
Those are the daily touchpoints that design already chose: `workout adapt` is the command
run each morning, and `status` is where every pending thing is listed.

```
3 questions and 1 message are waiting for you.
Go through them with 'queue answer'.
```

Hidden items are not counted until their time has passed. The hint is two lines and not a
walk because `workout adapt` already asks its own questions, and ending it with four more
would turn the morning's command into a form.

Amended 2026-09-14 (DESIGN_learning_doubt_nudge.md §8): `data reflect` and `data bootstrap`
print the same hint at their end, where their demotion prompt used to be.

In the companion, the hint prints nothing: the morning message already brings the questions,
and "Feeling tired" runs `workout adapt`, where a hint about a command she cannot type would
be noise.

## 6. Telegram

### 6.1 The push starts a walk

At the end of `bot morning`, after the briefing and its row of buttons, the first item of
the queue arrives as a separate message with its own buttons. On a morning when the week
planner proposes a change, it arrives once that proposal is answered
(DESIGN_waiting_proposal.md §5):

> 🙋 Quick question (7 left)
> Tuesday's 18:10 gym session, sets 1–4: 10, 10, 10, 9 reps at 100 kg. What was it?
>
> `[Belt squat]` `[Leg press]` `[Cable row]`
> `[Something else…]` `[Leave it unnamed]` `[🕐 Not now]`

"7 left" counts the items in this walk. After a tap, the message keeps its text, shows the
chosen answer under it ("→ Leg press") and loses its buttons. The next item arrives as a new
message, until the walk ends.

Nothing waits. The command that sent the question has already exited. She can tap "Feeling
tired" on the briefing, type a message to the router, or leave the question until the
evening. The question's buttons keep working for as long as the item is waiting.

A message from `sm queue tell` arrives the same way:

> 📬 Charge your watch tonight — long ride tomorrow.
>
> `[👍 Got it]` `[🕐 Not now]`

Amended 2026-10-10 (§13.2): the push no longer starts a walk. It ends with the queue's one
step: if no item is out, the first item of the line goes out. The same step runs after every
tap on a queued item, and on a wake of the scheduler between the morning time and 21:00. So a
message from `sm queue tell` at 14:00 arrives by 14:05 when nothing is out. "7 left" counts the
line. An item left unanswered is sent again from the next morning time on.

### 6.2 Buttons that carry their item

This is the main change to the bot. It needs a new sentinel, meaning a new kind of line the
CLI prints with a special marker so the bot reads it as an instruction instead of as text.

Today's non-blocking buttons, the `SM-BUTTONS` row, are remembered by the bot, one row per
chat, and a new row makes the previous one dead. That is deliberate: "an offer left
overnight is gone by breakfast" (DESIGN_bot_simple_frontend.md §12.3). A question cannot
live like that. If the question's row replaced the briefing's row, the push would lose
"Feeling tired" every morning there is a question.

So a queued item travels on its own line, `\x1eSM-QUEUE {json}`. It carries the item id, the
text, the buttons (a label and an action code each) and the time the walk started. The bot
sends the text as a new message and writes the whole meaning of each button into the button
itself: `q:<item id>:<action>:<walk start>`. For example, `q:12:a2:1789538400` is the second
answer of item 12, in a walk that started at 08:00 on Wednesday. A reminder's buttons carry
the time it was sent, marked as a reminder (`r1789538400`). The action holds a position in
the answers stored with the item, never the answer itself, so it always fits in Telegram's
64-byte limit.

The bot stores nothing about these buttons. They do not replace the briefing's row, the
briefing's row does not replace them, and a bot restart loses nothing.

One item brings the briefing's row with it, drawn under its own buttons: the proposal the
morning message makes (DESIGN_waiting_proposal.md §5).

A tap runs `sm bot queue 12 a2 --since 1789538400`, a hidden command beside `bot morning`. It
checks that item 12 is still waiting and still worth asking, applies the action, and sends
the next item of the walk or the closing line. After a reminder's tap it sends nothing more.
The walk start is also what "in 1 day" is measured from (§4). A tap while another command is
running gets today's "One moment — still finishing the last thing", and the buttons stay
alive.

In a terminal, the helper that would print this line prints the hint of §5.2 instead, so a
raw sentinel never reaches a terminal.

Amended 2026-10-10 (§13.7): a button is `q:<item id>:<action>`, for example `q:12:a2`, and the
`SM-QUEUE` line no longer carries the start of a walk. A button sent before this change has a
fourth part, which the bot reads past. A tap runs `sm bot queue 12 a2`. After it, the step of
§13.2 sends the next item, or the closing line when the line has run out.

### 6.3 Answers typed as text

A text answer such as "Something else…" is a tap that starts a short text question. `bot
queue` asks for the text through the existing text prompt, and her next message is the
answer. She has just tapped it, so she is about to type; the chat is busy only for that one
answer. If she does not answer within the prompt timeout, the item stays waiting, unchanged.

### 6.4 The companion's buttons

The companion shows the item's answers, its drop button under the kind's own name (for
example "Leave it unnamed"), and **🕐 Not now**. A message shows "👍 Got it" and "🕐 Not
now". A question kind without a drop shows its answers and "🕐 Not now" (amended
2026-09-14, DESIGN_learning_doubt_nudge.md §4).

"Not now" replaces the buttons on the same message with three:

> `[⏰ In 1 hour]` `[⏰ In 1 day]` `[↩️ After the others]`

The one sentence that explains them: the first two message you about it again at that time,
and the last one waits for the next round of questions. The bot builds these three from the
tap itself, since the item id and the walk start are in the button, so it still remembers
nothing. Their labels are one shared definition, used by the terminal's chooser and the bot.

The companion has no skip. Companion mode asks that the difference between two buttons fit
in one sentence she can understand. The true sentence for skip versus "after the others" is
"skip keeps it first in line for next time, after the others puts it behind the rest". She
never sees the line. She sees one question at a time, so on almost every morning the two
would do the same thing as far as she can tell. Of the two, "after the others" is the one to
keep: with skip, a question she keeps putting off would open every walk and stand in front of
the questions she would happily answer.

The expert persona in Telegram shows skip as well, like the terminal. Expert mode is exempt
from the one-sentence rule.

Amended 2026-09-28: the expert persona is removed (DESIGN_bot_simple_frontend.md §3), so no
chat message shows skip. The terminal still does.

Amended 2026-10-10 (§13.5): "Not now" swaps in two choices, "⏰ In 1 hour" and "⏰ Ask me
tomorrow". "↩️ After the others" is the terminal's alone: in the chat both others already put
the item behind the rest.

### 6.5 Reminders

The bot's scheduler already wakes at least every five minutes to see whether the morning push
is due. On each wake it now first asks the database whether any item's reminder time has
passed. That read happens inside the bot, the way it already re-reads the push settings on
every wake, so no command runs unless something is due.

When something is due, the scheduler runs the hidden `bot queue --remind` and waits for it to
finish before it considers the push. The wait matters because the bot starts a command
without waiting for it: without the wait, a push due on the same wake would find the chat
busy and retry three minutes later. With it, a reminder due at 07:58 arrives by 08:00, and
the 08:00 briefing follows straight after it. If another command is already running in the
chat, the scheduler tries again on the next wake, as it does for the push.

`bot queue --remind` checks each due item. It closes stale ones without a word, sends each of
the others as its own message, and clears their reminder time, so each reminder is sent
once:

> ⏰ You asked me to come back to this:
> Tuesday's 18:10 gym session, sets 13–16: 12, 12, 12, 12 reps at 45 kg. What was it?
>
> `[Chest press]` `[Shoulder press]` `[Pulldown]`
> `[Something else…]` `[Leave it unnamed]` `[🕐 Not now]`

A reminder is sent whatever the persona and whether or not the morning push is switched on:
the athlete asked for this one herself. A reminder set from the terminal arrives in Telegram
when the instance runs a bot.

Amended 2026-10-10 (§13.2): this section no longer holds. Nothing is sent as a reminder. On a
wake with no morning message to run, the scheduler asks the database whether it is between
the morning time and 21:00, an item is ready and none is out. If so it runs the hidden `bot
queue --next`, which sends the first item of the line. An item the athlete put off comes back
in its turn, under "⏰ Back to this one:", the words since 2026-10-13 (§13.5, choice 18).

## 7. The same week, with the queue

The set-naming and learning questions below are illustrations. What those features queue,
and how they word it, is decided in their own designs.

It is Tuesday 15 September, and the machine session leaves six unnamed blocks, as in §1.

On Wednesday at 05:00, the scheduled reflect run doubts the learning about back-to-back hard
days. Nobody is watching, so it queues the question: "You bounce back fine from two hard
days in a row." Queued at 05:00, it is first in line.

On Wednesday at 08:00, the push pulls Garmin, stores Tuesday's sets and queues six block
questions. It sends the briefing with its three buttons. Then it sends the first question of
a walk of seven, which is the learning one. She is making breakfast, so she taps "Not now",
then "In 1 hour". It is hidden until about 09:00 and drops out of this walk.

Block 1 arrives and she taps "Belt squat". Blocks 2 and 3 get "Leg press" and "Cable row".
Block 4 was her warm-up on the chest press at 20 kg, so she taps "Leave it unnamed". She is
not sure about block 5, so she taps "Not now", then "In 1 day": it is hidden until 07:58 on
Thursday. Block 6 she ignores and puts the phone away.

At 09:00 the scheduler wakes and finds the learning question due. It sends it as a reminder.
She taps "Still fits". Nothing follows it: block 6 waits for the next walk. At 10:00 she
taps "Feeling tired" on the briefing. It still works, and the coach eases today.

On Wednesday evening she opens Garmin Connect and names block 6 "pulldown" there.

On Thursday the scheduler wakes at 08:00. Block 5's reminder time has passed, so it sends the
reminder first, just before the briefing. She taps "Shoulder press". Then the push runs,
pulls Garmin, and the new name for block 6 arrives. Its walk starts with block 6, finds it
stale and closes it without a word. Nothing else is waiting, so the walk sends nothing, and
Thursday's push is the briefing alone.

Amended 2026-10-10: §13.3 tells a Wednesday under the line. In the week above, the learning
question put off until 09:00 no longer arrives at 09:00 on its own, because block 6 is out.
It follows the tap on block 6, or Thursday's briefing.

## 8. How a feature uses the queue

A feature that wants to tell or ask the athlete something provides five things, in its own
code:

- **A kind name**, stored in the `kind` column.
- **The wording**, in an expert version and a companion version, like the other renderers.
- **The check** that says whether an item is still worth asking.
- **What each answer does.**
- **The drop button's name**, or none for a message. Amended 2026-09-14
  (DESIGN_learning_doubt_nudge.md §4): or none for a question whose every answer settles it.

It then queues items. For each one it chooses the subject, which decides whether and when
the same thing can be asked again (§3), and it writes the payload, answers included.

That is all. A feature does not schedule anything, does not remember what it asked, and does
not touch the bot. The queue module holds the list of kinds and nothing about sets, learnings
or any other feature. The `message` kind of §5.1 is the first entry in that list and the
smallest example of one.

Amended 2026-09-14 (DESIGN_strength_tracking.md §7): `sets_final` and `set_names` are the next
two entries. A feature takes what it needs from `stamind/queue_kind.py` (the `Kind` shape,
`queue` and `NotApplied`), so the list of kinds can import the feature without the feature
importing the list.

Amended 2026-09-14 (DESIGN_learning_doubt_nudge.md §5): `learning`, from
`stamind/learning_doubts.py`, is the next entry.

Amended 2026-10-01 (DESIGN_cycle_retrospective.md §4): `retrospective`, from
`stamind/retrospective_question.py`, is one more entry. It asks how a finished mesocycle
went. Its subject is the id of the record it is about. Its one answer asks for typed text,
and its drop is "nothing to say". It goes stale when its record is removed, and seven days
after the end of its record.

Amended 2026-10-03 (DESIGN_waiting_proposal.md §3): `proposal`, from
`stamind/cli/workouts/proposal.py`, is the next entry and the first kind that stands alone
(§3). A kind says two more things when it does: that its items stand alone, and the line a
tap on a closed one gets.

Amended 2026-10-08 (DESIGN_waiting_proposal.md §6.3): `constraint` and `signal`, from
`stamind/cli/candidates.py`, are the next two entries. Their subject is the start of the run
that read the message and the candidate's place in the model's list. The run that queues them
sends them itself, ahead of the morning's walk: at once, or when its proposal is answered. A
kind says one more thing when its items are drawn bare, as these two are: the question and
its answers, with no "🙋 Quick question" line, no "Not now" and no closing line after it.

Amended 2026-10-09 (DESIGN_session_notes.md §3): `session_note`, from the same file, is one
more entry, drawn bare and sent the same way. It asks which of a day's sessions the athlete's
message is about, when the week planner could not tell.

## 9. Guardrails

A queue button can only run one of the answers its item was queued with, on that item, after
the item passes its check. The router cannot reach `bot queue`: it is not in the intent
table, and a typed "leg press" is a message to the router like any other. The model never
chooses which item is asked or what its buttons do. A feature may have the model write the
text of an item inside fixed wording, and nothing more.

What an answer writes must be reversible, the same condition DESIGN_bot_simple_frontend.md
§7 sets for anything a tap can change; each feature shows how its answers are undone. A drop
writes nothing except that the question is not asked again, and later and skip write only the
item's place in the queue. `sm queue tell` is a terminal command, not a tap.

## 10. Deliberately not done

- Priorities or a per-kind order. First in, first out.
- A way for the companion to open the queue on demand. The push brings it every morning.
- Tidying duplicate copies of a question in the chat. A question she ignores is sent again
  by each morning's walk. Every copy's buttons work while the item waits, and once one is
  tapped the others reply "Already settled".
- A walk on a morning when the push stays silent because the schedule has run out. The queue
  waits with it; reminders still arrive.
- Quiet hours. A reminder set at 23:30 for one hour arrives at 00:30.
- A way back from the "Not now" choices to the answers. The existing "Can't today" menu has
  none either; a mis-tap costs choosing "after the others".
- Deleting closed rows.
- The web UI.

Amended 2026-10-10 (§13.2, §13.5): three of these changed. The companion still cannot open the
queue, but the bot sends from it through the day and not only in the morning. A morning when
the push stays silent no longer holds the queue: the next wake sends from the line. Quiet
hours exist: nothing goes out on its own between 21:00 and the morning time, so "In 1 hour"
tapped at 23:30 arrives in the morning. A tap at night still brings the next item at once.

## 11. Open questions

- **Skip in the companion.** §6.4 leaves skip out of the companion and keeps it for the
  expert. That departs from the actions as first requested. The alternative is one more
  button whose difference from "after the others" she cannot see.
- **"How did the last workout feel?"** The queue can ask it, as a question whose one answer
  is typed text. The simple frontend design decided on 2026-08-25 that effort ratings belong
  to Garmin and are not captured in chat. A free-text question fits that decision; a 1-to-10
  effort question would reverse it.

## 12. Touch points

- `stamind/db/schema.py`: the `athlete_queue` table. `stamind/db/queue.py`: queue once per
  subject, the next item of a walk, close, move to the back, hide until a time, the items
  whose reminder time has passed.
- `stamind/athlete_queue.py`: the list of kinds with the `message` kind, the walk (the next
  waiting item, closing stale ones on the way), the actions with the "in 1 day" time, and
  sending due reminders.
- `stamind/prompt.py`: `emit_queue_item` with the `SM-QUEUE` sentinel, the hint in its
  place on a terminal, and the labels of the three later choices.
- `stamind/chat/callbacks.py` and `replies.py`, with the `q:` callback namespace in
  `stamind/chat/keyboards.py`:
  the sentinel sends a new message; a `q:` tap runs `bot queue`, keeps its
  buttons on a busy chat and shows the chosen answer; "Not now" swaps in the three choices;
  each scheduler wake runs `bot queue --remind` when a reminder is due and waits for it
  before the push.
- `stamind/cli/queue.py`: `sm queue` (bare runs `list`), `list`, `answer [id]`, `tell`, and
  the hidden `bot queue` with `--remind`, whose parser entry sits with the other `bot`
  commands in `cli/bot/parser.py`.
- `stamind/cli/bot/views.py`: `run_bot_morning` starts a walk at its end, or sends a
  proposal whose answer starts it.
- `stamind/cli/status.py` and `workout adapt` (`cli/workouts/adapt.py`): the hint, beside
  the end-of-schedule hint.
- `stamind/cli/render/`: the list, the item, reminder and hint renderers, expert and
  companion (the companion's hint prints nothing).
- Tests, with the `message` kind and a question kind defined in the tests: a subject queued
  once, including after a drop; queue order, and "after the others" moving an item to the
  back; a walk that shows each item once and leaves out hidden items and items queued during
  it; a stale item closed without being shown; a tap on a closed item; answers fixed at queue
  time; "in 1 day" measured from the walk start, whenever the tap came; an item hidden until
  its reminder time; a reminder sent once, not sent when stale, and not sent after a walk has
  already shown the item; a reminder's buttons ending without a next item; the scheduler
  sending a due reminder before the push on the same wake; bare `queue` listing; the hint in
  `status` and `workout adapt` and silent in the companion; the terminal hint in place of the
  sentinel; a `q:` tap leaving the live button row alone.
- Implemented designs, amended with the change: DESIGN_bot_simple_frontend.md §4.4 (a fifth
  sentinel), §4.3 (reminders on the scheduler's wake) and §7 (`bot queue` is reachable by a
  tap); DESIGN_cli_noargs.md §a3 (`queue` is the second group whose bare run lists);
  DESIGN_runway_nudge.md §4 (the queue hint shares its touchpoints). ARCHITECTURE.md: the
  queue, the sentinel and the reminder check. Designs still in progress are not edited.

Amended 2026-10-10: §13.7 lists what revision 4 touched.

## 13. Revision 4: one line, in the order items become ready

Designed and built on 2026-10-10. Sections 1 to 12 describe the queue before it. Each one that
the line changes ends with a note that says what (§13.7).

### 13.1 The problem

The queue has no rule of its own for when an item is sent. An item goes out because a command
sends it. The morning message opens a round. A tap sends the next item of that round. `workout
adapt` and `bot capture note` send the questions about what the athlete wrote. The scheduler
sends the reminders. Each of them is right. The gaps are between them.

**A question the athlete's own message queued waited 20 hours.** It is Saturday 3 October
2026, 12:15. The athlete writes "I'm tired today…". The `workout adapt` run this starts does
two things. It finds that a mesocycle has ended and queues "Your last three weeks of training
are done. How did they go for you?". It also saves a proposal. The proposal arrives at 12:17
and the athlete taps "Change it". The question does not follow. It arrives on Sunday at 08:00,
with the morning message. The athlete was in the chat and nothing stood in front of the
question. It waited because that run sends only the questions about the athlete's message
(DESIGN_waiting_proposal.md §6.3), and nothing else sends a question before the next morning.

**With the morning message switched off, no round ever starts.** The `push` setting turns the
daily briefing off. Reminders still go out, and so do the notices about a changed week
(DESIGN_change_heads_up.md §4). The queue's round does not, because the morning message is
what opens it. The same holds on a morning when the message stays silent because the schedule
has run out (§10).

### 13.2 The model

The author's words, 2026-10-10: "The messages should be scheduled. When there's no min/max,
they are delivered asap in order. When the min time of a message expires, it should be
enqueued right behind the messages to deliver asap." The minimum time is what "remind me in 1
hour" sets. The maximum is expiration.

Seven rules follow. Rules 3, 4 and 7 hold his three rulings of that day.

**1. Every waiting item has a ready time.** It is the time from which the item may be sent.
For a new item it is the start of the command that queued it. "In 1 hour" moves it to one hour
after the tap, and "Ask me tomorrow" to the athlete's morning time on the next day.

**2. The line.** The line is every waiting item whose ready time has passed, the earliest
ready time first. Items with the same ready time keep the order of their ids. So an item put
off for an hour does not take its old place back. When its hour is over, it stands behind
everything that became ready before then. A proposal is in no line, as today (§3).

**3. One at a time.** An item is **out** from the moment the bot sends it until the athlete
taps it, and at the latest until the next morning time (rule 5). The bot sends the first item
of the line only when nothing is out. The tap that answers an item, drops it or puts it off
is what lets the next one go.

"In 1 hour" therefore means at least one hour. It is 08:05 and the athlete puts the first
question off for an hour. The second question arrives at once, and they leave it. At 09:05 the
first question is ready again, behind the second. It is sent when the second is answered.
Ruled 2026-10-10: "when the athlete asks to be reminded in one hour, this means at least one
hour but can be more if there are other questions."

**4. When the bot sends.** At three moments, and the step is the same each time: if nothing is
out, send the first item of the line.

- After the morning message, as its last act.
- After a tap on a queued item, at any hour, because the athlete is in the chat.
- On a wake of the bot's scheduler, which comes at least every five minutes, but only between
  the athlete's morning time and 21:00. Those are the hours in which the notices about a
  changed week go out (DESIGN_change_heads_up.md §4).

So a question the nightly `data reflect` queues at 03:00 is ready at 03:00 and arrives after
the 08:00 briefing. A message the operator leaves with `sm queue tell` at 14:00 arrives by
14:05 when nothing is out. Ruled 2026-10-10.

Amended 2026-10-13, on two rulings of that day (§13.5, choices 7 and 9). The evening hour is a
setting, `evening-time`, 21:00 unless set. The notices about a changed week read the same
setting. And past the evening time a wake still sends while the athlete is in the chat, which
means they wrote or tapped in the last ten minutes. It is 23:30. The athlete taps "In 1 hour"
and goes to bed. The question comes back after the 08:00 briefing. Had they still been writing
to the coach at 00:40, it would have come back by 00:45.

**5. An item left unanswered comes back each morning.** At the athlete's morning time nothing
counts as out any more. The step that follows the morning message then sends the first item of
the line again, as each morning's round does today (§10).

**6. A reply comes first.** A reply is what a run sends on its own account: the proposal it
makes, and the questions about what the athlete wrote (DESIGN_waiting_proposal.md §3, §6.3).
Those are the kinds that stand alone or are drawn bare. The run sends them itself, as today,
whatever is out. A reply is out like any other item, so the line waits for its answer. After a
tap on a reply, the next question of the same run goes first. When there is none, the step of
rule 4 runs.

On a morning when the week planner proposes a change, the step after the morning message
finds the proposal out and sends nothing. The line starts when the proposal is answered, as
today (DESIGN_waiting_proposal.md §5).

**7. Expiration is the kind's own check.** It is the check of §3, unchanged. Each kind says
whether its item is still worth asking, and an item that is not is closed without a word. The
check runs before an item is sent and when it is tapped. No time is stored for it. Five of the
ten kinds expire on a fact and not on a date: a question about a set expires when the set gets
a name. The other five work their date out when they are checked, as the retrospective
question does with its seven days. Ruled 2026-10-10.

### 13.3 A Wednesday with the line

It is Wednesday 14 October 2026. The athlete's morning time is 08:00.

At 03:00 the nightly `data reflect` doubts something the coach learned and queues a question
about it. It is ready at 03:00. It is night, so nothing is sent.

At 08:00 the morning message runs. It finds that Monday's test was done and queues "How did
Monday's test go?", ready at 08:00. It sends the briefing. Then it sends the first item of the
line, the learning question: "🙋 Quick question (2 left)".

At 08:05 the athlete taps "Not now", then "In 1 hour". The learning question is now ready at
09:05. Nothing is out, so the test question arrives at once. The athlete is busy and leaves
it.

At 09:05 the learning question is ready again. It stands behind the test question, which is
out. Nothing is sent. Today the reminder would arrive at 09:05 on its own.

At 12:15 the athlete writes "My knee hurts until Friday". The week planner proposes a change.
The proposal arrives at 12:17 although the test question is out, because it is a reply. At
12:20 the athlete taps "Change it". The reply comes, and then "Shall I remember this
constraint?", the question of the same run. They tap "Yes". Nothing else arrives, because the
test question is still out.

At 14:00 the operator runs `sm queue tell "Charge your watch tonight."` in a terminal. The
message is ready at 14:00 and stands last in the line. Had nothing been out, it would have
arrived by 14:05.

At 18:30 the athlete answers the test question. The learning question arrives at once, under
"⏰ Back to this one:". They answer it. The operator's message arrives. They
tap "👍 Got it", and the bot says "That's all for now — thanks!".

Had the athlete left the test question alone all day, Thursday's briefing would be followed by
the test question again, with the other two still behind it.

### 13.4 The terminal and the typed commands

`sm queue answer` goes through the line, each item once. An item that becomes ready while the
command runs is shown too. Its choices are the ones of §5.1, with "in 1 day" reworded: "later
— tomorrow (Thu 08:00)" on a question and "remind me tomorrow (Thu 08:00)" on a message. "Skip"
writes nothing. "After the others" sets the ready time to now, which puts the item last in the
line. Showing an item in a terminal counts as sending it, so the bot does not send it again
the same day.

`sm queue list` calls an item hidden while its ready time is ahead, and shows that time.

`sm queue tell` says when its message goes out: "Queued #19. It goes out when its turn comes:
within minutes between 08:00 and 21:00, and at 08:00 otherwise."

Typed in the chat, `/queue answer` sends the first item of the line whatever is out, and
`/queue answer <id>` sends that item.

### 13.5 Choices made without the author

Each one changes something the athlete or the operator can see, or settles a detail the three
rulings left open. The author ruled on every one: on choice 5 on 2026-10-10, and on the others
on 2026-10-13.

1. **A reply does not wait in the line** (rule 6). At 08:00 a question arrives and the athlete
   leaves it. At 12:15 they write "My knee hurts until Friday". In one strict line, "Shall I
   remember this constraint?" would stand behind the morning's question and not be asked that
   day. As designed it comes at once, as today. This carries over the author's ruling of
   2026-10-09 (DESIGN_waiting_proposal.md §6.3, choice 1). **Kept**, on a condition, in his
   words: "Ok as long as the sets question is asked again if the athlete overlooks it." It
   is. The question left since the morning is sent again the next morning, after the briefing
   (rule 5). It is not sent again the same day.
2. **After a run's replies, the line goes on.** On 3 October the question about the finished
   mesocycle would follow the tap on "Change it". Today nothing follows: "only the questions
   of the run follow the answer to its proposal" (the same choice 1). What still does not
   follow is a question that is out. That was the reason for that choice: a question about
   Tuesday's sets, left since the morning, must not come up again in front of the athlete.
   **Kept.**
3. **A tap on a proposal on a later day is a tap like any other.** Today it brings nothing
   (DESIGN_waiting_proposal.md §5, §6.3). Now it brings that run's questions that are not out,
   or else the step of rule 4. The day a proposal was sent no longer has to be known.
   **Kept.**
4. **A run the athlete starts does not send from the line.** It sends its replies. What else
   it queued goes out on the next wake, within five minutes, or at the morning time when it is
   past 21:00. On 3 October there was a proposal, so the question would follow the tap at once.
   The other way is a fourth moment, at the end of every run the chat starts. Then each such
   command must end with the step, and `bot route`, the run that only works out what a message
   means, must not. **Kept.** Since choice 7 was ruled, the next wake sends past the evening
   time too: the athlete who started the run is in the chat.
5. **"⏰ Ask me tomorrow" replaces "⏰ In 1 day".** The words are the author's, and he ruled
   on the hour too, both on 2026-10-10: the item is ready at the athlete's morning time on the
   next day, so it comes with that morning's questions. It is Wednesday 18:30 and the athlete
   taps "Ask me tomorrow". The question is ready on Thursday at 08:00 and takes its turn after
   the briefing. A tap at 00:30 on Thursday means Friday. Today "In 1 day" is one day after the
   round began, less two minutes (§4). The other way is 24 hours after the tap: Thursday 18:30.
   The button reads the same under a message, where nothing is asked: the bot draws the later
   choices from the tap and does not know what the item is (§6.4).
6. **"↩️ After the others" leaves the chat.** "Not now" swaps in two choices, "⏰ In 1 hour" and
   "⏰ Ask me tomorrow". Both put the item behind the others. A third button would need a
   sentence that tells it apart from those two, and alone in the line it would bring the item
   straight back. The terminal keeps it (§13.4). **Kept.**
7. **A put-off item that comes due at night waits for the morning.** "In 1 hour" tapped at
   23:30 arrives at the morning time. Today it arrives at 00:30 (§10, "Quiet hours"). A tap at
   night still brings the next item at once. **Overruled in part**, in his words: "If the
   athlete is interacting with the UI during the night, it's okay to ask queued questions."
   With nobody in the chat the item still waits for the morning. While the athlete writes or
   taps, a wake sends it (rule 4, as amended).
8. **The `push` setting does not stop the line.** With the morning message off, the first wake
   after the morning time sends the first item. Reminders and notices already ignore that
   setting. **Kept.**
9. **21:00 is the notices' constant**, not a setting of its own. **Overruled: "Setting for
   evening hour."** It is `evening-time`, 21:00 unless set.
10. **The closing line follows the tap that empties the line**, a put-off item's tap included.
    Today nothing follows a reminder's tap. A bare question still gets no closing line.
    **Kept.**
11. **`sm queue tell` goes out the same day.** Today it waits for the next morning message. It
    has no waiting time like the 20 minutes of a changed week, because a message is typed once
    and not reached by trial and error. One the operator regrets before it is sent is closed
    with `sm queue answer <id>`. **Kept.**
12. **Seen in a terminal counts as sent** (§13.4). **Kept.**
13. **Two columns.** `ready_at` replaces `remind_at` and is never empty. `sent_at` is new.
    `queued_at` keeps the time the item was queued and is never rewritten: "after the others"
    used to overwrite it. **Kept.**
14. **An answer that could not be applied puts the item off until the next morning.** Added
    when the design was built: the rulings did not cover it. It is Wednesday 08:10. The
    athlete names a block of sets "butterfly", and Stamind knows no such exercise: "No
    exercise Stamind knows matches “butterfly”. Nothing named." The item still waits, and its
    message has lost its buttons. Before the line, the round went on to the next question and
    this one came back the next morning. That is kept: the item is ready again on Thursday at
    08:00, and the next question arrives at once. The other way is to leave it out. It would
    then hold back every question behind it until Thursday morning, with no button left to
    tap. The cost: it comes back under "⏰ You asked me to come back to this:", which is not
    what happened. **Overruled, for a third way: the question is asked again at once.** Right
    after "Nothing named.", the same question arrives again with all its buttons. The athlete
    types "pec deck", or taps "Leave it unnamed", or "Not now". The next question follows as
    usual. By Thursday they would not remember what the block was. The item keeps its place in
    the line and is no longer out, so nothing about it is stored. The cost is the case where
    Garmin cannot be reached: "Yes, final" brings the same question straight back, until the
    athlete taps "Not now". Two lines changed with it, because they promised a later time
    that no longer holds: "I'll ask again next time." is now "Nothing recorded.", and
    "Couldn't read the sets from Garmin, so nothing changed." no longer ends with "The
    question will come back."
15. **"In the chat" at night means a message or a tap in the last ten minutes.** Made when
    choice 7 was ruled. It is 23:28. The athlete asks the coach about tomorrow's swim, reads
    the answer and puts the phone down. A question is waiting in the line. The bot's next wake
    comes within five minutes, finds the athlete's message recent, and sends the question, at
    23:33 at the latest. So the question can arrive a few minutes after the athlete has left.
    The other way is to send it right under the coach's answer. That is the fourth moment of
    choice 4, and it would hold by day too. Ten minutes is two wakes: a wake that finds the
    chat busy leaves the queue to the next. **Kept, on a condition**, in his words: "I would
    prefer that messages that were enqueued at the front (the athlete has litterally just done
    the action) wouldn't wait 5 minutes to be posted but would be asked immediately." They do
    not wait. Those are the replies of rule 6: the proposal, and the questions about what the
    athlete just wrote. The run that queues them sends them itself, at any hour, and no wake is
    involved. The wake, and its five minutes, are for a question that is not about what the
    athlete just did.
16. **One evening hour, for the queue and for the notices about a changed week.** Made when
    choice 9 was ruled. The operator sets `evening-time` to 20:00. From 20:00 the bot sends
    neither a queued question nor a notice on its own. The other way is one setting for each.
    They were one constant, and the athlete sees one bot. **Kept.**
17. **The athlete cannot change the evening hour from the chat.** Made when choice 9 was
    ruled. The athlete writes "don't message me after 20:00". The bot does not change the
    hour: it is the operator's to set. `morning-time` can be changed from the chat, so the
    other way is to let the athlete change both. A setting can be changed from the chat only
    when someone puts it on that list on purpose (DESIGN_bot_simple_frontend.md §12.7), and
    nobody has for this one. **Overruled: "Let the athlete change it."** The athlete writes
    "don't message me after 8pm". The bot reads it back: "From 20:00 I'll stay quiet until the
    morning, unless you write to me first. OK?" A "Yes" sets it.
18. **The line above a returning question does not say who moved it.** It read "⏰ You asked
    me to come back to this:". The queue stores that an item's ready time was moved, and not
    who moved it. So the line was false for the companion when the operator had put one of
    their questions off in a terminal: they read "You asked me" about a question they had
    never seen. The other ways were to leave it, or to store who moved the time, which costs a
    column. **Ruled: "Neutral line."** It reads "⏰ Back to this one:". The words are mine.

### 13.6 Not handled

- An item nobody taps holds the line. It is sent again each morning, and what stands behind it
  waits, as today. Five of the ten kinds have no time limit: the operator's message, the two
  questions about strength sets, the learning question and the test-result question. Neither
  live queue has held two items of the line at once: 17 items from 19 September to 10 October
  2026, 13 of them replies.
- An item that is out and expires holds the line until a tap or the next morning. The wake's
  check reads the database and runs no kind's check, so that no command starts unless
  something can be sent (§6.5).
- A message Telegram refuses after its retries is recorded as sent. It comes back the next
  morning.
- The replies are still sent by their own commands, `workout adapt` and `bot capture note`.
  Moving those sends into the step is a later change.
- A copy of an unanswered question arrives each morning, as today (§10).
- A typed answer that never comes. The athlete taps "Tell me" and types nothing. The command
  ends after five minutes, the item stays out, and the line waits until the next morning.
  Before the line, the round stopped there too.

### 13.7 Touch points

| Where | What |
|---|---|
| `stamind/db/schema.py`, `scripts/migrate_queue_ready.py` (new) | `athlete_queue` gains `ready_at` and `sent_at` and loses `remind_at`; schema 27. The script sets `ready_at` to `remind_at` where one was set and to `queued_at` elsewhere. It runs once per instance, between the landing and the bots' restart (see below) |
| `stamind/db/queue.py` | the waiting items in the order they become ready, setting a ready time (which ends the item's turn), recording a send. The walk's query, "move to the back" and the due reminders go |
| `stamind/athlete_queue.py` | the line with expired items closed on the way; whether an item is out; the questions a run still has to ask; "tomorrow" as the next day's morning time, with its chat label "Ask me tomorrow"; the check the scheduler makes on a wake. `walk`, `shown` and the reminders go |
| `stamind/cli/queue.py` | one function for the step, called after a tap and by the hidden `bot queue --next`; `send_item` and `send_alone` record the send; after a tap on a reply, the next question of the same run. The walk-start token, `send_walk_step`, `--remind`, `--since` and the test on the day a proposal was sent go |
| `stamind/cli/bot/views.py` | `bot morning` ends with the step; `send_alone` no longer takes a walk's start |
| `stamind/chat/scheduler.py` | a wake tells the changes, then runs the morning message when it is due, and otherwise `bot queue --next` when the check says so. The reminder run goes |
| `stamind/chat/keyboards.py`, `callbacks.py`, `stamind/sentinels.py` | a queue button is `q:<id>:<action>`. A button drawn before the bot restarted has a fourth part, which is read past whatever it holds. "Not now" swaps in two choices |
| `stamind/heads_up.py` | the helper that places a time of day on a date becomes public (`at_time`). The queue reads it and the 21:00 constant where they are, so neither moved |
| `stamind/cli/queue.py` (the texts) | `queue list` reads `ready_at`; the "⏰" lead stands on an item whose ready time was moved; `queue tell` says when its message goes out |
| `docs/ARCHITECTURE.md` | the bot section, the scheduler's wake, the `athlete_queue` table |

It is built in one step. The round and the line read the same rows, so they cannot run side by
side.

The rulings of 2026-10-13 touched five more places. `stamind/settings.py` has the
`evening-time` setting. `stamind/heads_up.py` is handed the evening hour, as it is handed the
morning time, and no longer holds a constant. `stamind/athlete_queue.py` reads the setting, and
its check for a wake takes one more word: whether the athlete is in the chat.
`stamind/chat/scheduler.py` and `stamind/chat/app.py` note the instant of the athlete's last
message or tap and hand it to the wake. `stamind/cli/bot/capture.py` lets a chat message
change `evening-time`, and `stamind/chat/routing.py` tells the fast model that such a message
is a change of setting. For choices 14 and 18, `stamind/athlete_queue.py` marks an item whose
answer failed as no longer out, `stamind/cli/queue.py` holds the neutral line, and the two
kinds' lines are in `stamind/cli/bot/test_result.py` and `stamind/strength/questions.py`.

**The order on the day it lands.** A bot runs each command from the checkout. So between the
landing and the restart, the old bot meets the new code. Three steps go back to back, at an
hour when nobody is in the chat and away from the morning message: land the code, run the
script on each instance, restart both bots. It is 14:00 and the code lands. Until the script
has run, every command that reads the queue fails, "Feeling tired" included. Once it has run,
the old bot's scheduler fails on each wake, so no morning message goes out until the restart.
A question the old bot draws in between has buttons with an empty fourth part. They work once
the bot has restarted.

Sections amended on 2026-10-10, each with a dated note at its end: §3 (the columns, the order),
§4 (the later choices, the round), §5.1 (`queue tell`, the later choices), §6.1, §6.2, §6.4 and
§6.5, §7, §10 (quiet hours, the silent morning) and §12. In DESIGN_waiting_proposal.md: §3 and
§5 (the round after a proposal) and §6.3 (what follows a run's questions, the tap on a later
day). In DESIGN_change_heads_up.md §4: the wake's order. Designs still in progress are not
edited. For them the contract is that
`send_item` and `send_alone` stay the two functions that put an item in the chat, and that
both record the send.

Tests, one per rule: a ready time is the queue time until a later choice moves it, and the
queue time is never rewritten; the line orders by ready time, and an item put off stands
behind what became ready before its time; nothing is sent while an item is out, and a tap
sends the next; the step runs after the morning message and after a tap at night; a wake sends
inside the day's hours and not outside them, with the `push` setting off, and on a morning the
message stays silent; an unanswered item is sent again after the next morning time and not
before; a chat run's proposal and questions go out while an item of the line is out, and the
line waits for them; after the last of them, an item not yet sent follows and one that is out
does not; the Saturday of §13.1; an expired item is closed before it is sent and on a tap;
"Not now" offers two choices in the chat and the terminal keeps three; "Ask me tomorrow" makes
an item ready at the next day's morning time, whatever the hour of the tap; a button with a
fourth part still works; an item shown in a terminal is not sent the same day; the migration.
