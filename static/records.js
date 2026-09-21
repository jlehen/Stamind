// The three tabs that read the record back: Benchmarks, Learnings and History
// (ARCHITECTURE.md §8). Each is a hundred lines or less, too small for a file of
// its own.

// --- BENCHMARKS (DESIGN_benchmark_workouts.md) ---

async function fetchBenchmarks() {
    const listEl = document.getElementById("benchmarks-list");
    const stripEl = document.getElementById("thresholds-strip");
    const params = new URLSearchParams();
    const sport = document.getElementById("bfilter-sport").value.trim();
    const kind = document.getElementById("bfilter-kind").value.trim();
    if (sport) params.set("sport", sport);
    if (kind) params.set("kind", kind);

    try {
        const res = await fetch(`${API_BASE}/api/benchmarks?${params}`);
        const data = await res.json();
        if (!res.ok) {
            listEl.innerHTML = `<div class="item-meta">${escapeHtml(data.error || "Failed to load.")}</div>`;
            return;
        }

        const thresholds = data.thresholds || [];
        stripEl.innerHTML = thresholds.length
            ? `<div class="threshold-strip">` + thresholds.map(t =>
                // `formatted` already carries the unit (`benchmarks.format_value`), so the
                // box prints it alone rather than re-deriving or repeating the suffix.
                `<div class="threshold-box">`
                + `<div class="threshold-kind">${escapeHtml(t.label)}</div>`
                + `<div class="threshold-value">${escapeHtml(t.formatted)}</div></div>`).join("") + `</div>`
            : `<div class="item-meta">No thresholds on record. `
              + `Record a test with 'tm benchmark record'.</div>`;

        const rows = data.results || [];
        document.getElementById("benchmarks-count").innerText =
            `${rows.length} result${rows.length === 1 ? "" : "s"}`;
        if (!rows.length) {
            listEl.innerHTML = `<div class="item-meta">No benchmark results recorded yet.</div>`;
            return;
        }
        listEl.innerHTML = rows.map(r => {
            // `delta` already carries the direction-aware sign (a faster pace reads
            // positive), so the colour follows `improvement`, never the raw arithmetic.
            const delta = r.delta
                ? `<span class="bm-delta ${r.improvement ? "up" : "down"}">${escapeHtml(r.delta)}</span>`
                : `<span class="item-meta">first</span>`;
            return `<div class="bm-row">`
                + `<div class="bm-main">`
                + `<span class="bm-kind">${escapeHtml(r.label)}</span> `
                + `<span class="bm-value">${escapeHtml(r.formatted)}</span> ${delta}`
                + `</div>`
                + `<div class="item-meta">ID ${r.id} · ${escapeHtml(fmtDate(r.date))} · `
                + `${escapeHtml(sportTitle(r.sport_type))} · ${escapeHtml(r.source || "test")}</div>`
                + (r.note ? `<div class="si-desc">${escapeHtml(r.note)}</div>` : "")
                + `</div>`;
        }).join("");
    } catch (e) {
        listEl.innerHTML = `<div class="item-meta">Benchmark load error: ${escapeHtml(e.message)}</div>`;
    }
}

// --- LEARNINGS (read-only, with evidence) ---

async function fetchLearningsFull() {
    const sport = document.getElementById("lfilter-sport").value.trim();
    const confidence = document.getElementById("lfilter-confidence").value;
    const dormant = document.getElementById("lfilter-dormant").checked;
    const params = new URLSearchParams();
    if (sport) params.set("sport", sport);
    if (confidence) params.set("confidence", confidence);
    if (dormant) params.set("dormant", "1");

    const container = document.getElementById("learnings-list-container");
    try {
        const res = await fetch(`${API_BASE}/api/learnings?${params}`);
        const data = await res.json();
        const summary = data.summary || {};
        document.getElementById("learnings-summary-badge").innerText =
            `${summary.active || 0} active · ${summary.dormant || 0} dormant · ${summary.pending_demotion || 0} pending`;

        container.innerHTML = "";
        const learnings = data.learnings || [];
        if (!learnings.length) {
            container.innerHTML = `<div class="item-meta" style="padding:1rem;">No learnings match. `
                + `Run 'tm data bootstrap' (CLI) to seed observations.</div>`;
            return;
        }
        learnings.forEach(l => container.appendChild(renderLearningRow(l)));
    } catch (e) {
        container.innerHTML = `<div class="log-line error">Failed to load learnings: ${escapeHtml(e.message)}</div>`;
    }
}

