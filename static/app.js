// ---- RoamRadar Frontend ----

const VT_CENTER = [37.230, -80.424];
const map = L.map('map', { tap: true }).setView(VT_CENTER, 15);

// Ensure Leaflet recalculates container size after layout settles (critical for mobile)
setTimeout(() => map.invalidateSize(), 100);
setTimeout(() => map.invalidateSize(), 500);

let resizeTimer = null;
window.addEventListener('resize', () => {
  if (resizeTimer) clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => map.invalidateSize(), 150);
});

// Also invalidate when returning to the page (mobile browsers may pause rendering)
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) setTimeout(() => map.invalidateSize(), 200);
});

L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '&copy; OpenStreetMap', maxZoom: 19
}).addTo(map);

let userMarker = null;
let coverageLayer = null;
let recMarkers = [];

// ---- Score → color ----
function scoreColor(s) {
  if (s >= 80) return '#2ecc71';
  if (s >= 60) return '#f1c40f';
  if (s >= 40) return '#e67e22';
  return '#e74c3c';
}

function scoreClass(s) {
  if (s >= 80) return 'score-excellent';
  if (s >= 60) return 'score-good';
  if (s >= 40) return 'score-poor';
  return 'score-bad';
}

function qualityLabel(s) {
  if (s >= 80) return 'Excellent';
  if (s >= 60) return 'Good';
  if (s >= 40) return 'Poor';
  return 'Bad';
}

// ---- Campus reference locations (solid score-colored circles) ----
fetch('/api/locations')
  .then(r => r.json())
  .then(data => {
    const locLayer = L.layerGroup();
    data.features.forEach(f => {
      const [lon, lat] = f.geometry.coordinates;
      const p = f.properties;
      const score = p.teams_ready_score;
      const color = score != null ? scoreColor(score) : '#888';
      L.circleMarker([lat, lon], {
        radius: 10,
        fillColor: color,
        color: color,
        fillOpacity: 0.75,
        weight: 2,
      }).addTo(locLayer)
        .bindPopup(
          `<div style="font-size:13px;line-height:1.5">` +
          `<strong>${p.name}</strong><br>` +
          `<span style="color:${color}">●</span> Score: ${score != null ? score : 'N/A'}${score != null ? ' (' + qualityLabel(score) + ')' : ''}<br>` +
          `Signal: ${p.signal_pct != null ? p.signal_pct + '%' : 'N/A'}<br>` +
          `</div>`
        );
    });
    locLayer.addTo(map);
    locLayer.eachLayer(l => l.bringToBack());
    console.log(`Loaded ${data.features.length} campus locations`);
  })
  .catch(err => console.error('Location load failed:', err));

// ---- Real data points from CSVs (small score-colored circles) ----
fetch('/api/coverage')
  .then(r => r.json())
  .then(data => {
    const realLayer = L.layerGroup();
    data.features.filter(f => f.properties.data_source === 'real').forEach(f => {
      const [lon, lat] = f.geometry.coordinates;
      const p = f.properties;
      const color = scoreColor(p.teams_ready_score);
      L.circleMarker([lat, lon], {
        radius: 5,
        fillColor: color,
        color: color,
        fillOpacity: 0.9,
        weight: 1,
      }).addTo(realLayer)
        .bindPopup(
          `<div style="font-size:13px;line-height:1.5">` +
          `<strong>${p.location_name}</strong><br>` +
          `<span style="color:${color}">●</span> Score: ${p.teams_ready_score} (${qualityLabel(p.teams_ready_score)})<br>` +
          `Signal: ${p.signal_pct}% · RSSI: ${p.estimated_rssi_dbm} dBm<br>` +
          `Band: ${p.band} · Latency: ${p.latency_ms}ms<br>` +
          `Download: ${p.download_mbps != null ? p.download_mbps + ' Mbps' : 'N/A'}<br>` +
          `<em style="color:#888">real</em>` +
          `</div>`
        );
    });
    realLayer.addTo(map);
    console.log(`Loaded real data points`);
  })
  .catch(err => console.error('Real data load failed:', err));

