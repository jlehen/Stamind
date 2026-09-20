"""The companion voice on everything the schedule is built from
(DESIGN_bot_simple_frontend.md §6).

The other half of the line builders: goals, constraints, the plan and its mesocycles,
the fitness summary, the end of the schedule, and the queue's question. Where
`session_lines.py` says what a day holds, this says what the coach and the athlete have
agreed and where it is going — and it takes the date words from there rather than
spelling a day two ways."""
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from trainmate import athlete_queue
from trainmate.config import config
from trainmate.analytics.runway import (
    RUNWAY_MESOCYCLE, RUNWAY_PLAN_END_NEXT_GOAL, RUNWAY_SPAN,
)
from trainmate.text import capitalized, wrap_text
from trainmate.clock import days_between
from trainmate.cli.queue import queue_buttons
from trainmate.cli.runway import crossing_the_end, current_runway, runway_buttons
from trainmate.cli.render.session_lines import (
    simple_date_word, simple_span_words, simple_when, sport_emoji,
)


def simple_metric_words(metric: str) -> str:
    """A signal category as prose: `disturbed_sleep` reads 'disturbed sleep'. The
    underscore form is the storage key and stays expert detail (§6)."""
    return (metric or "").replace("_", " ").strip()


def simple_constraint_lines(constraints: List[Dict[str, Any]], today: str) -> List[str]:
    """Simple rendering of the directives the coach works around: one bullet per
    constraint, dates as day words, no IDs or tier tags (the expert `constraint list`
    keeps those). Empty reads as a clean slate, not a gap (§6 tone rule)."""
    if not constraints:
        return ["Nothing on the list — no rules to work around right now. "
                "Just tell me when something comes up 💬"]
    lines = ["📌 I'm working around:"]
    for c in constraints:
        bullet = "🛌" if c.get("rest") else "•"
        span = simple_span_words(c["start_date"], c["end_date"], today)
        lines.append(f"{bullet} {c['title']} — {span}")
    return lines


def simple_progress_lines(payload: Dict[str, Any], today: str) -> List[str]:
    """The two-line simple `progress` summary: a fitness-trend sentence (from the
    CTL series, ~28 days back) and a chart legend. Every branch keeps the §6 tone
    rule — a falling CTL reads as freshening up, not as decay."""
    days = payload.get("days") or []
    dated = [(d["date"], d.get("ctl")) for d in days
             if d.get("ctl") is not None and d["date"] <= today]
    trend = "Your training story is just getting started 🌱"
    if dated:
        now_date, now_ctl = dated[-1]
        base_cutoff = (
            datetime.strptime(now_date, "%Y-%m-%d") - timedelta(days=28)
        ).strftime("%Y-%m-%d")
        # Baseline: the newest sample at or before the cutoff; a shorter history
        # falls back to its earliest sample.
        older = [ctl for date, ctl in dated if date <= base_cutoff]
        base = older[-1] if older else dated[0][1]
        if base and base > 0 and len(dated) > 1:
            delta_pct = (now_ctl - base) / base * 100
            if delta_pct > 3:
                trend = f"Fitness is climbing — up {delta_pct:.0f}% this month 📈"
            elif delta_pct < -3:
                trend = "You're freshening up — recent rest is banking energy 🔋"
            else:
                trend = "Fitness is holding steady — consistency is doing its job 👍"
    return [
        trend,
        "The chart shows your fitness building up top, and week-by-week training "
        "below — keep stacking those weeks 💪",
    ]


def simple_goal_line(goal: Dict[str, Any], today: str) -> str:
    """One goal as the companion says it: sport emoji(s), title, day word and countdown.

    Its own function because a capture previews a goal it has not stored yet in exactly
    this wording — which is what makes a wrong `date_type` guess visible in the preview's
    first line rather than in the database (DESIGN_bot_simple_frontend.md §12.5)."""
    date_word = simple_date_word(str(goal["target_date"]))
    when = simple_when(str(goal["target_date"]), today)
    # 'on' a date something happens on; 'by ~' a horizon that only bounds the plan —
    # the same wording rule as the expert view.
    if goal.get("date_type") == "horizon":
        date_part = f"by ~{date_word} ({when})"
    else:
        date_part = f"on {date_word} ({when})"
    emoji = " ".join(sport_emoji(s) for s in str(goal["sport_type"]).split(","))
    return f"{emoji} {goal['title']} — {date_part}"


