// =============================================
// MODAL — Company detail drawer
// Shows risk number, badge, crisis, action,
// FinBERT sentiment bar, vs-sector comparison,
// and a radar chart for MCDM criteria.
// =============================================

let radarChart = null;

function openModal(c) {
  // Header
  document.getElementById('modal-company-name').textContent = c.name;
  document.getElementById('modal-company-meta').textContent = `${c.id} · ${c.sector}`;

  // Risk number
  const riskEl = document.getElementById('modal-risk-num');
  riskEl.textContent  = c.risk;
  riskEl.style.color  = riskBarColor(c.risk);

  // Level badge
  document.getElementById('modal-level-badge').innerHTML =
    `<span class="badge ${levelBadgeClass(c.level)}">${c.level}</span>`;

  // Crisis & Action
  document.getElementById('modal-crisis').textContent = c.crisis;
  document.getElementById('modal-action').textContent = c.action;

  // Sentiment bar
  const sp = sentimentPct(c.sentiment);
  document.getElementById('modal-sentiment-bar').style.width = sp + '%';
  document.getElementById('modal-sentiment-val').textContent = c.sentiment.toFixed(2);

  // vs. Sector average
  const sectorCos = companies.filter(x => x.sector === c.sector);
  const avg  = sectorCos.reduce((a, b) => a + b.risk, 0) / sectorCos.length;
  const diff = (c.risk - avg).toFixed(1);
  const diffColor = diff > 0 ? COLORS.critical : COLORS.low;
  document.getElementById('modal-vs-sector').innerHTML = `
    <span style="color:var(--muted)">Sector avg: <strong style="color:var(--text)">${avg.toFixed(1)}</strong></span>
    &nbsp;·&nbsp;
    <span style="color:${diffColor}">${diff > 0 ? '+' : ''}${diff} vs. avg</span>
  `;

  // Radar chart — MCDM criteria breakdown
  const sc = getCriteriaScores(c);
  const radarCtx = document.getElementById('modal-radar').getContext('2d');
  if (radarChart) { radarChart.destroy(); radarChart = null; }
  radarChart = new Chart(radarCtx, {
    type: 'radar',
    data: {
      labels: ['C1 Severity', 'C2 Reach', 'C3 Recoverability', 'C4 Criticality'],
      datasets: [{
        label: c.name,
        data: [sc.c1, sc.c2, sc.c3, sc.c4],
        backgroundColor: 'rgba(47,129,247,0.12)',
        borderColor: COLORS.accent,
        pointBackgroundColor: COLORS.accent,
        pointRadius: 4,
        borderWidth: 2
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#1c2128',
          borderColor: '#30363d',
          borderWidth: 1,
          titleColor: '#e6edf3',
          bodyColor: '#8b949e'
        }
      },
      scales: {
        r: {
          min: 0,
          max: 100,
          backgroundColor: 'transparent',
          grid:        { color: COLORS.grid },
          angleLines:  { color: COLORS.grid },
          ticks:       { color: COLORS.tick, backdropColor: 'transparent', font: { size: 10 }, stepSize: 25 },
          pointLabels: { color: COLORS.tick, font: { size: 11 } }
        }
      }
    }
  });

  // Compare shortcut button
  const cmpBtn = document.getElementById('modal-compare-btn');
  if (cmpBtn) {
    cmpBtn.onclick = () => {
      closeModal();
      if (typeof addCompare === 'function') addCompare(c.id);
      if (typeof switchTab === 'function') switchTab('compare');
    };
  }

  document.getElementById('modal-overlay').classList.add('open');
}

function closeModal() {
  document.getElementById('modal-overlay').classList.remove('open');
  if (radarChart) { radarChart.destroy(); radarChart = null; }
}

// Wire up close triggers
document.getElementById('modal-close-btn').addEventListener('click', closeModal);
document.getElementById('modal-overlay').addEventListener('click', e => {
  if (e.target === document.getElementById('modal-overlay')) closeModal();
});

