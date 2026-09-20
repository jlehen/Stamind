# Executing the code reorganization

Status: method, 2026-09-20. Companion to `REORG_code_layout.md`.

That file says **what** moves and where it lands. This file says **how the work is cut into
commits, how each one is checked, and what has landed so far**. Neither file replaces the other.

---

## 1. How to use this file

A session that picks up this work reads four things, in this order:

1. `AGENTS.md` — style, git policy, how to run the tests.
2. This file — the method and the ledger.
3. `REORG_code_layout.md` — the section covering the item it is about to do.
4. `docs/ARCHITECTURE.md` — the code structure as it stands.

Then it reads §8 below, the ledger, to see what has already landed. Then it takes the next
unfinished phase from §7, the order of work.

**One session does one phase, and lands it as one commit** (§3). It does the phase's items in
order, running the suite after each so it knows which item broke what, and squashes them into the
phase commit at the end. It does not start the next phase. When the commit is green and the ledger
line is written, the session is over.

Phase D is the exception: there a session does one file split, because that phase is 25 unrelated
splits and one commit each is what makes a red suite bisectable.

### Both REORG files are temporary, and they are tracked anyway

They are committed from the start and **deleted in the last commit of the branch**. Tracked,
because the ledger is how one session hands off to the next: left untracked it would die with the
worktree, and it would be at risk in the rebase onto main. Deleted at the end, because a
transition plan has no reason to outlive the transition.

The branch lands with `--no-ff`, so both files live inside the merge node's history and are gone
at its tip. Someone reading main never sees them. Someone bisecting into the reorg does, which is
exactly when a ledger earns its keep.

**What must survive moves out before the end, not at it.** Three destinations, and one of them is
not a document:

| What | Where it goes | When | State |
|---|---|---|---|
| The size rule, and the files exempt from it (`REORG_code_layout.md` §2) | `AGENTS.md`, under Code style | Phase A | done |
| The engine's call-time client lookup; no blanket re-export from a package `__init__` | `AGENTS.md`, under Code style | Phase A | done |
| The four known test failures, and what green means | `AGENTS.md`, under Test | Phase A | done |
| The layering rules — who may load whom | `tests/test_layering.py`, and `ARCHITECTURE.md` §14 | Phase C | done |
| The new layout, package by package | `ARCHITECTURE.md` §2, Module Map | Each phase | ongoing |
| Why the coach is engine/service, and why there is no `queue/` package (§4.11) | `ARCHITECTURE.md` §15, Design Rationale & History | Phase A | done |
| Why the package is `gcal/` and not `calendar/` (§4.11) | `ARCHITECTURE.md` §15 | Phase D item 2 | with the package |

The conventions go to `AGENTS.md` **in phase A, before any file is split.** A rule written down
after the work is documentation. The same rule written down before it is a constraint the work has
to satisfy — and a session picks up `AGENTS.md` on its own, without being told to read a section
of a transition plan.

`ARCHITECTURE.md` §15 already collects decisions in this shape: a short entry saying what was done,
what was rejected, and why. Two of §4.11's rejected alternatives were true of the code already and
went there in Phase A: why the coach splits into engine and service rather than by domain, and why
the athlete queue does not become a package. The `gcal/` naming waits for the package to exist,
because §15 describes what is. "No re-export shims" did not need an entry: `AGENTS.md` already says
every instance is operated by the author, so a migration is one-off.

Everything else in these two files is about the act of moving. It dies with a plain `git rm`.

---

## 2. Ground truth, measured 2026-09-20

**The test suite.** 1985 tests after Phase A, 100 seconds, run like this:

```
systemd-run --user --scope -q -p MemoryMax=1G -p MemorySwapMax=0 \
    venv/bin/python -m unittest discover -s tests -p "test_*.py"
```

**Four failures are the baseline, not a regression.** They come from the live `config.yaml`
being in companion mode. They are:

- In `test_cli_bot.MorningPushTest`: `test_adapt_first_off_never_touches_the_coach`.
- In `test_cli_settings.TestMorningPushKnobs`: `test_a_non_switch_is_refused`,
  `test_the_built_in_defaults_apply_with_nothing_configured` and
  `test_the_morning_command_adapts_only_when_the_switch_is_on`.

A commit is green when the suite fails those four and nothing else. Any fifth failure is yours.

**Do not run a single test file to decide whether you are done.** Some modules never bind a
test database of their own and rely on an earlier module in the full run having bound one, so
alone they fail with "tests must not open the production database". `test_dispatch` is the
example; `test_isolation_guards` was too until Phase A gave it its own. Use a per-file run while
iterating, and the full suite before committing. AGENTS.md carries this rule now.

**The line numbers in `REORG_code_layout.md` are stale.** They were taken from main at `da9ec8f`.
Since then `cli/plans.py` went from 1451 to 1493 lines, `coach/service/adaptation.py` from 830 to
815, and `db/base.py` from 919 to 635. Locate the code you are moving by its **symbol name**, not
by the line range the proposal quotes. Treat every line number there as a hint about roughly where
to look.

---

## 3. The commit rule

**One commit is one phase.** The owner decided this on 2026-09-20, after Phase A came back as
nine commits. A phase is the unit they want to read in one sitting, and nine subject lines in the
log for one afternoon of preparation is noise rather than history. Phase A was squashed into one
commit before the branch moved on.

**The phase commit's message carries what the small commits used to carry.** One paragraph per
kind of change inside the phase, in the order it was made, each saying what it did and why. A
reader asking "did behaviour change here?" reads the paragraph headings; a reader who wants the
mechanics reads the diff.

**A phase commit still must not carry an undesigned behaviour change.** A fix a split needs before
it will work goes in, with its test and its own paragraph. A change nobody asked for does not,
whatever else is in the commit — §7's Phase B is where `§5.2` left this branch for exactly that
reason.

**Phase D is the exception,** and the proposal already granted it: it is 25 unrelated file splits,
so a phase commit there means bisecting inside a commit by hand when the suite goes red. Phase D
stays one commit per file split (§7).

**Message format** is the one in `AGENTS.md`: `<file>: one line under 80-100 characters`, then a
blank line, then the longer description wrapped the same way. The `<file>` prefix is the basename,
and it is present only when the change mostly touches a single file. A phase commit that touches
twenty files takes no prefix; name the phase instead.

**`docs/ARCHITECTURE.md` is updated in the same commit as the code it describes.** Implemented
`DESIGN_*.md` files get their paths amended in that same commit. Designs still in progress are left
alone; their paths go stale until they are implemented, and that is accepted.

**Landing the branch.** With one commit per phase and Phase D's 25 splits, this reorg runs to
roughly thirty commits. That is far past the bar in `AGENTS.md` for earning a node in the graph,
so it lands with `--no-ff` after a rebase onto main.
A reorg is exactly the branch you want to be able to bisect later.

---

## 4. Why a green suite is not enough

It is a Tuesday. A session splits `cli/workouts/generate.py` into five files and moves
`workout adapt` into a new `adapt.py`. It runs the suite. Everything passes. It commits.

What actually happened: `tests/test_cli_workouts.py` patches
`trainmate.cli.workouts.generate.ensure_recent_data` so that the test does not hit Garmin for real.
After the split, `generate.py` still imports that name, so the patch still resolves and still
succeeds. But `workout adapt` now lives in `adapt.py` and reads its own copy. The patch reaches
nothing. The adapt tests pass while doing a real data pull.

