# Communication
- Use plain language, short sentences, one idea per sentence. Be explicit; do not imply.
- The problem is never vocabulary, it is compression: three ideas stacked in one clause, a
  mechanism named instead of shown.
- Codebase-private terms ("fingerprint", "§5.3") mean nothing without the design doc open.
  Say what the thing is in the same sentence, the first time. Test every sentence with "does
  this need the doc or the code open to follow?"
- Explain a behaviour as a story with a real week: "It is Wednesday. Thursday has a ride.
  The coach drops it. Here is what the calendar shows on Thursday afterwards."
- Vocabulary:
  - A **plan** is the periodization: the macrocycle and its mesocycles. Sessions are
    "sessions", "workouts" or "the schedule", never "the plan".
  - Say **mesocycle**, never "block". A **session** is planned; an **activity** is what
    Garmin recorded.
  - Name the model call, never "the planner" or "the call". The **week planner** writes the
    sessions inside `workout generate` and `workout adapt`. The **strength planner** writes
    a strength session. "The coach" is Stamind speaking to the athlete, whichever call
    wrote the words.
  - A **constraint** is what the athlete asks the coach to work around from one date to
    another (`constraints` table, `sm constraint add`). Never call it a "rule" or a
    "directive", in the chat's texts too. A sentence with no end date ("no gym on Fridays,
    ever") is a **preference**, kept in the athlete's profile.
  - A **brief** is the week planner's description of a strength day: what the session is
    for and what the plan asks of it, with no exercise, set, rep or load. The strength
    planner writes the session under it (DESIGN_strength_tracking.md §9).
  - Never say "regeneration" or "generate" bare. Say `plan generate` (writes the
    periodization) or `workout generate` (writes the sessions).

# Design
- Avoid over-engineering. It creeps in when a DESIGN_*.md is reviewed several times and
  each pass adds a mechanism for an edge case. Add one only if a plausible athlete hits the
  case in a real week; otherwise write a one-line "not handled". A review pass removes as
  readily as it adds; a pass that only adds is suspect.
- Design for athletes in general, not for the author's routine or equipment. State the
  general rule first; the author's data is only a worked example.
- Never infer a fact from noisy data (Garmin, a partial template match). Ask the human, or
  record it only from an authoritative source.
- A destructive command defaults to the reversible action (archive) and keeps the hard
  cascade behind `--purge`. If the docs keep warning the reader off a default, the default
  is wrong: fix it.
- The companion (the Telegram bot) follows three rules. The CLI is exempt.
  - A difference between two paths that cannot be explained in one sentence is a design
    bug. Collapse the behaviours; do not keep both and write better copy.
  - Every question goes through the athlete queue: the command saves it and ends, and a tap
    answers it whenever the athlete likes. No command waits on the athlete. An offer after
    an answer or a message is a question too. When a question needs another look, another
    moment or a queue feature that does not exist yet, adapt its queue kind; never ask on
    the spot (DESIGN_athlete_queue.md §2).
  - A row of buttons under a view stays a row, not a queued question. A view is what the
    athlete reads on screen: constraints, goals, the week, the plan, the morning message.
    Its buttons act on it and ask nothing, and showing the view again brings them back
    (DESIGN_chat_questions.md §2).

# Code
- Read docs/ARCHITECTURE.md first, and update it when a change touches what it records.
  Every task reads it in full, so every line costs every task. It holds what an agent needs
  before its first grep: one line per module, per table column and per command flag; the
  change recipes; each data flow as a short numbered list; the rules that span files. A
  fact that matters only inside one file lives in that file's docstring or design doc.
  Rationale lives in the design doc; a decision with no design doc gets a short §15 entry.
  History ("the bump to 27 adds…") belongs in a commit message.
- When adding a feature, check whether each command and data flow needs to know about it.
- Store exact values in the database, unless rounding saves something real. Round on
  display.
- Reuse business logic rather than duplicating it, unless reuse adds real complexity.
- The author operates every instance (the companion instance runs a second athlete from the
  same checkout). A migration is a one-off; write no backward-compatibility code.

# Git policy
- Never push without asking. Never open a pull request.
- Land a worktree branch by rebasing onto main and fast-forwarding. Only a branch with
  enough commits to be worth a node in the graph earns `--no-ff`.
- For the user's review, summarize the changes that were made.
- Commit message: a summary line under 80-100 characters, a blank line, then details in
  lines under 80-100 characters. Start the summary with `<basename>: ` only when the change
  mostly affects one file.

