// =============================================================
// detail.js — the company drawer: score, plain-English reasons,
// the five signals, three charts, headlines and the TOPSIS maths.
// The same renderer is reused for Company Search results
// (detailHtml(c, ctx, prefix) + renderDetailCharts(c, ctx, prefix)).
// =============================================================

let detailSymbol = null;
let lastFocus = null;

// Dates/benchmark the record's arrays line up with (search results bring their own).
function defaultCtx() {
  return { historyDates: D.historyDates, chartDates: D.chartDates, benchmarkCloses: D.benchmark.closes };
}

function openDetail(symbol, { updateHash = true } = {}) {
  const c = BY_SYMBOL[symbol];
  if (!c) return;
  detailSymbol = symbol;
  if (!$('#drawer').classList.contains('open')) lastFocus = document.activeElement;

  $('#d-name').textContent = c.name;
  $('#d-sub').textContent = `NSE: ${c.symbol} · ${c.sector} · ${fmt.inr(c.stock.close)} on ${fmt.date(c.asOf || D.asOf)}`;
  $('#d-body').innerHTML = detailHtml(c, defaultCtx(), 'd');
  $('#d-body').scrollTop = 0;

  $('#drawer').classList.add('open');
  $('#drawer').setAttribute('aria-hidden', 'false');
  $('#scrim').classList.add('open');
  document.body.style.overflow = 'hidden';
  $('#d-close').focus({ preventScroll: true });
  if (updateHash) history.replaceState(null, '', `#company/${encodeURIComponent(symbol)}`);

  renderDetailCharts(c, defaultCtx(), 'd');
}

function closeDetail({ updateHash = true } = {}) {
  if (!detailSymbol) return;
  detailSymbol = null;
  $('#drawer').classList.remove('open');
  $('#drawer').setAttribute('aria-hidden', 'true');
  $('#scrim').classList.remove('open');
  document.body.style.overflow = '';
  ['d-trend', 'd-price', 'd-specific'].forEach(destroyChart);
  if (updateHash) history.replaceState(null, '', `#${currentView}`);
  if (lastFocus && lastFocus.focus) lastFocus.focus({ preventScroll: true });
}

function sentimentTag(l) {
  return `<span class="sent ${l}">${l === 'negative' ? '− Negative' : l === 'positive' ? '+ Positive' : 'Neutral'}</span>`;
}

