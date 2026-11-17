// =============================================
// NAV — Sidebar tab switching
// =============================================

const tabTitles = {
  overview: 'System Overview',
  search:   'Company Search',
  sources:  'Source Comparison',
  register: 'Risk Register',
  compare:  'Company Comparator',
  mcdm:     'MCDM Weight Matrix',
  action:   'Action Engine',
  validation: 'Validation'
};

// Each tab's init function is registered here after the
// corresponding module loads (see bottom of each module file).
const tabInits = {};

let currentTab = 'overview';
const tabInited = {};

function switchTab(tab) {
  if (currentTab === tab) return;

  document.querySelector(`#tab-${currentTab}`).classList.remove('active');
  document.querySelector(`[data-tab="${currentTab}"]`).classList.remove('active');

  currentTab = tab;

  document.querySelector(`#tab-${tab}`).classList.add('active');
  document.querySelector(`[data-tab="${tab}"]`).classList.add('active');
  document.getElementById('topbar-title').textContent = tabTitles[tab];

  if (!tabInited[tab] && tabInits[tab]) {
    tabInits[tab]();
    tabInited[tab] = true;
  } else if (tab === 'compare') {
    // Re-render compare charts in case canvas was resized
    if (typeof renderCompareChart === 'function') renderCompareChart();
    if (typeof renderCompareRadar === 'function') renderCompareRadar();
  }
}

document.querySelectorAll('#sidebar-nav a').forEach(a => {
  a.addEventListener('click', () => switchTab(a.dataset.tab));
});

