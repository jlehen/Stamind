"""The zone table as text: the rows, the coverage line, the deltas and the caveats.

Column-aligned output, wrapped once here at `PROMPT_WIDTH` and never re-wrapped
downstream — a screen-width re-wrap would shred the columns
(DESIGN_intensity_distribution.md §6).
"""
from typing import Dict, List, Sequence, Tuple

from stamind.analytics.intensity import CURRENCY_BY_KEY, ZoneRow
from stamind.sports import is_strength_sport

PROMPT_WIDTH = 100

# Two claims with different scopes, so two notes: strength is a property of the sport and
# is suppressed when no strength sport is on screen; interval work with rest happens in
# running, cycling and rowing alike and never is (§9.6).
HR_STRENGTH_NOTE = (
    "Note: HR during strength work reflects rest between sets as much as effort — "
    "read those rows beside the session RPE."
)
HR_INTERVAL_NOTE = (
    "Note: HR during interval work with rest reflects the rest as much as the effort "
    "— read those rows beside the session RPE."
)
HR_LAG_NOTE = (
    "Note: HR needs 60-90s to climb, so short VO2max intervals bank most of their "
    "seconds in Z4 — measured by HR a genuine VO2max mesocycle looks like a threshold "
    "mesocycle. Prefer the power row where one exists."
)
NEVER_SUM_NOTE = (
    "Note: the HR and power rows of one sport are two views of the SAME time, never a "
    "total — a ride with a meter appears in both. Never add them."
)

# ------------------------------------------------------------------ render

def fmt_duration(seconds: float) -> str:
    """'55m' under an hour, '3h39' above — the compact form the tables use."""
    minutes = int(round(seconds / 60.0))
    if abs(minutes) < 60:
        return f"{minutes}m"
    sign = "-" if minutes < 0 else ""
    minutes = abs(minutes)
    return f"{sign}{minutes // 60}h{minutes % 60:02d}"


def _signed_duration(seconds: float) -> str:
    body = fmt_duration(abs(seconds))
    return f"+{body}" if seconds >= 0 else f"-{body}"


def _prefix(sport: str, currency: str, sport_width: int) -> str:
    return f"{sport.ljust(sport_width)}  {CURRENCY_BY_KEY[currency].tag.ljust(5)}  "


