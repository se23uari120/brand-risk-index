// =============================================================
// method.js — fills the "How it works" page with live numbers:
// criteria definitions, the AHP matrix (re-verified in the browser),
// a TOPSIS worked example and today's level distribution.
// =============================================================

// Principal eigenvector by power iteration — recomputes the AHP weights
// from the shipped matrix so readers can see they really come from it.
function ahpInBrowser(A) {
  const n = A.length;
  let w = Array(n).fill(1 / n);
  for (let it = 0; it < 200; it++) {
    const next = A.map(row => row.reduce((s, a, j) => s + a * w[j], 0));
    const sum = next.reduce((s, x) => s + x, 0);
    w = next.map(x => x / sum);
  }
  const Aw = A.map(row => row.reduce((s, a, j) => s + a * w[j], 0));
  const lambda = Aw.reduce((s, x, i) => s + x / w[i], 0) / n;
  const ci = (lambda - n) / (n - 1);
  return { w, lambda, ci, cr: ci / D.ahp.RI };
}

function topsis(points) {
  const v = points.map((x, i) => WEIGHTS[i] * x / 100);
  const dPos = Math.sqrt(v.reduce((s, x) => s + x * x, 0));
  const dNeg = Math.sqrt(v.reduce((s, x, i) => s + (WEIGHTS[i] - x) ** 2, 0));
  return { v, dPos, dNeg, score: 100 * dPos / (dPos + dNeg) };
}

function ratio(x) {
  if (Math.abs(x - 1) < 1e-9) return '1';
  if (x >= 1) return String(Math.round(x));
  return `1/${Math.round(1 / x)}`;
}

