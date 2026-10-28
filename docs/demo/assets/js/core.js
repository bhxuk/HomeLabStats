/* HomeLabStats core: helpers, API, charts, dialogs and tab routing. Loaded first. */
"use strict";
const DEMO = window.HLS_DEMO === true || new URLSearchParams(location.search).has("demo");
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const state = { tab: "overview", overview: null, lastOk: 0 };
const Tabs = {};          // each tab file registers { load, period, enter, leave }
const C = { cyan: "#22d3ee", violet: "#a78bfa", green: "#34d399", amber: "#fbbf24", red: "#f87171", blue: "#60a5fa", pink: "#f472b6", orange: "#fb923c", lime: "#a3e635", teal: "#2dd4bf" };
const PALETTE = [C.cyan, C.violet, C.green, C.amber, C.pink, C.blue, C.orange, C.lime, C.teal, C.red];

/* ---------- formatting ---------- */
function fmtBytes(n, d = 1) {
  if (n == null || isNaN(n)) return "-";
  const u = ["B", "KB", "MB", "GB", "TB", "PB"]; let i = 0;
  while (Math.abs(n) >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return (i === 0 ? n.toFixed(0) : n.toFixed(n >= 100 ? 0 : d)) + " " + u[i];
}
function fmtBits(bytesPerSec) {
  let b = (bytesPerSec || 0) * 8; const u = ["bps", "Kbps", "Mbps", "Gbps"]; let i = 0;
  while (b >= 1000 && i < u.length - 1) { b /= 1000; i++; }
  return (i === 0 ? b.toFixed(0) : b.toFixed(b >= 100 ? 0 : 1)) + " " + u[i];
}
function fmtDur(sec) {
  if (sec == null || sec < 0) return "-";
  sec = Math.floor(sec);
  const d = Math.floor(sec / 86400), h = Math.floor(sec % 86400 / 3600), m = Math.floor(sec % 3600 / 60);
  if (d) return `${d}d ${h}h`; if (h) return `${h}h ${m}m`; if (m) return `${m}m`; return `${sec}s`;
}
function ago(ts) { return ts ? fmtDur(Date.now() / 1000 - ts) + " ago" : "never"; }
function until(ts) { return ts ? "in " + fmtDur(ts - Date.now() / 1000) : "-"; }
function fmtTime(ts, withDate = false) {
  const d = new Date(ts * 1000);
  return withDate ? d.toLocaleString([], { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
function pct(v, d = 0) { return v == null ? "-" : v.toFixed(d) + "%"; }
function lvl(p, w = 75, c = 90) { return p >= c ? "crit" : p >= w ? "warn" : "ok"; }
function barColor(p, w = 75, c = 90) { return p >= c ? "var(--red)" : p >= w ? "var(--amber)" : "var(--cyan)"; }
function setBar(el, p, w, c) { el.style.width = Math.min(100, Math.max(0, p)) + "%"; el.style.background = barColor(p, w, c); }
function toast(msg) { const t = $("#toast"); t.textContent = msg; t.classList.add("show"); clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove("show"), 3200); }
function uptimeColor(u) { return u == null ? "var(--dim)" : u >= 99.5 ? "var(--green)" : u >= 95 ? "var(--amber)" : "var(--red)"; }

/* ---------- api ---------- */
async function api(path, opts = {}) {
  if (DEMO) return window.HLSDemo.api(path, opts);
  const init = { ...opts, headers: { Accept: "application/json", ...(opts.headers || {}) } };
  if (opts.json !== undefined) { init.body = JSON.stringify(opts.json); init.headers["Content-Type"] = "application/json"; delete init.json; }
  const r = await fetch(path, init);
  if (!r.ok) { let m = r.statusText; try { m = (await r.json()).detail || m; } catch {} throw new Error(m); }
  const ct = r.headers.get("content-type") || "";
  return ct.includes("json") ? r.json() : r.text();
}

/* ---------- charts ----------
   series: [{ name, color, data: [[t, v], ...], fill, dots }]
   opts:   { max, min, fmt, from, to, gap (seconds that break a line), height } */
function chart(id, series, opts = {}) {
  const wrap = typeof id === "string" ? document.getElementById(id) : id;
  if (!wrap) return;
  const cv = wrap.querySelector("canvas"), tip = wrap.querySelector(".tip");
  const dpr = window.devicePixelRatio || 1, W = wrap.clientWidth, H = wrap.clientHeight;
  if (!W || !H) return;
  if (cv.width !== Math.round(W * dpr) || cv.height !== Math.round(H * dpr)) { cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); }
  const ctx = cv.getContext("2d"); ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, W, H);
  const fmt = opts.fmt || (v => v.toFixed(0));
  const all = series.flatMap(s => s.data.filter(p => p[1] != null));
  let t0 = opts.from ?? Math.min(...all.map(p => p[0])), t1 = opts.to ?? Math.max(...all.map(p => p[0]));
  if (!all.length || !isFinite(t0)) {
    ctx.fillStyle = "#56697c"; ctx.font = "12px " + getComputedStyle(document.body).fontFamily; ctx.textAlign = "center";
    ctx.fillText(opts.empty || "No data yet", W / 2, H / 2); wrap._chart = null; return;
  }
  if (t1 <= t0) t1 = t0 + 1;
  const vmin = opts.min ?? 0;
  let top = opts.max ?? Math.max(...all.map(p => p[1])) * 1.15;
  if (opts.max == null && (!(top > vmin) || top - vmin < 1e-6)) top = vmin + 1;
  ctx.font = "11px " + getComputedStyle(document.body).getPropertyValue("--mono");
  const labels = [0, 1, 2, 3, 4].map(i => fmt(top - (top - vmin) * i / 4));
  const padL = Math.ceil(Math.max(...labels.map(l => ctx.measureText(l).width))) + 14, padR = 10, padT = 8, padB = 22;
  const w = W - padL - padR, h = H - padT - padB;
  const x = t => padL + (t - t0) / (t1 - t0) * w, y = v => padT + h - (Math.min(Math.max(v, vmin), top) - vmin) / (top - vmin) * h;
  ctx.strokeStyle = "rgba(125,145,165,.12)"; ctx.fillStyle = "#56697c"; ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const yy = Math.round(padT + h * i / 4) + .5; ctx.beginPath(); ctx.moveTo(padL, yy); ctx.lineTo(W - padR, yy); ctx.stroke();
    ctx.textAlign = "right"; ctx.fillText(labels[i], padL - 8, yy + 4);
  }
  const span = t1 - t0, ticks = Math.max(2, Math.min(7, Math.floor(w / 110)));
  ctx.textAlign = "center";
  for (let i = 0; i <= ticks; i++) {
    const t = t0 + span * i / ticks, xx = x(t);
    const lab = span > 2 * 86400 ? new Date(t * 1000).toLocaleDateString([], { day: "numeric", month: "short" }) : fmtTime(t);
    ctx.fillText(lab, Math.min(Math.max(xx, padL + 20), W - padR - 20), H - 6);
  }
  const gap = opts.gap ?? Infinity;
  for (const s of series) {
    const pts = s.data.filter(p => p[1] != null).map(p => [x(p[0]), y(p[1]), p[0]]);
    if (!pts.length) continue;
    const segs = []; let cur = [];
    pts.forEach((p, i) => { if (i && p[2] - pts[i - 1][2] > gap) { segs.push(cur); cur = []; } cur.push(p); });
    segs.push(cur);
    for (const seg of segs) {
      if (seg.length === 1) { ctx.beginPath(); ctx.arc(seg[0][0], seg[0][1], 2, 0, 7); ctx.fillStyle = s.color; ctx.fill(); continue; }
      ctx.beginPath(); seg.forEach(([px, py], i) => i ? ctx.lineTo(px, py) : ctx.moveTo(px, py));
      if (s.fill !== false) {
        const g = ctx.createLinearGradient(0, padT, 0, padT + h); g.addColorStop(0, s.color + "38"); g.addColorStop(1, s.color + "00");
        ctx.save(); ctx.lineTo(seg.at(-1)[0], padT + h); ctx.lineTo(seg[0][0], padT + h); ctx.closePath(); ctx.fillStyle = g; ctx.fill(); ctx.restore();
        ctx.beginPath(); seg.forEach(([px, py], i) => i ? ctx.lineTo(px, py) : ctx.moveTo(px, py));
      }
      ctx.strokeStyle = s.color; ctx.lineWidth = 1.7; ctx.lineJoin = "round"; ctx.stroke();
      if (s.dots) for (const [px, py] of seg) { ctx.beginPath(); ctx.arc(px, py, 2.6, 0, 7); ctx.fillStyle = s.color; ctx.fill(); }
    }
  }
  wrap._chart = { series, t0, t1, padL, w, fmt, x, H, padT, h };
  if (!wrap._hover && tip) {
    wrap._hover = true;
    wrap.addEventListener("mousemove", e => {
      const c = wrap._chart; if (!c) return;
      const rect = wrap.getBoundingClientRect(), mx = e.clientX - rect.left;
      if (mx < c.padL || mx > c.padL + c.w) { tip.style.display = "none"; return; }
      const t = c.t0 + (mx - c.padL) / c.w * (c.t1 - c.t0);
      const rows = c.series.map(s => {
        let best = null, bd = Infinity;
        for (const p of s.data) { const d = Math.abs(p[0] - t); if (d < bd && p[1] != null) { bd = d; best = p; } }
        return best ? [s, best] : null;
      }).filter(Boolean);
      if (!rows.length) { tip.style.display = "none"; return; }
      const tt = rows[0][1][0], long = c.t1 - c.t0 > 86400;
      tip.innerHTML = `<div class="dim">${esc(long ? fmtTime(tt, true) : new Date(tt * 1000).toLocaleTimeString())}</div>` +
        rows.slice(0, 10).map(([s, p]) => `<div><span style="color:${s.color}">●</span> ${esc(s.name)} ${esc(c.fmt(p[1]))}</div>`).join("");
      tip.style.display = "block";
      tip.style.left = Math.min(mx + 12, rect.width - tip.offsetWidth - 4) + "px"; tip.style.top = "6px";
    });
    wrap.addEventListener("mouseleave", () => { tip.style.display = "none"; });
  }
}
function legend(id, items) {
  const el = typeof id === "string" ? document.getElementById(id) : id;
  if (el) el.innerHTML = items.map(([n, c, v]) => `<span><i style="background:${c}"></i>${esc(n)}${v != null ? ` <b>${esc(v)}</b>` : ""}</span>`).join("");
}
function seg(el, options, value, onChange) {
  el = typeof el === "string" ? $(el) : el;
  el.innerHTML = options.map(([v, l]) => `<button data-v="${esc(v)}" class="${v === value ? "on" : ""}">${esc(l)}</button>`).join("");
  el.onclick = e => { const b = e.target.closest("button"); if (!b) return; $$("button", el).forEach(x => x.classList.toggle("on", x === b)); onChange(b.dataset.v); };
}

