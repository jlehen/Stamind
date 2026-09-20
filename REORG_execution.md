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
unfinished item from §7, the order of work. It does that one item, and stops.

**One session does one commit.** It does not do a phase. It does not do "the rest of the
splits". When the commit is green and the ledger line is written, the session is over.

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

| What | Where it goes | When |
|---|---|---|
| The size rule, and the files exempt from it (`REORG_code_layout.md` §2) | `AGENTS.md`, under Code style | Phase A |
| The engine's call-time client lookup; no blanket re-export from a package `__init__` | `AGENTS.md`, under Code style | Phase A |
| The four known test failures, and what green means | `AGENTS.md`, under Test | Phase A |
| The layering rules — who may load whom | `tests/test_layering.py`, and `ARCHITECTURE.md` §14 | Phase A |
| The new layout, package by package | `ARCHITECTURE.md` §2, Module Map | Each commit |
| What was considered and rejected, and why (§4.11) | `ARCHITECTURE.md` §15, Design Rationale & History | Phase A |

The conventions go to `AGENTS.md` **in phase A, before any file is split.** A rule written down
after the work is documentation. The same rule written down before it is a constraint the work has
to satisfy — and a session picks up `AGENTS.md` on its own, without being told to read a section
of a transition plan.

`ARCHITECTURE.md` §15 already collects decisions in this shape: a short entry saying what was done,
what was rejected, and why. The rejected alternatives from §4.11 — why the coach splits into engine
and service rather than by domain, why the package is `gcal/` and not `calendar/`, why there is no
`queue/` package, why there are no re-export shims — belong there. Unwritten, they get re-proposed
by the next person who looks at the layout.

Everything else in these two files is about the act of moving. It dies with a plain `git rm`.

---

## 2. Ground truth, measured 2026-09-20

**The test suite.** 1984 tests, 99 seconds, run like this:

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

**Do not run a single test file to decide whether you are done.** A per-file run falsely fails
`test_isolation_guards` and `test_dispatch`. Use a per-file run while iterating, and the full
suite before committing.

**The line numbers in `REORG_code_layout.md` are stale.** They were taken from main at `da9ec8f`.
Since then `cli/plans.py` went from 1451 to 1493 lines, `coach/service/adaptation.py` from 830 to
815, and `db/base.py` from 919 to 635. Locate the code you are moving by its **symbol name**, not
by the line range the proposal quotes. Treat every line number there as a hint about roughly where
to look.

---

## 3. The commit rule

**One commit is one kind of change.** It is a pure move, or a pure split, or a behaviour fix with
its test. It is never two of those at once.

The reason is what the reviewer has to do. On a pure move, git reports the rename and the diff is
nothing but import lines, so "did behaviour change here?" is answered by the shape of the diff. Mix
a behaviour fix into that same commit and the reviewer has to read every line to find it.

If a split turns out to need a behaviour fix before it will work, the fix lands first, as its own
commit, with its own test. Then the split lands on top of it.

**Message format** is the one in `AGENTS.md`: `<file>: one line under 80-100 characters`, then a
blank line, then the longer description wrapped the same way. The `<file>` prefix is the basename,
and it is present only when the change mostly touches a single file. A split that creates four
files names the file it split.

**`docs/ARCHITECTURE.md` is updated in the same commit as the code it describes.** Implemented
`DESIGN_*.md` files get their paths amended in that same commit. Designs still in progress are left
alone; their paths go stale until they are implemented, and that is accepted.

**Landing the branch.** This reorg will run to roughly forty commits. That is far past the bar in
`AGENTS.md` for earning a node in the graph, so it lands with `--no-ff` after a rebase onto main.
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

**A second check, in the same test, if it is not too noisy.** For each target `M.attr`, look for a
production module that does `from M import attr`. That module holds the name by value, so patching
`M.attr` will not reach it. This is the `util.notice` case above. Try it; it should flag
`util.notice` on the first run, which is a real bug that wants fixing anyway. If it turns out to
produce a pile of false positives, drop this half and keep the resolution check. Do not build an
allowlist of exceptions for it — that is the hand-maintained list `AGENTS.md` warns against.

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

