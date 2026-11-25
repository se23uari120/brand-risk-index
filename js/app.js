// =============================================================
// app.js — bootstraps the dashboard: detects the live server,
// tab routing (with deep links like #company/TMPV), lazy rendering,
// theme switching and redrawing when new data arrives.
// =============================================================

let currentView = 'overview';
let started = false;
const VIEWS = ['overview', 'companies', 'search', 'compare', 'mcdm', 'validation', 'method'];
const rendered = {};
const RENDER = {
  overview: renderOverview, companies: renderCompanies, search: renderSearch, compare: renderCompare,
  mcdm: renderMcdm, validation: renderValidation, method: renderMethod,
};

function showView(view, { updateHash = true } = {}) {
  if (!VIEWS.includes(view)) view = 'overview';
  currentView = view;
  VIEWS.forEach(v => {
    $(`#view-${v}`).classList.toggle('active', v === view);
    $(`#tab-${v}`).setAttribute('aria-selected', String(v === view));
  });
  RENDER[view]();          // cheap enough to refresh every time; keeps charts sized correctly
  if (view === 'validation' && canWrite() && !rendered.labels) { rendered.labels = true; loadLabelQueue(); }
  rendered[view] = true;
  if (updateHash) history.replaceState(null, '', `#${view}`);
  window.scrollTo({ top: 0 });
}

function route() {
  const h = decodeURIComponent(location.hash.slice(1));
  if (h.startsWith('company/')) {
    if (!rendered[currentView]) showView(currentView, { updateHash: false });
    openDetail(h.slice(8), { updateHash: false });
  } else if (h.startsWith('m-')) {
    showView('method', { updateHash: false });
    const el = document.getElementById(h);
    if (el) el.scrollIntoView();
  } else {
    if (detailSymbol) closeDetail({ updateHash: false });
    showView(h || 'overview', { updateHash: false });
  }
}

function renderChrome() {
  $('#brand-sub').textContent = `${D.exchange} · ${D.universe}`;
  $('#asof').textContent = `Data as of NSE close, ${fmt.date(D.asOf)}`;
  $('#foot').innerHTML = `Prices: Yahoo Finance (NSE) · News: Google News and Indian business outlets · Method: AHP-weighted TOPSIS over 5 stock &amp; news signals · ` +
    `Generated ${new Date(D.generatedAt).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' })}${sourceNote()}. Not investment advice.`;
}

// Called by live.js when the server has finished a new run.
function applyNewData() {
  if (!started) { start(); return; }
  renderChrome();
  fillSectorOptions();
  RENDER[currentView]();
  if (detailSymbol) {
    if (BY_SYMBOL[detailSymbol]) openDetail(detailSymbol, { updateHash: false });
    else closeDetail();
  }
}

function applyThemeChange() {
  // charts read colours from CSS tokens at draw time → redraw the visible ones
  RENDER[currentView]();
  if (detailSymbol) renderDetailCharts(BY_SYMBOL[detailSymbol], defaultCtx(), 'd');
}

function initTheme() {
  $('#theme-btn').addEventListener('click', () => {
    const dark = getComputedStyle(document.documentElement).colorScheme === 'dark';
    const next = dark ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem('brm-theme', next); } catch (e) { /* storage unavailable: theme just isn't remembered */ }
    applyThemeChange();
  });
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    if (!document.documentElement.dataset.theme) applyThemeChange();
  });
}

function start() {
  if (started) return;          // live.js may already have started it with newer server data
  started = true;
  $('#no-data').hidden = true;
  Chart.defaults.font.family = tok('--font');
  renderChrome();

  $$('.tab').forEach(b => b.addEventListener('click', () => showView(b.dataset.view)));
  // in-page links like href="#companies" or "#method"
  document.addEventListener('click', e => {
    const a = e.target.closest('a[href^="#"]');
    if (!a) return;
    const target = a.getAttribute('href').slice(1);
    if (VIEWS.includes(target)) { e.preventDefault(); if (detailSymbol) closeDetail({ updateHash: false }); showView(target); }
    else if (target.startsWith('company/')) { e.preventDefault(); openDetail(decodeURIComponent(target.slice(8))); }
    else if (target.startsWith('m-') && currentView === 'method') { e.preventDefault(); document.getElementById(target)?.scrollIntoView({ behavior: 'smooth' }); }
  });

  initCompanies();
  initCompare();
  initDetail();
  initSearch();
  initMcdm();
  initValidation();
  window.addEventListener('hashchange', route);
  route();
}

async function boot() {
  initTheme();
  await initLive();
  if (D && D.companies && D.companies.length) { start(); return; }
  $('#no-data').hidden = false;
  $$('.view').forEach(v => v.classList.remove('active'));
  if (SERVER.on) $('#no-data').innerHTML = 'The server is running its first scoring pass (about 2 minutes). This page fills in by itself when it is done.';
}

boot();