This is not hypothetical. It is already true in the repo today, in a smaller way:
`tests/test_workout_generate_window.py` patches `trainmate.util.notice`, and
`coach/service/workouts.py` imported `notice` by value, so that patch has never reached anything.
The test passes. It has been passing while asserting nothing.

So the suite catches breakage, but it does not catch a seam going quiet. Section 5 closes that gap
before any file moves.

---

## 5. The gate: two tests, written before anything moves

### 5.1 Every patch target still resolves

There are 417 `patch("trainmate…")` calls in `tests/`, but only **39 distinct targets**. They are
concentrated:

| Target | Calls |
|---|---|
| `trainmate.coach.engine.openrouter_client` | 132 |
| `trainmate.runtime.calendar_syncer` | 61 |
| `trainmate.runtime.garmin` | 48 |
| `trainmate.runtime.coach_service` | 45 |
| `trainmate.cli.workouts.generate.ensure_recent_data` | 23 |
| `trainmate.runtime.prompt` | 18 |
| the other 33 targets | 90 |

So one test can cover every seam at once. It walks `tests/` with `ast`, collects every string
literal passed to `patch()` that starts with `trainmate`, imports the module half and asserts the
attribute half exists. When a move orphans a seam, it fails and names the target.

**Its home is `tests/test_isolation_guards.py`.** That file already exists for exactly this — its
docstring says it is for "seams that fail silently … a guard that stopped working would be
invisible, so it is asserted here rather than trusted". It already parses source with `ast` and
`glob`.

**It must read a target a loop builds, not only a literal one.** Four sites write the target as a
loop variable or an f-string: `test_athlete_queue.py` loops over three module paths, and
`test_change_heads_up.py` loops over two attribute names and interpolates them into
`f"trainmate.cli.workouts.generate.{target}"`. A first cut collected only `ast.Constant` first
arguments and skipped all four — including three that name
`cli/workouts/generate.ensure_recent_data`, the seam §9 calls the worst case, and the one Phase D
is about to move. The collector now reads a `for` over a literal tuple of strings and an f-string
built from one. Resolved: 431 sites, 40 distinct targets at the time; Phase C's moves
took it to 439 and 42.

**Asking `trainmate.runtime` for an attribute builds the singleton.** `runtime.__getattr__`
constructs a Database against the athlete's own file, or a live Google client off the credentials,
and caches it for the process. Six of the 40 targets are `trainmate.runtime.<name>`, so the test
asks the builder registry instead of reading the attribute. It then needs no fixture of its own
and leaves nothing behind. A first cut bound a test database in `setUp`, which quietly built a
real `CalendarSyncer` for the `calendar_syncer` target — undoing §4.6 for the one test that names
it. The review caught that.

**The file imports the `tests` package itself.** `unittest discover -s tests` imports the modules
under `tests/` without importing the package, and the package `__init__` is what installs the
guards this file asserts on. Every other module gets it through `from tests import test_db_path`;
this one has no database to name, so it says `import tests` outright. Without it, a per-file run
of this module tests guards that were never installed, and three of its assertions fail.

**A second check, in the same test, if it is not too noisy.** For each target `M.attr`, look for a
production module that does `from M import attr`. That module holds the name by value, so patching
`M.attr` will not reach it. This is the `util.notice` case above. Try it; it should flag
`util.notice` on the first run, which is a real bug that wants fixing anyway. If it turns out to
produce a pile of false positives, drop this half and keep the resolution check. Do not build an
allowlist of exceptions for it — that is the hand-maintained list `AGENTS.md` warns against.

**Tried in Phase A, and dropped.** It found the bug it was expected to find: the four
`patch("trainmate.util.notice")` calls in `test_workout_generate_window.py` reached nothing,
because `coach/service/workouts.py` imports `notice` by value at module scope, so the three
conflict notices printed in every full run. Those four patches now name
`trainmate.coach.service.workouts.notice`.

With that fixed, every remaining flag was a false positive, and each needed a different excuse:
`trainmate_cli` imports `run_plan_generate` and never reads it; `garmin/__init__.py` re-exports
`_sync_calendar_signals` and nothing calls the re-export; `trainmate_bot` binds
`clock.now as athlete_now` on purpose, and `test_bot.py` patches that binding directly while
`test_clock.py` asserts on it. Three false positives out of three is the "pile" the paragraph
above names, and suppressing them needs exactly the hand-maintained allowlist it forbids. So the
gate is the resolution check alone.

### 5.2 The layers still hold

A new `tests/test_layering.py` asserts which layer may load which, by importing a module in a
subprocess and reading `sys.modules`. `tests/test_runtime.py` already does this shape of check for
sqlite, so copy its mechanics.

Two assertions:

- Importing `trainmate_web` loads no `trainmate.cli`, no `trainmate.coach.service`, no
  `trainmate.openrouter` and no `googleapiclient`. This is `REORG_code_layout.md` §4.3.
- Importing anything in `trainmate/analytics/` loads no `trainmate.db`. This is §4.1.

Both are keyed on module-name prefixes, never on a list of files.

The second assertion cannot be written until `analytics/` exists, so the layering test arrives in
two steps: the web half in the gate, the analytics half in the commit that creates `analytics/`.

**Revised in Phase A: neither half lands in the gate.** Both assertions are false today, and a
commit has to be green. Importing `trainmate_web` in a fresh interpreter loads 33 modules under
those four prefixes right now, which is the problem §4.3 exists to fix. Writing the assertion
early buys nothing the assertion written later does not: it is the acceptance test for §4.3, not a
guard against something regressing during the reorg. The guard against regression is §5.1, and
that is what the gate is.

So `tests/test_layering.py` is created in Phase C item 4, the commit that makes the web half true,
together with deleting the grep test below. It gains the analytics half in Phase C item 1. The
prose about the layering rules in `ARCHITECTURE.md` §14 goes with them, for the same reason:
ARCHITECTURE describes what is.

**Both halves landed in Phase C, and both are true.** The web half turned out to be most of the
way there already: Phase A's `coach/__init__.py` change and the Calendar client moving into
`runtime` had cut the 33 leaked modules down to four, all under `trainmate.cli`, all reached
through the one `modification_markers` import §4.3 names. Item 3 removed one of them as a side
effect and item 4 removed the rest.

When the web half lands, the grep-based `test_no_google_or_llm_import_at_module_scope` in
`tests/test_web.py` is deleted in the same commit. It only reads the text of one file, so it
already passes while the real import happens one module deeper.

### 5.3 What the gate buys

These two tests are what make it safe to hand a commit to an agent, or to a fresh session that has
none of this conversation in its context. Without them, "the suite is green" is a claim about
breakage only, and someone has to review every patch seam by hand on every commit. With them, a
seam going quiet is a red test that names the offender.

They are worth roughly one session. Everything after depends on them.

---

## 6. Agents: what they do and what they must not do

### 6.1 Never run two executing agents at once

Nearly every item in the proposal rewrites the import block at the top of many caller files. The
`util.py` split alone edits about 80 files, and 61 files import `util` today. Two agents working in
two worktrees will both edit the top of `cli/status.py`, on the same lines, and you will spend more
time on the merge than the work saved.

The executing line is **sequential**, in the dependency order of §7. One agent, or one session, at
a time.

### 6.2 Surveying fans out, because it is read-only

