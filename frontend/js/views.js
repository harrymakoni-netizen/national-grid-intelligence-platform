/**
 * Role-specific views (Section 11.4). Each renders only what the platform
 * can genuinely produce; anything requiring an unbuilt module renders an
 * explicit "not built" state rather than a fabricated chart. Section 15 --
 * a figure must carry what it was computed on -- applies to the UI too.
 */

function kpi(label, value, note, status = '') {
  return `<div class="kpi ${status}">
    <div class="kpi-label">${label}</div>
    <div class="kpi-value">${value}</div>
    <div class="kpi-note">${note || ''}</div>
  </div>`;
}

function notBuilt(title, body, section) {
  return `<div class="not-built">
    <span class="nb-title">${title} &mdash; not built</span>
    ${body}
    <div class="mt-2 text-[11px] text-mutedfg font-mono">${section}</div>
  </div>`;
}

function caseTable(cases, { compact = false } = {}) {
  if (!cases.length) return '<div class="text-[11px] text-mutedfg py-3">No cases flagged.</div>';
  const rows = cases.map((c) => `
    <tr class="clickable" data-conn="${c.connection_id}">
      <td class="font-mono">${c.connection_id}</td>
      <td>${causeBadge(c.predicted_cause)}</td>
      <td class="font-mono">${fmtNum(c.confidence)}</td>
      ${compact ? '' : `<td class="font-mono">${fmtNum(c.suspicion_score)}</td>`}
      <td class="font-mono">${fmtNum(c.estimated_recoverable_kw)}</td>
    </tr>`).join('');
  return `<table class="data">
    <thead><tr>
      <th>Connection</th><th>Predicted cause</th><th>Confidence</th>
      ${compact ? '' : '<th>Suspicion</th>'}<th>Recoverable (kW)</th>
    </tr></thead>
    <tbody>${rows}</tbody></table>`;
}

function wireCaseRows(container) {
  container.querySelectorAll('tr[data-conn]').forEach((tr) => {
    tr.addEventListener('click', () => openCaseModal(tr.dataset.conn));
  });
}

/* ---------------- EXECUTIVE ---------------- */
async function renderExecutive() {
  const s = State.summary;
  const solar = s.cases_by_cause.solar_adoption?.n || 0;
  const theftish = (s.cases_by_cause.partial_bypass?.n || 0)
    + (s.cases_by_cause.full_bypass?.n || 0);

  document.getElementById('exec-kpis').innerHTML = [
    kpi('Connections monitored', s.n_connections,
        `${s.n_transformers} distribution transformers`),
    kpi('Open cases', s.n_cases,
        `${theftish} theft-family &middot; ${s.cases_by_cause.vacancy?.n || 0} vacancy`,
        s.n_cases > 0 ? 'warn' : 'ok'),
    kpi('Est. recoverable', `${fmtNum(s.total_recoverable_kw)} kW`,
        `${fmtNum(s.recoverable_kwh_90d, 0)} kWh over a 90-day window`, 'bad'),
    kpi('Distributed solar detected', solar,
        solar === 0 ? 'see model limitations in About' : 'connections with inferred PV', 'ok'),
  ].join('');

  const ts = await DataSource.nodeTimeseries(State.rootId, State.scenarioId);
  lineChart('exec-chart', ts.ts.map((t) => t.slice(0, 10)), [{
    label: 'Estimated consumption (kW)',
    data: ts.mean_kw,
    borderColor: '#1E40AF',
    backgroundColor: 'rgba(30,64,175,0.10)',
    fill: true, tension: 0.25, pointRadius: 0, borderWidth: 2,
  }], { legend: false, yTitle: 'kW' });

  const causes = Object.keys(s.cases_by_cause);
  doughnutChart('exec-cause-chart',
    causes,
    causes.map((c) => s.cases_by_cause[c].recoverable_kw),
    causes.map((c) => CAUSE_COLORS[c] || '#475569'));

  const el = document.getElementById('exec-top-cases');
  el.innerHTML = caseTable(s.top_cases, { compact: true });
  wireCaseRows(el);
}

