/* === Enhancement Panel === */

async function loadEnhancementPanels() {
  if (!AppState.currentTaskId) return;
  await Promise.all([
    loadProgressPanel(),
    loadQualityFlowPanel(),
    loadSuspenseArcsPanel(),
    loadInfoGapPanel(),
    loadStoryEvolutionPanel(),
    loadRelationshipGraphPanel(),
    loadStyleFingerprintPanel(),
    loadModelRouterPanel(),
  ]);
}

async function loadQualityFlowPanel() {
  const el = $("quality-flow-content");
  const meta = $("quality-flow-meta");
  if (!AppState.currentTaskId || !el || !meta) return;
  try {
    const [d, scores] = await Promise.all([
      api(`/api/quality-flow/${AppState.currentTaskId}`),
      api(`/api/quality-scores/${AppState.currentTaskId}`).catch(() => ({ history: [], latest: null, total_scored: 0 })),
    ]);
    const steps = d.steps || [];
    const doneCount = steps.filter(s => s.done).length;
    const currentTask = d.current_task;
    const totalScored = scores.total_scored || 0;
    meta.textContent = currentTask ? (currentTask.stage || "运行中") : `${doneCount}/${steps.length}`;
    if (!steps.length) {
      el.innerHTML = '<div class="empty-state">暂无质量流程数据</div>';
      return;
    }
    const html = steps.map(step => `
      <div class="quality-step ${step.done ? 'done' : ''}">
        <div class="mark">${step.done ? '✓' : '·'}</div>
        <div class="body">
          <div class="title">${escapeHtml(step.name || step.key)}</div>
          <div class="note">${escapeHtml(step.note || '')}</div>
        </div>
      </div>
    `).join("");
    const runningHint = currentTask
      ? `<div class="catalog-item"><div class="info"><div class="title">当前运行</div><div class="meta">${escapeHtml(currentTask.label || '')}：${escapeHtml(currentTask.stage || '')}</div></div></div>`
      : "";
    let scoreHtml = '';
    if (scores.latest) {
      const s = scores.latest;
      const scoreColor = s.composite_score >= 7 ? 'var(--color-success)' : s.composite_score >= 5 ? 'var(--color-warning)' : 'var(--danger)';
      scoreHtml += `<div style="margin-top:8px;padding-top:8px;border-top:1px solid var(--line);">`;
      scoreHtml += `<div style="font-size:var(--text-xs);color:var(--color-primary);font-weight:var(--weight-medium);margin-bottom:4px;">质量评分 (共${totalScored}章)</div>`;
      scoreHtml += `<div class="catalog-item"><div class="info">
        <div class="title">综合: <span style="color:${scoreColor};font-weight:var(--weight-bold);">${s.composite_score}</span>/10 · AI: ${(s.ai_score * 100).toFixed(0)}%</div>
        <div class="meta">一致性: ${(s.consistency_score * 100).toFixed(0)}%</div>
        ${(s.issues && s.issues.length) ? `<div class="meta" style="color:var(--color-warning);">${s.issues.slice(0, 2).map(i => escapeHtml(i)).join('；')}</div>` : ''}
      </div></div>`;
      // Show recent history trend
      const history = scores.history || [];
      if (history.length > 1) {
        const trend = history.slice(-5).map(h => h.composite_score.toFixed(0)).join(' → ');
        scoreHtml += `<div class="catalog-item"><div class="info"><div class="meta">近期趋势: ${trend}</div></div></div>`;
      }
      scoreHtml += '</div>';
    }
    el.innerHTML = `<div class="quality-flow-grid">${html}</div>${runningHint}${scoreHtml}`;
  } catch (e) {
    meta.textContent = "不可用";
    el.innerHTML = '<div class="empty-state">暂无质量流程数据</div>';
  }
}

