# Design: Short messages in the chat, details on a page

**Status:** Designed, not implemented · **Date:** 2026-10-06

This design comes out of an interview with the author on 2026-10-06 (five decisions, §13),
a review by two reviewers, and three rulings of the author on 2026-10-07 (§13).
What the author did not decide is listed apart, in §14, so it can be reviewed.

The words this document uses:

- **The chat** is the Telegram conversation between the athlete and the bot.
- **The week planner** is the model call inside `workout generate`, `workout adapt` and
  `workout tweak` that writes the sessions. **The strength planner** is the model call that
  writes a gym session's exercises and kilograms.
- **A proposal** is what the two planners would change, saved until the athlete answers it
  with "✅ Change it" or "💪 Keep it as planned" (DESIGN_waiting_proposal.md).
- **The briefing** is the part of the morning message that shows today's sessions.
- **A row** is the line of buttons the bot draws under one of its messages.
- **A page** is a web page opened inside Telegram, like the Calendar. **The bucket** is the
  folder of encrypted files the pages read (DESIGN_miniapp_storage.md).

## 1. The problem

It is Sunday 4 October, 22:46. The athlete writes to the coach about the day's gravel ride:
it was harder than a road ride, and it felt good. At 22:48 the answer arrives. It has more
than 1,200 words. Telegram cuts it into two messages. It holds a summary of five sentences,
then seven sessions, each with a reason and with its old and its new text quoted in full.
The question "Shall I make these changes?" comes last, under all of it. The athlete taps
"Keep it as planned", mostly because the answer is too long to check.

This is not one bad evening. From 30 September to 6 October the bot sent this athlete 45
texts and about 8,000 words. The journal keeps every text the bot sends, so they can be
counted.

| What the text was | How many | Middle length | Share of all words |
|---|---|---|---|
| A proposal, above "Shall I make these changes?" | 6 | about 800 words | 54% |
| Today's sessions, in the briefing or under "📅 Today" | 10 | about 275 words | 33% |
| Everything else | 29 | 11 to 63 words | 13% |

Two kinds of text carry 87% of the words. About seven words in ten of a proposal are the
quoted old and new text of the sessions. Four texts were long enough to be cut in two.

The second athlete has the `terse` setting on, which drops the quotes
(DESIGN_output_verbosity.md §9). Her proposals stop at 355 words. Her session texts are
still about 310 words each, because `terse` does not touch them.

The texts are right. They are too long for what they are read for: a yes or a no, and what
to do today.

## 2. The rule

> In the chat, a text a planner wrote is a summary of at most two sentences, and one short
> line per session. Everything longer is one tap away, on a page.

Three things follow, and the rest of this document is their detail:

1. A proposal shows its summary, one line per changed session, and its buttons (§3).
2. A session shows its title, its length and one short line (§4).
3. "🔎 Tell me more" under either of them opens a page with the full text (§5, §6).

Nothing a planner decides changes. No stored text gets shorter. The session's full
description is still written, still stored, still on Google Calendar, and one tap away.

## 3. A proposal in the chat

Back to Sunday 4 October, 22:48, with this design. The bot first says, as today: "Kept with
today's “Long Low-Intensity Gravel Ride (up to 3 h)”." Then the athlete reads one message:

```
Good that it felt strong. The ride had about 50 minutes at tempo or harder, so I'd give
the easy rides left outdoors a flat route and a power limit.

🏋️ Fri 09 · split squats 40 → 36 kg
🚴 Sat 10 · flat route, stop at 178 W
🚴 Sun 11 · sprints on flat ground only
🏋️ Mon 12 · split squats 40 → 36 kg
🏋️ Fri 16 · swings 26 kg, dumbbell clean
🚴 Sat 17 · flat route, stop at 178 W
🚴 Sun 18 · outdoor limits added

Shall I make these changes?

[ ✅ Change it ]  [ 💪 Keep it as planned ]
[ 🔎 Tell me more ]
```

That is about 95 words. The words inside are an example: the planners write them.

**The summary** is the week planner's `reason`. It is at most two short sentences, about 30
words. It says what drove the change, starting with the athlete's note when there is one,
then what changes overall. It does not go through the sessions one by one, because the list
under it does.

**The list** has one line per session the proposal changes, in date order. A line is the
sport's emoji, the day, and the **change line**: at most eight words that say what changes,
with its number when it has one. "flat route, stop at 178 W". "moved to Sunday". The
planner that changed the session writes it (§7). The day is "Today" for today, and
otherwise the weekday and the day of the month, as the week view writes it.

Every changed session has a line, whatever the summary says. This is what the list is for:
the athlete never approves a change that the message did not name.

- A session the proposal removes gets the line "removed", written by the code.
- A session whose planner gave no change line shows its title and its length in its place.
- Two gym days changed the same way are two lines. Nothing is grouped.

**The lines that are there today stay.** "Kept with today's …" still answers a note
(DESIGN_session_notes.md). The run prints it before the proposal is saved, so it is a
message of its own, above the proposal. "This replaces my earlier proposal." still opens a
proposal that replaces another. The strength planner's notice that it could not recheck a
gym day's kilograms still closes the text (DESIGN_strength_tracking.md §9).

**One message.** Today the text is one message, or two when it is long, and the question is
another. Here the short text and the question are one message, and the buttons sit under
it. When the athlete answers, the message keeps its text and gains "→ ✅ Change it", as a
queued question does today. The chat then shows what was accepted, not only that something
was.

