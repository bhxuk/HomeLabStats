/* Docker tab: container list, actions, details drawer, disk usage and cleanup. */
"use strict";
const D = { data: null };

async function loadDocker() {
  try { D.data = await api("api/docker"); renderDocker(); }
  catch (e) { $("#dTbl tbody").innerHTML = `<tr><td colspan="9" class="empty">${esc(e.message)}</td></tr>`; }
}

function stateChip(c) {
  if (c.health === "unhealthy") return `<span class="chip red">● unhealthy</span>`;
  if (c.state === "running") return c.health === "starting" ? `<span class="chip amber">● starting</span>` : `<span class="chip green">● ${c.health === "healthy" ? "healthy" : "running"}</span>`;
  if (c.state === "restarting") return `<span class="chip amber">↻ restarting</span>`;
  if (c.state === "paused") return `<span class="chip violet">❚❚ paused</span>`;
  if (c.state === "exited") return `<span class="chip ${c.exit_code ? "red" : ""}">■ exited (${c.exit_code})</span>`;
  if (c.state === "created") return `<span class="chip">○ created</span>`;
  return `<span class="chip">${esc(c.state)}</span>`;
}
const isProblem = c => c.health === "unhealthy" || c.state === "restarting" || (c.state === "exited" && c.exit_code);

function actionButtons(c, compact = true) {
  const sm = "btn sm", out = [];
  if (!canManage()) return "";
  if (c.state === "running") {
    out.push(`<button class="${sm}" data-act="restart" data-id="${c.id}" title="Restart">↻${compact ? "" : " Restart"}</button>`);
    if (!c.is_self) out.push(`<button class="${sm}" data-act="pause" data-id="${c.id}" title="Pause">❚❚${compact ? "" : " Pause"}</button>`,
      `<button class="${sm} danger" data-act="stop" data-id="${c.id}" title="Stop">■${compact ? "" : " Stop"}</button>`);
  } else if (c.state === "paused") {
    out.push(`<button class="${sm}" data-act="unpause" data-id="${c.id}">▶ Resume</button>`);
  } else {
    out.push(`<button class="${sm}" data-act="start" data-id="${c.id}" title="Start">▶${compact ? "" : " Start"}</button>`);
    if (!c.is_self) out.push(`<button class="${sm} danger" data-act="remove" data-id="${c.id}" title="Remove">🗑${compact ? "" : " Remove"}</button>`);
  }
  return out.join("");
}

