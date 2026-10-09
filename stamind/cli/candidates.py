"""Turning the candidates a free-text note produced into rows — the questions asked
before anything is stored.

Two inboxes read the same message for the same two candidate kinds: `workout adapt -m`,
where extraction rides the coaching call, and `bot capture note`, where it is the whole
job (DESIGN_bot_simple_frontend.md §12.3). A terminal asks on the spot, through the
confirms below, the signal ladder included (§12.10). A run started from the chat queues
each question and ends, and a tap answers it (DESIGN_waiting_proposal.md §6.3). Nothing
here writes before a `yes`: the service's `capture_message_*` do, in both cases.
"""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

from stamind import clock, runtime, signals
from stamind.cli.bot.extraction import adjust_week_button
from stamind.clock import today_str
from stamind.config import config
from stamind.db.queue import queue_stamp
from stamind.queue_kind import QUESTION, Kind, queue
from stamind.sentinels import emit_buttons

# The answers of a queued question, as its item stores them (DESIGN_athlete_queue.md §3).
YES = "yes"
NO = "no"


def _span(candidate: Dict[str, Any], start_key: str, default_date: str) -> Tuple[str, str]:
    """A candidate's window, defaulted and ordered the way the service will store it."""
    start = candidate.get(start_key) or default_date
    end = candidate.get("end_date") or start
    return (start, start) if end < start else (start, end)


def _stated_value(candidate: Dict[str, Any]) -> Optional[float]:
    """The number the note stated, or None. A bool is not a measurement, and neither is
    anything the model invented outside the numeric types (DESIGN_signal_extraction.md §3)."""
    value = candidate.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def open_ended(candidate: Dict[str, Any]) -> bool:
    """A preference with no time bound — "never two workouts in a day" — which the extraction
    marks rather than dates. It has no home in the constraints table
    (DESIGN_bot_simple_frontend.md §12.3, 2026-09-16)."""
    return bool(candidate.get('open_ended')) and bool((candidate.get('title') or '').strip())


