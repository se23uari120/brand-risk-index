// =============================================================
// compare.js — up to four companies side by side.
// Each company keeps its colour slot while selected (colour follows
// the company, not its position), so removing one never repaints others.
// =============================================================

const MAX_COMPARE = 4;
let compareSel = [];            // [{ symbol, slot }]
let acIndex = -1;

function addCompare(symbol) {
  if (!BY_SYMBOL[symbol] || compareSel.some(s => s.symbol === symbol)) return;
  if (compareSel.length >= MAX_COMPARE) compareSel.shift();          // drop the oldest
  const used = new Set(compareSel.map(s => s.slot));
  const slot = [0, 1, 2, 3].find(i => !used.has(i));
  compareSel.push({ symbol, slot });
  if (currentView === 'compare') renderCompare();
}
function removeCompare(symbol) {
  compareSel = compareSel.filter(s => s.symbol !== symbol);
  renderCompare();
}

function initCompare() {
  if (!compareSel.length) D.companies.slice(0, 2).forEach(c => addCompare(c.symbol));
  const input = $('#cmp-input'), list = $('#cmp-list');

  const options = () => {
    const q = input.value.trim().toLowerCase();
    return D.companies.filter(c => !compareSel.some(s => s.symbol === c.symbol) &&
      (!q || c.name.toLowerCase().includes(q) || c.symbol.toLowerCase().includes(q))).slice(0, 8);
  };
  const close = () => { list.classList.remove('open'); input.setAttribute('aria-expanded', 'false'); acIndex = -1; };
  const open = () => {
    const opts = options();
    list.innerHTML = opts.length ? opts.map((c, i) => `
      <li role="option" id="ac-${i}" data-sym="${esc(c.symbol)}" aria-selected="${i === acIndex}">
        <span><strong>${esc(c.name)}</strong> <span class="muted small">${esc(c.symbol)}</span></span>
        <span class="small text-2">${fmt.score(c.score)} · ${c.level}</span></li>`).join('')
      : '<li class="muted small" aria-disabled="true">No matching company</li>';
    list.classList.add('open'); input.setAttribute('aria-expanded', 'true');
    input.setAttribute('aria-activedescendant', acIndex >= 0 ? `ac-${acIndex}` : '');
  };
  const pick = sym => { addCompare(sym); input.value = ''; close(); renderCompare(); };

  input.addEventListener('input', () => { acIndex = -1; open(); });
  input.addEventListener('focus', open);
  input.addEventListener('blur', () => setTimeout(close, 150));
  input.addEventListener('keydown', e => {
    const n = options().length;
    if (e.key === 'ArrowDown') { e.preventDefault(); acIndex = Math.min(n - 1, acIndex + 1); open(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); acIndex = Math.max(0, acIndex - 1); open(); }
    else if (e.key === 'Enter') { const o = options()[acIndex >= 0 ? acIndex : 0]; if (o) { e.preventDefault(); pick(o.symbol); } }
    else if (e.key === 'Escape') close();
  });
  list.addEventListener('mousedown', e => { const li = e.target.closest('li[data-sym]'); if (li) { e.preventDefault(); pick(li.dataset.sym); } });

  $('#cmp-clear').addEventListener('click', () => { compareSel = []; renderCompare(); });
  $('#cmp-chips').addEventListener('click', e => { const b = e.target.closest('button[data-remove]'); if (b) removeCompare(b.dataset.remove); });
  $('#cmp-suggest').addEventListener('click', e => { const b = e.target.closest('button[data-add]'); if (b) { addCompare(b.dataset.add); renderCompare(); } });
}

function renderCompare() {
  const t = theme();
  const sel = compareSel.map(s => ({ ...s, c: BY_SYMBOL[s.symbol], color: t.series[s.slot], cssVar: `var(--s${s.slot + 1})` }));

  $('#cmp-chips').innerHTML = sel.map(s => `
    <span class="chip"><span class="dot" style="background:${s.cssVar}"></span>${esc(s.c.name)}
      <button type="button" data-remove="${esc(s.symbol)}" aria-label="Remove ${esc(s.c.name)}">×</button></span>`).join('');

  const suggestions = D.companies.filter(c => !compareSel.some(s => s.symbol === c.symbol)).slice(0, 4);
  $('#cmp-suggest').innerHTML = compareSel.length < MAX_COMPARE && suggestions.length
    ? `Quick add: ${suggestions.map(c => `<button type="button" data-add="${esc(c.symbol)}">+ ${esc(c.name)}</button>`).join('')}`
    : `<span>${compareSel.length} of ${MAX_COMPARE} selected — adding another replaces the oldest.</span>`;

  const empty = sel.length === 0;
  $('#cmp-empty').hidden = !empty;
  $('#cmp-content').hidden = empty;
  if (empty) { destroyChart('cmp-trend'); destroyChart('cmp-signals'); return; }

  const legend = sel.map(s => `<span><i style="background:${s.cssVar}"></i>${esc(s.c.name)}</span>`).join('');
  $('#cmp-legend-1').innerHTML = legend;
  $('#cmp-legend-2').innerHTML = legend.replaceAll('<i ', '<i class="box" ');

  lineChart('cmp-trend', $('#chart-cmp-trend'), {
    labels: D.historyDates, yMin: 0, yMax: 100, zones: true, endLabels: true,
    series: sel.map(s => ({ label: s.c.name, data: s.c.history, color: s.color })),
    tipFmt: v => v.toFixed(1),
  });
  groupedBarChart('cmp-signals', $('#chart-cmp-signals'), {
    labels: CRIT.map(k => k.name),
    series: sel.map(s => ({ label: s.c.name, data: s.c.criteria, color: s.color })),
  });

  const metric = (label, f) => `<tr><th scope="row" style="font-weight:500;color:var(--text-2)">${label}</th>${sel.map(s => `<td>${f(s.c)}</td>`).join('')}</tr>`;
  $('#cmp-table').innerHTML = `
    <thead><tr><th></th>${sel.map(s => `<th><span style="display:inline-flex;align-items:center;gap:6px;color:var(--text)"><span class="chip-dot" style="width:10px;height:10px;border-radius:50%;background:${s.cssVar};display:inline-block"></span>${esc(s.c.name)}</span></th>`).join('')}</tr></thead>
    <tbody>
      ${metric('Risk score', c => meter(c.score, c.level))}
      ${metric('Level', c => levelPill(c.level))}
      ${metric('Rank', c => `${c.rank} of ${D.companies.length}`)}
      ${metric('1-week change', c => delta(c.change5d))}
      ${metric('Sector', c => esc(c.sector))}
      ${CRIT.map((k, i) => metric(`${esc(k.name)} <span class="muted small">(${(WEIGHTS[i] * 100).toFixed(0)}%)</span>`, c => `<span class="num">${c.criteria[i].toFixed(1)}</span>`)).join('')}
      ${metric('Company-specific move, 5 days', c => `<span class="num">${fmt.pct(c.stock.excess5)}</span> <span class="muted small">(${fmt.sigma(c.stock.z5)})</span>`)}
      ${metric('Share price, 5 days', c => `<span class="num">${fmt.pct(c.stock.ret5)}</span>`)}
      ${metric('Negative / all headlines, 7 days', c => `<span class="num">${c.news.neg7d} / ${c.news.count7d}</span>`)}
      ${metric('Biggest driver', c => esc(contributions(c)[0].name))}
      ${metric('In one line', c => `<span class="small text-2">${esc(headline(c))}</span>`)}
    </tbody>`;
}
