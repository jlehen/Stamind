# Review of DESIGN_strength_tracking.md phase 2 (rev. 10), 2026-09-16

Reviewed on branch worktree-strength-tracking-design after rebasing on main 3f6ebfe (the
vocabulary sweep). The sweep did not touch designs/DESIGN_strength_tracking.md or
trainmate/strength/, so everything below still stands. Each item says what is wrong, where,
and the fix I would make. Nothing has been changed yet.

The rule on main now (AGENTS.md, README "The words TrainMate uses"): say **mesocycle**,
never "block"; a **session** is planned, an **activity** is what Garmin recorded; name the
model call (**week planner**, **strength planner**), never "the planner" or "the call";
"the coach" is TrainMate speaking to the athlete.

## A. Vocabulary — DONE: design (rev. 11) and code (Group/groups(), activity_lines,
read_new_activities, activity_words, activity_ref, RECENT_DAYS, activity_exercises_by_day,
payload key "groups", CLI help). The athlete-facing "gym session" wording was kept on purpose
and the design says so in §7.

A1. **The header's list of five names is stale against main.** Lines 20–28 say "a block is
one mesocycle" and §12 repeats it ("a block is one mesocycle"). Main retired "block" for a
mesocycle. Rewrite the header list to main's rule (plan, mesocycle, week planner, strength
planner, session/activity) and every "block" that means a mesocycle to "mesocycle": about
ten uses, e.g. line 23 "inside the blocks the plan gives it", line 679 "when the block is in
a light week", line 855 "a five-week block", lines 1121–1124 "a block's boundary week",
"a block's test".

