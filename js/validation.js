// =============================================
// VALIDATION TAB — pilot back-test on documented incidents,
// hand-labelling for a FinBERT accuracy check, and a one-headline scorer.
// =============================================

let btPoll = null;
let evQueue = [];

async function initValidation() {
  if (!liveApiAvailable()) {
    document.getElementById('bt-body').textContent = 'Validation needs the backend. Start it with start.bat and open http://localhost:8000.';
    document.getElementById('ev-label-box').textContent = '—';
    return;
  }
  document.getElementById('bt-run').addEventListener('click', runBacktest);
  document.getElementById('ev-refresh').addEventListener('click', loadEvalMetrics);
  document.getElementById('tt-form').addEventListener('submit', scoreOneHeadline);
  loadBacktest();
  loadEvalSample();
  loadEvalMetrics();
}

// ── Back-test ────────────────────────────────────────────────
async function loadBacktest() {
  const box = document.getElementById('bt-body');
  const btn = document.getElementById('bt-run');
  try {
    const d = await fetch('/api/backtest').then(r => r.json());
    const st = d.state;
    if (st.running) {
      btn.disabled = true; btn.textContent = `Running… ${st.progress}/${st.total}`;
      box.innerHTML = `<div style="color:var(--muted)">Fetching and scoring ${escapeHtml(st.current || '')} (${st.progress}/${st.total})…</div>` +
        (d.results ? renderBacktest(d.results, true) : '');
      if (!btPoll) btPoll = setInterval(loadBacktest, 3000);
      return;
    }
    if (btPoll) { clearInterval(btPoll); btPoll = null; }
    btn.disabled = false; btn.textContent = d.results ? 'Run again' : 'Run back-test';
    if (!d.results) {
      box.innerHTML = `<div>No back-test has been run yet. ${d.incidents.length} documented incidents are configured
        (backend/data/incidents.json): ${d.incidents.map(i => escapeHtml(i.company)).join(', ')}.
        A run fetches about ${d.incidents.length * 4} Google News queries and takes a minute or two.</div>`;
      return;
    }
    box.innerHTML = (st.error ? `<div style="color:var(--critical)">Last run failed: ${escapeHtml(st.error)}</div>` : '') +
      renderBacktest(d.results, false);
  } catch (e) {
    box.textContent = 'Could not load the back-test: ' + e.message;
  }
}

async function runBacktest() {
  const btn = document.getElementById('bt-run');
  btn.disabled = true; btn.textContent = 'Starting…';
  await fetch('/api/backtest/run', { method: 'POST' }).catch(() => {});
  loadBacktest();
}

function renderBacktest(res, stale) {
  const m = res.metrics || {};
  if (!m.incidents) return '<div>No incidents could be scored.</div>';
  const pa = m.pairwise_accuracy, hr = m.hit_rate, fa = m.false_alarm_rate, mean = m.mean;
  const row = (label, k, hasRates) => `<tr>
      <td>${label}</td>
      <td class="num"><b>${pct(pa[k])}</b></td>
      <td class="num">${hasRates ? pct(hr[k]) : '—'}</td>
      <td class="num">${hasRates ? pct(fa[k]) : '—'}</td>
      <td class="num">${mean[k].incident} vs ${mean[k].control}</td></tr>`;
  const lv = (x) => `<span style="color:${riskBarColor(x.risk_index)};font-weight:600">${x.risk_index.toFixed(1)}</span>
      <span style="color:var(--muted);font-size:11px">${x.articles} art.</span>`;
  return `
    <div style="${stale ? 'opacity:.5' : ''}">
    <table class="data-table" style="margin-bottom:10px">
      <thead><tr><th>Method</th><th class="num">Incident &gt; control</th><th class="num">Hit rate (≥ ${m.flag_threshold})</th>
        <th class="num">False alarms (≥ ${m.flag_threshold})</th><th class="num">Mean incident vs control</th></tr></thead>
      <tbody>
        ${row('Brand Risk Index (AHP-TOPSIS)', 'risk_index', true)}
        ${row('Sentiment-only baseline', 'sentiment_only', true)}
        ${row('Mention-volume baseline', 'mention_volume', false)}
      </tbody>
    </table>
    <div style="font-size:11px;margin-bottom:12px">
      ${m.incidents} incidents · scored with ${escapeHtml(res.scorer)} · run ${new Date(res.run_at).toLocaleString()}.
      This is a pilot-scale check (report Sec. VII-C): it shows direction, not statistical significance.
      Hit rate = incident window reaches Moderate or Critical; false alarm = the control window does.
    </div>
    <div style="max-height:420px;overflow:auto">
    <table class="data-table">
      <thead><tr><th>Company · event</th><th>Date</th><th class="num">Incident index</th><th class="num">Control index</th>
        <th>Dominant issue found</th><th class="num">Sentiment-only</th></tr></thead>
      <tbody>${res.rows.map(r => `<tr title="${escapeHtml((r.incident.top[0] || {}).title || '')}">
        <td><b>${escapeHtml(r.company)}</b><div style="font-size:11px;color:var(--muted)">${escapeHtml(r.event)}</div></td>
        <td style="white-space:nowrap">${r.date}</td>
        <td class="num">${lv(r.incident)} <span class="badge ${levelBadgeClass(r.incident.level)}">${r.incident.level}</span></td>
        <td class="num">${lv(r.control)}</td>
        <td style="font-size:12px">${escapeHtml(r.incident.dominant_category || '—')}</td>
        <td class="num" style="font-size:12px">${r.incident.sentiment_only} vs ${r.control.sentiment_only}</td></tr>`).join('')}
      </tbody>
    </table></div></div>`;
}