async function loadProgressPanel() {
  const el = $("enh-progress-content");
  const meta = $("enh-progress-meta");
  if (!AppState.currentTaskId || !el) return;
  try {
    const d = await api(`/api/progress/${AppState.currentTaskId}`);
    meta.textContent = `${d.completed_anchors || 0}/${d.total_anchors || 0}`;
    const aProg = Math.round((d.a_progress || 0) * 100);
    const bProg = Math.round((d.b_progress || 0) * 100);
    const cProg = Math.round((d.c_progress || 0) * 100);
    el.innerHTML = `
      <div class="catalog-item"><div class="info">
        <span class="meta">A类(核心): ${aProg}%</span>
        <div style="margin-top:2px;height:4px;background:var(--line);border-radius:2px;"><div style="width:${aProg}%;height:100%;background:var(--color-primary);border-radius:2px;"></div></div>
      </div></div>
      <div class="catalog-item"><div class="info">
        <span class="meta">B类(关系): ${bProg}%</span>
        <div style="margin-top:2px;height:4px;background:var(--line);border-radius:2px;"><div style="width:${bProg}%;height:100%;background:var(--color-success);border-radius:2px;"></div></div>
      </div></div>
      <div class="catalog-item"><div class="info">
        <span class="meta">C类(揭示): ${cProg}%</span>
        <div style="margin-top:2px;height:4px;background:var(--line);border-radius:2px;"><div style="width:${cProg}%;height:100%;background:var(--color-warning);border-radius:2px;"></div></div>
      </div></div>
    `;
  } catch (e) {
    el.innerHTML = '<div class="empty-state">暂无数据</div>';
  }
}

async function loadSuspenseArcsPanel() {
  const el = $("enh-arcs-content");
  const meta = $("enh-arcs-meta");
  if (!AppState.currentTaskId || !el) return;
  try {
    const d = await api(`/api/suspense-arcs/${AppState.currentTaskId}`);
    const arcs = d.arcs || [];
    const totalChapters = d.story_total_chapters || AppState.currentTargetChapters || 0;
    meta.textContent = `${arcs.length} 活跃 / ${d.closed_count || 0} 已闭合${totalChapters ? ` / 全书${totalChapters}章` : ''}`;
    if (!arcs.length) {
      el.innerHTML = '<div class="empty-state">无活跃悬念弧</div>';
      return;
    }
    el.innerHTML = arcs.map(a => {
      const levelLabel = {short: "短弧", medium: "中弧", long: "长弧"}[a.level] || a.level;
      const overdueTag = a.overdue ? '<span style="color:var(--danger);">⚠逾期</span>' : '';
      return `<div class="catalog-item ${a.overdue ? 'finalized' : ''}"><div class="info">
        <div class="title">[${levelLabel}] ${escapeHtml(a.description)} ${overdueTag}</div>
        <span style="font-size:var(--text-xs);color:var(--muted);">第${a.planted_chapter}章 → 目标第${a.target_close_chapter}章</span>
      </div></div>`;
    }).join("");
  } catch (e) {
    el.innerHTML = '<div class="empty-state">暂无数据</div>';
  }
}

async function loadInfoGapPanel() {
  const el = $("enh-infogap-content");
  const meta = $("enh-infogap-meta");
  if (!AppState.currentTaskId || !el) return;
  try {
    const d = await api(`/api/info-gap/${AppState.currentTaskId}`);
    const rk = d.reader_knows || [];
    const ckk = d.character_knows || [];
    const rwtk = d.reader_wants_to_know || [];
    meta.textContent = `待揭${rwtk.length}`;
    let html = '';
    if (rwtk.length) {
      html += '<div style="font-size:var(--text-xs);color:var(--color-warning);font-weight:var(--weight-medium);margin-bottom:4px;">读者想知道:</div>';
      html += rwtk.slice(0, 5).map(s => `<div class="catalog-item"><div class="info"><span class="meta">? ${escapeHtml(s)}</span></div></div>`).join("");
    }
    if (rk.length) {
      html += '<div style="font-size:var(--text-xs);color:var(--text-2);font-weight:var(--weight-medium);margin:6px 0 4px;">读者已知:</div>';
      html += rk.slice(0, 3).map(s => `<div class="catalog-item"><div class="info"><span class="meta" style="color:var(--text-2);">✓ ${escapeHtml(s)}</span></div></div>`).join("");
    }
    el.innerHTML = html || '<div class="empty-state">暂无数据</div>';
  } catch (e) {
    el.innerHTML = '<div class="empty-state">暂无数据</div>';
  }
}