**The gym sessions stay in the list.** On 4 October three of the seven changes came from
the strength planner. They are three lines, and they are accepted or declined with the
rides, as DESIGN_waiting_proposal.md §7 says.

**What the proposal keeps for later.** The saved proposal keeps three things beside what a
tap writes: the short text above, the long text of today, and the content of its page (§6).
The long text is what the terminal shows, what the week planner is shown when the proposal
is still open at its next run, and what the chat sends when there is no page (§5).

## 4. A session in the chat

It is Saturday 10 October, 08:00. The morning message arrives:

```
🚴 Today: Long Low-Intensity Gravel Ride — Flat Route — 135 min
Ride easy at 155–175 W on a flat route. Ease off as soon as you pass 178 W.

[ 👍 Got it ]  [ 😴 Feeling tired ]  [ 🕐 Can't today ]
[ 🔎 Tell me more ]
```

On a gym day it reads:

```
🏋️ Today: Full-Body Strength (Heavy, Non-Failure) — 65 min
Six exercises, heavy, two reps short of failure. Split squats are at 36 kg.
```

**The short line** is new. It is at most two short sentences, about 20 words: what to do in
this session, and the one or two numbers to hold. It is stored with the session, in a new
column, `summary`. The plan already works this way: `plan generate` writes a short summary
beside each mesocycle's long text (DESIGN_output_verbosity.md §5.1).

**Who writes it.** The week planner writes it for every session it writes. The strength
planner writes it for a gym day, because only it knows the exercises and the kilograms. A
session a run keeps as it is keeps its short line.

**Where it shows.** In the two texts the bot sends unasked: the briefing, and the day's
sessions after "Change it" on a proposal that changed today. Under the title come the done
line when the session is trained, the short line, and what the athlete said about the
session ("You said: …"), as today.

"📅 Today" is a day the athlete asks for. With a bucket it prints the short line too, with
"Tell me more" under it. Without a bucket it prints the full description, as today: there is
no page to put the long text on, and asking for the day is itself the way to it (§5).

**Where the full description still shows.** On the page (§6), on the Calendar page's day
sheet for today and the days ahead, on Google Calendar, and in `workout show` of one day.
The week view is unchanged: it never showed a description.

**The Calendar's past is short** (§13, D6). It is Thursday 15 October. The athlete opens the
Calendar and taps Saturday the 10th. Under "Planned" the sheet shows the gravel ride's
title, its length and its short line. Under "Done" it shows what she rode. What she told
the coach about the session ("You said: …") stays under "Planned", on a past day as on any
other. The long description is no longer on that sheet. Today and every day ahead keep the full
description. A past session with no short line shows its title and its length only (§14,
A22).

**One function, two readers.** `simple_day_lines` draws a day for the chat, and it also
fills the Calendar's files. So it keeps printing the full description unless its caller
asks for the short form. The chat's callers ask, and so does the Calendar for a day that is
over.

**A session with no short line** shows its full description in the chat, as today, and gets
no button. That is every session written before this design lands, until a planner next
writes it. There is no backfill (§13, D4).

**`workout show` of one day prints the long text** (§13, D7). `workout show` prints each
session's detail, and today that always includes the full description. The new rule:

- When every session shown falls on one day, it prints the full description, as today.
- When the sessions span several days, it prints the short line in its place. `workout
  show` with no argument details seven days, so it is short.
- With `-H`, which adds each session's earlier forms, it prints the short line even for one
  day. The earlier forms print as today; their text is the one the Google Calendar event's
  history carries.
- `--long` (`-l`) and `--short` (`-s`) ask for one or the other, whatever the rule says.
- A session with no short line prints its full description in every case.

In the chat, `workout show -d <day>` prints the day in full the same way; a wider span is
the week view, as today. So the Calendar page's "💬 Full day in chat" button, which exists
for the moment the page could not load the full text, runs `workout show -d <day>`.
`workout list -vv` is the same listing as `workout show`, so it follows the same rule.
`workout list` and `workout list -v` are unchanged (§14, A24).

`-l` is `--link` today, on both `workout list` and `workout show`. `--long` takes the
letter, and `--link` keeps its long name only (§14, A23).

## 5. "🔎 Tell me more"

One rule: **"Tell me more" opens the full text of the message it sits under.**

Under a day's sessions it opens that day. Under a proposal it opens that proposal. It is
under a message only when that message left something out: a day whose sessions all show
their full description has no such button.

The button comes in two forms. The function that makes it picks one. It asks the test the
keyboard already uses: the config names a bucket, and this database was published
(DESIGN_miniapp_storage.md §8).

**With a bucket: a page button.** The button opens the page of §6. It carries the page's
address and nothing else, so the bot remembers nothing about it. Three things follow:

- It does not count as the chat's live row. Tapping "📅 Today" at 09:00 does not retire
  "😴 Feeling tired" under the 08:00 briefing.
- It stays under its message for good. Tapping "👍 Got it" removes the other buttons of
  the row and leaves this one. Under a proposal it stays after the answer too.
- A tap on it is not a message to the bot. Nothing runs, and the journal sees nothing.

**Without a bucket: the text in the chat.** The button is an ordinary button of the row,
like "Tell me more" under the plan view, which sends `bot mesocycle <id>`. Under the
briefing it sends `workout show -d <day>`, which prints the full description (§4).
Under a proposal it sends `bot proposal <id>`, a new hidden command that prints the
proposal's long text and changes nothing. This is the long message of today, asked for
instead of sent.

