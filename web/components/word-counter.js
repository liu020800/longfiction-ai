const WordCounter = {
  counters: new WeakMap(),

  bind(textarea, displayEl) {
    if (!textarea || !displayEl) return;

    const update = () => {
      const text = textarea.value || '';
      const chineseChars = (text.match(/[\u4e00-\u9fff]/g) || []).length;
      const totalChars = text.replace(/\s/g, '').length;
      displayEl.textContent = `${chineseChars} 字 / ${totalChars} 字符`;
    };

    textarea.addEventListener('input', update);
    update();

    this.counters.set(textarea, { displayEl, update });
  },

  unbind(textarea) {
    const data = this.counters.get(textarea);
    if (data) {
      textarea.removeEventListener('input', data.update);
      this.counters.delete(textarea);
    }
  },

  count(text) {
    const chinese = (text.match(/[\u4e00-\u9fff]/g) || []).length;
    const total = text.replace(/\s/g, '').length;
    return { chinese, total };
  }
};
