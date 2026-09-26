"""`bot capture test_result`, and the question the morning after a test
(DESIGN_benchmark_from_chat.md).

Both doors end in `benchmark record`'s own confirm: the typed one when the router names
`record_test`, and the `test_result` queue kind, whose "Tell me the number" answer hands
the typed text to the same capture with the session pinned (§2). The model reads the
message; the app parses the value, picks the sport, date and source, and assembles the
argv (§3, §5).
"""
import argparse
from datetime import date as _date, datetime, timedelta
from typing import Any, Dict, List, Optional

from stamind import runtime
from stamind.benchmarks import ANCHOR_KINDS, LOGBOOK_KINDS, SPORT_ANCHORS, anchors_for_sport
from stamind.cli.bot.extraction import (
    CAPTURE_ROLE, NEVER_FILL_RULE, capture_call, dated_context, no_find, valid_date,
)
from stamind.cli.bot.route import use_router_model
from stamind.clock import to_local, today_str as _today_str
from stamind.queue_kind import QUESTION, Kind, NotApplied, queue
from stamind.sports import CANONICAL_SPORTS, canonical_sport
from stamind.text import wrap_text
import stamind.cli.benchmarks as _benchmarks

KIND = "test_result"

# How far back the capture is shown the planned tests it may file a result under (§3).
RECENT_TEST_DAYS = 14

# e1RM is not offered from chat (§3; DESIGN_strength_tracking.md §12).
CHAT_KINDS = [kind for kind in LOGBOOK_KINDS if kind != "e1rm"]

# The sports a message may name: the canonical ones, and those the logbook tests on.
TEST_SPORTS = CANONICAL_SPORTS + [s for s in SPORT_ANCHORS if s not in CANONICAL_SPORTS]

TEST_RESULT_PROMPT = (
    CAPTURE_ROLE
    + "## TASK\n\n"
    "{dated}\n\n"
    "The athlete reports the result of a fitness test. Fill the fields below from what the\n"
    "message states.\n"
    + NEVER_FILL_RULE
    + '"kind" must be one of these, spelled EXACTLY as shown:\n'
    "{kinds}\n"
    "A bare number may be read against a test listed under RECENT TESTS: \"250\" answering\n"
    "an FTP test is ftp. With no listed test to read it against, a number alone names no\n"
    "kind: return null.\n"
    '"value" is the number exactly as the athlete wrote it: "4:15" stays "4:15". Never\n'
    "convert it: a race time is not a pace.\n"
    '"sport" is one of these, only when the message names it: {sports}.\n'
    '"performed" is true when the message says a test was done ("did the ramp test"), and\n'
    'false when it only states a number ("my FTP is 250").\n'
    '"session_id" is the id of the listed test the message reports on, or null.\n'
    '"note" is what the message says about the test beyond the number and the kind — the\n'
    "protocol, the conditions, how it went — copied in the athlete's own words, never\n"
    "summarized. null when the message says nothing more.\n\n"
    "## RECENT TESTS\n\n"
    "{sessions}\n\n"
    "## RESPONSE FORMAT\n\n"
    "You MUST respond with a JSON object containing:\n"
    "{{\n"
    '  "kind": "one of the kinds above (or null)",\n'
    '  "value": "the number as written (or null)",\n'
    '  "sport": "one of the sports above (or null)",\n'
    '  "date": "YYYY-MM-DD, only when the message names the day of the test (or null)",\n'
    '  "performed": true | false,\n'
    '  "session_id": "the id of a listed test (or null)",\n'
    '  "note": "the athlete\'s own words about the test (or null)"\n'
    "}}\n"
)

KIND_ASK = (
    "Which test was it — FTP, threshold pace, …? Tell me again with the number and I'll "
    "write it down."
)


def _value_ask(kind: str) -> str:
    anchor = ANCHOR_KINDS[kind]
    return (f"What did the test give for {anchor.label}, in {anchor.unit}? Tell me again "
            "with the number and I'll write it down.")


def _mismatch_ask(kind: str, sport: str) -> str:
    return (f"{ANCHOR_KINDS[kind].label} isn't something {sport} is tested on. Tell me "
            "again which test it was.")


def recent_tests(today: str) -> List[Dict[str, Any]]:
    """The planned tests of the last fourteen days, today included (§3)."""
    start = (datetime.strptime(today, "%Y-%m-%d")
             - timedelta(days=RECENT_TEST_DAYS - 1)).strftime("%Y-%m-%d")
    return [w for w in runtime.db.get_workouts(start_date=start, end_date=today)
            if w.get("benchmark_type")]


def usual_sport(kind: str) -> str:
    """The first sport tested on `kind`: cycling for FTP, running for threshold pace."""
    return next(sport for sport, kinds in SPORT_ANCHORS.items() if kind in kinds)


def _message_sport(raw: Any) -> Optional[str]:
    sport = canonical_sport(str(raw or ""))
    return sport if sport in TEST_SPORTS else None


