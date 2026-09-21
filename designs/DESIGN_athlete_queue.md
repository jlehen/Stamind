# Design: The queue of things TrainMate wants to tell or ask the athlete

**Status:** Implemented · **Date:** 2026-09-14 (rev. 3)

Revision 3 settles the terminal command: a bare `tm queue` lists, `tm queue answer` goes
through the items, and `tm queue tell` leaves a message, which is also the first thing that
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
the same cause: TrainMate has no place to put a question that can wait.

## 2. The rule: what goes in the queue

> A question is asked on the spot only when someone is watching the command and the command
> cannot go on without the answer. Every other question goes to the queue.

"Apply this proposal?" and "Did you mean this goal or that one?" stop a command that the
athlete just typed or tapped. She is there, and the command cannot continue without her.
Those stay blocking questions, exactly as today.

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
    the tap. Then TrainMate sends it again on its own, as a reminder (§6.5).
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

"Next time" means the next walk. The morning push starts one every day it runs (§6.1), and
`tm queue answer` starts one (§5.1).

**A reminder brings back one item on its own.** Acting on it ends there: it does not
continue into the rest of the queue, which waits for the next walk. For "in 1 day", a
reminder counts as a walk of one that started when it was sent. If a walk reaches the item
after its time has passed but before the reminder went out, for instance because the bot was
down, the walk shows it in its place and no reminder follows. On an instance without a bot
nothing can send a reminder, so the item simply shows up again in the terminal once its time
has passed.

## 5. The terminal

### 5.1 The command

`tm queue` is a command group with three sub-commands. A bare `tm queue` runs `tm queue
list`. That is the exception DESIGN_cli_noargs.md §a3 already makes for `settings`: a group
may act bare when it has one read-only view that shows its whole state, and its other
sub-commands are addressed through that view. `tm queue answer <id>` takes its id from the
list, as `settings set` takes a name from `settings list`.

```
$ tm queue
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

`tm queue list --closed` lists the closed items instead, in the order they closed. Each line
shows when the item closed and, at its end, how: answered, dropped, or stale. `-d` picks the
days they closed on, in the athlete's timezone and in the range grammar every filtering
command shares (DESIGN_cli_selectors.md §1). With no `-d` it shows the last 7 days. `-d`
without `--closed` is refused with a one-line hint, because the waiting list is the whole
queue and has no days to pick. The queue records when an item closed, not when the bot sent
it: a message sent on Tuesday morning and acknowledged that evening shows the evening.

```
$ tm queue list --closed
=== QUEUE · CLOSED 2026-09-10 Thu .. 2026-09-16 Wed ===

  #13  question  2026-09-16 Wed 08:04  Tue Sep 15 18:10 gym session, sets 1–4: …  · answered
  #11  message   2026-09-16 Wed 08:05  Charge your watch tonight — long ride tomorrow.  · answered
  #14  question  2026-09-16 Wed 21:10  Tue Sep 15 18:10 gym session, sets 5–8: …  · dropped

3 closed: 2 answered, 1 dropped.
```

`tm queue answer` walks the waiting items with the blocking chooser, one at a time:

```
$ tm queue answer

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
default, so a walk there skips everything and writes nothing. `tm queue answer 19` shows item
19 alone, whatever its place, and ends after it. An answer can be typed text, like
"something else…": the chooser asks for the text on the spot, and the kind applies it.

`tm queue tell "<text>"` queues a message:

```
$ tm queue tell "Charge your watch tonight — long ride tomorrow."
Queued #19. It goes out with the next morning message, or with 'queue answer'.
```

On an instance run for a companion athlete, this is how the operator leaves her a note, and
it is the only kind in this change: the `message` kind, whose subject is the time it was
queued (so the same words told twice are two messages), whose payload is the text, and
which is never stale. It is also what makes the queue checkable by hand before any feature
adopts it. A message the operator regrets is closed with `tm queue answer <id>` and "got
it".

In Telegram, the expert persona types the same commands. `queue list` and `queue tell`
answer in text. `queue answer` sends the first item as a message with buttons (§6.2) rather
than waiting on a chooser.

### 5.2 When the terminal reads the queue

The terminal shows the queue in four places and never starts a walk on its own.

`tm queue` and `tm queue list` show everything. `tm queue answer` goes through it.

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
the queue arrives as a separate message with its own buttons:

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

A message from `tm queue tell` arrives the same way:

> 📬 Charge your watch tonight — long ride tomorrow.
>
> `[👍 Got it]` `[🕐 Not now]`

### 6.2 Buttons that carry their item

This is the main change to the bot. It needs a new sentinel, meaning a new kind of line the
CLI prints with a special marker so the bot reads it as an instruction instead of as text.

