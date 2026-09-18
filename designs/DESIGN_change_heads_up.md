# Design: Telling the athlete when her week changes out of her sight

**Status:** Draft · **Date:** 2026-09-18 (rev. 6)

Revision 5 adds `workout notify`: the operator sends what is waiting at once, for the change
that should not wait for the morning (§4). Revision 6 gives it that name, because `queue
tell` already means something else, and says why it is not a `queue` command (§12).

Revision 2 settled the open question: a change made between 21:00 and her morning time waits
for the morning (§4).

Revision 4 makes the morning the normal time for every change. Only a change that touches
today's sessions goes out the same day (§4).

Revision 3 folded in a review against the code and her real history. What it added:

- The reason of a `workout adapt` run in the terminal is written for her, which needs a small
  prompt change (§3).
- A change that goes out the same day waits until the operator has left her week alone for 15
  minutes, and any waiting change goes out sooner if she opens her chat first (§4).
- When the operator runs the command again before the first attempt was sent, the terminal
  offers to replace that attempt (§5).
- A rollback tells her which change was undone, in the words she was told it with (§3, §6).
- The operator sees what she will get: a notice under the line, and `workout batches` shows
  each change's description and whether it is still waiting to be sent (§8).

## 1. The problem

In companion mode the athlete sees TrainMate only through her Telegram chat. The operator
also changes her sessions from the terminal, and she does not see those runs. Today she
hears about one kind of them late, and about the other kind never.

Here is what works. On Thursday 17 September at 22:51 her time, the operator ran `workout
generate -d today..` in the terminal. The week planner wrote a line for her. Nothing went out
that night. On Friday at 08:00 her morning message opened with it:

> Your coach changed your week: Friday the 25th is your 5 k test on the track — this week
> stays short so it's run fresh; from the 28th your easy runs grow to 40–50 min and finally
> get a real HR ceiling instead of the guessed one you've been fighting.

Here is what does not work. It is Wednesday 23 September, 19:30. Friday holds her first 5 k
test, and Friday is forecast to rain all day. The operator runs `workout adapt -m "rain all
Friday, move the test to Saturday"` in the terminal. The week planner moves the test to
Saturday, the slot kept for it, and makes Friday a rest day.

- Wednesday evening: nothing arrives.
- Thursday 08:00: the morning message shows Thursday, a rest day. It says nothing about
  Friday.
- Friday 08:00: the morning message shows a rest day. She had been getting ready to run the
  test that morning, and nothing says where it went.
- Saturday 08:00: the morning message shows the test.

She could have found out earlier by tapping "🗓 My week", which shows the new days with no
word about why they changed. The cause is simple: only `workout generate` writes a line for
the morning message. `workout adapt` writes none.

There is a second gap. Even the line from `workout generate` waits for the next morning
message. If the operator runs `workout generate -d today..` at 12:30 and it changes tonight's
run, she hears about it at 08:00 the next day, after the run.

This design covers `workout generate` and `workout adapt`. The other commands that change
sessions stay silent for now (§12).

## 2. The rule

> When `workout generate` or `workout adapt` changes the athlete's week and she did not
> watch it happen, TrainMate tells her on Telegram just before her next morning message. A
> change that touches today's sessions does not wait for the morning: it goes out the same
> day, once the operator has left her week alone for 15 minutes. If she opens her chat before
> either, she is told first. The operator can also send what is waiting at once.

She watched a run when it started from her chat: a button she tapped, a message she typed,
or the morning message itself. The run's output is the reply she reads, so she already
knows. A run started in the terminal, or anywhere else, she did not watch.

Her real history has both. Her two adaptations so far came from her chat: "I can’t today I
have a diner" on 2 September and "CAN we postpone this run to tomorrow ?" on 12 September.
She read each result in the reply, so neither would send anything. The `workout generate` of
17 September came from the terminal, so it would.

In expert mode the athlete is the operator, who started every run and watched it. Nothing is
sent.

