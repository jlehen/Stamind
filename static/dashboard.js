// The Dashboard tab: today's recovery and load numbers, the sync freshness line, the
// coach-memory summary, the goal and constraint listings, and the active coaching
// model (ARCHITECTURE.md §8). The strategy card the same tab shows is `plan.js`.

// --- STATUS (dashboard) ---

async function fetchStatus() {
    try {
        const res = await fetch(`${API_BASE}/api/status`);
        if (!res.ok) throw new Error("Failed to load status");
        const data = await res.json();

        const goalTitleEl = document.getElementById("header-goal-title");
        const goalCountdownEl = document.getElementById("header-goal-countdown");
        if (data.next_goal) {
            activeGoalId = data.next_goal.id;
            const sportsList = data.next_goal.sport_type
                .split(',').map(s => sportLabel(s.trim())).join(', ');
            goalTitleEl.innerText = `${data.next_goal.title} (${sportsList})`;

            const target = parseLocalDate(data.next_goal.target_date);
            const today = new Date();
            const diffDays = Math.ceil((target - today) / (1000 * 60 * 60 * 24));
            if (diffDays > 0) {
                goalCountdownEl.innerText = `${diffDays} days remaining`;
                goalCountdownEl.style.color = "var(--accent-cyan)";
            } else if (diffDays === 0) {
                goalCountdownEl.innerText = `Today is the day!`;
                goalCountdownEl.style.color = "var(--accent-green)";
            } else {
                goalCountdownEl.innerText = `Completed`;
                goalCountdownEl.style.color = "var(--text-muted)";
            }
        } else {
            activeGoalId = null;
            goalTitleEl.innerText = "No Active Goal";
            goalCountdownEl.innerText = "Add a goal with 'sm goal add'";
            goalCountdownEl.style.color = "var(--text-muted)";
        }

        updateMetrics(data.last_metrics, data.last_baseline);
        renderLearningsSummary(
            (data.coach_learnings && data.coach_learnings.learnings) || [],
            (data.coach_learnings && data.coach_learnings.summary) || null
        );
        renderSyncFreshness(data.sync_state);

        const strategyCard = document.getElementById("strategy-card");
        const noStrategyCard = document.getElementById("no-strategy-card");
        if (data.macrocycle && data.mesocycles && data.mesocycles.length > 0) {
            strategyCard.style.display = "block";
            if (noStrategyCard) noStrategyCard.style.display = "none";
            document.getElementById("strategy-philosophy").innerText =
                data.macrocycle.strategy;
            renderStrategyInputs(data.macrocycle);
            renderPlanFeedback(data.plan_feedback);
            renderTimeline(data.mesocycles, data.plan_feedback);

            if (data.macrocycle.created_at) {
                const created = new Date(data.macrocycle.created_at);
                const formattedDate = created.toLocaleDateString("en-US", {
                    weekday: "short", month: "short", day: "numeric", year: "numeric"
                });
                const formattedTime = created.toLocaleTimeString("en-US", {
                    hour: "numeric", minute: "2-digit"
                });
                document.getElementById("strategy-generated-at").innerText =
                    `Generated ${formattedDate} at ${formattedTime}`;
            } else {
                document.getElementById("strategy-generated-at").innerText = "";
            }
        } else {
            strategyCard.style.display = "none";
            if (noStrategyCard) noStrategyCard.style.display = "block";
        }

        const banner = document.getElementById("config-warning-banner");
        if (banner) {
            if (data.config_mismatch) {
                banner.style.display = "flex";
                logConsole(
                    "Warning: config.yaml has changed since the active periodization "
                    + "plan was generated. Run 'sm plan generate' to update.", "warning"
                );
            } else {
                banner.style.display = "none";
            }
        }
    } catch (e) {
        logConsole(`Error fetching status: ${e.message}`, "error");
    }
}

function renderLearningsSummary(learnings, summary) {
    const el = document.getElementById("memory-learnings");
    if (!el) return;
    if (!learnings || learnings.length === 0) {
        el.innerText = "No observations cached yet. Run 'sm data bootstrap' (CLI) to "
            + "reconstruct your training history and seed observations.";
        return;
    }
    let txt = `${summary ? summary.active : learnings.length} active observation(s)`;
    if (summary && summary.dormant) txt += ` · ${summary.dormant} dormant`;
    if (summary && summary.pending_demotion) txt += ` · ${summary.pending_demotion} pending demotion`;
    el.innerText = txt;
}

function renderSyncFreshness(syncState) {
    const el = document.getElementById("sync-freshness");
    if (!el) return;
    if (!syncState || (!syncState.through_date && !syncState.last_pull_utc)) {
        el.innerText = "Garmin data: never pulled — run 'sm data pull' (CLI).";
        return;
    }
    const through = syncState.through_date ? fmtDate(syncState.through_date) : "?";
    let ago = "";
    if (syncState.last_pull_utc) {
        const last = new Date(syncState.last_pull_utc);
        const hours = Math.floor((Date.now() - last) / 3600000);
        ago = hours < 1 ? " (just now)"
            : hours < 24 ? ` (${hours}h ago)`
            : ` (${Math.floor(hours / 24)}d ago)`;
    }
    el.innerText = `Garmin data through ${through}${ago} — pulling is CLI-only.`;
}

