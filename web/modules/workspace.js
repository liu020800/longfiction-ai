/* === Workspace Module === */

function workspacePrefsKey(taskId) {
  return taskId ? `lf-workspace:${taskId}` : null;
}

function normalizeBatchUiStart(value) {
  const num = Number(value || 0);
  return Number.isFinite(num) && num >= 1 ? Math.floor(num) : 1;
}

function normalizeBatchUiEnd(value) {
  const num = Number(value || 0);
  return Number.isFinite(num) && num >= 0 ? Math.floor(num) : 0;
}

function readWorkspacePrefs(taskId = AppState.currentTaskId) {
  const key = workspacePrefsKey(taskId);
  if (!key) return {};
  try {
    return JSON.parse(localStorage.getItem(key) || "{}");
  } catch (e) {
    return {};
  }
}

function writeWorkspacePrefs(patch) {
  const key = workspacePrefsKey(AppState.currentTaskId);
  if (!key) return;
  const next = { ...readWorkspacePrefs(), ...patch };
  localStorage.setItem(key, JSON.stringify(next));
}

function bindWorkspacePrefs() {
  if (AppState.workspacePrefsReady) return;
  const fields = [
    ["chapter-guidance", "input", (el) => ({ chapterGuidance: el.value })],
    ["chapter-target-words", "input", (el) => ({ chapterTargetWords: Number(el.value || 0) || AppState.currentWordsPerChapter || 2000 })],
    ["fragment-guidance", "input", (el) => ({ fragmentGuidance: el.value })],
    ["batch-start", "input", (el) => ({ batchStart: normalizeBatchUiStart(el.value) })],
    ["batch-end", "input", (el) => ({ batchEnd: normalizeBatchUiEnd(el.value) })],
    ["batch-auto-finalize", "change", (el) => ({ batchAutoFinalize: Boolean(el.checked) })],
    ["regen-hint", "input", (el) => ({ regenHint: el.value })],
  ];
  fields.forEach(([id, eventName, build]) => {
    const el = $(id);
    if (!el) return;
    el.addEventListener(eventName, () => writeWorkspacePrefs(build(el)));
  });
  AppState.workspacePrefsReady = true;
}

function restoreWorkspacePrefs() {
  const prefs = readWorkspacePrefs();
  $("chapter-guidance").value = prefs.chapterGuidance || "";
  $("chapter-target-words").value = prefs.chapterTargetWords || AppState.currentWordsPerChapter || 2000;
  $("fragment-guidance").value = prefs.fragmentGuidance || "";
  $("batch-start").value = normalizeBatchUiStart(prefs.batchStart ?? 1);
  $("batch-end").value = normalizeBatchUiEnd(prefs.batchEnd ?? 0);
  $("batch-auto-finalize").checked = prefs.batchAutoFinalize ?? true;
  $("regen-hint").value = prefs.regenHint || "";
}

function setApprovalState(isApproved) {
  AppState.approved = isApproved;
  const wsStatus = $("ws-status");
  if (isApproved) {
    wsStatus.textContent = "已确认";
    wsStatus.className = "pill pill-success";
  } else {
    wsStatus.textContent = "待确认";
    wsStatus.className = "pill pill-warning";
  }
}

function resetWorkspaceState() {
  AppState.currentCatalog = [];
  AppState.currentChapter = null;
  AppState.selectedVersions = [];
  AppState.approved = false;
  AppState.projectDirty = false;
  $("catalog").innerHTML = '<div class="empty-state">正在加载章节目录...</div>';
  $("chapter-meta").textContent = '未选择';
  $("chapter-content").textContent = '正在加载章节内容...';
  $("versions-meta").textContent = '未选择';
  $("versions-list").innerHTML = '<div class="empty-state">正在加载版本...</div>';
  $("timeline-meta").textContent = '加载中';
  $("timeline-list").innerHTML = '<div class="empty-state">正在加载时间线...</div>';
  $("foreshadow-meta").textContent = '加载中';
  $("foreshadow-list").innerHTML = '<div class="empty-state">正在加载伏笔...</div>';
}