// ── Hand-labelling ───────────────────────────────────────────
async function loadEvalSample() {
  const box = document.getElementById('ev-label-box');
  try {
    const d = await fetch('/api/eval/sample?n=15').then(r => r.json());
    evQueue = d.items;
    box.dataset.labelled = d.labelled;
    renderLabelCard();
  } catch (e) {
    box.textContent = 'Could not load headlines: ' + e.message;
  }
}

function renderLabelCard() {
  const box = document.getElementById('ev-label-box');
  const done = Number(box.dataset.labelled || 0);
  if (!evQueue.length) {
    box.innerHTML = `<div style="font-size:12px;color:var(--muted)">${done} headlines labelled.
      <button class="btn-ghost" id="ev-more">Load more headlines</button></div>`;
    document.getElementById('ev-more').addEventListener('click', loadEvalSample);
    return;
  }
  const h = evQueue[0];
  box.innerHTML = `
    <div style="font-size:11px;color:var(--muted)">${done} labelled so far · ${evQueue.length} in this batch</div>
    <div style="font-size:15px;margin:10px 0 4px;line-height:1.4">${escapeHtml(h.title)}</div>
    <div style="font-size:11px;color:var(--muted);margin-bottom:12px">${escapeHtml(h.company || '')}${h.outlet ? ' · ' + escapeHtml(h.outlet) : ''}</div>
    <div class="lbl-btns">
      <button class="btn-ghost" data-l="negative" style="border-color:${COLORS.critical};color:${COLORS.critical}">Negative</button>
      <button class="btn-ghost" data-l="neutral">Neutral</button>
      <button class="btn-ghost" data-l="positive" style="border-color:${COLORS.low};color:${COLORS.low}">Positive</button>
      <button class="btn-ghost" data-l="skip" style="flex:0">Skip</button>
    </div>`;
  box.querySelectorAll('[data-l]').forEach(b => b.addEventListener('click', () => submitLabel(h, b.dataset.l)));
}

async function submitLabel(h, label) {
  const box = document.getElementById('ev-label-box');
  box.querySelectorAll('button').forEach(b => { b.disabled = true; });
  try {
    const r = await fetch('/api/eval/label', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: h.title, label, company: h.company })
    }).then(x => x.json());
    box.dataset.labelled = r.labelled;
    evQueue.shift();
    renderLabelCard();
    if (r.labelled % 5 === 0) loadEvalMetrics();
  } catch (e) {
    box.querySelectorAll('button').forEach(b => { b.disabled = false; });
  }
}