function updateMetrics(metrics, baseline) {
    // 1. HRV
    const hrvVal = document.querySelector("#metric-hrv .metric-value");
    const hrvBase = document.querySelector("#metric-hrv .metric-baseline");
    const hrvBadge = document.getElementById("hrv-badge");
    if (metrics && metrics.hrv) {
        hrvVal.innerHTML = `${metrics.hrv} <span class="unit">ms</span>`;
        if (baseline && baseline.hrv_baseline_mean) {
            hrvBase.innerText = `baseline: ${baseline.hrv_baseline_mean.toFixed(1)} ms`;
            const diff = metrics.hrv - baseline.hrv_baseline_mean;
            const std = baseline.hrv_baseline_std || 5.0;
            hrvBadge.style.display = "inline-block";
            if (diff < -1.5 * std) { hrvBadge.className = "status-badge badge badge-danger"; hrvBadge.innerText = "Suppressed"; }
            else if (diff < -1.0 * std) { hrvBadge.className = "status-badge badge badge-warning"; hrvBadge.innerText = "Fatigued"; }
            else { hrvBadge.className = "status-badge badge badge-success"; hrvBadge.innerText = "Balanced"; }
        } else { hrvBase.innerText = "baseline: N/A"; hrvBadge.style.display = "none"; }
    } else { hrvVal.innerText = "--"; hrvBase.innerText = "baseline: --"; hrvBadge.style.display = "none"; }

    // 2. RHR
    const rhrVal = document.querySelector("#metric-rhr .metric-value");
    const rhrBase = document.querySelector("#metric-rhr .metric-baseline");
    const rhrBadge = document.getElementById("rhr-badge");
    if (metrics && metrics.rhr) {
        rhrVal.innerHTML = `${metrics.rhr} <span class="unit">bpm</span>`;
        if (baseline && baseline.rhr_baseline_mean) {
            rhrBase.innerText = `baseline: ${baseline.rhr_baseline_mean.toFixed(1)} bpm`;
            const diff = metrics.rhr - baseline.rhr_baseline_mean;
            const std = baseline.rhr_baseline_std || 2.5;
            rhrBadge.style.display = "inline-block";
            if (diff > 2.0 * std || diff >= 5) { rhrBadge.className = "status-badge badge badge-danger"; rhrBadge.innerText = "Elevated"; }
            else if (diff > 1.0 * std || diff >= 3) { rhrBadge.className = "status-badge badge badge-warning"; rhrBadge.innerText = "Stressed"; }
            else { rhrBadge.className = "status-badge badge badge-success"; rhrBadge.innerText = "Normal"; }
        } else { rhrBase.innerText = "baseline: N/A"; rhrBadge.style.display = "none"; }
    } else { rhrVal.innerText = "--"; rhrBase.innerText = "baseline: --"; rhrBadge.style.display = "none"; }

    // 3. Sleep
    const sleepVal = document.querySelector("#metric-sleep .metric-value");
    const sleepBase = document.querySelector("#metric-sleep .metric-baseline");
    const sleepBadge = document.getElementById("sleep-badge");
    if (metrics && metrics.sleep_score) {
        sleepVal.innerHTML = `${metrics.sleep_score} <span class="unit">/100</span>`;
        if (baseline && baseline.sleep_baseline_mean) {
            sleepBase.innerText = `baseline: ${baseline.sleep_baseline_mean.toFixed(1)}`;
            sleepBadge.style.display = "inline-block";
            if (metrics.sleep_score < 60) { sleepBadge.className = "status-badge badge badge-danger"; sleepBadge.innerText = "Poor"; }
            else if (metrics.sleep_score < 75) { sleepBadge.className = "status-badge badge badge-warning"; sleepBadge.innerText = "Fair"; }
            else { sleepBadge.className = "status-badge badge badge-success"; sleepBadge.innerText = "Good"; }
        } else { sleepBase.innerText = "baseline: N/A"; sleepBadge.style.display = "none"; }
    } else { sleepVal.innerText = "--"; sleepBase.innerText = "baseline: --"; sleepBadge.style.display = "none"; }

    // 4. ATL:CTL — relative overload. Only the high end warns: a LOW ratio is a taper,
    // deload, or intensity block doing its job (training_load.md §3/§4).
    const ratioVal = document.querySelector("#metric-load-ratio .metric-value");
    const ratioBase = document.querySelector("#metric-load-ratio .metric-baseline");
    const ratioBadge = document.getElementById("load-ratio-badge");
    const ratio = (metrics && metrics.ctl > 0 && metrics.atl != null)
        ? metrics.atl / metrics.ctl : null;
    if (ratio !== null) {
        ratioVal.innerText = ratio.toFixed(2);
        ratioBase.innerText = `fatigue: ${metrics.atl.toFixed(0)} | fitness: ${metrics.ctl.toFixed(0)}`;
        ratioBadge.style.display = "inline-block";
        if (ratio > 1.5) { ratioBadge.className = "status-badge badge badge-danger"; ratioBadge.innerText = "Spike"; }
        else if (ratio > 1.3) { ratioBadge.className = "status-badge badge badge-warning"; ratioBadge.innerText = "Overload"; }
        else if (ratio >= 1.0) { ratioBadge.className = "status-badge badge badge-success"; ratioBadge.innerText = "Building"; }
        else { ratioBadge.className = "status-badge badge badge-info"; ratioBadge.innerText = "Unloading"; }
    } else { ratioVal.innerText = "--"; ratioBase.innerText = "fatigue: -- | fitness: --"; ratioBadge.style.display = "none"; }
}

