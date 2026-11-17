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

// AHP weights computed from the pairwise matrix (report Table IV).
// Replaced with the live values from /api/mcdm/ahp when the backend is up.
let AHP_W = [0.4658, 0.2771, 0.1611, 0.0960];
const CRITERIA_LABELS = ['C1 Severity', 'C2 Reach', 'C3 Recoverability', 'C4 Criticality'];

const clip = (x, lo, hi) => Math.min(hi, Math.max(lo, x));

/**
 * MCDM criterion scores (0–100) for a company.
 * Uses the values the engine computed (c.criteria) when available; otherwise
 * applies the report Table III formulas to the stored sentiment and reach.
 */
function getCriteriaScores(c) {
  if (Array.isArray(c.criteria) && c.criteria.every(v => typeof v === 'number')) {
    const [c1, c2, c3, c4] = c.criteria;
    return { c1, c2, c3, c4 };
  }
  const c1 = clip(Math.abs(Math.min(0, c.sentiment || 0)) * 100, 5, 100);
  const c2 = REACH_SCORE[c.reach] || 25;
  const c3 = clip(0.6 * c1 + 0.4 * c2, 10, 100);
  const c4 = clip(0.8 * c1, 10, 100);
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

