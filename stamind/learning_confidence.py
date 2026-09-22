"""What a coach learning's confidence means, and how the evidence sets it.

A learning is an observation about the athlete — "you recover slowly from long
threshold sessions" — and its confidence is not something the model asserts. The app
derives it from how many distinct training weeks back the observation and how many
contradict it (DESIGN_evidence_based_confidence.md §3), lowers it when a week goes
against it, and lets it go dormant when nothing has reinforced it for long enough
(DESIGN_learning_doubt_nudge.md §3.2).

These are rules, not rows. They lived in `db/learnings.py`, which meant the storage
layer decided what "established" means; storage now keeps only storage.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from stamind.config import config


# Ordered confidence levels, weakest → strongest. Confidence is now APP-COMPUTED from each
# learning's evidence basis (see derive_confidence) rather than LLM-asserted.
CONFIDENCE_LEVELS = ("tentative", "moderate", "established")

# Sentinel stored in `proposed_confidence` when the pending downgrade is a *retirement*
# (net support fell to ≤0 under contradiction). Not a real confidence level, so it never
# validates as one.
RETIRE_PROPOSAL = "retire"


def normalize_sports(value: Any) -> str:
    """Normalizes a sport-scope value (list or comma string) to a comma-joined,
    lowercased string; empty/missing becomes 'general'."""
    if not value:
        return "general"
    if isinstance(value, (list, tuple)):
        parts = [str(s).strip().lower() for s in value if str(s).strip()]
    else:
        parts = [s.strip().lower() for s in str(value).split(",") if s.strip()]
    return ",".join(parts) if parts else "general"


def valid_confidence(value: Any) -> Optional[str]:
    """Returns the confidence value if it is a recognized level, else None."""
    return value if value in CONFIDENCE_LEVELS else None


def confidence_rank(value: Any) -> int:
    """Ordinal rank for comparing levels. RETIRE_PROPOSAL / unknown rank below tentative."""
    try:
        return CONFIDENCE_LEVELS.index(value) + 1
    except ValueError:
        return 0  # retire / unknown — below tentative


def step_down(level: str) -> str:
    """The next confidence level *down*, or RETIRE_PROPOSAL below tentative."""
    rank = confidence_rank(level)
    if rank <= 1:
        return RETIRE_PROPOSAL
    return CONFIDENCE_LEVELS[rank - 2]


def derive_confidence(
    supporting_weeks: int, contradicting_weeks: int,
    thresholds: Optional[Dict[str, int]] = None
) -> str:
    """Maps an evidence basis to a confidence level (DESIGN_evidence_based_confidence.md §3).

    `net = supporting − contradicting`. Returns RETIRE_PROPOSAL only when contradiction has
    actually driven net ≤ 0 — a learning with *no* basis yet (net 0, nothing contradicting)
    rests at the tentative floor rather than being proposed for retirement.
    """
    thresholds = thresholds or config.learning_confidence_thresholds
    net = supporting_weeks - contradicting_weeks
    if net >= thresholds.get("established", 5):
        return "established"
    if net >= thresholds.get("moderate", 3):
        return "moderate"
    if net >= 1:
        return "tentative"
    if contradicting_weeks > 0:
        return RETIRE_PROPOSAL
    return "tentative"


# A learning is "dormant" — kept in the DB but excluded from LLM prompts — once it has gone
# unreinforced for longer than the budget for its confidence level. Decay is soft: a dormant
# learning revives the moment new supporting evidence lands (or a staleness step re-arms its
# clock). Every reflect and bootstrap run also lowers a dormant learning one level
# (DESIGN_learning_doubt_nudge.md §3.2). The per-level budgets (days) are tunable via
# `config.learning_staleness_days`.


def learning_is_dormant(learning: Dict[str, Any], now: Optional[datetime] = None) -> bool:
    """True if a learning has gone unreinforced past its confidence-based budget."""
    now = now or datetime.now(timezone.utc)
    ref = learning.get("last_reinforced_at") or learning.get("created_at")
    if not ref:
        return False
    try:
        ref_dt = datetime.fromisoformat(ref)
    except (ValueError, TypeError):
        return False
    staleness_days = config.learning_staleness_days
    budget = staleness_days.get(
        learning.get("confidence") or "tentative", staleness_days["tentative"]
    )
    return (now - ref_dt) > timedelta(days=budget)
