/* Metrics tab: long-term history (the Netdata / Glances replacement). */
"use strict";
const M = { range: "1h", ctMetric: "cpu" };
const M_RANGES = [["1h", "1h"], ["6h", "6h"], ["24h", "24h"], ["7d", "7d"], ["30d", "30d"], ["90d", "90d"]];

async function loadMetrics() {
  try {
    const [sys, ct, sens] = await Promise.all([
      api(`api/metrics/system?range=${M.range}`),
      api(`api/metrics/containers?range=${M.range}&metric=${M.ctMetric}&top=8`),
      api("api/sensors"),
    ]);
    renderMetrics(sys, ct, sens);
  } catch (e) { $("#mNote").textContent = e.message; }
}

function renderMetrics(sys, ct, sens) {
  const p = sys.points, s = sys.summary || {}, now = Date.now() / 1000;
  const from = sys.since, to = now, gap = sys.bucket * 3.5;
  const opt = (o) => ({ from, to, gap, ...o });
  $("#mNote").textContent = p.length ? `${p.length} points, ${sys.bucket >= 60 ? sys.bucket / 60 + " min" : sys.bucket + " s"} resolution` : "History builds up from the moment HomeLabStats starts.";
  const col = k => p.map(r => [r.t, r[k]]);
  $("#mSummary").innerHTML = [
    ["CPU average", pct(s.cpu_avg, 1), `peak ${pct(s.cpu_peak)}`],
    ["Memory average", pct(s.mem_avg, 1), `peak ${pct(s.mem_peak)}`],
    ["Downloaded", fmtBytes(s.rx_total), `peak ${fmtBits(s.rx_peak)}`],
    ["Uploaded", fmtBytes(s.tx_total), `peak ${fmtBits(s.tx_peak)}`],
    ["Temperature", s.temp_avg != null ? s.temp_avg.toFixed(0) + "°C" : "n/a", s.temp_peak != null ? `peak ${s.temp_peak.toFixed(0)}°C` : "no sensor"],
  ].map(([l, b, sub]) => `<div class="panel card"><div class="label">${l}</div><div class="big" style="font-size:24px">${b}</div><div class="sub">${sub}</div></div>`).join("");

  chart("ch-m-cpu", [{ name: "CPU avg", color: C.cyan, data: col("cpu") }, { name: "CPU peak", color: C.cyan + "77", data: col("cpu_max"), fill: false }], opt({ max: 100, fmt: v => v.toFixed(0) + "%" }));
  legend("lg-m-cpu", [["Average", C.cyan], ["Peak", C.cyan + "77"]]);
  chart("ch-m-mem", [{ name: "Memory", color: C.violet, data: col("mem") }, { name: "Swap", color: C.amber, data: col("swap") }], opt({ max: 100, fmt: v => v.toFixed(0) + "%" }));
  legend("lg-m-mem", [["Memory", C.violet], ["Swap", C.amber]]);
  chart("ch-m-net", [{ name: "In", color: C.cyan, data: col("rx") }, { name: "Out", color: C.violet, data: col("tx") }], opt({ fmt: v => fmtBits(v) }));
  legend("lg-m-net", [["In", C.cyan, fmtBytes(s.rx_total)], ["Out", C.violet, fmtBytes(s.tx_total)]]);
  chart("ch-m-disk", [{ name: "Read", color: C.green, data: col("dr") }, { name: "Write", color: C.orange, data: col("dw") }], opt({ fmt: v => fmtBytes(v) + "/s" }));
  legend("lg-m-disk", [["Read", C.green], ["Write", C.orange]]);
  chart("ch-m-load", [{ name: "Load (1 min)", color: C.blue, data: col("load1") }], opt({ fmt: v => v.toFixed(1) }));
  legend("lg-m-load", [["1 min load", C.blue]]);
  const hasTemp = p.some(r => r.temp != null);
  chart("ch-m-temp", [{ name: "CPU", color: C.red, data: col("temp") }], opt({ fmt: v => v.toFixed(0) + "°", empty: hasTemp ? "No data yet" : "No CPU temperature sensor found", min: hasTemp ? Math.max(0, Math.floor(Math.min(...p.filter(r => r.temp != null).map(r => r.temp)) / 10) * 10 - 10) : 0 }));
  legend("lg-m-temp", [["CPU", C.red]]);

  const fmtCt = { cpu: v => v.toFixed(1) + "%", mem: v => fmtBytes(v), rx: v => fmtBits(v), tx: v => fmtBits(v) }[ct.metric];
  const names = ct.leaders.map(l => l.name);
  chart("ch-m-ct", names.map((n, i) => ({ name: n, color: PALETTE[i % PALETTE.length], data: ct.series[n] || [], fill: false })), { from, to, gap: Math.max(ct.bucket * 3.5, 90), fmt: fmtCt, empty: "No container data yet" });
  legend("lg-m-ct", ct.leaders.map((l, i) => [l.name, PALETTE[i % PALETTE.length], `avg ${fmtCt(l.avg)} · peak ${fmtCt(l.peak)}`]));

  const t = sens.temps || [], f = sens.fans || [];
  let html = "";
  if (t.length) html += `<div class="section-t" style="margin-top:0">Temperatures</div><div class="sensors">` + t.map(x => `<div class="sensor"><span title="${esc(x.chip)}">${esc(x.chip)} · ${esc(x.label)}</span><b style="color:${barColor(x.current, (x.high || 80) - 5, x.critical || 90)}">${x.current.toFixed(0)}°C</b></div>`).join("") + `</div>`;
  if (f.length) html += `<div class="section-t">Fans</div><div class="sensors">` + f.map(x => `<div class="sensor"><span>${esc(x.chip)} · ${esc(x.label)}</span><b>${x.rpm} rpm</b></div>`).join("") + `</div>`;
  if (sens.freqs?.length) html += `<div class="section-t">Core clocks</div><div class="sensors">` + sens.freqs.map((v, i) => `<div class="sensor"><span>cpu${i}</span><b>${(v / 1000).toFixed(2)} GHz</b></div>`).join("") + `</div>`;
  if (sens.battery) html += `<div class="section-t">Battery</div><div class="sensors"><div class="sensor"><span>${sens.battery.plugged ? "On mains" : "On battery"}</span><b>${sens.battery.percent.toFixed(0)}%</b></div></div>`;
  if (sens.users?.length) html += `<div class="section-t">Logged-in users</div><div class="sensors">` + sens.users.map(u => `<div class="sensor"><span>${esc(u.terminal || "")} ${u.host ? "from " + esc(u.host) : ""}</span><b style="font-size:14px">${esc(u.name)}</b></div>`).join("") + `</div>`;
  $("#sensors").innerHTML = html || `<div class="muted">No hardware sensors exposed. On the host, install <span class="mono">lm-sensors</span> and run <span class="mono">sudo sensors-detect</span>.</div>`;
  $("#sensNote").textContent = `${t.length} temperature, ${f.length} fan sensors`;
}

seg("#mRange", M_RANGES, M.range, v => { M.range = v; loadMetrics(); });
seg("#mCtMetric", [["cpu", "CPU"], ["mem", "Memory"], ["rx", "Net in"], ["tx", "Net out"]], M.ctMetric, v => { M.ctMetric = v; loadMetrics(); });
$("#mRefresh").onclick = loadMetrics;
Tabs.metrics = { load: loadMetrics, period: 15000 };
