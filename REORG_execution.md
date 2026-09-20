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
| The layering rules — who may load whom | `tests/test_layering.py`, and `ARCHITECTURE.md` §14 | Phase C | moved, see §5.2 |
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
built from one. Resolved: 431 sites, 40 distinct targets.

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

**Next up:** Phase C item 1 — the load model and the fitness/fatigue maths leave `garmin/`,
creating `analytics/`, with the analytics half of the layering test (§4.1, §5.2). Phase B is
already done bar the item that left this branch.

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
