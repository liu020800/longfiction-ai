const Sidebar = {
  COLLAPSED_KEY: 'lf-sidebar-collapsed',

  init() {
    const sidebar = document.getElementById('sidebar');
    if (!sidebar) return;

    const saved = localStorage.getItem(this.COLLAPSED_KEY);
    if (saved === 'true' || (window.innerWidth <= 1100 && saved !== 'false')) {
      sidebar.classList.add('collapsed');
    }

    this._updateToggleIcon();
  },

  toggle() {
    const sidebar = document.getElementById('sidebar');
    if (!sidebar) return;
    sidebar.classList.toggle('collapsed');
    const collapsed = sidebar.classList.contains('collapsed');
    localStorage.setItem(this.COLLAPSED_KEY, collapsed);
    this._updateToggleIcon();
  },

  _updateToggleIcon() {
    const sidebar = document.getElementById('sidebar');
    const btn = document.getElementById('sidebar-toggle');
    if (!sidebar || !btn) return;
    const collapsed = sidebar.classList.contains('collapsed');
    const icon = collapsed ? Icons.svg('chevronRight', '', 16) : Icons.svg('chevronLeft', '', 16);
    btn.innerHTML = icon;
  }
};
