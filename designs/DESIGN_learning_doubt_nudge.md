# Design: The coach asks before it stops trusting what it learned

**Status:** Proposed · **Date:** 2026-09-10

## 1. The problem

`data reflect` was built to run unattended: it snaps its window to the last completed
Sunday, so a daily cron line costs nothing six days out of seven, and `--auto` keeps it
from blocking on a prompt (DESIGN_backward_evaluation.md §8, DESIGN_evidence_based_confidence.md §7).
Once it runs that way, one thing it produces has nowhere to go.

Take the week of 14 September. Two weeks earlier the coach recorded, from the athlete's
own history, that she absorbs two hard days back to back. Reflect now reads two weeks in
which she did not: HRV down after each double, the second session cut short both times.
It emits a `contradict` delta, the app files the two weeks against the learning, the
derived level drops below the stored one, and the app writes a *proposal* — the learning
keeps its live confidence until a human rules (§7 of the confidence design, deliberately).

Interactively, that human moment is the end of the run: the CLI shows the learning and
asks demote / keep / skip. Under `--auto` the moment is skipped, and there is no other.
The proposal is a count in `status` and in the web summary, and a `⚠` line in
`learnings list`. The companion athlete never sees any of those. Meanwhile the learning
stays in every `workout generate` and `workout adapt` prompt at full strength, telling
the coach the athlete tolerates doubles that she has now failed twice. A proposal that
nobody is ever asked about is the design's own caution turned against it: the cautious
path was chosen so a human would confirm, and automation removed the human.

Staleness proposals do not have this problem under cron: `--auto` applies them directly,
which the confidence design argued is what "unattended" means for a time-driven,
low-stakes step. Only contradiction proposals queue. But a skip on an interactive run
leaves a staleness proposal pending too, and it is the same queue, so what follows
handles both and only one sentence differs.

## 2. Who decides, and what they are asked

The athlete decides. But not by reading the learning: a learning is written for the
coach's prompt, not for her. The rows a real instance holds say things like "appears able
to absorb a two-week mixed endurance overload of roughly 380-490 TSS when it is followed by
a lower-load consolidation week", or that easy volume "drifts into tempo: HR Z3 accumulated
2.0-2.3 h/week", or that logged session RPE "is unreliable" because it fell while severe-domain
power time rose. They name her in the third person. Shown one of those and asked "does it
still hold?", she can only guess at a number she never saw; the honest tap is "Not sure"
every time, and the queue is back where it started.

What she *can* answer is the felt claim underneath. "You bounce back fine from two hard
days in a row." "Evenings with a few drinks cost you the next morning." "The effort scores
you log run lower than the rides really were." Those she knows better than the data does,
and the data has just voiced a doubt about them. So the coach translates: an LLM call
rewrites the learning as one plain second-person sentence about her experience, and the
athlete says whether it still fits. The model authors prose, as it does for the week line
(DESIGN_plan_change_continuity.md §6.4); it never authors what the buttons run (§7).

That footing is the one DESIGN_bot_simple_frontend.md §5.5 gave `constraint rm`: the
CLI offers a fixed choice built from real rows, the athlete taps, the model decides
nothing. In companion mode she never types, so the question arrives as a message with
buttons. In expert mode there is no push, and the operator's surface is the cron job's
own output (§8).

## 3. When the coach asks

The bot has one unprompted channel, the morning push, and DESIGN_plan_change_continuity.md
§6.4 already chose not to add another. The question rides it.

Not every morning, though. The push's button row is one live row per chat: a tap spends
it (`trainmate_bot.py`, the `ui:` callback), so three answer buttons beside "😴 Feeling
tired" would mean that answering a question about last month drops the button she needed
for today. The runway button accepted that trade because it is one button and an offer.
Three buttons and a question is a different weight.

So the coach asks **on a morning with nothing else to offer buttons for**: a rest day (or
the rare day already trained by push time), and no runway row live. One gate, one
sentence: the question takes the row only when the row would otherwise be empty. The rest
day is also when the athlete has the headspace for "does this still describe you", which
is the behaviour a human coach has anyway. A proposal raised on a Wednesday waits for
Sunday; the doubt is weeks old by then and loses nothing.