/* ---------------- REVENUE PROTECTION ---------------- */
async function renderRevenue() {
  const s = State.summary;
  const cases = await DataSource.nodeCases(State.rootId, State.scenarioId);

  document.getElementById('rev-kpis').innerHTML = [
    kpi('Cases in queue', cases.length, 'ranked by confidence', 'warn'),
    kpi('Est. recoverable', `${fmtNum(s.total_recoverable_kw)} kW`, 'across all open cases', 'bad'),
    kpi('Highest-value case', cases.length ? `${fmtNum(cases.reduce((a, b) => a.estimated_recoverable_kw > b.estimated_recoverable_kw ? a : b).estimated_recoverable_kw)} kW` : '—', 'single connection'),
    kpi('Inspector capacity', 'not modelled', 'requires the field loop (item 9)'),
  ].join('');

  const tbl = document.getElementById('rev-case-table');
  tbl.innerHTML = caseTable(cases);
  wireCaseRows(tbl);

  const mapData = await DataSource.nodeMap(State.rootId, State.scenarioId);
  renderMap('rev-map', mapData.points);

  const prec = await DataSource.revenueProtection(State.scenarioId);
  const block = (title, ev) => {
    if (!ev || ev.n_cases === 0) return `<div class="kpi"><div class="kpi-label">${title}</div><div class="kpi-value">&mdash;</div></div>`;
    const pct = (v) => v === null ? '—' : `${Math.round(v * 100)}%`;
    return `<div class="kpi ${ev.exact_precision >= 0.4 ? 'ok' : 'warn'}">
      <div class="kpi-label">${title}</div>
      <div class="kpi-value">${pct(ev.exact_precision)}</div>
      <div class="kpi-note">${pct(ev.confusable_aware_precision)} allowing meter-failure / full-bypass confusion &middot; n=${ev.n_cases}</div>
    </div>`;
  };
  document.getElementById('rev-precision').innerHTML =
    block('Precision @ top 3', prec.precision_at_3) +
    block('Precision @ top 5', prec.precision_at_5) +
    block('Precision, whole queue', prec.precision_full_queue);
}

/* ---------------- NETWORK OPERATIONS ---------------- */
async function renderNetwork() {
  const s = State.summary;
  const mapData = await DataSource.nodeMap(State.rootId, State.scenarioId);

  const totalCases = mapData.points.reduce((a, p) => a + p.n_cases, 0);
  document.getElementById('net-kpis').innerHTML = [
    kpi('Transformers', s.n_transformers, 'with a digital twin model'),
    kpi('Connections placed', mapData.points.reduce((a, p) => a + p.n_connections, 0),
        'resolved to a transformer'),
    kpi('Transformers with cases', mapData.points.filter((p) => p.n_cases > 0).length,
        `${totalCases} cases total`, totalCases ? 'warn' : 'ok'),
    kpi('Asset health', 'not available', 'Module C not built'),
  ].join('');

  const select = document.getElementById('net-transformer-select');
  if (!select.dataset.filled) {
    select.innerHTML = mapData.points.map((p) => `<option value="${p.id}">${p.name} (${p.id})</option>`).join('');
    select.dataset.filled = '1';
    select.addEventListener('change', () => renderNonTechnicalLoss(select.value));
  }
  if (mapData.points.length) await renderNonTechnicalLoss(select.value || mapData.points[0].id);

  renderMap('net-map', mapData.points);

  document.getElementById('net-module-c').innerHTML = notBuilt(
    'Transformer health &amp; remaining useful life',
    `Survival analysis over thermal, loading, harmonic and imbalance history requires the grid sensing
     device (build item 6) to have accumulated real telemetry. No device exists yet, so there is no
     hazard model, no remaining-life estimate and no thermal alarm here &mdash; showing one would be
     fabricated.`,
    'Specification Section 8.3 &middot; build sequence item 11');
}