The one sentence she needs: whenever your coach changes your week without you, you get a
message saying what changed with your next morning message, or the same day if it is about
today.

## 3. What she gets

One message per change, with no buttons:

> Your coach changed your week: Friday is forecast to rain all day, so the 5 k test moves to
> Saturday, the slot kept for it. Friday becomes a rest day.

That line is an illustration; the week planner writes the real one.

- **`workout generate`**: the week line the week planner writes today for the morning
  message (`athlete_note`, DESIGN_plan_change_continuity.md §6.3). The week planner leaves it
  out when nothing she would notice changed, for example when a bare `workout generate` only
  extended the schedule. Then nothing is sent. No prompt change.
- **`workout adapt`**: its reason. The adapt prompt already calls the reason "the line the
  athlete reads most often", and the morning message already prints it after its own
  adaptation. An adaptation that changed nothing sends nothing.

The adapt reason needs one prompt change. Today the prompt hands the `-m` message to the week
planner as "the athlete's note", and the week planner answers whoever wrote the note. Her
real reason of 12 September shows it: "postponing today's long run, as you asked, is the
right call". That was right, because she had asked. In the Wednesday story the operator wrote
the note, so the same prompt would produce "moving the test to Saturday, as you asked", sent
to an athlete who asked nothing.

So when she is not watching the run (§6) and the run has a `-m` message, the prompt presents
the message as a note from her coach that she has not seen, and asks for the reason to be
written to her: what changed and why, never as a reply to the note. Everything else the
prompt does with the note stays as it is, including the constraints and daily signals read
from it. A run without a message, and every run she watches, keeps today's prompt byte for
byte.

**A rollback says what was undone.** When `workout rollback` or `plan rollback` undoes a
change she was told about, she gets that change's line back:

> Your coach undid this change: Friday is forecast to rain all day, so the 5 k test moves to
> Saturday, the slot kept for it. Friday becomes a rest day.

When it undoes several changes she was told about, the message opens "Your coach undid these
changes:" and quotes each line, oldest first. No LLM call is involved: the lines are the ones
stored with the changes (§6). When it undoes a change whose message had not gone out yet,
that message never goes out and the rollback says nothing about it: she never heard of the
change.

This is a change from today's behaviour, in two ways. Today the message is always "The change
to your week was undone." And today it is sent only for a change whose week line the morning
message delivered. From now on it is also sent when the operator undoes a change she made in
her own chat: she tapped "Feeling tired" on Tuesday, the operator rolls that back in the
evening, and she is told, which today she is not.

## 4. When it is sent

The bot's scheduler already wakes at least every five minutes. On each wake it first sends
the reminders that are due (DESIGN_athlete_queue.md §6.5), and then decides whether the
morning message is due. It now does one more thing in between: if changes are waiting to be
told and it is time to send them, it runs a new hidden command, `bot changes`, and waits for
it to finish. `bot changes` sends one message per waiting change, oldest first, and records
each one as told. If a command is already running in her chat, the scheduler tries again on
the next wake, as it does for reminders and the morning message. A change made while the bot
is down is sent when the bot comes back.

**A change waits for her morning time.** Her morning time (the `morning-time` setting, 08:00
for her) is when she learns what a day holds: the morning message's own adaptation already
changes today's session at that moment, and she reads the result then. A change to her week
belongs there too. At her morning time the scheduler sends the waiting changes first, then
the morning message, on the same wake. In the Wednesday story the operator moves the test at
19:30, and she reads about it on Thursday at 08:00, a day before the Friday it concerns. The
real case of 17 September is the same: the `workout generate` ran at 22:51, and its line
reached her just before Friday's 08:00 message, which is when she heard it under today's code
too.

Waiting also keeps the operator's work behind the scenes. The operator often gets to the
right week by trial and error: a run, a look at the result, another run. Nothing reaches her
phone while that goes on, and §5 makes sure the attempt that survives reads correctly.