async function loadWorkspaceProject() {
  if (!AppState.currentTaskId) {
    $("ws-project-title").textContent = "选择或创建项目";
    $("ws-project-id").textContent = "未选择";
    $("catalog").innerHTML = '';
    const el = EmptyState.chapters();
    el.querySelector('.empty-state-desc').textContent = '创建或打开一个项目开始创作';
    const btn = document.createElement('button');
    btn.className = 'btn-primary btn-sm';
    btn.style.marginTop = '4px';
    btn.textContent = '创建新项目';
    btn.onclick = showInitForm;
    el.appendChild(btn);
    $("catalog").appendChild(el);
    $("chapter-content").textContent = "";
    return;
  }
  resetWorkspaceState();
  try {
    const project = await api(`/api/project/${AppState.currentTaskId}`);
    AppState.currentTitle = project.title || "未命名项目";
    AppState.currentOutline = project.outline || "";
    AppState.currentGenre = project.genre || "urban_fantasy";
    AppState.currentStyle = project.style || "web_novel";
    AppState.currentTargetChapters = project.target_chapters || 10;
    AppState.currentPlannedChapters = project.planned_chapters || (project.chapters || []).length || 0;
    AppState.currentWordsPerChapter = project.words_per_chapter || 2000;
    $("meta-title").value = AppState.currentTitle;
    $("meta-outline").value = AppState.currentOutline;
    $("meta-genre").value = AppState.currentGenre;
    $("meta-style").value = AppState.currentStyle;
    $("meta-target-chapters").value = AppState.currentTargetChapters;
    $("meta-words-per-chapter").value = AppState.currentWordsPerChapter;
    $("ws-project-title").textContent = AppState.currentTitle;
    $("ws-project-id").textContent = AppState.currentTaskId;
    const wsTaskId = $("ws-task-id");
    if (wsTaskId) wsTaskId.textContent = AppState.currentTaskId;

    setApprovalState(Boolean(project.approved));

    $("world-editor").value = worldToText(project.world || {});
    $("characters-editor").value = charactersToText(project.characters || []);
    $("chapters-editor").value = chaptersToText(project.chapters || []);
    bindWorkspacePrefs();
    restoreWorkspacePrefs();
    AppState.projectDirty = false;

    await refreshCatalog();
    $("approve-status").textContent = AppState.approved
      ? `✓ 设定已确认，当前已规划 ${AppState.currentPlannedChapters}/${AppState.currentTargetChapters} 章`
      : "请检查设定后，点击「保存并确认」";

    const chaps = await api(`/api/chapters/${AppState.currentTaskId}`);
    if (chaps.chapters?.length) showChapter(chaps.chapters[chaps.chapters.length - 1]);
    else { $("chapter-meta").textContent = "未选择"; $("chapter-content").textContent = "← 在章节列表中点「生成」开始写作"; }

    await refreshCreativePanels();
    renderQualityHeatmap();
    await refreshTaskMonitor();
    startTaskMonitor();
  } catch (e) {
    toast("加载项目失败: " + e.message, "error");
    $("catalog").innerHTML = `<div class="empty-state">加载失败: ${e.message}</div>`;
  }
}

async function refreshCreativePanels() {
  await loadTimelineAndForeshadow();
  await loadEnhancementPanels();
}

function taskStatusText(status) {
  const s = String(status || "unknown");
  if (s.startsWith("running")) return "运行中";
  if (s.startsWith("completed")) return "已完成";
  if (s.startsWith("failed")) return "失败";
  if (s === "initialized") return "就绪";
  return s;
}

