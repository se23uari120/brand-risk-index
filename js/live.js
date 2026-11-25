// =============================================================
// live.js — finds the Python server. Three ways the page can run:
//
//  1. Served by the server itself (start.bat / Docker / Render URL):
//     loads /api/data. A live server (liveRefresh) re-scores hourly; a
//     refresh-on-visit server re-scores when a page opens and the data
//     is stale. Either way the page redraws when a run finishes. A
//     read-only public server (READ_ONLY=true) hides the editing tools.
//  2. A static copy with a hosted server set in js/config.js
//     (GitHub Pages + Render): the stored js/data.js shows at once while
//     the hosted server wakes up (~1 minute on a free plan); then it
//     refreshes on visit and Search works, and newer results replace
//     the stored ones in place.
//  3. A static copy without a server: stored results only.
// =============================================================

const SERVER = { on: false, remote: false, info: null, status: null, timer: null, search: 'off', wake: null, fromServer: false };
const POLL_RUNNING_MS = 8000, POLL_LIVE_MS = 30000, REVISIT_MS = 5 * 60000;

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
function connected() { return SERVER.on || SERVER.search === 'ready'; }
function refreshesOnVisit() { return connected() && !!SERVER.info && !!SERVER.info.refreshOnVisit; }

// Short note for the footer: where the numbers on screen come from.
function sourceNote() {
  if (SERVER.fromServer && SERVER.info && SERVER.info.refreshOnVisit) return ' · refreshed on visit';
  if (SERVER.on) return SERVER.info.liveRefresh ? ' · live server' : ' · server';
  return SERVER.remote ? ' · hosted server' : '';
}

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
function wakeServer() {
  if (SERVER.on) return Promise.resolve(true);
  if (!SERVER.remote) return Promise.resolve(false);
  if (SERVER.search === 'ready') return Promise.resolve(true);
  if (SERVER.wake) return SERVER.wake;
  SERVER.search = 'waking';
  renderLiveBadge(null);
  if (typeof renderSearchStatus === 'function') renderSearchStatus();
  SERVER.wake = (async () => {
    // a sleeping free instance needs about a minute; allow two tries
    let info = null;
    for (let i = 0; i < 2 && !info; i++) info = await fetchHealth(75000);
    SERVER.info = info;
    SERVER.search = info ? 'ready' : 'down';
    SERVER.wake = null;
    if (typeof renderSearchStatus === 'function') renderSearchStatus();
    if (info) afterConnect(); else renderLiveBadge(null);
    return !!info;
  })();
  return SERVER.wake;
}

async function loadServerData() {
  try {
    const payload = await getJSON('/api/data', { cache: 'no-store' });
    if (payload && payload.companies && payload.companies.length) { setData(payload); SERVER.fromServer = true; return true; }
  } catch (e) { /* first run may still be in progress */ }
  return false;
}

function fmtTime(iso) {
  const d = new Date(iso), today = new Date();
  return d.toDateString() === today.toDateString()
    ? d.toLocaleTimeString('en-IN', { timeStyle: 'short' })
    : d.toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' });
}

function renderLiveBadge(s) {
  const el = $('#live-badge');
  const info = SERVER.info;
  const waking = SERVER.remote && SERVER.search === 'waking';
  if (!waking && !(connected() && info && (info.liveRefresh || info.refreshOnVisit))) { el.hidden = true; return; }
  el.hidden = false;
  const running = !!(s && s.running);
  let text, title;
  if (waking) {
    text = 'Checking for updates…';
    title = 'Waking the free server that refreshes the data (about a minute after a quiet spell). The stored results are shown meanwhile.';
  } else if (running) {
    text = 'Updating…';
    title = 'Fetching fresh prices and headlines for every company. This page updates by itself when it is done (several minutes on a free server).';
  } else if (info.refreshOnVisit) {
    text = D && D.generatedAt ? `Updated ${fmtTime(D.generatedAt)}` : 'Up to date';
    title = `Re-scored when someone opens the page and the data is more than ${Math.round(info.staleMinutes)} minutes old.` +
      (s && s.lastError ? ` The last refresh was not used: ${s.lastError}.` : '');
  } else {
    text = 'Live';
    title = s ? `Server mode · re-scored every ${Math.round(s.refreshMinutes)} min` +
      (s.lastRun ? ` · last run ${fmtTime(s.lastRun)}` : '') + (s.lastError ? ` · last error: ${s.lastError}` : '') +
      (canWrite() ? ' · click to refresh now' : '') : 'Server mode';
  }
  el.innerHTML = `<span class="live-dot${running || waking ? ' busy' : ''}"></span>${esc(text)}`;
  el.title = title;
}

function schedule(ms, fn) {
  clearTimeout(SERVER.timer);
  SERVER.timer = ms ? setTimeout(fn, ms) : null;
}

// A status from the server: swap in newer results, redraw the badge, decide when to look again.
async function handleStatus(s) {
  SERVER.status = s;
  const newer = s.generatedAt && (!D || !D.generatedAt || new Date(s.generatedAt) > new Date(D.generatedAt));
  if (newer && await loadServerData()) applyNewData();     // even mid-run: the server's last results may beat ours
  renderLiveBadge(s);
  if (s.running) schedule(POLL_RUNNING_MS, pollLive);
  else if (SERVER.info && SERVER.info.liveRefresh) schedule(POLL_LIVE_MS, pollLive);
  else if (refreshesOnVisit()) schedule(REVISIT_MS, visit);     // keep a long-open page fresh
}

async function pollLive() {
  const s = await getJSON('/api/live/status', { cache: 'no-store' }).catch(() => null);
  if (s) handleStatus(s); else schedule(POLL_LIVE_MS, pollLive);
}

// "A dashboard is open": the server re-scores in the background if its results are stale.
async function visit() {
  if (document.hidden) { schedule(REVISIT_MS, visit); return; }
  const s = await getJSON('/api/live/visit', { method: 'POST' }).catch(() => null);
  if (s) handleStatus(s); else schedule(REVISIT_MS, visit);
}

let connectedOnce = false;
function afterConnect() {
  if (connectedOnce) return;
  connectedOnce = true;
  document.addEventListener('visibilitychange', () => { if (!document.hidden && refreshesOnVisit()) visit(); });
  if (typeof renderChrome === 'function' && started) renderChrome();
  if (refreshesOnVisit()) visit();
  else if (SERVER.info.liveRefresh) pollLive();
  else renderLiveBadge(null);
}

async function initLive() {
  $('#live-badge').addEventListener('click', async () => {
    if (canWrite()) {
      try { await getJSON('/api/live/refresh', { method: 'POST' }); } catch (e) { /* ignore */ }
      pollLive();
    } else if (refreshesOnVisit()) visit();
  });
  // mode 1: did a server of our own serve this page? (never on a static host)
  const staticHost = location.protocol === 'file:' || location.hostname.endsWith('github.io');
  SERVER.info = staticHost ? null : await fetchHealth(2500);
  SERVER.on = !!SERVER.info;
  if (!SERVER.on) {
    // mode 2: stored data now; the hosted server wakes in the background
    SERVER.remote = !!remoteBase();
    window.BRI_USE_REMOTE = SERVER.remote;
    if (SERVER.remote) wakeServer();
    return;
  }
  await loadServerData();
  afterConnect();
}
