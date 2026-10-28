/* Settings tab: management switch, speed test schedule, alert channels, data retention, activity log. */
"use strict";
const S = { data: null };
const CH_TYPES = {
  discord: { label: "Discord", fields: [["url", "Webhook URL", "https://discord.com/api/webhooks/…"]] },
  telegram: { label: "Telegram", fields: [["token", "Bot token", "123456:ABC…"], ["chat_id", "Chat ID", "123456789"]] },
  ntfy: { label: "ntfy", fields: [["url", "Topic URL", "https://ntfy.sh/my-homelab"], ["token", "Access token (optional)", ""]] },
  slack: { label: "Slack", fields: [["url", "Webhook URL", "https://hooks.slack.com/services/…"]] },
  webhook: { label: "Webhook (JSON POST)", fields: [["url", "URL", "https://example.com/hook"]] },
};
const NOTIFY_LABELS = {
  monitor_down: "A monitor goes down", monitor_up: "A monitor recovers", container_stopped: "A container crashes or keeps restarting",
  container_unhealthy: "A container's health check fails", system_alerts: "Critical system alerts (disk nearly full, very hot CPU, memory exhausted)",
  speedtest_slow: "A speed test is slow or fails", update_available: "A new HomeLabStats version is out",
};

async function loadSettings() {
  try {
    const d = await api("api/settings"); S.data = d;
    const s = d.settings;
    $$("[data-set]").forEach(el => {
      const v = s[el.dataset.set];
      if (el.type === "checkbox") el.checked = !!v; else el.value = String(v ?? "");
    });
    $("#dbInfo").textContent = `${fmtBytes(d.db.size)} · ${(d.db.sys_raw + d.db.sys_5m).toLocaleString()} metric rows, ${d.db.beats.toLocaleString()} heartbeats, ${d.db.speedtests} speed tests${d.db.oldest ? ` · history since ${new Date(d.db.oldest * 1000).toLocaleDateString()}` : ""}`;
    renderChannels(); renderNotifyOn();
  } catch (e) { toast(e.message); }
  loadActivity();
}
async function saveSettings(patch, quiet = false) {
  try {
    const r = await api("api/settings", { method: "PUT", json: patch });
    S.data.settings = r.settings;
    if (state.overview) state.overview.host.container_actions = r.settings.container_actions;
    if (!quiet) toast("Saved");
    renderChannels(); renderNotifyOn();
  } catch (e) { toast(e.message); loadSettings(); }
}
$$("[data-set]").forEach(el => el.addEventListener("change", () => {
  const k = el.dataset.set;
  let v = el.type === "checkbox" ? el.checked : el.value;
  if (["speedtest_interval_hours", "speedtest_alert_below_mbps", "retention_days"].includes(k)) v = +v;
  saveSettings({ [k]: v });
}));

function renderChannels() {
  const chs = S.data.settings.notify_channels;
  $("#chList").innerHTML = chs.map(c => `<div class="check" style="margin-bottom:6px"><span class="st ${c.enabled ? "ok" : "bad"}">${c.enabled ? "✓" : "–"}</span>
      <span class="name"><b>${esc(c.name)}</b> <span class="dim">${esc(CH_TYPES[c.type]?.label || c.type)}</span></span>
      <span class="val actions"><button class="btn sm" data-ch-test="${c.id}">Test</button><button class="btn sm" data-ch-edit="${c.id}">Edit</button></span></div>`).join("") ||
    `<div class="notice">No alert channels yet. Add Discord, Telegram, ntfy, Slack or a webhook to get notified when something goes down.</div>`;
}
function renderNotifyOn() {
  const on = S.data.settings.notify_on;
  $("#notifyOn").innerHTML = Object.entries(NOTIFY_LABELS).map(([k, l]) => `<div class="setrow" style="padding:8px 0"><div class="txt"><span style="font-size:13px;color:var(--text)">${esc(l)}</span></div><label class="switch"><input type="checkbox" data-notify="${k}" ${on[k] ? "checked" : ""}><span class="t"></span></label></div>`).join("");
}
$("#notifyOn").addEventListener("change", e => { const k = e.target.dataset.notify; if (k) saveSettings({ notify_on: { [k]: e.target.checked } }); });