// ---- GPS button ----
document.getElementById('gps-btn').addEventListener('click', () => {
  if (!navigator.geolocation) { alert('Geolocation not supported'); return; }
  navigator.geolocation.getCurrentPosition(pos => {
    const lat = pos.coords.latitude, lon = pos.coords.longitude;
    setUserLocation(lat, lon);
  }, err => {
    alert('Could not get location: ' + err.message);
  });
});

// ---- Manual input ----
document.getElementById('lookup-btn').addEventListener('click', () => {
  const lat = parseFloat(document.getElementById('lat-input').value);
  const lon = parseFloat(document.getElementById('lon-input').value);
  if (lat && lon) setUserLocation(lat, lon);
});

// ---- Map click ----
map.on('click', e => setUserLocation(e.latlng.lat, e.latlng.lng));

// ---- Set user location & query ----
function setUserLocation(lat, lon) {
  if (userMarker) map.removeLayer(userMarker);
  userMarker = L.circleMarker([lat, lon], {
    radius: 10, fillColor: '#4a4af0', color: '#fff',
    fillOpacity: 0.8, weight: 3,
  }).addTo(map);
  map.setView([lat, lon], 17, { animate: true });
  document.getElementById('lat-input').value = lat.toFixed(6);
  document.getElementById('lon-input').value = lon.toFixed(6);
  checkSignal(lat, lon);
}

function checkSignal(lat, lon) {
  // Lookup
  fetch('/api/lookup', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ latitude: lat, longitude: lon }),
  })
    .then(r => r.json())
    .then(data => {
      if (data.error) { console.error(data.error); return; }
      const c = data.connectivity;
      const dl = c.download_mbps != null ? `${c.download_mbps} Mbps` : 'N/A';
      document.getElementById('status-content').innerHTML = `
        <div class="score-badge ${scoreClass(c.teams_ready_score)}">${c.teams_ready_score} — ${qualityLabel(c.teams_ready_score)}</div>
        <p style="font-size:0.85rem;margin:6px 0">${c.message}</p>
        <p style="font-size:0.78rem;color:#888">Nearest: ${data.location.nearest_point} (${data.location.distance_meters}m)</p>
        <div class="metric-grid">
          <div class="metric"><div class="metric-label">Signal</div><div class="metric-value">${c.signal_pct}%</div></div>
          <div class="metric"><div class="metric-label">Latency</div><div class="metric-value">${c.latency_ms}ms</div></div>
          <div class="metric"><div class="metric-label">Download</div><div class="metric-value">${dl}</div></div>
          <div class="metric"><div class="metric-label">Band</div><div class="metric-value">${c.band}</div></div>
        </div>
      `;
    })
    .catch(err => console.error('Lookup failed:', err));

  // Recommend
  fetch('/api/recommend', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ latitude: lat, longitude: lon, min_score: 70 }),
  })
    .then(r => r.json())
    .then(data => {
      if (data.error) { console.error(data.error); return; }
      // Clear old rec markers
      recMarkers.forEach(m => map.removeLayer(m));
      recMarkers = [];

      let html = `<div class="agent-msg">${data.agent_message}</div>`;
      data.recommendations.forEach((r, i) => {
        html += `
          <div class="rec-card" data-lat="${r.latitude}" data-lon="${r.longitude}">
            <span class="rec-score" style="color:${scoreColor(r.teams_ready_score)}">${r.teams_ready_score}</span>
            <div class="rec-name">${i + 1}. ${r.location_name}</div>
            <div class="rec-meta">${r.distance_meters}m away · Signal ${r.signal_pct}% · ${r.latency_ms}ms · ${r.data_source}</div>
          </div>
        `;
        // No separate map markers — use campus location circles only
      });
      document.getElementById('recommend-content').innerHTML = html;

      // Click rec card → fly to location
      document.querySelectorAll('.rec-card').forEach(card => {
        card.addEventListener('click', () => {
          const clat = parseFloat(card.dataset.lat);
          const clon = parseFloat(card.dataset.lon);
          map.flyTo([clat, clon], 18, { duration: 0.8 });
        });
      });
    })
    .catch(err => console.error('Recommend failed:', err));
}
