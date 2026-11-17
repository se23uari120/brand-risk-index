// =============================================
// MCDM TAB — AHP weights & consistency (live from the API),
// expert-vs-objective (CRITIC) weights, and sensitivity analysis.
// Falls back to the static HTML when the backend is not running.
// =============================================

const SHORT_C = ['C1', 'C2', 'C3', 'C4'];

function pct(x, d = 0) { return (x * 100).toFixed(d) + '%'; }

async function initMcdm() {
  if (!liveApiAvailable()) {
    ['mcdm-critic', 'mcdm-sensitivity'].forEach(id => {
      document.getElementById(id).textContent = 'Start the backend (start.bat) to compute this from live data.';
    });
    return;
  }
  loadAhpPanel();
  loadCriticPanel();
  loadSensitivityPanel();
  const slider = document.getElementById('mcdm-alpha');
  slider.addEventListener('input', () => { document.getElementById('mcdm-alpha-val').textContent = slider.value; });
  slider.addEventListener('change', loadCriticPanel);
}

async function loadAhpPanel() {
  try {
    const a = await fetch('/api/mcdm/ahp').then(r => r.json());
    const keys = ['C1_severity', 'C2_reach', 'C3_recoverability', 'C4_criticality'];
    const names = ['Severity', 'Reach', 'Recoverability', 'Criticality'];
    const w = keys.map(k => a.weights[k]);
    AHP_W = w;
    document.getElementById('mcdm-weight-rows').innerHTML = keys.map((k, i) => `
      <tr><td><b style="color:var(--accent)">${SHORT_C[i]}</b></td><td>${names[i]}</td>
        <td><strong>${w[i].toFixed(4)}</strong></td>
        <td><div class="hbar-track"><div class="hbar" style="width:${(w[i] / w[0] * 100).toFixed(0)}%"></div></div></td></tr>`).join('');
    document.getElementById('mcdm-consistency').innerHTML =
      `λ<sub>max</sub> = ${a.lambda_max.toFixed(3)} · CI = ${a.consistency_index.toFixed(4)} · ` +
      `CR = ${a.consistency_ratio.toFixed(4)} ${a.acceptable ? '&lt; 0.10 — consistent' : '≥ 0.10 — revise the matrix'}`;
    document.getElementById('mcdm-weight-note').innerHTML = a.weights_match_config
      ? 'These computed weights are the ones the engine uses; config.py now lists the same values (the old README figures 0.35 / 0.28 / 0.22 / 0.15 in report Table IV were corrected).'
      : '<span style="color:var(--critical)">config.py weights differ from the computed weights.</span>';
    document.querySelectorAll('.mcdm-wlist').forEach(el => { el.textContent = '[' + w.map(x => x.toFixed(4)).join(', ') + ']'; });
    document.getElementById('mcdm-weights-inline').textContent = ' Weights in use: ' + w.map((x, i) => `${SHORT_C[i]} ${x.toFixed(3)}`).join(' · ') + '.';
    document.getElementById('mcdm-halflife').textContent = a.scoring.decay_half_life_hours;
    document.getElementById('mcdm-prior').textContent = a.scoring.severity_prior;
    document.getElementById('mcdm-sectors').innerHTML = Object.entries(a.scoring.sector_sensitivity)
      .sort((x, y) => y[1] - x[1])
      .map(([k, v]) => `<span class="chip">${escapeHtml(k)} <b class="chip-strong">${v.toFixed(2)}</b></span>`).join('');
  } catch (e) { /* keep static values */ }
}