function renderDocker() {
  const d = D.data; if (!d) return;
  const tb = $("#dTbl tbody");
  $("#dLocked").hidden = canManage() || !d.available;
  if (!d.available) {
    $("#dSummary").innerHTML = "";
    tb.innerHTML = `<tr><td colspan="9" class="empty">Docker is not reachable.<br><span class="dim mono" style="font-size:12px">${esc(d.error)}</span><br><br>Mount <span class="mono">/var/run/docker.sock</span> into the container, or add the service user to the <span class="mono">docker</span> group.</td></tr>`;
    return;
  }
  const cs = d.containers, run = cs.filter(c => c.state === "running");
  const cpu = run.reduce((a, c) => a + (c.stats?.cpu || 0), 0), mem = run.reduce((a, c) => a + (c.stats?.mem_used || 0), 0);
  const probs = cs.filter(isProblem).length;
  $("#dSummary").innerHTML = [
    ["Running", `${run.length}<small>/${cs.length}</small>`, `${cs.length - run.length} stopped`],
    ["Container CPU", `${cpu.toFixed(1)}<small>%</small>`, "of whole machine"],
    ["Container memory", fmtBytes(mem), d.info.mem ? `of ${fmtBytes(d.info.mem)}` : ""],
    ["Problems", `<span class="${probs ? "c-crit" : "c-ok"}">${probs}</span>`, probs ? "need attention" : "all good"],
    ["Engine", `<span style="font-size:22px">${esc(d.info.version || "?")}</span>`, `${d.info.images ?? "?"} images · ${esc(d.info.driver || "")}`],
  ].map(([l, b, s]) => `<div class="panel card"><div class="label">${l}</div><div class="big">${b}</div><div class="sub">${s}</div></div>`).join("");
  $("#dNote").textContent = `refreshed ${ago(d.time)}`;
  const q = $("#dSearch").value.toLowerCase(), f = $("#dState").value, group = $("#dGroup").value;
  let rows = cs.filter(c => (!q || `${c.name} ${c.image} ${c.project || ""}`.toLowerCase().includes(q)) &&
    (!f || (f === "running" && c.state === "running") || (f === "stopped" && c.state !== "running") || (f === "problem" && isProblem(c))));
  const now = Date.now() / 1000;
  const row = c => {
    const s = c.stats;
    return `<tr data-row="${c.id}" style="cursor:pointer">
      <td><div class="mono" style="font-weight:600">${esc(c.name)}${c.is_self ? `<span class="selfbadge">this app</span>` : ""}</div>${c.project && group !== "project" ? `<div class="dim" style="font-size:11px">${esc(c.project)}</div>` : ""}</td>
      <td>${stateChip(c)}${c.restart_count ? ` <span class="chip amber" title="restart count">↻${c.restart_count}</span>` : ""}</td>
      <td class="mono muted trunc" style="max-width:190px" title="${esc(c.image)}">${esc(c.image)}</td>
      <td class="r">${s ? `<div class="cellbar"><span class="mono" style="color:${barColor(s.cpu)}">${s.cpu.toFixed(1)}%</span><div class="bar"><i style="width:${Math.min(s.cpu * 4, 100)}%;background:${barColor(s.cpu)}"></i></div></div>` : `<span class="dim">-</span>`}</td>
      <td class="r mono">${s ? `${fmtBytes(s.mem_used)}<div class="dim" style="font-size:11px">${s.mem_limit && s.mem_limit < (d.info.mem || Infinity) ? "of " + fmtBytes(s.mem_limit) : (s.mem_pct.toFixed(1) + "% of host")}</div>` : `<span class="dim">-</span>`}</td>
      <td class="r mono muted" style="font-size:12px">${s ? `↓ ${fmtBytes(s.net_rx)}<br>↑ ${fmtBytes(s.net_tx)}` : "-"}</td>
      <td class="r mono muted">${c.state === "running" ? fmtDur(now - c.started) : (c.finished ? ago(c.finished) : "-")}</td>
      <td class="mono" style="font-size:12px">${c.ports.length ? c.ports.slice(0, 2).map(p => `<span class="chip">${esc(p)}</span>`).join(" ") + (c.ports.length > 2 ? ` <span class="dim" title="${esc(c.ports.slice(2).join(", "))}">+${c.ports.length - 2}</span>` : "") : (c.network_mode === "host" ? `<span class="chip violet">host</span>` : "")}</td>
      <td class="r"><div class="actions" style="justify-content:flex-end"><button class="btn sm" data-logs="${esc(c.name)}" title="Logs">Logs</button>${actionButtons(c)}</div></td></tr>`;
  };
  if (group === "project") {
    const groups = {};
    rows.forEach(c => (groups[c.project || "(no project)"] ||= []).push(c));
    tb.innerHTML = Object.keys(groups).sort().map(g => `<tr><td colspan="9" style="background:var(--bg2);font-size:11px;text-transform:uppercase;letter-spacing:1px;color:var(--muted);font-weight:700">${esc(g)} · ${groups[g].filter(c => c.state === "running").length}/${groups[g].length} running</td></tr>` + groups[g].map(row).join("")).join("");
  } else tb.innerHTML = rows.map(row).join("") || `<tr><td colspan="9" class="empty">No containers match</td></tr>`;
  if (state.drawer?.type === "container") refreshDrawerState();
}

async function containerAction(id, act) {
  const c = D.data?.containers.find(x => x.id === id); const name = c?.name || id;
  let removeVolumes = false;
  if (act === "stop" || act === "pause") {
    if (!await confirmDanger(`${act === "stop" ? "Stop" : "Pause"} ${name}?`, act === "stop" ? "The container will shut down. You can start it again from here." : "All processes in the container are frozen until you resume it.", act === "stop" ? "Stop" : "Pause")) return;
  }
  if (act === "remove") {
    const r = await dialog(`Remove ${name}?`, `<p class="muted" style="margin-top:0">This deletes the stopped container. Its image stays until you clean up images.</p>
      <label class="switch"><input type="checkbox" id="rmVols"><span class="t"></span>Also delete its anonymous volumes (data stored only inside this container)</label>`,
      [{ label: "Cancel", value: null }, { label: "Remove", cls: "primary", action: body => ({ v: $("#rmVols", body).checked }) }]);
    if (!r) return; removeVolumes = r.v;
  }
  try {
    await api(`api/docker/${id}/${act}${removeVolumes ? "?remove_volumes=true" : ""}`, { method: "POST" });
    toast(`${name}: ${act} done`);
    if (act === "remove" && state.drawer?.id === id) closeDrawer();
    setTimeout(loadDocker, 1200);
  } catch (err) { toast(err.message); }
}

$("#dSearch").addEventListener("input", renderDocker);
$("#dState").addEventListener("change", renderDocker);
$("#dGroup").addEventListener("change", renderDocker);
$("#dTbl").addEventListener("click", async e => {
  const lg = e.target.closest("[data-logs]"); if (lg) { e.stopPropagation(); return openLogsFor(lg.dataset.logs); }
  const b = e.target.closest("[data-act]"); if (b) { e.stopPropagation(); b.disabled = true; await containerAction(b.dataset.id, b.dataset.act); b.disabled = false; return; }
  const tr = e.target.closest("[data-row]"); if (tr) openContainer(tr.dataset.row);
});