function renderMethod() {
  const cs = D.companies;
  const sectors = {};
  cs.forEach(c => { sectors[c.sector] = (sectors[c.sector] || 0) + 1; });

  $('#m-universe-text').innerHTML =
    `The monitor tracks the <strong>${esc(D.universe)}</strong> — ${cs.length} of the largest companies listed on the <strong>National Stock Exchange of India</strong> — across ${Object.keys(sectors).length} sectors: ` +
    Object.entries(sectors).sort((a, b) => b[1] - a[1]).map(([s, k]) => `${esc(s)} (${k})`).join(', ') + '. ' +
    `Prices are compared with the NIFTY 50 index itself.`;

  // ── Criteria ──
  const top = cs[0];
  $('#m-criteria').innerHTML = CRIT.map((k, i) => `
    <div class="signal" style="padding:14px 0">
      <div class="signal-title">${esc(k.key)} · ${esc(k.name)} <span class="signal-tag">${esc(k.group)}</span>
        <span class="signal-weight">weight ${(WEIGHTS[i] * 100).toFixed(1)}%</span></div>
      <div></div>
      <div class="signal-ev" style="font-size:14px"><strong style="color:var(--text)">${esc(k.question)}</strong> ${esc(k.how)}</div>
      <div class="formula" style="grid-column:1/-1">${esc(k.formula)}</div>
      <div class="signal-ev muted">${esc(k.scale)}</div>
      <div class="signal-ev">Today's example — <a href="#company/${encodeURIComponent(top.symbol)}">${esc(top.name)}</a>: <strong>${top.criteria[i].toFixed(1)}</strong> points. ${esc(evidence(top, i))}</div>
    </div>`).join('');

  // ── AHP ──
  const A = D.ahp.matrix, names = CRIT.map(k => k.name);
  $('#m-matrix').innerHTML = `
    <thead><tr><th style="text-align:left">Row is … times as important as column</th>${CRIT.map(k => `<th>${esc(k.key)}</th>`).join('')}<th>Weight</th></tr></thead>
    <tbody>${A.map((row, i) => `<tr><th style="text-align:left">${esc(CRIT[i].key)} ${esc(names[i])}</th>${row.map((x, j) => `<td class="${i === j ? 'diag' : ''}">${ratio(x)}</td>`).join('')}<td><strong>${(WEIGHTS[i] * 100).toFixed(1)}%</strong></td></tr>`).join('')}</tbody>`;
  const chk = ahpInBrowser(A);
  $('#m-ahp-kv').innerHTML = `
    <div>λ<sub>max</sub><b>${D.ahp.lambda_max.toFixed(4)}</b></div>
    <div>Consistency index<b>${D.ahp.CI.toFixed(4)}</b></div>
    <div>Random index (n=${A.length})<b>${D.ahp.RI.toFixed(2)}</b></div>
    <div>Consistency ratio<b>${D.ahp.CR.toFixed(4)} ${D.ahp.consistent ? '<span class="ok-badge">✓ &lt; 0.10</span>' : ''}</b></div>`;
  const maxDiff = Math.max(...chk.w.map((x, i) => Math.abs(x - WEIGHTS[i])));
  const stockShare = WEIGHTS.slice(0, 3).reduce((s, x) => s + x, 0);
  $('#m-ahp-verify').innerHTML =
    `Re-computed in your browser from the matrix above: weights ${chk.w.map(x => (x * 100).toFixed(1) + '%').join(' · ')}, CR ${chk.cr.toFixed(4)} ` +
    `(${maxDiff < 1e-4 ? 'matches the pipeline exactly' : 'differs from the pipeline by ' + maxDiff.toFixed(5)}). ` +
    `Overall, stock behaviour carries <strong>${(stockShare * 100).toFixed(0)}%</strong> of the weight and news <strong>${((1 - stockShare) * 100).toFixed(0)}%</strong>.`;

  // ── TOPSIS worked example ──
  const sel = $('#m-topsis-co');
  if (!sel.options.length) {
    sel.innerHTML = cs.map(c => `<option value="${esc(c.symbol)}">${esc(c.name)} — ${fmt.score(c.score)}</option>`).join('');
    sel.addEventListener('change', renderTopsisExample);
  }
  renderTopsisExample();

  const all50 = topsis(CRIT.map(() => 50)).score;
  const oneMax = topsis(CRIT.map((_, i) => (i === 0 ? 100 : 0))).score;
  const avgOneMax = WEIGHTS[0] * 100;
  $('#m-topsis-why').innerHTML = `
    <li><strong>One severe signal is not averaged away.</strong> If only the market reaction is maxed out (100) and everything else is 0, a weighted average would give ${avgOneMax.toFixed(0)}, but TOPSIS gives <strong>${oneMax.toFixed(0)}</strong> — the company is clearly far from "safe".</li>
    <li><strong>It stays intuitive for balanced cases.</strong> Every signal at 50 gives exactly <strong>${all50.toFixed(0)}</strong>.</li>
    <li><strong>Fixed ideal points make days comparable.</strong> Classic TOPSIS uses the best and worst company of the day as the ideals, which forces someone to 100 and someone to 0 even on a calm day. Anchoring the ideals to 0 and 100 means a score of 40 today means the same as 40 last month — essential for tracking.</li>`;

  // ── Robustness, back-test, mode ──
  if (D.mcdm) {
    const cr = D.mcdm.comparison.find(x => x.name === 'CRITIC'), mc = D.mcdm.monteCarlo;
    $('#m-robust-now').innerHTML = `Today: CRITIC weights give a rank agreement of <strong>${cr.spearman.toFixed(2)}</strong> with AHP (${fmt.plural(cr.bandChanges, 'company')} change level), and across 1,000 random weightings the mean agreement is <strong>${mc.spearmanMean.toFixed(2)}</strong>.`;
  }
  const bt = D.backtest;
  $('#m-backtest-now').innerHTML = bt && bt.metrics && bt.metrics.pairwiseAccuracy
    ? `Latest run: the index was higher in the incident week for <strong>${Math.round(bt.metrics.pairwiseAccuracy.index * 100)}%</strong> of incidents and flagged ${Math.round(bt.metrics.hitRate.index * 100)}% of them (≥ ${bt.metrics.flagThreshold}), with ${Math.round(bt.metrics.falseAlarmRate.index * 100)}% false alarms on the control days.`
    : 'No back-test has been run on this data yet.';
  const stale = SERVER.info && SERVER.info.refreshOnVisit ? Math.round(SERVER.info.staleMinutes) : null;
  $('#m-mode-now').innerHTML = canWrite()
    ? '<strong>You are using the live server.</strong>'
    : SERVER.on
      ? `<strong>You are using the public read-only server.</strong> ${stale ? `It re-scores every company when someone opens the page and the data is more than ${stale} minutes old. ` : ''}Search and the headline scorer work; watchlist changes, labelling and manual re-runs are switched off.`
      : SERVER.remote
        ? '<strong>You are viewing the GitHub Pages copy with a free hosted server.</strong> The stored daily results show at once. The server then refreshes them when they are more than a few minutes old (this page updates by itself) and runs Search and the headline scorer. After a quiet spell it takes about a minute to wake up.'
        : '<strong>You are viewing the static version.</strong> Search and the server features are switched off.';

  // ── Levels, tracking, engine ──
  const counts = Object.fromEntries(LEVELS.map(l => [l, cs.filter(c => c.level === l).length]));
  $('#m-guide').innerHTML = guideHtml(counts);
  const days = D.historyDates.length;
  $('#m-tracking-now').innerHTML = `Right now the history holds <strong>${days} trading days</strong> (${fmt.date(D.historyDates[0])} – ${fmt.date(D.historyDates[days - 1])}). ` +
    `This data was generated on ${new Date(D.generatedAt).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' })} from the NSE close of ${fmt.date(D.asOf)}.`;
  const mix = D.sentimentMix || {};
  $('#m-engine').innerHTML = D.sentimentEngine === 'finbert'
    ? '<strong>Headline sentiment:</strong> scored with <strong>FinBERT</strong> (ProsusAI/finbert), a language model trained on financial news: score = P(positive) − P(negative), from −1 to +1.'
    : D.sentimentEngine === 'finbert+lexicon'
    ? `<strong>Headline sentiment:</strong> these results come from a refresh on the free server, which cannot load FinBERT. Headlines the daily FinBERT run had already scored keep their <strong>FinBERT</strong> score (${mix.finbert ?? '–'} headlines); headlines published since then are scored with the <strong>finance word list</strong> (${mix.lexicon ?? '–'} headlines) until the next daily run.`
    : '<strong>Headline sentiment:</strong> this data was scored with the built-in <strong>finance word list</strong> (terms like "probe", "penalty", "recall", "downgrade" vs. "order win", "upgrade"), because FinBERT was not installed where the pipeline ran. It is transparent but cruder — it can misread headlines. The automated daily job installs and uses FinBERT.';
}

