"""The argparse tree for the `plan` command family."""
from stamind.text import green
from stamind.cli.plans.feedback import RM_NO_ID, run_plan_feedback
from stamind.cli.plans.generate import run_plan_generate
from stamind.cli.plans.show import run_plan_keep, run_plan_show
from stamind.cli.plans.versions import (
    run_plan_diff, run_plan_rm, run_plan_rollback, run_plan_versions, run_plan_wipe,
)
from stamind.cli.selectors import CURRENT, parse_id_range


def add_plan_parser(subparsers, pull_bypass_parser, llm_debug_parser):
    # plan command & subparsers
    plan_parser = subparsers.add_parser(
        "plan",
        help="Manage and consult the periodized training plan (macrocycles & mesocycles)"
    )
    plan_subparsers = plan_parser.add_subparsers(
        dest="subcommand", help="Plan sub-commands"
    )
    
    # plan generate
    p_gen = plan_subparsers.add_parser(
        "generate",
        parents=[pull_bypass_parser, llm_debug_parser],
        help=(
            "Generate or adapt the periodized training plan strategy "
            "(macrocycles & mesocycles)"
        )
    )
    p_gen.set_defaults(func=run_plan_generate)
    p_gen.add_argument(
        "-f", "--force", action="store_true",
        help="Force regeneration of the macrocycle/mesocycle strategy"
    )
    p_gen.add_argument(
        "--fresh", action="store_true",
        help=(
            "Clean slate: don't show the model the plan currently in place, so the new "
            "strategy is not asked to continue it (implies --force). Your training "
            "history and plan feedback still feed in."
        )
    )
    # Not -m: that letter means "mesocycle" everywhere in the tree (DESIGN_cli_selectors.md §5).
    p_gen.add_argument(
        "--feedback", metavar="TEXT",
        help="Tell the coach what you think of the plan in place, then write the new one. "
             "The note is saved exactly as 'plan feedback \"TEXT\"' saves it: the new "
             "plan must address it along with any other pending note, and it stays "
             "pending if you decline the new plan"
    )
    p_gen.add_argument(
        "-y", "--yes", "--auto", action="store_true", dest="auto",
        help="Apply proposed plan updates automatically without prompting"
    )
    # Not -v: that letter already means "name each Calendar event" on three workout
    # sub-commands, and one letter meaning two things is what DESIGN_output_verbosity.md
    # §4 turned down a global --verbose for. This reads as the sibling it is of
    # --show-llm-prompt-only (§7).
    p_gen.add_argument(
        "--show-llm-context", action="store_true", dest="show_llm_context",
        help="Also print the planned-vs-actual review of your past plans that goes to "
             "the model as prompt context. Off by default: it is long, and it pushes "
             "the new strategy below the fold"
    )
    p_gen.add_argument(
        "-g", "--goal", "--goal-id", dest="goal_range", nargs="?", const=CURRENT,
        type=lambda raw: parse_id_range(raw, "goal"), metavar="RANGE",
        help="Goal(s) to plan for, as the shared range grammar: ID, ID.., ..ID or "
             "ID..ID (bare -g is the active goal). One ID plans that goal alone, bounded "
             "to its own span — the day after the goal before it, through its target "
             "date. A range plans every upcoming goal it covers, in date order, one "
             "strategy call each: '-g ..2' is everything through goal 2"
    )
    
    # plan show
    p_show = plan_subparsers.add_parser(
        "show",
        help="Show a macrocycle and its mesocycles periodization strategy "
             "(--goal/--macrocycle/--all, -w for workouts)",
        description=(
            "Show a periodization plan: the macrocycle strategy, the inputs it was "
            "generated from (goals, constraints, threshold anchors) and its mesocycle "
            "timeline. Flags any of those inputs that have changed since, and what to do "
            "about it. Defaults to the active plan of the next active goal; --goal reaches "
            "any goal including completed/archived ones, --macrocycle an earlier plan version, "
            "and --all every goal that has a plan."
        )
    )
    p_show.set_defaults(func=run_plan_show)
    p_show.add_argument(
        "-g", "--goal", "--goal-id", type=int, dest="goal_id",
        help="Target goal ID to show the periodization plan for (defaults to the next "
             "active goal)"
    )
    p_show.add_argument(
        "-M", "--macrocycle", type=int, dest="macrocycle_id", metavar="MACROCYCLE_ID",
        help="Show one macrocycle by ID — each plan version IS a macrocycle, so this is "
             "how you reach a superseded one ('plan versions' lists the IDs)"
    )
    p_show.add_argument(
        "-a", "--all", action="store_true",
        help="Show the active plan of every goal that has one (any status), oldest target "
             "date first"
    )
    p_show.add_argument(
        "-w", "--workouts", action="store_true",
        help="List each mesocycle's scheduled workouts, not just their count/load summary"
    )

    # plan keep
    p_keep = plan_subparsers.add_parser(
        "keep",
        help="Keep the current plan and stop flagging the inputs that changed",
        description=(
            "Record your current profile, goals and thresholds against the active plan "
            "without regenerating it. Use it when 'plan show' flags a changed input that "
            "would not have altered the periodization — a reworded preference, a "
            "corrected label — so the flag clears without spending a strategy call. The "
            "change still reaches your sessions at the next 'workout generate'."
        )
    )
    p_keep.set_defaults(func=run_plan_keep)
    p_keep.add_argument(
        "-g", "--goal", "--goal-id", type=int, dest="goal_id",
        help="Target goal ID whose plan to keep (defaults to the next active goal)"
    )

    # plan diff
    p_diff = plan_subparsers.add_parser(
        "diff", aliases=["df"],
        help="Compare two plan versions (strategy, mesocycles, inputs)",
        description=(
            "Compare two periodization plan versions field by field: what changed in the "
            "macrocycle strategy, which feedback notes each version carries, which "
            "mesocycles were added, removed, "
            "renamed or re-dated, and how the snapshotted inputs (goals, constraints, "
            "threshold anchors) differ. With no version given, compares the previous "
            "version against the active one; with one, that version against the active one."
        )
    )
    p_diff.set_defaults(func=run_plan_diff)
    p_diff.add_argument(
        "version_a", type=int, nargs="?", metavar="PLAN_ID_A",
        help="Older plan version to compare from (defaults to the previous version)"
    )
    p_diff.add_argument(
        "version_b", type=int, nargs="?", metavar="PLAN_ID_B",
        help="Newer plan version to compare to (defaults to the active version)"
    )
    p_diff.add_argument(
        "-g", "--goal", "--goal-id", type=int, dest="goal_id",
        help="Target goal ID whose plan versions to compare (defaults to the next active goal)"
    )
    p_diff.add_argument(
        "--full", action="store_true",
        help="Diff wholesale-rewritten prose sentence by sentence instead of collapsing it "
             "to a one-line note"
    )

    # plan versions
    p_versions = plan_subparsers.add_parser(
        "versions",
        help="List all plan versions (active + superseded) for a goal",
        description=(
            "List every periodization plan version kept for a goal — the active one and "
            "any superseded by later regenerations — with their IDs and dates, so you can "
            "inspect one ('plan show --macrocycle <ID>') or restore one "
            "('plan rollback --macrocycle <ID>')."
        )
    )
    p_versions.set_defaults(func=run_plan_versions)
    p_versions.add_argument(
        "-g", "--goal", "--goal-id", type=int, dest="goal_id",
        help="Target goal ID whose plan versions to list (defaults to the next active goal)"
    )

    # plan rm
    p_rm = plan_subparsers.add_parser(
        "rm", advanced=True,
        help="Remove/delete a specific periodization plan by Goal ID",
        description=(
            "Delete every periodization plan version a goal owns — superseded ones "
            "included, so the goal is left with no plan history at all. Its mesocycle "
            "mesocycles and plan feedback go with them, and upcoming sessions are left "
            "behind with no plan to explain them. The inventory is shown before "
            f"anything is deleted. Use '{green('plan generate --force')}' to replace a "
            f"plan reversibly, or '{green('plan rollback')}' to step back one "
            "regeneration."
        )
    )
    p_rm.set_defaults(func=run_plan_rm)
    p_rm.add_argument(
        "id", type=int,
        help="Goal ID whose periodization plan should be removed"
    )
    p_rm.add_argument(
        "-y", "--yes", action="store_true", help="Skip confirmation prompt"
    )

    # plan rollback
    p_rollback = plan_subparsers.add_parser(
        "rollback", aliases=["rb"],
        help="Restore a superseded plan version and its workouts",
        description=(
            "Undo a plan regeneration: restore an earlier periodization plan version "
            "and the workouts that were live under it. Defaults to the chronologically "
            "previous version of the next active goal's plan; repeat to walk further "
            "back, or target a specific version with --macrocycle. The current plan's "
            "upcoming workouts are archived and the restored version's are re-pushed to "
            "Google Calendar (the symmetric inverse of generation)."
        )
    )
    p_rollback.set_defaults(func=run_plan_rollback)
    p_rollback.add_argument(
        "-g", "--goal", "--goal-id", type=int, dest="goal_id",
        help="Target goal ID whose plan to roll back (defaults to the next active goal)"
    )
    p_rollback.add_argument(
        "-M", "--macrocycle", type=int, dest="macrocycle_id", metavar="MACROCYCLE_ID",
        help="Roll back to a specific plan version (macrocycle) ID instead of the previous one"
    )
    p_rollback.add_argument(
        "-y", "--yes", action="store_true", help="Skip confirmation prompt"
    )

    # plan feedback
    p_fb = plan_subparsers.add_parser(
        "feedback",
        help="Tell the coach what you think of the plan (bare run lists pending notes)",
        description=(
            "Leave a note about the plan for the next 'plan generate' to read. Notes "
            "accumulate against the active plan — a second thought adds to the first "
            "rather than replacing it — and are consumed when a new version supersedes "
            "the one they were written against. Bare text is plan-level; -m files the "
            "note to one mesocycle, by name, date or ID. A bare run lists what is pending; "
            "nothing here calls the LLM, so capture is instant."
        )
    )
    # `_parser` lets the handler route `--rm` with no ID back through argparse's own
    # missing-argument path (DESIGN_cli_noargs.md §a).
    p_fb.set_defaults(func=run_plan_feedback, _parser=p_fb)
    p_fb.add_argument(
        "text", nargs="?", default=None,
        help="The note to append (omit to list what is pending)"
    )
    p_fb.add_argument(
        "-m", "--mesocycle", dest="meso", nargs="?", const=CURRENT, metavar="ATOM",
        help="File the note to ONE mesocycle of any upcoming goal's plan: its name (any "
             "part of it), a date it covers (YYYY-MM-DD, today, -7d, +2w) or its mesocycle "
             "ID. Bare -m is the current mesocycle; without -m the note is plan-level"
    )
    p_fb.add_argument(
        "-g", "--goal", "--goal-id", type=int, dest="goal_id",
        help=(
            "Target goal ID whose plan the feedback should attach to (defaults to the "
            "plan -m names, else the next active goal); with -m, only that plan is searched"
        )
    )
    p_fb.add_argument(
        "--rm", nargs="?", type=int, const=RM_NO_ID, default=None, metavar="ID",
        help="Delete one pending note by ID (the bare listing shows them)"
    )
    p_fb.add_argument(
        "-y", "--yes", action="store_true", help="Skip the --rm confirmation prompt"
    )
    p_fb.add_argument(
        "--replan", action="store_true",
        help="After saving, regenerate the plan straight away (same preview-and-confirm "
             "as 'plan generate'; no --force needed)"
    )

    # plan wipe
    p_wipe = plan_subparsers.add_parser(
        "wipe", advanced=True, help="Wipe all periodization plans")
    p_wipe.set_defaults(func=run_plan_wipe)
    p_wipe.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompt")
    

    return plan_parser
