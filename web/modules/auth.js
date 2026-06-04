/* === Auth Module === */
function saveAuth(token, user) {
  AppState.authToken = token; AppState.currentUser = user;
  localStorage.setItem("auth_token", token);
  localStorage.setItem("current_user", JSON.stringify(user));
  updateAuthUI();
}

function clearAuth() {
  AppState.authToken = null; AppState.currentUser = null;
  localStorage.removeItem("auth_token");
  localStorage.removeItem("current_user");
  updateAuthUI();
  navigate("#dashboard");
}

function updateAuthUI() {
  if (AppState.currentUser) {
    $("sidebar-username").textContent = AppState.currentUser.nickname || AppState.currentUser.username;
    $("sidebar-balance").textContent = `¥${(AppState.currentUser.balance || 0).toFixed(1)}`;
    $("sidebar-login-btn").style.display = "none";
    const adminNav = $("nav-admin");
    adminNav.style.display = AppState.currentUser.role === "admin" ? "flex" : "none";
  } else {
    $("sidebar-username").textContent = "未登录";
    $("sidebar-balance").textContent = "¥0.0";
    $("sidebar-login-btn").style.display = "flex";
    $("nav-admin").style.display = "none";
  }
}

function showLoginDialog() {
  showDialog(`
    <h3>登录</h3>
    <div class="form-group"><label>用户名</label><input id="dlg-user" type="text" autofocus /></div>
    <div class="form-group"><label>密码</label><input id="dlg-pass" type="password" /></div>
    <div id="dlg-error" class="error-msg"></div>
    <div class="dialog-actions">
      <button class="btn-secondary" onclick="hideDialog()">取消</button>
      <button onclick="doLogin()" class="btn-primary">登录</button>
    </div>
    <p style="margin-top:12px;font-size:var(--text-sm);color:var(--muted);text-align:center;">
      没有账号？<a href="#" onclick="hideDialog();showRegisterDialog();" style="color:var(--color-primary-light);">注册</a>
    </p>
  `);
}

async function doLogin() {
  const btn = document.querySelector('.dialog-actions .btn-primary');
  await ButtonHelper.withLoading(btn, async () => {
    const u = $("dlg-user").value.trim(), p = $("dlg-pass").value;
    const d = await api("/api/auth/login", { method: "POST", body: JSON.stringify({ username: u, password: p }) });
    saveAuth(d.token, d.user);
    hideDialog(); toast("登录成功", "success");
    navigate(location.hash || "#dashboard");
  }).catch(e => { $("dlg-error").textContent = e.message; });
}

function showRegisterDialog() {
  showDialog(`
    <h3>注册</h3>
    <div class="form-group"><label>用户名</label><input id="dlg-reg-user" type="text" autofocus /></div>
    <div class="form-group"><label>密码</label><input id="dlg-reg-pass" type="password" /></div>
    <div class="form-group"><label>邮箱</label><input id="dlg-reg-email" type="email" /></div>
    <div class="form-group"><label>昵称</label><input id="dlg-reg-nick" type="text" /></div>
    <div id="dlg-reg-error" class="error-msg"></div>
    <div class="dialog-actions">
      <button class="btn-secondary" onclick="hideDialog()">取消</button>
      <button onclick="doRegister()" class="btn-primary">注册</button>
    </div>
  `);
}

async function doRegister() {
  const btn = document.querySelector('.dialog-actions .btn-primary');
  await ButtonHelper.withLoading(btn, async () => {
    const d = await api("/api/auth/register", {
      method: "POST",
      body: JSON.stringify({
        username: $("dlg-reg-user").value.trim(),
        password: $("dlg-reg-pass").value,
        email: $("dlg-reg-email").value.trim(),
        nickname: $("dlg-reg-nick").value.trim(),
      }),
    });
    saveAuth(d.token, d.user);
    hideDialog(); toast("注册成功", "success");
  }).catch(e => { $("dlg-reg-error").textContent = e.message; });
}