function headlineList(articles, empty = 'No relevant headlines in the last two weeks.') {
  if (!articles.length) return `<p class="muted small">${empty}</p>`;
  return `<ul class="news-list">${articles.map(a => {
    const url = safeUrl(a.u);
    const title = url ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(a.t)}</a>` : esc(a.t);
    return `<li class="news-item">${sentimentTag(a.l)}
      <div>${title}<div class="news-meta">${esc(a.s)} · ${fmt.date(a.d)}${a.sc != null ? ` · sentiment ${a.sc > 0 ? '+' : ''}${a.sc.toFixed(2)}` : ''}
      ${a.c && a.c !== 'General Coverage' ? ` · ${issueTag(a.c, true)}` : ''}</div></div></li>`;
  }).join('')}</ul>`;
}

function detailHtml(c, ctx, prefix) {
  const s = c.stock, n = c.news;
  const contrib = contributions(c);
  const total = contrib.reduce((a, k) => a + k.contrib, 0) || 1;
  const issue = c.issue || { dominant: NO_ISSUE, categories: [], regulators: {} };

  const signals = CRIT.map((k, i) => `
    <div class="signal">
      <div class="signal-title">${esc(k.name)} <span class="signal-tag">${esc(k.group)}</span>
        <span class="signal-weight">weight ${(WEIGHTS[i] * 100).toFixed(0)}%</span></div>
      <div class="signal-val">${c.criteria[i].toFixed(0)}</div>
      <div class="meter" role="img" aria-label="${esc(k.name)}: ${c.criteria[i].toFixed(0)} of 100"><span style="width:${Math.max(1, c.criteria[i])}%"></span></div>
      <div class="signal-ev">${esc(evidence(c, i))}</div>
      <details class="how"><summary>How is this measured?</summary>
        <p><strong>${esc(k.question)}</strong> ${esc(k.how)}</p>
        <div class="formula">${esc(k.formula)}</div>
        <p class="muted">${esc(k.scale)}</p>
      </details>
    </div>`).join('');

  // TOPSIS working for this company
  const rows = CRIT.map((k, i) => {
    const r = c.criteria[i] / 100, v = WEIGHTS[i] * r;
    return { k, x: c.criteria[i], w: WEIGHTS[i], v, dp: v * v, dn: (WEIGHTS[i] - v) ** 2 };
  });
  const sumP = rows.reduce((a, r) => a + r.dp, 0), sumN = rows.reduce((a, r) => a + r.dn, 0);
  const dPos = Math.sqrt(sumP), dNeg = Math.sqrt(sumN);
  const score = 100 * dPos / (dPos + dNeg);

  const rejected = Object.entries(n.rejected || {}).map(([k, v]) => `${v} ${k}`).join(', ');
  const regs = Object.entries(issue.regulators || {}).map(([k, v]) => `${esc(k)}${v > 1 ? ` (${v})` : ''}`).join(', ');
  const rankText = c.rank ? ` · rank ${c.rank} of ${D.companies.length}` : '';
  const histN = c.history.filter(v => v != null).length;

  return `
    <div class="card">
      <div class="score-hero">
        <div class="hero-num">${fmt.score(c.score)}</div>
        <div class="hero-side">
          <div>${levelPill(c.level)} <span class="small muted" style="margin-left:6px">out of 100${rankText}</span></div>
          <div class="small text-2">1-week change ${delta(c.change5d)}${c.range ? ` · 90% range <strong class="num">${c.range[0].toFixed(0)}–${c.range[1].toFixed(0)}</strong>` : ''}</div>
          ${issue.dominant !== NO_ISSUE ? `<div class="small text-2">Main issue in the news: ${issueTag(issue.dominant)}${regs ? ` · regulators named: ${regs}` : ''}</div>` : ''}
        </div>
      </div>
      <div style="margin-top:12px">${meter(c.score, c.level, false)}</div>
    </div>

    <div class="card">
      <div class="card-head"><h3>Why this score</h3></div>
      <ul class="reasons">${reasons(c).map(r => `<li>${r}</li>`).join('')}</ul>
      <p class="callout" style="margin-top:12px"><strong>${c.level}:</strong> ${esc(D.guidance[c.level])}</p>
    </div>

    <div class="card">
      <div class="card-head"><h3>The five signals</h3><span class="hint">risk points 0–100</span></div>
      ${signals}
      <p class="small muted" style="margin-top:6px">Biggest driver: <strong>${esc(contrib[0].name)}</strong> (${Math.round(contrib[0].contrib / total * 100)}% of the weighted total).</p>
    </div>

    <div class="card">
      <div class="card-head"><h3>Risk score, last ${histN} trading days</h3><span class="hint">shaded: Moderate / High zones</span></div>
      <div class="chart-box h-220"><canvas id="cv-${prefix}-trend" role="img" aria-label="Daily risk score for ${esc(c.name)}"></canvas></div>
      <details class="data-view"><summary>Show as table</summary><div class="table-wrap">${dataTable(['Date', 'Score', 'Level'],
        ctx.historyDates.map((d, i) => [d, c.history[i]]).filter(r => r[1] != null).reverse().map(([d, v]) => [fmt.date(d), v.toFixed(1), levelOf(v)]))}</div></details>
    </div>

    <div class="card">
      <div class="card-head"><h3>Share price vs NIFTY 50</h3><span class="hint">6 months, both rebased to 100</span></div>
      <div class="legend"><span><i style="background:var(--s1)"></i>${esc(c.name)}</span><span><i style="background:var(--series-muted)"></i>NIFTY 50</span></div>
      <div class="chart-box h-220"><canvas id="cv-${prefix}-price" role="img" aria-label="Share price of ${esc(c.name)} compared with the NIFTY 50"></canvas></div>
      <p class="small muted" style="margin-top:8px">5-day move: ${esc(c.name)} ${fmt.pct(s.ret5)} · NIFTY 50 ${fmt.pct(s.idxRet5)}${s.peerRet5 != null ? ` · sector peers ${fmt.pct(s.peerRet5)}` : ''}.</p>
    </div>

    <div class="card">
      <div class="card-head"><h3>Company-specific performance</h3><span class="hint">market &amp; sector moves removed</span></div>
      <div class="chart-box h-220"><canvas id="cv-${prefix}-specific" role="img" aria-label="Cumulative company-specific return for ${esc(c.name)}"></canvas></div>
      <p class="small muted" style="margin-top:8px">This line is what is left of the share-price move after subtracting what the NIFTY 50${s.hasPeers ? ' and sector peers' : ''} explain
        (β to NIFTY ${s.beta.toFixed(2)}${s.hasPeers ? `, β to sector ${s.betaSector.toFixed(2)}` : ''}). Falls in this line are what the stock signals measure.</p>
    </div>

    <div class="card">
      <div class="card-head"><h3>Headlines, last 2 weeks</h3><span class="hint">${n.neg7d} negative · ${n.pos7d} positive in the last ${D.newsWindowDays} days${n.outlets7d ? ` · ${fmt.plural(n.outlets7d, 'outlet')}` : ''}</span></div>
      ${issue.categories && issue.categories.length ? `<p class="small text-2" style="margin-bottom:8px">Negative coverage by issue: ${issue.categories.map(x => `${issueTag(x.category, true)} ${Math.round(x.share * 100)}%`).join(' &nbsp;')}</p>` : ''}
      ${headlineList(n.articles)}
      <p class="small muted" style="margin-top:10px">Sentiment engine: ${D.sentimentEngine === 'finbert' ? 'FinBERT' : 'finance word list'}. ${n.fetched} headlines found, ${n.kept} kept as relevant${rejected ? ` (removed: ${esc(rejected)})` : ''}.</p>
    </div>

    <div class="card">
      <details class="how" style="font-size:14px"><summary style="font-weight:600">Show the calculation (TOPSIS)</summary>
        <div class="table-wrap" style="margin-top:10px">
          <table class="data">
            <thead><tr><th>Signal</th><th class="r">Points</th><th class="r">Weight w</th><th class="r">v = w × points/100</th><th class="r">v²</th><th class="r">(w − v)²</th></tr></thead>
            <tbody>${rows.map(r => `<tr><td>${esc(r.k.name)}</td><td class="r num">${r.x.toFixed(1)}</td><td class="r num">${r.w.toFixed(3)}</td><td class="r num">${r.v.toFixed(4)}</td><td class="r num">${r.dp.toFixed(5)}</td><td class="r num">${r.dn.toFixed(5)}</td></tr>`).join('')}</tbody>
          </table>
        </div>
        <div class="formula">D⁺ = √${sumP.toFixed(5)} = ${dPos.toFixed(4)}   ·   D⁻ = √${sumN.toFixed(5)} = ${dNeg.toFixed(4)}</div>
        <div class="formula">Score = 100 × ${dPos.toFixed(4)} ÷ (${dPos.toFixed(4)} + ${dNeg.toFixed(4)}) = <strong>${score.toFixed(1)}</strong></div>
        ${c.range ? `<p class="muted">The 90% range (${c.range[0].toFixed(1)}–${c.range[1].toFixed(1)}) comes from re-scoring 200 random resamples of the week's headlines: it shows how much the score depends on which stories happened to be picked up.</p>` : ''}
      </details>
    </div>`;
}

function renderDetailCharts(c, ctx, prefix) {
  const t = theme();
  lineChart(`${prefix}-trend`, $(`#cv-${prefix}-trend`), {
    labels: ctx.historyDates, series: [{ label: 'Risk score', data: c.history, color: t.accent }],
    yMin: 0, yMax: 100, zones: true, tipFmt: v => `${v.toFixed(1)} · ${levelOf(v)}`,
  });

  const base = arr => { const b = arr.find(v => v != null); return arr.map(v => (v == null || !b ? null : +(v / b * 100).toFixed(2))); };
  lineChart(`${prefix}-price`, $(`#cv-${prefix}-price`), {
    labels: ctx.chartDates,
    series: [{ label: c.name, data: base(c.closes), color: t.series[0] }, { label: 'NIFTY 50', data: base(ctx.benchmarkCloses), color: t.seriesMuted }],
    tipFmt: v => v.toFixed(1),
  });

  lineChart(`${prefix}-specific`, $(`#cv-${prefix}-specific`), {
    labels: ctx.chartDates, series: [{ label: 'Company-specific', data: c.specific, color: t.accent, fill: true }],
    yFmt: v => `${v > 0 ? '+' : ''}${v}%`, tipFmt: v => `${v > 0 ? '+' : ''}${v.toFixed(1)}%`, zeroLine: true,
  });
}

function initDetail() {
  $('#d-close').addEventListener('click', () => closeDetail());
  $('#scrim').addEventListener('click', () => closeDetail());
  $('#d-compare').addEventListener('click', () => {
    const sym = detailSymbol;
    closeDetail({ updateHash: false });
    addCompare(sym);
    showView('compare');
  });
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && detailSymbol) closeDetail();
    if (e.key === 'Tab' && detailSymbol) {           // keep focus inside the open drawer
      const f = $$('#drawer a[href], #drawer button, #drawer summary, #drawer [tabindex]:not([tabindex="-1"])').filter(el => el.offsetParent !== null);
      if (!f.length) return;
      if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
      else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
    }
  });
  // any element with data-symbol (lists on the overview) opens the drawer
  document.addEventListener('click', e => {
    const el = e.target.closest('[data-symbol]:not(tr)');
    if (el && !el.closest('#drawer')) openDetail(el.dataset.symbol);
  });
  document.addEventListener('keydown', e => {
    const el = e.target.closest && e.target.closest('[data-symbol]:not(tr)');
    if (el && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); openDetail(el.dataset.symbol); }
  });
}
