// =============================================
// COMPANY SEARCH — Brand Image Risk assessment for ANY company
// GET /api/search → news (live or past dates) → FinBERT →
// Table III criteria → AHP-TOPSIS index, confidence range,
// dominant issue, explanation, source comparison.
// =============================================

let searchCharts = {};
let lastSearch = null;
const RECENT_KEY = 'bri-recent-searches';

function getRecent() {
  try { return JSON.parse(localStorage.getItem(RECENT_KEY) || '[]'); } catch { return []; }
}
function pushRecent(name) {
  try {
    const list = [name, ...getRecent().filter(n => n.toLowerCase() !== name.toLowerCase())].slice(0, 8);
    localStorage.setItem(RECENT_KEY, JSON.stringify(list));
  } catch { /* storage unavailable */ }
  renderRecent();
}
function renderRecent() {
  const box = document.getElementById('search-recent');
  const list = getRecent();
  if (!list.length) { box.innerHTML = ''; return; }
  box.innerHTML = `<span style="color:var(--muted)">Recent:</span>` + list.map(n =>
    `<a href="#" data-recent="${escapeHtml(n)}" class="chip" style="color:var(--accent);text-decoration:none">${escapeHtml(n)}</a>`
  ).join('');
  box.querySelectorAll('[data-recent]').forEach(a => a.addEventListener('click', e => {
    e.preventDefault();
    document.getElementById('search-company').value = a.dataset.recent;
    runSearch();
  }));
}

let suggestTimer = null;
function onCompanyInput() {
  clearTimeout(suggestTimer);
  const q = document.getElementById('search-company').value.trim();
  const hint = document.getElementById('search-hint');
  if (q.length < 2) { hint.textContent = ''; return; }
  suggestTimer = setTimeout(async () => {
    try {
      const d = await fetch('/api/resolve?q=' + encodeURIComponent(q)).then(r => r.json());
      document.getElementById('search-suggest').innerHTML =
        d.suggestions.map(s => `<option value="${escapeHtml(s.name)}">${escapeHtml(s.sector)}${s.origin === 'monitored' ? ' · monitored' : ''}</option>`).join('');
      hint.innerHTML = d.match
        ? `Recognised as <b style="color:var(--text)">${escapeHtml(d.match.name)}</b> · ${escapeHtml(d.match.sector)}` +
          (d.match.aliases.length ? ` · also matches headlines with ${d.match.aliases.map(escapeHtml).join(', ')}` : '')
        : 'Not in the company directory: news will be matched on the name as typed. Pick a sector for a sector-specific C4.';
    } catch { /* ignore */ }
  }, 250);
}

async function initSearch() {
  const form = document.getElementById('search-form');
  form.addEventListener('submit', e => { e.preventDefault(); runSearch(); });
  renderRecent();

  const hours = document.getElementById('search-hours');
  hours.addEventListener('change', () => {
    document.getElementById('search-dates').style.display = hours.value === 'custom' ? 'inline-flex' : 'none';
  });
  const today = new Date().toISOString().slice(0, 10);
  document.getElementById('search-to').max = today;
  document.getElementById('search-from').max = today;

  if (!liveApiAvailable()) {
    document.getElementById('search-result').innerHTML =
      `<div class="card" style="padding:24px;color:var(--muted)">Company search needs the backend. Start it with <code>start.bat</code> and open http://localhost:8000.</div>`;
    document.getElementById('search-btn').disabled = true;
    return;
  }
  document.getElementById('search-company').addEventListener('input', onCompanyInput);
  try {
    const res = await fetch('/api/sector-list').then(r => r.json());
    const sel = document.getElementById('search-sector');
    res.sectors.sort((a, b) => a.name.localeCompare(b.name)).forEach(s => {
      const o = document.createElement('option');
      o.value = s.name; o.textContent = `${s.name} (×${s.sensitivity.toFixed(2)})`; sel.appendChild(o);
    });
  } catch (e) { /* sectors optional */ }
}

