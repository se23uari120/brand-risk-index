// =============================================
// MCDM TAB — static content only
// All MCDM content (formula, AHP matrix,
// TOPSIS steps) is rendered in HTML.
// This module exists as a no-op placeholder
// so the nav registry stays consistent.
// =============================================

function initMcdm() {
  // Nothing dynamic needed — the tab is fully static HTML.
}

// Register with nav
tabInits['mcdm'] = initMcdm;