function renderLearningRow(l) {
    const sports = l.sports || "general";
    const conf = l.confidence || "tentative";
    const row = document.createElement("div");
    row.className = "learning-item" + (l.dormant ? " dormant" : "");

    let proposed = "";
    if (l.proposed_confidence) {
        const tgt = l.proposed_confidence === "retire" ? "retire" : l.proposed_confidence;
        proposed = `<div class="learning-proposed">⚠ proposed demotion → ${escapeHtml(tgt)} `
            + `<span class="item-meta">— resolve with 'tm learnings demote ${l.id}' or `
            + `'tm learnings keep ${l.id}'</span></div>`;
    }
    row.innerHTML = `
        <div class="learning-main">
            <span class="learning-tag">[${l.id} · ${escapeHtml(sports)} · ${escapeHtml(conf)}]</span>
            ${escapeHtml(l.text)}
            ${l.dormant ? `<span class="learning-dormant">(dormant)</span>` : ""}
        </div>
        <div class="learning-actions"></div>
        ${proposed}
        <div class="learning-evidence" id="evidence-${l.id}" style="display:none;"></div>`;

    const actionsEl = row.querySelector(".learning-actions");
    const b = document.createElement("button");
    b.className = "btn-link";
    b.innerText = "evidence";
    b.addEventListener("click", () => toggleEvidence(l.id));
    actionsEl.appendChild(b);
    return row;
}

window.toggleEvidence = async function(id) {
    const box = document.getElementById(`evidence-${id}`);
    if (!box) return;
    if (box.style.display !== "none") { box.style.display = "none"; return; }
    box.style.display = "block";
    box.innerHTML = `<span class="item-meta">Loading evidence...</span>`;
    try {
        const res = await fetch(`${API_BASE}/api/learnings/${id}/evidence`);
        const data = await res.json();
        if (!res.ok) { box.innerHTML = `<span class="log-line error">${escapeHtml(data.error)}</span>`; return; }
        const fmt = (arr) => arr.length ? arr.map(e => e.week_commencing).join(", ") : "—";
        box.innerHTML =
            `<div class="evidence-line"><span class="evidence-pos">Supporting weeks:</span> ${fmt(data.supporting)}</div>` +
            `<div class="evidence-line"><span class="evidence-neg">Contradicting weeks:</span> ${fmt(data.contradicting)}</div>`;
    } catch (e) { box.innerHTML = `<span class="log-line error">${escapeHtml(e.message)}</span>`; }
};

// --- HISTORY (activities / metrics / signals) ---

