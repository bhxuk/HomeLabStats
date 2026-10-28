/* Processes tab. */
"use strict";
const P = { sort: "cpu", desc: true, paused: false };

async function loadProcesses() {
  if (P.paused) return;
  const q = encodeURIComponent($("#pSearch").value), lim = $("#pLimit").value;
  try {
    const d = await api(`api/processes?sort=${P.sort}&desc=${P.desc}&limit=${lim}&q=${q}`);
    $("#pCount").textContent = d.matched === d.total ? `${d.total} processes` : `${d.matched} of ${d.total} processes`;
    const now = Date.now() / 1000, manage = canManage();
    $("#pTbl tbody").innerHTML = d.processes.map(p => `<tr>
      <td class="r mono dim">${p.pid}</td><td class="mono"><b style="font-weight:600">${esc(p.name)}</b></td><td class="muted">${esc(p.user)}</td>
      <td>${p.container ? `<a href="#" class="chip cyan" data-ctlogs="${esc(p.container)}" title="Open logs">${esc(p.container)}</a>` : ""}</td>
      <td class="r"><div class="cellbar"><span class="mono" style="color:${barColor(p.cpu)}">${p.cpu.toFixed(1)}</span><div class="bar"><i style="width:${Math.min(p.cpu, 100)}%;background:${barColor(p.cpu)}"></i></div></div></td>
      <td class="r mono">${fmtBytes(p.rss)} <span class="dim">${p.mem.toFixed(1)}%</span></td>
      <td class="r mono muted">${p.threads ?? "-"}</td><td class="r mono muted">${p.started ? fmtDur(now - p.started) : "-"}</td>
      <td class="cmd" title="${esc(p.cmd)}">${esc(p.cmd)}</td>
      <td class="r">${manage && p.pid > 1 ? `<button class="btn sm danger" data-kill="${p.pid}" data-name="${esc(p.name)}">End</button>` : ""}</td></tr>`).join("") ||
      `<tr><td colspan="10" class="empty">No matching processes</td></tr>`;
  } catch (e) { $("#pTbl tbody").innerHTML = `<tr><td colspan="10" class="empty">${esc(e.message)}</td></tr>`; }
}

$$("#pTbl th.sortable").forEach(th => th.addEventListener("click", () => {
  const s = th.dataset.sort;
  if (P.sort === s) P.desc = !P.desc; else { P.sort = s; P.desc = !["name", "user", "pid"].includes(s); }
  $$("#pTbl th").forEach(x => x.classList.remove("sorted")); th.classList.add("sorted"); loadProcesses();
}));
let pT; $("#pSearch").addEventListener("input", () => { clearTimeout(pT); pT = setTimeout(loadProcesses, 250); });
$("#pLimit").addEventListener("change", loadProcesses);
$("#pPause").addEventListener("click", e => { P.paused = !P.paused; e.target.textContent = P.paused ? "Resume" : "Pause"; if (!P.paused) loadProcesses(); });
$("#pTbl").addEventListener("click", async e => {
  const lg = e.target.closest("[data-ctlogs]");
  if (lg) { e.preventDefault(); openLogsFor(lg.dataset.ctlogs); return; }
  const b = e.target.closest("[data-kill]"); if (!b) return;
  const choice = await dialog(`End ${b.dataset.name} (${b.dataset.kill})?`,
    `<p class="muted" style="margin:0">"End" asks the process to exit cleanly (SIGTERM). "Force kill" stops it immediately (SIGKILL) and may lose unsaved data.</p>`,
    [{ label: "Cancel", value: null }, { label: "Force kill", value: "kill" }, { label: "End", cls: "primary", value: "terminate" }]);
  if (!choice) return;
  try { await api(`api/processes/${b.dataset.kill}/${choice}`, { method: "POST" }); toast(`Sent ${choice} to ${b.dataset.name}`); setTimeout(loadProcesses, 800); }
  catch (err) { toast(err.message); }
});
Tabs.processes = { load: loadProcesses, period: 3000 };
