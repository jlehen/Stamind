// The plan: the goals and constraints it was generated from, its mesocycle timeline,
// the feedback filed against it, and the comparison between two of its versions
// (ARCHITECTURE.md §8). It draws the Dashboard tab's strategy card, which is why
// `dashboard.js` calls in here from fetchStatus.

// --- THE STRATEGY CARD ---

/** One note of the plan's feedback log: date, what it was filed to, the text. */
function feedbackNote(n) {
    const date = n.created_at ? fmtDate(String(n.created_at).slice(0, 10)) : "";
    return `<div class="pf-note">`
        + `<span class="pf-meta">${escapeHtml(date)}`
        + ` · ${escapeHtml(n.mesocycle_name || "plan-level")}</span>`
        + `<span class="si-desc">${escapeHtml(n.text || "")}</span></div>`;
}

/** The notes the athlete addressed to the next plan version. Read-only here: they are
 *  written with `tm plan feedback` and are consumed by the next generation
 *  (DESIGN_plan_feedback.md §8). */
function renderPlanFeedback(notes) {
    const el = document.getElementById("strategy-feedback");
    if (!el) return;
    const all = notes || [];
    if (!all.length) { el.innerHTML = ""; return; }
    el.innerHTML = `<div class="si-heading"><i class="fa-solid fa-comments"></i> `
        + `Your feedback on this plan (${all.length} pending)</div>`
        + all.map(feedbackNote).join("");
}

// Renders the goals and constraints the plan was generated from. These are snapshotted
// on the macrocycle (server-side), so they reflect the inputs the plan was built on
// rather than the current live records, which may since have changed.
function renderStrategyInputs(macrocycle) {
    const el = document.getElementById("strategy-inputs");
    if (!el) return;

    const rawGoals = macrocycle.goals_snapshot;
    // New snapshots carry constraint fields; legacy plans (pre-constraints-rename)
    // carry the old lifeevents_snapshot — read whichever is present.
    const rawEvents = macrocycle.constraints_snapshot ?? macrocycle.lifeevents_snapshot;
    // Every active constraint at generation time (not just the replan=1 subset `rawEvents`
    // fingerprints), tagged with `replan`. Null on plans predating this column.
    const rawAllEvents = macrocycle.all_constraints_snapshot;
    if (rawGoals == null && rawEvents == null) {
        el.innerHTML = `<div class="strategy-inputs-note">`
            + `Inputs considered: not recorded (plan predates input snapshots).</div>`;
        return;
    }

    let goals = [], events = [], allEvents = null;
    try { goals = rawGoals ? JSON.parse(rawGoals) : []; } catch (e) { goals = []; }
    try { events = rawEvents ? JSON.parse(rawEvents) : []; } catch (e) { events = []; }
    try { allEvents = rawAllEvents ? JSON.parse(rawAllEvents) : null; } catch (e) { allEvents = null; }
    // The tactical (replan=0) constraints the prompt saw but the fingerprint didn't —
    // shown separately so "Constraints considered" never reads as "None" while one of
    // these plainly shaped the strategy text.
    const tactical = allEvents ? allEvents.filter(e => !e.replan) : null;

    const goalItems = goals.length
        ? goals.map(g => `<li>`
            + `<span class="si-title">${escapeHtml(g.title || "")}</span> `
            + `<span class="si-meta">(${escapeHtml((g.sport_type || "").toUpperCase())}) `
            + `· ${escapeHtml(fmtDate(g.target_date))}</span>`
            + (g.description ? `<div class="si-desc">${escapeHtml(g.description)}</div>` : "")
            + `</li>`).join("")
        : `<li class="si-empty">None</li>`;

    const constraintItems = (list) => list.length
        ? list.map(e => {
            // Snapshots are historical: tolerate the current `rest` flag, the pre-rev-6
            // binding/sport/type, and the original event_type/impact_description.
            const label = e.type || e.event_type || "";
            const enforcement = "rest" in e
                ? (e.rest ? "no training" : "advisory")
                : (e.binding || "");
            const tags = [label, enforcement, e.sport ? `[${e.sport}]` : ""]
                .filter(Boolean).map(escapeHtml).join(" ");
            const detail = e.description || e.impact_description;
            return `<li>`
                + `<span class="si-title">${escapeHtml(e.title || "")}</span> `
                + `<span class="si-meta">(${tags}) `
                + `· ${escapeHtml(fmtSpan(e.start_date, e.end_date, " → "))}</span>`
                + (detail ? `<div class="si-desc">${escapeHtml(detail)}</div>` : "")
                + `</li>`;
        }).join("")
        : `<li class="si-empty">None</li>`;

    const tacticalSection = tactical ? `
            <div class="si-section">
                <div class="si-heading"><i class="fa-solid fa-calendar-check"></i> Also active (tactical — did not trigger replan)</div>
                <ul class="si-list">${constraintItems(tactical)}</ul>
            </div>` : "";

    el.innerHTML = `
        <details class="strategy-inputs-details">
            <summary>Inputs considered (${goals.length} goal${goals.length === 1 ? "" : "s"}, `
                + `${events.length} constraint${events.length === 1 ? "" : "s"})</summary>
            <div class="si-section">
                <div class="si-heading"><i class="fa-solid fa-flag-checkered"></i> Goals considered</div>
                <ul class="si-list">${goalItems}</ul>
            </div>
            <div class="si-section">
                <div class="si-heading"><i class="fa-solid fa-calendar-day"></i> Constraints considered (plan-shaping)</div>
                <ul class="si-list">${constraintItems(events)}</ul>
            </div>${tacticalSection}
        </details>`;
}