function renderTaskMonitor(tasks, pipeline) {
  const list = $("task-monitor-list");
  const meta = $("task-monitor-meta");
  if (!list || !meta) return;
  const active = (tasks || []).filter(t => String(t.status || "").startsWith("running"));
  meta.textContent = active.length ? `${active.length} 个任务运行中` : "无运行任务";
  meta.className = active.length ? "pill pill-warning" : "pill";

  const visible = active.length ? active : (tasks || []).slice(-5).reverse();
  if (!visible.length) {
    const generated = pipeline?.generated ?? AppState.currentCatalog.filter(ch => ch.generated).length;
    const planned = pipeline?.planned_chapters ?? AppState.currentCatalog.length;
    list.innerHTML = `<div class="empty-state">当前无耗时任务。章节进度：${generated || 0}/${planned || 0}。</div>`;
    return;
  }
  list.innerHTML = visible.map(task => {
    const status = String(task.status || "");
    const progress = Math.max(0, Math.min(100, Math.round((task.progress || 0) * 100)));
    const cls = status.startsWith("running") ? "running" : (status.startsWith("failed") ? "failed" : "completed");
    const updated = task.updated_at ? ` · ${escapeHtml(task.updated_at.replace("T", " ").replace("Z", ""))}` : "";
    return `
      <div class="task-card ${cls}">
        <div class="task-title">
          <span>${escapeHtml(task.label || task.type || "任务")}</span>
          <span class="pill">${taskStatusText(task.status)}</span>
        </div>
        <div class="task-stage">${escapeHtml(task.stage || "等待状态更新")}${updated}</div>
        <div class="task-progress"><span style="width:${progress}%;"></span></div>
      </div>`;
  }).join("");
}

async function refreshTaskMonitor() {
  if (!AppState.currentTaskId) return;
  try {
    const d = await api(`/api/tasks/${AppState.currentTaskId}`);
    const runningBatch = (d.active || []).find(t => t.type === "batch");
    if (runningBatch) {
      AppState.currentBatchId = runningBatch.id;
      localStorage.setItem("current_batch_id", runningBatch.id);
      await refreshBatchStatus();
    }
    // Auto-refresh catalog when generated count changes
    const pipelineGenerated = d.pipeline?.generated ?? 0;
    const prevGenerated = AppState._lastKnownGenerated ?? 0;
    if (pipelineGenerated > prevGenerated && prevGenerated > 0) {
      await refreshCatalog();
    }
    AppState._lastKnownGenerated = pipelineGenerated;
    renderTaskMonitor(d.tasks || [], d.pipeline || {});
  } catch (e) {
    const list = $("task-monitor-list");
    if (list) list.innerHTML = `<div class="empty-state">${escapeHtml(e.message)}</div>`;
  }
}

function startTaskMonitor() {
  if (AppState.taskMonitorTimer) clearInterval(AppState.taskMonitorTimer);
  AppState.taskMonitorTimer = setInterval(async () => {
    if (!AppState.currentTaskId) return;
    await refreshTaskMonitor();
  }, 4000);
}

async function loadTemplates() {
  try {
    const d = await api("/api/templates");
    AppState.templatesCache = d.templates || [];
  } catch (e) { AppState.templatesCache = []; }
}

function showInitForm() {
  loadTemplates().then(() => {
    const templateOptions = AppState.templatesCache.map(t =>
      `<option value="${t.id}">${t.name}</option>`
    ).join("");

    showDialog(`
      <h3>新建小说项目</h3>
      <div class="form-group"><label>选择灵感模板（可选）</label>
        <select id="dlg-template" onchange="applyTemplate()" style="width:100%;">
          <option value="">—— 自定义灵感 ——</option>
          ${templateOptions}
        </select>
      </div>
      <div class="form-group"><label>小说灵感 / 故事设定</label><textarea id="dlg-outline" rows="7" style="width:100%;" placeholder="写下你的核心灵感、主角、冲突、世界观偏好或想要的爽点。AI 会先据此生成项目骨架和设定草稿。"></textarea></div>
      <div style="display:flex;gap:12px;">
        <div class="form-group" style="flex:1;"><label>类型</label>
          <select id="dlg-genre" style="width:100%;">
            <option value="urban_fantasy">都市玄幻</option>
            <option value="xuanhuan">玄幻</option>
            <option value="xianxia">仙侠</option>
            <option value="sci_fi">科幻</option>
            <option value="romance">言情</option>
          </select>
        </div>
        <div class="form-group" style="flex:1;"><label>风格</label>
          <select id="dlg-style" style="width:100%;">
            <option value="web_novel">爽文</option>
            <option value="dark">暗黑</option>
            <option value="humor">轻松</option>
            <option value="serious">严肃</option>
          </select>
        </div>
      </div>
      <div style="display:flex;gap:12px;">
        <div class="form-group" style="flex:1;"><label>总目标章节数</label><input id="dlg-chapters" type="number" value="120" /></div>
        <div class="form-group" style="flex:1;"><label>每章字数</label><input id="dlg-words" type="number" value="2000" /></div>
      </div>
      <div id="dlg-init-error" class="error-msg"></div>
      <div class="dialog-actions">
        <button class="btn-secondary" onclick="hideDialog()">取消</button>
        <button onclick="doInitProject()" class="btn-primary">生成设定草稿</button>
      </div>
    `);
  });
}

