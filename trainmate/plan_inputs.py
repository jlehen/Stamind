"""What shapes a periodization plan, how it is fingerprinted, and how it is diffed.

When `plan generate` runs it hashes the inputs the strategy was written against — the
athlete profile, the goals, the plan-shaping constraints, the thresholds and the science
documents — and stores those hashes on the macrocycle. Later, `plan show` hashes the same
inputs again: if they differ, the plan was built from a picture that has since changed
(DESIGN_plan_staleness.md).

This module is what "the inputs" means, in one place. It used to be three: the partition
lived at the foot of `config.py`, the goal and constraint cleaners were methods on the
engine that the engine never called, and the diff text sat in the coach service. What is
*not* here is the judgment — whether a difference is worth flagging, and what to do about
it — which is `coach/service/staleness.py`.

It stays flat and pure so the read-only web app can hash the config without importing the
coach (§4.4).
"""
import difflib
import hashlib
import json
import os
from typing import Any, Dict, List, Optional

from trainmate.config import config
from trainmate.types import Constraint, Objective


# Threshold anchors are excluded from the config fingerprint: they anchor per-workout zone
# targets, not the phase structure. They are snapshotted on the macrocycle and only flag
# the plan stale past a relative drift tolerance (`coach.threshold_replan_pct`) — see
# service.config_changed(). Only `max_hr` still lives in config; lthr/ftp are named here so
# a config still carrying them stays out of the hash (DESIGN_benchmark_workouts.md §3.4).
PROFILE_THRESHOLD_FIELDS = ('max_hr', 'lthr', 'ftp')

# Profile fields that reach every prompt but cannot shape the *periodization*, so editing
# one must not flag the plan stale (DESIGN_plan_staleness.md §3). `preferences` is
# session-level by contract: structure lives in the athlete's science documents, which
# are fingerprinted on their own (§11).
PROFILE_NON_PLAN_FIELDS = ('name', 'equipment', 'preferences')

# Per-day `weekly_schedule` sub-keys that shape individual sessions but not the mesocycle
# structure — swapping a day's kit changes what that day is, not the periodization
# (DESIGN_plan_staleness.md §4). The day's hours/max_sessions/certainty_percent stay in.
SCHEDULE_NON_PLAN_KEYS = ('equipment',)


def plan_profile() -> Dict[str, Any]:
    """The user_profile fields that shape the periodization strategy.

    Single source of truth for the config_hash fingerprint. The partition and its
    rationale are DESIGN_plan_staleness.md §3–§4: thresholds are tolerance-checked
    separately (see above), `name`/`equipment` and each day's `equipment` are excluded as
    not plan-shaping, and everything else — availability, target hours, preferences,
    injuries, sports — is. The exclusions are a denylist so a profile field added later
    counts as plan-shaping until someone decides otherwise (§6).

    Deliberately NOT fingerprinted: prompt-context knobs such as
    `coach.metrics_lookback_days`, which change what the coach *sees*, not what the plan
    should be.
    """
    return plan_shaping(config.user_profile)


def plan_shaping(user_profile: Dict[str, Any]) -> Dict[str, Any]:
    """`plan_profile()`'s partition applied to any profile dict — the live one, or a
    snapshot stored under an earlier partition (DESIGN_plan_staleness.md §7)."""
    excluded = set(PROFILE_THRESHOLD_FIELDS) | set(PROFILE_NON_PLAN_FIELDS)
    profile = {k: v for k, v in user_profile.items() if k not in excluded}
    schedule = profile.get('weekly_schedule')
    if isinstance(schedule, dict):
        profile['weekly_schedule'] = {
            day: (
                {k: v for k, v in spec.items() if k not in SCHEDULE_NON_PLAN_KEYS}
                if isinstance(spec, dict) else spec
            )
            for day, spec in schedule.items()
        }
    return profile


def changed_plan_profile_fields(old_profile: Dict[str, Any]) -> List[str]:
    """The plan-shaping profile fields that differ between `old_profile` (a snapshot taken
    at plan generation) and the live config, so staleness can say *what* moved.

    Names a field whether it was added, removed, or edited — the athlete needs to know
    which input to look at, not which of the three happened to it (DESIGN_plan_staleness.md
    §5)."""
    # Read through the current partition: a field that stopped being plan-shaping after
    # the snapshot was taken is not a deletion (§7).
    old_profile = plan_shaping(old_profile)
    current = plan_profile()
    return sorted(
        k for k in set(old_profile) | set(current)
        if old_profile.get(k) != current.get(k)
    )


