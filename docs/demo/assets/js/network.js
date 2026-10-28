/* Network tab: live bandwidth, connectivity checks, speed tests and interfaces. */
"use strict";
const N = { net: null, stRange: "30", stTimer: null, ifTick: 0 };

async function loadNetworkTab() {
  try {
    const t = await api("api/traffic");
    $("#bwRx").textContent = fmtBits(t.now.rx); $("#bwTx").textContent = fmtBits(t.now.tx);
    $("#bwRxSub").textContent = `today ${fmtBytes(t.today.rx)} · peak ${fmtBits(t.today.rx_peak)}`;
    $("#bwTxSub").textContent = `today ${fmtBytes(t.today.tx)} · peak ${fmtBits(t.today.tx_peak)}`;
    $("#bwNote").textContent = "last 6 minutes";
    chart("chBw", [{ name: "In", color: C.cyan, data: t.history.map(p => [p.t, p.rx]) }, { name: "Out", color: C.violet, data: t.history.map(p => [p.t, p.tx]) }], { fmt: v => fmtBits(v) });
    const busy = Object.entries(t.per_interface).filter(([n]) => !n.startsWith("veth") && n !== "lo").sort((a, b) => (b[1].rx + b[1].tx) - (a[1].rx + a[1].tx)).slice(0, 5);
    $("#bwIfaces").innerHTML = busy.map(([n, r]) => `<span class="mono">${esc(n)} <b>↓${fmtBits(r.rx)}</b> <b>↑${fmtBits(r.tx)}</b></span>`).join("");
  } catch (e) { $("#bwNote").textContent = e.message; }
  if (N.ifTick++ % 3 === 0) loadInterfaces();
}

async function loadInterfaces() {
  try {
    const d = await api("api/network");
    const kc = { physical: "cyan", wifi: "cyan", tailscale: "violet", vpn: "violet", container: "", loopback: "" };
    $("#ifTbl tbody").innerHTML = d.interfaces.map(i => `<tr>
      <td class="mono"><span style="color:${i.up ? "var(--green)" : "var(--red)"}">●</span> <b style="font-weight:600">${esc(i.name)}</b>${d.gateway.interface === i.name ? ` <span class="chip cyan">default</span>` : ""}</td>
      <td><span class="chip ${kc[i.kind] || ""}">${i.kind}</span></td>
      <td class="mono" style="font-size:12px">${esc(i.ipv4.join(", ") || i.ipv6[0] || "-")}${i.mac && i.kind !== "loopback" ? `<div class="dim">${esc(i.mac)}</div>` : ""}</td>
      <td class="r mono muted">${i.speed ? (i.speed >= 1000 ? i.speed / 1000 + " Gb" : i.speed + " Mb") : "-"}</td>
      <td class="r mono" style="color:var(--cyan)">${fmtBits(i.rx)}</td><td class="r mono" style="color:var(--violet)">${fmtBits(i.tx)}</td>
      <td class="r mono muted">${fmtBytes(i.rx_total)}</td><td class="r mono muted">${fmtBytes(i.tx_total)}</td>
      <td class="r mono ${i.errors + i.drops ? "c-warn" : "dim"}">${i.errors + i.drops}</td></tr>`).join("");
    if (d.last_check && !N.net) renderChecks(d.last_check);
  } catch (e) { $("#ifTbl tbody").innerHTML = `<tr><td colspan="9" class="empty">${esc(e.message)}</td></tr>`; }
}

