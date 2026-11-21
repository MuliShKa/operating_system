"use strict";

const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const state = {
  catalog: [],
  tasks: {},            // id -> task (with team)
  mode: "quick",
  team: null,
  jobs: [],
  history: {},
  ports: [],
  selected: null,       // job id shown in the log panel
  follow: true,
  log: { job: null, offset: 0, partial: "", busy: false },
};

const MAX_CHUNK = 256 * 1024;   // same as MAX_LOG_CHUNK in server.py
const ICON = { queued: "○", running: '<span class="spin">◐</span>', passed: "✓", failed: "✗", cancelled: "–" };
const LABEL = { queued: "Queued", running: "Running", passed: "PASS", failed: "FAIL", cancelled: "Cancelled" };

// ---------- helpers ----------
function fmtDur(s) {
  if (s == null) return "";
  s = Math.round(s);
  if (s < 60) return `${s} s`;
  return `${Math.floor(s / 60)} min ${String(s % 60).padStart(2, "0")} s`;
}
function ago(ts) {
  const s = Date.now() / 1000 - ts;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return new Date(ts * 1000).toLocaleDateString();
}
let toastTimer;
function toast(msg) {
  const el = $("#toast");
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 2600);
}
async function api(path, body) {
  const res = await fetch(path, body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.message || data.error || res.statusText);
  return data;
}
function store(key, value) { try { localStorage.setItem(key, value); } catch { /* private mode */ } }
function recall(key) { try { return localStorage.getItem(key); } catch { return null; } }

/** The job that matters for a task right now: running/queued first, else the newest. */
function currentJob(taskId) {
  const jobs = state.jobs.filter((j) => j.task === taskId);
  return jobs.find((j) => j.status === "running") || jobs.find((j) => j.status === "queued") || null;
}
function runnable(team) { return team.tasks.filter((t) => t.kind !== "tests"); }

// ---------- run ----------
async function run(taskIds, batch) {
  const longOnes = taskIds.filter((id) => /10 min/.test(state.tasks[id].note));
  if (state.mode === "official" && longOnes.length &&
      !confirm(`Official mode: ${longOnes.join(", ")} cut the Internet for 10 minutes each. Continue?`)) return;
  try {
    const { queued } = await api("/api/run", { tasks: taskIds, quick: state.mode === "quick", batch });
    toast(queued.length === 1 ? `${taskIds[0]} queued` : `${queued.length} jobs queued`);
    if (!state.jobs.some((j) => j.status === "running")) select(queued[0]);
    await refresh();
  } catch (e) { toast(`Could not queue: ${e.message}`); }
}

// ---------- catalog rendering ----------
function renderTabs() {
  $("#team-tabs").innerHTML = state.catalog.map((team) => {
    const tasks = runnable(team);
    const passed = tasks.filter((t) => state.history[t.id]?.status === "passed").length;
    const failed = tasks.some((t) => state.history[t.id]?.status === "failed");
    const tallyColor = failed ? "var(--fail)" : passed === tasks.length ? "var(--pass)" : "var(--muted)";
    return `<button class="tab ${team.id === state.team ? "active" : ""}" data-team="${team.id}" role="tab"
              aria-selected="${team.id === state.team}">
              <span class="tally" style="color:${tallyColor}">${passed}/${tasks.length}</span>
              <strong>${team.id}</strong><span>${esc(team.name)}</span></button>`;
  }).join("");
}

function renderTeam() {
  const team = state.catalog.find((t) => t.id === state.team);
  if (!team) return;
  const count = runnable(team).length;
  $("#team-panel").innerHTML = `
    <div class="team-head">
      <div>
        <h2><span class="id">${team.id}</span>${esc(team.name)}</h2>
        <p>${esc(team.summary)}</p>
      </div>
      <div class="team-actions">
        <button class="btn primary" data-run-team="${team.id}" ${team.ready ? "" : "disabled"}>
          ▶ Run ${team.id} · ${count} in a row</button>
        ${team.ready ? "" : `<span class="venv-missing">No virtualenv: run bash ${team.id}/scripts/setup.sh</span>`}
      </div>
    </div>
    <div class="cards">
      ${team.tasks.map((t) => `
        <article class="card ${t.kind === "tests" ? "tests" : ""}" data-card="${t.id}">
          <div class="card-top">
            <span class="card-id">${t.id}</span>
            ${t.kind === "extra" ? '<span class="tag extra">Extra</span>' : ""}
            ${t.kind === "tests" ? '<span class="tag">Tests</span>' : ""}
          </div>
          <h3>${esc(t.title)}</h3>
          <div class="concept">${esc(t.concept)}</div>
          <p class="expected">${esc(t.expected)}</p>
          ${t.note ? `<div class="note">⏱ ${esc(t.note)}</div>` : ""}
          <div class="card-foot">
            <span class="badge" data-badge></span>
            <span class="last" data-last></span>
            <span class="spacer"></span>
            <button class="btn small" data-log hidden>Logs</button>
            <button class="btn small primary" data-run="${t.id}" ${team.ready ? "" : "disabled"}>▶ Run</button>
          </div>
        </article>`).join("")}
    </div>`;
  updateCards();
}