function renderTimeline(mesocycles, planFeedback) {
    const container = document.getElementById("web-timeline-container");
    if (!container) return;
    container.innerHTML = "";

    const detailsBox = document.getElementById("cycle-details-box");
    const detailsName = document.getElementById("cycle-details-name");
    const detailsDates = document.getElementById("cycle-details-dates");
    const detailsFocus = document.getElementById("cycle-details-focus");
    const detailsFeedback = document.getElementById("cycle-details-feedback");

    if (!mesocycles || mesocycles.length === 0) {
        detailsBox.style.display = "none";
        return;
    }

    mesocycles.sort((a, b) => parseLocalDate(a.start_date) - parseLocalDate(b.start_date));
    const overallStart = parseLocalDate(mesocycles[0].start_date);
    const overallEnd = parseLocalDate(mesocycles[mesocycles.length - 1].end_date);
    const totalDays = Math.ceil((overallEnd - overallStart) / (1000 * 60 * 60 * 24)) + 1;

    const today = new Date();
    today.setHours(0, 0, 0, 0);
    let activeBlockEl = null;

    mesocycles.forEach(m => {
        const start = parseLocalDate(m.start_date);
        const end = parseLocalDate(m.end_date);
        const duration = Math.ceil((end - start) / (1000 * 60 * 60 * 24)) + 1;
        const widthPct = totalDays > 0 ? (duration / totalDays) * 100 : 100;

        const block = document.createElement("div");
        block.className = "cycle-block";
        block.style.width = `${widthPct}%`;
        block.innerText = m.name;
        block.title = `${m.name} (${fmtSpan(m.start_date, m.end_date)})`;

        let status = "future";
        if (end < today) status = "done";
        else if (start <= today && today <= end) status = "active";
        block.classList.add(status);

        block.addEventListener("click", () => {
            document.querySelectorAll(".cycle-block").forEach(el => el.classList.remove("selected"));
            block.classList.add("selected");
            detailsBox.style.display = "block";
            detailsName.innerText = m.name;
            detailsDates.innerText =
                `${fmtSpan(m.start_date, m.end_date)} (${duration} days)`;
            detailsFocus.innerText = m.focus;
            const filed = (planFeedback || []).filter(n => n.mesocycle_id === m.id);
            detailsFeedback.innerHTML = filed.length
                ? `<div class="si-heading"><i class="fa-solid fa-comment-medical"></i> `
                  + `Mesocycle feedback</div>`
                  + filed.map(feedbackNote).join("")
                : "";
        });

        container.appendChild(block);
        if (status === "active") activeBlockEl = block;
    });

    const defaultSelect = activeBlockEl || container.firstElementChild;
    if (defaultSelect) defaultSelect.click();
}

// --- Plan versions & comparison (see DESIGN_plan_rollback.md; rolling back is
//     `tm plan rollback`, a CLI action) ---

