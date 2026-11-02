// =============================================
// OVERVIEW TAB
// Charts: horizontal bar (sector avg risk) +
//         stacked bar (risk distribution) +
//         top-5 critical companies table
// =============================================

function initOverview() {
  // --- Sector Average Risk — horizontal bar chart ---
  const sAvg   = sectors.map(s => s.avg);
  const sNames = sectors.map(s => s.name.length > 24 ? s.name.slice(0, 22) + '…' : s.name);
  const sBarColors = sAvg.map(v => v >= 70 ? COLORS.critical : v >= 40 ? COLORS.moderate : COLORS.low);

  createChart('sector-avg', document.getElementById('chart-sector-avg').getContext('2d'), {
    type: 'bar',
    data: {
      labels: sNames,
      datasets: [{
        label: 'Avg Risk Index',
        data: sAvg,
        backgroundColor: sBarColors,
        borderRadius: 3,
        borderSkipped: false
      }]
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#1c2128',
          borderColor: '#30363d',
          borderWidth: 1,
          titleColor: '#e6edf3',
          bodyColor: '#8b949e',
          callbacks: { label: ctx => ` Risk Index: ${ctx.raw}` }
        }
      },
      scales: {
        x: {
          min: 0, max: 100,
          grid:   { color: COLORS.grid },
          ticks:  { color: COLORS.tick, font: { size: 11 } },
          border: { color: COLORS.grid }
        },
        y: {
          grid:   { display: false },
          ticks:  { color: COLORS.tick, font: { size: 11 } },
          border: { color: COLORS.grid }
        }
      }
    }
  });

  // --- Sectoral Risk Distribution — stacked bar chart ---
  const sLabels = sectors.map(s => s.name.split(' ')[0]);

  createChart('sector-stack', document.getElementById('chart-sector-stack').getContext('2d'), {
    type: 'bar',
    data: {
      labels: sLabels,
      datasets: [
        { label: 'Low',      data: sectors.map(s => s.low),      backgroundColor: COLORS.low,      borderRadius: 0, stack: 's' },
        { label: 'Moderate', data: sectors.map(s => s.moderate), backgroundColor: COLORS.moderate, borderRadius: 0, stack: 's' },
        { label: 'Critical', data: sectors.map(s => s.critical), backgroundColor: COLORS.critical, borderRadius: 3, stack: 's' }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          display: true,
          labels: { color: COLORS.tick, font: { size: 11 }, boxWidth: 12, boxHeight: 12, padding: 10 }
        },
        tooltip: {
          backgroundColor: '#1c2128',
          borderColor: '#30363d',
          borderWidth: 1,
          titleColor: '#e6edf3',
          bodyColor: '#8b949e'
        }
      },
      scales: {
        x: {
          stacked: true,
          grid:   { display: false },
          ticks:  { color: COLORS.tick, font: { size: 11 } },
          border: { color: COLORS.grid }
        },
        y: {
          stacked: true,
          grid:   { color: COLORS.grid },
          ticks:  { color: COLORS.tick, font: { size: 11 } },
          border: { color: COLORS.grid }
        }
      }
    }
  });

  // --- Top 5 Critical Companies table ---
  const top5  = [...companies].sort((a, b) => b.risk - a.risk).slice(0, 5);
  const tbody = document.querySelector('#top5-table tbody');
  tbody.innerHTML = top5.map(c => `
    <tr style="cursor:default">
      <td class="id-cell">${c.id}</td>
      <td><strong>${c.name}</strong></td>
      <td style="color:var(--muted)">${c.sector}</td>
      <td>
        <div class="risk-bar-wrap">
          <div class="risk-bar-bg"><div class="risk-bar-fill" style="width:${c.risk}%;background:${riskBarColor(c.risk)}"></div></div>
          <span class="risk-bar-val">${c.risk}</span>
        </div>
      </td>
      <td><span class="badge ${levelBadgeClass(c.level)}">${c.level}</span></td>
      <td style="color:var(--muted);font-size:12px">${c.crisis}</td>
      <td><span style="font-size:12px;color:var(--accent)">${c.action}</span></td>
    </tr>
  `).join('');
}

// Register with nav
tabInits['overview'] = initOverview;