def simple_goal_lines(goals: List[Dict[str, Any]], today: str) -> List[str]:
    """Simple rendering of the goals view: each goal still ahead with a day word and a
    countdown, then the completed ones as one celebration line. No IDs or state tags
    (the expert `goal list` keeps those); an archived goal was called off and says
    nothing at all (§6 tone rule). Empty reads as an invitation, not a gap."""
    from trainmate.db.objectives import GOAL_COMPLETED, GOAL_UPCOMING, goal_state
    upcoming = [g for g in goals if goal_state(g, today) == GOAL_UPCOMING]
    completed = [g for g in goals if goal_state(g, today) == GOAL_COMPLETED]
    lines: List[str] = []
    if upcoming:
        lines.append("🎯 What you're training for:")
        for g in upcoming:
            lines.append(simple_goal_line(g, today))
            description = (g.get("description") or "").strip()
            if description:
                lines.append(wrap_text(description))
    else:
        lines.append(
            "No goal on the horizon right now — once one is set, your training "
            "will build toward it 🎯"
        )
    if completed:
        count = len(completed)
        goal_word = "goal" if count == 1 else "goals"
        lines.append(f"\n✅ {count} {goal_word} already behind you — nice collection 🏆")
    return lines


def simple_goal_edit_lines(
    goal: Dict[str, Any], changes: Dict[str, Any], today: str
) -> List[str]:
    """A proposed goal edit, drawn from the REAL row beside what it would become
    (DESIGN_bot_simple_frontend.md §12.4).

    The row half is what makes a wrong nomination die visibly: the athlete reads the goal
    the model picked, in the words she knows it by, before anything is written."""
    lines = [f"Your goal {simple_goal_line(goal, today)}"]
    if "title" in changes:
        lines.append(f"→ rename it to “{changes['title']}”")
    if "target_date" in changes:
        lines.append(
            f"→ move it to {simple_date_word(changes['target_date'])} "
            f"({simple_when(changes['target_date'], today)})"
        )
    if "description" in changes:
        lines.append(f"→ note against it: {changes['description']}")
    return lines


def simple_constraint_edit_lines(
    constraint: Dict[str, Any], changes: Dict[str, Any], today: str
) -> List[str]:
    """A proposed change to one of the rules the coach works around (§12.4), rendered
    from the stored row the same way `simple_constraint_lines` renders the list."""
    span = simple_span_words(constraint["start_date"], constraint["end_date"], today)
    lines = [f"Your rule “{constraint['title']}” — {span}"]
    if "title" in changes:
        lines.append(f"→ restate it as “{changes['title']}”")
    if "start_date" in changes or "end_date" in changes:
        start = changes.get("start_date", constraint["start_date"])
        end = changes.get("end_date", constraint["end_date"])
        lines.append(f"→ make it {simple_span_words(start, end, today)}")
    if "description" in changes:
        lines.append(f"→ note against it: {changes['description']}")
    return lines


def simple_plan_shaping_line(impact: Dict[str, Any]) -> str:
    """How big a directive just captured turns out to be, without the commands that would
    escalate it: building it into the plan is `plan generate`, which is operator work, and
    the adjust offer beside this capture is what the athlete can actually do (§12.10)."""
    return (
        f"That's a big one — it covers {impact['days']} days and takes out a good part "
        "of a normal week."
    )


def simple_focus_snippet(text: str, limit: int = 220) -> str:
    """The opening of a mesocycle's focus, for the plan view: the first sentence when
    one ends within `limit` chars, else a word-boundary cut with an ellipsis. A one-word
    label the `plan generate` model likes to open with ("Purpose: …") goes — it is a field
    name, not a headline. The full prescription is a tap away (`bot mesocycle`, §11.2)."""
    text = " ".join(text.split())
    text = re.sub(r"^[A-Za-z]+:\s+", "", text)
    text = capitalized(text)
    cut = text.find(". ")
    if 0 <= cut < limit:
        return text[:cut + 1]
    if len(text) <= limit:
        return text
    return text[:text.rfind(" ", 0, limit)] + "…"


def simple_mesocycle_window(start: str, end: str) -> str:
    """A training mesocycle's span as the plan view's leading column — 'Aug 17 – Sep 06'.
    Weekday and year go, where `simple_date_word` keeps the weekday: a mesocycle boundary is
    a week rather than an appointment, and the column has to stay scannable (§11.1)."""
    def month_day(date_str: str) -> str:
        return datetime.strptime(date_str, "%Y-%m-%d").strftime("%b %d")
    return f"{month_day(start)} – {month_day(end)}"