async function runSearch() {
  const name = document.getElementById('search-company').value.trim();
  if (name.length < 2) return;
  const sector = document.getElementById('search-sector').value;
  const hours  = document.getElementById('search-hours').value;
  const terms  = document.getElementById('search-terms').value.trim();
  const btn = document.getElementById('search-btn');
  const out = document.getElementById('search-result');

  const qs = new URLSearchParams({ company: name });
  if (hours === 'custom') {
    const f = document.getElementById('search-from').value, t = document.getElementById('search-to').value;
    if (!f || !t) { out.innerHTML = `<div class="card" style="padding:20px;color:var(--critical)">Pick both a start and an end date.</div>`; return; }
    qs.set('date_from', f); qs.set('date_to', t);
  } else {
    qs.set('hours', hours);
  }
  if (sector) qs.set('sector', sector);
  if (terms)  qs.set('terms', terms);

  btn.disabled = true; btn.textContent = 'Analysing…';
  out.innerHTML = `<div class="card" style="padding:28px;text-align:center;color:var(--muted);font-size:13px">
    Fetching news for <strong style="color:var(--text)">${escapeHtml(name)}</strong>, scoring each headline with FinBERT and computing the index…</div>`;

  try {
    const r = await fetch('/api/search?' + qs.toString());
    if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
    const data = await r.json();
    lastSearch = { ...data, _terms: terms, _sector: sector };
    pushRecent(data.name || name);
    renderSearchResult(data);
  } catch (e) {
    out.innerHTML = `<div class="card" style="padding:24px;color:var(--critical)">Search failed: ${escapeHtml(e.message)}</div>`;
  } finally {
    btn.disabled = false; btn.textContent = 'Analyse';
  }
}

function statBox(label, value, sub, color) {
  return `<div class="card" style="padding:14px">
    <div class="stat-label">${label}</div>
    <div class="stat-value" style="margin-top:6px;font-size:22px;${color ? `color:${color}` : ''}">${value}</div>
    ${sub ? `<div class="stat-delta" style="line-height:1.4;color:var(--muted)">${sub}</div>` : ''}
  </div>`;
}

function periodText(d) {
  return d.period && d.period.from ? `${d.period.from} → ${d.period.to}` : `last ${d.lookback_hours}h`;
}

function fmtS(x) { return (x >= 0 ? '+' : '') + Number(x).toFixed(2); }

function monitoredAverageCriteria() {
  const live = companies.filter(c => c.source === 'live');
  const set = live.length ? live : companies;
  if (!set.length) return null;
  const sums = [0, 0, 0, 0];
  set.forEach(c => { const s = getCriteriaScores(c); [s.c1, s.c2, s.c3, s.c4].forEach((v, i) => { sums[i] += v; }); });
  return sums.map(v => +(v / set.length).toFixed(1));
}

