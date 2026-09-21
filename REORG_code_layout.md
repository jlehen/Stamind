# Re-organizing the TrainMate code

Status: proposal, 2026-09-19. Decisions taken 2026-09-20 (§0), and Phase A of
`REORG_execution.md` §7 landed the same day. Nothing has moved between subsystems yet.

How it was made: ten read-only agents each surveyed one subsystem. Each listed what its subsystem
does and proposed splits inside it. A final pass compared those lists across subsystems and
decided which code should change subsystem.

**This file says what moves and where it lands. `REORG_execution.md` says how the work is cut into
commits, how each one is checked, and what has landed so far.** Read that file before starting a
session of this work. It revises §8 below in two places, and it holds the ledger.

**The line numbers below are stale.** They refer to main at `da9ec8f`. Since then `cli/plans.py`
has grown to 1493 lines, `coach/service/adaptation.py` has shrunk to 815, and `db/base.py` to 635.
Find the code you are moving by its symbol name. Treat every line range quoted here as a hint about
roughly where to look.

---

## 0. Decisions taken, 2026-09-20

The owner answered the questions in §9. What follows is what was decided and what is
already done on this branch.

**Done on this branch.**
- **The schema squash (§6.3, question 1): done.** Both databases — the owner's and
  piupiu's — were stamped at SCHEMA_VERSION 18, so every in-place migration had already
  run on both. `db/base.py` drops from 919 to 635 lines and holds no `ALTER`, `DROP` or
  `RENAME` at all. A fresh database before and after has the same 46 objects and the same
  274 columns and indexes, in the same order, with the same types and defaults. Seven
  migration tests went with it. A database older than the squash now needs a checkout
  from before it.
- **Difference 1 (§5.1): fixed**, and it uncovered a second, larger bug. The adapt
  prompt asks the week planner for an intensity target and the model answers, but
  `structure_revision` — the row shape both revision commands write — carried neither
  zone field, so apply read the stripped row, found no target and carried the old one
  forward. In `workout adapt` and `workout tweak` the target was asked for, answered and
  then dropped. Both are fixed: the row carries the target, and adapt asks
  `prescription_matches` instead of its own five-field check.
- **Difference 4 (§5.4): fixed.** The 15-day summary groups activities by canonical sport,
  so the week planner no longer reads road and indoor cycling as two sports.
- `docs/ARCHITECTURE.md` says the schema is CREATE-only now.
- **Phase A of `REORG_execution.md` §7: done.** The gate test (§5.1 there), the durable
  conventions into `AGENTS.md` and `ARCHITECTURE.md`, the §7 deletions below,
  `coach/__init__.py` as a docstring (§4.5) and the Calendar client built by
  `runtime` (§4.6). Two of §7's claims were wrong and §7 now says which.

**Decided, not yet done.**
- **Difference 3 (§5.3): retracted.** It is a designed difference, not two copies of
  one rule: `DESIGN_cli_selectors.md` bounds `-g N` to that goal's own span on purpose,
  and the service prints a notice when its own derivation disagrees. One narrow residue
  is written up in §5.3 and is not proposed.