# Code style
- Everything wraps at 100 characters: code, comments and LLM prompts.
- A multiline LLM prompt is a triple-quoted string or implicit concatenation in parentheses.
- LLM prompts, system and user message alike, use `## SECTION NAME` for a top-level
  section, `### SUB-SECTION NAME` only under `## TASK`, and a `====` banner only around a
  document quoted verbatim. Names are ALL CAPS, no trailing colon. Read
  designs/DESIGN_prompt_structure.md before adding a section. Every design doc lives under
  designs/.
- Prefer early exits (`continue`, `return`, `raise`) over nesting inside a conditional. The
  goal is fewer indentation levels, not fewer lines: never fold a branch into a conditional
  expression. Two plain four-line branches beat one dense ternary, and a ternary that
  decides two things at once is always worse than its `if`/`else`.
- Run LLM prose through `wrap_text` (`stamind/text.py`) before displaying it.
- File size. Over 500 lines: split into pieces of 150 to 400. From 400 to 500: split only
  if the file holds two jobs that change for different reasons. Under 100: merge into a
  sibling, unless it is a concept of its own or breaks an import cycle. Split by what the
  code does (one command, one concept, one pipeline step), never into "helpers". First trim
  docstrings that restate the design doc. Exceptions: `stamind_web.py` (flat list of
  independent GET handlers), `db/schema.py` (one ordered run of CREATE statements under
  `SCHEMA_VERSION`), `static/style.css` (not Python). `coach/engine/adapt.py` and
  `coach/service/analysis.py` are over because of one method each (`_workout_adapt_logic`,
  `_run_workout_analysis`): the cut is a refactor of that method. `stamind_bot.py` stays
  under 100 because the `sm-bot` supervisor execs it by path.
- A package `__init__.py` holds a docstring and at most the class the package assembles
  from its submodules. It re-exports nothing: a re-export gives a name two homes, and a
  patch on one home misses code that reads the other. `garmin/__init__.py` still
  re-exports; it is debt, not precedent.
- Reach a name a test patches through its module, never through a by-value import. `from
  x import name` binds a copy, the test's `patch` replaces a name nothing reads, and the
  test reaches OpenRouter for real.
  - Under `stamind/coach/engine/`: `import stamind.coach.engine as _eng`, then call
    `_eng.openrouter_client`.
  - A command that runs another: `import stamind.cli.plans.generate as _generate`, then
    `_generate.run_plan_generate(...)`. Argparse's `set_defaults(func=...)` is a reference,
    not a call, so parsers keep plain imports. `tests/test_isolation_guards.py` catches it.
- One command family per file under `stamind/cli/`; split it into a file per command past
  about 400 lines. Code shared by two commands goes in a module of its own (`cli/common.py`
  for renderers), never in whichever command file defined it first. A function-local import
  that dodges a cycle between two CLI modules means shared code is misplaced: move it.
- Comments and docstrings say what the code does and name the design section that says why
  (`DESIGN_x.md §N`): one line of why plus the pointer, never the rationale restated. A
  caveat has one home; elsewhere, point at it.

# Test
- Use `unittest`. Run the tests without asking the user.
- Run tests under a memory cap. A test stuck in a loop can fill the memory, and the kernel
  then kills the whole terminal session. The suite peaks near 200 MB:

  ```
  systemd-run --user --scope -q -p MemoryMax=1G -p MemorySwapMax=0 \
      venv/bin/python -m unittest discover -s tests -p "test_*.py"
  ```

  For one file, put its name after `-p`, for example `-p "test_bot.py"`.
- Green means every test passes. A test never reads the operator's live `config.yaml`: pin
  what it needs with `patch.dict` on `config.data`. A test that depends on where a run
  started (the terminal or the athlete's chat) pins it with `started_from` from
  `tests/helpers.py`.
- Iterate with single-file runs; run the full suite before committing. Some modules rely on
  an earlier module binding the test database, so alone they fail with "tests must not open
  the production database" (`test_dispatch.py` for one).
- A fresh worktree fails at test collection until `config.yaml` and `venv` are symlinked in
  from the main checkout. Only `test_gcal_client.py` and `test_gcal_history.py` also need
  `service_account.json`. Never symlink `stamind.db`: the worktree's own empty database
  keeps a stray run off the athlete's data.
- An invariant that spans files ("a propose method never writes") gets a test that reads
  the source and names the offender. Key it on a shape (a return annotation, a directory
  glob), never on a hand-kept list of names. First try to delete the invariant instead:
  collapsing two commands into one flow removes the invariant, the test and the drift.
