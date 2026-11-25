// =============================================================
// search.js — Company Search: any NSE-listed company, now or as of
// a past day, scored by the server exactly like the watchlist
// (GET /api/search). Works with the page's own server (start.bat)
// or a hosted one set in js/config.js (woken up on first use); on a
// static copy without either, the tab explains how to enable it.
// =============================================================

const RECENT_KEY = 'brm-recent-searches';
let searchTimer = null, searchSeq = 0;

function recentSearches() {
  try { return JSON.parse(localStorage.getItem(RECENT_KEY) || '[]'); } catch (e) { return []; }
}
function pushRecent(name) {
  try {
    const list = [name, ...recentSearches().filter(x => x.toLowerCase() !== name.toLowerCase())].slice(0, 6);
    localStorage.setItem(RECENT_KEY, JSON.stringify(list));
  } catch (e) { /* storage unavailable */ }
}

function renderSearchStatus() {
  const el = $('#search-status');
  if (!SERVER.remote) { el.hidden = true; return; }
  el.hidden = false;
  if (SERVER.search === 'ready') {
    const wordList = SERVER.info && SERVER.info.sentiment !== 'finbert';
    el.innerHTML = 'Connected to the free search server.' + (wordList
      ? ' It scores headlines with the finance word list (FinBERT needs more memory than the free plan has), so a searched score can differ a little from the FinBERT-scored dashboard.'
      : '');
  } else if (SERVER.search === 'down') {
    el.innerHTML = 'The search server did not answer. <button type="button" class="btn small" id="search-retry">Try again</button>';
  } else {
    el.innerHTML = '<span class="live-dot busy"></span> Starting the free search server. After a quiet spell this takes about a minute; then searches run normally.';
  }
}

// true once a server can answer: our own, or the hosted one after it wakes up
async function searchServerReady() {
  return SERVER.on || (SERVER.remote && await wakeSearchServer());
}

function renderSearch() {
  const offered = searchOffered();
  $('#search-static').hidden = offered;
  $('#search-live').hidden = !offered;
  if (!offered) return;
  if (SERVER.remote) wakeSearchServer();       // start waking it as soon as the tab is opened
  renderSearchStatus();
  const rec = recentSearches();
  $('#search-recent').innerHTML = rec.length
    ? `Recent: ${rec.map(r => `<button type="button" data-q="${esc(r)}">${esc(r)}</button>`).join('')}`
    : 'Try: <button type="button" data-q="Swiggy">Swiggy</button><button type="button" data-q="Paytm">Paytm</button><button type="button" data-q="Vedanta">Vedanta</button>';
  const max = new Date(); $('#search-date').max = max.toISOString().slice(0, 10);
}

