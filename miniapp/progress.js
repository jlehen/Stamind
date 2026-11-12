// The Progress page's DOM layer (DESIGN_progress_page.md §3): it downloads the progress file,
// then draws the tab and the span chosen, again at each tap, with no trip back to the bot.
// Read-only, like the Calendar. Every question goes to `progress_logic.js`; this file only
// lays the answers out, the chart as SVG in its own code (§4.3). "?v=dev" becomes the commit
// at deploy.
import { stamp } from "./calendar_logic.js?v=dev";
import * as logic from "./progress_logic.js?v=dev";
import * as storage from "./storage.js?v=dev";

const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;

const ui = {
  tabs: document.getElementById("tabs"),
  spans: document.getElementById("spans"),
  stamp: document.getElementById("stamp"),
  view: document.getElementById("view"),
  problem: document.getElementById("problem"),
  sheet: document.getElementById("record-sheet"),
  sheetTitle: document.getElementById("sheet-title"),
  sheetBody: document.getElementById("sheet-body"),
  sheetClose: document.getElementById("sheet-close"),
};

const state = { file: null, tab: logic.FIRST_TAB, span: logic.FIRST_SPAN,
                grain: logic.FIRST_GRAIN };

// The calendar's strip colours, numbered along the file's list of mesocycles.
const STRIPS = 6;
const SVG = "http://www.w3.org/2000/svg";

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) {
    node.className = className;
  }
  if (text !== undefined) {
    node.textContent = text;
  }
  return node;
}

function shape(tag, attributes, text) {
  const node = document.createElementNS(SVG, tag);
  for (const [name, value] of Object.entries(attributes)) {
    node.setAttribute(name, value);
  }
  if (text !== undefined) {
    node.textContent = text;
  }
  return node;
}

function choices(box, options, chosen, pick) {
  // A row of buttons, the chosen one marked: the tabs, and the spans under them.
  box.replaceChildren();
  for (const option of options) {
    const button = element("button", "choice", option.label);
    button.type = "button";
    button.setAttribute("aria-pressed", String(option.key === chosen));
    button.addEventListener("click", () => pick(option.key));
    box.append(button);
  }
}

// ---------------------------------------------------------------------------------------
// Fitness (§3.1).
// ---------------------------------------------------------------------------------------

// The chart's rows, top to bottom: the goals' marks, the lines, the bars, the bands, the
// months.
const MARKS = 16;
const LINES = 150;
const GAP = 8;
const BARS = 70;
const STRIP = 8;
const MONTHS = 14;
const HEIGHT = MARKS + LINES + GAP + BARS + 4 + STRIP + MONTHS;

function drawChart(model, width) {
  const svg = shape("svg", { viewBox: `0 0 ${width} ${HEIGHT}`, class: "chart",
                             role: "img", "aria-label": "Fitness and form, and the weeks" });
  const x = (iso) => logic.xAt(model, iso, width);
  const day = x(logic.shiftDay(model.from, 1));
  const span = (model.high - model.low) || 1;
  const y = (value) => MARKS + (model.high - value) / span * LINES;
  const barsTop = MARKS + LINES + GAP;

  // Form's zero, above which the athlete is fresh.
  svg.append(shape("line", { x1: 0, x2: width, y1: y(0), y2: y(0), class: "zero" }));
  svg.append(shape("text", { x: 2, y: y(model.high) + 10, class: "axis" },
                   String(Math.round(model.high))));
  svg.append(shape("text", { x: 2, y: y(0) - 2, class: "axis" }, "0"));

  for (const bar of model.bars) {
    const left = x(bar.monday);
    const room = x(logic.shiftDay(bar.monday, 7)) - left;
    const height = (value) => (value || 0) / model.most * BARS;
    const planned = height(bar.planned);
    const done = height(bar.done);
    svg.append(shape("rect", { x: left + room * 0.12, y: barsTop + BARS - planned,
                               width: room * 0.36, height: planned, class: "planned" }));
    svg.append(shape("rect", { x: left + room * 0.52, y: barsTop + BARS - done,
                               width: room * 0.36, height: done, class: "done" }));
    if (bar.label && room >= 24) {
      svg.append(shape("text", { x: left + room / 2,
                                 y: barsTop + BARS - Math.max(planned, done) - 2,
                                 class: "hours" }, bar.label));
    }
  }

  for (const series of [["fitness", model.fitness], ["form", model.form]]) {
    for (const segment of series[1]) {
      const points = segment.points.map(([date, value]) => `${x(date) + day / 2},${y(value)}`);
      svg.append(shape("polyline", { points: points.join(" "),
                                     class: `${series[0]}${segment.dashed ? " ahead" : ""}` }));
    }
  }

  const stripTop = barsTop + BARS + 4;
  for (const band of model.bands) {
    svg.append(shape("rect", { x: x(band.start), y: stripTop,
                               width: x(logic.shiftDay(band.end, 1)) - x(band.start),
                               height: STRIP, class: "band",
                               style: `fill: var(--meso-${band.index % STRIPS})` }));
  }
  let lastMonth = -Infinity;
  for (let date = model.from; date <= model.to; date = logic.shiftDay(date, 1)) {
    if (!date.endsWith("-01") || x(date) - lastMonth < 32) {
      continue;
    }
    lastMonth = x(date);
    const month = new Date(`${date}T12:00:00`).toLocaleString("en", { month: "short" });
    svg.append(shape("text", { x: lastMonth + 2, y: HEIGHT - 2, class: "axis" }, month));
  }

  if (model.from <= model.today && model.today <= model.to) {
    svg.append(shape("line", { x1: x(model.today) + day / 2, x2: x(model.today) + day / 2,
                               y1: MARKS, y2: stripTop, class: "today" }));
  }
  for (const goal of model.goals) {
    const middle = x(goal.date) + day / 2;
    svg.append(shape("line", { x1: middle, x2: middle, y1: MARKS, y2: stripTop,
                               class: "goal-line" }));
    svg.append(shape("text", { x: Math.min(Math.max(middle, 7), width - 7), y: MARKS - 3,
                               class: "goal-flag" }, "🎯"));
  }
  return svg;
}