def _lay_out(prefix: str, cells: Sequence[str], width: int) -> List[str]:
    """A row's cells over as many lines as `width` allows, continuations hanging under
    the first cell so the sport/currency prefix is never repeated."""
    if not cells:
        return []
    cell_w = max(len(c) for c in cells) + 2
    per_line = max(1, (width - len(prefix)) // cell_w)
    lines, pad = [], " " * len(prefix)
    for i in range(0, len(cells), per_line):
        head = prefix if i == 0 else pad
        body = "".join(c.ljust(cell_w) for c in cells[i:i + per_line])
        lines.append((head + body).rstrip())
    return lines


def _zone_cells(row: ZoneRow, divisor: float, with_pct: bool) -> List[str]:
    """One cell per zone, named — bare 'Z4' is markedly less legible to a model than
    'Z4 threshold' (§5). Percentages are of RECORDED zone seconds, so they sum to 100
    and the coverage line carries the recording gap on its own (§4)."""
    labels = CURRENCY_BY_KEY[row.currency].labels
    total = row.total
    cells = []
    for i, label in enumerate(labels, start=1):
        figure = fmt_duration(row.seconds[i - 1] / divisor)
        cell = f"Z{i} {label} {figure}"
        if with_pct:
            pct = (row.seconds[i - 1] / total * 100.0) if total else 0.0
            cell += f" ({pct:.0f}%)"
        cells.append(cell)
    return cells


def format_table(
    rows: Sequence[ZoneRow], divisor: float = 1.0, with_pct: bool = True,
    indent: str = "", width: int = PROMPT_WIDTH,
) -> List[str]:
    """The zone table itself. `divisor` turns totals into a per-week rate."""
    if not rows:
        return []
    sport_width = max(len(r.sport) for r in rows)
    out: List[str] = []
    for row in rows:
        prefix = indent + _prefix(row.sport, row.currency, sport_width)
        out.extend(_lay_out(prefix, _zone_cells(row, divisor, with_pct), width))
    return out


def format_coverage(
    rows: Sequence[ZoneRow], indent: str = "", width: int = PROMPT_WIDTH
) -> List[str]:
    """'Coverage: running 94% HR · cycling 96% HR, 67% power'.

    Low coverage means the effort sat BELOW Z1, not that nothing was done — a model
    reading absence as inactivity prescribes more aerobic volume on top of a base
    mesocycle that already had it (§7). Zeros are indistinguishable from NULLs in the
    columns themselves, so this fraction does all that work.
    """
    if not rows:
        return []
    per_sport: Dict[str, List[Tuple[str, str]]] = {}
    order: List[str] = []
    for row in rows:
        if row.sport not in per_sport:
            per_sport[row.sport] = []
            order.append(row.sport)
        name = "power" if row.currency == "power" else "HR"
        per_sport[row.sport].append((name, f"{row.coverage * 100:.0f}% {name}"))
    per_sport = {
        sport: [text for _, text in sorted(entries, key=lambda e: e[0] != "HR")]
        for sport, entries in per_sport.items()
    }
    body = " · ".join(f"{sport} {', '.join(per_sport[sport])}" for sport in order)
    return wrap_line(f"Coverage: {body}", indent, width)


def wrap_line(text: str, indent: str, width: int) -> List[str]:
    """Plain greedy wrap with a hanging indent, so a long note stays inside `width`."""
    words, lines, cur = text.split(), [], indent
    for word in words:
        candidate = f"{cur} {word}" if cur.strip() else cur + word
        if len(candidate) > width and cur.strip():
            lines.append(cur)
            cur = indent + "  " + word
        else:
            cur = candidate
    if cur.strip():
        lines.append(cur)
    return lines


def format_notes(rows: Sequence[ZoneRow], indent: str = "", width: int = PROMPT_WIDTH) -> List[str]:
    """The measurement caveats that travel WITH the numbers — emitted as facts, never
    corrected for (§7). The app aligns; the LLM reasons."""
    out: List[str] = []
    if any(r.currency == "hr" for r in rows):
        out.extend(wrap_line(HR_LAG_NOTE, indent, width))
        out.extend(wrap_line(HR_INTERVAL_NOTE, indent, width))
        if any(is_strength_sport(r.sport) for r in rows if r.currency == "hr"):
            out.extend(wrap_line(HR_STRENGTH_NOTE, indent, width))
    if len({r.sport for r in rows if r.currency == "power"} & {
        r.sport for r in rows if r.currency == "hr"
    }):
        out.extend(wrap_line(NEVER_SUM_NOTE, indent, width))
    return out


# ------------------------------------------------------------------- delta

def format_delta_table(
    rows: Sequence[ZoneRow], weeks: int,
    prev_rows: Sequence[ZoneRow], prev_weeks: int, prev_name: str,
    indent: str = "", width: int = PROMPT_WIDTH,
) -> List[str]:
    """Mesocycle-over-mesocycle change in per-week rates (§4.1).

    A sport or currency missing from either side is reported as absent rather than as a
    -100% swing: a changed sport mix is not intensity creep.
    """
    if not weeks or not prev_weeks:
        return []
    prev_by_key = {(r.sport, r.currency): r for r in prev_rows}
    cur_by_key = {(r.sport, r.currency): r for r in rows}
    cur_sports = {r.sport for r in rows}
    prev_sports = {r.sport for r in prev_rows}
    sport_width = max([len(r.sport) for r in list(rows) + list(prev_rows)] or [1])
    out: List[str] = []
    for row in rows:
        prefix = indent + _prefix(row.sport, row.currency, sport_width)
        prev = prev_by_key.get((row.sport, row.currency))
        if prev is None:
            what = "not trained" if row.sport not in prev_sports else "no data in this currency"
            out.append(f"{prefix}— {what} in {prev_name}, no comparison")
            continue
        out.extend(_lay_out(prefix, _delta_cells(row, weeks, prev, prev_weeks), width))
    for sport, currency in prev_by_key:
        if (sport, currency) in cur_by_key:
            continue
        prefix = indent + _prefix(sport, currency, sport_width)
        what = "not trained" if sport not in cur_sports else "no data in this currency"
        out.append(f"{prefix}— present in {prev_name}, {what} here")
    return out


def _delta_cells(row: ZoneRow, weeks: int, prev: ZoneRow, prev_weeks: int) -> List[str]:
    labels = CURRENCY_BY_KEY[row.currency].labels
    cells = []
    for i, label in enumerate(labels, start=1):
        now = row.seconds[i - 1] / weeks
        before = prev.seconds[i - 1] / prev_weeks
        change = _signed_duration(now - before)
        if before:
            pct = f"{(now - before) / before * 100:+.0f}%"
        else:
            pct = "new" if now else "—"
        cells.append(f"Z{i} {label} {change} ({pct})")
    return cells
