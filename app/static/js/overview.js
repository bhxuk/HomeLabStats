/* Overview tab, plus the header (status, host, update badge). Polled every 2s by boot.js. */
"use strict";
state.topBy = "cpu";

async function loadOverview() {
  try {
    const d = await api("api/overview"); state.overview = d; state.lastOk = Date.now();
    const live = $("#live"); live.classList.remove("stale", "pulse"); void live.offsetWidth; live.classList.add("pulse");
    renderHeader(d);
    if (state.tab === "overview") renderOverview(d);
  } catch (e) { $("#live").classList.add("stale"); $("#liveTxt").textContent = "offline: " + e.message; }
}

function setUpdBadge(available, latest) {
  $("#bUpd").hidden = !available; $("#updPill").hidden = !available;
  if (available) $("#updPill").lastChild.textContent = `Update to v${latest}`;
}

function renderHeader(d) {
  const h = d.host, c = d.current || {};
  $("#hHost").textContent = h.hostname; $("#hOs").textContent = `${h.os} · ${h.kernel} · up ${fmtDur(c.uptime)}`;
  document.title = `${h.hostname} · HomeLabStats`; $("#ver").textContent = "v" + h.version;
  const pill = $("#statusPill"); pill.className = "pill " + d.status;
  const n = d.alerts.length;
  $("#statusTxt").textContent = { ok: "HEALTHY", warn: `${n} WARNING${n > 1 ? "S" : ""}`, crit: "CRITICAL" }[d.status];
  if (d.update) setUpdBadge(d.update.available, d.update.latest);
  $("#bProc").textContent = c.proc_count ?? 0;
  $("#bDock").textContent = d.docker.available ? d.docker.running : "-";
  $("#bDisk").textContent = d.disks.length;
  const mb = $("#bMon"), m = d.monitors || {};
  mb.textContent = m.down ? `${m.down} down` : (m.total || 0); mb.classList.toggle("bad", !!m.down);
}