def _dated(candidates: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The constraint candidates worth asking about: titled, and not a preference for good."""
    return [
        candidate for candidate in candidates
        if (candidate.get('title') or '').strip() and not open_ended(candidate)
    ]


def _tell_open_ended(candidates: Sequence[Dict[str, Any]], text: str) -> None:
    """Says where a preference for good belongs, quoting `text`, the note as written, so it
    can be passed on. It is never stored."""
    preferences = [
        candidate['title'].strip() for candidate in candidates if open_ended(candidate)
    ]
    if preferences:
        runtime.render.constraints_open_ended(preferences, text)


def coach_reaches(start: str, today: str) -> bool:
    """Whether a `workout adapt` run today could act on a constraint that starts on `start`:
    it stops at the end of the mesocycle under way (DESIGN_mesocycle_boundary.md §2)."""
    mesocycle = runtime.db.get_active_mesocycle(today)
    return bool(mesocycle) and start <= mesocycle['end_date']


def _store_constraint(candidate: Dict[str, Any], date_str: str) -> Optional[int]:
    """Stores one confirmed constraint and says so. Returns its id, or None when the
    service kept nothing."""
    cid, shaping = runtime.coach_service.capture_message_constraint(candidate, date_str)
    if cid is None:
        return None
    start, end = _span(candidate, 'start_date', date_str)
    runtime.render.constraint_captured(cid, candidate['title'].strip(), start, end, date_str)
    if shaping:
        # The escalation this names is the operator's typed work: in companion
        # chat the same fact is said without commands, and the plan-adjusting tap
        # is the offer the capture ends on (DESIGN_bot_simple_frontend.md §12.10).
        runtime.render.constraint_plan_shaping(cid, shaping)
    return cid


def _store_signal(candidate: Dict[str, Any], date_str: str, metric: str) -> bool:
    """Logs one confirmed signal under `metric`, the category the athlete settled on, and
    says so. False when no row was written."""
    rows = runtime.coach_service.capture_message_signal(candidate, date_str, metric)
    if not rows:
        runtime.render.signal_not_logged(metric)
        return False
    start, end = _span(candidate, 'date', date_str)
    runtime.render.signal_logged(metric, len(rows), start, end, date_str)
    return True


def _categories(candidate: Dict[str, Any]) -> Tuple[str, Optional[str], bool]:
    """(the category the model named, a category in use that is close to it or None,
    whether the named one is new) — DESIGN_signal_extraction.md §6. An unusable name comes
    back empty."""
    metric = signals.normalize_metric(candidate.get('metric'))
    if not metric:
        return "", None, False
    known = runtime.coach_service.known_signal_metrics()
    if metric in known:
        return metric, None, False
    return metric, signals.nearest_known(metric, known), True


# --- a terminal: asked on the spot ---

def confirm_new_constraints(
    candidates: Sequence[Dict[str, Any]], date_str: str, text: str = ""
) -> List[int]:
    """Asks about each constraint the note produced and stores the confirmed ones
    (DESIGN_constraints.md §8 two-confirmation flow, step 1).

    Returns the ids created. Declining discards the extraction — on the adapt path the
    note has already informed that run's adaptation regardless, since the same LLM call
    produced both."""
    captured: List[int] = []
    for candidate in _dated(candidates):
        start, end = _span(candidate, 'start_date', date_str)
        if not runtime.prompt.confirm(runtime.render.constraint_candidate_question(
            candidate['title'].strip(), start, end, date_str
        )):
            runtime.render.constraint_candidate_discarded()
            continue
        cid = _store_constraint(candidate, date_str)
        if cid is not None:
            captured.append(cid)
    _tell_open_ended(candidates, text)
    return captured


def confirm_new_signals(candidates: Sequence[Dict[str, Any]], date_str: str) -> int:
    """Asks about each daily signal the note produced, then writes the confirmed ones
    (DESIGN_signal_extraction.md §2). Returns how many were logged.

    A category close to one already in use is offered as a ladder of two y/N questions —
    the existing category first, the coined one second — so the reflexive `y` lands on
    reuse and coining a category takes a deliberate second answer (§6). Declining both
    logs nothing.
    """
    logged = 0
    for candidate in candidates:
        metric, near, new = _categories(candidate)
        if not metric:
            continue
        start, end = _span(candidate, 'date', date_str)
        value = _stated_value(candidate)

        def _ask(name: str, new_category: bool) -> bool:
            return runtime.prompt.confirm(runtime.render.signal_candidate_question(
                name, value, start, end, date_str, new_category=new_category,
            ))

        chosen = None
        if near and _ask(near, False):
            chosen = near
        elif _ask(metric, new):
            chosen = metric

        if not chosen:
            runtime.render.signal_candidate_discarded()
            continue
        logged += _store_signal(candidate, date_str, chosen)
    return logged


# --- the chat: queued, and answered with a tap (DESIGN_waiting_proposal.md §6.3) ---

def _constraint_wording(item: Dict[str, Any]) -> str:
    payload = item['payload']
    start, end = _span(payload['candidate'], 'start_date', payload['date'])
    return runtime.render.constraint_candidate_question(
        payload['candidate']['title'].strip(), start, end, today_str()
    )


def _constraint_stale(item: Dict[str, Any]) -> bool:
    """Its last day is behind: nothing is left to work around."""
    payload = item['payload']
    return _span(payload['candidate'], 'start_date', payload['date'])[1] < today_str()


def _apply_constraint(item: Dict[str, Any], index: int, text: Optional[str]) -> None:
    """"Yes" stores the constraint. The offer to adjust the week follows it only where the
    item asks for one and the coach can reach the constraint's first day."""
    payload = item['payload']
    if payload['answers'][index]['label'] != YES:
        runtime.render.constraint_candidate_discarded()
        return
    if _store_constraint(payload['candidate'], payload['date']) is None:
        return
    start, _end = _span(payload['candidate'], 'start_date', payload['date'])
    if payload['offer'] and coach_reaches(start, today_str()):
        emit_buttons([adjust_week_button()])


def _signal_wording(item: Dict[str, Any]) -> str:
    payload = item['payload']
    start, end = _span(payload['candidate'], 'date', payload['date'])
    value = _stated_value(payload['candidate'])
    if payload['near']:
        return runtime.render.signal_candidate_choice(
            payload['near'], payload['metric'], value, start, end, today_str()
        )
    return runtime.render.signal_candidate_question(
        payload['metric'], value, start, end, today_str(), new_category=payload['new'],
    )


def _signal_stale(item: Dict[str, Any]) -> bool:
    """Its last day is further back than the days of metrics the coach reads."""
    payload = item['payload']
    earliest = clock.today_date() - timedelta(days=max(config.metrics_lookback_days, 1) - 1)
    last_day = _span(payload['candidate'], 'date', payload['date'])[1]
    return datetime.strptime(last_day, "%Y-%m-%d").date() < earliest


def _apply_signal(item: Dict[str, Any], index: int, text: Optional[str]) -> None:
    """An answer that names a category logs the signal under it; "No" logs nothing."""
    payload = item['payload']
    metric = payload['answers'][index].get('metric')
    if not metric:
        runtime.render.signal_candidate_discarded()
        return
    if _store_signal(payload['candidate'], payload['date'], metric) and payload['offer']:
        emit_buttons([adjust_week_button()])


# Both are drawn bare and have no drop: "No" already settles them.
CONSTRAINT_KIND = Kind(
    name="constraint", shape=QUESTION,
    wording=_constraint_wording, companion_wording=_constraint_wording,
    is_stale=_constraint_stale, apply=_apply_constraint, bare=True,
)
SIGNAL_KIND = Kind(
    name="signal", shape=QUESTION,
    wording=_signal_wording, companion_wording=_signal_wording,
    is_stale=_signal_stale, apply=_apply_signal, bare=True,
)


def _signal_answers(metric: str, near: Optional[str]) -> List[Dict[str, Any]]:
    """Two answers, or three when a category in use is close: that one first, so the
    reflexive tap lands on reuse (DESIGN_signal_extraction.md §6)."""
    if not near:
        return [{'label': YES, 'metric': metric}, {'label': NO}]
    return [
        {'label': signals.metric_words(near), 'metric': near},
        {'label': f"{signals.metric_words(metric)} (new)", 'metric': metric},
        {'label': NO},
    ]


def queue_candidates(
    constraints: Sequence[Dict[str, Any]], signal_rows: Sequence[Dict[str, Any]],
    date_str: str, text: str, offer: bool,
) -> List[Dict[str, Any]]:
    """Queues one question per constraint, then one per signal, in the order a terminal
    asks them, and returns the items. `offer` says a "Yes" is followed by the offer to
    adjust the week, which a run of the coach has no use for.

    An item's subject is the start of this run and the candidate's place in the model's
    list, so the same words sent again ask again."""
    run = queue_stamp(clock.command_start())
    ids: List[Optional[int]] = []
    for place, candidate in enumerate(_dated(constraints)):
        ids.append(queue(CONSTRAINT_KIND.name, f"{run}:{place}", {
            'candidate': candidate, 'date': date_str, 'offer': offer,
            'answers': [{'label': YES}, {'label': NO}],
        }))
    _tell_open_ended(constraints, text)
    for place, candidate in enumerate(signal_rows):
        metric, near, new = _categories(candidate)
        if not metric:
            continue
        ids.append(queue(SIGNAL_KIND.name, f"{run}:{place}", {
            'candidate': candidate, 'date': date_str, 'offer': offer,
            'metric': metric, 'near': near, 'new': new,
            'answers': _signal_answers(metric, near),
        }))
    return [runtime.db.get_queue_item(item_id) for item_id in ids if item_id is not None]