Before a split, a surveyor agent reads the current code and produces a short spec:

- the real symbol list for each new file, since the proposal's line numbers are stale (§2);
- every production caller of each symbol that moves;
- every test that names the file, the module path, or a symbol in it;
- every `patch()` target that points into the file being split.

Several surveyors can run at once, because they read different subsystems and write nothing. This
is how `REORG_code_layout.md` itself was made, so the approach is known to work here.

The surveyor's output goes to the executor. It does not go into the proposal document.

### 6.3 Executing agents work one phase at a time

The feedback loop is 99 seconds, which is short enough that an agent can iterate on its own. A good
executor prompt is narrow and contains:

- the one phase to produce, named from §7, and its items in order;
- the surveyor's symbol list from §6.2;
- the relevant sections of `REORG_code_layout.md`, quoted or pointed to;
- the traps from §9 that apply to those items;
- the baseline from §2 — four known failures, and the exact command;
- the instruction to run the suite after each item, squash the phase into one commit, write its
  ledger line, and stop.

A prompt that says "do the whole reorg" is the wrong size. So is one that says "do Phase A item 3":
the owner reads a phase at a time, and a session handing back a third of one leaves the next
session working out where it stopped.

**What makes this safe is §5, not the agent's report.** An agent will report a green suite in good
faith while having silenced a patch seam. The gate tests turn that from a judgement call into a red
test.

---

## 7. The order of work

This revises §8 of `REORG_code_layout.md` in two places, both noted below.

### Phase A — the gate, the conventions, and the cleanups — **DONE**

1. The patch-target test (§5.1). The layering test moved out of the gate; §5.2 says why.
2. The durable conventions moved to `AGENTS.md` and `ARCHITECTURE.md`, per the table in §1. They
   come before any split, because these are the rules the splits follow.
3. The deletions in `REORG_code_layout.md` §7: dead code, unused imports, stale docstrings. Two of
   that list's claims were wrong and the list now says so. The function-local imports it also
   names were left alone: §7 itself says a move in §4 removes the reason for most of them, so
   hoisting them now would be work done twice.
4. `coach/__init__.py` became a docstring (§4.5), and the copy of the science banner it was
   forcing on `strength/planner.py` went with it.
5. `runtime` builds the Calendar client instead of the import building it (§4.6). `AGENTS.md`'s
   worktree note now says `service_account.json` is needed by two test modules, not by collection.

Low risk, and it makes every later diff smaller.

### Phase B — the behaviour fixes

Already done, except one item that leaves this branch.

- §5.1 and §5.4 landed. See the ledger.
- §5.3 is retracted; it is a designed difference, not a duplicated rule.
- **§5.2 leaves this branch.** It is superseded by wanting e1RM dropped from the benchmark anchors
  entirely, and `DESIGN_strength_tracking.md` deliberately kept it. That makes it an undesigned
  behaviour change. Putting it here would break the §3 commit rule one level up, at the branch. It
  needs its own design and its own branch. Not part of this work.

### Phase C — the moves between subsystems — **DONE**

1. The load model and the fitness/fatigue maths leave `garmin/`, creating `analytics/` (§4.1).
   The analytics half of the layering test lands here (§5.2).
2. **`util.py` is split and deleted (§4.7).** *This is the second revision: the proposal put it
   last, at its phase 5.* It moves here, for two reasons. It cannot go earlier, because §4.7 sends
   the fitness/fatigue colours to `analytics/pmc.py`, which the step above creates. And it should
   not go later, because 17 of the 21 files that get split in phase D import `util` today. Split
   `util` last and you cut `cli/render.py` into four files, each born with a
   `from trainmate.util import …` line, and then a codemod rewrites all four. Split it here and
   every later file is born with the right import. The proposal's stated reason for going last was
   to keep the codemod's diff pure — but that diff is pure either way, since the number of files
   does not change what kind of edit it is.
   This commit also changes the `wrap_text` line in `AGENTS.md`, which names `trainmate/util.py`.
3. One home for "which activity was which session" (§4.2).
4. `workout_state.py`, and the web app stops importing the CLI (§4.3).
5. `plan_inputs.py` and the staleness mixin (§4.4).
6. `sentinels.py`, the line protocol between the CLI and the bot (§4.8).
7. Printing leaves the coach service (§4.9), then the smaller moves (§4.10).

After this phase the web app loads no CLI, no coach and no Google code, and the layering test says
so.

**What did not land, and why.** Three rows of §4.10 wait for the package that receives
them: `CoachContext` → `service/athlete_context.py` (row c), `ROUTABLE_SETTINGS` →
`cli/bot/capture.py` (row g), and the router intent table → `chat/routing.py` (row p).

Row f — the four plan print helpers → `cli/common.py` — waits for a different reason:
`cli/common.py` exists today, so the destination is not the obstacle. Its stated
justification is that `plan show` and `plan diff` share them, and both of those are in
`cli/plans.py`, so there is no cross-file caller to serve. Phase D item 8 cuts that file
into a package and the helpers find their home then; moving them now would be work done
twice.

Row h — `warn_stale_before` → `cli/workouts/calendar_sync.py` — did land. It was missing
from the first pass and the review caught it.

**`cli/plans.py` got bigger, from 1493 lines to 1501.** It received the plan-preview
printing §4.9 took out of the coach service, because it is the file that drives
`plan generate` and the only other candidate — `cli/common.py` — would have held it
for no caller. The file is already named in `AGENTS.md` as debt, and Phase D item 8
cuts it into a package; the preview lands in `cli/plans/generate.py` there.

Three more were declined outright, and §8 records why. Two of them are the same
shape — a guarantee a write always makes, which the proposal wanted moved out to the
caller — and that reasoning is now in `ARCHITECTURE.md` §15, because it will come up
again.

### Phase D — the file splits

*This is the first revision: the proposal said one commit per subsystem. **One commit per file
split** instead.* `coach/service` alone is five separate splits; putting them in one commit means
that when the suite goes red you are bisecting inside a commit, by hand.

That gives roughly 25 commits. Take the subsystems in this order, lowest in the import graph first:

1. **analytics** — `intensity.py` into three; `progression.py` with `timeline.py` into three;
   `plan_diff.py` with `plan_lineage.py` into `plan_versions.py`. **DONE**, as one commit
   rather than three: the owner asked for one commit per phase on the day it was done, and
   the three splits are one subsystem. The rest of Phase D keeps the one-commit-per-split
   rule unless the owner says otherwise.
2. **integrations** — the `gcal/` package, and three merged duplicates rather than the two
   named here. The `garmin/` tidy-up turned out to be already done. **DONE**, as one commit:
   `event.py` and `client.py` are two halves of one file and land together.
3. **database** — `workouts.py` into three; `base.py` into two; `periodization.py` into two;
   the small mergers. **DONE**, as one commit: the three splits and the mergers all land in
   `db/`, and three of the item's bullets turned out to be work earlier phases had already
   done.
4. **strength** — `planner.py` into two. **DONE**, as one commit: the prompt and the
   pass are two halves of one file and the second cannot be read without the first.
5. **coach/engine** — `workouts.py` into four. **DONE**, as one commit: the four are
   one file's four jobs, and two of them exist only to be imported by the other two.
6. **coach/service** — `workouts.py`, `adaptation.py`, `planning.py`, `context.py`, one commit
   each.
7. **CLI command families** — `workouts/generate.py` into five; `data.py` and `journal.py` into
   packages.
