const ButtonHelper = {
  withLoading(btn, asyncFn) {
    if (!btn) return asyncFn();
    const originalText = btn.textContent;
    const originalWidth = btn.offsetWidth;
    btn.classList.add('btn-loading');
    btn.disabled = true;
    btn.style.minWidth = originalWidth + 'px';

    return asyncFn()
      .then((result) => {
        return result;
      })
      .catch((err) => {
        throw err;
      })
      .finally(() => {
        btn.classList.remove('btn-loading');
        btn.disabled = false;
        btn.style.minWidth = '';
        btn.textContent = originalText;
      });
  },

  setLoading(btn, loading, text = '处理中...') {
    if (!btn) return;
    if (loading) {
      btn._origText = btn.textContent;
      btn.classList.add('btn-loading');
      btn.disabled = true;
    } else {
      btn.classList.remove('btn-loading');
      btn.disabled = false;
    }
  }
};