**The files go up before the button does.** Stamind uploads the pages' files when a command
ends (DESIGN_miniapp_storage.md §6). The bot sends a row the moment the command prints it,
which is earlier. So the one function that makes a "Tell me more" button runs the upload
step first, with the proposal's file first in it. The step runs again when the command
ends, as today. Without this the button would always arrive before the file. A proposal
sent before a question such as "Shall I remember …?" would have no file until that question
was answered, which can take five minutes.

**The address never reaches the journal**, because it holds the page key
(DESIGN_miniapp_storage.md §8). The bot journals a row's labels only, as today.

**On a morning with a proposal**, the briefing has its "Tell me more" too (§13, D8). Today
such a briefing has no row, because the proposal's message carries every button
(DESIGN_waiting_proposal.md §5). A page button asks nothing and is not the chat's live row,
so it can sit under the briefing without bringing a second question. The athlete can then
read today's session in full, as planned, before she answers the proposal under it. The
proposal's own "Tell me more" shows what would change.

Without a bucket the briefing gets no button on such a morning. A chat button there would
be replaced by the proposal's row half a second later, and a tap on it would answer "That
offer expired".

## 6. The page

One new page, `details`, with two forms. It is read-only: it has no button that sends
anything to the bot. The Calendar page's code is not changed; what its files say of a day
that is over is (§4).

**Why a page of its own.** A page opened from a button under a message cannot send to the
bot. Telegram allows that only to a page opened from the keyboard. The Calendar and the gym
logger both send: "💬 Full day in chat", and a gym log. Opened from under a message, a gym
log would look sent and be lost. So "Tell me more" never opens them.

### 6.1 A day

It is Saturday, 08:01. The athlete taps "Tell me more" under the briefing. The page
downloads October's file, the one the Calendar reads, and draws Saturday's sheet: the same
headings and the same lines the Calendar shows when she taps Saturday there. The gravel
ride's whole description is under "Planned".

No new file is built for this. The month files already hold the day's full text
(DESIGN_miniapp_storage.md §4).

One line is missing. On the day of a goal, the Calendar opens the sheet with the goal,
which it reads from another file. This page does not show it.

A button stays under its message for good (§5), so one day it sits under a day that is
over. The page then shows that day as the Calendar does: short (§4).

### 6.2 A proposal

It is Sunday 4 October, 22:49. The athlete taps "Tell me more" under the proposal. The page
shows the summary, then one card per changed session, in date order. A card holds:

- the session's line and what it replaces, as the long text writes them today:
  "🚴 Sat Oct 10: Long Low-Intensity Gravel Ride — Flat Route — 135 min (was Long
  Low-Intensity Gravel Ride)";
- the planner's one-sentence reason for this session (`change_reason`);
- for a session whose title and load did not change, the passages that changed, as "Was"
  and "Now" pairs (DESIGN_workout_revisions.md §9.1);
- the whole new description, folded, and opened by a tap. For a session that is new or has
  a new title, it is shown open, because no "Was" and "Now" pair exists for it.

The last point closes a gap of today. On 4 October the summary named a "breach rule". The
rule was defined in Saturday's new description. Saturday had a new title, so the long
message quoted nothing of it, and the athlete could not read the rule anywhere.

**One file.** The proposal's page reads one file, with the label `proposal`. It holds the
newest proposal saved, whatever its answer, with the proposal's number. One proposal is
open at a time (DESIGN_waiting_proposal.md §3), so one file is enough, and nothing ever has
to be deleted from the bucket. The file is built from what the saved proposal keeps (§3),
so `sm data publish` can build it again. A proposal saved before this lands keeps no page
content, and no file is built from it.

**An older button.** The button's address carries its proposal's number. The athlete
scrolls up and taps "Tell me more" under Thursday's proposal, and a newer one was made
since. The file holds the newer number. The page says "This proposal was replaced by a
newer one. The newest is further down in the chat." and shows nothing else.

### 6.3 When the page cannot show it

- **The file does not arrive within 10 seconds**, or cannot be opened: "These details could
  not be loaded. Close this page and tap again in a moment." This follows the Calendar's
  rule for a file that cannot be used (DESIGN_miniapp_storage.md §7.1).
- **The file holds an older proposal than the button's**, because the upload failed: the
  same message.
- **The day has nothing in its month's file**: "Nothing is planned on this day."

The page never offers to send the text in the chat, because it cannot send (§6, above).

### 6.4 Who can read it

Nothing new. The proposal's file is encrypted with the page key, like the month files, and
its name cannot be guessed. A page button's address carries the page key, as the
keyboard's buttons do. Whoever holds the athlete's Telegram holds both
(DESIGN_miniapp_storage.md §5, §16). Every text on the page is drawn as plain text, never
as HTML, because a planner wrote it (DESIGN_miniapp_storage.md §7).

One thing grows. The page key now sits under every message that has a "Tell me more", for
as long as the bot token lives, and not only in the newest keyboard. What a leaked address
gives away, and how to end it, is in DESIGN_miniapp_storage.md §16.

## 7. What the planners are asked

All of this is in `## RESPONSE FORMAT`. No section is added to a prompt.

**The week planner**, in `workout generate`, `workout adapt` and `workout tweak`:

| Field | On | Asked for |
|---|---|---|
| `summary` (new) | every session it writes, except a gym day and a rest day | At most 2 short sentences, about 20 words, for the athlete: what to do, and the one or two numbers to hold. Plain words. No name coined in the description. |
| `change` (new) | every session it changes, in `workout adapt` and `workout tweak` | At most 8 words: what changes, with its number when it has one. No reason. |
| `change_reason` | as today | Unchanged: one sentence of at most 20 words. It is read again by later runs. |
| `reason` | the whole answer of `workout adapt` and `workout tweak` | At most 2 short sentences, about 30 words. What drove the change, the athlete's note first, then what changes overall. Not the sessions one by one. |

