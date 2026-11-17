// =============================================
// COMPARE TAB (Company Comparator)
// =============================================

// Default selected companies so the Comparator shows rich comparison values immediately
let selectedCompanies = [];

// Palette for up to 4 compared companies
const CMP_COLORS = ['#2f81f7', '#d29922', '#238636', '#da3633'];

function initCompare() {
  // Ensure default selections if empty
  if (selectedCompanies.length === 0 && typeof companies !== 'undefined' && companies.length > 0) {
    const defaultIds = ['BR-104', 'BR-101']; // Zomato & Tata Motors
    defaultIds.forEach(id => {
      const found = companies.find(c => c.id === id);
      if (found) selectedCompanies.push(found);
    });
  }

  // Populate the select dropdown
  populateCompareSelect();

  // Wire search input & autocomplete
  setupCompareAutocomplete();

  // Wire Quick Add buttons
  setupQuickAddButtons();

  // Clear all button
  const clearBtn = document.getElementById('cmp-clear');
  if (clearBtn) {
    clearBtn.addEventListener('click', () => {
      selectedCompanies = [];
      renderCompareUI();
    });
  }

  // Initial render
  renderCompareUI();
}

function populateCompareSelect() {
  const sel = document.getElementById('cmp-select');
  if (!sel || typeof companies === 'undefined') return;

  sel.innerHTML = '<option value="">+ Add company from list...</option>';
  companies.forEach(c => {
    const isSel = selectedCompanies.some(s => s.id === c.id);
    const opt = document.createElement('option');
    opt.value = c.id;
    opt.textContent = `${c.name} (${c.id}) · Risk: ${c.risk} [${c.level}]`;
    if (isSel) opt.disabled = true;
    sel.appendChild(opt);
  });

  sel.onchange = () => {
    if (sel.value) {
      addCompare(sel.value);
      sel.value = '';
    }
  };
}

function setupCompareAutocomplete() {
  const input = document.getElementById('cmp-search');
  const drop  = document.getElementById('cmp-drop');
  if (!input || !drop) return;

  function renderDropMatches(query) {
    const q = (query || '').toLowerCase().trim();
    const available = companies.filter(c => !selectedCompanies.some(s => s.id === c.id));
    
    let matches = available;
    if (q) {
      matches = available.filter(c =>
        c.name.toLowerCase().includes(q) ||
        c.id.toLowerCase().includes(q) ||
        (c.sector && c.sector.toLowerCase().includes(q))
      );
    }
    matches = matches.slice(0, 8);

    if (matches.length === 0) {
      drop.innerHTML = '<div style="padding:10px 12px;font-size:12px;color:var(--muted)">No matching companies available</div>';
      drop.classList.add('open');
      return;
    }

    drop.innerHTML = matches.map(c => `
      <div class="autocomplete-item" data-id="${c.id}">
        <div style="display:flex;align-items:center;gap:8px">
          <strong style="color:var(--text)">${c.name}</strong>
          <span style="font-size:11px;color:var(--muted)">${c.id}</span>
          <span class="badge ${levelBadgeClass(c.level)}" style="font-size:10px;padding:1px 6px">${c.level}</span>
        </div>
        <div style="text-align:right">
          <span style="font-size:12px;font-weight:700;color:${riskBarColor(c.risk)}">${c.risk}</span>
          <div class="ac-sector">${c.sector}</div>
        </div>
      </div>
    `).join('');

    drop.classList.add('open');

    // Use mousedown with preventDefault so focus isn't lost before item is added
    drop.querySelectorAll('.autocomplete-item').forEach(item => {
      item.addEventListener('mousedown', (e) => {
        e.preventDefault();
        addCompare(item.dataset.id);
        input.value = '';
        drop.classList.remove('open');
      });
    });
  }

  input.addEventListener('input', () => {
    renderDropMatches(input.value);
  });

  input.addEventListener('focus', () => {
    renderDropMatches(input.value);
  });

  input.addEventListener('blur', () => {
    setTimeout(() => drop.classList.remove('open'), 200);
  });

  input.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') drop.classList.remove('open');
  });
}

function setupQuickAddButtons() {
  document.querySelectorAll('.cmp-quick-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const id = btn.dataset.id;
      if (id) addCompare(id);
    });
  });
}

