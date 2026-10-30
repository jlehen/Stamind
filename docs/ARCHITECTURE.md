# Stamind Architecture & System Manifest

This is the map a coding agent reads before its first grep; `AGENTS.md` (under *Code*)
says what it holds and what it does not. Each concept has one home here, and the other
sections point at it. The *why* lives in the `DESIGN_*.md` files, and
[§15](#15-design-rationale--history) holds the decisions with no design doc of their own.

## Contents

1. [System Overview](#1-system-overview)
2. [Module Map](#2-module-map) · [Change recipes](#change-recipes-where-to-edit-for-a-given-task)
3. [coach Package Architecture](#3-coach-package-architecture)
   · [CoachEngine](#coachengine) · [CoachService](#coachservice)
4. [Database — Key Patterns](#4-database--key-patterns)
5. [Database Schema](#5-database-schema) — [workouts](#workouts) · [Workout state: three axes](#workout-state--three-orthogonal-axes-not-one-enum) · [other tables](#completed_activities)
6. [Singletons](#6-singletons)
7. [CLI Commands Reference](#7-cli-commands-reference)
8. [Web API Endpoints](#8-web-api-endpoints)
9. [Configuration (`config.yaml`)](#9-configuration-configyaml)
10. [Key Data Flows](#10-key-data-flows) — [Plan gen](#plan-generation-plan-generate) · [Workout gen](#workout-generation-workout-generate) · [Adaptation](#daily-adaptation-workout-adapt) · [Data pull](#data-pull-data-pull-and-auto-ensure) · [Analysis](#data-analysis-data-bootstrap--data-reflect)
11. [Terminology: Plans vs. Workouts](#11-terminology-plans-vs-workouts)
12. [Sports Science & Coaching Mathematics](#12-sports-science--coaching-mathematics)
13. [Daily Signals (Calendar Ingest)](#13-daily-signals-calendar-ingest)
14. [Testing](#14-testing)
15. [Design Rationale & History](#15-design-rationale--history)
16. [Gym Logger (Telegram Mini App)](#16-gym-logger-telegram-mini-app)
17. [Calendar (Telegram Mini App and `sm calendar`)](#17-calendar-telegram-mini-app-and-sm-calendar)

---

## 1. System Overview

Stamind is a local AI sports-science coaching application. The user
configures goals and constraints; Stamind generates periodized training plans
(macrocycle → mesocycles) and workout schedules (microcycles), then adapts them
daily based on Garmin metrics. The sessions can be pushed to Google Calendar.

```
  +--------------------------------------------------+
  |               User Interface Layer               |
  |  stamind_cli.py (dispatcher) + stamind/cli/  |
  |  stamind_web.py (Flask)                        |
  |  stamind_bot.py (Telegram → CLI subprocess)    |
  +---------------------------+----------------------+
                              |
  +---------------------------v----------------------+
  |               Coaching Logic Layer               |
  |  stamind/coach/service/ ─ CoachService          |
  |    │ orchestrates DB + calendar + LLM calls       |
  |  stamind/coach/engine/  ─ CoachEngine           |
  |    │ pure logic: prompt building, hash, LLM calls │
  |  stamind/coach/formatting.py (pure helpers)    |
  |  stamind/openrouter.py  (OpenRouter LLM client) |
  |  stamind/plan_inputs.py (what shapes a plan)    |
  |  stamind/plan_versions.py (which versions, and  |
  |    what changed between two)                      |
  +---------------------------+----------------------+
                              |
  +---------------------------v----------------------+
  |              Training Maths Layer                |
  |  stamind/analytics/                             |
  |    load pmc compare weekly_evidence adherence     |
  |    intensity zone_tables mesocycle_report         |
  |    progression timeline runway chart baselines    |
  |    rows in, numbers out: opens no database        |
  +---------------------------+----------------------+
                              |
  +---------------------------v----------------------+
  |              Data & Integration Layer            |
  |  stamind/db/              (SQLite CRUD)        |
  |  stamind/garmin/          (Garmin direct pull) |
  |  stamind/gcal/            (Calendar sync)      |
  +--------------------------------------------------+
```

---

## 2. Module Map

Every module exposes one **singleton** at module level (see [§6](#6-singletons) for
the list). UIs and tests import the singleton directly — never instantiate the
classes themselves.

### Entry Points

- **`stamind_cli.py`** — the argparse dispatcher (`main()`) and its helpers, no business
  logic. Singletons live in `stamind/runtime.py` ([§6](#6-singletons)), which handlers read
  directly, so nothing under `stamind/` imports this module. `run_once` is the one path
  `main` and the REPL share: it brackets the command with a journal run (DESIGN_logging.md
  §3) and ends with `page_files.sync.after_command`, the pages' upload
  ([§17](#17-calendar-telegram-mini-app-and-sm-calendar)).
- **`stamind/cli/`** — one module or package per command family, handlers named `run_*()`:
  `status`, `calendar`, `goals`, `constraints`, `benchmarks`, `signals`, `learnings`,
  `settings`, `strength` (with `strength_log` and `strength_ingest`), `queue` (what shows
  and sends a queued item) with `queue_commands` (the `queue` and `bot queue` commands,
  apart because the commands a tap runs import the queue), `progress` (with
  `progress_load` and `progress_zones`), and the packages `plans/`, `workouts/`, `data/`,
  `journal/` and `bot/`, the hidden commands the Telegram bot spawns, whose `__init__.py`
  maps its files (DESIGN_bot_simple_frontend.md §12). Shared by several families:
  `common` (the renderers), `selectors` (the range grammar) with `windows` (the resolvers
  that turn it into dates), `argparse_ext`, the `render/` package (the two voices and the
  companion line builders, [§6](#6-singletons)), `candidates` (the questions that turn a
  note's constraints and signals into rows, and the `session_note`, `constraint` and
  `signal` queue kinds), `staleness` (the changed-input wording) and `runway` (the
  end-of-schedule nudge every daily surface draws, DESIGN_runway_nudge.md §3).
- **`stamind_web.py`** — Flask REST API behind the dashboard. **Read-only**: GET
  handlers over `db` and the shared pure modules, no writes, no Garmin, no LLM, no
  Calendar ([§8](#8-web-api-endpoints)).
- **`stamind_bot.py`** — the Telegram chat front-end, launched by `./sm-bot`. It builds
  `stamind.chat.app.ChatBot` and calls `run()`; everything else is the `stamind/chat/`
  package, whose `__init__.py` maps its files: `app` (`ChatBot`, the shared state,
  `_serve`), `runner` (one CLI subprocess per place of a chat), `replies` (what goes back
  into the chat), `messages` and `callbacks` (a message, a tap), `routing` (the intent
  table and what each intent runs), `keyboards` (every button drawn and every tap
  decoded), `scheduler` (the push, the nightly reflect, the queue's wake), and beside it
  `stamind/sentinels.py` (the `\x1e` line protocol between the CLI and the bot, both ends
  in one file). No module in the package imports `python-telegram-bot`: `telegram_api`
  names the library inside each function (`tests/test_layering.py` holds the rule), which
  is what lets `sm bot route` read the intent table on a command line and
  `tests/chat_harness.py` drive a real `ChatBot` against stand-ins.

  What the bot does, and where each rule is written:
  - **A message is a CLI command line**, run through `stamind_cli.py` as a subprocess
    (`STAMIND_FRONTEND=json`, `STAMIND_RENDER=simple`). A leading `/` is the line as
    typed, a keyboard label runs fixed argv, and other text is classified by `sm bot
    route` (`routing.ROUTER_INTENTS`; the fast model picks an intent, never argv). Prose
    comes back as text; a prompt, a chart, a button row, a flush and a queued item come
    back as sentinel frames (`sentinels.py`, [§6](#6-singletons)). Every Telegram call but the
    poll goes through `telegram_api.retrying_request` (DESIGN_telegram_send_retry.md §2).
  - **Two places per chat**: its own, one command at a time, and a long run beside it, one
    that asks the week planner (`runner.py`; DESIGN_long_runs_beside_chat.md §2, §7).
    Polling never pauses, so `/cancel` and `/restart` reach the bot while a command
    computes; `_serve` drives the Updater by hand, which is why it sets the command menu
    itself (`_set_command_menu`: the library calls `post_init` only from `run_polling()`).
    The timeouts are `telegram.prompt_timeout_seconds` and
    `telegram.command_timeout_seconds` ([§9](#9-configuration-configyaml)).
  - **Self-restart.** `./sm-bot` supervises a worker and relaunches it on exit 75
    (`RESTART_EXIT_CODE`, a contract between `sm-bot` and `chat/runner.py`) or 129, a
    worker killed by SIGHUP (DESIGN_bot_restart.md §4, §5).
  - **The companion** (DESIGN_bot_simple_frontend.md): the reply keyboard is
    `keyboards.SIMPLE_KEYBOARD`; writes reach the chat through three shapes and no
    fourth, view, picker and capture, which `cli/bot/__init__.py` names (§12 there). In
    the chat a capture saves its read-back as a *confirmation* in the athlete queue and
    ends, and a "Yes" that stored a constraint or found nothing is followed by its own
    question, "Shall I adjust your week?" or "Shall I pass it to your coach?", whose "Yes"
    starts `workout adapt` beside the chat (DESIGN_chat_questions.md §2, §4). The voice
    is `runtime.render` ([§6](#6-singletons), DESIGN_render_persona.md).
  - **The morning push** is `sm bot morning` (`cli/bot/views.py`), run by `scheduler.py`
    inside the `morning-time` → `morning-deadline` window and idempotent on the
    `settings` row `push_morning_last` (DESIGN_bot_simple_frontend.md §4.2, §4.3); the
    proposal it saves is DESIGN_waiting_proposal.md §5.
  - **Short messages**, where the pages are published: a proposal is one message, its short
    text above "Shall I make these changes?"; a day the chat draws (the morning message,
    "📅 Today", today after a proposal's answer) shows each session's short line. Under
    either, "🔎 Tell me more" opens `miniapp/details.html`: a page button
    (`telegram_api.PAGE_CELL`), never the live row, kept under its message, never journalled
    (`cli/render/proposal_lines.py`, `page_files/sync.py` `page_button`/`day_button`,
    DESIGN_short_messages.md §3–§6).
  - **The athlete queue** travels as `SM-QUEUE` (`cli/queue.py`); a tap runs `sm bot
    queue <id> <action>` (`cli/queue_commands.py`), which applies the action and sends
    the next item, and the buttons carry `q:<id>:<action>` so the bot stores nothing
    (DESIGN_athlete_queue.md §6.2, §13). A tap whose answer queued a question is followed
    by it, and an answer may put its own item off until the next morning
    (`queue_kind.PutOff`, DESIGN_chat_questions.md §6).
  - **A change made out of the athlete's sight** is told by the hidden `bot changes`
    before any push or reply; the rule is `stamind/heads_up.py`
    (DESIGN_change_heads_up.md).
  - **The nightly reflect**: the first wake after 03:00, Wednesday to Sunday, starts
    `data reflect --auto` as a process outside the chat (DESIGN_learning_doubt_nudge.md
    §3.1).

### Package `stamind/`

One line per module; the rule each keeps is the part worth knowing before opening it.

| File | Singleton | Purpose |
|---|---|---|
| `types.py` | — | TypedDicts: `Objective`, `Constraint`, `DailySignal`, `Workout` (the hydrated session, not a table row, §5), `CompletedActivity`, `AthleteMetric`, `AthleteBaseline`, `Macrocycle`, `Mesocycle`, `PlanFeedback` |
| `config.py` | `config` | Reads `config.yaml`; typed properties |
| `runtime.py` | the lot | The lazily built singletons every handler reads ([§6](#6-singletons)) |
| `prompt.py` | `runtime.prompt` | The prompt broker: `confirm`/`choose`/`ask_text` over `TtyPrompt` or `JsonPrompt`, journalling every answer (DESIGN_logging.md §5.6); `athlete_watching()`, true only for a run the bot started (DESIGN_change_heads_up.md §6) |
| `sentinels.py` | — | The CLI↔bot line protocol, both ends in one file (above). Standard library only |
| `output.py` | — | Which tier a message belongs to, and so who sees it: `print`, `aside` (terminal only), `step` (prints and journals), `warn`/`fail` (always print, journal), `notice` (the athlete's own data, never journalled), `Progress` and `Spinner` (DESIGN_output_verbosity.md, DESIGN_logging.md §5) |
| `text.py` | — | How a line looks: colours, `cmd`, `wrap_text`, `render_table`, the width budgets. Decides nothing about whether a line prints |
| `clock.py` | — | The athlete's time: `now`, `to_local`, `today_date`/`today_str` (no other module calls `date.today()`), the one date renderer `fmt_date`/`fmt_span`/`fmt_timestamp`, and the ISO arithmetic (DESIGN_user_timezone.md) |
| `journal.py` | — | The run journal, `logs/runs/YYYY-MM-DD.jsonl`: the writer, the run stack, the reader, retention, `llm_durations`. Imports only `config`; file names and `ts` are UTC because asking `clock` would open the database (DESIGN_logging.md §4) |
| `settings.py` | — | The preference registry: one `Setting` per runtime knob with its validator, and the one resolver over the stored row, `config.yaml` and the default; the single writer of `settings` rows (DESIGN_settings.md) |
| `llm_models.py` | — | Which model to query: the `llm.models` menu and the stored choice (`list_models`, `active_model`, `resolve_token`, DESIGN_model_selection.md) |
| `openrouter.py` | `openrouter_client` | The OpenRouter client: `json_object` replies, the last of two objects wins; prints the wait notice and the flush before every call |
| `sports.py` | — | The canonical sport vocabulary (`SPORT_MAPPING`, `canonical_sport`, `STRENGTH_SPORTS`); dependency-free so `db` and adherence share it |
| `plan_inputs.py` | — | What shapes a plan and how it is fingerprinted and diffed (`plan_profile`, `plan_config_hash`, the goal and constraint cleaners). Flat and pure so the dashboard hashes the config without the coach; the judgment is `coach/service/staleness.py` (DESIGN_plan_staleness.md) |
| `plan_versions.py` | — | A plan's versions and what changed between two: `plan_lineage` (by macrocycle id, never a date query, DESIGN_plan_rollback.md §6.1), `resolve_versions`, `diff_plans`, `input_snapshots`. Format-free; `plan diff` and `/api/plan/diff` both render it |
| `workout_state.py` | — | Two of a session's three axes ([§5](#workout-state--three-orthogonal-axes-not-one-enum)): `modification_markers` and `calendar_status`; derived from a row, no database, so the web app can import it |
| `learning_confidence.py` | — | What a learning's confidence means: the levels, `derive_confidence`, `step_down`, dormancy. Pure rules (DESIGN_evidence_based_confidence.md §3) |
| `learning_doubts.py` | — | The `learning` queue kind and `settle_doubts`, which every reflect and bootstrap calls (DESIGN_learning_doubt_nudge.md) |
| `athlete_queue.py` | — | The queue of questions and messages for the athlete: `KINDS`, the line, what is out, and the check the scheduler makes on a wake (DESIGN_athlete_queue.md). Rows in `db/queue.py`; shown and sent by `cli/queue.py`; the commands in `cli/queue_commands.py` |
| `queue_kind.py` | — | What a feature brings to the queue: `Kind`, `queue(kind, subject, payload)`, `queue_replacing` (a confirmation that closes an older one about the same row), `NotApplied` and `PutOff` (what an answer raises to leave its item waiting, or to put it off until the morning). Apart from `athlete_queue.py` to break the cycle through `strength/sets.py` |
| `heads_up.py` | — | Telling the athlete about a change made out of their sight: the wording, the send rule (`due`, `changes_due`, `sends_after_delay`), `changes_notify_upto` (DESIGN_change_heads_up.md). Pure but for `waiting()`/`changes_due()`, so `db/workout_change.py` imports it safely |
| `freshness.py` | — | How fresh is fresh enough, for Garmin and the Calendar: `last_pull_age`, `fresh_notice`. Flat because `garmin/` and `gcal/` must not import each other; the decision stayed with each caller ([§15](#15-design-rationale--history)) |
| `cycle_records.py` | — | The date check: which retrospective records exist, when one is due, how one reads (DESIGN_cycle_retrospective.md §3). Rows in `db/retrospectives.py` |
| `retrospective_question.py` | — | The `retrospective` queue kind (DESIGN_cycle_retrospective.md §4) |
| `calendar_days.py` | — | The one list of days the calendar page and `sm calendar` draw: `gather` → a `Calendar` of `Day`s, facts only, reads and never pulls (DESIGN_calendar_miniapp.md §4) |
| `timeline_rows.py` | — | The one row fetch behind `sm progress` and `/api/timeline.png`; outside `analytics/` because it reads the database |
| `benchmarks.py` | — | The fitness-test anchor kinds per sport (`SPORT_ANCHORS`, `anchors_for_sport`) ([§5](#benchmark_results)) |
| `signals.py` | — | The daily-signal vocabulary and `write_signal_days` ([§13](#13-daily-signals-calendar-ingest)) |
| `science/` | — | The shipped science guidelines the prompts quote ([§3](#3-coach-package-architecture)) |
| `db/` | `db` | SQLite, `Database` composed from per-domain mixins. The only write path onto `workouts` is `workout_change.py`; a session as it stands is `workouts.py`, its lineage and change log `workout_history.py`; `schema.py` the DDL, `base.py` the connection |
| `coach/` | `coach_service` | `service/` (`CoachService`: reads the database, orchestrates, prints), `engine/` (`CoachEngine`: the prompts and the model call), `formatting.py`, `honoring.py` (`honored_at`: who may stamp it, `needs_a_pass`, DESIGN_constraint_honoring.md), `proposals.py` and `revisions.py` (the frozen proposals and the pure helpers behind one), `picture.py` (what a `workout adapt` run saw, kept in the `settings` row `adapt_last_seen` so the morning push can tell what is new: `take`, `news`, `nights`, `remember`, DESIGN_quiet_morning.md §3, §4) ([§3](#3-coach-package-architecture)) |
| `analytics/` | module functions | Training maths over rows the caller fetched: opens no database, calls no model (`tests/test_layering.py`). `load.py` (the load model), `pmc.py` (CTL/ATL/TSB), `adherence.py` and `compare.py` (the verdict on a planned session), `intensity.py`, `zone_tables.py` and `mesocycle_report.py` (time in zone, DESIGN_intensity_distribution.md), `progression.py`, `timeline.py` and `chart.py` (the progress timeline, DESIGN_progress_timeline.md), `runway.py` (DESIGN_runway_nudge.md §2), `weekly_evidence.py`, `baselines.py`. `__init__.py` re-exports nothing |
| `garmin/` | module functions | `client.py` (login, fetch), `sync.py` (`pull`, `ensure_data`, the `sync_state` watermark, the Calendar ride-along, §13), `derived.py` (where a handle meets the maths: `recompute_derived`, `backfill_tss`, `warmup_cutoff`). `__init__.py` still re-exports everything: debt, not precedent (AGENTS.md) |
| `gcal/` | `CalendarSyncer` | Google Calendar, both ways: `event.py` (what an event says, no Google import), `history.py`, `client.py` (the only file that calls the API), `reconcile.py` (the pass after every change, DESIGN_workout_revisions.md §8); `__init__.py` maps them and re-exports nothing ([§15](#15-design-rationale--history)) |
| `strength/` | — | Strength tracking (DESIGN_strength_tracking.md): the exercise table (`vocabulary.py`, DESIGN_exercise_table.md), Garmin's sets (`sets.py`), the strength planner (`planner.py` + `planner_prompt.py`, §9), the gym logger's payloads (`logger.py`, §16), planned against done (`comparison.py`, DESIGN_strength_planned_vs_done.md); `__init__.py` maps the rest. Rows in `db/strength.py` |
| `page_files/` | — | The pages' encrypted files in a bucket (DESIGN_miniapp_storage.md): `recipe.py`, `bucket.py`, `sync.py` (`after_command`, `page_button`, `data publish`/`unpublish`); `__init__.py` maps them |
| `chat/` | `ChatBot` | The Telegram front-end (above) |

### Change recipes (where to edit for a given task)

Start here when you know *what* you want to change but not *which files*. The data
flow for each lives in [§10](#10-key-data-flows).

| To change… | Edit these |
|---|---|
| Daily adaptation logic | `coach/service/adapt.py:workout_adapt*`, `coach/engine/adapt.py:_workout_adapt_logic`, `coach/formatting.py` ([§10](#daily-adaptation-workout-adapt)) |
| Plan / strategy generation | `coach/service/planning.py:plan_generate`, `coach/engine/planning.py:_plan_generate_strategy` ([§10](#plan-generation-plan-generate)) |
| Plan version comparison / display | `stamind/plan_versions.py`, `cli/plans/versions.py`, `/api/plan/diff` in `stamind_web.py`, `static/plan.js` |
| Plan feedback (the athlete's notes on the plan) | `db/periodization.py` (`*_plan_feedback`), `cli/plans/feedback.py`, `cli/selectors.py:resolve_meso_atom`, `coach/service/planning.py` (the `plan generate` gate), `coach/engine/planning.py` (the prompt section). DESIGN_plan_feedback.md |
| What the athlete said about a session | `coach/engine/notes.py:note_session_task`, `cli/workouts/adapt.py:_note_candidates`, `cli/candidates.py:keep_note` (the `session_note` kind), `db/workout_history.py:add_session_note`, `db/workouts.py:_session_note_rows`, `coach/formatting.py:athlete_note_lines`, `coach/engine/sessions.py:athlete_words_task`, `coach/engine/generate.py` (`spoken_workouts`), `strength/history.py:_notes_by_day`, `cli/workouts/listing.py`, `cli/render/session_lines.py:simple_day_lines`. DESIGN_session_notes.md |
| Workout generation span | `coach/service/generate.py:workout_generate`, `cli/workouts/generate.py:_resolve_span`, `cli/workouts/strength_only.py:_span`, `cli/workouts/parser.py`, `config.workout_generation_span_days` |
| Commitment window | `settings.commitment_days`/`commitment_end`, `coach/service/standing.py`, `coach/formatting.py:format_standing_workouts`, `gcal/reconcile.py:leaves_trace`, `workout_changes.commitment_end` |
| A plan-shaping input changed since the plan was built | `plan_inputs.py` (what shapes a plan and its hash), `coach/service/staleness.py` (the judgment, `plan_fingerprints()`, the `plan keep` stamp), `cli/staleness.py` (every wording the athlete reads), and the surfaces: `cli/plans/show.py`, `cli/plans/generate.py`, `cli/workouts/generate.py`, `cli/status.py`, `stamind_web.py` (a banner off `plan_config_hash()`). DESIGN_plan_staleness.md §9 |
| The schedule is running out | `analytics/runway.py` (the detector and its four kinds), `cli/runway.py` (every wording, the push button), and the surfaces: `cli/workouts/adapt.py`, `cli/workouts/listing.py`, `cli/status.py`, `cli/bot/views.py::run_bot_morning`; `config.runway_warning_days`. DESIGN_runway_nudge.md |
| Generation covering every date of its span | `coach/engine/generate.py` (the TASK sentence), `coach/service/guards.py:_fill_coverage_gaps`. DESIGN_runway_nudge.md §2.1 |
| Whether the schedule reflects a constraint | `coach/honoring.py` (`honored_at`, `needs_a_pass`), `coach/proposals.py:covered_constraint_ids`, the two stamps in `coach/service/generate.py` and `coach/service/revision_apply.py`, `cli/constraints.py:point_at_honor`, `cli/status.py`, `cli/common.py:constraint_line`/`report_unhonored`, `db/constraints.py` (`mark_honored`, `clear_honored`, `clear_honored_after`). DESIGN_constraint_honoring.md (§5: no command, no SQL copy of the predicate) |
| Coach learnings / confidence | `db/learnings.py`, `coach/service/athlete_context.py` (`_apply_learning_updates`, `_review_learning_proposals`), `learning_doubts.py`; the model is DESIGN_evidence_based_confidence.md |
| Backward analysis (bootstrap/reflect) | `coach/service/analysis.py:_run_workout_analysis`, `coach/engine/analysis.py:_data_analyze_logic` ([§10](#data-analysis-data-bootstrap--data-reflect)) |
| Garmin pull / metrics / load model | `garmin/sync.py` (`pull`, `ensure_data`), `garmin/derived.py`, `analytics/load.py`, `analytics/pmc.py` ([§12](#12-sports-science--coaching-mathematics)) |
| Progress timeline / PMC projection | `analytics/progression.py`, `analytics/timeline.py`, `stamind/timeline_rows.py`, `analytics/chart.py`, `cli/progress.py` + `cli/progress_load.py`, `/api/timeline.png`. DESIGN_progress_timeline.md |
| Intensity distribution / time in zone | `analytics/intensity.py` (which sports qualify and in which currency; `judgeable`, `COVERAGE_MIN_BY_SPORT`, keys canonical), `analytics/zone_tables.py`, `analytics/mesocycle_report.py`, `coach/service/mesocycle_context.py` (`_intensity_mesocycle_context` for adapt, `_mesocycle_progress_context` for `workout generate`, `_planning_zone_currencies`), `coach/service/history_context.py`, `cli/status.py`, `cli/progress_zones.py`, `progression.weekly_aggregates`, `cli/data/show.py` (`--zones`), `/api/zones` + `static/progress.js`. DESIGN_intensity_distribution.md |
| Planned time in zone (a session's intensity target) | `db/schema.py` (`planned_zone_currency`, `planned_zone1..7_sec`), `db/workout_change.py:WorkoutChange.append`, `intensity.parse_planned_zones`/`format_planned_zones`, `coach/engine/sessions.py` (`planned_zone_task`, `planned_zone_fields`), `gcal/event.py`, `coach/formatting.py`, `cli/workouts/session_line.py::prescription_lines`. DESIGN_intensity_distribution.md §9.8 |
| Calendar push / daily-signal ingest | `stamind/gcal/` ([§13](#13-daily-signals-calendar-ingest)) |
| Workout state (modified/calendar/removed) | `stamind/workout_state.py`, `db/workouts.py` ([§5](#workout-state--three-orthogonal-axes-not-one-enum)) |
| What became of a planned session (the adherence verdict) | `analytics/adherence.py` (`classify_adherence`, `STATUS_LABELS`, `unplanned_kind`, `off_plan_gaps`), `analytics/compare.py` (`adherence_window`, `adherence_verdicts`, `compare_days`, `format_actual`), `gcal/reconcile.py:mark_adherence_range`, `gcal/event.py` (the title tag), `cli/workouts/session_line.py::adherence_marker`, `cli/workouts/listing.py::_list_verdicts`, `/api/workouts` + `static/workouts.js`, `calendar_days.py` ([§5](#workout-state--three-orthogonal-axes-not-one-enum), [§17](#17-calendar-telegram-mini-app-and-sm-calendar)) |
| Which timezone dates are read in | `stamind/clock.py`, the push window in `chat/scheduler.py`. DESIGN_user_timezone.md |
| A preference the athlete can change at runtime | a registry entry in `stamind/settings.py` (not a command), `cli/settings.py`, and the reader that consumes it. DESIGN_settings.md |
| Cycle retrospectives | `stamind/cycle_records.py`, `db/retrospectives.py`, `coach/service/retrospective.py`, `coach/engine/retrospective.py`, `stamind/retrospective_question.py`, `coach/service/history_context.py` (what `plan generate` reads), `cli/plans/show.py` (`-vv`), `cli/plans/retro.py`, `cli/common.py` (`print_mesocycle_head`, `print_retrospective`). DESIGN_cycle_retrospective.md |
| A question or message no command waits on | a `Kind` (`stamind/queue_kind.py`) in `KINDS` of `stamind/athlete_queue.py`, and `queue_kind.queue(kind, subject, payload)` from the feature; nothing in the bot. DESIGN_athlete_queue.md §8; `strength/questions.py` is the worked example |
| A long run beside the chat | `chat/routing.py:long_run`, `chat/runner.py` (`_keep_behind`, `_start_kept`, `KEPT_LINES`), `chat/callbacks.py:tap_long_run`, `queue_kind.Kind.long_run`/`confirmation`, `athlete_queue.long_run_name`/`lived_out`, `cli/queue_commands.py:GOES_ON`, `cli/bot/hand_off.py` (`pass_to_coach`, `adjust_week`), `cli/workouts/proposal.py` (`schedule`, `replace_sessions`), `cli/workouts/generate.py:propose_weeks`, `coach/proposals.py` (`generate_to_json`/`generate_from_json`), `cli/bot/views.py:_morning_adaptation`. DESIGN_long_runs_beside_chat.md |
| A proposal that waits for the athlete's answer | `cli/workouts/proposal.py` (the `proposal` kind, `save`, `open_proposal`, `shown_to_week_planner`, `out_of_date`), `coach/proposals.py` (`week_planner_changed`, `revision_to_json`/`revision_from_json`), `coach/engine/notes.py:open_proposal_task`, `cli/queue.py:send_alone`, `cli/workouts/adapt.py:_settle`, `cli/bot/views.py:_morning_adaptation`. DESIGN_waiting_proposal.md |
| Whether the morning push asks the week planner | `coach/picture.py` (`take`, `news`, `nights`, `remember`), `cli/bot/views.py:_asks`, `strength/planner.py:has_work`, `db/workout_history.py:newest_change_with_sessions(exclude_kind)`, `RevisionProposal.seen`, the `adapt_last_seen` row of `settings`. DESIGN_quiet_morning.md |
| A strength activity's sets | `strength/sets.py`, `strength/vocabulary.py` + `exercises.tsv` (then rebuild `miniapp/exercises.json` with `miniapp/build_exercises.py`), `strength/questions.py`, `db/strength.py`, `cli/strength.py`, `cli/strength_log.py`, the `strength-sets-since` setting. DESIGN_strength_tracking.md, DESIGN_exercise_table.md |
| A gym session logged on the phone | `miniapp/`, `strength/logger.py`, `cli/strength_ingest.py`, `strength/sets.py::take_over_logs`, `db/strength.py` (`gym_logs`, `upsert_logged_activity`, `save_gym_log`, `gym_log_for_day`, `garmin_activity_with_log`, `move_gym_log`). DESIGN_gym_logger.md ([§16](#16-gym-logger-telegram-mini-app)) |
| A past strength session against its planned lines | `strength/comparison.py`, `db/strength.py::attach_lifted`, `analytics/adherence.py` (`_discrepancy_reasons`, `_pairing_order`, `is_ambiguous_match`), `cli/common.py` (`strength_table`, `simple_comparison_lines`), `strength/sets.py::done_text`. DESIGN_strength_planned_vs_done.md |
| What a strength session prescribes | `strength/planner.py`, `strength/planner_prompt.py`, `strength/progression.md`, `strength/history.py`, `strength/prescription.py`, `prescribed_sets` + `strength_checks` in `db/schema.py`, `db/workout_change.py::WorkoutChange`, the pass's place in `coach/service/generate.py` and `coach/service/adapt.py`. DESIGN_strength_tracking.md §9 |
| A chain: several movements done as one set, one key joined with `>` | `strength/vocabulary.py` (`parts`, `words`, `side_mark`, `shared_load`, `shared_names`), `strength/logger.py::parse_log`, `strength/planner_prompt.py::_known_key` + the prompt's chain paragraph, `strength/progression.md` ("A chain"), `miniapp/logic.js` (`partsOf`, `chipsOf`, `replacePart`, `removePart`, `chainAfter`), `miniapp/app.js::cardTitle`. Everything else keys on the string. DESIGN_strength_combos.md |
| A CLI command | `stamind/cli/<family>.py` (`run_*`), the dispatcher in `stamind_cli.py` ([§7](#7-cli-commands-reference)) |
| A message telling the athlete to run something | `text.cmd()` inside the line's colour call, emitted with `output.aside` |
| Whether a line reaches the chat | `output.aside` (terminal only) vs `print`; a list of lines gates on `text.asides_enabled()`. DESIGN_output_verbosity.md §3 |
| Recording that something happened | `output.step`/`warn`/`fail` print and journal in one go; `stamind/journal.py` directly only for structured fields (`journal.record`) or what must never reach the athlete (`journal.debug`); event names from `journal.EVENTS`; `runtime.prompt` journals every answer itself. DESIGN_logging.md §2, §4.2, §5 |
| Reading back what a command did | `sm journal` (`cli/journal/`), `logs/runs/*.jsonl`; a run's prompts are `logs/llm_exchanges/*<run id>*`. DESIGN_logging.md §6, §7 |
| How long the coach's prose is | `coach/engine/prompt.py` (`## WRITING FOR THE ATHLETE`) + the per-field caps in each `## RESPONSE FORMAT`; a field re-injected into later prompts is not capped (DESIGN_output_verbosity.md §5.1); the short proposal in the chat (`cli/render/proposal_lines.py`, DESIGN_short_messages.md §3) |
| A web view of existing data | a GET in `stamind_web.py` + a panel under `static/` ([§8](#8-web-api-endpoints)) |
| A web endpoint that would write | does not go in the web app: add the CLI command ([§8](#8-web-api-endpoints)) |
| DB schema / a new column | the `db/*.py` mixin + the table in [§5](#5-database-schema) |

---

## 3. coach Package Architecture

The `stamind/coach/` package's `__init__.py` is a docstring. Each name is imported
from the submodule that defines it — `from stamind.coach.service import coach_service`,
`from stamind.coach.formatting import format_baseline` — so a light submodule costs only
itself. The submodules:

- `formatting.py` — pure prompt-formatting helpers, no I/O, no model;
  `format_planned_workouts_detailed` tags trained and already-eased sessions for the adapt
  prompt ([§15](#a-session-already-behind-us-carries-its-verdict)).
- `engine/` — `CoachEngine` (prompt construction, hashing, LLM calls), assembled from
  mixins; its `__init__.py` names each file. It owns the `openrouter_client` binding,
  **the patch target for tests:** `stamind.coach.engine.openrouter_client`.
- `service/` — `CoachService` + the `coach_service` singleton (data I/O, caching,
  orchestration), fourteen mixins, one file per job; the package `__init__.py` names each.
  Callers reach all of them through `coach_service`, so a method moving between files is
  invisible outside the package. It holds no handles of its own: `_db` and `_prompt` are
  properties over `runtime.db` and `runtime.prompt`, and it has no Calendar handle at all
  (the comment beside `_prompt` in `service/__init__.py` says why).
- `honoring.py`, `proposals.py`, `revisions.py` and `picture.py` sit beside them: whether
  the schedule reflects a constraint yet, the frozen records the coach hands the CLI before
  the athlete has accepted anything, the pure helpers that fill one in, and the picture a
  `workout adapt` run took of its inputs (DESIGN_quiet_morning.md §3).

### `_load_science_guidelines(app_science_dir, science_dir) → str`
Module-level in `formatting.py`: one `====` banner per corpus (DESIGN_prompt_structure.md
§3), `""` when both directories are empty. Called by
`CoachService._load_science_guidelines()`.

**The two corpora are layered, and the layering is one-directional.**
`stamind/science/` (built-in) owns *how to measure and what the words mean*; `science/`
(user) owns *what to do*. So a user document may cite a built-in one; a built-in one may
never cite a user document by name, because the user corpus is gitignored and may be empty
or contain anything. Concretely, a built-in file must not state a duration, a loading ratio,
a taper magnitude, a session count, or a mesocycle order — those are the user layer's to set,
and a built-in file that fixes one silently overrides the philosophy the athlete supplied.
Each built-in file therefore opens with an `AUTHORITY:` line naming its role
(`VOCABULARY` / `DIAGNOSTIC` / `MEASUREMENT` / `PROTECTIVE`), and the user files with the
authority they claim over each other (`PRESCRIPTIVE` / `REFERENCE ONLY`). The same
precedence is stated to the coach at run time, in each mesocycle's `provenance` line — the file
headers alone would not tell it which corpus yields, and the user corpus can be empty or
say anything.

The one carve-out: **a built-in file may hold a hard rule when that rule can only ever
reduce load.** `recovery_metrics.md` is protective in whole, and `training_load.md` §5's
final directive is flagged inline as a floor. Anything that would add or sustain load is a
default the user layer overrides.

### `CoachEngine`
**Pure business logic — no DB or I/O.** All methods are prefixed `_` (called by
`CoachService` or directly by tests). Every prompt uses one section hierarchy
(DESIGN_prompt_structure.md §2), and every call carries a label the journal records.

- **`_build_system_prompt(...)`** — the shared system prompt: guidelines, strategy, goals,
  constraints (`_render_constraints`) and the athlete profile (`_format_athlete_profile`,
  whose threshold anchors render from `stamind.benchmarks.ANCHOR_KINDS`).
- **`_plan_generate_strategy(...)`** → `{strategy, mesocycles}`, label `plan_generate`.
  Builds its own system prompt, with the previous strategy in place of the active one.
  Branches on the goal's `date_type` ([§15](#goal-dates-event-vs-training-horizon)) and
  on a kept in-flight mesocycle (DESIGN_mesocycle_progress.md §7); takes the past plans'
  records (DESIGN_cycle_retrospective.md §7), the anchor history
  (DESIGN_benchmark_workouts.md Rev. 5) and the learnings (DESIGN_backward_evaluation.md
  §10.1).
- **`_plan_reshape_verdict(...)`** → `{reshaping, why}`, label `plan_verdict`: would
  `plan generate` reshape the plan after this change (DESIGN_plan_staleness.md §10).
- **`_retrospective_writer(...)`** → `{record, athlete_line}`, label
  `retrospective_writer` (`engine/retrospective.py`, DESIGN_cycle_retrospective.md §5).
- **`_workout_generate_logic(...)`** → `{reasoning, workouts[]}`, label
  `workout_generate`. `num_days` and `start_str` set the span; `mesocycle_progress` adds
  the section that continues a mesocycle under way (DESIGN_mesocycle_progress.md §4) and
  `mesocycle_has_intensity` the one that judges its composition
  (DESIGN_intensity_distribution.md §9.2a); the TASK states the coverage invariant
  (DESIGN_runway_nudge.md §2.1).
- **`_workout_adapt_logic(...)`** → `{change_needed, reason, adapted_workouts[]}`, label
  `workout_adapt` (`workout_tweak` under `tweak=True`). The house rules are
  `STANDING RULES` (DESIGN_adapt_task_prompt.md §2);
  near the mesocycle's end it adds `THIS MESOCYCLE IS ENDING`, and the week after the
  range is shown read-only (DESIGN_mesocycle_boundary.md §3, §7); the same call extracts
  the note's constraint and signal candidates (DESIGN_constraints.md §8).
- **`_data_analyze_logic(...)`** → `{macrocycle_summary, inferred_macrocycle,
  inferred_mesocycles[], physiological_insights[], learning_updates[]}`, label
  `workout_analysis`.

**Coach learnings.** A learning is a discrete observation about the athlete with a sport
scope and an app-computed confidence. Only `_data_analyze_logic` authors them, as
evidence-cited deltas; `_workout_generate_logic` and `_workout_adapt_logic` read them and
author none. The app merges them (`CoachService._apply_learning_updates` →
`db.apply_learning_deltas`); confidence is `learning_confidence.py`'s and the model never
sets it; downgrades are proposed and asked through the `learning` queue kind
(DESIGN_evidence_based_confidence.md §3, §5, §6, §7; DESIGN_learning_doubt_nudge.md). The
`learnings` command family views and curates them: `rm` archives, `--purge` deletes.

### `CoachService`
**Orchestrator — owns all DB and calendar access.** Exposes the public API the UIs call,
one line each here; the flows are [§10](#10-key-data-flows).

- **`plan_generate(force, objective_id, auto_apply, fresh, start_date, show_context)`** →
  a `PlanProposal`, saved only under `auto_apply`, else by `plan_apply` once accepted.
  `fresh` withholds the plan in place from the prompt and implies `force`
  (DESIGN_backward_evaluation.md §6.1).
- **`plan_apply(objective_id, strategy, mesocycles, fingerprints=None)`** — persists a
  generated strategy. Pass the `PlanFingerprints` taken at generation time: omitting them
  re-reads the inputs as they are now, which hides an edit made in between.
- **`workout_generate(start_date, end_date, prefer_macro_id, fresh)`** → a
  `GenerateProposal`, nothing written. Starts tomorrow when today's session is already
  done; shows the week either side read-only (DESIGN_mesocycle_boundary.md §7) and the
  recent sessions the athlete spoke about (DESIGN_session_notes.md §4); forces a rest
  session on every `rest = 1` date of the span.
- **`workout_generate_apply(proposal)`** — the accepted half: one `generate` change, the
  voids first; Calendar follows from the reconcile (DESIGN_workout_revisions.md §10).
- **`workout_generate_strength(start_date, end_date)`** — `--strength-only`: the strength
  planner alone, as a `RevisionProposal` of kind `generate` (DESIGN_strength_tracking.md
  §9).
- **`replan(force, objective_id)`** — `plan_generate` then `workout_generate` and its
  apply, no preview: the unattended path.
- **`workout_adapt(target_date_str, message=None)`** → a `RevisionProposal` with
  `reason`, `workouts`, `pairs`/`removals`, and from a note the unconfirmed constraint
  and signal candidates (DESIGN_constraints.md §8, DESIGN_signal_extraction.md). The
  rules its sessions pass are [§10](#daily-adaptation-workout-adapt) step 5 and
  DESIGN_workout_revisions.md §9.1; it raises when no mesocycle covers the date
  (DESIGN_mesocycle_boundary.md §6).
- **`constraint_plan_impact` / `constraint_is_plan_shaping`** — the magnitude heuristic
  behind the replan proposal of `constraint add`/`edit`; its two thresholds are
  [§9](#9-configuration-configyaml) keys; human-confirmed, never an automatic
  `plan generate` (DESIGN_constraints.md §7).
- **`workout_tweak(message, tweak_dates, today_str)`** — `workout_adapt(...,
  tweak=True)` with the request's TASK; the reach is the mesocycle's end or
  `TWEAK_REACH_DAYS` from today, whichever is later (DESIGN_workout_tweak.md §3).
- **`workout_revision_apply(proposal)`** — the accepted half of adapt and tweak: one
  change of the proposal's kind, voids first, stamps `honored_at` (`honoring.stamp`);
  whether a revision counts as an easing is derived at read time
  ([§5](#workout-state--three-orthogonal-axes-not-one-enum)).
- **`workout_revision_record_no_change(proposal)`** — an adapt that held still writes its
  `workout_changes` row anyway and stamps `honored_at`. Like `workout_revision_apply` and
  `proposal.save`, it writes the run's picture when the run was evaluated on today
  (`picture.remember`, DESIGN_quiet_morning.md §3, §6).
- **`data_bootstrap(...)` / `data_reflect(...)`** — the shared `_run_workout_analysis`
  under horizon `long` or `short` (DESIGN_backward_evaluation.md §5, §8, §9, §13). A
  reply that parses but carries nothing raises before anything is written.
- **`_build_prior_training_context(prior_macros, today_str)`** — the planned-vs-actual
  review `plan generate` reads; its docstring says what it holds
  (DESIGN_backward_evaluation.md §6.1); `_mesocycle_reviews` lists the mesocycles behind
  it, a written record standing in for the detail (DESIGN_cycle_retrospective.md §7).
- **`plan_rm(objective_id)`** — deletes every plan version of the goal.
- **`plan_rollback(objective_id, target_macrocycle_id)`** — restores a superseded version
  and its workouts through the one point-in-time undo (DESIGN_plan_rollback.md).
- **`effective_thresholds()`** — the athlete's current anchors: `max_hr` from config
  overlaid with the latest logbook row per kind; `_effective_profile()` merges them onto
  the profile every prompt gets (DESIGN_benchmark_workouts.md §3.3).
- **`config_changed(macro)`** — the single staleness judgment, reached from the CLI
  through `cli/staleness.py`; its docstring lists the five axes
  (DESIGN_plan_staleness.md §11; `e1rm` never trips it, DESIGN_benchmark_workouts.md §3.3).
- **`plan_reshape_verdict(macro, change_reason)`** — the verdict call behind the staleness
  question; fails open (DESIGN_plan_staleness.md §10).
- **`retrospectives_step()`** / **`write_retrospective(record, wait_notice)`** — the date
  check then the write step, one due record per run; the record of a plan is written from
  its mesocycle records (DESIGN_cycle_retrospective.md §3, §5, §6).

**Singleton:** `coach_service = CoachService()` at the bottom of `coach/service/__init__.py`.
Read it off `runtime`, which is the handle a test patches:
```python
from stamind import runtime
runtime.coach_service
```
`from stamind.coach.service import coach_service` reaches the same object directly, for a
caller that wants its own handle. `from stamind.coach import coach_service` does not work:
the package re-exports nothing ([§15](#where-the-files-are-cut-and-why)).

---

## 4. Database — Key Patterns

**Package:** `stamind/db/` · **Singleton:** `runtime.db`

`Database` is composed from per-domain mixins, assembled in `__init__.py` and reached
only through `runtime.db`; the package exports nothing else. `base.py` (`BaseDB`) owns the
connection and the transaction that joins several, `schema.py` (`SchemaMixin`) the DDL and
the version stamp, and one mixin per domain the rest. The `workouts` table takes three:
`workout_change.py` is the only way to write a session and the one way to undo one,
`workouts.py` reads a session as it stands today, and `workout_history.py` answers what
happened to it. App preferences (`SettingsMixin`) live in `base.py`: key/value rows, not
training data, so a wipe leaves them alone.

- Every method opens a fresh `sqlite3` connection (context manager), commits,
  and closes.
- `foreign_keys = ON` is set on every connection; cascades are used on
  macrocycles→mesocycles.
- `db.workout_change(kind, summary, macrocycle_id)` is the **only** write path onto
  `workouts`. Everything inside one `with` statement shares a transaction and a
  `workout_changes` row; `change.append(...)` merges what it is given onto the slot's live
  revision and inserts a new one, `change.void(...)` says the slot now holds no session,
  and `change.restore(revision)` appends a stamped copy of an older one. A proposed
  revision whose prescription matches the live one is not written. On close the handle
  runs the Calendar reconcile over the lineages it touched
  (DESIGN_workout_revisions.md §6/§8).
- **Sports:** `stamind/sports.py` is the vocabulary (`SPORT_MAPPING`, `canonical_sport`,
  `CANONICAL_SPORTS`, which feeds the `--sport` choices and `SPORT_TYPE_ENUM` in
  `coach/engine/sessions.py`, so adding a sport there reaches both). Matching
  canonicalizes both sides and compares exactly ([§15](#15-design-rationale--history));
  `completed_activities.activity_type` keeps Garmin's raw string and every read
  canonicalizes.
- `db.week_lock()` is one look at the week at a time, across processes: a `flock` on
  `<database>.week-lock`, re-entrant in a process, held by `workout_change`, by every run of
  the week planner from reading the week to saving its answer (a terminal lets go before it
  asks, then writes nothing if `heads_up.week_changed`), and by a tap on a proposal; the
  scheduler counts it as busy (`week_busy`) (DESIGN_long_runs_beside_chat.md §3).
- `rollback_to_change(change_id, from_date)` is the **one** undo primitive, point in time:
  it reverts that change and every change after it, per slot rather than per lineage (its
  docstring says why), with `from_date` as the floor. `workout rollback`, `plan rollback`
  and the goal reinstate all reduce to it, and it writes its own `note` through
  `heads_up.undone_note` (DESIGN_workout_revisions.md §10, DESIGN_plan_rollback.md §9,
  DESIGN_change_heads_up.md §6).

### Methods by domain

Each mixin follows one naming convention (`add_*`/`save_*` writers, `get_*`/`get_*s`
readers, `update_*` partial patch, `delete_*` hard delete, `wipe_*` clear), so the
signatures are read off the mixin in `stamind/db/`. Only what the convention does not say:

- **Constraints** (`constraints.py`): `get_constraints(start, end)` returns the rows
  overlapping a window, open-ended when `end` is None.
- **Daily Signals** (`signals.py`): reconciled by Calendar event id, so the writer and
  deleter are `*_by_event` variants beside the id-based ones; cleared by `wipe_metrics`.
- **Workouts** (`workouts.py`): the table is a log, so there is no `save_`, `update_` or
  `delete_`; the write side is `workout_change`. The readers return the hydrated session
  (the live revision plus what its lineage derives); `get_workout_by_id` takes a lineage
  id; voids are excluded unless `include_removed=True`; `get_cancelled_workouts` is the
  wider read `workout tweak` needs (DESIGN_workout_tweak.md §3.1). The history readers
  (`workout_history.py`): `get_plan_revisions`, `get_workout_changes`, the heads-up
  readers `waiting_changes`/`changes_with_lines` with `mark_changes_told`
  (DESIGN_change_heads_up.md §6), `newest_change_with_sessions`, and the push recorders
  `mark_workout_pushed`/`mark_workout_adherence_pushed`, the only writers of the two
  signatures, which write `workout_calendar_state`. `add_session_note` keeps the
  athlete's words with a session (DESIGN_session_notes.md).
- **Completed Activities** (`activities.py`): `save_completed_activity` upserts on
  `activity_id` naming its columns, so it never touches the strength columns;
  `get_baseline(date)` returns the closest prior baseline.
- **Strength sets** (`strength.py`): `name_exercise_sets` is the only writer of
  `named_by = athlete`; `strength_set_rows` is the one query the strength history is built
  from; every write that changes what the history shows calls `bump_strength_history`
  (DESIGN_strength_tracking.md §5, §9).
- **Wipes** (`wipes.py`): `wipe_garmin_data(start, end)` also clears `analysis_cache`,
  resets the watermarks on a full wipe, and runs `garmin.recompute_derived()` itself after
  its transaction commits, because deleted load stays baked into every later day's CTL
  until a sweep re-derives it (DESIGN_pmc_fitness_fatigue.md §4);
  `wipe_calendar_signals` always resets the Calendar sync token; `wipe_metrics()` is both.
- **Coach Learnings** (`learnings.py`): `get_learnings()` annotates `dormant`,
  `archived` and `proposed_confidence`; `add_learning` seeds a synthetic basis; the
  evidence mutators (`apply_learning_deltas`, `recompute_all_confidence`,
  `apply_staleness_steps`, `demote_learning`, `keep_learning`) implement the model
  (DESIGN_evidence_based_confidence.md §3, §6).
- **Analysis Cache** (`analysis.py`): one row per `horizon`, keyed by an evidence
  fingerprint; `wipe_analysis_cache()` is the single wipe path
  (DESIGN_backward_evaluation.md §5.1).
- **Macrocycles/Mesocycles** (`periodization.py`): versioned. `save_macrocycle`
  supersedes the goal's active version (kept) and inserts the new one, running the
  mesocycles through `repair_mesocycle_contiguity` (DOMAIN_MODEL.md §4);
  `set_active_macrocycle(id)` promotes a version; `get_macrocycle_for_objective` returns
  the active one, `get_macrocycle_versions` any; `get_preceding_macrocycle` is the
  previous goal's (DESIGN_plan_rollback.md §6.1). The plan's feedback log is here too
  (`add_/list_/get_/rm_plan_feedback`, DESIGN_plan_feedback.md §6).
- **Retrospectives** (`retrospectives.py`): `add_retrospective` is `INSERT OR IGNORE` on
  the goal, level and start date, so the date check creates nothing twice
  (DESIGN_cycle_retrospective.md §11).

---

## 5. Database Schema

SQLite database at `stamind.db` (path from `config.db_path`), in **WAL** mode with the
busy timeout `BUSY_TIMEOUT_SECONDS` (`db/base.py` says why).

`_init_db` creates every table at `SCHEMA_VERSION` (`db/schema.py`) and stamps it in a
`schema_version` table; later starts do nothing, so `sm --help` performs no I/O. It is
**CREATE TABLE IF NOT EXISTS only**, no in-place migrations (one-off scripts by policy,
AGENTS.md); clearing the stamp rebuilds a missing table. Bump `SCHEMA_VERSION` on any DDL
change: reusing a stamped number is silent, and `test_db_lifecycle.py` fingerprints the
schema and fails on an unbumped one.

`db.transaction()` runs several writes as one connection and one commit, rolling the lot
back on an exception; methods called inside it join it.

### objectives
| Column        | Type       | Notes                                                |
|---------------|------------|------------------------------------------------------|
| `id`          | INTEGER PK |                                                      |
| `title`       | TEXT       |                                                      |
| `target_date` | TEXT       | YYYY-MM-DD                                           |
| `sport_type`  | TEXT       | Single or comma-separated (e.g. `running,cycling`) |
| `status`      | TEXT       | `active` or `archived` **only** — see below           |
| `description` | TEXT       |                                                      |
| `date_type`   | TEXT       | `event` (default) or `horizon` — see below            |

`date_type` says what `target_date` means, an **event** to peak for or a **horizon** to
train toward; the planning prompt branches on it (`engine/planning.py`) and
`plan_inputs.clean_goals` includes it only when `horizon`, so older plans keep their
`goals_hash` ([§15](#goal-dates-event-vs-training-horizon)).

`status` records only whether the goal was **called off**; completion is derived on every
read by `db.objectives.goal_state()` → `upcoming | completed | archived`, the one function
every surface renders (DESIGN_backward_evaluation.md §12).

The accessors name which question they ask (`upcoming_objectives`,
`get_active_objective`, `get_preceding_objectives`; DOMAIN_MODEL.md §2).

### constraints
Everything the athlete asks the coach to work around,
at any horizon (DESIGN_constraints.md).
| Column        | Type       | Notes                                                     |
|---------------|------------|-----------------------------------------------------------|
| `id`          | INTEGER PK |                                                           |
| `start_date`  | TEXT       | YYYY-MM-DD                                                 |
| `end_date`    | TEXT       | YYYY-MM-DD (== start for a single day)                     |
| `rest`        | INTEGER    | 0/1 — the **single** deterministic edge (rev 6): 1 = a no-training window whose dates skip the LLM and are forced to rest. Everything else is advisory prose the coach honors by judgement |
| `title`       | TEXT       | The constraint, stated short; the `list` display string   |
| `description` | TEXT       | Optional richer context, read by the LLM                  |
| `replan`      | INTEGER    | 1 = escalated to plan-shaping (built into the plan, §7)    |
| `source`      | TEXT       | `manual` \| `message` \| `lifeevent`                      |
| `created`     | TEXT       | UTC ISO                                                    |
| `honored_at`  | TEXT       | UTC ISO of the last coach pass that had this constraint in scope with authority over every day of it still ahead; NULL until one has. `coach/honoring.py` owns who may stamp it and whether the schedule is missing it (DESIGN_constraint_honoring.md §2, §4) |

Index: `idx_constraints_start` on `start_date`.

### workouts

**Append-only.** A row is one *revision* of one session and is never updated or deleted;
every change appends. The newest revision in a `(date, sport_canonical)` slot is the live
one, and everything else is history. Two triggers in `db/schema.py` (`workouts_no_update`,
`workouts_no_delete`) enforce that; several state facts are **derived, not stored** (see
[Workout state](#workout-state--three-orthogonal-axes-not-one-enum) below). See
DESIGN_workout_revisions.md.

| Column                  | Type       | Notes                                            |
|-------------------------|------------|--------------------------------------------------|
| `id`                    | INTEGER PK | The revision id. Monotonic (AUTOINCREMENT), which is what makes "highest id in the slot" mean "newest". |
| `change_id`             | INTEGER    | NOT NULL — the `workout_changes` row that appended this revision. |
| `lineage_id`            | INTEGER    | Stable session identity, surviving both edits and date moves. Equals `id` on a session's first revision. Nullable only *inside* the inserting transaction: a first revision is born NULL and seeded before commit, the one UPDATE the trigger permits. |
| `date`                  | TEXT       | YYYY-MM-DD (scheduled day)                       |
| `sport_canonical`       | TEXT       | The slot key (`stamind.sports.canonical_sport`). |
| `sport_type`            | TEXT       | The spelling as written.                         |
| `title`                 | TEXT       |                                                  |
| `short_name`            | TEXT       | At most five characters naming the kind of session ("Easy", "Hills", "Z2"), shown under the calendar cell's icon. Written with the title by the week planner and taken as given like `title`; not a prescription field (a revision differing only in it is dropped, and Google Calendar never shows it); NULL on a rest day (DESIGN_calendar_miniapp.md §3.6). |
| `summary`               | TEXT       | The short line the chat shows in place of the description, about 20 words: written by the week planner on every session but a gym day and a rest day, and by the strength planner on a gym day, which copies it with the sets it keeps. Taken as given and not a prescription field, like `short_name`. NULL on a session written before it existed (DESIGN_short_messages.md §4, §7). |
| `description`           | TEXT       |                                                  |
| `duration_minutes`      | INTEGER    |                                                  |
| `rpe`                   | INTEGER    | Expected RPE 1–10 (excluded from `pushed_signature`) |
| `tss`                   | INTEGER    | Expected Training Stress Score                   |
| `void`                  | INTEGER    | 0/1 — 1 ⟺ this slot holds no session as of this revision. When it is the newest revision in the slot there is no session that day; when it is not, it is history like any other row. |
| `reason`                | TEXT       | This revision's note: why it changed, or why it was cancelled. The change kind says which. |
| `restored_from`         | INTEGER    | Only on a `rollback`/`reinstate` copy: the revision it duplicates. The adaptation tally follows it to skip spans that were undone. |
| `macrocycle_id`         | INTEGER    | Plan version this revision belongs to — the per-date tag every scoping read uses (goal stand-down, `plan show`). |
| `created_at`            | TEXT       | UTC ISO — when the SESSION entered the plan, carried across its revisions. Distinct from the change's own timestamp. |
| `benchmark_type`        | TEXT       | Benchmark identity: non-NULL ⟺ this session is a fitness test (`ftp_20min`, `run_5k_tt`, `e1rm`, …). Creation-time intent, carried forward by the append merge so a partial re-save preserves it; `change.append(clear_benchmark=True)` is the one way to blank it, used when an adaptation replaces a test with something that is no longer that test (`DESIGN_benchmark_workouts.md` §4.2). Rendered as `[BENCHMARK]` in `workout list`. |
| `planned_zone_currency` | TEXT       | `hr` \| `power` (`DESIGN_intensity_distribution.md` §9.8) |
| `planned_zone1..7_sec`  | INTEGER    | Planned time in zone.                            |

Indexes: `idx_workouts_slot (date, sport_canonical, id)` serves the live view;
`idx_workouts_lineage (lineage_id, id)` serves every lineage derivation.

View `live_workouts`: the newest revision per slot. Every reader keeps its own `WHERE`
and changes only its `FROM`.

### workout_changes

One row per command invocation that wrote workouts — written even when the pass appended
nothing, because an adapt that looked at the metrics and held is a real event.

| Column          | Type       | Notes                                             |
|-----------------|------------|---------------------------------------------------|
| `id`            | INTEGER PK | The batch key. `workout rollback` undoes a change and everything after it. |
| `created_at`    | TEXT       | UTC ISO, when the command ran.                    |
| `kind`          | TEXT       | `generate` · `adapt` · `tweak` · `rollback` · `stand-down` · `reinstate`. Fixed at write time; one invocation has exactly one kind. |
| `summary`       | TEXT       | The batch rationale. |
| `macrocycle_id` | INTEGER    | The plan version in force when this ran: context for `workout batches`, distinct from the per-row tag. |
| `note`          | TEXT       | The coach's one line to the athlete about this change. A `generate` writes it only when something they would notice changed (DESIGN_plan_change_continuity.md §6.3); an `adapt` that changed something stores its reason here too; a `rollback` writes its own line about what it undid. NULL on everything else (DESIGN_change_heads_up.md §6). |
| `told_at`       | TEXT       | UTC ISO, when the athlete was told about this change: stamped as it is written when they watched the run, else by `bot changes`. A change is **waiting** when it has a `note`, no `told_at`, and still stands (DESIGN_change_heads_up.md §6). |
| `commitment_end`| TEXT       | Last day of the commitment window in force when this ran, so a removal is judged by the window it was written under rather than by the one standing when the Calendar sync happens to run (§5.2). |

The two live databases also carry a dead `sleep_seen` column, left by the once-a-morning
skip the picture replaced; the schema is CREATE-only and cannot drop it
(DESIGN_quiet_morning.md §7).

### workout_calendar_state

Sync bookkeeping, keyed by **lineage** rather than revision: there is one Calendar event
per session and it must follow that session across both edits and date moves. Off the row
because a successful push is not a prescription change — left there, `workout push -f`
alone would double the table.

| Column                       | Type       | Notes                                    |
|------------------------------|------------|------------------------------------------|
| `lineage_id`                 | INTEGER PK |                                          |
| `google_event_id`            | TEXT       | Non-NULL ⟺ a Calendar event exists (may be stale) |
| `pushed_signature`           | TEXT       | What the last ordinary push sent. Only writer: `mark_workout_pushed`. |
| `adherence_pushed_signature` | TEXT       | What the last `compare --mark` adherence push sent. Only writer: `mark_workout_adherence_pushed`. |

#### Workout state = three orthogonal axes (not one enum)

Three independent facts, none stored as a status string, all three reaching the athlete
as markers in the Flags column of `workout list` (`print_marker_legend` glosses the
markers on screen).

**1. Modified?** = the change kind of the live revision, recorded when the change ran:

| Live revision's change kind | Reads as |
|---|---|
| `generate` | unmodified |
| `adapt` | adapted |
| `tweak` | tweaked (changed on request) |

A `rollback`/`reinstate` copy reads as the prescription it restored; a void reads
`[REMOVED]`. `modification_markers` in `stamind/workout_state.py` is the single renderer,
and it draws the standing easings too (`[ADAPTED ×2]`). The adaptation tally
(`adaptation_count` / `adapted_at`) is walked over the lineage, which is why `lineage_id`
exists (DESIGN_workout_revisions.md §7).

**2. Calendar state** = derived by `stamind.workout_state.calendar_status(workout)`:

| Result | Condition |
|--------|-----------|
| `unpushed` | `google_event_id IS NULL` |
| `synced` | `pushed_signature == ` current calendar-field hash |
| `stale` | `pushed_signature != ` current hash |

`mark_workout_pushed` is the only writer of `pushed_signature`; `CALENDAR_FIELDS` carries
`revision_id`, so any appended revision moves the hash (DESIGN_calendar_lineage.md §6).
Stale persists until a push lands; `warn_stale_before` (`cli/workouts/calendar_sync.py`)
names the past ones. The past-looking pass, `mark_adherence_range` (`gcal/reconcile.py`),
stamps `adherence_pushed_signature` on `data pull` and `workout compare` (`--no-mark`
skips).

**3. Removed?** = the live revision is a **void**. Nothing is deleted; `get_workouts`
excludes voids unless `include_removed=True`, so they vanish from every listing and are
not counted as misses.

### completed_activities
| Column              | Type    | Notes                                              |
|---------------------|---------|----------------------------------------------------|
| `activity_id`       | TEXT PK | Garmin activity ID, or `log:<date>` for the placeholder a gym log hangs off until Garmin's own activity for that day turns up ([§16](#16-gym-logger-telegram-mini-app)) |
| `date`              | TEXT    | YYYY-MM-DD                                         |
| `start_time`        | TEXT    |                                                    |
| `activity_name`     | TEXT    |                                                    |
| `activity_type`     | TEXT    | Garmin type string, raw (e.g. `running`, `gravel_cycling`); canonicalized on read |
| `duration_sec`      | REAL    |                                                    |
| `distance_km`       | REAL    |                                                    |
| `elevation_gain_m`  | REAL    |                                                    |
| `avg_hr`            | INTEGER |                                                    |
| `max_hr`            | INTEGER |                                                    |
| `rpe`               | INTEGER | User-entered in Garmin (directWorkoutRpe); NULL if not entered (never synthesised) |
| `tss`               | REAL    | Measured TSS only: power TSS if a power meter recorded, else hrTSS; NULL if neither. Training *load* is derived on the fly, not stored — see Load model below |
| `bike_avg_watts`    | INTEGER | From Garmin; NULL for non-bike activities          |
| `zone1_sec`–`zone5_sec`     | INTEGER | Time in each HR zone (seconds); NULL if missing |
| `power_zone1_sec`–`power_zone7_sec` | INTEGER | Time in each Coggan power zone (seconds); NULL unless a power meter recorded |
| `sets_read_at`      | TEXT    | Strength sessions: when the sets were read from Garmin (UTC, queue form); NULL until the morning after (DESIGN_strength_tracking.md §6) |
| `sets_final_at`     | TEXT    | When the sets were frozen; NULL while "are the sets final?" waits. Part of a naming question's subject |
| `discarded`         | INTEGER | 1 after `strength discard`: the activity's sets are left out of the strength history; it still counts as training |

### exercise_sets
Every set of a strength session as Garmin recorded it, rest entries included
(DESIGN_strength_tracking.md §5). Read once and frozen; only `strength reset` reads a
session again. Rows cascade with their `completed_activities` row.

| Column         | Type    | Notes                                                                 |
|----------------|---------|-----------------------------------------------------------------------|
| `activity_id`  | TEXT    | The Garmin activity; `UNIQUE (activity_id, seq)`, `ON DELETE CASCADE`  |
| `seq`          | INTEGER | Position in Garmin's list, rest entries included, from 1              |
| `set_type`     | TEXT    | `active` or `rest`                                                    |
| `exercise`     | TEXT    | The key of the exercise's class in the exercise table (DESIGN_exercise_table.md §4), so weighted pull-ups and plain ones are one history. A Garmin name the table lacks is its own key; a chain is its movements' keys joined with `>` (DESIGN_strength_combos.md §3). NULL while unnamed |
| `garmin_name`  | TEXT    | What Garmin said: `CATEGORY/NAME`, a bare `CATEGORY`, or `UNKNOWN`    |
| `reps`         | INTEGER |                                                                       |
| `load_kg`      | REAL    | Garmin's grams / 1000; NULL when no weight was entered. On a bodyweight exercise, the added load |
| `duration_sec` | REAL    |                                                                       |
| `named_by`     | TEXT    | `watch` (the watch's guess), `garmin` (a person's pick in Garmin), `athlete` (an answer in Stamind), NULL while unnamed |

### prescribed_sets
What the strength planner wrote for one revision of one strength session
(DESIGN_strength_tracking.md §9). The session's description is rendered from these rows, so
the kilograms the athlete reads and the kilograms stored as data cannot disagree. Planned
sessions are append-only, so the rows belong to a revision and go with it: they are written
in the same transaction, copied by a rollback, carried to a moved session's new day by
the strength planner, carried forward by a revision that continues the session, and
cascaded away with their `workouts` row.

| Column       | Type    | Notes                                                        |
|--------------|---------|--------------------------------------------------------------|
| `workout_id` | INTEGER | The revision; `UNIQUE (workout_id, position)`, `ON DELETE CASCADE` |
| `position`   | INTEGER | Order in the session, from 1                                 |
| `exercise`   | TEXT    | A key of the exercise table, or a chain of keys joined with `>`; reps are then rounds (DESIGN_strength_combos.md §3) |
| `sets`       | INTEGER |                                                              |
| `reps_low` / `reps_high` | INTEGER | The rep range, equal for a fixed count. The reps are the athlete's dial, the load the strength planner's (§10) |
| `load_kg`    | REAL    | NULL for a bodyweight exercise with nothing added            |
| `light`      | INTEGER | 1 on every row of a light week's session, which the history marks "(light)" |

### strength_checks
Which evidence each strength session's kilograms were last weighed against
(DESIGN_strength_tracking.md §9). Keyed by lineage, so it follows the session across
revisions and across a move. Written when a proposal is applied or recorded as no change,
never when it is proposed.

| Column            | Type    | Notes                                                    |
|-------------------|---------|----------------------------------------------------------|
| `lineage_id`      | INTEGER | PK — `workouts.lineage_id`, the session                   |
| `checked_against` | TEXT    | The value `strength_history_changed_at` had when the history shown to the strength planner was built — not the clock, so sets read while a preview waited are not counted as weighed |

### session_notes
What the athlete said about a session, word for word (DESIGN_session_notes.md). Keyed by
lineage, so it follows the session across revisions and a move. Written by `workout adapt -m`
once the coach's call returns; hydration reads it back as the session's `athlete_notes`, and
every prompt that lists the session prints it under it. Never edited or trimmed: the prompts are
bounded by their own look back. `wipe_workouts` clears it with the sessions.

| Column       | Type       | Notes                                              |
|--------------|------------|----------------------------------------------------|
| `id`         | INTEGER PK | Order of arrival                                   |
| `lineage_id` | INTEGER    | `workouts.lineage_id`, the session                 |
| `sent_at`    | TEXT       | UTC ISO, when the note was kept                    |
| `text`       | TEXT       | The note exactly as the athlete typed it           |

### gym_logs
The raw log the gym logger page sent, kept beside the sets it was turned into
(DESIGN_gym_logger.md §5). Its cards say which planned line each set stood for, which the
sets alone lose, so `attach_lifted` reads the sets of a logged activity from here
(DESIGN_strength_planned_vs_done.md §8).
One row per activity: ingesting a day twice replaces its log, and the row moves onto
Garmin's activity when the pull takes the log over. Rows cascade with their
`completed_activities` row.

| Column        | Type    | Notes                                                        |
|---------------|---------|---------------------------------------------------------------|
| `activity_id` | TEXT PK | The activity the log belongs to, `ON DELETE CASCADE`          |
| `revision_id` | INTEGER | The `workouts.id` the page was given; NULL when it had none   |
| `received_at` | TEXT    | When `strength ingest` read the file (UTC ISO)                |
| `payload`     | TEXT    | The page's message verbatim, as it was sent                   |

### page_files
The record: what Stamind remembers of each file it uploaded for the calendar and "Goals &
plan" pages (DESIGN_miniapp_storage.md §6). The step after every command uploads nothing
unless this table holds the index file's address with a fingerprint (a first upload that
failed leaves a row with only its error), so a database `data publish` never
published, a worktree's or the test suite's, uploads nothing. `data unpublish` empties it.
Untouched by every `wipe`.

| Column        | Type    | Notes                                                        |
|---------------|---------|---------------------------------------------------------------|
| `address`     | TEXT PK | The file's full address, bucket, folder and name. The name is computed from the bot token, so another token or bucket finds no row of its own |
| `label`       | TEXT    | What the file holds: `calendar/2026-09`, `calendar/index` or `plan` |
| `fingerprint` | TEXT    | SHA-256 of the content last uploaded, before encryption and without the stamp; NULL until one upload succeeded |
| `uploaded_at` | TEXT    | When that upload succeeded (UTC ISO)                          |
| `error`       | TEXT    | The last attempt's HTTP status or error type when it failed, else NULL; `sm status` shows it |

### activity_match_decisions
The athlete's answer to a planned-vs-completed pairing the matcher had to guess at
([§15](#a-pairing-the-matcher-had-to-guess-at-is-a-question-not-a-fact)). Keyed by
activity and sport rather than workout id, because workout rows are replaced on every
revision and the athlete must not be asked again. Written by
`CoachService.record_match_decision`; every adherence surface passes
`db.get_rejected_matches()` into `analyze_adherence`.

| Column            | Type       | Notes                                              |
|-------------------|------------|----------------------------------------------------|
| `activity_id`     | TEXT       | PK together with `sport_canonical`                 |
| `sport_canonical` | TEXT       | The planned session's slot sport                   |
| `accepted`        | INTEGER    | 0/1 — 0 = the pairing is discarded and the session reads not done |
| `decided_at`      | TEXT       | UTC ISO                                            |

### athlete_metrics_cache
| Column            | Type    | Notes                  |
|-------------------|---------|------------------------|
| `date`            | TEXT PK | YYYY-MM-DD             |
| `rhr`             | INTEGER | Resting heart rate     |
| `hrv`             | INTEGER | Overnight HRV average  |
| `sleep_score`     | INTEGER | 0–100                  |
| `stress`          | INTEGER |                        |
| `ctl`             | REAL    | Fitness — CTL, 42-day EWMA of daily load (PMC). NULL in the leading-edge warm-up window and on pre-recompute rows |
| `atl`             | REAL    | Fatigue — ATL, 7-day EWMA of daily load |
| `tsb`             | REAL    | Form — TSB = CTL(yesterday) − ATL(yesterday) |

CTL/ATL/TSB are the stored load model, written by `garmin.recompute_derived()` over every
calendar day; the ATL:CTL ratio is derived at read time, never stored
([§12](#12-sports-science--coaching-mathematics), DESIGN_load_ratio.md).

### athlete_baselines
28-day rolling baseline computed during `garmin.recompute_derived()` (a full
sweep run after every pull).

| Column                      | Type    |
|-----------------------------|---------|
| `date`                      | TEXT PK |
| `rhr_baseline_mean`         | REAL    |
| `rhr_baseline_std`          | REAL    |
| `hrv_baseline_mean`         | REAL    |
| `hrv_baseline_std`          | REAL    |
| `sleep_baseline_mean`       | REAL    |
| `sleep_baseline_std`        | REAL    |

### sync_state
Per-source sync progress, one row per `key`. The `garmin` row holds the pull
watermark: `through_date` is the forward high-water mark (local YYYY-MM-DD) and
only ever advances; `last_pull_utc` is an instant compared against now for the
freshness interval. The `calendar_signals` row instead holds `sync_token` (the
opaque Calendar `nextSyncToken`) with `through_date` NULL. Each source populates
only the columns it uses. See §10 (Data Pull), §13 (Daily Signals),
`DESIGN_garmin_direct_pull.md`, and `DESIGN_calendar_signal_ingest.md`.

| Column          | Type    | Notes                                            |
|-----------------|---------|--------------------------------------------------|
| `key`           | TEXT PK | Source key: `garmin` or `calendar_signals`       |
| `through_date`  | TEXT    | Garmin forward high-water mark (local YYYY-MM-DD)|
| `last_pull_utc` | TEXT    | ISO instant of last successful sync              |
| `sync_token`    | TEXT    | Calendar `nextSyncToken` (calendar_signals row)  |

### settings
App preferences that outlive one invocation but are not training data: a key/value
store, untouched by every `wipe`. Every athlete-facing key is one entry in the
`stamind/settings.py` registry, written only by `settings set` (DESIGN_settings.md §2; the
registry is the list, [§9](#9-configuration-configyaml) the config keys where a
setting has one). Four internal markers are not preferences: `push_morning_last`, the
morning push's per-day stamp; `adapt_last_seen`, the picture the last `workout adapt` run
took of its inputs, as JSON, which the push compares with a fresh one
(DESIGN_quiet_morning.md §3); `changes_notify_upto`, the id of the newest change
`workout notify` asked the bot to send (DESIGN_change_heads_up.md §4); and
`strength_history_changed_at`, bumped by every write that changes what the strength
history shows, the evidence a kept strength session's kilograms may move on
(DESIGN_strength_tracking.md §5, §9).

| Column       | Type    | Notes                                              |
|--------------|---------|----------------------------------------------------|
| `key`        | TEXT PK | Preference name (`llm_model`, `timezone`, …)        |
| `value`      | TEXT    | Stored value (a model identifier, a zone name, …) |
| `updated_at` | TEXT    | UTC ISO instant of the last write                  |

### athlete_queue
Questions and messages held for the athlete until she is there to answer
(DESIGN_athlete_queue.md §3). A `(kind, subject)` is queued once, ever, so a dropped
question is never asked again. The line's order is `ready_at, id` (§13.2). Every instant is a UTC
ISO string to the microsecond, in one form, so the columns compare as strings. Untouched by
every `wipe`, and closed rows are kept; `queue list --closed` lists them.

| Column      | Type    | Notes                                                              |
|-------------|---------|--------------------------------------------------------------------|
| `id`        | INTEGER | Primary key: what `queue answer <id>` and a button name            |
| `kind`      | TEXT    | The feature that asks (`message`), a key of `athlete_queue.KINDS`   |
| `subject`   | TEXT    | What it asks about, in that feature's own terms                    |
| `payload`   | TEXT    | JSON written at queue time: what to show and the fixed answers     |
| `queued_at` | TEXT    | The start of the command that queued it; never rewritten           |
| `ready_at`  | TEXT    | From when the item may be sent: `queued_at`, then what "in 1 hour", "tomorrow" or "after the others" set. Never NULL |
| `sent_at`   | TEXT    | When it was last put in front of the athlete, in the chat or in a terminal; NULL before that and after a later choice |
| `closed_at` | TEXT    | NULL while the item waits                                          |
| `outcome`   | TEXT    | `answered`, `dropped` or `stale`                                   |

### daily_signals
External daily signals ingested from tagged Google Calendar events; `metric` is an opaque
category and `value` an optional magnitude. Reconciled by `google_event_id`
([§13](#13-daily-signals-calendar-ingest)). Three producers write them, the Calendar
syncer, `signal add` and the signal candidates a `workout adapt` note yields, all through
`signals.write_signal_days`; `stamind/signals.py` holds the suggested vocabulary and the
exclusion table beside it (its docstring says why they live together).

| Column            | Type        | Notes                                          |
|-------------------|-------------|------------------------------------------------|
| `id`              | INTEGER PK  | Autoincrement                                  |
| `date`            | TEXT        | YYYY-MM-DD the signal applies to               |
| `metric`          | TEXT        | Opaque category, e.g. `alcohol`                |
| `value`           | REAL        | Optional numeric magnitude (NULL if untagged)  |
| `text`            | TEXT        | Human blurb (summary/description) for the coach|
| `google_event_id` | TEXT UNIQUE | Calendar event id — reconciliation key         |
| `updated`         | TEXT        | Event `updated` RFC3339 (debug)                |

### benchmark_results
The dated fitness-test logbook, the single home of the athlete's trainable thresholds
(DESIGN_benchmark_workouts.md §3.2); the latest row per `anchor_kind` is what
`CoachService.effective_thresholds()` feeds the prompts and the staleness snapshot, and
`benchmarks.with_previous()` supplies each row's delta for the mesocycle report and
`GET /api/benchmarks`. The vocabulary (kind → label, unit, direction) and
`SPORT_ANCHORS`/`anchors_for_sport()` live in `stamind/benchmarks.py` (a mismatch warns,
never refuses; no kind is privileged, DESIGN_benchmark_workouts.md §3.5). CRUD in
`db/benchmarks.py`, commands in `cli/benchmarks.py`.

| Column        | Type       | Notes                                                     |
|---------------|------------|-----------------------------------------------------------|
| `id`          | INTEGER PK | Autoincrement                                             |
| `date`        | TEXT       | YYYY-MM-DD the test was performed                         |
| `sport_type`  | TEXT       | Canonicalized sport                                       |
| `anchor_kind` | TEXT       | `ftp` \| `lthr` \| `threshold_pace` \| `css` \| `e1rm` \| `mas` |
| `value`       | REAL       | The measured number (pace kinds stored in base unit)     |
| `unit`        | TEXT       | `W` \| `bpm` \| `min/km` \| `sec/100m` \| `kg` \| `km/h`  |
| `source`      | TEXT       | `test` \| `manual` \| `modeled`                           |
| `workout_id`  | INTEGER    | Nullable lineage id of the planned test it satisfied; set by `--session` |
| `note`        | TEXT       | Free text (protocol, conditions)                          |
| `created`     | TEXT       | UTC ISO                                                    |

### coach_learnings
Discrete, addressable athlete-observation records. Confidence is **app-computed**
from the `learning_evidence` basis (below), not asserted by the LLM
(DESIGN_evidence_based_confidence.md §3).

| Column                | Type       | Notes                                                  |
|-----------------------|------------|--------------------------------------------------------|
| `id`                  | INTEGER PK | Referenced by `revise`/`reinforce`/`contradict`/`retire` deltas |
| `text`                | TEXT       | LLM-generated observation                              |
| `sports`              | TEXT       | Comma-separated sport scope, or `general` (default)    |
| `confidence`          | TEXT       | App-computed: `tentative` / `moderate` / `established` |
| `proposed_confidence` | TEXT       | Pending, human-confirmable **downgrade** (`retire` = propose retirement); NULL when none |
| `created_at`          | TEXT       | ISO timestamp                                          |
| `updated_at`          | TEXT       | ISO timestamp; last content/metadata change            |
| `last_reinforced_at`  | TEXT       | ISO timestamp; drives decay → `dormant` (DESIGN_evidence_based_confidence.md §3); refreshed only by a *new* supporting week or a staleness step |
| `status`              | TEXT       | `active` / `archived`; retiring a learning archives it (DESIGN_learning_doubt_nudge.md §6) |

### learning_evidence
The per-learning **evidence basis**: the distinct training **weeks** backing each
learning, tagged supporting/contradicting; `confidence` is a pure function of it.
The `UNIQUE(learning_id, week_commencing, polarity)` constraint is the dedup
guarantee (re-citing a counted week is an `INSERT OR IGNORE` no-op;
DESIGN_evidence_based_confidence.md §5).

| Column            | Type       | Notes                                              |
|-------------------|------------|----------------------------------------------------|
| `id`              | INTEGER PK |                                                    |
| `learning_id`     | INTEGER    | FK → coach_learnings.id (ON DELETE CASCADE)        |
| `week_commencing` | TEXT       | YYYY-MM-DD (Monday) — the evidence anchor          |
| `polarity`        | INTEGER    | +1 supporting · −1 contradicting                   |
| `source`          | TEXT       | `reflect` \| `bootstrap` \| `manual` \| `migration`     |
| `reason`          | TEXT       | On a contradicting week: what went against the learning, one line from reflect (DESIGN_learning_doubt_nudge.md §4) |
| `created_at`      | TEXT       | ISO timestamp                                      |

`UNIQUE(learning_id, week_commencing, polarity)`

### macrocycles
| Column            | Type                  | Notes                                            |
|-------------------|-----------------------|--------------------------------------------------|
| `id`              | INTEGER PK            |                                                  |
| `objective_id`    | INTEGER FK→objectives | Cascade delete                                   |
| `strategy`        | TEXT                  | LLM-generated strategy text                      |
| `goals_hash`      | TEXT                  | SHA-256 of objectives at generation time         |
| `constraints_hash`| TEXT                  | SHA-256 of the plan-shaping (replan=1) constraints at generation time (§7) |
| `config_hash`     | TEXT                  | SHA-256 of the plan-shaping `user_profile` fields, thresholds, `name` and equipment excluded (DESIGN_plan_staleness.md §3) |
| `config_snapshot` | TEXT                  | JSON of the effective threshold anchors the plan was generated with; staleness only past `coach.threshold_replan_pct` drift; NULL on older plans. Shown by `plan show`, compared by `plan diff` |
| `profile_snapshot`| TEXT                  | JSON of the plan-shaping profile fields the plan was generated with, so the staleness reason can name the one that moved; NULL on older plans (§5) |
| `goals_snapshot`  | TEXT                  | JSON of the goals the plan was generated from; NULL on older plans. Shown by `plan show` and the web strategy card |
| `constraints_snapshot` | TEXT             | JSON of the plan-shaping constraints the plan was generated from; NULL on older plans |
| `created_at`      | TEXT                  | ISO timestamp                                    |
| `status`          | TEXT                  | `active` or `superseded`; exactly one active version per objective, and readers filter on it (DESIGN_plan_rollback.md) |
| `superseded_at`   | TEXT                  | ISO timestamp a version stopped being active; NULL while active |
| `summary`         | TEXT                  | The strategy in at most two sentences, written beside it by `plan generate`; `plan show` prints it in place of the strategy unless `-v`. NULL when the model leaves it out (DESIGN_output_verbosity.md §5.1) |

A new `plan generate` **supersedes** the prior version (kept) rather than deleting it, so
`plan rollback` can restore an earlier version and its workouts (DESIGN_plan_rollback.md).

### mesocycles
| Column          | Type                    | Notes                                   |
|-----------------|-------------------------|-----------------------------------------|
| `id`            | INTEGER PK              |                                         |
| `macrocycle_id` | INTEGER FK→macrocycles  | Cascade delete                          |
| `name`          | TEXT                    | E.g. "Base Building"                    |
| `start_date`    | TEXT                    | YYYY-MM-DD                              |
| `end_date`      | TEXT                    | YYYY-MM-DD                              |
| `focus`         | TEXT                    | E.g. "Zone 2 aerobic base, high volume" |
| `summary`       | TEXT                    | One sentence on what the mesocycle is for, written by `plan generate` for the "Goals & plan" page; NULL when the model leaves it out (DESIGN_calendar_miniapp.md §3.7) |

### plan_feedback
The plan's feedback log — an append-only list of notes the athlete addressed to the
**next** plan version, written while this one is in force (DESIGN_plan_feedback.md §6).

| Column          | Type                    | Notes                                   |
|-----------------|-------------------------|-----------------------------------------|
| `id`            | INTEGER PK              | The handle `plan feedback --rm` takes   |
| `macrocycle_id` | INTEGER FK→macrocycles  | The plan version the note was written   |
|                 |                         | against. Cascade delete                 |
| `mesocycle_id`  | INTEGER FK→mesocycles   | The mesocycle it was filed to; NULL =   |
|                 |                         | plan-level. Cascade delete              |
| `created_at`    | TEXT                    | ISO-8601 UTC, full precision; orders    |
|                 |                         | the log oldest first everywhere         |
| `text`          | TEXT                    | The note, verbatim — never LLM-touched  |
|                 |                         | at capture                              |

**Pending** := rows whose `macrocycle_id` is the goal's *active* macrocycle. There is no
consumed flag: supersession is the consumption event, so a `plan generate` that is previewed
and declined leaves the notes pending, and a `plan rollback` makes an earlier version's
notes pending again. Pending notes are a plan input, so their presence alone makes
`plan generate` run without `--force` (DESIGN_plan_feedback.md §7).

### retrospectives
One record per finished mesocycle and per finished plan (DESIGN_cycle_retrospective.md
§11). A record carries its own goal, name and dates and points at no plan version, so a
later version of the plan cannot lose it. The date check creates and removes the rows
(`stamind/cycle_records.py`).

| Column          | Type                    | Notes                                   |
|-----------------|-------------------------|-----------------------------------------|
| `id`            | INTEGER PK              | The handle `plan retro redo` takes      |
| `objective_id`  | INTEGER FK→objectives   | Cascade delete, so `goal rm --purge` removes the records. `plan rm` and `plan wipe` keep the goal and delete the records themselves |
| `level`         | TEXT                    | `'mesocycle'` or `'plan'`               |
| `name`          | TEXT                    | The mesocycle's name, or the goal's title for a plan. Shown, and not part of the key |
| `start_date`    | TEXT                    | First day covered                       |
| `end_date`      | TEXT                    | Last day trained                        |
| `ended_by`      | TEXT                    | `'finished'` (reached its end date), `'replaced'` (`plan generate` dropped it) or `'called_off'` (the goal was called off) |
| `intent`        | TEXT                    | The mesocycle's focus, or the plan's strategy, copied when the record is created |
| `numbers`       | TEXT                    | JSON, exact values; NULL until written  |
| `body`          | TEXT                    | The record lines; NULL until written    |
| `athlete_line`  | TEXT                    | The sentence for the athlete            |
| `athlete_words` | TEXT                    | The athlete's answer, as typed          |
| `created_at`    | TEXT                    | ISO-8601 UTC                            |
| `written_at`    | TEXT                    | ISO-8601 UTC; NULL until written        |

`UNIQUE(objective_id, level, start_date)`: a mesocycle is the same mesocycle across plan
versions when its goal and its start date are the same.

### analysis_cache
Cached backward-evaluation reconstruction, one row per `horizon`, keyed by an evidence
fingerprint and cleared by `wipe_metrics` (DESIGN_backward_evaluation.md §5.1). The
horizon selects the question: `long` (`data bootstrap`) asks for the periodization
structure, `short` (`data reflect`) only how the athlete responded (§10.3). Three readers:
`plan generate`'s review (`CoachService._cached_reconstructions()`, both slots),
`stamind/timeline_rows.py` (the `~` bands, `long` only, DESIGN_progress_timeline.md §6.1)
and `data show-analysis`. None checks the fingerprint, which the writing flow alone
consults; `_maybe_warn_stale_analysis()` says when the window falls
`coach.analysis_staleness_days` behind (§10.2).

| Column           | Type       | Notes                                              |
|------------------|------------|----------------------------------------------------|
| `id`             | INTEGER PK |                                                    |
| `horizon`        | TEXT       | `long` \| `short` — UNIQUE; the cache slot         |
| `fingerprint`    | TEXT       | Hash of the per-activity load fields (`date`, type, `duration_sec`, `tss`, `rpe`, `zone1..5_sec` — not merely the id set, so a corrected re-pull invalidates the cache) + metrics + overlapping constraints + the window's `daily_signals` + the full-history `signal_days` section as computed + window |
| `window_start`   | TEXT       | YYYY-MM-DD                                         |
| `window_end`     | TEXT       | YYYY-MM-DD                                         |
| `reconstruction` | TEXT       | JSON: inferred cycles + physiological insights     |
| `created_at`     | TEXT       | ISO timestamp                                      |

---

## 6. Singletons

`stamind/runtime.py` owns the process-wide singletons. Read them off the module at
use time — never instantiate the classes, and never bind the value at import:

```python
from stamind import runtime

runtime.config           # Config
runtime.db               # Database
runtime.coach_service    # CoachService
runtime.calendar_syncer  # CalendarSyncer
runtime.garmin           # module functions (pull, ensure_data, …)
runtime.prompt           # the prompt broker (see below)
runtime.render           # the renderer — the voice (see below)
```

`runtime` resolves each name on first access and caches it, so **importing a module
never builds a Database or opens the file**; `--help` does no I/O. Assigning
(`runtime.db = fake`) shadows the accessor for the process, which is the single
override point for tests.

Nothing reads the Calendar service-account credentials until something asks for
`runtime.calendar_syncer`, so a command or a test on an instance with no Calendar never
needs the file. Reading at use time is what makes one assignment authoritative: a name
bound by value at import is invisible to a later override. `stamind_cli.py` is a plain
entry point that nothing under `stamind/` imports; handlers reach the singletons through
`runtime`.

`openrouter_client.model` and `clock.active_zone()` are the same shape: resolved from the
`settings` table on first use, cached for the process, dropped by `reset_model()` and
`clock.reset_cache()` so a `settings set` in the same process takes
(DESIGN_model_selection.md §3.1, DESIGN_user_timezone.md §2, §3).

The **prompt broker** is `runtime.prompt`, injected into `CoachService` so the service
asks a question without importing a front-end. `make_prompt()` picks `TtyPrompt` or
`JsonPrompt` from `STAMIND_FRONTEND`; every interactive site goes through `confirm`,
`choose` or `ask_text`; a cancel raises `PromptCancelled`, which `run_once` catches; Garmin
MFA stays outside it (`garmin/client.py`, TTY-gated); every answer is journalled here
(DESIGN_logging.md §5.6). `prompt.py`'s docstring holds the rest.

The **renderer** is `runtime.render`, the same shape one axis over: the broker chooses a
*transport*, the renderer a *voice*, and they are two objects because the axes are
independent (the web dashboard is expert-voiced with no TTY). A command body holds no
`if simple:` branch: it calls `runtime.render.<what happened>(…)`, `CompanionRenderer`'s
override set is the opted-in list, and the expert table renderers stay in their command
modules with `ExpertRenderer` delegating. `cli/render/__init__.py` maps the package and
states the import rule; `test_simple_render.py` exempts `cli/render/` by directory and
`cli/bot/` file by file; `tests/helpers.run_cli` drops the cached renderer per invocation.
The three calendar files there are [§17](#17-calendar-telegram-mini-app-and-sm-calendar)
(DESIGN_render_persona.md).

Tests bind the database through `tests.helpers.rebind_test_db` ([§14](#14-testing)). Two
names are still patched where they are used:
`stamind.coach.engine.openrouter_client` (the LLM seam), and the clock at its source,
`tests.helpers.pin_clock` freezing `stamind.clock.now`, the one instant `today_date()`
reads.

---

## 7. CLI Commands Reference

Invoked as `python stamind_cli.py [--llm-model MODEL] <command> [subcommand] [args]`; the
handlers are `run_<command>_<subcommand>()` under `stamind/cli/` ([§2](#entry-points)).
`help` alone has no handler: it introspects the parser tree (`_print_command_tree` in
`stamind_cli.py`).

**Short forms** (DESIGN_cli_noargs.md §d): any prefix that matches exactly one command at
its level is that command — `pl g` is `plan generate` — so the "Short form" column lists
examples, not a closed set; an ambiguous prefix is refused, naming the candidates. A few
non-prefix shorthands and tie-breaks are registered as real aliases in the parsers; `rm`
deliberately gets none, so `r` never shortens the destructive command.

**LLM commands share two flags** the table omits: `--show-llm-prompt-only` prints the
prompt and exits before the model call, and the root `--llm-model MODEL` pins the thinking
model for one invocation ([§6](#6-singletons)).

**Range filters** (DESIGN_cli_selectors.md): every command that filters by span takes
`-d/--date`, `-m/--mesocycle`, `-M/--macrocycle` and `-g/--goal` over one grammar; they
intersect, and `resolve_window` (`cli/windows.py`) turns them into one (start, end) under
the default window each command declares with `add_selector_args`.
`TestSelectorVocabularyInvariants` walks the real parser and pins the letters.
`resolve_meso_atom` is the single-target counterpart, the one mesocycle `plan feedback
-m` names (DESIGN_plan_feedback.md §4–§5).

**A bare command group** prints that level's help and exits 1 (`build_parser` reads
`named_subparsers`, so a new group is covered; `tests/test_dispatch.py` walks the same
tree). The exception is a group whose whole state is one read-only view (`settings`,
`queue`), which acts bare instead (DESIGN_cli_noargs.md §a3).

| Command      | Subcommand   | Short form | Description                                                            |
|--------------|--------------|----------|--------------------------------------------------------------------------|
| `help`       | —            | —        | Print every command and sub-command with its one-line help, recursing through the whole sub-parser tree (unlike `--help`, which only shows one level) |
| `shell`      | —            | —        | The REPL (`_repl` in `stamind_cli.py`): reads command lines until EOF and runs each through `run_once`, so every line is its own journal run under one parent run |
| `status`     | —            | `s`, `st` | Show active goals, recent metrics, coach learnings. Also names the end of the scheduled workouts when it is near or just behind, with the exact command that extends it — printed outside the goal branch, so the "nothing is planned beyond it" case reaches the athlete who has no goal on record (DESIGN_runway_nudge.md §4) |
| `calendar`   | —            | —        | `calendar [DATE]`: the month holding DATE (today by default) as a grid in expert marks, Monday first; freshens Garmin over the month's past days unless `--no-pull`; a day's detail stays `workout list -d DATE -vv` (`cli/render/calendar_grid.py`, DESIGN_calendar_miniapp.md §7, [§17](#17-calendar-telegram-mini-app-and-sm-calendar)) |
| `goal`       | `add`        | `g a`    | Add objective (`TITLE DATE SPORT…` positional, `--desc`, `--date-type`)  |
| `goal`       | `edit`       | `g e`    | Edit objective by ID. `--status archived` calls the goal off: it stands its upcoming sessions down and clears their Calendar events, keeping the plan, its versions and its feedback. `--status active` reinstates the goal and offers those sessions back, floored at today (DESIGN_backward_evaluation.md §14) |
| `goal`       | `rm`         | `g r`    | Call the goal off, the same action as `goal edit --status archived`, without asking (`goal edit --status active` brings it all back). `--purge` deletes the objective and everything the cascade takes with it, printing the inventory and asking first; `-y` skips the prompt (DESIGN_backward_evaluation.md §14.5) |
| `goal`       | `list`       | `g l`    | List the goals that matter — upcoming and completed. Called-off goals are hidden and counted in a footer; `-a/--all` shows them (§14.5) |
| `goal`       | `wipe`       | —        | Delete all objectives                                                    |
| `constraint` | `add`        | `cons a` | Author a constraint (positional `TITLE`, `--start`, `--end`, `--desc`, `--rest`, `--replan`/`--no-replan`; never prompts — see DESIGN_cli_noargs.md §a2) |
| `constraint` | `edit`       | `cons e` | Adjust scope / rest / text / replan by ID (`--rest`/`--no-rest`)        |
| `constraint` | `rm`         | `cons r` | Remove a constraint by ID                                               |
| `constraint` | `list`       | `cons l` | List constraints from the current mesocycle onward (`-a`/`--all`, `-v`, selectors `-d`/`-m`/`-M`/`-g`; default anchor: active mesocycle start, else show all) |
| `constraint` | `show`       | `cons s` | Show a constraint in detail (incl. plan-shaping status and whether a coach pass has honored it) |
| `constraint` | `wipe`       | —        | Delete all constraints                                                  |
| `benchmark`  | `record`     | `be rec` | Log a fitness-test result to the `benchmark_results` logbook: positional `SPORT` plus one anchor flag (`--ftp`, `--lthr`, `--threshold-pace`, `--css`, `--e1rm`, `--mas`), `-d/--date` (default today), `--note`, `--source` (`manual` default), `--session ID` (the planned test it satisfies, stored as `workout_id`). The confirm and the lines after it speak through `runtime.render`, since `bot capture test_result` reaches this command from chat (DESIGN_benchmark_from_chat.md §3). An implausible sport/anchor pair (`SPORT_ANCHORS`) warns and asks; `-y` skips that prompt ([§5](#benchmark_results)). `b` alone is ambiguous with `bot` |
| `benchmark`  | `list`       | `be l`   | The logbook newest first, each row with its delta against the previous row of the same kind |
| `benchmark`  | `rm`         | `be rm`  | Delete one logbook row by ID                                            |
| `benchmark`  | `wipe`       | —        | Delete the whole logbook (hidden; `-y`)                                 |
| `signal`     | `add`        | `sig a`  | Author daily signal(s) (positional `METRIC [TEXT…]` or `-l/--label`, `--value N`, `-d RANGE` — no `-m`/`-M`, a signal spans days not mesocycles; one tagged all-day event per day) |
| `signal`     | `rm`         | `sig r`  | Remove signal(s) by positional ID(s) or metric, and/or selectors `-d`/`-m`/`-M`/`-g` (deletes calendar event + local row) |
| `signal`     | `list`       | `sig l`  | List signals (positional `METRIC` or `--metric`, selectors `-d`/`-m`/`-M`/`-g`; default window `metrics_lookback_days`) |
| `signal`     | `list-metrics` | `sig lm` | Show distinct metrics in use with counts and date span                   |
| `learnings`  | `list`       | `l`      | Show coach learnings (`-t/--type/--sport`, `--confidence`, `--dormant`; `-a/--all` includes archived ones) |
| `learnings`  | `show`       | —        | Show a learning's full text + per-week evidence basis by ID             |
| `learnings`  | `edit`       | —        | Edit a learning's text (`ID TEXT`, both positional)                     |
| `learnings`  | `rm`         | `r`      | Archive a learning by ID; `--purge` deletes it and its evidence (DESIGN_learning_doubt_nudge.md §6) |
| `learnings`  | `restore`    | —        | Bring an archived learning back, at tentative, with its evidence        |
| `learnings`  | `demote`     | —        | Accept a pending confidence downgrade by ID                            |
| `learnings`  | `keep`       | —        | Dismiss + affirm a pending downgrade by ID                             |
| `learnings`  | `wipe`       | —        | Delete all coach learnings                                             |
| `plan`       | `generate`   | `pl g`   | Generate/reuse macrocycle+mesocycles (`-f` to force, `-y/--auto` to apply without the preview, `--fresh` for a clean slate that withholds the plan in place from the prompt, `--show-llm-context` to also print the planned-vs-actual review the prompt carries — off by default, DESIGN_output_verbosity.md §7; `--feedback TEXT` first files TEXT as a plan-level note, exactly as `plan feedback "TEXT"` does, and refuses a goal range or a goal with no plan yet — DESIGN_plan_feedback.md §4). `-g/--goal [RANGE]` takes the shared range grammar: one ID plans that goal alone, bounded to its own span (opening the day after the goal before it); a range plans every upcoming goal it covers, in date order, one strategy call each — `-g ..2` is everything through goal 2 (DESIGN_cli_selectors.md §9) |
| `plan`       | `show`       | `pl s`   | Show a periodization plan: the strategy's `summary` and the mesocycle timeline with each mesocycle's `summary`. `-v` prints the full `strategy` and `focus`, the feedback notes and the snapshotted inputs, and flags inputs that changed since the plan was built, with both routes out, `plan generate` or `plan keep` (DESIGN_plan_staleness.md §9). `-vv` adds the retrospective records under the text they look back on (DESIGN_cycle_retrospective.md §8). `-g/--goal ID` (any status), `-M/--macrocycle ID` (a superseded version: each plan version is a macrocycle), `-a/--all`, `-w/--workouts` |
| `plan`       | `retrospective` | —     | A goal's retrospective records in the layout of `plan show` and nothing else: the plan's record in place of the strategy, each mesocycle's in place of its focus, with the record ID that `plan retro redo` takes (`cli/plans/retro.py`, DESIGN_cycle_retrospective.md §8). `-g/--goal ID` (any status). Read-only, no model call |
| `plan`       | `retro`      | —        | `plan retro redo ID`: one retrospective record written again, the athlete's words kept; `--words TEXT` replaces them first, `--clear-words` drops them, `--show-llm-prompt-only` prints the writer's prompt (`cli/plans/retro.py`, DESIGN_cycle_retrospective.md §9) |
| `plan`       | `keep`       | —        | Record the current profile/goals/thresholds against the active plan **without** a new `plan generate` (`-g/--goal ID`), clearing the changed-input flag `plan show` raises. The dismiss half of staleness: same write as declining at the `plan generate` prompt, reachable without spending a strategy call (DESIGN_plan_staleness.md §9) |
| `plan`       | `versions`   | `pl v`   | List a goal's kept plan versions — active + superseded — with IDs and dates (`-g/--goal ID`) |
| `plan`       | `diff`       | `pl df`  | Compare two plan versions (`[PLAN_ID_A] [PLAN_ID_B]`, `-g/--goal ID`): strategy prose, each version's attached feedback notes, mesocycles added/removed/renamed/re-dated, and snapshotted input deltas. No ID → previous vs active; one ID → that vs active. Prose rewritten wholesale collapses to a note unless `--full`. Comparison logic in `stamind/plan_versions.py`, shared with `/api/plan/diff` |
| `plan`       | `rollback`   | `pl rb`  | Restore a superseded plan version + its workouts (`-g/--goal ID`, `-M/--macrocycle ID`, `-y`); defaults to the chronologically previous version. The inverse of eager generation (DESIGN_plan_rollback.md) |
| `plan`       | `rm`         | `pl rm`  | Delete plan for a goal ID, with the goal's retrospective records, which the inventory it prints before asking counts. The old `pl d` alias is gone — `d` now prefixes `diff` |
| `plan`       | `feedback`   | `pl f`   | Append a note about the plan to its append-only log — bare text is plan-level, `-m [ATOM]` files it to one mesocycle of any upcoming goal's plan by name-infix / date / mesocycle ID (bare `-m` = the current mesocycle), and that mesocycle picks the plan. Bare run lists what is pending, `--rm ID [-y]` deletes one, `--replan` runs `plan generate` straight away (the same as `plan generate --feedback` for a plan-level note), `-g/--goal ID` targets another goal's plan (and confines `-m` to it). No LLM at capture; the next `plan generate` reads the whole log and must address every note (DESIGN_plan_feedback.md) |
| `plan`       | `wipe`       | —        | Delete all plans, and every retrospective record with them               |
| `progress`   | `[SPORT ...]` | `pr`    | Show the progress timeline: measured load to date, plan-projected forward (CTL/ATL/TSB), weekly planned-vs-actual bars with the hours planned and done each week (`-w/--weeks N`, `--chart [PATH]` for a PNG, `--explain` for the TSB-lag note; DESIGN_progress_timeline.md). `-z`/`--zones` (implied by naming a sport) adds one weekly time-in-zone table per sport — measured behind today, prescribed ahead of it (`--mesocycles` for mesocycle grain, `--power`/`--hr` to force the currency; DESIGN_intensity_distribution.md §9.6/§9.8). The sport argument scopes the **zone tables only**: CTL/ATL/TSB, the projection and the load table stay whole-athlete |
| `workout`    | `list`       | `w l`    | Show planned workouts, a 7-day window from today by default, as a table with one row per session (`cli/workouts/session_line.py::session_table`, a column no row fills is left out). Positional `TARGET…` (workout IDs and/or date selectors) plus `-d`/`-m`/`-M`/`-g`, `-t/--type TYPE` and `-L/--link` (DESIGN_cli_selectors.md). A session dated today or earlier carries its adherence verdict in the Result column (`DONE`, `PARTIAL`, `MISSED`, `REST OK`, `REST BROKEN`, or `NOT YET` for one still ahead today), and the listing freshens Garmin over that past span unless `--no-pull` ([§5](#workout-state--three-orthogonal-axes-not-one-enum)). `-v` adds each session's short form under its row (`prescription_lines`); `-vv` turns each row back into one line (`workout_line`, markers in brackets) with the full detail under it. A listing that runs past the last scheduled session ends on a marker saying so (DESIGN_runway_nudge.md §4). |
| `workout`    | `show`       | `w sh`   | `workout list -vv` under a name that says what it does: the same handler with the detail flag pinned on, the same positional targets and the same selectors. `wo sh 12` details one session. The one difference is the default window: a bare `wo sh` details today's sessions, where a bare `wo li` lists seven days. `-H/--history [N]` prints the session's earlier forms under it, newest first, capped at N (`gcal/history.py::depth_section`). The detail prints each description for one day and the session's short line in its place over several days or with `-H`; `-l/--long` and `-s/--short` choose, and a session with no short line prints its description (`listing.py::_full_text`, DESIGN_short_messages.md §4). |
| `workout`    | `compare`    | `w c`    | Compare planned vs completed (`analyze_adherence()`): prints PLANNED/ACTUAL per day, flags misses (red), rest violations (red), unplanned high-load (yellow), then a discrepancy summary. Today's untrained sessions read `(not yet — still ahead today)` and are not misses (`pending_from`, [§10](#10-key-data-flows)). Same selectors as `workout list`; default 14-day lookback; a bare span (`-d 7d`) looks *back*; end capped at today. |
| `workout`    | `generate`   | `w g`    | Write the sessions for a span from the plan's mesocycles (the dates pick the plan, not a goal — DESIGN_cli_selectors.md §8). No selector → from the day after the schedule stops, for `config.workout_generation_span_days`; a span never opens before today; refused when the plan is covered to its last day. Span flags, mutually exclusive: `-g/--goal [ID]`, `-d`, `-m`, `-M` (which also settles which plan where two cover the days). Previews the sessions as `workout list` draws them and asks; on a `y` it writes one `generate` change and pushes to Calendar ([§10](#workout-generation-workout-generate)). `-f`/`-y` skip the prompts. `--fresh` empties the commitment window (DESIGN_plan_change_continuity.md §4.4). `--strength-only` (not with `--fresh`) calls the strength planner alone (`cli/workouts/strength_only.py`, DESIGN_strength_tracking.md §9). `--propose`, what the chat's "📅 Plan my next weeks" sends, asks nothing and writes nothing: it saves the weeks as a queued proposal, or the question "Shall I plan these weeks?" when sessions stand in the span (`cli/workouts/proposal.py`, DESIGN_long_runs_beside_chat.md §4). From a terminal it first offers to replace the newest change the athlete was never told about (`cli/workouts/heads_up.py`, shared with `workout adapt`; DESIGN_change_heads_up.md §5, §8). |
| `workout`    | `rollback`   | `w r`    | Undo a workout change **and every change after it**, putting the sessions back the way they were the moment before it ran (`--batch N` per `workout batches`, default #1 the newest; `-y`). Any change qualifies, an adapt or a tweak included. The only undo. Leaves the active plan version alone — unlike `plan rollback` (DESIGN_workout_revisions.md §10). |
| `workout`    | `batches`    | `w b`    | List the commands that wrote workouts over `-d RANGE` (default: the last 7 days), newest first, each with the `#N` that `workout rollback --batch` takes, its kind, revision count, date span, plan version and stored description; `(held)` for a pass that appended nothing, `not sent yet` for a change the athlete has not been told about (DESIGN_change_heads_up.md §8). Every entry is undoable, the newest included (DESIGN_workout_revisions.md §10) |
| `workout`    | `notify`     | `w n`    | List the changes to the athlete's week not yet told, and on a `y` (`-y`) ask the bot to send them on its next wake (`changes_notify_upto`); `--all` lists every change over `-d RANGE` with its `sent`/`not sent yet`/`undone, never sent` tag and sends nothing, `--sent` keeps the sent ones (DESIGN_change_heads_up.md §4) |
| `workout`    | `adapt`      | `w a`    | Run daily adaptation check (`-d/--date` one day: `YYYY-MM-DD`, `today`, `-1d`; `-m` athlete note — kept, since adapt takes no mesocycle selector; `--lookback DAYS` overrides `metrics_lookback_days` for this run; `-y` auto-apply). Draws the same end-of-schedule hint `status` does, and **refuses** outright when every mesocycle of the plan is behind today (DESIGN_runway_nudge.md §4). From the terminal it asks the same replace question as `workout generate` — counting itself as reaching every day from the one it adapts, since only the week planner's answer says which days it writes — presents `-m` to the week planner as the athlete's coach's note, and prints under the reason when it reaches the athlete (DESIGN_change_heads_up.md §3, §5, §8). The `-m` note is also stored with the day's session, and the command asks which session when the day has several (DESIGN_session_notes.md §3) |
| `workout`    | `tweak`      | `w t`    | Ask the coach for a change the athlete decided (`MESSAGE` positional, e.g. `"Saturday: a 4 hour hike instead of the ride"`): shorter or harder, another sport, other exercises in a strength session, a session added, dropped or brought back, moved, two days swapped. `workout adapt`'s flow, preview and apply with a narrower job: only the days the request is about may change, each between today and the end of the current mesocycle, or a week ahead when that is later (DESIGN_workout_tweak.md §3.2). `-d DATE` names a day and may be given more than once; without it the week planner reads the days off the message. `-y` applies without asking; `--no-pull` and the LLM debug flags as on `adapt`. Recorded as kind `tweak`, undone by `workout rollback` (DESIGN_workout_tweak.md §3) |
| `workout`    | `push`       | `w p`    | Sync planned workouts to Google Calendar. Defaults to today onward; pushes only unsynced unless `-f`/`--force` re-pushes already-synced ones. |
| `workout`    | `wipe`       | —        | Delete all workouts                                                      |
| `workout`    | `prune-calendar` | —    | Delete Calendar workout events that no local row references — the orphans a fresh DB, a restored backup, or a wipe that never reached Calendar leaves behind. Ownership read from the `source=stamind` tag, not from stored ids; events of soft-removed workouts are kept. `-d RANGE` windows it (as on `data wipe`), `-n`/`--dry-run` previews, `-y` skips the prompt |
| `data`       | `pull`       | `d p`    | Fetch Garmin activities/metrics and Google Calendar signals (`-d RANGE`/`--metrics-only`/`--activities-only`/`--sleep`). Defaults to the last 2 days ending today. |
| `data`       | `bootstrap`  | `d b`    | Cold-start reconstruction over the full backlog; seeds evidence-based learnings, sets the reflect watermark. Flags: `-d RANGE`, `--context`, `--force`, `--inspect-only`, `--auto`. No date filter → window auto-detected (since previous goal, else 12 wk). |
| `data`       | `reflect`    | `d r`    | Incremental analysis since the reflect watermark; updates learnings + physiological insights (no cycle inference — §10.3) and resolves pending demotions (same flags as `bootstrap`). Window ends on the last completed week unless an end date is given, so a mid-week run with nothing complete costs nothing. `--auto`: unattended — staleness demotions auto-apply, contradiction ones stay queued. |
| `data`       | `show-metrics` | `d sm` | Show athlete metrics over a date range (default 7-day lookback). Selectors `-d`/`-m`/`-M`/`-g` plus `-a`/`--all`, `--no-pull`, `--csv`. |
| `data`       | `show-activities` | `d sa` | Show completed activities over a date range (default 7-day lookback). Selectors `-d`/`-m`/`-M`/`-g` plus `-a`/`--all`, `-t/--type` filter, `--no-pull`, `--csv`. |
| `data`       | `show-analysis` | `d san` | Show the reconstruction stored by the last `bootstrap` — inferred macro focus, the mesocycles `progress` draws as `~` bands, physiological insights. Strictly read-only (renders the slot; never calls the LLM, unlike `bootstrap --inspect-only`). `--short` reads `reflect`'s slot instead; flags when activities post-date the slot's window. |
| `data`       | `backfill-tss` | —      | Recompute the measured `tss` for all stored activities under the current zone model (no Garmin calls), then refresh derived workload |
| `data`       | `publish`    | `--force` | Check the bucket's setup step by step (bucket and token known, service account accepted, write and rewrite a test file, download it with no credential and fresh, no listing), then upload every file of the pages, every month from the first, and delete any other file in this bot's folder. Refuses a folder holding files this database never uploaded unless `--force` (DESIGN_miniapp_storage.md §9) |
| `data`       | `unpublish`  | `--force` | Delete this bot's files from the bucket, the index file first, and empty `page_files`; same guard as `publish` |
| `data`       | `wipe`       | `--garmin`, `--calendar`, `-d RANGE`, `-y` | Delete cached data. No scope flag = everything (Garmin evidence + daily signals) and reset watermarks; `--garmin`/`--calendar` narrow the scope; date flags restrict to a window |
| `settings`   | `list`       | `se l`   | Every preference with its value and where that value came from — the stored row, `config.yaml`, or the built-in default. With a NAME, that one setting in detail: the numbered model menu for `thinking-model`, the local clock for `timezone`. A bare `settings` lists — the read-only-family exception (DESIGN_cli_noargs.md §a3, applied by DESIGN_settings.md §4) |
| `settings`   | `set`        | `se s`, `se use` | Change one preference: `settings set thinking-model 3`, `settings set timezone Europe/Paris`, `settings set morning-time 07:00`. The name takes any unambiguous prefix. Validated by the setting's own parser — a value it cannot read is refused and nothing is written. Stored in `settings`; survives restarts |
| `settings`   | `reset`      | `se r`   | Forget one stored preference so `config.yaml`, or the built-in default, rules again |
| `queue`      | `list`       | `q l`    | Every waiting question and message in queue order, then the ones put off until later with when they come back. `--closed` lists the closed ones instead, in the order they closed, each with its outcome; `-d RANGE` picks the days they closed on (default: the last 7). A bare `queue` lists — the second read-only family (DESIGN_cli_noargs.md §a3, DESIGN_athlete_queue.md §5.1) |
| `queue`      | `answer`     | `q a`    | Go through the line with the blocking chooser, each item once: its answers, then drop, skip (Enter), and later — in 1 hour, tomorrow (the athlete's morning time), after the others. An item shown here counts as sent, so the bot leaves it until the next morning. `queue answer <id>` shows that item alone. In chat it sends the first item with its buttons instead |
| `queue`      | `tell`       | `q t`    | Queue a message for the athlete: `queue tell "Charge your watch tonight."` The bot sends it when its turn comes, within minutes between `morning-time` and `evening-time`; `queue answer` shows it in a terminal |
| `strength`   | `name`       | `str n`  | `strength name DATE`: show that day's strength activities one line per exercise or unnamed group (`sets.exercise_lines`), and name the line the athlete picks, from the recent exercises, the exercises like its name (`vocabulary.similar`) or a typed name the model matches to the table; a name can go to part of a line's sets. Keeping a name the watch guessed confirms it, and the first pick freezes an activity still waiting for "are the sets final?" (DESIGN_strength_tracking.md §7) |
| `strength`   | `reset`      | `str r`  | `strength reset DATE`: read that day's sets again from Garmin, dropping the names given in Stamind, freeze them anew, make the watch's guesses still standing the athlete's, and queue a question for every group still unnamed. How a name fixed in Connect after the freeze comes in. On a day with two strength activities it asks which one |
| `strength`   | `discard`    | `str d`  | `strength discard DATE [--undo]`: keep that day's activity out of the strength history; it still counts as training. The sets stay stored; its waiting questions are settled. On a day with two strength activities it asks which one |
| `strength`   | `log`        | `str l`  | `strength log [EXERCISE] [-p PATTERN]`: the athlete's own logbook. Bare, the lifts on record grouped by movement pattern with their session count and last day; with an exercise (its exact words, or else a part that matches every lift whose words hold it), a line per session oldest first under a heading that gives the lift's words, its pattern and its gear. Groups by pattern, never merges two lifts into one series; sessions counted by day, discarded sessions and unnamed sets left out, no number derived (DESIGN_strength_tracking.md §7) |
| `strength`   | `exercises`  | `str e`  | `strength exercises [TEXT] [-p PATTERN]`: the shipped exercise table. Bare, the nine movement patterns and the group with no pattern, and how many exercises each holds; with a pattern or a search term, the exercises themselves in their words, sorted by them, the athlete's own marked, each with its main muscles and its gear on a line under it (§4, DESIGN_exercise_table.md §7) |
| `strength`   | `ingest`     | `str i`  | `strength ingest FILE`: store the JSON the gym logger page sent as that day's sets, every set named by the athlete, and print what was done beside what was written. Writes the placeholder activity `log:<date>`, so the next morning's pull hands the sets to Garmin's own activity for the day. Ingesting the same day twice replaces the earlier log. Run by the bot, not usually typed ([§16](#16-gym-logger-telegram-mini-app)) |
| `journal`    | —            | `j`      | The operational record: one row per command run, newest first (id, when, source, command, wall time, model calls · tokens, how it ended), with a line under the table for every run that did not simply finish. Runs that only looked are left out unless `-a`; `-v` prints command lines and reasons in full. Filters: `-n N`, `-d RANGE`, `--source`, `--command`, `--failed`; `--cost` for the token rollup, `--follow` to tail the file (DESIGN_logging.md §7) |
| `journal`    | `show`       | `j 5a0e` | Everything one run wrote, by id prefix: where it ran, each event as an offset from its start, the LLM exchange files it produced, the traceback if it failed, and the runs it spawned. The bare `journal <id>` form is the same command; an ambiguous prefix lists what it matched |
| `journal`    | `prune`      | `j p`    | Force the retention sweep now — journal days past `logging.retain_days`, exchange files past `logging.retain_exchange_days`. Otherwise it runs at most once a UTC day, off the first command to finish (DESIGN_logging.md §10) |

---

## 8. Web API Endpoints

Flask server at `stamind_web.py`, bound per the `web.*` keys
([§9](#9-configuration-configyaml)). Static files served from `static/`.

**The dashboard is read-only.** It never writes a row, calls Garmin or the model, or
touches the Calendar; a `before_request` guard 405s every mutating verb and
`tests/test_web.py::TestReadOnly` fails on a route registered with one. It opens no
journal run; only failures are recorded (DESIGN_logging.md §13).

The **front-end** is `static/index.html` plus six scripts in one global scope, no module
system and no bundler, loaded in this order: `common.js`, `dashboard.js`, `plan.js`,
`workouts.js`, `progress.js`, `records.js`. Two rules: `common.js` loads first, because
the others read the `const`/`let` names it declares; and a script reaches another
script's name only from inside a function, since top-level code runs the moment its file
loads. The six tabs are lazy-loaded on first show.

Endpoints delegate to the functions the CLI uses rather than re-deriving; each row names
them.

| Method | Path                            | Description                                  |
|--------|---------------------------------|----------------------------------------------|
| GET    | `/api/status`                   | Active goal, latest metrics, coach learnings (under `coach_learnings.learnings` + `.summary`), macrocycle+mesocycles, `config_mismatch`, `sync_state` (data freshness) |
| GET    | `/api/objectives`               | All objectives (`goal list`)                 |
| GET    | `/api/constraints`              | Active + upcoming constraints — the read view of `constraint list`. Its window is a rolling `metrics_lookback_days` plus everything upcoming, **not** the CLI's active-mesocycle anchor |
| GET    | `/api/workouts`                 | List workouts (`?start_date=&end_date=&sport_type=&include_removed=`). Rows carry derived `calendar_status` + `modification_markers`, plus `adherence` (`{status, label, reasons, completed}`, null for a row still ahead of us) from `analytics/compare.py::adherence_verdicts` — the same grader the CLI asks, and not through the CLI, which §14's layering rule forbids.. |
| GET    | `/api/workouts/compare`         | Plan-vs-actual adherence (`workout compare`); no `ensure_data`. `?start_date=&end_date=&sport=` (default 14-day lookback, end capped at today) → `{filters, days[], discrepancies[], informational[]}` |
| GET    | `/api/workouts/batches`         | Workout changes, newest first (`{batches:[{id, created_at, kind, summary, workouts, held, restorable, first_date, last_date, macrocycle_ids}]}`); undoing one is `workout rollback` |
| GET    | `/api/plan`                     | Active plan for a goal (`plan show`): `?goal_id=` (default next active) → `{goal, macrocycle, mesocycles}` |
| GET    | `/api/plan/versions`            | Plan versions for a goal (`?goal_id=`; active + superseded) |
| GET    | `/api/plan/diff`                | Compare two plan versions (`?goal_id=&from_version=&to_version=`; defaults to previous vs active) → `{goal, diff}`, the same `plan_versions.diff_plans` structure the CLI renders. `{error, code}` + 400/404 when the pair cannot be formed |
| GET    | `/api/zones`                    | Per-sport, per-zone time in zone (`progress -z`; its sports and currencies come from `intensity.window_sport_stats`/`select_zone_sports`/`zone_currency`, the CLI tables' own functions). `?weeks=N\|all` (default 8), `?sport=` (repeatable, overrides the volume filter), `?currency=hr\|power` → `{window, sports[{sport, currency, zone_labels, coverage, weeks[]}], omitted}`. Weeks past today carry the *prescribed* zones (`future: true`); a future week planned in the other currency reports `currency_mismatch` rather than converting (DESIGN_intensity_distribution.md §9.8) |
| GET    | `/api/benchmarks`               | Benchmark logbook newest first + current thresholds (`benchmark list`). `?sport=&kind=`; each row carries `formatted`, a direction-aware `delta` vs the previous row of its kind, and `improvement` |
| GET    | `/api/learnings`                | List coach learnings (`?sport=&confidence=&dormant=`) + `summary` |
| GET    | `/api/learnings/<id>/evidence`  | Per-week evidence basis (supporting/contra)  |
| GET    | `/api/timeline.png`             | Progress timeline as a PNG image (the same renderer as the bot photo, DESIGN_progress_timeline.md §7.2): merged past/planned load + projected CTL/ATL/TSB. `?weeks=N` (default 8, ≥1 else 400; `all` = full history) re-windows the past half. Not cached. matplotlib absent → 503 with install hint |
| GET    | `/api/activities`               | Completed activities (`?start_date=&end_date=`) |
| GET    | `/api/daily-signals`            | Daily-signals (`signal list`; `?start_date=&end_date=&metric=`) |
| GET    | `/api/daily-signals/metrics`    | Distinct signal metrics with counts + first/last date (`signal list-metrics`) |
| GET    | `/api/metrics`                  | Cached metrics (range, else last 30 days)    |
| GET    | `/api/models`                   | Configured LLM menu with the active entry marked (`settings list thinking-model`) → `{models, active, source, set_at}` |

Every other verb on every path returns **405** `{error, method, path}`.

---

## 9. Configuration (`config.yaml`)

The file is `config.yaml` at the repo root unless the `STAMIND_CONFIG` env var names
another one — that is how a second athlete runs from the same checkout: own config, own
`database:`, own `science/` guidelines, own `logs/`, own Telegram token and Garmin
account; only the code is shared. An explicitly named file must exist and parse (a typo
aborts rather than silently running against the primary athlete's database). Relative
`database:`, `science_dir:`, `logging.dir`, `service_account_file` and
`garmin.token_dir` values resolve against the config file's directory — or, when the
top-level `data_dir:` key is set, against that directory (itself config-file-relative),
which moves the whole instance's state under one prefix without repeating it on every
path key — the Garmin token store (default `.garminconnect` beside the config,
DESIGN_garmin_direct_pull.md §11) included, so a `data_dir:` instance keeps its own:
garminconnect resumes a stored token before it looks at the configured email, so two
athletes sharing one store would silently pull one Garmin account's data. Two athletes
share one set of guidelines only by pointing `science_dir:` at the same absolute path,
never by default.

Keys — dotted names are nested sections (`llm.api_key` is `llm:` → `api_key:`). Everything
but the credentials is optional and falls back to the default shown:

| Key                    | Type | Description                                                   |
|------------------------|------|---------------------------------------------------------------|
| `llm.api_key`          | str  | OpenRouter key; the `OPENROUTER_API_KEY` env var wins when set |
| `llm.models`           | list | Models both model roles pick from, in display order; the first entry is the default until `settings set thinking-model` picks another. Absent/empty → `google/gemini-3.5-flash` alone (DESIGN_model_selection.md §1) |
| `google.calendar_id`   | str  | Target calendar ID                                            |
| `google.storage_bucket` | str | Optional. The Google Cloud Storage bucket the pages read their files from; unset, nothing is built or uploaded and the buttons are as before (DESIGN_miniapp_storage.md §3, §11) |
| `garmin.email` / `garmin.password` | str | Garmin login; config.yaml only (kept out of the environment) |
| `garmin.token_dir`     | str  | Garmin token store (default `.garminconnect` beside the config, or under `data_dir:`) |
| `refresh_minutes`      | int | Throttle window shared by Garmin pulls **and** Calendar-signal syncs; reads inside it reuse the cache. Top-level, default 120; read as `config.data_refresh_minutes` |
| `garmin.mutable_days` / `garmin.backfill_prompt_days` / `garmin.initial_backfill_days` / `garmin.throttle_seconds` | — | Auto-ensure tuning (defaults 3 / 30 / 90 / 0.2; see [§10 Data Pull](#data-pull-data-pull-and-auto-ensure)) |
| `garmin.pmc_ctl_days` / `garmin.pmc_atl_days` | int | PMC time constants (42 / 7 — the supported configuration, [§12](#fitnessfatigueform-pmc-model)) |
| `garmin.hr_zone_coverage_min` / `garmin.zone_min_activity_minutes` / `garmin.zone_coverage_display_min` / `garmin.zone_coverage_display_min_by_sport` | — | Load-model coverage gate (0.5), the too-short-to-judge cut-off (20 min) and the display coverage bars (0.8, per canonical sport) — [§12](#load-model-per-activity), DESIGN_intensity_distribution.md |
| `garmin.hours_load_floor` | float | Load per hour an activity or a planned session must exceed for its time to count in the week's hours (10, what an hour at RPE 1 gives) — DESIGN_progress_timeline.md §7.1 |
| `google.service_account_file` | str | Path to service account JSON (default: `service_account.json`) |
| `data_dir`             | str  | Directory every relative path key below resolves against, replacing the config file's directory as the base; itself config-file-relative. Absent → the config file's directory (the pre-`data_dir` rule) |
| `database`             | str  | SQLite file this instance operates on; a relative value resolves against the config file's directory / `data_dir:` (default: `stamind.db`) |
| `science_dir`          | str  | Directory whose `*.md` files become the ATHLETE-PROVIDED science section in every coaching prompt (`coach/formatting.py:_load_science_guidelines`); a relative value resolves against the config file's directory (default: `science`). The app's own `stamind/science/` is not configurable |
| `logging.dir`          | str  | Root of the operator log directories — `runs/` (the journal, read with `sm journal`), `llm_exchanges/` (the full prompts) and `gym_logs/` (each gym logger message, as `strength ingest` was given it). Relative to the config file's directory, like `database:` (default: `logs`). DESIGN_logging.md §6 |
| `logging.level`        | str  | Lowest level that reaches the journal file: `debug`\|`info`\|`warn`\|`error` (default `info`). `debug` turns on the records for exceptions the app deliberately swallows on screen |
| `logging.retain_days` / `logging.retain_exchange_days` | int | Days each directory keeps (default 90 each). The sweep runs at most once a UTC day, off the first command to finish; `sm journal prune` forces one |
| `llm.fast_model`       | str  | Cheaper model the bot's free-text router (`sm bot route`) and its capture extractions (`sm bot capture`) use; a role, not a `settings list thinking-model` entry. Absent → the active thinking model (DESIGN_bot_simple_frontend.md §5.4, §12.2) |
| `telegram.operator_name` | str | What the companion calls the human who runs the CLI. "Coach" is already the app in the athlete's vocabulary, so the operator gets a word of their own; absent → "the person who set this up for you" (DESIGN_render_persona.md §5) |
| `telegram.push.*`      | —    | Morning push: `enabled` (default true), `morning_time` (`08:00`), `morning_deadline` (`15:00`), `evening_time` (`21:00`, from when the bot sends no queued item and no notice on its own), `adapt_first` (default false → ask the week planner before rendering, when something is new since the last run or a night since the last one in hand is not normal, else the morning is quiet, DESIGN_quiet_morning.md §2; a session it would change is saved as a proposal the athlete answers with a tap, DESIGN_waiting_proposal.md §5) |
| `telegram.bot_token` / `telegram.allowed_chat_ids` | — | The bot's token (or the `TELEGRAM_BOT_TOKEN` env var) and the numeric chat-id allowlist that gates every chat |
| `telegram.command_timeout_seconds` / `telegram.prompt_timeout_seconds` | — | The silent-run watchdog (180) and the idle-prompt cancel (300) |
| `telegram.send_retry_seconds` | float | How long a call Telegram failed to answer is tried again before the bot gives up and journals one warning (default 180; 0 = off). The poll is not affected. DESIGN_telegram_send_retry.md §3 |
| `telegram.change_delay_minutes` | int | How long a change to one of today's sessions waits before the athlete is told, measured from the newest waiting change so a second run restarts it (default: 20; 0 sends on the bot's next wake). Also a setting (`settings set change-delay N`). DESIGN_change_heads_up.md §4 |
| `telegram.confirmation_days` | int | On how many mornings after the day it was asked a question about what the athlete just wrote, such as "Shall I pass it to your coach?", is sent again after the morning message; on the next one it closes (default: 3). Also a setting (`settings set confirmation-days N`). DESIGN_chat_questions.md §2 |
| `web.host` / `web.port` / `web.debug` | — | Where the dashboard binds (`127.0.0.1` / 5000 / false) |
| `coach.metrics_lookback_days` | int | Rolling window for adaptation (default: 15)                  |
| `coach.signal_days_lookahead` / `coach.signal_days_min_days` | int | The look-ahead that groups signal days into one episode (default: 3) and the fewest signal days worth showing (default: 1) (DESIGN_quantitative_signal_impact.md) |
| `learning_staleness_days` | map | Days a learning may go unreinforced, per confidence level, before it is dormant and steps down one level (DESIGN_evidence_based_confidence.md §3) |
| `coach.adapt_terminal_window_days` | int | How close to a mesocycle's end counts as its terminal window (default: 3). Gates what the coach **model** is told (`THIS MESOCYCLE IS ENDING`); the CLI's end-of-schedule hint runs on the knob below |
| `coach.runway_warning_days` | int | How many days ahead the daily surfaces announce that the scheduled workouts run out — and how many days past the end they keep saying so before going quiet (default: 7). DESIGN_runway_nudge.md §7 |
| `coach.workout_generation_span_days` | int | Default span length for `workout generate` (default: 28)     |
| `coach.workout_commitment_days` | int | Days from today the athlete is treated as already committed to: the sessions standing there reach the `workout generate` prompt to be answered for one by one, and a removal there keeps its Calendar event, marked (default: 7; 0 disables both). Also a setting (`settings set commitment-days N`). DESIGN_plan_change_continuity.md §4.1 |
| `strength.sets_since` | date | First day whose strength sets are read from Garmin: before it the athlete did not correct the watch, so the names were not checked. Unset, no sets are read. Also a setting (`settings set strength-sets-since 2026-09-03`). DESIGN_strength_tracking.md §3 |
| `strength.recent_days` | int | How many recent strength days the strength history shows, per exercise and as whole sessions, and the naming answers are ranked over (default: 8). DESIGN_strength_tracking.md §8 |
| `strength.habit_after` | int | How many times a departure from a strength session's prescription happens before the strength planner writes it in (default: 2). It only counts the days `recent_days` shows, so raise that with it. DESIGN_strength_tracking.md §9 |
| `coach.replan_displaced_load_pct` / `coach.replan_rest_span_days` | — | The two constraint-magnitude triggers behind the `constraint add`/`edit` replan proposal (defaults 50 % / 3 days; [§3](#coachservice)) |
| `coach.minor_activity_load_threshold` | float| Workload score below which an activity is "minor"            |
|                         |      | (default: 25). Controls rest-day violations and unplanned    |
|                         |      | activity visibility (shown as gray/minor if below threshold,  |
|                         |      | yellow/unplanned if above). Mismatch tolerance for planned   |
|                         |      | workouts is dynamically computed from expected workload.     |
| `coach.rpe_divergence_ratio` | float| sRPE-load ÷ measured-load above which a session is flagged   |
|                         |      | to the coach as "felt harder than measured" (default: 1.5;   |
|                         |      | set very high to disable)                                    |
| `learning_confidence_thresholds` | dict | Distinct net supporting weeks to reach each confidence |
|                         |      | level: `{moderate: 3, established: 5}` (defaults). Tentative ≥1 |
|                         |      | and proposed-retirement ≤0 are fixed. Re-levels on recompute. |
| `coach.threshold_replan_pct` | float| Relative drift (%) a physiological threshold may move from   |
|                         |      | the plan-generation value before the plan is flagged stale   |
|                         |      | (default: 5).                                                |
| `user_profile`          | dict | Athlete profile section (see below); no threshold required   |

`user_profile` keys: `name`, `birth_year`, `gender`, `max_hr`, `weekly_target_hours`,
`sport_preferences`, `chronic_injuries`, `preferences`, `equipment`,
`weekly_schedule`. `weekly_schedule` maps day names to
`{total_available_hours, max_sessions, certainty_percent, equipment}`; it is
optional — without it the week planner places sessions on any day, sized by
`weekly_target_hours`, and the prompt says so instead of listing days. Trainable
thresholds (`ftp`/`lthr`/…) are **not** here — they live in the `benchmark_results`
logbook (`DESIGN_benchmark_workouts.md` §3.4); config keeps only quasi-fixed `max_hr`. A
threshold-less profile is a valid cold start (the coach nudges, never refuses).

Not every key flags the active plan stale when edited. `name`, `equipment` and each day's
`equipment` reach the prompt but do not shape the periodization, so editing one proposes no
replan; the rest of the mesocycle does (`DESIGN_plan_staleness.md` §3–§4).

---

## 10. Key Data Flows

### Plan Generation (`plan generate`)
1. `CoachService.plan_generate()` fetches the active objectives and constraints and
   computes `goals_hash`, `constraints_hash` (plan-shaping constraints only) and
   `config_hash`.
2. When `config_changed()` reports no drift on the existing macrocycle, no plan feedback is
   pending and `force=False`, the plan is reused. Pending notes open the gate on their own
   (DESIGN_plan_feedback.md §7).
3. Otherwise it builds the read-only planned-vs-actual review
   (`_build_prior_training_context()`, DESIGN_backward_evaluation.md §6, §10.1) and the
   records of past plans (`_plan_retrospectives_text()`, DESIGN_cycle_retrospective.md
   §7), and passes them with the active learnings into
   `CoachEngine._plan_generate_strategy()` → LLM → `{strategy, mesocycles}`. The review
   reaches the screen only under `--show-llm-context` (DESIGN_output_verbosity.md §7).
4. The plan window runs from the start date to the goal, with no minimum or maximum
   length: the science guidelines decide how to periodize it, and Stamind never invents
   intermediate goals. A kept in-flight mesocycle may start before the plan start
   (DESIGN_mesocycle_progress.md §7).
5. Saves the new macrocycle and its mesocycles as the goal's active plan version; the
   previous version is kept as superseded (`plan versions`, DESIGN_plan_rollback.md).

### Workout Generation (`workout generate`)
1. The CLI resolves the span, both ends (`_resolve_span`): the selectors, else from the day
   after the schedule stops for `config.workout_generation_span_days`; a span never opens
   before today (DESIGN_cli_selectors.md §8). When live sessions stand inside it, the CLI
   confirms before the model call; `-f/--force` skips every prompt.
2. `CoachService.workout_generate(start_date, end_date, prefer_macro_id, fresh)` resolves
   the mesocycles governing the span (`db.get_governing_mesocycles`: the dates decide, not
   a goal), raises "run `plan generate`" when none does, and fetches the metrics history
   and the baseline.
3. It builds the prompt's context: the elapsed part of the mesocycle being continued
   (`_mesocycle_progress_context`, DESIGN_mesocycle_progress.md,
   DESIGN_intensity_distribution.md §9.2a) and the sessions already standing in the
   commitment window (`--fresh` empties it; DESIGN_plan_change_continuity.md §4, §6.1).
4. `CoachEngine._workout_generate_logic(num_days)` → LLM → `{reasoning, athlete_note?,
   workouts[]}`, read-only with respect to learnings ([§3](#3-coach-package-architecture)).
   `_resolve_standing` maps the answers onto the standing sessions (`keep`, `drop`,
   `replaces`; DESIGN_plan_change_continuity.md §4.5), then the deterministic passes run
   (a `rest` constraint's row, §5.5 there; coverage, DESIGN_runway_nudge.md §2.1).
5. The strength planner (`strength/planner.py::run`, DESIGN_strength_tracking.md §9)
   writes every strength session that has no prescribed sets yet from its brief and checks
   the ones the athlete was already shown, in one call. A week with nothing to write costs
   no call.
6. The result is a `GenerateProposal`, nothing written: the sessions, the voids with their
   reasons, and a `StandingLine` per session the athlete was told about, computed from
   what apply will write. The CLI prints them through the same `session_table` as
   `workout list -v`, then asks.
7. On a `y`, `workout_generate_apply(proposal)` opens one `generate` change stamped with
   the coach's line (`note`) and `commitment_end`: the voids first, then one revision per
   day filled, tagged with the `macrocycle_id`, unless identical to what is live. Calendar
   follows from the change handle's reconcile pass. Undo is `workout rollback`, or `plan
   rollback` to step the strategy back with it.

### Daily Adaptation (`workout adapt`)
1. `CoachService.workout_adapt()` fetches the window's metrics, planned sessions
   (`include_removed=True`; the removed ones are shown as deliberate cancellations),
   completed activities and daily signals (from one day earlier than the metrics, since
   recovery lags the signal; DESIGN_quantitative_signal_impact.md §6.1). A `-m/--message`
   note rides as a bounded prompt section, and the same call says which session it is
   about (`note_session`; "unclear" with several sessions asks on a terminal and queues in
   the chat, DESIGN_session_notes.md §3). Where it reads its inputs it takes the picture
   of them (`coach/picture.py:take`), identifiers and hashes the next morning compares
   with; a tweak takes none (DESIGN_quiet_morning.md §3).
2. `analyze_adherence()` grades the active sessions only. The window ends on the
   evaluation date, so `pending_from=target_date` marks that day's untrained sessions
   pending, not missed; only the absence of an activity is deferred this way.
3. The active mesocycle for the target date sets `meso_end_date`, the adaptation range's
   end; the seven days after it are read too and shown read-only
   (DESIGN_mesocycle_boundary.md §7). `_intensity_mesocycle_context()` adds the
   mesocycle's measured intensity distribution as its own `intensity_context` argument,
   which gates the `CORRECTING EXECUTION DRIFT` branch
   (DESIGN_intensity_distribution.md §9.3).
4. `CoachEngine._workout_adapt_logic()` → LLM → `{change_needed, reason,
   adapted_workouts[]}`, read-only with respect to learnings.
5. Any proposal dated outside the range (the mesocycle firewall's write side,
   `guards.py:_keep_inside` with a notice, the same drop `workout generate` runs on its
   span; DESIGN_mesocycle_boundary.md §1, §7) or targeting a completed session is dropped;
   a session under a `rest = 1` constraint is eased to rest
   (`guards.py:_enforce_rest_windows_revision`, DESIGN_constraints.md §6).
   `_resolve_moves` reads each entry's `replaces` (DESIGN_workout_revisions.md §4), then
   the strength planner runs on the same `strength/planner.py::run`
   (DESIGN_strength_tracking.md §9). The result is a `RevisionProposal`
   ([§3](#coachservice)); the caller asks about each extracted constraint and signal
   candidate (`cli/candidates.py`: on the spot on a terminal, queued in the chat).
6. If applied, `workout_revision_apply()` opens one `adapt` change: a session overridden
   with nothing becomes a void, a moved one a void at the source plus a revision at the
   destination with the same lineage, and the batch rationale lands on the change row as
   `summary` and as the athlete's line `note` (DESIGN_change_heads_up.md §6). Whether a
   revision counts as an easing is decided at read time, against its predecessor
   (DESIGN_workout_revisions.md §7). Calendar follows from the reconcile.
7. A run started from the athlete's chat does not ask and apply: `_adapt` saves the
   proposal to the athlete queue (`cli/workouts/proposal.py:save`) and sends it
   (`cli/queue.py:send_alone`); "Change it" writes it through `workout_revision_apply`
   unless it is out of date. One proposal is open at a time: every run reads it
   (`proposal.open_proposal`) and shows it to the week planner
   (`proposal.shown_to_week_planner`), and saving one closes the others
   (DESIGN_waiting_proposal.md §2, §3, §6, §7).
8. Apply, no-change and save each write the run's picture to the `settings` row
   `adapt_last_seen` when the run was evaluated on today (`picture.remember`). With
   `adapt-first` on, the morning push (`cli/bot/views.py:_asks`) runs `workout adapt` only
   when a fresh picture differs from it (`picture.news`, the table in
   DESIGN_quiet_morning.md §3), or a night since the last one in hand is not normal
   (`picture.nights`, after the forced pull, §4). Otherwise the morning is quiet, with one
   journal `note`; a missing or broken picture or an error in the gate asks (§5, §6).

### A change on request (`workout tweak`)

1. `run_workout_tweak` runs `workout adapt`'s CLI flow (`_adapt(args, tweak=True)`): the
   same pull, preview and apply. `-d` may be given once per day.
2. `CoachService.workout_tweak()` calls `workout_adapt(..., tweak=True)`: the TASK head
   becomes the request's, the fatigue, drift and terminal-window sections are left out,
   and the request and every cancelled session ahead sit under sections of their own
   (DESIGN_workout_tweak.md §3, §4).
3. The days are the `-d` days, else the reply's `tweak_dates`; a reply that names no day,
   or a day past the current mesocycle, stops the run, and every entry on another date is
   dropped before the moves are resolved (§3.2). A tweak that replaces an open proposal
   may also write that proposal's days (DESIGN_waiting_proposal.md §6.2).
4. The proposal has `kind="tweak"` and covers no constraint; apply records a `tweak`
   change, with no `[Adapted]` tag, which restarts the count of easings like a `generate`.

### Data Pull (`data pull`) and auto-ensure

Data is pulled directly from Garmin Connect (`stamind/garmin/`,
DESIGN_garmin_direct_pull.md).

1. `garmin.pull(start, end)` logs in (token persistence, TTY-gated MFA), fetches
   activities (storing the measured TSS and the athlete's own RPE, neither synthesised)
   and daily metrics, writing a row to `athlete_metrics_cache` for every day in range,
   all-null ones included, so the table's coverage records what has been pulled. It then
   reads the sets of every strength activity never read
   (`strength.sets.read_new_activities`, DESIGN_strength_tracking.md §6).
2. `garmin.recompute_derived()` runs a full sweep over every cached day: the PMC EWMAs and
   the 28-day baseline. The ATL:CTL ratio is derived at read time (§12).
3. The `sync_state` watermark advances (`through_date` forward only, `last_pull_utc`).

**Auto-ensure.** Read-side commands call `garmin.ensure_data(start, end)` at entry
(idempotent per process). It pulls the derivation-padded window when the gap is small or
recent, prints a copy-pastable `data pull` for a large backfill and continues on cached
data, and always pulls a warm-up gap lying before the requested window. It also rides
along the Calendar daily-signal sync (`gcal.client.sync_calendar_signals`) under the same
`data_refresh_minutes` throttle; `--no-pull` and `--force-pull` override it. Dates are the
athlete's (`clock.today_date`, DESIGN_user_timezone.md §1); stored instants stay UTC. The
web app never calls this.

### Data Analysis (`data bootstrap` / `data reflect`)

Both share `CoachService._run_workout_analysis()`; they differ in how the window is
resolved and whether they set or advance the reflect watermark (`sync_state`, key
`reflect`). `data bootstrap` (once) resolves a wide window from the goals (else 12 weeks),
runs under horizon `long`, sets the watermark, and is confirmed before a repeat run
(`--force` proceeds, `--auto` skips). Its reconstruction is what `plan generate` reuses
and what `progress` draws its `~` bands from (`analysis_cache`, [§5](#5-database-schema)).
`data reflect` (incremental) starts the day after the watermark, runs under horizon
`short`, advances it forward only, and returns without a model call when there is no new
evidence.

The shared core:
1. Queries the window's completed activities, metrics and constraints (discounting
   context only: a constraint may explain an anomaly away, never support a learning).
2. Builds `signal_days` (`_signal_days`, DESIGN_quantitative_signal_impact.md) over the
   athlete's full history, then computes the evidence fingerprint and checks
   `analysis_cache[horizon]`: a match without `--force` returns the cached reconstruction
   ([§5](#5-database-schema)). The check lives only in this writing flow.
3. Groups activities and metrics by Monday-commencing ISO week, each weekly summary
   carrying the overlapping constraints and the recovery z-scores
   (DESIGN_richer_analysis_evidence.md), all deterministic.
4. `CoachEngine._data_analyze_logic()` → LLM → the reconstruction and `learning_updates[]`.
5. Unless `--inspect-only`: applies the `learning_updates` to each learning's evidence
   basis and re-derives confidence (upgrade auto, downgrade proposed;
   [§3](#3-coach-package-architecture), DESIGN_evidence_based_confidence.md §6), caches
   the reconstruction, and `_review_learning_proposals(auto)` resolves the pending
   downgrades (§7 there).

### Cycle retrospectives

A finished mesocycle or plan gets a short record of what it was for and what came out of
it (DESIGN_cycle_retrospective.md). The date check (`stamind/cycle_records.py`, §3)
decides which records exist; it runs at the start of `plan generate` and `workout adapt`,
in the morning routine and inside `goal_archive`, through
`CoachService.retrospectives_step`. The write step (`coach/service/retrospective.py`, §4,
§5) fills a blank record once it is due, seven days after its end: it refreshes Garmin,
computes the numbers and calls the retrospective writer (`coach/engine/retrospective.py`),
one record per run. The question (`stamind/retrospective_question.py`, §4) is queued when
the record is created and asked once, and an answer runs the writer at once. The record of a
plan covers its mesocycle records (§6). `plan generate`'s prompt is the only reader (§7); `plan show
-vv` and `plan retrospective` show the records (§8), and `plan retro redo` is §9.

---

## 11. Terminology: Plans vs. Workouts

- **Plan** = the periodization: one *active* macrocycle per goal, superseded versions
  kept, plus its mesocycles (the `plan` commands, [§7](#7-cli-commands-reference);
  versions and undo, DESIGN_plan_rollback.md).
- **Workouts** = the sessions the week planner writes under a mesocycle (the `workout`
  commands, §7; the flows, [§10](#10-key-data-flows)).

Every session is written by the coach. A change the athlete decided is `workout tweak`
([§10](#a-change-on-request-workout-tweak)); the request travels in the session's
`modification_reason` ("On request: …"), which the next `workout adapt` reads and leaves
alone unless the metrics call for a change.

---

## 12. Sports Science & Coaching Mathematics

### Load model (per activity)
The stored `tss` column is the **objective measurement only**; the training
**load** is derived on the fly (`analytics.load.activity_load`) via a best-available
fallback — methods are never blended or max-ed:

1. **Power TSS** (Coggan 7-zone, `POWER_ZONE_TSS_PER_SEC`) when a power meter
   recorded — `TSS/s = IF² × 100 / 3600` per zone (Z6/Z7 extrapolated, Z7 IF
   capped at 1.60).
2. **hrTSS** (Friel 5-zone, `HR_ZONE_TSS_PER_SEC`) when HR-zone coverage
   ≥ `config.hr_zone_coverage_min` (`garmin.hr_zone_coverage_min`, default 0.5).
   Coverage = Σ(HR-zone secs)/duration; guards
   against Garmin's HR zone-1 floor zeroing out low-intensity work (yoga, easy
   walks, lift-served skiing).
3. **Session RPE** (Foster sRPE = `RPE × 10 × hours`) when the user entered an
   RPE and power is absent / HR is too sparse. **RPE is user-entered only and
   never computed from power or HR.**

When method 3 should apply but no RPE was entered, the weak hrTSS (or 0) is kept
and the activity is counted in an aggregated underestimate warning. There is no
activity-type special case — coverage + the divergence flag cover strength and
hybrid activities (e.g. kettlebell HIIT: hrTSS captures the cardio, divergence
flags the muscular cost).

### RPE divergence (external vs internal load)
`analytics.load.rpe_divergence` flags activities where the measurement came from power/HR but the
user's RPE implies ≥ `rpe_divergence_ratio` (config, default 1.5) × the measured load —
i.e. it felt harder than it measured (heat, sleep debt, muscular damage). For those rows
`activity_load()` takes **the load from RPE instead**, and `load_method()` returns the
distinct `rpe_divergence` provenance, so every downstream number (PMC, weekly load,
zones) carries the bump. The stored `tss` measurement is left untouched; the ratio is
what explains the bump to the coach.

### ATL:CTL load ratio
`analytics.pmc.load_ratio(atl, ctl)` = ATL ÷ CTL at read time, never stored;
`color_load_ratio` colours the overload end only (`training_load.md` §4 judges a low ratio
against the mesocycle). It replaced the ACWR model (DESIGN_load_ratio.md).

### Fitness/Fatigue/Form (PMC) model
Two layers, one recurrence. The EWMAs are the whole stored load model, and the ATL:CTL
ratio above is derived *from* them — different questions off one series: asymptotic
fitness/form (CTL/ATL/TSB) and scale-invariant relative overload (the ratio).

**Backward core** (`analytics/pmc.py`, DESIGN_pmc_fitness_fatigue.md §3): `compute_pmc()`
walks the classic Coggan EWMAs over every calendar day, TSB = yesterday's CTL − ATL;
`garmin/derived.py` stores them on `athlete_metrics_cache` in every `recompute_derived()`
sweep and holds `warmup_cutoff`, the one warm-up cutoff every surface blanks against; the
time constants are config (`pmc_ctl_days`/`pmc_atl_days`) and `analytics.pmc.pmc_cells`
renders the triple.

**Projection layer** (`analytics/progression.py`, `analytics/timeline.py`,
DESIGN_progress_timeline.md §3, §4): past days read the stored series verbatim; the anchor is
the last stored row strictly before today, and from it the same recurrence is folded
forward over the actual-then-planned daily load, stopping at the last generated session.
`assemble_timeline` builds the payload and `timeline_rows.py` is the one row fetch behind
every surface.

### Daily Readiness Signals
The thresholds are `analytics/baselines.py` (its docstring states them). `workout adapt`
reads them over `metrics_lookback_days` and discounts a depressed morning that a logged
signal explains (DESIGN_quantitative_signal_impact.md §6.1).

### Science Guidelines Files
`stamind/science/` is built in; `science/` (`science_dir`, gitignored) is the athlete's,
injected into every prompt and snapshotted on the macrocycle so an edit flags the plan
stale (DESIGN_plan_staleness.md §11); `science.samples/` holds sets to copy from. How the
two are layered is [§3](#_load_science_guidelinesapp_science_dir-science_dir--str).

---

## 13. Daily Signals (Calendar Ingest)

External daily signals (alcohol, sleep quality, stress, a heatwave) reach Stamind through
the one Google Calendar: one all-day event per signal-day, tagged in
`extendedProperties.private` with `source=stamind-context` (configurable as
`calendar_signal_tag`), a `metric` and an optional numeric `value`. Any producer may write
them; Stamind's own `signal` command is one.

**Inbound flow:**

```
Calendar (tagged events) ──► gcal.client.sync_calendar_signals
   ──► calendar_syncer.sync_signals (syncToken; server-side filtered on the full
                                     pull only, client-side otherwise)
   ──► db.upsert/delete_daily_signal_by_event ──► daily_signals table
   ──► coach analysis weekly summaries (per-week `daily_signals`)
```

Where the code is: `gcal/client.py::sync_signals` (its docstring is the `syncToken` rule),
reached through `sync_calendar_signals`, which `garmin/sync.py` rides along `data pull`
and `ensure_data` under the Garmin throttle (DESIGN_calendar_signal_ingest.md);
`db/signals.py` for the rows; `cli/signals.py` for `signal add/rm/list/list-metrics`, which
write the same tagged events and mirror them locally (DESIGN_signal_authoring.md);
`stamind/signals.py` for the vocabulary. The coach reads the rows in each week's summary
and, by value, through `signal_days` (DESIGN_quantitative_signal_impact.md).

---

## 14. Testing

Tests use `unittest`. The command, and the memory cap to run it under, are in AGENTS.md.

### Which layer may load which

Three rules. The first two, and §2's chat rule, are asserted in `tests/test_layering.py`,
by importing a module in a fresh subprocess and reading `sys.modules` afterwards — what
actually got loaded, not what the file says it imports. Those are keyed on module-name
prefixes, never on a list of files, so a module added tomorrow is covered the day it is
written. The third is written down here and nowhere else.

**Nothing under `stamind/analytics/` loads `stamind.db`.** It is training maths
over rows the caller fetched. A module there may still *take* a database handle —
`adherence_window` does — because being handed one is not the same as importing the
storage layer. The rule is what lets the coach, the CLI and the web app share one
load model without three of them paying for a package they are not using.

**Importing `stamind_web` loads no `stamind.cli`, no `stamind.coach`, no
`stamind.openrouter`, no `stamind.gcal` and no `googleapiclient`.**
The dashboard reads and writes nothing (§8), and that is a claim about capability,
not intent: a reader that has imported the coach service is one call away from
writing, and the operator reading a chart did not ask for either. It also means the
web process starts without a service-account file or an OpenRouter key.

**The model client stays off the CLI's startup path**, and so does any package a command
only sometimes needs (`garmin/`, the Google libraries). `stamind/openrouter.py` imports
`requests`, so a module the dispatcher reaches imports the client inside the function
that calls it; a module only the coach service reaches (`coach/engine/`,
`strength/planner.py`) imports it at the top. Two places catch people out:
`strength/questions.py`, which `athlete_queue.py` imports and every `cli/` module that
imports the queue reaches through it, and `cli/bot/`, whose `__init__.py` lists its four
deferred imports. No test holds this rule: `tests/test_layering.py` covers the analytics
package, the web app and the chat package only.

Each test file's module docstring says what it covers. `tests/test_cli_*.py` is one file
per command family, output and argument handling with the service mocked, and
`test_dispatch.py` walks the parser tree itself (every leaf binds a handler, every bare
group self-helps).

Tests get a fresh SQLite file per module (`tests.test_db_path`) and bind it through
`tests.helpers.rebind_test_db` / `bind_test_db`, which set `runtime.db` and the remaining
by-value sites in one call ([§6](#6-singletons)). `openrouter_client` is mocked via
`@patch`. `tests/__init__.py` installs the suite-wide seams before any module is
collected, and says why beside each: the production-database guard, the no-network guard,
the Calendar ride-along stub, the journal directory, the bucket, and the silenced
reconcile line. `tests/test_isolation_guards.py` fails on any module that builds a
database path beside the tests again.

The same file resolves every `patch("stamind…")` target in the suite by importing the
module half and reading the attribute half, the way `mock.patch` does, so a symbol that
moved to another file is one red test naming the target and the test file, instead of a
patch that stubs nothing while the test keeps passing. It reads a target a loop builds as
well as a literal one, because three of the four sites that name an `ensure_recent_data`
(`cli/status`, `cli/workouts/adapt`, `cli/workouts/generate`) build it that way and the
fourth, `cli/bot/views.py`, writes it out in full. A target passed `create=True` is
skipped; `patch.object` and `patch.dict` need no guard, since a name that has moved
raises `AttributeError` where it is used.

Asking `stamind.runtime` for an attribute would *build* the singleton — a Database
against the athlete's own file, a live Google client off the credentials — so the guard
asks its builder registry instead, and builds nothing ([§6](#6-singletons)).

Fixture dates ride on today (`_days_out(...)`/`GOAL_DATE`) rather than on fixed
dates wherever the code compares them against the clock: a plan window needs its
goal in the future, so a hardcoded date silently expires the test once it passes.

Integration / manual test scripts (not part of the test suite, and they do reach
the real Calendar):
- `scripts/run_integration.py`, `scripts/run_calendar.py`

---

## 15. Design Rationale & History

*Why* the current design looks the way it does. A decision with a design doc lives there,
and the section that implements it points at it. The entries below are the decisions
with no design doc of their own.

### Load model: single fallback, no additive blend
`Workload = activity_load(act)` picks one best-available method (power TSS → hrTSS →
sRPE); the former `TSS + RPE × hours` additive blend was removed because it
double-counted internal and external load. RPE is user-entered only and never
synthesised from power/HR. See [§12](#12-sports-science--coaching-mathematics).

### Goal dates: event vs. training horizon
Not every goal happens on its date — some dates only say how far the athlete wants to
train. Description prose could not express that: a goal stating, in capitals, that its
date was indicative and not a race still got a freshening phase pinned to the date,
because the event framing is structural — the planning task ("the last mesocycle must
end on or around the goal date"), its response format ("Peak & Taper, Race/Event"),
and the user message ("'{title}' on {date}") all restate it, and one `Details:` field
loses that argument every time. `objectives.date_type` (`event` default | `horizon`)
makes the meaning a field that both the prompts and deterministic code branch on: a
horizon plan still ends around the date (a plan needs an end), but its last mesocycle is
an ordinary training mesocycle with no peak/taper pinned to the date, and the goal-week
no-benchmark carve-out does not apply — there is no event for a maximal test to
compete with. `plan_inputs.clean_goals` includes the field only when it is `horizon`: an
event goal — every goal predating the field — hashes exactly as before, so shipping the
field did not flag existing plans stale, while flipping a goal either way adds or
removes the key, changes `goals_hash`, and prompts the replan that change warrants.
Current-state reference: [§5 objectives](#objectives).

### A session already behind us carries its verdict
`workout list` used to answer only "what was planned", so the athlete asking what they
did last week got the plan read back at them and had to run `workout compare` to find out
which of it actually happened — two commands for one question, and the listing quietly
implying that a session it drew was a session that took place. The verdict now rides on
the listing itself, today included: an untrained session on an unfinished day reads
`[NOT YET]` rather than `[MISSED]`, which is the `pending_from` rule
([§10](#10-key-data-flows)) surfacing where it is finally visible.

Nothing new grades anything. `analytics/compare.py::adherence_window` is the single
DB-backed pairing, handed the handle rather than opening one —
`analyze_adherence` over a window — and `adherence_verdicts` keys `classify_adherence`'s
answer by workout id; the Calendar marker, the terminal marker and the web badge are three
renderings of that one map. The wording is shared too (`adherence.STATUS_LABELS`): the
Calendar tag map was the only place a verdict had ever been given a word, so a second
surface would have invented a second wording, which is exactly how `[Partial]` on a
calendar event and something else in a listing would have come to describe one session.

Two things this forced. The listing grades its **whole** window rather than the rows it is
showing, because matching is per-day and first-come — hand it only the rows that survived
a `--type` filter and the day's activity goes to whoever is left, so a rest day beside a
ride would read `[REST BROKEN]` the moment the ride was filtered out. And the listing
became a command that reads completed activities, so it freshens Garmin like every other
one that does; the cost is bounded by scoping the pull to the past part of the window,
which leaves the ordinary forward-looking `workout list` entirely offline.

### The adapt prompt reads the verdict, not just the pairing
`workout adapt` is the fourth reader of that map, and for a while it was the one that
ignored it. It asked only whether a planned session had matched *anything*, and tagged
every match `[COMPLETED — locked history, not adaptable]` — collapsing `done` and
`partial` into one word. That is wrong in a specific and costly way, because
`indoor_cardio` is an alias of `strength_training`: a ten-minute warm-up logged before a
lift the athlete then abandoned pairs with the 65-minute session it was supposed to open.
The prompt told the week planner a session that never happened was in the bank, and the guard
that backs the tag dropped any proposal touching it — so the week planner could not salvage the
rest of the day even after reading, three sections lower, its own discrepancy line saying
10 minutes were performed against 65 planned.

`adherence.performed_sessions` now hands the prompt `classify_adherence`'s verdict plus the
duration and load actually recorded, and the tag states them: a partial says it is partial
and reports what was performed. The numbers, not an adjective, carry the meaning — a
partial is as often an overshoot as a shortfall, so the tag stays neutral and lets the
planned figures already on the line above do the comparing.

The lock narrows with it. History is still history: any match on a day already behind the
evaluation date stays locked, partial included, because rewriting a past calendar event is
meaningless whatever the verdict. On the **evaluation date** a session becomes history only
once its planned *time* was actually spent. Duration is the test, not load — strength load
read off heart rate is unreliable enough that this codebase already falls back to sRPE for
it, but minutes in the gym are not in doubt. So a session abandoned after its warm-up stays
adaptable for the rest of the day, which lands it in exactly the state an untrained session
on an unfinished day was already in (`pending`, above): on the evaluation date, a session is
locked only once the planned time has been spent. What the athlete already did travels with
it, so the week planner salvages the remainder rather than re-prescribing the whole session.

### A pairing the matcher had to guess at is a question, not a fact
Everything above assumes the pairing is right. Sometimes it is a guess, and one was:
`SPORT_MAPPING` lists `indoor_cardio` among `strength_training`'s aliases, so a
ten-minute warm-up logged before an abandoned lift was the only candidate on the day and
first-come load-sorted matching handed it the 65-minute session. Grading that pairing more
honestly does not help, because the pairing itself is what is wrong — the athlete did none
of the session, and calling it "partial, 10m performed" is a better-worded version of the
same false claim.

Only the athlete can settle it, so `adherence.is_ambiguous_match` marks the pairings worth
asking about and `pending_match_questions` raises them. A terminal run of `workout adapt`
with someone there asks **before** the LLM call, not after: a wrong pairing does not merely
mislabel a row in a listing, it tells the week planner a session was performed, and by the
time a proposal comes back that premise is already baked into it. Every other run — the
chat, the morning run, `-y` — never waits on the athlete: it queues "Was that the session,
cut short?" (the `cut_short` kind, `cli/workouts/cut_short.py`) and goes on with the
matcher's own pairing. That question stands at the front of the line, so its answer reaches
the next run, and closes after the `confirmation-days` mornings (DESIGN_chat_questions.md
§3).

The test is duration alone. By the time a pairing exists the sport check has already done
its work — a ride never reaches a strength session, whatever its length — so the type is
not what is in doubt. What is left undecided is that an activity of the right sport ran far
shorter than planned, which is either the session cut short or something else entirely (a
warm-up, a fragment). Nothing in the data separates those two readings, and the athlete's
answer is different in each case: count it as partially performed, or discard it and let
the session read as not done.

That applies to an exact sport match as readily as an aliased one. A 10-minute
`strength_training` activity against a 65-minute lift is exactly as unclear as a 10-minute
`indoor_cardio` one; an earlier version of this excluded exact matches on the theory that
they must be a cut session, which is only one of the two things it can be. An activity that
ran roughly its planned length is never questioned, so an ordinary day costs nothing.

The answer persists in `activity_match_decisions`, keyed by `(activity_id, sport)` rather
than by workout id — workout rows are replaced on every revision, so a workout id would go
stale the next time the day is adapted and the athlete would be asked again. Every
adherence surface passes `db.get_rejected_matches()` into `analyze_adherence`, so the
terminal listing, the web badge and the coach cannot disagree about what counts as done. A
rejected activity is passed over for that session and stays available to the rest of the
day's pairing, which is what makes it fall through to the unplanned/informational path
rather than vanishing.

The question is a refinement, never a gate: a run that queues it falls back to the
matcher's own answer, which the duration rule above already makes sane.


### The sport check only does its work if it matches exactly
The section above rests on "a ride never reaches a strength session, whatever its length."
It did. `SPORT_MAPPING` lists `fitness` among `strength_training`'s aliases, and matching
fell back to a substring test — `t in act_type` — so Garmin's `e_bike_fitness` contained an
alias and a 34-minute e-bike ride was handed a 10-minute evening circuit.

The damage was not the mislabelled row. The pairing graded `partial`, and because the ride
ran *longer* than the circuit there was no duration shortfall, so `is_ambiguous_match` had
nothing to question and `performed_sessions` marked the session `locked` — history, not to
be rewritten. When the athlete said that evening that the circuit was off, the adapt could
only add a copy to the next day; it was not permitted to withdraw the original. A loose
string test became a plan the athlete never chose.

The substring fallback had no legitimate work to do: across both instances every real
pairing was already an exact alias hit, and the only matches it added were wrong ones. It
also quietly folded every resort ski day into `ski_touring` — each `downhill_skiing` alias
ends in `skiing`, which `ski_touring` also lists — collapsing the one distinction
`SPORT_MAPPING` draws most deliberately. Matching now canonicalizes both sides and compares
them exactly, which is the rule the zone vocabulary already settled on for the same reason
(DESIGN_intensity_distribution.md §6.1 "Exact over substring"): an unrecognised type stays
unrecognised, visible as its own row, and is repaired by adding an alias — not by a net
that guesses. `e_bike_fitness` is deliberately left unmapped; a motor-assisted ride is not
a cycling activity, and its load still reaches the PMC through `completed_activities`.

### Where the files are cut, and why

Four layout decisions with no design doc and no other home in this document.

- **`coach/` splits into `engine/` and `service/`, not by domain.** The engine writes the
  prompts and makes the model call; the service reads the database, orchestrates and
  prints. One place to patch the model call, and prompt tests that run without a
  database. The names stay parallel: `engine/generate.py` ↔ `service/generate.py` ↔
  `cli/workouts/generate.py`, and the same for `adapt`.
- **The Calendar package is `gcal/`**, because the standard library owns `calendar` and
  the code has local variables of that name. `event.py` builds the whole event body with
  no Google import, so a test asserts on a body without a service account; `client.py` is
  the only file that calls the API. `reconcile.py` imports `client.py` inside the one
  function that needs it, and `gcal/__init__.py` re-exports nothing: either would put
  `googleapiclient` and the credentials read back into every importer of `reconcile`, and
  the read-only web app reaches `reconcile` through `runtime._build_db`. No test guards
  the deferred import; this is the only place the rule is written.
- **`freshness.py` is one answer to "is what we have fresh enough?"** for Garmin and the
  Calendar: the age of the last pull and the cache-hit sentence. A file of its own
  because neither `garmin/` nor `gcal/` may import the other. The decision itself stayed
  with each caller: Garmin carries on to fetch a missing day, while the Calendar sync
  returns on the spot.
- **`db/analysis.py` stays under the size floor** as a concept of its own (AGENTS.md): one
  reconstruction per horizon, keyed by an evidence fingerprint
  (DESIGN_backward_evaluation.md §5.1), with no tie to `db/activities.py` but a shared
  wipe.

---

## 16. Gym Logger (Telegram Mini App)

A gym session is the one session Garmin records badly, so the athlete ticks sets on a
page while resting between them, and every set arrives named. The contract is
DESIGN_gym_logger.md (§2 says where things live, §7 what it leaves undecided); the catalog
the page searches is DESIGN_exercise_table.md §3.2 and §8, and a logged session against
its planned lines is DESIGN_strength_planned_vs_done.md.

**Where the code is.** `miniapp/` is the page: static files, no build step, no server;
`logic.js` is the pure logic under node tests in `miniapp/tests/`, `app.js` the DOM,
`markdown.js` the export button, and `exercises.json` is built from the exercise table by
`build_exercises.py` (`tests/test_miniapp.py` fails when the two disagree).
`strength/logger.py` is the two payloads, pure and strict. `cli/strength_ingest.py` is
`strength ingest`; `strength/sets.py::read_new_activities` runs the takeover
(`db/strength.py::move_gym_log`) before any set is read from Garmin. The rows are
`gym_logs` ([§5](#gym_logs)). On the bot's side: `keyboards.gym_button`,
`app.ChatBot._keyboard` (built on every send) and `messages.on_web_app_data`; a typed
message starting with `{` is a pasted log on the same path. The bot parses nothing:
every write goes through the CLI. The comparison is `strength/comparison.py`, drawn by
`cli/common.py::strength_table` and `simple_comparison_lines` ([§6](#6-singletons) says
why they are not in `cli/render/`).

## 17. Calendar (Telegram Mini App and `sm calendar`)

The calendar is read-only: the sessions, what Garmin recorded, the goals, the
constraints, the signals and the mesocycles, and it changes nothing. The contract is
DESIGN_calendar_miniapp.md (§9 says where things live, §11 what it leaves out); the
encrypted month files both pages read from a bucket are DESIGN_miniapp_storage.md (§12
says where things live).

**Where the code is.** `stamind/calendar_days.py` gathers the facts, one `Day` per date,
and each view words them itself: `cli/render/calendar_page.py` (the page's snapshot and
month files), `cli/render/plan_page.py` ("Goals & plan"), `cli/render/calendar_grid.py`
(the terminal grid behind `cli/calendar.py`). The pages are `miniapp/calendar.html`,
`plan.html` and `details.html` (a proposal in full, DESIGN_short_messages.md §6) and their
`*_logic.js` under node tests, with `storage.js` the bucket read they share. `page_files/sync.py` adds the bucket parameters to both buttons and uploads
the files that changed after every command (`after_command`, from `run_once`). On the
bot's side, `ChatBot._page_buttons` builds both addresses on every send,
`RepliesMixin._send_keyed` is the one send that attaches the keyboard, and
`on_web_app_data` turns a `calendar_day` message into `workout show -d <date>` and a
`plan_why` one into `plan show --macrocycle <id>`; any other page message is a gym log
([§16](#16-gym-logger-telegram-mini-app)).