async function loadEvalMetrics() {
  const box = document.getElementById('ev-metrics');
  box.textContent = 'Calculating…';
  try {
    const d = await fetch('/api/eval/metrics').then(r => r.json());
    if (!d.labelled) { box.textContent = 'No labels yet. Label a few headlines on the left.'; return; }
    const f = d.finbert, h = d.heuristic;
    const cls = ['negative', 'neutral', 'positive'];
    const cm = f.confusion;
    box.innerHTML = `
      <table class="data-table">
        <thead><tr><th>Scorer</th><th class="num">Accuracy</th><th class="num">Macro-F1</th>${cls.map(c => `<th class="num">F1 ${c.slice(0, 3)}</th>`).join('')}</tr></thead>
        <tbody>
          <tr><td>${d.finbert_is_model ? 'FinBERT' : 'FinBERT (not loaded — heuristic)'}</td><td class="num"><b>${pct(f.accuracy)}</b></td><td class="num">${f.macro_f1.toFixed(2)}</td>${cls.map(c => `<td class="num">${f.per_class[c].f1.toFixed(2)}</td>`).join('')}</tr>
          <tr><td>Keyword heuristic</td><td class="num">${pct(h.accuracy)}</td><td class="num">${h.macro_f1.toFixed(2)}</td>${cls.map(c => `<td class="num">${h.per_class[c].f1.toFixed(2)}</td>`).join('')}</tr>
          <tr><td>Majority-class baseline</td><td class="num">${pct(d.majority_baseline)}</td><td colspan="4"></td></tr>
        </tbody>
      </table>
      <div style="font-size:12px;font-weight:600;margin:12px 0 4px">FinBERT confusion matrix (rows = your label)</div>
      <table class="matrix-table" style="width:auto">
        <thead><tr><th></th>${cls.map(c => `<th>${c}</th>`).join('')}</tr></thead>
        <tbody>${cls.map(g => `<tr><td style="text-align:left;color:var(--muted)">${g}</td>${cls.map(p =>
          `<td class="${g === p ? 'diag' : ''}">${cm[g][p]}</td>`).join('')}</tr>`).join('')}</tbody>
      </table>
      <div style="font-size:11px;color:var(--muted);margin-top:8px">
        ${d.labelled} labelled (${d.gold_distribution.negative} neg · ${d.gold_distribution.neutral} neu · ${d.gold_distribution.positive} pos), ${d.skipped} skipped.
        Headlines are sampled in equal numbers per FinBERT prediction, so this is not accuracy on the natural news mix.
        ${d.labelled < 50 ? 'Label at least 50 for a meaningful estimate.' : ''}
      </div>
      ${d.disagreements.length ? `<details style="margin-top:8px"><summary style="cursor:pointer;font-size:12px">Disagreements (${d.disagreements.length})</summary>
        <div style="font-size:12px;margin-top:6px">${d.disagreements.map(x => `<div style="padding:4px 0;border-top:1px solid var(--border)">
          ${escapeHtml(x.title)} <span style="color:var(--muted)">— you: ${x.gold}, FinBERT: ${x.finbert} (${x.finbert_score >= 0 ? '+' : ''}${x.finbert_score.toFixed(2)})</span></div>`).join('')}</div></details>` : ''}`;
  } catch (e) {
    box.textContent = 'Could not compute metrics: ' + e.message;
  }
}

// ── One-headline scorer (report appendix: "Score one headline") ──
async function scoreOneHeadline(e) {
  e.preventDefault();
  const text = document.getElementById('tt-text').value.trim();
  const out = document.getElementById('tt-out');
  if (!text) return;
  out.textContent = 'Scoring…';
  try {
    const d = await fetch('/api/score-text', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text })
    }).then(r => r.json());
    const r = d.result;
    const col = r.label === 'negative' ? COLORS.critical : r.label === 'positive' ? COLORS.low : COLORS.tick;
    out.innerHTML = `<b style="color:${col};text-transform:uppercase">${r.label}</b>
      score ${r.score >= 0 ? '+' : ''}${r.score.toFixed(3)} ·
      P(neg) ${r.negative.toFixed(2)} · P(neu) ${r.neutral.toFixed(2)} · P(pos) ${r.positive.toFixed(2)} ·
      crisis type <span class="chip">${escapeHtml(d.crisis_category.category)}</span>
      ${d.regulators.length ? ' · regulators: ' + escapeHtml(d.regulators.join(', ')) : ''}
      <span style="color:var(--muted)">(${d.scorer})</span>`;
  } catch (err) {
    out.textContent = 'Scoring failed: ' + err.message;
  }
}

tabInits['validation'] = initValidation;