function updateQuickBtnStates() {
  document.querySelectorAll('.cmp-quick-btn').forEach(btn => {
    const isSel = selectedCompanies.some(s => s.id === btn.dataset.id);
    if (isSel) {
      btn.style.opacity = '0.4';
      btn.style.borderColor = 'var(--accent)';
      btn.style.cursor = 'default';
    } else {
      btn.style.opacity = '1';
      btn.style.borderColor = 'var(--border)';
      btn.style.cursor = 'pointer';
    }
  });
}

function addCompare(id) {
  if (typeof companies === 'undefined') return;
  const c = companies.find(x => x.id === id);
  if (!c) return;

  if (selectedCompanies.some(s => s.id === id)) return;

  if (selectedCompanies.length >= 4) {
    // If already at max 4, rotate out the earliest
    selectedCompanies.shift();
  }

  selectedCompanies.push(c);
  renderCompareUI();
}

function removeCompare(id) {
  selectedCompanies = selectedCompanies.filter(c => c.id !== id);
  renderCompareUI();
}

function renderCompareUI() {
  updateQuickBtnStates();
  populateCompareSelect();

  // Slot hint counter
  const slotHint = document.getElementById('cmp-slot-hint');
  if (slotHint) {
    slotHint.textContent = `${selectedCompanies.length} / 4 companies selected`;
  }

  // Render chip pills
  const chips = document.getElementById('cmp-chips');
  if (chips) {
    if (selectedCompanies.length === 0) {
      chips.innerHTML = '<span style="font-size:12px;color:var(--muted)">No companies selected yet. Use search, dropdown, or quick-add above.</span>';
    } else {
      chips.innerHTML = selectedCompanies.map((c, idx) => `
        <div class="compare-card">
          <div style="display:flex;align-items:center;gap:8px">
            <span style="width:10px;height:10px;border-radius:50%;background:${CMP_COLORS[idx]};display:inline-block"></span>
            <div>
              <div class="cc-name">${c.name}</div>
              <div class="cc-sector">${c.id} · ${c.sector}</div>
            </div>
          </div>
          <div style="display:flex;align-items:center;gap:8px">
            <span class="badge ${levelBadgeClass(c.level)}" style="font-size:10px">${c.level}</span>
            <strong style="font-size:13px;color:${riskBarColor(c.risk)}">${c.risk}</strong>
            <button class="cc-remove" data-id="${c.id}" title="Remove company">&times;</button>
          </div>
        </div>
      `).join('');

      chips.querySelectorAll('.cc-remove').forEach(btn => {
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          removeCompare(btn.dataset.id);
        });
      });
    }
  }

  const empty = document.getElementById('cmp-empty');
  const content = document.getElementById('cmp-content');

  if (selectedCompanies.length === 0) {
    if (empty) empty.style.display = 'block';
    if (content) content.style.display = 'none';
    destroyChart('compare');
    destroyChart('compare-radar');
    return;
  }

  if (empty) empty.style.display = 'none';
  if (content) content.style.display = 'block';

  // Render top cards, charts, and table
  renderCompareCards();
  renderCompareChart();
  renderCompareRadar();
  renderCompareTable();
}

function renderCompareCards() {
  const grid = document.getElementById('cmp-cards-grid');
  if (!grid) return;

  grid.innerHTML = selectedCompanies.map((c, idx) => `
    <div class="card" style="border-top:3px solid ${CMP_COLORS[idx]};padding:14px">
      <div style="display:flex;justify-content:space-between;align-items:flex-start">
        <div>
          <div style="font-size:14px;font-weight:700;color:var(--text)">${c.name}</div>
          <div style="font-size:11px;color:var(--muted)">${c.id} · ${c.sector}</div>
        </div>
        <span class="badge ${levelBadgeClass(c.level)}">${c.level}</span>
      </div>

      <div style="display:flex;align-items:baseline;gap:6px;margin-top:12px">
        <span style="font-size:28px;font-weight:800;color:${riskBarColor(c.risk)}">${c.risk}</span>
        <span style="font-size:12px;color:var(--muted)">/ 100 Risk</span>
      </div>

      <div style="margin-top:10px">
        <div style="font-size:11px;color:var(--muted);margin-bottom:3px">FinBERT Sentiment</div>
        <div class="sentiment-bar-wrap">
          <div class="sentiment-bar-bg" style="flex:1">
            <div class="sentiment-bar-fill" style="width:${sentimentPct(c.sentiment)}%"></div>
          </div>
          <span class="sentiment-val">${c.sentiment.toFixed(2)}</span>
        </div>
      </div>

      <div style="margin-top:10px;font-size:11px;color:var(--muted)">
        <div><strong>Crisis:</strong> ${c.crisis}</div>
        <div style="margin-top:3px;color:var(--accent)"><strong>Action:</strong> ${c.action}</div>
      </div>
    </div>
  `).join('');
}

