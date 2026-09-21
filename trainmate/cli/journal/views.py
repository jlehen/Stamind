"""What `journal` prints: the listing, one run in full, the cost rollup and the tail.

The runs themselves come from `runs.py`, already read and already filtered; everything
here turns them into columns, glosses and footers that fit the screen
(DESIGN_logging.md §7.2). The `journal` handlers are at the bottom, one per sub-command.
"""
import argparse
import os
import textwrap
import time
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Tuple

from trainmate import journal
from trainmate.text import (
    bold, cyan, dim, display_width, flex_width, gray, green, pad_visible, red, render_table,
    truncate_visible, visible_len, yellow,
)
from trainmate.output import notice
from trainmate.clock import fmt_timestamp
from trainmate.cli.journal.runs import (
    collect, command_path, date_window, day_bounds, in_window, local_time, RunSummary,
    select_runs,
)


# How many runs the listing shows when nothing else is asked for.
DEFAULT_LIMIT = 20

# Seconds between polls while `--follow` tails the file.
FOLLOW_POLL_SECONDS = 0.5

_LEVEL_COLOR = {"warn": yellow, "error": red, "debug": gray}

# What the END column says, the colour it says it in, and what it means. The legend
# glosses the words that are actually on screen, in this order (§7.2).
_END_GLOSS = (
    ("ok", green, "finished"),
    ("warn", yellow, "finished, but logged a warning or an error"),
    ("cancelled", dim, "stopped with Ctrl-C"),
    ("FAILED", red, "raised — 'journal <id>' has the traceback"),
    ("?", yellow, "no end recorded: still running, or killed"),
)
_END_COLOR = {word: color for word, color, _gloss in _END_GLOSS}


def _end_word(run: RunSummary) -> str:
    """The END column: the outcome, plus what the run wrote (§7)."""
    if run.outcome is None:
        return "?"
    if run.outcome == "failed":
        return "FAILED"
    if run.outcome == "cancelled":
        return "cancelled"
    if run.warns or run.errors:
        return "warn"
    return "ok"


def _end_cell(run: RunSummary) -> str:
    word = _end_word(run)
    return _END_COLOR[word](word)


def _time_cell(run: RunSummary) -> str:
    if run.ms is None:
        return "—"
    return f"{run.ms / 1000:.1f}s"


def _llm_cell(run: RunSummary) -> str:
    if not run.llm_calls:
        return "—"
    return f"{run.llm_calls} · {run.tokens / 1000:.0f}k"


def _when_cell(run: RunSummary) -> str:
    return fmt_timestamp(run.started)


_HEADERS = ["RUN", "WHEN", "SRC", "COMMAND", "TIME", "LLM", "END"]

# The command line is the one cell with no upper bound, so it is the one that gives way
# when the table would otherwise run past the screen (§7.2).
_COMMAND_COLUMN = _HEADERS.index("COMMAND")


def _print_listing(
    runs: List[RunSummary], limit: int, hidden: int = 0, verbose: bool = False
) -> None:
    shown = runs[:limit] if limit else runs
    if not shown:
        print("No runs match." if journal.day_paths() else "No runs recorded yet.")
        if hidden:
            print(dim(_omissions(hidden, 0, [])))
        return
    rows = [
        [run.id, _when_cell(run), run.source, run.command,
         _time_cell(run), _llm_cell(run), _end_cell(run)]
        for run in shown
    ]
    room = flex_width(_HEADERS, rows, _COMMAND_COLUMN)
    clipped = not verbose and any(
        visible_len(row[_COMMAND_COLUMN]) > room for row in rows
    )
    print(render_table(_HEADERS, rows, flex=None if verbose else _COMMAND_COLUMN))
    print()
    reasons, reasons_cut = _reasons(shown, verbose)
    for line in reasons:
        print(line)
    if reasons:
        print()
    for line in _legend(shown):
        print(gray(line))
    cut = (["command lines"] if clipped else []) + (["warnings"] if reasons_cut else [])
    for line in _wrap(_omissions(hidden, len(runs) - len(shown), cut)):
        print(dim(line))


