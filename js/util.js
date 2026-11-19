// =============================================================
// util.js — shared data access, formatting and plain-English
// explanations used by every view.
// =============================================================

let D = null, BY_SYMBOL = {}, WEIGHTS = [], CRIT = [];
const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];

// The data comes from js/data.js (static site) or /api/data (live server).
function setData(payload) {
  D = payload || null;
  BY_SYMBOL = D ? Object.fromEntries(D.companies.map(c => [c.symbol, c])) : {};
  WEIGHTS = D ? D.ahp.weights : [];
  CRIT = D ? D.criteria : [];
}
setData(window.RISK_DATA);

// ── Safety: headlines and sources come from external feeds ──────────────────
function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
}
function safeUrl(u) {
  try { const x = new URL(u); return (x.protocol === 'https:' || x.protocol === 'http:') ? x.href : null; }
  catch { return null; }
}

// ── Formatting ─────────────────────────────────────────────────────────────
const fmt = {
  score: v => (v == null ? '–' : v.toFixed(1)),
  pct: (v, d = 1) => (v == null ? '–' : (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v * 100).toFixed(d) + '%'),
  pctAbs: (v, d = 1) => (v == null ? '–' : Math.abs(v * 100).toFixed(d) + '%'),
  times: v => (v == null ? '–' : v.toFixed(1) + '×'),
  sigma: z => (z == null ? '–' : (z > 0 ? '+' : z < 0 ? '−' : '') + Math.abs(z).toFixed(1) + 'σ'),
  inr: v => (v == null ? '–' : '₹' + v.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })),
  date(iso, opts = { day: 'numeric', month: 'short', year: 'numeric' }) {
    if (!iso) return '–';
    const [y, m, d] = iso.slice(0, 10).split('-').map(Number);
    return new Date(y, m - 1, d).toLocaleDateString('en-IN', opts);
  },
  dateShort: iso => fmt.date(iso, { day: 'numeric', month: 'short' }),
  plural: (n, word) => `${n} ${n === 1 ? word : /[^aeiou]y$/.test(word) ? word.slice(0, -1) + 'ies' : word + 's'}`,
};

// ── Levels ─────────────────────────────────────────────────────────────────
const LEVELS = ['Low', 'Moderate', 'High'];
function levelOf(score) {
  if (score >= D.thresholds.high) return 'High';
  if (score >= D.thresholds.moderate) return 'Moderate';
  return 'Low';
}
// distinct shapes so the level never relies on colour alone
const SHAPE = {
  Low: '<svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true"><circle class="shape" cx="5" cy="5" r="4.5"/></svg>',
  Moderate: '<svg width="11" height="10" viewBox="0 0 11 10" aria-hidden="true"><path class="shape" d="M5.5 0.3 10.8 9.7H0.2z"/></svg>',
  High: '<svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true"><path class="shape" d="M5 0 10 5 5 10 0 5z"/></svg>',
};
const levelPill = level => `<span class="level lvl-${level}">${SHAPE[level]}${level}</span>`;
const levelRange = level => level === 'Low' ? `0 – ${D.thresholds.moderate}`
  : level === 'Moderate' ? `${D.thresholds.moderate} – ${D.thresholds.high}` : `${D.thresholds.high} – 100`;

function meter(score, level, label = true) {
  const w = Math.max(1.5, Math.min(100, score || 0));
  return `<div class="meter-wrap lvl-${level}"><div class="meter" role="img" aria-label="Risk score ${fmt.score(score)} out of 100"><span style="width:${w}%"></span></div>${label ? `<span class="meter-val">${fmt.score(score)}</span>` : ''}</div>`;
}

function delta(v) {
  if (v == null) return '<span class="delta flat" title="Not enough history yet">–</span>';
  if (Math.abs(v) < 0.5) return `<span class="delta flat" title="Little change in 5 trading days">±${Math.abs(v).toFixed(1)}</span>`;
  return v > 0
    ? `<span class="delta up" title="Risk score rose ${v.toFixed(1)} points in 5 trading days">▲ ${v.toFixed(1)}</span>`
    : `<span class="delta down" title="Risk score fell ${Math.abs(v).toFixed(1)} points in 5 trading days">▼ ${Math.abs(v).toFixed(1)}</span>`;
}