function applyTemplate() {
  const tid = $("dlg-template").value;
  const t = AppState.templatesCache.find(t => t.id === tid);
  if (!t) return;
  $("dlg-outline").value = t.outline || "";
  $("dlg-genre").value = t.genre || "urban_fantasy";
  $("dlg-style").value = t.style || "web_novel";
  $("dlg-chapters").value = t.target_chapters || 100;
  $("dlg-words").value = t.words_per_chapter || 2000;
}

async function doInitProject() {
  const btn = document.querySelector('.dialog-actions .btn-primary');
  await ButtonHelper.withLoading(btn, async () => {
    const d = await api("/api/init", {
      method: "POST",
      body: JSON.stringify({
        outline: $("dlg-outline").value.trim(),
        genre: $("dlg-genre").value,
        style: $("dlg-style").value,
        target_chapters: Number($("dlg-chapters").value),
        words_per_chapter: Number($("dlg-words").value),
      }),
    });
    AppState.currentTaskId = d.task_id;
    hideDialog();
    toast("项目初始化成功", "success");
    navigate("#workspace");
    loadWorkspaceProject();
  }).catch(e => { $("dlg-init-error").textContent = e.message; });
}

function renderCatalog(catalog, volumeName) {
  AppState.currentCatalog = catalog || [];
  const root = $("catalog");
  if (!AppState.currentCatalog.length) { root.innerHTML = ''; root.appendChild(EmptyState.chapters()); return; }

  const totalCount = AppState.currentCatalog.length;
  const generatedCount = AppState.currentCatalog.filter(ch => ch.generated).length;
  const progress = totalCount ? Math.round((generatedCount / totalCount) * 100) : 0;
  const progressFill = $("catalog-progress-fill");
  const progressText = $("catalog-progress-text");
  if (progressFill) progressFill.style.width = progress + '%';
  if (progressText) progressText.textContent = `${generatedCount}/${totalCount} 已规划 (${progress}%)`;

  let html = '';

  if (volumeName) {
    const totalWords = AppState.currentCatalog.reduce((s, ch) => s + (ch.word_count || 0), 0);
    const finalizedCount = AppState.currentCatalog.filter(ch => ch.finalized).length;
    html += `
      <div class="volume-header">
        <span class="volume-name">${escapeHtml(volumeName)}</span>
        <span class="volume-stats">${generatedCount}/${totalCount} 章已规划 · 总目标 ${AppState.currentTargetChapters || totalCount} 章 · ${finalizedCount} 章已定稿 · ${totalWords} 字</span>
      </div>`;
  }

  html += AppState.currentCatalog.map((ch, i) => {
    const statusIcon = ch.finalized ? '🔒' : (ch.generated ? '✓' : '○');
    const action = ch.generated ? "regenerate" : "generate";
    return `
    <div class="catalog-item ${ch.generated ? "done" : ""} ${ch.finalized ? "finalized" : ""}" data-idx="${ch.chapter_index}">
      <div class="idx">${i + 1}</div>
      <div class="info">
        <div class="title">${statusIcon} ${escapeHtml(ch.title)}</div>
        <div class="meta">${ch.word_count || 0}字 · ${ch.finalized ? "已定稿" : (ch.generated ? "草稿" : "未生成")}</div>
      </div>
      <div class="actions">
        ${ch.generated ? `<button class="btn-xs btn-outline" data-action="view" data-idx="${ch.chapter_index}">查看</button>` : ""}
        <button class="btn-xs" data-action="${action}" data-idx="${ch.chapter_index}" ${(AppState.approved && !AppState.projectDirty) || ch.generated ? "" : "disabled"}>${ch.generated ? "重生成" : "生成"}</button>
      </div>
    </div>`;
  }).join("");

  root.innerHTML = html;
}

