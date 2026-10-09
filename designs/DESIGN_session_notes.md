# Design: What the athlete says about a session

**Status:** Implemented · **Date:** 2026-09-30

The athlete tells the coach how a session went: "This was tough. I did it on Zwift in ERG mode,
set the intervals to 235w. I stopped at ~12:30 in the second round." The bot hands those words to
`workout adapt -m` for one run, and then they are gone. When that run changes no session, nothing
a later model call reads holds them. When it does change one, a number the athlete gave can
survive in the new session's text, but only by accident. Garmin cannot replace the words: it does
not know that the reps were in ERG, that the athlete stopped by choice, or how long the climb took
inside a two-hour ride. This design keeps the words with the session they are about.

## 1. The week

It is Wednesday 30 Sep. One session is planned: "Climb-Pace 2x15 min", with a 242 W ceiling. The
athlete rides it and writes the message above. The chat echoes "→ passing that on to your coach",
and `workout adapt` runs as it always has. Before the coach's answer, one line says "Kept with
today's “Climb-Pace 2x15 min”". On Monday 5 Oct the week planner writes the week after the FTP
re-test. Its prompt lists the sessions the athlete commented on in the last two weeks. Wednesday's
session is there with its prescription and the athlete's words, next to that day's Garmin line.
On about 15 Oct, Wednesday falls out of every prompt's look back, and the words go with it.

## 2. What is kept

One row per message: the session's lineage id (the identity a session keeps through all its
revisions, DESIGN_workout_revisions.md §4), when it was sent, and the text exactly as typed. No
model touches the text. The row hangs off the planned session, not the Garmin activity, for two
reasons. The planned session holds the prescription the words are about: the watts, the reps. And
it exists before Garmin uploads the ride, so a message sent next to the bike is kept at once.

Only `workout adapt -m` keeps its note, from the chat or the terminal. A `workout tweak` request
is a change the athlete decided, and it is acted on at once, so it is not kept.

## 3. Which session

Amended 2026-10-09. The first rule went by the date alone: with one session that day, the note
was kept with it, whatever the words said. On Wednesday 7 October the athlete wrote "No
training on November 12th, I bring my child to work", and the words were kept with that day's
FTP test. On Thursday "Tomorrow I will not go to work, so no access to the gym" was kept with
Thursday's recovery ride.

A note is kept only when it is about the training of the day: "not much time today, had to
cut it short", "after a long warm-up", "not on my normal bike". Whether it is, only the words
can say. The week planner is the model call inside `workout adapt` that writes the sessions,
and it reads the note in that run anyway. Its answer says which session the note is about.

The candidates are a day's sessions, rest days left out. The day is the one `workout adapt`
runs for: today, unless the terminal passes `--date`. It is the day before when the note says
so: "yesterday's ride was tough", written the next morning. A note that names no day is about
today. The week planner gives one of three answers:

- **A session**, named by its day and its sport. The note is kept with it, and the line in §1
  says which: "Kept with yesterday's “Climb-Pace 2x15 min”."
- **None.** The note is about another day, about how the athlete feels with no word about a
  session, or it is a question. It is not kept. `workout adapt` still reads it once.
- **One of that day's sessions, and the note does not say which.** The week planner never
  picks. With one session that day, the note is kept with it. With several, the athlete is
  asked. Yesterday works as today does: "yesterday was tough" after a day with a ride and a
  gym session asks which of the two.

How the athlete is asked. In a terminal, on the spot: "Which session is this about?", one
choice per session, plus "Not about a session". In the chat the question is queued, as every
question in the chat is (DESIGN_athlete_queue.md §2). It is sent with the other questions of
that run: at once, or when the coach's proposal is answered (DESIGN_waiting_proposal.md
§6.3). It quotes the words, because it can arrive minutes after them:

> You wrote: “not much time today, had to cut it short”
> Which of today's sessions was that about?
>
> `[Easy Ride]` `[Kettlebell HIIT]` `[Not about a session]`

A tap on a session keeps the note with it: "Kept with today's “Kettlebell HIIT”." The last
answer keeps nothing. The question is closed without being asked once its day is out of every
prompt's look back (§4), because nobody would read the note.

An answer the app cannot use keeps nothing: a sport with no session that day, one that two
sessions of the day share, or a day other than those two.

The row is written after the coach's call returns, so a call that fails and a message sent again
do not leave the same words twice.

**Choices**, made without the author:

1. A remark about how the athlete feels, with no word about a session ("I'm tired today"), is
   not kept. The other way keeps it with the day's session, where a later run would read it
   beside a session that went badly.
2. The week planner answered for the sessions of the day it runs for and no other.
   **Overruled 2026-10-09: it may name yesterday's session.**
3. The question in the chat quotes the athlete's words. The terminal's question does not: the
   words were typed a moment before, on the same screen.
4. A note is about yesterday only when its words say so. "That ride was brutal", sent at
   07:00 before today's ride, is read as about today. The other way lets the week planner
   work the day out from which session has been trained, which is a guess.
5. No day further back than yesterday. "Tuesday's intervals were too hard", written on
   Thursday, is not kept.

## 4. Who reads it, and for how long

A hydrated session carries its notes as `athlete_notes`, and a prompt that prints a past session
prints them under it:

- `workout adapt` lists every session of its look back with the full prescription and what was
  performed. The notes follow the description.
- The week planner is shown no past sessions one by one, only the Garmin activities of its look
  back. It gets one section, RECENT SESSIONS THE ATHLETE SPOKE ABOUT: the sessions of that look
  back that carry a note, each with its prescription and the words. A session from today on is
  already in one of its other lists, which print the notes the same way.
- The strength planner's SESSIONS AS DONE puts the words under their day.

Nothing is trimmed. Storage grows by about ten short rows a month. The prompts are bounded
already: a note is printed only where its session is, and every prompt looks back a fixed
distance (`metrics_lookback_days` for the two week-level calls, `strength.recent_days` for the
strength planner).

## 5. Not handled

- A message sent the next morning about yesterday's ride is kept with yesterday's session
  when it says "yesterday" (amended 2026-10-09, §3). Before, it was kept with today's
  session. One that does not say so is read as about today, and one about an earlier day is
  not kept.
- A fact that should outlive the look back, such as a climb record or "ERG feels harder than
  riding outdoors", has no home here. `plan generate` and `data reflect` do not read the notes.
  Amended 2026-10-01 (DESIGN_cycle_retrospective.md §5): the retrospective writer reads the
  notes of a mesocycle's sessions when it writes the record of that mesocycle. A reason
  stated in a note can so outlive the look back, inside the record. A record is not a home
  for a standing fact such as a climb record.
- A note is never edited or removed on its own. `wipe_workouts` clears them with the sessions.