// --- OBJECTIVES & CONSTRAINTS (read-only listings) ---

async function fetchObjectives() {
    try {
        const res = await fetch(`${API_BASE}/api/objectives`);
        if (!res.ok) throw new Error();
        const goals = await res.json();
        const container = document.getElementById("goals-list");
        container.innerHTML = "";
        if (goals.length === 0) {
            container.innerHTML = `<div class="item-meta" style="padding:0.5rem;">No goals yet.</div>`;
            return;
        }
        goals.forEach(g => {
            const sportsList = g.sport_type.split(',').map(s => sportTitle(s.trim())).join(', ');
            const item = document.createElement("div");
            item.className = "list-item";
            item.innerHTML = `
                <div class="item-info">
                    <span class="item-title">${escapeHtml(g.title)} (${escapeHtml(sportsList)})</span>
                    <span class="item-meta">ID ${g.id} · Target: ${escapeHtml(fmtDate(g.target_date))} · ${escapeHtml(g.status)}</span>
                    ${g.description ? `<span class="si-desc">${escapeHtml(g.description)}</span>` : ""}
                </div>`;
            container.appendChild(item);
        });
    } catch (e) {
        logConsole("Failed to load goals", "error");
    }
}

// A constraint is advisory prose the coach works around; the one toggle is `rest`, a
// deterministic full no-training window (DESIGN_constraints.md rev 6).
async function fetchEvents() {
    try {
        const res = await fetch(`${API_BASE}/api/constraints`);
        if (!res.ok) throw new Error();
        const events = await res.json();
        const container = document.getElementById("events-list");
        container.innerHTML = "";
        if (events.length === 0) {
            container.innerHTML = `<div class="item-meta" style="padding:0.5rem;">No active or upcoming constraints.</div>`;
            return;
        }
        events.forEach(ev => {
            const badge = ev.rest
                ? `<span class="badge badge-danger">no training</span>`
                : `<span class="badge badge-info">advisory</span>`;
            const item = document.createElement("div");
            item.className = "list-item";
            item.innerHTML = `
                <div class="item-info">
                    <span class="item-title">${escapeHtml(ev.title)} ${badge}</span>
                    <span class="item-meta">ID ${ev.id} · ${escapeHtml(fmtSpan(ev.start_date, ev.end_date, " → "))}`
                    + (ev.replan ? " · replan" : "") + `</span>
                    ${ev.description ? `<span class="si-desc">${escapeHtml(ev.description)}</span>` : ""}
                </div>`;
            container.appendChild(item);
        });
    } catch (e) {
        logConsole("Failed to load constraints", "error");
    }
}

// --- COACHING MODEL (`model list`) ---

async function fetchModels() {
    const el = document.getElementById("models-list");
    if (!el) return;
    try {
        const res = await fetch(`${API_BASE}/api/models`);
        const data = await res.json();
        const rows = data.models || [];
        if (!rows.length) { el.innerHTML = `<div class="item-meta">No models configured.</div>`; return; }
        const source = data.source ? ` <span class="item-meta">(${escapeHtml(data.source)})</span>` : "";
        el.innerHTML = `<div class="model-active">Active: <code>${escapeHtml(data.active || "?")}</code>${source}</div>`
            + rows.map(m => `<div class="model-row${m.active ? " is-active" : ""}">`
                + `<span class="model-num">${m.number == null ? "·" : m.number}</span>`
                + `<code>${escapeHtml(m.model)}</code>`
                + (m.active ? ` <span class="badge badge-success">active</span>` : "")
                + `</div>`).join("");
    } catch (e) {
        el.innerHTML = `<div class="item-meta">Failed to load models: ${escapeHtml(e.message)}</div>`;
    }
}

// --- INITIALIZATION ---
document.addEventListener("DOMContentLoaded", () => {
    fetchStatus();
    fetchObjectives();
    fetchEvents();
    fetchModels();
});
