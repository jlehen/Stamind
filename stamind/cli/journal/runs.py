"""Reading the run journal back: which runs are on disk, and which of them were asked for.

`stamind/journal.py` owns what a record is and how it is written; this file turns the
records of one window into a `RunSummary` per run and applies the flags that narrow the
listing (DESIGN_logging.md §7). It prints nothing — `views.py` does that.

Every stamp in the files is UTC (§4), so every date question here goes through the
athlete's zone first: "what happened on Tuesday" is answered in local terms.
"""
import argparse
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from stamind import journal
from stamind.cli.windows import resolve_window
from stamind.clock import to_local


# The read-only views the listing leaves out until `-a` asks for them (§7.1). Keyed on the
# verb — the last word of the canonical command path — so one entry covers every group's
# `list`, and a `show` added under a new group tomorrow is covered the day it lands.
READ_ONLY_VERBS = frozenset({
    "list", "list-metrics", "show", "show-metrics", "show-activities", "show-analysis",
    "status", "progress", "compare", "batches", "versions", "diff", "journal", "help",
    "shell",
    # A bare `settings` is `settings list`: the one group that acts, read-only, when it is
    # given no sub-command (DESIGN_cli_noargs.md §a3).
    "settings",
})

# An argv carrying one of these printed help and did nothing else.
HELP_FLAGS = ("-h", "--help", "--helpall")


@dataclass
class RunSummary:
    """One run as the listing sees it: the two bracket records and nothing else (§7)."""
    id: str
    started: str = ""
    source: str = "?"
    command: str = ""                   # the line as it was typed, prefixes and all
    path: str = ""                      # the canonical command that line resolved to
    argv: List[str] = field(default_factory=list)
    parent: Optional[str] = None
    pid: Optional[int] = None
    config: Optional[str] = None
    db: Optional[str] = None
    outcome: Optional[str] = None       # None = no run.end: still going, or killed
    exit_code: Optional[int] = None
    ms: Optional[int] = None
    llm_calls: int = 0
    tokens: int = 0
    warns: int = 0
    errors: int = 0
    warning: str = ""                   # the first one it logged, verbatim (§7.3)
    error: Optional[str] = None
    traceback: Optional[str] = None


# --- reading ---------------------------------------------------------------------

def local_time(ts: Any) -> Optional[datetime]:
    """A record's UTC stamp as an instant in the athlete's zone."""
    try:
        return to_local(datetime.fromisoformat(str(ts)))
    except (TypeError, ValueError):
        return None


def _command_of(argv: List[str]) -> str:
    """The command a run is, without its arguments: the leading two bare words.

    `plan generate -g 2` is `plan generate`; `status` is `status`. Only a fallback now:
    what was typed may be any unambiguous prefix, so `wo a` reads as `wo a` here and not
    as `workout adapt` — `command_path` prefers the canonical name the record carries (§7.1)."""
    words = []
    for token in argv:
        if token.startswith("-") or len(words) == 2:
            break
        words.append(token)
    return " ".join(words)


def command_path(run: "RunSummary") -> str:
    """The canonical command the run turned out to be, falling back to the words it was
    typed as for a run that was killed before its parse — or that predates `cmd` (§7.1)."""
    return run.path or _command_of(run.argv)


def collect(start_day: Optional[date], end_day: Optional[date]) -> Dict[str, RunSummary]:
    """Every run in the window, keyed by id, from its two bracket records — plus the
    first warning each one logged, which is what its END column is reporting (§7.3)."""
    runs: Dict[str, RunSummary] = {}
    first_warning: Dict[str, str] = {}
    for rec in journal.iter_records(start_day, end_day):
        ev = rec.get("ev")
        run_id = str(rec.get("run") or journal.NO_RUN)
        if ev not in ("run.start", "run.end"):
            if rec.get("lvl") in ("warn", "error"):
                first_warning.setdefault(run_id, str(rec.get("msg") or ""))
            continue
        summary = runs.setdefault(run_id, RunSummary(id=run_id))
        d = rec.get("d") or {}
        if ev == "run.start":
            summary.started = str(rec.get("ts") or "")
            summary.source = str(d.get("source") or "?")
            summary.argv = list(d.get("argv") or [])
            summary.command = str(rec.get("msg") or "")
            summary.parent = d.get("parent")
            summary.pid = d.get("pid")
            summary.config = d.get("config")
            summary.db = d.get("db")
            continue
        summary.outcome = str(d.get("outcome") or "ok")
        summary.path = str(d.get("cmd") or "")
        summary.exit_code = d.get("exit")
        summary.ms = d.get("ms")
        summary.llm_calls = int(d.get("llm_calls") or 0)
        summary.tokens = int(d.get("tokens") or 0)
        summary.warns = int(d.get("warns") or 0)
        summary.errors = int(d.get("errors") or 0)
        summary.error = d.get("error")
        summary.traceback = d.get("traceback")
    # After the pass: a run split across two day files can log a warning before its bracket.
    for run_id, summary in runs.items():
        summary.warning = first_warning.get(run_id, "")
    return runs