async function loadStoryEvolutionPanel() {
  const el = $("story-evolution-content");
  const meta = $("story-evolution-meta");
  const btn = $("apply-story-evolution-btn");
  if (!AppState.currentTaskId || !el || !meta) return;
  try {
    const [d, obsPayload] = await Promise.all([
      api(`/api/story-evolution/${AppState.currentTaskId}`),
      api(`/api/chapter-observations/${AppState.currentTaskId}`).catch(() => ({ chapters: [] })),
    ]);
    AppState.storyEvolution = d;
    const obsMap = new Map((obsPayload.chapters || []).map(item => [item.chapter_index, item.observations || {}]));
    const pending = d.pending_finalized_count || 0;
    meta.textContent = pending ? `${pending}章待同步` : "已同步";
    if (btn) btn.disabled = pending === 0;

    if (!pending) {
      const history = d.history || [];
      const last = history[history.length - 1];
      el.innerHTML = `<div class="empty-state">当前设定已跟上定稿进度${last ? `，上次同步到第${last.synced_to_chapter}章` : ""}</div>`;
      return;
    }

    const range = d.pending_range?.length ? `第${d.pending_range[0]}章至第${d.pending_range[1]}章` : "定稿章节";
    const charUpdates = d.character_updates || [];
    const planUpdates = d.chapter_plan_updates || [];
    const worldUpdates = d.world_updates || [];
    const outlineUpdates = d.outline_updates || [];
    const summaries = d.finalized_summaries || [];
    const unresolved = d.unresolved_threads || [];
    const drift = d.plan_drift_report || {};

    let html = `<div class="catalog-item evolution-brief"><div class="info">
      <div class="title">${escapeHtml(range)} 有新变化</div>
      <div class="meta">将沉淀 ${charUpdates.length} 个角色状态、${worldUpdates.length} 条世界观增量、${outlineUpdates.length} 条大纲演进，并重规划后续 ${planUpdates.length} 章。</div>
    </div></div>`;

    if (drift.checked) {
      const driftSignals = (drift.signals || []).slice(0, 3).join("；");
      html += `<div class="catalog-item"><div class="info">
        <div class="title">规划漂移检查 · ${escapeHtml(drift.recommended ? "建议重规划" : "暂不重规划")}</div>
        <div class="meta">${escapeHtml(drift.reason || "")}</div>
        ${driftSignals ? `<div class="meta">${escapeHtml(driftSignals)}</div>` : ""}
      </div></div>`;
    }

    if (summaries.length) {
      html += `<div class="evolution-section-title">定稿依据</div>`;
      html += summaries.slice(0, 3).map(item => {
        const obs = obsMap.get((item.chapter_no || 1) - 1) || {};
        const movement = (obs.hook_movements || []).slice(0, 2).join("；");
        return `<div class="catalog-item"><div class="info">
          <div class="title">第${item.chapter_no}章 · ${escapeHtml(item.title)}</div>
          <div class="meta">${escapeHtml(item.summary)}</div>
          ${movement ? `<div class="meta">观察：${escapeHtml(movement)}</div>` : ""}
        </div></div>`;
      }).join("");
    }

    if (charUpdates.length) {
      html += `<div class="evolution-section-title">角色连续性</div>`;
      html += charUpdates.slice(0, 4).map(item => `<div class="catalog-item"><div class="info">
        <div class="title">${escapeHtml(item.name)}</div>
        <div class="meta">${escapeHtml((item.memory_additions || []).join("；"))}</div>
      </div></div>`).join("");
    }

    if (worldUpdates.length) {
      const worldText = worldUpdates.slice(0, 3).map(item => typeof item === "string" ? item : item.summary).join("；");
      html += `<div class="catalog-item"><div class="info">
        <div class="title">世界观增量</div>
        <div class="meta">${escapeHtml(worldText)}</div>
      </div></div>`;
    }

    if (unresolved.length) {
      html += `<div class="catalog-item"><div class="info">
        <div class="title">未回收伏笔提醒</div>
        <div class="meta">${escapeHtml(unresolved.slice(0, 3).map(item => `第${item.planted_chapter}章：${item.description}`).join("；"))}</div>
      </div></div>`;
    }

    el.innerHTML = html;
  } catch (e) {
    meta.textContent = "不可用";
    if (btn) btn.disabled = true;
    el.innerHTML = '<div class="empty-state">暂无演进数据</div>';
  }
}

async function applyStoryEvolution() {
  if (!AppState.currentTaskId) return;
  const btn = $("apply-story-evolution-btn");
  let preview = AppState.storyEvolution;
  try {
    preview = await api(`/api/story-evolution/${AppState.currentTaskId}`);
    AppState.storyEvolution = preview;
  } catch (e) {
    toast(e.message, "error");
    return;
  }
  if (!(preview.pending_finalized_count || 0)) {
    toast("当前没有需要同步的定稿变化", "info");
    await loadStoryEvolutionPanel();
    return;
  }
  const range = preview.pending_range?.length ? `第${preview.pending_range[0]}章至第${preview.pending_range[1]}章` : "最新定稿章节";
  const planUpdates = preview.chapter_plan_updates || [];
  const charUpdates = preview.character_updates || [];
  const worldUpdates = preview.world_updates || [];
  const outlineUpdates = preview.outline_updates || [];
  const confirmed = await DialogSystem.confirm({
    title: "同步故事演进？",
    message: `${range} 将写入正式记忆：更新 ${charUpdates.length} 个角色、${worldUpdates.length} 条世界观增量、${outlineUpdates.length} 条大纲演进，并只调整未来未生成的 ${planUpdates.length} 个章节规划。已生成/已定稿正文不会被改写。`,
    confirmText: "确认同步",
    cancelText: "再看看",
    type: "info",
  });
  if (!confirmed) return;
  await ButtonHelper.withLoading(btn, async () => {
    const d = await api(`/api/story-evolution/${AppState.currentTaskId}/apply`, { method: "POST" });
    if (d.status === "applied") {
      toast("已同步故事演进记忆与后续章节规划", "success");
      await loadWorkspaceProject();
    } else {
      toast("当前没有需要同步的定稿变化", "info");
      await loadStoryEvolutionPanel();
    }
  }).catch(e => toast(e.message, "error"));
}

