/** Navigation, scenario selection, and view lifecycle. */

const VIEWS = [
  { section: 'Operations' },
  { id: 'executive', label: 'Executive', title: 'Executive',
    subtitle: 'National loss exposure and recovery opportunity at a glance',
    icon: 'M3 3v18h18M7 15l4-5 3 3 5-7' },
  { id: 'revenue', label: 'Revenue protection', title: 'Revenue protection',
    subtitle: 'Ranked case queue, evidence, and geographic concentration',
    icon: 'M12 2 4 6v6c0 5 3.4 8.6 8 10 4.6-1.4 8-5 8-10V6l-8-4z' },
  { id: 'network', label: 'Network operations', title: 'Network operations',
    subtitle: 'Energy balance, technical vs non-technical loss, asset coverage',
    icon: 'M4 20h16M6 16V8m6 8V4m6 12v-6' },
  { id: 'control', label: 'System control', title: 'System control',
    subtitle: 'Observed demand and the load-shedding regime in effect',
    icon: 'M12 2v6m0 8v6M2 12h6m8 0h6' },
  { section: 'Compliance & customers' },
  { id: 'regulatory', label: 'Regulatory', title: 'Regulatory & compliance',
    subtitle: 'Traceability of every reported figure back to source',
    icon: 'M6 2h9l5 5v15H6zM15 2v5h5' },
  { id: 'industrial', label: 'Industrial customer', title: 'Industrial customer',
    subtitle: 'Tenant view for large commercial and industrial sites',
    icon: 'M3 21V9l6 4V9l6 4V9l6 4v8z' },
  { section: 'Explore' },
  { id: 'explorer', label: 'Network explorer', title: 'Network explorer',
    subtitle: 'National aggregate down to an individual connection',
    icon: 'M4 6h16M7 12h13M10 18h10' },
  { id: 'about', label: 'About this build', title: 'About this build',
    subtitle: 'What is built, what is not, and how each figure was produced',
    icon: 'M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM12 8h.01M11 12h1v5h1' },
];

let currentView = 'executive';
const rendered = new Set();

function buildNav() {
  const nav = document.getElementById('role-nav');
  nav.innerHTML = VIEWS.map((v) => {
    if (v.section) return `<div class="nav-section">${v.section}</div>`;
    return `<button class="nav-item" data-view="${v.id}" aria-pressed="false">
      <svg class="w-4 h-4 shrink-0 opacity-80" viewBox="0 0 24 24" fill="none" stroke="currentColor"
           stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="${v.icon}"/></svg>
      <span>${v.label}</span>
    </button>`;
  }).join('');

  nav.querySelectorAll('.nav-item').forEach((btn) => {
    btn.addEventListener('click', () => switchView(btn.dataset.view));
  });
}

async function switchView(viewId) {
  currentView = viewId;
  const meta = VIEWS.find((v) => v.id === viewId);

  document.querySelectorAll('#role-nav .nav-item').forEach((b) =>
    b.setAttribute('aria-pressed', String(b.dataset.view === viewId)));
  document.querySelectorAll('.view').forEach((s) =>
    s.classList.toggle('hidden', s.dataset.view !== viewId));

  document.getElementById('view-title').textContent = meta.title;
  document.getElementById('view-subtitle').textContent = meta.subtitle;

  try {
    if (viewId === 'executive') await renderExecutive();
    else if (viewId === 'revenue') await renderRevenue();
    else if (viewId === 'network') await renderNetwork();
    else if (viewId === 'control') await renderControl();
    else if (viewId === 'regulatory') await renderRegulatory();
    else if (viewId === 'industrial') await renderIndustrial();
    else if (viewId === 'explorer') { breadcrumbTrail = []; await renderExplorer(State.rootId); }
    else if (viewId === 'about') await renderAbout();
    rendered.add(viewId);
  } catch (err) {
    console.error(`view ${viewId} failed`, err);
  }
  invalidateMaps();
}

async function loadScenario(scenarioId) {
  State.scenarioId = scenarioId;
  document.getElementById('loading').classList.remove('hidden');

  const scenarios = await DataSource.scenarios();
  const meta = scenarios.find((s) => s.id === scenarioId) || scenarios[0];
  State.scenarioConfig = meta && meta.config ? meta.config : null;

  const root = await DataSource.root(scenarioId);
  State.rootId = root.id;
  State.summary = await DataSource.summary(scenarioId);

  const mode = await DataSource.mode();
  document.getElementById('view-context').innerHTML =
    `${meta ? meta.substation_id : ''} &middot; seed ${meta ? meta.seed : '?'} &middot; ` +
    `${State.summary.n_connections} connections &middot; ` +
    `<span class="${mode === 'live' ? 'text-green-600' : 'text-mutedfg'}">${mode === 'live' ? 'live backend' : 'static snapshot'}</span>`;

  document.getElementById('loading').classList.add('hidden');
  rendered.clear();
  await switchView(currentView);
}

async function init() {
  buildNav();

  document.getElementById('modal-close').addEventListener('click', closeModal);
  document.getElementById('case-modal').addEventListener('click', (e) => {
    if (e.target.id === 'case-modal') closeModal();
  });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeModal(); });

  let scenarios = [];
  try {
    scenarios = await DataSource.scenarios();
  } catch (err) {
    document.getElementById('loading').innerHTML =
      '<div class="card"><strong>No scenario data found.</strong><br>' +
      '<span class="text-mutedfg text-xs">Run <code>python scripts/seed_demo_scenario.py</code> then start the API, ' +
      'or generate the static snapshot with <code>python scripts/export_static_api.py</code>.</span></div>';
    return;
  }

  const select = document.getElementById('scenario-select');
  select.innerHTML = scenarios.map((s) =>
    `<option value="${s.id}">${s.substation_id} · seed ${s.seed}</option>`).join('');
  select.addEventListener('change', () => loadScenario(select.value));

  if (scenarios.length) await loadScenario(scenarios[0].id);
}

function closeModal() {
  const m = document.getElementById('case-modal');
  m.classList.add('hidden');
  m.classList.remove('flex');
}

init();
