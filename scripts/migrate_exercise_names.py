#!/usr/bin/env python3
"""One-off conversion: the exercise names stored before the exercise table become keys
(DESIGN_exercise_table.md §9). Run again after two lines of the table are merged, it moves
what is stored under the name that stopped being a key to the key of its line (§3.2).

It rewrites three places: `exercise_sets.exercise`, `prescribed_sets.exercise`, and the `n`
of every entry in `gym_logs.payload`. It leaves `workouts.description` alone, and a stored
log's `v`. Before anything it stops while a "what was this?" question or a proposal waits
in the queue. It prints every stored old name with the key it becomes, writes nothing while
one of them is not settled, and otherwise writes after a yes. A second run changes nothing.

It operates on the instance named by `STAMIND_CONFIG`, or on the default config when that
variable is unset. Run it once per athlete, from the repository root, with the bots stopped
(§9 has the operator's steps):

    venv/bin/python scripts/migrate_exercise_names.py \\
        --rename "back squat=SQUAT/BARBELL_BACK_SQUAT" --rename "plank=PLANK/PLANK"

`--db PATH` converts that file instead of the instance's database, to try it on a copy.
`--yes` writes without asking.
"""
import argparse
import json
import os
import sqlite3
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional

# Run as `venv/bin/python scripts/<this>` from the repo root: sys.path[0] is scripts/,
# so the package root has to be put on the path explicitly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stamind.cli.workouts.proposal import KIND as PROPOSAL  # noqa: E402
from stamind.config import CONFIG_PATH, config  # noqa: E402
from stamind.strength import vocabulary  # noqa: E402
from stamind.strength.sets import SET_NAMES, fmt_kg  # noqa: E402

MIGRATION_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "exercise_name_migration.tsv"
)
SETS, PRESCRIBED, LOGS = "exercise_sets", "prescribed_sets", "gym_logs"
COUNTED = (
    (SETS, "set", "sets"), (PRESCRIBED, "planned line", "planned lines"),
    (LOGS, "log entry", "log entries"),
)


@dataclass
class Stored:
    """One stored old name: where it is, and the key it becomes, None while not settled."""
    place: str
    row: object            # the row's id; for a log, (activity_id, index of the entry)
    old: str
    key: Optional[str]
    loads: List[float]


def is_old(name: Optional[str]) -> bool:
    """Whether a stored value is still an old name: those are lower case, keys upper case. So
    is a name whose line was merged into another, which the table now holds as a later name
    of that line (§3.2)."""
    if not name:
        return False
    if any(letter.islower() for letter in name):
        return True
    return vocabulary.key_of(name) not in (None, name)


def read_migration(path: str = MIGRATION_PATH) -> Dict[str, List[str]]:
    """For each old name, the keys of the classes its line became."""
    listed: Dict[str, List[str]] = {}
    with open(path, encoding="utf-8") as table:
        for line in table:
            if not line.strip() or line.startswith("#"):
                continue
            old, keys = line.rstrip("\n").split("\t")
            listed[old] = keys.split()
    return listed


def parse_renames(given: List[str]) -> Dict[str, str]:
    """`--rename "old name=KEY"` as a dict. A key the table lacks stops the script."""
    renames: Dict[str, str] = {}
    for one in given:
        old, _, key = one.partition("=")
        if vocabulary.get(key.strip()) is None:
            raise SystemExit(f"--rename \"{one}\": {key.strip()!r} is not a key of the table.")
        renames[old.strip()] = key.strip()
    return renames


def new_key(
    old: str, said: Optional[str], renames: Dict[str, str], listed: Dict[str, List[str]]
) -> Optional[str]:
    """The five rules, in order: a rename, the key of the line a merged name now sits on, the
    one key of the list, the class holding the set's own Garmin name `said` when it is one of
    several keys, else not settled."""
    if old in renames:
        return renames[old]
    if vocabulary.key_of(old):
        return vocabulary.key_of(old)
    keys = listed.get(old, [])
    if len(keys) == 1:
        return keys[0]
    own = vocabulary.key_of(said)
    if own in keys:
        return own
    return None


def waiting_items(conn: sqlite3.Connection) -> List[sqlite3.Row]:
    """The "what was this?" questions and the proposals still waiting in the queue."""
    return conn.execute(
        "SELECT id, kind, queued_at FROM athlete_queue "
        "WHERE closed_at IS NULL AND kind IN (?, ?) ORDER BY id",
        (SET_NAMES, PROPOSAL),
    ).fetchall()


