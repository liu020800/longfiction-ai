/* === App Init & Event Bindings === */

window.addEventListener("hashchange", () => navigate(location.hash || "#dashboard"));

window.addEventListener("load", () => {
  ThemeManager.init();
  Sidebar.init();
  Keyboard.init();
  updateAuthUI();
  initReaderControls();
  initDashboardSearch();
  navigate(location.hash || "#dashboard");
});

$("sidebar-user").onclick = () => navigate("#settings");
$("sidebar-login-btn").onclick = (e) => { e.preventDefault(); showLoginDialog(); };

document.addEventListener("click", (e) => {
  const tab = e.target.closest(".ws-tab");
  if (!tab) return;
  qsa(".ws-tab").forEach(t => t.classList.remove("active"));
  tab.classList.add("active");
  qsa(".ws-textarea").forEach(t => t.classList.remove("active-editor"));
  const target = $(`${tab.dataset.tab}-editor`);
  if (target) target.classList.add("active-editor");
});

$("ws-back").onclick = () => navigate("#dashboard");
$("ws-delete-project").onclick = async () => {
  if (!AppState.currentTaskId) return;
  const confirmed = await DialogSystem.confirm({
    title: '删除项目',
    message: `确定要删除项目「${AppState.currentOutline.slice(0, 30)}」吗？此操作不可恢复。`,
    confirmText: '删除',
    type: 'danger',
    dangerous: true
  });
  if (!confirmed) return;
  try {
    const tid = AppState.currentTaskId;
    await api(`/api/db/project/${tid}`, { method: "DELETE" });
    toast("项目已删除", "success");
    AppState.allProjects = AppState.allProjects.filter(p => p.task_id !== tid);
    AppState.currentTaskId = null;
    navigate("#dashboard");
  } catch (e) { toast("删除失败: " + e.message, "error"); }
};

$("approve-btn").onclick = async () => {
  if (!AppState.currentTaskId) return;
  await ButtonHelper.withLoading($("approve-btn"), async () => {
    const d = await api("/api/project", {
      method: "POST",
      body: JSON.stringify({
        task_id: AppState.currentTaskId,
        outline: AppState.currentOutline,
        genre: AppState.currentGenre,
        style: AppState.currentStyle,
        target_chapters: AppState.currentTargetChapters,
        words_per_chapter: AppState.currentWordsPerChapter,
        world: textToWorld($("world-editor").value),
        characters: textToCharacters($("characters-editor").value),
        chapters: textToChapters($("chapters-editor").value),
      }),
    });
    AppState.approved = true; AppState.projectDirty = false;
    setApprovalState(true);
    $("approve-status").textContent = "保存成功，可以生成章节";
    renderCatalog(d.catalog);
    toast("设定已确认", "success");
    await loadTimelineAndForeshadow();
  }).catch(e => { $("approve-status").textContent = `保存失败: ${e.message}`; toast(e.message, "error"); });
};

$("save-meta-btn").onclick = async () => {
  if (!AppState.currentTaskId) return;
  await ButtonHelper.withLoading($("save-meta-btn"), async () => {
    const d = await api("/api/project/meta", {
      method: "PUT",
      body: JSON.stringify({
        task_id: AppState.currentTaskId,
        title: $("meta-title").value.trim(),
        outline: $("meta-outline").value.trim(),
        genre: $("meta-genre").value,
        style: $("meta-style").value,
        target_chapters: Number($("meta-target-chapters").value),
        words_per_chapter: Number($("meta-words-per-chapter").value),
      }),
    });
    AppState.currentTitle = d.project.title || AppState.currentTitle;
    AppState.currentOutline = d.project.outline;
    AppState.currentGenre = d.project.genre;
    AppState.currentStyle = d.project.style;
    AppState.currentTargetChapters = d.project.target_chapters;
    AppState.currentPlannedChapters = d.project.planned_chapters || AppState.currentPlannedChapters;
    AppState.currentWordsPerChapter = d.project.words_per_chapter;
    AppState.projectDirty = true;
    if (!$("chapter-target-words").value || Number($("chapter-target-words").value) <= 0) {
      $("chapter-target-words").value = AppState.currentWordsPerChapter;
    }
    setApprovalState(false);
    $("approve-status").textContent = "项目参数已保存，请确认设定后继续生成。";
    $("ws-project-title").textContent = AppState.currentTitle;
    toast("项目参数已更新", "success");
  }).catch(e => { toast(e.message, "error"); });
};

