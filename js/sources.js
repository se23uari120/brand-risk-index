// =============================================
// SOURCES — compare what each news outlet says
//   1. Per-company comparison panel (Company Search)
//   2. "Source Comparison" tab: company × outlet matrix
// =============================================

let srcChart = null;
let srcSort = 'coverage';

function sentColor(s) {
  return s < -0.05 ? COLORS.critical : s > 0.05 ? COLORS.low : COLORS.tick;
}
function fmtSent(s) {
  return s == null ? '—' : (s >= 0 ? '+' : '') + Number(s).toFixed(2);
}

const SOURCE_SORTS = {
  coverage: { label: 'Most coverage',        fn: (a, b) => b.articles - a.articles || a.avg_sentiment - b.avg_sentiment },
  negative: { label: 'Most negative first',  fn: (a, b) => a.avg_sentiment - b.avg_sentiment },
  positive: { label: 'Most positive first',  fn: (a, b) => b.avg_sentiment - a.avg_sentiment },
  risk:     { label: 'Highest risk first',   fn: (a, b) => (b.risk_index ?? -1) - (a.risk_index ?? -1) },
  name:     { label: 'Outlet A–Z',           fn: (a, b) => a.outlet.localeCompare(b.outlet) },
};

// ---------- 1. Per-company panel ----------
function renderSourceComparisonCard(d) {
  const c = d.consensus || {};
  const agreeCol = c.agreement === 'High' ? COLORS.low : c.agreement === 'Mixed' ? COLORS.moderate : c.agreement === 'Conflicting' ? COLORS.critical : COLORS.tick;
  const summary = c.spread == null
    ? `<span style="color:var(--muted)">${escapeHtml(c.agreement || 'Not enough sources')}</span>`
    : `Source agreement: <strong style="color:${agreeCol}">${escapeHtml(c.agreement)}</strong>
       <span style="color:var(--muted)">(spread ${c.spread.toFixed(2)} across ${c.outlets_compared} outlets with 2+ articles)</span>
       · Most negative: <strong>${escapeHtml(c.most_negative_outlet)}</strong>
       · Most positive: <strong>${escapeHtml(c.most_positive_outlet)}</strong>`;

  return `
    <div class="card" style="padding:16px;margin-bottom:16px">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap">
        <div class="card-title">Source Comparison · ${(d.sources || []).length} outlets</div>
        <label style="font-size:12px;color:var(--muted)">Order by
          <select id="src-sort" class="input-field" style="font-size:12px;padding:4px 8px;margin-left:4px">
            ${Object.entries(SOURCE_SORTS).map(([k, v]) => `<option value="${k}" ${k === srcSort ? 'selected' : ''}>${v.label}</option>`).join('')}
          </select>
        </label>
      </div>
      <div style="font-size:12px;margin-top:6px">${summary}</div>
      <div class="chart-wrap" style="height:${Math.max(160, Math.min(12, (d.sources || []).length) * 26 + 40)}px;margin-top:12px"><canvas id="src-chart"></canvas></div>
      <div style="overflow-x:auto;margin-top:12px">
        <table class="data-table" id="src-table">
          <thead><tr>
            <th>#</th><th>Outlet</th><th style="text-align:right">Articles</th><th>Avg sentiment</th>
            <th style="text-align:right">Neg / Neu / Pos %</th><th style="text-align:right">Risk (this source only)</th>
            <th>Most negative headline</th>
          </tr></thead>
          <tbody></tbody>
        </table>
      </div>
      <div style="font-size:11px;color:var(--muted);margin-top:6px">
        Risk per source = AHP-TOPSIS index computed only from that outlet's articles, ranked against the monitored companies (shown for outlets with 2+ articles). Click a row to see that outlet's headlines.
      </div>
    </div>`;
}

function wireSourceComparison(d) {
  const sel = document.getElementById('src-sort');
  if (!sel) return;
  sel.addEventListener('change', () => { srcSort = sel.value; drawSourceComparison(d); });
  drawSourceComparison(d);
}

