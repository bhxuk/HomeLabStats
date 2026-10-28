/* Logs tab: live container log viewer (the Dozzle replacement). */
"use strict";
const L = { id: null, name: null, lines: [], lastTs: null, timer: null, listTimer: null, max: 20000, busy: false };
const LV_ERR = /\b(error|err|fatal|crit(ical)?|panic|exception|traceback|failed)\b/i;
const LV_WARN = /\b(warn(ing)?)\b/i;
const LV_DBG = /\b(debug|trace|verbose)\b/i;

function tsNum(s) {
  if (!s) return 0;
  const m = s.match(/^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(\.\d+)?/);
  return m ? Date.parse(m[1] + "Z") / 1000 + parseFloat("0" + (m[2] || ".0")) : 0;
}
function parseLine(raw) {
  const m = raw.match(/^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z) (.*)$/s);
  const ts = m ? m[1] : null, text = m ? m[2] : raw;
  const lv = LV_ERR.test(text) ? "err" : LV_WARN.test(text) ? "warn" : LV_DBG.test(text) ? "dbg" : "";
  return { ts, text, lv };
}
function filterRe() {
  const f = $("#lFilter").value.trim(); if (!f) return null;
  try { return new RegExp(f, "gi"); } catch { return new RegExp(f.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi"); }
}
function lineVisible(l, re) {
  const lv = $("#lLevel").value;
  if (lv === "err" && l.lv !== "err") return false;
  if (lv === "warn" && l.lv !== "err" && l.lv !== "warn") return false;
  if (re) { re.lastIndex = 0; if (!re.test(l.text)) return false; }
  return true;
}
function lineHtml(l, re) {
  let t = esc(l.text);
  if (re) { const src = re.source; try { t = t.replace(new RegExp(src, "gi"), m => `<mark>${m}</mark>`); } catch {} }
  const ts = l.ts ? new Date(l.ts).toLocaleString([], { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "";
  return `<div class="ln ${l.lv}"><span class="ts">${esc(ts)}</span>${t}</div>`;
}
function renderAllLines() {
  const out = $("#lOut"), re = filterRe();
  const vis = L.lines.filter(l => lineVisible(l, re));
  out.innerHTML = vis.length ? vis.map(l => lineHtml(l, re)).join("") : `<div class="empty">${L.lines.length ? "No lines match the filter" : "No log output yet"}</div>`;
  $("#lCount").textContent = `${vis.length}${vis.length !== L.lines.length ? " of " + L.lines.length : ""} lines`;
  out.scrollTop = out.scrollHeight;
}
function appendLines(newLines) {
  if (!newLines.length) return;
  const out = $("#lOut"), atBottom = out.scrollHeight - out.scrollTop - out.clientHeight < 60, re = filterRe();
  if (!L.lines.length) out.innerHTML = "";
  L.lines.push(...newLines);
  let trimmed = false;
  if (L.lines.length > L.max) { L.lines.splice(0, L.lines.length - L.max); trimmed = true; }
  if (trimmed) return renderAllLines();
  const html = newLines.filter(l => lineVisible(l, re)).map(l => lineHtml(l, re)).join("");
  if (html) { if (out.querySelector(".empty")) out.innerHTML = ""; out.insertAdjacentHTML("beforeend", html); }
  $("#lCount").textContent = `${L.lines.length} lines`;
  if (atBottom) out.scrollTop = out.scrollHeight;
}

async function selectContainer(id, name) {
  clearInterval(L.timer);
  L.id = id; L.name = name; L.lines = []; L.lastTs = null;
  $("#lName").textContent = name; $("#lOut").innerHTML = `<div class="empty">Loading logs</div>`;
  $$("#lItems .it").forEach(x => x.classList.toggle("sel", x.dataset.id === id));
  $("#lDownload").href = `api/docker/${id}/logs.txt`; $("#lDownload").setAttribute("download", `${name}.log`);
  try {
    const d = await api(`api/docker/${id}/logs?tail=${$("#lTail").value}`);
    if (L.id !== id) return;
    L.lines = d.lines.map(parseLine); L.lastTs = d.last_ts;
    $("#lState").textContent = d.state;
    renderAllLines();
  } catch (e) { $("#lOut").innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
  L.timer = setInterval(pollLogs, 1500);
}
async function pollLogs() {
  if (!L.id || !$("#lFollow").checked || L.busy || document.hidden) return;
  L.busy = true;
  try {
    const q = L.lastTs ? `since=${encodeURIComponent(L.lastTs)}` : `tail=${$("#lTail").value}`;
    const d = await api(`api/docker/${L.id}/logs?${q}`);
    $("#lState").textContent = d.state;
    const last = tsNum(L.lastTs);
    const fresh = d.lines.map(parseLine).filter(l => !L.lastTs || !l.ts || tsNum(l.ts) > last);
    if (d.last_ts) L.lastTs = d.last_ts;
    appendLines(fresh);
    $("#lInfo").textContent = `live · updated ${new Date().toLocaleTimeString()}`;
  } catch (e) { $("#lInfo").textContent = e.message; }
  L.busy = false;
}

async function loadLogList() {
  try {
    if (!D.data || Date.now() / 1000 - (D.data.time || 0) > 6) D.data = await api("api/docker");
  } catch (e) { $("#lItems").innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
  const q = $("#lSearch").value.toLowerCase();
  const cs = (D.data.containers || []).filter(c => !q || c.name.toLowerCase().includes(q));
  const color = c => c.health === "unhealthy" ? C.red : c.state === "running" ? C.green : c.state === "exited" && c.exit_code ? C.red : "#56697c";
  $("#lItems").innerHTML = cs.map(c => `<div class="it ${c.id === L.id ? "sel" : ""}" data-id="${c.id}" data-name="${esc(c.name)}"><span class="d" style="background:${color(c)}"></span><span class="trunc">${esc(c.name)}</span></div>`).join("") || `<div class="empty">No containers</div>`;
  if (!D.data.available) $("#lItems").innerHTML = `<div class="empty">Docker not reachable</div>`;
  if (L.pending) { const c = cs.find(x => x.name === L.pending); L.pending = null; if (c) selectContainer(c.id, c.name); }
}

function openLogsFor(name) { L.pending = name; L.id = null; showTab("logs"); }

$("#lItems").addEventListener("click", e => { const it = e.target.closest(".it"); if (it) selectContainer(it.dataset.id, it.dataset.name); });
$("#lSearch").addEventListener("input", loadLogList);
let lfT; $("#lFilter").addEventListener("input", () => { clearTimeout(lfT); lfT = setTimeout(renderAllLines, 200); });
$("#lLevel").addEventListener("change", renderAllLines);
$("#lTail").addEventListener("change", () => L.id && selectContainer(L.id, L.name));
$("#lWrap").addEventListener("change", e => $("#lPane").classList.toggle("nowrap", !e.target.checked));
$("#lTs").addEventListener("change", e => $("#lPane").classList.toggle("nots", !e.target.checked));
$("#lClear").onclick = () => { L.lines = []; renderAllLines(); };
$("#lDownload").addEventListener("click", e => { if (!L.id || DEMO) { e.preventDefault(); toast(DEMO ? "Downloads are disabled in the demo" : "Pick a container first"); } });

Tabs.logs = {
  enter: () => { loadLogList(); clearInterval(L.listTimer); L.listTimer = setInterval(() => !document.hidden && loadLogList(), 5000); if (L.id && !L.timer) L.timer = setInterval(pollLogs, 1500); },
  leave: () => { clearInterval(L.listTimer); clearInterval(L.timer); L.timer = null; },
};