async function loadPlanVersions() {
    const listEl = document.getElementById("plan-versions-list");
    if (!listEl) return;
    listEl.innerHTML = `<div class="item-meta">Loading versions…</div>`;
    try {
        const params = activeGoalId != null ? `?goal_id=${activeGoalId}` : "";
        const res = await fetch(`${API_BASE}/api/plan/versions${params}`);
        const data = await res.json();
        const versions = (data && data.versions) || [];
        if (versions.length <= 1) {
            listEl.innerHTML = `<div class="item-meta">No earlier versions yet. `
                + `Regenerating this plan keeps the previous version here so you can compare it.</div>`;
            return;
        }
        listEl.innerHTML = versions.map(v => {
            const active = v.status !== "superseded";
            const created = v.created_at
                ? new Date(v.created_at).toLocaleDateString("en-US",
                    { weekday: "short", month: "short", day: "numeric", year: "numeric" })
                : "?";
            let excerpt = (v.strategy || "").replace(/\s+/g, " ").trim();
            if (excerpt.length > 90) excerpt = excerpt.slice(0, 89) + "…";
            const badge = active
                ? `<span class="badge badge-success">ACTIVE</span>`
                : `<span class="badge badge-info">superseded</span>`;
            const action = active
                ? `<span class="item-meta">current</span>`
                : `<button class="btn btn-secondary btn-sm" data-diff="${v.id}" `
                  + `title="Compare this version against the active plan">`
                  + `<i class="fa-solid fa-code-compare"></i> Compare</button>`;
            return `<div class="plan-version-row">`
                + `<div class="plan-version-head">${badge} `
                + `<span class="item-meta">ID ${v.id} · generated ${escapeHtml(created)}</span>`
                + `<span class="plan-version-action">${action}</span></div>`
                + (excerpt ? `<div class="si-desc">${escapeHtml(excerpt)}</div>` : "")
                + `</div>`;
        }).join("");
        listEl.querySelectorAll("button[data-diff]").forEach(btn => {
            btn.addEventListener("click", () => loadPlanDiff(btn.dataset.diff));
        });
        listEl.insertAdjacentHTML("beforeend",
            `<div class="cli-guidance"><i class="fa-solid fa-terminal"></i> `
            + `Restore one with <code>tm plan rollback --version &lt;id&gt;</code>.</div>`);
        hidePlanDiff();
    } catch (e) {
        listEl.innerHTML = `<div class="item-meta">Failed to load versions: ${escapeHtml(e.message)}</div>`;
    }
}

// --- Plan version comparison (GET /api/plan/diff; same structure the CLI's
// `plan diff` renders as text — see trainmate/plan_versions.py) ---

function hidePlanDiff() {
    const panel = document.getElementById("plan-diff-panel");
    if (panel) { panel.style.display = "none"; panel.innerHTML = ""; }
}

function diffLine(marker, text, cls) {
    return `<div class="pd-line pd-${cls}">`
        + `<span class="pd-marker">${marker}</span>`
        + `<span class="pd-text">${escapeHtml(text)}</span></div>`;
}

/** Renders one prose comparison. A passage the coach rewrote wholesale stays collapsed
 *  behind a disclosure — expanded, it is just both versions in full (the web equivalent
 *  of the CLI's --full). */
function renderProse(prose) {
    if (!prose || !prose.changed) return `<div class="pd-empty">unchanged</div>`;
    const lines = prose.groups.map(b =>
        b.removed.map(s => diffLine("−", s, "removed")).join("")
        + b.added.map(s => diffLine("+", s, "added")).join("")
    ).join("");
    if (!prose.rewritten) return lines;
    return `<details class="pd-rewritten"><summary>`
        + `rewritten (${prose.old_count} sentences → ${prose.new_count}) — show sentences`
        + `</summary>${lines}</details>`;
}

/** Each version's own feedback notes. An append-only log is not prose-diffed: for
 *  adjacent versions, A's notes are what drove B (DESIGN_plan_feedback.md §8). */
function renderFeedbackSides(entry) {
    if (!entry) return `<div class="pd-empty">none</div>`;
    return ["from", "to"].map((side, i) => {
        const notes = entry[side] || [];
        const body = notes.length
            ? notes.map(n => `<div class="pd-detail">${escapeHtml(fmtDate(n.date))} · `
                + `${escapeHtml(n.filing || "plan-level")} · ${escapeHtml(n.text)}</div>`).join("")
            : `<div class="pd-empty">none</div>`;
        return `<div class="pd-detail"><b>${i === 0 ? "A" : "B"}</b>:</div>${body}`;
    }).join("");
}

function renderMesocycles(entries) {
    const changed = (entries || []).filter(e => e.change !== "unchanged");
    if (!changed.length) return `<div class="pd-empty">unchanged</div>`;
    return changed.map(e => {
        if (e.change === "added" || e.change === "removed") {
            const added = e.change === "added";
            return diffLine(added ? "+" : "−",
                `${e.name} (${fmtSpan(e.dates.start, e.dates.end, " → ")})`,
                added ? "added" : "removed");
        }
        const header = e.renamed ? `${e.from_name}  →  ${e.name}` : e.name;
        let out = diffLine("~", header, "changed");
        if (e.dates) {
            out += `<div class="pd-detail">dates `
                + `${escapeHtml(fmtSpan(e.dates.from.start, e.dates.from.end, " → "))}`
                + `  ⇒  ${escapeHtml(fmtSpan(e.dates.to.start, e.dates.to.end, " → "))}</div>`;
        }
        for (const f of e.fields) {
            out += `<div class="pd-detail">${escapeHtml(f.field)}: `
                + `${escapeHtml(f.from ?? "—")}  ⇒  ${escapeHtml(f.to ?? "—")}</div>`;
        }
        if (e.focus) out += `<div class="pd-detail pd-focus">focus:</div>` + renderProse(e.focus);
        return out;
    }).join("");
}

