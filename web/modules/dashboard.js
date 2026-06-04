/* === Dashboard Module === */
function initDashboardSearch() {
  const searchInput = $("dashboard-search");
  const filterSelect = $("dashboard-filter");
  if (!searchInput || !filterSelect) return;
  const applyFilter = () => {
    const keyword = searchInput.value.trim().toLowerCase();
    const status = filterSelect.value;
    const filtered = AppState.allProjects.filter(p => {
      const matchKeyword = !keyword || (p.title || p.outline || "").toLowerCase().includes(keyword);
      const matchStatus = status === 'all' || (status === 'approved' ? p.approved : !p.approved);
      return matchKeyword && matchStatus;
    });
    renderProjectGrid(filtered);
  };
  searchInput.addEventListener('input', applyFilter);
  filterSelect.addEventListener('change', applyFilter);
}

function renderProjectGrid(projects) {
  const grid = $("project-grid");
  if (!projects.length) {
    const el = EmptyState.projects();
    grid.innerHTML = '';
    grid.appendChild(el);
    return;
  }
  grid.innerHTML = projects.map(p => {
    const progress = p.total_chapters ? Math.round(((p.generated || 0) / p.total_chapters) * 100) : 0;
    return `
    <div class="project-card" data-id="${p.task_id}">
      <div class="project-card-title">${escapeHtml(p.title || p.outline || "未命名项目")}</div>
      <div class="project-card-desc">${escapeHtml(p.outline || "")}</div>
      <div class="project-card-meta">
        <span>${p.generated || 0} / ${p.total_chapters || 0} 章</span>
        <span>${p.approved ? "已确认" : "待确认"}</span>
      </div>
      <div class="project-card-progress">
        <div class="project-card-progress-bar" style="width:${progress}%;"></div>
      </div>
      <div class="project-card-actions">
        <button class="btn-sm card-open">打开</button>
        <button class="btn-sm btn-outline card-delete" style="color:var(--danger);">删除</button>
      </div>
    </div>`;
  }).join("");

  grid.querySelectorAll(".project-card").forEach(card => {
    const id = card.dataset.id;
    qs(".card-open", card).onclick = () => { AppState.currentTaskId = id; resetWorkspaceState(); navigate("#workspace"); loadWorkspaceProject(); };
    qs(".card-delete", card).onclick = async (e) => {
      e.stopPropagation();
      const confirmed = await DialogSystem.confirm({
        title: '删除项目',
        message: `确定要删除该项目吗？此操作不可恢复。`,
        confirmText: '删除',
        type: 'danger',
        dangerous: true
      });
      if (!confirmed) return;
      try {
        await api(`/api/db/project/${id}`, { method: "DELETE" });
        toast("项目已删除", "success");
        AppState.allProjects = AppState.allProjects.filter(p => p.task_id !== id);
        if (AppState.currentTaskId === id) {
          AppState.currentTaskId = null;
          navigate("#dashboard");
        }
        renderProjectGrid(AppState.allProjects);
      } catch (e) { toast("删除失败: " + e.message, "error"); }
    };
  });
}

async function loadDashboard() {
  $("dashboard-new-project").onclick = () => {
    if (!AppState.currentUser) {
      showLoginDialog();
      return;
    }
    AppState.currentTaskId = null;
    resetWorkspaceState();
    showInitForm();
  };
  try {
    const data = await api("/api/projects");
    AppState.allProjects = data.projects || [];
    const stats = AppState.allProjects.reduce((acc, p) => {
      acc.projects++; acc.chapters += p.total_chapters || 0; acc.generated += p.generated || 0;
      return acc;
    }, { projects: 0, chapters: 0, generated: 0 });
    $("stat-projects").textContent = stats.projects;
    $("stat-chapters").textContent = stats.chapters;
    $("stat-finalized").textContent = stats.generated;
    $("stat-words").textContent = "N/A";
    renderProjectGrid(AppState.allProjects);
  } catch (e) {
    const msg = e.message || "加载失败";
    if (msg.includes("未登录") || msg.includes("过期")) {
      $("project-grid").innerHTML = `<div class="empty-state"><div class="empty-state-icon">🔒</div><div class="empty-state-title">请先登录</div><div class="empty-state-desc">登录后查看你的创作项目</div><button class="btn-primary btn-sm" style="margin-top:8px;" onclick="showLoginDialog()">立即登录</button></div>`;
    } else {
      $("project-grid").innerHTML = `<div class="empty-state">加载失败: ${msg}</div>`;
    }
  }
}
