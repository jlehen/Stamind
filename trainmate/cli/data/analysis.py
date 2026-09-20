"""`data bootstrap`, `data reflect` and `data show-analysis`: what the model made of the
past training.

Bootstrap reads the whole backlog once, reflect reads what has happened since the last
watermark, and show-analysis prints the reconstruction either of them stored, without
calling the model again (DESIGN_backward_evaluation.md).
"""
import argparse
from trainmate import athlete_queue, runtime
from trainmate.text import (
    bold, cmd, cyan, format_labeled_paragraph, format_labeled_text, gray, green, magenta,
    red, wrap_text, yellow,
)
from trainmate.output import notice
from trainmate.cli.selectors import resolve_window


# The learning-delta ops db.apply_learning_deltas acts on; anything else was skipped there,
# so the report must not present it as saved (DESIGN_backward_evaluation.md §13).
_LEARNING_OPS = ("add", "revise", "reinforce", "contradict", "retire")


def run_data_bootstrap(args: argparse.Namespace) -> None:
    """Cold-start reconstruction over the full training backlog (seeds learnings,
    establishes the reflect watermark)."""
    window = resolve_window(args)
    result = runtime.coach_service.data_bootstrap(
        from_date_str=window[0],
        until_date_str=window[1],
        context=args.context,
        force=args.force,
        inspect_only=args.inspect_only,
        no_pull=args.no_pull,
        force_pull=args.force_pull,
        auto=getattr(args, "auto", False),
    )
    _render_analysis_report(result, args.inspect_only)
    _doubts_hint(args)


def run_data_reflect(args: argparse.Namespace) -> None:
    """Incremental reflection over evidence accrued since the last reflect watermark."""
    window = resolve_window(args)
    result = runtime.coach_service.data_reflect(
        from_date_str=window[0],
        until_date_str=window[1],
        context=args.context,
        force=args.force,
        inspect_only=args.inspect_only,
        no_pull=args.no_pull,
        force_pull=args.force_pull,
    )
    # An empty result read nothing new, and the service already printed why.
    if result:
        _render_analysis_report(result, args.inspect_only)
    _doubts_hint(args)


def _doubts_hint(args: argparse.Namespace) -> None:
    """The queue hint where the end-of-run demotion prompt used to be: a run queues its
    doubts for the athlete instead of asking (DESIGN_learning_doubt_nudge.md §8)."""
    if not args.inspect_only:
        runtime.render.queue_hint(*athlete_queue.waiting_counts())


def run_data_show_analysis(args: argparse.Namespace) -> None:
    """Renders the stored reconstruction for one horizon slot; never recomputes it
    (DESIGN_backward_evaluation.md §5.1, forward consumer 3)."""
    horizon, source = ("short", "data reflect") if args.short else ("long", "data bootstrap")
    cached = runtime.db.get_analysis_cache(horizon)
    if not cached or not cached.get("reconstruction"):
        notice(f"No {horizon}-horizon reconstruction stored. Run "
               f"{cmd(source)} to build one.")
        return

    window = f"{cached.get('window_start')} to {cached.get('window_end')}"
    computed = (cached.get("created_at") or "")[:10]
    print()
    print(gray(wrap_text(f"From {cmd(source)} · window {window} · computed {computed}")))
    _render_analysis_report(cached["reconstruction"], inspect_only=False)

    # Training since the window closed is absent from the picture above, so say so rather
    # than let it read as current. Both slots point at reflect: bootstrap reads the backlog
    # once, so its slot falling behind is by design (DESIGN_backward_evaluation.md §5).
    window_end = cached.get("window_end")
    newer = [
        a for a in runtime.db.get_completed_activities(start_date=window_end)
        if a["date"] > window_end
    ] if window_end else []
    if not newer:
        return

    one = len(newer) == 1
    if horizon == "short":
        remedy = f"{cmd('data reflect')} folds {'it' if one else 'them'} in."
    else:
        remedy = (
            f"Bootstrap builds it once, so it will not catch up. {cmd('data reflect')} "
            f"follows the training since. Read it with {cmd('data show-analysis --short')}."
        )
    notice(
        f"{len(newer)} {'activity' if one else 'activities'} since {window_end} "
        f"{'post-dates' if one else 'post-date'} this analysis. {remedy}",
    )