function drawSourceComparison(d) {
  const rows = [...(d.sources || [])].sort(SOURCE_SORTS[srcSort].fn);
  const tbody = document.querySelector('#src-table tbody');
  tbody.innerHTML = rows.map((s, i) => {
    const w = Math.round(Math.abs(s.avg_sentiment) * 100);
    const neg = s.most_negative || {};
    const negLink = neg.url ? `<a href="${escapeHtml(neg.url)}" target="_blank" rel="noopener" style="color:var(--text)">${escapeHtml(neg.title)}</a>` : escapeHtml(neg.title || '');
    return `<tr data-outlet="${escapeHtml(s.outlet)}" style="cursor:pointer">
      <td class="id-cell">${i + 1}</td>
      <td><strong>${escapeHtml(s.outlet)}</strong><div style="font-size:10px;color:var(--muted)">via ${s.providers.map(p => escapeHtml(PROVIDER_LABELS[p] || p)).join(', ')}</div></td>
      <td style="text-align:right">${s.articles}</td>
      <td><div style="display:flex;align-items:center;gap:6px">
        <div style="width:60px;height:6px;background:var(--border);border-radius:3px;overflow:hidden"><div style="width:${w}%;height:100%;background:${sentColor(s.avg_sentiment)}"></div></div>
        <span style="color:${sentColor(s.avg_sentiment)};font-weight:600;font-size:12px">${fmtSent(s.avg_sentiment)}</span></div></td>
      <td style="text-align:right;font-size:12px"><span style="color:${COLORS.critical}">${Math.round(s.negative_pct)}</span> / ${Math.round(s.neutral_pct)} / <span style="color:${COLORS.low}">${Math.round(s.positive_pct)}</span></td>
      <td style="text-align:right">${s.risk_index == null ? '<span style="color:var(--muted);font-size:12px">n&lt;2</span>'
        : `<span style="color:${riskBarColor(s.risk_index)};font-weight:600">${s.risk_index.toFixed(1)}</span> <span class="badge ${levelBadgeClass(s.level)}">${s.level}</span>`}</td>
      <td style="font-size:12px;min-width:220px;max-width:360px"><div style="display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden" title="${escapeHtml(neg.title || '')}"><span style="color:${sentColor(neg.sentiment || 0)}">${fmtSent(neg.sentiment)}</span> ${negLink}</div></td>
    </tr>`;
  }).join('');

  tbody.querySelectorAll('tr[data-outlet]').forEach(tr => tr.addEventListener('click', e => {
    if (e.target.closest('a')) return;
    const sel = document.getElementById('hl-outlet');
    sel.value = tr.dataset.outlet;
    filterHeadlines(tr.dataset.outlet);
    document.getElementById('hl-list').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }));

  // Bar chart: average sentiment per outlet (top 12 in current order)
  const top = rows.slice(0, 12);
  if (srcChart) { srcChart.destroy(); srcChart = null; }
  srcChart = new Chart(document.getElementById('src-chart').getContext('2d'), {
    type: 'bar',
    data: {
      labels: top.map(s => `${s.outlet} (${s.articles})`),
      datasets: [{
        label: 'Avg FinBERT sentiment',
        data: top.map(s => s.avg_sentiment),
        backgroundColor: top.map(s => sentColor(s.avg_sentiment)),
        borderRadius: 3, borderSkipped: false
      }]
    },
    options: {
      indexAxis: 'y', responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: ctx => {
          const s = top[ctx.dataIndex];
          return ` ${fmtSent(s.avg_sentiment)} · ${s.articles} articles · ${Math.round(s.negative_pct)}% negative`;
        } } }
      },
      scales: {
        x: { min: -1, max: 1, grid: { color: COLORS.grid }, ticks: { color: COLORS.tick, font: { size: 11 } } },
        y: { grid: { display: false }, ticks: { color: COLORS.tick, font: { size: 11 } } }
      }
    }
  });
}

function filterHeadlines(outlet) {
  const sel = document.getElementById('hl-outlet');
  if (sel && outlet) sel.value = outlet;
  applyHeadlineFilters();
}

// Combined outlet + issue-type filter for the search headline list
function applyHeadlineFilters() {
  const o = (document.getElementById('hl-outlet') || {}).value || 'all';
  const c = (document.getElementById('hl-cat') || {}).value || 'all';
  let shown = 0;
  document.querySelectorAll('#hl-list [data-outlet]').forEach(row => {
    const ok = (o === 'all' || row.dataset.outlet === o) && (c === 'all' || row.dataset.cat === c);
    row.style.display = ok ? 'flex' : 'none';
    shown += ok;
  });
  const cnt = document.getElementById('hl-count');
  if (cnt) cnt.textContent = `${shown} shown`;
}

// ---------- 2. Source Comparison tab (all monitored companies) ----------
let srcMatrixMin = 1;

