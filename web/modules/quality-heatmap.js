/* === 章节质量热力图 === */

async function renderQualityHeatmap() {
  const container = $("quality-heatmap-content");
  if (!container || !AppState.currentTaskId) return;
  try {
    const catalog = AppState.currentCatalog || [];
    if (!catalog.length) {
      container.innerHTML = '<div class="empty-state">暂无章节数据</div>';
      return;
    }
    const scores = catalog.map(ch => ({
      idx: ch.chapter_index,
      title: ch.title,
      status: ch.status || "draft",
      word_count: ch.word_count || 0,
      consistency_score: ch.consistency_score ?? 0.5,
      ai_score: ch.ai_score ?? 0.5,
      finalized: ch.status === "finalized",
    }));
    const avgConsistency = scores.reduce((s, c) => s + c.consistency_score, 0) / scores.length;
    const avgAi = scores.reduce((s, c) => s + c.ai_score, 0) / scores.length;
    const maxWords = Math.max(...scores.map(s => s.word_count), 1);
    const meta = $("quality-heatmap-meta");
    if (meta) meta.textContent = `共${scores.length}章，平均一致性${(avgConsistency*100).toFixed(0)}%，AI分${(avgAi*100).toFixed(0)}%`;
    let html = `<div class="heatmap-grid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(28px,1fr));gap:3px;padding:4px;">`;
    for (const s of scores) {
      const consistencyColor = s.consistency_score >= 0.8 ? "#22c55e" : s.consistency_score >= 0.5 ? "#eab308" : "#ef4444";
      const opacity = 0.3 + (s.word_count / maxWords) * 0.7;
      const borderColor = s.finalized ? "#22c55e" : s.status === "generated" ? "#3b82f6" : "#6b7280";
      html += `<div class="heatmap-cell" data-tip="${escapeHtml(s.title)}" style="aspect-ratio:1;border-radius:4px;background:${consistencyColor};opacity:${opacity};border:2px solid ${borderColor};cursor:pointer;position:relative;" onclick="showChapterByIndex(${s.idx})" title="第${s.idx+1}章 ${escapeHtml(s.title)}&#10;一致性: ${(s.consistency_score*100).toFixed(0)}% / AI分: ${(s.ai_score*100).toFixed(0)}%&#10;字数: ${s.word_count} / 状态: ${s.status}"></div>`;
    }
    html += `</div>`;
    html += `<div class="heatmap-legend" style="display:flex;gap:12px;padding:4px 4px 8px;flex-wrap:wrap;font-size:var(--text-xs);color:var(--text-2);">
      <span>🔵 颜色=一致性(绿好/黄中/红差)</span>
      <span>📊 深浅=相对字数</span>
      <span>🟢 边框绿=已定稿 / 蓝=已生成 / 灰=草稿</span>
    </div>`;
    container.innerHTML = html;
  } catch (e) {
    container.innerHTML = '<div class="empty-state">暂无数据</div>';
  }
}

function showChapterByIndex(idx) {
  if (!AppState.currentCatalog) return;
  const ch = AppState.currentCatalog.find(c => c.chapter_index === idx);
  if (ch && ch.id) {
    showChapter(ch);
  } else {
    toast("该章节未生成", "warning");
  }
}