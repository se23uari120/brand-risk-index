// =============================================
// ACTION ENGINE TAB
// Alert feed (all companies sorted by risk) +
// donut chart (counts per risk level)
// =============================================

function initAction() {
  // --- Alert feed ---
  const sorted = [...companies].sort((a, b) => b.risk - a.risk);
  const feed   = document.getElementById('alert-feed');

  feed.innerHTML = sorted.map(c => `
    <div class="alert-item alert-${c.level.toLowerCase()}">
      <div style="flex:1">
        <div class="ai-name">
          ${c.name}
          <span class="badge ${levelBadgeClass(c.level)}" style="margin-left:6px">${c.level}</span>
        </div>
        <div class="ai-action">${c.action} · ${c.crisis}</div>
        <div style="font-size:11px;color:var(--muted);margin-top:3px">${c.id} · ${c.sector} · Reach: ${c.reach}</div>
      </div>
      <div class="ai-risk" style="color:${riskBarColor(c.risk)}">${c.risk}</div>
    </div>
  `).join('');

  // --- Donut chart ---
  const counts = {
    Low:      companies.filter(c => c.level === 'Low').length,
    Moderate: companies.filter(c => c.level === 'Moderate').length,
    Critical: companies.filter(c => c.level === 'Critical').length
  };

  createChart('donut', document.getElementById('chart-donut').getContext('2d'), {
    type: 'doughnut',
    data: {
      labels: ['Low', 'Moderate', 'Critical'],
      datasets: [{
        data: [counts.Low, counts.Moderate, counts.Critical],
        backgroundColor: [COLORS.low, COLORS.moderate, COLORS.critical],
        borderColor: '#1c2128',
        borderWidth: 3,
        hoverOffset: 4
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: '68%',
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#1c2128',
          borderColor: '#30363d',
          borderWidth: 1,
          titleColor: '#e6edf3',
          bodyColor: '#8b949e',
          callbacks: { label: ctx => ` ${ctx.label}: ${ctx.raw} companies` }
        }
      }
    }
  });

  // --- Custom donut legend ---
  const legendEl = document.getElementById('donut-legend');
  const legendItems = [
    { label: 'Low',      count: counts.Low,      color: COLORS.low },
    { label: 'Moderate', count: counts.Moderate, color: COLORS.moderate },
    { label: 'Critical', count: counts.Critical, color: COLORS.critical }
  ];
  legendEl.innerHTML = legendItems.map(l => `
    <div style="display:flex;align-items:center;gap:5px">
      <span style="width:10px;height:10px;border-radius:2px;background:${l.color};display:inline-block"></span>
      <span style="font-size:12px;color:var(--muted)">${l.label}</span>
      <span style="font-size:12px;font-weight:600;color:var(--text)">${l.count}</span>
    </div>
  `).join('');
}

// Register with nav
tabInits['action'] = initAction;

