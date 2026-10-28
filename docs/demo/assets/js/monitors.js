/* Monitors tab: uptime checks (the Uptime Kuma replacement). */
"use strict";
const MN = { data: null, sel: null, range: "24h" };
const TYPE_LABEL = { http: "HTTP(S)", tcp: "TCP port", ping: "Ping", dns: "DNS", docker: "Container" };

async function loadMonitors() {
  try { MN.data = await api("api/monitors"); renderMonitors(); if (MN.sel) loadMonitorDetail(MN.sel, true); }
  catch (e) { $("#mnList").innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
}
const monTarget = m => m.type === "tcp" ? `${m.target}:${m.port}` : m.type === "http" && m.keyword ? `${m.target} · "${m.keyword}"` : m.target;
const beatsHtml = (beats, n = 40) => `<div class="beats">${Array.from({ length: Math.max(0, n - beats.length) }, () => "<i></i>").join("")}${beats.slice(-n).map(b => `<i class="${b.ok ? "ok" : "bad"}" title="${esc(new Date(b.ts * 1000).toLocaleString())}: ${esc(b.msg || "")}${b.ms != null ? " (" + b.ms.toFixed(0) + " ms)" : ""}"></i>`).join("")}</div>`;

function renderMonitors() {
  const d = MN.data; if (!d) return;
  const s = d.summary, ms = d.monitors;
  const avgUp = ms.filter(m => m.uptime_24h != null);
  $("#mnSummary").innerHTML = [
    ["Up", `<span class="c-ok">${s.up}</span>`, `of ${s.total} monitors`],
    ["Down", `<span class="${s.down ? "c-crit" : ""}">${s.down}</span>`, s.down ? s.down_names.slice(0, 3).join(", ") : "nothing down"],
    ["Paused", s.paused, s.pending ? `${s.pending} waiting for first check` : "monitors"],
    ["Uptime (24h)", avgUp.length ? (avgUp.reduce((a, m) => a + m.uptime_24h, 0) / avgUp.length).toFixed(2) + "<small>%</small>" : "-", "average across monitors"],
  ].map(([l, b, sub]) => `<div class="panel card"><div class="label">${l}</div><div class="big">${b}</div><div class="sub">${esc(String(sub)).replace(/&lt;small&gt;/g, "")}</div></div>`).join("");
  const q = $("#mnSearch").value.toLowerCase();
  const rows = ms.filter(m => !q || `${m.name} ${m.target}`.toLowerCase().includes(q));
  rows.sort((a, b) => (a.status === "down" ? 0 : 1) - (b.status === "down" ? 0 : 1));
  $("#mnList").innerHTML = rows.map(m => `<div class="mon ${m.id === MN.sel ? "sel" : ""}" data-id="${m.id}">
      <span class="dotbig st-${m.status}" title="${m.status}"></span>
      <div style="min-width:0"><div class="nm">${esc(m.name)}</div><div class="tg">${esc(TYPE_LABEL[m.type] || m.type)} · ${esc(monTarget(m))}</div></div>
      ${beatsHtml(m.beats || [])}
      <div class="pct" style="color:${uptimeColor(m.uptime_24h)}">${m.uptime_24h != null ? m.uptime_24h.toFixed(2) + "%" : "-"}</div>
      <div class="ms">${m.avg_ms_24h != null ? m.avg_ms_24h.toFixed(0) + " ms" : ""}</div>
      <div class="actions"><button class="btn sm" data-edit="${m.id}" title="Edit">Edit</button></div></div>`).join("") ||
    `<div class="panel empty">${ms.length ? "No monitors match" : `No monitors yet.<br><br>Add one, or import everything from Uptime Kuma in one click.`}</div>`;
}

async function loadMonitorDetail(id, quiet = false) {
  MN.sel = id;
  $$("#mnList .mon").forEach(x => x.classList.toggle("sel", +x.dataset.id === id));
  if (!quiet) $("#mnDetail").innerHTML = `<div class="empty">Loading</div>`;
  try { renderMonitorDetail(await api(`api/monitors/${id}?range=${MN.range}`)); }
  catch (e) { $("#mnDetail").innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
}
function renderMonitorDetail(m) {
  const up = k => m[k] != null ? `<b style="color:${uptimeColor(m[k])}">${m[k].toFixed(2)}%</b>` : "<b>-</b>";
  const statusTxt = { up: "Up", down: "Down", pending: "Pending", paused: "Paused" }[m.status];
  $("#mnDetail").innerHTML = `
    <div class="row"><span class="dotbig st-${m.status}" style="width:12px;height:12px;border-radius:50%;background:currentColor;box-shadow:0 0 10px currentColor"></span>
      <b style="font-size:17px">${esc(m.name)}</b><span class="spacer"></span>
      <button class="btn sm" data-mact="check">Check now</button><button class="btn sm" data-mact="toggle">${m.enabled ? "Pause" : "Resume"}</button><button class="btn sm" data-edit="${m.id}">Edit</button></div>
    <div class="muted mono" style="font-size:12px;margin:6px 0 2px;word-break:break-all">${esc(TYPE_LABEL[m.type])} · ${esc(monTarget(m))}</div>
    <div class="muted" style="font-size:12px">${statusTxt}${m.since ? " for " + fmtDur(Date.now() / 1000 - m.since) : ""} · every ${fmtDur(m.interval)} · down after ${m.retries} failed check${m.retries > 1 ? "s" : ""}${m.notify ? "" : " · alerts off"}</div>
    <div class="mini-stats" style="margin:12px 0"><span>24h ${up("uptime_24h")}</span><span>7d ${up("uptime_7d")}</span><span>30d ${up("uptime_30d")}</span><span>avg <b>${m.avg_ms_24h != null ? m.avg_ms_24h.toFixed(0) + " ms" : "-"}</b></span></div>
    <div class="row"><div class="seg" id="mnRange"></div></div>
    <div class="chart mt" id="chMon" style="height:170px"><canvas></canvas><div class="tip"></div></div>
    <div class="section-t">Incidents</div>
    <div class="feed">${feedHtml(m.incidents || [], "No incidents in the kept history.")}</div>
    <div class="section-t">Recent checks</div>
    <div class="tablewrap" style="max-height:260px;overflow:auto"><table class="data"><tbody>${(m.recent || []).slice(0, 50).map(b => `<tr><td><span class="chip ${b.ok ? "green" : "red"}">${b.ok ? "UP" : "DOWN"}</span></td><td class="mono muted" style="font-size:12px">${esc(fmtTime(b.ts, true))}</td><td class="r mono">${b.ms != null ? b.ms.toFixed(0) + " ms" : ""}</td><td class="muted trunc" style="max-width:240px;font-size:12px" title="${esc(b.msg)}">${esc(b.msg)}</td></tr>`).join("")}</tbody></table></div>
    <div class="row mt"><span class="spacer"></span><button class="btn sm danger" data-mact="delete">Delete monitor</button></div>`;
  seg("#mnRange", [["1h", "1h"], ["24h", "24h"], ["7d", "7d"], ["30d", "30d"], ["90d", "90d"]], MN.range, v => { MN.range = v; loadMonitorDetail(m.id, true); });
  const now = Date.now() / 1000, span = { "1h": 3600, "24h": 86400, "7d": 7 * 86400, "30d": 30 * 86400, "90d": 90 * 86400 }[m.range];
  const pts = m.series || [];
  const hasMs = pts.some(p => p.ms != null);
  chart("chMon", hasMs ? [{ name: "Response", color: C.cyan, data: pts.map(p => [p.t, p.ms]) }, { name: "Down", color: C.red, data: pts.filter(p => !p.ok).map(p => [p.t, p.ms ?? 0]), fill: false, dots: true }]
                       : [{ name: "Up", color: C.green, data: pts.map(p => [p.t, p.ok ? 1 : 0]) }],
    { from: now - span, to: now, fmt: hasMs ? v => v.toFixed(0) + " ms" : v => v >= .99 ? "up" : v <= .01 ? "down" : "", max: hasMs ? undefined : 1, gap: Math.max(m.interval * 4, Math.max(60, span / 240) * 2.5), empty: "No checks yet" });
  $("#mnDetail").dataset.id = m.id; $("#mnDetail").dataset.enabled = m.enabled;
}

$("#mnList").addEventListener("click", e => {
  const ed = e.target.closest("[data-edit]"); if (ed) { e.stopPropagation(); return editMonitor(+ed.dataset.edit); }
  const card = e.target.closest(".mon"); if (card) loadMonitorDetail(+card.dataset.id);
});
$("#mnDetail").addEventListener("click", async e => {
  const ed = e.target.closest("[data-edit]"); if (ed) return editMonitor(+ed.dataset.edit);
  const b = e.target.closest("[data-mact]"); if (!b) return;
  const id = +$("#mnDetail").dataset.id;
  try {
    if (b.dataset.mact === "check") { b.disabled = true; b.textContent = "Checking"; renderMonitorDetail(await api(`api/monitors/${id}/check`, { method: "POST" })); loadMonitors(); }
    if (b.dataset.mact === "toggle") { await api(`api/monitors/${id}`, { method: "PUT", json: { enabled: $("#mnDetail").dataset.enabled !== "1" } }); loadMonitors(); }
    if (b.dataset.mact === "delete") {
      if (!await confirmDanger("Delete this monitor?", "Its history and uptime data are deleted too.", "Delete")) return;
      await api(`api/monitors/${id}`, { method: "DELETE" }); MN.sel = null; $("#mnDetail").innerHTML = `<div class="empty">Monitor deleted.</div>`; loadMonitors();
    }
  } catch (err) { toast(err.message); b.disabled = false; }
});
$("#mnSearch").addEventListener("input", renderMonitors);

/* ---------- editor ---------- */
function monitorForm(m) {
  const v = k => esc(m[k] ?? "");
  const containers = (D.data?.containers || []).map(c => c.name).sort();
  return `<div class="grid-f">
    <div class="field"><label>Type</label><select class="select" name="type">${Object.entries(TYPE_LABEL).map(([k, l]) => `<option value="${k}" ${m.type === k ? "selected" : ""}>${l}</option>`).join("")}</select></div>
    <div class="field"><label>Name</label><input class="input" name="name" value="${v("name")}" placeholder="Sonarr"></div>
  </div>
  <div class="field" data-for="http"><label>URL</label><input class="input" name="target_http" value="${m.type === "http" ? v("target") : ""}" placeholder="http://192.168.0.150:8989"></div>
  <div class="grid-f" data-for="tcp"><div class="field"><label>Host</label><input class="input" name="target_tcp" value="${m.type === "tcp" ? v("target") : ""}" placeholder="192.168.0.150"></div>
    <div class="field"><label>Port</label><input class="input" type="number" name="port" value="${v("port")}" placeholder="8989"></div></div>
  <div class="field" data-for="ping"><label>Host or IP</label><input class="input" name="target_ping" value="${m.type === "ping" ? v("target") : ""}" placeholder="bhxuk-nas or 100.x.x.x"></div>
  <div class="field" data-for="dns"><label>Hostname to resolve</label><input class="input" name="target_dns" value="${m.type === "dns" ? v("target") : ""}" placeholder="google.com"></div>
  <div class="field" data-for="docker"><label>Container</label><select class="select" name="target_docker">${containers.map(n => `<option ${m.target === n ? "selected" : ""}>${esc(n)}</option>`).join("")}${m.type === "docker" && m.target && !containers.includes(m.target) ? `<option selected>${v("target")}</option>` : ""}</select><span class="hint">Down when the container is not running or its health check fails.</span></div>
  <div data-for="http">
    <div class="grid-f">
      <div class="field"><label>Expected status codes</label><input class="input" name="expect" value="${m.expect ? v("expect") : "200-399"}"><span class="hint">e.g. 200-399, 200,401</span></div>
      <div class="field"><label>Method</label><select class="select" name="method">${["GET", "HEAD", "POST"].map(x => `<option ${m.method === x ? "selected" : ""}>${x}</option>`).join("")}</select></div>
    </div>
    <div class="grid-f">
      <div class="field"><label>Keyword (optional)</label><input class="input" name="keyword" value="${v("keyword")}" placeholder="Text that must appear in the page"></div>
      <div class="field"><label>&nbsp;</label><label class="switch"><input type="checkbox" name="invert" ${m.invert ? "checked" : ""}><span class="t"></span>Down if keyword IS found</label></div>
    </div>
    <label class="switch mb"><input type="checkbox" name="ignore_tls" ${m.ignore_tls ? "checked" : ""}><span class="t"></span>Ignore TLS certificate errors (self-signed)</label>
  </div>
  <div class="grid-f mt">
    <div class="field"><label>Check every</label><select class="select" name="interval">${[[20, "20 seconds"], [30, "30 seconds"], [60, "1 minute"], [120, "2 minutes"], [300, "5 minutes"], [900, "15 minutes"], [3600, "1 hour"]].map(([s, l]) => `<option value="${s}" ${(+m.interval || 60) === s ? "selected" : ""}>${l}</option>`).join("")}</select></div>
    <div class="field"><label>Mark down after</label><select class="select" name="retries">${[1, 2, 3, 5].map(n => `<option value="${n}" ${(+m.retries || 2) === n ? "selected" : ""}>${n} failed check${n > 1 ? "s" : ""}</option>`).join("")}</select></div>
    <div class="field"><label>Timeout (seconds)</label><input class="input" type="number" name="timeout" min="2" max="60" value="${m.timeout || 10}"></div>
    <div class="field"><label>&nbsp;</label><label class="switch"><input type="checkbox" name="notify" ${m.notify === 0 ? "" : "checked"}><span class="t"></span>Send alerts</label></div>
  </div>
  <div id="mfTest" class="mt"></div>`;
}
function readMonitorForm(body) {
  const f = n => body.querySelector(`[name="${n}"]`);
  const type = f("type").value;
  return {
    type, name: f("name").value.trim(), target: (f(`target_${type}`).value || "").trim(), port: type === "tcp" ? +f("port").value || null : null,
    expect: f("expect").value.trim() || "200-399", method: f("method").value, keyword: type === "http" ? f("keyword").value.trim() || null : null,
    invert: f("invert").checked, ignore_tls: f("ignore_tls").checked, interval: +f("interval").value, retries: +f("retries").value,
    timeout: +f("timeout").value || 10, notify: f("notify").checked,
  };
}
async function editMonitor(id = null, preset = {}) {
  if (!D.data) { try { D.data = await api("api/docker"); } catch {} }
  const m = id ? MN.data.monitors.find(x => x.id === id) : { type: "http", interval: 60, retries: 2, ...preset };
  const sync = body => { const t = body.querySelector('[name="type"]').value; $$("[data-for]", body).forEach(el => el.hidden = el.dataset.for !== t); };
  const p = dialog(id ? `Edit ${m.name}` : "Add monitor", monitorForm(m), [
    { label: "Cancel", value: null },
    { label: "Test", action: async body => { const r = await api("api/monitors/test", { method: "POST", json: readMonitorForm(body) }); $("#mfTest", body).innerHTML = `<div class="notice ${r.ok ? "good" : "bad"}">${r.ok ? "✓ Up" : "✕ Down"}: ${esc(r.msg)}${r.ms != null ? ` (${r.ms.toFixed(0)} ms)` : ""}</div>`; return false; } },
    { label: id ? "Save" : "Add monitor", cls: "primary", action: async body => {
      const data = readMonitorForm(body);
      if (!data.name) data.name = data.target.replace(/^https?:\/\//, "").replace(/\/$/, "");
      return id ? api(`api/monitors/${id}`, { method: "PUT", json: data }) : api("api/monitors", { method: "POST", json: data });
    } },
  ]);
  const body = $("#dlgBody"); sync(body); body.querySelector('[name="type"]').onchange = () => sync(body);
  const saved = await p;
  if (saved && saved.id) { toast(id ? "Monitor saved" : "Monitor added"); await loadMonitors(); loadMonitorDetail(saved.id); }
}
$("#mnAdd").onclick = () => editMonitor();

/* ---------- import from Uptime Kuma ---------- */
$("#mnKuma").onclick = async () => {
  let found;
  try { found = await api("api/monitors/kuma"); } catch (e) { return toast(e.message); }
  if (!found.found) return dialog("Import from Uptime Kuma", `<div class="notice bad">${esc(found.message)}</div><p class="muted" style="font-size:13px">The import reads Uptime Kuma's database through its Docker volume, so the Uptime Kuma container needs to still exist (it can be stopped).</p>`);
  const r = await dialog("Import from Uptime Kuma", `<div class="notice good">${esc(found.message)}</div>
    <p class="muted" style="font-size:13px">Copies your HTTP, keyword, port, ping, DNS and Docker monitors with their intervals and retries. Monitors that already exist here are skipped. Uptime Kuma itself is not changed.</p>
    <label class="switch"><input type="checkbox" id="kNotif" checked><span class="t"></span>Also import Discord, Telegram, ntfy, Slack and webhook alert channels</label>`,
    [{ label: "Cancel", value: null }, { label: "Import", cls: "primary", action: body => api("api/monitors/import-kuma", { method: "POST", json: { include_notifications: $("#kNotif", body).checked } }) }]);
  if (!r) return;
  await loadMonitors();
  dialog("Import finished", `<div class="notice good">Imported ${r.added.length} monitor${r.added.length === 1 ? "" : "s"}${r.channels_added.length ? ` and ${r.channels_added.length} alert channel${r.channels_added.length === 1 ? "" : "s"}` : ""}.</div>
    ${r.skipped.length ? `<div class="section-t">Already here (skipped)</div><div class="muted" style="font-size:13px">${r.skipped.map(esc).join(", ")}</div>` : ""}
    ${r.unsupported.length ? `<div class="section-t">Not imported</div><div class="muted" style="font-size:13px">${r.unsupported.map(esc).join(", ")}</div>` : ""}
    <p class="muted" style="font-size:13px">Tip: monitors that pointed at Docker container names (like <span class="mono">http://sonarr:8989</span>) may need changing to the server's IP, because HomeLabStats checks from the host.</p>`);
};
Tabs.monitors = { load: loadMonitors, period: 10000 };