async function renderNonTechnicalLoss(transformerId) {
  const d = await DataSource.nodeNonTechnicalLoss(transformerId, State.scenarioId);
  const pct = d.mean_measured_kw ? (100 * d.mean_nontechnical_loss_kw / d.mean_measured_kw) : 0;
  document.getElementById('net-coverage').innerHTML =
    `twin coverage ${Math.round(d.twin_coverage_fraction * 100)}% &middot; ` +
    `mean residual <strong>${fmtNum(d.mean_nontechnical_loss_kw)} kW</strong> ` +
    `(${fmtNum(pct, 1)}% of inflow)`;

  const note = document.getElementById('net-ntl-note');
  if (note) {
    note.innerHTML = (d.metered_connection_ids && d.metered_connection_ids.length)
      ? `<span class="badge badge-slate">meter reads used</span>
         ${d.metered_connection_ids.length} industrial connection${d.metered_connection_ids.length === 1 ? '' : 's'}
         (<span class="font-mono">${d.metered_connection_ids.join(', ')}</span>) are accounted from post-paid meter
         reads, not reconstructed from vending events. Reconstructing a customer who buys in rare bulk lots
         understates them badly &mdash; on this feeder that single connection alone produced a 23&nbsp;kW phantom
         residual that looked exactly like theft. A real utility already holds these meter reads (Section 3.1).`
      : '';
  }

  lineChart('net-ntl-chart', d.ts.map((t) => t.slice(0, 10)), [
    { label: 'Energy into transformer (sensor-emulated)', data: d.measured_kw,
      borderColor: '#0F172A', borderWidth: 2, pointRadius: 0, tension: 0.25 },
    { label: 'Accounted to customers (Module A)', data: d.accounted_kw,
      borderColor: '#3B82F6', borderWidth: 2, pointRadius: 0, tension: 0.25 },
    { label: 'Modelled technical loss (digital twin)', data: d.modelled_technical_loss_kw,
      borderColor: '#16A34A', borderWidth: 2, pointRadius: 0, tension: 0.25 },
    { label: 'Non-technical loss (residual)', data: d.nontechnical_loss_kw,
      borderColor: '#DC2626', backgroundColor: 'rgba(220,38,38,0.12)', borderWidth: 2,
      pointRadius: 0, tension: 0.25, fill: true, borderDash: [4, 3] },
  ], { yTitle: 'kW', beginAtZero: false });
}

/* ---------------- SYSTEM CONTROL ---------------- */
async function renderControl() {
  const ts = await DataSource.nodeTimeseries(State.rootId, State.scenarioId);
  lineChart('ctl-chart', ts.ts.map((t) => t.slice(0, 10)), [{
    label: 'Observed demand (kW)', data: ts.mean_kw,
    borderColor: '#1E40AF', backgroundColor: 'rgba(30,64,175,0.08)',
    fill: true, tension: 0.25, pointRadius: 0, borderWidth: 2,
  }], { legend: false, yTitle: 'kW' });

  document.getElementById('ctl-module-d').innerHTML = notBuilt(
    'Day-ahead and week-ahead demand forecasting',
    `Gradient-boosted quantile regression over lagged demand, calendar features, temperature and
     shedding history. The chart above is <strong>historical reconstruction only</strong> &mdash; there is
     no forecast in this system, and the curve must not be read as one.`,
    'Specification Section 8.4 &middot; build sequence item 11');

  document.getElementById('ctl-module-e').innerHTML = notBuilt(
    'Criticality-weighted shedding allocation',
    `A mixed-integer optimisation balancing critical load protection, equity of cumulative outage hours,
     transformer thermal stress and switching feasibility. It consumes a demand forecast, so it cannot be
     built before Module D. Note the specification is explicit that this optimiser is
     <em>not</em> machine learning and must not be presented as such.`,
    'Specification Section 9.1 &middot; build sequence item 12');

  const cfg = State.scenarioConfig || {};
  const sched = cfg.shedding_schedule_by_group || {};
  const groups = Object.keys(sched);
  const el = document.getElementById('ctl-shedding');
  if (!groups.length) {
    el.innerHTML = '<div class="text-[11px] text-mutedfg py-2">No shedding schedule recorded for this scenario.</div>';
    return;
  }
  const dayNames = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  const rows = groups.map((g) => {
    const windows = sched[g].map((w) =>
      `${dayNames[w.dow]} ${String(w.start_hour).padStart(2, '0')}:00&ndash;${String(w.end_hour).padStart(2, '0')}:00`);
    const shown = windows.slice(0, 6).join(', ') + (windows.length > 6 ? ` &hellip; (+${windows.length - 6} more)` : '');
    return `<tr><td class="font-mono">Group ${g}</td><td>${sched[g].length} windows/week</td><td class="text-[11px] text-mutedfg">${shown}</td></tr>`;
  }).join('');
  el.innerHTML = `<table class="data"><thead><tr><th>Group</th><th>Windows</th><th>Schedule</th></tr></thead><tbody>${rows}</tbody></table>
    <p class="text-[11px] text-mutedfg mt-3">
      This schedule is a documented approximation of publicly-reported ZESA patterns, generated with the
      scenario &mdash; not a transcription of a real published schedule. It matters because every consumption
      baseline in Zimbabwe is distorted by shedding, and Module A conditions on it explicitly.</p>`;
}