**The strength planner:**

| Field | On | Asked for |
|---|---|---|
| `summary` (new) | every session it writes or changes | The same limit: what kind of session it is, and what the athlete should know before starting. |
| `change` (new) | a session it was asked to check and is changing | The same limit as the week planner's. Required there, as `reason` already is. |

`## WRITING FOR THE ATHLETE` says today that it governs the rationale and the summary prose
only, and that a session's `description` is the prescription. That sentence stays true. The
two new fields are summary prose, so the section's four rules cover them.

**Stored or not.** `summary` is stored with the session. `change` is read once, in the
proposal's message, so it is kept with the saved proposal and not written to the session.
`change_reason` is stored as today.

**A gym session keeps its short line when the strength planner keeps its kilograms.** That
holds also when the week planner changed the session's brief in the same run. It is Monday.
`workout adapt` rewrites Friday's brief for a light week, and the strength planner answers
that Friday's sets stand. The code then copies the sets under the new brief, which makes a
new form of the session. It copies the short line with them. Without this, Friday's briefing
would show the long gym text again.

**A short line alone is not a change.** A session whose only difference is its short line
is not written again. So a planner that rewords a short line it was not asked to touch
changes nothing.

**Nothing checks the limits.** The prompt states them, and says that a limit is a hard
limit. On 4 October the week planner wrote 74 words against a limit of 60. §11 says how the
real lengths are watched after this lands.

## 8. The `terse` setting goes

`terse` does two things today: it halves the summary's room, and it stops the quotes of old
and new text (DESIGN_output_verbosity.md §9). After this design the first is the rule for
everyone, and the second is the rule in the chat. What would be left is a switch that
changes the length of one sentence. So the setting is removed:

- `reason` is at most two short sentences for everyone (§7).
- `workout generate`'s `reasoning` is at most two sentences for everyone. It was four, and
  two with `terse` on.
- The chat never quotes old and new text. The page does, for everyone.
- A terminal always quotes them. With `terse` on, it did not.
- "your messages are too long" no longer switches anything. The router stops offering the
  setting.

The stored value is left in each database. Nothing reads it.

## 9. What does not change

- **What the planners decide**, and every text they store. A description is as long as
  today.
- **A terminal**, except `workout show` (§4). `workout adapt` typed in a terminal shows the
  preview it shows today, `workout list` and `workout list -v` list as today, and
  `sm queue answer <id>` shows a proposal's long text.
- **What the week planner is shown** of a proposal that is still open: the long text
  (DESIGN_waiting_proposal.md §6.2).
- **When a proposal waits and when it is written**, and the rule for gym sessions
  (DESIGN_waiting_proposal.md §2, §7).
- **The week view, "✅ Done lately", the plan and the mesocycle review.**
- **The "Goals & plan" page**, and the Calendar page for today and the days ahead.
- **The line told ahead of a tap** when a change was written elsewhere
  (DESIGN_change_heads_up.md), and the sentence of a morning on which only kilograms moved.
  Both are short already.

## 10. Not handled

- **A session written before this lands** shows its full description until a planner next
  writes it. On the day this lands, every session of the running mesocycle is one of them.
  `workout generate` writes them again, except the sessions of the next `commitment-days`
  (7 by default) that it keeps as promised (DESIGN_plan_change_continuity.md §4). Those
  show their full text until they pass or a run changes them.
- **Without a bucket, "Tell me more" is an ordinary button of its row.** Tapping it removes
  the row's other buttons, "😴 Feeling tired" among them. Under a proposal the athlete asked
  for, it is also the chat's one live row, so the morning's buttons expire the moment the
  proposal arrives. A bot restart forgets it. With a bucket none of this happens (§5).
- **A failed upload.** The page then shows the file of the command before, and the short
  line in the chat is newer than the page, until the next command uploads
  (DESIGN_miniapp_storage.md §16).
- **A proposal's message over Telegram's 4,096 characters** is refused by Telegram, so the
  proposal is saved and never shown. It takes more than 50 changed sessions.
- **The plan view's own "Tell me more"** still answers in the chat. It is reached only by
  typing "my plan"; the keyboard opens the "Goals & plan" page.

## 11. How we know it worked

The journal keeps every text the bot sends. One week after this lands, the same count as §1
is run again. The targets:

| Text | Before | Target |
|---|---|---|
| A proposal's message | about 800 words in the middle, 1,200 at most | under 150 words |
| One session in the briefing | about 275 words | under 45 words |
| Messages cut in two | 4 in a week | none |

A summary over 40 words, or a short line over 30, is read by hand: the limit in the prompt
did not hold, and the prompt is where it is fixed.

## 12. Where things live