function renderCompareChart() {
  const canvas = document.getElementById('chart-compare');
  if (!canvas || selectedCompanies.length === 0) return;

  const labels = selectedCompanies.map(c => c.name.split(' ')[0]);
  const riskData = selectedCompanies.map(c => c.risk);
  const sentData = selectedCompanies.map(c => Math.round(Math.abs(c.sentiment) * 100));
  const reachData = selectedCompanies.map(c => REACH_SCORE[c.reach] || 25);

  createChart('compare', canvas.getContext('2d'), {
    type: 'bar',
    data: {
      labels,
      datasets: [
        {
          label: 'Composite Risk Index',
          data: riskData,
          backgroundColor: '#da3633',
          borderRadius: 3
        },
        {
          label: 'FinBERT Negative Depth (|s|×100)',
          data: sentData,
          backgroundColor: '#d29922',
          borderRadius: 3
        },
        {
          label: 'Media Reach Velocity Score',
          data: reachData,
          backgroundColor: '#2f81f7',
          borderRadius: 3
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          display: true,
          position: 'top',
          labels: { color: COLORS.tick, font: { size: 11 }, boxWidth: 12, boxHeight: 12, padding: 12 }
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
          grid: { display: false },
          ticks: { color: COLORS.tick, font: { size: 12, weight: '600' } },
          border: { color: COLORS.grid }
        },
        y: {
          min: 0,
          max: 100,
          grid: { color: COLORS.grid },
          ticks: { color: COLORS.tick, font: { size: 11 }, stepSize: 20 },
          border: { color: COLORS.grid }
        }
      }
    }
  });
}

function renderCompareRadar() {
  const canvas = document.getElementById('chart-compare-radar');
  if (!canvas || selectedCompanies.length === 0) return;

  const datasets = selectedCompanies.map((c, idx) => {
    const sc = getCriteriaScores(c);
    const color = CMP_COLORS[idx];
    return {
      label: c.name,
      data: [sc.c1, sc.c2, sc.c3, sc.c4],
      backgroundColor: color + '22',
      borderColor: color,
      pointBackgroundColor: color,
      pointRadius: 4,
      borderWidth: 2
    };
  });

  createChart('compare-radar', canvas.getContext('2d'), {
    type: 'radar',
    data: {
      labels: ['C1 Severity', 'C2 Reach', 'C3 Recoverability', 'C4 Criticality'],
      datasets: datasets
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          display: true,
          position: 'top',
          labels: { color: COLORS.tick, font: { size: 11 }, boxWidth: 10, boxHeight: 10, padding: 8 }
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
        r: {
          min: 0,
          max: 100,
          backgroundColor: 'transparent',
          grid: { color: COLORS.grid },
          angleLines: { color: COLORS.grid },
          ticks: { color: COLORS.tick, backdropColor: 'transparent', font: { size: 10 }, stepSize: 25 },
          pointLabels: { color: COLORS.tick, font: { size: 11, weight: '600' } }
        }
      }
    }
  });
}