def stored_names(
    conn: sqlite3.Connection, renames: Dict[str, str], listed: Dict[str, List[str]]
) -> List[Stored]:
    """Every value of the three places that is still an old name."""
    found: List[Stored] = []
    for row in conn.execute("SELECT id, exercise, garmin_name, load_kg FROM exercise_sets"):
        if not is_old(row["exercise"]):
            continue
        key = new_key(row["exercise"], row["garmin_name"], renames, listed)
        loads = [] if row["load_kg"] is None else [row["load_kg"]]
        found.append(Stored(SETS, row["id"], row["exercise"], key, loads))
    for row in conn.execute("SELECT id, exercise, load_kg FROM prescribed_sets"):
        if not is_old(row["exercise"]):
            continue
        key = new_key(row["exercise"], None, renames, listed)
        loads = [] if row["load_kg"] is None else [row["load_kg"]]
        found.append(Stored(PRESCRIBED, row["id"], row["exercise"], key, loads))
    for row in conn.execute("SELECT activity_id, payload FROM gym_logs"):
        for index, entry in enumerate(json.loads(row["payload"])["x"]):
            old = entry["n"].strip()
            if not is_old(old):
                continue
            loads = [float(one[1]) for one in entry["sets"] if one[1] is not None]
            found.append(Stored(LOGS, (row["activity_id"], index), old,
                                new_key(old, None, renames, listed), loads))
    return found


def unsettled(found: List[Stored]) -> List[str]:
    """The names with a stored occurrence that has no key: a name is settled only when
    every stored occurrence of it is."""
    return sorted({one.old for one in found if one.key is None})


def _loads(loads: List[float]) -> str:
    if not loads:
        return "no load"
    low, high = min(loads), max(loads)
    if low == high:
        return f"{fmt_kg(low)} kg"
    return f"{fmt_kg(low)}–{fmt_kg(high)} kg"


def report(found: List[Stored], listed: Dict[str, List[str]]) -> List[str]:
    """One line per old name and the key it becomes, with how often it is stored and its
    loads. A name not settled has no key there, and one whose sets go to several keys has a
    line per key."""
    left = unsettled(found)
    groups: Dict[tuple, List[Stored]] = {}
    for one in found:
        key = "" if one.old in left else one.key
        groups.setdefault((one.old, key), []).append(one)
    lines: List[str] = []
    for (old, key), members in sorted(groups.items()):
        counts = []
        for place, one_word, many_word in COUNTED:
            count = sum(1 for one in members if one.place == place)
            if not count:
                continue
            counts.append(f"{count} {one_word if count == 1 else many_word}")
        loads = _loads([load for one in members for load in one.loads])
        lines.append(f"  {old}  →  {key or 'NOT SETTLED'}   ({', '.join(counts)}; {loads})")
        if not key and listed.get(old):
            lines.append(f"      one of: {', '.join(listed[old])}")
    return lines


def write(conn: sqlite3.Connection, found: List[Stored]) -> None:
    """Rewrites every found value to its key, in one transaction."""
    logs: Dict[str, Dict[int, str]] = {}
    for one in found:
        if one.place == LOGS:
            activity_id, index = one.row
            logs.setdefault(activity_id, {})[index] = one.key
            continue
        conn.execute(f"UPDATE {one.place} SET exercise = ? WHERE id = ?", (one.key, one.row))
    for activity_id, entries in logs.items():
        payload = json.loads(conn.execute(
            "SELECT payload FROM gym_logs WHERE activity_id = ?", (activity_id,)
        ).fetchone()["payload"])
        for index, key in entries.items():
            payload["x"][index]["n"] = key
        conn.execute(
            "UPDATE gym_logs SET payload = ? WHERE activity_id = ?",
            (json.dumps(payload, separators=(",", ":"), ensure_ascii=False), activity_id),
        )
    conn.commit()


def convert(db_path: str, renames: Dict[str, str], yes: bool) -> int:
    """The whole run on one database file. Returns the exit code: 0 when the file holds no
    old name afterwards."""
    listed = read_migration()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        waiting = waiting_items(conn)
        if waiting:
            print("These wait in the queue, and a tap on one would write old names. Answer "
                  "each with `sm queue answer ID`, then run this again:")
            for item in waiting:
                print(f"  id {item['id']}  {item['kind']}  queued {item['queued_at']}")
            return 1
        found = stored_names(conn, renames, listed)
        if not found:
            print("No old name is stored. Nothing to convert.")
            return 0
        print("\n".join(report(found, listed)))
        left = unsettled(found)
        if left:
            print(f"\nNot settled: {', '.join(left)}. Nothing was written. Give a rename "
                  "for each:")
            for old in left:
                print(f"  --rename \"{old}=KEY\"")
            return 1
        if not yes and input(f"\nRewrite these {len(found)} values? [y/N] ").lower() != "y":
            print("Nothing was written.")
            return 1
        write(conn, found)
        print(f"\nRewrote {len(found)} values.")
        return 0
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rename", action="append", default=[], metavar="OLD=KEY",
                        help="What the athlete lifted under an old name. Repeatable")
    parser.add_argument("--db", metavar="PATH",
                        help="Convert this file instead of the instance's database")
    parser.add_argument("--yes", action="store_true", help="Write without asking")
    args = parser.parse_args()
    renames = parse_renames(args.rename)
    db_path = args.db or config.db_path
    print(f"Instance: {CONFIG_PATH}")
    print(f"Database: {db_path}")
    if not os.path.exists(db_path):
        print("No database there. Nothing to convert.")
        return 0
    return convert(db_path, renames, args.yes)


if __name__ == "__main__":
    sys.exit(main())