function renderOverview(d) {
  const h = d.host, c = d.current || {};
  $("#alerts").innerHTML = d.alerts.map(a => `<div class="alert ${a.level}"><span class="tag">${esc(a.area)}</span>${esc(a.message)}</div>`).join("");
  if (c.cpu == null) return;
  $("#cCpu").innerHTML = `${c.cpu.toFixed(0)}<small>%</small>`; $("#cCpu").className = "big c-" + lvl(c.cpu);
  $("#cCpuSub").textContent = `${h.cores_logical} threads · ${h.cpu_model}`; setBar($("#cCpuBar"), c.cpu);
  $("#cMem").innerHTML = `${c.mem.percent.toFixed(0)}<small>%</small>`; $("#cMem").className = "big c-" + lvl(c.mem.percent, 85, 95);
  $("#cMemSub").textContent = `${fmtBytes(c.mem.used)} of ${fmtBytes(c.mem.total)}` + (c.swap.total ? ` · swap ${c.swap.percent.toFixed(0)}%` : "");
  setBar($("#cMemBar"), c.mem.percent, 85, 95);
  if (c.cpu_temp != null) {
    $("#cTemp").innerHTML = `${c.cpu_temp.toFixed(0)}<small>°C</small>`; $("#cTemp").className = "big c-" + lvl(c.cpu_temp, 80, 90);
    const others = (c.temps || []).filter(t => /nvme|drivetemp|amdgpu|nouveau/.test(t.chip));
    $("#cTempSub").textContent = others.length ? others.slice(0, 2).map(t => `${t.chip} ${t.current.toFixed(0)}°`).join(" · ") : "CPU package";
    setBar($("#cTempBar"), c.cpu_temp, 80, 90);
  } else { $("#cTemp").innerHTML = `<span class="dim">n/a</span>`; $("#cTempSub").textContent = "no sensors found"; }
  const loadPct = c.load[0] / h.cores_logical * 100;
  $("#cLoad").textContent = c.load[0].toFixed(2); $("#cLoad").className = "big c-" + lvl(loadPct, 100, 150);
  $("#cLoadSub").textContent = `${c.load.join(" / ")} · ${c.proc_count} processes`; setBar($("#cLoadBar"), loadPct, 100, 150);
  $("#cNet").innerHTML = `<span style="color:var(--cyan)">↓</span> ${fmtBits(c.net_total.rx)}<br><span style="color:var(--violet)">↑</span> ${fmtBits(c.net_total.tx)}`;
  const tt = d.traffic_today;
  $("#cNetSub").textContent = tt ? `today ↓ ${fmtBytes(tt.rx)} ↑ ${fmtBytes(tt.tx)}` : "";
  const dk = d.docker;
  if (dk.available) {
    $("#cDock").innerHTML = `${dk.running}<small>/${dk.total}</small>`; $("#cDock").className = "big " + (dk.unhealthy ? "c-crit" : "");
    $("#cDockSub").textContent = dk.unhealthy ? `${dk.unhealthy} unhealthy` : `running · ${dk.total - dk.running} stopped`;
  } else { $("#cDock").innerHTML = `<span class="dim">n/a</span>`; $("#cDockSub").textContent = "Docker not reachable"; }
  const m = d.monitors || {};
  if (m.total) {
    $("#cMon").innerHTML = `${m.up}<small>/${m.total}</small>`; $("#cMon").className = "big " + (m.down ? "c-crit" : "c-ok");
    $("#cMonSub").textContent = m.down ? `${m.down} down: ${m.down_names.slice(0, 2).join(", ")}` : "all up";
  } else { $("#cMon").innerHTML = `<span class="dim">0</span>`; $("#cMonSub").textContent = "add one on the Monitors tab"; }

  const hist = d.history;
  chart("chSys", [{ name: "CPU", color: C.cyan, data: hist.map(p => [p.t, p.cpu]) }, { name: "Memory", color: C.violet, data: hist.map(p => [p.t, p.mem]) }],
    { max: 100, fmt: v => v.toFixed(0) + "%" });
  legend("lgSys", [["CPU", C.cyan, c.cpu.toFixed(0) + "%"], ["Memory", C.violet, c.mem.percent.toFixed(0) + "%"]]);
  chart("chNet", [{ name: "Down", color: C.cyan, data: hist.map(p => [p.t, p.rx]) }, { name: "Up", color: C.violet, data: hist.map(p => [p.t, p.tx]) }],
    { fmt: v => fmtBits(v) });
  legend("lgNet", [["Down", C.cyan, fmtBits(c.net_total.rx)], ["Up", C.violet, fmtBits(c.net_total.tx)]]);

  $("#coreInfo").textContent = h.cpu_freq_mhz ? `${(h.cpu_freq_mhz / 1000).toFixed(2)} GHz` : "";
  $("#cores").innerHTML = c.per_cpu.map((v, i) => `<div class="core"><div class="v" style="color:${barColor(v)}">${v.toFixed(0)}</div><div class="n">cpu${i}</div><div class="bar"><i style="width:${v}%;background:${barColor(v)}"></i></div></div>`).join("");
  const top = state.topBy === "cpu" ? d.top_cpu : d.top_mem;
  $("#topTbl").innerHTML = top.map(p => `<tr><td class="trunc mono">${esc(p.name)}</td><td class="dim mono" style="font-size:12px">${p.pid}</td><td class="r" style="color:${state.topBy === "cpu" ? barColor(p.cpu) : "inherit"}">${p.cpu.toFixed(1)}%</td><td class="r">${fmtBytes(p.rss)}</td></tr>`).join("");
  $("#diskMini").innerHTML = d.disks.slice(0, 5).map(x => `<div style="margin-bottom:12px"><div style="display:flex;font-size:13px"><span class="mono trunc">${esc(x.mount)}</span><span class="spacer"></span><span class="mono" style="color:${barColor(x.percent, 85, 95)}">${x.percent.toFixed(0)}%</span></div><div class="muted" style="font-size:11px">${fmtBytes(x.free)} free of ${fmtBytes(x.total)}</div><div class="bar thin"><i style="width:${x.percent}%;background:${barColor(x.percent, 85, 95)}"></i></div></div>`).join("") || `<div class="muted">No disks found</div>`;
  $("#feedMini").innerHTML = feedHtml(d.events || []);
}

$("#topSel").addEventListener("change", e => { state.topBy = e.target.value; if (state.overview) renderOverview(state.overview); });
setInterval(() => {
  if (!state.lastOk) return;
  const s = Math.round((Date.now() - state.lastOk) / 1000);
  $("#liveTxt").textContent = s < 4 ? "live" : `updated ${s}s ago`;
  if (s > 15) $("#live").classList.add("stale");
}, 1000);
Tabs.overview = { enter: () => { if (state.overview) renderOverview(state.overview); } };