function renderCompareTable() {
  const table = document.getElementById('cmp-table');
  if (!table) return;

  const thead = table.querySelector('thead tr');
  const tbody = document.getElementById('cmp-tbody');

  // Header
  thead.innerHTML =
    '<th style="color:var(--muted);font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.08em;padding:10px 14px;border-bottom:1px solid var(--border);width:220px">Comparison Dimension</th>' +
    selectedCompanies.map((c, idx) =>
      `<th style="color:var(--text);font-size:13px;font-weight:700;padding:10px 14px;border-bottom:1px solid var(--border)">
        <div style="display:flex;align-items:center;gap:6px">
          <span style="width:8px;height:8px;border-radius:50%;background:${CMP_COLORS[idx]}"></span>
          ${c.name}
        </div>
      </th>`
    ).join('');

  // Row definitions
  const rows = [
    {
      label: 'Corporate Identifier',
      fn: c => `<span style="font-family:monospace;color:var(--muted)">${c.id}</span>`
    },
    {
      label: 'Industry Sector',
      fn: c => `<strong>${c.sector}</strong>`
    },
    {
      label: 'Composite Risk Index (0–100)',
      fn: c => `
        <div class="risk-bar-wrap">
          <div class="risk-bar-bg"><div class="risk-bar-fill" style="width:${c.risk}%;background:${riskBarColor(c.risk)}"></div></div>
          <span class="risk-bar-val" style="font-size:14px;font-weight:700;color:${riskBarColor(c.risk)}">${c.risk}</span>
        </div>`
    },
    {
      label: 'Threat Classification',
      fn: c => `<span class="badge ${levelBadgeClass(c.level)}">${c.level} Risk</span>`
    },
    {
      label: 'FinBERT Sentiment Score',
      fn: c => `
        <div class="sentiment-bar-wrap">
          <div class="sentiment-bar-bg" style="width:80px"><div class="sentiment-bar-fill" style="width:${sentimentPct(c.sentiment)}%"></div></div>
          <span class="sentiment-val" style="font-weight:600">${c.sentiment.toFixed(2)}</span>
        </div>`
    },
    {
      label: 'Media Reach Velocity',
      fn: c => `<span style="font-weight:600;color:${c.reach === 'Viral' ? COLORS.critical : COLORS.text}">${c.reach}</span> (${REACH_SCORE[c.reach] || 25} pts)`
    },
    {
      label: `C1 Severity (w ${AHP_W[0].toFixed(3)})`,
      fn: c => {
        const sc = getCriteriaScores(c);
        return `<span style="font-variant-numeric:tabular-nums">${sc.c1.toFixed(1)} / 100</span>`;
      }
    },
    {
      label: `C2 Reach (w ${AHP_W[1].toFixed(3)})`,
      fn: c => {
        const sc = getCriteriaScores(c);
        return `<span style="font-variant-numeric:tabular-nums">${sc.c2.toFixed(1)} / 100</span>`;
      }
    },
    {
      label: `C3 Recoverability (w ${AHP_W[2].toFixed(3)})`,
      fn: c => {
        const sc = getCriteriaScores(c);
        return `<span style="font-variant-numeric:tabular-nums">${sc.c3.toFixed(1)} / 100</span>`;
      }
    },
    {
      label: `C4 Criticality (w ${AHP_W[3].toFixed(3)})`,
      fn: c => {
        const sc = getCriteriaScores(c);
        return `<span style="font-variant-numeric:tabular-nums">${sc.c4.toFixed(1)} / 100</span>`;
      }
    },
    {
      label: 'Sector Benchmark Variance',
      fn: c => {
        const avg = sectorAvgRisk(c.sector);
        if (!avg) return '-';
        const diff = (c.risk - avg).toFixed(1);
        const color = diff > 0 ? COLORS.critical : COLORS.low;
        return `<span style="color:${color};font-weight:600">${diff > 0 ? '+' : ''}${diff}</span> vs sector avg (${avg})`;
      }
    },
    {
      label: 'Dominant Crisis Scenario',
      fn: c => `<span style="font-size:12px;color:var(--muted)">${c.crisis}</span>`
    },
    {
      label: 'Action Engine Directive',
      fn: c => `<span style="color:var(--accent);font-weight:600;font-size:12px">${c.action}</span>`
    }
  ];

  tbody.innerHTML = rows.map(r => `
    <tr style="cursor:default">
      <td style="font-size:11px;color:var(--muted);font-weight:700;text-transform:uppercase;letter-spacing:0.06em;white-space:nowrap;background:rgba(255,255,255,0.01)">${r.label}</td>
      ${selectedCompanies.map(c => `<td>${r.fn(c)}</td>`).join('')}
    </tr>
  `).join('');
}

// Register with nav registry
tabInits['compare'] = initCompare;