function renderSearchResult(d) {
  const out = document.getElementById('search-result');
  Object.values(searchCharts).forEach(c => c.destroy());
  searchCharts = {};

  if (!d.found) {
    out.innerHTML = `<div class="card" style="padding:24px;color:var(--muted)">
      ${escapeHtml(d.message)} Try a longer window, the company's full or short name, or add aliases.</div>`;
    return;
  }

  const lc = d.label_counts || {};
  const sentColor = d.compound_sentiment < -0.05 ? COLORS.critical : d.compound_sentiment > 0.05 ? COLORS.low : COLORS.tick;
  const watchBtn = d.data_source !== 'live' ? '' : d.on_watchlist
    ? `<span class="chip">On watchlist (${escapeHtml(d.watchlist_id)})</span>`
    : `<button id="watch-btn" class="btn-ghost" style="border-color:var(--accent);color:var(--accent);font-weight:600">+ Add to watchlist</button>`;
  const resolved = d.resolved
    ? `matched <b>${escapeHtml(d.resolved.name)}</b>${d.resolved.origin === 'monitored' ? ' (monitored)' : ''}`
    : 'name as typed';
  const regs = Object.entries(d.regulators || {});
  const contrib = d.contributions || {};
  const cKeys = ['C1_severity', 'C2_reach', 'C3_recoverability', 'C4_criticality'];
  const crit = cKeys.map(k => d[k]);
  const levelCol = riskBarColor(d.risk_index);

  out.innerHTML = `
    <div class="card" style="padding:16px;margin-bottom:16px;display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap">
      <div>
        <div style="font-size:20px;font-weight:700">${escapeHtml(d.name)}
          ${d.data_source === 'historical' ? '<span class="chip" style="vertical-align:middle">past period</span>' : ''}</div>
        <div style="font-size:12px;color:var(--muted);margin-top:2px">
          ${escapeHtml(d.sector)} (C4 ×${Number(d.sector_multiplier).toFixed(2)}) · ${resolved} · ${d.article_count} headlines · ${periodText(d)} ·
          ${escapeHtml(d.scorer)} · ${new Date(d.timestamp).toLocaleString()}
        </div>
        <div style="font-size:12px;margin-top:4px">Sources: ${sourceBreakdown(d.source_counts) || '—'} · ${(d.sources || []).length} outlets</div>
      </div>
      ${watchBtn}
    </div>

    <div class="card" style="padding:18px;margin-bottom:16px">
      <div style="display:flex;gap:24px;flex-wrap:wrap;align-items:center">
        <div style="min-width:170px">
          <div class="stat-label">Brand Image Risk Index</div>
          <div style="font-size:44px;font-weight:800;color:${levelCol};line-height:1.1">${d.risk_index.toFixed(1)}<span style="font-size:16px;font-weight:400;color:var(--muted)">/100</span></div>
          <div style="margin-top:4px"><span class="badge ${levelBadgeClass(d.level)}">${d.level}</span>
            <span style="font-size:11px;color:var(--muted);margin-left:6px">90% range ${d.ci_low}–${d.ci_high}</span></div>
        </div>
        <div style="flex:1;min-width:260px">
          ${riskMeter(d.risk_index, d.ci_low, d.ci_high)}
          <div style="margin-top:12px;font-size:11px;color:var(--muted)">PRESCRIBED ACTION (report Table V)</div>
          <div style="font-size:14px;font-weight:600;color:${levelCol};margin-top:2px">${escapeHtml(d.action)}</div>
          ${d.ci_levels && d.ci_levels.length > 1 ? `<div style="font-size:11px;color:var(--moderate);margin-top:4px">The range crosses a band boundary (${d.ci_levels.join(' / ')}): treat the band as provisional.</div>` : ''}
        </div>
        <div style="min-width:150px;font-size:12px">
          <div class="stat-label">Versus monitored companies</div>
          <div style="font-size:22px;font-weight:700;margin-top:4px">#${d.rank} <span style="font-size:13px;font-weight:400;color:var(--muted)">of ${d.ranked_among}</span></div>
          <div style="color:var(--muted)">monitored average ${d.peer_avg ?? '—'}</div>
        </div>
      </div>
    </div>

    <div class="grid-4" style="margin-bottom:16px">
      ${statBox('Dominant issue', escapeHtml(d.dominant_category), escapeHtml(d.dominant_crisis), d.dominant_category.startsWith('No ') ? COLORS.low : null)}
      ${statBox('FinBERT sentiment', fmtS(d.compound_sentiment),
        `${lc.negative || 0} negative · ${lc.neutral || 0} neutral · ${lc.positive || 0} positive<br>negative intensity s = ${d.negative_effective_sentiment.toFixed(2)}`, sentColor)}
      ${statBox('Reach of negative news', escapeHtml(d.reach_label),
        `${d.negative_volume} recency-weighted negative headlines across ${d.negative_outlets} outlets`)}
      ${statBox('Regulators in negative news', regs.length ? regs.map(([k]) => escapeHtml(k)).join(', ') : 'None',
        regs.length ? regs.map(([k, v]) => `${escapeHtml(k)} in ${v} headline${v > 1 ? 's' : ''}`).join(' · ') : 'No RBI / SEBI / USFDA / court mentions', regs.length ? COLORS.moderate : null)}
    </div>

    <div class="grid-auto" style="margin-bottom:16px">
      <div class="card" style="padding:16px">
        <div class="card-title">Why this score</div>
        <ul style="margin:8px 0 12px 16px;padding:0;font-size:12.5px;line-height:1.55">
          ${(d.explanation || []).map(e => `<li>${escapeHtml(e)}</li>`).join('')}
        </ul>
        <table class="data-table">
          <thead><tr><th>Criterion</th><th class="num">Score</th><th class="num">Weight</th><th title="Share of the distance from the lowest-risk baseline">Share</th></tr></thead>
          <tbody>${cKeys.map((k, i) => `<tr><td>${CRITERIA_LABELS[i]}</td><td class="num">${crit[i].toFixed(0)}</td>
            <td class="num">${(d.ahp_weights ? d.ahp_weights[k] : AHP_W[i]).toFixed(3)}</td>
            <td><div style="display:flex;align-items:center;gap:6px"><div class="hbar-track" style="flex:1"><div class="hbar" style="width:${((contrib[k] || 0) * 100).toFixed(0)}%"></div></div>
            <span style="font-size:11px;color:var(--muted);width:32px;text-align:right">${((contrib[k] || 0) * 100).toFixed(0)}%</span></div></td></tr>`).join('')}</tbody>
        </table>
      </div>
      <div class="card" style="padding:16px">
        <div class="card-title">Criteria vs. monitored average</div>
        <div class="chart-wrap" style="height:260px;margin-top:8px"><canvas id="search-radar"></canvas></div>
      </div>
    </div>

    <div class="grid-auto" style="margin-bottom:16px">
      <div class="card" style="padding:16px">
        <div class="card-title">Coverage over time</div>
        <div class="chart-wrap" style="height:230px;margin-top:8px"><canvas id="search-timeline"></canvas></div>
      </div>
      <div class="card" style="padding:16px">
        <div class="card-title">Issue types (crisis-event classifier)</div>
        <table class="data-table" style="margin-top:6px">
          <thead><tr><th>Issue type</th><th class="num">Headlines</th><th class="num">Negative</th><th title="Share of the severity score">Share</th></tr></thead>
          <tbody>${(d.categories || []).map(c => `<tr style="cursor:pointer" data-cat-row="${escapeHtml(c.category)}"><td>${escapeHtml(c.category)}</td>
            <td class="num">${c.articles}</td><td class="num">${c.negative}</td>
            <td><div style="display:flex;align-items:center;gap:6px"><div class="hbar-track" style="flex:1"><div class="hbar" style="background:${COLORS.critical};width:${(c.share_of_severity * 100).toFixed(0)}%"></div></div>
            <span style="font-size:11px;color:var(--muted);width:32px;text-align:right">${(c.share_of_severity * 100).toFixed(0)}%</span></div></td></tr>`).join('')}</tbody>
        </table>
        <div style="font-size:11px;color:var(--muted);margin-top:6px">Rule-based keyword classifier; click a row to filter the headlines below.</div>
      </div>
    </div>

    ${(d.drivers || []).length ? `
    <div class="card" style="padding:16px;margin-bottom:16px">
      <div class="card-title">Headlines driving the severity score</div>
      ${d.drivers.map(h => `<div style="display:flex;gap:10px;padding:7px 0;border-top:1px solid var(--border);font-size:13px;align-items:baseline">
        <span style="min-width:44px;font-weight:700;color:${COLORS.critical}">${(h.severity_share * 100).toFixed(0)}%</span>
        <span style="flex:1">${h.url ? `<a href="${escapeHtml(h.url)}" target="_blank" rel="noopener" style="color:var(--text)">${escapeHtml(h.title)}</a>` : escapeHtml(h.title)}
          <div style="color:var(--muted);font-size:11px;margin-top:2px">${escapeHtml(h.outlet || '')} · FinBERT ${fmtS(h.sentiment)} · ${escapeHtml(h.category || '')} · recency weight ${Number(h.weight).toFixed(2)}${h.published ? ' · ' + new Date(h.published).toLocaleDateString() : ''}</div></span>
      </div>`).join('')}
      <div style="font-size:11px;color:var(--muted);margin-top:6px">Percent = this headline's share of the severity numerator (its negative intensity × recency weight).</div>
    </div>` : ''}

    ${renderSourceComparisonCard(d)}

    <div class="card" style="padding:16px">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap">
        <div class="card-title">All headlines (FinBERT scored, most negative first) <span id="hl-count" style="font-weight:400;color:var(--muted);font-size:11px"></span></div>
        <div style="display:flex;gap:6px;flex-wrap:wrap">
          <select id="hl-cat" class="input-field" style="font-size:12px;padding:4px 8px">
            <option value="all">All issue types</option>
            ${(d.categories || []).map(c => `<option value="${escapeHtml(c.category)}">${escapeHtml(c.category)} (${c.articles})</option>`).join('')}
          </select>
          <select id="hl-outlet" class="input-field" style="font-size:12px;padding:4px 8px">
            <option value="all">All sources (${d.headlines.length})</option>
            ${(d.sources || []).map(s => `<option value="${escapeHtml(s.outlet)}">${escapeHtml(s.outlet)} (${s.articles})</option>`).join('')}
          </select>
        </div>
      </div>
      <div id="hl-list" style="margin-top:8px">
        ${d.headlines.map(h => {
          const s = Number(h.sentiment) || 0;
          const col = s < -0.05 ? COLORS.critical : s > 0.05 ? COLORS.low : COLORS.tick;
          const title = escapeHtml(h.title);
          const link = h.url ? `<a href="${escapeHtml(h.url)}" target="_blank" rel="noopener" style="color:var(--text)">${title}</a>` : title;
          const when = h.published ? new Date(h.published).toLocaleDateString() : '';
          const cat = h.category && h.category !== 'General Coverage' ? ` · <span class="chip">${escapeHtml(h.category)}</span>` : '';
          return `<div data-outlet="${escapeHtml(h.outlet || h.source || '')}" data-cat="${escapeHtml(h.category || '')}" style="display:flex;gap:10px;padding:7px 0;border-top:1px solid var(--border);font-size:13px">
            <span style="color:${col};font-weight:600;min-width:48px">${fmtS(s)}</span>
            <span style="flex:1">${link}<div style="color:var(--muted);font-size:11px;margin-top:2px"><strong style="color:var(--text);font-weight:600">${escapeHtml(h.outlet || h.source || '')}</strong> · via ${escapeHtml(PROVIDER_LABELS[h.provider] || h.provider || '')}${when ? ' · ' + when : ''}${cat}${(h.regulators || []).length ? ' · ' + escapeHtml(h.regulators.join(', ')) : ''}</div></span>
          </div>`;
        }).join('')}
      </div>
    </div>`;

  // Radar: this company vs. monitored average
  const avg = monitoredAverageCriteria();
  const ds = [{
    label: d.name, data: crit,
    backgroundColor: 'rgba(47,129,247,0.15)', borderColor: COLORS.accent,
    pointBackgroundColor: COLORS.accent, pointRadius: 4, borderWidth: 2
  }];
  if (avg) ds.push({ label: 'Monitored average', data: avg, backgroundColor: 'rgba(139,148,158,0.08)',
    borderColor: COLORS.tick, borderDash: [4, 3], pointRadius: 2, borderWidth: 1.5 });
  searchCharts.radar = new Chart(document.getElementById('search-radar').getContext('2d'), {
    type: 'radar',
    data: { labels: CRITERIA_LABELS, datasets: ds },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { labels: { color: COLORS.tick, font: { size: 11 } } } },
      scales: { r: {
        min: 0, max: 100,
        grid: { color: COLORS.grid }, angleLines: { color: COLORS.grid },
        pointLabels: { color: COLORS.tick, font: { size: 11 } },
        ticks: { color: COLORS.tick, backdropColor: 'transparent', stepSize: 25 }
      } }
    }
  });

  // Timeline: daily headline counts by FinBERT label + average sentiment
  const tl = d.timeline || [];
  searchCharts.timeline = new Chart(document.getElementById('search-timeline').getContext('2d'), {
    data: {
      labels: tl.map(t => t.date.slice(5)),
      datasets: [
        { type: 'bar', label: 'Negative', data: tl.map(t => t.negative), backgroundColor: COLORS.critical, stack: 'n', yAxisID: 'y' },
        { type: 'bar', label: 'Neutral', data: tl.map(t => t.articles - t.negative - t.positive), backgroundColor: '#30363d', stack: 'n', yAxisID: 'y' },
        { type: 'bar', label: 'Positive', data: tl.map(t => t.positive), backgroundColor: COLORS.low, stack: 'n', yAxisID: 'y' },
        { type: 'line', label: 'Avg sentiment', data: tl.map(t => t.avg_sentiment), borderColor: COLORS.accent,
          backgroundColor: COLORS.accent, yAxisID: 'y2', tension: 0.3, pointRadius: 2 }
      ]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { labels: { color: COLORS.tick, font: { size: 11 }, boxWidth: 10 } } },
      scales: {
        x: { stacked: true, grid: { display: false }, ticks: { color: COLORS.tick, font: { size: 10 } } },
        y: { stacked: true, grid: { color: COLORS.grid }, ticks: { color: COLORS.tick, precision: 0 }, title: { display: true, text: 'headlines', color: COLORS.tick } },
        y2: { position: 'right', min: -1, max: 1, grid: { display: false }, ticks: { color: COLORS.tick } }
      }
    }
  });

  document.getElementById('hl-outlet').addEventListener('change', applyHeadlineFilters);
  document.getElementById('hl-cat').addEventListener('change', applyHeadlineFilters);
  out.querySelectorAll('[data-cat-row]').forEach(r => r.addEventListener('click', () => {
    document.getElementById('hl-cat').value = r.dataset.catRow;
    applyHeadlineFilters();
    document.getElementById('hl-list').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }));
  applyHeadlineFilters();
  wireSourceComparison(d);

  const wb = document.getElementById('watch-btn');
  if (wb) wb.addEventListener('click', addToWatchlist);
}

async function addToWatchlist() {
  if (!lastSearch) return;
  const wb = document.getElementById('watch-btn');
  wb.disabled = true; wb.textContent = 'Adding…';
  const extra = (lastSearch.search_terms || []).slice(1);
  try {
    const r = await fetch('/api/watchlist', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: lastSearch.name, sector: lastSearch._sector || lastSearch.sector, search_terms: extra })
    }).then(r => r.json());
    wb.outerHTML = `<span style="font-size:12px;color:var(--low)">Added as ${escapeHtml(r.company.id)} · re-scoring all companies…</span>`;
    // Pick up the refreshed dataset once the background run finishes.
    const start = Date.now();
    const poll = setInterval(async () => {
      const s = await fetch('/api/live/status').then(x => x.json()).catch(() => null);
      if ((s && !s.running && s.last_run && s.last_run !== liveLastRun) || Date.now() - start > 300000) {
        clearInterval(poll);
        loadLiveData(true);
      }
    }, 4000);
  } catch (e) {
    wb.disabled = false; wb.textContent = '+ Add to watchlist';
  }
}

tabInits['search'] = initSearch;