async function refreshCatalog() {
  if (!AppState.currentTaskId) return;
  try {
    const d = await api(`/api/catalog/${AppState.currentTaskId}`);
    renderCatalog(d.catalog, d.volume_name || "第一部");
    renderQualityHeatmap();
  } catch (e) {}
}

function showChapter(ch) {
  AppState.currentChapter = ch;
  if (!ch) return;
  const versionText = ch.version ? ` | v${ch.version}` : "";
  $("chapter-meta").textContent = `${ch.title} | ${ch.word_count}字${versionText}`;
  $("chapter-content").textContent = ch.content || "";
  updateWordCounter(ch.content || "");
  loadVersionsForCurrentChapter();
  // 显示定稿错误（如有）
  const errEl = $("finalize-errors");
  if (errEl) {
    if (ch.finalize_errors && ch.finalize_errors.length > 0) {
      errEl.innerHTML = "<strong>⚠️ 定稿问题：</strong><br>" + ch.finalize_errors.map(e => "• " + e).join("<br>");
      errEl.style.display = "block";
    } else {
      errEl.style.display = "none";
    }
  }
}

function updateWordCounter(text) {
  const counter = $("word-counter");
  if (!counter) return;
  const { chinese, total } = WordCounter.count(text);
  counter.textContent = `${chinese} 字 / ${total} 字符`;
}

async function regenerateSection(type) {
  if (!AppState.currentTaskId) return;
  const btn = $(`regen-${type === 'world' ? 'world' : type === 'characters' ? 'characters' : 'chapters'}`);
  await ButtonHelper.withLoading(btn, async () => {
    const hint = $("regen-hint").value.trim();
    const d = await api(`/api/project/regenerate/${type}`, {
      method: "POST", body: JSON.stringify({ task_id: AppState.currentTaskId, prompt_hint: hint }),
    });
    if (d.world) $("world-editor").value = worldToText(d.world);
    if (d.characters) $("characters-editor").value = charactersToText(d.characters);
    if (d.chapters) $("chapters-editor").value = chaptersToText(d.chapters);
    if (d.catalog) renderCatalog(d.catalog);
    if (type === "chapters") {
      AppState.currentChapter = null;
      $("chapter-meta").textContent = "未选择";
      $("chapter-content").textContent = "章节规划已重置，请从第1章重新生成正文";
      $("versions-meta").textContent = "未选择";
      $("versions-list").innerHTML = '<div class="empty-state">章节重规划后，旧版本已清空</div>';
      updateWordCounter("");
    }
    setApprovalState(false);
    $("approve-status").textContent = "已重生成，请确认后再生成章节";
    toast("重生成完成", "success");
    await loadTimelineAndForeshadow();
    await refreshTaskMonitor();
    await loadEnhancementPanels();
  }).catch(e => { toast("重生成失败: " + e.message, "error"); });
}

function initReaderControls() {
  const fontUp = $("reader-font-up");
  const fontDown = $("reader-font-down");
  const fullscreen = $("reader-fullscreen");
  if (fontUp) fontUp.onclick = () => { AppState.readerFontSize = Math.min(22, AppState.readerFontSize + 2); $("chapter-content").style.fontSize = AppState.readerFontSize + 'px'; };
  if (fontDown) fontDown.onclick = () => { AppState.readerFontSize = Math.max(12, AppState.readerFontSize - 2); $("chapter-content").style.fontSize = AppState.readerFontSize + 'px'; };
  if (fullscreen) fullscreen.onclick = () => {
    const reader = $("chapter-content");
    reader.classList.toggle('reading-mode');
    if (reader.classList.contains('reading-mode')) {
      const closeBtn = document.createElement('button');
      closeBtn.className = 'btn-sm btn-ghost';
      closeBtn.style.cssText = 'position:fixed;top:20px;right:20px;z-index:1001;font-size:18px;';
      closeBtn.textContent = '✕';
      closeBtn.onclick = () => { reader.classList.remove('reading-mode'); closeBtn.remove(); };
      document.body.appendChild(closeBtn);
    }
  };
}

