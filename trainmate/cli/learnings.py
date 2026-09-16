import argparse
import sys
from typing import Optional

from trainmate import runtime
from trainmate.learning_doubts import contradiction_reasons
from trainmate.util import (
    bold, green, red, yellow, cyan, magenta, gray, cmd, fmt_timestamp, format_labeled_paragraph,
    format_labeled_text, notice,
)


def _confidence_color(conf: str):
    """Maps a confidence level to its display color function."""
    if conf == 'established':
        return green
    if conf == 'moderate':
        return yellow
    return gray


def _print_learning(l: dict) -> None:
    """Renders a single learning as a coloured [id|sports|confidence] tag + wrapped text.

    Shared by `learnings list` and `learnings show`; mirrors the legacy status rendering
    so the move out of `status` doesn't change how an individual learning reads."""
    sports_str = l.get('sports') or 'general'
    conf_str = l.get('confidence') or 'tentative'

    if l.get("archived") or l.get("dormant"):
        # Kept on record but no longer fed to the coach until restored or reaffirmed.
        state = "archived" if l.get("archived") else "dormant"
        tag = f"  [{l['id']}|{sports_str}|{conf_str}]"
        print(format_labeled_paragraph(gray(tag), gray(f"{l['text']} ({state})")))
    else:
        conf_disp = _confidence_color(conf_str)(conf_str)
        tag = f"  [{cyan(str(l['id']))}|{magenta(sports_str)}|{conf_disp}]"
        print(format_labeled_paragraph(tag, l['text']))

    # Pending, human-confirmable confidence downgrade (resolve with 'learnings demote'/'keep'
    # here, or through the question the reflect run queued for the athlete).
    proposed = l.get("proposed_confidence")
    if proposed:
        target = "retire" if proposed == "retire" else proposed
        notice(f"     ⚠ proposed demotion → {target} (confirm with "
               + cmd("learnings demote") + "/" + cmd("learnings keep") + ")")


def _echo_learning(learning_id: int) -> None:
    """Re-reads a just-mutated learning and echoes it in the `learnings list` format."""
    learning = runtime.db.get_learning(learning_id)
    if learning:
        _print_learning(learning)


def _not_found(learning_id: int) -> None:
    notice(f"Learning with ID {learning_id} not found.", red)
    sys.exit(1)


def print_learning_kept(learning: dict) -> None:
    """What keeping a doubted learning prints in the expert's words
    (DESIGN_learning_doubt_nudge.md §4)."""
    _print_learning(learning)
    print(green("Learning kept; pending demotion dismissed."))


def print_learning_demoted(learning_id: int, result: Optional[str]) -> None:
    """What accepting a pending demotion prints: the new level, or the archive (§4, §6)."""
    if result is None:
        notice(f"Learning with ID {learning_id} has no pending demotion.")
        return
    if result == "retired":
        print(green(f"Learning with ID {learning_id} retired and archived — "
                    + cmd(f"learnings restore {learning_id}") + " brings it back."))
        return
    _echo_learning(learning_id)
    print(green(f"Learning demoted to '{result}'."))


def _print_learning_dates(l: dict) -> None:
    """Prints the created/updated/reinforced timestamps shared by `list -v` and `show`."""
    for label, field in (
        ("created   ", "created_at"), ("updated   ", "updated_at"),
        ("reinforced", "last_reinforced_at"),
    ):
        value = l.get(field)
        print(f"  {label}: {fmt_timestamp(value) if value else '-'}")


