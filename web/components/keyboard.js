const Keyboard = {
  handlers: new Map(),

  init() {
    document.addEventListener('keydown', (e) => {
      const isInput = ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName);
      for (const [combo, handler] of this.handlers) {
        const parts = combo.split('+');
        const key = parts[parts.length - 1];
        const needsCtrl = parts.includes('Ctrl');
        const needsShift = parts.includes('Shift');
        const needsAlt = parts.includes('Alt');

        let match = e.key.toLowerCase() === key.toLowerCase();
        if (needsCtrl) match = match && (e.ctrlKey || e.metaKey);
        if (needsShift) match = match && e.shiftKey;
        if (needsAlt) match = match && e.altKey;

        if (isInput && needsCtrl && !needsShift && !needsAlt) {
          match = false;
        }

        if (match) {
          e.preventDefault();
          handler(e);
          break;
        }
      }
    });
  },

  bind(combo, handler) {
    this.handlers.set(combo, handler);
  },

  unbind(combo) {
    this.handlers.delete(combo);
  }
};