// Tiny inline trend line (no axes): last value marked with the level colour.
function sparkline(values, level, w = 84, h = 26) {
  const pts = values.map((v, i) => [i, v]).filter(p => p[1] != null);
  if (pts.length < 2) return '<span class="muted small">–</span>';
  const n = values.length - 1, max = 100;
  const x = i => 2 + (i / n) * (w - 6), y = v => h - 3 - (v / max) * (h - 6);
  const d = pts.map((p, k) => `${k ? 'L' : 'M'}${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join('');
  const last = pts[pts.length - 1];
  return `<svg class="spark lvl-${level}" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" role="img" aria-label="Score trend, latest ${fmt.score(last[1])}">` +
    `<path d="${d}"/><circle class="shape" cx="${x(last[0]).toFixed(1)}" cy="${y(last[1]).toFixed(1)}" r="3"/></svg>`;
}

// ── Explanations ───────────────────────────────────────────────────────────
// How much each signal pushes the score (weight × points), largest first.
function contributions(c) {
  return CRIT.map((k, i) => ({ i, key: k.key, name: k.name, points: c.criteria[i], weight: WEIGHTS[i], contrib: WEIGHTS[i] * c.criteria[i] }))
    .sort((a, b) => b.contrib - a.contrib);
}

function mainWindow(s) {
  const week = -s.z5 >= -s.z20;
  return { week, excess: week ? s.excess5 : s.excess20, z: week ? s.z5 : s.z20, period: week ? 'this week' : 'over the past month' };
}

function rarity(z) {
  if (z <= -3) return 'very rare — a move this size happens by chance well under 1% of the time';
  if (z <= -2) return 'unusual — roughly a 1-in-40 chance in a normal week';
  return 'a mild underperformance';
}

function topNegative(c) {
  return c.news.articles.find(a => a.l === 'negative') || null;
}

// One sentence of evidence per signal (used in the detail panel).
function evidence(c, i) {
  const s = c.stock, n = c.news;
  const vs = s.hasPeers ? 'the NIFTY 50 and its sector' : 'the NIFTY 50';
  switch (i) {
    case 0: {
      const m = mainWindow(s);
      return m.excess < 0
        ? `${fmt.pctAbs(m.excess)} worse than expected ${m.period} after removing ${vs} (${fmt.sigma(m.z)}).`
        : `In line with or better than expected: ${fmt.pct(s.excess5)} this week, ${fmt.pct(s.excess20)} this month vs. ${vs}.`;
    }
    case 1:
      return `Volatility ${fmt.times(s.volRatio)} and volume ${fmt.times(s.volumeRatio)} their normal levels` +
        (s.excess5 >= 0 ? ' — but the stock is beating expectations, so this counts for only a quarter.' : '.');
    case 2:
      return s.abnDrawdown > 0.0005
        ? `Company-specific performance is ${fmt.pctAbs(s.abnDrawdown)} below its 3-month best (${s.ddSigma.toFixed(1)} × its normal 3-month wobble).`
        : 'Company-specific performance is at its 3-month best — no lingering damage.';
    case 3:
      return n.count7d
        ? `${fmt.plural(n.count7d, 'relevant headline')} in the last ${D.newsWindowDays} days; their average negativity scores ${c.criteria[3].toFixed(0)} / 100.`
        : `No relevant headlines in the last ${D.newsWindowDays} days, so this signal is 0.`;
    case 4:
      return `${fmt.plural(n.neg7d, 'negative headline')} in the last ${D.newsWindowDays} days.`;
  }
  return '';
}

// Plain-English bullet points explaining the score, most important first.
function reasons(c) {
  const s = c.stock, n = c.news, out = [];
  const vs = s.hasPeers ? 'the NIFTY 50 and its sector peers' : 'the NIFTY 50';
  let newsDone = false;
  for (const k of contributions(c)) {
    if (k.points < 15) continue;
    if (k.i === 0) {
      const m = mainWindow(s);
      out.push(`The shares did <strong>${fmt.pctAbs(m.excess)} worse than expected ${m.period}</strong>, after allowing for ${vs}. That is ${rarity(m.z)}.`);
    } else if (k.i === 1) {
      out.push(`Investors are trading it nervously: volatility is <strong>${fmt.times(s.volRatio)}</strong> and volume <strong>${fmt.times(s.volumeRatio)}</strong> their usual levels.`);
    } else if (k.i === 2) {
      out.push(`The damage is lingering: company-specific performance is <strong>${fmt.pctAbs(s.abnDrawdown)} below its best</strong> level of the last 3 months.`);
    } else if (!newsDone) {
      newsDone = true;
      const top = topNegative(c);
      out.push(`<strong>${n.neg7d} of ${n.count7d}</strong> relevant headlines in the last ${D.newsWindowDays} days were negative` +
        (top ? `, for example “${esc(top.t)}”.` : '.'));
    }
  }
  if (!out.length) out.push('Nothing unusual right now: the share price is moving in line with the market and its sector, and news coverage is not negative.');
  if (s.excess5 > 0.02) out.push(`On the positive side, the shares beat expectations this week (${fmt.pct(s.excess5)}).`);
  if (!n.count7d) out.push(`No relevant news in the last ${D.newsWindowDays} days — this score rests on stock behaviour alone.`);
  return out;
}

// Short phrase for list rows.
function headline(c) {
  const top = contributions(c).find(k => k.points >= 15);
  if (!top) return 'Moving in line with the market';
  const s = c.stock;
  if (top.i === 0) { const m = mainWindow(s); return `${fmt.pctAbs(m.excess)} worse than expected ${m.week ? 'this week' : 'this month'}`; }
  if (top.i === 1) return `Volatility ${fmt.times(s.volRatio)} normal`;
  if (top.i === 2) return `${fmt.pctAbs(s.abnDrawdown)} below its 3-month best`;
  return `${fmt.plural(c.news.neg7d, 'negative headline')} this week`;
}

// Issue type behind the negative coverage (crisis classifier)
const NO_ISSUE = 'No significant adverse coverage';
function issueTag(cat, small = false) {
  if (!cat || cat === NO_ISSUE) return '';
  return `<span class="tag${small ? ' small' : ''}" title="Issue type (crisis classifier)">${esc(cat)}</span>`;
}

async function getJSON(url, opts) {
  const r = await fetch(url, opts);
  let body = null;
  try { body = await r.json(); } catch (e) { /* not JSON */ }
  if (!r.ok) throw new Error((body && (body.detail || body.error)) || `HTTP ${r.status}`);
  return body;
}

// Small accessible data table (the "table view" twin of a chart).
function dataTable(headers, rows) {
  return `<table class="data"><thead><tr>${headers.map((h, i) => `<th${i ? ' class="r"' : ''}>${esc(h)}</th>`).join('')}</tr></thead>` +
    `<tbody>${rows.map(r => `<tr>${r.map((v, i) => `<td${i ? ' class="r num"' : ''}>${esc(v)}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
}

function median(arr) {
  const a = arr.filter(v => v != null).sort((x, y) => x - y);
  if (!a.length) return null;
  const m = Math.floor(a.length / 2);
  return a.length % 2 ? a[m] : (a[m - 1] + a[m]) / 2;
}