def _legend(shown: List[RunSummary]) -> List[str]:
    """The gray footer that says what the two coded columns mean (§7.2).

    Only the outcomes actually on screen are glossed: a legend that explains what is not
    there is a paragraph the eye learns to skip."""
    words = {_end_word(run) for run in shown}
    lines = ["END  " + " · ".join(
        f"{word} = {gloss}" for word, _color, gloss in _END_GLOSS if word in words
    )]
    if any(run.llm_calls for run in shown):
        lines.append("LLM  model calls · tokens")
    return [line for text in lines for line in _wrap(text, indent="     ")]


def _reason(run: RunSummary) -> str:
    """Why a run did not simply finish: the exception that ended it, else the first
    warning it logged (§7.3)."""
    if run.outcome == "failed" and run.error:
        return str(run.error)
    return run.warning


def _reasons(shown: List[RunSummary], verbose: bool) -> Tuple[List[str], bool]:
    """One line per unhappy run, under the table, and whether any was cut to fit (§7.3).

    Clipped with its own newlines collapsed, so that one run is one line; `-v` gives the
    message its shape back, because the multi-line ones are lists."""
    rows = [(run, _reason(run).strip()) for run in shown]
    rows = [(run, why) for run, why in rows if why]
    if not rows:
        return [], False
    word_width = max(len(_end_word(run)) for run, _why in rows)
    id_width = max(len(run.id) for run, _why in rows)
    indent = word_width + id_width + 4
    lines, cut = [], False
    for run, why in rows:
        word = _end_word(run)
        head = (_END_COLOR[word](word) + " " * (word_width - len(word))
                + "  " + run.id.ljust(id_width) + "  ")
        if not verbose:
            flat = " ".join(why.split())
            cut = cut or visible_len(head + flat) > display_width()
            lines.append(truncate_visible(head + flat, display_width()))
            continue
        # Laid out by hand rather than through `_wrap`: the hanging indent has to line up
        # under text that starts after a coloured head, whose escapes textwrap would count.
        body = _reflow(why, display_width() - indent)
        lines.append(head + body[0])
        lines.extend(" " * indent + more for more in body[1:])
    return lines, cut


def _reflow(text: str, width: int) -> List[str]:
    """A logged message wrapped to `width`, each of its own lines kept and its own indent
    with it: these are written to be read, and the indented ones are lists (§7.3)."""
    out = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        margin = " " * (len(line) - len(line.lstrip()))
        out.extend(textwrap.wrap(
            stripped, width=max(20, width), initial_indent=margin,
            subsequent_indent=margin + "  ", break_on_hyphens=False,
        ))
    return out or [""]


def _wrap(text: str, indent: str = "") -> List[str]:
    """One footer line inside the client's width, continuations indented so they read as
    the same line rather than as a new one."""
    return textwrap.wrap(
        text, width=display_width(), subsequent_indent=indent, break_on_hyphens=False
    )


def _omissions(hidden: int, older: int, clipped: List[str]) -> str:
    """The dim line naming what the listing left out, and the flag that brings it back."""
    parts = []
    if hidden:
        parts.append(f"{hidden} read-only run(s) hidden (-a for all)")
    if clipped:
        parts.append(f"{' and '.join(clipped)} clipped (-v for the full text)")
    if older:
        parts.append(f"{older} older run(s) not shown (raise -n)")
    return " · ".join(parts)


def _print_detail(run: RunSummary, runs: Dict[str, RunSummary]) -> None:
    """One run: its header, every record it wrote, and the runs it spawned."""
    print(bold(f"run {run.id}") + " · " + (run.command or "?"))
    where = [run.source]
    if run.pid is not None:
        where.append(f"pid {run.pid}")
    if run.config:
        where.append(os.path.basename(run.config))
    if run.db:
        where.append(os.path.basename(run.db))
    print(dim("  " + " · ".join(where)))
    print(dim("  " + _span_line(run)))
    if run.parent:
        print(dim(f"  parent {run.parent}"))
    print()
    _print_events(run)
    children = sorted(
        (r for r in runs.values() if r.parent == run.id), key=lambda r: r.started
    )
    if not children:
        return
    print()
    print(bold(f"{len(children)} run(s) started by this one:"))
    for child in children:
        print(f"  {child.id}  {_when_cell(child)}  "
              f"{pad_visible(child.command, 30)}  {_end_cell(child)}")