8. **CLI views** — `plans.py`, `progress.py`, `selectors.py`, then `render.py`. Render goes
   last, because it imports from all of them.
   `selectors.py` is on this list because Phase C put it there: it took the three goal
   helpers from `cli/plans.py` and went 475 → 524 lines. It holds two jobs that change for
   different reasons — the `A..B` grammar, which parses text and touches no database, and
   the resolvers, which turn a parsed range into a window by reading one. Cut it there.
9. **front-ends** — `cli/bot.py` into a package; `trainmate_bot.py` into `trainmate/chat/`, moves
   only.

**Test files follow the code, in the same commit as the split they follow.** The 500-line rule
applies to them too, at lower priority.

### Phase E — optional, and each one is its own decision

- The bot's `main()` becomes a `ChatBot` class. Decided for this branch, as its own commit after
  the moves-only step (`REORG_code_layout.md` §0).
- `static/app.js` cut into four scripts by tab.
- Splitting the largest test files on size alone.

### The last commit

`git rm REORG_code_layout.md REORG_execution.md`, and nothing else. Everything durable left these
files in phase A or in the commit that made it true, so this commit is two deletions and is
reviewable at a glance. If it wants to carry anything besides the deletions, something was missed
earlier — put it where it belongs and keep this commit empty of content.

---

## 8. Ledger

One line per phase, newest at the bottom. A session adds its line **in the same commit as the
work**, naming the commit subject. The SHA is one `git log --grep` away, so no backfill is needed.
The lines above Phase A are one per item, from before §3 changed.

**Landed on this branch**

- **§6.3, the schema squash** — every one-off migration folded into the CREATE statements. Both
  databases were already at SCHEMA_VERSION 18. `db/base.py` went 919 → 635 lines. Seven migration
  tests went with it. `1cdfc44 base.py: fold every one-off migration into the CREATE statements`
- **§5.4, the two cycling sports** — the 15-day summary groups by canonical sport, so the week
  planner no longer reads road and indoor cycling as two sports.
  `a45d117 context.py: count the 15-day summary's sports canonically`
- **Docs** — ARCHITECTURE says the schema is CREATE-only.
  `3bea963 ARCHITECTURE.md: say the schema is CREATE-only now`
- **The proposal** — `adca8bc REORG_code_layout.md: the code-reorganization proposal`
- **§5.1, part one** — a proposed revision carries the intensity target, which both
  `workout adapt` and `workout tweak` were asking for, receiving and then dropping.
  `a2bc22e revisions.py: carry the intensity target on a proposed revision`
- **§5.1, part two** — adapt asks `prescription_matches` instead of its own five-field check.
  `9e12348 adaptation.py: adapt asks the shared no-op rule, not its own`
- **Docs** — §5.3 retracted, §0 records the decisions.
  `8876a74 REORG_code_layout.md: retract §5.3, record what is done`
- **The method** — this file. The commit rule, the session contract, the agent boundaries, the
  gate, the ledger, and two revisions to the proposal's order of work.
  `REORG_execution.md: how the reorganization is cut into commits`
- **Phase A, all five items.** The gate resolves 431 patch sites naming 40 distinct targets, and
  caught one dead patch on the way in. The conventions are in `AGENTS.md` and `ARCHITECTURE.md`.
  Seven dead symbols are gone, and so are the imports nothing read: 71 in `trainmate_cli.py`, the
  eleven `cli/workouts/__init__.py` re-exported for it, six more across four production files, and
  the ten `import trainmate.coach` lines the coach change left dead in the tests. Five stale
  docstrings point at `runtime` instead of `trainmate_cli`.
  `coach/__init__.py` is a docstring, so `from trainmate.coach import honoring` costs 59 modules
  instead of 506, and the science banner the cycle was forcing `strength/planner.py` to copy is
  one function again. Nothing builds a `CalendarSyncer` at import, so a checkout with no
  credentials file runs 1944 of the 1985 tests. Two revisions to the method: the layering test
  moves to Phase C (§5.2), and the by-value half of the gate is dropped (§5.1).
  `Phase A: the gate, the conventions, and the cleanups`
- **The review of Phase A**, in the same commit. A read-only agent re-derived every number and
  swept every deleted symbol. It found two things the suite could not: `scripts/` is not on the
  suite's path, so `scripts/run_integration.py` was left importing the `calendar_syncer` §4.6
  deleted; and `test_workout_revisions.py` had come to depend on another module having imported
  `coach.service` first, which is the shape of bug this branch exists to remove. It also found
  three gaps in the gate itself — see §5.1 — and six doc claims that were wrong or stale.
  **Run the suite per-file as well as whole after a phase that moves imports.** The full run hid
  both of the above.

- **Phase C, all seven items.** `trainmate/analytics/` now holds the training maths:
  `load.py` (the load model plus `planned_load`, which `adherence.py` had), `pmc.py` (the
  fitness/fatigue series plus the bands that colour it), `compare.py` (one
  `adherence_window` where three surfaces each had their own pairing) and
  `weekly_evidence.py` (six pure statics off the coach service). `garmin/` is down to
  `client`, `sync` and `derived`, and one `warmup_cutoff(dbh)` replaces five hand copies.
  `util.py` is gone: `text.py` for how a line looks, `output.py` for which tier it is,
  and `clock.py` grown to own the day as well as the zone — one `parse_date`/`date_range`/
  `shift` for seven copies, one `capitalized` for five. The codemod touched 80 files.
  `calendar_state.py` is `workout_state.py` and carries `modification_markers`, so
  importing `trainmate_web` now loads no CLI, no coach, no OpenRouter and no Google code
  at all. Plan staleness is three files with one role each: `plan_inputs.py` says what
  the inputs are, `coach/service/staleness.py` judges them (one `plan_fingerprints()` for
  three hand-built copies, five forwarding wrappers deleted, ~40 test references
  repointed), and `cli/staleness.py` is 126 lines of wording. `sentinels.py` holds both
  ends of the CLI↔bot line protocol: one `parse_frame` for four byte-identical readers,
  one `prompt_answer` for six hand-built dicts. The plan preview prints from the CLI
  through the renderer, as `workout generate`'s already did. Of §4.10: six copies of the
  anchor label became `benchmarks.label_for_kind`, three copies of the strength proposal
  fields became `planner.proposal_fields`, the learning confidence model left `db/` for
  `learning_confidence.py`, and `config.py` imports no app module any more.
  `tests/test_layering.py` is new and holds both rules; `test_utils.py` split into
  `test_text.py` and `test_output.py`; `test_load.py`, `test_sentinels.py` and
  `test_learning_confidence.py` followed the code they test.
  `Phase C: the moves between subsystems`
- **Three declines, recorded rather than silently skipped.** §4.1 wanted `db/wipes.py` to
  stop recomputing and let `data wipe` do it; §4.10 row n wanted `rollback_to_change` to
  take its note from the caller. Both take a guarantee the write always makes and hand it
  to whoever remembers — and both were deliberate decisions with a comment and, in the
  first case, a test pinning them. `ARCHITECTURE.md` §15 now carries the general rule.
  §4.10 row j wanted `_hold_around` returned by the strength planner as
  `StrengthPass.held`; the planner is handed only the strength sessions in the adapt
  path, so it cannot see the other sports it would have to hold. The inline
  weekly-summary builder in `service/analysis.py` stayed too: it is not a function today
  and it reads the database twice, so extracting it is a refactor of
  `_run_workout_analysis`, which belongs with Phase D's split of that file.