/* ---------------- REGULATORY ---------------- */
async function renderRegulatory() {
  const s = State.summary;
  const root = await DataSource.node(State.rootId, State.scenarioId);
  const ts = await DataSource.nodeTimeseries(State.rootId, State.scenarioId);
  const meanKw = ts.mean_kw.reduce((a, b) => a + b, 0) / (ts.mean_kw.length || 1);

  document.getElementById('reg-trace').innerHTML = `
    <div class="text-[12.5px] leading-relaxed">
      <div class="font-mono text-[12px] mb-3">
        National estimated consumption = <strong>${fmtNum(meanKw)} kW</strong> (period mean)
      </div>
      <ol class="space-y-2 ml-1">
        <li>&#8594; <strong>Aggregated from</strong> ${ts.n_connections} connections resolved beneath
            <span class="font-mono">${root.id}</span>, summed at each interval.</li>
        <li>&#8594; <strong>Each connection's series</strong> is Module A's reconstruction from that
            connection's prepaid vending events &mdash; not a meter read, and carrying a stated
            uncertainty band (p10&ndash;p90).</li>
        <li>&#8594; <strong>Each reconstruction</strong> respects a hard bound: cumulative consumption can
            never exceed cumulative purchases, by construction.</li>
        <li>&#8594; <strong>Connections are attributed</strong> to a transformer through a confidence-scored
            association, versioned over time &mdash; never an assumed fact
            (Section 11.1).</li>
        <li>&#8594; <strong>Technical loss</strong> is computed by an OpenDSS power-flow solution over the
            feeder's unbalanced LV network, not an assumed percentage.</li>
      </ol>
    </div>`;

  document.getElementById('reg-provenance').innerHTML = `
    <p class="mb-3">Every figure this platform produces carries the basis it was computed on. For this scenario:</p>
    <table class="data">
      <thead><tr><th>Quantity</th><th>Basis</th><th>Status</th></tr></thead>
      <tbody>
        <tr><td>Consumption profiles</td><td>Module A reconstruction from vending events</td><td><span class="badge badge-amber">estimated</span></td></tr>
        <tr><td>Technical loss</td><td>OpenDSS power flow over surveyed network parameters</td><td><span class="badge badge-amber">modelled</span></td></tr>
        <tr><td>Energy into transformer</td><td>Sensor-emulated from scenario ground truth</td><td><span class="badge badge-red">no hardware yet</span></td></tr>
        <tr><td>Case classifications</td><td>Weak supervision over consumption + vending features</td><td><span class="badge badge-amber">estimated</span></td></tr>
        <tr><td>Queue precision</td><td>Synthetic ground truth, not field-confirmed outcomes</td><td><span class="badge badge-red">not a field result</span></td></tr>
        <tr><td>Reliability indices (SAIDI/SAIFI)</td><td>Requires outage records the platform does not yet ingest</td><td><span class="badge badge-slate">not built</span></td></tr>
      </tbody>
    </table>
    <p class="mt-3 text-[11px] text-mutedfg">
      Automated regulatory submission generation (Section 11.5) is not built. The traceability chain above is
      the foundation it would rest on.</p>`;
}