function updateCards() {
  document.querySelectorAll("[data-card]").forEach((card) => {
    const id = card.dataset.card;
    const job = currentJob(id);
    const hist = state.history[id];
    const status = job ? job.status : hist?.status;
    card.className = card.className.replace(/\bst-\w+/g, "").trim() + (status ? ` st-${status}` : "");
    const badge = card.querySelector("[data-badge]");
    badge.className = `badge ${status || ""}`;
    badge.innerHTML = status ? `${ICON[status]} ${LABEL[status]}` : "Not run yet";
    const last = card.querySelector("[data-last]");
    if (job?.status === "running") last.textContent = fmtDur(job.duration);
    else if (job?.status === "queued") last.textContent = `#${job.id} in queue`;
    else last.textContent = hist ? `${fmtDur(hist.duration)} · ${hist.mode} · ${ago(hist.ended)}` : "";
    const logBtn = card.querySelector("[data-log]");
    const latest = [...state.jobs].reverse().find((j) => j.task === id);
    logBtn.hidden = !latest;
    if (latest) logBtn.dataset.log = latest.id;
    card.querySelector("[data-run]").textContent = job ? "+ Queue again" : "▶ Run";
  });
}

// ---------- queue ----------
function renderJobs() {
  const list = $("#jobs");
  const running = state.jobs.find((j) => j.status === "running");
  const queued = state.jobs.filter((j) => j.status === "queued").length;
  const done = state.jobs.filter((j) => ["passed", "failed"].includes(j.status));
  const failed = done.filter((j) => j.status === "failed").length;
  $("#queue-summary").textContent = [
    running ? `running ${running.task}` : "idle",
    queued ? `${queued} waiting` : "",
    done.length ? `${done.length - failed} pass · ${failed} fail` : "",
  ].filter(Boolean).join(" · ");
  $("#cancel-all").disabled = !running && !queued;

  if (!state.jobs.length) {
    list.innerHTML = '<li class="empty">Nothing yet. Run a scenario, a whole team, or everything.</li>';
    return;
  }
  list.innerHTML = state.jobs.map((j) => {
    const active = j.status === "running" || j.status === "queued";
    return `<li class="job ${j.status} ${j.id === state.selected ? "selected" : ""}" data-job="${j.id}">
      <span class="icon">${ICON[j.status]}</span>
      <span class="name"><b>${j.task}</b><span>${esc(j.title)}</span>
        ${j.batch ? `<span class="batch">${esc(j.batch)} · ${j.mode}</span>` : `<span class="batch">${j.mode}</span>`}</span>
      <span class="meta">${j.status === "queued" ? "waiting" : fmtDur(j.duration)}</span>
      ${active ? `<button class="x" data-cancel="${j.id}" title="${j.status === "running" ? "Stop (Ctrl+C)" : "Remove from queue"}">✕</button>` : "<span></span>"}
    </li>`;
  }).join("");
  if (running && running.id !== renderJobs.lastRunning) {   // keep the running job in view
    list.querySelector(".job.running")?.scrollIntoView({ block: "nearest" });
  }
  renderJobs.lastRunning = running?.id;
}

function renderPorts() {
  $("#ports").innerHTML = state.ports.map((p) => {
    if (!p.busy) return `<span class="port" title="Free"><span class="dot"></span>:${p.port}</span>`;
    const who = p.command ? `PID ${p.pid}: ${p.command}` : "used by another program";
    const running = state.jobs.some((j) => j.status === "running");
    const stop = p.ours && !running ? `<button data-port-stop="${p.port}" title="Send Ctrl+C to it">stop</button>` : "";
    return `<span class="port busy" title="${esc(who)}"><span class="dot"></span>:${p.port} busy ${stop}</span>`;
  }).join("");
}

// ---------- logs ----------
function select(jobId) {
  if (state.selected === jobId) return;
  state.selected = jobId;
  state.log = { job: jobId, offset: 0, partial: "", busy: false };
  $("#log").innerHTML = "";
  updateLogHead();
  renderJobs();
  pollLog();
}

function updateLogHead() {
  const job = state.jobs.find((j) => j.id === state.selected);
  $("#log-title").textContent = job ? `${job.task} · ${job.title}` : "Logs";
  $("#log-status").innerHTML = job ? `<span class="badge ${job.status}">${ICON[job.status]} ${LABEL[job.status]}</span>` : "";
  const raw = $("#log-raw");
  raw.hidden = !job;
  if (job) raw.href = `/api/logfile/${encodeURIComponent(job.log)}`;
}