def science_documents(s_dir: str) -> Dict[str, str]:
    """Every `*.md` under `s_dir` as {filename: text}, in name order; {} when the
    directory is missing or holds none. One reader for the prompt and the fingerprint, so
    the coach and the staleness check agree on what the athlete's guidelines are."""
    if not os.path.isdir(s_dir):
        return {}
    docs: Dict[str, str] = {}
    for filename in sorted(os.listdir(s_dir)):
        if not filename.endswith(".md"):
            continue
        filepath = os.path.join(s_dir, filename)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                docs[filename] = f.read()
        except Exception as e:
            print(f"Error reading science guideline {filename}: {e}")
    return docs


def athlete_science_documents() -> Dict[str, str]:
    """The athlete's own guidelines (`science_dir`), the prescriptive input the plan is
    generated from and the fifth staleness axis (DESIGN_plan_staleness.md §11)."""
    return science_documents(config.science_dir)


def changed_science_documents(old_docs: Dict[str, str]) -> List[str]:
    """The athlete's science files that differ between `old_docs` (a snapshot taken at
    plan generation) and the directory now — added, removed or edited, like
    `changed_plan_profile_fields` (§11)."""
    current = athlete_science_documents()
    return sorted(
        name for name in set(old_docs) | set(current)
        if old_docs.get(name) != current.get(name)
    )


def plan_config_hash() -> str:
    """Hash of the plan-shaping user config (see `plan_profile`).

    Lives here, beside the config it fingerprints, rather than on the coaching engine:
    the read-only web dashboard shows a "config changed since this plan" banner, and
    reaching the engine for it would drag the LLM client and the Google Calendar
    service-account credentials into a surface that writes to neither (ARCHITECTURE.md §8).
    """
    serialized = json.dumps({'user_profile': plan_profile()}, sort_keys=True)
    return hashlib.sha256(serialized.encode('utf-8')).hexdigest()


def clean_goals(objectives: List[Objective]) -> List[Dict[str, Any]]:
    """The goal fields that matter for planning, normalized and stably ordered.

    Single source of truth for both the goals_hash fingerprint and the snapshot
    persisted on the macrocycle, so the two can never drift apart.
    """
    cleaned = []
    for o in objectives:
        entry = {
            'id': o.get('id'),
            'title': o.get('title'),
            'target_date': o.get('target_date'),
            'sport_type': o.get('sport_type'),
            'description': o.get('description'),
            'status': o.get('status')
        }
        # Only when it departs from the default, so pre-field plans keep their
        # goals_hash; flipping a goal either way still changes the hash
        # (ARCHITECTURE.md §15 "Goal dates").
        if o.get('date_type') == 'horizon':
            entry['date_type'] = 'horizon'
        cleaned.append(entry)
    cleaned.sort(key=lambda x: (str(x['target_date']), x['id'] or 0))
    return cleaned


def clean_constraints(constraints: List[Constraint]) -> List[Dict[str, Any]]:
    """The constraint fields that matter for planning, normalized and stably ordered.

    Single source of truth for both the constraints_hash fingerprint and the snapshot
    persisted on the macrocycle (see `clean_goals`). Fed only the plan-shaping
    (`replan = 1`) constraints by the caller, so tactical directives don't flag the
    plan stale (DESIGN_constraints.md §7).
    """
    cleaned = []
    for c in constraints:
        cleaned.append({
            'id': c.get('id'),
            'title': c.get('title'),
            'start_date': c.get('start_date'),
            'end_date': c.get('end_date'),
            'rest': int(c.get('rest') or 0),
            'description': c.get('description'),
        })
    cleaned.sort(key=lambda x: (str(x['start_date']), x['id'] or 0))
    return cleaned


def clean_constraints_all(constraints: List[Constraint]) -> List[Dict[str, Any]]:
    """Every active constraint, tagged with its `replan` flag — display only.

    `clean_constraints` above is fed only the `replan = 1` subset, so the plan's
    staleness fingerprint and snapshot never see a tactical directive. But the prompt
    (`_plan_generate_strategy`) renders *every* active constraint, so a `plan show`
    that reads only the fingerprinted subset can print "Constraints considered: None"
    while a tactical constraint plainly shaped the strategy. This is the same cleaning
    rule, just unfiltered and marked so a caller can tell plan-shaping from tactical.
    """
    cleaned = clean_constraints(constraints)
    replan_by_id = {c.get('id'): int(c.get('replan') or 0) for c in constraints}
    for entry in cleaned:
        entry['replan'] = replan_by_id.get(entry['id'], 0)
    return cleaned


def goals_hash(objectives: List[Objective]) -> str:
    """Computes a hash representation of objectives list to check for updates."""
    serialized = json.dumps(clean_goals(objectives), sort_keys=True)
    return hashlib.sha256(serialized.encode('utf-8')).hexdigest()