- **Phase D item 1, the analytics package.** The training maths is one package now.
  `intensity.py` is three files: `analytics/intensity.py` (452) the zone model,
  `analytics/zone_tables.py` (211) the text tables and their caveats, and
  `analytics/mesocycle_report.py` (377) the report plus the window helpers that decide what
  a completed week is. `progression.py` with `timeline.py` is three more:
  `analytics/progression.py` (381) the day series and weekly aggregates,
  `analytics/timeline.py` (292) the bands, warnings, assembly and clipping, and
  `analytics/runway.py` (137) the end-of-plan detector. `plan_diff.py` with
  `plan_lineage.py` is the flat `plan_versions.py` (349). `adherence.py`, `chart.py` and
  `baselines.py` moved in unchanged. `plan_dates(workouts)` is the one answer to "which
  rows does the schedule cover", where four callers had built the list by hand, and
  `clock.day_str` replaces the two private `strftime` copies the split would otherwise have
  left in two new files. `tests/test_progression.py` split into itself and
  `tests/test_timeline.py`, and `TestPlanEnd` moved to `tests/test_runway.py`.
  `Phase D item 1: the training maths moves into analytics/`

- **One instruction in the proposal was refused.** `REORG_code_layout.md` §6.7 put the
  timeline's row fetch in `analytics/timeline.py`. It cannot go there: `build_timeline_payload`
  imports `ARCHIVED` from `db/objectives.py` and calls `garmin.warmup_cutoff`, and §5.2's
  layering rule — now `tests/test_layering.py` — forbids anything under `analytics/` from
  loading `trainmate.db`. Being handed a handle is allowed; importing the package is not. So
  the fetch is the flat `trainmate/timeline_rows.py`, and `ARCHITECTURE.md` §15 says why.

- **Two defects found on the way, both fixed here.** `trainmate_web.py` has a route handler
  named `plan_versions`, which shadowed the newly-named module and turned `/api/plan/diff`
  into a 500; it imports the two symbols by name instead. And `analytics/weekly_evidence.py`
  annotated a return as `Tuple[...]` without importing `Tuple` — Phase C's, invisible because
  Python 3.14 evaluates annotations lazily.

- **Two things deliberately left.** `clock.day_str` is used by the analytics files this commit
  touched and nowhere else; about 65 other `strftime("%Y-%m-%d")` call sites across `db/`,
  `coach/service/`, `cli/` and `journal.py` are a separate codemod, not a phase commit's
  business. And `tests/test_intensity.py` (809 lines) was not split. It can be: sixteen of its
  eighteen classes test only the model or only the report, and only `TestZonesAndRendering`
  and `TestNotes` mix. It is left because §7 puts test-file size splits at lower priority and
  Phase E owns them, not because the file resists cutting. `tests/test_runway.py` is 736 lines
  for the same reason, and grew here by absorbing `TestPlanEnd`.

- **The review of Phase D item 1**, in the same commit. A read-only agent re-parsed every old
  and new file with `ast` and compared each function body byte for byte — no behaviour change
  outside the ones named above. It confirmed the gate resolves 439 patch sites naming 42
  targets, including the one this commit moved, and that importing `analytics.intensity` now
  costs five `trainmate` modules where the flat file cost eight. It found the dedup had
  stopped two sites short — `_s` survived in the new `mesocycle_report.py` and
  `weekly_aggregates` still built the plan's dates by hand — an unused
  `from trainmate.analytics import timeline` in `chart.py` that re-coupled the chart to the
  timeline module at import time, three locals in `cli/runway.py` shadowing the newly imported
  `plan_end`, a docstring there naming the assembly where it meant the fetch, and fourteen
  stale symbol references across `ARCHITECTURE.md` and six design docs. All fixed before this
  commit.

- **Phase D item 2, the integrations.** `trainmate/gcal/` is the Calendar package now:
  `history.py` (173) the revision list an event's description ends with, `event.py` (204)
  what the event says — the title tags, the whole description, `event_url`, and
  `event_day` — with no Google import in it, `client.py` (386) the only file that calls
  the API, and `reconcile.py` (245) the pass that makes the calendar agree with the log.
  `__init__.py` is 17 lines of docstring. Three rules that were written twice are written
  once: `freshness.py` holds the age of the last pull and the "using cache" line that
  Garmin and the Calendar each had their own copy of, `event.event_day` replaces the
  inline date read in the signal ingest and `_event_day` in `cli/workouts/calendar_sync.py`,
  and `history.load_line` is the one writer of `Duration | TSS | RPE`, which the top of
  the event and every history entry had each rendered for themselves. The
  `delete_workout_event` alias is gone. `tests/test_calendar.py` split into
  `test_gcal_client.py` and `test_gcal_reconcile.py`, and `test_calendar_lineage.py`
  became `test_gcal_history.py`.
  `Phase D item 2: the Calendar code becomes the gcal/ package`

- **What the split bought immediately.** The title-tag tests used to build a real
  `CalendarSyncer` — which reads the service-account credentials file — patch a mock
  service onto it, run `sync_workout`, and dig the event body back out of the mock's call
  list, all to check one word in a title. They call `event_body(workout)["summary"]` now,
  so `test_gcal_reconcile.py` builds no client at all. Two test modules still need the
  credentials file rather than three; `AGENTS.md` says which, and the count of tests that
  collect without it is 1959 of 1989.

- **Four corrections to the proposal, found by doing it.** §6.8 said "nine test assertions
  change to `delete_event`": six did, plus two production call sites and the definition.
  §6.8 and §7 said "two merged duplicates": three landed, because the `gcal/history.py`
  bullet asks for the load line separately from the "Other changes" list that names the
  other two. §7's "`garmin/` tidy-up" had nothing left in it — §6.8 asks that `garmin/`
  keep `client`, `sync` and `derived` and that `_safe_round` sit in `sync.py`, and both
  were already true; the only garmin work here is the throttle merge. And §6.8 put
  `event.py` at "about 270 lines"; it is 204, because the load line went to `history.py`
  instead. The other three estimates were good to within five lines.

- **One decision the proposal did not make.** §6.8 said the refresh throttle was a
  duplicate to merge but not where the merged copy should live, and a new top-level
  module is a layout decision. `trainmate/freshness.py` is that decision, taken here:
  neither `garmin/` nor `gcal/` may import the other, and no module they both already
  depend on was about freshness. `ARCHITECTURE.md` §15 carries the reasoning.

- **The review of Phase D item 2**, in the same commit. A read-only agent re-derived every
  moved function against its old text, ran the suite whole and per file, and probed the
  import graph in fresh interpreters. It found no behaviour change — the throttle still
  compares timedeltas rather than truncated minutes (5.9 minutes against a 5-minute window
  is still stale), both "is fresh" sentences are byte-identical to the two they replace,
  and the `""`-to-`None` change in `event_day` and `load_line` is invisible behind guards
  that were already truthiness tests. What it did find was documentation: a comment in
  `reconcile.py` claimed `tests/test_layering.py` guards its deferred import, and it does
  not — importing `trainmate_web` never reaches `reconcile`, because the web app builds
  its database handle inside a request. The rule now lives in `ARCHITECTURE.md` §15, which
  says plainly that no test holds it. It also found the same caveat written in four
  places, a `freshness.py` docstring that restated §15 nearly verbatim without citing it,
  a `gcal/__init__.py` that listed its submodules in the wrong dependency order, an
  `event.py` docstring that miscounted its own database reads, one stale
  `calendar_lineage.py` path in `ARCHITECTURE.md` that the sweep's own grep filter had
  hidden, and a §15 sentence that invented a disagreement between the two throttle copies
  to justify merging them — they had in fact always agreed. All fixed before this commit.

