// The gym logger's "Export to Markdown" (DESIGN_gym_logger.md §1): the session as a few lines
// of Markdown for the athlete's own training notes. No DOM here, so `node --test` runs it.
// "?v=dev" becomes the commit at deploy, like the imports in app.js (DESIGN_gym_logger.md §2).
import { capitalise, clockAt, doneSetCount, formatClock, formatKg, localDate }
  from "./logic.js?v=dev";

const EN_DASH = "–";
const EM_DASH = "—";

// Before any set is ticked this is the session as the page holds it; after, the ticked sets.
export function toMarkdown(state, now) {
  const doneOnly = doneSetCount(state) > 0;
  const day = state.startedAt ? localDate(state.startedAt) : state.d;
  const lines = [`### ${day} [${state.t}]`];
  if (state.startedAt) {
    const end = clockAt(state, now);
    const minutes = Math.round((end - state.startedAt) / 60000);
    lines.push(`${formatClock(state.startedAt)}${EN_DASH}${formatClock(end)} (${minutes} min)`);
  }
  if (state.notes) {
    lines.push("", state.notes);
  }
  lines.push("");
  for (const exercise of state.x) {
    const sets = doneOnly ? exercise.sets.filter((set) => set.done) : exercise.sets;
    if (!sets.length) {
      continue;
    }
    let line = `- ${capitalise(exercise.n)}: ${setRuns(sets)}`;
    if (exercise.note && exercise.note.trim()) {
      line += ` ${EM_DASH} ${exercise.note.trim()}`;
    }
    lines.push(line);
  }
  if (state.note && state.note.trim()) {
    lines.push("", `Note: ${state.note.trim()}`);
  }
  return `${lines.join("\n")}\n`;
}

// Consecutive sets with the same reps and load read as one run: "1x5 (120 kg), 2x6 (140 kg)".
function setRuns(sets) {
  const runs = [];
  for (const set of sets) {
    const last = runs[runs.length - 1];
    if (last && last.reps === set.reps && last.kg === set.kg) {
      last.count += 1;
      continue;
    }
    runs.push({ count: 1, reps: set.reps, kg: set.kg });
  }
  return runs.map((run) => {
    const load = run.kg === null ? "bodyweight" : `${formatKg(run.kg)} kg`;
    return `${run.count}x${run.reps} (${load})`;
  }).join(", ");
}