/* ---------- dialogs & drawer ---------- */
function dialog(title, bodyHtml, buttons = [{ label: "Close" }]) {
  return new Promise(resolve => {
    const d = $("#dlg");
    $("#dlgTitle").textContent = title; $("#dlgBody").innerHTML = bodyHtml;
    $("#dlgFoot").innerHTML = buttons.map((b, i) => `<button class="btn ${b.cls || ""}" data-i="${i}">${esc(b.label)}</button>`).join("");
    const close = v => { d.classList.remove("open"); d.onclick = null; resolve(v); };
    d.onclick = async e => {
      if (e.target === d || e.target.closest("[data-close]")) return close(null);
      const btn = e.target.closest("#dlgFoot button"); if (!btn) return;
      const b = buttons[+btn.dataset.i];
      if (b.action) {
        btn.disabled = true;
        try { const r = await b.action($("#dlgBody")); if (r !== false) close(r ?? true); }
        catch (err) { toast(err.message); }
        btn.disabled = false;
      } else close(b.value ?? null);
    };
    d.classList.add("open");
    setTimeout(() => { const f = $("#dlgBody input, #dlgBody select"); if (f) f.focus(); }, 50);
  });
}
async function confirmDanger(title, html, label = "Confirm") {
  return dialog(title, `<p style="margin:0;color:var(--muted)">${html}</p>`, [{ label: "Cancel", value: false }, { label, cls: "primary", value: true }]);
}
function openDrawer(title, stateHtml, bodyHtml) {
  $("#drTitle").textContent = title; $("#drState").innerHTML = stateHtml || ""; $("#drBody").innerHTML = bodyHtml;
  $("#drawer").classList.add("open"); $("#scrim").classList.add("open");
}
function closeDrawer() { $("#drawer").classList.remove("open"); $("#scrim").classList.remove("open"); state.drawer = null; }
$("#drClose").onclick = closeDrawer; $("#scrim").onclick = closeDrawer;
document.addEventListener("keydown", e => { if (e.key === "Escape") { closeMenu(); closeDrawer(); $("#dlg").classList.remove("open"); } });

