// =============================================================
// mcdm.js — the MCDM tab: how much do the results depend on the
// AHP weights? AHP vs CRITIC (objective) weights with an interactive
// blend, the CRITIC inputs, and the sensitivity analysis
// (judgement perturbation, one-at-a-time, Monte Carlo).
// Everything is computed by the pipeline (mcdm/sensitivity.py);
// the blend slider re-runs TOPSIS in the browser.
// =============================================================

function topsisAll(weights) {
  return D.companies.map(c => {
    const v = c.criteria.map((x, i) => weights[i] * x / 100);
    const dp = Math.hypot(...v), dn = Math.hypot(...v.map((x, i) => weights[i] - x));
    return dp + dn ? 100 * dp / (dp + dn) : 0;
  });
}
function rankOf(arr) {
  const order = arr.map((v, i) => [v, i]).sort((a, b) => b[0] - a[0]);
  const r = Array(arr.length);
  order.forEach(([, i], k) => { r[i] = k + 1; });
  return r;
}
function spearmanJS(a, b) {
  const ra = rankOf(a), rb = rankOf(b), n = a.length;
  const mean = (n + 1) / 2;
  let num = 0, da = 0, db = 0;
  for (let i = 0; i < n; i++) { num += (ra[i] - mean) * (rb[i] - mean); da += (ra[i] - mean) ** 2; db += (rb[i] - mean) ** 2; }
  return da && db ? num / Math.sqrt(da * db) : 1;
}
const KEYS = () => CRIT.map(k => k.key);
const pctW = w => (w * 100).toFixed(1) + '%';

function renderMcdm() {
  const m = D.mcdm;
  if (!m) { $('#mcdm-body').innerHTML = '<div class="card empty">No MCDM analysis in this data — run the pipeline again.</div>'; return; }
  const names = CRIT.map(k => `${k.key} ${k.name}`);

  // 1. weights compared
  $('#mcdm-compare').innerHTML = `
    <thead><tr><th>Weights</th>${CRIT.map(k => `<th class="r" title="${esc(k.name)}">${esc(k.key)}</th>`).join('')}<th class="r">Rank agreement with AHP</th><th class="r">Level changes</th><th>Top 3</th></tr></thead>
    <tbody>${m.comparison.map(v => `<tr><td><strong>${esc(v.name)}</strong></td>${v.weights.map(w => `<td class="r num">${pctW(w)}</td>`).join('')}
      <td class="r num">${v.spearman.toFixed(3)}</td><td class="r num">${v.bandChanges}</td>
      <td class="small">${v.top.slice(0, 3).map(s => esc((BY_SYMBOL[s] || { name: s }).name)).join(', ')}</td></tr>`).join('')}</tbody>`;
  renderBlend();

  // 2. CRITIC inputs
  $('#mcdm-critic').innerHTML = `
    <thead><tr><th></th>${CRIT.map(k => `<th class="r">${esc(k.key)}</th>`).join('')}</tr></thead>
    <tbody>
      <tr><th scope="row" class="text-2" style="font-weight:500">Spread across companies (σ)</th>${m.critic.sigma.map(x => `<td class="r num">${x.toFixed(3)}</td>`).join('')}</tr>
      ${m.critic.correlation.map((row, i) => `<tr><th scope="row" class="text-2" style="font-weight:500">Correlation with ${esc(KEYS()[i])}</th>
        ${row.map((x, j) => `<td class="r num heat" style="--h:${i === j ? 0 : Math.abs(x)};--hc:${x >= 0 ? 'var(--s1)' : 'var(--high)'}">${i === j ? '—' : x.toFixed(2)}</td>`).join('')}</tr>`).join('')}
      <tr><th scope="row" style="font-weight:600">CRITIC weight</th>${m.critic.weights.map(x => `<td class="r num"><strong>${pctW(x)}</strong></td>`).join('')}</tr>
    </tbody>`;

  // 3. judgement perturbation
  $('#mcdm-judgements').innerHTML = `
    <thead><tr><th>Judgement</th><th class="r">Changed</th><th class="r">CR</th>${CRIT.map(k => `<th class="r">${esc(k.key)}</th>`).join('')}<th class="r">Rank agreement</th><th class="r">Level changes</th><th class="r">Top company changes?</th></tr></thead>
    <tbody>${m.judgements.map(j => `<tr><td>${esc(j.judgement)}</td><td class="r num">${esc(j.from)} → ${esc(j.to)}</td>
      <td class="r num">${j.CR.toFixed(3)}${j.consistent ? '' : ' ⚠'}</td>${j.weights.map(w => `<td class="r num">${pctW(w)}</td>`).join('')}
      <td class="r num">${j.spearman.toFixed(3)}</td><td class="r num">${j.bandChanges}</td><td class="r">${j.topChanged ? 'yes' : 'no'}</td></tr>`).join('')}</tbody>`;
  const minRho = Math.min(...m.judgements.map(j => j.spearman)), maxBand = Math.max(...m.judgements.map(j => j.bandChanges));
  $('#mcdm-judgements-note').textContent = `Across all ${m.judgements.length} one-step changes the ranking agreement never drops below ${minRho.toFixed(3)} and at most ${fmt.plural(maxBand, 'company')} change level.`;

  // 4. one-at-a-time
  const deltas = [...new Set(m.oneAtATime.map(o => o.changePct))];
  $('#mcdm-oat').innerHTML = `
    <thead><tr><th>Weight of…</th>${deltas.map(d => `<th class="r">${d > 0 ? '+' : ''}${d}%</th>`).join('')}</tr></thead>
    <tbody>${CRIT.map(k => `<tr><td>${esc(k.key)} ${esc(k.name)}</td>${deltas.map(d => {
      const o = m.oneAtATime.find(x => x.criterion === k.key && x.changePct === d);
      return `<td class="r num" title="${o.bandChanges} level changes">${o.spearman.toFixed(3)}${o.bandChanges ? ` <span class="muted">(${o.bandChanges})</span>` : ''}</td>`;
    }).join('')}</tr>`).join('')}</tbody>`;

  // 5. Monte Carlo
  const mc = m.monteCarlo;
  $('#mcdm-mc-summary').innerHTML = `
    <div>Weight draws<b>${mc.draws.toLocaleString('en-IN')}</b></div>
    <div>Mean rank agreement<b>${mc.spearmanMean.toFixed(3)}</b></div>
    <div>Worst 5% of draws<b>${mc.spearmanP5.toFixed(3)}</b></div>
    <div>Weight ranges (5–95%)<b class="small" style="font-size:12px">${mc.weightRange.map(w => `${w.criterion} ${Math.round(w.p5 * 100)}–${Math.round(w.p95 * 100)}%`).join(' · ')}</b></div>`;
  const top = mc.companies.slice(0, 15);
  $('#mcdm-mc-box').style.height = (top.length * 26 + 50) + 'px';
  rangeChart('mcdm-mc', $('#chart-mcdm-mc'), {
    labels: top.map(c => (BY_SYMBOL[c.symbol] || { name: c.symbol }).name),
    ranges: top.map(c => [c.p5, c.p95]), points: top.map(c => c.score),
    tip: i => [` score ${top[i].score.toFixed(1)} · 90% of weightings ${top[i].p5.toFixed(1)}–${top[i].p95.toFixed(1)}`,
      ` keeps its level in ${Math.round(top[i].levelStability * 100)}% · keeps its rank in ${Math.round(top[i].rankStability * 100)}%`],
  });
  $('#mcdm-mc-table').innerHTML = dataTable(['Company', 'Score', '5%', '95%', 'Keeps level', 'Keeps rank'],
    mc.companies.map(c => [(BY_SYMBOL[c.symbol] || { name: c.symbol }).name, c.score.toFixed(1), c.p5.toFixed(1), c.p95.toFixed(1),
      Math.round(c.levelStability * 100) + '%', Math.round(c.rankStability * 100) + '%']));
}