**A change that touches today does not wait.** The second gap of §1 is the case: at 12:30 the
operator changes tonight's run, and 08:00 tomorrow is too late. A change touches today when
one of the session rows it wrote is dated today in her time zone, a session moved out of
today included. Such a change goes out once the newest waiting change is at least 15 minutes
old, so that a second attempt made a few minutes later still finds the first one unsent (§5).
At 12:30 the operator changes tonight's run, and she is told between 12:45 and 12:50. It goes
out only between her morning time and 21:00. After 21:00 today's session is behind her, and
the change waits for the morning like any other. The 15 minutes and the 21:00 are constants.

Put together, the scheduler sends when it is between her morning time and 21:00, the newest
waiting change is at least 15 minutes old, and at least one waiting change either touches
today or was made before today's morning time. It then sends every waiting change, oldest
first, so that she reads them in the order they were made. A change made in the last 15
minutes before her morning time arrives a few minutes after the morning message.

**The operator can send it now.** TrainMate cannot know that the operator is done trying, or
that a change to tomorrow matters tonight. The operator can. It is Wednesday 18:00 and the
operator moves Thursday's run to the morning, because Thursday evening is taken. Nothing
touches Wednesday, so the message would wait for Thursday 08:00, an hour before the run. The
operator runs `workout notify` in the terminal. It lists the changes that are waiting, each
with the line she will get, and asks before going on. She has the message within five
minutes.

A command in the terminal cannot post to Telegram; only the bot does. So `workout notify`
stores the id of the newest waiting change in a settings marker, `changes_notify_upto`, and the
scheduler counts that as a reason to send on its next wake, whatever the hour and however
young the change: the operator said now. The chat must still be free. It sends every waiting
change, as always. The marker is an id so that it cannot outlive its purpose: if the waiting
changes are rolled back before the wake, no waiting change is that old, and the next change
the operator makes is not sent early by a leftover. With nothing waiting, or on an expert
instance, `workout notify` says so and does nothing.

The automatic rule for today stays. With the command alone, forgetting it after changing
tonight's run would bring back the second gap of §1.

**If she opens her chat, she is told first.** Both waits exist so that a message does not
reach her at a bad moment or in the middle of the operator's work. Neither matters once she
is in the chat, because she is about to see the changed week anyway. It is Wednesday 22:00
and the operator moves the test; the message waits for 08:00. On Thursday at 07:15 she taps
"🗓 My week" over breakfast. Without this rule she sees the test on Saturday with no word
about why, which is the very complaint of §1. So when she taps a button or types a message
and a change is waiting, the bot first runs `bot changes` and waits for it, then does what
she asked. The same holds at 18:02 when the operator changed her week at 18:00: she reads
the 18:00 change first, then the reply to her own tap, in the order things happened.

The message goes out whether or not the morning message is switched on. The `push` setting
turns off the daily briefing; it does not mean "keep changes to my week from me". Reminders
work the same way. With the morning message off, a change held overnight still goes out at
her morning time.

## 5. When the operator tries again

A waiting line was written by the week planner while it looked at the week as it stood then.
That is a problem when the operator runs the command a second time before the first attempt
was sent.

It is Wednesday 22:00. The operator runs `workout adapt -m "rain all Friday, move the test to
Saturday"`. That is change 7, and it waits. At 22:10 the forecast looks better and the
operator runs `workout adapt -m "forecast improved, keep the test on Friday"`. That is change
8. It rewrites Friday and Saturday, so nothing change 7 wrote still stands, and change 7's
message is correctly dropped (§6). But change 8's line was written against the week change 7
left behind. At 08:00 she reads "the forecast improved, so the test stays on Friday after
all", and she never heard that it had moved.

Checking change ids cannot repair that: the ids already cancel the right message, and the
sentence that survives is still written against a week she never saw. What repairs it is
running the second attempt against the week she knows.

So a `workout generate` or `workout adapt` started in the terminal asks one question first,
when the newest change that wrote sessions is one still waiting to be told:

> Change #7 (adapt, Wed 22:00) has not been sent to the athlete yet.
> Replace it, or build on it?

