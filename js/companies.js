// =============================================================
// companies.js — searchable, filterable, sortable table of
// every tracked company. Rows open the detail drawer.
// =============================================================

const tableState = { q: '', sector: '', index: '', level: '', sort: 'rank', dir: 1 };

const SORTERS = {
  rank: c => c.rank,
  name: c => c.name.toLowerCase(),
  score: c => -c.score,
  change5d: c => -(c.change5d ?? -Infinity),
  excess5: c => c.stock.excess5,
  neg7d: c => -c.news.neg7d,
};

const INDEX_SHORT = { 'NIFTY 50': 'NIFTY 50', 'NIFTY Next 50': 'Next 50' };
const indexOf = c => c.index || 'Added';

function fillSectorOptions() {
  const sel = $('#f-sector'), keep = sel.value;
  const sectors = [...new Set(D.companies.map(c => c.sector))].sort();
  sel.innerHTML = '<option value="">All sectors</option>' + sectors.map(s => `<option value="${esc(s)}">${esc(s)}</option>`).join('');
  sel.value = sectors.includes(keep) ? keep : '';
  tableState.sector = sel.value;
  // index filter (NIFTY 50 / NIFTY Next 50 / companies added from Search)
  const isel = $('#f-index'), ikeep = isel.value;
  const idx = [...new Set(D.companies.map(indexOf))].sort((a, b) => (a === 'Added') - (b === 'Added') || a.localeCompare(b));
  isel.hidden = idx.length < 2;
  isel.innerHTML = `<option value="">All indices</option>` + idx.map(i => `<option value="${esc(i)}">${esc(i)} (${D.companies.filter(c => indexOf(c) === i).length})</option>`).join('');
  isel.value = idx.includes(ikeep) ? ikeep : '';
  tableState.index = isel.value;
}

function initCompanies() {
  fillSectorOptions();

  $('#f-search').addEventListener('input', e => { tableState.q = e.target.value.trim().toLowerCase(); renderCompanies(); });
  $('#f-sector').addEventListener('change', e => { tableState.sector = e.target.value; renderCompanies(); });
  $('#f-index').addEventListener('change', e => { tableState.index = e.target.value; renderCompanies(); });
  $$('#f-level button').forEach(b => b.addEventListener('click', () => {
    tableState.level = b.dataset.level;
    $$('#f-level button').forEach(x => x.setAttribute('aria-pressed', String(x === b)));
    renderCompanies();
  }));
  $$('#co-table th button[data-sort]').forEach(b => b.addEventListener('click', () => {
    const key = b.dataset.sort;
    tableState.dir = tableState.sort === key ? -tableState.dir : 1;
    tableState.sort = key;
    renderCompanies();
  }));
  $('#co-body').addEventListener('click', e => {
    const tr = e.target.closest('tr[data-symbol]');
    if (tr) openDetail(tr.dataset.symbol);
  });
  $('#co-body').addEventListener('keydown', e => {
    const tr = e.target.closest('tr[data-symbol]');
    if (tr && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); openDetail(tr.dataset.symbol); }
  });
}

function renderCompanies() {
  const { q, sector, index, level, sort, dir } = tableState;
  const rows = D.companies.filter(c =>
    (!q || c.name.toLowerCase().includes(q) || c.symbol.toLowerCase().includes(q) || (c.legalName || '').toLowerCase().includes(q)) &&
    (!sector || c.sector === sector) && (!index || indexOf(c) === index) && (!level || c.level === level));
  const key = SORTERS[sort];
  rows.sort((a, b) => { const x = key(a), y = key(b); return (x < y ? -1 : x > y ? 1 : 0) * dir; });

  $$('#co-table th').forEach(th => th.removeAttribute('aria-sort'));
  const active = $(`#co-table th button[data-sort="${sort}"]`);
  if (active) active.parentElement.setAttribute('aria-sort', dir === 1 ? 'ascending' : 'descending');

  $('#f-count').textContent = `Showing ${rows.length} of ${D.companies.length}`;
  $('#co-empty').hidden = rows.length > 0;
  $('#co-body').innerHTML = rows.map(c => `
    <tr class="clickable" tabindex="0" data-symbol="${esc(c.symbol)}" aria-label="${esc(c.name)}: open details">
      <td class="r num muted hide-sm">${c.rank}</td>
      <td class="co-cell"><div class="co-name">${esc(c.name)}</div><div class="co-sub">${esc(c.symbol)} · ${esc(c.sector)}${c.index ? ` · ${esc(INDEX_SHORT[c.index] || c.index)}` : ''}</div></td>
      <td class="score-cell">${meter(c.score, c.level)}<div class="show-sm" style="margin-top:4px">${levelPill(c.level)}</div></td>
      <td class="hide-sm">${levelPill(c.level)}</td>
      <td class="r">${delta(c.change5d)}</td>
      <td class="r num hide-sm" title="${esc(evidence(c, 0))}">${fmt.pct(c.stock.excess5)}</td>
      <td class="r num hide-sm">${c.news.count7d ? `<strong>${c.news.neg7d}</strong> / ${c.news.count7d}` : '<span class="muted">none</span>'}</td>
      <td class="hide-sm">${sparkline(c.history, c.level)}</td>
    </tr>`).join('');
}
