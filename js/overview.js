// =============================================================
// overview.js — the landing view: summary tiles, highest risk,
// risers, negative news, sector averages and the level guide.
// =============================================================

function renderOverview() {
  const cs = D.companies;
  const n = cs.length;

  $('#intro-text').innerHTML =
    `A daily <strong>brand risk score from 0 to 100</strong> for ${n} NSE-listed companies (the ${esc(D.universe)}). ` +
    `It reads two kinds of evidence: how the <strong>share price</strong> behaves once market- and sector-wide moves are removed, ` +
    `and how <strong>negative the news</strong> is. <a href="#method">How is it calculated?</a>`;

  // ── Tiles ──
  const counts = Object.fromEntries(LEVELS.map(l => [l, cs.filter(c => c.level === l).length]));
  const med = median(cs.map(c => c.score));
  const medChange = median(cs.map(c => c.change5d));
  const tile = (label, value, foot, icon = '') =>
    `<div class="card tile"><div class="tile-label">${icon}${label}</div><div class="tile-value">${value}</div><div class="tile-foot">${foot}</div></div>`;
  $('#tiles').innerHTML = [
    tile('Companies tracked', n, `${esc(D.universe)} · NSE`),
    tile('High risk', counts.High, `score ${levelRange('High')}`, `<span class="lvl-High">${SHAPE.High}</span>`),
    tile('Moderate risk', counts.Moderate, `score ${levelRange('Moderate')}`, `<span class="lvl-Moderate">${SHAPE.Moderate}</span>`),
    tile('Typical score', fmt.score(med),
      medChange == null ? 'median of all companies' : `median · ${delta(medChange)} vs last week`),
  ].join('');

  // ── Highest risk list ──
  $('#top-list').innerHTML = cs.slice(0, 8).map(c => `
    <li class="rank-item" tabindex="0" data-symbol="${esc(c.symbol)}" role="button" aria-label="${esc(c.name)}, score ${fmt.score(c.score)}, ${c.level}. Open details">
      <span class="rank-no">${c.rank}</span>
      <div style="min-width:0">
        <div class="co-name">${esc(c.name)} <span class="co-sub" style="display:inline">${esc(c.symbol)}</span></div>
        <div class="co-reason">${esc(headline(c))}</div>
      </div>
      <div>${meter(c.score, c.level)}<div style="margin-top:4px">${levelPill(c.level)}</div></div>
      <div class="r hide-sm" style="text-align:right">${delta(c.change5d)}</div>
      <div class="hide-sm">${sparkline(c.history, c.level)}</div>
    </li>`).join('');

  // ── Risers ──
  const risers = cs.filter(c => c.change5d != null && c.change5d >= 1).sort((a, b) => b.change5d - a.change5d).slice(0, 5);
  $('#risers').innerHTML = risers.length ? risers.map(c => `
    <li class="mini-item" tabindex="0" data-symbol="${esc(c.symbol)}" role="button">
      <div class="grow"><div class="co-name">${esc(c.name)}</div><div class="co-sub">${esc(headline(c))}</div></div>
      ${delta(c.change5d)}
      <span class="meter-val" style="min-width:36px">${fmt.score(c.score)}</span>
    </li>`).join('') : '<li class="muted small" style="padding:8px 4px">No company’s score rose by a point or more this week.</li>';

  // ── Negative news ──
  $('#news-window-hint').textContent = `last ${D.newsWindowDays} days`;
  const neg = cs.filter(c => c.news.neg7d > 0).sort((a, b) => b.news.neg7d - a.news.neg7d || b.score - a.score).slice(0, 5);
  $('#neg-news').innerHTML = neg.length ? neg.map(c => {
    const top = topNegative(c);
    return `
    <li class="mini-item" tabindex="0" data-symbol="${esc(c.symbol)}" role="button">
      <div class="grow"><div class="co-name">${esc(c.name)}</div>${top ? `<div class="mini-quote">“${esc(top.t)}”</div>` : ''}</div>
      <span class="small text-2" style="white-space:nowrap"><strong>${c.news.neg7d}</strong> of ${c.news.count7d}</span>
    </li>`;
  }).join('') : '<li class="muted small" style="padding:8px 4px">No negative headlines this week.</li>';

  // ── Sector chart ──
  const groups = {};
  cs.forEach(c => { (groups[c.sector] = groups[c.sector] || []).push(c); });
  const sectors = Object.entries(groups).map(([name, list]) => ({
    name, n: list.length, avg: list.reduce((s, c) => s + c.score, 0) / list.length,
    top: list.reduce((m, c) => (c.score > m.score ? c : m), list[0]),
  })).sort((a, b) => b.avg - a.avg);
  $('#sector-box').style.height = (sectors.length * 28 + 40) + 'px';
  hbarChart('sector', $('#chart-sector'), {
    labels: sectors.map(s => s.name), values: sectors.map(s => +s.avg.toFixed(1)),
    max: Math.max(50, Math.ceil(Math.max(...sectors.map(s => s.avg)) / 10) * 10 + 10),
    tip: i => ` ${sectors[i].avg.toFixed(1)} average · ${fmt.plural(sectors[i].n, 'company')} · highest: ${sectors[i].top.name} (${sectors[i].top.score.toFixed(1)})`,
  });
  $('#sector-table').innerHTML = dataTable(['Sector', 'Companies', 'Average score', 'Highest'],
    sectors.map(s => [s.name, s.n, s.avg.toFixed(1), `${s.top.name} (${s.top.score.toFixed(1)})`]));

  // ── Level guide ──
  $('#guide').innerHTML = guideHtml(counts);
}

function guideHtml(counts) {
  return LEVELS.slice().reverse().map(l => `
    <div class="guide-item lvl-${l}">
      <h4>${SHAPE[l]} ${l}<span class="range">score ${levelRange(l)}${counts ? ` · ${fmt.plural(counts[l], 'company')} today` : ''}</span></h4>
      <p>${esc(D.guidance[l])}</p>
    </div>`).join('');
}