async function initSourcesTab() {
  const box = document.getElementById('sources-body');
  if (!liveApiAvailable()) {
    box.innerHTML = `<div class="card" style="padding:24px;color:var(--muted)">Source comparison needs the backend (start.bat → http://localhost:8000).</div>`;
    return;
  }
  document.getElementById('srcm-min').addEventListener('change', e => { srcMatrixMin = Number(e.target.value); loadSourceMatrix(); });
  document.getElementById('srcm-cols').addEventListener('change', loadSourceMatrix);
  loadSourceMatrix();
}

async function loadSourceMatrix() {
  const box = document.getElementById('sources-body');
  let data;
  try {
    data = await fetch('/api/source-matrix?min_articles=' + srcMatrixMin).then(r => r.json());
  } catch (e) {
    box.innerHTML = `<div class="card" style="padding:24px;color:var(--critical)">Could not load source matrix.</div>`;
    return;
  }
  const nCols = Number(document.getElementById('srcm-cols').value);
  const outlets = data.outlets.slice(0, nCols);

  const outletTable = `
    <div class="card" style="padding:0;overflow:hidden;margin-bottom:16px">
      <div style="padding:14px 16px 0" class="card-title">Outlets ordered by total coverage of monitored companies · showing ${outlets.length} of ${data.outlets.length}</div>
      <div style="overflow-x:auto"><table class="data-table">
        <thead><tr><th>#</th><th>Outlet</th><th style="text-align:right">Articles</th><th style="text-align:right">Companies covered</th><th>Avg sentiment (weighted)</th><th style="text-align:right">% negative</th></tr></thead>
        <tbody>${outlets.map((o, i) => `<tr>
          <td class="id-cell">${i + 1}</td><td><strong>${escapeHtml(o.outlet)}</strong></td>
          <td style="text-align:right">${o.articles}</td><td style="text-align:right">${o.companies}</td>
          <td style="color:${sentColor(o.avg_sentiment)};font-weight:600">${fmtSent(o.avg_sentiment)}</td>
          <td style="text-align:right;color:${COLORS.critical}">${o.negative_pct.toFixed(0)}%</td></tr>`).join('')}
        </tbody></table></div>
    </div>`;

  const cell = c => {
    if (!c) return `<td style="text-align:center;color:var(--border)">·</td>`;
    const a = Math.min(0.85, 0.15 + Math.abs(c.avg) * 0.9);
    const bg = c.avg < -0.05 ? `rgba(218,54,51,${a})` : c.avg > 0.05 ? `rgba(35,134,54,${a})` : 'rgba(139,148,158,0.15)';
    return `<td title="${c.n} articles · ${c.neg}% negative" style="text-align:center;background:${bg};font-size:12px;font-variant-numeric:tabular-nums">${fmtSent(c.avg)}<div style="font-size:10px;opacity:.75">${c.n}</div></td>`;
  };
  const matrix = `
    <div class="card" style="padding:0;overflow:hidden">
      <div style="padding:14px 16px 0" class="card-title">Company × source sentiment matrix (cell = avg FinBERT sentiment, small number = articles)</div>
      <div style="overflow-x:auto"><table class="data-table" style="min-width:${300 + outlets.length * 90}px">
        <thead><tr><th>Company</th><th style="text-align:right">Risk</th><th>Agreement</th>
          ${outlets.map(o => `<th style="text-align:center;white-space:normal;min-width:80px">${escapeHtml(o.outlet)}</th>`).join('')}</tr></thead>
        <tbody>${data.companies.map(r => {
          const cons = r.consensus || {};
          const ac = cons.agreement === 'High' ? COLORS.low : cons.agreement === 'Mixed' ? COLORS.moderate : cons.agreement === 'Conflicting' ? COLORS.critical : COLORS.tick;
          return `<tr><td><strong>${escapeHtml(r.name)}</strong></td>
            <td style="text-align:right;color:${riskBarColor(r.risk_index || 0)};font-weight:600">${r.risk_index != null ? Number(r.risk_index).toFixed(1) : '—'}</td>
            <td style="font-size:12px;color:${ac}" title="${cons.spread != null ? 'spread ' + cons.spread : ''}">${escapeHtml(cons.agreement || '—')}</td>
            ${outlets.map(o => cell(r.cells[o.outlet])).join('')}</tr>`;
        }).join('')}</tbody></table></div>
    </div>`;

  box.innerHTML = outletTable + matrix;
}

tabInits['sources'] = initSourcesTab;
