// =============================================
// HELPERS — Shared constants & utility functions
// =============================================

const COLORS = {
  low:      '#238636',
  moderate: '#d29922',
  critical: '#da3633',
  accent:   '#2f81f7',
  grid:     '#21262d',
  tick:     '#8b949e',
  text:     '#e6edf3'
};

const REACH_SCORE = { Viral: 100, High: 75, Medium: 50, Low: 25 };

/**
 * Compute deterministic MCDM criteria scores (0–100) for a company.
 * C1 Severity        → risk index directly
 * C2 Reach           → reach score lookup
 * C3 Recoverability  → |sentiment| × 100
 * C4 Criticality     → level-based proxy
 */
function getCriteriaScores(c) {
  const c1 = c.risk;
  const c2 = REACH_SCORE[c.reach] || 0;
  const c3 = Math.abs(c.sentiment) * 100;
  const c4Map = { Low: 20, Moderate: 60, Critical: 90 };
  const c4 = c4Map[c.level] || 0;
  return { c1, c2, c3, c4 };
}

/** Returns the CSS class name for a risk badge. */
function levelBadgeClass(level) {
  if (level === 'Low')      return 'badge-low';
  if (level === 'Moderate') return 'badge-moderate';
  if (level === 'Critical') return 'badge-critical';
  return '';
}

/** Returns the bar/text color for a numeric risk value. */
function riskBarColor(risk) {
  if (risk < 40) return COLORS.low;
  if (risk < 70) return COLORS.moderate;
  return COLORS.critical;
}

/** Converts a sentiment float to an integer percentage (0–100). */
function sentimentPct(s) {
  return Math.round(Math.abs(s) * 100);
}

/** Computes the average risk index for companies in a given sector. */
function sectorAvgRisk(sector) {
  const co = companies.filter(c => c.sector === sector);
  if (!co.length) return null;
  return (co.reduce((a, b) => a + b.risk, 0) / co.length).toFixed(1);
}

// =============================================
// CHART INSTANCE REGISTRY
// Tracks Chart.js instances so they can be
// destroyed before re-creation (avoids canvas
// reuse errors on tab switches).
// =============================================

const chartInstances = {};

function destroyChart(key) {
  if (chartInstances[key]) {
    chartInstances[key].destroy();
    delete chartInstances[key];
  }
}

function createChart(key, ctx, config) {
  destroyChart(key);
  chartInstances[key] = new Chart(ctx, config);
  return chartInstances[key];
}

