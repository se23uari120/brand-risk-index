// =============================================================
// charts.js — thin, themed wrappers around Chart.js.
// Colours come from CSS tokens so light/dark both work; marks are
// thin (2px lines, ≤18px bars, 4px rounded ends), grids hairline.
// =============================================================

const CHARTS = {};

function tok(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
function theme() {
  return {
    text: tok('--text'), text2: tok('--text-2'), muted: tok('--muted'), grid: tok('--grid'), axis: tok('--axis'),
    surface: tok('--surface'), accent: tok('--accent'), low: tok('--low'), moderate: tok('--moderate'), high: tok('--high'),
    series: [tok('--s1'), tok('--s2'), tok('--s3'), tok('--s4')], seriesMuted: tok('--series-muted'),
  };
}
function alpha(hex, a) {
  const h = hex.replace('#', '');
  const n = parseInt(h.length === 3 ? h.split('').map(x => x + x).join('') : h, 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}

// ── Plugins ─────────────────────────────────────────────────────────────────
// vertical hairline that follows the hovered x position
const crosshairPlugin = {
  id: 'crosshair',
  afterDatasetsDraw(chart, _args, opts) {
    const act = chart.tooltip && chart.tooltip.getActiveElements();
    if (!opts || !opts.enabled || !act || !act.length) return;
    const x = act[0].element.x, { top, bottom } = chart.chartArea, ctx = chart.ctx;
    ctx.save(); ctx.strokeStyle = opts.color; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(x, top); ctx.lineTo(x, bottom); ctx.stroke(); ctx.restore();
  },
};
// tinted background bands for the Moderate / High score ranges
const zonesPlugin = {
  id: 'zones',
  beforeDatasetsDraw(chart, _args, opts) {
    if (!opts || !opts.enabled) return;
    const { ctx, chartArea: a, scales: { y } } = chart, t = theme();
    const bands = [[D.thresholds.moderate, D.thresholds.high, t.moderate, 'Moderate'], [D.thresholds.high, 100, t.high, 'High']];
    ctx.save();
    for (const [lo, hi, col, label] of bands) {
      const y1 = Math.max(a.top, y.getPixelForValue(Math.min(hi, y.max))), y0 = Math.min(a.bottom, y.getPixelForValue(Math.max(lo, y.min)));
      if (y0 <= y1) continue;
      ctx.fillStyle = alpha(col, 0.09); ctx.fillRect(a.left, y1, a.right - a.left, y0 - y1);
      ctx.fillStyle = t.muted; ctx.font = '11px ' + tok('--font'); ctx.textAlign = 'left'; ctx.textBaseline = 'top';
      if (y0 - y1 > 14) ctx.fillText(label, a.left + 6, y1 + 3);
    }
    ctx.restore();
  },
};
// value printed just past the end of each horizontal bar
const barValuePlugin = {
  id: 'barValue',
  afterDatasetsDraw(chart, _args, opts) {
    if (!opts || !opts.enabled) return;
    const ctx = chart.ctx; ctx.save();
    ctx.fillStyle = opts.color; ctx.font = '600 12px ' + tok('--font'); ctx.textBaseline = 'middle'; ctx.textAlign = 'left';
    chart.getDatasetMeta(0).data.forEach((bar, i) => {
      const v = chart.data.datasets[0].data[i];
      ctx.fillText(opts.format ? opts.format(v) : v, bar.x + 6, bar.y);
    });
    ctx.restore();
  },
};
// series names at the right end of lines, with leader lines when nudged apart
const endLabelPlugin = {
  id: 'endLabels',
  afterDatasetsDraw(chart, _args, opts) {
    if (!opts || !opts.enabled) return;
    const ctx = chart.ctx, a = chart.chartArea, items = [];
    chart.data.datasets.forEach((ds, i) => {
      const meta = chart.getDatasetMeta(i);
      if (meta.hidden) return;
      for (let k = ds.data.length - 1; k >= 0; k--) {
        if (ds.data[k] != null) { const p = meta.data[k]; items.push({ label: ds.label, x: p.x, y: p.y, ly: p.y }); break; }
      }
    });
    items.sort((p, q) => p.y - q.y);
    for (let k = 1; k < items.length; k++) items[k].ly = Math.max(items[k].ly, items[k - 1].ly + 14);
    const overflow = items.length ? items[items.length - 1].ly - (a.bottom - 4) : 0;
    if (overflow > 0) items.forEach(it => { it.ly -= overflow; });
    ctx.save(); ctx.font = '12px ' + tok('--font'); ctx.textBaseline = 'middle'; ctx.textAlign = 'left';
    for (const it of items) {
      const lx = a.right + 10;
      ctx.strokeStyle = opts.leader; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(it.x + 3, it.y); ctx.lineTo(lx - 3, it.ly); ctx.stroke();
      ctx.fillStyle = opts.color; ctx.fillText(it.label, lx, it.ly);
    }
    ctx.restore();
  },
};
Chart.register(crosshairPlugin, zonesPlugin, barValuePlugin, endLabelPlugin);

// ── Shared option builders ─────────────────────────────────────────────────
function baseOptions(t) {
  return {
    responsive: true, maintainAspectRatio: false, animation: { duration: 250 },
    interaction: { mode: 'index', intersect: false },
    font: { family: tok('--font') },
    plugins: {
      legend: { display: false },
      tooltip: {
        backgroundColor: t.surface, borderColor: t.axis, borderWidth: 1, padding: 10, cornerRadius: 8,
        titleColor: t.muted, titleFont: { weight: '500', size: 12 }, bodyColor: t.text, bodyFont: { size: 13, weight: '600' },
        usePointStyle: true, boxWidth: 14, boxHeight: 2, filter: item => item.raw != null,
        callbacks: { labelPointStyle: () => ({ pointStyle: 'line', rotation: 0 }) },
      },
      crosshair: { enabled: true, color: t.axis },
      zones: { enabled: false }, barValue: { enabled: false }, endLabels: { enabled: false },
    },
  };
}
function axis(t, extra = {}) {
  return {
    grid: { color: t.grid, drawTicks: false }, border: { color: t.axis },
    ticks: { color: t.muted, font: { size: 11 }, padding: 6 }, ...extra,
  };
}
function mount(key, canvas, config) {
  if (CHARTS[key]) CHARTS[key].destroy();
  CHARTS[key] = new Chart(canvas, config);
  return CHARTS[key];
}
function destroyChart(key) { if (CHARTS[key]) { CHARTS[key].destroy(); delete CHARTS[key]; } }

// ── Chart types ────────────────────────────────────────────────────────────
// Line chart. series: [{label, data, color, width?, fill?}]
function lineChart(key, canvas, { labels, series, yMin, yMax, zones = false, endLabels = false, yFmt, tipFmt, zeroLine = false, xFmt = fmt.dateShort }) {
  const t = theme();
  const opts = baseOptions(t);
  opts.plugins.zones.enabled = zones;
  opts.plugins.endLabels = { enabled: endLabels, color: t.text2, leader: t.axis };
  if (endLabels) opts.layout = { padding: { right: 96 } };
  opts.plugins.tooltip.callbacks.title = items => xFmt(labels[items[0].dataIndex]);
  opts.plugins.tooltip.callbacks.label = ctx => ` ${tipFmt ? tipFmt(ctx.raw) : ctx.raw}  ${series.length > 1 ? ctx.dataset.label : ''}`;
  opts.scales = {
    x: axis(t, { grid: { display: false }, ticks: { color: t.muted, font: { size: 11 }, maxRotation: 0, autoSkip: true, maxTicksLimit: 6, callback: (v, i) => xFmt(labels[i]) } }),
    y: axis(t, {
      min: yMin, max: yMax, ticks: { color: t.muted, font: { size: 11 }, padding: 6, maxTicksLimit: 6, callback: v => (yFmt ? yFmt(v) : v) },
      grid: { color: ctx => (zeroLine && ctx.tick.value === 0 ? t.axis : t.grid), drawTicks: false },
    }),
  };
  return mount(key, canvas, {
    type: 'line',
    data: {
      labels,
      datasets: series.map(s => ({
        label: s.label, data: s.data, borderColor: s.color, backgroundColor: s.fill ? alpha(s.color, 0.10) : s.color,
        fill: s.fill ? 'origin' : false, borderWidth: s.width || 2, pointRadius: 0, pointHoverRadius: 4,
        pointHoverBorderWidth: 2, pointHoverBorderColor: t.surface, pointHoverBackgroundColor: s.color,
        spanGaps: true, tension: 0, borderJoinStyle: 'round', borderCapStyle: 'round',
      })),
    },
    options: opts,
  });
}

// Horizontal bar chart with one series.
function hbarChart(key, canvas, { labels, values, max = 100, color, tip, valueFmt = v => v.toFixed(1) }) {
  const t = theme();
  const opts = baseOptions(t);
  opts.indexAxis = 'y';
  opts.interaction = { mode: 'nearest', axis: 'y', intersect: false };
  opts.plugins.crosshair.enabled = false;
  opts.plugins.barValue = { enabled: true, color: t.text2, format: valueFmt };
  opts.layout = { padding: { right: 40 } };
  opts.plugins.tooltip.callbacks.title = items => labels[items[0].dataIndex];
  opts.plugins.tooltip.callbacks.label = ctx => (tip ? tip(ctx.dataIndex) : ` ${valueFmt(ctx.raw)}`);
  opts.plugins.tooltip.callbacks.labelPointStyle = () => ({ pointStyle: 'rect', rotation: 0 });
  opts.scales = {
    x: axis(t, { min: 0, max, ticks: { color: t.muted, font: { size: 11 }, stepSize: 25 } }),
    y: axis(t, { grid: { display: false }, ticks: { color: t.text2, font: { size: 12 }, autoSkip: false } }),
  };
  return mount(key, canvas, {
    type: 'bar',
    data: { labels, datasets: [{ data: values, backgroundColor: color || t.series[0], hoverBackgroundColor: alpha(color || t.series[0], 0.8), borderRadius: 4, borderSkipped: 'start', maxBarThickness: 18 }] },
    options: opts,
  });
}

// Grouped horizontal bars: categories on y, one dataset per company.
function groupedBarChart(key, canvas, { labels, series }) {
  const t = theme();
  const opts = baseOptions(t);
  opts.indexAxis = 'y';
  opts.interaction = { mode: 'index', axis: 'y', intersect: false };
  opts.plugins.crosshair.enabled = false;
  opts.plugins.tooltip.callbacks.label = ctx => ` ${ctx.raw.toFixed(1)}  ${ctx.dataset.label}`;
  opts.plugins.tooltip.callbacks.labelPointStyle = () => ({ pointStyle: 'rect', rotation: 0 });
  opts.scales = {
    x: axis(t, { min: 0, max: 100, ticks: { color: t.muted, font: { size: 11 }, stepSize: 25 } }),
    y: axis(t, { grid: { display: false }, ticks: { color: t.text2, font: { size: 12 } } }),
  };
  return mount(key, canvas, {
    type: 'bar',
    data: {
      labels,
      datasets: series.map(s => ({ label: s.label, data: s.data, backgroundColor: s.color, borderRadius: 4, borderSkipped: 'start', maxBarThickness: 10, categoryPercentage: 0.78, barPercentage: 0.86 })),
    },
    options: opts,
  });
}

// Paired horizontal bars (e.g. incident week vs control day).
function pairedBarChart(key, canvas, { labels, a, b, aLabel, bLabel }) {
  const t = theme();
  return groupedBarChart(key, canvas, {
    labels, series: [{ label: aLabel, data: a, color: t.series[0] }, { label: bLabel, data: b, color: t.seriesMuted }],
  });
}

// Floating range bars (5–95%) with a dot for the actual value, one row per item.
function rangeChart(key, canvas, { labels, ranges, points, tip }) {
  const t = theme();
  const opts = baseOptions(t);
  opts.indexAxis = 'y';
  opts.interaction = { mode: 'index', axis: 'y', intersect: false };
  opts.plugins.crosshair.enabled = false;
  opts.plugins.tooltip.filter = item => item.datasetIndex === 0;
  opts.plugins.tooltip.callbacks.title = items => labels[items[0].dataIndex];
  opts.plugins.tooltip.callbacks.label = ctx => tip(ctx.dataIndex);
  opts.plugins.tooltip.callbacks.labelPointStyle = () => ({ pointStyle: 'rect', rotation: 0 });
  opts.plugins.zones = { enabled: false };
  opts.scales = {
    x: axis(t, { min: 0, max: 100, ticks: { color: t.muted, font: { size: 11 }, stepSize: 25 } }),
    y: axis(t, { grid: { display: false }, ticks: { color: t.text2, font: { size: 12 }, autoSkip: false } }),
  };
  return mount(key, canvas, {
    type: 'bar',
    data: {
      labels,
      datasets: [
        { type: 'bar', label: '5–95% range', data: ranges, backgroundColor: alpha(t.series[0], 0.28), borderRadius: 4, borderSkipped: false, maxBarThickness: 12 },
        { type: 'line', label: 'Score', data: points, showLine: false, pointRadius: 4, pointHoverRadius: 5, pointBackgroundColor: t.series[0], pointBorderColor: t.surface, pointBorderWidth: 2 },
      ],
    },
    options: opts,
  });
}
