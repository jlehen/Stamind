"""What the athlete is asked once a session is in: whether a planned test was done and what
it gave, whether a short activity was the session cut short, and a reminder to enter an RPE.
The morning message and the Garmin check both end on it.
"""
from datetime import datetime, timedelta

from stamind import rpe_reminder, runtime
from stamind.analytics.compare import adherence_verdicts
from stamind.cli.bot import test_result
from stamind.cli.render.session_lines import SIMPLE_DONE_STATUSES
from stamind.cli.workouts import cut_short
from stamind.output import step

def _ask_about_tests(today: str) -> None:
    """Queues the test-result question for each planned test of the past seven days and
    today that was done or partly done and has no result in the logbook
    (DESIGN_benchmark_from_chat.md §4). A failure must not sink the push."""
    start = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
    try:
        tests = [w for w in runtime.db.get_workouts(start_date=start, end_date=today)
                 if w.get("benchmark_type")]
        if not tests:
            return
        verdicts = adherence_verdicts(runtime.db, start, today, today)
        for w in tests:
            if (verdicts.get(w["id"]) or {}).get("status") in SIMPLE_DONE_STATUSES:
                test_result.ask_about(w)
    except Exception as e:
        step(f"Could not check the past week's tests: {e}")


def queue_session_questions(today: str) -> None:
    """What the athlete is asked once a session is in: the morning push and the Garmin check
    both end on it."""
    _ask_about_tests(today)
    cut_short.queue_questions(today)
    rpe_reminder.queue_reminders(today)