def _span_line(run: RunSummary) -> str:
    """`2026-08-24 Mon 19:22 → 19:23 · 96.4s · failed (exit 1)`."""
    started = local_time(run.started)
    parts = [fmt_timestamp(run.started)]
    if started is not None and run.ms is not None:
        ended = started.timestamp() + run.ms / 1000
        parts[0] += " → " + datetime.fromtimestamp(
            ended, tz=started.tzinfo
        ).strftime("%H:%M")
        parts.append(f"{run.ms / 1000:.1f}s")
    if run.outcome is None:
        parts.append("no end recorded — still running, or killed")
        return " · ".join(parts)
    ending = run.outcome
    if run.exit_code is not None:
        ending += f" (exit {run.exit_code})"
    parts.append(ending)
    return " · ".join(parts)


def _print_events(run: RunSummary) -> None:
    """Every record the run wrote, as offsets from its ``run.start``."""
    records = [
        rec for rec in journal.iter_records(*day_bounds(run))
        if str(rec.get("run")) == run.id
    ]
    records.sort(key=lambda rec: (str(rec.get("ts")), rec.get("seq") or 0))
    origin = local_time(run.started)
    width = max([len(str(rec.get("ev") or "")) for rec in records] + [9])
    for rec in records:
        moment = local_time(rec.get("ts"))
        offset = (moment - origin).total_seconds() if moment and origin else 0.0
        level = str(rec.get("lvl") or "info")
        color = _LEVEL_COLOR.get(level, str)
        head = f"{offset:+7.1f}s  {pad_visible(color(level), 5)}  "
        head += pad_visible(cyan(str(rec.get("ev") or "")), width)
        lines = str(rec.get("msg") or "").split("\n")
        print(f"{head}  {lines[0]}")
        indent = " " * visible_len(head) + "  "
        for extra in lines[1:]:
            print(indent + extra)
        for extra in _continuations(rec):
            print(indent + dim(extra))


def _continuations(rec: Dict[str, Any]) -> List[str]:
    """The lines that hang under a record: the exchange file, the traceback."""
    d = rec.get("d") or {}
    out = []
    if d.get("file"):
        out.append(str(d["file"]))
    trace = d.get("traceback")
    if trace:
        out.extend(str(trace).rstrip("\n").split("\n"))
    return out


# --- the cost rollup --------------------------------------------------------------

def _print_cost(args: argparse.Namespace) -> None:
    """Volume by model and by command (§7).

    Tokens, not money: prompt caching means the two are not proportional, so read this
    as a volume rather than a bill."""
    since, until = date_window(args)
    runs = collect(since, until)
    wanted = {
        run_id for run_id, run in runs.items()
        if run.started and in_window(run, since, until)
    }
    by_model: Dict[str, List[int]] = defaultdict(lambda: [0, 0])   # calls, tokens
    model_runs: Dict[str, set] = defaultdict(set)
    for rec in journal.iter_records(since, until):
        if rec.get("ev") != "llm.call":
            continue
        run_id = str(rec.get("run"))
        if run_id not in wanted:
            continue
        d = rec.get("d") or {}
        model = str(d.get("model") or "?")
        by_model[model][0] += 1
        by_model[model][1] += int(d.get("tokens") or 0)
        model_runs[model].add(run_id)
    if not by_model:
        print("No model calls recorded in that window.")
        return

    rows = []
    for model in sorted(by_model, key=lambda m: -by_model[m][1]):
        calls, tokens = by_model[model]
        rows.append([model, str(len(model_runs[model])), str(calls), f"{tokens:,}"])
    rows.append([
        "", str(len({r for s in model_runs.values() for r in s})),
        str(sum(v[0] for v in by_model.values())),
        f"{sum(v[1] for v in by_model.values()):,}",
    ])
    print(render_table(["MODEL", "RUNS", "CALLS", "TOKENS"], rows))

    by_command: Dict[str, List[int]] = defaultdict(lambda: [0, 0, 0])  # runs, calls, tokens
    for run_id in wanted:
        run = runs[run_id]
        if not run.llm_calls:
            continue
        entry = by_command[command_path(run) or run.command]
        entry[0] += 1
        entry[1] += run.llm_calls
        entry[2] += run.tokens
    if not by_command:
        return
    print()
    print(render_table(
        ["COMMAND", "RUNS", "CALLS", "TOKENS"],
        [[name, str(v[0]), str(v[1]), f"{v[2]:,}"]
         for name, v in sorted(by_command.items(), key=lambda kv: -kv[1][2])],
    ))