function checkRow(ok, name, val, title = "") { return `<div class="check" title="${esc(title)}"><span class="st ${ok ? "ok" : "bad"}">${ok ? "✓" : "✕"}</span><span class="name">${name}</span><span class="val">${val}</span></div>`; }
function pingVal(p) { return p.ok ? `${p.avg?.toFixed(1)} ms <span class="dim">±${p.jitter?.toFixed(1)}</span>${p.loss ? ` <span class="c-warn">${p.loss}% loss</span>` : ""}` : `<span class="c-crit">${esc(p.error || "failed")}</span>`; }
function renderChecks(r) {
  N.net = r;
  const s = r.summary;
  $("#ncSummary").innerHTML = `<span class="${s.passed === s.total ? "c-ok" : "c-warn"}" style="font-weight:600">${s.passed}/${s.total} checks passed</span> <span class="dim">· ${ago(r.time)}</span>`;
  let html = `<div class="subhead">Gateway &amp; public IP</div><div class="checks">`;
  if (r.gateway.ping) html += checkRow(r.gateway.ping.ok, `gateway ${esc(r.gateway.ip)} <span class="dim">via ${esc(r.gateway.interface)}</span>`, pingVal(r.gateway.ping));
  html += checkRow(!!r.public_ip.ip, "public IP", r.public_ip.ip ? `<span style="color:var(--text)">${esc(r.public_ip.ip)}</span>` : `<span class="c-crit">${esc(r.public_ip.error)}</span>`);
  html += `</div><div class="subhead">Ping</div><div class="checks">` + r.pings.map(p => checkRow(p.ok, `${esc(p.target)} <span class="dim">${esc(p.method)}</span>`, pingVal(p))).join("");
  html += `</div><div class="subhead">DNS</div><div class="checks">` + r.dns.map(x => checkRow(x.ok, esc(x.name), x.ok ? `${x.ms} ms <span class="dim">${esc(x.addresses[0] || "")}</span>` : `<span class="c-crit">${esc(x.error)}</span>`)).join("");
  html += `</div><div class="subhead">HTTPS</div><div class="checks">` + r.http.map(x => checkRow(x.ok, esc(x.url.replace(/^https?:\/\//, "")), x.ok ? `${x.status} · ${x.ms} ms` : `<span class="c-crit">${esc(x.status || x.error)}</span>`, x.error || "")).join("") + `</div>`;
  $("#ncBody").innerHTML = html;
}
async function runChecks() {
  const b = $("#ncRun"); b.disabled = true; $("#ncProg").hidden = false;
  try { renderChecks(await api("api/network/check", { method: "POST" })); } catch (e) { toast(e.message); }
  b.disabled = false; $("#ncProg").hidden = true;
}
$("#ncRun").onclick = runChecks;

/* ---------- speed tests ---------- */
async function loadSpeed() { try { renderSpeed(await api(`api/speedtest?days=${N.stRange}`)); } catch (e) { $("#stInfo").textContent = e.message; } }
function renderSpeed(s) {
  const last = s.last, run = s.running;
  $("#stRun").disabled = run; $("#stRun").textContent = run ? "Testing" : "Run test"; $("#stProg").hidden = !run;
  ["stDown", "stUp", "stPing"].forEach(id => $("#" + id).classList.remove("active"));
  const set = (id, v) => $(`#${id} b`).textContent = v;
  if (run) {
    const live = s.live?.mbps != null ? s.live.mbps.toFixed(0) : "…";
    if (s.phase === "download") { $("#stDown").classList.add("active"); set("stDown", live); }
    if (s.phase === "upload") { $("#stUp").classList.add("active"); set("stUp", live); }
    if (s.phase === "latency") $("#stPing").classList.add("active");
    $("#stInfo").textContent = `Running ${s.engine} test: ${s.phase || "starting"}`;
    if (!N.stTimer) N.stTimer = setInterval(loadSpeed, 800);
  } else {
    clearInterval(N.stTimer); N.stTimer = null;
    if (last) {
      set("stDown", last.download.toFixed(last.download < 100 ? 1 : 0)); set("stUp", last.upload.toFixed(last.upload < 100 ? 1 : 0)); set("stPing", last.ping.toFixed(1));
      $("#stInfo").innerHTML = `${last.url ? `<a href="${esc(last.url)}" target="_blank" rel="noopener">${esc(last.server)} ↗</a>` : esc(last.server)}${last.isp ? " · " + esc(last.isp) : ""} · ${esc(last.engine === "ookla" ? "Ookla" : "Cloudflare")} · ${ago(last.ts)}${last.jitter != null ? ` · jitter ${last.jitter} ms` : ""}`;
    }
    if (s.error) $("#stInfo").innerHTML = `<span class="c-crit">Last test failed: ${esc(s.error)}</span>`;
  }
  $("#stSched").innerHTML = s.interval_hours ? `Automatic every ${s.interval_hours}h · next ${until(s.next_run)}` : `Automatic tests are off`;
  const ok = s.history.filter(x => !x.error).slice().reverse();
  const now = Date.now() / 1000;
  chart("chSpeed", [{ name: "Download", color: C.cyan, data: ok.map(x => [x.ts, x.download]), dots: ok.length < 60 }, { name: "Upload", color: C.violet, data: ok.map(x => [x.ts, x.upload]), dots: ok.length < 60 }],
    { from: N.stRange === "36500" ? undefined : now - N.stRange * 86400, to: now, fmt: v => v.toFixed(0) + " Mbps", empty: "No speed tests in this period" });
  const st = s.stats, f = v => v == null ? "-" : v.toFixed(0);
  $("#stStats tbody").innerHTML = [["24 hours", st["24h"]], ["7 days", st["7d"]], ["30 days", st["30d"]], ["All time", st.all]].map(([l, r]) =>
    `<tr><td class="muted">${l}</td><td class="r mono" style="color:var(--cyan)" title="min ${f(r.down_min)} / max ${f(r.down_max)}">${f(r.down_avg)}</td><td class="r mono" style="color:var(--violet)" title="min ${f(r.up_min)} / max ${f(r.up_max)}">${f(r.up_avg)}</td><td class="r mono">${r.ping_avg != null ? r.ping_avg.toFixed(1) : "-"}</td><td class="r mono muted">${r.n}${r.failed ? ` <span class="c-crit">+${r.failed} failed</span>` : ""}</td></tr>`).join("");
  $("#stTbl tbody").innerHTML = s.history.map(x => `<tr><td class="muted">${esc(new Date(x.ts * 1000).toLocaleString([], { dateStyle: "short", timeStyle: "short" }))}</td>
    <td><span class="chip ${x.trigger === "scheduled" ? "violet" : ""}">${esc(x.trigger || "manual")}</span></td>
    ${x.error ? `<td colspan="4" class="c-crit" style="font-size:12px">${esc(x.error)}</td>` : `<td class="r mono" style="color:var(--cyan)">${x.download.toFixed(1)}</td><td class="r mono" style="color:var(--violet)">${x.upload.toFixed(1)}</td><td class="r mono">${x.ping}</td><td class="r mono muted">${x.jitter ?? "-"}</td>`}
    <td class="muted trunc" style="max-width:240px" title="${esc(x.server || "")}">${x.url ? `<a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.server || "result")} ↗</a>` : esc(x.server || "")}</td><td class="r"><button class="btn sm" data-del="${x.id}" title="Delete">✕</button></td></tr>`).join("") ||
    `<tr><td colspan="8" class="empty">No tests in this period. Hit Run test, or turn on automatic tests in Settings.</td></tr>`;
}
$("#stRun").onclick = async () => { try { renderSpeed({ ...(await api(`api/speedtest?engine=${$("#stEngine").value}`, { method: "POST" })), history: [], stats: { "24h": {}, "7d": {}, "30d": {}, all: {} } }); loadSpeed(); } catch (e) { toast(e.message); } };
$("#stTbl").addEventListener("click", async e => {
  const b = e.target.closest("[data-del]"); if (!b) return;
  if (!confirm("Delete this speed test from the log?")) return;
  try { await api(`api/speedtest/${b.dataset.del}`, { method: "DELETE" }); loadSpeed(); } catch (err) { toast(err.message); }
});
$("#stEngine").addEventListener("change", e => api("api/settings", { method: "PUT", json: { speedtest_engine: e.target.value } }).then(() => toast(`Speed tests will use ${e.target.selectedOptions[0].text}`)).catch(err => toast(err.message)));
$("#stCsv").addEventListener("click", e => { if (DEMO) { e.preventDefault(); toast("Downloads are disabled in the demo"); } });
seg("#stRange", [["7", "7d"], ["30", "30d"], ["90", "90d"], ["365", "1y"], ["36500", "All"]], N.stRange, v => { N.stRange = v; loadSpeed(); });

Tabs.network = {
  load: loadNetworkTab, period: 2000,
  enter: () => { loadNetworkTab(); loadInterfaces(); loadSpeed(); if (!N.net) runChecks(); api("api/settings").then(s => { $("#stEngine").value = s.settings.speedtest_engine; }).catch(() => {}); },
};