| Where | What |
|---|---|
| `stamind/db/schema.py`, `stamind/db/workout_change.py`, `stamind/db/workouts.py`, a one-off script | `workouts.summary`, added to the live databases the way `scripts/migrate_calendar_columns.py` added `short_name` |
| `stamind/coach/engine/generate.py`, `adapt.py` | the fields of §7 in `## RESPONSE FORMAT` |
| `stamind/coach/revisions.py` | `structure_revision` keeps `summary` and the change line. It drops, without a word, any field it does not name |
| `stamind/strength/planner_prompt.py`, `planner.py` | `summary` and `change` in the strength planner's answer; `_keep` copies the live session's short line, which nothing else carries over (§7) |
| `stamind/cli/render/session_lines.py` | the short form of `simple_day_lines` (§4); the short list of a proposal |
| `stamind/cli/render/companion.py` | a requested day (§4); the proposal's short text |
| `stamind/cli/workouts/proposal.py` | what the saved proposal keeps (§3); the item's message |
| `stamind/cli/queue.py` | `send_alone` prints the long text in a terminal only; the row under today's sessions after "Change it" |
| `stamind/cli/bot/views.py`, `parser.py` | the briefing's row, also on a morning with a proposal (§5); `bot proposal <id>` |
| `stamind/cli/workouts/parser.py`, `listing.py` | `workout show`: the rule of §4, `--long`/`-l` and `--short`/`-s`; `--link` loses `-l` |
| `stamind/cli/render/calendar_page.py` | a day that is over is drawn short (§4) |
| `stamind/sentinels.py`, `stamind/chat/keyboards.py`, `replies.py`, `callbacks.py`, `telegram_api.py` | the page button (§5) |
| `stamind/chat/messages.py` | "💬 Full day in chat" runs `workout show -d <day>` |
| `stamind/page_files/sync.py` | the `proposal` file, first in the upload step; the one function that makes a "Tell me more" button (§5), beside `button_params` |
| `stamind/cli/render/__init__.py`, `companion.py`, `stamind/runtime.py` | `make_renderer` moves (build step 2) |
| `stamind/cli/render/` | a small module that builds the proposal file's content |
| `miniapp/details.html`, `details.js` | the page of §6, over `storage.js` and `calendar_logic.js` |
| `stamind/settings.py`, `stamind/cli/bot/capture.py`, `stamind/chat/routing.py`, `stamind/coach/service/adapt.py`, `stamind/coach/service/generate.py`, `stamind/coach/engine/`, `stamind/cli/workouts/revisions.py` | `terse` and `quotes_wording` go, with every reader of the setting |
| `docs/ARCHITECTURE.md` | the bot section, the pages, the schema, and the `workout list` / `workout show` rows of the command reference (`-l` moves, `-s` arrives) |

Implemented designs amended when each step lands: DESIGN_output_verbosity.md §5 (the
limits), §9 (`terse` is removed); DESIGN_bot_simple_frontend.md §4.1, §4.4 and §6 (the
briefing, the page button, the preview); DESIGN_waiting_proposal.md §3 (how a proposal is
sent); DESIGN_workout_revisions.md §9.1 (the "Was" and "Now" pairs are on the page);
DESIGN_miniapp_storage.md §4, §6 and §7 (the `proposal` file, the upload before a button,
the third page); DESIGN_calendar_miniapp.md §5 and §6 (the sheet of a day that is over,
what "Full day in chat" runs); DESIGN_waiting_proposal.md §5 (the briefing's page button on
a morning with a proposal); DESIGN_settings.md (one setting fewer).

**Tests**, one per rule:

- Every changed session has a line in the short list, also when the summary names none, and
  when a planner gave no change line.
- The briefing prints the short line when the session has one and the full description when
  it has none; a day with no short line gets no button.
- A requested day prints the short line when the database was published, and the full
  description otherwise.
- `workout show` prints the full description for one day, and the short line for several
  days and with `-H`; `--long` and `--short` override both; a session with no short line
  prints its description.
- The Calendar's file for a month holds the full description for today and the days ahead,
  and none for a day that is over.
- On a morning with a proposal, the briefing has a page button when the database was
  published, and no button otherwise.
- A gym session whose brief changed and whose kilograms stand keeps its short line.
- The row holds a page button when the database was published, and a chat button otherwise.
- A page button is not the chat's live row, survives a tap on another button of its row,
  and its address is in no journal line.
- Making a "Tell me more" button runs the upload step first, with the `proposal` file first
  in it.
- The `proposal` file holds the newest proposal, and is built again from the database.
- On the page: a proposal number that differs from the file's shows the "replaced" line; a
  file that does not arrive shows the "could not be loaded" line; a day draws the sheet
  `calendar_logic.js` returns.
- The tests of DESIGN_waiting_proposal.md still pass: a tap writes what was saved.

## 13. What was decided

The author answered each of these in the interview of 2026-10-06. They are also the first
rows of the Decisions Log at the end.

| ID | Question | Answer |
|---|---|---|
| D1 | Which messages get the short form? | Proposals, and each session's own text. Not the plan, not the mesocycle review. |
| D2 | What does the athlete see before answering a proposal? | The summary, then one short line per changed session. One new short field from each planner. |
| D3 | Where do the details open? | On a page, like the Calendar. |
| D4 | What stands under a session's title? | A short line the planner writes, stored with the session. A session written before shows its full text until it is next written. |
| D5 | What happens to the gym changes in a reply to a note? | The same list and the same yes or no. |

The author ruled on these on 2026-10-07, after reading the review.

| ID | Topic | Ruling |
|---|---|---|
| D6 | The Calendar's past | The Calendar stops showing the long text of a past session. It shows the short text. |
| D7 | `workout show` | It shows the long text by default only when it displays one day, and the short text otherwise. `--short`/`-s` and `--long`/`-l` override. With `-H` it defaults to the short text even for one day. |
| D8 | "Tell me more" on a morning with a proposal | The athlete must be able to read the full text before accepting. This overrules A10. |

## 14. Decided without asking the author

The interview had seven minutes. These choices were made after it, by Claude, to make the
design whole. None was put to the author. Each is open to objection, and each names what
it was chosen over.

