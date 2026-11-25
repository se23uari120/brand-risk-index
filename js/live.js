// =============================================================
// live.js — finds the Python server. Three ways the page can run:
//
//  1. Served by the server itself (start.bat / Docker / Render URL):
//     loads /api/data, and if the server re-scores (liveRefresh) shows
//     the Live badge and redraws when a run finishes. A read-only
//     public server (READ_ONLY=true) hides the editing tools.
//  2. A static copy with a hosted server set in js/config.js
//     (GitHub Pages + Render): the stored js/data.js loads at once, and
//     the hosted server is only woken up when someone uses Search or
//     the headline scorer (a free server can take ~1 minute to wake).
//  3. A static copy without a server: stored results only.
// =============================================================

const SERVER = { on: false, remote: false, info: null, status: null, timer: null, search: 'off', wake: null };

// The configured server, if it is on another site than this page.
function remoteBase() {
  const base = (window.BRI_API_BASE || '').replace(/\/$/, '');
  if (!base) return '';
  try { return new URL(base, location.href).origin === location.origin ? '' : base; } catch (e) { return ''; }
}

// Editing tools (watchlist, labels, re-runs) need a server we are served by that allows changes.
function canWrite() { return SERVER.on && !!SERVER.info && !SERVER.info.readOnly; }
// Search and the headline scorer work with any server, including a hosted one.
function searchOffered() { return SERVER.on || SERVER.remote; }

async function fetchHealth(timeoutMs) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const r = await fetch('/api/health', { cache: 'no-store', signal: ctrl.signal });
    if (!r.ok) return null;
    const j = await r.json();
    return j && j.server ? j : null;
  } catch (e) { return null; } finally { clearTimeout(t); }
}

// Wake the hosted server (mode 2). Resolves to true when it answers.
function wakeSearchServer() {
  if (SERVER.on) return Promise.resolve(true);
  if (!SERVER.remote) return Promise.resolve(false);
  if (SERVER.search === 'ready') return Promise.resolve(true);
  if (SERVER.wake) return SERVER.wake;
  SERVER.search = 'waking';
  if (typeof renderSearchStatus === 'function') renderSearchStatus();
  SERVER.wake = (async () => {
    // a sleeping free instance needs about a minute; allow two tries
    let info = null;
    for (let i = 0; i < 2 && !info; i++) info = await fetchHealth(75000);
    SERVER.info = info;
    SERVER.search = info ? 'ready' : 'down';
    SERVER.wake = null;
    if (typeof renderSearchStatus === 'function') renderSearchStatus();
    return !!info;
  })();
  return SERVER.wake;
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
  if (!SERVER.on || !SERVER.info || !SERVER.info.liveRefresh) { el.hidden = true; return; }
  el.hidden = false;
  const running = s && s.running;
  el.innerHTML = `<span class="live-dot${running ? ' busy' : ''}"></span>${running ? 'Updating…' : 'Live'}`;
  el.title = s ? `Server mode · re-scored every ${Math.round(s.refreshMinutes)} min` +
    (s.lastRun ? ` · last run ${new Date(s.lastRun).toLocaleTimeString('en-IN', { timeStyle: 'short' })}` : '') +
    (s.lastError ? ` · last error: ${s.lastError}` : '') + (canWrite() ? ' · click to refresh now' : '') : 'Server mode';
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
  // mode 1: did a server of our own serve this page? (never on a static host)
  const staticHost = location.protocol === 'file:' || location.hostname.endsWith('github.io');
  SERVER.info = staticHost ? null : await fetchHealth(2500);
  SERVER.on = !!SERVER.info;
  if (!SERVER.on) {
    // mode 2: stored data now, the hosted server only on demand
    SERVER.remote = !!remoteBase();
    window.BRI_USE_REMOTE = SERVER.remote;
    return;
  }
  await loadServerData();
  if (!SERVER.info.liveRefresh) return; // e.g. the public read-only server: new data arrives by redeploy
  $('#live-badge').addEventListener('click', async () => {
    if (!canWrite()) return;
    try { await getJSON('/api/live/refresh', { method: 'POST' }); } catch (e) { /* ignore */ }
    pollLive();
  });
  pollLive();
  SERVER.timer = setInterval(pollLive, 30000);
}