async function loadCriticPanel() {
  const box = document.getElementById('mcdm-critic');
  const alpha = document.getElementById('mcdm-alpha').value;
  try {
    const r = await fetch('/api/mcdm/weights?alpha=' + alpha);
    if (!r.ok) throw new Error((await r.json()).detail);
    const d = await r.json();
    const rows = d.companies.map(n => ({ n, a: d.ahp.index[n], c: d.critic.index[n], m: d.combined.index[n] }))
      .sort((x, y) => y.a - x.a);
    const rank = key => {
      const sorted = [...rows].sort((x, y) => y[key] - x[key]);
      return Object.fromEntries(sorted.map((r, i) => [r.n, i + 1]));
    };
    const ra = rank('a'), rc = rank('c'), rm = rank('m');
    const cell = (v, r) => `<td class="num" style="color:${riskBarColor(v)}">${v.toFixed(1)} <span style="color:var(--muted);font-size:10px">#${r}</span></td>`;
    box.innerHTML = `
      <table class="data-table">
        <thead><tr><th>Weights</th>${SHORT_C.map(c => `<th class="num">${c}</th>`).join('')}<th class="num">Spearman vs AHP</th></tr></thead>
        <tbody>
          <tr><td>AHP (expert)</td>${d.ahp.weights.map(w => `<td class="num">${w.toFixed(3)}</td>`).join('')}<td class="num">1.000</td></tr>
          <tr><td>CRITIC (objective)</td>${d.critic.weights.map(w => `<td class="num">${w.toFixed(3)}</td>`).join('')}<td class="num">${d.critic.spearman_vs_ahp.toFixed(3)}</td></tr>
          <tr><td>Combined (${d.alpha} AHP)</td>${d.combined.weights.map(w => `<td class="num">${w.toFixed(3)}</td>`).join('')}<td class="num">${d.combined.spearman_vs_ahp.toFixed(3)}</td></tr>
        </tbody>
      </table>
      <div style="font-size:11px;color:var(--muted);margin:8px 0 12px">
        CRITIC gives more weight to criteria that vary more across companies and are less correlated with the others
        (σ = ${d.critic_detail.sigma.map(x => x.toFixed(2)).join(' / ')}). C3 and C4 are calculated from C1, so they are highly
        correlated with it (report Sec. VIII, "derived criteria"); CRITIC partly corrects for that redundancy.
      </div>
      <div style="max-height:320px;overflow:auto">
      <table class="data-table">
        <thead><tr><th>Company</th><th class="num">AHP index</th><th class="num">CRITIC index</th><th class="num">Combined</th></tr></thead>
        <tbody>${rows.map(r => `<tr><td>${escapeHtml(r.n)}</td>${cell(r.a, ra[r.n])}${cell(r.c, rc[r.n])}${cell(r.m, rm[r.n])}</tr>`).join('')}</tbody>
      </table></div>`;
  } catch (e) {
    box.textContent = 'Could not compute weights: ' + e.message;
  }
}