The last column is what the two reviewers said, and what the author ruled since. A reviewer
may object to a choice. It may not remove one: the author rules on each. Where a review
found a hole in a choice, the hole was closed and the choice kept, and the column says so.
A choice the author overruled keeps its row, with the ruling beside it.

| ID | Choice | Why | What it was chosen over | What the reviewers and the author said |
|---|---|---|---|---|
| A1 | The `terse` setting is removed (§8). Its two-sentence limit becomes the rule for everyone, and `workout generate`'s `reasoning` drops to two sentences too. | After this design the setting would only change one sentence's length. A switch with so little behind it is one more thing to explain. | Keeping `terse` as a switch between two and three sentences. Keeping four sentences for `workout generate`. | Thorough: buildable. The setting has three more readers than first listed; §12 names them all now. Pragmatic: right-sized, deletion only. It should land straight after the short proposal; the build order now says so. |
| A2 | The "Was" and "Now" quotes leave the chat for everyone and go to the page. A terminal always shows them. | They are seven words in ten of a proposal, and D3 puts the details on a page. | Keeping the quotes in the chat for an athlete who asks for them. | Thorough: buildable. The page must show the pairs whatever `terse` says, until the setting is gone (build step 2). Pragmatic: right-sized. |
| A3 | The page is read-only. "Change it" and "Keep it as planned" are tapped in the chat. | A page opened from under a message cannot send to the bot (§6). | A page with its own yes and no, which needs another way back to the bot. | Pragmatic: right-sized. |
| A4 | One new page, `details`, shows both a day and a proposal. The Calendar page is not changed. | The Calendar and the gym logger send to the bot, and a page opened from under a message cannot. A gym log edited there would be lost. | Opening the Calendar itself on the day. | Pragmatic: right-sized. The page must exist for proposals anyway, and the day form is about 65 more lines. The other way is two taps every morning. |
| A5 | A session's "Tell me more" shows the day's whole sheet, as the Calendar does: what is planned, what was done, signals and constraints. | The month file holds it already, so nothing new is built or uploaded. | A page that shows the planned session only. | Thorough: one line differs. On a goal's day the Calendar opens the sheet with the goal, read from another file. This page does not show it (§6.1). Pragmatic: right-sized. **Author, 2026-10-07 (D6):** a day that is over shows the short line, on the Calendar and on this page alike. |
| A6 | One `proposal` file, replaced by each new proposal. An older proposal's button gets "replaced by a newer one". | One proposal is open at a time. One file never needs a deletion. | One file per proposal, kept or cleaned up. | Pragmatic: needed. What a tap writes does not hold the old sessions that the "Was" side needs, so the proposal has to keep its page's content. |
| A7 | The proposal's page shows, per session, the reason, the changed passages, and the whole new description folded. | The passages point at what changed. The whole text was missing on 4 October for a session with a new title. | Old and new description side by side in full. The passages only. | Pragmatic: right-sized. |
| A8 | With no bucket, "Tell me more" sends the long text in the chat (§5). | The short form must not depend on a Google bucket. This is also the long text of today, so nothing new is written. | No short form at all without a bucket. No details at all without a bucket. | Thorough objected. As first written, "📅 Today" without a bucket carried its own chat button, which retired "😴 Feeling tired" under the morning briefing. Answered by A20. **Pragmatic objects and would drop this form.** Both of the author's instances are published, so it serves no athlete today. Its shape: where the pages are not published, the chat stays exactly as it is today, long texts and no "Tell me more". That removes the hidden command `bot proposal`, three chat buttons and two tests, and leaves one difference to explain in place of three. The price: an operator with no bucket gets no short messages. Its second choice, if the short form must work without a bucket: no button under a day, and `bot proposal` under a proposal only. **Thorough, second pass, would drop it too,** and found a second hole: under a proposal the athlete asked for, the chat button is the chat's one live row, so the morning's buttons expire when the proposal arrives, with no tap (§10). Pragmatic, second pass: that hole makes its second choice weaker than it first rated it. **Not applied: the author rules.** What each ruling changes in the build is under this table. **Pragmatic, after D8:** the ruling adds weight to the objection. With A8 kept, an instance with no bucket has no button under the briefing on a morning with a proposal, so D8 is met there only through "📅 Today". With the form dropped, the briefing there is the long text of today, and D8 is met with no code. |
| A9 | The short text and "Shall I make these changes?" are one message, and it keeps its text after the answer. | The buttons sit under what they answer, and the chat keeps what was accepted. | Two messages, as today. | Thorough: the message is sent whole, so Telegram refuses one over 4,096 characters. That takes more than 50 changed sessions; listed in §10. Pragmatic: no more code than two messages. "Kept with today's …" is printed earlier in the run, so it stays a message of its own; §3 now says so. |
| A10 | On a morning with a proposal, the briefing has no "Tell me more" (§5). | The author decided on 2026-10-05 that such a morning has one keyboard. | A lone "Tell me more" under the briefing. | Pragmatic: right-sized. **Overruled by the author, 2026-10-07 (D8):** the briefing has its "Tell me more" on such a morning too, as a page button, which asks nothing and is not the chat's live row (§5). |
| A11 | A gym day's short line is written by the strength planner only. | One writer per field. Only the strength planner knows the exercises and kilograms. | The week planner writing a first short line from the brief, replaced later. | Thorough objected. A gym day whose brief the week planner changed, and whose kilograms the strength planner kept, was written again with no short line. Fixed: the short line is copied with the sets (§7). The choice itself stands. Pragmatic: the fix is needed, and it is one line. |
| A12 | A page button stays under its message for good, after "Got it" and after a proposal's answer (§5). | The bot remembers nothing about it, so nothing makes it stale. The athlete can read the details at the trailhead. | Removing it with the other buttons of its row. | Thorough: buildable. Every function that reads or writes a row expects a button that calls the bot back, so each has to learn the page button. Pragmatic: about 15 lines in all. |
| A13 | The files go up before the button does (§5). | A proposal sent before a waiting question would otherwise have no file for minutes. | Uploading at the end of the command only, as today. A separate upload when a proposal is saved. | Thorough: confirmed, and needed on every path. The bot sends a row the moment it is printed, and the upload runs when the command ends. Pragmatic: keep it, in one place. The one function that makes the button runs the step; §5 now says so. |
| A14 | `workout list -d <day> -v` prints the full description in the chat, and "💬 Full day in chat" sends it (§4). | The button exists for the moment the page has no full text. `plan show -v` already means this. | A new command for the full day. | Thorough objected. In a terminal `-v` on this command already means "add the exercises or zone times", and `-vv` the full detail. Kept, with both meanings stated in §4. Pragmatic: three lines; without it "Full day in chat" would answer with the short line. **Replaced after the author's ruling of 2026-10-07 (D7):** see A24. |
| A15 | The change line is not written to the session. It lives in the saved proposal only (§7). | It is read once. DESIGN_output_verbosity.md §5.1 stores only prose that is read again. | A column for it. | Thorough: buildable. The change line must be named where the planner's answer becomes a session, or it is dropped before the proposal is saved (§12). Pragmatic: right-sized. |
| A16 | Nothing checks or cuts a text that passes its limit (§7, §11). | Cutting a sentence can cut its meaning, and a second model call costs time and money. The lengths are counted after a week instead. | Cutting after the second sentence. A retry. A rewrite by the fast model. | Pragmatic: right-sized. |
| A17 | The list never groups two sessions changed the same way (§3). | One line per session is the rule the athlete can rely on. | "Fri 09, Mon 12 · split squats 40 → 36 kg" on one line. | Pragmatic: right-sized. |
| A18 | The terminal changes in one place only: `terse` no longer hides the quotes there (§8, §9). | AGENTS.md exempts the terminal from the companion's rules. | A short form in the terminal too. | Pragmatic: right-sized. **Changed by the author, 2026-10-07 (D7):** `workout show` in a terminal follows the new rule of §4. |
| A19 | No red-team pass and no visual preview were run before this document was written. The author asked for a review by two reviewers instead, on 2026-10-06. | The interview's time was up. | Asking two more questions after the seven minutes. | — |
| A20 | Added in the review. Without a bucket, "📅 Today" prints the full description, as today, with no button. Only the texts the bot sends unasked are short there (§4). | A chat button under "📅 Today" would become the chat's one live row and retire the morning's buttons. Asking for the day is already a request for its text. | The short line with a chat button under it. A "not handled" line. | Thorough, second pass: accepted; it closes the "📅 Today" hole. Pragmatic: better than a "not handled" line, and less code. But it fixes half: without a bucket, a tap on the briefing's own "Tell me more" still removes "😴 Feeling tired" (§10). It would fold this choice into its objection to A8. **Not applied: the author rules.** |
| A21 | Added in the review. A session whose only difference is its short line is not written again (§7). | `short_name` already works this way. A reworded short line would otherwise make a new form of the session, and a Google Calendar update with it. | Counting the short line among the fields that make a session changed. | Pragmatic: costs no code. The list of fields that make a session count as changed simply does not gain the new column. |
| A22 | Added with D6. On the Calendar, a past session with no short line shows its title and its length only, never its long text (§4). | The author asked that the Calendar stop showing the long text of past sessions. Every session written before this lands has no short line, and a past session is never written again. | Falling back to the long text, which keeps the whole past long for good. | Thorough: no objection from the code; what the athlete told the coach about a session stays on a past day (§4). Pragmatic: right-sized, and the same code as the fallback. With the fallback nothing would change on the day it lands, because no past session has a short line and none is written again. The price: for a session written before step 1, the long text is then only in `workout show -d <day>` and on Google Calendar. |
| A23 | Added with D7. `--long` takes the letter `-l`, and `--link` keeps its long name only (§4). | The author asked for `--long`/`-l`. Today `-l` is `--link`, on `workout list` and on `workout show`. | `--long` with another letter, or with none. | Thorough: no objection; one parser line and one row of docs/ARCHITECTURE.md, no test and no bot table. Pragmatic: right-sized. `-l` for `--long` is the author's own letter. |
| A24 | Added with D7. "💬 Full day in chat", and "Tell me more" without a bucket, run `workout show -d <day>`. `-v` gets no new meaning (§4, §5). This replaces A14. | The author's rule for `workout show` already gives the long text of one day, in the chat as in a terminal. | A14: `-v` meaning "the full text" in the chat and something else in a terminal. | Thorough: no objection; nothing stands between the Calendar's button and `workout show`. Pragmatic: right-sized, and no more code than A14. `workout list -vv` follows the rule too, because `workout show` is that listing (§4). |