- **Difference 2 (§5.2): superseded.** The owner wants e1RM dropped from the benchmark
  anchors entirely. The strength design deliberately kept it
  (DESIGN_strength_tracking.md, "The benchmark logbook is untouched … `e1rm` stays one
  lift"), so dropping it is a separate, undesigned change. Once e1RM is gone there is no
  anchor left for the two copies of the replan band to disagree about.
- **`util.py` is deleted and split (§4.7): approved**, AGENTS.md line included.
- **Package names (§9.5): approved.** `trainmate/chat/`, `gcal/`, `analytics/`.
- **The bot's `main()` → `ChatBot` class (§6.6, question 4): separate commits, same
  branch.** Moving `routing`, `keyboards` and the scheduler rules is a cut-and-paste with
  no logic change; the class conversion turns 30 closures over 12 shared names into
  attributes and moves about 250 test references. The two carry very different risk, and
  the Telegram process is the surface with the least test coverage, so they get a commit
  each — but both land on this branch, not a later one.

---

## 1. Where we start

The `trainmate/` package holds about 38,200 lines in 110 Python files. The three entry scripts add
2,725 lines.

- **27 files are over 500 lines.** Ten are over 1,000:
  - `trainmate_bot.py` (1,613)
  - `cli/plans.py` (1,451)
  - `coach/engine/workouts.py` (1,302)
  - `cli/render.py` (1,290)
  - `cli/bot.py` (1,282)
  - `coach/service/workouts.py` (1,139)
  - `db/workouts.py` (1,122)
  - `cli/progress.py` (1,042)
  - `intensity.py` (1,019)
  - `cli/workouts/generate.py` (1,007)
- **13 files under 100 lines** are not package `__init__` files. Most of them should stay (§6).

The surveys found three problems besides size.

**1. Several "pure" modules are heavy to import.** `db/` and the maths modules never import the
CLI or the coach, so the layers are mostly clean. But `adherence.py`, `intensity.py` and
`progression.py` need the load model, and the load model lives in `garmin/`. Importing anything in
`garmin/` runs `garmin/__init__.py`, which loads `garmin/sync.py`, then `strength/sets.py`, then the
whole database package. So a pure function costs 36 to 40 modules to import. It is also why some
tests must set up a test database before they import `progression`.

**2. Shared code lives in whichever command file wrote it first.** The read-only web app imports
two CLI modules.
- One of those imports loads the coach service, the OpenRouter client and the Google client. This
  was checked in a fresh interpreter.
- The code that pairs planned sessions with Garmin activities for a date range is written three
  times.

**3. Three rules exist twice, and the copies disagree.** Each disagreement changes what the
athlete sees (§5). A fourth candidate turned out to be designed, and §5.3 records the
retraction.

---

## 2. The size rule

- A Python file over **500 lines** is split.
- The new pieces land between **150 and 400 lines**.
- A file of 400 to 500 lines is split only when it holds two jobs that change for different
  reasons.
- A file under 100 lines is merged into a sibling, unless it is a real concept on its own or it
  exists to break an import cycle. Each case below says which.
- The CLI keeps its stricter rule from AGENTS.md: a command family splits into one file per
  command past about 400 lines.
- A split follows what the code does: a command, a concept, or a step of a pipeline. It never
  follows "helpers".
- Some files are over the limit because their docstrings restate design rationale. Trim those
  docstrings first: AGENTS.md already asks for one line of why and a § pointer. `config.py` and
  `journal.py` should fall under 500 this way (§6.10).

Three exceptions stay over 500 lines, each for a stated reason:
- **`trainmate_web.py`** (about 680 lines after §4.2). It is a flat list of independent GET
  handlers. Splitting it needs Flask blueprints and a fix to the static-folder path, and it buys
  no separation.
- **`db/schema.py`** (534 lines). The retraction below was wrong, and Phase D item 3
  measured it: ~~No longer an exception: the migrations were squashed (§0), so the schema
  half of `db/base.py` is about 470 lines and splits within the rule.~~ The squash left a
  485-line `_init_db`, not a ~440-line one. It stays one file for the reason
  `trainmate_web.py` does — a flat run of CREATE statements navigated by table name — and
  more so, since they run in one order under one `SCHEMA_VERSION`. `AGENTS.md` names it.
- **`static/style.css`.** It is not Python. ~~`static/app.js` too; an optional cut per tab
  is in §6.6.~~ **Phase E item 2 took that cut**, so only the stylesheet is left here.
  `AGENTS.md` says the same.

---

## 3. What each subsystem does

This is the list the cross-subsystem pass worked from.

| # | Subsystem | What it does |
|---|---|---|
| 1 | coach/service | Writes the plan: `plan generate`, `plan apply`, `plan rollback`. Judges whether the plan is stale. Writes the sessions for a span: `workout generate` and `--strength-only`. Adapts or tweaks sessions and applies the revisions. Asks the athlete about activity pairings it had to guess. Reads past training into reconstructions and learnings: `data bootstrap` and `data reflect`. Stands a goal's sessions down and back. Sizes a constraint. Assembles the prompt context. |
| 2 | coach/engine + LLM | Makes one model call and records it. Chooses the model. Builds the shared system prompt, the `plan generate` prompt and the two week-planner prompts. Reads the athlete's note into candidate constraints and signals. Builds the analysis prompt. Fingerprints inputs. Renders rows as prompt text. Turns a reply into revisions. Owns the honoring rule and the proposal records. |
| 3 | database | Connections and transactions. Schema and migrations. The one write path onto sessions (`WorkoutChange`). Reading a session as it stands today. The change log and undo. The Calendar ledger. Versioned plans, and which plan governs a date. Confidence in learnings. The store of Garmin evidence. The athlete's inputs. |
| 4 | CLI views | Dispatches a command line. Resolves selectors. Speaks in two voices, expert and companion. Runs the `plan` commands, the progress text and status. Pairs sessions with activities and marks Calendar events (both misplaced). The freshness gate. The wording for staleness and for the end of the schedule. |
| 5 | CLI command families | Changes sessions through the coach. Undoes changes and tells the athlete. Shows sessions and grades them. The Calendar commands, the Garmin-cache commands and the analysis commands. Goals, constraints, signals, benchmarks, learnings, the queue, settings and strength sets. Reads the run journal back. |
| 6 | Front-ends | Relays a CLI run to Telegram. The line protocol between the CLI and the bot. Asks a question on any surface. Turns a chat message into a command: keyboard, router, captures, pickers. The morning push. Process control. The read-only dashboard. |
| 7 | Training analytics | Sport and anchor vocabulary. The readiness verdict. Pairs sessions with activities and gives the verdict. The load of a planned session. Time in zone and the zone target. The report for one mesocycle. The load series and the PMC fold. The timeline payload and the chart. The end-of-schedule detector. Comparing plan versions. |
| 8 | Integrations | Talks to Garmin and pulls data into the database. Refreshes data before a read. The load and fitness/fatigue maths (misplaced). The stored derived metrics. Builds, writes and deletes events. Makes Calendar agree after a change. Reads signals in and writes signal events. |
| 9 | Strength | Maps Garmin exercise names. Reads the sets once. Groups and renders them. Names sets through the athlete queue. The strength history. The description and its brief. The strength planner. Records the checks. |
| 10 | Infrastructure | Configuration. Preferences. The athlete's clock. The singletons. Text layout and output tiers. The run journal. The plan-input fingerprint (misplaced). The fitness/fatigue colours (misplaced). The athlete queue, learning doubts and the heads-up. |

Six functions appear in more than one row. They drive §4:
- **Which activity was which session.** Rows 1, 4, 5, 6 and 7.
- **The load and fitness/fatigue maths.** They live in row 8. Rows 1, 4, 5, 6 and 7 use them.
- **Plan staleness.** Rows 1, 2, 4 and 10.
- **Dates.** Rows 4, 5, 7, 8 and 10, with seven copies of the ISO date parser.
- **The sentinel line protocol.** Split across the two files of row 6.
- **The fitness/fatigue colours.** They sit in row 10, while the matching display rule sits in
  row 8.

---

## 4. Moves between subsystems

### 4.1 The load model and the fitness/fatigue maths leave `garmin/`

**What is in there.**
- `garmin/load.py` (203 lines) is pure maths: TSS from power, from heart rate, and from session RPE.
- `garmin/pmc.py` lines 18–160 are pure too: `compute_pmc`, `load_ratio`, `pmc_ramp`,
  `pmc_display_values` and `pmc_data_caveat`.

**Who uses it.** Only `garmin/sync.py` uses this maths inside Garmin, when it stores an activity.
Every other caller is outside Garmin: the maths modules, the coach, the CLI and the web app.
Because the maths sits in `garmin/`, a pure caller loads the whole database package (§1).

**The moves.**
- `garmin/load.py` becomes `analytics/load.py`.
  - `adherence.planned_load` joins it. It is the twin of `activity_load`: one values a planned
    session, the other a recorded activity.
  - `_rpe_tss` becomes public, because adherence and intensity import it.
- The pure part of `garmin/pmc.py` becomes `analytics/pmc.py`. It also receives:
  - the colour bands from `util.py`: `color_load_ratio`, `color_tsb`, `color_ramp`, `pmc_cells`,
    `pmc_warming_note` and `PMC_TSB_LAG_NOTE`;
  - `_derivation_pad_days` from `garmin/client.py`.
- The stored part of `garmin/pmc.py` becomes `garmin/derived.py`: `recompute_derived`,
  `_write_derived`, `backfill_tss` and `pmc_history_start`.
  - It also gains one `warmup_cutoff(dbh)`.
  - That function replaces five hand copies of
    `pmc_warmup_cutoff_for(pmc_history_start(dbh), config.pmc_ctl_days)`. The copies are in
    `cli/common.py`, twice in `coach/service/context.py`, in `coach/service/analysis.py` and in
    `timeline.py`.
- `db/wipes.py` stops importing Garmin code. `data wipe`, its only caller (`cli/data.py:107`),
  calls `db.wipe_garmin_data` and then `garmin.recompute_derived`.

**Result.**
- `garmin/` holds three files: `client` (about 190 lines), `sync` (about 350) and `derived`
  (about 140).
- The pure modules no longer load the database.
- The hidden import cycle between Calendar and Garmin (§4.6) disappears.

**Cost.**
- About 16 production files and 8 test files change their imports.
- 43 tests replace `trainmate.runtime.garmin` with a mock. After the move, they run the real maths,
  so expect a few assertion updates. One example is `test_data_show_metrics_command`.

### 4.2 One home for "which activity was which session"

It is Monday. The athlete opens the compare tab of the dashboard. The web app pairs last week's
sessions with last week's activities. It uses its own copy of the database reads, of
`compare_days` and of the "minor / unplanned / off-plan" rule. `workout compare` on the terminal
does the same with a second copy. `cli/common.adherence_results` holds a third. A fix to one copy
does not reach the other two.

**The moves.**
- A new **`analytics/compare.py`** (about 170 lines) receives:
  - `adherence_window(dbh, start, end, today)`. This becomes the one pairing that reads the
    database. It replaces `cli/common.py:121–167`, `cli/workouts/generate.py:833–853` and
    `trainmate_web.py:262–284`. `timeline.build_timeline_payload(dbh)` already works this way.
  - `adherence_verdicts`.
  - `compare_days`, from `generate.py:872–911`. Its copy in `trainmate_web.py:286–313` goes.
  - A new `unplanned_kind()`. It replaces three copies: `adherence.py:423–438`,
    `trainmate_web.py:335–340` and `generate.py:964–969`.
  - `format_actual`, from `cli/common.py:98–118`.
- `analytics/adherence.py` stays the pure pairing and verdict code (about 430 lines).
- The Calendar verdict loop (`mark_adherence_from_results`, `mark_adherence_range`, now at
  `cli/common.py:170–231`) moves to `gcal/reconcile.py`. It is the second pass that makes Calendar
  agree with the log.
- The coach's questions about guessed pairings stay in the coach service, in the renamed file
  `matching.py` (§6.2).

### 4.3 The web app stops importing the CLI

**What happens today.** `import trainmate_web` in a fresh interpreter loads four things the web
app should never need: `coach.service.*`, `openrouter`, `google_calendar` and `googleapiclient`.
It happens through one line, `from trainmate.cli.workouts._helpers import modification_markers`
(`trainmate_web.py:24`). That runs `cli/workouts/__init__.py`, then `generate.py`, and so on.

The test that the web app is read-only (`test_web.py:641`) still passes. It only greps the text of
the web file.

**The moves.**
- `modification_markers` moves into `calendar_state.py`, and the file is renamed
  `workout_state.py`.
  - The file then holds two of a session's three state axes (ARCHITECTURE §5, "three orthogonal
    axes").
  - The change recipe in ARCHITECTURE already lists the two together.
- The pairing and compare code comes from `analytics/compare.py` (§4.2).
- The grep test is replaced by a subprocess check. It imports `trainmate_web` and then reads
  `sys.modules`.
  - It checks that no `trainmate.cli`, `trainmate.coach.service`, `trainmate.openrouter` or
    `googleapiclient` module was loaded.
  - It is keyed on module-name prefixes, not on a list of files.
  - `test_runtime.py` already does the same kind of check for sqlite.

### 4.4 Plan staleness: three files, one role each

**What plan staleness is.** When `plan generate` runs, TrainMate stores hashes of the inputs that
shaped the plan: the profile, the goals, the constraints, the thresholds and the science
documents. Later, `plan show` compares them. If they differ, it says the plan was built from
inputs that have since changed.

**Where it lives today: five files.**
- `config.py` lines 593–710: the list of inputs that shape the plan, and their hash.
- `coach/engine/prompt.py` lines 233–313: the cleaning and hashing of goals and constraints. The
  engine never calls them.
- `coach/service/prompt.py`: the judgment and the diff text.
- `coach/service/planning.py` (twice) and `cli/staleness.py` (once): three hand-built copies of
  `PlanFingerprints`.

The three copies have already drifted. `cli/staleness.py` calls `service._get_config_hash`, while
`planning.py` calls `engine._get_config_hash`. Both end at `config.plan_config_hash`, so there is
no bug yet.

**The moves.**
- **`trainmate/plan_inputs.py`** (new, flat, pure, about 300 lines) holds what shapes a plan, how
  to fingerprint it, and how to diff it. It receives:
  - the block from `config.py`;
  - the goal and constraint clean/hash functions from `engine/prompt.py`;
  - the pure diff-text helpers from `coach/service/prompt.py:17–128`.

  It stays flat because the read-only web app reads `plan_config_hash`.
- **`coach/service/staleness.py`** (`StalenessMixin`, about 370 lines) receives:
  - the judgment: `config_changed`, `_threshold_reasons`, `staleness_diff` and the rest;
  - `plan_reshape_verdict`;
  - one `plan_fingerprints()` builder, replacing the three copies;
  - `stamp` and `cached_verdict` from `cli/staleness.py`.
- **`cli/staleness.py`** keeps only the wording (about 110 lines).
- The fingerprint of the evidence used by the analysis cache is a different concept.
  `_get_evidence_fingerprint` moves to `service/analysis.py`, its only user.
- The wrappers that only forward a call are deleted. They are the engine's `_clean_profile` and
  `_get_config_hash`, and the service's `_get_config_hash`, `_get_goals_hash` and
  `_get_constraints_hash`. About 40 test references change to point at `plan_inputs`.

### 4.5 `coach/__init__.py` becomes a docstring — **DONE**

**The problem.** Today `coach/__init__.py` imports the engine and the service, to re-export them.
So importing a light module such as `coach/honoring.py` (as `cli/status.py` does) loads:
- the whole service;
- the OpenRouter client;
- the strength planner.

It also creates an import cycle. Because of it, `strength/planner.py` cannot import
`coach/formatting.py`, so it re-implements the science banner: `_athlete_science` is a
line-for-line copy of `formatting._science_section`.

**The change.**
- Only a docstring stays in `coach/__init__.py`.
- About 20 test lines change `from trainmate.coach import coach_service` to
  `from trainmate.coach.service import coach_service`. The builder in `runtime.py` changes the same
  way.
- About 50 test lines change `trainmate.coach.config.data` to `trainmate.config.config.data`. It is
  the same object.
- `from trainmate.coach import honoring` keeps working, because it imports a submodule.
- `strength/planner.py` then reuses the science section from `coach/formatting.py`, and the copy
  goes.
- The docstring's list of patch targets is stale. `trainmate.coach.service.db` and
  `.calendar_syncer` no longer exist. Fix it here and in ARCHITECTURE §3.

### 4.6 `runtime` builds the Calendar client, not the import — **DONE**

**What happens today.**
- `google_calendar.py:526` builds `calendar_syncer = CalendarSyncer()` when the module is imported.
  The constructor reads `service_account.json` (lines 70–73).
- `cli/workouts/generate.py:9` imports `event_url` from that module when it loads.
- So every CLI command, and the web app, needs the credentials file even when Calendar is not
  configured.

That is why a fresh worktree fails at test collection until the symlink exists (AGENTS.md).

**The change.**
- Drop the instance built at import. `runtime._build_calendar_syncer` returns `CalendarSyncer()`.
- The 61 `patch("trainmate.runtime.calendar_syncer")` sites do not change. `test_calendar.py`
  builds its own client.
- Together with §4.1, this also removes the imports hidden inside functions at
  `garmin/sync.py:197` and `calendar_reconcile.py:90`.
- AGENTS.md's worktree note can then probably drop `service_account.json`. Check this when doing
  the change.

### 4.7 `util.py` is split by topic and deleted

`util.py` is 677 lines covering five topics, and 62 production files import it. Its name is the
smell AGENTS.md warns about.

**The moves.**
- **`trainmate/text.py`** (about 390 lines): how text looks.
  - Colours, `cmd`, wrapping, widths, tables, `strip_ansi` and `asides_enabled`.
  - One `capitalized`. Today there are five copies: `strength/prescription.py:84`,
    `strength/questions.py:34`, `cli/strength.py:114`, `cli/queue.py:134` and `cli/render.py:444`.
- **`trainmate/output.py`** (about 150 lines): what the app says, in which tier.
  - `aside`, `step`, `warn`, `fail` and `notice`.
  - `Progress` and `Spinner`.
- **`clock.py`** grows to about 240 lines: the athlete's time, and how a day is written.
  - `today_date`, `today_str`, `days_between`, `fmt_date`, `fmt_span` and `fmt_timestamp`.
  - One ISO date parser, one `date_range` and one `shift`. They replace seven copies:
    `garmin/client._to_date/_date_range/_shift`, `signals.date_range`, `progression._to_date`,
    `cli/progress._to_date`, `cli/workouts/generate._shift` and `intensity._d`.
- **The fitness/fatigue colours** go to `analytics/pmc.py` (§4.1).

**Consequences.**
- There is no re-export shim. AGENTS.md prefers a one-off migration, so one mechanical codemod
  edits about 80 files, tests included.
- Two real import cycles go away: `util` with `clock`, and `util` with `journal`. Four imports
  hidden inside functions go with them.
- AGENTS.md names `trainmate/util.py` in its `wrap_text` rule, so that line must change
  (question 3 in §9).
- One test patch already does nothing: `patch("trainmate.util.notice")` in
  `test_workout_generate_window.py:351–394`. `coach/service/workouts.py` imports `notice` by value,
  so the patch never reaches it. After the move, the patch fails loudly, and it gets fixed.

### 4.8 The line protocol between the CLI and the bot lives in one module

**What the protocol is.** When the bot runs a command, the CLI writes some lines that start with
the byte `\x1e`. Each carries a tag and a JSON payload: `TM-PROMPT`, `TM-PHOTO`, `TM-BUTTONS`,
`TM-FLUSH` or `TM-QUEUE`. The bot reads these lines instead of posting them in the chat.

**Why it is split today.**
- The writers are in `prompt.py:35–123`.
- The readers are in `trainmate_bot.py:412–491`. Four of them have identical bodies.
- Each frame's fields are documented twice.
- The bot builds its answer dict by hand in six places.

**The moves.**
- **`trainmate/sentinels.py`** (about 190 lines, standard library only) receives:
  - the tags and the writers;
  - one `parse_frame`, replacing the four readers;
  - `is_json_frontend`;
  - a `prompt_answer()` builder, replacing the six hand-built dicts.
- `prompt.py` keeps the question broker (about 275 lines).
- The queue's "later" codes (`prompt.py:126–137`) move to `athlete_queue.py`. The comment there
  says they sit in `prompt.py` "where the bot reads them too". The bot now imports
  `athlete_queue`, so that reason no longer holds.

### 4.9 Printing leaves the coach service

- The plan preview moves to `cli/plans/generate.py`. It is `_banner`,
  `_print_prior_training_review` and `_print_new_strategy`, now at `service/planning.py:18–54`. This
  matches how the `workout generate` preview already works.
- `capture_message_constraint` calls `runtime.render.constraint_plan_shaping`
  (`planning.py:207`). It should return the impact and let `cli/candidates.py` render it.
- The `## PREVIOUS PERIODIZATION STRATEGY` section is built in `service/planning.py:479–483`. It
  moves to `engine/planning.py`. It is the only `##` prompt section built outside the engine.

### 4.10 Smaller moves

| What | From | To | Why |
|---|---|---|---|
| `RevisionPair` | `coach/revisions.py:12–21` | `coach/proposals.py` | A record the CLI reads. The logic should depend on the records, not the reverse. |
| `PlanProposal` | `types.py:219–228` | `coach/proposals.py` | Not a database row. `service/planning.py` is its only user. |
| `CoachContext` | `coach/proposals.py:131–150` | `service/athlete_context.py` | Not a proposal. Only the service uses it. |
| `LEARNING_UPDATES_FIELD` | `engine/__init__.py` | `engine/analysis.py` | Its only user. |
| `goal_range_for_window`, `_goal_span_start`, `_resolve_goal` | `cli/plans.py` | `cli/selectors.py` | `constraints.py` and six plan commands use them. This removes the imports hidden inside functions at `constraints.py:176,206`, which claim a cycle that does not exist. |
| The four plan print helpers | `cli/plans.py:273–323` | `cli/common.py` | `plan show` and `plan diff` share them. |
| `ROUTABLE_SETTINGS` | `cli/settings.py:22–36` | `cli/bot/capture.py` | Its only user. It sits next to `SETTING_DESCRIPTIONS`, which is keyed on the same names. |
| `warn_stale_before` | `cli/workouts/_helpers.py` | `cli/workouts/calendar_sync.py` | Its only caller. |
| The weekly-evidence maths: `signal_days`, `week_response_features`, `day_response_z`, `week_constraints`, `norm_signal_value`, the weekly-summary builder, `_pmc_week_summary` | `service/analysis.py`, `service/context.py` | `analytics/weekly_evidence.py` (about 445 lines) | None of it reads the database. |
| `_hold_around` | `service/adaptation.py:651–667` | Returned by the strength planner as `StrengthPass.held` | Two service files use it. The planner already has the sessions it needs. |
| The four strength proposal fields, copied three times | `service/workouts.py` (×2), `service/adaptation.py` | `strength.planner.proposal_fields(strength)` | One copy. |
| `WATCH`, `GARMIN`, `ATHLETE` | `strength/sets.py:24–26` | `db/strength.py` | They duplicate `NAMED_BY_PERSON`. |
| The confidence model for learnings | `db/learnings.py:6–98` | `trainmate/learning_confidence.py` | Pure rules. Storage keeps only storage. |
| `heads_up.undone_note` | called from `db/workouts.py:972` | Computed by the two service callers and passed in | The database layer stops choosing words for the athlete. It also stops loading `heads_up`, `settings` and `llm_models`. |
| The end of the commitment window | `cli/workouts/generate.py:201–203` | `settings.commitment_end(today)` | `service._commitment_window` already owns this rule. |
| The two halves of the router's intent table | `cli/bot.py:77–151`, `trainmate_bot.py:152–213` | `trainmate/chat/routing.py` | They are one table. The test that checks the two files against each other becomes a check inside one file. |
| The anchor label with its fallback to the kind (six copies) | intensity, `cli/benchmarks`, context, web | `benchmarks.label_for_kind` | One copy. |
| `Config.signal_metrics` | `config.py:488–503` | `signals.py` | It is the only app module `config.py` imports. Low priority. |

### 4.11 Considered and not proposed

- **Split the coach by domain instead of into engine and service.** No. The engine holds the
  prompts and the model call. The service reads the database and orchestrates. That split gives:
  - one patch point for the model call, used about 150 times in the tests;
  - prompt tests that run without a database.

  A split by domain would still need two files per domain. Fix the names instead:
  `engine/generate.py` ↔ `service/generate.py` ↔ `cli/workouts/generate.py`, and the same for
  adapt.
- **A `trainmate/queue/` package.** No. `queue_kind.py` really does break a cycle:
  `strength/sets` imports `queue_kind`, and `athlete_queue` imports `strength/questions`, which
  imports `strength/sets`. `db/queue.py` and `cli/queue.py` belong to their layers. That leaves two
  files, which does not earn a package.
- **A `trainmate/calendar/` name.** No. It collides with the standard library's `calendar` module
  and with local variables called `calendar`. Use `gcal/`.
- **Re-export shims to spare the importers.** No. AGENTS.md prefers one-off migrations.
- **No split for these files.** Each is one job: `coach/formatting.py` (408), `openrouter.py`
  (454), `adherence.py` (about 430), `selectors.py` (475), `cli/constraints.py` (486),
  `cli/strength.py` (463), `cli/queue.py` (421) and `settings.py` (384).

---

## 5. Rules that exist twice and disagree

Merging each pair of copies changes what the athlete sees, so each needs your OK. I propose to
fix them before the moves, so that a move never hides a change of behaviour.

### 5.1 `workout adapt` drops a correction that only changes the zone target

It is Wednesday. Thursday's run has a zone target of 40 minutes in Z2. Wednesday's HRV is poor.
`workout adapt` runs, and the week planner keeps Thursday's title, description and load. It lowers
the target to 30 minutes in Z2 and 10 minutes in Z1.

The adapt service has its own check, `_revision_is_change` (`coach/service/adaptation.py:157`). It
compares only the title, the description, the duration, the RPE and the TSS. So it decides nothing
changed and drops the revision. On Thursday, the watch and Calendar still show the old target. A
benchmark flag that is added or removed on its own is dropped the same way.

The rule on the write path does count the zone target and the benchmark flag
(`db/workouts.py:44`, `PRESCRIPTION_FIELDS`). So does the preview's rule
(`coach/revisions.py:prescription_matches`).

**Fix.** Adapt uses `prescription_matches`. The whitespace normalisation that adapt does today
moves into `prescription_matches`, so a re-listing that only changes spacing stays a no-op.

### 5.2 `benchmark record` tells the athlete to regenerate the plan for an e1RM

It is Tuesday. The athlete records a squat e1RM of 110 kg. The last one was 102 kg, 8% lower.

`benchmark record` prints: "This moves your effective threshold past the replan band — run
`plan generate`".

`plan show` never marks the plan as stale for this. Its check, `_threshold_reasons`, skips e1RM on
purpose, so that a squat PR cannot invalidate a whole periodization
(DESIGN_intensity_distribution.md §10). The athlete is told to do something the rest of the app
says is not needed.

**Fix.** One rule in `benchmarks.py` for "did this anchor move past the band?", with the e1RM
exclusion. `cli/benchmarks.py` and `_threshold_reasons` both use it.

### 5.3 A goal's span — RETRACTED, this one is designed

I reported this as a fourth rule with two disagreeing copies. It is not. The difference is
deliberate and documented, and this section is kept only so the claim does not outlive its
correction.

`DESIGN_cli_selectors.md`, "A named goal is bounded to its own span", says the service's
derivation is the thing being corrected: when the goal before has no plan, that derivation
"quietly swallows the days belonging to a goal nobody has planned for". So `-g N` bounds
the plan to N's own span, "whether or not that goal has a plan". The CLI owning that
policy while the service takes `start_date` is deliberate as well, and the service prints
a notice at exactly the moment the two readings disagree, ending "Plan that goal
separately to cover them."

**What is left, and it is narrow.** A constraint's replan picks its goals by goal span
(`goal_range_for_window`), while the rows in those days may belong to an older plan built
before that goal existed. So the offer can rebuild a goal whose plan does not hold the
disrupted days, and leave alone the plan that does.

It only bites when an unplanned goal sits in front of a planned one. The fix, if it is
ever worth it, is to ask the data rather than derive from goals:
`db.get_periodization_ids_for_date` already answers which plan covers a day. Goal spans
would stay exactly as they are for the `-g` grammar. Not proposed for now — no athlete
has hit it, and the notice already explains the case it comes from.

### 5.4 The week planner reads road cycling and indoor cycling as two sports

The 15-day summary in `coach/service/context.py:33` groups activities by their raw `activity_type`.
Every other surface groups by the canonical sport, through `intensity.sport_durations`.

The athlete rode three times outdoors and twice on the trainer. The week planner may read, for
example, "road_biking: 3 activities, 4.5 h" and "indoor_cycling: 2 activities, 2.0 h". Meanwhile
`status` and `progress` say "cycling 6.5 h".

**Fix.** Use `intensity.sport_durations`. This is low risk.

**Smaller.** `plan_diff.input_snapshots` crashes on a malformed snapshot column. The coach's copy
of the same parser tolerates one. The tolerant version becomes the only one, in `plan_inputs.py`
(§4.4).

---

## 6. File splits, subsystem by subsystem

Sizes are approximate and include imports.

### 6.1 coach/engine — **DONE in Phase D item 5**

**`engine/workouts.py` (1,304 lines, not 1,302) becomes four files.** The `~Lines`
column below is the estimate; the actual is `generate.py` 428, `adapt.py` 509,
`sessions.py` 229, `notes.py` 217. `sessions.py` lands within a line and
`generate.py` within eight; `notes.py` is twelve over and `adapt.py` twenty-nine,
which puts it over the 500 rule as well. The bullet at the end of this section is
why, and `ARCHITECTURE.md` §15 now carries that reasoning where it will outlive
this file.

| New file | What it holds | ~Lines |
|---|---|---|
| `engine/generate.py` | `WorkoutGenerateMixin`: `_workout_generate_logic` (677–881) and the sections only `workout generate` uses: `_standing_sessions_task` 60–119, `_past_constraints_task` 276–288, `_mesocycle_progress_task` 291–325, `_mesocycle_composition_task` 328–368, `_standing_answer_fields` 534–557, `_athlete_note_field` 560–571 | 420 |
| `engine/adapt.py` | `WorkoutAdaptMixin`: `_workout_adapt_logic` (883–1302), `_terminal_window_task` 38–57, `_FATIGUE_READING_TASK` 140–164, `RULE_MOVE_FIRST` and `RULE_MESOCYCLE_NOT_YOURS` 589–603, `_standing_rules_task` 606–613 | 480 |
| `engine/sessions.py` | How the week planner writes one session entry: `_SPORT_TYPE_ENUM` 15–35, the strength brief and request tasks 167–208, `_planned_zone_task` 477–513, `_replaces_field` 516–531, `_planned_zone_fields` 574–586, `_LOCKED_HISTORY_TASK` 122–138, `_move_task` 616–636, `_benchmark_task` 639–671 | 230 |
| `engine/notes.py` | What is done with the athlete's words: `_tweak_task` 211–273, the constraint and signal extraction tasks 371–436, `NEW_*_SCHEMA` 439–474, and the two inline "ATHLETE'S NOTE FOR TODAY" texts (1057–1083), lifted into `_note_for_today_task`. `workout adapt -m` and `bot capture note` share it. | 205 |

**Other changes.**
- The new files must look up `_eng.openrouter_client` when they are called. A
  `from … import openrouter_client` would silently defeat about 150 test patches. **Done.
  The real count is 132, and only `generate.py` and `adapt.py` need it: `sessions.py` and
  `notes.py` are prompt text and call nothing.**
- ~~`engine/prompt.py` drops to about 235 lines once the hashing half leaves (§4.4).~~
  Phase C already did; it is 228.
- ~~`engine/__init__.py` drops to about 15 lines: the patch seam and the class
  composition.~~ It is 25. `AGENTS.md` asks a package `__init__` for a docstring as well,
  and naming the package's seven files takes eleven of those lines.
- ~~Dead code to delete: `coach/formatting.format_planned_workouts` (220–229) and
  `llm_models.stored_model` (24–27).~~ Phase A already deleted both.
- `show_prompt_only`: **one done, one declined.** It is declared in
  `OpenRouterClient.__init__` now, and the two readers ask a plain attribute instead of
  `getattr(…, False)`. Its check did **not** move into the engine. The doc's
  `service/planning.py:284` was stale — Phase C moved it to
  `coach/service/staleness.py:193` — and reading it there shows what it decides: `plan
  show` makes a cheap verdict call *before* the call the flag is about, so without the
  guard that preliminary would print its own prompt and exit first. "This is the
  preliminary, not the call the athlete asked to see" is knowledge the orchestrator has
  and the engine does not; a `_plan_reshape_verdict` that returned `None` there could not
  say why. One function-local import in the service is the smaller cost.
- These stay whole: `formatting.py`, `openrouter.py`, `honoring.py`, `proposals.py`,
  `revisions.py`, `llm_models.py`, `engine/planning.py` and `engine/analysis.py`. **All
  eight untouched but for the one `__init__` line above.**
- **Separate work, and still outstanding.** `_workout_adapt_logic` is 420 lines with 27
  parameters — 370 after this split, which is what leaves `adapt.py` at 509. That method is
  the real problem, and cutting it into named steps is a separate job.

### 6.2 coach/service — **DONE in Phase D item 6**

The service goes from 6 mixin files to 13. Each split adds one base class to `CoachService`.
Callers keep calling `coach_service.x`, so very few tests change. **The start was 7 files,
not 6: Phase C had already taken the staleness half out of `prompt.py` into a file of its
own. The end is 13 as predicted.** Six files under `tests/` changed: three that name a
mixin or a module path, two that patched the clock, and `helpers.py`, which gained the
scoped clock one of those two needed.

The `~Lines` estimates were good. The actual, against the estimate: `generate.py` 438
(440), `standing.py` 334 (350), `guards.py` 329 (335), `adapt.py` 454 (470),
`revision_apply.py` 370 (365), `matching.py` 123 (125), `planning.py` 430 (440),
`goals_constraints.py` 222 (225), `history_context.py` 373 (365),
`mesocycle_context.py` 319 (320), `athlete_context.py` 360 (340). `athlete_context.py`
is the worst miss, twenty over, because `CoachContext` came into it from
`coach/proposals.py` and the estimate did not count that.

Three land above the 150-to-400 band a split's pieces are meant to land in:
`planning.py` at 430, `generate.py` at 438 and `adapt.py` at 454. The 400-to-500 rule
does not excuse them — that rule says when an existing file must be split, not where a
split's pieces may land. What is true is that each of the three is one job, and each is
thirty to fifty lines over because one long method dominates it: the three the "Separate
work" note at the end of this section defers, `plan_generate` (256), `workout_generate`
(263) and `workout_adapt` (341). Cutting any of those brings its file inside the band,
and none of them is cut here.

**`workouts.py` (1,124 lines, not the 1,139 the survey measured):**
- It is renamed **`generate.py`** (about 440 lines) and keeps `workout_generate` (728–993),
  `workout_generate_apply` (995–1094) and `workout_generate_strength` (1096–1139).
- **`standing.py`** (about 350 lines): the sessions the athlete was already told about.
  - `REPLACED_DAY_REASON`.
  - The commitment window (32–41) and `_standing_sessions` (43–56).
  - `_dropped_rest` (299–311), `_resolve_standing` (313–481) and `_generate_voids` (483–523).
  - The standing report lines (525–589).
- **`guards.py`** (about 335 lines): the rules the app enforces whatever the model wrote. Generate
  and adapt share it.
  - The rest windows (86–186, 215–266).
  - The coverage backstop `_fill_coverage_gaps` (188–213).
  - The benchmark collisions (268–297).
  - `_event_date_for_macrocycle` (591–607) and `_warn_missing_boundary_benchmarks` (609–684).
- `_today_workout_completed` (58–84) goes to `matching.py`.
- `workout_rollback` (686–726) goes to `revision_apply.py`.
- **The commitment window is not here to move.** §6.2 listed it beside
  `_standing_sessions`; it is `settings.commitment_days`/`commitment_end` and has been for
  a while. `_standing_sessions` — the intersection of the span with that window — is what
  went to `standing.py`.
- **`_hold_around` went to `revision_apply.py`**, which the plan did not say. §4.10 row j
  wanted the strength planner to return it and Phase C declined that, leaving it in
  `adaptation.py` with two callers, `workout_adapt` and `workout_generate_strength`. It
  went to `guards.py` first, on the strength of that file's "shared by generate and adapt"
  description, and the review moved it on: it fills the `held` field of a proposal that
  `workout_revision_apply` consumes, and the rule it compensates for — a date the proposal
  mentions holds only the sessions named for it — is written there. The tell was that
  `guards.py`'s module docstring had needed a sentence that did not belong to its
  paragraph.

**`adaptation.py` (815 lines, not 830):**
- It is renamed **`adapt.py`** (about 470 lines) and keeps `workout_adapt` (306–649),
  `workout_tweak` and its helpers (261–304), `_outside_tweak_reach` and `_is_keep_marker`.
  ~~`_revision_is_change` goes (§5.1).~~ **It did not go, and §5.1 never asked it to.**
  Phase B made its body ask `prescription_matches` instead of comparing five fields by
  hand; the method itself stays, because it is what reads the live session off the
  database before asking. It is in `adapt.py`, its only caller.
- **`revision_apply.py`** (about 365 lines): how a revision lands.
  - Moves and swaps: `_vacated_rest`, `_move_source` and `_resolve_moves` (43–155).
  - `workout_revision_apply` (670–809) and `workout_revision_record_no_change` (811–830).
  - `workout_rollback`.
- **`matching.py`** (about 125 lines): which activity was which session, and what the athlete
  ruled.
  - `_rejected_matches`, `pending_match_questions` and `record_match_decision` (189–259).
  - `_today_workout_completed`.
  - It is under 150 lines, but four callers share it: generate, `--strength-only`, adapt, and the
    adapt CLI.

**`planning.py` (637 lines, not 745):**
- **`planning.py`** keeps about 440 lines: `plan_rm`, `plan_generate` (302–582), `plan_apply`
  (584–641) and `plan_rollback` (643–713).
- **`goals_constraints.py`** (about 225 lines):
  - `goal_archive` and `goal_reinstate` (64–139);
  - `constraint_plan_impact` (141–177);
  - the message captures (179–238) and `known_signal_metrics`;
  - `constraint_is_plan_shaping` (240–262).
- The printing (18–54) goes to the CLI (§4.9).
- `_changed_inputs_text` and `plan_reshape_verdict` (264–300) go to `staleness.py`.
- `replan` (715–745) is only called by tests; see §7.

**`prompt.py` (323 lines, not 606):** — the staleness half left in Phase C; the rename is
**DONE in Phase D item 6**, although §7 there lists only four files for that item. It is
here because §4.10 row c sends `CoachContext` to `service/athlete_context.py`, and Phase C
recorded that row as waiting for the file to exist. Nothing else creates it.
- **`staleness.py`** (about 370 lines), as described in §4.4. It is 302, and gained
  `_changed_inputs_text` from `planning.py` here.
- It is renamed **`athlete_context.py`** (about 340 lines; it is 360). Without the rename
  there would be three files named `prompt.py` that mean three different things. It keeps:
  - the effective thresholds and profile, and the science documents;
  - `_coach_context`, joined by `CoachContext`;
  - the strategy text (367–443), with the "Not established yet…" fallback written once;
  - the learnings text, the learning updates, `learning_question` and the three nudges.

**`context.py` (663 lines, not 684):**
- **`history_context.py`** (about 365 lines): what the prompts are told about past training.
  - The 15-day summary (14–78), with the fix from §5.4.
  - The PMC lines (81–192).
  - `_intensity_history_context` (522–556) and `_build_prior_training_context` (558–625).
  - The reconstructions (627–684).
- **`mesocycle_context.py`** (about 320 lines): the current mesocycle as generate and adapt see it,
  lines 225–520.
- `_pmc_week_summary` goes to `analytics/weekly_evidence.py`.

**Other changes.**
- ~~`analysis.py` drops to about 420 lines once the pure maths leaves (§4.10).~~ **The maths
  left in Phase C and the file is 660 lines, not 420.** The estimate was simply wrong: 326
  of those lines are `_run_workout_analysis`, and about 150 of those are the inline
  weekly-summary builder Phase C's ledger left for "Phase D's split of that file". There is
  no such split in this section — §7 item 6 names four files and this is not one of them —
  and lifting that loop out is a refactor of a 326-line method, the same deferred job as
  `_workout_adapt_logic`. It would also not be enough: the file would land at about 520
  lines, still over the rule, so the commit would have carried a 150-line rewrite of a
  live code path and bought nothing measurable. Left, and `ARCHITECTURE.md` §15 now
  records the size and the cut that would fix it, beside the entry that says the same of
  `coach/engine/adapt.py`.
- `__init__.py` drops its unused imports, and `DEFAULT_REFLECT_WEEKS` moves to `analysis.py`.
  **Both done.** `__init__.py` is 69 lines: a docstring naming all thirteen files, the
  mixin imports and the class.

**Tests.**
- `test_runway.py` imports `GuardsMixin` from `service.guards` (at lines 641 and 651).
- `test_context_sport_gap.py:7` imports `MesocycleContextMixin`.
- The clock patch `patch("trainmate.coach.service._today_str")` only reaches a new file that keeps
  the `import trainmate.coach.service as _svc` back-import. Better: switch those seven patches to
  `tests.helpers.pin_clock`, and drop the back-import from all six files that carry it.
  **Taken, and it was four patches and five files.** Every service file that needs today
  now reads `clock.today_str`, imported by value. `pin_clock` patches `clock.now`, which
  `today_str` calls, so it reaches all of them at once — the alias never had to exist. One
  of the four had to stay scoped: `test_reinstating_recovers_only_what_is_still_ahead`
  archives a goal, then moves the clock five days on and reinstates it, so a whole-test
  pin would archive under the later clock and lose the session the test is about. That one
  uses a new `tests.helpers.clock_at`, which is the patcher `pin_clock` starts, unstarted.
  `ARCHITECTURE.md` §3 carries the rule now, so §9's trap here is spent.

**Separate work.** The real size drivers are the three methods measured above:
`workout_adapt`, `workout_generate` and `plan_generate`. Cutting them into named steps is a
separate job.

### 6.3 Database

**`workouts.py` (1,122 lines) becomes three files:**

| New file | What it holds | ~Lines |
|---|---|---|
| `db/workout_change.py` | The only way to write a session: the `WorkoutChange` handle (125–362), `workout_change` (370–403), `_same_prescription` and `PRESCRIPTION_FIELDS` (33–53), `_reconcile_calendar`, `_macrocycle_tag`, and `rollback_to_change` (937–1000) | 405 |
| `db/workouts.py` | Reading a session as it stands today: lines 20–122, 423–684, 722–770 and 1002–1018 | 430 |
| `db/workout_history.py` | The change log, the history of a session's lineage, and the record of which Calendar events hold which sessions: lines 686–720, 772–933 and 1020–1122 | 315 |

`test_workout_revisions.py:34` exempts one file by name (`APPEND_PATH_MODULE = "workouts.py"`). It
should be keyed on `name.startswith("workout")` instead.

**`base.py` (635 lines after the squash, not 919) becomes two files.** — **DONE**
- `base.py` is 158 lines with the settings methods merged in, as below.
- `schema.py` is 534, not the ~470 predicted; §2 above now carries the corrected number and
  the reason it stays one file.
  - `_init_db` keeps its name, on a new `SchemaMixin`.
  - The two `workouts` triggers are one `WORKOUTS_APPEND_ONLY_TRIGGERS` constant, a tuple of
    two statements because `execute` takes one and `executescript` would commit inside
    `wipe_workouts`'s open transaction. The `wipes.py` copy lacked `IF NOT EXISTS`; the
    merged text has it, which is harmless there because the wipe drops both first.

**`periodization.py` (574 lines) becomes two files.** — **DONE**
- `periodization.py` (374): plan versions, feedback, writes, and the contiguity repair.
- `mesocycles.py` (217): which mesocycle covers a date. `get_mesocycles_for_macrocycle` went
  with them, so one file owns every read of the table; `save_macrocycle` still writes it.
- ~~Delete `get_next_mesocycle`.~~ Phase A already did.

**Other changes.** — **DONE, with one decline**
- ~~`learnings.py` drops to about 485 lines once the confidence model leaves (§4.10).~~
  Phase C already did; it is 476.
- `settings.py` (46 lines) merged into `base.py`, keeping `SettingsMixin` as its own class
  there. It is also what lands `base.py` inside the 150–400 range: alone it was 110.
- **`analysis.py` does NOT merge into `activities.py`. Declined.** The size rule's own escape
  hatch applies — a backward-evaluation reconstruction cache keyed by an evidence
  fingerprint is a concept on its own, not an activity, and the only tie is that one wipe
  clears both. The merge would also have made a 405-line file holding two jobs that change
  for different reasons, which the 400-to-500 rule then asks to split again.
  `ARCHITECTURE.md` §15 records it.
- `get_completed_activity` moved from `strength.py` to `activities.py`, beside the plural
  read of the same table. (The doc's `37–42` was stale; it was at 43–48.)
- One read of prescribed sets instead of three:
  - ~~delete `get_prescribed_sets`~~ — Phase A already did;
  - `prescribed_sets_for_revisions` wraps `_prescribed_set_rows`. Note the end state is two
    reads, not one: `WorkoutChange.prescribed_sets` is a third and stays, because it names
    six columns rather than `SELECT *` and reads inside the change's own transaction.
- ~~`db/__init__.py` drops the learnings re-exports.~~ Phase C already did. It drops its
  old-style `__getattr__` here: `trainmate/settings.py` (4 sites), `clock.py` (2) and
  `llm_models.py` (1) read `runtime.db` now, and so do the three `scripts/` the plan did not
  count. `runtime.db` is the only way to the singleton.
- These stay as they are: `activities` (but for the one method it gained), `strength`,
  `objectives`, `constraints`, `wipes`, `queue`, `signals` and `benchmarks`.

### 6.4 CLI views — **DONE in Phase D item 8**

The estimates in this section were the best of the whole proposal: eleven of the twelve new
files land within twenty-five lines of what it predicted, and four within two.

**`plans.py` (~~1,451~~ 1,510 lines by the time it was split) becomes the package
`cli/plans/`:**

| File | What it holds | ~Lines | Actual |
|---|---|---|---|
| `generate.py` | `plan generate`, plus the preview printing that comes from the service | 290 | 312 |
| `show.py` | `plan show` and `plan keep` | 360 | 366 |
| `versions.py` | `plan versions`, `diff`, `rollback`, `rm` and `wipe` | 385 | 385 |
| `feedback.py` | `plan feedback` | 165 | 162 |
| `parser.py` | the argparse tree | 270 | 280 |

`__init__.py` is six lines of docstring. §4.10 row f sent "the four plan print helpers" to
`cli/common.py` and they went, losing their leading underscore because they now cross a file:
`print_hanging`, `print_indented`, `print_segments` and `print_feedback_notes`. **A fifth went
with them, which the plan did not name: `add_feedback_note`.** Without it `generate.py` and
`feedback.py` import each other — `plan generate --feedback` files a note, and
`plan feedback --replan` runs `plan generate` — which is the cycle `AGENTS.md` says to move the
shared code out of rather than dodge with a deferred import.

**`render.py` (~~1,290~~ 1,301) becomes the package `cli/render/`.**
- `__init__.py` holds `make_renderer` (25 lines with the docstring).
- `expert.py` (about 300 lines; it is 302): the terminal voice.
- `companion.py` (about 320 lines; it is 332): the simple-bot voice.
- `session_lines.py` (about 310 lines; it is 307): companion lines about sessions and days.
- `plan_lines.py` (about 385 lines; it is 388): companion lines about goals, constraints and
  the plan.

It is cut by voice and by topic, not by command. DESIGN_render_persona.md §3–4 keeps the companion
voice in one place. **The date words — `simple_date_word`, `simple_day_word`, `simple_when`,
`simple_span_words` — are read by both halves and live in `session_lines.py`, which
`plan_lines.py` imports.** That is what the two line estimates above already assumed: put them the
other way and `session_lines.py` is 270 and `plan_lines.py` 430.

**Rules for the render split.**
- No blanket re-export from `__init__.py`. A re-export is exactly what made the `_today_str` patch
  miss. **Held, with one unavoidable exception: `__init__.py` imports `ExpertRenderer` and
  `CompanionRenderer` because `make_renderer` returns one of them.** Nothing else is imported
  there, and `tests/test_simple_render.py` names each class from its own module.
- ~~`test_simple_render.py` has `ALLOWED = {"render.py", "bot.py"}`, keyed on file names. It should
  be keyed on the directories instead.~~ **Done, and it was broken twice over: `cli_dir =
  Path(render_module.__file__).parent` re-roots from `trainmate/cli/` to `trainmate/cli/render/`
  for a package, so the scan would have passed vacuously.** `ALLOWED` is `{"bot.py"}` now — the
  one exception the design names — and the package's own files are exempt by
  `render_dir not in path.parents`.
- ~~Its five `_today_str` patches switch to `pin_clock`.~~ **Done.** All five wrapped a call to
  `simple_day_lines`, so they became one `pin_clock(self, "2026-08-25")` in `DayLinesTest.setUp`.

**`progress.py` (~~1,042~~ 1,039) becomes three files.**
- `progress.py` (about 390 lines; it is 365): the command, `render_progress`, the chart, the
  parser, and `_weeks_arg` — which came in from `cli/argparse_ext.py`, whose only CLI caller it
  was.
- `progress_load.py` (about 305 lines; it is 298): the fitness line and the weekly load table.
- `progress_zones.py` (about 390 lines; it is 416): the time-in-zone grid, by week and by
  mesocycle. Sixteen over the band, and left there; `ARCHITECTURE.md` §15 says why.

Four names lost their underscore because they now cross a file: `short_date`, `weekday`,
`warning_line` and `NO_BAND`.

**`selectors.py` (524) becomes two files** — it is on this list because Phase C grew it, and §7
of `REORG_execution.md` says where to cut.
- `selectors.py` (314): the `A..B` grammar. What an atom may be, what a range parses to, the `-m`
  single-atom resolver, and how a command registers the flags. It opens no database.
- `windows.py` (227): the resolvers. A mesocycle, macrocycle or goal ID has to be looked up to
  learn the days it spans, so this is where `resolve_window` and the three goal helpers went.
  `OFFSET_RE` and `offset_days` lost their underscore, crossing the other way.

**Other changes.**
- `argparse_ext.py` (468 lines): optionally, a new `dashless.py` (about 190 lines) takes the
  command-line rewriting. Low priority. **Not done. It is 456 now, `_weeks_arg` having left.**
- `common.py` ends at about 250 lines. **It is 189.**
  - It loses the adherence code and the Calendar marking (§4.2), the dead
    `resolve_cleanup_range`, and `pmc_warmup_cutoff` (which goes to `garmin/derived`).
  - It gains the plan print helpers. **Five, not four; see above.** Its two function-local
    `from trainmate import runtime` were hoisted at the same time: `runtime.py` imports nothing
    heavy, so they dodged nothing.
- `trainmate_cli.py` drops about 70 unused imports. **Phase A did.**
- These stay as they are:
  - `status.py` (393 lines). `run_status` is one 320-line function, though.
  - ~~`selectors.py`,~~ `staleness.py`, `runway.py` and `candidates.py`.

### 6.5 CLI command families — **DONE in Phase D item 7**

**`workouts/generate.py` (~~1,007 lines~~ 954 by the time it was split — Phase C took the
pairing, `compare_days`, `unplanned_kind` and `_shift` out of it) holds five commands. It
becomes one file per command:**

| File | What it holds | ~Lines | Actual |
|---|---|---|---|
| `adapt.py` | `workout adapt` and `workout tweak` | 175 | 174 |
| `generate.py` | `workout generate` | 370 | 369 |
| `rollback.py` | `workout batches` and `workout rollback`, the only undo | 125 | 126 |
| `listing.py` | `workout list` and `workout show`; not named `list.py`, which would shadow the builtin | 180 | 184 |
| `compare.py` | `workout compare`, once `compare_days` has left | 120 | 162 |

Four of the five land within four lines of the estimate. `compare.py` is 42 over because
the estimate counted the handler alone: `print_workout_compare`, `print_set_lines` and
`print_calendar_marked` are the expert report `ExpertRenderer` delegates to, and they
belong with the command that asks for it.

**Other changes.**
- `workouts/_helpers.py` becomes **`session_line.py`** (about 95 lines; it is 94):
  `workout_line`, `adherence_marker` and `prescription_lines`. Three commands share it.
  Its one dead import, `datetime`, went with the rename.
- **`data.py` (~~899 lines~~ 901)** becomes the package `cli/data/`:
  - `cache.py` (about 105 lines; it is 107): `pull`, `backfill-tss` and `wipe`.
  - `show.py` (about 370 lines; it is 384): `show-metrics` and `show-activities`.
  - `analysis.py` (about 210 lines; it is 215): `bootstrap`, `reflect` and `show-analysis`.
    `_LEARNING_OPS` came with it, out from between the two CSV constants it sat among and
    beside `_render_analysis_report`, its only reader.
  - `parser.py` (about 240 lines; it is 243).
  - The three handler files have no edge between them, so the cut needed no shared module.
- **`journal.py` (~~739 lines~~ 740)** becomes the package `cli/journal/`:
  - `runs.py` (about 230 lines; it is 223): reads and filters the runs, and prints nothing.
  - `views.py` (about 415 lines; it is 440): the printers and the handlers. Forty over the
    band, and left there. No method dominates it — the longest is `_print_cost` at sixty
    lines — so the only cuts available are a file for the cost rollup and a file for the
    `--follow` tail, at about sixty and about forty-five lines each, which the same rule
    then asks to be merged back into a sibling.
  - `parser.py` (about 95 lines; it is 102).
  - Seven names now cross a file boundary and lost their leading underscore, as the
    strength planner's six did in item 4: `collect`, `select_runs`, `date_window`,
    `local_time`, `command_path`, `in_window` and `day_bounds`. Three were renamed further
    than the underscore because the bare word was taken or vague — `path` is a local in
    `_follow`, and `window` and `local` say nothing on their own.
  - `DEFAULT_LIMIT` is in `views.py`, not `runs.py`: it is how many runs the listing
    prints, which is a printing decision, and `parser.py` already imports from `views`.
- These stay as they are:
  - `constraints.py` (486), `strength.py` (463) and `queue.py` (421). Each is one job.
  - `strength_only.py` (68). It is its own flow.
  - `heads_up.py`.
  - `revisions.py`. Its name is pinned by a glob in a test.

**A trap in this split — sprung, and the count was right.** After the split, `generate.py`
still imports `ensure_recent_data`. So an unchanged
`patch("…workouts.generate.ensure_recent_data")` in an adapt test still succeeds, but it
patches nothing, and the test silently runs a real pull. All twelve targets must move to
`…workouts.adapt.ensure_recent_data`: `test_cli_workouts` (×7), `test_runway` (×3),
`test_athlete_queue` and `test_workout_tweak`. Of the 25 sites that named it — not the 23
the gate's table in `REORG_execution.md` §5.1 records, which predates some of the tests —
exactly those twelve moved and thirteen stayed with `workout generate`. Each was
shown to bite rather than assumed to: with the twelve pointed at the old path and the body
of `cli/common.ensure_recent_data` made to raise just past its `--no-pull` exit, those
twelve tests failed and nothing else did. Pointed at `adapt`, with the same sabotage in
place, all twelve passed again. The four sites in the same files that do not patch it at
all fail under the sabotage either way: they neutralise the pull one level down, at
`runtime.garmin`.

### 6.6 Front-ends — **DONE: step 1 in Phase D item 9, step 2 in Phase E item 1**

**`cli/bot.py` (~~1,282~~ 1,287 lines) becomes the package `cli/bot/`:**
- `views.py` (about 255 lines; it is 258): the morning push, the week's changes, the
  pickers and the mesocycle page.
- `route.py` (about 105 lines; it is 91, because `ROUTER_INTENTS` left for
  `chat/routing.py` under §4.10 row p and only `ROUTER_SYSTEM_PROMPT` stayed). Under the
  100 line floor and staying there: it is one command, and the only sibling it could merge
  into is `capture.py`, which reads `use_router_model` from it and would land at 442.
- ~~`capture.py` (about 420 lines, including `ROUTABLE_SETTINGS`). To stay strictly under
  400, split the change_setting capture into its own file.~~ **It is 351 and holds the
  change_setting capture, because a different file came out of it instead — see
  `extraction.py` below. `ROUTABLE_SETTINGS` did land here, with `routable_setting`,
  which reads it and had nowhere else to go.**
- `edit.py` (about 330 lines; it is 331).
- `parser.py` (about 170 lines; it is 151). Under the band, as `cli/journal/parser.py` at
  102 already is: it is the argparse wiring its package's other files must not import.
- **`extraction.py` (125), which this section did not name.** What every capture's model
  call shares: the role it opens with, the rows the athlete could mean, the call, and the
  two lanes out of a miss. It is separate because `capture.py` dispatches the five intents
  and therefore imports `edit.py`, while `edit.py` needs those same names — folding them
  into `capture.py` is an import cycle, and `AGENTS.md` says to move the shared code out
  rather than defer an import. Under the 150 line floor, on the rule's own two exceptions:
  it is a concept of its own and it is what breaks that cycle.
- `__init__.py` is 21 lines of docstring.

Its 29 imports hidden inside functions are all hoisted: none of them dodges a cycle. One exception:
`clock.now` should be called as `clock.now()`, so that the `pin_clock` patch still reaches it.
**Four were not hoisted, for a reason this section did not have: three
`from trainmate.openrouter import openrouter_client` and one
`from trainmate.coach.engine.notes import …`. `trainmate_cli` imports this package's
parser, so hoisting any of them puts `requests` on every command's startup path — the
regression Phase D item 4 measured and put back (`ARCHITECTURE.md` §14). Measured again
here: 285 modules and about 105 ms, against 277 and 108 before, and no `requests`. The
other 25 are at the top of their files, and the one `clock.now` among them is called as
`clock.now()`.**

**`trainmate_bot.py` (~~1,613~~ 1,529 lines — Phase C's `sentinels.py` took the four frame
readers out of it) moves into `trainmate/chat/`.** The script stays at its path as
a launcher, because `tm-bot` runs it directly.
- **Step 1, moves only. DONE.** ~~The script drops to about 900 lines.~~ **It drops to
  1,135. The estimate assumed more than the three modules below would leave; what stays is
  `main()` and its closures (about 830 lines), plus `_Session`, the restart teardown, the
  subprocess environment, the reply chunking, the allowlist and the welcome and menu
  cards the handlers print. Step 2 is what takes the rest.**
  - `routing.py` (about 275 lines; it is 232, with the intent table from §4.10 row p).
  - `keyboards.py` (about 195 lines; it is 206). It holds the reply keyboard and what each
    of its labels runs, and the four inline-callback namespaces with their decoders.
  - The pure part of the scheduler: `scheduler.py` (97). Under the floor, and a concept of
    its own — when the push and the nightly reflect are due.
  - `__init__.py` is 11 lines of docstring.
- **Step 2, a real refactor (question 4 in §9). DONE in Phase E item 1.** ~~`main()` is 852
  lines made of 30 closures over 12 shared names.~~ It was 845 lines and 30 closures, and
  the shared names are fourteen, not twelve. `trainmate_bot.py` is 38 lines now: it builds
  `ChatBot` and calls `run()`.
  - ~~It would become a `ChatBot` class, with `runner`, `handlers` and `scheduler` mixins,
    plus `app.py`.~~ **Five mixins, not three.** A single `handlers.py` would have landed
    at about 440 lines, over the band, and it cuts cleanly along the two kinds of update
    Telegram delivers: `messages.py` (232) is what the athlete typed, `callbacks.py` (189)
    is what they tapped. `runner.py` (262) kept one CLI subprocess from launch to exit and
    handed the sending to `replies.py` (222) — the five senders, plus the ✋ Stop button,
    which the same flushes raise and retire. `scheduler.py` went 97 → 175 with its mixin
    beside the arithmetic it drives. `app.py` is 169: the configuration, the client, the
    shared state, and the Application/Updater lifetime.
  - **One module this section did not name: `telegram_api.py` (92).** `tests/test_layering.py`
    says nothing under `trainmate/chat/` may load the telegram library, which is what keeps
    `tm bot route` — spawned once per free-text message — from dragging the front-end onto a
    command line. Moving the process into the package would have broken that, so one file
    names the library and imports it inside each function. Under the 100-line floor, on the
    rule's own two exceptions: a concept of its own, and the thing that holds a layering
    rule true. It also collapsed the six places that built an inline keyboard out of rows
    of (label, callback_data) — five copies of one comprehension, two of them spelling the
    loop variable `cb`, plus the Stop button's single-button form — into one
    `inline_keyboard(rows)`.
  - ~~About 250 test references would move.~~ **Thirty.** `tests/test_bot.py` named 29
    attributes of `trainmate_bot` and `tests/test_runway.py` one. The estimate was out by
    an order of magnitude because `main()`'s closures were unreachable from a test: only
    the module-level helpers around them could be named at all, which is the coverage gap
    the conversion was for.
  - **The welcome and menu cards went to `keyboards.py`, as item 9 said whoever opened this
    file should decide.** They name the reply keyboard's labels one by one, so the comment
    saying "these two are edited together" is gone — they are in the same file now.
    `keyboards.py` is 296.

**Other changes.**
- `trainmate/sentinels.py`, as described in §4.8. `prompt.py` drops to about 275 lines.
- `trainmate_web.py` stays whole, as an exception (§2). It drops to about 680 lines with §4.2.
- ~~`static/app.js`: optionally, cut it into four scripts by tab: common, dashboard, records and
  plan. No build step is needed.~~ **DONE in Phase E item 2, and it is six scripts, not
  four.** No build step was needed, as this line said. The four names were close but two
  of them do not exist as files: `dashboard.js` (286) is the Dashboard tab's own panels
  only, because the strategy card, the mesocycle timeline, the feedback notes and the
  version comparison are one subject and make `plan.js` (374) on their own — leaving them
  in would have put `dashboard.js` past 650. `records.js` (290) is Benchmarks, Learnings
  and History, none of which is big enough for a file (57, 80 and 142 lines). The two the
  list did not name are `workouts.js` (307), the session cards with compare and the change
  log, and `progress.js` (174), the time-in-zone tables with the timeline PNG.
  `common.js` (103) is what they share. `ARCHITECTURE.md` §8 carries the load-order
  rules and §15 the reasoning.

### 6.7 Training analytics: a new package `trainmate/analytics/`

The package gets an **empty** `__init__.py`. A garmin-style re-export would load the heavy report
module whenever someone imports the light zone model.

**`intensity.py` (1,019 lines) becomes three files.**
- `intensity.py` (about 440 lines): the zone model, the per-sport sums, the currency choice, and
  the zone target on a session.
- `zone_tables.py` (about 210 lines): the zone tables, at prompt width.
- `mesocycle_report.py` (about 375 lines): the text report for one mesocycle.

After the split, `intensity` imports only `config` and `sports`. Eight modules only want the zone
target: the Calendar code, `coach/formatting`, `coach/revisions` and the CLI session line among
them. They stop loading the report.

**`progression.py` (783 lines) and `timeline.py` (48 lines) become three files.**
- `progression.py` (about 395 lines): the day series with the PMC fold, and the weekly aggregates.
- `timeline.py` (about 325 lines): the bands, the warnings, the assembly, the row fetch, and the
  clipping.
- `runway.py` (about 140 lines): `plan_end`, `plan_gap` and `runway`.
  - It pairs with `cli/runway.py`: the detector here, the wording there.
  - Three copies of the "the plan ends here" rule go into it.

**Other contents of the package.**
- New files: `load.py` and `pmc.py` (§4.1), `compare.py` (§4.2) and `weekly_evidence.py` (§4.10).
- These move in unchanged: `adherence.py` (440 lines, one job), `chart.py` and `baselines.py`.

**Outside the package.**
- `plan_diff.py` and `plan_lineage.py` merge into one flat `plan_versions.py` (about 350 lines).
  Both are about versions of the periodization and both take a database handle. It stays outside
  `analytics/` because it does no training maths.
- `sports.py` and `benchmarks.py` stay flat. They are vocabularies that the database and the coach
  import.

### 6.8 Integrations

**The Calendar code becomes the package `trainmate/gcal/`,** mirroring `garmin/`. Its `__init__.py`
holds only a docstring.
- `gcal/event.py` (about 270 lines): what a workout's event says.
  - The tags, the labels and `event_url`.
  - The 150 text-building lines of `sync_workout`, as `event_body(workout, adherence)`.
  - It has no Google imports.
- `gcal/client.py` (about 390 lines): `CalendarSyncer` and `sync_calendar_signals`.
  - `CalendarSyncer` writes, lists and deletes events, and syncs signals in both directions.
  - No instance is built at import (§4.6).
  - The `delete_workout_event` alias goes. Nine test assertions change to `delete_event`.
- `gcal/reconcile.py` (about 240 lines): `calendar_reconcile.py`, plus the adherence marking loop
  (§4.2).
- `gcal/history.py` (169 lines): `calendar_lineage.py`, unchanged.
  - Its `_load` becomes the one function that writes the "Duration | TSS | RPE" line.
  - `google_calendar.py:145–160` renders the same line today.

**Other changes.**
- `calendar_state.py` becomes the flat `workout_state.py` (§4.3). It does not go into `gcal/`.
- `garmin/` keeps `client`, `sync` and `derived` (§4.1). `_safe_round` moves to `sync.py`.
- `signals.py` stays flat. `config.py` imports it, so it must stay light.
- Two duplicates to merge:
  - the refresh throttle (`garmin/sync.py:258–268` and `google_calendar.py:548–565`);
  - reading an event's date (`google_calendar.py:400–401` and `calendar_sync._event_day`).

### 6.9 Strength — **DONE in Phase D item 4**

**`planner.py` (737 lines, not 724) becomes two files.**
- `planner_prompt.py` (365, not the ~345 estimated): `SYSTEM_PROMPT`, the prompt builders and
  the reply checks.
- `planner.py` (394, not ~380): the pass, the call, folding the answers in, and the write.
  - `_ask` and `_complete` stay here, because tests patch them.
  - Only a few references in `test_strength_planner.py` and `test_prompt_gates.py` change.
    Seven and two.
- **Two things the list above left out, and both halves read them.** The `Session` record —
  one session the call was asked about — is what the pass builds and what the prompt's
  session block is written from. And `_moved_on`, the rule saying a session's brief or
  duration changed since its sets were written, is asked by the prompt (to tell the model to
  write it again) and by the fold-in (to let that answer through). Both went to
  `planner_prompt.py`, `_moved_on` as a `Session.moved_on` property so the rule sits on the
  record it asks about rather than straddling the two files. Six names lost a leading
  underscore because they now cross a file: `Session`, `Answer`, `system_prompt`,
  `user_content`, `clean_session` and `same_rows`.

**Other changes.**
- `vocabulary.py` (86) and `prescription.py` (84, not 85) stay. Both are real concepts on their
  own, and `prescription.py` also breaks a cycle between `history.py` and `planner.py`. Left
  alone.
- The two OpenRouter imports hidden inside functions move to the top of their files.
  **One done, one declined.** `planner._complete` is hoisted: everything that reaches
  `strength/planner.py` has loaded the model client already. `questions.propose` keeps its
  import inside the function, and §7's "imports hidden inside functions" list is wrong to
  leave it out. `athlete_queue.py` imports `strength/questions.py`, six CLI modules import
  `athlete_queue`, so hoisting it put `requests` on every command's startup path and took
  `import trainmate_cli` from 107 ms and 254 modules to 201 ms and 542. It also made the
  three lazy OpenRouter imports §7 *does* exempt — `settings.py:133` and two flag-guarded
  sites in `trainmate_cli.py` — buy nothing at all. The rule is in `ARCHITECTURE.md` §14
  now, so it outlives this file.
- `sets.py` is 380 lines, not 384. If it ever passes 400, cut it at line 290.
- The `__init__.py` docstring is out of date and should list every file. **Done**, all seven.

### 6.10 Infrastructure

**`util.py`** is split and deleted, as described in §4.7.

**`config.py` (710 lines).**
- The plan-input block leaves (§4.4). That brings it to about 590 lines.
- Then trim the docstrings that restate rationale (221 lines of them). That brings it under 500.
- Drop the `replan_hard_span_days` fallback (`config.py:268–271`) with a one-off edit to the
  config file.

**`journal.py` (649 lines).** Keep it whole and trim its docstrings. If it is still over 500
afterwards, split it into the writer (about 430 lines) and the day files (about 230).

**Other changes.**
- `settings.py` and `clock.py` read `runtime.db` instead of doing `from trainmate.db import db`
  inside functions (six places). **Done in Phase D item 3, and it was seven places, not six:
  `llm_models.py` has one too. Three `scripts/` did it at module scope as well.**
- These stay flat: `queue_kind` (the cycle breaker), `athlete_queue`, `heads_up`,
  `learning_doubts` and `runtime`.
- Pick one way to reach the config: 42 files import `config` directly, and 3 use `runtime.config`.

---

## 7. Delete first — **DONE in Phase A, with two corrections**

**Dead code.** Nothing in production calls any of these.
- `coach/formatting.format_planned_workouts`.
- `llm_models.stored_model`.
- `db.get_next_mesocycle` and `db.get_prescribed_sets`. Both gone; §6.3 no longer asks again.
- `cli/common.resolve_cleanup_range`.
- ~~The `delete_workout_event` alias.~~ **Wrong: it has two production callers**,
  `calendar_reconcile.py:169` and `cli/workouts/calendar_sync.py:79`. Kept.
- ~~`calendar_reconcile.no_calendar_sync`.~~ **Kept.** No production path enters it and the
  `--no-sync` flag its docstring cited is gone, but twelve test lines in `test_calendar.py` and
  `test_cli_workouts.py` use it to write fixture state without the write path reconciling first —
  which is what lets those tests ask `_plan` a question it has not already answered. The
  docstring now says that instead.
- `strength/sets.ATHLETE`, and the `history.SETS_NOT_READ` alias. The alias had one reader, in
  its own module; that read names `sets.SETS_NOT_READ` now.
- Unused imports:
  - `math` and `time` in `garmin/load.py`;
  - `import trainmate.garmin as _g` in `garmin/pmc.py`;
  - `config` and `_today_date` in `coach/service/__init__.py`.
- About 70 unused imports in `trainmate_cli.py`: every `run_*` in lines 57–89 and 104. The dead
  re-exports in `cli/workouts/__init__.py` go with them.

**Production code that only tests call.** Decide item by item:
- `replan()` (`service/planning.py:715–745`). It is the only reason `plan_generate` defaults to
  `auto_apply=True`, and about 30 test calls rely on that default.
- `_get_coach_system_prompt`, `recompute_all_confidence`, `get_workout_revision`,
  `get_strength_check` and `wipe_metrics`.

**Imports hidden inside functions. Not done, and deliberately left for the phase that moves the
code.** About 84 of the 102 can go. They either dodge no cycle, and the surveys checked each file,
or a move in §4 removes their reason — and hoisting one now, then moving the file in Phase C or D,
is the same edit twice. Move them to the top of the file, in the phase that moves the file. These
stay where they are:
- the eight builders in `runtime.py`, which is the one sanctioned lazy place;
- the four imports in the pair between `llm_models` and `settings`, and `settings.py:133`
  (OpenRouter, on the coach-model hook);
- the three in `prompt.py`, which keeps its top-of-file imports to the standard library;
- the two OpenRouter imports behind a flag in `trainmate_cli.py`;
- `garmin/client.py:52` (the optional `garminconnect` package) and `chart.py` (the optional
  matplotlib). The count of 102 does not include these two, because they are not `trainmate`
  imports.

**Stale docs.** All fixed in Phase A.
- The patch targets in the `coach/__init__.py` docstring — the whole docstring was rewritten
  with §4.5.
- The `cli/__init__.py` docstring, and the `prompt.py` one, which said `cli.prompt`. Both name
  `trainmate.runtime` now.
- The path at `trainmate_web.py:245`, which named a file that became a package.
- ARCHITECTURE §7, where it said `trainmate_cli` owns the singletons. §2 and §6 were already
  correct; §3 was rewritten with §4.5.

---

## 8. Order of work

**`REORG_execution.md` §7 is the live version of this list, and its §8 is the ledger.** It revises
what follows in three places — `util.py` moves earlier, Phase D is one commit per file split, and
a phase is one commit — and it records what has landed. Read it, not this section, before starting.

Each phase is one commit. After it, the full suite passes under the memory cap.
ARCHITECTURE.md is updated in the same commit as the code it describes. Implemented DESIGN files
get their paths amended. Designs still in progress are left alone, so their paths go stale until
they are implemented.

1. **Clean-up with no moves. DONE**, as Phase A there, with the gate test and the conventions
   ahead of it.
   - The deletions in §7.
   - Empty `coach/__init__.py` (§4.5).
   - Stop building the Calendar client at import (§4.6).

   Low risk. It makes every later diff smaller.
2. **The four behaviour fixes (§5).** Each gets a test that plays out its story. They come before
   the moves, so that a move never hides a change of behaviour.
3. **The moves between subsystems.**
   - The load and PMC maths (§4.1) and the compare code (§4.2).
   - `workout_state.py` and the web import test (§4.3).
   - `plan_inputs.py` and the staleness mixin (§4.4).
   - `sentinels.py` (§4.8).
   - Printing out of the service (§4.9), and the smaller moves (§4.10).

   After this phase, the web app loads no CLI, coach or Google code.
4. **File splits,** one commit per subsystem. Start with the modules that import the fewest
   others:
   1. analytics
   2. integrations
   3. database
   4. strength
   5. coach/engine
   6. coach/service
   7. CLI command families
   8. CLI views, with `render` last, since it imports from all of them
   9. front-ends
5. **Split and delete `util.py`,** and update AGENTS.md (§4.7). This is a codemod over about 80
   files. It is best done alone, so that its diff is nothing but import changes.
6. **Optional.**
   - The `ChatBot` class.
   - The `app.js` split.
   - Splitting the test files.

**The test files follow the code.** The biggest ones are each a single class:
- `test_periodization.py`: 2,891 lines. `TestPeriodization` alone is about 1,650.
- `test_cli_workouts.py`: 1,699 lines.
- `test_adaptation_adapt.py`: 1,505 lines.

Split a test file when the code it covers splits. For example, `test_cli_workouts.py` becomes one
file per workout command. The same 500-line rule applies, at lower priority.

**Traps the surveys found.**
- **Patches that silently miss.** A patch on a name the old module still imports patches nothing.
  One example is `ensure_recent_data` (§6.5). `trainmate.util.notice` already patches nothing
  today.
- **Engine lookups.** The engine's new files must look up `_eng.openrouter_client` at call time.
- **The service clock.** The service's new files that read the clock need the `_svc` back-import,
  unless the clock patches move to `pin_clock`.
- **Tests keyed on file names.** Re-key each one on a shape, such as a directory or a prefix, in
  the same commit as the move:
  - the `ALLOWED` set in `test_simple_render`;
  - `APPEND_PATH_MODULE` in `test_workout_revisions`;
  - the `workouts/revisions*.py` glob in `test_service_invariants`;
  - the `runway.py` exemption in `test_runway`;
  - the `util.py` exemption in `test_utils`;
  - the read-only grep in `test_web`.
- **Mixin method names.** A method name must stay unique across a class's mixins, or one method
  silently hides the other. No name clashes today.
- **Per-file test runs.** A module that binds no test database of its own fails alone, because
  it relies on an earlier module in the full run having bound one. `test_dispatch` is the
  example. Run the full suite.

---

## 9. Questions for you

**All five were answered on 2026-09-20 — see §0.** They are kept
here as the record of what was asked.

1. **Squash the one-off migrations in `db/schema.py`?**
   - The schema halves, from 815 lines to about 470, and about six migration tests go.
   - Afterwards the code cannot upgrade an old database file. That includes the
     `trainmate.db.pre-revisions-…` and `.klausenpass` backups at the repo root.
   - If you never restore those backups, squash.
2. **Fix the four behaviour differences in §5?** For §5.3, which rule decides where a goal's span
   starts?
   - After the previous goal **that has a plan**, as `plan generate` does today.
   - After the previous goal **of any kind**, as the constraint replan does today.

   I lean to the first. The replan should rebuild the plan that actually holds the disrupted days.
3. **Delete `util.py`?** It changes one line of AGENTS.md (the `wrap_text` rule names
   `trainmate/util.py`).
4. **When should the bot's `main()` become a `ChatBot` class?** In phase 4, or later as its own
   job?
5. **Package names.**
   - `trainmate/chat/` for the Telegram process. `trainmate/bot/` would sit confusingly next to
     `cli/bot/`.
   - `gcal/` for Calendar.
   - `analytics/` for the maths.

---

## Appendix: the layout after this proposal

```
trainmate_cli.py              launcher (unchanged role)
trainmate_bot.py              launcher → trainmate.chat
trainmate_web.py              read-only API (exception to the size rule)
trainmate/
  analytics/                  pure training maths, empty __init__
    load.py pmc.py adherence.py compare.py intensity.py zone_tables.py
    mesocycle_report.py progression.py timeline.py runway.py chart.py
    weekly_evidence.py baselines.py
  chat/                       the Telegram process: routing keyboards scheduler (+ app handlers
                              runner if §6.6 step 2)
  cli/
    plans/ render/ bot/ workouts/ data/ journal/     packages, one file per command or topic
    progress.py progress_load.py progress_zones.py status.py common.py selectors.py
    argparse_ext.py (dashless.py) staleness.py runway.py candidates.py
    goals.py constraints.py signals.py benchmarks.py learnings.py queue.py settings.py strength.py
  coach/                      __init__ is a docstring
    engine/   prompt planning analysis generate adapt sessions notes
    service/  generate standing guards adapt revision_apply matching planning goals_constraints
              staleness athlete_context history_context mesocycle_context analysis
    formatting.py honoring.py proposals.py revisions.py
  db/         base schema workout_change workouts workout_history periodization mesocycles
              learnings activities strength objectives constraints wipes queue signals benchmarks
  garmin/     client sync derived
  gcal/       client event reconcile history
  strength/   vocabulary sets questions history prescription planner planner_prompt
  config.py settings.py clock.py runtime.py journal.py text.py output.py prompt.py sentinels.py
  types.py sports.py benchmarks.py signals.py llm_models.py openrouter.py plan_inputs.py
  plan_versions.py workout_state.py athlete_queue.py queue_kind.py heads_up.py
  learning_doubts.py learning_confidence.py
```