/* ---------------- INDUSTRIAL ---------------- */
async function renderIndustrial() {
  const s = State.summary;
  const nInd = s.archetype_counts.industrial || 0;
  const nCom = s.archetype_counts.small_commercial || 0;

  document.getElementById('ind-kpis').innerHTML = [
    kpi('Industrial sites', nInd, 'on this feeder'),
    kpi('Commercial sites', nCom, 'small commercial tariff'),
    kpi('Maximum-demand exposure', 'not modelled', 'needs tariff + interval data'),
    kpi('Identified savings', 'not available', 'Module G not built'),
  ].join('');

  // Industrial/commercial connections, resolved through the transformer tree.
  const mapData = await DataSource.nodeMap(State.rootId, State.scenarioId);
  const rows = [];
  for (const p of mapData.points) {
    const node = await DataSource.node(p.id, State.scenarioId);
    for (const c of node.connections) {
      if (c.archetype === 'industrial' || c.archetype === 'small_commercial') {
        rows.push(`<tr class="clickable" data-conn="${c.id}">
          <td class="font-mono">${c.id}</td>
          <td>${c.archetype === 'industrial' ? '<span class="badge badge-red">industrial</span>' : '<span class="badge badge-slate">commercial</span>'}</td>
          <td class="font-mono">${p.name}</td>
          <td>${c.status}</td>
          <td class="font-mono">${fmtNum(c.confidence)}</td>
        </tr>`);
      }
    }
  }
  const tbl = document.getElementById('ind-table');
  tbl.innerHTML = rows.length
    ? `<table class="data"><thead><tr><th>Connection</th><th>Class</th><th>Transformer</th><th>Status</th><th>Assoc. confidence</th></tr></thead><tbody>${rows.join('')}</tbody></table>`
    : '<div class="text-[11px] text-mutedfg py-3">No industrial or commercial connections on this feeder.</div>';
  wireCaseRows(tbl);

  document.getElementById('ind-module-g').innerHTML = notBuilt(
    'Non-intrusive load monitoring (per-machine disaggregation)',
    `Sequence-to-point convolutional disaggregation of a plant's aggregate demand into motors, compressors,
     chillers and furnaces. It needs high-resolution interval data from a real site plus a supervised
     commissioning exercise &mdash; neither of which exists yet. This is the Path A commercial product and
     the first extension module scheduled, but nothing here is built.`,
    'Specification Section 9.3 &middot; build sequence item 10');
}

/* ---------------- NETWORK EXPLORER ---------------- */
let breadcrumbTrail = [];