**What each ruling on A8 changes in the build.** Both reviewers would drop the form for an
instance with no bucket. The author has three ways to rule:

- **A8 kept, as this document is written.** Step 2 builds `bot proposal <id>` and the chat
  button under a proposal. Step 6 builds the chat button under the briefing and after
  "Change it", and keeps "📅 Today" long without a bucket (A20). The two flaws of §10's
  second line stay, and the briefing gets no button on a morning with a proposal (§5). No
  athlete of today meets any of this: both instances are published.
- **The form dropped.** Where the pages are not published, the chat is exactly as it is
  today: long texts and no "Tell me more". Gone from this document: `bot proposal <id>`, the
  chat buttons, A20, §10's second line, and the "Without a bucket" paragraph of §5. D1, D2
  and D4 then hold only on a published instance.
- **In between.** No chat button under a day, and `bot proposal <id>` under a proposal
  only. A proposal the athlete asks for at 08:30 still expires the buttons under the 08:00
  briefing.

## 15. Not verified

- **That a button under a message can open a page in the bot's chat**, with the page's
  address intact after the `#`. Telegram documents such buttons for a private chat with a
  bot. It was not tried on a phone. Neither was how long an address such a button accepts;
  ours is about 150 characters after the page's own. Both are step 0 of the build order,
  the way DESIGN_calendar_miniapp.md §8 measured the keyboard's limit first.
