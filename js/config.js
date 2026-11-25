// =============================================
// CONFIG: where a hosted Python server lives.
//
// ''  → no hosted server. The page still uses its own server when one
//       serves it (start.bat, Docker, or the Render URL itself).
// URL → a static copy of the dashboard (GitHub Pages, or index.html opened
//       from disk) keeps loading the stored daily results instantly and uses
//       this server for Company Search and the headline scorer, e.g.
//       window.BRI_API_BASE = 'https://brand-risk-index.onrender.com';
//       (see render.yaml and the README's Hosting section)
// =============================================

window.BRI_API_BASE = window.BRI_API_BASE || '';
window.BRI_USE_REMOTE = false;   // switched on by live.js only when the page has no server of its own

(function () {
  const origFetch = window.fetch.bind(window);
  window.fetch = (url, opts) => {
    const base = window.BRI_USE_REMOTE ? (window.BRI_API_BASE || '').replace(/\/$/, '') : '';
    return origFetch(base && typeof url === 'string' && url.startsWith('/api/') ? base + url : url, opts);
  };
})();