async function refreshBatchStatus() {
  if (!AppState.currentBatchId) return;
  try {
    const d = await api(`/api/status/${AppState.currentBatchId}`);
    $("batch-meta").textContent = d.status || '运行中';
    const chunks = [];
    if (typeof d.progress === 'number') chunks.push(`进度：${Math.round(d.progress * 100)}%`);
    if (d.results?.requested_start_chapter !== undefined && d.results?.start_chapter !== undefined && d.results.requested_start_chapter !== d.results.start_chapter) {
      chunks.push(`已自动校正起点：从第${d.results.requested_start_chapter + 1}章调整到第${d.results.start_chapter + 1}章，确保连续生成`);
    }
    if (d.results?.total !== undefined && d.results?.generated !== undefined) {
      chunks.push(`批量范围：第${(d.results.start_chapter ?? 0) + 1}章到第${d.results.end_chapter ?? 0}章，共 ${d.results.total} 章；已生成 ${d.results.generated} 章，已定稿 ${d.results.finalized || 0} 章`);
    }
    if (d.results?.stopped_early && d.results?.stop_reason) {
      chunks.push(`提前停止：${d.results.stop_reason}`);
    }
    if (d.last_chapter) chunks.push(`最近章节：第${(d.last_chapter.chapter_index ?? 0) + 1}章 ${d.last_chapter.title || ''}`);
    if (d.results?.chapters) chunks.push(...d.results.chapters.slice(-5).map(c => `第${(c.chapter_index ?? 0) + 1}章：${c.status}`));
    $("batch-progress").innerHTML = chunks.length ? chunks.map(t => `<div class="catalog-item"><div class="info"><span class="meta">${escapeHtml(t)}</span></div></div>`).join('') : '<div class="empty-state">暂无进度</div>';
    // Refresh catalog during batch so sidebar updates in real-time
    AppState._batchPollCount = (AppState._batchPollCount || 0) + 1;
    if (AppState._batchPollCount % 3 === 0) {
      await refreshCatalog();
    }
    if (String(d.status).startsWith('completed') || String(d.status).startsWith('failed')) {
      AppState.currentBatchId = null;
      AppState._batchPollCount = 0;
      localStorage.removeItem("current_batch_id");
      await refreshCatalog();
      await refreshCreativePanels();
      await refreshTaskMonitor();
    }
  } catch (e) {
    $("batch-progress").innerHTML = `<div class="empty-state">${escapeHtml(e.message)}</div>`;
  }
}

async function loadVersionsForCurrentChapter() {
  const vl = $("versions-list");
  if (!AppState.currentTaskId || !AppState.currentChapter) { vl.innerHTML = ''; vl.appendChild(EmptyState.versions()); return; }
  try {
    const dbCh = await api(`/api/db/project/${AppState.currentTaskId}/chapters`);
    const match = (dbCh.chapters || []).find(c => c.chapter_index === AppState.currentChapter.chapter_index);
    if (!match) { vl.innerHTML = ''; vl.appendChild(EmptyState.versions()); return; }
    const versions = await api(`/api/db/chapter/${match.id}/versions`);
    AppState.selectedVersions = [];
    $("versions-meta").textContent = `${versions.title} | v${versions.current_version}`;
    vl.innerHTML = (versions.versions || []).map(v => `
      <div class="version-item">
        <span>v${v.version}</span>
        <span style="color:var(--muted);font-size:var(--text-xs);">${v.word_count}字 · 一致性 ${v.consistency_score}</span>
        <div style="margin-left:auto;display:flex;gap:4px;">
          <button class="btn-xs btn-outline" data-vpick="${match.id}:${v.version}">选</button>
          <button class="btn-xs btn-outline" data-vview="${match.id}:${v.version}">看</button>
          <button class="btn-xs btn-outline" data-vselect="${match.id}:${v.version}">设当前</button>
        </div>
      </div>
    `).join("");
  } catch (e) { vl.innerHTML = `<div class="empty-state">${e.message}</div>`; }
}

