// =============================================
// MAIN — Application bootstrap
// Runs after all modules are loaded.
// Initialises the Overview tab immediately
// (it's the default active tab).
// All other tabs initialise lazily on first visit.
// =============================================

document.addEventListener('DOMContentLoaded', () => {
  // Boot the default tab
  initOverview();
  tabInited['overview'] = true;

  // Pre-fill the register count label
  document.getElementById('reg-count').textContent =
    `${companies.length} / ${companies.length} shown`;
});