async function renderExplorer(nodeId) {
  const targetId = nodeId || State.rootId;
  const node = await DataSource.node(targetId, State.scenarioId);

  const idx = breadcrumbTrail.findIndex((b) => b.id === targetId);
  if (idx >= 0) breadcrumbTrail = breadcrumbTrail.slice(0, idx + 1);
  else breadcrumbTrail.push({ id: node.id, name: node.name });

  const nav = document.getElementById('breadcrumb');
  nav.innerHTML = breadcrumbTrail.map((b, i) =>
    `${i > 0 ? '<span class="text-mutedfg mx-1">/</span>' : ''}<button class="hover:text-primary hover:underline" data-node="${b.id}">${b.name}</button>`).join('');
  nav.querySelectorAll('button').forEach((btn) =>
    btn.addEventListener('click', () => renderExplorer(btn.dataset.node)));

  document.getElementById('node-title').textContent = node.name;
  document.getElementById('node-type-badge').textContent = node.node_type;

  const list = document.getElementById('children-list');
  const rows = [];
  node.children.forEach((c) => rows.push(
    `<button class="tree-row" data-node="${c.id}">
      <span>${c.name}</span><span class="text-[10.5px] font-mono text-mutedfg">${c.node_type}</span>
    </button>`));
  node.connections.forEach((c) => rows.push(
    `<button class="tree-row" data-conn="${c.id}">
      <span class="font-mono text-[11.5px]">${c.id}</span>
      <span class="text-[10.5px] font-mono text-mutedfg">${c.archetype || ''}</span>
    </button>`));
  list.innerHTML = rows.length ? rows.join('') : '<div class="text-[11px] text-mutedfg py-2">No children.</div>';
  list.querySelectorAll('button[data-node]').forEach((b) =>
    b.addEventListener('click', () => renderExplorer(b.dataset.node)));
  list.querySelectorAll('button[data-conn]').forEach((b) =>
    b.addEventListener('click', () => openCaseModal(b.dataset.conn)));

  const ts = await DataSource.nodeTimeseries(targetId, State.scenarioId);
  document.getElementById('node-conn-count').textContent = ts.n_connections;
  lineChart('node-chart', ts.ts.map((t) => t.slice(0, 10)), [{
    label: 'Estimated consumption (kW)', data: ts.mean_kw,
    borderColor: '#1E40AF', backgroundColor: 'rgba(30,64,175,0.10)',
    fill: true, tension: 0.25, pointRadius: 0, borderWidth: 2,
  }], { legend: false, yTitle: 'kW' });

  const cases = await DataSource.nodeCases(targetId, State.scenarioId);
  const tbl = document.getElementById('explorer-case-table');
  tbl.innerHTML = caseTable(cases);
  wireCaseRows(tbl);
}

/* ---------------- ABOUT ---------------- */
async function renderAbout() {
  const s = State.summary;
  const built = [
    ['Network hierarchy &amp; confidence-scored association', 'Section 5.1, 11.1', true],
    ['Synthetic vending &amp; network generator', 'Section 12.1', true],
    ['Ingestion &amp; time-series storage (MQTT + HTTP)', 'Section 11.2', true],
    ['Feeder digital twin (OpenDSS power flow)', 'Section 7', true],
    ['Module A &mdash; consumption reconstruction', 'Section 8.1', true],
    ['Module B &mdash; loss attribution (stages 1&ndash;2)', 'Section 8.2', true],
    ['Drill-down interface', 'Section 11.3', true],
    ['Grid sensing device firmware', 'Section 6 &middot; item 6', false],
    ['Module C &mdash; asset health / remaining life', 'Section 8.3', false],
    ['Module D &mdash; demand forecasting', 'Section 8.4', false],
    ['Module E &mdash; shedding allocation', 'Section 9.1', false],
    ['Module G &mdash; industrial NILM', 'Section 9.3', false],
    ['Field operations app &amp; label feedback loop', 'Section 10 &middot; item 9', false],
    ['Module B stage 3 &mdash; supervised on field labels', 'Section 8.2', false],
  ];
  document.getElementById('about-modules').innerHTML = `<table class="data">
    <thead><tr><th>Component</th><th>Specification</th><th>Status</th></tr></thead>
    <tbody>${built.map(([name, sec, done]) => `<tr>
      <td>${name}</td><td class="text-[11px] text-mutedfg font-mono">${sec}</td>
      <td>${done ? '<span class="badge badge-green">built &amp; tested</span>' : '<span class="badge badge-slate">not built</span>'}</td>
    </tr>`).join('')}</tbody></table>`;

  let perfHtml = '';
  try {
    const perf = await DataSource.heldOutEvaluation();
    perfHtml += `<div class="kpi">
      <div class="kpi-label">Module A reconstruction error</div>
      <div class="kpi-value">${fmtNum(perf.daily_mae_kw, 3)} kW</div>
      <div class="kpi-note">daily MAE against <strong>real held-out interval data</strong> (${Math.round(perf.daily_relative_mae * 100)}% of mean).
        ${perf.source}</div>
    </div>`;
  } catch { /* static snapshot may omit it */ }

  perfHtml += `<div class="text-[12px] leading-relaxed space-y-2">
    <p><strong>Known limitations, stated plainly.</strong> Solar-adoption detection is the weakest part of
    Module B, for a structural reason: Module A reconstructs a connection's consumption by scaling one fixed
    daily shape, so it cannot represent a <em>shape</em> change. A real solar adopter's signature
    (daylight collapses &minus;99.7%, evening untouched &plus;4.9% in this scenario's ground truth) is flattened
    to a uniform reduction before Module B ever sees it. That is an information gap between the two modules,
    not a threshold to tune.</p>
    <p>Queue precision is roughly 47% at the top three cases and ~15% across the whole queue, measured on
    synthetic ground truth across ten independent scenarios. The gap between those two numbers is the point:
    ranking works, and inspector capacity is the binding constraint.</p>
  </div>`;
  document.getElementById('about-performance').innerHTML = perfHtml;
}