A2. **"Session" means a Garmin activity through the whole strength half.** §3 says in bold
"a strength session is an activity whose raw Garmin type is strength_training and that
returned at least one set" and §12 repeats it. From there "session" is the recorded thing
in §6 ("a session's sets are read once"), §7 ("one per session", "the session is
discarded"), §8 ("last eight strength session days", "each entry shows that exercise's
last three sessions", "the session RPE"), §10 ("the session RPE"), while §9 uses "session"
for the planned thing ("sessions to write", "a kept session"). A reader of §8 cannot tell
which is meant without §3. Fix: "strength activity" for the recorded thing in the design's
own prose, "day" where the design already counts by day, and the same in the docstrings of
trainmate/strength/sets.py ("A strength session's sets") and questions.py. Open call for
the user: the athlete-facing wording "Thu Sep 3 09:43 gym session" (questions.py
session_words / companion_session_words) is what an athlete would say; decide whether the
rule applies to text the athlete reads.

A3. **"Block" for a group of unnamed sets.** About thirty-five uses, from the title
("naming the blocks") through §7 and §12, plus `Block` and `blocks()` in sets.py and
`payload["blocks"]` in questions.py. The sweep explicitly left this to the strength
branch. With "block" no longer meaning a mesocycle anywhere else it no longer collides,
but main's rule is "never block", and the design's own companion wording already says
"5 groups of sets it couldn't name". Recommend "group" in prose and code (`SetGroup`,
`groups()`), or decide explicitly that "block" is allowed for this one meaning and write
that into AGENTS.md.

A4. **"Block" for a prompt region.** Line 704 "would double the block with names", line 914
"the shipped and the athlete's science blocks". Say "region" (§9 already says "prompt
region" once).

A5. **"Workout" for a recorded activity.** Lines 582, 617–633 ("a day with two workouts",
"done in two workouts of one day", "a day with one workout"), 540 and 1062 ("the workout
still counts as training"), 1066. Main's README says the commands call sessions "workouts",
so "workout" for the recorded thing is the wrong side. Say "activity".

A6. **"The coach" standing for the strength planner.** Line 328 "the coach would have read a
deload", line 583 area / §8 "A coach shown one exercise prescribes the belt squat blind",
line 883 "stated so the coach can defend a number". Say "the strength planner". The other
"the coach" uses (§1, §2, §11) are TrainMate speaking and are fine.

A7. **"Weight planning"** (§7 line ~537, §12 line ~1093 "keep a session out of weight
planning") is an unnamed sixth thing. Say "out of the strength history" or "away from the
strength planner".

No bare "planner", no "the call", none of the dead names (kilogram call, prescription call,
strength_prescribe, block planner, top planner).

## B. Gaps and inconsistencies in phase 2 — DONE in rev. 12, with two departures from the
fixes proposed below: B4/B5 restate the science as a rep range at one load (the reps the
athlete's dial, the load the strength planner's), so every session is written at the next
one's numbers and no ladder is written ahead; and C2 is solved by a failed strength planner
call failing the proposal, as a failed week planner call does, so a session with a brief
and no sets never exists. C1–C6 also DONE.

The week used below is the design's own: `workout generate` wrote the mesocycle on Sunday
September 13, the athlete lifts at the gym Monday the 14th, Thursday the 17th is the next
gym day, `workout adapt` runs each morning.

B1. **A kept strength session with no prescribed sets never triggers the strength
planner.** §9 "What it is given" says such a session (written before phase 2, or whose
strength planner call failed) is a session to write, and "Checking the output" says "the
next `workout generate` or `workout adapt` writes it". But "The same stamp says when the
strength planner runs at all" lists two triggers: the week planner wrote a strength
session, or the stamp is later than the change time of a kept session **with** prescribed
sets. A quiet Tuesday and Wednesday where the week planner keeps everything never run it.
Fix: a third trigger, a kept strength session in the span has no prescribed sets.

B2. **The evidence rule leaks when the answer is "keep".** Monday's sets are read Tuesday
morning, so the stamp moves past Thursday's Sunday revision. Tuesday's adapt shows Thursday
to the strength planner, which answers "keep"; nothing is appended, so Thursday's revision
time is still Sunday. Wednesday's adapt asks again, and this time randomness gives 142.5
where it stood at 145, the case the rule exists to prevent. Fix: remember per session
which stamp it was last checked against (on the change row, or a small table keyed by
lineage), and apply a change only when the stamp is later than both the revision time and
that check. Also say out loud that the stamp is global: naming a lat pulldown group from two
weeks ago counts as new evidence for every kept session in the span.

B3. **A revised or moved session is rewritten from scratch.** "Sessions to write" includes
"new, revised or moved". When the week planner shifts Thursday to Friday for the weather or
shortens it by ten minutes, the whole session is written again, kilograms included, with no
evidence rule. `workout swap`, which also moves a session, copies the sets. Two ways to move
a session, two fates for the numbers (the companion explicability rule). Fix: a revised
session that already has prescribed sets is a session to check, shown with its new brief;
its sets change only on new evidence or when the brief changed.

B4. **The §9 example breaks the §10 one-dial rule.** §10: one dial per session, never both;
load goes up only once every set reaches the top of the range. §9's Monday: belt squat
3×5 @ 140 → 4×4 @ 145, glute bridge 4×5 @ 130 → 4×4 @ 135. Reps and load both moved, and 5
was not the top of a range that continues at 4. Fix the example (e.g. belt squat 4×5 @ 145
after 3×5 hit the top of a 3–5 range, or 3×6 @ 140 in a 4–6 range) or the rule; an
implementer will copy the example into a test.

B5. **Nothing says how ten sessions are written from one history.** A `workout generate`
over five weeks writes ten strength sessions at once; double progression only says how to
step from the last lifted session to the next. The §9 Thursday example assumes a ladder was
written ahead ("the next step of a ladder Monday did not climb"), which the rule as stated
cannot produce, since a step depends on reps not yet lifted. Fix: the science file says
sessions after the next are written as if the ones before went to plan, and the
kept-session check corrects them as sets come in.

B6. **The week after a light week starts from the wrong place.** In a light week the load
comes down a tenth and a set is dropped. The next week the history shows that light session
as the most recent, with nothing on the line saying the day was light. "Reps go up until
every set reaches the top" reads the lighter load as the baseline; "a session that missed
the bottom is repeated" cannot tell a miss from a planned reduction. Fix: the file says a
light week is not a step and the next week resumes from the session before it, and the
history marks a day whose prescription was a light one.

B7. **The history cannot show what was skipped.** The prescription prints beside an
exercise only when the athlete did it. Monday's chin-ups, prescribed 3×4 and never done,
appear nowhere: no chin-up entry, and no other line mentions them. The strength planner
writes chin-ups again every Monday, never knowing. A session skipped altogether shows
nowhere either. The open question "whether sessions in kilograms get followed" is one the
strength planner cannot observe. Fix: a line per day listing prescribed exercises not done.
In the same place, "prescribed 3×5 @ 75" drops the rep range (reps_low–reps_high) the
strength planner was progressing in; print it.

## C. Smaller things

C1. **The seam.** The brief is free prose from the week planner; a brief with a paragraph
break splits at the wrong blank line. Collapse blank lines when storing the brief, or store
it in its own column.

C2. **Sessions written before phase 2.** Their description is the old prose ("Squat 4x4, hip
thrust or RDL 4x4 at 8RM load"), not a brief. When the strength planner writes them (kept,
no sets → session to write), that prose sits above the seam naming reps that may disagree
with the lines below. Say how the transition goes: the week planner rewrites them first, or
the strength planner is told the text above the seam is not a brief and the description is
replaced.

C3. **The `sets_final` drop label.** Phase 2 makes it "leave it as it is", meaning the
watch's guesses never count, while "yes, final" means they do. Both read as "it's fine" at
breakfast, and the wrong tap silently loses a session from the history for good. The drop
should say what it does, e.g. "don't count these names".

C4. **Where `strength.history_changed_at` lives** is not said (§5 names it; presumably the
settings table like `sets_since`). Say so.

C5. **`sets_final` staleness.** §7 lists `strength reset`, discard and a vanished activity;
§11.1 says `strength name` also freezes a waiting session, so it belongs on that list.

C6. **Discarded sessions and the "last three".** §8 says discarded days are skipped when
choosing the eight days; it does not say the three sessions per exercise skip them too.
Say it.

## D. Verified against the code (no action)

`structure_revision` runs at proposal time before anything is appended, so the strength
planner can rewrite the in-memory revisions and one row per session is right.
`WorkoutChange.append` / `restore` are where the design puts the sets. The no-op rule
(`PRESCRIPTION_FIELDS` in db/workouts.py) compares the stored description, so "sets not
written on a suppressed row" holds. The profile has both equipment lists
(`user_profile.equipment` and `weekly_schedule.<day>.equipment`). `tm bot morning` refreshes
Garmin, which reads the sets, before the morning adapt, so Tuesday's adapt sees Monday's
lifts. exercises.tsv: 1,498 lines, 801 accessory, 697 outside it (design says 692; close
enough). Schema is 14 on main, so `prescribed_sets` as 15 is right.

---

# Review of rev. 12 (commit 35ace96), 2026-09-16

Read by a fresh agent that was given the document and the code and none of the conclusions
behind rev. 12, then every code claim below checked again by hand. Same week as before: the
week planner (the LLM call inside `workout generate` and `workout adapt` that writes the
sessions of the coming weeks) wrote the mesocycle on Sunday September 13, the athlete lifts
Monday the 14th and Thursday the 17th, and `workout adapt` runs every morning inside the
morning push. The strength planner is the new LLM call that writes a strength session's
exercises and kilograms. Nothing has been changed yet.

## E. Things that break a real week

Status 2026-09-17: E2 and E3 DONE in rev. 13, with "brief" added to the design's names.
E1, F1–F6 and G1 DONE in rev. 14. G1 was restated: the sets follow the lineage, and the gap
is that `workout adapt` cannot yet name where a session came from (a main-side change, not
made; the user asked for a TODO item, text handed over since the TODO file is outside this
worktree). G2 dropped as a no-op. E4 DONE in rev. 15 as proposed below, plus the athlete is
told in the preview and the morning briefing when the kilograms were not rechecked. G3
DONE in rev. 16. Every item of the rev. 12 review is now closed.

E1. **A kilogram change cancels the other session of that day.** When `workout adapt`
applies a proposal, it runs a displacement rule: for every date the proposal mentions, any
session already on that date whose sport is neither in the proposal nor on the "held" list
is treated as pushed aside and voided, with the note "Removing overridden workout". The
held list is built from the sessions the week planner said to keep, plus completed ones
(trainmate/coach/service/adaptation.py, lines 336–349 and 436–455). Rev. 12 lets the
strength planner add a rewrite of a kept session to the proposal after the week planner
has answered, and says an adapt whose week planner changed nothing still becomes a
proposal that way (§9). Nothing puts that date's other sessions on the held list. The
design's own Thursday is a two-session day: the Wednesday brief says "fresh for Thursday's
intervals" and the next paragraph puts Thursday at the gym. Tuesday morning the week
planner keeps everything and the strength planner raises Thursday's belt squat to 145. The
proposal now names Thursday with one sport, strength. At apply, Thursday's intervals are on
a proposed date, not proposed and not held, so they are voided. The athlete opens the
calendar and Thursday's intervals are gone because a kilogram moved. Fix: when the strength
planner rewrites a session the week planner did not mention, the date's other sessions join
the held list before the proposal is built. One line of code; say it in §9 where the
strength planner is placed inside `workout_adapt`.

E2. **`prescribed_sets` cannot be schema 15.** The schema number is a "skip the work"
marker: a database already stamped with the current number never runs a migration added
under that number. `SCHEMA_VERSION` is 15 on main and on this branch (trainmate/db/base.py
line 12); phase 1's `exercise_sets` rides under 15 since the rebase, and the athlete's
database was stamped 15 by the September 14 read. Phase 2 under 15 would never create
`prescribed_sets` or `strength_checks` there, and the first `workout generate` would fail
on insert. The earlier review's "schema is 14 on main" was true when written and is not
now. Fix: 16, in the three places the design says 15 (header, §9, §11).

E3. **A hand-added strength session is a session to write, never written, and a trigger
every morning.** Rev. 12 defines the sessions to write as every strength session in the
span with no prescribed sets, says a session the athlete added with `workout add` is never
rewritten, says `workout add` starts a lineage with no prescribed sets, and says the one
kept session without prescribed sets is one written before phase 2. Those four sentences
cannot all be true: a hand-added session has no prescribed sets, so it is a session to
write that must not be written, and it makes the strength planner run every morning (the
new third trigger) with nothing it may do. The code can tell such a session apart: its
source is "manual" when its lineage's first change is an add (trainmate/db/workouts.py,
lines 164–171). There is a further case behind it. The continuity design makes a
hand-added session a standing one that the week planner may revise with a full entry,
description included (DESIGN_plan_change_continuity.md §4.2, §4.5), and rev. 12's new
instruction tells the week planner to write a brief for a strength day. On Wednesday the
athlete adds "Saturday gym with Paul, 60 min" for the 19th. Thursday's, Friday's and
Saturday's adapts each run the strength planner for nothing. On Friday the week planner
shortens Saturday to 40 minutes to protect Sunday's ride and, following its instruction,
writes a brief over the athlete's text. Saturday now has a brief and no sets, the state
rev. 12 says never exists. Fix: sessions to write are those with no prescribed sets that
were not added by hand, hand-added ones are out of the run trigger, and a hand-added
session stays the athlete's until the week planner writes a brief over it, from which
moment it is a session to write like any other. Drop the "one kept session" sentence.

E4. **A failed strength planner call now takes today's easing down with it.** Rev. 12 fails
the whole proposal when the strength planner fails twice, "the way it does today when the
week planner's call fails". Checked: in the morning push, `_auto_adapt_note`
(trainmate/cli/bot.py lines 271–288) catches every exception, prints a terminal aside that
never reaches the chat, renders the stored schedule, and the day marker is set anyway (line
412), so the next try is tomorrow. In the terminal, `workout adapt` prints the error. So
the sentence is right for the terminal and silent about the push. The new cost is the
coupling. Tuesday the 15th, HRV is low after Monday's lifting and a bad night; the week
planner eases Tuesday's intervals to an easy hour; the strength planner is then asked to
check Thursday and the model provider times out twice. The proposal fails. The morning
message shows Tuesday's intervals at full load, and nothing about the easing is sent.
Nothing about Thursday's belt squat needed deciding before Thursday. Fix: a failed strength
planner call fails the proposal only when there is a session to write, because a brief
with no sets is the state the rule prevents. When there are only sessions to check, a
failed call means "keep" for all of them: the old sets stand, the week planner's changes
apply, and the check happens tomorrow, since the stamp is still later than each session's
row. A session to check whose every entry fails validation is a keep too, not a failure.
And say what the push does: the schedule renders as stored and the error is a terminal
aside, as DESIGN_bot_simple_frontend.md already has it.

## F. Rules an implementer would copy into code and regret

F1. **The NOT DONE lines include today and days whose sets are not read yet.** The new
list walks "each day back to the oldest of the eight" that had a strength session with
prescribed sets and did not do all of it, and prints the whole session when the day has no
strength activity. Nothing excludes today. Thursday the 17th at 07:00 the push runs adapt;
the gym session is at 18:00; the history ends with "Thu Sep 17: no strength activity (belt
squat 3×4–6 @ 145, ...)". The strength planner reads a skipped session on a day that has not
happened. Separately, the set-reading step gives up on a Garmin error and leaves the
activity with `sets_read_at` NULL (trainmate/strength/sets.py line 279), so on Friday, if
Thursday's read failed, the line says the same about a session the athlete did. Fix: the
lines cover days before today, and a day with an activity whose sets are not read yet is
printed as "sets not read yet", the phrase §6 already uses.

F2. **After a light week, an athlete who lifts three times a week loses the day to resume
from.** §10 says the week after a light week resumes from the last day that was not light.
§8 shows each exercise's last three days. Those agree only when the light week holds at
most two days of the exercise. The design's athlete lifts twice a week, so the example
works; an athlete who lifts Monday, Wednesday and Friday, with the light week September 28
to October 4, opens Monday October 5 with the belt squat's entry showing three light days
and nothing before them. Fix: light days do not count toward the three. An entry shows the
last three days that were not light, and every light day since the oldest of them.

F3. **The briefing's note is the week planner's sentence even when only the strength
planner changed something.** Rev. 12 says the reason for changing a kept session lands in
the revision's reason column and so reaches the morning briefing's note. Checked: the note
the push sends is the proposal's overall reason (bot.py line 283), which is the week
planner's, defaulting to "No adaptation needed." (adaptation.py line 110). The per-session
reason reaches `workout batches` only. Tuesday the week planner holds everything and the
strength planner raises Thursday to 145; the push prints "No adaptation needed." while
Thursday's kilograms have moved. Fix: when the week planner's proposal is empty and the
strength planner's changes make it one, the proposal's reason is the strength planner's
reasons, one sentence per changed session.

F4. **A shorter session keeps the full list of exercises.** A change to a session to check
is applied when the stamp moved or "the brief is not the one its sets were written under".
The duration is a field the week planner owns, apart from the brief's prose. Wednesday the
athlete writes "short on time Thursday, 40 minutes max"; the week planner cuts Thursday
from 70 to 40 minutes and leaves the brief, whose purpose has not changed. The strength
planner returns four exercises in place of seven; the rule drops the answer because
neither the stamp nor the brief moved. Thursday shows 40 minutes and seven exercises. Fix:
the duration is part of what the sets were written under, beside the brief. The date is
not, since a moved date is the case the rule protects.

F5. **When the `strength_checks` row is written is not said, and the propose-never-writes
rule decides it.** A "keep" appends nothing, a proposal can be declined at the preview, and
a propose method never writes (AGENTS.md). So the row for a keep has to be written by apply
or by the no-change record (`workout_revision_record_no_change`), and a declined proposal
writes nothing, so tomorrow asks again. Also the value stored should be the stamp the
history was built from, not the clock, or a read that lands between building the history
and applying is missed. Fix: two sentences in §9 saying exactly that.

F6. **What bumps the stamp.** The set-reading step runs on every pull and every push and
most mornings finds nothing to read. An implementer bumping on every run makes the check
run every morning, which is the randomness case the table prevents. The other way round,
the pull's deletion reconcile removes an activity and the cascade takes its sets, which
changes the history, and neither is on the list of writers. Fix: the step bumps only when
it stored at least one activity's sets, and a reconcile that deletes a strength activity
with sets bumps too.

## G. Claims of rev. 12 that are wrong or unsaid

G1. **An adapt that moves a session to another date does not keep its lineage.** Rev. 12
says a session the week planner moved keeps its sets and its `strength_checks` row "whose
lineage the row follows". Checked: adapt carries a lineage only for a same-date sport
substitution (adaptation.py lines 462–483); there is no cross-date move. A week planner
that moves Thursday's gym to Friday for the rain returns Thursday as rest and Friday as
strength, and Friday starts a new lineage with no prescribed sets, so it is a session to
write. `workout swap` does carry the lineage (trainmate/coach/service/editing.py line 182).
So the two ways of moving a session do not give the numbers one fate, contrary to what §9
now says. Fix, the smaller one: say it plainly. A session the week planner moves to another
date is written anew from the same history, at the next one's numbers like every session
(§10), and `workout swap` keeps its sets. The numbers come from the same place either way.

G2. **In `workout generate` past the committed window, "new" and "revised" are the same
thing.** The continuity design shows the week planner the standing sessions only; every
session past the window is written fresh, and its row lands on the existing lineage
(workouts.py line 198). Such a session has prescribed sets on its live revision and a fresh
brief in the proposal, so it is both. Either way its brief differs in wording and the sets
are rewritten. A re-run of `workout generate` on Sunday the 20th rewrites every October
Monday's kilograms from the same history. Fix: say that in `workout generate` a standing
session is a session to check and every other strength session in the span is a session to
write, and that re-running generate over days already written rewrites their kilograms the
way it rewrites everything else there. That is existing behaviour and needs no machinery.

G3. **Smaller things.** The §9 example writes the belt squat as two entries, "1×5 @ 120,
3×4–6 @ 140", and the §8 line for the same day prints "prescribed 3×4–6 @ 140", dropping
the warm-up; say that all of an exercise's entries print, in order, and that the step rule
in §10 reads the working entries, or a 1×4 warm-up at 120 reads as a set under the bottom
of the range. §10 says a set under the bottom "holds it with a note", but a keep appends
nothing whatever the notes say, so drop "with a note". Thursday the 17th is both "Thursday's
intervals" and "at the gym"; say it is a two-session day, since it is the day E1 bites. A
restore copies older sets while the `strength_checks` row keeps the later stamp, so the
restored numbers wait for new evidence; one sentence saying that is what an undo should do.
The open-questions list in §12 has its bullets run together into one paragraph with " - "
separators, since before rev. 12, and nine lines run past the wrap, seven of them rev. 12
insertions.

## H. Vocabulary

Clean against AGENTS.md: no "block", no bare "the planner" or "the call" outside the
definitions, "session" only for the planned thing and "activity" for the recorded one,
"workout" only in command and API names, "mesocycle" throughout, and the athlete-facing
"gym session" said to be deliberate.

## I. Verified against the code (no action)

Lineages continue in their slot unless the slot is empty or void, the change is an add, or
a generate lands on a manual session. `workout add` sessions are distinguishable by source.
The `settings` table already holds code-written markers (`push_morning_last`,
`push_note_last`), so the stamp has precedent, and it must not get a `Setting(...)` entry
in the registry, which the design already says. An adapt's span is today through the
active mesocycle's end; a generate's is what its selector picks. The no-op rule compares the
prescription fields and ignores the reason. Restore is a copy stamped `restored_from`. The
morning push runs the refresh, then the set-reading step, then the adapt.

## J. What I would change first

E1 and E2 break a real week outright. E3 and E4 are rev. 12 fixes that opened new gaps.
F1, F2 and F3 are the ones an implementer copies into code as written. The rest are one or
two sentences each.