function renderBlend() {
  const m = D.mcdm, a = +$('#mcdm-alpha').value / 100;
  const w = WEIGHTS.map((x, i) => a * x + (1 - a) * m.critic.weights[i]);
  const sum = w.reduce((s, x) => s + x, 0), wn = w.map(x => x / sum);
  const base = D.companies.map(c => c.score), idx = topsisAll(wn);
  const rb = rankOf(base), ri = rankOf(idx);
  const lv = idx.map(levelOf), changes = lv.filter((l, i) => l !== D.companies[i].level).length;
  $('#mcdm-alpha-val').textContent = `${Math.round(a * 100)}% AHP · ${Math.round((1 - a) * 100)}% CRITIC`;
  $('#mcdm-blend-weights').innerHTML = CRIT.map((k, i) => `<div>${esc(k.key)} ${esc(k.name)}<b>${pctW(wn[i])}</b></div>`).join('');
  const movers = D.companies.map((c, i) => ({ c, from: rb[i], to: ri[i], s: idx[i] })).sort((x, y) => x.to - y.to).slice(0, 10);
  $('#mcdm-blend-result').innerHTML = `
    <p class="small text-2" style="margin:8px 0">Rank agreement with today's AHP ranking: <strong>${spearmanJS(base, idx).toFixed(3)}</strong> ·
      ${fmt.plural(changes, 'company')} would change level.</p>
    <table class="data"><thead><tr><th class="r">#</th><th>Company</th><th class="r">Score with these weights</th><th class="r">AHP rank</th></tr></thead>
    <tbody>${movers.map(x => `<tr><td class="r num">${x.to}</td><td>${esc(x.c.name)}</td><td class="r num">${x.s.toFixed(1)}</td>
      <td class="r num">${x.from}${x.from !== x.to ? ` <span class="muted">(${x.from > x.to ? '▲' : '▼'}${Math.abs(x.from - x.to)})</span>` : ''}</td></tr>`).join('')}</tbody></table>`;
}

function initMcdm() {
  $('#mcdm-alpha').addEventListener('input', () => { if (D.mcdm) renderBlend(); });
}
