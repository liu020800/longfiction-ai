const ToastSystem = {
  MAX_TOASTS: 5,
  DURATIONS: { success: 3000, info: 4000, warning: 6000, error: 0 },
  ICONS: {
    success: Icons.svg('check', 'toast-icon', 18),
    error: Icons.svg('x', 'toast-icon', 18),
    warning: Icons.svg('alertTriangle', 'toast-icon', 18),
    info: Icons.svg('info', 'toast-icon', 18)
  },

  show(msg, type = 'info') {
    const container = document.getElementById('toast-container');
    while (container.children.length >= this.MAX_TOASTS) {
      container.firstChild.remove();
    }

    const el = document.createElement('div');
    el.className = `toast ${type}`;
    const icon = this.ICONS[type] || this.ICONS.info;
    el.innerHTML = `${icon}<span class="toast-msg">${msg}</span><span class="toast-close">&times;</span>`;

    el.querySelector('.toast-close').onclick = () => this._remove(el);
    el.onclick = (e) => { if (!e.target.classList.contains('toast-close')) this._remove(el); };

    container.appendChild(el);

    const duration = this.DURATIONS[type] ?? 4000;
    if (duration > 0) {
      setTimeout(() => this._remove(el), duration);
    }
  },

  _remove(el) {
    if (!el.parentNode) return;
    el.classList.add('toast-exit');
    setTimeout(() => el.remove(), 200);
  },

  success(msg) { this.show(msg, 'success'); },
  error(msg) { this.show(msg, 'error'); },
  warning(msg) { this.show(msg, 'warning'); },
  info(msg) { this.show(msg, 'info'); }
};