def date_window(args: argparse.Namespace) -> tuple:
    """The local date window `-d` asked for, or (None, None) for everything on disk.

    The same `-d start..end` grammar every other range command speaks
    (DESIGN_cli_selectors.md §3), rather than the `--since`/`--until` pair that retired
    with it — one vocabulary, so `-d 7d` reads here exactly as it does in `data pull`."""
    start, end = resolve_window(args)
    return _as_date(start), _as_date(end)


def _as_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    return date.fromisoformat(str(value).strip())


def select_runs(args: argparse.Namespace) -> Tuple[List[RunSummary], int]:
    """The runs the flags ask for, newest first, and how many views were left out."""
    since, until = date_window(args)
    # This very run is excluded: it has no `run.end` yet, so it would head every
    # listing as a `?` and turn up under --failed as the command you just typed.
    mine = journal.current_id()
    runs = [r for r in collect(since, until).values() if r.started and r.id != mine]
    if since or until:
        runs = [r for r in runs if in_window(r, since, until)]
    source = getattr(args, "source", None)
    if source:
        runs = [r for r in runs if r.source == source]
    wanted = getattr(args, "command_filter", None)
    if wanted:
        runs = [r for r in runs if _matches_command(r, wanted)]
    if getattr(args, "failed", False):
        runs = [r for r in runs if _is_trouble(r)]
    hidden = 0
    # Naming a command is asking for it, views included; otherwise this listing is about
    # what the app did, and a run that only printed did nothing (§7.1).
    if not getattr(args, "show_all", False) and not wanted:
        kept = [r for r in runs if not _is_view(r)]
        hidden = len(runs) - len(kept)
        runs = kept
    runs.sort(key=lambda r: r.started, reverse=True)
    return runs, hidden


def _matches_command(run: RunSummary, wanted: str) -> bool:
    """What `--command "workout adapt"` matches: the canonical name first, so a run typed
    `wo a` answers to it too, and the typed line for records that predate `cmd` (§7.1)."""
    wanted = wanted.strip().lower()
    return command_path(run).startswith(wanted) or run.command.startswith(wanted)


def _is_view(run: RunSummary) -> bool:
    """Whether the run only looked at things: a read-only view, or a help print (§7.1).

    Trouble and model calls are never a view, whatever the command was: an error raised
    inside `workout list` is exactly what this listing exists to put in front of you."""
    if _is_trouble(run) or run.llm_calls:
        return False
    if not run.argv or any(flag in run.argv for flag in HELP_FLAGS):
        return True
    return command_path(run).split(" ")[-1] in READ_ONLY_VERBS


def in_window(run: RunSummary, since: Optional[date], until: Optional[date]) -> bool:
    """Whether the run started inside the athlete's local window."""
    moment = local_time(run.started)
    if moment is None:
        return False
    if since and moment.date() < since:
        return False
    return not (until and moment.date() > until)


def _is_trouble(run: RunSummary) -> bool:
    """What `--failed` means: it failed, it was killed before it could say anything, or
    it finished having written a warning or an error."""
    if run.outcome is None:
        return True
    return run.outcome == "failed" or run.warns > 0 or run.errors > 0


def day_bounds(run: RunSummary) -> tuple:
    """The local day the run started and the one it ended on — a long run has its tail
    in the next day's file (§4)."""
    started = local_time(run.started)
    if started is None:
        return None, None
    ended = started
    if run.ms:
        ended = datetime.fromtimestamp(
            started.timestamp() + run.ms / 1000, tz=started.tzinfo
        )
    return started.date(), ended.date()