**Replace** rolls change 7 back, exactly as `workout rollback` would, and then runs the
command. The week planner sees the week she knows, so the line it writes is right for her.
The rollback itself says nothing, because she never heard of change 7 (§3). Three attempts in
a row, each replacing the one before, leave one change and one message.

**Build on it** runs the command on top, as today. It is there because two real changes in a
row are legitimate: `workout generate` for next month, then `workout adapt` for Friday's
rain. Both messages go out, oldest first, and read as a story in order.

The question is asked only about the newest change. If she changed something in her chat
after change 7, or the operator edited a session by hand after it, the newest change is not a
waiting one and nothing is asked: a rollback undoes everything after its target, and her own
change must not disappear as a side effect. A run with `-y`, `--auto` or `--force` asks
nothing and builds on top, as today. Once change 7 has been sent, a second run is a real
second change, its line is written against a week she knows, and nothing is asked.

## 6. What TrainMate records

Today the morning message keeps one number, `push_note_last`: the id of the last change it
told her about. That is not enough once a change can be told the moment it is written. Take
two changes two minutes apart. At 18:00 the operator runs `workout adapt` in the terminal,
and its message waits. At 18:02 she taps "Feeling tired", and that change is told as it is
written, in the reply. Moving the one number to the 18:02 change would mark the 18:00 change
as told when it never was.

So each change records it on its own row. `workout_changes` gets a `told_at` column: when the
athlete was told about the change. It is written in two places:

- **When the change is written**, if she is watching the run: the instance is in companion
  mode and the run was started from her chat. On an expert instance it is always written
  here. `workout_change`, the one function every command uses to record a change, asks a
  single helper whether she is watching, so every command stamps `told_at` the same way. The
  adapt prompt (§3) and the terminal question (§5) ask the same helper.
- **By `bot changes`**, once it has printed the message for the bot to post. It cannot know
  whether Telegram accepted the message; the morning message's own marker has the same
  limit today.

A change is waiting to be told when it has a line for her, has no `told_at`, and still
stands. "Still stands" is the test the morning message already uses: something the change
wrote is still the current session of its day (`change_has_live_revisions`). A change that
was rolled back before it was told fails that test. So does a change that a later run
completely overwrote. Neither is sent.

`workout adapt` now stores its reason in `note` as well as in `summary`, so the line for the
athlete lives in one column for both commands. `summary` stays the description `workout
batches` shows (§8). An adaptation that changed nothing stores no `note`, as today.

A rollback writes its message in its own `note` when it is recorded. It looks at the changes
it undoes and keeps those that have a `told_at` and wrote a session dated today or later.
With none, it writes no `note` and says nothing. Otherwise its `note` is "Your coach undid
this change:" followed by the `note` of each, oldest first ("these changes:" for several). If
none of them has a `note`, as with an adaptation made before this design or a session she
moved by hand, the `note` is today's sentence, "The change to your week was undone." A
rollback that is itself undone is not quoted.

`bot changes` sends a rollback's line as it is, and puts "Your coach changed your week:" in
front of a `workout generate` or `workout adapt` line.

How a run knows she is watching: the bot starts every command it runs in her chat with
`TRAINMATE_FRONTEND=json` (`prompt.is_json_frontend()`), and companion mode is `telegram.ui:
simple` in the instance's config (`config.telegram_ui`). The `/ui` switch in the chat lasts
only until the bot restarts, so the config file decides, here and in the bot's two new steps
(§4). This rests on her chat being the only one the bot allows, which is the single-athlete
instance model (DESIGN_bot_simple_frontend.md §4.3). An instance that allowed a second chat
would count a run from it as watched by her.

## 7. The morning message

The morning message stops opening with the week line. `pending_week_note`, the
`push_note_last` marker and the code in `run_bot_morning` that prints and stamps the line all
go. Nothing is lost: a change still waiting when the morning message is due is sent by the
scheduler just before it (§4).

The morning message's own adaptation is a run in her chat. Its change is recorded as told
when it is written, and the briefing prints its reason after today's sessions, as it does
today.