function key(className, text) {
  const item = element("li");
  item.append(element("span", `swatch ${className}`), element("span", "", text));
  return item;
}

function showFitness() {
  const model = logic.chart(state.file, state.span);
  if (!model.fitness.length && !model.bars.length) {
    ui.view.append(element("p", "problem", "No training on record in this span."));
    return;
  }
  ui.view.append(drawChart(model, Math.max(280, ui.view.clientWidth)));
  const keys = element("ul", "legend");
  keys.append(key("key-fitness", "Fitness (CTL)"), key("key-form", "Form (TSB)"),
              key("key-planned", "Planned load of the week"),
              key("key-done", "Load done, its hours over it"));
  ui.view.append(keys, element("p", "line chart-note", logic.CHART_NOTE));
  const named = element("ul", "legend");
  for (const band of model.bands) {
    named.append(key(`meso-${band.index % STRIPS}`, band.name));
  }
  for (const goal of model.goals) {
    named.append(element("li", "", goal.text));
  }
  ui.view.append(named);
}

// ---------------------------------------------------------------------------------------
// Weeks (§3.2) and Mesocycles (§3.3).
// ---------------------------------------------------------------------------------------

function showWeeks() {
  const rows = logic.weekRows(state.file, state.span);
  const list = element("ul", "weeks");
  for (const row of rows) {
    if (row.kind === "now") {
      list.append(element("li", "week-now", row.text));
      continue;
    }
    // A tap opens the week in place, with the terminal's lines for it.
    const item = element("li");
    const button = element("button", "week-row");
    button.type = "button";
    button.append(element("span", "week-label", row.label));
    row.parts.forEach((part, index) => {
      if (index) {
        button.append(" · ");
      }
      button.append(element("span", part.short ? "short" : "", part.text));
    });
    button.append(element("span", "week-open", "▸"));
    const open = element("div", "week-lines");
    open.hidden = true;
    for (const line of row.lines) {
      const className = ["line", line.short ? "short" : "", line.under ? "under" : ""];
      open.append(element("p", className.join(" ").trim(), line.text));
    }
    button.addEventListener("click", () => {
      open.hidden = !open.hidden;
      button.classList.toggle("opened", !open.hidden);
    });
    item.append(button, open);
    list.append(item);
  }
  if (rows.every((row) => row.kind === "now")) {
    list.append(element("li", "problem", "No week that has ended had sessions written here."));
  }
  ui.view.append(list);
}

function openSheet(sheet) {
  ui.sheetTitle.textContent = sheet.title;
  ui.sheetBody.replaceChildren(...sheet.lines.map((line) => element("p", "line", line)));
  ui.sheet.hidden = false;
}

function showMesocycles() {
  const cards = logic.recordCards(state.file, state.span);
  if (!cards.length) {
    ui.view.append(element("p", "problem", "No mesocycle has a record here yet."));
    return;
  }
  for (const card of cards) {
    const box = element(card.sheet ? "button" : "section", "card record");
    box.append(element("p", "line card-line", card.head),
               element("p", "line record-status", card.status));
    for (const line of card.lines) {
      box.append(element("p", "line", line));
    }
    if (card.sheet) {
      box.type = "button";
      box.addEventListener("click", () => openSheet(card.sheet));
    }
    ui.view.append(box);
  }
}

// ---------------------------------------------------------------------------------------
// Intensity (§3.4).
// ---------------------------------------------------------------------------------------

const ZONE_ROWS = 110;

function zoneStack(seconds, scale) {
  // A bar's zones, bottom up, as [zone index, height].
  return (seconds || []).map((value, index) => [index, value * scale]);
}

