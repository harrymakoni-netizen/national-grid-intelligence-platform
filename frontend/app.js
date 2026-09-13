const API = "";

let currentScenarioId = null;
let currentNodeId = null;
let breadcrumbTrail = []; // [{id, name}]
let nodeChart = null;
let modalChart = null;

const CAUSE_COLORS = {
  solar_adoption: "#D97706",
  vacancy: "#64748B",
  meter_failure: "#DC2626",
  full_bypass: "#DC2626",
  partial_bypass: "#EA580C",
  normal: "#16A34A",
};

async function fetchJSON(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url} -> ${res.status}`);
  return res.json();
}

async function init() {
  const scenarios = await fetchJSON(`${API}/api/scenarios`);
  const select = document.getElementById("scenario-select");
  select.innerHTML = scenarios
    .map((s) => `<option value="${s.id}">${s.substation_id} (seed ${s.seed}, ${s.weeks}w)</option>`)
    .join("");
  select.addEventListener("change", () => loadScenario(select.value));

  if (scenarios.length === 0) {
    document.getElementById("node-title").textContent =
      "No scenarios found -- run scripts/seed_demo_scenario.py first.";
    return;
  }
  await loadScenario(scenarios[0].id);
  await loadModelPerformance();
}

async function loadModelPerformance() {
  try {
    const perf = await fetchJSON(`${API}/api/module-a/held-out-evaluation`);
    const el = document.getElementById("model-performance");
    el.classList.remove("hidden");
    el.innerHTML = `
      <div class="font-semibold mb-1">Module A reconstruction error against held-out REAL interval data</div>
      <div class="text-mutedfg">Source: ${perf.source}</div>
      <div class="flex gap-6 mt-2 font-mono">
        <div>Daily MAE: <span class="text-foreground font-semibold">${perf.daily_mae_kw} kW</span> (${(perf.daily_relative_mae * 100).toFixed(0)}% of mean)</div>
        <div>Monthly MAE: <span class="text-foreground font-semibold">${perf.monthly_mae_kw} kW</span></div>
      </div>`;
  } catch (e) {
    console.warn("model performance unavailable", e);
  }
}

async function loadScenario(scenarioId) {
  currentScenarioId = scenarioId;
  const root = await fetchJSON(`${API}/api/scenarios/${scenarioId}/root`);
  breadcrumbTrail = [{ id: root.id, name: root.name }];
  await loadNode(root.id);
}

async function loadNode(nodeId) {
  currentNodeId = nodeId;
  const node = await fetchJSON(`${API}/api/nodes/${nodeId}?scenario_id=${currentScenarioId}`);

  const idx = breadcrumbTrail.findIndex((b) => b.id === nodeId);
  if (idx >= 0) {
    breadcrumbTrail = breadcrumbTrail.slice(0, idx + 1);
  } else {
    breadcrumbTrail.push({ id: node.id, name: node.name });
  }
  renderBreadcrumb();

  document.getElementById("node-title").textContent = node.name;
  document.getElementById("node-type-badge").textContent = node.node_type;

  renderChildren(node);
  await renderNodeChart(nodeId);
  await renderCaseQueue(nodeId);
}

function renderBreadcrumb() {
  const nav = document.getElementById("breadcrumb");
  nav.innerHTML = breadcrumbTrail
    .map((b, i) => {
      const sep = i > 0 ? '<span class="text-mutedfg mx-1">/</span>' : "";
      return `${sep}<button class="hover:text-primary hover:underline" data-node="${b.id}">${b.name}</button>`;
    })
    .join("");
  nav.querySelectorAll("button").forEach((btn) => {
    btn.addEventListener("click", () => loadNode(btn.dataset.node));
  });
}

function renderChildren(node) {
  const list = document.getElementById("children-list");
  const rows = [];

  for (const child of node.children) {
    rows.push(
      `<button class="w-full text-left px-2 py-1.5 rounded hover:bg-muted flex items-center justify-between" data-node="${child.id}">
        <span>${child.name}</span>
        <span class="text-xs font-mono text-mutedfg">${child.node_type}</span>
      </button>`
    );
  }
  for (const conn of node.connections) {
    rows.push(
      `<button class="w-full text-left px-2 py-1.5 rounded hover:bg-muted flex items-center justify-between" data-conn="${conn.id}">
        <span>${conn.id.split("-").pop()}</span>
        <span class="text-xs font-mono text-mutedfg">${conn.archetype ?? ""} &middot; conf ${conn.confidence.toFixed(2)}</span>
      </button>`
    );
  }

  list.innerHTML = rows.length
    ? rows.join("")
    : '<div class="text-mutedfg text-xs py-2">No children.</div>';

  list.querySelectorAll("button[data-node]").forEach((btn) => {
    btn.addEventListener("click", () => loadNode(btn.dataset.node));
  });
  list.querySelectorAll("button[data-conn]").forEach((btn) => {
    btn.addEventListener("click", () => openCaseModal(btn.dataset.conn));
  });
}

async function renderNodeChart(nodeId) {
  const data = await fetchJSON(`${API}/api/nodes/${nodeId}/timeseries?scenario_id=${currentScenarioId}`);
  document.getElementById("node-conn-count").textContent = data.n_connections;

  const ctx = document.getElementById("node-chart");
  if (nodeChart) nodeChart.destroy();
  nodeChart = new Chart(ctx, {
    type: "line",
    data: {
      labels: data.ts.map((t) => t.slice(0, 10)),
      datasets: [
        {
          label: "Reconstructed consumption (kW)",
          data: data.mean_kw,
          borderColor: "#1E40AF",
          backgroundColor: "rgba(30,64,175,0.1)",
          fill: true,
          tension: 0.2,
          pointRadius: 0,
        },
      ],
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: { x: { ticks: { maxTicksLimit: 10 } } },
    },
  });
}

async function renderCaseQueue(nodeId) {
  const cases = await fetchJSON(`${API}/api/nodes/${nodeId}/cases?scenario_id=${currentScenarioId}`);
  const body = document.getElementById("case-table-body");
  const empty = document.getElementById("case-table-empty");

  if (cases.length === 0) {
    body.innerHTML = "";
    empty.classList.remove("hidden");
    return;
  }
  empty.classList.add("hidden");

  body.innerHTML = cases
    .map((c) => {
      const color = CAUSE_COLORS[c.predicted_cause] ?? "#475569";
      return `<tr class="border-b border-border hover:bg-muted cursor-pointer" data-conn="${c.connection_id}">
        <td class="py-1.5 pr-3 font-mono">${c.connection_id}</td>
        <td class="py-1.5 pr-3"><span class="px-1.5 py-0.5 rounded text-white text-xs" style="background:${color}">${c.predicted_cause}</span></td>
        <td class="py-1.5 pr-3 font-mono">${c.confidence.toFixed(2)}</td>
        <td class="py-1.5 pr-3 font-mono">${c.suspicion_score.toFixed(2)}</td>
        <td class="py-1.5 pr-3 font-mono">${c.estimated_recoverable_kw.toFixed(2)}</td>
      </tr>`;
    })
    .join("");

  body.querySelectorAll("tr").forEach((tr) => {
    tr.addEventListener("click", () => openCaseModal(tr.dataset.conn));
  });
}

async function openCaseModal(connectionId) {
  const modal = document.getElementById("case-modal");
  modal.classList.remove("hidden");
  modal.classList.add("flex");
  document.getElementById("modal-title").textContent = connectionId;
  document.getElementById("modal-subtitle").textContent = "Loading...";
  document.getElementById("modal-ground-truth").classList.add("hidden");
  document.getElementById("modal-evidence").innerHTML = "";

  const [detail, groundTruth, series] = await Promise.all([
    fetchJSON(`${API}/api/cases/${connectionId}?scenario_id=${currentScenarioId}`).catch(() => null),
    fetchJSON(`${API}/api/cases/${connectionId}/ground-truth?scenario_id=${currentScenarioId}`).catch(() => null),
    fetchJSON(`${API}/api/connections/${connectionId}/timeseries?scenario_id=${currentScenarioId}`),
  ]);

  if (detail) {
    const color = CAUSE_COLORS[detail.predicted_cause] ?? "#475569";
    document.getElementById("modal-subtitle").innerHTML =
      `Predicted: <span class="px-1.5 py-0.5 rounded text-white" style="background:${color}">${detail.predicted_cause}</span> ` +
      `&middot; confidence ${detail.confidence.toFixed(2)} &middot; transformer ${detail.transformer_id}`;

    const evidenceRows = Object.entries(detail.evidence)
      .map(([k, v]) => `<tr class="border-b border-border"><td class="py-1 pr-4 text-mutedfg">${k}</td><td class="py-1">${v}</td></tr>`)
      .join("");
    document.getElementById("modal-evidence").innerHTML = evidenceRows;
  } else {
    document.getElementById("modal-subtitle").textContent = "No case classification (insufficient purchase history).";
  }

  if (groundTruth && groundTruth.has_ground_truth) {
    const gt = document.getElementById("modal-ground-truth");
    gt.classList.remove("hidden");
    gt.classList.add("bg-amber-50", "border", "border-accent");
    const matched = detail && detail.predicted_cause === groundTruth.anomaly_type;
    gt.innerHTML = `<span class="font-mono font-semibold">SYNTHETIC GROUND TRUTH:</span> actually injected as
      <span class="font-mono">${groundTruth.anomaly_type}</span> starting ${groundTruth.start_ts.slice(0, 10)}
      (${JSON.stringify(groundTruth.parameters)}) --
      <span class="${matched ? "text-green-700" : "text-destructive"} font-semibold">${matched ? "model matched" : "model did not match"}</span>`;
  }

  const ctx = document.getElementById("modal-chart");
  if (modalChart) modalChart.destroy();
  const purchaseAnnotations = series.purchase_events.map((e) => e.ts.slice(0, 10));
  modalChart = new Chart(ctx, {
    type: "line",
    data: {
      labels: series.ts.map((t) => t.slice(0, 10)),
      datasets: [
        { label: "p90", data: series.p90_kw, borderColor: "transparent", backgroundColor: "rgba(30,64,175,0.12)", fill: "+1", pointRadius: 0 },
        { label: "p10", data: series.p10_kw, borderColor: "transparent", backgroundColor: "rgba(255,255,255,0)", fill: false, pointRadius: 0 },
        { label: "Reconstructed (kW)", data: series.mean_kw, borderColor: "#1E40AF", pointRadius: 0, tension: 0.2 },
      ],
    },
    options: {
      responsive: true,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            afterBody: (items) => {
              const label = items[0]?.label;
              return purchaseAnnotations.includes(label) ? ["⚡ purchase event this day"] : [];
            },
          },
        },
      },
      scales: { x: { ticks: { maxTicksLimit: 8 } } },
    },
  });
}

document.getElementById("modal-close").addEventListener("click", () => {
  document.getElementById("case-modal").classList.add("hidden");
  document.getElementById("case-modal").classList.remove("flex");
});
document.getElementById("case-modal").addEventListener("click", (e) => {
  if (e.target.id === "case-modal") {
    e.currentTarget.classList.add("hidden");
    e.currentTarget.classList.remove("flex");
  }
});

init();
