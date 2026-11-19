// =============================================================
// validation.js — the Validation tab: does the index work?
//   • back-test on documented incidents (stored results; re-run on the server)
//   • sentiment check against human labels (labelling needs the server)
//   • one-headline scorer (server)
//   • news-source comparison (from this week's headlines)
// =============================================================

const METHOD_NAMES = { index: 'Risk index (stock + news)', stockOnly: 'Stock signals only', newsOnly: 'News signals only',
  sentimentOnly: 'Average sentiment only', mentionVolume: 'Number of headlines' };
let labelQueue = [], btPoll = null;

function renderValidation() {
  renderBacktest(D.backtest);
  renderEvaluation(D.evaluation);
  renderSources();
  $$('.server-only').forEach(el => { el.hidden = !SERVER.on; });
  $$('.static-only').forEach(el => { el.hidden = SERVER.on; });
}

// ── back-test ──────────────────────────────────────────────────────────────
function renderBacktest(bt) {
  if (!bt || !bt.rows || !bt.metrics || !bt.metrics.pairwiseAccuracy) {     // none yet, or an old-format file
    $('#bt-body').innerHTML = `<p class="muted">No back-test results yet. Run <code>py -3 backend/run_pipeline.py --backtest</code>${SERVER.on ? ' or press “Run back-test”' : ''}.</p>`;
    return;
  }
  const m = bt.metrics;
  const pct = x => (x == null ? '–' : Math.round(x * 100) + '%');
  $('#bt-meta').textContent = `${m.incidents} incidents · run ${new Date(bt.runAt).toLocaleDateString('en-IN', { dateStyle: 'medium' })} · sentiment: ${bt.sentimentEngine === 'finbert' ? 'FinBERT' : 'word list'}`;
  $('#bt-body').innerHTML = `
    <div class="table-wrap"><table class="data">
      <thead><tr><th>Method</th><th class="r" title="Share of incidents scored riskier in the incident week than 60 days earlier">Incident &gt; control</th>
        <th class="r" title="Incident week reaches Moderate or High (score ≥ ${m.flagThreshold})">Hit rate</th>
        <th class="r" title="Control day reaches Moderate or High">False alarms</th><th class="r">Mean: incident</th><th class="r">Mean: control</th></tr></thead>
      <tbody>${Object.keys(METHOD_NAMES).map(k => `<tr${k === 'index' ? ' style="font-weight:600"' : ''}><td>${METHOD_NAMES[k]}</td>
        <td class="r num">${pct(m.pairwiseAccuracy[k])}</td><td class="r num">${pct(m.hitRate[k])}</td><td class="r num">${pct(m.falseAlarmRate[k])}</td>
        <td class="r num">${m.mean[k].incident}</td><td class="r num">${m.mean[k].control}</td></tr>`).join('')}</tbody>
    </table></div>
    <div class="chart-box section-gap" id="bt-box"><canvas id="chart-bt" role="img" aria-label="Risk index on each incident day and its control day"></canvas></div>
    <div class="legend" style="margin-top:6px"><span><i class="box" style="background:var(--s1)"></i>Incident week</span><span><i class="box" style="background:var(--series-muted)"></i>Control (60 days earlier)</span></div>
    <div class="table-wrap section-gap"><table class="data">
      <thead><tr><th>Company</th><th>Event</th><th class="r">Incident</th><th class="r">Control</th><th class="r">Shares vs expected (5 d)</th><th>Most negative headline</th></tr></thead>
      <tbody>${bt.rows.map(r => {
        const top = (r.incident.top || [])[0];
        const url = top && safeUrl(top.u);
        return `<tr><td><strong>${esc(r.company)}</strong><div class="co-sub">${fmt.date(r.date)}${r.listed ? '' : ' · not listed (news only)'}</div></td>
          <td class="small text-2" style="min-width:200px">${esc(r.event)}</td>
          <td class="r">${meterInline(r.incident.index)}</td><td class="r">${meterInline(r.control.index)}</td>
          <td class="r num">${r.incident.excess5 != null ? fmt.pct(r.incident.excess5) : '–'}</td>
          <td class="small" style="min-width:220px">${top ? (url ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(top.t)}</a>` : esc(top.t)) + ` <span class="muted">(${esc(top.s)})</span>` : '<span class="muted">no headlines found</span>'}</td></tr>`;
      }).join('')}</tbody></table></div>`;
  $('#bt-box').style.height = (bt.rows.length * 30 + 50) + 'px';
  pairedBarChart('bt', $('#chart-bt'), {
    labels: bt.rows.map(r => `${r.company} (${r.date.slice(0, 4)})`),
    a: bt.rows.map(r => r.incident.index), b: bt.rows.map(r => r.control.index), aLabel: 'Incident week', bLabel: 'Control',
  });
}

function meterInline(v) {
  return `<span class="num" style="font-weight:600">${v.toFixed(1)}</span> ${levelPill(levelOf(v))}`;
}

async function runBacktestNow() {
  const btn = $('#bt-run');
  btn.disabled = true;
  try { await getJSON('/api/backtest/run', { method: 'POST' }); } catch (e) { alert(e.message); btn.disabled = false; return; }
  clearInterval(btPoll);
  btPoll = setInterval(async () => {
    const r = await getJSON('/api/backtest').catch(() => null);
    if (!r) return;
    const st = r.state;
    btn.textContent = st.running ? `Running… ${st.progress}/${st.total}${st.current ? ' · ' + st.current : ''}` : 'Run back-test';
    if (!st.running) {
      clearInterval(btPoll); btn.disabled = false;
      if (r.results) { D.backtest = r.results; renderBacktest(r.results); }
    }
  }, 2500);
}

// ── sentiment check ────────────────────────────────────────────────────────
function renderEvaluation(ev) {
  const box = $('#eval-results');
  if (!ev || !ev.labelled) {
    box.innerHTML = `<p class="muted small">No headlines labelled yet.${SERVER.on ? ' Label a few above, then press “Show results”.' : ' Labelling needs the Python server (start.bat).'}</p>`;
    return;
  }
  const eng = ev.engines || {};
  const names = { lexicon: 'Finance word list', finbert: 'FinBERT' };
  const main = eng.finbert ? 'finbert' : 'lexicon';
  const cm = eng[main].confusion, cls = ['negative', 'neutral', 'positive'];
  box.innerHTML = `
    <p class="small text-2">${ev.labelled} labelled headlines (${ev.goldDistribution.negative} negative · ${ev.goldDistribution.neutral} neutral · ${ev.goldDistribution.positive} positive).
      The sample is balanced by the model's prediction, so accuracy here is not the accuracy on everyday news.</p>
    <table class="data" style="margin-top:8px"><thead><tr><th>Engine</th><th class="r">Accuracy</th><th class="r">Macro-F1</th><th class="r">F1 negative</th><th class="r">F1 neutral</th><th class="r">F1 positive</th></tr></thead>
      <tbody>${Object.entries(eng).map(([k, r]) => `<tr><td>${names[k] || k}</td><td class="r num">${Math.round(r.accuracy * 100)}%</td><td class="r num">${r.macroF1.toFixed(2)}</td>
        ${cls.map(c => `<td class="r num">${r.perClass[c].f1.toFixed(2)}</td>`).join('')}</tr>`).join('')}
        <tr><td class="muted">Always guessing the most common label</td><td class="r num muted">${Math.round(ev.majorityBaseline * 100)}%</td><td colspan="4"></td></tr></tbody></table>
    <h4 style="margin:14px 0 6px;font-size:14px">${names[main]}: what it predicted for each human label</h4>
    <table class="matrix" style="max-width:420px"><thead><tr><th>Human ↓ / model →</th>${cls.map(c => `<th>${c}</th>`).join('')}</tr></thead>
      <tbody>${cls.map(g => `<tr><th>${g}</th>${cls.map(p => `<td class="${g === p ? 'diag-ok' : ''}">${cm[g][p]}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
}

async function loadLabelQueue() {
  try {
    const r = await getJSON('/api/eval/sample?n=15');
    labelQueue = r.items;
    $('#label-count').textContent = `${r.labelled} labelled so far`;
    showNextLabel();
  } catch (e) { $('#label-card').innerHTML = `<p class="muted">${esc(e.message)}</p>`; }
}
function showNextLabel() {
  const h = labelQueue[0];
  $('#label-card').innerHTML = h ? `
    <p class="small muted">${esc(h.company)}${h.outlet ? ' · ' + esc(h.outlet) : ''}</p>
    <p style="font-size:16px;margin:6px 0 12px;color:var(--text)">“${esc(h.title)}”</p>
    <p class="small text-2" style="margin-bottom:8px">Is this headline negative, neutral or positive for the company's reputation?</p>
    <div class="picker">${['negative', 'neutral', 'positive', 'skip'].map(l => `<button class="btn${l === 'skip' ? '' : ' label-' + l}" type="button" data-label="${l}">${l[0].toUpperCase() + l.slice(1)}</button>`).join('')}</div>`
    : '<p class="muted">All sampled headlines are labelled. Press “New sample” for more.</p>';
}
async function submitLabel(label) {
  const h = labelQueue.shift();
  if (!h) return;
  try {
    const r = await getJSON('/api/eval/label', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: h.title, label, company: h.company }) });
    $('#label-count').textContent = `${r.labelled} labelled so far`;
  } catch (e) { alert(e.message); }
  showNextLabel();
}