function buildTable(rows, columns, emptyMsg) {
    if (!rows || !rows.length) return `<div class="item-meta">${emptyMsg}</div>`;
    const head = columns.map(c => `<th>${c.label}</th>`).join("");
    const body = rows.map(r => "<tr>" + columns.map(c => {
        let v = c.get ? c.get(r) : r[c.key];
        if (v == null) v = "";
        return `<td>${escapeHtml(String(v))}</td>`;
    }).join("") + "</tr>").join("");
    return `<table class="data-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

async function fetchHistory() {
    const from = document.getElementById("hist-from").value;
    const until = document.getElementById("hist-until").value;
    const range = new URLSearchParams();
    if (from) range.set("start_date", from);
    if (until) range.set("end_date", until);

    // Activities
    try {
        const res = await fetch(`${API_BASE}/api/activities?${range}`);
        const acts = await res.json();
        document.getElementById("activities-table").innerHTML = buildTable(acts, [
            { label: "Date", get: a => fmtDate(a.date) },
            { label: "Type", key: "activity_type" },
            { label: "Name", key: "activity_name" },
            { label: "Duration", get: a => `${(a.duration_sec / 60).toFixed(0)}min` },
            { label: "Dist (km)", get: a => a.distance_km != null ? a.distance_km.toFixed(1) : "" },
            { label: "Avg HR", key: "avg_hr" },
            { label: "TSS", get: a => a.tss != null ? Math.round(a.tss) : "" },
            { label: "RPE", key: "rpe" },
        ], "No activities in range.");
    } catch (e) { logConsole(`Activities load error: ${e.message}`, "error"); }

    // Metrics
    try {
        const res = await fetch(`${API_BASE}/api/metrics?${range}`);
        const metrics = await res.json();
        document.getElementById("metrics-table").innerHTML = buildTable(metrics, [
            { label: "Date", get: m => fmtDate(m.date) },
            { label: "RHR", key: "rhr" },
            { label: "HRV", key: "hrv" },
            { label: "Sleep", key: "sleep_score" },
            { label: "Stress", key: "stress" },
            { label: "ATL:CTL", get: m => (m.ctl > 0 && m.atl != null) ? (m.atl / m.ctl).toFixed(2) : "" },
        ], "No metrics in range.");
    } catch (e) { logConsole(`Metrics load error: ${e.message}`, "error"); }

    // Daily signals — vocabulary, calendar strips, then the raw rows.
    try {
        const [sigRes, vocabRes] = await Promise.all([
            fetch(`${API_BASE}/api/daily-signals?${range}`),
            fetch(`${API_BASE}/api/daily-signals/metrics`),
        ]);
        const sigs = await sigRes.json();
        const vocab = await vocabRes.json();
        renderSignalVocab(vocab.metrics || []);
        renderSignalChart(sigs);
        document.getElementById("signal-table").innerHTML = buildTable(sigs, [
            { label: "Date", get: r => fmtDate(r.date) },
            { label: "Metric", key: "metric" },
            { label: "Value", key: "value" },
            { label: "Note", key: "text" },
        ], "No daily signals in range.");
    } catch (e) { logConsole(`Signal load error: ${e.message}`, "error"); }
}

/** `signal list-metrics`: which signals exist at all, how many rows each has and the
 *  span it covers — the vocabulary behind the strips below. */
function renderSignalVocab(metrics) {
    const el = document.getElementById("signal-vocab");
    if (!el) return;
    if (!metrics.length) {
        el.innerHTML = `<div class="item-meta">No signals recorded. `
            + `Add one with 'tm signal add'.</div>`;
        return;
    }
    el.innerHTML = metrics.map(m =>
        `<span class="sig-chip" title="${escapeHtml(fmtSpan(m.first_date, m.last_date, " → "))}">`
        + `${escapeHtml(m.metric)} <span class="sig-chip-count">${m.count}</span></span>`).join("");
}

/** One row per metric, one cell per day in the loaded range: a calendar strip whose
 *  shading is the value's rank within that metric (metrics have no shared scale — sleep
 *  hours and units of alcohol cannot share a ramp). Days with no signal stay blank. */
function renderSignalChart(rows) {
    const el = document.getElementById("signal-chart");
    const badge = document.getElementById("signal-window-badge");
    if (!el) return;
    if (!rows || !rows.length) {
        el.innerHTML = "";
        if (badge) badge.innerText = "";
        return;
    }

    const dates = rows.map(r => r.date).sort();
    const start = parseLocalDate(dates[0]);
    const end = parseLocalDate(dates[dates.length - 1]);
    const days = [];
    for (let d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) {
        const pad = n => String(n).padStart(2, "0");
        days.push(`${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`);
    }
    if (badge) {
        badge.innerText = `${fmtSpan(dates[0], dates[dates.length - 1], " → ")}`
            + ` · ${rows.length} signals`;
    }

    const byMetric = new Map();
    rows.forEach(r => {
        if (!byMetric.has(r.metric)) byMetric.set(r.metric, new Map());
        byMetric.get(r.metric).set(r.date, r);
    });

    const html = Array.from(byMetric.entries()).map(([metric, byDate]) => {
        const values = Array.from(byDate.values())
            .map(r => Number(r.value)).filter(v => Number.isFinite(v));
        const min = values.length ? Math.min(...values) : 0;
        const max = values.length ? Math.max(...values) : 0;
        const cells = days.map(day => {
            const row = byDate.get(day);
            if (!row) return `<span class="sig-cell" title="${escapeHtml(day)}: —"></span>`;
            const v = Number(row.value);
            // A metric whose values never vary still deserves a visible mark, so a flat
            // series pins to full intensity rather than dividing by a zero span.
            const level = Number.isFinite(v) && max > min
                ? Math.round(((v - min) / (max - min)) * 4) + 1
                : 5;
            const label = [day, row.value != null ? `value ${row.value}` : null, row.text]
                .filter(Boolean).join(" · ");
            return `<span class="sig-cell lvl${level}" title="${escapeHtml(label)}"></span>`;
        }).join("");
        return `<div class="sig-row"><span class="sig-label">${escapeHtml(metric)}</span>`
            + `<span class="sig-strip">${cells}</span></div>`;
    }).join("");

    el.innerHTML = html
        + `<div class="item-meta sig-axis">${escapeHtml(days[0])} → ${escapeHtml(days[days.length - 1])}`
        + ` · shading is each signal's own range</div>`;
}

// Filter/refresh buttons
document.getElementById("btn-learnings-refresh").addEventListener("click", fetchLearningsFull);
document.getElementById("btn-history-refresh").addEventListener("click", fetchHistory);
document.getElementById("btn-benchmarks-refresh").addEventListener("click", fetchBenchmarks);