def constraints_hash(constraints: List[Constraint]) -> str:
    """Computes a hash representation of the plan-shaping constraints to check for
    updates (DESIGN_constraints.md §7 — computed over `replan = 1` constraints only)."""
    serialized = json.dumps(clean_constraints(constraints), sort_keys=True)
    return hashlib.sha256(serialized.encode('utf-8')).hexdigest()


_PROFILE_CHANGED = "athlete profile changed"
_SCIENCE_CHANGED = "training guidelines changed"


def _profile_change_reason(snapshot_raw: Optional[str]) -> str:
    """Why the profile fingerprint no longer matches, naming the fields when the plan
    carries a snapshot to compare against (DESIGN_plan_staleness.md §5).

    Falls back to the bare reason for a plan generated before the snapshot column, and for
    the one-off mismatch every pre-existing plan sees when the plan-shaping partition
    itself changes (§7) — in both cases the fields cannot be attributed honestly."""
    old_profile = _snapshot_profile(snapshot_raw)
    if old_profile is None:
        return _PROFILE_CHANGED
    fields = changed_plan_profile_fields(old_profile)
    return f"{_PROFILE_CHANGED}: {', '.join(fields)}" if fields else _PROFILE_CHANGED


def _snapshot_profile(snapshot_raw: Optional[str]) -> Optional[Dict[str, Any]]:
    """The plan-time profile a macrocycle carries, or None when it has none it can be
    held to (pre-snapshot plan, or a snapshot that does not parse)."""
    if not snapshot_raw:
        return None
    try:
        old_profile = json.loads(snapshot_raw)
    except (ValueError, TypeError):
        return None
    return old_profile if isinstance(old_profile, dict) else None


def _snapshot_science(snapshot_raw: Optional[str]) -> Optional[Dict[str, str]]:
    """The athlete's science documents as the plan saw them, {filename: text}, or None
    when the plan carries none it can be held to (DESIGN_plan_staleness.md §11)."""
    if not snapshot_raw:
        return None
    try:
        docs = json.loads(snapshot_raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(docs, dict):
        return None
    return docs if all(isinstance(v, str) for v in docs.values()) else None


def _profile_field_lines(value: Any) -> List[str]:
    """One field as lines a diff can work on: prose stays prose, structure becomes
    sorted JSON so a reordered dict does not read as a change."""
    if value is None:
        return []
    if isinstance(value, str):
        return value.splitlines()
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False).splitlines()


def _snapshot_records(snapshot_raw: Optional[str]) -> Optional[List[Dict[str, Any]]]:
    """The goal or constraint list a macrocycle carries, or None when it has none it can
    be held to (DESIGN_plan_change_continuity.md §6.5)."""
    if not snapshot_raw:
        return None
    try:
        records = json.loads(snapshot_raw)
    except (ValueError, TypeError):
        return None
    return records if isinstance(records, list) else None


def records_diff_text(
    old_records: List[Dict[str, Any]], new_records: List[Dict[str, Any]], label: str
) -> str:
    """A unified diff of two cleaned record lists, so a moved race date reads as the edit
    it is rather than as the word "goals" (§6.5). Empty when nothing differs."""
    if old_records == new_records:
        return ""
    lines = difflib.unified_diff(
        _profile_field_lines(old_records), _profile_field_lines(new_records),
        fromfile=f"{label} (when the plan was generated)", tofile=f"{label} (now)",
        lineterm="", n=1,
    )
    return "\n".join(lines)


def profile_diff_text(old_profile: Dict[str, Any]) -> str:
    """A unified diff per plan-shaping field that differs between `old_profile` and the
    live config, so the athlete and the coach see the same edit the flag names
    (DESIGN_plan_staleness.md §10). Empty when nothing differs."""
    current = plan_profile()
    old_profile = plan_shaping(old_profile)
    chunks = []
    for field in changed_plan_profile_fields(old_profile):
        lines = difflib.unified_diff(
            _profile_field_lines(old_profile.get(field)),
            _profile_field_lines(current.get(field)),
            fromfile=f"{field} (when the plan was generated)",
            tofile=f"{field} (now)", lineterm="", n=1,
        )
        chunks.append("\n".join(lines))
    return "\n\n".join(chunks)


def science_diff_text(old_docs: Dict[str, str]) -> str:
    """A unified diff per athlete science file that differs between `old_docs` and the
    directory now (§11). Empty when nothing differs."""
    current = athlete_science_documents()
    chunks = []
    for name in changed_science_documents(old_docs):
        lines = difflib.unified_diff(
            _profile_field_lines(old_docs.get(name)),
            _profile_field_lines(current.get(name)),
            fromfile=f"{name} (when the plan was generated)",
            tofile=f"{name} (now)", lineterm="", n=1,
        )
        chunks.append("\n".join(lines))
    return "\n\n".join(chunks)