def _session_id(raw: Any) -> Optional[int]:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def capture_test_result(text: str, pinned: Optional[int] = None) -> Optional[int]:
    """Reads one message into a `benchmark record` run and returns the recorded row's id,
    or None when nothing was recorded: a field was missing, or she said no (§3). `pinned`
    is the session the morning-after question is about; the capture is then shown that
    test alone."""
    today = _today_str()
    sessions = recent_tests(today)
    if pinned is not None:
        session = runtime.db.get_workout_by_id(pinned)
        sessions = [session] if session else []
    listed = "\n".join(
        f"- id {w['id']}: {w['date']}, {w['sport_type']}, “{w['title']}”" for w in sessions
    ) or "(none)"
    data = capture_call(
        TEST_RESULT_PROMPT.format(
            dated=dated_context(today), sessions=listed,
            kinds="\n".join(f"- {k}: {ANCHOR_KINDS[k].label}, in {ANCHOR_KINDS[k].unit}"
                            for k in CHAT_KINDS),
            sports=", ".join(TEST_SPORTS),
        ),
        text, "bot_capture_test_result",
    )
    if data is None:
        no_find(text)
        return None

    kind = str(data.get("kind") or "").strip().lower()
    if kind not in CHAT_KINDS:
        print(wrap_text(KIND_ASK))
        return None
    raw = str(data.get("value") or "").strip()
    try:
        _benchmarks.parse_value(kind, raw)
    except (ValueError, IndexError):
        print(wrap_text(_value_ask(kind)))
        return None

    by_id = {w["id"]: w for w in sessions}
    session = by_id.get(pinned if pinned is not None else _session_id(data.get("session_id")))
    sport = _message_sport(data.get("sport"))
    if sport is None and session:
        sport = canonical_sport(session["sport_type"])
    if sport is None:
        sport = usual_sport(kind)
    plausible = anchors_for_sport(sport)
    if plausible and kind not in plausible:
        print(wrap_text(_mismatch_ask(kind, sport)))
        return None

    date = session["date"] if session else (valid_date(data.get("date")) or today)
    source = "manual"
    if session or data.get("performed") is True:
        source = "test"
    args = argparse.Namespace(
        sport=sport, date=date, note=str(data.get("note") or "").strip() or None,
        session=session["id"] if session else None, source=source, yes=False,
        **{k: None for k in LOGBOOK_KINDS},
    )
    setattr(args, kind, raw)
    return _benchmarks.run_benchmark_record(args)


# --- the morning-after question (§4) ---

TELL_ME = {"label": "tell me the number", "ask": "What number did the test give you?"}


def _day(payload: Dict[str, Any]) -> _date:
    return _date.fromisoformat(payload["date"])


def _wording(item: Dict[str, Any]) -> str:
    payload = item["payload"]
    day = _day(payload)
    return (f"What did the test on {day:%a %b} {day.day} give? “{payload['title']}” "
            f"(session #{payload['workout_id']}) is done, with no result in the logbook.")


def _companion_wording(item: Dict[str, Any]) -> str:
    """'Saturday's' within the week the question was queued in, 'the Sep 1' after it."""
    payload = item["payload"]
    day = _day(payload)
    queued = to_local(datetime.fromisoformat(item["queued_at"])).date()
    when = f"{day:%A}'s" if 0 <= (queued - day).days < 7 else f"the {day:%b} {day.day}"
    return (f"How did {when} “{payload['title']}” go? Tell me the number it gave you and "
            "I'll write it down.")


def has_result(workout_id: int, sport: str, day: str) -> bool:
    """Whether the logbook holds a result for this test: one filed under it, or one for
    its sport dated on or after its day (§4)."""
    return any(
        row["workout_id"] == workout_id
        or (canonical_sport(row["sport_type"]) == sport and row["date"] >= day)
        for row in runtime.db.get_benchmark_results()
    )


def _is_stale(item: Dict[str, Any]) -> bool:
    payload = item["payload"]
    session = runtime.db.get_workout_by_id(payload["workout_id"])
    if session is None or session.get("removed"):
        return True
    return has_result(payload["workout_id"], payload["sport"], payload["date"])


def _apply(item: Dict[str, Any], index: int, text: Optional[str]) -> None:
    """The typed answer goes to the capture with the session pinned. A "No" on the
    read-back leaves the item waiting (§4)."""
    use_router_model(argparse.Namespace())
    if capture_test_result(text or "", item["payload"]["workout_id"]) is None:
        raise NotApplied("I'll ask again next time.")
    return None


TEST_RESULT_KIND = Kind(
    name=KIND, shape=QUESTION,
    wording=_wording, companion_wording=_companion_wording,
    is_stale=_is_stale, apply=_apply, drop_label="nothing to record",
)


def ask_about(session: Dict[str, Any]) -> None:
    """Queues the question about one planned test done without a result, once (§4)."""
    sport = canonical_sport(session["sport_type"])
    if has_result(session["id"], sport, session["date"]):
        return
    queue(KIND, str(session["id"]), {
        "workout_id": session["id"],
        "date": session["date"],
        "title": session["title"],
        "sport": sport,
        "answers": [dict(TELL_ME)],
    })