Today's non-blocking buttons, the `TM-BUTTONS` row, are remembered by the bot, one row per
chat, and a new row makes the previous one dead. That is deliberate: "an offer left
overnight is gone by breakfast" (DESIGN_bot_simple_frontend.md §12.3). A question cannot
live like that. If the question's row replaced the briefing's row, the push would lose
"Feeling tired" every morning there is a question.

So a queued item travels on its own line, `\x1eTM-QUEUE {json}`. It carries the item id, the
text, the buttons (a label and an action code each) and the time the walk started. The bot
sends the text as a new message and writes the whole meaning of each button into the button
itself: `q:<item id>:<action>:<walk start>`. For example, `q:12:a2:1789538400` is the second
answer of item 12, in a walk that started at 08:00 on Wednesday. A reminder's buttons carry
the time it was sent, marked as a reminder (`r1789538400`). The action holds a position in
the answers stored with the item, never the answer itself, so it always fits in Telegram's
64-byte limit.

The bot stores nothing about these buttons. They do not replace the briefing's row, the
briefing's row does not replace them, and a bot restart loses nothing.

A tap runs `tm bot queue 12 a2 --since 1789538400`, a hidden command beside `bot morning`. It
checks that item 12 is still waiting and still worth asking, applies the action, and sends
the next item of the walk or the closing line. After a reminder's tap it sends nothing more.
The walk start is also what "in 1 day" is measured from (§4). A tap while another command is
running gets today's "One moment — still finishing the last thing", and the buttons stay
alive.

In a terminal, the helper that would print this line prints the hint of §5.2 instead, so a
raw sentinel never reaches a terminal.

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
two entries. A feature takes what it needs from `trainmate/queue_kind.py` (the `Kind` shape,
`queue` and `NotApplied`), so the list of kinds can import the feature without the feature
importing the list.

Amended 2026-09-14 (DESIGN_learning_doubt_nudge.md §5): `learning`, from
`trainmate/learning_doubts.py`, is the next entry.

## 9. Guardrails

A queue button can only run one of the answers its item was queued with, on that item, after
the item passes its check. The router cannot reach `bot queue`: it is not in the intent
table, and a typed "leg press" is a message to the router like any other. The model never
chooses which item is asked or what its buttons do. A feature may have the model write the
text of an item inside fixed wording, and nothing more.

What an answer writes must be reversible, the same condition DESIGN_bot_simple_frontend.md
§7 sets for anything a tap can change; each feature shows how its answers are undone. A drop
writes nothing except that the question is not asked again, and later and skip write only the
item's place in the queue. `tm queue tell` is a terminal command, not a tap.

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

## 11. Open questions

- **Skip in the companion.** §6.4 leaves skip out of the companion and keeps it for the
  expert. That departs from the actions as first requested. The alternative is one more
  button whose difference from "after the others" she cannot see.
- **"How did the last workout feel?"** The queue can ask it, as a question whose one answer
  is typed text. The simple frontend design decided on 2026-08-25 that effort ratings belong
  to Garmin and are not captured in chat. A free-text question fits that decision; a 1-to-10
  effort question would reverse it.

## 12. Touch points

- `trainmate/db/schema.py`: the `athlete_queue` table. `trainmate/db/queue.py`: queue once per
  subject, the next item of a walk, close, move to the back, hide until a time, the items
  whose reminder time has passed.
- `trainmate/athlete_queue.py`: the list of kinds with the `message` kind, the walk (the next
  waiting item, closing stale ones on the way), the actions with the "in 1 day" time, and
  sending due reminders.
- `trainmate/prompt.py`: `emit_queue_item` with the `TM-QUEUE` sentinel, the hint in its
  place on a terminal, and the labels of the three later choices.
- `trainmate_bot.py`, with the `q:` callback namespace in `trainmate/chat/keyboards.py`:
  the sentinel sends a new message; a `q:` tap runs `bot queue`, keeps its
  buttons on a busy chat and shows the chosen answer; "Not now" swaps in the three choices;
  each scheduler wake runs `bot queue --remind` when a reminder is due and waits for it
  before the push.
- `trainmate/cli/queue.py`: `tm queue` (bare runs `list`), `list`, `answer [id]`, `tell`, and
  the hidden `bot queue` with `--remind`, whose parser entry sits with the other `bot`
  commands in `cli/bot/parser.py`.
- `trainmate/cli/bot/views.py`: `run_bot_morning` starts a walk at its end.
- `trainmate/cli/status.py` and `workout adapt` (`cli/workouts/adapt.py`): the hint, beside
  the end-of-schedule hint.
- `trainmate/cli/render/`: the list, the item, reminder and hint renderers, expert and
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
