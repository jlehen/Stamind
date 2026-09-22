"""Argparse wiring for the `data` command group.

Each sub-parser binds its handler with set_defaults(func=...), so the flags and the
function that reads them are defined together.
"""
from stamind.cli.selectors import add_selector_args
from stamind.cli.data.analysis import (
    run_data_bootstrap, run_data_reflect, run_data_show_analysis,
)
from stamind.cli.data.cache import run_data_backfill_tss, run_data_pull, run_data_wipe
from stamind.cli.data.show import run_data_show_activities, run_data_show_metrics


def add_data_parser(subparsers, pull_bypass_parser, llm_debug_parser):
    # data command & subparsers
    data_parser = subparsers.add_parser(
        "data",
        help="Manage and sync athlete metrics and activities"
    )
    data_subparsers = data_parser.add_subparsers(
        dest="subcommand", help="Data sub-commands"
    )
    
    # data pull
    d_pull = data_subparsers.add_parser(
        "pull",
        help="Fetch Garmin activities/metrics and Google Calendar signals",
        description=(
            "Fetch activities and daily metrics directly from Garmin Connect into the "
            "local cache, advancing the sync watermark. With no range, pulls the last "
            "2 days ending today (-d 7d for a different window, or -d A..B for an "
            "explicit range). Pulls both metrics and activities unless "
            "--metrics-only/--activities-only is given. Also syncs tagged daily-signal "
            "events (alcohol, sleep, stress, …) from Google Calendar into the local cache. "
            "Past Calendar events in the pulled range are stamped with the adherence "
            "verdict unless --no-mark is given."
        )
    )
    d_pull.set_defaults(func=run_data_pull)
    add_selector_args(d_pull, direction="backward", default="2d", span_days=2)
    d_pull.add_argument(
        "--no-mark", action="store_true", dest="no_mark",
        help="Skip stamping past Calendar events with the adherence verdict"
    )
    d_pull.add_argument(
        "--sleep", type=float, dest="sleep", metavar="SECONDS",
        help="Throttle: seconds to sleep between Garmin calls (default from config)"
    )
    pull_group = d_pull.add_mutually_exclusive_group()
    pull_group.add_argument(
        "--metrics-only", action="store_true", help="Pull daily metrics only"
    )
    pull_group.add_argument(
        "--activities-only", action="store_true", help="Pull activities only"
    )

    # data bootstrap — cold-start backward reconstruction over the full backlog
    d_boot = data_subparsers.add_parser(
        "bootstrap", aliases=["b"], advanced=True,
        parents=[pull_bypass_parser, llm_debug_parser],
        help="Reconstruct macro/mesocycles from your full backlog (run once): "
             "seeds coach learnings + a cached reconstruction fed to 'plan generate'",
        description=(
            "Cold-start: reverse-engineer past training cycles from completed workouts "
            "and metrics. With no date filter, the window is auto-detected from the active "
            "goal (since the previous goal, else 12 weeks back). Two outputs: (1) coach "
            "learnings, delta-updated from the evidence; and (2) a cached reconstruction — "
            "the inferred macro focus, mesocycles, and physiological insights — which "
            "'plan generate' replays read-only into its strategy prompt so the next plan "
            "builds on your demonstrated training arc. Also establishes the reflect "
            "watermark so later 'data reflect' runs only ingest newer evidence. Cached by "
            "evidence fingerprint: an unchanged re-run reuses the cache unless --force; "
            "--inspect-only renders the analysis without writing learnings or the cache."
        )
    )
    d_boot.set_defaults(func=run_data_bootstrap)
    # data reflect — incremental reflection over evidence since the last reflect
    d_reflect = data_subparsers.add_parser(
        "reflect",
        parents=[pull_bypass_parser, llm_debug_parser],
        help="Update coach learnings from how the athlete responded to training "
             "since the last reflect (incremental; no cycle inference)",
        description=(
            "Incremental: analyze only evidence accrued since the last reflect watermark "
            "(the day after the last reflected-through date), through the last COMPLETED "
            "week — the evidence basis counts whole weeks, so a run with nothing complete "
            "since the watermark reports nothing new and costs no LLM call. Its output is "
            "coach learnings and physiological insights; unlike 'data bootstrap' it does "
            "not reverse-engineer macro/mesocycles, which a few weeks cannot support. A "
            "date filter overrides both the watermark and the completed-week end. Because "
            "overlapping history is never re-counted, repeated runs no longer ratchet "
            "confidence to 'established'. Run 'data bootstrap' first to establish a "
            "baseline. --inspect-only renders without writing; --force bypasses the "
            "per-window cache."
        )
    )
    d_reflect.set_defaults(func=run_data_reflect)
    for d_an in (d_boot, d_reflect):
        # direction="none": an unbounded side stays unbounded, so the service keeps
        # auto-detecting the window it was never told (a bare span still looks back).
        add_selector_args(d_an, direction="none")
        d_an.add_argument(
            "--context", dest="context",
            help="Optional text context detailing subjective athlete notes (travel, illness, etc.)"
        )
        d_an.add_argument(
            "-f", "--force", action="store_true",
            help="Recompute even if the evidence is unchanged (bypass the analysis cache)"
        )
        d_an.add_argument(
            "--inspect-only", action="store_true",
            help="Read-only: show the analysis without writing coach learnings or the cache"
        )
        d_an.add_argument(
            "--auto", action="store_true",
            help="Unattended: ask nothing on the spot, so a repeat bootstrap is skipped. Doubts "
                 "about learnings go to the athlete queue either way."
        )

    # data backfill-tss
    d_btss = data_subparsers.add_parser(
        "backfill-tss", advanced=True,
        help="Recompute TSS for all stored activities using the current "
             "zone-based model (no Garmin calls needed)"
    )
    d_btss.set_defaults(func=run_data_backfill_tss)
    add_selector_args(d_btss, direction="none")
    d_btss.add_argument(
        "-v", "--verbose", action="store_true",
        help="List activities with low HR-zone coverage that need an RPE"
    )

    # data show-metrics
    d_sm = data_subparsers.add_parser(
        "show-metrics", aliases=["sm"],
        parents=[pull_bypass_parser],
        help="Show athlete metrics over a date range",
        description=(
            "Show cached daily athlete metrics (RHR, HRV, sleep, stress) over a date "
            "range. With no date filter, looks back 7 days ending today; -a/--all "
            "shows every cached row. Freshens recent data from Garmin first unless "
            "--no-pull or --all is given. Use --csv for machine-readable output."
        )
    )
    d_sm.set_defaults(func=run_data_show_metrics)
    add_selector_args(d_sm, meso=True, macro=True, goal=True, direction="backward",
                      default="7d")
    d_sm.add_argument(
        "--csv", action="store_true", dest="csv",
        help="Output data as CSV for script consumption"
    )
    d_sm.add_argument(
        "-a", "--all", action="store_true", dest="all",
        help="Show all cached athlete metrics"
    )

    # data show-activities
    d_sa = data_subparsers.add_parser(
        "show-activities", aliases=["sa"],
        parents=[pull_bypass_parser],
        help="Show completed activities over a date range",
        description=(
            "Show cached completed activities over a date range. With no date filter, "
            "looks back 7 days ending today; -a/--all shows every cached activity. "
            "Filter with --type (alias-aware: 'cycling' matches gravel, MTB and indoor "
            "rides too), freshen from Garmin unless --no-pull/--all, and use --csv for "
            "machine-readable output. The TSS column shows the training LOAD with where "
            "it came from — (pwr), (hr), (rpe), (rpe+) when your RPE outvoted a "
            "trustworthy meter, (sparse!) when the recording was too thin to trust and "
            "no RPE was entered."
        )
    )
    d_sa.set_defaults(func=run_data_show_activities)
    add_selector_args(d_sa, meso=True, macro=True, goal=True, sport=True,
                      direction="backward", default="7d")
    d_sa.add_argument(
         "--csv", action="store_true", dest="csv",
         help="Output data as CSV for script consumption (every zone column, both "
              "coverage fractions and the load provenance, unconditionally)"
     )
    d_sa.add_argument(
        "--zones", action="store_true", dest="zones",
        help="Show time in zone per activity instead of the distance/HR/watts columns: "
             "one row per activity and currency, so a ride with both a meter and a "
             "strap gets a [pwr] row and an [HR] row. Includes per-activity zone "
             "coverage — the column that turns 'the strap dropped out somewhere this "
             "week' into a named activity."
    )
    d_sa.add_argument(
        "-a", "--all", action="store_true", dest="all",
        help="Show all cached completed activities"
    )

    # data show-analysis — the stored reconstruction, rendered without recomputing it
    d_san = data_subparsers.add_parser(
        "show-analysis", aliases=["san"],
        help="Show the macro/mesocycle reconstruction stored by the last "
             "'data bootstrap' (read-only: no LLM call, no Garmin pull)",
        description=(
            "Print the reconstruction cached by the last 'data bootstrap': the inferred "
            "macro focus, the mesocycles 'sm progress' draws as '~' bands, and the "
            "physiological insights. Read-only in the strict sense — it renders what is "
            "stored and never calls the LLM, unlike 'data bootstrap --inspect-only' which "
            "recomputes as soon as the evidence has moved. --short shows the last "
            "'data reflect' instead — its recent-response read: summary and physiological "
            "insights, no cycles, because a few weeks cannot support a periodization "
            "claim. Only the latest of each is kept, so this is the current picture, not "
            "a history."
        )
    )
    d_san.set_defaults(func=run_data_show_analysis)
    d_san.add_argument(
        "--short", action="store_true",
        help="Show the short-horizon reconstruction from the last 'data reflect' instead "
             "of the bootstrap one"
    )

    # data wipe
    d_wipe = data_subparsers.add_parser(
        "wipe", advanced=True,
        help="Wipe locally cached Garmin data and/or daily signals from the database",
        description=(
            "Delete locally cached data. With no scope flag, wipes everything (Garmin "
            "metrics, baselines, activities, and ingested daily signals) and "
            "resets the sync watermarks. --garmin or --calendar narrow the scope; -d "
            "restricts it to a date window (the next 'data pull' re-fetches what was "
            "removed)."
        ),
    )
    d_wipe.set_defaults(func=run_data_wipe)
    d_wipe.add_argument(
        "--garmin", action="store_true",
        help="Wipe only Garmin evidence (metrics, baselines, activities, analysis cache)"
    )
    d_wipe.add_argument(
        "--calendar", "--signals", action="store_true", dest="calendar",
        help="Wipe only ingested daily signals and reset the Calendar sync token"
    )
    add_selector_args(d_wipe, direction="none")
    d_wipe.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompt")
    

    return data_parser
