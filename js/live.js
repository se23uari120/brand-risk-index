// =============================================================
// live.js — detects the Python server (start.bat / Docker / a hosted
// copy set in js/config.js). With a server the dashboard:
//   • loads the newest results from /api/data instead of js/data.js
//   • polls /api/live/status and redraws when a new run finishes
//   • enables Company Search, the watchlist and the server parts of
//     the Validation tab
// Without one (GitHub Pages, or index.html opened directly) it runs on
// the stored js/data.js.
// =============================================================

const SERVER = { on: false, status: null, timer: null };

async function detectServer() {
  // no server behind a plain static copy (opened from disk or on GitHub Pages) unless one is configured
  if (!window.BRI_API_BASE && (location.protocol === 'file:' || location.hostname.endsWith('github.io'))) return false;
  try {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), 2500);
    const r = await fetch('/api/health', { cache: 'no-store', signal: ctrl.signal });
    clearTimeout(t);
    if (!r.ok) return false;
    const j = await r.json();
    return !!(j && j.server);
  } catch (e) { return false; }
}

async function loadServerData() {
  try {
    const payload = await getJSON('/api/data', { cache: 'no-store' });
    if (payload && payload.companies && payload.companies.length) { setData(payload); return true; }
  } catch (e) { /* first run may still be in progress */ }
  return false;
}

function renderLiveBadge(s) {
  const el = $('#live-badge');
  if (!SERVER.on) { el.hidden = true; return; }
  el.hidden = false;
  const running = s && s.running;
  el.innerHTML = `<span class="live-dot${running ? ' busy' : ''}"></span>${running ? 'Updating…' : 'Live'}`;
  el.title = s ? `Server mode · re-scored every ${Math.round(s.refreshMinutes)} min` +
    (s.lastRun ? ` · last run ${new Date(s.lastRun).toLocaleTimeString('en-IN', { timeStyle: 'short' })}` : '') +
    (s.lastError ? ` · last error: ${s.lastError}` : '') + ' · click to refresh now' : 'Server mode';
}

async function pollLive() {
  const s = await getJSON('/api/live/status', { cache: 'no-store' }).catch(() => null);
  if (!s) return;
  SERVER.status = s;
  renderLiveBadge(s);
  if (!s.running && s.generatedAt && (!D || s.generatedAt !== D.generatedAt)) {
    if (await loadServerData()) applyNewData();
  }
}

async function initLive() {
  SERVER.on = await detectServer();
  if (!SERVER.on) return;
  await loadServerData();
  $('#live-badge').addEventListener('click', async () => {
    try { await getJSON('/api/live/refresh', { method: 'POST' }); } catch (e) { /* ignore */ }
    pollLive();
  });
  pollLive();
  SERVER.timer = setInterval(pollLive, 30000);
}