$("import-txt-btn").onclick = async () => {
  if (!AppState.currentTaskId) return;
  const text = $("import-txt-text").value.trim();
  if (!text) { toast("请先粘贴小说内容", "error"); return; }
  await ButtonHelper.withLoading($("import-txt-btn"), async () => {
    const d = await api("/api/project/import-txt", {
      method: "POST",
      body: JSON.stringify({ task_id: AppState.currentTaskId, text }),
    });
    $("chapters-editor").value = chaptersToText(d.chapters || []);
    renderCatalog(d.catalog);
    AppState.projectDirty = true;
    setApprovalState(false);
    $("approve-status").textContent = "已导入章节内容，请确认设定后继续续写。";
    toast("已有小说已导入", "success");
  }).catch(e => { toast(e.message, "error"); });
};

$("regen-world").onclick = () => regenerateSection("world");
$("regen-characters").onclick = () => regenerateSection("characters");
$("regen-chapters").onclick = () => regenerateSection("chapters");
const taskMonitorRefresh = $("task-monitor-refresh");
if (taskMonitorRefresh) taskMonitorRefresh.onclick = refreshTaskMonitor;

$("catalog").addEventListener("click", async (e) => {
  const btn = e.target.closest("button");
  if (!btn) return;
  const idx = Number(btn.dataset.idx), action = btn.dataset.action;
  if (!AppState.currentTaskId) return;
  if (action === "view") {
    try {
      const d = await api(`/api/chapter/${AppState.currentTaskId}/${idx}`);
      showChapter(d.chapter);
    } catch (e) { toast(e.message, "error"); }
    return;
  }
  await ButtonHelper.withLoading(btn, async () => {
    const path = action === "regenerate" ? "/api/chapter/regenerate" : "/api/chapter";
    const d = await api(path, {
      method: "POST",
      body: JSON.stringify({
        task_id: AppState.currentTaskId,
        chapter_index: idx,
        multi_version: false,
        guidance: $("chapter-guidance").value.trim(),
        target_words: Number($("chapter-target-words").value || 2000),
        auto_finalize: $("auto-finalize") ? $("auto-finalize").checked : true,
      }),
    });
    showChapter(d.chapter);
    renderCatalog(d.catalog);
    await refreshCreativePanels();
    await refreshTaskMonitor();
    toast(action === "regenerate" ? "章节已重生成" : "章节已生成", "success");
  }).catch(e => { toast(e.message, "error"); });
});

$("finalize-btn").onclick = async () => {
  if (!AppState.currentTaskId || !AppState.currentChapter) return;
  await ButtonHelper.withLoading($("finalize-btn"), async () => {
    const d = await api("/api/chapter/finalize", { method: "POST", body: JSON.stringify({ task_id: AppState.currentTaskId, chapter_index: AppState.currentChapter.chapter_index }) });
    renderCatalog(d.catalog); await refreshCreativePanels(); await refreshTaskMonitor(); toast("章节已定稿，可在「故事演进」中审阅同步", "success");
  }).catch(e => { toast(e.message, "error"); });
};
$("unfinalize-btn").onclick = async () => {
  if (!AppState.currentTaskId || !AppState.currentChapter) return;
  await ButtonHelper.withLoading($("unfinalize-btn"), async () => {
    const d = await api("/api/chapter/unfinalize", { method: "POST", body: JSON.stringify({ task_id: AppState.currentTaskId, chapter_index: AppState.currentChapter.chapter_index }) });
    renderCatalog(d.catalog); await refreshCreativePanels(); await refreshTaskMonitor(); toast("已取消定稿", "info");
  }).catch(e => { toast(e.message, "error"); });
};
$("continue-btn").onclick = async () => {
  if (!AppState.currentTaskId || !AppState.currentChapter) return;
  await ButtonHelper.withLoading($("continue-btn"), async () => {
    const d = await api("/api/chapter/continue", { method: "POST", body: JSON.stringify({
      task_id: AppState.currentTaskId, chapter_index: AppState.currentChapter.chapter_index,
      guidance: $("chapter-guidance").value.trim(), target_words: Number($("chapter-target-words").value || 800),
    })});
    showChapter(d.chapter); renderCatalog(d.catalog); await refreshCreativePanels(); await refreshTaskMonitor(); toast("章节续写完成", "success");
  }).catch(e => { toast(e.message, "error"); });
};
$("revise-btn").onclick = async () => {
  if (!AppState.currentTaskId || !AppState.currentChapter) return;
  await ButtonHelper.withLoading($("revise-btn"), async () => {
    const d = await api("/api/chapter/revise", { method: "POST", body: JSON.stringify({
      task_id: AppState.currentTaskId, chapter_index: AppState.currentChapter.chapter_index,
      guidance: $("chapter-guidance").value.trim(),
    })});
    showChapter(d.chapter); renderCatalog(d.catalog); await refreshCreativePanels(); await refreshTaskMonitor(); toast("整章改写完成", "success");
  }).catch(e => { toast(e.message, "error"); });
};
$("revise-fragment-btn").onclick = async () => {
  if (!AppState.currentTaskId || !AppState.currentChapter) return;
  await ButtonHelper.withLoading($("revise-fragment-btn"), async () => {
    const d = await api("/api/chapter/revise-fragment", { method: "POST", body: JSON.stringify({
      task_id: AppState.currentTaskId, chapter_index: AppState.currentChapter.chapter_index,
      fragment: $("fragment-guidance").value.trim(), guidance: $("chapter-guidance").value.trim(),
    })});
    showChapter(d.chapter); renderCatalog(d.catalog); await refreshCreativePanels(); await refreshTaskMonitor(); toast("片段改写完成", "success");
  }).catch(e => { toast(e.message, "error"); });
};