- **Three things it found and left.** Two `mark_adherence_from_results` tests had been
  sitting in the Calendar client's test file; they moved to `test_gcal_reconcile.py`, and
  `test_gcal_client.py` is 512 lines rather than 807. Still over 500, and §7 leaves test
  sizes to Phase E. `tests/helpers.py`'s `_DB_BINDING_SITES` is dead: Phase C moved every
  module in it to `runtime.db`, so none of the nine binds `db` by value any more and only
  the special-cased `trainmate.runtime` entry does anything. Deleting the tuple is its own
  change, not a phase commit's. And `garmin/sync.py` had a `"recently pulled"` fallback
  that was unreachable before this commit and obviously so after it; that one was cut.

- **Phase D item 3, the database package.** `db/workouts.py` was 1,122 lines holding three
  jobs a caller never mixes, and it is three files now. `workout_change.py` (412) is the
  write path — the `WorkoutChange` handle, the `workout_change` context manager, the
  macrocycle tag, the Calendar reconcile on close, and `rollback_to_change`, the one undo
  every rollback command reduces to. `workouts.py` (426) answers "what is on Thursday":
  the live revision of a slot and the hydration that turns it into a `Workout`.
  `workout_history.py` (319) answers "what happened to Thursday": every form the session
  has had, the change log, and which Calendar event holds it. The three are mixins on one
  `Database`, so they reach each other through `self` and exactly one name crosses —
  `workouts.py` imports `_ZONE_COLUMNS`, which lives with the two constants built from it.
  `db/base.py` is 158 lines about connections, with `SettingsMixin` merged in from the
  46-line `settings.py`; the DDL is `schema.py` (534) on a new `SchemaMixin`, and
  `_init_db` keeps its name. `periodization.py` is 374 for plan versions, feedback and the
  writes, and `mesocycles.py` (217) owns every read of the mesocycles table.
  `get_completed_activity` moved from `strength.py` to `activities.py`, and
  `prescribed_sets_for_revisions` is four lines wrapping `_prescribed_set_rows` where it
  was a byte-identical copy of its SQL. `db/__init__.py` is 48 lines: a docstring and the
  class, nothing else.
  `Phase D item 3: the database package`

- **The `trainmate.db.db` accessor is gone, which was the largest part of this by reach.**
  §6.3 asked for it once `settings.py`, `clock.py` and `llm_models.py` read `runtime.db`.
  They do now — seven call sites, not the six §6.10 counted, and three `scripts/` did the
  same import at module scope, which neither section mentioned. `runtime.db` is the one way
  to the singleton. Four test modules were leaning on the accessor: `test_web.py` saved and
  restored a handle that `/api/models` no longer reads, `test_periodization.py` and
  `test_workout_state.py` each bound `trainmate.db.db` by hand instead of calling
  `rebind_test_db`, and `tests/helpers.py` carried a `_DB_BINDING_SITES` entry and half of
  `restore_db_handles` for it.

- **Two decisions the proposal did not make, both written into `ARCHITECTURE.md` §15.**
  `db/schema.py` is 534 lines, over the rule. §2 of the proposal had retracted the exception
  for it on the strength of a ~470-line estimate made before the squash landed; the real
  number is 534 and the retraction's premise fails. It stays one file for the reason
  `trainmate_web.py` does, and more so — the CREATE statements are not independent, they run
  in one order inside one method under one `SCHEMA_VERSION`, so cutting the file lets a
  schema change touch two files while the version describing it lives in one. `AGENTS.md`
  names it as the third standing exception. And `analysis.py` did **not** merge into
  `activities.py`: the size rule's own escape hatch applies, and the merge would have
  produced a 405-line file holding two jobs that change for different reasons — the shape
  the 400-to-500 rule then asks to split again.

- **Three of the item's bullets were already done, and the plan now says so.**
  `get_next_mesocycle` and `get_prescribed_sets` went in Phase A; the learnings re-exports
  and the `learnings.py` slimming went in Phase C. §6.3 asked for all four again. Two more
  corrections: `strength.py:37–42` for `get_completed_activity` was stale (43–48), and the
  "one read of prescribed sets instead of three" lands at two, not one —
  `WorkoutChange.prescribed_sets` is a genuinely different read, six named columns inside
  the change's own transaction, and it stays.

- **No test file was split, and the reason is not size.** §7 says test files follow the code
  in the same commit. None of these three splits has a test file that follows it: the db
  tests are organized by behaviour, not by module. The mesocycle-reader assertions sit
  inside `TestDateKeyedGeneration` in `tests/test_periodization.py` (2,884 lines) among
  tests about generation, and `tests/test_db.py` (756) is one `TestDatabase` grab-bag.
  Cutting either follows a different axis from this commit's, which is Phase E's
  size-only work. `test_workout_revisions.py` did change: `APPEND_PATH_MODULE =
  "workouts.py"` is `APPEND_PATH_PREFIX = "workout"`, keyed on a shape as §9 asks.

- **The review of Phase D item 3**, in the same commit. A read-only agent matched every
  moved function by name across the split, stripped the docstrings and compared the
  unparsed bodies: over a hundred came back byte-identical and exactly three differ, which
  are the three intended edits. It did not take the trigger merge on reading — it built a
  scratch database and ran five scenarios, including two `wipe_workouts()` calls back to
  back and one nested inside an outer `transaction()`, and confirmed the `IF NOT EXISTS`
  the merged text adds is seen by the `DROP TRIGGER` three statements above it. It ran
  `prescribed_sets_for_revisions` against a real strength session beside
  `_prescribed_set_rows` and got the same keys, the same rows and the same nine columns.
  It found no behaviour change, no lost symbol, no method-name clash across the eighteen
  mixins, no import cycle, and 439 patch sites naming 42 targets — unchanged, because this
  commit moved none.

- **What the review found, all of it documentation, and all of it fixed here.** The worst
  was mine: rewriting the comment over `_DB_BINDING_SITES` in `tests/helpers.py`, I
  restated its claim that eight modules bind the handle by value. Not one of the other
  seven has since Phase C, so `rebind_test_db` was walking a list that did nothing. The
  tuple is gone and the function is one assignment, `runtime.db = test_db`. Two design
  docs still described the deleted accessor: `DESIGN_model_selection.md` said
  `llm_models` "imports `trainmate.db.db` inside the functions", and
  `DESIGN_constraints.md` had one line still naming `base.py` three lines below one the
  sweep had corrected to `schema.py`. `ATHLETE_VOID_KINDS` had been left in
  `db/workouts.py`, which never reads it, away from `CHANGE_KINDS` — of which it is a
  subset; it sits beside it now, and its three importers name the new path. And 24 test
  modules carried an `import trainmate.db` that nothing used; this commit removes the last
  reason for any of them, so they went with it.