async function loadRelationshipGraphPanel() {
  const el = $("rel-graph-content");
  const meta = $("rel-graph-meta");
  if (!AppState.currentTaskId || !el) return;
  try {
    const d = await api(`/api/character-state/${AppState.currentTaskId}`);
    const chars = d.characters || {};
    const charNames = Object.keys(chars);
    const dead = d.dead_characters || [];
    const rels = d.relationships || [];
    meta.textContent = rels.length ? `${rels.length} 关系` : `${charNames.length} 角色`;
    if (!charNames.length && !rels.length) {
      el.innerHTML = '<div class="empty-state">生成章节后自动构建角色关系网络</div>';
      return;
    }
    const relLabels = { friend: "友好", enemy: "敌对", neutral: "中立", ally: "同盟", rival: "对手", mentor: "师长", disciple: "弟子" };
    const stateLabels = { initial: "初始", growing: "成长", strong: "强盛", peak: "巅峰", declining: "衰落", recovering: "恢复" };
    let html = '';
    if (rels.length) {
      html += '<div style="font-size:var(--text-xs);color:var(--color-primary);font-weight:var(--weight-medium);margin-bottom:4px;">角色关系</div>';
      html += rels.slice(0, 10).map(r => {
        const label = relLabels[r.type] || r.type;
        return `<div class="catalog-item"><div class="info">
          <div class="title">${escapeHtml(r.character1)} → ${escapeHtml(r.character2)}</div>
          <div class="meta">${escapeHtml(label)}（强度 ${r.strength || 0}）</div>
        </div></div>`;
      }).join('');
    }
    if (charNames.length) {
      html += '<div style="font-size:var(--text-xs);color:var(--text-2);font-weight:var(--weight-medium);margin:6px 0 4px;">角色状态</div>';
      html += charNames.map(name => {
        const c = chars[name];
        const stateLabel = stateLabels[c.current_state] || c.current_state;
        const deadTag = dead.includes(name) ? ' <span style="color:var(--danger);">已死亡</span>' : '';
        return `<div class="catalog-item"><div class="info">
          <div class="title">${escapeHtml(name)} · ${escapeHtml(stateLabel)}${deadTag}</div>
          <div class="meta">战力 ${c.power_level || 0}/${c.max_power_level || 100} · 最近出场第${c.last_updated_chapter || 0}章</div>
        </div></div>`;
      }).join('');
    }
    el.innerHTML = html;
  } catch (e) {
    meta.textContent = "不可用";
    el.innerHTML = '<div class="empty-state">暂无角色关系数据</div>';
  }
}