/* ---------- details drawer ---------- */
async function openContainer(id) {
  const c = D.data?.containers.find(x => x.id === id); if (!c) return;
  state.drawer = { type: "container", id, range: "24h" };
  openDrawer(c.name, stateChip(c), `<div class="empty">Loading</div>`);
  try {
    const [info, hist] = await Promise.all([api(`api/docker/${id}/inspect`), api(`api/docker/${encodeURIComponent(c.name)}/history?range=24h`)]);
    if (state.drawer?.id !== id) return;
    state.drawer.info = info;
    renderContainerDrawer(c, info, hist);
  } catch (e) { $("#drBody").innerHTML = `<div class="notice bad">${esc(e.message)}</div>`; }
}
function refreshDrawerState() {
  const c = D.data?.containers.find(x => x.id === state.drawer.id); if (!c) return;
  $("#drState").innerHTML = stateChip(c);
  const a = $("#drActions"); if (a) a.innerHTML = `<button class="btn sm" data-logs="${esc(c.name)}">View logs</button>` + actionButtons(c, false);
}
function renderContainerDrawer(c, info, hist) {
  const kv = rows => `<dl class="kvs">${rows.filter(r => r[1] != null && r[1] !== "").map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v}</dd>`).join("")}</dl>`;
  const h = info.health || {};
  $("#drBody").innerHTML = `
    <div class="actions" id="drActions"></div>
    <div class="section-t">Usage <span class="seg" id="drRange" style="float:right;margin-top:-6px"></span></div>
    <div class="chart" id="drChartCpu" style="height:140px"><canvas></canvas><div class="tip"></div></div>
    <div class="chart mt" id="drChartMem" style="height:140px"><canvas></canvas><div class="tip"></div></div>
    <div class="section-t">Container</div>
    ${kv([["Image", esc(info.image)], ["Image ID", esc(info.image_id)], ["Created", info.created ? esc(new Date(info.created * 1000).toLocaleString()) : null],
      ["Started", info.started && info.state === "running" ? `${esc(new Date(info.started * 1000).toLocaleString())} (${fmtDur(Date.now() / 1000 - info.started)})` : null],
      ["Last exit", info.state !== "running" ? `code ${info.exit_code}${info.oom_killed ? " · killed: out of memory" : ""}${info.error ? " · " + esc(info.error) : ""}` : null],
      ["Restart policy", esc(info.restart_policy)], ["Restarts", info.restart_count], ["Command", esc(info.command)], ["User", esc(info.user)],
      ["Network", esc(info.network_mode)], ["Privileged", info.privileged ? "yes" : null],
      ["Memory limit", info.mem_limit ? fmtBytes(info.mem_limit) : "none"], ["CPU limit", info.cpu_limit ? info.cpu_limit + " cores" : "none"],
      ["Compose", info.compose_project ? `${esc(info.compose_project)} / ${esc(info.compose_service)}` : null], ["Compose folder", esc(info.compose_dir)]])}
    ${info.ports.length ? `<div class="section-t">Ports</div><div class="actions">${info.ports.map(p => `<span class="chip">${esc(p)}</span>`).join("")}</div>` : ""}
    ${info.networks.length ? `<div class="section-t">Networks</div>${kv(info.networks.map(n => [n.name, esc(n.ip || "-")]))}` : ""}
    ${info.mounts.length ? `<div class="section-t">Volumes & mounts</div><div class="tablewrap"><table class="data"><thead><tr><th>Container path</th><th>Source</th><th></th></tr></thead><tbody>${info.mounts.map(m => `<tr><td class="mono" style="font-size:12px">${esc(m.dest)}</td><td class="mono muted trunc" style="font-size:12px;max-width:260px" title="${esc(m.source)}">${esc(m.source)}</td><td>${m.rw ? "" : `<span class="chip">ro</span>`} <span class="chip">${esc(m.type)}</span></td></tr>`).join("")}</tbody></table></div>` : ""}
    ${info.env_keys.length ? `<div class="section-t">Environment variables (${info.env_keys.length})</div><div class="actions">${info.env_keys.map(k => `<span class="chip">${esc(k)}</span>`).join("")}</div><div class="dim mt" style="font-size:11px">Values are hidden.</div>` : ""}
    ${h.status ? `<div class="section-t">Health check: ${esc(h.status)}${h.failing_streak ? `, failing ${h.failing_streak}x` : ""}</div>${(h.log || []).map(l => `<div class="check"><span class="st ${l.exit === 0 ? "ok" : "bad"}">${l.exit === 0 ? "✓" : "✕"}</span><span class="name" style="white-space:normal;font-size:12px">${esc(l.output || "(no output)")}</span><span class="val">${l.start ? esc(fmtTime(l.start)) : ""}</span></div>`).join("")}` : ""}`;
  refreshDrawerState();
  seg("#drRange", [["1h", "1h"], ["24h", "24h"], ["7d", "7d"], ["30d", "30d"]], state.drawer.range, async v => {
    state.drawer.range = v; drawContainerCharts(await api(`api/docker/${encodeURIComponent(c.name)}/history?range=${v}`));
  });
  drawContainerCharts(hist);
}
function drawContainerCharts(hist) {
  const p = hist.points, now = Date.now() / 1000, span = { "1h": 3600, "24h": 86400, "7d": 7 * 86400, "30d": 30 * 86400 }[hist.range] || 86400;
  const o = { from: now - span, to: now, gap: hist.bucket * 3.5, empty: "No history yet (collected every 30 seconds while running)" };
  chart("drChartCpu", [{ name: "CPU", color: C.cyan, data: p.map(r => [r.t, r.cpu]) }], { ...o, fmt: v => v.toFixed(1) + "%" });
  chart("drChartMem", [{ name: "Memory", color: C.violet, data: p.map(r => [r.t, r.mem]) }], { ...o, fmt: v => fmtBytes(v) });
}
$("#drBody").addEventListener("click", async e => {
  const lg = e.target.closest("[data-logs]"); if (lg) { closeDrawer(); return openLogsFor(lg.dataset.logs); }
  const b = e.target.closest("[data-act]"); if (b) { b.disabled = true; await containerAction(b.dataset.id, b.dataset.act); b.disabled = false; }
});

/* ---------- disk usage & cleanup ---------- */
async function openDiskUsage(force = false) {
  dialog("Docker disk usage", `<div class="empty">Measuring, this can take a few seconds</div>`, [{ label: "Close" }]);
  let du;
  try { du = await api(`api/docker/df${force ? "?force=true" : ""}`); }
  catch (e) { $("#dlgBody").innerHTML = `<div class="notice bad">${esc(e.message)}</div>`; return; }
  const manage = canManage();
  const line = (label, detail, size, target, btn) => `<div class="dfrow"><div><b style="font-family:inherit">${label}</b><div class="muted" style="font-size:12px">${detail}</div></div><b>${fmtBytes(size)}</b>${target && manage ? `<button class="btn sm danger" data-prune="${target}">${btn}</button>` : "<span></span>"}</div>`;
  $("#dlgBody").innerHTML = `
    ${line("Unused images", `${du.images.unused_count} of ${du.images.count} images are not used by any container`, du.images.unused_size, "images_unused", "Remove unused")}
    ${line("Dangling images", `${du.images.dangling_count} untagged leftovers from rebuilds and pulls`, du.images.dangling_size, "images_dangling", "Remove")}
    ${line("Build cache", `${du.build_cache.count} entries`, du.build_cache.reclaimable, "build_cache", "Clear")}
    ${line("Stopped containers", `${du.containers.stopped} stopped, writable layers total ${fmtBytes(du.containers.size)}`, du.containers.size, "containers", "Remove stopped")}
    ${line("Volumes", `${du.volumes.count} volumes, ${du.volumes.unused_count} not attached. Volumes hold data, so remove them by hand.`, du.volumes.size, null)}
    <div class="section-t">Largest images</div>
    <div class="tablewrap"><table class="data"><tbody>${du.top_images.map(i => `<tr><td class="mono trunc" style="max-width:320px;font-size:12px">${esc(i.tag)}</td><td>${i.in_use ? `<span class="chip green">in use</span>` : `<span class="chip">unused</span>`}</td><td class="r mono">${fmtBytes(i.size)}</td></tr>`).join("")}</tbody></table></div>
    ${manage ? "" : `<div class="notice mt">Cleanup is off. Turn on container controls in Settings.</div>`}`;
  $("#dlgBody").onclick = async e => {
    const b = e.target.closest("[data-prune]"); if (!b) return;
    const labels = { images_unused: "every image not used by a container (they will be downloaded again if needed)", images_dangling: "dangling images", build_cache: "the build cache", containers: "all stopped containers" };
    if (!confirm(`Remove ${labels[b.dataset.prune]}?`)) return;
    b.disabled = true; b.textContent = "Working";
    try { const r = await api("api/docker/prune", { method: "POST", json: { target: b.dataset.prune } }); toast(`Freed ${fmtBytes(r.freed)} (${r.removed} removed)`); openDiskUsage(true); loadDocker(); }
    catch (err) { toast(err.message); b.disabled = false; }
  };
}
$("#dDiskBtn").onclick = () => openDiskUsage();
Tabs.docker = { load: loadDocker, period: 5000 };
