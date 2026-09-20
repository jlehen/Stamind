# Design: The coach asks before it stops trusting what it learned

**Status:** Implemented (2026-09-14) · **Date:** 2026-09-14 (rev. 3)

Revision 3 answers a review of revision 2. On a companion instance, the bot's scheduler runs
reflect at night from Tuesday night on, outside the athlete's chat (§3.1). Every run applies
staleness steps directly, so the only doubt left to ask about is a contradiction (§3.2).
Reflect writes one line saying what went against the learning, and the question tells her
what the coach saw in her own sessions, worded discreetly (§4). The answers are Still fits
and Not really, which is also the answer when she is not sure. The question has no drop
button, so every answer settles the doubt (§4). A setting lets her stop being asked, and the
coach then decides by itself (§3.4). A retirement archives the learning, and every other
answer mends itself with training (§6).

Revision 2 put the question in the athlete queue (DESIGN_athlete_queue.md). At the end of
every `data reflect` and `data bootstrap` run, the coach queues one question for each pending
proposal, and the end-of-run prompt went away. The queue's row is the record of what was
asked (§5).

## 1. The problem

`data reflect` was built to run unattended: it snaps its window to the last completed
Sunday, so running it every day costs nothing six days out of seven, and `--auto` keeps it
from blocking on a prompt (DESIGN_backward_evaluation.md §8, DESIGN_evidence_based_confidence.md §7).
On a companion instance nothing runs it today. The athlete cannot type it, and no scheduler
starts it, so the date reflect has read up to stays where the bootstrap left it. And even
once it runs, one thing it produces has nowhere to go.

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

Even the interactive moment asks the wrong person on a companion instance. When the
operator runs reflect by hand for her, the end-of-run prompt asks the operator whether
something the coach learned about her still holds.

TrainMate now has a place for a question that nobody is waiting on: the athlete queue. It
holds a question until the athlete is there, sends it with the morning push, and keeps its
buttons working until she taps one. This design queues the doubt there.

## 2. Who decides, and what they are asked

The athlete decides. But not by reading the learning: a learning is written for the
coach's prompt, not for her. The rows a real instance holds say things like "appears able
to absorb a two-week mixed endurance overload of roughly 380-490 TSS when it is followed by
a lower-load consolidation week", or that easy volume "drifts into tempo: HR Z3 accumulated
2.0-2.3 h/week", or that logged session RPE "is unreliable" because it fell while severe-domain
power time rose. They name her in the third person. Shown one of those and asked "does it
still hold?", she can only guess at a number she never saw, and the honest answer is a shrug
every time.

What she *can* answer is the felt claim underneath. "You bounce back fine from two hard
days in a row." "The effort scores you log run lower than the rides really were." Those
she knows better than the data does, and the data has just voiced a doubt about them. So
the coach translates: an LLM call rewrites the learning as one plain second-person sentence
about her experience, and the athlete says whether it still fits. The model authors prose,
as it does for the week line (DESIGN_plan_change_continuity.md §6.4); it never authors what
the buttons run (§7).

Her feel alone is not enough, though. Take a learning that says her runs drift to tempo
unless the session caps her heart rate. The capped runs work, and she spends two weeks
mostly easy, so reflect doubts the learning. Asked only "You tend to run harder than an easy
pace — does that still fit?", she answers from how running feels: the easy pace feels like
walking, so she taps "Still fits", and overrules the two weeks that showed the cap working.
Her own sense of effort is what that learning exists to correct. Told "You tend to run
harder than an easy pace. But lately your runs have stayed easy.", she taps "Not really",
which is right. So the question also says what the coach saw, in terms of her own sessions
(§4). The same sentence settles a learning that only records what she did: "You haven't
started strength training yet. But the last two weeks had three strength sessions."

When she cannot tell even then, the coach goes by what it saw, and the question tells her
that "Not really" is the answer for that too. That is what a human coach does with an
athlete's "I don't know": lean on the doubted idea a little less and keep watching. An
athlete who would rather not be asked at all turns the questions off (§3.4).

The footing is the queue's (DESIGN_athlete_queue.md §9). The question's answers are fixed
when it is queued, built from the real proposal, and the model decides nothing. In
companion mode the question arrives in chat with buttons. In expert mode the operator
answers it with `queue answer` (§8).

