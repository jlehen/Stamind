// The Workouts tab: the session cards, the plan-versus-actual compare, and the log of
// workout changes (ARCHITECTURE.md §8).

const SPORT_ICONS = {
    running: "fa-person-running", cycling: "fa-bicycle", hiking: "fa-mountain-sun",
    strength_training: "fa-dumbbell", yoga: "fa-spa", ski_touring: "fa-person-skiing-nordic",
    rowing: "fa-ship", downhill_skiing: "fa-person-skiing", resort_skiing: "fa-person-skiing",
    swimming: "fa-person-swimming", rest: "fa-bed",
};

// --- WORKOUTS (read-only listing) ---

async function fetchWorkouts() {
    try {
        const from = document.getElementById("wfilter-from").value || todayStr();
        const until = document.getElementById("wfilter-until").value;
        const sport = document.getElementById("wfilter-sport").value;
        const removed = document.getElementById("wfilter-removed").checked;

        const params = new URLSearchParams({ start_date: from });
        if (until) params.set("end_date", until);
        if (sport) params.set("sport_type", sport);
        if (removed) params.set("include_removed", "1");

        const res = await fetch(`${API_BASE}/api/workouts?${params}`);
        if (!res.ok) throw new Error();
        const workouts = await res.json();

        const container = document.getElementById("workouts-list-container");
        container.innerHTML = "";
        document.getElementById("workout-count").innerText = `${workouts.length} workouts`;

        if (workouts.length === 0) {
            container.innerHTML = `<div class="item-meta" style="text-align:center; padding: 2rem;">`
                + `No workouts in range. Generate some with 'sm workout generate'.</div>`;
            return;
        }
        workouts.forEach(w => container.appendChild(renderWorkoutCard(w)));
    } catch (e) { logConsole("Failed to load workouts", "error"); }
}

function renderWorkoutCard(w) {
    const dateObj = parseLocalDate(w.date);
    const dayNum = dateObj.getDate();
    const monthStr = dateObj.toLocaleDateString("en-US", { month: "short" });
    const weekdayStr = dateObj.toLocaleDateString("en-US", { weekday: "short" });

    // Derived facts come from the API (calendar_status / modification_markers),
    // mirroring the CLI markers (ARCHITECTURE.md §5).
    const modMarkers = w.modification_markers || [];
    const calStatus = w.calendar_status || "unpushed";
    const isRemoved = !!w.removed;

    let cardClass = "workout-card";
    if (isRemoved) cardClass += " removed";
    else if (modMarkers.length) cardClass += " adapted";
    else if (calStatus === "synced") cardClass += " synced";

    const iconGlyph = SPORT_ICONS[w.sport_type] || "fa-dumbbell";
    const iconClass = `workout-sport-icon ${w.sport_type || "rest"}`;

    const badges = [];
    // What became of a session already behind us, first because it is the salient state
    // for a finished day. The word comes from the API (`adherence.label`) rather than a
    // copy of the vocabulary here (ARCHITECTURE.md §5).
    const adherence = w.adherence;
    if (adherence && adherence.label) {
        const why = (adherence.reasons || []).join("; ");
        const title = why ? ` title="${escapeHtml(why)}"` : "";
        badges.push(`<span class="wbadge adh-${escapeHtml(adherence.status)}"${title}>`
            + `${escapeHtml(adherence.label.toUpperCase())}</span>`);
    }
    // One badge per marker: the kind of the latest change and the easings that still
    // stand (DESIGN_workout_revisions.md §12).
    for (const marker of modMarkers) {
        badges.push(`<span class="wbadge adapted">${escapeHtml(marker)}</span>`);
    }
    if (calStatus === "synced") badges.push(`<span class="wbadge synced">SYNCED</span>`);
    else if (calStatus === "stale") badges.push(`<span class="wbadge stale">STALE</span>`);
    if (isRemoved) badges.push(`<span class="wbadge removed">REMOVED</span>`);

    const stats = [];
    if (w.duration_minutes) stats.push(`${w.duration_minutes}min`);
    if (w.tss != null) stats.push(`TSS ${w.tss}`);
    if (w.rpe != null) stats.push(`RPE ${w.rpe}`);
    const statsHtml = stats.length ? `<span class="workout-stats">${stats.join(" · ")}</span>` : "";

    let reasonHtml = "";
    if (w.modification_reason) {
        reasonHtml = `<div class="workout-reason"><i class="fa-solid fa-triangle-exclamation"></i> ${escapeHtml(w.modification_reason)}</div>`;
    }
    let origHtml = "";
    if (w.original_description && w.original_description !== w.description) {
        origHtml = `<div class="workout-orig"><i class="fa-solid fa-clock-rotate-left"></i> Originally: ${escapeHtml(w.original_description)}</div>`;
    }
    let removedHtml = "";
    if (isRemoved && w.removed_reason) {
        removedHtml = `<div class="workout-reason"><i class="fa-solid fa-ban"></i> Cancelled: ${escapeHtml(w.removed_reason)}</div>`;
    }

    const item = document.createElement("div");
    item.className = cardClass;
    item.innerHTML = `
        <div class="workout-date">
            <span class="workout-day">${dayNum}</span>
            <span class="workout-month">${monthStr}</span>
            <span class="workout-weekday">${weekdayStr}</span>
        </div>
        <div class="workout-body">
            <span class="workout-title">${escapeHtml(w.title)} ${badges.join(" ")}</span>
            ${statsHtml}
            <span class="workout-desc">${escapeHtml(w.description)}</span>
            ${reasonHtml}${origHtml}${removedHtml}
        </div>
        <div class="${iconClass}"><i class="fa-solid ${iconGlyph}"></i></div>`;
    return item;
}