function classify(line) {
  const clean = line.replace(/\x1b\[[0-9;]*[A-Za-z]/g, "");
  if (clean.startsWith("[launcher]")) return ["l-launcher", clean];
  if (/\bFAIL(ED)?\b|Traceback|Error:/.test(clean)) return ["l-fail", clean];
  if (/\bPASS(ED)?\b|\bOK\b$/.test(clean)) return ["l-pass", clean];
  if (/^\s*(={3,}|-{3,}|#{2,})|^\s*OS\d-\d|SUMMARY|^Ran \d+ tests?/.test(clean)) return ["l-head", clean];
  if (/warning|WARN/i.test(clean)) return ["l-warn", clean];
  return ["", clean];
}

function appendLog(text, final) {
  const view = $("#log");
  const nearBottom = view.scrollHeight - view.scrollTop - view.clientHeight < 60;
  const lines = (state.log.partial + text).split("\n");
  state.log.partial = final ? "" : lines.pop();
  if (final && lines.at(-1) === "") lines.pop();
  if (!lines.length) return;
  const frag = document.createDocumentFragment();
  for (const line of lines) {
    const [cls, clean] = classify(line);
    const span = document.createElement("span");
    if (cls) span.className = cls;
    span.textContent = clean + "\n";
    frag.appendChild(span);
  }
  view.appendChild(frag);
  if (nearBottom) view.scrollTop = view.scrollHeight;
}

async function pollLog() {
  const log = state.log;
  if (log.job == null || log.busy) return;
  log.busy = true;
  try {
    let more = true;
    while (more && log === state.log) {
      const data = await api(`/api/log/${log.job}?offset=${log.offset}`);
      if (log !== state.log) break;
      const finished = !["running", "queued"].includes(data.status);
      more = data.offset - log.offset >= MAX_CHUNK;   // a big log arrives in several chunks
      log.offset = data.offset;
      if (data.status !== "queued") $("#log").querySelector(".empty")?.remove();
      if (data.text) appendLog(data.text, false);
      if (finished && !more && log.partial) appendLog("", true);
      if (data.status === "queued" && !$("#log").childElementCount) {
        $("#log").innerHTML = '<span class="empty">Waiting in the queue…</span>';
      }
    }
  } catch { /* server restarting: next tick retries */ }
  log.busy = false;
}

// ---------- polling ----------
async function refresh() {
  try {
    const data = await api("/api/state");
    state.jobs = data.jobs;
    state.history = data.history;
    state.ports = data.ports;
  } catch { return; }
  const running = state.jobs.find((j) => j.status === "running");
  if (state.follow && running && running.id !== state.selected) select(running.id);
  else if (state.selected == null && state.jobs.length) select(state.jobs.at(-1).id);
  renderJobs();
  renderPorts();
  renderTabs();
  updateCards();
  updateLogHead();
}

// ---------- events ----------
document.addEventListener("click", async (e) => {
  const el = e.target.closest("button, [data-job]");
  if (!el) return;
  const d = el.dataset;
  if (d.mode) {
    state.mode = d.mode;
    store("launcher.mode", d.mode);
    document.querySelectorAll(".segmented button").forEach((b) => {
      b.classList.toggle("active", b === el);
      b.setAttribute("aria-checked", b === el);
    });
  } else if (d.team) {
    state.team = d.team;
    store("launcher.team", d.team);
    renderTabs();
    renderTeam();
  } else if (d.run) {
    run([d.run], null);
  } else if (d.runTeam) {
    const team = state.catalog.find((t) => t.id === d.runTeam);
    run(runnable(team).map((t) => t.id), `${team.id} · all scenarios`);
  } else if (d.log) {
    state.follow = false;
    $("#follow").checked = false;
    select(Number(d.log));
  } else if (d.cancel) {
    e.stopPropagation();
    await api(`/api/cancel/${d.cancel}`, {}).catch((err) => toast(err.message));
    toast("Stopping…");
    refresh();
  } else if (d.portStop) {
    const res = await api(`/api/port-stop/${d.portStop}`, {}).catch((err) => ({ message: err.message }));
    toast(res.message);
    setTimeout(refresh, 1500);
  } else if (d.job) {
    state.follow = false;
    $("#follow").checked = false;
    select(Number(d.job));
  }
});

$("#run-everything").addEventListener("click", () => {
  const ids = state.catalog.filter((t) => t.ready).flatMap((t) => runnable(t).map((x) => x.id));
  run(ids, "Everything · OS1 → OS5");
});
$("#cancel-all").addEventListener("click", async () => {
  if (!confirm("Stop the running job and empty the queue?")) return;
  await api("/api/cancel-all", {});
  toast("Stopping everything…");
  refresh();
});
$("#clear").addEventListener("click", async () => { await api("/api/clear", {}); refresh(); });
$("#follow").addEventListener("change", (e) => {
  state.follow = e.target.checked;
  if (state.follow) refresh();
});

// ---------- start ----------
(async function init() {
  state.catalog = await api("/api/catalog");
  state.catalog.forEach((team) => team.tasks.forEach((t) => { state.tasks[t.id] = { ...t, team: team.id }; }));
  const savedTeam = recall("launcher.team");
  state.team = state.catalog.some((t) => t.id === savedTeam) ? savedTeam : state.catalog[0].id;
  const savedMode = recall("launcher.mode");
  if (savedMode) document.querySelector(`[data-mode="${savedMode}"]`)?.click();
  renderTabs();
  renderTeam();
  await refresh();
  setInterval(refresh, 1000);
  setInterval(pollLog, 600);
})();
