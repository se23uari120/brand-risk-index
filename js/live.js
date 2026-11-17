// =============================================
// LIVE — Pulls live-scored data from the FastAPI backend
// (news RSS → FinBERT → AHP-TOPSIS) and re-renders the
// dashboard. Falls back silently to static js/data.js
// when the page is opened as a plain file.
// =============================================

const LIVE_POLL_MS = 60 * 1000;   // how often the page checks the backend
let liveLastRun = null;

// The API is available when the page is served by the Python server
// (start.bat / Hugging Face Space), or when js/config.js points a static copy
// (e.g. GitHub Pages) at a running server via BRI_API_BASE.
function liveApiAvailable() {
  if (window.BRI_API_BASE) return true;
  if (location.hostname.endsWith('github.io')) return false;   // static GitHub Pages copy
  return location.protocol === 'http:' || location.protocol === 'https:';
}

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, ch => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]
  ));
}

function mapApiCompany(r) {
  return {
    id:        r.id,
    name:      r.name,
    sector:    r.sector,
    risk:      Math.round(Number(r.risk_index) * 10) / 10,
    level:     r.level,
    crisis:    r.dominant_crisis || 'Operational Scrutiny',
    sentiment: Number(r.compound_sentiment) || 0,
    reach:     r.reach_label,
    action:    r.action,
    source:    r.data_source || 'fallback',
    articles:  r.article_count || 0,
    headlines: r.headlines || [],
    sourceCounts: r.source_counts || {},
    criteria:  ['C1_severity', 'C2_reach', 'C3_recoverability', 'C4_criticality'].map(k => Number(r[k])),
    category:  r.dominant_category || null,
    ciLow:     r.ci_low ?? null,
    ciHigh:    r.ci_high ?? null,
    explanation: r.explanation || [],
    contributions: r.contributions || null,
    categories: r.categories || [],
    regulators: r.regulators || {},
    rank:      r.rank || null
  };
}

// ── News-source labelling (Moneycontrol / Google News / RSS) ──
const PROVIDER_LABELS = { moneycontrol: 'Moneycontrol', google_news: 'Google News', rss: 'Direct RSS', sample: 'Benchmark sample' };
const PROVIDER_COLORS = { moneycontrol: '#e3a008', google_news: '#2f81f7', rss: '#8b949e', sample: '#8b949e' };

function providerBadge(p) {
  if (!p) return '';
  const col = PROVIDER_COLORS[p] || '#8b949e';
  return `<span style="font-size:10px;font-weight:600;color:${col};border:1px solid ${col};border-radius:3px;padding:0 4px;margin-right:4px;white-space:nowrap">${escapeHtml(PROVIDER_LABELS[p] || p)}</span>`;
}

function sourceBreakdown(counts) {
  const order = ['moneycontrol', 'google_news', 'rss', 'sample'];
  return order.filter(k => counts && counts[k])
    .map(k => `<span style="color:${PROVIDER_COLORS[k]}">${PROVIDER_LABELS[k]}: ${counts[k]}</span>`)
    .join(' · ');
}

function rebuildSectors() {
  const map = {};
  companies.forEach(c => {
    const s = map[c.sector] || (map[c.sector] = { name: c.sector, low: 0, moderate: 0, critical: 0, sum: 0, n: 0 });
    s[c.level.toLowerCase()]++;
    s.sum += c.risk; s.n++;
  });
  const list = Object.values(map).map(s => ({
    name: s.name, low: s.low, moderate: s.moderate, critical: s.critical,
    avg: Math.round((s.sum / s.n) * 10) / 10
  })).sort((a, b) => b.avg - a.avg);
  sectors.splice(0, sectors.length, ...list);
}

