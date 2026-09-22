// The Progress tab: the time-in-zone tables and the server-rendered timeline PNG
// (ARCHITECTURE.md §8). Each half names its own design section below.

/** A zone cell's time, capped to four characters exactly as `progress_zones.fmt_zone_cell`
 *  renders it in the terminal — `55m`, `5h00`, `12h`, `—` for none. */
function fmtZoneCell(seconds) {
    const minutes = Math.round((seconds || 0) / 60);
    if (minutes <= 0) return "—";
    if (minutes < 60) return `${minutes}m`;
    const hours = Math.floor(minutes / 60);
    return hours >= 10 ? `${hours}h` : `${hours}h${String(minutes % 60).padStart(2, "0")}`;
}

function fmtDuration(seconds) {
    const minutes = Math.round((seconds || 0) / 60);
    if (minutes < 60) return `${minutes}min`;
    return `${Math.floor(minutes / 60)}h${String(minutes % 60).padStart(2, "0")}`;
}

// --- TIME IN ZONE (DESIGN_intensity_distribution.md §9.6/§9.8) ---
// The web form of `sm progress -z`: one table per qualifying sport, measured behind
// today and prescribed ahead of it. Every judgement (which sports, which currency, what
// counts as undercounted) is made server-side by the same functions the CLI calls — this
// only draws the result.

let zonesWeeks = "8";

async function fetchZones() {
    const container = document.getElementById("zones-container");
    if (!container) return;
    container.innerHTML = `<div class="item-meta">Loading zone distribution…</div>`;
    const params = new URLSearchParams({ weeks: zonesWeeks });
    const currency = document.getElementById("zfilter-currency").value;
    if (currency) params.set("currency", currency);
    try {
        const res = await fetch(`${API_BASE}/api/zones?${params}`);
        const data = await res.json();
        if (!res.ok) {
            container.innerHTML = `<div class="item-meta">${escapeHtml(data.error || "Zones unavailable.")}</div>`;
            return;
        }
        renderZones(data);
    } catch (e) {
        container.innerHTML = `<div class="item-meta">Zone load error: ${escapeHtml(e.message)}</div>`;
    }
}