async function loadTimelineAndForeshadow() {
  if (!AppState.currentTaskId) return;
  let observationMap = new Map();
  try {
    const obs = await api(`/api/chapter-observations/${AppState.currentTaskId}`);
    observationMap = new Map((obs.chapters || []).map(item => [item.chapter_index, item.observations || {}]));
  } catch (e) {
    observationMap = new Map();
  }
  try {
    const tl = await api(`/api/db/project/${AppState.currentTaskId}/timeline`);
    $("timeline-meta").textContent = `${tl.timeline?.length || 0} 条`;
    $("timeline-list").innerHTML = (tl.timeline || []).length
      ? tl.timeline.map(t => {
        const obs = observationMap.get(t.chapter_index) || {};
        const chars = (obs.characters_on_stage || []).slice(0, 4).join("、");
        const locations = (obs.locations || []).slice(0, 3).join("、");
        const resources = (obs.resources_touched || []).slice(0, 3).join("、");
        const extra = [
          chars ? `人物：${escapeHtml(chars)}` : "",
          locations ? `地点：${escapeHtml(locations)}` : "",
          resources ? `资源：${escapeHtml(resources)}` : "",
        ].filter(Boolean).join(" · ");
        return `<div class="catalog-item"><div class="info">
          <div class="meta">第${t.chapter_index + 1}章 [${escapeHtml(t.event_type)}] ${escapeHtml(t.description)}</div>
          ${extra ? `<div class="meta">${extra}</div>` : ""}
        </div></div>`;
      }).join("")
      : '<div class="empty-state">定稿后逐步形成</div>';
  } catch (e) { $("timeline-list").innerHTML = `<div class="empty-state">${e.message}</div>`; }

  try {
    const fs = await api(`/api/db/foreshadow/${AppState.currentTaskId}`);
    $("foreshadow-meta").textContent = `${fs.unresolved_count || 0} 条未回收`;
    $("foreshadow-list").innerHTML = (fs.foreshadows || []).length
      ? fs.foreshadows.map(f => {
        const triggerText = (f.trigger_keywords || []).length ? `触发词：${escapeHtml((f.trigger_keywords || []).join("、"))}` : "";
        const payoffText = f.payoff_condition ? `回收条件：${escapeHtml(f.payoff_condition)}` : "";
        const typeText = f.foreshadow_type ? `类型：${escapeHtml(f.foreshadow_type)}` : "";
        const deadlineText = Number.isFinite(f.close_by_chapter) && f.close_by_chapter !== null ? `最迟第${f.close_by_chapter}章回收` : "";
        const statusLabel = f.status === "resolved" ? "已回收" : (f.status === "closing" ? "回收期" : "进行中");
        const extra = [typeText, triggerText, payoffText, deadlineText].filter(Boolean).join(" · ");
        return `<div class="catalog-item ${f.status === "resolved" ? "done" : ""}"><div class="info">
          <div class="title">${f.status === "resolved" ? "✓" : (f.status === "closing" ? "◐" : "○")} ${escapeHtml(f.description)}</div>
          <div class="meta">第${f.planted_chapter + 1}章${f.resolved_chapter !== null ? ` → 第${f.resolved_chapter + 1}章` : " · 未回收"} · ${escapeHtml(statusLabel)}</div>
          ${extra ? `<div class="meta">${extra}</div>` : ""}
        </div></div>`;
      }).join("")
      : '<div class="empty-state">无伏笔</div>';
  } catch (e) { $("foreshadow-list").innerHTML = `<div class="empty-state">${e.message}</div>`; }
}