function updateKpis() {
  const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
  const live = companies.filter(c => c.source === 'live');
  set('kpi-entities', companies.length);
  set('kpi-entities-sub', `Across ${new Set(companies.map(c => c.sector)).size} sectors`);
  set('kpi-signals', live.reduce((a, c) => a + (c.articles || 0), 0).toLocaleString());
  set('kpi-signals-sub', `Live articles · ${live.length} companies covered`);
  set('kpi-critical', companies.filter(c => c.level === 'Critical').length);
  const avgEl = document.getElementById('kpi-avg');
  if (avgEl && companies.length) {
    const avg = companies.reduce((a, c) => a + c.risk, 0) / companies.length;
    avgEl.innerHTML = `${avg.toFixed(1)}<span style="font-size:16px;font-weight:400;color:var(--muted)">/100</span>`;
    avgEl.style.color = riskBarColor(avg);
    const mod = companies.filter(c => c.level === 'Moderate').length;
    set('kpi-avg-sub', `${mod} Moderate · ${companies.filter(c => c.level === 'Low').length} Low`);
  }
}

function rerenderAll() {
  updateKpis();
  // Overview & action are idempotent; re-run them directly.
  if (tabInited['overview']) initOverview();
  if (tabInited['action'])   initAction();
  if (tabInited['sources'] && typeof loadSourceMatrix === 'function') loadSourceMatrix();

  // Register: refresh sector options + table without duplicating listeners.
  if (tabInited['register']) {
    const sel = document.getElementById('reg-sector');
    const keep = sel.value;
    [...sel.querySelectorAll('option')].forEach(o => { if (o.value) o.remove(); });
    [...new Set(companies.map(c => c.sector))].sort().forEach(s => {
      const opt = document.createElement('option');
      opt.value = s; opt.textContent = s; sel.appendChild(opt);
    });
    sel.value = keep;
    applyRegFilter();
  }

  if (tabInited['compare']) {
    if (typeof populateCompareSelect === 'function') populateCompareSelect();
    if (typeof renderCompareUI === 'function') renderCompareUI();
  }
}

function setLiveStatusText(status) {
  const el = document.getElementById('live-sync-text');
  if (!el) return;
  if (!status) { el.textContent = 'Static dataset (backend offline)'; return; }
  if (status.running && !status.last_run) { el.textContent = 'Fetching live news…'; return; }
  const when = status.last_run ? new Date(status.last_run).toLocaleString() : '—';
  el.textContent =
    `Last sync: ${when} · ${status.live_companies}/${companies.length} live · ` +
    `${status.total_articles} articles (${status.moneycontrol_articles || 0} Moneycontrol) · ${status.scorer}` +
    (status.running ? ' · refreshing…' : '');
  const footer = document.getElementById('sidebar-count');
  if (footer) footer.textContent = `System Live · ${companies.length} companies`;
}

async function loadLiveData(force = false) {
  if (!liveApiAvailable()) return;
  try {
    const status = await fetch('/api/live/status').then(r => r.json());
    setLiveStatusText(status);
    if (!force && status.last_run === liveLastRun) return;
    // On first load, show the latest stored results even while a run is in progress.

    const res = await fetch('/api/companies').then(r => r.json());
    const mapped = (res.data || []).map(mapApiCompany);
    if (!mapped.length) return;
    companies.splice(0, companies.length, ...mapped);
    rebuildSectors();
    liveLastRun = status.last_run;
    rerenderAll();
    setLiveStatusText(status);
  } catch (e) {
    console.warn('Live API unavailable, using static data.js', e);
    setLiveStatusText(null);
  }
}

async function triggerLiveRefresh() {
  const btn = document.getElementById('live-refresh-btn');
  btn.disabled = true; btn.textContent = 'Refreshing…';
  try {
    await fetch('/api/live/refresh', { method: 'POST' });
    await loadLiveData(true);
  } finally {
    btn.disabled = false; btn.textContent = '↻ Refresh live';
  }
}

