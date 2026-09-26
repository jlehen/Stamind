# Design: Recording a test result from the companion chat

**Status:** Implemented · **Date:** 2026-09-26

Today a fitness-test result reaches the logbook (`benchmark_results`, the dated list of
FTP, threshold pace and the other measured thresholds) through one door only: the typed
command `benchmark record cycling --ftp 250`. An athlete on the companion chat has no door.
The week planner schedules a test at every mesocycle boundary, the athlete rides it, and the
number stays on the Zwift screen. This adds two doors into the chat, and both end at the same
question.

## 1. The week

It is Saturday. The morning message said "Today: 20-min FTP test, indoors". At 11:00 the test is
done and Zwift shows 250 W. The athlete types "Did the ramp test instead, 250, legs were heavy". The
chat answers "→ writing down your test result", then: "Your FTP from today's test, “20-min FTP
test”: 250 W, up from 235 W (+6.4%). Note: “ramp test instead, legs were heavy”. Shall I write it down?" with Yes and No
buttons. She taps Yes. The chat says "Written down 💪" Because 6.4% is past the replan band, one more
line follows: "That's a big enough change that your plan should be rebuilt around it — ⟨operator⟩
takes care of that from the computer."

Now the same Saturday, but she types nothing. On Sunday at 08:00 the morning message arrives,
and after it one question from the queue: "How did Saturday's “20-min FTP test” go? Tell me the
number it gave you and I'll write it down." Under it: `[Tell me the number]` `[Nothing to
record]` `[🕐 Not now]`. She taps the first button, types "250", and gets the same read-back
and the same Yes and No as above. The stored row is the same too, and it points at Saturday's
session, so the logbook knows which planned test the number satisfied.

## 2. Two doors, one shape

The typed door is a new router intent, `record_test`, in the capture shape of
DESIGN_bot_simple_frontend.md §12.1: the router only names the intent, and a second, domain
focused call, `bot capture test_result "<text>"`, reads the message. The morning-after door
is a question kind in the athlete queue (DESIGN_athlete_queue.md §8) whose "Tell me the
number" answer takes typed text and hands it to that same capture. The one sentence that
explains the two: type your result whenever you have it, or wait for me to ask the morning
after a test; either way I read it back and ask before I write it down.

## 3. What the capture reads

The extraction runs on the router model and sees today's date, the five kinds it may return
(FTP, LTHR, threshold pace, CSS, MAS, spelled as the logbook stores them), and the benchmark
sessions of the last fourteen days, each as id, date, title and sport. It returns the kind,
the value as the athlete wrote it ("4:15" stays "4:15"), the sport if the message names one,
the date if the message names one, whether the message says a test was performed, and the id
of the listed session the message reports on, or null. Reading a bare "250" against a listed
FTP test is resolving, which §12.2 allows; inventing a kind with no test listed is filling,
which it forbids, so the reply asks "Which test was it — FTP, threshold pace, …?" and stops.

The extraction also returns a note: what the message says about the test beyond the number, such as
the protocol, the conditions or how it went, copied in the athlete's own words and never summarized,
or null when the message says nothing more. It becomes the row's `note`, which is the one place the
protocol is written down: the anchors line that both `plan generate` and `workout generate` read
carries it as "athlete's note", and a ramp test and a 20-minute test are not one series
(DESIGN_benchmark_workouts.md rev. 5). The router model is up to this because copying is not
judging; the same role already copies a goal's description and a rule's title out of free text. Its
two ways of getting it wrong, a paraphrase or an invented protocol, both land in the read-back in
quotes and die on "No". Storing the whole message as the note would need no model, and was not
chosen because a note that repeats the number and the kind is noise on that anchors line. A bare
"250" typed to the morning-after question gives no note.

The app then fills the rest: the value is parsed by the CLI's own pace-or-number reader; the
date is the named session's, else the message's, else today; the sport is the message's, else
the session's, else the kind's usual sport; the source is `test` when a session was named or
a test was said to be performed, and `manual` otherwise, the same weaker default the command
line uses. e1RM is not offered from chat: one number per lift is a footgun the terminal help
already warns about, and DESIGN_strength_tracking.md §12 wants the anchor gone.

The capture then calls `benchmark record` through its module, as the other captures call
`goal add`, with a new `--session ID` flag carrying the named session. The command keeps its
propose-then-confirm rule (DESIGN_benchmark_workouts.md §5.1); the confirm sentence and the
two lines after it become `runtime.render` methods, since every command a tap can reach speaks
through the renderer (§12.11). The companion words are §1's. The expert words are today's,
and `--session` is useful on the terminal for the same reason: the logbook's `workout_id`
column has been empty since Phase 1 because nothing ever set it.

No offer button follows a recorded result: nothing about the week changes today because of a
number. Sessions already written keep their watts and paces; the next time the week planner
writes or changes a session, it prescribes from the new value. A change past the replan band
gets the operator line in companion mode and the `plan generate` hint in expert mode, one
fact rendered twice, like `constraint_plan_shaping`.

## 4. The morning-after question

`bot morning`, after the data refresh it already runs, grades the benchmark sessions of the
past seven days. Each one graded done or partial, with no logbook row for its sport dated on
or after its day, is queued once, subject = the session's lineage id. The kind, `test_result`,
brings the five things §8 asks for: the wording above in both voices, a stale check (such a
row now exists, or the session is no longer live), the "Tell me the number" answer whose text
goes to the capture with the session pinned, the drop "Nothing to record", and the standard
"Not now". A "No" on the read-back raises `NotApplied`, so the item waits and the next walk
asks again. On the terminal the same item shows up in `sm queue answer`, and the typed answer
runs the same capture in the expert voice.

## 5. Guardrails

The model names an intent, fills typed fields, and may name a listed session; the CLI parses the
value, checks the kind against the sport as `benchmark record` already does, renders the preview
from the parsed values, and writes only after the tap. A wrong reading dies visibly: the read-back
shows the kind, the unit, the date, the note in quotes and the test it is filed under. The row is
reversible by the operator with `benchmark rm`, which stays typed vocabulary. The queue button runs
only the answer the item was queued with, on that item.

## 6. Touch points

| File | Change |
|---|---|
| `stamind/chat/routing.py` | `record_test` in the intent table, the capture map and the echoes; one line on the help card in `keyboards.py` |
| `stamind/cli/bot/route.py` | one router rule: a message stating a test's number is `record_test` even when it also says how the test felt |
| `stamind/cli/bot/test_result.py` (new) | the extraction prompt, the missing-field asks, the argv assembly, and the `test_result` queue kind; a file of its own because `capture.py` is at 359 lines |
| `stamind/cli/benchmarks.py` | `--session ID`; the confirm and the two after-lines move behind `runtime.render` |
| `stamind/cli/render/companion.py`, `expert.py` | `benchmark_confirm_question`, `benchmark_not_recorded`, `benchmark_recorded`, `benchmark_replan` |
| `stamind/athlete_queue.py`, `stamind/cli/bot/views.py` | the kind in `KINDS`; `bot morning` queues the question |
| `docs/ARCHITECTURE.md`, `DESIGN_bot_simple_frontend.md` §12.8, `DESIGN_benchmark_workouts.md` §5.3 | the intent row; the auto-link Phase 3 wanted now arrives through the question |
| `tests/test_cli_bot_capture.py`, `tests/test_athlete_queue.py` | one test per outcome above; `RouterTablesTest` picks up the new row on its own |

## 7. Not handled

A raw time the app would have to convert ("ran the 5k in 22:30") is asked back as a pace; the
capture transcribes, it does not compute a threshold. Units other than the logbook's (min/mile) are
read as the logbook's and die at the preview. A test done without the watch is never asked about,
and the typed door still works. Rewriting the sessions already on the calendar after a within-band
change is left as it is today. The companion day view does not mark a session as a test; the
session's title says it. A note remembered after the Yes has no chat door; the operator deletes and
re-records the row, which is the logbook's one correction path.