def run_learning_list(args: argparse.Namespace) -> None:
    """Lists coach learnings, optionally filtered by sport, confidence, or dormancy.
    Archived learnings are hidden unless -a/--all (DESIGN_learning_doubt_nudge.md §6)."""
    learnings = runtime.db.get_learnings()

    if not getattr(args, "all", False):
        learnings = [l for l in learnings if not l.get("archived")]
    if getattr(args, "dormant", False):
        learnings = [l for l in learnings if l.get("dormant")]
    if getattr(args, "sport", None):
        needle = args.sport.lower()
        learnings = [l for l in learnings if needle in (l.get("sports") or "general").lower()]
    if getattr(args, "confidence", None):
        learnings = [l for l in learnings if (l.get("confidence") or "tentative") == args.confidence]

    print(bold(cyan("=== COACH LEARNINGS ===")))
    if not learnings:
        print(gray("No learnings match." if (
            getattr(args, "dormant", False) or getattr(args, "sport", None)
            or getattr(args, "confidence", None)
        ) else "None yet."))
        if not runtime.db.get_learnings():
            notice("Run " + cmd("data bootstrap")
                   + " to reconstruct your training history and seed observations.")
        return

    verbose = getattr(args, "verbose", False)
    for l in learnings:
        _print_learning(l)
        if verbose:
            _print_learning_dates(l)


def run_learning_show(args: argparse.Namespace) -> None:
    """Displays one learning, archived or not, with its full evidence basis (the 'why' behind
    its confidence) and what reflect said went against it."""
    learning = runtime.db.get_learning(args.id)
    if not learning:
        _not_found(args.id)

    _print_learning(learning)
    _print_learning_dates(learning)

    evidence = runtime.db.get_learning_evidence(args.id)
    sup = [e for e in evidence if e['polarity'] >= 0]
    con = [e for e in evidence if e['polarity'] < 0]
    print(bold("\n  Evidence basis:"))
    if not evidence:
        print(gray("    (none — confidence will decay without supporting weeks)"))
        return

    def _weeks(rows):
        return ", ".join(f"{r['week_commencing']}({r['source']})" for r in rows)

    print(green(f"    supporting ({len(sup)} wk): ") + (_weeks(sup) or "-"))
    if not con:
        return
    print(red(f"    contradicting ({len(con)} wk): ") + _weeks(con))
    for row in contradiction_reasons(args.id):
        print(format_labeled_text(f"      {', '.join(row['weeks'])}: ", row["reason"]))


def run_learning_edit(args: argparse.Namespace) -> None:
    """Revises the text of an existing learning."""
    if not runtime.db.get_learning(args.id):
        _not_found(args.id)

    runtime.db.update_learning(args.id, args.text)
    _echo_learning(args.id)
    print(green("Learning updated successfully."))


def run_learning_rm(args: argparse.Namespace) -> None:
    """Archives a learning by ID, or with --purge deletes it and its evidence for good
    (DESIGN_learning_doubt_nudge.md §6)."""
    if not runtime.db.get_learning(args.id):
        _not_found(args.id)

    if args.purge:
        runtime.db.delete_learning(args.id)
        print(green(f"Learning with ID {args.id} and its evidence deleted."))
        return
    if not runtime.db.archive_learning(args.id):
        notice(f"Learning with ID {args.id} is already archived. Add --purge to delete it.")
        return
    print(green(f"Learning with ID {args.id} archived — "
                + cmd(f"learnings restore {args.id}") + " brings it back."))


def run_learning_restore(args: argparse.Namespace) -> None:
    """Puts an archived learning back at tentative, with its evidence (§6)."""
    if not runtime.db.get_learning(args.id):
        _not_found(args.id)

    if not runtime.db.restore_learning(args.id):
        notice(f"Learning with ID {args.id} is not archived.")
        return
    _echo_learning(args.id)
    print(green("Learning restored at tentative."))


def run_learning_demote(args: argparse.Namespace) -> None:
    """Accepts a pending confidence downgrade for a learning."""
    runtime.render.learning_demoted(args.id, runtime.db.demote_learning(args.id))


def run_learning_keep(args: argparse.Namespace) -> None:
    """Dismisses a pending downgrade: the contradicting weeks behind it are overruled."""
    learning = runtime.db.get_learning(args.id)
    if not learning:
        _not_found(args.id)
    if not learning.get("proposed_confidence"):
        notice(f"Learning with ID {args.id} has no pending demotion to dismiss.")
        return

    runtime.db.keep_learning(args.id)
    runtime.render.learning_kept(runtime.db.get_learning(args.id))