Two edge states inherit the runway design's answers. The exhausted-schedule silence
(`run_bot_morning`'s early return) stays silent: no plan, no push, no question. And a
rest day inside the runway window shows the runway offer and holds the question, since
extending the schedule is the more urgent of the two.

**One question per morning.** With several proposals pending, the push takes a
contradiction before a staleness proposal (the contradicted learning is the one still
steering prompts at full strength), lowest id first within each; the next rest day takes
the next. A morning of three questions is a form, not a coach.

**Re-asking.** An unanswered question is re-asked once per reflect pass, not once per
day. Under the weekly cron that is weekly, which is how often a human coach would raise
the same doubt; a hand-run reflect re-raises it too, which is what the CLI's own "skip:
re-raised on the next run" already means. The marker that makes this true is in §5.

## 4. What she sees

> Rest day — enjoy it 🎉
>
> 🤔 Something I've been assuming about you — tell me if it still fits: *You bounce back
> fine from two hard days in a row.* Lately I'm less sure. If it doesn't fit any more,
> I'll lean on it less.
>
> `[✅ Still fits]` `[❌ Not really]` `[🤷 Not sure]`

The sentence in italics is the coach's. `CoachService.learning_question(learning)` makes
one short call with the learning's text and sports and asks for a single second-person
statement of what the learning claims about the athlete's experience: plain words, no
metrics, no zones, no name, in the prompt's language. A *statement* rather than a
question, so the frame around it fixes what the buttons mean: "still fits" is always the
learning holding, whatever wording the model chose. The call happens only once the gate
in §3 has passed, so it costs one call on a free morning with a candidate, and it has the
`_auto_adapt_note` posture: a failure logs a terminal aside and the push goes out without
a question, marker untouched, so the next free morning tries again.

Everything around the italics is a fixed English string, like the rest of the companion.
No id, no confidence tier (§5.5's rule for companion prose).

**Two facts, two middle sentences.** A contradiction proposal says *"Lately I'm less
sure."* A staleness proposal says *"It's been a while since I saw it."* The second is what
the CLI's own `keep` means by staleness (it refreshes recency rather than overruling
evidence), so the bot must not claim recent training disproved something when nothing
did. `db.keep_learning` already decides which kind a proposal is, inline; that test moves
to a named `db.proposal_kind(learning_id)` so the wording and the keep share one definition.

**The last sentence says what "Not really" does.** A demotion one rung down reads *"If it
doesn't fit any more, I'll lean on it less."* A proposal on the retirement rung reads
*"If it doesn't fit any more, I'll set it aside."*, which is what it now does (§6).

Three buttons, the CLI's three answers. **Still fits** sends `learnings keep <id>`: the
athlete overrules the contradicting weeks, and `keep` neutralizes those evidence rows and
re-derives confidence. **Not really** sends `learnings demote <id>`. **Not sure** is an
`ack` that runs nothing ("No problem — I'll ask again another time."), which is the CLI's
skip: the proposal stays pending and comes back after the next reflect pass. A typed
reply instead of a tap goes to the free-text router like any other message, which cannot
reach these verbs; nothing changes and the buttons stay.

What the tap prints back is a renderer method with a companion body, the way
`constraint_removed` is (§10): *"Thanks — good to know, I'll keep that in mind."* for
keep, *"Got it — I'll lean on that less."* for a demotion, *"Got it — I've set that idea
aside."* for a retirement, and *"Already settled — thanks!"* when the proposal was
resolved in the meantime, whether by the operator or by a reflect pass that reinforced
the learning. The expert bodies keep today's text and the labeled learning block.

## 5. State

One settings-table marker, beside `MORNING_MARKER` and `NOTE_MARKER` in `cli/bot.py`:
`push_learning_asked`, a small JSON map of `learning_id → reflect watermark at the time
it was asked`. A proposal is a candidate for this morning's question when it is pending
and either absent from the map or filed under an older watermark than the current
`sync_state['reflect']`. The push writes the entry only when the question was actually
sent (the §6.4 rule: track what was delivered, not the day), and drops entries whose
learning no longer has a proposal, so a resolved question does not keep a dead key. The
coach's sentence is not stored; the next ask makes a fresh one.

Keying on the reflect watermark rather than a day count is what makes "once per reflect
pass" need no new number and no clock: a reflect that found nothing new does not move the
watermark, and then nothing was re-read and there is no new reason to ask. A question row
that another command's buttons displaced before she answered waits the same way a shrug
does: it comes back after the next reflect pass.

The cron line for reflect goes midweek and before the morning window, say a Wednesday
05:00 beside a 07:00 `morning_time`: midweek because the watermark is forward-only and
Garmin can still rewrite Sunday's ride for a few days, before the window so a proposal
raised that morning is asked that morning if the day is free.

The bot process holds none of this. A restart, a forced re-run, and the push loop's
catch-up ticks all read the same two facts from the database, per the §4.2 rule that the
push scheduler owns no state.

## 6. Nothing a tap does is final

Both buttons erase something today. "Not really" on the retirement rung runs
`demote_learning`, which `DELETE`s the row. "Still fits" runs `keep_learning`, which
`DELETE`s every contradicting evidence row, so a mis-tap wipes two bad weeks and the doubt
needs two more to come back. §7 of the simple-frontend design asks that a tap-reachable
mutation be reversible or confirm-gated; a confirm step would make her surest answer two
taps, so both become reversible instead, following what `goal rm` already does (a
`status` column, `--purge` for the real delete).

- `coach_learnings` gains `status TEXT DEFAULT 'active'` (`'active' | 'archived'`), a
  one-line migration beside the phase-2 ones. `get_learnings()` returns active rows, which
  is what every prompt reads; `learnings list --archived` shows the rest.
- Every path that retires a learning archives it instead: `demote_learning` on the
  `retire` target, the `retire` delta op, the `--auto` staleness ladder's bottom rung, and
  `learnings rm`. `learnings rm --purge` is the hard delete, with the evidence cascade.
  A delta addressed to an archived learning is skipped like one addressed to a missing id.
- `learnings restore <id>` puts an archived learning back at tentative with its evidence.
- `keep_learning` sets the contradicting rows' polarity to `0` rather than deleting them.
  `_evidence_counts` already counts only `±1`, so the arithmetic is unchanged, and
  `learnings show` lists the weeks as overruled. The unique key
  `(learning_id, week, polarity)` still holds.

Reversible by the operator is what the guardrail means (a companion `constraint rm` is
undone the same way), so the companion gets no undo button.

## 7. Guardrails

`learnings keep <id>` and `learnings demote <id>` become tap-reachable, and only as the
morning push's fixed argv built from a real pending row: the same posture as
`constraint rm` in DESIGN_bot_simple_frontend.md §7, which is amended in the same change.
Neither is routable from free text, and the router's intent table does not grow. The
model writes the sentence in italics and nothing else: which learning is asked, what the
buttons run, and what the frame around the sentence promises are the CLI's, rendered from
database rows (§4.4). With §6, both taps are reversible, so the guardrail holds without a
confirm step.

## 8. Expert mode

There is no push. The operator's surfaces are the ones the confidence design built:
`status` counts pending proposals, `learnings list` marks them, and an interactive
`data reflect` (without `--auto`) resolves them at run end. One addition: `data reflect
--auto` ends by listing the proposals it left pending, one line each with the id, the
target and the `learnings keep`/`learnings demote` hint. The cron job's output is the
operator's morning push, and today it says nothing about the queue.

## 9. Deliberately not done

- **A separate push, or a second scheduler.** The question rides the existing morning
  push and its settings markers, like the week line and the runway offer before it.
- **Auto-accepting old proposals.** A proposal unanswered for N days could apply itself.
  The confidence design ruled this out for contradiction demotions, and nothing here
  changes that: the queue now has a reader, which was the missing piece.
- **Recording "Not sure".** It is an ack, not a command, so the app cannot count shrugs
  and has no give-up rule; a proposal she is unsure about is asked again after each
  reflect pass until she or the operator settles it.
- **Showing the numbers.** The CLI's `learnings show` lists the weeks for and against.
  The companion asks about her experience instead; the weeks would be dates she cannot
  act on. If a "why do you think so?" is ever wanted, it is a `bot` view like `bot block`,
  not more push.
- **Asking beside the session buttons.** Considered in §3 and rejected: one tap would
  spend both rows' meaning.
- **A `workout adapt` hint in expert mode.** The runway design added its hint to the
  daily CLI touchpoints; this one is not schedule-shaped, the auto-reflect summary
  carries the queue, and a third line under every adaptation about the coach's memory is
  noise on the surface that decides today's training.

## 10. Touch points

- `trainmate/cli/bot.py`: the candidate selection and marker (`push_learning_asked`),
  `learning_answer_buttons(learning)`, the gate in `run_bot_morning` after the runway row,
  the coach call under the `_auto_adapt_note` posture.
- `trainmate/coach/service/`: `learning_question(learning)` and its prompt (one
  second-person statement, plain words, no metrics, no name).
- `trainmate/cli/render.py`: `simple_learning_question_lines(statement, kind, target)`
  beside `simple_runway_lines`; renderer methods `learning_kept`, `learning_demoted(level)`,
  `learning_set_aside`, `learning_settled` with expert and companion bodies.
- `trainmate/db/learnings.py` and `db/base.py`: the `status` column and migration,
  archive in place of the four deletes, `restore_learning`, `proposal_kind(learning_id)`
  with `keep_learning` calling it, polarity `0` in `keep_learning`, `_exists` on active rows.
- `trainmate/cli/learnings.py`: `rm --purge`, `restore`, `list --archived`, `show` naming
  overruled weeks, keep/demote printing through the renderer.
- `trainmate/coach/service/prompt.py`: the pending list at the end of an `--auto` review.
- `tests/test_cli_bot.py`, `tests/test_learnings*.py`: the gate (session buttons win,
  runway wins, rest day asks), one-per-morning and its ordering, the re-ask keyed on the
  watermark, the marker pruned on resolution, the two middle sentences and two last
  sentences, the coach call failing without sinking the push, archive-and-restore for
  each retire path, overruled rows not counted.
- Docs: DESIGN_bot_simple_frontend.md §7 (guardrail amendment), DESIGN_evidence_based_confidence.md
  §7 (AS BUILT rev 3: a third resolving surface, retirement archives), ARCHITECTURE.md §3
  propose/confirm paragraph, README's learnings bullet.