function initSearch() {
  const input = $('#search-input'), list = $('#search-list');
  const close = () => { list.classList.remove('open'); input.setAttribute('aria-expanded', 'false'); };

  input.addEventListener('input', () => {
    clearTimeout(searchTimer);
    const q = input.value.trim();
    if (q.length < 2) { close(); return; }
    const seq = searchSeq;
    searchTimer = setTimeout(async () => {
      try {
        if (!(await searchServerReady()) || input.value.trim() !== q) return;
        const { results } = await getJSON('/api/resolve?q=' + encodeURIComponent(q));
        if (seq !== searchSeq || input.value.trim() !== q) return;    // a search started meanwhile: keep the list closed
        list.innerHTML = results.length ? results.map(r => `
          <li role="option" data-q="${esc(r.symbol)}"><span><strong>${esc(r.name)}</strong> <span class="muted small">NSE: ${esc(r.symbol)}</span></span>
          <span class="small text-2">${esc(r.sector || '')}${r.onWatchlist ? ' · tracked' : ''}</span></li>`).join('')
          : '<li class="muted small" aria-disabled="true">No NSE-listed company found</li>';
        list.classList.add('open'); input.setAttribute('aria-expanded', 'true');
      } catch (e) { close(); }
    }, 250);
  });
  input.addEventListener('blur', () => setTimeout(close, 150));
  input.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); close(); runSearch(input.value); } if (e.key === 'Escape') close(); });
  list.addEventListener('mousedown', e => {
    const li = e.target.closest('li[data-q]');
    if (li) { e.preventDefault(); input.value = li.dataset.q; close(); runSearch(li.dataset.q); }
  });
  $('#search-go').addEventListener('click', () => runSearch(input.value));
  $('#search-recent').addEventListener('click', e => { const b = e.target.closest('button[data-q]'); if (b) { input.value = b.dataset.q; runSearch(b.dataset.q); } });
  $('#search-status').addEventListener('click', e => { if (e.target.closest('#search-retry')) wakeSearchServer(); });
  $('#search-result').addEventListener('click', async e => {
    const b = e.target.closest('#search-add');
    if (!b) return;
    b.disabled = true; b.textContent = 'Adding…';
    try {
      const r = await getJSON('/api/watchlist', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ q: b.dataset.symbol }) });
      b.textContent = r.status === 'exists' ? 'Already tracked' : 'Added — scored in the next refresh (~2 min)';
    } catch (err) { b.disabled = false; b.textContent = 'Add to watchlist'; alert(err.message); }
  });
}

async function runSearch(q) {
  q = (q || '').trim();
  if (!q) return;
  clearTimeout(searchTimer);
  const asOf = $('#search-date').value;
  const out = $('#search-result'), seq = ++searchSeq;
  ['s-trend', 's-price', 's-specific'].forEach(destroyChart);
  if (SERVER.remote && SERVER.search !== 'ready') {
    out.innerHTML = `<div class="card empty">Waiting for the free search server to wake up (about a minute), then scoring <strong>${esc(q)}</strong>…</div>`;
  }
  if (!(await searchServerReady())) {
    if (seq === searchSeq) out.innerHTML = `<div class="card empty">Could not reach the search server. Try again in a minute.</div>`;
    return;
  }
  if (seq !== searchSeq) return;
  out.innerHTML = `<div class="card empty">Scoring <strong>${esc(q)}</strong>${asOf ? ` as of ${fmt.date(asOf)}` : ''} — downloading prices and headlines (${SERVER.remote ? 'up to a minute on the free server' : 'about 10–30 seconds'})…</div>`;
  try {
    const res = await getJSON(`/api/search?q=${encodeURIComponent(q)}${asOf ? `&as_of=${asOf}` : ''}`);
    if (seq !== searchSeq) return;
    pushRecent(res.company.name);
    const c = res.company;
    out.innerHTML = `
      <div class="card">
        <div class="card-head" style="margin-bottom:4px">
          <div><h2 style="font-size:19px">${esc(c.name)}</h2>
            <div class="co-sub">NSE: ${esc(c.symbol)} · ${esc(c.sector)}${c.legalName ? ` · ${esc(c.legalName)}` : ''} · ${fmt.inr(c.stock.close)}</div></div>
          ${res.onWatchlist ? '<span class="tag">On the watchlist</span>'
            : canWrite() ? `<button class="btn small" id="search-add" type="button" data-symbol="${esc(c.symbol)}">+ Add to watchlist</button>` : ''}
        </div>
        <p class="small muted">${res.live ? `Live assessment as of the latest NSE close (${fmt.date(c.asOf)}) and headlines up to now.`
          : `Assessment as of ${fmt.date(c.asOf)}, using only prices and headlines available then.`}
          Scored exactly like the monitored companies, so the numbers are comparable.</p>
      </div>
      ${detailHtml(c, res.context, 's')}`;
    renderDetailCharts(c, res.context, 's');
    renderSearch();
  } catch (err) {
    if (seq !== searchSeq) return;
    out.innerHTML = `<div class="card empty">Could not score <strong>${esc(q)}</strong>: ${esc(err.message)}</div>`;
  }
}
