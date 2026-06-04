const ThemeManager = {
  STORAGE_KEY: 'lf-theme',
  TRANSITION_CLASS: 'theme-transition',

  init() {
    const saved = localStorage.getItem(this.STORAGE_KEY) || 'dark';
    this.apply(saved, false);
  },

  apply(theme, animate = true) {
    if (animate) {
      document.documentElement.classList.add(this.TRANSITION_CLASS);
      setTimeout(() => document.documentElement.classList.remove(this.TRANSITION_CLASS), 350);
    }
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem(this.STORAGE_KEY, theme);
    this.updateToggleIcon(theme);
  },

  toggle() {
    const current = document.documentElement.getAttribute('data-theme') || 'dark';
    const next = current === 'dark' ? 'light' : 'dark';
    this.apply(next);
  },

  current() {
    return document.documentElement.getAttribute('data-theme') || 'dark';
  },

  updateToggleIcon(theme) {
    const btn = document.getElementById('theme-toggle-btn');
    if (btn) {
      const icon = theme === 'dark' ? Icons.svg('sun', 'theme-icon', 18) : Icons.svg('moon', 'theme-icon', 18);
      const label = theme === 'dark' ? '亮色模式' : '暗色模式';
      btn.innerHTML = icon + `<span class="nav-label">${label}</span>`;
    }
  }
};