# --- follow -----------------------------------------------------------------------

def _follow() -> None:
    """Tail today's file, one rendered line per new record, until Ctrl-C.

    Re-resolves the path every poll so a run that crosses midnight UTC keeps printing
    from the next day's file (§4)."""
    print(dim(f"Following {journal.runs_dir()} — Ctrl-C to stop."))
    path, handle = None, None
    try:
        while True:
            current = journal.today_path()
            if current != path:
                if handle is not None:
                    handle.close()
                path, handle = current, _open_at_end(current)
            for line in handle or []:
                rec = journal.parse_record(line)
                if rec is not None:
                    _print_follow_line(rec)
            time.sleep(FOLLOW_POLL_SECONDS)
    except KeyboardInterrupt:
        print()
    finally:
        if handle is not None:
            handle.close()


def _open_at_end(path: str):
    try:
        handle = open(path, "r", encoding="utf-8", errors="replace")
    except OSError:
        return None
    handle.seek(0, os.SEEK_END)
    return handle


def _print_follow_line(rec: Dict[str, Any]) -> None:
    moment = local_time(rec.get("ts"))
    stamp = moment.strftime("%H:%M:%S") if moment else "??:??:??"
    color = _LEVEL_COLOR.get(str(rec.get("lvl")), str)
    print(f"{dim(stamp)}  {rec.get('run')}  "
          f"{pad_visible(cyan(str(rec.get('ev') or '')), 14)}  "
          f"{color(str(rec.get('msg') or ''))}")


# --- handlers ---------------------------------------------------------------------

def run_journal(args: argparse.Namespace) -> None:
    """The listing, the cost rollup, or a tail — `journal show` has the detail view."""
    if getattr(args, "follow", False):
        _follow()
        return
    if getattr(args, "cost", False):
        _print_cost(args)
        return
    runs, hidden = select_runs(args)
    _print_listing(
        runs, getattr(args, "limit", DEFAULT_LIMIT), hidden,
        verbose=getattr(args, "verbose", False),
    )


def run_journal_show(args: argparse.Namespace) -> None:
    """One run in full, found by a unique id prefix — git-style (§7)."""
    prefix = str(args.run or "").strip().lower()
    runs = collect(None, None)
    matches = sorted(
        (run for run_id, run in runs.items() if run_id.startswith(prefix) and run.started),
        key=lambda r: r.started, reverse=True,
    )
    if not matches:
        notice(f"No run whose id starts with '{prefix}'.", red)
        return
    if len(matches) > 1:
        notice(f"'{prefix}' matches {len(matches)} runs:")
        _print_listing(matches, len(matches))
        return
    _print_detail(matches[0], runs)


def run_journal_prune(args: argparse.Namespace) -> None:
    """Force the retention sweep the daily stamp file would otherwise gate (§10)."""
    days, exchanges = journal.prune()
    print(green(
        f"Pruned {days} journal day file(s) and {exchanges} LLM exchange file(s)."
    ))