// --- COMPARE / ADHERENCE ---

async function runCompare() {
    const from = document.getElementById("cmp-from").value;
    const until = document.getElementById("cmp-until").value;
    const sport = document.getElementById("cmp-sport").value;
    const params = new URLSearchParams();
    if (from) params.set("start_date", from);
    if (until) params.set("end_date", until);
    if (sport) params.set("sport", sport);

    const target = document.getElementById("compare-results");
    target.innerHTML = `<div class="item-meta">Comparing...</div>`;
    try {
        const res = await fetch(`${API_BASE}/api/workouts/compare?${params}`);
        const data = await res.json();
        if (!res.ok) { target.innerHTML = `<div class="log-line error">${escapeHtml(data.error)}</div>`; return; }
        renderCompare(data);
    } catch (e) {
        target.innerHTML = `<div class="log-line error">Compare error: ${escapeHtml(e.message)}</div>`;
    }
}

function fmtActivity(u) {
    const a = u.activity;
    const parts = [`${(a.duration_sec / 60).toFixed(0)}min`, `load ${u.load}`];
    if (a.tss) parts.push(`TSS ${Math.round(a.tss)}`);
    if (a.rpe) parts.push(`RPE ${a.rpe}`);
    let s = `[${a.activity_type}] ${a.activity_name} (${parts.join(", ")})`;
    if (u.rpe_divergence) s += ` — HR under-counted ${u.rpe_divergence}x`;
    return s;
}

function renderCompare(data) {
    const target = document.getElementById("compare-results");
    target.innerHTML = "";

    const head = document.createElement("div");
    head.className = "item-meta compare-filters";
    head.innerText = `From ${fmtDate(data.filters.start_date)} `
        + `to ${fmtDate(data.filters.end_date)}` +
        (data.filters.sport ? ` · ${data.filters.sport}` : "");
    target.appendChild(head);

    if (!data.days.length) {
        target.insertAdjacentHTML("beforeend", `<div class="item-meta">No planned workouts or completed activities in this range.</div>`);
        return;
    }

    data.days.forEach(day => {
        const block = document.createElement("div");
        block.className = "compare-day";
        let html = `<div class="compare-date">${fmtDate(day.date)}</div>`;
        day.results.forEach(r => {
            const w = r.planned;
            const planned = r.is_rest ? `[REST]` :
                `[${sportLabel(w.sport_type)}] <strong>${escapeHtml(w.title)}</strong>` +
                (w.duration_minutes ? ` (${w.duration_minutes}min${w.tss != null ? ", TSS " + w.tss : ""})` : "");
            html += `<div class="compare-line"><span class="compare-label">PLANNED</span> ${planned}</div>`;
            if (r.completed) {
                const a = r.completed;
                const act = `[${a.activity_type}] ${escapeHtml(a.activity_name)} (${(a.duration_sec / 60).toFixed(0)}min${a.tss ? ", TSS " + Math.round(a.tss) : ""})`;
                const cls = r.rest_violation ? "actual-bad" : "actual-good";
                const tag = r.rest_violation ? ` <strong class="actual-bad">[REST VIOLATION]</strong>` : "";
                html += `<div class="compare-line"><span class="compare-label">ACTUAL</span> <span class="${cls}">${act}</span>${tag}</div>`;
            } else if (r.pending) {
                html += `<div class="compare-line"><span class="compare-label">ACTUAL</span> <span class="actual-muted">(not yet — still ahead today)</span></div>`;
            } else if (!r.is_rest) {
                html += `<div class="compare-line"><span class="compare-label">ACTUAL</span> <span class="actual-bad">(none — missed)</span></div>`;
            }
        });
        day.unplanned.forEach(u => {
            const label = u.kind === "minor" ? "(minor)" : u.kind === "off_plan" ? "(off-plan)" : "UNPLANNED";
            const cls = u.kind === "unplanned" ? "actual-warn" : "actual-muted";
            html += `<div class="compare-line"><span class="compare-label">${label}</span> <span class="${cls}">${escapeHtml(fmtActivity(u))}</span></div>`;
        });
        block.innerHTML = html;
        target.appendChild(block);
    });

    const summary = document.createElement("div");
    summary.className = "compare-summary";
    if (data.discrepancies.length) {
        summary.innerHTML = `<div class="compare-disc-head">${data.discrepancies.length} discrepanc${data.discrepancies.length !== 1 ? "ies" : "y"} found</div>` +
            // Each entry carries its facts plus a rendered `text`; the kind is exposed
            // as a data attribute so styling never has to read the sentence.
            data.discrepancies.map(d =>
                `<div class="actual-warn" data-kind="${escapeHtml(d.kind)}">${escapeHtml(d.text)}</div>`
            ).join("");
    } else {
        summary.innerHTML = `<div class="actual-good">No discrepancies found. Great adherence!</div>`;
    }
    if (data.informational && data.informational.length) {
        summary.innerHTML += `<div class="compare-disc-head" style="margin-top:0.75rem;">Outside any plan (informational)</div>` +
            data.informational.map(a => `<div class="actual-muted">${fmtDate(a.date)}: [${a.activity_type}] ${escapeHtml(a.activity_name)}</div>`).join("");
    }
    target.appendChild(summary);
}