async function editChannel(id = null) {
  const chs = S.data.settings.notify_channels;
  const c = id ? chs.find(x => x.id === id) : { type: "discord", name: "", enabled: true };
  const fields = t => CH_TYPES[t].fields.map(([k, l, ph]) => `<div class="field"><label>${l}</label><input class="input" name="${k}" value="${esc(c.type === t ? c[k] || "" : "")}" placeholder="${esc(ph)}"></div>`).join("");
  const body = `<div class="grid-f"><div class="field"><label>Type</label><select class="select" name="type">${Object.entries(CH_TYPES).map(([k, v]) => `<option value="${k}" ${c.type === k ? "selected" : ""}>${v.label}</option>`).join("")}</select></div>
    <div class="field"><label>Name</label><input class="input" name="name" value="${esc(c.name)}" placeholder="My phone"></div></div>
    <div id="chFields">${fields(c.type)}</div>
    <label class="switch"><input type="checkbox" name="enabled" ${c.enabled ? "checked" : ""}><span class="t"></span>Enabled</label>
    <div id="chTestOut" class="mt"></div>`;
  const read = b => {
    const t = b.querySelector('[name="type"]').value, o = { id: c.id, type: t, name: b.querySelector('[name="name"]').value || CH_TYPES[t].label, enabled: b.querySelector('[name="enabled"]').checked };
    CH_TYPES[t].fields.forEach(([k]) => o[k] = b.querySelector(`[name="${k}"]`).value.trim()); return o;
  };
  const buttons = [{ label: "Cancel", value: null }];
  if (id) buttons.push({ label: "Delete", action: async () => { await saveSettings({ notify_channels: chs.filter(x => x.id !== id) }, true); toast("Channel deleted"); return true; } });
  buttons.push({ label: "Send test", action: async b => { const r = await api("api/settings/test-channel", { method: "POST", json: { channel: read(b) } }); $("#chTestOut", b).innerHTML = `<div class="notice ${r.ok ? "good" : "bad"}">${r.ok ? "Test alert sent. Check your app." : esc(r.error)}</div>`; return false; } });
  buttons.push({ label: "Save", cls: "primary", action: async b => {
    const ch = read(b); const list = id ? chs.map(x => x.id === id ? ch : x) : [...chs, ch];
    await saveSettings({ notify_channels: list }, true); toast("Channel saved"); return true;
  } });
  const p = dialog(id ? `Edit ${c.name}` : "Add alert channel", body, buttons);
  const tsel = $('#dlgBody [name="type"]'); tsel.onchange = () => { $("#chFields").innerHTML = fields(tsel.value); };
  await p;
}
$("#chAdd").onclick = () => editChannel();
$("#chList").addEventListener("click", async e => {
  const ed = e.target.closest("[data-ch-edit]"); if (ed) return editChannel(ed.dataset.chEdit);
  const t = e.target.closest("[data-ch-test]"); if (!t) return;
  const ch = S.data.settings.notify_channels.find(x => x.id === t.dataset.chTest);
  t.disabled = true;
  const r = await api("api/settings/test-channel", { method: "POST", json: { channel: ch } }).catch(err => ({ ok: false, error: err.message }));
  toast(r.ok ? `Test sent to ${ch.name}` : `Failed: ${r.error}`); t.disabled = false;
});
$("#dbCompact").onclick = async e => {
  e.target.disabled = true;
  try { const r = await api("api/settings/compact", { method: "POST" }); toast(`Database compacted to ${fmtBytes(r.size)}`); loadSettings(); } catch (err) { toast(err.message); }
  e.target.disabled = false;
};
async function loadActivity() {
  try { $("#feedFull").innerHTML = feedHtml(await api(`api/events?limit=200${$("#evKind").value ? "&kind=" + $("#evKind").value : ""}`)); }
  catch (e) { $("#feedFull").innerHTML = `<div class="muted">${esc(e.message)}</div>`; }
}
$("#evKind").onchange = loadActivity;
Tabs.settings = { enter: loadSettings, load: loadActivity, period: 15000 };
