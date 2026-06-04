/* === Navigation === */
function navigate(hash) {
  const overlay = document.getElementById('dialog-overlay');
  if (overlay && overlay.style.display !== 'none') return;
  const page = hash.replace("#", "").split("/")[0] || "dashboard";
  qsa(".nav-item").forEach(n => n.classList.toggle("active", n.dataset.page === page));
  qsa(".page").forEach(p => p.classList.remove("active"));
  const pg = $(`page-${page}`);
  if (pg) pg.classList.add("active");
  qsa(".bottom-tab-item").forEach(t => t.classList.toggle("active", t.dataset.page === page));
  if (page === "dashboard") loadDashboard();
  if (page === "workspace") loadWorkspaceProject();
  if (page === "settings") loadSettings();
  if (page === "admin") loadAdmin();
}