/* ---------- tabs ---------- */
let tabTimer = null;
function showTab(t, opts = {}) {
  if (!Tabs[t]) t = "overview";
  if (state.tab !== t && Tabs[state.tab]?.leave) Tabs[state.tab].leave();
  state.tab = t; history.replaceState(null, "", "#" + t);
  $$(".tab").forEach(b => b.classList.toggle("active", b.dataset.tab === t));
  $$("section.view").forEach(s => s.classList.toggle("active", s.id === "v-" + t));
  clearInterval(tabTimer);
  const tab = Tabs[t];
  if (tab.enter) tab.enter(opts); else if (tab.load) tab.load();
  if (tab.period && tab.load) tabTimer = setInterval(() => !document.hidden && tab.load(), tab.period);
  if (opts.anchor) setTimeout(() => document.getElementById(opts.anchor)?.scrollIntoView({ behavior: "smooth" }), 100);
}
$("#tabs").addEventListener("click", e => { const b = e.target.closest(".tab"); if (b) showTab(b.dataset.tab); });
document.addEventListener("click", e => {
  const a = e.target.closest("[data-goto]");
  if (a) { e.preventDefault(); showTab(a.dataset.goto, { anchor: a.dataset.anchor }); }
});
const canManage = () => !!state.overview?.host?.container_actions;
const levelDot = l => `<span class="d lv-${esc(l || "info")}"></span>`;
function feedHtml(events, empty = "Nothing yet") {
  return events.map(e => `<div class="ev">${levelDot(e.level)}<div class="tt"><b>${esc(e.title)}</b>${e.detail ? `<span title="${esc(e.detail)}">${esc(e.detail)}</span>` : ""}</div><time title="${esc(new Date(e.ts * 1000).toLocaleString())}">${esc(ago(e.ts))}</time></div>`).join("") || `<div class="muted" style="font-size:13px">${empty}</div>`;
}

/* ---------- popup menu ---------- */
function popMenu(anchor, items) {
  closeMenu();
  const m = document.createElement("div"); m.className = "popmenu"; m.id = "popmenu";
  m.innerHTML = items.map((it, i) => it.sep ? `<hr>` : `<button data-i="${i}" class="${it.danger ? "danger" : ""}" ${it.disabled ? "disabled" : ""}>${esc(it.label)}</button>`).join("");
  document.body.appendChild(m);
  const r = anchor.getBoundingClientRect();
  const left = Math.min(r.right - m.offsetWidth, window.innerWidth - m.offsetWidth - 8);
  const top = r.bottom + 6 + m.offsetHeight > window.innerHeight ? r.top - m.offsetHeight - 6 : r.bottom + 6;
  m.style.left = Math.max(8, left) + "px"; m.style.top = Math.max(8, top) + "px";
  m.onclick = e => { const b = e.target.closest("button[data-i]"); if (!b || b.disabled) return; closeMenu(); items[+b.dataset.i].onClick?.(); };
  setTimeout(() => document.addEventListener("click", closeMenu, { once: true }), 0);
}
function closeMenu() { document.getElementById("popmenu")?.remove(); }
window.addEventListener("scroll", closeMenu, true);