- **That the planners hold the new limits**, and that their short lines say what matters.
  One replay of the 4 October exchange with a plainer prompt still wrote 70 words against
  60.
- **How long the upload step takes when it runs before a row.** It adds its time to every
  command that sends "Tell me more". With nothing to upload it reads four months from the
  database, about 52 ms (DESIGN_miniapp_storage.md §6).

## Decisions Log

| ID | Topic | Decision | Rationale | Source | Date |
|---|---|---|---|---|---|
| D1 | Scope | Proposals and each session's own text get the short form. The plan and the mesocycle review do not. | These two kinds carry 87% of the words the bot sends in a week. The others are read once a month. | Interview | 2026-10-06 |
| D2 | First view of a proposal | The summary, then one short line per changed session, then the buttons. Each planner writes one new short field. | Every change is named, so none is approved unseen. About 95 words where 4 October had more than 1,200. | Interview | 2026-10-06 |
| D3 | Where the details open | On a page, like the Calendar. | The chat stays short for good. The author chose it over a second chat message and over a folded quote. | Interview | 2026-10-06 |
| D4 | A session's short line | A short line the planner writes, stored with the session. No backfill. | `plan generate` already writes a summary beside each mesocycle's long text. | Interview | 2026-10-06 |
| D5 | Gym changes in a reply to a note | They stay in the same list and under the same yes or no. | They are three short lines now. DESIGN_waiting_proposal.md §7 is unchanged. | Interview | 2026-10-06 |
| D6 | The Calendar's past | The day sheet of a day that is over shows a session's short line, not its long description. | The author's ruling. On a past day, what was done is what the sheet is read for. | Interview | 2026-10-07 |
| D7 | `workout show` | The long text by default for one day, the short line for several days and with `-H`. `--long`/`-l` and `--short`/`-s` override. | The author's ruling. It also gives the chat its way to a day's long text, so `-v` gets no second meaning. | Interview | 2026-10-07 |
| D8 | "Tell me more" on a morning with a proposal | The briefing has its "Tell me more" on such a morning too. | The author's ruling, which overrules A10: the athlete must be able to read the full text before accepting. | Interview | 2026-10-07 |

## Dependency Graph & Implementation Order

```
0 the check on a phone ──► 2 short proposal, with its page ──► 3 terse removed
                                        │
1 short line stored ──┬─────────────────┴──► 6 short day, with its page form
                      ├──► 4 workout show ──────────────────────┘
                      └──► 5 the Calendar's short past
```

Each step from 1 on works on its own, and each can be landed alone.

0. **The check on a phone** (§15): a button under a message opens a page, and the page
   reads its address after the `#`. D3 hangs on it. If it fails, the design needs another
   answer before anything is built. Step 2 also waits for the author's ruling on A8 and A20
   (§14): it decides whether the chat form and `bot proposal <id>` are built at all.
1. **The short line is written and stored** (§4, §7): the column, and `summary` in both
   planners' answers. The chat does not change yet. It lands early on purpose: there is no
   backfill, so every session written from then on has its short line when the later steps
   land.
2. **The short proposal, with its page** (§3, §5, §6.2, §7): `change`; the two-sentence
   `reason`; the short text and the question as one message; "Tell me more" in both forms;
   `details` with its proposal form; the `proposal` file; the upload before a button.
   First, `make_renderer` moves out of `cli/render/__init__.py` into `companion.py`. Today
   `page_files/sync.py` imports `cli/render`, whose `__init__.py` loads both renderers, and
   `expert.py` loads `cli/queue.py` and `cli/workouts/listing.py`. So of the files that
   print these rows, only `cli/bot/views.py` can import `page_files.sync` until that move;
   `cli/render/companion.py` and `cli/queue.py` sit inside that circle, and so does
   `cli/workouts/proposal.py`. Proposals come first because they are 54% of the words. The
   page shows the "Was" and "Now" pairs whatever `terse` says.
3. **`terse` is removed** (§8), straight after step 2. From then on the setting would
   switch nothing the athlete can see.
4. **`workout show`** (§4, D7): the rule, `--long`/`-l` and `--short`/`-s`; `--link` loses
   `-l`; "Full day in chat" runs `workout show -d <day>`. Needs step 1 only. Nothing changes
   in the chat yet: there `workout show` of a day and "📅 Today" still print the same text.
5. **The Calendar's short past** (§4, D6). Needs step 1 only. After it lands,
   `sm data publish` is run once per instance, so the months older than the Calendar's ten
   weeks lose their long texts too.
6. **The short day, with its page form** (§4, §5, §6.1): the briefing, also on a morning
   with a proposal, "📅 Today" and the day after "Change it". Needs steps 1, 2 and 4.