## 3. When the coach asks

### 3.1 Who runs reflect

On a companion instance, the bot's scheduler runs it. The scheduler already wakes at least
every five minutes to send reminders and the morning push (DESIGN_athlete_queue.md §6.5).
From Wednesday to Sunday, on its first wake after 03:00 on the athlete's clock, it also starts
`data reflect --auto`.

The first of those runs, in the night from Tuesday to Wednesday, reads the week that ended on
Sunday. Waiting two days lets late Garmin syncs and edits to the weekend's activities land
before reflect reads them; the date reflect has read up to only moves forward, so a week it
has read is not read again. The runs from Thursday to Sunday find nothing new, unless the bot
was down on Wednesday night, in which case the first of them does Wednesday's work. On Monday
and Tuesday the scheduler does not start reflect.

It starts reflect outside her chat, the way the bot already runs the free-text router's
classifier: as a process of its own whose output goes to the bot's journal. Nothing is posted
to her, and the chat is not busy while it runs, so a tap at 03:05 is answered as usual. The
scheduler does not wait for it before the push.

A run that finds nothing new prints "Nothing new to reflect on" to the journal and makes no
model call. Wednesday's run makes the analysis call: on the operator's instance on
8 September that took 76 seconds and about 63,000 tokens. The scheduler remembers in memory
the day it last started reflect, as it does for the push. After a restart it may start a
second run the same day, which finds nothing new and does nothing.

The expert persona has no push and no nightly reflect: the operator runs reflect by hand,
or from cron.

### 3.2 What a run queues

At the end of every `data reflect` and `data bootstrap`, the staleness sweep runs first. It
lowers each learning that has gone past its silence budget by one level, directly, with or
without `--auto`. The confidence design proposed these steps on a run without `--auto` so
that the end-of-run prompt could ask about them. With that prompt gone, a proposal would turn
a time-driven step into a question she cannot answer: "it's been a while since I saw it"
tells her nothing about herself. A staleness step lowers the level without touching the
evidence, so the next supporting week raises it again.

Then the coach queues one question for each pending proposal whose learning is not dormant
and has no question waiting already (§5). Every pending proposal is now a contradiction.
The end-of-run prompt that asked demote, keep or skip is gone.

That follows the queue's rule for what is asked on the spot (DESIGN_athlete_queue.md §2): a
question is asked on the spot only when someone is watching and the command cannot go on
without the answer. Nothing in reflect waits on this answer, since a proposal changes
nothing until someone rules on it. Queuing also sends the question to the right person. On
a companion instance, a reflect the operator runs by hand queues her question for her
instead of putting it to the operator.

### 3.3 The same week

It is Wednesday 16 September. At 03:00 the scheduler starts reflect. The week that ended on
Sunday is the second in which she did not absorb her doubles. The learning had three
supporting weeks and stood at moderate. Two contradicting weeks leave it one week of net
support, which is tentative, so the app writes a proposal to demote it to tentative. Reflect
also wrote down what it saw: HRV fell after both doubles, and the second session was cut
short each time. At the end of the run the coach writes the two plain sentences and queues
the question, dated 03:00.

At 08:00 the morning push sends the briefing on today's easy run with its three buttons.
Then it starts its walk through the queue, and the learning question is the first item. She
is getting ready for work, so she taps "Not now" and then "In 1 day". On Thursday at 07:58
the question comes back as a reminder, just ahead of the push. She taps "Not really". The
learning drops to tentative, and the bot answers "Got it — I'll lean on that less." Every
`workout generate` and `workout adapt` from then on sees it at tentative.

A question she has not tapped stays in the queue, and each morning's walk sends it again,
like any queued question. Every answer settles the doubt.

When the schedule has run out and the push stays silent, the question waits with the rest
of the queue (DESIGN_athlete_queue.md §10).

### 3.4 When she would rather not be asked

A switch, `learning-questions`, decides whether the coach asks at all. It is on by default.