function drawZoneWeeks(chart, width) {
  const height = MARKS + ZONE_ROWS + MONTHS;
  const svg = shape("svg", { viewBox: `0 0 ${width} ${height}`, class: "chart",
                             role: "img", "aria-label": `${chart.head}, week by week` });
  const x = (iso) => logic.xAt(chart, iso, width);
  const bottom = MARKS + ZONE_ROWS;
  svg.append(shape("text", { x: 2, y: MARKS + 8, class: "axis" }, logic.hours(chart.most)));
  for (const item of chart.items) {
    const left = x(item.monday);
    const room = x(logic.shiftDay(item.monday, 7)) - left;
    let top = bottom;
    for (const [zone, size] of zoneStack(item.seconds, ZONE_ROWS / chart.most)) {
      top -= size;
      svg.append(shape("rect", { x: left + room * 0.15, y: top, width: room * 0.7,
                                 height: size, class: `zone zone-${zone + 1}`
                                 + (item.ahead ? " ahead" : "") }));
    }
    if (item.mark === "!" || item.mark === "~") {
      svg.append(shape("text", { x: left + room / 2, y: top - 2, class: "hours" }, item.mark));
    }
  }
  const today = state.file.today;
  if (chart.from <= today && today <= chart.to) {
    svg.append(shape("line", { x1: x(today), x2: x(today), y1: MARKS, y2: bottom,
                               class: "today" }));
  }
  return svg;
}

function zoneBar(seconds, most) {
  // One mesocycle's average week across the row, its zones left to right.
  const bar = element("span", "zone-bar");
  (seconds || []).forEach((value, index) => {
    const part = element("span", `zone zone-${index + 1}`);
    part.style.width = `${value / most * 100}%`;
    bar.append(part);
  });
  return bar;
}

function showZoneMesocycles(chart, box) {
  for (const item of chart.items) {
    // A tap shows what the mesocycle set out to do (§3.4).
    const row = element("button", "meso-zones");
    row.type = "button";
    row.append(element("span", "line card-line", `${item.name}, ${item.dates}`));
    if (item.seconds) {
      row.append(zoneBar(item.seconds, chart.most),
                 element("span", "line record-status",
                         `${logic.hours(logic.total(item.seconds))} ${item.per}`));
    } else {
      row.append(element("span", "line record-status", "no time in these zones"));
    }
    row.addEventListener("click", () => openSheet({ title: item.name,
                                                     lines: [item.dates, item.focus] }));
    box.append(row);
  }
}

function showIntensity() {
  const grains = element("div", "choices");
  choices(grains, logic.GRAINS, state.grain, (grain) => { state.grain = grain; draw(); });
  ui.view.append(grains);
  const charts = logic.intensity(state.file, state.span, state.grain);
  if (!charts.length) {
    ui.view.append(element("p", "problem", logic.NO_ZONES));
    return;
  }
  for (const chart of charts) {
    const box = element("section", "zones");
    box.append(element("h3", "part", chart.head));
    if (state.grain === "meso") {
      showZoneMesocycles(chart, box);
    } else {
      box.append(drawZoneWeeks(chart, Math.max(280, ui.view.clientWidth)));
    }
    const keys = element("ul", "legend zone-keys");
    chart.labels.forEach((label, index) => {
      keys.append(key(`zone zone-${index + 1}`, `Z${index + 1} ${label}`));
    });
    for (const mark of chart.marks) {
      keys.append(element("li", "", logic.MARKS[mark]));
    }
    box.append(keys);
    ui.view.append(box);
  }
}

// ---------------------------------------------------------------------------------------
// The page.
// ---------------------------------------------------------------------------------------

const VIEWS = { fitness: showFitness, weeks: showWeeks, mesocycles: showMesocycles,
                intensity: showIntensity };

function draw() {
  choices(ui.tabs, logic.TABS, state.tab, (tab) => { state.tab = tab; draw(); });
  choices(ui.spans, logic.spansOffered(state.file), state.span,
          (span) => { state.span = span; draw(); });
  ui.view.replaceChildren();
  VIEWS[state.tab]();
}

function fail(message) {
  ui.view.hidden = true;
  ui.problem.textContent = message;
  ui.problem.hidden = false;
}

function wire() {
  ui.sheetClose.addEventListener("click", () => { ui.sheet.hidden = true; });
  ui.sheet.addEventListener("click", (event) => {
    if (event.target === ui.sheet) {
      ui.sheet.hidden = true;
    }
  });
}

async function start() {
  if (tg) {
    tg.ready();
    tg.expand();
  }
  wire();
  const files = storage.storageFromHash(window.location.hash);
  if (!files) {
    fail(logic.NO_BUTTON);
    return;
  }
  try {
    state.file = await storage.fetchFile(files, storage.PROGRESS);
  } catch (problem) {
    console.warn("the progress file could not be had", problem);
    fail(logic.COULD_NOT_LOAD);
    return;
  }
  ui.stamp.textContent = stamp(state.file.at);
  draw();
}

start();
