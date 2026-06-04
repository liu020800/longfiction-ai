const EmptyState = {
  render(options = {}) {
    const {
      icon = '',
      title = '',
      desc = '',
      action = '',
      actionFn = null
    } = options;

    const iconHtml = icon ? `<div class="empty-state-icon">${icon}</div>` : '';
    const titleHtml = title ? `<div class="empty-state-title">${title}</div>` : '';
    const descHtml = desc ? `<div class="empty-state-desc">${desc}</div>` : '';
    const actionHtml = action ? `<button class="btn-primary btn-sm" style="margin-top:4px;">${action}</button>` : '';

    const el = document.createElement('div');
    el.className = 'empty-state';
    el.innerHTML = `${iconHtml}${titleHtml}${descHtml}${actionHtml}`;

    if (actionFn && action) {
      el.querySelector('button').onclick = actionFn;
    }

    return el;
  },

  projects() {
    return this.render({
      icon: Icons.svg('folder', '', 40),
      title: '还没有创作项目',
      desc: '点击新建项目开始你的创作之旅',
      action: '新建项目',
      actionFn: () => document.getElementById('dashboard-new-project')?.click()
    });
  },

  chapters() {
    return this.render({
      icon: Icons.svg('book', '', 40),
      title: '暂无章节',
      desc: '创建项目并确认设定后显示章节目录'
    });
  },

  versions() {
    return this.render({
      icon: Icons.svg('layers', '', 40),
      title: '暂无版本',
      desc: '生成章节后可查看版本历史'
    });
  },

  foreshadowing() {
    return this.render({
      icon: Icons.svg('sparkles', '', 40),
      title: '暂无伏笔',
      desc: '在创作过程中可以埋设和回收伏笔'
    });
  }
};