$("batch-generate-btn").onclick = async () => {
  if (!AppState.currentTaskId) return;
  await ButtonHelper.withLoading($("batch-generate-btn"), async () => {
    if (!$("batch-auto-finalize").checked) {
      throw new Error("批量推进为了保证长篇连续性，必须开启“自动定稿”。");
    }
    const uiStart = normalizeBatchUiStart($("batch-start").value);
    const uiEnd = normalizeBatchUiEnd($("batch-end").value);
    if (uiEnd > 0 && uiEnd < uiStart) {
      throw new Error("结束章不能小于起始章。");
    }
    const d = await api("/api/batch-generate", {
      method: "POST", background: true,
      body: JSON.stringify({
        task_id: AppState.currentTaskId,
        start_chapter: uiStart - 1,
        end_chapter: uiEnd > 0 ? uiEnd : 0,
        auto_finalize: $("batch-auto-finalize").checked, max_retries: 1,
      }),
    });
    const endText = uiEnd || (AppState.currentPlannedChapters || AppState.currentCatalog.length || 0);
    toast(`批量推进已启动：计划从第${uiStart}章连续推进到第${endText}章`, "info");
    AppState.currentBatchId = d.batch_id;
    localStorage.setItem("current_batch_id", d.batch_id);
    $("batch-meta").textContent = "进行中";
    $("batch-progress").innerHTML = '<div class="empty-state">批量任务已启动，正在轮询进度...</div>';
    await refreshTaskMonitor();
    refreshBatchStatus();
    const timer = setInterval(async () => {
      if (!AppState.currentBatchId) { clearInterval(timer); return; }
      await refreshBatchStatus();
    }, 4000);
  }).catch(e => { toast(e.message, "error"); });
};

const storyEvolutionBtn = $("apply-story-evolution-btn");
if (storyEvolutionBtn) storyEvolutionBtn.onclick = applyStoryEvolution;

const styleLearnBtn = $("style-learn-btn");
if (styleLearnBtn) styleLearnBtn.onclick = openStyleLearnDialog;
const styleLearnSubmit = $("style-learn-submit");
if (styleLearnSubmit) styleLearnSubmit.onclick = submitStyleLearn;

$("versions-list").addEventListener("click", async (e) => {
  const pick = e.target.closest("[data-vpick]");
  const view = e.target.closest("[data-vview]");
  const sel = e.target.closest("[data-vselect]");
  if (pick) {
    const val = pick.dataset.vpick;
    if (AppState.selectedVersions.includes(val)) { AppState.selectedVersions = AppState.selectedVersions.filter(v => v !== val); pick.textContent = "选"; }
    else { if (AppState.selectedVersions.length >= 2) AppState.selectedVersions.shift(); AppState.selectedVersions.push(val); pick.textContent = "已选"; }
    return;
  }
  if (view) { const [cid, ver] = view.dataset.vview.split(":"); const d = await api(`/api/db/chapter/${cid}/content/${ver}`); showChapter({ ...AppState.currentChapter, content: d.content, word_count: d.word_count, consistency_score: d.consistency_score, version: d.version }); return; }
  if (sel) { const [cid, ver] = sel.dataset.vselect.split(":"); const d = await api("/api/db/chapter/select-version", { method: "POST", body: JSON.stringify({ chapter_id: Number(cid), version: Number(ver) }) }); if (AppState.currentChapter) { AppState.currentChapter = { ...AppState.currentChapter, content: d.content, version: d.current_version, word_count: d.word_count }; showChapter(AppState.currentChapter); } await loadVersionsForCurrentChapter(); }
});

