// =============================================
// CONFIG — where the Python API lives.
//
// ''  → same server that serves this page (start.bat, or the Hugging Face Space).
// URL → a static copy of the dashboard (e.g. GitHub Pages) uses that server for
//       live data and Company Search, e.g.
//       window.BRI_API_BASE = 'https://YOUR-NAME-brand-risk-index.hf.space';
// =============================================

window.BRI_API_BASE = window.BRI_API_BASE || '';

(function () {
  const base = (window.BRI_API_BASE || '').replace(/\/$/, '');
  if (!base) return;
  const origFetch = window.fetch.bind(window);
  window.fetch = (url, opts) =>
    origFetch(typeof url === 'string' && url.startsWith('/api/') ? base + url : url, opts);
})();