- **One thing found and left, for whoever writes the last commit.** Nine files under
  `trainmate/` and `tests/` cite `REORG_code_layout.md` or `REORG_execution.md` by section
  number in a docstring — `signals.py`, `clock.py`, `workout_state.py`,
  `test_layering.py`, `test_cli_plans.py` and `test_isolation_guards.py`. Both files are
  deleted in the branch's last commit, so those pointers will dangle. None was added here.
  §1's table is where that belongs: either the rationale moves to `ARCHITECTURE.md` §15
  before the end, or the pointers go.

- **Phase D item 4, the strength planner.** `strength/planner.py` was 737 lines holding
  two jobs, and it is two files now. `planner_prompt.py` (365) is what the call says and
  what it will accept back: the system prompt, the blocks the user message is built from,
  and the checks a returned exercise passes before it becomes a prescribed set — one that
  fails is left out with a line for the preview. `planner.py` (394) is the pass: which
  sessions the call is about, the call itself, folding the answers into the proposal, and
  writing them. `_ask` and `_complete` stayed there, because every case in
  `tests/test_strength_planner.py` patches `_complete`. Six names lost a leading
  underscore because they now cross a file — `Session`, `Answer`, `system_prompt`,
  `user_content`, `clean_session`, `same_rows` — and nine test references moved with them,
  seven in `test_strength_planner.py` and two in `test_prompt_gates.py`.
  `Phase D item 4: the strength planner splits from its prompt`

- **One shape change the split needed, which the plan did not name.** `_moved_on(session)`
  answers whether the brief or the duration a session's sets were written under has changed
  since. It is Wednesday. Thursday's gym was written for 70 minutes, and the week planner
  cuts it to 40. Both halves of the file ask that question: the prompt puts a line under
  Thursday telling the model to write it again, and the fold-in lets the answer through
  even though Thursday's kilograms were weighed yesterday. A module function would
  therefore have had to live in one file and be imported by the other, and the import goes
  the wrong way — the prompt cannot import the pass. It is a property on the session record
  now, `Session.moved_on`, beside the `lineage_id` property that was already there. The
  `Session` record itself went to `planner_prompt.py` for the same reason: the prompt's
  session block is written from it.

- **§6.9's four "Other changes": three done, one declined.** `strength/__init__.py` is a
  docstring listing all seven files. `sets.py` is 380 lines, under the 400 the plan named
  as the line to cut at, so it was left alone, as were `vocabulary.py` and
  `prescription.py`. Of the two OpenRouter imports hidden inside functions, only
  `planner._complete` was hoisted — see the next entry.

- **The other hoist was done, measured, and put back.** `strength/questions.py` calls the
  model once, to propose vocabulary names for an exercise the athlete typed. Its import of
  the client sat inside that function, and §6.9 asked for it at the top of the file. Hoisted,
  it put `requests` on the startup path of every command. The chain is one line long:
  `athlete_queue.py` imports `strength/questions.py`, and `cli/data.py`, `cli/queue.py`,
  `cli/render.py`, `cli/status.py`, `cli/workouts/generate.py` and `trainmate_bot.py` all
  import `athlete_queue`. `import trainmate_cli` went from 107 ms and 254 modules to 201 ms
  and 542, so `tm status` — and every chat command, because the bot runs the CLI as a
  subprocess — paid about 95 ms it had not paid before. It also cancelled the three lazy
  OpenRouter imports §7 keeps on purpose, `settings.py:133` and two flag-guarded sites in
  `trainmate_cli.py`: the client was already loaded before any of them ran. The import is
  back inside `propose` with two lines saying why, and the rule now has a durable home in
  `ARCHITECTURE.md` §14 beside the two the layering test asserts. No test holds it —
  `tests/test_layering.py` covers the analytics package and the web app only, and both were
  green while the CLI regressed.

- **No test file was split, and not for want of size.** `tests/test_strength_planner.py` is
  597 lines and `test_prompt_gates.py` is 581. Neither follows this commit's axis:
  `test_strength_planner.py` is organized by what the pass does — checking, writing again,
  going through generate, recording — and nearly every case runs the whole pass through
  `planner.run`. Cutting either is size-only work, which §7 leaves to Phase E.

- **The gate is unmoved at 439 patch sites naming 42 targets.** This split moved no patch
  target: `tests/helpers.py` patches `trainmate.strength.planner.run` and
  `test_strength_planner.py` patches `planner._complete`, and both stayed in `planner.py`.

- **The review of Phase D item 4**, in the same commit. A read-only agent matched every
  symbol across the split by name, applied the six renames, stripped the docstrings and
  compared the unparsed bodies: exactly four differ, and all four are the intended edits —
  the `moved_on` property, `_complete` losing its local import, and the two call sites now
  reading `session.moved_on`. `SYSTEM_PROMPT` and the other five constants are byte-identical,
  no symbol is defined in both files, and nothing in the repo still names an old path. It
  confirmed the patch on `trainmate.openrouter.openrouter_client.complete` still bites rather
  than assuming it: `openrouter_client` is an instance, so the patch replaces a method on the
  one object both binding styles name. Its one blocking finding is the entry above; it
  measured the module counts and timings in fresh interpreters and isolated the cause to that
  single import line, which is more than the suite could have told anyone.

- **One thing the review pushed back on, and it stays as it is.** `Session` — the record of
  one session the call was asked about — lives in `planner_prompt.py`, which §6.9 described
  as the prompt builders and the reply checks. It is neither. It is there because the
  prompt's session block is written from it, so the import has to run that way. The clean
  alternative is a third file holding `Session` and `Answer`, about 45 lines. That is a
  two-file split turned into three for one dataclass, and it would separate `Answer` from
  the reply checks it belongs beside. `AGENTS.md` asks a review pass to cut as readily as it
  adds, so this one does not add.

- **Phase D item 5, the week planner's prompts.** `coach/engine/workouts.py` was 1,304
  lines holding four jobs, and it is four files now. `sessions.py` (229) is what the model
  is told about one session entry rather than about the span: the sport enum both schemas
  list, the intensity target, its two schema members, the `replaces` field, the strength
  brief, what may not be rewritten, how a move is written, and what a benchmark entry must
  keep. `notes.py` (217) is what is done with the athlete's words: the `workout tweak` TASK
  head, the note section, and the constraint and signal extraction that `bot capture note`
  asks for too. `generate.py` (428) is `WorkoutGenerateMixin` — the sessions already
  standing and how to answer for each, the mesocycle already under way, the constraints
  that ended inside it, and the builder. `adapt.py` (509) is `WorkoutAdaptMixin` — the
  standing rules, how to read a depressed morning, the terminal window, the drift
  correction, and the builder. `__init__.py` composes five mixins where it composed four.
  Nine names lost a leading underscore because they now cross a file: `SPORT_TYPE_ENUM`,
  `LOCKED_HISTORY_TASK`, `strength_brief_task`, `planned_zone_task`, `planned_zone_fields`,
  `replaces_field`, `move_task`, `benchmark_task` and `tweak_task`. Test references moved
  with them in `test_prompt_gates.py`, `test_sports.py` and `test_mesocycle_progress.py`,
  and `cli/bot.py`'s function-local import now names `notes.py`.
  `Phase D item 5: the week planner's prompts split into four`

