// =============================================
// RISK REGISTER TAB
// Searchable, filterable table of all companies.
// Clicking a row opens the detail modal.
// =============================================

let regFiltered = [...companies];

function initRegister() {
  // Populate sector dropdown from data
  const sectorsSet = [...new Set(companies.map(c => c.sector))].sort();
  const sel = document.getElementById('reg-sector');
  sectorsSet.forEach(s => {
    const opt = document.createElement('option');
    opt.value = s;
    opt.textContent = s;
    sel.appendChild(opt);
  });

  document.getElementById('reg-search').addEventListener('input', applyRegFilter);
  document.getElementById('reg-sector').addEventListener('change', applyRegFilter);
  document.getElementById('reg-level').addEventListener('change', applyRegFilter);

  renderRegTable(companies);
}

function applyRegFilter() {
  const q      = document.getElementById('reg-search').value.toLowerCase();
  const sector = document.getElementById('reg-sector').value;
  const level  = document.getElementById('reg-level').value;

  regFiltered = companies.filter(c => {
    const matchQ = !q      || c.name.toLowerCase().includes(q) || c.id.toLowerCase().includes(q);
    const matchS = !sector || c.sector === sector;
    const matchL = !level  || c.level  === level;
    return matchQ && matchS && matchL;
  });

  renderRegTable(regFiltered);
}

function renderRegTable(data) {
  document.getElementById('reg-count').textContent = `${data.length} / ${companies.length} shown`;

  const tbody = document.getElementById('reg-tbody');
  tbody.innerHTML = data.map(c => `
    <tr data-id="${c.id}">
      <td class="id-cell">${c.id}</td>
      <td><strong>${c.name}</strong></td>
      <td style="color:var(--muted);font-size:12px">${c.sector}</td>
      <td>
        <div class="risk-bar-wrap">
          <div class="risk-bar-bg"><div class="risk-bar-fill" style="width:${c.risk}%;background:${riskBarColor(c.risk)}"></div></div>
          <span class="risk-bar-val">${c.risk}</span>
        </div>
      </td>
      <td><span class="badge ${levelBadgeClass(c.level)}">${c.level}</span></td>
      <td style="color:var(--muted);font-size:12px;max-width:160px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${c.crisis}</td>
      <td>
        <div class="sentiment-bar-wrap">
          <div class="sentiment-bar-bg"><div class="sentiment-bar-fill" style="width:${sentimentPct(c.sentiment)}%"></div></div>
          <span class="sentiment-val">${c.sentiment.toFixed(2)}</span>
        </div>
      </td>
      <td><span style="font-size:12px;color:${c.reach === 'Viral' ? COLORS.critical : COLORS.muted}">${c.reach}</span></td>
      <td style="font-size:12px;color:var(--accent);max-width:140px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${c.action}</td>
    </tr>
  `).join('');

  // Row click → open modal
  tbody.querySelectorAll('tr[data-id]').forEach(row => {
    row.addEventListener('click', () => {
      const company = companies.find(c => c.id === row.dataset.id);
      if (company) openModal(company);
    });
  });
}

// Register with nav
tabInits['register'] = initRegister;

