/* === API Client === */
async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (AppState.authToken) headers["Authorization"] = `Bearer ${AppState.authToken}`;
  let resp;
  try {
    resp = await fetch(path, { headers, ...options });
  } catch (e) {
    throw new Error("网络异常，请检查连接");
  }
  const data = await resp.json().catch(() => ({}));
  if (resp.status === 401) {
    clearAuth();
    showLoginDialog();
    throw new Error("登录已过期，请重新登录");
  }
  if (!resp.ok) throw new Error(data.detail || `HTTP ${resp.status}`);
  return data;
}
