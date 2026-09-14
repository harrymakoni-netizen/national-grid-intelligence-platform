/** Chart.js + Leaflet helpers. */

Chart.defaults.font.family = "'Fira Sans', sans-serif";
Chart.defaults.font.size = 11;
Chart.defaults.color = '#64748B';

const _charts = {};
const _maps = {};

function destroyChart(id) {
  if (_charts[id]) {
    _charts[id].destroy();
    delete _charts[id];
  }
}

function lineChart(canvasId, labels, datasets, opts = {}) {
  destroyChart(canvasId);
  const el = document.getElementById(canvasId);
  if (!el) return null;
  _charts[canvasId] = new Chart(el, {
    type: 'line',
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: opts.legend === false ? { display: false }
          : { display: true, position: 'top', align: 'end', labels: { boxWidth: 10, boxHeight: 10, padding: 12 } },
        tooltip: opts.tooltip || {},
      },
      scales: {
        x: { grid: { display: false }, ticks: { maxTicksLimit: 10, autoSkip: true } },
        y: {
          grid: { color: '#F1F5F9' },
          title: opts.yTitle ? { display: true, text: opts.yTitle, color: '#94A3B8', font: { size: 10 } } : undefined,
          beginAtZero: opts.beginAtZero !== false,
        },
      },
      ...opts.extra,
    },
  });
  return _charts[canvasId];
}

function doughnutChart(canvasId, labels, values, colors) {
  destroyChart(canvasId);
  const el = document.getElementById(canvasId);
  if (!el) return null;
  _charts[canvasId] = new Chart(el, {
    type: 'doughnut',
    data: { labels, datasets: [{ data: values, backgroundColor: colors, borderWidth: 0 }] },
    options: {
      responsive: true,
      cutout: '58%',
      plugins: { legend: { position: 'bottom', labels: { boxWidth: 10, boxHeight: 10, padding: 10, font: { size: 10.5 } } } },
    },
  });
  return _charts[canvasId];
}

/**
 * Transformer map. Circle radius encodes case count, colour encodes the
 * dominant predicted cause -- but every marker also carries a text popup
 * with the same facts, because location meaning must never depend on
 * colour alone (accessibility guidance for geographic charts).
 */
function renderMap(containerId, points, { fitPadding = 40 } = {}) {
  const el = document.getElementById(containerId);
  if (!el) return;

  if (_maps[containerId]) {
    _maps[containerId].remove();
    delete _maps[containerId];
  }
  if (!points || points.length === 0) {
    el.innerHTML = '<div class="p-4 text-[11px] text-mutedfg">No geographic data for this node.</div>';
    return;
  }

  const map = L.map(el, { scrollWheelZoom: false, attributionControl: true });
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap contributors',
  }).addTo(map);

  const latlngs = [];
  points.forEach((p) => {
    const color = p.n_cases > 0 ? (CAUSE_COLORS[p.top_cause] || '#DC2626') : '#16A34A';
    const radius = 9 + Math.min(p.n_cases, 12) * 1.8;
    const marker = L.circleMarker([p.latitude, p.longitude], {
      radius,
      color: '#fff',
      weight: 2,
      fillColor: color,
      fillOpacity: 0.82,
    }).addTo(map);

    marker.bindPopup(
      `<strong>${p.name}</strong><br>` +
      `<span style="font-family:'Fira Code',monospace">${p.id}</span><br>` +
      `${p.n_connections} connections &middot; ${p.rating_kva ?? '?'} kVA<br>` +
      `<strong>${p.n_cases}</strong> open case${p.n_cases === 1 ? '' : 's'}` +
      (p.top_cause ? ` &middot; top: ${p.top_cause}` : '') + '<br>' +
      `est. recoverable ${p.recoverable_kw} kW`
    );
    marker.bindTooltip(`${p.name} — ${p.n_cases} case${p.n_cases === 1 ? '' : 's'}`, { direction: 'top' });
    latlngs.push([p.latitude, p.longitude]);
  });

  map.fitBounds(L.latLngBounds(latlngs), { padding: [fitPadding, fitPadding], maxZoom: 15 });
  _maps[containerId] = map;
  // Leaflet needs a nudge when its container was hidden at creation time.
  setTimeout(() => map.invalidateSize(), 60);
  return map;
}

function invalidateMaps() {
  Object.values(_maps).forEach((m) => m.invalidateSize());
}