## 8. What the operator sees

Until now the reason of a terminal `workout adapt` never left the terminal. From now on it
reaches her phone, so the terminal says so. On a companion instance, a terminal `workout
generate` prints one line under "Your coach:", and a terminal `workout adapt` prints it under
its reason, both before the question that accepts the change:

> The athlete gets this line on Telegram before her next morning message, or in about 20
> minutes if today's sessions change. `workout notify` sends it now.

`workout batches` lists every change with its date, kind, size and span, and nothing about
what the change was, although a description is already stored with most of them: the week
planner's reasoning for a `workout generate`, its reason for a `workout adapt`, the typed
reason of a `workout rm`, and "Undo of change #6 (generate)." for a rollback. It now prints
that description under each row, cut at about 200 characters. A change still waiting to be
told also says "not sent yet", which is what the question of §5 refers to. No command gains
an LLM call for this: the commands that have none are instant today and stay so.

## 9. Migration

When the column is added, every existing change is marked as told (`told_at` set to its
`created_at`), and the `push_note_last` row is deleted. Without that, the first wake after
the upgrade would send every old line at once. Nothing is lost on her instance:
`push_note_last` is 6, the newest change, so she has already heard every line there is.

## 10. Touch points

- `trainmate/db/base.py`: the `told_at` column on `workout_changes`, with the migration of §9.
- `trainmate/db/workouts.py`: `workout_change` stamps `told_at` when she is watching;
  `rollback_to_change` builds the rollback's `note` from the told changes it undoes (§6); a
  query for the changes waiting to be told, and a write that marks them told;
  `get_workout_changes` also says which changes are waiting. `newest_change_with_note` and
  `newest_change_of_kind` lose their only caller and go, and the test in
  `tests/test_workout_generate_window.py` that reads the first one moves to the new query.
- The helper that says whether she is watching, beside `is_json_frontend` in
  `trainmate/prompt.py`.
- `trainmate/coach/service/adaptation.py`: `workout_revision_apply` stores the reason in
  `note`.
- `trainmate/coach/engine/workouts.py`: the adapt prompt presents the `-m` message as her
  coach's note when she is not watching (§3). It is one more branch on the existing
  `has_message` gate.
- `trainmate/cli/workouts/generate.py`: the replace question at the start of
  `run_workout_generate` and `run_workout_adapt`, before the LLM call (§5); the notice under
  the line (§8); `_change_line` prints the description and "not sent yet"; the new `workout
  notify` (§4), with its parser entry in `trainmate/cli/workouts/parser.py`.
- `trainmate/cli/bot.py`: the hidden `bot changes`; `run_bot_morning` loses the week line.
- `trainmate_bot.py`: `scheduler_wake` runs `bot changes` after the due reminders and before
  the morning message, in companion mode, when the chat is free and either the three
  conditions of §4 hold or a waiting change is no newer than `changes_notify_upto`. One helper
  runs `bot changes`
  ahead of her input, called where `on_message` and `on_callback` accept a tap or a message,
  before anything is routed or started. Both checks are a database read inside the bot, like
  the one for reminders. The 21:00 and the 15 minutes are constants beside them.
- `docs/ARCHITECTURE.md`: the `workout_changes` table (`note`, `told_at`), the scheduler, and
  the internal settings markers.
- DESIGN_plan_change_continuity.md §6.4 is implemented, so it gets a dated amendment pointing
  here: the week line is sent by the scheduler, not by the morning message, and the undone
  message quotes the change.

## 11. Tests

- A `workout adapt` run in the terminal on a companion instance leaves its change waiting.
  The same run from her chat, or on an expert instance, is told as it is written.
- `workout generate` with a week line leaves its change waiting; without one, it does not.
- The adapt prompt names the message as her coach's note only for a run she is not watching,
  and is unchanged byte for byte otherwise.
- `bot changes` sends each waiting change once, oldest first, with the right wording, and
  sends nothing when run again.