function renderZones(data) {
    const container = document.getElementById("zones-container");
    const badge = document.getElementById("zones-window-badge");
    if (badge) {
        const w = data.window || {};
        badge.innerText = `${w.weeks === "all" ? "all weeks" : `${w.weeks} weeks`} `
            + `· ${fmtDuration(w.window_seconds || 0)} total`;
    }

    const parts = [];
    const sports = data.sports || [];
    if (!sports.length) {
        parts.push(`<div class="item-meta">No sport has recorded zone data in this window. `
            + `Zones come from HR or power streams on synced activities.</div>`);
    }

    sports.forEach(s => {
        const nZones = s.zone_labels.length;
        const header = `<div class="zone-head">`
            + `<span class="zone-sport">${escapeHtml(sportTitle(s.sport))}</span>`
            + `<span class="badge badge-info">${escapeHtml(s.tag)} ${Math.round((s.coverage || 0) * 100)}%</span>`
            + `<span class="item-meta">${fmtDuration(s.sport_seconds)} in window</span>`
            + `</div>`;

        const cols = s.zone_labels.map((_, i) => `<th>Z${i + 1}</th>`).join("");
        const rows = s.weeks.map(wk => {
            const cells = [];
            const total = (wk.seconds || []).reduce((a, b) => a + b, 0);
            for (let i = 0; i < nZones; i++) {
                const secs = wk.seconds ? wk.seconds[i] : 0;
                cells.push(`<td>${escapeHtml(fmtZoneCell(secs))}</td>`);
            }
            // The stacked bar is the web's addition over the terminal: the same numbers,
            // read as a shape. Weeks with nothing recorded draw no bar at all.
            const bar = total > 0
                ? `<div class="zone-bar">` + (wk.seconds || []).map((secs, i) =>
                    secs > 0
                        ? `<span class="zone-seg z${i + 1}" style="width:${(secs / total) * 100}%" `
                          + `title="Z${i + 1} ${escapeHtml(s.zone_labels[i])}: ${escapeHtml(fmtZoneCell(secs))}"></span>`
                        : ""
                  ).join("") + `</div>`
                : `<div class="zone-bar empty"></div>`;

            const marks = [];
            if (wk.undercounted) marks.push(`<span class="zone-mark" title="recording covered less of this week than the sport's bar — the row understates it">!</span>`);
            if (wk.in_progress) marks.push(`<span class="zone-mark" title="week in progress">*</span>`);
            if (wk.currency_mismatch) marks.push(`<span class="zone-mark" title="planned in the other currency; not converted">≠</span>`);

            const cls = ["zone-row"];
            if (wk.future) cls.push("future");
            if (wk.in_progress) cls.push("current");
            return `<tr class="${cls.join(" ")}">`
                + `<td class="zone-week">${escapeHtml(wk.week_commencing)}${marks.join("")}</td>`
                + cells.join("")
                + `<td class="zone-bar-cell">${bar}</td></tr>`;
        }).join("");

        parts.push(`<div class="zone-table-wrap">${header}`
            + `<table class="data-table zone-table"><thead><tr><th>Week</th>${cols}<th></th></tr></thead>`
            + `<tbody>${rows}</tbody></table></div>`);
    });

    const om = data.omitted || {};
    const notes = [];
    if ((om.low_volume || []).length) {
        notes.push(`${om.low_volume.map(sportTitle).join(", ")} omitted `
            + `(under ${Math.round((om.min_share || 0.1) * 100)}% of the window's duration)`);
    }
    if ((om.no_zone_data || []).length) {
        notes.push(`${om.no_zone_data.map(sportTitle).join(", ")} omitted (no zone data)`);
    }
    if ((data.window || {}).hidden_weeks) {
        notes.push(`${data.window.hidden_weeks} more week(s) outside this window`);
    }
    notes.push(`weeks past today show what the plan prescribes`);
    parts.push(`<div class="item-meta zone-legend">${escapeHtml(notes.join(" · "))}</div>`);

    container.innerHTML = parts.join("");
}

// --- PROGRESS TAB (DESIGN_progress_timeline.md §7.3) ---
// V1 is the picture, not an app: an <img> pointing at GET /api/timeline.png plus
// quick-range buttons that set ?weeks= and reload it. The empty / still-warming
// states are drawn inside the PNG by the server renderer, identical to the bot
// photo. A 503 (matplotlib missing) shows the endpoint's install hint verbatim.

let progressWeeks = "8";

async function fetchProgress() {
    const img = document.getElementById("progress-image");
    const errEl = document.getElementById("progress-image-error");
    const url = `${API_BASE}/api/timeline.png?weeks=${progressWeeks}`;
    try {
        const res = await fetch(url);
        if (!res.ok) {
            // 503 (matplotlib absent) or 400 (bad weeks) — show the body text.
            const text = await res.text();
            img.style.display = "none";
            errEl.style.display = "";
            errEl.textContent = text || `Progress chart unavailable (HTTP ${res.status}).`;
            return;
        }
        const blob = await res.blob();
        if (img.dataset.objectUrl) URL.revokeObjectURL(img.dataset.objectUrl);
        const objectUrl = URL.createObjectURL(blob);
        img.dataset.objectUrl = objectUrl;
        img.src = objectUrl;
        img.style.display = "";
        errEl.style.display = "none";
    } catch (e) {
        logConsole(`Progress load error: ${e.message}`, "error");
    }
}

document.querySelectorAll(".progress-range-btn").forEach(btn => {
    btn.addEventListener("click", () => {
        document.querySelectorAll(".progress-range-btn").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        progressWeeks = btn.dataset.weeks;
        zonesWeeks = btn.dataset.weeks;
        fetchProgress();
        fetchZones();
    });
});

// The refresh button
document.getElementById("btn-zones-refresh").addEventListener("click", fetchZones);
