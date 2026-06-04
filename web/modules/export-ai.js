/* === Export & AI Tools Module === */

async function downloadExport(format) {
  if (!AppState.currentTaskId) { toast("请先选择项目", "warning"); return; }
  try {
    const url = format === 'zip' ? `/api/export/${AppState.currentTaskId}` : `/api/export/${AppState.currentTaskId}/${format}`;
    const resp = await fetch(url, { headers: { "Authorization": `Bearer ${AppState.authToken}` } });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.detail || `导出失败 (${resp.status})`);
    }
    const blob = await resp.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    const ext = format === 'zip' ? 'zip' : format;
    a.download = `longfiction_${AppState.currentTaskId}.${ext}`;
    a.click();
    URL.revokeObjectURL(a.href);
    toast(`已导出 ${format.toUpperCase()} 文件`, "success");
  } catch (e) { toast(e.message, "error"); }
}

function downloadZip() { downloadExport('zip'); }
function downloadTxt() { downloadExport('txt'); }
function downloadEpub() { downloadExport('epub'); }

async function detectAI() {
  if (!AppState.currentChapter?.content) { toast("请先生成章节内容", "warning"); return; }
  try {
    const d = await api("/api/ai-detect", {
      method: "POST",
      body: JSON.stringify({ text: AppState.currentChapter.content }),
    });
    showDialog(`
      <h3>AI 痕迹检测报告</h3>
      <div style="max-height:400px;overflow-y:auto;">
        <p style="margin-bottom:8px;">检测到 <strong>${d.patterns_found || 0}</strong> 种 AI 写作模式</p>
        <p style="font-size:var(--text-sm);color:var(--muted);">AI 痕迹评分: <strong style="color:${(d.ai_score || 0) > 0.5 ? 'var(--color-danger)' : 'var(--color-success)'};">${((d.ai_score || 0) * 100).toFixed(1)}%</strong></p>
        ${(d.patterns || d.details || []).map(p => `<div style="padding:6px 0;border-bottom:1px solid var(--line);"><span style="color:var(--color-warning);">${p.name || p}</span></div>`).join('')}
      </div>
      <div class="dialog-actions"><button class="btn-secondary" onclick="hideDialog()">关闭</button></div>
    `);
  } catch (e) { toast(e.message, "error"); }
}

async function rewriteStyle() {
  if (!AppState.currentChapter?.content) { toast("请先生成章节内容", "warning"); return; }
  const confirmed = await DialogSystem.confirm({
    title: '去AI改写',
    message: '将对当前章节内容进行去AI痕迹改写，使其更自然、更像人类书写。改写后内容将替换当前章节预览。是否继续？',
    confirmText: '开始改写',
    type: 'info'
  });
  if (!confirmed) return;
  try {
    toast("正在执行去AI改写，请稍候...", "info");
    const d = await api("/api/style-rewrite", {
      method: "POST",
      body: JSON.stringify({ text: AppState.currentChapter.content }),
    });
    $("chapter-content").textContent = d.rewritten || AppState.currentChapter.content;
    updateWordCounter(d.rewritten || "");
    toast(`改写完成 (${d.original_length}→${d.rewritten_length}字)`, "success");
  } catch (e) { toast(e.message, "error"); }
}

async function analyzeDialogue() {
  if (!AppState.currentChapter?.content) { toast("请先生成章节内容", "warning"); return; }
  try {
    const d = await api("/api/dialogue-analyze", {
      method: "POST",
      body: JSON.stringify({ text: AppState.currentChapter.content }),
    });
    showDialog(`
      <h3>对话分析报告</h3>
      <div style="max-height:400px;overflow-y:auto;">
        <p>对话数量: <strong>${d.dialogue_count || 0}</strong></p>
        <p>角色分布: ${(d.characters || []).join(', ') || '无'}</p>
      </div>
      <div class="dialog-actions"><button class="btn-secondary" onclick="hideDialog()">关闭</button></div>
    `);
  } catch (e) { toast(e.message, "error"); }
}

async function loadStyleLibrary() {
  try {
    const d = await api("/api/styles");
    showDialog(`
      <h3>写作风格库</h3>
      <div style="max-height:400px;overflow-y:auto;display:flex;flex-direction:column;gap:8px;">
        ${(d.styles || []).map(s => `<div class="struct-card"><div class="struct-card-header"><span class="struct-card-title">${s.name}</span><span class="pill">${s.id}</span></div><div style="font-size:var(--text-sm);color:var(--text-2);">${(s.features || []).join(' · ')}</div></div>`).join('')}
      </div>
      <div class="dialog-actions"><button class="btn-secondary" onclick="hideDialog()">关闭</button></div>
    `);
  } catch (e) { toast(e.message, "error"); }
}