$("compare-versions-btn").onclick = async () => {
  if (AppState.selectedVersions.length !== 2) { toast("请选择两个版本进行对比", "warning"); return; }
  const [a, b] = AppState.selectedVersions;
  const [cid1, v1] = a.split(":"), [cid2, v2] = b.split(":");
  if (cid1 !== cid2) { toast("只能对比同一章节的两个版本", "warning"); return; }
  try {
    const d = await api("/api/db/chapter/compare", { method: "POST", body: JSON.stringify({ chapter_id: Number(cid1), version1: Number(v1), version2: Number(v2) }) });
    $("versions-meta").textContent = `对比 v${d.version1.version} vs v${d.version2.version}`;
    $("versions-list").innerHTML = `<div class="catalog-item"><div class="info"><div class="title">差异 ${d.diff_lines} 行</div><pre class="reader" style="min-height:120px;max-height:280px;font-size:var(--text-xs);">${escapeHtml(d.diff)}</pre><button class="btn-sm" onclick="loadVersionsForCurrentChapter()">返回版本列表</button></div></div>`;
  } catch (e) { toast(e.message, "error"); }
};

$("plant-foreshadow-btn").onclick = async () => {
  if (!AppState.currentTaskId) return;
  try {
    await api("/api/db/foreshadow/plant", {
      method: "POST", body: JSON.stringify({
        project_id: AppState.currentTaskId,
        description: $("foreshadow-desc").value.trim(),
        chapter_index: Number($("foreshadow-chapter").value || 0),
      }),
    });
    toast("伏笔已埋设", "success");
    $("foreshadow-desc").value = "";
    await loadTimelineAndForeshadow();
  } catch (e) { toast(e.message, "error"); }
};

$("save-profile-btn").onclick = async () => {
  await ButtonHelper.withLoading($("save-profile-btn"), async () => {
    await api("/api/auth/me", {
      method: "PUT",
      body: JSON.stringify({ nickname: $("set-nickname").value.trim(), email: $("set-email").value.trim() }),
    });
    toast("保存成功", "success");
  }).catch(e => { toast(e.message, "error"); });
};

$("llm-save-btn").onclick = async () => {
  await ButtonHelper.withLoading($("llm-save-btn"), saveLlmConfig).catch(e => { toast(e.message, "error"); });
};
$("llm-reset-btn").onclick = () => loadLlmConfig();

$("admin-refresh-users").onclick = loadAdmin;

$("admin-recharge-btn").onclick = async () => {
  await ButtonHelper.withLoading($("admin-recharge-btn"), async () => {
    await api("/api/admin/recharge", {
      method: "POST",
      body: JSON.stringify({
        user_id: Number($("admin-recharge-uid").value),
        amount: Number($("admin-recharge-amount").value),
      }),
    });
    toast("充值成功", "success");
    loadAdmin();
  }).catch(e => { $("admin-status").textContent = e.message; });
};

$("theme-toggle-btn").onclick = (e) => { e.preventDefault(); ThemeManager.toggle(); };
$("sidebar-toggle").onclick = () => Sidebar.toggle();

Keyboard.bind('Ctrl+s', () => {
  if (AppState.currentTaskId && $("approve-btn")) $("approve-btn").click();
});
Keyboard.bind('Escape', () => {
  const overlay = $("dialog-overlay");
  if (overlay.style.display !== 'none') {
    const inputs = overlay.querySelectorAll('input, textarea');
    const hasContent = [...inputs].some(i => i.value.trim());
    if (hasContent && document.activeElement?.tagName !== 'BODY') return;
    hideDialog(); return;
  }
  const reader = $("chapter-content");
  if (reader.classList.contains('reading-mode')) { reader.classList.remove('reading-mode'); return; }
});

updateAuthUI();