def simple_mesocycle_length(total_days: int) -> str:
    """How long a mesocycle runs. Exact-week mesocycles read in weeks; anything ragged reads in
    days rather than as a rounded lie."""
    if total_days % 7 == 0:
        weeks = total_days // 7
        return "1 week" if weeks == 1 else f"{weeks} weeks"
    return f"{total_days} days"


# Telegram renders inline labels short; the prose above a picker carries the full
# title, so a leaf label only has to be recognisable.
PICKER_LABEL_MAX = 28


def picker_label(text: str) -> str:
    """A button label cut to what Telegram will show whole."""
    if len(text) > PICKER_LABEL_MAX:
        return text[:PICKER_LABEL_MAX - 1] + "…"
    return text


def simple_mesocycle_lines(m: Dict[str, Any], today: str) -> List[str]:
    """One training mesocycle as a stanza head: the marker and name, then the window and
    the one thing the window cannot say — nothing behind her, how far into the mesocycle
    she is, length ahead (§11.2). The plan view adds the focus headline under the
    active mesocycle; `bot mesocycle` adds the whole focus."""
    start, end = str(m["start_date"]), str(m["end_date"])
    total_days = max(1, days_between(start, end) + 1)
    window = simple_mesocycle_window(start, end)
    if end < today:
        return [f"✅ {m['name']}", window]
    if start <= today:
        total_weeks = max(1, -(-total_days // 7))  # ceiling
        week_now = min(total_weeks, days_between(start, today) // 7 + 1)
        return [f"📍 {m['name']}", f"{window} · you're in week {week_now} of {total_weeks}"]
    return [f"⏳ {m['name']}", f"{window} · {simple_mesocycle_length(total_days)}"]


def simple_plan_lines(
    goal: Dict[str, Any], macrocycle: Dict[str, Any],
    mesocycles: List[Dict[str, Any]], today: str,
) -> List[str]:
    """Simple rendering of one periodization plan: the road to the goal — mesocycles done,
    the mesocycle the athlete is in (with its focus headline), mesocycles ahead — closed by the
    goal day. Strategy prose, IDs, feedback and snapshotted inputs stay expert detail
    (§11).

    Each mesocycle is a stanza with a blank line before it: a phone flows the text, so
    whitespace is the only column it can draw (§11.2)."""
    lines = [f"🧭 The road to {goal['title']}"]
    if macrocycle.get("status") == "superseded":
        lines.append("(an older version of the plan — a newer one has replaced it)")
    if not mesocycles:
        lines.append("No training mesocycles drawn up yet — check back soon 🌱")
        return lines
    for m in mesocycles:
        lines.append("")
        lines.extend(simple_mesocycle_lines(m, today))
        focus = (m.get("focus") or "").strip()
        if focus and str(m["start_date"]) <= today <= str(m["end_date"]):
            lines.append(wrap_text(simple_focus_snippet(focus)))
    date_word = simple_date_word(str(goal["target_date"]))
    when = simple_when(str(goal["target_date"]), today)
    lines.append("")
    if goal.get("date_type") == "horizon":
        lines.append(f"🏁 Building toward ~{date_word} ({when}) — keep stacking 💪")
    else:
        lines.append(f"🏁 The big day: {date_word} ({when}) — you've got this 💪")
    return lines


def simple_mesocycle_buttons(mesocycles: List[Dict[str, Any]], today: str) -> List[dict]:
    """The door under the plan view to a mesocycle's full prescription (§11.2): one leaf
    per mesocycle under way or still ahead, each sending the read-only `bot mesocycle <id>`.
    A lone candidate is offered directly; several sit behind one "Tell me more", so
    the row is never wider than a thumb. Finished mesocycles say nothing here either (§6)."""
    ahead = [m for m in mesocycles if str(m["end_date"]) >= today]
    if not ahead:
        return []
    leaves = [
        {"label": picker_label(simple_mesocycle_lines(m, today)[0]),
         "send": f"bot mesocycle {m['id']}"}
        for m in ahead
    ]
    if len(leaves) == 1:
        return [{"label": "🔎 Tell me more", "send": leaves[0]["send"]}]
    return [{"label": "🔎 Tell me more", "menu": leaves}]

# What simple mode says wherever the expert view would suggest `plan generate`: the
# athlete in companion mode cannot run it — the operator sets the plan up
# (DESIGN_bot_simple_frontend.md §11).
SIMPLE_NO_PLAN_LINE = (
    "No training plan here yet — it will appear once your goal is set up 🌱"
)

# What the push says instead of the rest-day line once the schedule is exhausted
# (DESIGN_runway_nudge.md §6): an empty day is then the schedule running out, not a
# coaching decision.
SIMPLE_PASSED_LINE = "You've finished everything on the schedule 🎉"

# The one-liner the companion week view ends on when its window crosses the cliff (§6),
# mirroring the expert listing's marker.
SIMPLE_END_NOTE = "That's the end of the current schedule."


def simple_end_note(end_date: Optional[str]) -> Optional[str]:
    """The companion week view's version of `runway.list_end_marker`
    (DESIGN_runway_nudge.md §6)."""
    return SIMPLE_END_NOTE if crossing_the_end(end_date) else None


def simple_end_buttons(end_date: Optional[str]) -> List[dict]:
    """The offer beside the companion week view's end note (§6).

    Two gates, so the rule stays one sentence: the listing must cross the end of the
    schedule (else the button has no context to sit under) and the nudge must be live
    (else `runway_buttons` returns nothing anyway). The note can therefore draw alone,
    but a button never draws without it."""
    if crossing_the_end(end_date) is None:
        return []
    return runway_buttons(current_runway())


def simple_plan_wrapped_line() -> str:
    """What the companion says once the plan is behind and a new goal is the only way
    forward: the next step, named as operator work (DESIGN_render_persona.md §5).

    Its own function because two surfaces say it — the morning push after the wrap-up
    lead, and `workout adapt`'s refusal on its own."""
    return (
        "When you know what you'd like to work toward next, tell "
        f"{config.telegram_operator_name} — setting up a new goal happens from the "
        "computer."
    )


def simple_plan_setup_line() -> str:
    """What the companion says once a goal exists but the periodization for it does not
    (DESIGN_bot_simple_frontend.md §12.5).

    `simple_plan_wrapped_line`'s sentence family — never "your coach", which formally
    means the app: a plan gets set up from the computer, by the operator, and a goal row
    being cheap is exactly why the periodization built on it stays behind the §7 line."""
    return (
        "The training plan for it gets set up from the computer — "
        f"{config.telegram_operator_name} takes care of that part."
    )


def simple_runway_lines(state: Dict[str, Any], today: str) -> List[str]:
    """The morning push's companion wording for one runway state
    (DESIGN_runway_nudge.md §6).

    Span and mesocycle cliffs read as an offer, because the button beside them performs it;
    a plan cliff reads as a wrap-up, because periodization is operator work in companion
    mode and there is nothing here for the athlete to tap."""
    kind, days_left = state["kind"], state["days_left"]
    if kind in (RUNWAY_MESOCYCLE, RUNWAY_SPAN):
        if days_left < 0:
            return ["Want me to plan the next few weeks?"]
        when = simple_when(state["last_covered_date"], today)
        return [f"Heads up — your schedule runs out {when}. "
                "Want me to plan the next few weeks?"]

    wrap_up = (
        "wrapped up" if days_left < 0
        else f"wraps up {simple_when(state['last_covered_date'], today)}"
    )
    lead = f"🎉 Your plan {wrap_up} — that's the goal you've been training toward!"
    if kind == RUNWAY_PLAN_END_NEXT_GOAL:
        obj = state["objective"]
        when = simple_when(str(obj["target_date"]), today)
        return [f"{lead} Next up is {obj['title']} ({when}) — that stretch gets set up "
                f"from the computer, by {config.telegram_operator_name}."]
    return [f"{lead} {simple_plan_wrapped_line()}"]


def simple_queue_message(
    item: Dict[str, Any], left: Optional[int]
) -> Tuple[str, List[dict]]:
    """One queued item in the companion's words, without skip: its difference from "after
    the others" does not fit in a sentence she can see (DESIGN_athlete_queue.md §6.4).
    `left` counts the walk from this item on, and None marks a reminder (§6.5)."""
    text = athlete_queue.wording(item, companion=True)
    buttons = queue_buttons(item, skip=False)
    if left is None:
        return f"⏰ You asked me to come back to this:\n{text}", buttons
    if athlete_queue.kind_of(item).shape == athlete_queue.MESSAGE:
        return f"📬 {text}", buttons
    return f"🙋 Quick question ({left} left)\n{text}", buttons
