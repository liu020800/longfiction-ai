const DialogSystem = {
  show(html) {
    const overlay = document.getElementById('dialog-overlay');
    const content = document.getElementById('dialog-content');
    content.innerHTML = html;
    overlay.style.display = 'flex';
    overlay.classList.remove('closing');
    overlay.onclick = (e) => { if (e.target === overlay) this.hide(); };
    const box = overlay.querySelector('.dialog-box');
    if (box) {
      box.addEventListener('click', (e) => e.stopPropagation());
    }
    setTimeout(() => {
      const firstInput = overlay.querySelector('input, textarea, select');
      if (firstInput) firstInput.focus();
      else if (box) box.focus();
    }, 50);
  },

  hide() {
    const overlay = document.getElementById('dialog-overlay');
    overlay.classList.add('closing');
    setTimeout(() => {
      overlay.style.display = 'none';
      overlay.classList.remove('closing');
    }, 150);
  },

  async confirm(options = {}) {
    const {
      title = '确认操作',
      message = '确定要执行此操作吗？',
      confirmText = '确认',
      cancelText = '取消',
      type = 'info',
      dangerous = false
    } = options;

    const typeColors = {
      danger: 'var(--color-danger)',
      warning: 'var(--color-warning)',
      info: 'var(--color-primary)'
    };
    const typeIcons = {
      danger: Icons.svg('alertTriangle', 'confirm-icon', 24),
      warning: Icons.svg('alertTriangle', 'confirm-icon', 24),
      info: Icons.svg('info', 'confirm-icon', 24)
    };
    const iconColor = typeColors[type] || typeColors.info;
    const icon = typeIcons[type] || typeIcons.info;

    return new Promise((resolve) => {
      this.show(`
        <div style="display:flex;align-items:flex-start;gap:14px;">
          <div style="color:${iconColor};flex-shrink:0;margin-top:2px;">${icon}</div>
          <div style="flex:1;">
            <h3 style="margin-bottom:8px;">${title}</h3>
            <p style="font-size:var(--text-md);color:var(--text-2);line-height:1.6;">${message}</p>
          </div>
        </div>
        <div class="dialog-actions" style="margin-top:24px;">
          <button class="btn-secondary" id="dlg-cancel">${cancelText}</button>
          <button class="${dangerous ? 'btn-danger' : 'btn-primary'}" id="dlg-confirm">${confirmText}</button>
        </div>
      `);
      document.getElementById('dlg-confirm').onclick = () => { this.hide(); resolve(true); };
      document.getElementById('dlg-cancel').onclick = () => { this.hide(); resolve(false); };
    });
  }
};