def run_learning_wipe(args: argparse.Namespace) -> None:
    """Wipes all coach learnings from the database after confirmation."""
    if not args.yes:
        if not runtime.prompt.confirm(
            "Are you sure you want to wipe all coach learnings?", danger=True
        ):
            print("Wipe cancelled.")
            return

    runtime.db.wipe_learnings()
    print(green("All coach learnings wiped successfully."))


def add_learnings_parser(subparsers):
    # learnings command & subparsers
    learnings_parser = subparsers.add_parser(
        "learnings",
        help="View and curate coach learnings (LLM observations from your history)"
    )
    learnings_subparsers = learnings_parser.add_subparsers(
        dest="subcommand", help="Learnings sub-commands"
    )

    # learnings list
    ln_list = learnings_subparsers.add_parser(
        "list", help="Show coach learnings"
    )
    ln_list.set_defaults(func=run_learning_list)
    ln_list.add_argument(
        "--dormant", action="store_true", help="Show only dormant (decayed) learnings"
    )
    ln_list.add_argument(
        "-t", "--type", "--sport-type", "--sport", dest="sport",
        help="Filter by sport (substring match)"
    )
    ln_list.add_argument(
        "--confidence", choices=["tentative", "moderate", "established"], metavar="LEVEL",
        help="Filter by confidence level: %(choices)s"
    )
    ln_list.add_argument(
        "-a", "--all", action="store_true", help="Also show archived learnings"
    )
    ln_list.add_argument(
        "-v", "--verbose", action="store_true",
        help="Also show created/updated/reinforced timestamps"
    )

    # learnings show
    ln_show = learnings_subparsers.add_parser(
        "show", help="Show a learning and its evidence basis by ID"
    )
    ln_show.set_defaults(func=run_learning_show)
    ln_show.add_argument("id", type=int, help="Learning ID to display")

    # learnings edit
    ln_edit = learnings_subparsers.add_parser(
        "edit", help="Revise the text of a learning"
    )
    ln_edit.set_defaults(func=run_learning_edit)
    ln_edit.add_argument("id", type=int, help="Learning ID to edit")
    ln_edit.add_argument("text", help="New learning text")

    # learnings rm
    ln_rm = learnings_subparsers.add_parser(
        "rm", help="Archive a learning by ID (--purge deletes it)"
    )
    ln_rm.set_defaults(func=run_learning_rm)
    ln_rm.add_argument("id", type=int, help="Learning ID to archive")
    ln_rm.add_argument(
        "--purge", action="store_true",
        help="Delete the learning and its evidence for good instead of archiving it"
    )

    # learnings restore
    ln_restore = learnings_subparsers.add_parser(
        "restore", help="Put an archived learning back, at tentative"
    )
    ln_restore.set_defaults(func=run_learning_restore)
    ln_restore.add_argument("id", type=int, help="Learning ID to restore")

    # learnings demote
    ln_demote = learnings_subparsers.add_parser(
        "demote", help="Accept a pending confidence demotion"
    )
    ln_demote.set_defaults(func=run_learning_demote)
    ln_demote.add_argument("id", type=int, help="Learning ID to demote")

    # learnings keep
    ln_keep = learnings_subparsers.add_parser(
        "keep", help="Dismiss a pending demotion (affirms the learning)"
    )
    ln_keep.set_defaults(func=run_learning_keep)
    ln_keep.add_argument("id", type=int, help="Learning ID to keep")

    # learnings wipe
    ln_wipe = learnings_subparsers.add_parser(
        "wipe", advanced=True, help="Wipe all coach learnings")
    ln_wipe.set_defaults(func=run_learning_wipe)
    ln_wipe.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompt")

    return learnings_parser