// --- Workout changes (see DESIGN_workout_revisions.md §10; undoing one is
//     `sm workout rollback`) ---

async function loadWorkoutBatches() {
    const listEl = document.getElementById("workout-batches-list");
    if (!listEl) return;
    listEl.innerHTML = `<div class="item-meta">Loading batches…</div>`;
    try {
        const res = await fetch(`${API_BASE}/api/workouts/batches`);
        const data = await res.json();
        const batches = (data && data.batches) || [];
        if (!batches.length) {
            listEl.innerHTML = `<div class="item-meta">Nothing has written workouts yet. `
                + `Every command that does is listed here, and every one is undoable.</div>`;
            return;
        }
        listEl.innerHTML = batches.map(b => {
            const when = new Date(b.created_at).toLocaleString("en-US",
                { weekday: "short", month: "short", day: "numeric", year: "numeric",
                  hour: "2-digit", minute: "2-digit" });
            // A change that appended nothing — an adapt that held — is listed as itself.
            const state = b.held
                ? `<span class="item-meta">held</span>`
                : b.restorable
                    ? `<span class="item-meta">${b.restorable} upcoming</span>`
                    : `<span class="item-meta">all in the past</span>`;
            const plans = (b.macrocycle_ids || []).join(", ");
            const span = b.first_date
                ? `${escapeHtml(fmtSpan(b.first_date, b.last_date, " → "))}`
                : "nothing changed";
            return `<div class="plan-version-row">`
                + `<div class="plan-version-head">`
                + `<span class="badge badge-info">${escapeHtml(b.kind)}</span> `
                + `<span class="item-meta">${escapeHtml(when)}`
                + (plans ? ` · plan ID ${escapeHtml(plans)}` : "") + `</span>`
                + `<span class="plan-version-action">${state}</span></div>`
                + `<div class="si-desc">${span}</div>`
                + `</div>`;
        }).join("");
        listEl.insertAdjacentHTML("beforeend",
            `<div class="cli-guidance"><i class="fa-solid fa-terminal"></i> `
            + `Undo a change with <code>sm workout rollback</code>.</div>`);
    } catch (e) {
        listEl.innerHTML = `<div class="item-meta">Failed to load batches: ${escapeHtml(e.message)}</div>`;
    }
}

document.getElementById("workout-batches").addEventListener("toggle", (e) => {
    if (e.target.open) loadWorkoutBatches();
});

// --- SPORT FILTERS (the two <select>s above the lists) ---

/** Fills a <select> with the sports actually present in the data, so the filter can
 *  never fall behind the canonical sport list the way a hardcoded <option> set did. */
function populateSportFilter(selectEl, sports) {
    if (!selectEl) return;
    const current = selectEl.value;
    const opts = [`<option value="">All</option>`].concat(
        sports.map(s => `<option value="${escapeHtml(s)}">${escapeHtml(sportTitle(s))}</option>`)
    );
    selectEl.innerHTML = opts.join("");
    if (sports.includes(current)) selectEl.value = current;
}

/** Sport filters are built from the sports actually planned, so a newly-canonical sport
 *  appears here the moment it is used — the hardcoded <option> list this replaces had
 *  silently fallen behind the CLI's. */
async function populateSportFilters() {
    try {
        const res = await fetch(`${API_BASE}/api/workouts`);
        if (!res.ok) return;
        const workouts = await res.json();
        const sports = Array.from(new Set(workouts.map(w => w.sport_type).filter(Boolean))).sort();
        populateSportFilter(document.getElementById("wfilter-sport"), sports);
        populateSportFilter(document.getElementById("cmp-sport"), sports.filter(s => s !== "rest"));
    } catch (e) { /* filters simply stay at "All" */ }
}

// Filter/refresh buttons
document.getElementById("btn-workout-refresh").addEventListener("click", fetchWorkouts);
document.getElementById("btn-compare-run").addEventListener("click", runCompare);

// --- INITIALIZATION ---
document.addEventListener("DOMContentLoaded", () => {
    const wf = document.getElementById("wfilter-from");
    if (wf) wf.value = todayStr();

    populateSportFilters();
});
