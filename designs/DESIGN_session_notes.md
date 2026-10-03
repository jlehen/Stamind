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

A rule on the date, never a model's guess. The candidates are the day's sessions, rest days left
out. The day is the one `workout adapt` runs for: today, unless the terminal passes `--date`.

- One candidate: the note is kept with it, and the line in §1 says which.
- Two or more: the athlete is asked "Which session is this about?", one button per session, plus
  "Not about a session".
- None: the note is not kept. `workout adapt` still reads it once.

The row is written after the coach's call returns, so a call that fails and a message sent again
do not leave the same words twice.

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

- A message sent the next morning about yesterday's ride is kept with today's session. The line
  in §1 shows it.
- A fact that should outlive the look back, such as a climb record or "ERG feels harder than
  riding outdoors", has no home here. `plan generate` and `data reflect` do not read the notes.
  Amended 2026-10-01 (DESIGN_cycle_retrospective.md §5): the retrospective writer reads the
  notes of a mesocycle's sessions when it writes the record of that mesocycle. A reason
  stated in a note can so outlive the look back, inside the record. A record is not a home
  for a standing fact such as a climb record.
- A note is never edited or removed on its own. `wipe_workouts` clears them with the sessions.