/** A plan predating a snapshot column has nothing recorded — never read that as the
 *  inputs having been deleted. */
function renderMissing(missing) {
    if (missing === "both") return `<div class="pd-empty">not recorded on either version</div>`;
    const side = missing === "old" ? "A" : "B";
    return `<div class="pd-empty">not recorded on ${side} — that plan predates the snapshot</div>`;
}

function renderRecords(diff) {
    if (diff.missing) return renderMissing(diff.missing);
    if (!diff.added.length && !diff.removed.length && !diff.changed.length) {
        return `<div class="pd-empty">unchanged</div>`;
    }
    return diff.removed.map(r => diffLine("−", `[ID ${r.id}] ${r.title || ""}`, "removed")).join("")
        + diff.added.map(r => diffLine("+", `[ID ${r.id}] ${r.title || ""}`, "added")).join("")
        + diff.changed.map(r => diffLine("~", `[ID ${r.id}] ${r.title}`, "changed")
            + r.fields.map(f => `<div class="pd-detail">${escapeHtml(f.field)}: `
                + `${escapeHtml(String(f.from))}  ⇒  ${escapeHtml(String(f.to))}</div>`).join("")
        ).join("");
}

function renderThresholds(diff) {
    if (diff.missing) return renderMissing(diff.missing);
    if (!diff.added.length && !diff.removed.length && !diff.changed.length) {
        return `<div class="pd-empty">unchanged</div>`;
    }
    return diff.removed.map(t => diffLine("−", `${t.key}: ${t.value}`, "removed")).join("")
        + diff.added.map(t => diffLine("+", `${t.key}: ${t.value}`, "added")).join("")
        + diff.changed.map(t => diffLine("~",
            `${t.key}: ${t.from}  ⇒  ${t.to}`
            + (t.pct != null ? ` (${t.pct >= 0 ? "+" : ""}${t.pct.toFixed(1)}%)` : ""),
            "changed")).join("");
}

function diffSection(title, body) {
    return `<div class="pd-section"><div class="si-heading">${title}</div>${body}</div>`;
}

async function loadPlanDiff(fromVersion) {
    const panel = document.getElementById("plan-diff-panel");
    if (!panel) return;
    panel.style.display = "block";
    panel.innerHTML = `<div class="item-meta">Comparing…</div>`;
    try {
        const params = new URLSearchParams({ from_version: fromVersion });
        if (activeGoalId != null) params.set("goal_id", activeGoalId);
        const res = await fetch(`${API_BASE}/api/plan/diff?${params}`);
        const data = await res.json();
        if (!res.ok) {
            panel.innerHTML = `<div class="item-meta">${escapeHtml(data.error || "Comparison failed.")}</div>`;
            return;
        }
        const d = data.diff;
        const when = v => v.created_at
            ? new Date(v.created_at).toLocaleDateString("en-US",
                { weekday: "short", month: "short", day: "numeric", year: "numeric" })
            : "?";
        panel.innerHTML = `<div class="pd-head">`
            + `<span class="pd-title">Plan ID ${d.from.id} <span class="pd-arrow">→</span> `
            + `ID ${d.to.id}</span>`
            + `<span class="item-meta">${escapeHtml(when(d.from))} → ${escapeHtml(when(d.to))}</span>`
            + `<button class="btn btn-secondary btn-sm pd-close" id="btn-close-plan-diff">`
            + `<i class="fa-solid fa-xmark"></i></button></div>`
            + diffSection("Strategy", renderProse(d.strategy))
            + diffSection("Athlete feedback", renderFeedbackSides(d.feedback))
            + diffSection("Mesocycles", renderMesocycles(d.mesocycles))
            + diffSection("Goals considered", renderRecords(d.goals))
            + diffSection("Constraints considered", renderRecords(d.constraints))
            + diffSection("Thresholds considered", renderThresholds(d.thresholds));
        document.getElementById("btn-close-plan-diff")
            .addEventListener("click", hidePlanDiff);
    } catch (e) {
        panel.innerHTML = `<div class="item-meta">Comparison error: ${escapeHtml(e.message)}</div>`;
    }
}

document.getElementById("plan-versions").addEventListener("toggle", (e) => {
    if (e.target.open) loadPlanVersions();
});
