/* Storage tab. */
"use strict";
async function loadStorage() {
  try {
    const d = await api("api/disks");
    $("#disks").innerHTML = d.disks.map(x => {
      const col = barColor(x.percent, 85, 95);
      return `<div class="panel disk"><div class="top-row"><span class="mount" title="${esc(x.mount)}">${esc(x.mount)}</span><span class="pct" style="color:${col}">${x.percent.toFixed(0)}%</span></div>
        <div class="meta"><span class="chip">${esc(x.fstype || "?")}</span>${x.network ? `<span class="chip violet">network</span>` : ""}<span class="chip trunc" style="max-width:200px" title="${esc(x.device)}">${esc(x.device)}</span></div>
        <div class="bar"><i style="width:${x.percent}%;background:${col}"></i></div>
        <div class="nums"><div><span>Used</span><b>${fmtBytes(x.used)}</b></div><div><span>Free</span><b style="color:${col}">${fmtBytes(x.free)}</b></div><div><span>Total</span><b>${fmtBytes(x.total)}</b></div></div></div>`;
    }).join("") || `<div class="panel empty">No disks found</div>`;
    const io = Object.entries(d.io || {}).sort();
    $("#ioTbl tbody").innerHTML = io.map(([n, v]) => `<tr><td class="mono">${esc(n)}</td><td class="r mono">${fmtBytes(v.read)}/s</td><td class="r mono">${fmtBytes(v.write)}/s</td><td class="r"><div class="cellbar"><span class="mono">${v.busy.toFixed(0)}%</span><div class="bar"><i style="width:${v.busy}%;background:${barColor(v.busy, 70, 90)}"></i></div></div></td></tr>`).join("") || `<tr><td colspan="4" class="empty">No physical disk stats available</td></tr>`;
  } catch (e) { $("#disks").innerHTML = `<div class="panel empty">${esc(e.message)}</div>`; }
}
Tabs.storage = { load: loadStorage, period: 10000 };