// ── one-headline scorer ────────────────────────────────────────────────────
async function scoreHeadline() {
  const text = $('#hs-input').value.trim();
  if (!text) return;
  $('#hs-out').innerHTML = '<p class="muted small">Scoring…</p>';
  try {
    const r = await getJSON('/api/score-headline', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }) });
    $('#hs-out').innerHTML = `<p style="margin-top:8px">${sentimentTag(r.label)} <strong class="num">${r.score > 0 ? '+' : ''}${r.score.toFixed(2)}</strong>
      <span class="muted small">(${r.engine === 'finbert' ? 'FinBERT' : 'word list'})</span> · issue type ${issueTag(r.category)}${r.keyword ? ` <span class="muted small">matched “${esc(r.keyword)}”</span>` : ''}
      ${r.regulators.length ? ` · regulators: ${esc(r.regulators.join(', '))}` : ''}</p>`;
  } catch (e) { $('#hs-out').innerHTML = `<p class="muted small">${esc(e.message)}</p>`; }
}

// ── sources ────────────────────────────────────────────────────────────────
function renderSources() {
  const rows = (D.sources || []).slice(0, 15);
  if (!rows.length) { $('#src-table').innerHTML = '<p class="muted small">No source data.</p>'; return; }
  const total = (D.sources || []).reduce((s, r) => s + r.headlines, 0);
  $('#src-meta').textContent = `${fmt.plural(D.sources.length, 'outlet')} carried ${total} relevant headlines in the last ${D.newsWindowDays} days`;
  $('#src-table').innerHTML = `<table class="data"><thead><tr><th>Outlet</th><th class="r">Headlines</th><th class="r">Companies</th><th class="r">Negative</th><th class="r">Average sentiment</th></tr></thead>
    <tbody>${rows.map(r => `<tr><td>${esc(r.outlet)}</td><td class="r num">${r.headlines}</td><td class="r num">${r.companies}</td>
      <td class="r num">${Math.round(r.negative / r.headlines * 100)}%</td><td class="r num">${r.avgSentiment > 0 ? '+' : ''}${r.avgSentiment.toFixed(2)}</td></tr>`).join('')}</tbody></table>`;
}

function initValidation() {
  $('#bt-run').addEventListener('click', runBacktestNow);
  $('#label-card').addEventListener('click', e => { const b = e.target.closest('button[data-label]'); if (b) submitLabel(b.dataset.label); });
  $('#label-new').addEventListener('click', loadLabelQueue);
  $('#label-results').addEventListener('click', async () => {
    try { const ev = await getJSON('/api/eval/metrics'); D.evaluation = ev; renderEvaluation(ev); } catch (e) { alert(e.message); }
  });
  $('#hs-go').addEventListener('click', scoreHeadline);
  $('#hs-input').addEventListener('keydown', e => { if (e.key === 'Enter') scoreHeadline(); });
}