def _render_analysis_report(result: dict, inspect_only: bool) -> None:
    """Renders a bootstrap/reflect reconstruction + applied coach learning deltas."""
    print(bold(cyan("\n=== HISTORICAL WORKOUT ANALYSIS REPORT ===")))
    
    # Macrocycle Overview. The reconstruction windows keep bare dates: labelled with
    # weekdays they outrun the bot's 48-column budget, and a window an analysis was run
    # over is read as a span, not as days to train on.
    if "inferred_macrocycle" in result:
        im = result["inferred_macrocycle"]
        print("\n" + format_labeled_paragraph(
            f"{bold('Macrocycle Focus')} "
            f"({magenta(im.get('start_date', ''))} to {magenta(im.get('end_date', ''))}):",
            im.get('overall_focus', 'N/A'), color_fn=cyan
        ))
    
    if "macrocycle_summary" in result:
        print(format_labeled_paragraph(f"{bold('Summary')}:", result["macrocycle_summary"]))

    # Inferred Mesocycles
    if "inferred_mesocycles" in result and result["inferred_mesocycles"]:
        print(bold(cyan("\nDetected Mesocycles:")))
        for meso in result["inferred_mesocycles"]:
            c_tag = meso.get("estimated_consistency", "Moderate")
            if c_tag == "High":
                c_disp = green("[High Consistency]")
            elif c_tag == "Low":
                c_disp = red("[Low Consistency]")
            else:
                c_disp = yellow("[Moderate Consistency]")

            print(format_labeled_text(
                "  - ",
                f"{green(meso.get('name', 'Phase'))} "
                f"({cyan(meso.get('start_date', ''))} to {cyan(meso.get('end_date', ''))}) "
                f"{c_disp}"
            ))
            print(format_labeled_paragraph(
                "    * Detected Focus:", str(meso.get('focus_detected', 'N/A'))
            ))
            print(f"    * Avg Weekly TSS: {meso.get('average_weekly_tss', 'N/A')}")

    # Physiological Insights
    if "physiological_insights" in result and result["physiological_insights"]:
        print(bold(cyan("\nPhysiological Insights:")))
        for insight in result["physiological_insights"]:
            print(format_labeled_text("  - ", str(insight)))

    # Coach learnings (incremental updates applied to learnings)
    updates = result.get("learning_updates")
    if updates:
        # "Saved" is a claim, so it is only made when some delta named an op the app
        # acts on — a response whose every delta is unreadable saved nothing (§13).
        saved_any = any(
            isinstance(u, dict) and u.get("op") in _LEARNING_OPS for u in updates
        )
        if inspect_only:
            header = "Coach Observations (NOT saved — inspect mode):"
        elif saved_any:
            header = "Coach Observations (Saved to learnings):"
        else:
            header = "Coach Observations (none saved — see below):"
        print(bold(cyan("\n" + header)))
        try:
            learnings_map = {l['id']: l for l in runtime.db.get_learnings()}
        except Exception:
            learnings_map = {}
        for u in updates:
            if not isinstance(u, dict):
                notice(f"  ! unreadable update ({type(u).__name__}) — skipped")
                continue
            op = u.get("op")
            meta = []
            if u.get("sports"):
                meta.append(u["sports"])
            ev = u.get("evidence")
            if isinstance(ev, (list, tuple)) and ev:
                meta.append(f"weeks: {', '.join(str(w) for w in ev)}")
            suffix = f" ({'; '.join(meta)})" if meta else ""

            def _existing_text(uid):
                if uid is not None and uid in learnings_map:
                    return learnings_map[uid]['text']
                return ""

            if op == "add":
                print(format_labeled_text("  + ", f"{u.get('text', '')}{suffix}"))
            elif op == "revise":
                print(format_labeled_text(
                    f"  ~ [{u.get('id')}] ", f"{u.get('text', '')}{suffix}"
                ))
            elif op == "reinforce":
                tag = f"  ↑ reinforced [{u.get('id')}]{suffix}"
                text = _existing_text(u.get("id"))
                print(format_labeled_paragraph(tag, text) if text else tag)
            elif op == "contradict":
                tag = f"  ↓ contradicted [{u.get('id')}]{suffix}"
                text = _existing_text(u.get("id"))
                print(format_labeled_paragraph(tag, text) if text else tag)
                if isinstance(u.get("reason"), str) and u["reason"].strip():
                    print(format_labeled_text("      because: ", u["reason"].strip()))
            elif op == "retire":
                print(f"  - retired [{u.get('id')}]")
            else:
                # Named no op the app knows, so nothing was saved for it. Printing the
                # skip keeps the section from rendering empty under a "Saved" header
                # (DESIGN_backward_evaluation.md §13).
                notice(f"  ! unreadable update (op={op!r}) — skipped")

    print(bold(cyan("\n==========================================")))
