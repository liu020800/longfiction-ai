/* === AI痕迹检测 + 阅读器内联高亮 === */

async function detectAIWithHighlight() {
  if (!AppState.currentChapter?.content) { toast("请先生成章节内容", "warning"); return; }
  const reader = $("chapter-content");
  if (!reader) return;
  const text = AppState.currentChapter.content;
  try {
    const d = await api("/api/ai-detect/highlight", {
      method: "POST",
      body: JSON.stringify({ text }),
    });
    const score = d.ai_score ?? 0;
    const positions = d.positions || [];
    const details = d.details || [];
    if (!positions.length) {
      toast("✅ 未检测到明显AI痕迹", "success");
      return;
    }
    const severityColors = { high: "var(--color-danger)", mid: "var(--color-warning)", low: "var(--color-info)" };
    const severityBg = { high: "rgba(239,68,68,0.15)", mid: "rgba(245,158,11,0.15)", low: "rgba(59,130,246,0.12)" };
    let resultHtml = "";
    let lastEnd = 0;
    for (const p of positions) {
      const before = escapeHtml(text.slice(lastEnd, p.start));
      const matched = escapeHtml(text.slice(p.start, p.end));
      resultHtml += before;
      resultHtml += `<mark class="ai-highlight severity-${p.severity_class}" title="${escapeHtml(p.pattern_name)}" style="background:${severityBg[p.severity_class]};border-bottom:2px solid ${severityColors[p.severity_class]};color:var(--text);border-radius:2px;padding:0 1px;cursor:help;">${matched}</mark>`;
      lastEnd = p.end;
    }
    resultHtml += escapeHtml(text.slice(lastEnd));
    reader.innerHTML = resultHtml;
    const legendHtml = `
      <div class="ai-legend" style="display:flex;gap:16px;margin-top:8px;padding:8px 12px;background:var(--surface-2);border-radius:8px;flex-wrap:wrap;align-items:center;">
        <span style="font-size:var(--text-xs);font-weight:var(--weight-medium);color:var(--text-2);">AI痕迹评分: <strong style="color:${severityColors[score < 0.3 ? 'high' : score < 0.6 ? 'mid' : 'low']};">${(score * 100).toFixed(0)}%</strong></span>
        <span style="display:flex;align-items:center;gap:4px;font-size:var(--text-xs);color:var(--text-2);"><span style="display:inline-block;width:12px;height:12px;border-radius:2px;background:${severityBg.high};border-bottom:2px solid ${severityColors.high};"></span> 高权重(${positions.filter(p=>p.severity_class==='high').length})</span>
        <span style="display:flex;align-items:center;gap:4px;font-size:var(--text-xs);color:var(--text-2);"><span style="display:inline-block;width:12px;height:12px;border-radius:2px;background:${severityBg.mid};border-bottom:2px solid ${severityColors.mid};"></span> 中权重(${positions.filter(p=>p.severity_class==='mid').length})</span>
        <span style="display:flex;align-items:center;gap:4px;font-size:var(--text-xs);color:var(--text-2);"><span style="display:inline-block;width:12px;height:12px;border-radius:2px;background:${severityBg.low};border-bottom:2px solid ${severityColors.low};"></span> 低权重(${positions.filter(p=>p.severity_class==='low').length})</span>
        <span style="margin-left:auto;"><button class="btn-ghost btn-xs" onclick="clearAIHighlights()">清除高亮</button></span>
      </div>`;
    const existingLegend = reader.parentElement.querySelector(".ai-legend");
    if (existingLegend) existingLegend.remove();
    reader.insertAdjacentHTML("afterend", legendHtml);
    toast(`检测到 ${details.length} 类模式共 ${positions.length} 处`, details.length <= 3 ? "info" : "warning");
  } catch (e) { toast(e.message, "error"); }
}

function clearAIHighlights() {
  const reader = $("chapter-content");
  if (!reader) return;
  reader.textContent = AppState.currentChapter?.content || reader.textContent;
  const legend = reader.parentElement.querySelector(".ai-legend");
  if (legend) legend.remove();
}

async function detectAIShowReport() {
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
        ${(d.details || []).map(p => {
          const sevClass = p.severity >= 0.8 ? 'high' : p.severity >= 0.6 ? 'mid' : 'low';
          const sevColors = {high: 'var(--color-danger)', mid: 'var(--color-warning)', low: 'var(--color-info)'};
          return `<div style="padding:6px 0;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;align-items:center;">
            <span><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${sevColors[sevClass]};margin-right:6px;"></span><strong>${p.name}</strong> <span style="color:var(--text-2);font-size:var(--text-xs);">x${p.count}</span></span>
            <span style="color:var(--text-2);font-size:var(--text-xs);">${p.description}</span>
          </div>`;
        }).join('')}
      </div>
      <div class="dialog-actions">
        <button class="btn-secondary" onclick="hideDialog();detectAIWithHighlight()">在阅读器中高亮</button>
        <button class="btn-secondary" onclick="hideDialog()">关闭</button>
      </div>
    `);
  } catch (e) { toast(e.message, "error"); }
}