### 6.3 Executing agents work one commit at a time

The feedback loop is 99 seconds, which is short enough that an agent can iterate on its own. A good
executor prompt is narrow and contains:

- the one commit to produce, named as an item from §7;
- the surveyor's symbol list from §6.2;
- the relevant section of `REORG_code_layout.md`, quoted or pointed to;
- the traps from §9 that apply to this item;
- the baseline from §2 — four known failures, and the exact command;
- the instruction to stop after one commit and write its ledger line.

A prompt that says "do phase 4" is the wrong size and will produce an unreviewable commit.

**What makes this safe is §5, not the agent's report.** An agent will report a green suite in good
faith while having silenced a patch seam. The gate tests turn that from a judgement call into a red
test.

---

## 7. The order of work

This revises §8 of `REORG_code_layout.md` in two places, both noted below.

### Phase A — the gate, the conventions, and the cleanups

1. The patch-target test and the web half of the layering test (§5). **Do this first.**
2. The durable conventions move to `AGENTS.md` and `ARCHITECTURE.md`, per the table in §1. This is
   one commit, and it comes before any split, because these are the rules the splits follow.
3. The deletions in `REORG_code_layout.md` §7: dead code, unused imports, stale docstrings.
4. `coach/__init__.py` becomes a docstring (§4.5).
5. `runtime` builds the Calendar client instead of the import building it (§4.6). Check afterwards
   whether `AGENTS.md`'s worktree note can drop `service_account.json`.

Low risk, and it makes every later diff smaller.

### Phase B — the behaviour fixes

Already done, except one item that leaves this branch.

- §5.1 and §5.4 landed. See the ledger.
- §5.3 is retracted; it is a designed difference, not a duplicated rule.
- **§5.2 leaves this branch.** It is superseded by wanting e1RM dropped from the benchmark anchors
  entirely, and `DESIGN_strength_tracking.md` deliberately kept it. That makes it an undesigned
  behaviour change. Putting it here would break the §3 commit rule one level up, at the branch. It
  needs its own design and its own branch. Not part of this work.

### Phase C — the moves between subsystems

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

### Phase D — the file splits

*This is the first revision: the proposal said one commit per subsystem. **One commit per file
split** instead.* `coach/service` alone is five separate splits; putting them in one commit means
that when the suite goes red you are bisecting inside a commit, by hand.

That gives roughly 25 commits. Take the subsystems in this order, lowest in the import graph first:

1. **analytics** — `intensity.py` into three; `progression.py` with `timeline.py` into three;
   `plan_diff.py` with `plan_lineage.py` into `plan_versions.py`.
2. **integrations** — the `gcal/` package; the `garmin/` tidy-up and its two merged duplicates.
3. **database** — `workouts.py` into three; `base.py` into two; `periodization.py` into two; the
   small mergers.
4. **strength** — `planner.py` into two.
5. **coach/engine** — `workouts.py` into four.
6. **coach/service** — `workouts.py`, `adaptation.py`, `planning.py`, `context.py`, one commit
   each.
7. **CLI command families** — `workouts/generate.py` into five; `data.py` and `journal.py` into
   packages.
8. **CLI views** — `plans.py`, `progress.py`, then `render.py`. Render goes last, because it
   imports from all of them.
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

One line per item, newest at the bottom. A session adds its line **in the same commit as the work**,
naming the commit subject. The SHA is one `git log --grep` away, so no backfill is needed.

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

**Next up:** Phase A item 1 — the gate tests (§5).

---

## 9. Traps that apply to every commit

Check each one against the item you are doing. Most commits touch two or three of them.

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
This bites in `cli/bot.py`, whose 29 function-local imports all get hoisted.

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
`_today_str` patch miss. `analytics/__init__.py` stays empty; `coach/__init__.py` and
`gcal/__init__.py` hold only a docstring.

**No re-export shims to spare the importers.** `AGENTS.md` prefers a one-off migration, and every
instance of TrainMate is operated by the author.
