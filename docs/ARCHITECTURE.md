# Stamind Architecture & System Manifest

This is the map a coding agent reads before its first grep; `AGENTS.md` (under *Code*)
says what it holds and what it does not. Each concept has one home here, and the other
sections point at it. The *why* lives in the `DESIGN_*.md` files, and
[§15](#15-design-rationale--history) holds the decisions with no design doc of their own.

## Contents

1. [System Overview](#1-system-overview)
2. [Module Map](#2-module-map) · [Change recipes](#change-recipes-where-to-edit-for-a-given-task)
3. [coach Package Architecture](#3-coach-package-architecture) — **canonical** coach-learnings / confidence model
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
daily based on Garmin metrics. Plans and workouts can be pushed to Google
Calendar.

```
  +--------------------------------------------------+
  |               User Interface Layer               |
  |  stamind_cli.py (shim) + stamind/cli/        |
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
  |  stamind/timeline_rows.py fetches the rows      |
  |    analytics/timeline.py assembles, so the fetch  |
  |    sits outside the package                       |
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
| `coach/` | `coach_service` | `service/` (`CoachService`: reads the database, orchestrates, prints), `engine/` (`CoachEngine`: the prompts and the model call), `formatting.py`, `honoring.py` (`honored_at`: who may stamp it, `needs_a_pass`, DESIGN_constraint_honoring.md), `proposals.py` and `revisions.py` (the frozen proposals and the pure helpers behind one) ([§3](#3-coach-package-architecture)) |
| `analytics/` | module functions | Training maths over rows the caller fetched: opens no database, calls no model (`tests/test_layering.py`). `load.py` (the load model), `pmc.py` (CTL/ATL/TSB), `adherence.py` and `compare.py` (the verdict on a planned session), `intensity.py`, `zone_tables.py` and `mesocycle_report.py` (time in zone, DESIGN_intensity_distribution.md), `progression.py`, `timeline.py` and `chart.py` (the progress timeline, DESIGN_progress_timeline.md), `runway.py` (DESIGN_runway_nudge.md §2), `weekly_evidence.py`, `baselines.py`. `__init__.py` re-exports nothing |
| `garmin/` | module functions | `client.py` (login, fetch), `sync.py` (`pull`, `ensure_data`, the `sync_state` watermark, the Calendar ride-along, §13), `derived.py` (where a handle meets the maths: `recompute_derived`, `backfill_tss`, `warmup_cutoff`). `__init__.py` still re-exports everything: debt, not precedent (AGENTS.md) |
| `gcal/` | `CalendarSyncer` | Google Calendar, both ways: `event.py` (what an event says, no Google import), `history.py`, `client.py` (the only file that calls the API), `reconcile.py` (the pass after every change, DESIGN_workout_revisions.md §8); `__init__.py` maps them and re-exports nothing ([§15](#15-design-rationale--history)) |
| `strength/` | — | Strength tracking (DESIGN_strength_tracking.md): the exercise table (`vocabulary.py`, DESIGN_exercise_table.md), Garmin's sets (`sets.py`), the strength planner (`planner.py` + `planner_prompt.py`, §9), the gym logger's payloads (`logger.py`, §16), planned against done (`comparison.py`, DESIGN_strength_planned_vs_done.md); `__init__.py` maps the rest. Rows in `db/strength.py` |
| `page_files/` | — | The pages' encrypted files in a bucket (DESIGN_miniapp_storage.md): `recipe.py`, `bucket.py`, `sync.py` (`after_command`, `data publish`/`unpublish`); `__init__.py` maps them |
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
| Coach learnings / confidence | `db/learnings.py`, `coach/service/athlete_context.py` (`_apply_learning_updates`, `_review_learning_proposals`), `learning_doubts.py`; the model is [§3](#3-coach-package-architecture) |
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
| A strength activity's sets | `strength/sets.py`, `strength/vocabulary.py` + `exercises.tsv` (then rebuild `miniapp/exercises.json` with `miniapp/build_exercises.py`), `strength/questions.py`, `db/strength.py`, `cli/strength.py`, `cli/strength_log.py`, the `strength-sets-since` setting. DESIGN_strength_tracking.md, DESIGN_exercise_table.md |
| A gym session logged on the phone | `miniapp/`, `strength/logger.py`, `cli/strength_ingest.py`, `strength/sets.py::take_over_logs`, `db/strength.py` (`gym_logs`, `upsert_logged_activity`, `save_gym_log`, `gym_log_for_day`, `garmin_activity_with_log`, `move_gym_log`). DESIGN_gym_logger.md ([§16](#16-gym-logger-telegram-mini-app)) |
| A past strength session against its planned lines | `strength/comparison.py`, `db/strength.py::attach_lifted`, `analytics/adherence.py` (`_discrepancy_reasons`, `_pairing_order`, `is_ambiguous_match`), `cli/common.py` (`strength_table`, `simple_comparison_lines`), `strength/sets.py::done_text`. DESIGN_strength_planned_vs_done.md |
| What a strength session prescribes | `strength/planner.py`, `strength/planner_prompt.py`, `strength/progression.md`, `strength/history.py`, `strength/prescription.py`, `prescribed_sets` + `strength_checks` in `db/schema.py`, `db/workout_change.py::WorkoutChange`, the pass's place in `coach/service/generate.py` and `coach/service/adapt.py`. DESIGN_strength_tracking.md §9 |
| A CLI command | `stamind/cli/<family>.py` (`run_*`), the dispatcher in `stamind_cli.py` ([§7](#7-cli-commands-reference)) |
| A message telling the athlete to run something | `text.cmd()` inside the line's colour call, emitted with `output.aside` |
| Whether a line reaches the chat | `output.aside` (terminal only) vs `print`; a list of lines gates on `text.asides_enabled()`. DESIGN_output_verbosity.md §3 |
| Recording that something happened | `output.step`/`warn`/`fail` print and journal in one go; `stamind/journal.py` directly only for structured fields (`journal.record`) or what must never reach the athlete (`journal.debug`); event names from `journal.EVENTS`; `runtime.prompt` journals every answer itself. DESIGN_logging.md §2, §4.2, §5 |
| Reading back what a command did | `sm journal` (`cli/journal/`), `logs/runs/*.jsonl`; a run's prompts are `logs/llm_exchanges/*<run id>*`. DESIGN_logging.md §6, §7 |
| How long the coach's prose is | `coach/engine/prompt.py` (`## WRITING FOR THE ATHLETE`) + the per-field caps in each `## RESPONSE FORMAT`; a field re-injected into later prompts is not capped (DESIGN_output_verbosity.md §5.1); the `terse` setting (§9, `quotes_wording` in `cli/workouts/revisions.py`) |
| A web view of existing data | a GET in `stamind_web.py` + a panel under `static/` ([§8](#8-web-api-endpoints)) |
| A web endpoint that would write | does not go in the web app: add the CLI command ([§8](#8-web-api-endpoints)) |
| DB schema / a new column | the `db/*.py` mixin + the table in [§5](#5-database-schema) |

---

## 3. coach Package Architecture

The `stamind/coach/` package's `__init__.py` is a docstring. Each name is imported
from the submodule that defines it — `from stamind.coach.service import coach_service`,
`from stamind.coach.formatting import format_baseline` — so a light submodule costs only
itself: `from stamind.coach import honoring` used to load 506 modules and now loads 59.
The submodules:

- `formatting.py` — pure prompt-formatting helpers (no I/O, no LLM):
  `format_metrics_history`, `format_completed_activities`,
  `format_planned_workouts_detailed` (adapt-only
  variant that includes each session's full description so the model preserves
  interval/rest detail it isn't deliberately changing, tags a session already
  trained `[COMPLETED — locked history, not adaptable]` or `[PARTIAL — …]` with
  what was actually performed, from `adherence.performed_sessions`
  ([§15](#a-session-already-behind-us-carries-its-verdict)), and tags
  already-eased sessions `[ALREADY EASED …]` with
  recency/count from `adapted_at`/`adaptation_count` so a re-run doesn't compound
  the cut), `format_removed_workouts`, `format_daily_signals`
  (renders the window's `daily_signals` rows into the adapt prompt),
  `format_baseline`, `_load_science_guidelines`.
- `engine/` — `CoachEngine` (prompt construction, hashing, LLM calls), assembled
  from mixins (`prompt`, `planning`, `generate`, `adapt`, `analysis`, `retrospective`). It owns the
  `openrouter_client` binding — **patch target for tests:**
  `stamind.coach.engine.openrouter_client`. Two of its files hold no mixin.
  `sessions.py` is the prompt sections about one session entry rather than about the
  span: the sport enum, the intensity target and its two schema members, the `replaces`
  field, the strength brief and the sessions just outside the days being written, which
  `workout generate` and `workout adapt` both send, then the locked history, how a move is
  written and what a benchmark entry must keep, which only adapt sends today. `notes.py`
  is what is done with the athlete's words: the
  `workout tweak` TASK head, the note section, the constraint and signal extraction
  that `bot capture note` asks for too, and the section that asks which session of the day
  the note is about.
- `service/` — `CoachService` + the `coach_service` singleton (data I/O, caching,
  orchestration), assembled from fourteen mixins, one file per job; the package
  `__init__.py` names each file and what it holds. Callers reach all of them through
  `coach_service`, so a method moving between these files is invisible outside the
  package. It holds no handles of its own: `_db` and `_prompt` are properties reading `runtime.db`
  and `runtime.prompt`, and it has no Calendar handle at all — the comment beside
  `_prompt` in `service/__init__.py` says why. Nothing here aliases the clock either: a
  file that needs today reads `clock.today_str`, and a test freezes it with
  `tests.helpers.pin_clock`, which patches `clock.now` and so reaches every one of them
  at once.
- `honoring.py`, `proposals.py` and `revisions.py` sit beside them: whether the schedule
  reflects a constraint yet, the frozen records the coach hands the CLI before the athlete
  has accepted anything, and the pure helpers that fill one in.

### `_load_science_guidelines(app_science_dir, science_dir) → str`
Module-level function in `formatting.py`. Concatenates all `*.md` files from
`stamind/science/` (built-in) and `science/` (user-provided), **one `====` banner per
source** so the coach can tell whose material it is reading, and so the documents' own
markdown headings are visibly not the prompt's (`DESIGN_prompt_structure.md` §3). The
banners are emitted here, not by the three call sites. Returns `""` when neither directory
holds documents, so no empty banner is produced. Called by
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
`CoachService` or directly by tests).

- **`_build_system_prompt(...)`** — assembles the main LLM system prompt
  (guidelines, strategy, goals, constraints, athlete profile). Every prompt in the app —
  system and user message alike — uses one section hierarchy: `## NAME` for a top-level
  section, `### NAME` for a sub-section of `## TASK`, and a `====` banner only around a
  verbatim quoted document (`DESIGN_prompt_structure.md` §2). `_render_constraints`
  renders the active constraints section (`title | dates | enforcement | description`, where
  enforcement is "no training (rest enforced)" or "advisory").
- **`_format_athlete_profile(profile)`** — formats the (effective) profile into a
  readable prompt segment. Threshold anchors render generically from
  `stamind.benchmarks.ANCHOR_KINDS` (label + unit), so a new anchor kind shows up with
  no prompt-code change (`DESIGN_benchmark_workouts.md` §3.5).
- **The plan's input fingerprints are no longer the engine's.** They were five methods
  here — `_clean_goals`, `_clean_constraints`, `_get_goals_hash`, `_get_constraints_hash`
  and `_get_config_hash` — and the engine never called any of them; the service did. They
  are module-level functions in `stamind/plan_inputs.py` now, with the partition they
  hash and the diff text that explains a change. See that file, and the paragraph under
  §2's `plan_inputs.py` row.
- **`_plan_generate_strategy(...)`** — LLM call → `{strategy, mesocycles}` covering the
  plan start through the goal date, whatever the horizon. Label `plan_generate`.
  Branches on the goal's `date_type`: a `horizon` goal's task forbids pinning a
  peak/taper/realization phase to the date and drops the `Peak & Taper, Race/Event`
  phase examples ([§15](#goal-dates-event-vs-training-horizon)).
  Branches again on `current_mesocycle`, the mesocycle the athlete is mid-way through: when
  one is offered, the task quotes it and lets the model either keep it as the first
  mesocycle **at its original start date** or discard it and start on the plan start,
  stating which in the strategy. A mesocycle re-dated to today would contain none of the
  sessions already trained under it, since mesocycles own their sessions by date containment
  (`DESIGN_mesocycle_progress.md` §7).
  Takes `plan_retrospectives`, the text of every written record of a plan, oldest first,
  and prints it as `## RETROSPECTIVES OF PAST PLANS` before `## PRIOR TRAINING REVIEW`
  (DESIGN_cycle_retrospective.md §7).
  Takes `anchor_history`, the same ANCHORS ON RECORD text `workout generate` gets
  (`CoachService._anchor_history_text()`): each threshold's latest value with its date,
  source and note, placed after the athlete profile so a value is never read without how
  it was obtained (`DESIGN_benchmark_workouts.md` Rev. 5).
  Builds its own system prompt rather than calling `_build_system_prompt`, which states
  the ACTIVE strategy and mesocycles as settled fact — the very artifact this call produces;
  the plan prompt shows the *previous* strategy instead. It takes `learnings` explicitly
  for that reason: the shared builder's `COACH LEARNINGS` section is the one part it does
  want, and without the argument this was the only coach call blind to the observations
  the analysis flow authors (DESIGN_backward_evaluation.md §10.1).
- **`_plan_reshape_verdict(change_reason, diff_text, strategy, mesocycles)`** — the
  cheap preliminary behind the staleness question: given what changed and the plan in
  force, would `plan generate` reshape the periodization? → `{reshaping, why}`. Label
  `plan_verdict`. Called only through `CoachService.plan_reshape_verdict` (below).
- **`_retrospective_writer(record, today_str, measured, constraints, signals,
  spoken_workouts, mesocycle_records, wait_notice)`** — the retrospective writer
  (`engine/retrospective.py`, DESIGN_cycle_retrospective.md §5): the one model call that
  writes a record's lines and the sentence for the athlete → `{record, athlete_line}`.
  Label `retrospective_writer`. The system message is a role line, `## TASK` and
  `## RESPONSE FORMAT`, with no science documents and no profile. For a mesocycle the user
  message holds `## THE MESOCYCLE`, `## WHAT WAS MEASURED`, `## CONSTRAINTS AND SIGNALS IN
  THOSE WEEKS`, then `## SESSIONS THE ATHLETE SPOKE ABOUT` and `## THE ATHLETE'S WORDS`
  when there are any. The task asks for a record with no advice, a reason only where the
  inputs state one, and 400 characters for a mesocycle. `wait_notice` is set only when the
  athlete has just answered and waits for the reply.
- **`_workout_generate_logic(...)`** — LLM call → `{reasoning, workouts[]}`. Accepts
  `num_days` (default 28) driving the horizon and `start_str` (defaults to today) for
  the first day to schedule — the prompt tells the model to begin there. When
  `mesocycle_progress` is supplied it appends a `CONTINUING A MESOCYCLE ALREADY UNDER WAY`
  section (`_mesocycle_progress_task`) and renders that data as the first user-content
  section, so a mid-mesocycle regeneration continues the mesocycle's ramp instead of restarting
  it, does not repeat a deload already taken, and does not re-place a fitness test the
  mesocycle already ran — that clause **bounds** the otherwise-unconditional BENCHMARK
  PLACEMENT rule (DESIGN_mesocycle_progress.md §4). With `mesocycle_has_intensity` it further
  appends `JUDGING THE MESOCYCLE'S COMPOSITION` (`_mesocycle_composition_task`), the other end of
  DESIGN_intensity_distribution.md §9.4's handoff (§9.2a): composition is generate's, but
  only after attributing the divergence — measured-vs-prescribed decides whether the plan
  or the athlete is off, and re-shaping the mesocycle around a mis-execution is forbidden by
  name. The flag rides separately from `mesocycle_progress` because that section quotes the
  zone tables and must not be promised when they have no rows. **Read-only** w.r.t.
  learnings. Label `workout_generate`.
  Its TASK also states the coverage invariant — every date of the span carries an entry,
  a rest day explicitly (DESIGN_runway_nudge.md §2.1) — and
  `coach/service/guards.py:_fill_coverage_gaps` backstops it deterministically, so the
  end of the schedule can be read off the rows rather than guessed at.
- **`_workout_adapt_logic(...)`** — LLM call →
  `{change_needed, reason, adapted_workouts[]}`. **Read-only** w.r.t. learnings.
  The TASK states its cross-cutting rules once, as `STANDING RULES` immediately after
  the decision branches; the sections below cite them rather than restate them, so a
  rule has one wording and cannot drift copy by copy (DESIGN_adapt_task_prompt.md §2).
  Within `config.adapt_terminal_window_days` of the mesocycle's end it appends a
  `THIS MESOCYCLE IS ENDING` section biasing the model toward holding load, since a cut
  there cannot rebound (DESIGN_mesocycle_boundary.md §3). `neighbour_workouts`, the week
  after the range, is shown read-only the way generate's week either side is (§7 of the
  same doc). There is **no separate
  classification pass** for `--message`: the same call also extracts any
  constraint candidates from the note and returns them as `new_constraints`
  (DESIGN_constraints.md §8). Label `workout_adapt`.
- **`_data_analyze_logic(...)`** — LLM call → `{macrocycle_summary,
  inferred_macrocycle, inferred_mesocycles[], physiological_insights[],
  learning_updates[]}`. Reverse-engineers cycles from weekly summaries. Label
  `workout_analysis`.

**Coach learnings via evidence-cited deltas:** only `_data_analyze_logic`
(the `data bootstrap`/`data reflect` flow) emits a `learning_updates` array
(shared prompt field `LEARNING_UPDATES_FIELD`). `_workout_generate_logic` **and**
`_workout_adapt_logic` are **read-only** — they consume the rendered learnings but author
none (DESIGN_backward_evaluation.md §11; DESIGN_evidence_based_confidence.md §2).
The app owns the merge via `CoachService._apply_learning_updates()` →
`db.apply_learning_deltas(deltas, available_weeks, source)`, so a model that omits
an existing learning cannot lose it. Deltas the app cannot act on are still skipped, but
the merge returns `{"applied", "skipped"}` and a non-zero skip is reported — otherwise
"the model authored nothing" and "the app understood nothing" look the same
(DESIGN_backward_evaluation.md §13). Each learning carries a **sport scope**
(`sports`) and an **app-computed confidence** (`tentative`/`moderate`/`established`).
The LLM **no longer sets confidence** — it only attributes each observation to the
training **week(s)** it was shown (`week_commencing` Mondays). The five ops:
- `{"op": "add", text, sports?, evidence:[weeks]}` — new record; seeds its
  supporting basis from `evidence`; confidence derived.
- `{"op": "revise", id, text?, sports?, evidence?:[weeks]}` — edit fields; if
  `evidence` given, also adds supporting weeks.
- `{"op": "reinforce", id, evidence:[weeks]}` — add supporting weeks (no
  reword). **No `evidence` ⇒ no-op.**
- `{"op": "contradict", id, evidence:[weeks], reason?}` — add contradicting weeks, each
  carrying the one-line `reason`; may trigger a *proposed* demotion.
- `{"op": "retire", id}` — archives the learning, basis kept.

Cited weeks are validated against `available_weeks` (the analysed window's
Mondays); weeks outside it are dropped (skip-malformed philosophy).

**Confidence = f(evidence basis)** (DESIGN_evidence_based_confidence.md §3).
`net = distinct supporting weeks − distinct contradicting weeks`; thresholds
(`config.learning_confidence_thresholds`, default moderate 3 / established 5) map
`net` to a level. The retirement sentinel is returned only when `net ≤ 0` **and**
`contradicting_weeks > 0`: a learning with no basis at all rests at the `tentative`
floor, without which every freshly added learning would be proposed for retirement on
its first recompute. **Upgrades auto-apply; downgrades are proposed, not applied** —
`db._recompute_confidence()` writes the lower level to `proposed_confidence` and
leaves the live `confidence` intact. Re-citing counted weeks is a structural
no-op (the `UNIQUE(learning_id, week_commencing, polarity)` constraint), so re-running /
`--force` / overlapping windows cannot inflate confidence. `last_reinforced_at`
refreshes only when a *new* supporting week lands (or on a staleness demotion).

**Decay (soft) + staleness demotion:** a learning is *dormant* once unreinforced
past its confidence budget (`config.learning_staleness_days`: tentative 21d / moderate
60d / established 180d, via `db.learning_is_dormant()`). Dormant records stay in
the DB, are listed by `learnings list` (marked), and are **excluded from prompts**. Every
reflect and bootstrap run also **lowers a dormant learning one level** directly
(`apply_staleness_steps`) and re-arms the clock at the lower (shorter) budget, so an
untouched learning walks established → moderate → tentative → archived over real time.

**Propose / confirm flow — the athlete decides:** a contradiction-driven downgrade is
only proposed, and the athlete rules on it (DESIGN_learning_doubt_nudge.md). At the end of
every `data bootstrap`/`data reflect`, `CoachService._review_learning_proposals()` applies
the staleness steps, then `learning_doubts.settle_doubts()` queues one question in the
athlete queue per pending proposal whose learning is not dormant and has no question
waiting. The question carries two sentences from `CoachService.learning_question()`: what
the learning claims about the athlete, and what the coach saw against it, taken from the
contradicting weeks' `reason`. "Still fits" runs `db.keep_learning` (the −1 rows are
deleted and confidence re-derived); "Not really" runs `db.demote_learning`. Nothing is
asked on the spot, with or without `--auto`; the operator can still settle a doubt by hand
with `learnings demote <id>` / `learnings keep <id>`, and the waiting question then closes
as stale. With the `learning-questions` setting off, the run applies each pending proposal
itself. **Retirement archives** (`coach_learnings.status`): the retirement rung of
`demote_learning`, the `retire` delta op, the staleness bottom rung and `learnings rm` all
archive; `learnings restore` brings a learning back at tentative with its evidence, and
`learnings rm --purge` is the hard delete.
`CoachService._get_learnings_text()` renders only active (not dormant, not archived)
learnings as `[id|sports|confidence] text` into every using flow's prompt.

**Inspection / curation:** the `learnings` command family is the home for viewing
and hand-curating records — `list` (filters: `--sport`/`--confidence`/`--dormant`;
archived learnings only with `-a/--all`), `show <id>` (full text + per-week evidence basis
with each contradicting week's reason; finds archived learnings too), `edit`, `rm`
(archives; `--purge` deletes), `restore`, `demote`, `keep`, `wipe`. `status` carries only a
one-line summary (`N active, M dormant, K pending demotion`, archived left out) pointing at
`learnings list`.

**Cold-start nudge:** when there are no active learnings, `plan generate` and
`status` suggest running `data bootstrap` (the only flow that authors learnings).

**A learning added by hand** is seeded with a synthetic supporting basis sized to
sustain the confidence it was given (`db._seed_synthetic_evidence()`, source `manual`),
so the first recompute does not demote it for lack of evidence. The one-off that did the
same for learnings predating the evidence model went with the schema squash.

### `CoachService`
**Orchestrator — owns all DB and calendar access.** Exposes the public API
called by the UIs.

- **`plan_generate(force, objective_id, auto_apply, fresh, start_date, show_context)`** —
  fetches objectives/constraints, checks hashes (constraints hash covers only the
  plan-shaping `replan=1` rows), calls `CoachEngine._plan_generate_strategy()`, returns a
  `PlanProposal`. Saves to DB only
  under `auto_apply`; otherwise the caller passes the proposal to `plan_apply()` once
  the athlete accepts. The plan window has no minimum or maximum length (§10, step 4).
  `fresh` (CLI `--fresh`) withholds the `PREVIOUS PERIODIZATION STRATEGY` section and its
  `CONTINUITY WITH THE PREVIOUS PLAN` instruction, so the strategy is written without the
  plan in place to build on; it implies `force`, since there is nothing to reuse when the
  point is to depart. Everything derived from what the athlete *did* is unaffected — the
  planned-vs-actual review still covers the replaced plan's elapsed mesocycles, as do the
  history summary, the learnings and the athlete's plan feedback
  (DESIGN_backward_evaluation.md §6.1).
- **`workout_generate(start_date, end_date, prefer_macro_id, fresh)`** — requires an existing
  macrocycle.
  Writes nothing: it returns a `GenerateProposal` (reasoning, the proposed sessions
  already tagged with their date's `macrocycle_id`, the live plan they would displace,
  and `gen_start`), which the caller previews and hands back to
  `workout_generate_apply()` once the athlete accepts — the same
  propose-then-apply split as `plan_generate`/`plan_apply`.
  `fresh` (CLI `--fresh`) empties the commitment window for that run, so the week planner
  writes every day of the span the way it writes a day past the window, and the change
  stamps no `commitment_end` (DESIGN_plan_change_continuity.md §4.4).
  `fresh` also has the strength planner write every strength session again
  (DESIGN_strength_tracking.md §9).
  Applies the deterministic rest-window pre-pass to the generated workouts
  (`_enforce_rest_windows_generate(workouts, constraints, gen_start, gen_end)`: every
  `rest = 1` date in the *requested* span `[gen_start, gen_end]` — not the span the model
  happened to return — becomes a single rest session, **including
  dates the model returned nothing for** — an absent row and an explicit rest day mean
  different things to adherence. Every other constraint is advisory, left to the model)
  before proposing, so the forced rest days are visible in the preview.
  - **Preserves a completed session:** if today's planned workout already has a
    matching completed activity (`_today_workout_completed`, a one-day
    `analyze_adherence` pass), generation starts *tomorrow*; otherwise today. A
    defensive filter drops any model-emitted workout dated outside `[gen_start, gen_end]`.
  - **The week either side:** the live sessions planned in the seven days before
    `gen_start` (never before today) and the seven after `gen_end` reach the week planner as
    `SESSIONS JUST OUTSIDE THE SPAN`, shown and never written, so a weekly rule counts the
    whole week and not the part of it this run writes (DESIGN_mesocycle_boundary.md §7).
  - **What the athlete said:** the sessions of the look back before today that carry a note
    reach the week planner as `RECENT SESSIONS THE ATHLETE SPOKE ABOUT`, each with its
    prescription and the words, to read beside that day's Garmin line
    (DESIGN_session_notes.md §4).
  - **Horizon:** `num_days` from `end_date` (or `config.workout_generation_span_days`)
    relative to the start, then `CoachEngine._workout_generate_logic()`.
- **`workout_generate_apply(proposal)`** — the accepted half. Archives the previous
  proposed sessions under one `generate` change, voiding every day from `gen_start` the
  new sessions do not fill and appending the rest with the `macrocycle_id` the proposal
  already carries. It touches no Calendar code: the change handle's reconcile pass makes
  the calendar mirror the active plan when the change commits, under one summary line and
  a progress bar. Appending (not deleting) makes regeneration undoable via
  `workout_rollback` or `plan_rollback` (DESIGN_workout_revisions.md §10).
- **`workout_generate_strength(start_date, end_date)`** — `workout generate --strength-only`.
  No week planner call: the strength planner writes every strength session of the span
  again (`write_again`), and the ones whose sets changed come back as a `RevisionProposal`
  of kind `generate`, the other sessions of their dates held, for `workout_revision_apply`
  (DESIGN_strength_tracking.md §9). The span opens tomorrow only when today's strength
  session already has a matching completed activity (`_today_workout_completed` with
  `sport`); a run done that morning leaves tonight's gym in the span.
- **`plan_apply(objective_id, strategy, mesocycles, fingerprints=None)`** — persists an
  already-generated strategy + mesocycles, returning the goal id it saved under.
  `fingerprints` are the goals/constraints/config hashes and snapshots taken when the
  strategy was generated (`PlanFingerprints`, `coach/proposals.py`) and are stored
  verbatim. Omitting them re-reads the inputs as they are *now*, which records an edit
  made between generating and accepting as though the strategy had been built from it —
  exactly the drift the staleness detector exists to catch. Only callers applying a plan
  they did not just generate should leave it unset.
- **`replan(force, objective_id)`** — convenience: `plan_generate` (auto-applied) then
  `workout_generate` + `workout_generate_apply`, with no preview — the unattended path
  ([§11](#11-terminology-plans-vs-workouts)).
- **`workout_adapt(target_date_str, message=None)`** — fetches metrics + workouts in
  the rolling window and the week after the range, calls
  `CoachEngine._workout_adapt_logic()`, returns a
  `RevisionProposal` (`coach/proposals.py`) carrying `reason`, `workouts`, `pairs`/
  `removals` and the two candidate lists below; caller decides whether to apply.
  `open_proposal` is the proposal the athlete has not answered yet, which the answer
  replaces (DESIGN_waiting_proposal.md §6.2).
  - **`message`** (CLI `-m/--message`): a fast-capture inbox. There is no separate
    classification call — the same adapt call may return two kinds of candidate
    extracted from the note, both raw and **unconfirmed**, both gated on the same
    `has_message` flag:
    - `new_constraints` — constraint candidates (DESIGN_constraints.md §8). The
      CLI confirms each with the athlete, then persists it via
      `capture_message_constraint` (singular, one call per confirmed candidate) as a
      `constraint` row (`source='message'`, `replan=0`, honored this run and every
      future run). Auto-capture never sets `replan=1` — a plan-shaping capture only
      *surfaces a suggestion* to escalate.
    - `new_signals` — the external causes acting on the athlete on given days
      (DESIGN_signal_extraction.md). Confirmed one at a time before the adaptation
      preview, then written through `capture_message_signal` → `signals.write_signal_days`,
      the same calendar-first path `signal add` uses ([§13](#13-daily-signals-calendar-ingest)).
      `value` survives only when it is a real number, so a model's guess cannot enter
      the quantitative path as a measurement.
  - **Rest-window pre-pass** (`_enforce_rest_windows_revision`): eases any future,
    not-yet-completed planned session under a `rest = 1` constraint to rest, regardless
    of the model's proposals.
  - **Mesocycle firewall (write side):** any proposal dated past the mesocycle end is dropped
    with a notice (`guards.py:_keep_inside`, the same drop `workout generate` runs on its
    span) — the week after it is shown read-only, so a post-boundary date is the week planner
    writing where it was told not to ([§15](#15-design-rationale--history),
    DESIGN_mesocycle_boundary.md §1, §7).
  - **Requires a mesocycle:** `workout_adapt` raises "No active periodization strategy found"
    when `get_active_mesocycle` returns nothing, as `workout_generate` does. Adapt's
    judgements are all relative to the mesocycle, so there is nothing to adapt towards
    without one (DESIGN_mesocycle_boundary.md §6).
  - **Constraint magnitude** (`constraint_plan_impact` / `constraint_is_plan_shaping`):
    the §7 heuristic behind the `constraint add`/`edit` replan proposal. Two independent
    triggers, either firing: displaced planned load ≥ `config.replan_displaced_load_pct`
    of the trailing week's planned load, or a `rest` window spanning ≥
    `config.replan_rest_span_days`. Deliberately **no key-session term** — Stamind has
    no priority field at all. Human-confirmed, never auto-regen.
  - **Only-changes contract:** the prompt shows the whole forward plan through the
    mesocycle end but instructs the model to return **only sessions it is changing** —
    omitted sessions are preserved (apply never drops a date with no proposal). A date the
    model *does* touch is the exception: it keeps only the sports named on it, so a
    same-day session of another sport is named with a **keep marker** —
    `{date, sport_type, keep: true}` and nothing else (DESIGN_workout_revisions.md §9.1).
  - **Locked history:** any proposal targeting a `(date, sport)` that already has a
    matching completed activity (incl. one done earlier today) is dropped — a finished
    workout is never "adapted".
  - **No-op backstop** (`_revision_is_change`): a proposal reproducing an existing
    same-sport session on every meaningful field (title, description, duration/RPE/TSS —
    whitespace- and int/float-insensitive) is **held, not dropped**: no revision row, but
    it still counts as proposed on its date, so the displacement rule cannot void the
    session the re-list was protecting. Held slots travel on `RevisionProposal.held`, which
    both the preview and apply union into the date's proposed sports (§9.1).
- **`workout_tweak(message, tweak_dates, today_str)`** — `workout adapt`'s path with a
  narrower job: the athlete has decided the change, the week planner writes it
  (DESIGN_workout_tweak.md §3). It calls `workout_adapt(..., tweak=True)`, which swaps
  the adapt TASK for the request's, leaves out the fatigue-reading sections and the drift
  context, and lists every cancelled session ahead (`get_cancelled_workouts`) so one can
  be brought back. After the reply, the days are the caller's `-d` days, else the
  `tweak_dates` the week planner returned; a reply that changes sessions and names none,
  or names a day past the tweak's reach, raises. The reach, `range_end`, is the end of the
  current mesocycle or `TWEAK_REACH_DAYS` (7) from today, whichever is later
  (DESIGN_workout_tweak.md §3.2); `workout adapt` stops at the mesocycle's end. Every
  entry on another date is dropped, and so is a move whose other end is on another date,
  before the moves are resolved. The strength planner is shown those days only. The proposal carries
  `kind="tweak"` and covers no constraint.
- **Moves and swaps** (`_resolve_moves` / `_move_source`): a move may land on a slot that
  already holds a session of the same sport. When that session moves out in the same reply,
  the two swap days (DESIGN_workout_tweak.md §3.1). Otherwise `workout_revision_apply` ends
  it there with a void, and the moved session takes the slot
  (DESIGN_workout_revisions.md §4).
- **`workout_revision_apply(proposal)`** — the accepted half of `workout_adapt` and
  `workout_tweak`. Opens one change of the proposal's `kind` (`adapt` or `tweak`): a
  session the pass drops becomes a **void** revision (never a
  `DELETE`), a cross-sport substitution is a void at the source plus a revision at the
  destination on the same lineage, and every revised session appends with its own
  `modification_reason`; the batch `reason` lands on the `workout_changes` row. Voids go
  first. Touches no Calendar code — the change handle's reconcile pass does — and stamps
  `honored_at` on the constraints the proposal covered (`honoring.stamp`). Nothing is
  stamped on the row for recency: whether a revision counts as an easing is derived at
  read time from the lineage ([§5](#workout-state--three-orthogonal-axes-not-one-enum)).
- **`workout_revision_record_no_change(proposal)`** — the other outcome. An adapt that
  looked at the metrics and held still writes its `workout_changes` row (appending
  nothing) and stamps `honored_at`, so "no adaptation needed" is a recorded event and a
  valid honoring claim ([§10](#daily-adaptation-workout-adapt), step 6).
- **`data_bootstrap(...)` / `data_reflect(...)`** — read past training from completed
  activities + metrics via the shared `_run_workout_analysis` core, which passes the
  horizon down so each asks its own question (§10.3). `bootstrap` = cold-start over the
  full backlog (horizon `long`), reverse-engineers the cycles, sets the reflect
  watermark; `reflect` = incremental since the watermark (horizon `short`), recent
  response only, advances it. Reflect's window ends on the last **completed** week
  unless an end date is named, so a part-week is never cited as a whole one and a run
  with nothing complete since the watermark makes no LLM call (§10.4). Both reuse
  `analysis_cache` on unchanged evidence; `force` recomputes; `inspect_only` renders
  without writing. A response that parses but carries no readable content raises before
  anything is written — caching it would pin the emptiness behind the fingerprint and move
  the watermark as if the history had been read; a partly-readable one saves and names the
  parts it could not use. See DESIGN_backward_evaluation.md §5, §8, §9, §13.
- **`_build_prior_training_context(prior_macros, today)`** — builds the read-only
  "planned vs actual" review injected into the `plan generate` strategy prompt
  (Option A). The finished mesocycles come from the stored records, for every goal; the
  mesocycle under way comes from every plan handed in **and from the plan the athlete is
  currently in** (it adds `get_governing_macrocycle()` itself) — drift diagnosed only one
  macrocycle late is history (`_mesocycle_reviews`, below). The caller passes both the
  *preceding goal's* plan and the one being
  *replaced*; they are different macrocycles whenever three or more planned goals chain
  (DESIGN_backward_evaluation.md §6.1). Each mesocycle shown in full carries its volume/load line plus the per-sport per-zone intensity
  table and the **mesocycle-over-mesocycle delta**, which is the intensity-creep check and lives
  here only: it is a periodization question, so `adapt` never sees it
  (DESIGN_intensity_distribution.md §4.1/§9.2) — beside **what the plan prescribed** over
  the same weeks (§9.2a) and **one planned-vs-actual load line per week**, without which a
  half-missed mesocycle reads exactly like a completed one. Folds in every cached
  reconstruction (`_cached_reconstructions()`): summary, inferred macrocycle and mesocycles,
  and physiological insights. Writes nothing anywhere — it is prompt context, never a
  note in the plan's feedback log; the records it reads are written by the write step. The whole review is wrapped **once**, at build time, and printed
  verbatim — the zone tables are column-aligned and a screen-width re-wrap shreds them.
- **`_mesocycle_reviews(macros, today)`** — the list of mesocycles behind the above
  (DESIGN_cycle_retrospective.md §7). The finished mesocycles are the mesocycle records of
  every goal, a called-off one included, oldest first. So a mesocycle that lives only in a
  replaced plan version is shown, which a walk over plan versions could not do. A written
  record is printed in place of the full detail (`cycle_records.record_text`), about 0.5 KB
  where the detail takes about 7 KB. Two kinds keep the full detail: the mesocycle that
  finished most recently, which also prints its record under it, and a record that has no
  lines yet. The mesocycles under way come from `macros` through `plan_lineage`, in full
  detail. One line names the goal whenever it changes: `Toward "Gran Fondo" (goal dated
  2026-10-15):`. The delta baseline of a mesocycle shown in full is the one before it in
  this list, across goals too. `_mesocycle_review` renders one mesocycle in full, and the
  retrospective writer reads the same text.
- **`plan_rm(objective_id)`** — deletes macrocycle + mesocycles for that objective
  (cascades in DB; removes *all* versions, active and superseded).
- **`plan_rollback(objective_id, target_macrocycle_id)`** — restores a superseded plan
  version (the chronologically previous one by default, or a specific id) and its
  workouts. Flips the active macrocycle, then undoes every workout change made after that
  version's newest one, through the same point-in-time primitive `workout rollback` uses.
  The restore is deliberately unscoped: restoring the whole moment is what keeps one
  session from ending up live in two slots (DESIGN_plan_rollback.md,
  DESIGN_workout_revisions.md §10).
- **`effective_thresholds()`** — the linchpin accessor (`DESIGN_benchmark_workouts.md`
  §3.3): the athlete's current threshold anchors, `max_hr` from config overlaid with the
  latest logbook row per kind (`db.latest_thresholds()`). `_effective_profile()` merges
  these onto `config.user_profile`, and every engine prompt call (generate/adapt/plan/
  analysis) passes that merged profile so zones are prescribed from live values.
- **The three snapshot builders** (on `StalenessMixin`, `coach/service/staleness.py`).
  **`_get_config_snapshot()`** — `effective_thresholds()` as JSON, snapshotted on the
  macrocycle. **`_get_profile_snapshot()`** — `plan_inputs.plan_profile()` as JSON,
  snapshotted alongside it so staleness can name the field that moved.
  **`_get_science_snapshot()`** — `plan_inputs.athlete_science_documents()` as JSON, the
  text itself rather than a hash, so the diff and the verdict call can read the edit
  (`DESIGN_plan_staleness.md` §11). The hash itself is `plan_inputs.plan_config_hash()`;
  the service's forwarding wrapper is gone.
- **`config_changed(macro)`** — the single staleness judgment, reached from the CLI only
  through `cli/staleness.py` (which owns the wording and the four surfaces; the re-stamp
  is `CoachService.stamp`, beside the judgment) and directly by the `plan_generate` reuse
  check. Returns a human-readable reason when the plan-shaping profile fingerprint
  mismatches or an effective threshold anchor drifted more than
  `coach.threshold_replan_pct` from the macrocycle's `config_snapshot`, else None. A kind
  absent from the old snapshot (newly recorded) is skipped; a kind that disappears counts
  as drift (§3.5). `e1rm` is skipped entirely: the logbook has no per-exercise field, so a
  deadlift PR after a squat PR reads as one anchor jumping ~70% and would invalidate a
  whole periodization — it still joins the snapshot and the prompt, it just never trips a
  replan (DESIGN_benchmark_workouts.md §3.3). Macrocycles without a snapshot (legacy)
  judge on the fingerprint alone. The profile half of the reason names the fields that
  moved when the macrocycle carries a `profile_snapshot`, and degrades to a bare
  "athlete profile changed" when it does not (`DESIGN_plan_staleness.md` §5). The fifth
  axis is the athlete's science documents: `"training guidelines changed: <file>, …"`
  when the `science_snapshot` no longer matches `science_dir`, and silence for a plan
  that carries no snapshot (§11). On the goals axis, a goal whose date has passed since
  the plan was generated is not a change: `_goals_still_ahead` drops it from the stored
  list before the comparison and before the diff (§12). `plan show` does not ask at all
  for the plan of a goal that is completed or archived.
- **`retrospectives_step()`** — what `plan generate`, `workout adapt` and the morning
  routine run at their start (`service/retrospective.py`, DESIGN_cycle_retrospective.md
  §3, §5): the date check, then the write step. The write step writes one due record, the
  oldest first. A failure prints one line and never stops the command; the next run tries
  again. It writes nothing under `--show-prompt`, where the writer would print its own
  prompt in place of the command's.
- **`write_retrospective(record, wait_notice)`** — writes one record and returns its
  sentence for the athlete. For the record of a plan it first writes the blank mesocycle
  records the plan covers, then the plan's own from their text, and its numbers are their
  sums, with the fitness and each benchmark taken as first and last value
  (`_plan_numbers`). For a mesocycle it refreshes Garmin for the record's days with
  `ensure_data`, computes the numbers, calls the writer and stores the result. The numbers
  are totals over the record's own days: sessions done out of planned from
  `adherence_verdicts` (rest days left out), hours and load produced from the activities,
  load planned from `planned_load`, fitness from the CTL stored for the first and the last
  day, and each benchmark with a result in those days beside its latest value before them.
  `## WHAT WAS MEASURED` is `_mesocycle_review`, the text the review prints for a
  mesocycle. It raises when the writer fails, and the record keeps what it held.
- **`plan_reshape_verdict(macro, change_reason)`** — the verdict call's read on whether the
  change `config_changed` reported would have reshaped `macro`: `{reshaping, why}`, or
  `None`. Reached from `cli/staleness.py` when the changed-input question is put to the
  athlete. Fails open on purpose — any error, a malformed reply, or `--show-llm-prompt-only`
  leaves the athlete with the question and no verdict, since the staleness question must
  never hang on the network (`DESIGN_plan_staleness.md` §10).
- **`_get_coach_system_prompt(objectives, constraints, ...)`** — builds the system
  prompt without making an LLM call (used by tests).

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
connection and the transaction that joins several, and `schema.py` (`SchemaMixin`) owns the
DDL and the version stamp. The domains are `objectives.py`, `constraints.py`, `signals.py`,
`benchmarks.py`, `activities.py`, `learnings.py`, `analysis.py`, `periodization.py`,
`mesocycles.py`, `queue.py`, `strength.py`, `page_files.py` and `wipes.py`. The `workouts` table takes three,
because one file for the append-only log ran past a thousand lines: `workout_change.py` is
the only way to write a session and the one way to undo one, `workouts.py` reads a session
as it stands today, and `workout_history.py` answers what happened to it — every form it has
had, the change log, and which Calendar event holds it. App preferences (`SettingsMixin`)
live in `base.py`: they are key/value rows, not training data, and a wipe leaves them
alone.

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
- **Sport-type matching is alias-aware** (`stamind/sports.py`, `SPORT_MAPPING`):
  the coach's prompts/generated/adapted workouts speak canonical names
  (`strength_training`), while legacy rows may use an alias (`strength`). `get_workout`
  and the append path key on `sport_canonical`, so a canonical lookup or write resolves
  an aliased session instead of reporting it missing or inserting a duplicate; the stored
  `sport_type` keeps the spelling as written. Adaptation's override check compares
  canonically too. `analytics/adherence.py` imports `canonical_sport` from `stamind/sports.py`
  (kept dependency-free to avoid the `adherence → garmin → stamind.db` import cycle).
- **The canonical sports are** `running`, `cycling`, `hiking`, `strength_training`,
  `yoga`, `ski_touring`, `rowing` and `downhill_skiing`. `downhill_skiing` covers
  lift-served skiing *and* snowboarding (Garmin files both under one resort type) and is
  deliberately kept apart from `ski_touring`: no sustained climb, so the load profile and
  the prescriptions differ. `CANONICAL_SPORTS` (declaration order of `SPORT_MAPPING`) is
  the single source of truth for the `goal add`/`goal edit` `--sport` choices
  (`stamind/cli/goals.py`) and for the `sport_type` enum in the generate/adapt prompts
  (`SPORT_TYPE_ENUM` in `stamind/coach/engine/sessions.py`, wrapped to match the
  hand-written schema around it) — adding a sport to `SPORT_MAPPING` reaches all three.
- **The canonical cycling name is `cycling`**, with `road_biking`, `road_cycling`,
  `gravel_cycling`, `mountain_biking`, `cyclocross`, `bmx`, `indoor_cycling`,
  `virtual_ride` and `biking` as its aliases — they all share one set of Garmin cycling
  zone boundaries, which is the criterion for sharing a zone-table row
  (DESIGN_intensity_distribution.md §6.1). This replaced a second, disagreeing
  vocabulary: `CYCLING_TERMS` (in the load model, since removed) held substring *fragments* matched loosely
  by `sync.py`, and had `gravel_cycling`/`cyclocross` that `SPORT_MAPPING` lacked, so a
  gravel ride got its power zones fetched and then fell through into a row of its own.
  `CYCLING_TERMS` is gone; `sync.py`'s power gate is now
  `canonical_sport(type_key) == "cycling"`. That gate is a **classifier, not a
  pre-filter** — Garmin reports `avgPower` for running too, and running watts scored
  against a cycling FTP are meaningless. Matching is exact, not substring: an
  unrecognised type surfaces as its own row so you can see which alias to add, and
  `data pull -d START..END` re-fills the window once you have.
- **Canonicalize on read, not on write.** `completed_activities.activity_type` keeps
  Garmin's raw string; every read path goes through `canonical_sport()`. Overwriting
  `gravel_cycling` with `cycling` in the column would be a lossy write undoable only by
  a re-pull. A one-off sport-rename script, since run and deleted, was the one exception,
  and it touched only `workouts.sport_type` (the plan's own vocabulary, which should agree
  with what the reports print).
- `rollback_to_change(change_id, from_date)` is the **one** undo primitive, and it is
  point-in-time: it reverts that change *and every change after it*. It works per slot
  rather than per lineage, because a change can end a lineage by appending over it — a
  move landing on a slot another session held — and the session to bring back is then
  the slot's previous occupant. For every slot the target or
  a later change wrote, the revision live there just before it is copied forward, stamped
  `restored_from`; a slot that held nothing gets a void. `workout rollback`, `plan
  rollback` (targeted at the moment just after the restored version's newest change) and
  the goal reinstate all reduce to this. The floor is the same rule archival had:
  appending a copy into a past slot would silently make it the live session for a day
  already trained (DESIGN_plan_rollback.md §9, DESIGN_workout_revisions.md §10). The
  rollback writes its own `note` as it is recorded: the changes it undoes that the athlete
  was told about and that wrote a session from `from_date` on, quoted oldest first — the
  plain "The change to your week was undone." when none of them has a line, and nothing
  when there are none (`heads_up.undone_note`, DESIGN_change_heads_up.md §6).

### Methods by domain

Each domain mixin follows the same naming convention, so the full signatures are
discoverable by reading the mixin in `stamind/db/` (grep the file named for the
domain). The convention: `add_*`/`save_*` (writers; `save_*` is an upsert),
`get_*`/`get_*s` (single-row by id / ranged-or-filtered list), `update_*` (partial
`**kwargs` patch), `delete_*` (hard delete), `wipe_*` (clear the domain). Only the
methods whose behavior is *not* obvious from that convention are called out below.

- **Objectives** (`objectives.py`) — plain CRUD; nothing beyond the convention.
- **Constraints** (`constraints.py`). Beyond the CRUD
  convention: `get_constraints(start, end)` returns rows overlapping a window (open-ended
  when `end` is None — the plan form).
- **Daily Signals** (`signals.py`) — external signals are reconciled **by
  Calendar event id**, so the writer/deleter are `*_by_event(google_event_id, …)`
  variants alongside the id-based ones used by the `signal` command. Cleared by
  `wipe_metrics` (see §13).
- **Workouts** (`workouts.py`) — the naming convention does not apply here, because the
  table is a log rather than a set of rows to edit. The whole write side is
  `workout_change` (see Key Patterns above); there is no `save_`, no `update_`, no
  `delete_`. On the read side, `get_workouts` / `get_workout` / `get_workout_by_id` return
  the *hydrated* session — the live revision plus what its lineage derives (`original_*`
  and the adaptation tally) — so everything above this module sees the dict shape it
  always did. `get_workout_by_id` takes a **lineage** id, the one `workout list` prints,
  and resolves it to that session's newest live revision, which is what stops `workout
  show` addressing a dead revision. Voids are excluded unless `include_removed=True`; there
  is no `include_archived` any more. `get_cancelled_workouts(start, end)` is the wider read
  `workout tweak` needs: every slot in the range whose live revision is a void, including
  a session that lives on as a rest day on the same date, but not one that moved to
  another date and stands there (DESIGN_workout_tweak.md §3.1). The history readers are
  `get_plan_revisions` (every
  revision, flagged live) and `get_workout_changes` (the batch list `workout batches`
  renders, each entry with its `note` and a `waiting` flag). The heads-up readers
  (DESIGN_change_heads_up.md §6): `waiting_changes()` — a line for the athlete, no
  `told_at`, and the change still stands — and `changes_with_lines()`, every change with a
  line, told or not, oldest first, for `workout notify --all` and `--sent`, with
  `mark_changes_told` its one writer besides `workout_change` itself, which stamps
  `told_at` as it writes when `prompt.athlete_watching()`. "Still stands" is
  `change_has_live_revisions`: a live revision the change wrote, or a live rollback copy
  of one, followed through `restored_from` however many copies deep.
  `newest_change_with_sessions` is what the terminal's replace question looks at, with `change_date_span` for the days it wrote and `change_writes_day` for whether it wrote today's. The push recorders `mark_workout_pushed` / `mark_workout_adherence_pushed`
  are the **only** writers of `pushed_signature` / `adherence_pushed_signature`, and they
  write `workout_calendar_state`, not the log. Undo: `rollback_to_change` (above).
  `add_session_note` keeps the athlete's words with a session (`session_notes`); hydration
  reads them back as `athlete_notes` (DESIGN_session_notes.md).
- **Completed Activities** (`activities.py`) — `save_completed_activity` upserts on
  `activity_id`, naming its columns, so it never touches the strength columns.
- **Strength sets** (`strength.py`) — `strength_activities` (raw `strength_training` rows,
  optionally unread), `store_exercise_sets` (replaces an activity's sets and stamps
  `sets_read_at`, and `sets_final_at` when frozen), `name_exercise_sets` (the only writer of
  `named_by = athlete`), `confirm_watch_names` (the watch's guesses become the athlete's
  when she says the sets are final), `freeze_exercise_sets`, `set_activity_discarded`,
  `activity_exercises_by_day` for the recent-exercises answers, and `strength_set_rows`, the
  one query the strength history is built from: every active set, named or not, with its
  activity's start, length and RPE. The sets cascade with their activity, so the
  pull's deletion reconcile and `wipe_garmin_data` take them along. Every write that changes
  what the history shows calls `bump_strength_history`, which is the evidence a kept
  session's kilograms may move on; `prescribed_sets_for_revisions` and
  `record_strength_check` read and write the planned side
  (DESIGN_strength_tracking.md §5, §9).
- **Metrics & Baselines** (`activities.py`) — `get_baseline(date)` returns the
  *closest prior* baseline. The scoped wipes (in `wipes.py`) are the non-obvious part:
  `wipe_garmin_data(start, end)` also clears the evidence-derived `analysis_cache`
  and, on a *full* wipe, resets the garmin/reflect/bootstrap watermarks (a dated wipe
  leaves them, since re-pull detects gaps by row presence);
  `wipe_calendar_signals(start, end)` always resets the Calendar sync token (the
  incremental sync otherwise can't backfill deleted rows); `wipe_metrics()` = both.
  `wipe_garmin_data` runs `garmin.recompute_derived()` **itself**, after its own
  transaction commits: deleted load stays baked into every later day's CTL/ATL EWMA
  until a sweep re-derives it (DESIGN_pmc_fitness_fatigue.md §4). It used to sit at the
  command layer (`cli/data.py`) to dodge a garmin↔db import cycle, which meant any
  other caller silently corrupted the derived metrics; the lazy `runtime` singletons
  removed the cycle, so the invariant now belongs to the operation.
- **Coach Learnings** (`learnings.py`) — `get_learnings()` annotates each record with
  computed `dormant` and `archived` flags and its `proposed_confidence`; `get_learning(id)`
  reads one; `add_learning` seeds a synthetic basis sustaining the level;
  `archive_learning`/`restore_learning`, and `delete_learning` for `learnings rm --purge`;
  plus the evidence/decay mutators (`apply_learning_deltas`, `recompute_all_confidence`,
  `apply_staleness_steps`, `demote_learning`, `keep_learning`) and module-level
  helpers/constants (`CONFIDENCE_LEVELS`, `RETIRE_PROPOSAL`, `ACTIVE`/`ARCHIVED`,
  `derive_confidence`, `step_down`,
  `learning_is_dormant`; the staleness budgets are config, not a constant —
  `config.learning_staleness_days`). The
  evidence/confidence/decay model these implement is **canonical** in
  [§3](#3-coach-package-architecture); tables in [§5](#5-database-schema).
  Periodization strategy lives in `macrocycles`, not here.
- **Analysis Cache** (`analysis.py`) — caches a backward-evaluation reconstruction
  (one row per `horizon`) keyed by an evidence fingerprint, so a re-run over unchanged
  data reuses it instead of re-calling the LLM; `save_analysis_cache` /
  `get_analysis_cache` (which parses `reconstruction` from JSON) /
  `wipe_analysis_cache()` — the last is the single wipe path, which `wipe_garmin_data()`
  delegates to rather than inlining its own DELETE. See DESIGN_backward_evaluation.md §5.1.
- **Macrocycles/Mesocycles** (`periodization.py`) — versioned: `save_macrocycle`
  **supersedes** the objective's existing active version (marks it `superseded`, keeps
  it) and inserts the new active one, running the mesocycles through
  `repair_mesocycle_contiguity` on the way in so within-plan gaps and overlaps never reach
  the table (DOMAIN_MODEL.md §4); `set_active_macrocycle(id)` promotes a version
  and supersedes the rest. `get_macrocycle_for_objective` returns the active version
  only, while `get_macrocycle(id)` / `get_macrocycle_versions` /
  `get_previous_macrocycle_version` reach any version for walk-back navigation.
  `get_preceding_macrocycle` is the other "previous plan" — the previous *goal's* active
  one, for retrospective views that must not walk superseded versions; `plan_versions.py`
  is the shared walk. Plan versioning + rollback: DESIGN_plan_rollback.md (§6.1 for the
  two accessors). The plan's feedback log lives here too: `add_plan_feedback` /
  `list_plan_feedback` (joined with mesocycle names, oldest first) / `get_plan_feedback` /
  `rm_plan_feedback`, replacing the `update_*_feedback` overwrite slots
  (DESIGN_plan_feedback.md §6). `delete_macrocycle_for_objective` deletes the goal's
  retrospectives with its plan versions.
- **Retrospectives** (`retrospectives.py`) — one record per finished mesocycle and per
  finished plan (DESIGN_cycle_retrospective.md §11). `add_retrospective` inserts with
  `INSERT OR IGNORE` and returns None when the goal already has a record of that level
  starting that day, so running the date check twice creates nothing twice.
  `get_retrospectives(objective_id, level)` lists oldest first and parses `numbers` from
  JSON. `write_retrospective` stores what the write step produced,
  `set_retrospective_words` the athlete's own words. The module also names the two levels
  and the three ways a record ends.

---

## 5. Database Schema

SQLite database at `stamind.db` (path from `config.db_path`), in **WAL** mode with a
5-second busy timeout — CLI, web app and bot are concurrent surfaces over one file, so a
pull overlapping a dashboard refresh is ordinary rather than exceptional.

`_init_db` creates every table at `SCHEMA_VERSION` (`db/schema.py`) and records that in a
`schema_version` table. Later starts see the stamp and do nothing, so `sm --help`
performs no I/O. It is **CREATE TABLE IF NOT EXISTS only**: there are no in-place
migrations. A new table is built by the CREATE on the next start. A column added to a
table that exists, or stored values rewritten, is done once per instance, by a one-off
script under `scripts/` or an ALTER by hand (a migration is one-off by policy, AGENTS.md),
and the CREATE statements carry what it built. Clearing the stamp rebuilds a database that
is missing a table. Bump
`SCHEMA_VERSION` when the DDL changes — reusing the number a previous commit already
stamped is silent, since every existing database skips the change while fresh ones (and so
the tests) look fine; `test_db_lifecycle.py` fingerprints the schema and fails on an
unbumped change.

`db.transaction()` runs several writes as one connection and one commit, and rolls the
lot back on an exception. Methods called inside it join automatically — their own
`conn.commit()` is deferred to the end — so a PMC recompute over a long history costs
one connection instead of one per day.

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

`date_type` says what `target_date` means: an **event** is a day something happens
on, so the plan peaks and tapers for it; a **horizon** is just how far the athlete
wants to train toward the goal — the plan still ends around the date, but with an
ordinary training mesocycle, no peak/taper pinned to it, and the goal-week
no-benchmark carve-out does not apply. The planning prompt branches on it
(`engine/planning.py`), goal lines everywhere tag it
(`engine/prompt.py:_render_goal_lines`), and `_clean_goals` includes it only when
`horizon` so pre-existing plans keep their `goals_hash`. Rationale in
[§15](#goal-dates-event-vs-training-horizon).

`status` records one thing: whether the goal was **called off**. Completion is not
stored — a goal that is not archived and whose `target_date` has passed *is*
completed, derived on every read by `db.objectives.goal_state()` →
`upcoming | completed | archived`. That one function is what every surface (`goal
list`, `status`, the web view) renders, so no two of them can disagree. `goal edit
--status` offers only `active`/`archived`. Rationale — and the two
opposite failure modes the old three-value column produced — in
DESIGN_backward_evaluation.md §12.

The accessors name which question they ask: **`upcoming_objectives()`** (not
archived, date not passed) is "the goals that matter" at every planning and picker
site; **`get_active_objective()`** with no ID is the next goal still ahead, while
its ID form resolves any non-archived goal, past or future; and
**`get_preceding_objectives()`** deliberately includes completed goals, which are
the point of the lookup. `runway.plan_gap()` filters only `!= archived` — its
`target_date > plan_end_date` comparison already answers the date question.

### constraints
Everything the athlete asks the coach to work around,
at any horizon (DESIGN_constraints.md). Supersedes `lifeevents`.
| Column        | Type       | Notes                                                     |
|---------------|------------|-----------------------------------------------------------|
| `id`          | INTEGER PK |                                                           |
| `start_date`  | TEXT       | YYYY-MM-DD                                                 |
| `end_date`    | TEXT       | YYYY-MM-DD (== start for a single day)                     |
| `rest`        | INTEGER    | 0/1 — the **single** deterministic edge (rev 6): 1 = a no-training window whose dates skip the LLM and are forced to rest. Everything else is advisory prose the coach honors by judgement |
| `title`       | TEXT       | The constraint, stated short; the `list` display string   |
| `description` | TEXT       | Optional richer context, read by the LLM                  |
| `replan`      | INTEGER    | 1 = escalated to plan-shaping (built into the plan, §7)    |
| `source`      | TEXT       | `manual` \| `message` \| `lifeevent` (migration)          |
| `created`     | TEXT       | UTC ISO                                                    |
| `honored_at`  | TEXT       | UTC ISO of the last coach pass that had this constraint in scope **with authority over every day of it still ahead** — `workout generate` or `workout adapt`. NULL ⟺ the schedule does not reflect it yet. Deliberately NOT a claim that the schedule changed. Two rules, both owned by `coach/honoring.py` and nowhere else: who may stamp (`covers`), and whether the schedule is missing the constraint at all (`needs_a_pass` — unstamped, `replan = 0`, a non-empty window, and **at least one session scheduled in that window**, since a window with nothing in it is nothing to reshuffle). `status`, `constraint list`/`show` and the add-time message all call that one predicate; there is deliberately no SQL half-copy of it in `db/constraints.py`, because that is how they came to disagree (DESIGN_constraint_honoring.md §2/§4). Cleared by a `constraint edit` that moves the window or rewrites the constraint, and by a rollback restoring a plan older than the honoring |

Index: `idx_constraints_start` on `start_date`.

### workouts

**Append-only.** A row is one *revision* of one session and is never updated or deleted;
every change appends. The newest revision in a `(date, sport_canonical)` slot is the live
one, and everything else is history. Two triggers enforce that (see
[Workout state](#workout-state--three-orthogonal-axes-not-one-enum) below); several state
facts are **derived, not stored**. See DESIGN_workout_revisions.md.

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
| `summary`       | TEXT       | The batch rationale — what `adaptation_summary` used to copy onto every row. |
| `macrocycle_id` | INTEGER    | The plan version in force when this ran: context for `workout batches`, distinct from the per-row tag. |
| `note`          | TEXT       | The coach's one line to the athlete about this change. A `generate` writes it only when something they would notice changed (DESIGN_plan_change_continuity.md §6.3); an `adapt` that changed something stores its reason here too; a `rollback` writes its own line about what it undid. NULL on everything else (DESIGN_change_heads_up.md §6). |
| `told_at`       | TEXT       | UTC ISO, when the athlete was told about this change: stamped as it is written when they watched the run, else by `bot changes`. A change is **waiting** when it has a `note`, no `told_at`, and still stands (DESIGN_change_heads_up.md §6). |
| `sleep_seen`    | INTEGER    | 1 when an `adapt` (or `tweak`) read a sleep score for its day, 0 when it ran before the watch had synced, NULL on every other kind. What lets the morning push skip an adaptation that already ran with the night in hand (DESIGN_bot_simple_frontend.md §4.2). |
| `commitment_end`| TEXT       | Last day of the commitment window in force when this ran, so a removal is judged by the window it was written under rather than by the one standing when the Calendar sync happens to run (§5.2). |

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

*Archived* is no longer an axis. A superseded revision is not a flagged row but a position
in a chain: an older sibling in its slot. What remains is three independent facts, none
stored as a status string.

All three axes reach the athlete as bracket markers on one `workout list` line, so the
words are glossed under the listing: `print_marker_legend` in `cli/workouts/session_line.py` draws
a gray footer saying what each marker means, for the markers that listing actually
printed (`line_markers` reads them back off the rendered lines). `[STALE]` is why it
exists — the word names no subject on its own, and what it is about is the session's
Google Calendar event. Only markers on screen are glossed, the way `journal` glosses only
the outcomes on screen (DESIGN_logging.md §7.2), and a legend is answer-level output
rather than an aside (DESIGN_output_verbosity.md §3.3). The `workout generate` preview
prints the same footer, since it draws the same lines.

**1. Modified?** = the change kind of the live revision. No heuristic, no string prefixes,
no precedence rule — the kind was recorded when the change ran:

| Live revision's change kind | Reads as |
|---|---|
| `generate` | unmodified |
| `adapt` | adapted |
| `tweak` | tweaked (changed on request) |

  - A `rollback`/`reinstate` copy re-establishes an earlier prescription, so it reads as
    whatever *that* prescription was — the same `restored_from` jump the tally makes.
    Voids carry `[REMOVED]` instead.
  - **Markers:** `workout list` renders the kind *and* the standing easings, so a session
    eased twice reads `[ADAPTED ×2]` and one changed on request `[TWEAKED]`. Two facts
    rather than one, which is why there is no longer a rule about which wins.
    `modification_markers` in `stamind/workout_state.py` is the single renderer; the web
    API serves its output.
  - **The adaptation tally** (`adaptation_count` / `adapted_at`) is derived by walking the
    lineage backwards from the live revision: jump over any span a `restored_from` copy
    undid, stop at the first `generate` or `tweak` (a re-prescription; easings of the old
    form do not describe the new one), and count the `adapt` revisions whose duration or
    TSS fell against their own predecessor. Because the walk follows the *lineage*, it
    survives a move — which is the whole reason `lineage_id` exists. The daily adaptation
    renders it
    as the `[ALREADY EASED …]` tag so a re-run holds an already-eased session instead of
    stacking another cut onto still-lagging recovery.

**2. Calendar state** = derived by `stamind.workout_state.calendar_status(workout)`:

| Result | Condition |
|--------|-----------|
| `unpushed` | `google_event_id IS NULL` |
| `synced` | `pushed_signature == ` current calendar-field hash |
| `stale` | `pushed_signature != ` current hash |

  - `mark_workout_pushed` is the **only** writer of `pushed_signature`. Under revisions
    this falls out rather than being arranged: the live row after any change is a
    *different row*, its hash differs from the stored signature, and it reads stale.
    `CALENDAR_FIELDS` carries `revision_id`, which is what makes *any* appended revision
    move the hash — the event renders the whole lineage as its history, so a lineage that
    grew is an event that changed (DESIGN_calendar_lineage.md §6).
  - **Who keeps the Calendar true.** Every workout change ends with one **reconcile pass**
    over the lineages it touched, after commit (`stamind/gcal/reconcile.py`). The
    change handle schedules it, so the only way to write workouts already schedules the
    reconcile, and no command carries Calendar code. Per lineage, keyed on its **newest
    revision**, live in its slot or not (`get_lineage_head`): a session that still owns
    its slot and whose signature differs is pushed; one that no longer owns it was
    superseded, and its event goes. A void is decided by `leaves_trace`
    (DESIGN_plan_change_continuity.md §5.2) — the athlete's own removal (a goal stood
    down), or one removed inside the commitment window the change ran under keeps its
    event, retitled, and gets one if it never had one; every other void's event is
    deleted and its state row dropped. Reading the lineage rather than the slot is what
    lets a marker written and then covered in the same run survive the run that wrote it.
  - **What the event says.** Title tags first (`[Done]`/`[Adapted]`/`[Deleted]`/
    `[Cancelled]`; a tweaked session has no tag, its `Reason:` says what was asked), then
    the body: the current load line, the current
    description, its `Reason:`, the intensity target, the **`History` section** — every
    earlier revision of the lineage, newest first, each with its date, load, target,
    reason and body (`gcal/history.py`, DESIGN_calendar_lineage.md) — and last the
    `Planned: … · Last adapted: … · Adapted ×N` lifecycle line over the goal/macro/meso/
    workout ids. A session that has never been revised has no `History` section and renders
    exactly as before.
  - **Stale is a retry marker, not a defect.** It persists when the push could not land
    (offline, API error) or was declined (`--no-sync`), and every pushed event reads stale
    once after a change to `CALENDAR_FIELDS` — the stored hash was taken over the old
    field list, so it cannot be reproduced and one re-push clears it. `workout push`
    defaults to **today onward**, so `warn_stale_before` (in
    `cli/workouts/calendar_sync.py`) reports anything stranded stale in the past and the
    `-d START..` window to recover it. The batch runs under one self-erasing progress bar
    with the per-event lines silenced (`sync_multiple`), the same framing the reconcile
    pass gives a workout change: an event *update* prints nothing of its own, so a long
    push would otherwise be silent.
  - **Orphans** are the reverse direction: an event whose session is gone (fresh DB,
    restored backup, a wipe that skipped Calendar) can no longer be named locally, so
    `workout prune-calendar` sweeps from the calendar side — `list_workout_events` finds
    them by the `source=stamind` tag and deletes any id no lineage claims.
  - **Backward adherence marking** is the past-looking counterpart to the forward push:
    for each *strictly past* planned workout with an event, it re-renders the event with a
    verdict from `adherence.classify_adherence` — a `[Done]`/`[Missed]`/`[Partial]`/
    `[Rest OK]`/`[Rest broken]` title tag and an `Adherence:` description header.
    Today/future are skipped. Runs **by default** on `data pull` and `workout compare`
    (`--no-mark` skips); best-effort, no-op without a calendar. Shared pipeline
    `mark_adherence_range`→`mark_adherence_from_results` in `cli/common.py`. Each push
    stamps `adherence_pushed_signature` (calendar fields **plus** verdict) so a later pass
    skips a no-op write; kept in its **own** column, and any edit to the session
    invalidates it so a re-mark follows.
  - **The verdict is shown where the session is listed**, not only on the Calendar:
    `workout list` marks every listed session dated today or earlier
    `[DONE]`/`[PARTIAL]`/`[MISSED]`/`[REST OK]`/`[REST BROKEN]`, or `[NOT YET]` for one
    still ahead of the athlete today, and `-v` names the activity it was graded against
    plus what a `[PARTIAL]` differed by. `/api/workouts` hands the dashboard the same
    verdict as each row's `adherence` (status, word, reasons, matched activity), rendered
    as a badge. One pairing behind all three — `analytics/compare.py:adherence_verdicts`
    over `adherence_window` — so a terminal line, a Calendar event and a web card cannot
    disagree about whether a session happened. The listing grades **the whole window**,
    never the rows it happens to be showing: matching is per-day and first-come, so a
    narrowed listing that graded only its own rows would hand an activity to whichever
    session survived the filter. Because the listing now reports on completed activities,
    it freshens Garmin over that past span first (`--no-pull` skips it); a listing
    entirely in the future costs neither a pull nor a query.

**3. Removed?** = the live revision is a **void**. The session is not deleted, and
everything before the void is still in the log. `get_workouts` excludes voids by default
(`include_removed=False`), so they vanish from `workout list`/`compare`, adherence,
generation and the web API, and are **not** counted as misses. The adapt flow re-fetches
the voids of a goal stood down (`include_removed=True`) and surfaces them to the week
planner as deliberate cancellations; `workout tweak` is shown every void ahead instead
(`get_cancelled_workouts`), so a request can bring one back. A session an adapt or a
tweak dropped and a session a plan no longer holds are voids too — the change kind is
what tells them apart, and it is what decides whether the Calendar event is kept or torn
down.

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
| `exercise`     | TEXT    | The key of the exercise's class in the exercise table (DESIGN_exercise_table.md §4), so weighted pull-ups and plain ones are one history. A Garmin name the table lacks is its own key. NULL while unnamed |
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
| `exercise`   | TEXT    | A key of the exercise table                                  |
| `sets`       | INTEGER |                                                              |
| `reps_low` / `reps_high` | INTEGER | The rep range, equal for a fixed count. The reps are the athlete's dial, the load the strength planner's (§10) |
| `load_kg`    | REAL    | NULL for a bodyweight exercise with nothing added            |
| `light`      | INTEGER | 1 on every row of a light week's session, which the history marks "(light)" |

### strength_checks
Which evidence each strength session's kilograms were last weighed against
(DESIGN_strength_tracking.md §9). Keyed by lineage, so it follows the session across
revisions and across a move. Written when a proposal is applied or recorded as no change,
never when it is proposed. Without it a kept Thursday could come back at 142.5 where it
stood at 145 the next morning, from lifting already weighed.

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

CTL/ATL/TSB (the Performance Management Chart, DESIGN_pmc_fitness_fatigue.md) are the
whole stored load model, computed in `garmin.recompute_derived()` over every calendar
day (rest days decay the EWMAs) and upserted onto existing metrics rows. The two time
constants (CTL/ATL) are config-backed under `garmin:`; the defaults are the supported
configuration. The warm-up window (first τ_ctl days of history) is suppressed at every
surface, and a static "still warming up" flag is shown while total history is short
(< 3·τ_ctl).

**ATL:CTL ratio.** Relative overload — fatigue against the athlete's own fitness base —
is *derived at read time* by `analytics.pmc.load_ratio(atl, ctl)`, never stored: it is a
division of two columns already on the row. It replaced the stored ACWR
(`acute_workload`/`chronic_workload`/`acwr`, dropped by the guarded DDL in
`db/schema.py`); see DESIGN_load_ratio.md.

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
App preferences that outlive one invocation but aren't training data — a generic
key/value store, so the next single-value preference needs no schema change.
Untouched by every `wipe` (a data wipe is about training history). Every athlete-facing
key is one entry in the `stamind/settings.py` registry, written only by `settings set`
(DESIGN_settings.md): `llm_model` and `fast_llm_model`, the thinking and fast model
identifiers; `timezone`, the IANA zone every date is computed in;
`workout_commitment_days` (`commitment-days`), how many days from today the athlete is
treated as already committed to; `push_enabled`, `push_morning_time`,
`push_morning_deadline` and `push_adapt_first`, the morning-push window and its switches;
`push_evening_time` (`evening-time`), the hour from which the bot sends nothing on its own
(DESIGN_athlete_queue.md §13.2 rule 4);
`changes_delay_minutes` (`change-delay`), how long a change to one of today's sessions waits
before the athlete is told (DESIGN_change_heads_up.md §4); `confirmation_days`
(`confirmation-days`), on how many mornings a question about what the athlete just wrote is
asked again (DESIGN_chat_questions.md §2); `coach_terse` (`terse`), whether
the coach keeps what it says about a change short (DESIGN_output_verbosity.md §9);
`strength_logger` (`strength-logger`), whether the companion keyboard offers the gym
logger button (DESIGN_gym_logger.md §6).
Three internal markers are the exception, not preferences: `push_morning_last`, the
per-day idempotency stamp (`DESIGN_bot_simple_frontend.md` §4.3);
`changes_notify_upto`, the id of the newest change `workout notify` asked the bot to send
at once — an id rather than a flag, so it cannot send a later change early
(DESIGN_change_heads_up.md §4); and `strength_history_changed_at`, bumped by every
write that changes what the strength history shows — a read that stored sets, a freeze, a
name given or cleared, a discard or its undo, and the pull's reconcile deleting a strength
activity that had sets. That last one is the evidence a kept strength session's kilograms
may move on (DESIGN_strength_tracking.md §5, §9). `push_note_last` is gone: whether the
athlete heard of a change is `workout_changes.told_at` now.

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
External daily signals (alcohol, sleep, stress, …) ingested from tagged
Google Calendar events. Stamind is domain-agnostic: `metric` is an opaque
category and `value` an optional numeric magnitude. Reconciled by
`google_event_id` (upsert on edit, delete on cancellation). See §13 and
`DESIGN_calendar_signal_ingest.md`.

Three producers write these rows: the external syncer, `signal add`
(`DESIGN_signal_authoring.md`), and `workout adapt --message`, which extracts signal
candidates from the note and writes the ones the athlete confirms
(`DESIGN_signal_extraction.md`). All three go through the calendar first —
`google_event_id` is NOT NULL — and all three share `signals.write_signal_days`.
`stamind/signals.py` also holds the suggested category vocabulary
(`DEFAULT_SIGNAL_METRICS`, augmented by `coach.signal_metrics` in config) and
`SIGNAL_CHANNEL_EXCLUSIONS`, the substring table that stops a category being correlated
against a reading measuring the same thing. Vocabulary and exclusion table live in one
file because the exclusion matches on the category's spelling: a sleep category named
without "sleep" in it silently loses the guard.

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
The dated fitness-test logbook (`DESIGN_benchmark_workouts.md` §3.2) — the single home
for the athlete's trainable thresholds now that `ftp`/`lthr` have left config (§3.4). One
row per measurement; "latest" is newest by `date`, `id` as tiebreak. The latest row per
`anchor_kind` is what `CoachService.effective_thresholds()` feeds the coaching prompt and
the plan-staleness snapshot. Two further consumers read the logbook **rows** rather than
the effective set — the intensity mesocycle report (`mesocycle_report._benchmark_lines`, into the
coaching prompt and `sm progress`) and the read-only `GET /api/benchmarks` — both via
`benchmarks.with_previous()`, which supplies the per-row delta against the previous row of
the same kind. No privileged kinds — cycling FTP and a first swim CSS flow
identically (§3.5). Vocabulary (kind → label, unit, better-direction) lives in
`stamind/benchmarks.py`, which also holds `SPORT_ANCHORS`/`anchors_for_sport()`: the
plausible anchors per **canonical** sport (aliases resolve through `canonical_sport`),
behind a *warning* on an implausible pair (`record swimming --ftp 250` warns and records
anyway). Never an error — `sport_type` is a label, the effective threshold is keyed on
`anchor_kind` alone, and an unknown sport stays silent. CRUD in `db/benchmarks.py`; CLI
verb `benchmark record`/`list`/`rm` (+ hidden `wipe`) (`cli/benchmarks.py`).

| Column        | Type       | Notes                                                     |
|---------------|------------|-----------------------------------------------------------|
| `id`          | INTEGER PK | Autoincrement                                             |
| `date`        | TEXT       | YYYY-MM-DD the test was performed                         |
| `sport_type`  | TEXT       | Canonicalized sport                                       |
| `anchor_kind` | TEXT       | `ftp` \| `lthr` \| `threshold_pace` \| `css` \| `e1rm` \| `mas` |
| `value`       | REAL       | The measured number (pace kinds stored in base unit)     |
| `unit`        | TEXT       | `W` \| `bpm` \| `min/km` \| `sec/100m` \| `kg` \| `km/h`  |
| `source`      | TEXT       | `test` \| `manual` \| `modeled` (last anticipates Phase 3)|
| `workout_id`  | INTEGER    | Nullable lineage id of the planned test it satisfied; set by `--session` |
| `note`        | TEXT       | Free text (protocol, conditions)                          |
| `created`     | TEXT       | UTC ISO                                                    |

### coach_learnings
Discrete, addressable athlete-observation records. Confidence is **app-computed**
from the `learning_evidence` basis (below), not asserted by the LLM. Full model:
[§3](#3-coach-package-architecture).

| Column                | Type       | Notes                                                  |
|-----------------------|------------|--------------------------------------------------------|
| `id`                  | INTEGER PK | Referenced by `revise`/`reinforce`/`contradict`/`retire` deltas |
| `text`                | TEXT       | LLM-generated observation                              |
| `sports`              | TEXT       | Comma-separated sport scope, or `general` (default)    |
| `confidence`          | TEXT       | App-computed: `tentative` / `moderate` / `established` |
| `proposed_confidence` | TEXT       | Pending, human-confirmable **downgrade** (`retire` = propose retirement); NULL when none |
| `created_at`          | TEXT       | ISO timestamp                                          |
| `updated_at`          | TEXT       | ISO timestamp; last content/metadata change            |
| `last_reinforced_at`  | TEXT       | ISO timestamp; drives decay → `dormant` (see §3); refreshed only by a *new* supporting week or a staleness step |
| `status`              | TEXT       | `active` / `archived`; retiring a learning archives it (DESIGN_learning_doubt_nudge.md §6) |

### learning_evidence
The per-learning **evidence basis**: the distinct training **weeks** backing each
learning, tagged supporting/contradicting; `confidence` is a pure function of it.
The `UNIQUE(learning_id, week_commencing, polarity)` constraint is the dedup
guarantee (re-citing a counted week is an `INSERT OR IGNORE` no-op). Full model:
[§3](#3-coach-package-architecture); DESIGN_evidence_based_confidence.md §5.

| Column            | Type       | Notes                                              |
|-------------------|------------|----------------------------------------------------|
| `id`              | INTEGER PK |                                                    |
| `learning_id`     | INTEGER    | FK → coach_learnings.id (ON DELETE CASCADE)        |
| `week_commencing` | TEXT       | YYYY-MM-DD (Monday) — the evidence anchor          |
| `polarity`        | INTEGER    | +1 supporting · −1 contradicting                   |
| `source`          | TEXT       | `reflect` \| `bootstrap` \| `manual` \| `migration` (`plan` is a reserved value in the schema comment; `plan generate` is a non-writer, so nothing emits it) |
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
| `config_hash`     | TEXT                  | SHA-256 of the plan-shaping `user_profile`       |
|                   |                       | fields (thresholds, `name` and equipment excluded |
|                   |                       | — `DESIGN_plan_staleness.md` §3)                  |
| `config_snapshot` | TEXT                  | JSON of the effective threshold anchors (`max_hr` |
|                   |                       | + logbook kinds) the plan was generated with;     |
|                   |                       | staleness only past `coach.threshold_replan_pct`  |
|                   |                       | drift. NULL on plans predating the column. Shown  |
|                   |                       | by `plan show`, compared by `plan diff`.          |
| `profile_snapshot`| TEXT                  | JSON of the plan-shaping profile fields the plan  |
|                   |                       | was generated with, so the staleness reason can   |
|                   |                       | name which one moved. NULL on plans predating the |
|                   |                       | column — those get the unnamed reason (§5).       |
| `goals_snapshot`  | TEXT                  | JSON of the goals the plan was generated from    |
|                   |                       | (same cleaned data the hash covers); NULL on     |
|                   |                       | plans predating the column. Shown by `plan show` |
|                   |                       | and the web strategy card.                       |
| `constraints_snapshot` | TEXT             | JSON of the plan-shaping constraints the plan was |
|                   |                       | generated from; NULL on pre-snapshot plans (older |
|                   |                       | plans fall back to a legacy `lifeevents_snapshot`) |
| `created_at`      | TEXT                  | ISO timestamp                                    |
| `status`          | TEXT                  | `active` or `superseded`. Exactly one active     |
|                   |                       | version per objective; readers filter on active. |
|                   |                       | Defaults to `active` (legacy rows). See           |
|                   |                       | DESIGN_plan_rollback.md.                          |
| `superseded_at`   | TEXT                  | ISO timestamp a version stopped being active;     |
|                   |                       | NULL while active.                               |
| `summary`         | TEXT                  | The strategy in at most two sentences, written beside it by `plan generate`; `plan show` prints it in place of the strategy unless `-v`. NULL when the model leaves it out (DESIGN_output_verbosity.md §5.1) |

Regenerating a plan **supersedes** the prior version (kept) rather than deleting it, so
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
consumed flag: supersession is the consumption event, so a regeneration that is previewed
and declined leaves the notes pending, and a `plan rollback` makes an earlier version's
notes pending again. Pending notes are a plan input, so their presence alone makes
`plan generate` regenerate without `--force` (DESIGN_plan_feedback.md §7).

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
Cached backward-evaluation reconstruction (inferred cycles + insights), keyed by
an evidence fingerprint. One row per `horizon`; cleared by `wipe_metrics`. See
DESIGN_backward_evaluation.md §5.1.

The `horizon` **selects the question, not just the slot**: `_data_analyze_logic` takes it
and branches, so `long` (`data bootstrap`) asks for the periodization structure while
`short` (`data reflect`) asks only how the athlete responded and is told not to infer
macro/mesocycles — a few weeks cannot support the claim
(DESIGN_backward_evaluation.md §10.3). Three forward consumers read the table —
`plan generate`'s prior-training context via `CoachService._cached_reconstructions()`;
`stamind/timeline_rows.py`, which feeds the reconstruction's `inferred_mesocycles` into
`timeline.assemble_timeline()` as `~`-prefixed bands wherever no planned mesocycle covers
the span (DESIGN_progress_timeline.md §6.1); and `data show-analysis`, which renders a
slot as stored. The timeline reads `long` alone; the plan prompt replays **both** slots,
`short` only when its window *starts* after `long`'s ends — a window that re-reads
bootstrap's weeks on its way past them would show one body of evidence twice. Neither
consumer checks the fingerprint — it is consulted only in the *writing* flow, so a
months-old reconstruction can be replayed (the covered window is printed alongside it),
and `_maybe_warn_stale_analysis()` says so once the latest of the two windows falls
`coach.analysis_staleness_days` behind. That warning is judged over the same accessor the
prompt reads, so the `data reflect` it points at is a command that can clear it
(DESIGN_backward_evaluation.md §10.2).

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

The same applies to the Calendar. The Calendar module used to build a `CalendarSyncer`
at module scope, and that constructor reads the service-account credentials file — so
every CLI command and the web app needed that file on disk even on an instance with no
Calendar configured, and a fresh worktree could not collect a single test without it.
The builder constructs it now, so nothing reads the credentials until something asks for
`runtime.calendar_syncer`.

Reading at use time is what makes one assignment authoritative. Binding by value
captures whatever existed at import and is invisible to a later override — that mismatch
is why replacements used to "take" for some modules and not others. `stamind.db` used
to carry its own lazy `db` accessor for callers that wanted a handle of their own; it is
gone, and `runtime.db` is the only way to reach the singleton.

`stamind_cli.py` is a plain entry point: it holds `main()` and its helpers, and
nothing under `stamind/` imports it. Handlers reach singletons through `runtime`, so
the import cycle that forced the old `sys.modules.setdefault("stamind_cli", …)`
self-alias no longer exists.

`openrouter_client.model` is a lazily-resolved property, not a plain attribute: it reads
the stored choice from the database on first use, so importing the module never opens the
DB. Assigning to it pins a model for the invocation (how `--llm-model` overrides the stored
choice); `reset_model()` drops the cache so the next call re-resolves — what
`settings set thinking-model` calls, since the REPL runs many commands in one process
(DESIGN_model_selection.md §3.1).

`clock.active_zone()` is the same shape for the athlete's timezone: the
`settings.timezone` row is read on first use and cached for the process, since
`today_date()` asks on every call. `clock.reset_cache()` drops it — the registry's
`on_change` hook for the `timezone` setting, and what the bot's push loop calls each tick
because `settings set` runs in a CLI subprocess (DESIGN_user_timezone.md §2/§3).

`stamind/garmin/` exposes module-level functions rather than a singleton, all
re-exported from its `__init__.py`: `pull()`, `ensure_data()`, `reset_memo()` (tests),
`connect()`, `recompute_derived()`, `backfill_tss()`, `pmc_history_start()` and
`warmup_cutoff()`, plus the `GarminClient` class and `GarminAuthRequired`. The training
maths it used to re-export — `activity_load`, `compute_pmc`, `load_ratio` and the rest —
is `stamind/analytics/`, imported by name.

The **prompt broker** is `runtime.prompt`. `CoachService` takes it as a constructor
argument (`prompt_instance=`, defaulting to `runtime.prompt`) so the service can ask a
question without importing a frontend — it used to do `import stamind_cli as cli`
mid-method, which meant any non-terminal caller got a terminal conversation.
`make_prompt()` selects the transport from
`STAMIND_FRONTEND`: `TtyPrompt` (the default — `input()` with `[y/N]`, EOF→default,
keys pressed before the question dropped, a confirm re-asked on anything but
yes/no/blank, DESIGN_output_verbosity.md §8.5) or `JsonPrompt` (`json` — the Telegram
bot). Every interactive `input()` site routes
through `cli.prompt.confirm(message, danger=…)` / `cli.prompt.choose(message, [Choice…],
default=…)` / `cli.prompt.ask_text(...)`. `JsonPrompt` writes one sentinel-framed
request line (`\x1eSM-PROMPT {json}`, fields `v/id/type/message/default/danger/choices`)
to stdout and waits to read one JSON answer line (`{v,id,answer}` or `{v,id,cancelled}`)
from stdin. A cancellation raises `PromptCancelled`, an ordinary `Exception`. It once
subclassed `BaseException` so the handlers' broad `except Exception` nets could not
mistake a deliberate abort for a command error; those nets are gone, a structural test
fails on any `except Exception` enclosing a prompt call, and `run_once` catches it before
its own error boundary — `main` prints `Cancelled.`. Garmin MFA (`garmin/client.py`)
stays outside the broker: it's gated by `sys.stdin.isatty()` and raises
`GarminAuthRequired` off a TTY, so it never hangs the bot.

The broker is also where an answer is **journalled**, in `_record_answer` — one `info`
`note` reading `<question> → yes|no`, with `d.answer` for querying. It goes here and not
at the ~29 call sites because this is the only thing that asks, so a question added later
is covered the day it lands; `tests/test_journal.py` fails on any bare `input()` under
`stamind/cli/` or `stamind/coach/` to keep that true. Three cases stay apart: EOF (cron,
a pipe) records `defaulted` rather than a decision nobody made, a cancel records the
question that was open, and `ask_text` is not journalled at all because its answer is the
athlete's free text (DESIGN_logging.md §4.4). The record lands on the innermost open run of
the process that writes — under the bot that is the CLI subprocess, so it carries the
command's run id and not the bot's. The two imports it needs are deferred so this module
still imports nothing beyond the stdlib. DESIGN_logging.md §5.6

The **renderer** is `runtime.render`, the same shape one axis over: the broker chooses a
*transport*, the renderer chooses a *voice*. `cli/render/persona.make_renderer()` reads
`STAMIND_RENDER` once and returns `ExpertRenderer` (reports, tables, IDs, operator
nudges) or `CompanionRenderer` (prose, day words, no IDs, no commands the athlete cannot
type). They are two objects and not one "persona" because the axes are independent:
the web dashboard is expert-voiced with no TTY. A command body holds no `if simple:`
branch — it calls `runtime.render.<what happened>(…)`, and `CompanionRenderer`'s override set is the
opted-in list; the `cli/render/` package also holds every companion line builder —
`session_lines.py` for a day and what was trained in it, `plan_lines.py` for the goals,
constraints and plan it is built from — so the whole voice reads in one place. Two more
files there speak for the calendar ([§17](#17-calendar-telegram-mini-app-and-sm-calendar)):
`calendar_page.py` builds the page's snapshot from those line builders, `plan_page.py` the
"Goals & plan" page's, and
`calendar_grid.py` is `sm calendar`'s month grid, which `ExpertRenderer.calendar_month`
prints. The expert table renderers stay in their command modules (`print_workout_table`,
`print_plan`, `print_progress_report`, …) and `ExpertRenderer` delegates. Command
modules never import `cli/render/` — the builder in `runtime.py` defers that import,
which is what keeps the graph acyclic, and `test_simple_render.py` exempts the render
package by directory, so cutting it into more files cannot widen the exemption. The one
command package allowed to import the builders directly is `cli/bot/`, because the
companion surfaces are companion-only and have nothing to choose; that exemption is
spelled out file by file (`bot/views.py`, `bot/capture.py`, `bot/edit.py`, `bot/goal.py`)
rather than by directory, so a new file there has to be added to it deliberately. The
package's `__init__.py` holds only its docstring: `make_renderer` lives in `persona.py`, so
importing a line builder does not import the two renderers, whose expert half reaches into
the commands and, through `cli/queue.py`, the list of queue kinds that imports `bot/edit.py`
and `bot/goal.py`. `tests/helpers.run_cli`
drops the cached renderer per invocation so each run reads the environment as a real CLI
process does. DESIGN_render_persona.md

For tests, call `tests.helpers.rebind_test_db(test_db)`: it sets `runtime.db` plus the
remaining by-value sites in one call, so a module cannot be left reading a different
handle than its neighbours. `tests/__init__.py` installs two backstops before anything
imports the app — `sqlite3.connect` refuses the production database and `socket.connect`
refuses remote hosts — because both seams otherwise fail silently and leave a green
test that measured nothing. `tests/test_isolation_guards.py` asserts they still fire.
That file also fails when a test calls `tempfile.mkdtemp()` without registering an
`shutil.rmtree`, which is the same shape of silent failure: the suite once left 22,600
directories under `/tmp`, filled the partition and cost every process its scratch space.
The same file fails when one command calls another's `run_*` handler through a name it
imported by value: a `patch` aimed at the handler's own module then stubs a name the
caller never reads, so the real handler runs and a test that believed it had mocked the
coach reaches OpenRouter. A command reaches another through its module —
`import stamind.cli.plans.generate as _generate`, then `_generate.run_plan_generate(…)`
— exactly as `coach/engine/` reaches `_eng.openrouter_client`.

Names still patched where they are *used* rather than through `runtime`:
`stamind.coach.engine.openrouter_client` (the LLM seam). The clock is patched at its
source instead — `tests/helpers.pin_clock` freezes `stamind.clock.now`, the one instant
`today_date()` reads — so a module that imported `today_str`/`today_date` by value is
pinned with it. That was a list of the individual import sites and had drifted to 6 of
the 24 that exist, which is how real dates reached fixtures and expired them.

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
prompt and exits before the call, and the root `--llm-model MODEL` pins the thinking
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
| `learnings`  | `list`       | `l`      | Show coach learnings (`-t/--type/--sport`, `--confidence`, `--dormant`)            |
| `learnings`  | `show`       | —        | Show a learning's full text + per-week evidence basis by ID             |
| `learnings`  | `edit`       | —        | Edit a learning's text (`ID TEXT`, both positional)                     |
| `learnings`  | `rm`         | `r`      | Delete a learning by ID                                                 |
| `learnings`  | `demote`     | —        | Accept a pending confidence downgrade by ID                            |
| `learnings`  | `keep`       | —        | Dismiss + affirm a pending downgrade by ID                             |
| `learnings`  | `wipe`       | —        | Delete all coach learnings                                             |
| `plan`       | `generate`   | `pl g`   | Generate/reuse macrocycle+mesocycles (`-f` to force, `-y/--auto` to apply without the preview, `--fresh` for a clean slate that withholds the plan in place from the prompt, `--show-llm-context` to also print the planned-vs-actual review the prompt carries — off by default, DESIGN_output_verbosity.md §7; `--feedback TEXT` first files TEXT as a plan-level note, exactly as `plan feedback "TEXT"` does, and refuses a goal range or a goal with no plan yet — DESIGN_plan_feedback.md §4). `-g/--goal [RANGE]` takes the shared range grammar: one ID plans that goal alone, bounded to its own span (opening the day after the goal before it); a range plans every upcoming goal it covers, in date order, one strategy call each — `-g ..2` is everything through goal 2 (DESIGN_cli_selectors.md §9) |
| `plan`       | `show`       | `pl s`   | Show a periodization plan: the strategy's `summary` and the mesocycle timeline with each mesocycle's `summary`. `-v` prints the full `strategy` and `focus`, the feedback notes and the snapshotted inputs, and flags inputs that changed since the plan was built, with both routes out, `plan generate` or `plan keep` (DESIGN_plan_staleness.md §9). `-vv` adds the retrospective records under the text they look back on (DESIGN_cycle_retrospective.md §8). `-g/--goal ID` (any status), `-M/--macrocycle ID` (a superseded version: each plan version is a macrocycle), `-a/--all`, `-w/--workouts` |
| `plan`       | `retrospective` | —     | A goal's retrospective records in the layout of `plan show` and nothing else: the plan's record in place of the strategy, each mesocycle's in place of its focus, with the record ID that `plan retro redo` takes (`cli/plans/retro.py`, DESIGN_cycle_retrospective.md §8). `-g/--goal ID` (any status). Read-only, no model call |
| `plan`       | `retro`      | —        | `plan retro redo ID`: one retrospective record written again, the athlete's words kept; `--words TEXT` replaces them first, `--clear-words` drops them, `--show-llm-prompt-only` prints the writer's prompt (`cli/plans/retro.py`, DESIGN_cycle_retrospective.md §9) |
| `plan`       | `keep`       | —        | Record the current profile/goals/thresholds against the active plan **without** regenerating it (`-g/--goal ID`), clearing the changed-input flag `plan show` raises. The dismiss half of staleness: same write as declining at the `plan generate` prompt, reachable without spending a strategy call (DESIGN_plan_staleness.md §9) |
| `plan`       | `versions`   | `pl v`   | List a goal's kept plan versions — active + superseded — with IDs and dates (`-g/--goal ID`) |
| `plan`       | `diff`       | `pl df`  | Compare two plan versions (`[PLAN_ID_A] [PLAN_ID_B]`, `-g/--goal ID`): strategy prose, each version's attached feedback notes, mesocycles added/removed/renamed/re-dated, and snapshotted input deltas. No ID → previous vs active; one ID → that vs active. Prose rewritten wholesale collapses to a note unless `--full`. Comparison logic in `stamind/plan_versions.py`, shared with `/api/plan/diff` |
| `plan`       | `rollback`   | `pl rb`  | Restore a superseded plan version + its workouts (`-g/--goal ID`, `-M/--macrocycle ID`, `-y`); defaults to the chronologically previous version. The inverse of eager generation (DESIGN_plan_rollback.md) |
| `plan`       | `rm`         | `pl rm`  | Delete plan for a goal ID, with the goal's retrospective records, which the inventory it prints before asking counts. The old `pl d` alias is gone — `d` now prefixes `diff` |
| `plan`       | `feedback`   | `pl f`   | Append a note about the plan to its append-only log — bare text is plan-level, `-m [ATOM]` files it to one mesocycle of any upcoming goal's plan by name-infix / date / mesocycle ID (bare `-m` = the current mesocycle), and that mesocycle picks the plan. Bare run lists what is pending, `--rm ID [-y]` deletes one, `--replan` regenerates straight away (the same as `plan generate --feedback` for a plan-level note), `-g/--goal ID` targets another goal's plan (and confines `-m` to it). No LLM at capture; the next `plan generate` reads the whole log and must address every note (DESIGN_plan_feedback.md) |
| `plan`       | `wipe`       | —        | Delete all plans, and every retrospective record with them               |
| `progress`   | `[SPORT ...]` | `pr`    | Show the progress timeline: measured load to date, plan-projected forward (CTL/ATL/TSB), weekly planned-vs-actual bars with the hours planned and done each week (`-w/--weeks N`, `--chart [PATH]` for a PNG, `--explain` for the TSB-lag note; DESIGN_progress_timeline.md). `-z`/`--zones` (implied by naming a sport) adds one weekly time-in-zone table per sport — measured behind today, prescribed ahead of it (`--mesocycles` for mesocycle grain, `--power`/`--hr` to force the currency; DESIGN_intensity_distribution.md §9.6/§9.8). The sport argument scopes the **zone tables only**: CTL/ATL/TSB, the projection and the load table stay whole-athlete |
| `workout`    | `list`       | `w l`    | Show planned workouts, a 7-day window from today by default. Positional `TARGET…` (workout IDs and/or date selectors) plus `-d`/`-m`/`-M`/`-g`, `-t/--type TYPE` and `-l/--link` (DESIGN_cli_selectors.md). A session dated today or earlier carries its adherence verdict (`[DONE]`, `[PARTIAL]`, `[MISSED]`, `[REST OK]`, `[REST BROKEN]`, or `[NOT YET]` for one still ahead today), and the listing freshens Garmin over that past span unless `--no-pull` ([§5](#workout-state--three-orthogonal-axes-not-one-enum)). `-v` adds each session's short form (`cli/workouts/session_line.py::prescription_lines`), `-vv` the full detail. A listing that runs past the last scheduled session ends on a marker saying so (DESIGN_runway_nudge.md §4). |
| `workout`    | `show`       | `w sh`   | `workout list -vv` under a name that says what it does: the same handler with the detail flag pinned on, the same positional targets and the same selectors. `wo sh 12` details one session. The one difference is the default window: a bare `wo sh` details today's sessions, where a bare `wo li` lists seven days. `-H/--history [N]` prints the session's earlier forms under it, newest first, capped at N (`gcal/history.py::depth_section`). |
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

Flask server at `stamind_web.py`, runs on port 5000. Static files served from
`static/`.

**The dashboard is read-only.** It reads the database and renders it: it never writes a
row, never calls Garmin, never calls the LLM, and never touches Google Calendar. Every
one of those is a CLI (or bot) action. The rule is enforced, not merely documented — a
`before_request` guard 405s every mutating verb, and `tests/test_web.py::TestReadOnly`
fails if any route is registered with one.

It is also the one surface that opens **no journal run**: a read-only GET neither changes
anything nor costs anything, so there is nothing to bracket, and keeping the run stack out
of Flask's threaded request handling is the second reason. Only failures are recorded — an
`internal` record with no run id, written by an `errorhandler` that re-raises so Flask
still renders the response it would have (DESIGN_logging.md §13).

That is a deliberate demotion from the previous contract ("the API tracks the CLI feature
set"), which decayed silently: parity was achieved once, in June 2026, and every feature
added CLI-first afterwards — daily-signal authoring, the benchmark logbook, model
selection — was simply missing from the web with nothing to signal it. A surface that
only reads has no parity to lose. New CLI commands add a *view* here when their data is
worth looking at, and cost nothing when it is not.

Consequences worth having: no request can leave the database in a state the CLI did not
put it in, so the app is safe to leave running and cannot race the CLI or the bot over a
workout row; and it needs neither the Calendar service-account credentials nor an LLM key
to start, because it imports neither `stamind.gcal` nor `coach_service`. The one thing
it did need from the coaching engine — the plan-shaping config fingerprint behind the
"config changed" banner — is `plan_inputs.plan_config_hash()`, a flat pure module the
coach reads too, so the two cannot drift. It used to be reached through a forwarding
wrapper on the engine; that wrapper is gone and both callers name the function.

The **front-end** is `static/index.html` plus six scripts, cut along the tabs:

- `common.js` — the API base, the date and sport formatting, the console log, the tab
  switch. Everything more than one of the others reads, plus `todayStr`, which only
  `workouts.js` calls but belongs beside `parseLocalDate`, `fmtDate` and `fmtSpan`.
- `dashboard.js` — the Dashboard tab's own panels: today's recovery and load numbers, the
  sync freshness line, the coach-memory summary, the goal and constraint listings, the
  active model.
- `plan.js` — the strategy card, the mesocycle timeline, the feedback notes and the
  version comparison. Drawn inside the Dashboard tab, which is why `fetchStatus` in
  `dashboard.js` calls into it, but about the periodization rather than about today.
- `workouts.js` — the Workouts tab.
- `progress.js` — the Progress tab.
- `records.js` — Benchmarks, Learnings and History, the three tabs that read the record
  back. None of them fills a file on its own.

There is no module system and no bundler: `index.html` lists them as six plain `<script>`
tags and they share one global scope, so a name defined in one is visible to all. Two
rules follow, and a new panel has to keep both.

- **`common.js` loads first.** It declares `API_BASE`, `activeGoalId` and `loadedTabs`
  with `const`/`let`. Those live in the global lexical scope rather than on `window`, so a
  script that ran before `common.js` and read one would raise a `ReferenceError` — not
  read `undefined` and carry on.
- **A script may only reach another script's name from inside a function.** Function
  bodies run after every tag has loaded, so any of them may call any other. Code at the
  top of a file runs the moment that file loads, so it may only name what its own file or
  an earlier one has already defined. Today no file breaks this: each registers its own
  buttons, and the two that have start-up work to do — `dashboard.js` and
  `workouts.js` — each register their own `DOMContentLoaded` block rather than sharing
  one. So the six are independent of each other's order beyond `common.js` going first.

The six **top-level tabs** are all lazy-loaded on first show:

- **Dashboard** — status, recovery/load metrics, sync freshness, coach-memory summary,
  objective and constraint listings, the active LLM (`settings list thinking-model`), and the
  strategy card
  (philosophy, the goals/constraints snapshot the plan was generated from, the pending
  feedback log, the mesocycle timeline — a mesocycle's own notes appear in its details panel
  — and a "Plan versions & compare" disclosure whose
  superseded entries render `/api/plan/diff` into `#plan-diff-panel`).
- **Workouts** — date/sport/removed-filtered list with the derived state markers, the
  compare/adherence view, and the archived-batch listing.
- **Progress** — an `<img>` framing the server-rendered `/api/timeline.png` chart with
  `8w`/`26w`/`all` quick ranges (DESIGN_progress_timeline.md §7.3/§8.5), plus the **time
  in zone** tables: the web form of `sm progress -z`, one table per qualifying sport,
  measured behind today and prescribed ahead of it, each week also drawn as a stacked
  proportion bar (DESIGN_intensity_distribution.md §9.6/§9.8).
- **Benchmarks** — the current effective threshold set and the logbook, newest first,
  each row carrying its direction-aware delta against the previous row of the same kind
  (DESIGN_benchmark_workouts.md §3.2/§6).
- **Learnings** — filterable list with per-week evidence.
- **History** — activities and recovery-metric tables, and the **daily-signal**
  visualisation: the metric vocabulary (`signal list-metrics`) as chips, then one
  calendar strip per metric shaded within that metric's own range, over the raw rows.

Panels that used to carry a button now name the command that does the job
(`sm plan generate`, `sm workout tweak`, `sm learnings demote`, …), including the
long-standing CLI-only flows `data pull`/`bootstrap`/`reflect` (interactive / MFA-bound,
DESIGN_garmin_direct_pull.md §11). Sport filter dropdowns are built from the sports
actually present in the data rather than a hardcoded `<option>` list — the old list had
itself fallen behind the canonical sports.

Endpoints delegate rather than re-derive, so the two surfaces cannot disagree:
`GET /api/workouts` annotates rows with `calendar_status` + `modification_status` and,
for a row today or earlier, the `adherence` verdict `workout list` marks (§5),
`/api/workouts/compare` reuses `analyze_adherence`, `/api/plan/diff` returns
`plan_versions.diff_plans` verbatim, and `/api/zones` picks its sports and currencies with
`intensity.window_sport_stats`/`select_zone_sports`/`zone_currency` — the same three
functions the CLI tables call, which moved from the progress tables into `analytics/intensity.py` for
exactly that reason.

| Method | Path                            | Description                                  |
|--------|---------------------------------|----------------------------------------------|
| GET    | `/api/status`                   | Active goal, latest metrics, coach learnings (under `coach_learnings.learnings` + `.summary`), macrocycle+mesocycles, `config_mismatch`, `sync_state` (data freshness) |
| GET    | `/api/objectives`               | All objectives (`goal list`)                 |
| GET    | `/api/constraints`              | Active + upcoming constraints — the read view of `constraint list`. Its window is a rolling `metrics_lookback_days` plus everything upcoming, **not** the CLI's active-mesocycle anchor |
| GET    | `/api/workouts`                 | List workouts (`?start_date=&end_date=&sport_type=&include_removed=`). Rows carry derived `calendar_status` + `modification_status`, plus `adherence` (`{status, label, reasons, completed}`, null for a row still ahead of us) from `analytics/compare.py::adherence_verdicts` — the same grader the CLI asks, and not through the CLI, which §14's layering rule forbids. No pull — §8. |
| GET    | `/api/workouts/compare`         | Plan-vs-actual adherence (`workout compare`); no `ensure_data`. `?start_date=&end_date=&sport=` (default 14-day lookback, end capped at today) → `{filters, days[], discrepancies[], informational[]}` |
| GET    | `/api/workouts/batches`         | Workout changes, newest first (`{batches:[{id, created_at, kind, summary, workouts, held, restorable, first_date, last_date, macrocycle_ids}]}`); undoing one is `workout rollback` |
| GET    | `/api/plan`                     | Active plan for a goal (`plan show`): `?goal_id=` (default next active) → `{goal, macrocycle, mesocycles}` |
| GET    | `/api/plan/versions`            | Plan versions for a goal (`?goal_id=`; active + superseded) |
| GET    | `/api/plan/diff`                | Compare two plan versions (`?goal_id=&from_version=&to_version=`; defaults to previous vs active) → `{goal, diff}`, the same `plan_versions.diff_plans` structure the CLI renders. `{error, code}` + 400/404 when the pair cannot be formed |
| GET    | `/api/zones`                    | Per-sport, per-zone time in zone (`progress -z`). `?weeks=N\|all` (default 8), `?sport=` (repeatable, overrides the volume filter), `?currency=hr\|power` → `{window, sports[{sport, currency, zone_labels, coverage, weeks[]}], omitted}`. Weeks past today carry the *prescribed* zones (`future: true`); a future week planned in the other currency reports `currency_mismatch` rather than converting (§9.8) |
| GET    | `/api/benchmarks`               | Benchmark logbook newest first + current thresholds (`benchmark list`). `?sport=&kind=`; each row carries `formatted`, a direction-aware `delta` vs the previous row of its kind, and `improvement` |
| GET    | `/api/learnings`                | List coach learnings (`?sport=&confidence=&dormant=`) + `summary` |
| GET    | `/api/learnings/<id>/evidence`  | Per-week evidence basis (supporting/contra)  |
| GET    | `/api/timeline.png`             | Progress timeline as a PNG image (same §7.2 renderer as the bot photo): merged past/planned load + projected CTL/ATL/TSB. `?weeks=N` (default 8, ≥1 else 400; `all` = full history) re-windows the past half. Not cached. matplotlib absent → 503 with install hint |
| GET    | `/api/activities`               | Completed activities (`?start_date=&end_date=`) |
| GET    | `/api/daily-signals`            | Daily-signals (`signal list`; `?start_date=&end_date=&metric=`) |
| GET    | `/api/daily-signals/metrics`    | Distinct signal metrics with counts + first/last date (`signal list-metrics`) |
| GET    | `/api/metrics`                  | Cached metrics (range, else last 30 days)    |
| GET    | `/api/models`                   | Configured LLM menu with the active entry marked (`settings list thinking-model`) → `{models, active, source, set_at}` |

Every other verb on every path returns **405** `{error, method, path}`.

Writes live in the CLI: `goal`/`constraint`/`signal`/`benchmark` authoring,
`plan generate`/`rollback`/`feedback`, `workout adapt`/`tweak`/`generate`/`push`/
`rollback`, `learnings edit`/`demote`/`keep`/`rm`, `settings set`, and
`data pull`/`bootstrap`/`reflect`.

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
| `telegram.push.*`      | —    | Morning push: `enabled` (default true), `morning_time` (`08:00`), `morning_deadline` (`15:00`), `evening_time` (`21:00`, from when the bot sends no queued item and no notice on its own), `adapt_first` (default false → ask the week planner before rendering, unless it already ran today with last night's sleep score in hand and nothing has been trained since; a session it would change is saved as a proposal the athlete answers with a tap, DESIGN_waiting_proposal.md §5) |
| `telegram.bot_token` / `telegram.allowed_chat_ids` | — | The bot's token (or the `TELEGRAM_BOT_TOKEN` env var) and the numeric chat-id allowlist that gates every chat |
| `telegram.command_timeout_seconds` / `telegram.prompt_timeout_seconds` | — | The silent-run watchdog (180) and the idle-prompt cancel (300) |
| `telegram.send_retry_seconds` | float | How long a call Telegram failed to answer is tried again before the bot gives up and journals one warning (default 180; 0 = off). The poll is not affected. DESIGN_telegram_send_retry.md §3 |
| `telegram.change_delay_minutes` | int | How long a change to one of today's sessions waits before the athlete is told, measured from the newest waiting change so a second run restarts it (default: 20; 0 sends on the bot's next wake). Also a setting (`settings set change-delay N`). DESIGN_change_heads_up.md §4 |
| `telegram.confirmation_days` | int | On how many mornings after the day it was asked a question about what the athlete just wrote, such as "Shall I pass it to your coach?", is sent again after the morning message; on the next one it closes (default: 3). Also a setting (`settings set confirmation-days N`). DESIGN_chat_questions.md §2 |
| `web.host` / `web.port` / `web.debug` | — | Where the dashboard binds (`127.0.0.1` / 5000 / false) |
| `coach.metrics_lookback_days` | int | Rolling window for adaptation (default: 15)                  |
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
   what apply will write. The CLI prints them through the same `workout_line` and
   `prescription_lines` as `workout list`, then asks.
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
   the chat, DESIGN_session_notes.md §3).
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
   span; DESIGN_mesocycle_boundary.md §1, §7) or targeting a completed session is dropped.
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
the record is created, and an answer runs the writer at once. The record of a plan covers
its mesocycle records (§6). `plan generate`'s prompt is the only reader (§7); `plan show
-vv` and `plan retrospective` show the records (§8), and `plan retro redo` is §9.

---

## 11. Terminology: Plans vs. Workouts

- **Plan** = periodization strategy: one *active* macrocycle (per objective, with
  superseded versions kept) + its mesocycles.  Commands:
  `plan generate/show/keep/versions/diff/rm/rollback/feedback`. `plan versions` lists every
  kept version; `plan show --macrocycle <id>` renders a specific (e.g. superseded) one,
  `--all` every goal's, `--workouts` each mesocycle's sessions; `plan diff` compares two
  versions.
- **Workouts** = the planned sessions of each microcycle, implementing the mesocycle focus.
  Commands: `workout generate/adapt/tweak/push/rollback/batches`. `workout generate`
  lists what it proposes and, on a `y`, pushes it to Calendar eagerly; `workout rollback`
  undoes one change and everything after it (`workout batches` lists them), and
  `plan rollback` does the same while also stepping the strategy back
  (DESIGN_plan_rollback.md, DESIGN_workout_revisions.md §10).

Every session is written by the coach. An athlete who has decided a change asks for it
with `workout tweak` ([§10](#a-change-on-request-workout-tweak)). A session changed on request
carries the request in its `modification_reason` ("On request: …"), which the next
`workout adapt` reads beside the session and leaves alone unless the metrics call for a
change.

Plan must be generated before workouts. Workouts cover the span the selector flags on
`workout generate` name, both ends of it — by default from the day after the schedule
stops, onward for `workout_generation_span_days` (in `config.yaml`, falling back to 28
days).
`replan()` calls `plan_generate` then `workout_generate` + `workout_generate_apply` in one
step (always uses the config default, and applies without a preview — it is the
unattended path).

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

### Workload per activity
`Workload = activity_load(act)` — the single fallback value above.

### ATL:CTL load ratio
Relative overload — fatigue against the athlete's own fitness base.
`analytics.pmc.load_ratio(atl, ctl)` = ATL ÷ CTL straight off the PMC EWMAs below, derived
at **read time** and never stored; `None` when either is NULL or CTL ≤ 0 (no base to
divide by). Colouring (`analytics.pmc.color_load_ratio`) is **overload-only**: > 1.5 red,
1.3–1.5 yellow, at or below 1.3 bare — a *low* ratio is phase-dependent, and
`training_load.md` §4 judges the ratio against the planned mesocycle rather than a universal
band. This replaced the rolling-sum acute/chronic/ACWR model (7/28-day sums with the
0.8–1.3 "sweet spot"), whose stored columns are dropped by guarded DDL in `db/schema.py`
and whose universal band fought block periodization. See DESIGN_load_ratio.md.

### Fitness/Fatigue/Form (PMC) model
Two layers, one recurrence. The EWMAs are the whole stored load model, and the ATL:CTL
ratio above is derived *from* them — different questions off one series: asymptotic
fitness/form (CTL/ATL/TSB) and scale-invariant relative overload (the ratio).

**Backward core** (`analytics/pmc.py` for the maths, `garmin/derived.py` for the sweep that stores it, DESIGN_pmc_fitness_fatigue.md): the classic
Coggan discrete `1/τ` EWMAs walked over every calendar day of history —
`compute_pmc()`, with TSB = *yesterday's* CTL − ATL (day-entering form) —
stored per day on `athlete_metrics_cache` (`ctl`/`atl`/`tsb`) by every
`recompute_derived()` sweep. Time constants come from config
(`pmc_ctl_days`/`pmc_atl_days`, default 42/7; the defaults are the supported
configuration). Leading-edge warm-up blanking (`pmc_warmup_cutoff_for`),
the young-DB caveat (`pmc_data_caveat`), and the ramp rate (`pmc_ramp`)
gate/derive display values. Consumers: coach prompts, `sm status` and
`sm data show-metrics` — the last two render the triple through the shared
`analytics.pmc.pmc_cells`, and derive the one warm-up cutoff through
`garmin/derived.py:warmup_cutoff(dbh, history_start=None)`. (`workout adapt` prints only a one-line day count;
its metrics-trajectory table was removed.)

**Projection layer** (`stamind/analytics/progression.py` and `analytics/timeline.py`, DESIGN_progress_timeline.md):
this is PMC Phase 2, generalized to the full daily series. Past days read the
stored series verbatim (never recomputed — `sm progress` and `sm status` must
agree); the *anchor* is the latest stored row **strictly before today** with
non-NULL PMC, and from it the same recurrence is folded forward
(`compute_pmc(..., seed=(ctl, atl))`) over the merged actual-then-planned daily
load series (past: `activity_load` above; future: `analytics.load.planned_load` over
non-removed `workouts` — see DESIGN_progress_timeline.md §3 for the seam rule),
stopping at the last generated workout. `compute_pmc` stores its outputs at
**full precision** (rounding moved to display) so the fold reproduces the stored
series bit-exactly. `assemble_timeline` builds the whole payload; `timeline.
build_timeline_payload` is the one row-fetching path behind both surfaces.
Consumers: `sm progress` (CLI, numbers-first + optional `--chart` PNG), the
Telegram bot (text for free via CLI parity, plus the photo transport for the
chart), and `GET /api/timeline.png` (the web **Progress** tab, framing the same
`chart.render_timeline_png` PNG). One computation and one chart renderer feed
all three; only the delivery differs.

### Daily Readiness Signals
- HRV drops > 1 std below baseline mean → flag potential overtraining
- RHR rises > 1 std above baseline mean (min +3 bpm) → flag potential
  overtraining
- `workout adapt` acts on these signals over the rolling
  `metrics_lookback_days` window, but first discounts a depressed morning that a
  logged `daily_signals` signal the day before explains (lifestyle noise, not training
  fatigue): today's session may still be eased or rescheduled for acute readiness, but
  the mesocycle's planned load is not cut on a non-training artifact.

### Science Guidelines Files
- `stamind/science/` — built-in: `benchmarks.md`, `periodization.md`,
  `recovery_metrics.md`, `training_load.md`, `zones.md`
- `science/` (`science_dir`, gitignored) — user-provided; empty by default; any `.md`
  files added here are injected into every LLM prompt, and snapshotted on the macrocycle
  so an edit flags the plan stale (`DESIGN_plan_staleness.md` §11). `science.samples/`
  holds ready-made sets to copy from, one directory per training philosophy (see README).
- The two are layered — built-in owns measurement and vocabulary, user owns
  prescription, and the citation only runs one way. Contract in
  [§3](#_load_science_guidelinesapp_science_dir-science_dir--str).

---

## 13. Daily Signals (Calendar Ingest)

External daily signals the coach should factor in — alcohol, sleep quality,
stress, big meals, a heatwave — reach Stamind through the **single existing
Google Calendar**, not through app-specific features. Producers write one all-day
event per signal-day, tagged in `extendedProperties.private`:
`source=stamind-context` (the positive marker, configurable via
`calendar_signal_tag`), `metric` (opaque category), and an optional numeric
`value`. Two producers exist: a separate syncer (out of scope, mirroring
`GarminScraper`) for spreadsheet-backed streams, and Stamind's own `signal`
command (outbound, below) for ad-hoc signals. Full specs:
`DESIGN_calendar_signal_ingest.md` (ingest) and `DESIGN_signal_authoring.md`
(authoring).

**Inbound flow:**

```
Calendar (tagged events) ──► gcal.client.sync_calendar_signals
   ──► calendar_syncer.sync_signals (syncToken; server-side filtered on the full
                                     pull only, client-side otherwise)
   ──► db.upsert/delete_daily_signal_by_event ──► daily_signals table
   ──► coach analysis weekly summaries (per-week `daily_signals`)
```

- **Distinguishing events:** Stamind writes workouts tagged `source=stamind` and
  ingests only events tagged `source=stamind-context` (or the configured
  `calendar_signal_tag`). The server-side `privateExtendedProperty` filter applies to
  the **full pull only** — the API forbids it alongside a `syncToken` — so the
  incremental stream carries every changed event and is filtered **client-side** before
  anything is parsed. The guarantee is "untagged events are never *ingested*", not
  "never fetched".
- **Sync, not append:** incremental via Calendar `syncToken` — edits upsert by
  `google_event_id`, cancellations delete. A cancelled event arrives stripped of its
  extended properties, so the tag guard cannot run on it: `_ingest_signal_event` counts
  it as a change only when `delete_daily_signal_by_event` actually removed a row —
  otherwise cancelled workouts and cancelled private appointments would inflate the
  reported count on the unfiltered incremental path. First run / expired token (HTTP 410)
  falls back to a full pull of all tagged events (no date horizon needed; the
  list is bulk and sparse). Token persisted in `sync_state[calendar_signals]`.
- **Cadence:** rides along `data pull` (force) and the auto-ensure-before-read
  path (`garmin.ensure_data` → bridge `_sync_calendar_signals`, throttled to the
  Garmin refresh window and memoized once per process). Best-effort: a missing
  calendar config or any Calendar error is swallowed with a warning. The gating
  and error handling live in `gcal/client.py::sync_calendar_signals`; `garmin/sync.py`
  only bridges to it via a guarded lazy import.
- **Coach use:** two complementary paths. (1) *Qualitative* — each week's summary
  carries a `daily_signals` list (all rows, no collapsing) the LLM reads beside the
  metrics, the same way `constraints` contextualize anomalies. (2) *Quantitative*
  (`signal_days`, step 3a above; DESIGN_quantitative_signal_impact.md) — the
  optional numeric `value` is aligned per-episode against the bracketing mornings'
  recovery and day-of load, full-history, so the LLM can read dose-response,
  persistence, and the drink-and-hard-day confound. Both are hashed into the analysis
  evidence fingerprint, so an added/edited/deleted signal invalidates the cached
  reconstruction **unconditionally** — in-window rows are hashed as fields, and rows
  outside the window reach the hash through the full-history `signal_days` section, which
  is hashed as computed (§10, step 2/3a). Because that section is hashed as computed,
  `signal_days_lookahead` and `signal_days_min_days` are fingerprinted
  transitively: editing either invalidates the cached reconstruction. That is a
  deliberate, narrow exception to config values not being hashed here — a different knob
  produces a different prompt, so the cached answer is not an answer to the current
  question (DESIGN_quantitative_signal_impact.md §8).

**Outbound flow (first-party authoring — the `signal` command):** for
ad-hoc signals where standing up a syncer is overkill (a heatwave), the user can
author the same tagged events directly, since the private-property tag is
unsettable from the Calendar UI. `signal add` writes one tagged all-day event
per day in a range (`add_signal_event`, idempotent upsert-by-(date, metric)) and
mirrors the rows locally via `upsert_daily_signal_by_event` so they appear before
the next pull. `signal rm` deletes the **calendar event** (`delete_event`) before
the local row, so a full re-pull (`data wipe --calendar`) can't resurrect it.
`signal list` (default window: `metrics_lookback_days`, the coach's metrics-lookback
window) and `signal list-metrics` inspect what's recorded. Authored events are
indistinguishable from synced ones downstream — `sync_signals`, the analysis
prompt, and the evidence fingerprint are untouched. Handlers: `cli/signals.py`;
spec: `DESIGN_signal_authoring.md`.

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
compete with. `_clean_goals` includes the field only when it is `horizon`: an event
goal — every goal predating the field — hashes exactly as before, so shipping the
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
`plan.html` and their `*_logic.js` under node tests, with `storage.js` the bucket read
both share. `page_files/sync.py` adds the bucket parameters to both buttons and uploads
the files that changed after every command (`after_command`, from `run_once`). On the
bot's side, `ChatBot._page_buttons` builds both addresses on every send,
`RepliesMixin._send_keyed` is the one send that attaches the keyboard, and
`on_web_app_data` turns a `calendar_day` message into `workout list -d <date>` and a
`plan_why` one into `plan show --macrocycle <id>`; any other page message is a gym log
([§16](#16-gym-logger-telegram-mini-app)).
