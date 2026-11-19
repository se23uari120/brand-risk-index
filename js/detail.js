// =============================================================
// detail.js — the company drawer: score, plain-English reasons,
// the five signals, the TOPSIS maths, three charts, headlines.
// =============================================================

let detailSymbol = null;
let lastFocus = null;

function openDetail(symbol, { updateHash = true } = {}) {
  const c = BY_SYMBOL[symbol];
  if (!c) return;
  detailSymbol = symbol;
  if (!$('#drawer').classList.contains('open')) lastFocus = document.activeElement;

  $('#d-name').textContent = c.name;
  $('#d-sub').textContent = `NSE: ${c.symbol} · ${c.sector} · ${fmt.inr(c.stock.close)} on ${fmt.date(D.asOf)}`;
  $('#d-body').innerHTML = detailHtml(c);
  $('#d-body').scrollTop = 0;

  $('#drawer').classList.add('open');
  $('#drawer').setAttribute('aria-hidden', 'false');
  $('#scrim').classList.add('open');
  document.body.style.overflow = 'hidden';
  $('#d-close').focus({ preventScroll: true });
  if (updateHash) history.replaceState(null, '', `#company/${encodeURIComponent(symbol)}`);

  renderDetailCharts(c);
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

function detailHtml(c) {
  const s = c.stock, n = c.news;
  const contrib = contributions(c);
  const total = contrib.reduce((a, k) => a + k.contrib, 0) || 1;

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
    return { k, x: c.criteria[i], r, w: WEIGHTS[i], v, dp: v * v, dn: (WEIGHTS[i] - v) ** 2 };
  });
  const dPos = Math.sqrt(rows.reduce((a, r) => a + r.dp, 0)), dNeg = Math.sqrt(rows.reduce((a, r) => a + r.dn, 0));
  const score = 100 * dPos / (dPos + dNeg);

  const articles = n.articles.length ? `<ul class="news-list">${n.articles.map(a => {
    const url = safeUrl(a.u);
    const title = url ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(a.t)}</a>` : esc(a.t);
    return `<li class="news-item"><span class="sent ${a.l}">${a.l === 'negative' ? '− Negative' : a.l === 'positive' ? '+ Positive' : 'Neutral'}</span>
      <div>${title}<div class="news-meta">${esc(a.s)} · ${fmt.date(a.d)}${a.sc != null ? ` · sentiment ${a.sc > 0 ? '+' : ''}${a.sc.toFixed(2)}` : ''}</div></div></li>`;
  }).join('')}</ul>` : '<p class="muted small">No relevant headlines in the last two weeks.</p>';

  const rejected = Object.entries(n.rejected || {}).map(([k, v]) => `${v} ${k}`).join(', ');

  return `
    <div class="card">
      <div class="score-hero">
        <div class="hero-num">${fmt.score(c.score)}</div>
        <div class="hero-side">
          <div>${levelPill(c.level)} <span class="small muted" style="margin-left:6px">out of 100 · rank ${c.rank} of ${D.companies.length}</span></div>
          <div class="small text-2">1-week change ${delta(c.change5d)}</div>
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
      <p class="small muted" style="margin-top:6px">Biggest driver today: <strong>${esc(contrib[0].name)}</strong> (${Math.round(contrib[0].contrib / total * 100)}% of the weighted total).</p>
    </div>

    <div class="card">
      <div class="card-head"><h3>Risk score, last ${c.history.filter(v => v != null).length} trading days</h3><span class="hint">shaded: Moderate / High zones</span></div>
      <div class="chart-box h-220"><canvas id="cv-d-trend" role="img" aria-label="Daily risk score for ${esc(c.name)}"></canvas></div>
      <details class="data-view"><summary>Show as table</summary><div class="table-wrap">${dataTable(['Date', 'Score', 'Level'],
        D.historyDates.map((d, i) => [d, c.history[i]]).filter(r => r[1] != null).reverse().map(([d, v]) => [fmt.date(d), v.toFixed(1), levelOf(v)]))}</div></details>
    </div>

    <div class="card">
      <div class="card-head"><h3>Share price vs NIFTY 50</h3><span class="hint">6 months, both rebased to 100</span></div>
      <div class="legend"><span><i style="background:var(--s1)"></i>${esc(c.name)}</span><span><i style="background:var(--series-muted)"></i>NIFTY 50</span></div>
      <div class="chart-box h-220"><canvas id="cv-d-price" role="img" aria-label="Share price of ${esc(c.name)} compared with the NIFTY 50"></canvas></div>
      <p class="small muted" style="margin-top:8px">5-day move: ${esc(c.name)} ${fmt.pct(s.ret5)} · NIFTY 50 ${fmt.pct(s.idxRet5)}${s.peerRet5 != null ? ` · sector peers ${fmt.pct(s.peerRet5)}` : ''}.</p>
    </div>

    <div class="card">
      <div class="card-head"><h3>Company-specific performance</h3><span class="hint">market &amp; sector moves removed</span></div>
      <div class="chart-box h-220"><canvas id="cv-d-specific" role="img" aria-label="Cumulative company-specific return for ${esc(c.name)}"></canvas></div>
      <p class="small muted" style="margin-top:8px">This line is what is left of the share-price move after subtracting what the NIFTY 50${s.hasPeers ? ' and sector peers' : ''} explain
        (β to NIFTY ${s.beta.toFixed(2)}${s.hasPeers ? `, β to sector ${s.betaSector.toFixed(2)}` : ''}). Falls in this line are what the stock signals measure.</p>
    </div>

    <div class="card">
      <div class="card-head"><h3>Headlines, last 2 weeks</h3><span class="hint">${n.neg7d} negative · ${n.pos7d} positive in the last ${D.newsWindowDays} days</span></div>
      ${articles}
      <p class="small muted" style="margin-top:10px">Sentiment engine: ${D.sentimentEngine === 'finbert' ? 'FinBERT' : 'finance word list'}. ${n.fetched} headlines found, ${n.kept} kept as relevant${rejected ? ` (removed: ${esc(rejected)})` : ''}.</p>
    </div>

    <div class="card">
      <details class="how" open style="font-size:14px"><summary style="font-weight:600">Show the calculation (TOPSIS)</summary>
        <div class="table-wrap" style="margin-top:10px">
          <table class="data">
            <thead><tr><th>Signal</th><th class="r">Points</th><th class="r">Weight w</th><th class="r">v = w × points/100</th><th class="r">v²</th><th class="r">(w − v)²</th></tr></thead>
            <tbody>${rows.map(r => `<tr><td>${esc(r.k.name)}</td><td class="r num">${r.x.toFixed(1)}</td><td class="r num">${r.w.toFixed(3)}</td><td class="r num">${r.v.toFixed(4)}</td><td class="r num">${r.dp.toFixed(5)}</td><td class="r num">${r.dn.toFixed(5)}</td></tr>`).join('')}</tbody>
          </table>
        </div>
        <div class="formula">D⁺ = √${rows.reduce((a, r) => a + r.dp, 0).toFixed(5)} = ${dPos.toFixed(4)}   ·   D⁻ = √${rows.reduce((a, r) => a + r.dn, 0).toFixed(5)} = ${dNeg.toFixed(4)}</div>
        <div class="formula">Score = 100 × ${dPos.toFixed(4)} ÷ (${dPos.toFixed(4)} + ${dNeg.toFixed(4)}) = <strong>${score.toFixed(1)}</strong></div>
      </details>
    </div>`;
}

function renderDetailCharts(c) {
  const t = theme();
  lineChart('d-trend', $('#cv-d-trend'), {
    labels: D.historyDates, series: [{ label: 'Risk score', data: c.history, color: t.accent }],
    yMin: 0, yMax: 100, zones: true, tipFmt: v => `${v.toFixed(1)} · ${levelOf(v)}`,
  });

  const base = arr => { const b = arr.find(v => v != null); return arr.map(v => (v == null || !b ? null : +(v / b * 100).toFixed(2))); };
  lineChart('d-price', $('#cv-d-price'), {
    labels: D.chartDates,
    series: [{ label: c.name, data: base(c.closes), color: t.series[0] }, { label: 'NIFTY 50', data: base(D.benchmark.closes), color: t.seriesMuted }],
    tipFmt: v => v.toFixed(1), endLabels: false,
  });

  lineChart('d-specific', $('#cv-d-specific'), {
    labels: D.chartDates, series: [{ label: 'Company-specific', data: c.specific, color: t.accent, fill: true }],
    yFmt: v => `${v > 0 ? '+' : ''}${v}%`, tipFmt: v => `${v > 0 ? '+' : ''}${v.toFixed(1)}%`, zeroLine: true,
  });
}

function initDetail() {
  $('#d-close').addEventListener('click', closeDetail);
  $('#scrim').addEventListener('click', closeDetail);
  $('#d-compare').addEventListener('click', () => {
    const sym = detailSymbol;
    closeDetail();
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