async function loadSensitivityPanel() {
  const box = document.getElementById('mcdm-sensitivity');
  try {
    const r = await fetch('/api/mcdm/sensitivity');
    if (!r.ok) throw new Error((await r.json()).detail);
    const d = await r.json();
    const mc = d.monte_carlo;
    const j = d.judgements;
    const minRho = Math.min(...j.map(x => x.spearman));
    const maxBand = Math.max(...j.map(x => x.band_changes));
    const oat = d.one_at_a_time;
    const oatWorst = oat.reduce((a, b) => (b.spearman < a.spearman ? b : a));

    box.innerHTML = `
      <div class="grid-4" style="margin-bottom:14px">
        ${miniStat('Mean rank correlation', mc.spearman_mean.toFixed(3), `${mc.draws} random weight sets (5th pct ${mc.spearman_p5.toFixed(3)})`)}
        ${miniStat('Judgement changes', `${j.length}`, `each pairwise judgement ±1 Saaty step · lowest ρ ${minRho.toFixed(3)}`)}
        ${miniStat('Max band changes', `${maxBand}`, 'companies changing band under any single judgement change')}
        ${miniStat('Worst ±50% weight change', oatWorst.spearman.toFixed(3), `ρ when ${oatWorst.criterion} weight ${oatWorst.change_pct > 0 ? '+' : ''}${oatWorst.change_pct}%`)}
      </div>

      <div style="font-size:12px;font-weight:600;margin-bottom:6px">Index range per company under weight uncertainty (5–95%, Monte Carlo)</div>
      <div class="chart-wrap" style="height:${Math.max(180, mc.companies.length * 22)}px"><canvas id="chart-sens-mc"></canvas></div>

      <div class="grid-auto" style="margin-top:14px">
        <div>
          <div style="font-size:12px;font-weight:600;margin-bottom:6px">Pairwise-judgement perturbation</div>
          <div style="max-height:300px;overflow:auto">
          <table class="data-table">
            <thead><tr><th>Judgement</th><th>Change</th><th class="num">CR</th><th class="num">ρ</th><th class="num">Band changes</th><th class="num">Max Δ index</th></tr></thead>
            <tbody>${j.map(x => `<tr><td>${x.judgement}</td><td>${x.from} → ${x.to}</td>
              <td class="num" style="color:${x.consistent ? 'inherit' : 'var(--critical)'}">${x.CR.toFixed(3)}</td>
              <td class="num">${x.spearman.toFixed(3)}</td><td class="num">${x.band_changes}</td><td class="num">${x.max_index_change.toFixed(1)}</td></tr>`).join('')}</tbody>
          </table></div>
        </div>
        <div>
          <div style="font-size:12px;font-weight:600;margin-bottom:6px">One-at-a-time weight changes</div>
          <div style="max-height:300px;overflow:auto">
          <table class="data-table">
            <thead><tr><th>Criterion</th><th class="num">Change</th><th class="num">ρ</th><th class="num">Band changes</th><th class="num">Max Δ index</th></tr></thead>
            <tbody>${oat.map(x => `<tr><td>${x.criterion}</td><td class="num">${x.change_pct > 0 ? '+' : ''}${x.change_pct}%</td>
              <td class="num">${x.spearman.toFixed(3)}</td><td class="num">${x.band_changes}</td><td class="num">${x.max_index_change.toFixed(1)}</td></tr>`).join('')}</tbody>
          </table></div>
        </div>
      </div>
      <div style="font-size:11px;color:var(--muted);margin-top:10px">
        ρ = Spearman rank correlation with the base ranking (1 = identical order). Computed on the ${d.companies} companies in the latest run.
        Band stability per company: ${mc.companies.map(c => `${escapeHtml(c.name)} ${pct(c.band_stability)}`).join(' · ')}.
      </div>`;

    const labels = mc.companies.map(c => c.name);
    createChart('sens-mc', document.getElementById('chart-sens-mc').getContext('2d'), {
      type: 'bar',
      data: {
        labels,
        datasets: [
          { label: '5–95% range', data: mc.companies.map(c => [c.p5, c.p95]),
            backgroundColor: mc.companies.map(c => riskBarColor(c.base_index) + '66'), borderRadius: 3, barThickness: 10 },
          { type: 'scatter', label: 'AHP weights', data: mc.companies.map(c => ({ x: c.base_index, y: c.name })),
            backgroundColor: COLORS.text, pointRadius: 3 }
        ]
      },
      options: {
        indexAxis: 'y', responsive: true, maintainAspectRatio: false,
        plugins: { legend: { labels: { color: COLORS.tick, font: { size: 11 } } } },
        scales: {
          x: { min: 0, max: 100, grid: { color: COLORS.grid }, ticks: { color: COLORS.tick } },
          y: { type: 'category', labels, grid: { display: false }, ticks: { color: COLORS.tick, font: { size: 11 } } }
        }
      }
    });
  } catch (e) {
    box.textContent = 'Could not run the sensitivity analysis: ' + e.message;
  }
}

function miniStat(label, value, sub) {
  return `<div style="border:1px solid var(--border);border-radius:6px;padding:10px">
    <div class="stat-label">${label}</div>
    <div style="font-size:20px;font-weight:700;margin-top:4px">${value}</div>
    <div style="font-size:11px;color:var(--muted);margin-top:2px">${sub}</div></div>`;
}

tabInits['mcdm'] = initMcdm;
