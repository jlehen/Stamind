// Stamind dashboard — a READ-ONLY view over the database (ARCHITECTURE.md §8).
// Nothing here writes: the API refuses every mutating verb, so each panel that used to
// carry a button now names the CLI command that does the job instead.
//
// This file is what every panel shares: the API base, the date and sport formatting, the
// console log and the tab switch. There is no module system and no bundler here, so it
// has to load first — ARCHITECTURE.md §8 lists the script order and what rests on it.

const API_BASE = "";
let activeGoalId = null;
const loadedTabs = new Set(["view-dashboard"]);

// Logging helper
function logConsole(message, type = "success") {
    const consoleLogs = document.getElementById("console-logs");
    if (!consoleLogs) return;

    const timestamp = new Date().toLocaleTimeString();
    const line = document.createElement("div");
    line.className = `log-line ${type}`;
    line.innerText = `[${timestamp}] ${message}`;
    consoleLogs.appendChild(line);
    consoleLogs.scrollTop = consoleLogs.scrollHeight;
}

function escapeHtml(s) {
    const div = document.createElement("div");
    div.innerText = s == null ? "" : s;
    return div.innerHTML;
}

function parseLocalDate(dateStr) {
    const parts = String(dateStr).split("-");
    return new Date(parts[0], parts[1] - 1, parts[2]);
}

/** 'YYYY-MM-DD' -> 'YYYY-MM-DD Ddd', the same form `clock.fmt_date` renders in the CLI.
 *  Anything unparseable comes back untouched, so a row's missing date stays blank. */
function fmtDate(dateStr) {
    if (!dateStr) return "";
    const d = parseLocalDate(dateStr);
    if (isNaN(d)) return String(dateStr);
    return `${dateStr} ${d.toLocaleDateString("en-US", { weekday: "short" })}`;
}

/** A date range with the weekday on both ends; one day long collapses to one date. */
function fmtSpan(start, end, sep = " to ") {
    if (start && start === end) return fmtDate(start);
    return `${fmtDate(start)}${sep}${fmtDate(end)}`;
}

function todayStr() {
    const d = new Date();
    const pad = n => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function sportLabel(sport) {
    return (sport || "").replace(/_/g, " ").toUpperCase();
}

function sportTitle(sport) {
    return (sport || "").replace(/_/g, " ");
}

// --- TAB NAVIGATION ---

window.switchMainTab = function(viewId) {
    document.querySelectorAll(".main-view").forEach(el => el.classList.remove("active"));
    document.querySelectorAll(".main-tab-btn").forEach(el => el.classList.remove("active"));
    const view = document.getElementById(viewId);
    if (view) view.classList.add("active");
    const btn = document.querySelector(`.main-tab-btn[data-tab="${viewId}"]`);
    if (btn) btn.classList.add("active");

    // Lazy-load each tab's data the first time it is shown.
    if (!loadedTabs.has(viewId)) {
        loadedTabs.add(viewId);
        if (viewId === "view-workouts") fetchWorkouts();
        else if (viewId === "view-learnings") fetchLearningsFull();
        else if (viewId === "view-history") fetchHistory();
        else if (viewId === "view-benchmarks") fetchBenchmarks();
        else if (viewId === "view-progress") { fetchProgress(); fetchZones(); }
    }
};

window.switchTab = function(tabId) {
    document.querySelectorAll(".tab-content").forEach(el => el.classList.remove("active"));
    document.querySelectorAll(".accordion-card .tab-btn").forEach(el => el.classList.remove("active"));

    document.getElementById(tabId).classList.add("active");
    const btn = Array.from(document.querySelectorAll(".accordion-card .tab-btn")).find(
        b => (tabId === "tab-goals" && b.innerText.includes("Goals")) ||
             (tabId === "tab-events" && b.innerText.includes("Constraints"))
    );
    if (btn) btn.classList.add("active");
};

// The console panel is shared by every tab, so its clear button lives with it.
document.getElementById("btn-clear-logs").addEventListener("click", () => {
    const consoleLogs = document.getElementById("console-logs");
    if (consoleLogs) consoleLogs.innerHTML = "";
});