/* ---------------- CASE MODAL ---------------- */
async function openCaseModal(connectionId) {
  const modal = document.getElementById('case-modal');
  modal.classList.remove('hidden');
  modal.classList.add('flex');
  document.getElementById('modal-title').textContent = connectionId;
  document.getElementById('modal-subtitle').textContent = 'Loading…';
  document.getElementById('modal-ground-truth').classList.add('hidden');
  document.getElementById('modal-evidence').innerHTML = '';

  const [detail, gt, series] = await Promise.all([
    DataSource.caseDetail(connectionId, State.scenarioId).catch(() => null),
    DataSource.caseGroundTruth(connectionId, State.scenarioId).catch(() => null),
    DataSource.connectionTimeseries(connectionId, State.scenarioId).catch(() => ({ ts: [], mean_kw: [], p10_kw: [], p90_kw: [], purchase_events: [] })),
  ]);

  if (detail) {
    document.getElementById('modal-subtitle').innerHTML =
      `Predicted ${causeBadge(detail.predicted_cause)} &middot; confidence ${fmtNum(detail.confidence)} &middot; transformer <span class="font-mono">${detail.transformer_id}</span>`;
    document.getElementById('modal-evidence').innerHTML = Object.entries(detail.evidence)
      .map(([k, v]) => `<tr><td class="py-1 pr-4 text-mutedfg">${k}</td><td class="py-1">${v}</td></tr>`).join('');
  } else {
    document.getElementById('modal-subtitle').textContent =
      'No case classification — insufficient purchase history to reconstruct.';
  }

  if (gt && gt.has_ground_truth) {
    const el = document.getElementById('modal-ground-truth');
    const matched = detail && detail.predicted_cause === gt.anomaly_type;
    el.className = 'mb-4 rounded p-3 text-[12px] border ' +
      (matched ? 'bg-green-50 border-green-300' : 'bg-amber-50 border-amber-300');
    el.innerHTML = `<span class="font-mono font-semibold">SYNTHETIC GROUND TRUTH</span> &mdash; actually injected as
      <span class="font-mono font-semibold">${gt.anomaly_type}</span> from ${gt.start_ts.slice(0, 10)}
      <span class="text-mutedfg">${JSON.stringify(gt.parameters)}</span><br>
      <span class="${matched ? 'text-green-700' : 'text-amber-700'} font-semibold">
        ${matched ? '✓ model classification matched' : '✗ model classification did not match'}</span>`;
  }

  const purchaseDays = new Set((series.purchase_events || []).map((e) => e.ts.slice(0, 10)));
  lineChart('modal-chart', series.ts.map((t) => t.slice(0, 10)), [
    { label: 'p90', data: series.p90_kw, borderColor: 'transparent', backgroundColor: 'rgba(30,64,175,0.13)', fill: '+1', pointRadius: 0 },
    { label: 'p10', data: series.p10_kw, borderColor: 'transparent', fill: false, pointRadius: 0 },
    { label: 'Reconstructed (kW)', data: series.mean_kw, borderColor: '#1E40AF', borderWidth: 2, pointRadius: 0, tension: 0.25 },
  ], {
    legend: false, yTitle: 'kW',
    tooltip: { callbacks: { afterBody: (items) => purchaseDays.has(items[0]?.label) ? ['⚡ prepaid purchase this day'] : [] } },
  });
}