With it off, a run queues no question. It applies each pending proposal itself, the way the
staleness sweep applies its steps: a demotion lowers the learning one level, and a
retirement archives it. That is the step "Not really" would have taken. A question still
waiting when the switch goes off is stale (§5), so the next walk closes it without showing
it, and the next run applies its proposal. Turning the switch back on undoes nothing; the
next doubt is asked.

Take an athlete who finds these questions a chore. On Thursday morning she writes "stop
asking me about that stuff". The router sends it to the chat's settings change
(DESIGN_bot_simple_frontend.md §12.7), which reads it back as its effect: "I'll stop asking
about what I've learned about you, and go by what I see instead. OK?" She confirms. That
night's reflect run finds nothing new, but it still lowers the learning her waiting question
was about, and Friday's walk closes the question without showing it. Later, "you can ask me
again" reads back as "I'll ask you again before I lean less on something I've learned about
you. OK?"

The switch is on the list of settings she can change from chat, because it shapes her own
experience of the chat, like the morning push. The operator changes it with
`settings set learning-questions off`. On an expert instance off means the same thing:
reflect demotes on contradiction and queues nothing.

With the switch off, contradiction lowers a learning with nobody confirming, which the
confidence design ruled out (DESIGN_evidence_based_confidence.md §7). Here the athlete made
that choice herself, for every doubt at once.

## 4. What she sees

The question arrives as a message of its own after the briefing, so the briefing's buttons
stay live:

> 🙋 Quick question (1 left)
> Something I've been assuming about you — tell me if it still fits: “You bounce back fine
> from two hard days in a row.” But the last two times you had hard days back to back, you
> cut the second one short. If it doesn't fit any more, or you're not sure, I'll lean on
> it less.
>
> `[Still fits]` `[Not really]` `[🕐 Not now]`