async function loadStyleFingerprintPanel() {
  const el = $("style-fp-content");
  const meta = $("style-fp-meta");
  if (!AppState.currentTaskId || !el) return;
  try {
    const d = await api(`/api/style-fingerprint/${AppState.currentTaskId}`);
    const fp = d.style_fingerprint;
    if (!fp || !Object.keys(fp).length) {
      meta.textContent = "未学习";
      el.innerHTML = '<div class="empty-state">点击"学习风格样本"上传参考文本，系统将提取风格指纹</div>';
      return;
    }
    meta.textContent = "已学习";
    let html = '';
    // Format A: from StyleLearner.learn_style
    if (fp.sentence_length_dist || fp.dialogue_density != null) {
      const fmtArr = v => Array.isArray(v) ? v.map(n => (Number(n) * 100).toFixed(0) + '%').join(' / ') : String(v);
      const fmtPct = v => (Number(v) * 100).toFixed(1) + '%';
      const dims = [
        { key: "sentence_length_dist", label: "句长分布", format: fmtArr },
        { key: "dialogue_density", label: "对话密度", format: fmtPct },
        { key: "rhetoric_frequency", label: "修辞频率", format: fmtPct },
        { key: "emotion_tone", label: "情感色调", format: fmtArr },
        { key: "rhythm_pattern", label: "节奏模式", format: fmtArr },
      ];
      html = dims.map(dim => {
        const val = fp[dim.key];
        if (val == null) return '';
        return `<div class="catalog-item"><div class="info">
          <div class="title">${escapeHtml(dim.label)}</div>
          <div class="meta">${escapeHtml(dim.format(val))}</div>
        </div></div>`;
      }).filter(Boolean).join('');
    }
    // Format B: from analyze_style_fingerprint
    if (!html && (fp.avg_sentence_length != null || fp.style_hint)) {
      const items = [];
      if (fp.avg_sentence_length != null) items.push(["平均句长", `${fp.avg_sentence_length}字`]);
      if (fp.short_sentence_ratio != null) items.push(["短句占比", `${(fp.short_sentence_ratio * 100).toFixed(0)}%`]);
      if (fp.paragraph_count != null) items.push(["段落数", `${fp.paragraph_count}`]);
      if (fp.dialogue_mark_density != null) items.push(["对话标记密度", `${(fp.dialogue_mark_density * 100).toFixed(2)}%`]);
      if (fp.rhythm_keywords && fp.rhythm_keywords.length) items.push(["节奏关键词", fp.rhythm_keywords.join('、')]);
      if (fp.style_hint) items.push(["风格提示", fp.style_hint]);
      html = items.map(([label, val]) => `<div class="catalog-item"><div class="info">
        <div class="title">${escapeHtml(label)}</div>
        <div class="meta">${escapeHtml(val)}</div>
      </div></div>`).join('');
    }
    el.innerHTML = html || '<div class="empty-state">风格指纹为空</div>';
  } catch (e) {
    meta.textContent = "不可用";
    el.innerHTML = '<div class="empty-state">暂无风格指纹数据</div>';
  }
}

function openStyleLearnDialog() {
  const dlg = $("style-learn-dialog");
  if (dlg && dlg.showModal) dlg.showModal();
}

async function submitStyleLearn() {
  if (!AppState.currentTaskId) return;
  const input = $("style-learn-input");
  const text = (input ? input.value : '').trim();
  if (!text || text.length < 500) {
    toast("请粘贴至少500字的参考文本", "error");
    return;
  }
  const btn = $("style-learn-submit");
  await ButtonHelper.withLoading(btn, async () => {
    await api("/api/style/learn", {
      method: "POST",
      body: JSON.stringify({ task_id: AppState.currentTaskId, texts: [text] }),
    });
    toast("风格指纹学习完成", "success");
    const dlg = $("style-learn-dialog");
    if (dlg && dlg.close) dlg.close();
    await loadStyleFingerprintPanel();
  }).catch(e => toast(e.message, "error"));
}

async function loadModelRouterPanel() {
  const el = $("model-router-content");
  const meta = $("model-router-meta");
  if (!AppState.currentTaskId || !el) return;
  try {
    const d = await api("/api/model-router/stats");
    const recs = d.recommendations || {};
    const stats = d.stats || {};
    const recEntries = Object.values(recs);
    const modelCount = Object.keys(stats).length;
    meta.textContent = modelCount ? `${modelCount} 模型` : "--";
    if (!recEntries.length && !modelCount) {
      el.innerHTML = '<div class="empty-state">暂无模型调用统计</div>';
      return;
    }
    const taskLabels = { plan: "规划", write: "写作", rewrite: "风格重写", check: "一致性检查", world: "世界观", character: "角色", plot: "情节" };
    let html = '';
    if (recEntries.length) {
      html += recEntries.map(r => {
        const label = taskLabels[r.task_type] || r.task_type;
        return `<div class="catalog-item"><div class="info">
          <div class="title">${escapeHtml(label)}</div>
          <div class="meta">推荐：${escapeHtml(r.recommended_model || '--')}（置信 ${r.confidence ?? '--'}）</div>
        </div></div>`;
      }).join('');
    }
    let totalCalls = 0;
    for (const model of Object.keys(stats)) {
      for (const task of Object.keys(stats[model])) {
        totalCalls += stats[model][task].total_calls || 0;
      }
    }
    if (totalCalls > 0) meta.textContent = `${modelCount} 模型 · ${totalCalls} 次调用`;
    el.innerHTML = html || '<div class="empty-state">暂无模型调用统计</div>';
  } catch (e) {
    meta.textContent = "不可用";
    el.innerHTML = '<div class="empty-state">暂无模型调用统计</div>';
  }
}