// Index meter: band colours, point estimate and 90% confidence range.
function riskMeter(idx, lo, hi) {
  const ci = (lo != null && hi != null)
    ? `<div class="meter-ci" style="left:${lo}%;width:${Math.max(0.8, hi - lo)}%"></div>` : '';
  return `<div class="meter">${ci}<div class="meter-pt" style="left:${idx}%"></div></div>
    <div class="meter-scale"><span>0</span><span style="margin-left:30%">40</span><span style="margin-left:20%">70</span><span>100</span></div>`;
}

// Why-this-score block shown in the company modal for live companies.
function renderModalExplain(c) {
  const box = document.getElementById('modal-headlines');
  if (!box || c.source !== 'live') return '';
  const range = c.ciLow != null ? `90% range ${c.ciLow}–${c.ciHigh}` : '';
  const regs = Object.entries(c.regulators || {}).map(([k, v]) => `${k} ×${v}`).join(', ');
  return `<div style="border:1px solid var(--border);border-radius:6px;padding:10px;margin-bottom:10px">
    <div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:6px">
      <span><b>${escapeHtml(c.category || '—')}</b>${regs ? ` · regulators: ${escapeHtml(regs)}` : ''}</span>
      <span style="color:var(--muted)">${range}</span></div>
    ${riskMeter(c.risk, c.ciLow, c.ciHigh)}
    <ul style="margin:8px 0 0 16px;padding:0;font-size:12px;color:var(--muted);line-height:1.5">
      ${(c.explanation || []).map(e => `<li>${escapeHtml(e)}</li>`).join('')}
    </ul></div>`;
}

// Render live headlines inside the company modal.
function renderModalHeadlines(c) {
  const box = document.getElementById('modal-headlines');
  if (!box) return;
  const hs = c.headlines || [];
  if (!hs.length) {
    box.innerHTML = `<div style="color:var(--muted);font-size:12px">No live headlines (benchmark profile in use).</div>`;
    return;
  }
  box.innerHTML = renderModalExplain(c) + `
    <div style="font-size:11px;color:var(--muted);margin-bottom:6px">
      ${c.source === 'live' ? `${c.articles} live articles (${sourceBreakdown(c.sourceCounts)}) · most negative first` : 'Benchmark sample headlines'}
    </div>` + hs.map(h => {
      const s = Number(h.sentiment) || 0;
      const col = s < -0.05 ? COLORS.critical : s > 0.05 ? COLORS.low : COLORS.tick;
      const title = escapeHtml(h.title);
      const link = h.url ? `<a href="${escapeHtml(h.url)}" target="_blank" rel="noopener" style="color:var(--text)">${title}</a>` : title;
      return `<div style="display:flex;gap:8px;padding:5px 0;border-top:1px solid var(--border, #30363d);font-size:12px">
        <span style="color:${col};font-weight:600;min-width:44px">${s >= 0 ? '+' : ''}${s.toFixed(2)}</span>
        <span style="flex:1">${providerBadge(h.provider)}${link}<span style="color:var(--muted)"> · ${escapeHtml(h.outlet || h.source || '')}${h.category && h.category !== 'General Coverage' ? ` · <span class="chip">${escapeHtml(h.category)}</span>` : ''}</span></span>
      </div>`;
    }).join('');
}

// Wrap openModal so headlines appear alongside the existing detail view.
const _origOpenModal = openModal;
openModal = function (c) {
  _origOpenModal(c);
  renderModalHeadlines(c);
};

document.addEventListener('DOMContentLoaded', () => {
  const btn = document.getElementById('live-refresh-btn');
  if (!liveApiAvailable()) {
    if (btn) btn.style.display = 'none';
    setLiveStatusText(null);
    return;
  }
  btn.addEventListener('click', triggerLiveRefresh);
  fetch('/api/mcdm/ahp').then(r => r.json()).then(a => {
    AHP_W = ['C1_severity', 'C2_reach', 'C3_recoverability', 'C4_criticality'].map(k => a.weights[k]);
  }).catch(() => {});
  loadLiveData(true);
  setInterval(() => loadLiveData(false), LIVE_POLL_MS);
});