- A change rolled back before it was told is never sent, and the rollback sends nothing. A
  change rolled back after it was told makes the rollback quote its line; several are quoted
  oldest first; a told change without a line gives the plain sentence; a told adaptation that
  changed nothing gives no message at all.
- The scheduler sends waiting changes after due reminders and before the morning message on
  the same wake. It does not send while the chat is busy, in expert mode, or while the newest
  waiting change is younger than 15 minutes. It sends whether or not the morning message is
  switched on.
- A change that touches no session of today is not sent that day. It goes out at her next
  morning time, ahead of the morning message, and also when the bot was down at that time and
  comes back later in the day.
- A change that touches today, a session moved out of today included, goes out the same day
  once it is 15 minutes old, together with any older waiting change, oldest first. Made at
  21:00 or later, or before her morning time, it waits for her morning time.
- A tap or a message from her while a change is waiting gets the change first, whatever the
  hour and however young the change, and then its own reply.
- `workout notify` lists the waiting changes and, once confirmed, makes the scheduler send them
  on its next wake, after 21:00 and under 15 minutes old included. With nothing waiting, or
  on an expert instance, it does nothing. A marker left behind by a rollback of every waiting
  change does not send the next change early.
- A terminal run asks the replace question when the newest change that wrote sessions is
  waiting. Replace rolls it back before the week planner is called and leaves one waiting
  change. Nothing is asked when her own change came after it, when the waiting change was
  already sent, with `-y`, or on an expert instance.
- The terminal notice appears on a companion instance and not on an expert one.
- `workout batches` prints each description and marks a waiting change.
- The morning message no longer carries the week line.
- The migration marks existing changes as told and removes `push_note_last`.

## 12. Deliberately not done

- `workout swap`, `workout add`, `workout rm`, `workout restore`, and calling a goal off or
  reinstating it. They change her week too, and stay silent for now.
- A list of the changed days under the line. The line names what moved, and "🗓 My week"
  shows the whole week.
- One message written at send time that sums up everything since she was last told. It would
  need a prompt of its own and an LLM call on each send. Replacing the unsent attempt (§5)
  gets the right sentence without either. What stays uncovered: the operator answers "build
  on it", and the second run then overwrites everything the first one wrote. The first
  message is dropped and the second may refer to it.
- Undoing a rollback. She is told "The change to your week was undone." and not that the
  earlier change is back.
- The athlete queue. It is the place for things TrainMate wants to tell or ask her, but its
  messages carry "Got it" and "Not now" and come back every morning until she taps one. A
  change is read once, like the briefing. The queue also does not record whether a message
  went out, which the undone message needs.
- Telling her the same day, on its own, about a change to tomorrow's sessions. She hears at
  her morning time, which is before she trains and is when she learns what any day holds.
  When the evening before matters, for a bag to pack or a lane to book, the operator runs
  `workout notify` (§4).
- Sending the morning's changes ahead of her morning time, for example an hour before. Her
  morning time is the hour she chose to hear from TrainMate, which is the same reason nothing
  is sent after 21:00.
- `workout notify` as a `queue` command. `tm queue` lists the group's whole state and its
  other commands act on what that list shows (DESIGN_athlete_queue.md §5.1). A waiting change
  is not a queue item, so the list would not show what the command sends. Listing the changes
  there too would give "waiting" two meanings in one list: received and not yet answered for
  an item, not sent yet for a change. The changes are listed by `workout batches`, so the
  command that sends them sits beside it.
- Sending a `queue tell` message at once. The queue has the same gap: a note queued at 21:10
  about tonight goes out the next morning. That belongs to DESIGN_athlete_queue.md.
- Settings for the evening hour and the settle time. Both are constants. An evening setting
  beside `morning-time` would only matter for an athlete who trains after 21:00 and whose
  session the operator changes that same evening.
- Holding reminders overnight too. She chose their time herself (DESIGN_athlete_queue.md
  §10).
- A coach-written description for the commands that make no LLM call. They already store the
  reason the operator typed or a fixed sentence (§8).