The first line and "Not now" belong to the queue (DESIGN_athlete_queue.md §6.1, §6.4). The
two sentences in the middle are the coach's. `CoachService.learning_question(learning,
reasons)` makes one short call with the learning's text and sports and the reasons reflect
wrote for its contradicting weeks. It asks for two things:

- **The statement:** one second-person sentence saying what the learning claims about the
  athlete's experience. It is a *statement* rather than a question, so the frame around it
  fixes what the buttons mean: "Still fits" is always the learning holding, whatever wording
  the model chose.
- **What the coach saw:** one second-person sentence about her own recent sessions that went
  against the statement.

Both are in plain words, with no metrics, no zones and no name, in the prompt's language.
Both describe effects without naming substances, health conditions or private life. A
learning about drinking becomes "Some evenings out cost you the next morning". The question
travels as a phone notification, and its first lines can show on a lock screen.

**The reason.** Reflect's `contradict` op gains a `reason`: one line, written for the coach,
saying what in the cited weeks went against the observation. The app stores it with each
contradicting week the op files. `learning_question` reads the reasons of the learning's
contradicting weeks, and reflect's report prints the reason under the contradiction. A
contradiction that comes back without a reason still counts. Its question then says *"Lately
I'm less sure."* in place of what the coach saw.

The call is made when the question is queued, because a queued item is written complete and
later shown without calling anything (DESIGN_athlete_queue.md §3). It is made whatever the
persona, since `/ui` can switch the persona before the question is shown. It costs one short
call per queued question, on a run that has just made the long analysis call. Like the
morning push's own adaptation, a failure must not sink the run: it prints a terminal aside
and queues nothing for that learning, and the next reflect run tries again.

Everything around the two sentences is a fixed English string, like the rest of the
companion, with no id and no confidence tier (the companion prose rule of
DESIGN_bot_simple_frontend.md §5.5).

**The last sentence says what "Not really" does, and that it is also the answer when she is
not sure.** A demotion one rung down reads *"If it doesn't fit any more, or you're not sure,
I'll lean on it less."* A proposal on the retirement rung reads *"If it doesn't fit any more,
or you're not sure, I'll set it aside."*, which archives the learning (§6).

The answers are the CLI's:

- **Still fits** keeps the learning the way `learnings keep <id>` does: the athlete overrules
  the contradicting weeks, and `keep` deletes those evidence rows and re-derives confidence.
- **Not really** demotes it the way `learnings demote <id>` does. It is also the answer when
  she cannot tell: the coach only asks when what it saw goes against the learning, so going
  by what it saw means leaning on the learning less.
- **Not now** offers the queue's three choices: in 1 hour, in 1 day, after the others.

The question has no drop button (DESIGN_athlete_queue.md §4). A drop closes a question
without doing anything, which here would leave the learning at full strength with nobody
left to ask, the outcome this design exists to end. "Not now" already puts a question off,
and the switch of §3.4 stops the questions altogether. A typed reply instead of a tap goes to the free-text router like any other
message, which cannot reach these answers; nothing changes and the buttons stay.

What a tap prints back is a renderer method with a companion body, the way
`constraint_removed` is: *"Thanks — good to know, I'll keep that in mind."* for Still fits;
*"Got it — I'll lean on that less."* or *"Got it — I've set that idea aside."* for Not
really. A tap on a question whose proposal
was settled in the meantime, by the operator or by a reflect run that reinforced the
learning, gets the queue's "Already settled — thanks!" (§5). The expert bodies keep today's
text and the labeled learning lines.

## 5. The queued item

The item's kind is `learning`. Its subject is the learning's id and the time the question
was queued, so a later doubt about the same learning is a new subject. The payload holds the
learning's id, the step the proposal asks for (the target level or retirement), the coach's
two sentences, the learning's text, level and reasons for the expert wording, and the two
answers. The queue's row is the whole record of what was asked.

**One waiting question per learning.** Before it queues, the run looks for a question about
the same learning that is still waiting, hidden ones included, and runs that question's
check first. If one still waits, it queues nothing. Reflect runs every night from Wednesday
to Sunday, so without this rule each of those nights would add another copy of a question
she has put off.

Every answer settles the proposal. So a pending proposal with no question waiting has one of
two causes: its question was never queued because the sentence call failed, or its old
question went stale. Both need a new question, and the next run queues it.

**The check.** A question is stale when the questions are switched off (§3.4), when its
learning is gone, archived or dormant, or when the learning no longer has the proposal the
question was about: no proposal at all, or a different step. A dormant learning is out of every prompt already, so her answer would change
nothing. Two examples of the rest. The operator runs `learnings keep 4` on Wednesday evening;
Thursday's walk finds the question stale and closes it without showing it. Or a third
contradicting week turns a demotion to tentative into a retirement. The waiting question
promised "I'll lean on it less", which is no longer what "Not really" would do, so the run
that filed the third week closes it and queues a new question with the retirement's last
sentence.

## 6. What a slip costs

Some of this erases something today. "Not really" on the retirement rung
runs `demote_learning`, which `DELETE`s the learning and its evidence. The staleness sweep's
bottom rung, the `retire` delta op and `learnings rm` delete the same way. Those become
archives, following what `goal rm` already does (a `status` column, `--purge` for the real
delete).

Every other answer mends itself with training, the way a human coach leans on something
less, sees it hold up, and leans on it more again. Take a learning at moderate with three
supporting and two contradicting weeks, and a slip each way.

- She means "Still fits" but taps "Not really". The learning drops to tentative. Its
  evidence is untouched, so two more supporting weeks bring it back to moderate without
  anyone asking.
- She means "Not really" but taps "Still fits". The two contradicting weeks are deleted, as
  `learnings keep` deletes them today, and the learning stays at moderate. The next two weeks
  that go against it raise the doubt again, and the question comes back.

A slip costs a few weeks of the coach leaning slightly the wrong way on one line of its
prompt. That is how the answers meet the reversibility DESIGN_bot_simple_frontend.md §7 and
DESIGN_athlete_queue.md §9 ask of a tap, without a confirm step that would make her surest
answer two taps. The archive covers the one answer that would otherwise lose a learning and
its history.

- `coach_learnings` gains `status TEXT DEFAULT 'active'` (`'active' | 'archived'`), a
  one-line migration beside the phase-2 ones.
- `get_learnings()` keeps returning every row, and marks each with an `archived` flag beside
  the `dormant` flag it already computes. Whatever leaves dormant learnings out leaves
  archived ones out the same way: the prompt builder, the web app's listing and the counts
  in `status`. `learnings list` hides archived learnings unless given `-a/--all`, like
  `constraint list`. Every `learnings` command that looks a learning up by id still finds an
  archived one, so `learnings show 4` shows what `learnings restore 4` would bring back.
- Two of the database's direct reads of the table skip archived rows: the staleness sweep,
  and the check that a delta names a real learning. A delta addressed to an archived
  learning is skipped like one addressed to a missing id.
- Every path that retires a learning archives it instead: `demote_learning` on the
  `retire` target, the `retire` delta op, the staleness sweep's bottom rung, and
  `learnings rm`. `learnings rm --purge` is the hard delete, with the evidence cascade.
- `learnings restore <id>` puts an archived learning back at tentative with its evidence.

Reversible by the operator is what the guardrail means for the archive (a companion
`constraint rm` is undone the same way), so the companion gets no undo button.

## 7. Guardrails

The queue's guardrail covers the taps (DESIGN_athlete_queue.md §9). A tap runs the hidden
`bot queue <item> <action>`, which can only run one of the two answers the question was
queued with, on that learning, after the question passes its check (§5). `learnings keep`
and `learnings demote` stay typed commands: no button sends them, nothing routes to them
from free text, and the router's intent table does not grow. The model writes the two
sentences in the middle of the question and nothing else. Which learning is asked, what the
answers do and the words around the sentences come from database rows and fixed strings.
With §6, no answer loses anything for good, so the guardrail holds without a confirm step.

## 8. Expert mode

There is no push in expert mode, and the question is queued all the same. The operator
meets it in the queue hint that `status` and `workout adapt` print while something waits,
and at the end of the reflect or bootstrap run that queued it, which prints the same
two-line hint where the end-of-run prompt used to be. `tm queue answer` goes through it at a
terminal, and the expert chat types `queue answer`.

The expert wording is the learning as the coach stores it, with the step the proposal asks
for, the reasons reflect gave, and what each answer does:

```
Recent weeks contradict learning #4: moderate → tentative.
[4|cycling|moderate] Responds well to back-to-back hard days.
Week of 2026-09-07: HRV fell after both doubles and the second session was cut short.
Still fits keeps it and overrules those weeks. Not really demotes it.
```

The first line is what `tm queue` lists. A retirement's first line ends in "→ retire", and
its last line says not really archives it. `learnings list` keeps its `⚠` line, and
`learnings keep` and `learnings demote` still settle a proposal by hand; the waiting
question then closes as stale.

## 9. Deliberately not done

- **Auto-accepting old proposals.** A question she keeps putting off could apply itself after
  N days. The confidence design ruled that out for contradiction demotions. Here she settles
  a question with one tap, and the switch of §3.4 is her standing choice to let the coach
  decide.
- **Letting the model decide not to ask.** A learning she cannot judge by feel is still
  asked, with what the coach saw, and "Not really" is the answer when that is not enough.
  The model never chooses whether a question is queued (DESIGN_athlete_queue.md §9).
- **Telling her the switch exists.** Nothing in the question mentions it; the operator tells
  her, as with the morning time.
- **An undo button.** A slip mends itself with training, and a retirement is restored from
  the archive (§6).
- **Showing the numbers.** The CLI's `learnings show` lists the weeks for and against.
  The companion asks about her experience instead; the weeks would be dates she cannot
  act on. If a "why do you think so?" is ever wanted, it is a `bot` view like `bot mesocycle`,
  not more text in the question.
- **Keeping the end-of-run prompt for runs someone watches.** On the operator's own instance
  it would save typing `queue answer`. On a companion instance it asks the operator about
  her, and on either it would leave two ways to settle the same doubt.
- **Staleness proposals from before this change.** Neither instance holds one, so nothing
  converts them.

## 10. Touch points

- `trainmate_bot.py`: `scheduler_wake` starts `data reflect --auto` once a day after 03:00,
  from Wednesday to Sunday, in companion mode, as a process outside the chat whose output
  goes to the journal.
- `trainmate/settings.py`: the `learning-questions` switch, on by default.
  `trainmate/cli/settings.py`: it joins `ROUTABLE_SETTINGS`. `trainmate/cli/bot.py`: its line
  in `SETTING_DESCRIPTIONS`, its two sentences in `_setting_effect`, and the router's
  description of `change_setting`, so "stop asking me about that stuff" reaches it.
- `trainmate/learning_doubts.py` (new): the `learning` kind (expert and companion wording,
  the check of §5, the two answers, no drop), registered in `athlete_queue.KINDS`; and the
  queuing of §5, which skips a learning with a question still waiting or a dormant learning,
  and asks the coach for the sentences of each new question.
- `trainmate/athlete_queue.py` and `trainmate/cli/queue.py`: a question kind without a drop
  label offers no drop, in `queue_buttons` and `terminal_choices`, and `act` refuses a drop
  on it.
- `trainmate/coach/service/`: `learning_question(learning, reasons)` and its prompt (the
  statement and what the coach saw, plain and discreet; the call is
  `CoachEngine._learning_question_logic`). In `prompt.py`, `_review_learning_proposals` runs
  the staleness sweep in its applying form on every run, loses its prompt, and queues the
  questions (or, with the switch off, applies the proposals).
- `trainmate/coach/engine/__init__.py`: `reason` on the `contradict` op in
  `LEARNING_UPDATES_FIELD`.
- `trainmate/db/learnings.py` and `db/schema.py`: the `status` column on `coach_learnings` and
  a `reason` column on `learning_evidence`, with their migrations; `apply_learning_deltas`
  storing a contradiction's reason; the `archived` flag in `get_learnings`; archive in place
  of the four deletes; `restore_learning`; the staleness sweep without its proposing branch;
  `keep_learning` without its staleness branch; archived rows skipped by the sweep and by
  `_exists`.
- `trainmate/cli/learnings.py`: `rm --purge`, `restore`, `list -a/--all`, `show` finding an
  archived learning and printing the reasons, keep/demote printing through the renderer.
- `trainmate/cli/data/analysis.py`: the reason under a contradiction in the reflect report, and the
  queue hint at the end of `data reflect` and `data bootstrap`.
- `trainmate/cli/status.py` and `trainmate_web.py`: archived learnings left out.
- `trainmate/cli/render/`: renderer methods for the two answers' replies, one rung down or
  on the retirement rung, with expert and companion bodies. The question's own companion
  wording lives with the kind in `learning_doubts.py`, as the strength kinds' does.
- Tests (`tests/test_bot.py`, `tests/test_athlete_queue.py`, `tests/test_learnings*.py`, a
  new `tests/test_learning_doubts.py`): the scheduler starting reflect once a day after 03:00
  from Wednesday to Sunday in companion mode only, without making the chat busy, and not on
  Monday or Tuesday; reflect queuing one question per pending proposal with and without
  `--auto`, and prompting for nothing; staleness steps applied on a run without `--auto`; no
  second question while one waits, hidden or not, and none for a dormant learning; the check
  closing a question kept by hand, retired, archived, gone dormant, or whose step changed; a
  failed sentence call queuing nothing and the next run queuing it; a contradiction's reason
  stored and passed on, and the fallback sentence without one; a question kind without a drop
  showing no drop and refusing one; each answer's effect and reply on both rungs; the switch
  off queuing nothing, applying pending proposals on a run that read nothing new, and closing
  a waiting question as stale; the chat's settings change reading the switch back as its
  effect;
  archive-and-restore for each retire path; `learnings show` finding an archived learning.
- Docs: DESIGN_evidence_based_confidence.md §6 (the contradiction's reason) and §7 (AS BUILT
  rev 3: every run applies staleness steps; pending proposals go to the athlete queue
  instead of an end-of-run prompt, or apply directly with the questions switched off;
  retirement archives); DESIGN_settings.md §1 (the switch joins the listing);
  DESIGN_bot_simple_frontend.md §12.7 (the chat's allowlist grows); DESIGN_athlete_queue.md §4, §6.4 and
  §8 (a question kind may have no drop, when every answer settles it) and §5.2 (reflect and
  bootstrap print the hint); DESIGN_bot_simple_frontend.md §4.3 (the scheduler runs reflect
  at night from Wednesday to Sunday in companion mode); ARCHITECTURE.md §3 propose/confirm
  paragraph; README's learnings bullet.