- **Two inline blocks of prompt text became named sections, and neither changes a
  prompt.** The plan asked for one: the two ATHLETE'S NOTE FOR TODAY texts, one for a run
  the athlete is watching and one for a note their human coach typed, are
  `notes.py::note_for_today_task(watching)`. The call site went from
  `if has_message and not tweak and athlete_watching(): … elif has_message and not tweak: …`
  to one branch with the call inside it. The second was not asked for: CORRECTING
  EXECUTION DRIFT is `adapt.py::_DRIFT_TASK`, a module constant eighteen lines below
  `_FATIGUE_READING_TASK`, which is the same kind of thing and was already one. It also
  gave the "adapt owns execution, generate owns periodization" comment a home beside the
  text it explains, and named the design doc the old comment's bare `§9.2` left implicit.
  It does not make the file shorter — the text moves within it — and this line says so
  rather than claiming a size win.

- **`adapt.py` is 509 lines, over the rule, and it is named rather than hidden.** 370 of
  them are `_workout_adapt_logic`, the one method §6.1 defers as separate work. Every
  section it appends already lives outside it, so there is nothing left to move; a fifth
  file holding adapt's own constants would be about 110 lines and break the same rule from
  the other side. `ARCHITECTURE.md` §15 carries that, because this file is deleted at the
  end of the branch and the fact has to outlive it. It is not added to `AGENTS.md`'s three
  standing exceptions: those are permanent, and this one is waiting for a specific cut.

- **`tweak_task` sits in `notes.py`, and that is a judgement call.** It is the whole
  `## TASK` head of `workout tweak` — find the days, change only those days, do what is
  asked, it is the athlete's call, name the request — so by shape it looks like adapt's.
  It is there because every line of it is about carrying out something the athlete wrote,
  which is what the file is for, and because moving it and `note_for_today_task` into
  `adapt.py` would take that file from 509 to about 610 and buy nothing.

- **The gate is unmoved at 439 patch sites naming 42 targets.** No patch target named
  `coach.engine.workouts`. The 132 that matter name
  `trainmate.coach.engine.openrouter_client`, and both new builders were run under that
  patch to prove it still bites rather than inferring it from a green suite.
  `import trainmate_cli` is unchanged at 107 ms and 254 modules, with no `requests` on the
  path.

- **Byte-for-byte proof, not a green suite.** A harness built every subset of the two
  builders' optional inputs — 8,192 variants each, and both values of `athlete_watching`
  for adapt — against the pre-split file loaded from `git show HEAD:…/workouts.py`. The
  system prompt, the user content and the call label came back identical every time.

- **No test file was split.** None of the three that changed follows this commit's axis:
  `test_prompt_gates.py` (581) is organized by which gate it asserts, across both
  builders, and the other two only repoint an import. §7 leaves size-only test splits to
  Phase E.

- **§6.1's "Other changes": three were already done, one is done here, one is declined.**
  The dead code went in Phase A and `engine/prompt.py` shrank in Phase C; §6.1 now says
  so. `show_prompt_only` is declared in `OpenRouterClient.__init__`, so its two readers
  ask a plain attribute instead of `getattr(…, False)`. Moving its check out of the
  service was declined, and §6.1 records why: the check decides that a preliminary verdict
  call is not the call the athlete asked to see the prompt for, and only the orchestrator
  knows there are two calls.

- **The review of Phase D item 5**, in the same commit. A read-only agent re-parsed both
  trees with `ast`, applied the nine renames and compared the unparsed bodies: all 31 old
  symbols present exactly once, none defined twice, none lost, and exactly one body
  differing — `_workout_adapt_logic`, by precisely the two intended edits. It read the
  source rather than the tests for the client trap and found nine `openrouter` lines under
  `coach/engine/`, of which one is the seam in `__init__.py` and none is a by-value
  import. It checked the five-mixin MRO for a hidden method and found none, and swept
  `trainmate/`, `tests/`, `scripts/`, `docs/`, `designs/` and `AGENTS.md` for the old
  names, finding hits only in this plan's own description of the before-state. Its
  blocking findings were documentation: `DESIGN_runway_nudge.md` cites a rule it
  attributes to `adapt`, and the sweep had pointed that line at `generate.py`; the
  `show_prompt_only` bullets above were neither done nor accounted for; and these ledger
  lines did not exist yet. It also found `engine/__init__.py` claiming every file in the
  package reaches the model when two make no call, a sentence in `ARCHITECTURE.md` §15
  saying the CLI still carries an older name for generate when `cli/workouts/generate.py`
  does not, and four bare `§N` comments — two of which the split had made ambiguous, since
  `adapt.py` and `generate.py` each now carry one `§5.2` with no doc named. All fixed here.

**Next up:** Phase D item 6 — **coach/service**: `workouts.py`, `adaptation.py`,
`planning.py` and `context.py`, one commit each (§6.2). Items 7 to 9 follow in §7's order,
one commit per file split. Two traps wait there that this item never met: the service
clock (§9), and the mixin count going from 6 to 13.

---

## 9. Traps that apply to every commit

Check each one against the item you are doing. Most phases touch several of them.

**A patch that silently stops biting.** The failure story is in §4. The gate test in §5.1 catches
it, which is why the gate comes first. When a split moves a function out of a file that still
imports the same name, every `patch()` on the old path still resolves and still reaches nothing.
`cli/workouts/generate.ensure_recent_data` has 23 call sites and is the worst case.

**The engine must look up the client, not import it.** The new files in `coach/engine/` read
`_eng.openrouter_client` when they are called. A `from … import openrouter_client` at the top of
the file would silently defeat 132 test patches.

**The service clock.** A new file in `coach/service/` that reads the clock needs the
`import trainmate.coach.service as _svc` back-import, or the
`patch("trainmate.coach.service._today_str")` sites miss it. The better fix is to switch those
patches to `tests.helpers.pin_clock` and drop the back-import from all six files that carry it.
There are 8 such patches on `cli.constraints._today_str`, 5 on `cli.render._today_str` and 4 on
`coach.service._today_str`.

**`clock.now` must be called as `clock.now()`.** Binding it to a local name defeats `pin_clock`.
This bites in `cli/bot.py`, whose 29 function-local imports all get hoisted. `trainmate_bot.py` is
the one deliberate exception: it binds `clock.now as athlete_now`, and `test_bot.py` patches that
binding while `test_clock.py` asserts on it, so leave it alone.

**Tests keyed on file names.** Re-key each on a shape — a directory or a name prefix — in the same
commit as the move that breaks it:

- the `ALLOWED` set in `test_simple_render.py`;
- `APPEND_PATH_MODULE` in `test_workout_revisions.py`;
- the `workouts/revisions*.py` glob in `test_service_invariants.py`;
- the `runway.py` exemption in `test_runway.py`;
- the `util.py` exemption in `test_utils.py`;
- the read-only grep in `test_web.py`, which §5.2 deletes outright.

**Mixin method names must stay unique across a class's mixins.** Two mixins with the same method
name means one silently hides the other. There are no clashes today, and the service goes from 6
mixins to 13, so check before adding a base class.

**No blanket re-export from a new package's `__init__.py`.** A re-export is what made the
`_today_str` patch miss. `analytics/__init__.py` stays empty; `gcal/__init__.py` holds only a
docstring, as `coach/__init__.py` now does. `AGENTS.md` carries this rule since Phase A, and names
`garmin/__init__.py` and `cli/workouts/__init__.py` as the two that still break it.

**No re-export shims to spare the importers.** `AGENTS.md` prefers a one-off migration, and every
instance of TrainMate is operated by the author.
