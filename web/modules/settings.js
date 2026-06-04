/* === Settings & Admin Module === */
async function loadSettings() {
  if (!AppState.currentUser) { $("set-username").value = ""; return; }
  try {
    const me = await api("/api/auth/me");
    $("set-username").value = me.username || "";
    $("set-nickname").value = me.nickname || "";
    $("set-email").value = me.email || "";
    $("set-role").value = me.role || "";
    $("set-balance").value = `¥${(me.balance || 0).toFixed(2)}`;
    $("set-recharged").value = `¥${(me.total_recharged || 0).toFixed(2)}`;
    $("set-consumed").value = `¥${(me.total_consumed || 0).toFixed(2)}`;
  } catch (e) { toast(e.message, "error"); }
  loadLlmConfig();
}

let _llmConfigData = null;

async function loadLlmConfig() {
  try {
    const d = await api("/api/llm-config");
    _llmConfigData = d;
    $("llm-api-base").value = d.api_base || "";
    $("llm-api-key").value = "";
    $("llm-key-hint").textContent = d.api_key_set ? `当前: ${d.api_key_preview}` : "未设置";
    const m = d.models || {};
    $("llm-model-default").value = m.default || "";
    $("llm-model-planner").value = m.planner || "";
    $("llm-model-writer").value = m.writer || "";
    $("llm-model-style").value = m.style || "";
    $("llm-model-check").value = m.check || "";
    $("llm-model-embedding").value = m.embedding || "";
    $("llm-use-response-format").checked = !!d.use_response_format;
    $("llm-timeout").value = d.timeout_seconds || 90;
    $("llm-config-badge").textContent = d.api_key_set ? "已配置" : "未配置";
    $("llm-config-badge").className = `llm-badge ${d.api_key_set ? "badge-ok" : "badge-warn"}`;
    const warns = d.warnings || [];
    $("llm-warnings").innerHTML = warns.length
      ? warns.map(w => `<div class="llm-warn-item">⚠ ${escapeHtml(w)}</div>`).join("")
      : "";
    const isAdmin = d.is_admin;
    const inputs = document.querySelectorAll(".llm-config-section input");
    inputs.forEach(el => { el.disabled = !isAdmin; });
    $("llm-save-btn").style.display = isAdmin ? "" : "none";
    $("llm-reset-btn").style.display = isAdmin ? "" : "none";
  } catch (e) {
    $("llm-warnings").innerHTML = `<div class="llm-warn-item">加载模型配置失败: ${escapeHtml(e.message)}</div>`;
  }
}

async function saveLlmConfig() {
  const body = {
    api_base: $("llm-api-base").value.trim(),
    models: {
      default: $("llm-model-default").value.trim(),
      planner: $("llm-model-planner").value.trim(),
      writer: $("llm-model-writer").value.trim(),
      style: $("llm-model-style").value.trim(),
      check: $("llm-model-check").value.trim(),
      embedding: $("llm-model-embedding").value.trim(),
    },
    use_response_format: $("llm-use-response-format").checked,
    timeout_seconds: Number($("llm-timeout").value) || 90,
  };
  const keyVal = $("llm-api-key").value.trim();
  if (keyVal) body.api_key = keyVal;
  try {
    const d = await api("/api/llm-config", { method: "PUT", body: JSON.stringify(body) });
    if (d.env_persisted) {
      toast("模型配置已保存，立即生效且已同步到.env文件", "success");
    } else {
      toast("内存配置已生效，但.env文件同步失败", "warning");
    }
    $("llm-save-status").textContent = d.env_persisted ? "已保存并持久化" : "仅内存生效";
    await loadLlmConfig();
  } catch (e) {
    toast("保存失败: " + e.message, "error");
    $("llm-save-status").textContent = e.message;
  }
}

async function loadAdmin() {
  try {
    const d = await api("/api/admin/users");
    const currentUserId = AppState.currentUser?.id;
    $("admin-users-body").innerHTML = (d.users || []).map(u => `
      <tr>
        <td>${u.id}</td>
        <td>${escapeHtml(u.username)}</td>
        <td>${escapeHtml(u.nickname || "")}</td>
        <td>${escapeHtml(u.email || "")}</td>
        <td>${u.role}</td>
        <td>¥${(u.balance || 0).toFixed(2)}</td>
        <td>${u.is_active ? "✓" : "✗"}</td>
        <td>
          <button class="btn-xs" onclick="toggleAdminUser(${u.id},${!u.is_active})">${u.is_active ? "禁用" : "启用"}</button>
          ${u.id !== currentUserId ? `<button class="btn-xs" style="color:var(--danger);" onclick="deleteAdminUser(${u.id},'${escapeHtml(u.username)}')">删除</button>` : ''}
        </td>
      </tr>
    `).join("");
  } catch (e) { $("admin-users-body").innerHTML = `<tr><td colspan="8" class="empty-state">${e.message}</td></tr>`; }
}

async function toggleAdminUser(uid, active) {
  try {
    await api("/api/admin/user", { method: "PUT", body: JSON.stringify({ user_id: uid, is_active: active }) });
    toast("用户状态已更新", "success");
    loadAdmin();
  } catch (e) { toast(e.message, "error"); }
}

async function deleteAdminUser(uid, username) {
  const confirmed = await DialogSystem.confirm({
    title: '删除用户',
    message: `确定要删除用户「${username}」吗？此操作不可恢复，该用户的所有数据将被清除。`,
    confirmText: '删除',
    type: 'danger',
    dangerous: true
  });
  if (!confirmed) return;
  try {
    await api(`/api/admin/user/${uid}`, { method: "DELETE" });
    toast("用户已删除", "success");
    loadAdmin();
  } catch (e) { toast(e.message, "error"); }
}
