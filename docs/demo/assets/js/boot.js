/* Starts the app: demo data if needed, the 2 second overview loop, then the tab from the URL. */
"use strict";
window.addEventListener("resize", () => {
  clearTimeout(window._rz);
  window._rz = setTimeout(() => { const t = Tabs[state.tab]; if (state.tab === "overview" && state.overview) renderOverview(state.overview); else if (t?.load && state.tab !== "network") t.load(); }, 200);
});
(async function boot() {
  if (DEMO) {
    $("#demoBanner").hidden = false;
    if (!window.HLSDemo) await new Promise((res, rej) => { const s = document.createElement("script"); s.src = "assets/demo.js"; s.onload = res; s.onerror = rej; document.head.appendChild(s); });
  }
  await loadOverview();
  setInterval(() => !document.hidden && loadOverview(), 2000);
  const t = location.hash.slice(1);
  showTab(Tabs[t] ? t : "overview");
})();