function renderTopsisExample() {
  const c = BY_SYMBOL[$('#m-topsis-co').value] || D.companies[0];
  const r = topsis(c.criteria);
  $('#m-topsis-table').innerHTML = `
    <thead><tr><th>Signal</th><th class="r">Points</th><th class="r">r = points/100</th><th class="r">Weight w</th><th class="r">v = w·r</th><th class="r">(v − 0)²</th><th class="r">(v − w)²</th></tr></thead>
    <tbody>${CRIT.map((k, i) => `<tr><td>${esc(k.name)}</td><td class="r num">${c.criteria[i].toFixed(1)}</td><td class="r num">${(c.criteria[i] / 100).toFixed(3)}</td>
      <td class="r num">${WEIGHTS[i].toFixed(3)}</td><td class="r num">${r.v[i].toFixed(4)}</td><td class="r num">${(r.v[i] ** 2).toFixed(5)}</td><td class="r num">${((WEIGHTS[i] - r.v[i]) ** 2).toFixed(5)}</td></tr>`).join('')}</tbody>
    <tfoot><tr><td colspan="5" style="font-weight:600">D⁺ = ${r.dPos.toFixed(4)} · D⁻ = ${r.dNeg.toFixed(4)}</td><td colspan="2" class="r" style="font-weight:600">Score = ${r.score.toFixed(1)}</td></tr></tfoot>`;
  $('#m-topsis-check').textContent = `Pipeline score for ${c.name}: ${fmt.score(c.score)} (${levelOf(c.score)}). ` +
    (Math.abs(r.score - c.score) < 0.1 ? 'The browser calculation matches.' : 'Small differences come from rounding the displayed points.');
}
