/* Storm Atlas: North Atlantic extratropical storm map. Plain JS + Leaflet, no build step. */
(async function () {
  'use strict';
  const $ = (s) => document.querySelector(s);
  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));

  // ---------- data ----------
  let M;
  try {
    M = await (await fetch('data/manifest.json')).json();
  } catch (e) {
    document.body.insertAdjacentHTML('beforeend',
      '<div style="position:fixed;inset:0;display:grid;place-items:center;color:#fff;font:16px system-ui;text-align:center;padding:2rem">' +
      'No data found (web/data/manifest.json).<br>Run <code>stormatlas demo</code> or <code>stormatlas fetch</code> first, and serve this folder over HTTP.</div>');
    return;
  }
  const G = M.grid;
  const times = M.times.map((t) => new Date(t));
  const NT = times.length;
  const fields = {};
  for (const [name, meta] of Object.entries(M.fields)) {
    const buf = await (await fetch('data/' + meta.file)).arrayBuffer();
    fields[name] = Object.assign({ raw: new Uint16Array(buf) }, meta);
  }
  const plane = G.ny * G.nx;

  function nodeVal(f, k, y, x) {
    const r = f.raw[k * plane + y * G.nx + x];
    return r === f.missing ? NaN : f.offset + r * f.scale;
  }
  function sample(name, k, lat, lon) {
    const f = fields[name];
    if (!f) return NaN;
    const fy = (G.lat0 - lat) / G.dlat, fx = (lon - G.lon0) / G.dlon;
    if (fy < 0 || fx < 0 || fy > G.ny - 1 || fx > G.nx - 1) return NaN;
    const y0 = Math.min(Math.floor(fy), G.ny - 2), x0 = Math.min(Math.floor(fx), G.nx - 2);
    const ty = fy - y0, tx = fx - x0;
    const a = nodeVal(f, k, y0, x0), b = nodeVal(f, k, y0, x0 + 1), c = nodeVal(f, k, y0 + 1, x0), d = nodeVal(f, k, y0 + 1, x0 + 1);
    return (a * (1 - tx) + b * tx) * (1 - ty) + (c * (1 - tx) + d * tx) * ty;
  }

  // ---------- state ----------
  const hash = new URLSearchParams(location.hash.slice(1));
  const state = {
    k: clamp(parseInt(hash.get('t') || '0', 10) || 0, 0, NT - 1),
    raster: hash.get('r') || (fields.wind ? 'wind' : 'none'),
    iso: true, tracks: true, units: 'kmh', basemap: 'land',
    sel: hash.get('s') || null, playing: false,
  };
  if (state.raster !== 'none' && !fields[state.raster]) state.raster = 'none';
  const UNITS = { kmh: ['km/h', 3.6], kt: ['kn', 1.943844], ms: ['m/s', 1] };
  const fmtWind = (ms) => (ms == null || isNaN(ms)) ? '–' : Math.round(ms * UNITS[state.units][1]) + ' ' + UNITS[state.units][0];
  const fmtT = (d, o) => d.toLocaleString('en-GB', Object.assign({ weekday: 'short', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: 'UTC', hour12: false }, o || {}));
  const fmtDay = (d) => d.toLocaleString('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' });

  // ---------- colour maps ----------
  const MAPS = {
    wind: { lo: 0, hi: 40, label: 'Wind (10 m)', stops: [[0, 20, 40, 90, 0], [8, 40, 110, 180, .35], [14, 60, 180, 170, .6], [20, 250, 220, 70, .7], [26, 255, 140, 40, .78], [32, 240, 60, 60, .82], [40, 200, 40, 200, .85]] },
    swh: { lo: 0, hi: 12, label: 'Significant wave height', stops: [[0, 20, 40, 90, 0], [1, 40, 90, 170, .4], [3, 40, 170, 200, .6], [5, 120, 220, 120, .7], [7, 250, 230, 80, .78], [9, 250, 120, 60, .82], [12, 210, 40, 150, .85]] },
  };
  for (const m of Object.values(MAPS)) {
    m.lut = new Uint8ClampedArray(256 * 4);
    for (let i = 0; i < 256; i++) {
      const v = m.lo + (m.hi - m.lo) * i / 255;
      let j = 0;
      while (j < m.stops.length - 2 && v > m.stops[j + 1][0]) j++;
      const a = m.stops[j], b = m.stops[j + 1], t = clamp((v - a[0]) / (b[0] - a[0]), 0, 1);
      for (let c = 0; c < 3; c++) m.lut[i * 4 + c] = a[c + 1] + (b[c + 1] - a[c + 1]) * t;
      m.lut[i * 4 + 3] = 255 * (a[4] + (b[4] - a[4]) * t);
    }
  }

  // ---------- map ----------
  const map = L.map('map', { center: [52, -22], zoom: 3.5, minZoom: 2, maxZoom: 8, zoomSnap: 0.5, zoomControl: false,
    maxBounds: [[-5, -140], [88, 80]], attributionControl: true });
  L.control.zoom({ position: 'topleft' }).addTo(map);
  map.attributionControl.setPrefix('');
  map.createPane('landPane').style.zIndex = 210;
  map.createPane('fieldPane').style.zIndex = 250;
  map.getPanes().fieldPane.style.pointerEvents = 'none';

  const landLayer = L.layerGroup();
  try {
    const topo = await (await fetch('vendor/land-50m.json')).json();
    const land = topojson.feature(topo, topo.objects.land);
    // Rings that cross the 180° meridian (Chukotka, Wrangel Island) jump from +180 to -180, which
    // Leaflet draws as a filled band across the whole map. Keep each ring continuous instead
    // (longitudes may go past ±180; those parts sit outside the map's bounds).
    const unwrap = (ring) => {
      let sum = ring.length ? ring[0][0] : 0;
      for (let i = 1; i < ring.length; i++) {
        const d = ring[i][0] - ring[i - 1][0];
        if (d > 180) ring[i][0] -= 360; else if (d < -180) ring[i][0] += 360;
        sum += ring[i][0];
      }
      // Shift the whole ring back so its bulk is in -180..180 (otherwise Eurasia, which starts in
      // Chukotka, ends up 360° west and off the map).
      const shift = -360 * Math.round(sum / ring.length / 360);
      if (shift) for (const p of ring) p[0] += shift;
    };
    for (const f of land.type === 'FeatureCollection' ? land.features : [land]) {
      const g = f.geometry;
      (g.type === 'Polygon' ? [g.coordinates] : g.type === 'MultiPolygon' ? g.coordinates : []).forEach((poly) => poly.forEach(unwrap));
    }
    L.geoJSON(land, { pane: 'landPane', interactive: false,
      style: { color: '#5f78a8', weight: 0.8, fillColor: '#243656', fillOpacity: 1 } }).addTo(landLayer);
  } catch (e) { console.warn('land outline failed', e); }

  const tileDefs = {
    carto: () => L.tileLayer('https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png', { maxZoom: 8,
      attribution: '© OpenStreetMap contributors © CARTO' }),
    gibs: () => {
      const d = new Date((M.run ? new Date(M.run) : new Date()).getTime() - 86400000).toISOString().slice(0, 10);
      return L.tileLayer(`https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/MODIS_Terra_CorrectedReflectance_TrueColor/default/${d}/GoogleMapsCompatible_Level9/{z}/{y}/{x}.jpg`,
        { maxNativeZoom: 9, maxZoom: 8, attribution: 'Imagery: NASA EOSDIS GIBS / ESDIS (MODIS Terra, ' + d + ')' });
    },
  };
  let tileLayer = null;
  function setBasemap(b) {
    state.basemap = b;
    if (tileLayer) { map.removeLayer(tileLayer); tileLayer = null; }
    if (b === 'land') { landLayer.addTo(map); document.getElementById('map').style.background = '#0a1626'; }
    else { map.removeLayer(landLayer); tileLayer = tileDefs[b]().addTo(map); tileLayer.setZIndex(1); document.getElementById('map').style.background = '#bcd'; }
    field.schedule();
  }

  // ---------- field canvas (raster + isobars) ----------
  const isoCache = new Map();
  function contour(k, level) {
    const f = fields.msl, out = [];
    const fr = (lv, a, b) => (lv - a) / (b - a);
    for (let y = 0; y < G.ny - 1; y++) for (let x = 0; x < G.nx - 1; x++) {
      const a = nodeVal(f, k, y, x), b = nodeVal(f, k, y, x + 1), c = nodeVal(f, k, y + 1, x + 1), d = nodeVal(f, k, y + 1, x);
      if (a !== a || b !== b || c !== c || d !== d) continue;
      const idx = (a >= level ? 1 : 0) | (b >= level ? 2 : 0) | (c >= level ? 4 : 0) | (d >= level ? 8 : 0);
      if (idx === 0 || idx === 15) continue;
      const T = [x + fr(level, a, b), y], R = [x + 1, y + fr(level, b, c)], B = [x + fr(level, d, c), y + 1], Lf = [x, y + fr(level, a, d)];
      const seg = (p, q) => out.push(p[0], p[1], q[0], q[1]);
      switch (idx) {
        case 1: case 14: seg(Lf, T); break;
        case 2: case 13: seg(T, R); break;
        case 3: case 12: seg(Lf, R); break;
        case 4: case 11: seg(R, B); break;
        case 5: seg(Lf, T); seg(R, B); break;
        case 6: case 9: seg(T, B); break;
        case 7: case 8: seg(Lf, B); break;
        case 10: seg(T, R); seg(Lf, B); break;
      }
    }
    return Float32Array.from(out);
  }
  function isoLevels(k) {
    if (isoCache.has(k)) return isoCache.get(k);
    const f = fields.msl;
    let lo = Infinity, hi = -Infinity;
    for (let i = 0; i < plane; i += 3) { const v = nodeVal(f, k, Math.floor(i / G.nx), i % G.nx); if (v === v) { if (v < lo) lo = v; if (v > hi) hi = v; } }
    const res = [];
    for (let lv = Math.ceil(lo / 4) * 4; lv <= hi; lv += 4) res.push({ lv, seg: contour(k, lv) });
    isoCache.set(k, res);
    if (isoCache.size > 12) isoCache.delete(isoCache.keys().next().value);
    return res;
  }

  const field = {
    canvas: null, pending: false,
    init() {
      this.canvas = L.DomUtil.create('canvas', 'leaflet-zoom-hide');
      this.canvas.style.position = 'absolute';
      map.getPanes().fieldPane.appendChild(this.canvas);
      map.on('move zoomend resize viewreset', () => this.schedule());
      this.schedule();
    },
    schedule() { if (this.pending) return; this.pending = true; requestAnimationFrame(() => { this.pending = false; this.draw(); }); },
    draw() {
      const size = map.getSize(), c = this.canvas, ctx = c.getContext('2d');
      c.width = size.x; c.height = size.y;
      L.DomUtil.setPosition(c, map.containerPointToLayerPoint([0, 0]));
      ctx.clearRect(0, 0, size.x, size.y);
      // projections of grid rows/cols into container pixels
      const xs = new Float32Array(G.nx), ys = new Float32Array(G.ny);
      for (let x = 0; x < G.nx; x++) xs[x] = map.latLngToContainerPoint([G.lat0, G.lon0 + x * G.dlon]).x;
      for (let y = 0; y < G.ny; y++) ys[y] = map.latLngToContainerPoint([G.lat0 - y * G.dlat, G.lon0]).y;
      if (state.raster !== 'none') this.raster(ctx, size);
      if (state.iso && fields.msl) this.isobars(ctx, size, xs, ys);
    },
    raster(ctx, size) {
      const m = MAPS[state.raster], step = 3;
      const w = Math.ceil(size.x / step), h = Math.ceil(size.y / step);
      const lons = new Float32Array(w), lats = new Float32Array(h);
      for (let i = 0; i < w; i++) lons[i] = map.containerPointToLatLng([i * step, 0]).lng;
      for (let j = 0; j < h; j++) lats[j] = map.containerPointToLatLng([0, j * step]).lat;
      const img = new ImageData(w, h), d = img.data, name = state.raster, k = state.k;
      for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) {
        const v = sample(name, k, lats[j], lons[i]);
        if (v !== v) continue;
        const li = ((clamp((v - m.lo) / (m.hi - m.lo), 0, 1) * 255) | 0) * 4, o = (j * w + i) * 4;
        d[o] = m.lut[li]; d[o + 1] = m.lut[li + 1]; d[o + 2] = m.lut[li + 2]; d[o + 3] = m.lut[li + 3];
      }
      const tmp = document.createElement('canvas'); tmp.width = w; tmp.height = h;
      tmp.getContext('2d').putImageData(img, 0, 0);
      ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = 'high';
      ctx.drawImage(tmp, 0, 0, w * step, h * step);
    },
    isobars(ctx, size, xs, ys) {
      const light = state.basemap === 'carto';
      const main = light ? '#10233f' : '#ffffff', halo = light ? 'rgba(255,255,255,.7)' : 'rgba(0,0,0,.55)';
      const levels = isoLevels(state.k), labels = [];
      const px = (gx, gy) => {
        const x0 = Math.floor(gx), y0 = Math.floor(gy);
        const x1 = Math.min(x0 + 1, G.nx - 1), y1 = Math.min(y0 + 1, G.ny - 1);
        return [xs[x0] + (xs[x1] - xs[x0]) * (gx - x0), ys[y0] + (ys[y1] - ys[y0]) * (gy - y0)];
      };
      ctx.lineCap = 'round';
      for (const pass of [0, 1]) {
        for (const { lv, seg } of levels) {
          const major = lv % 20 === 0;
          ctx.beginPath();
          for (let i = 0; i < seg.length; i += 4) {
            const a = px(seg[i], seg[i + 1]), b = px(seg[i + 2], seg[i + 3]);
            if ((a[0] < -50 && b[0] < -50) || (a[0] > size.x + 50 && b[0] > size.x + 50) || (a[1] < -50 && b[1] < -50) || (a[1] > size.y + 50 && b[1] > size.y + 50)) continue;
            ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]);
            if (pass === 1 && labels.length < 400 && Math.hypot(b[0] - a[0], b[1] - a[1]) > 3 &&
                a[0] > 40 && a[0] < size.x - 40 && a[1] > 40 && a[1] < size.y - 40 &&
                !labels.some((l) => Math.abs(l.x - a[0]) < 150 && Math.abs(l.y - a[1]) < 60 && (l.lv === lv ? true : Math.hypot(l.x - a[0], l.y - a[1]) < 40)))
              labels.push({ x: a[0], y: a[1], lv, ang: Math.atan2(b[1] - a[1], b[0] - a[0]) });
          }
          if (pass === 0) { ctx.strokeStyle = halo; ctx.lineWidth = major ? 3.6 : 2.4; ctx.stroke(); }
          else { ctx.strokeStyle = main; ctx.globalAlpha = major ? 0.95 : 0.6; ctx.lineWidth = major ? 1.7 : 1; ctx.stroke(); ctx.globalAlpha = 1; }
        }
      }
      ctx.font = '600 11px system-ui, sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      for (const l of labels) {
        let a = l.ang; if (a > Math.PI / 2) a -= Math.PI; if (a < -Math.PI / 2) a += Math.PI;
        ctx.save(); ctx.translate(l.x, l.y); ctx.rotate(a);
        ctx.lineWidth = 3.5; ctx.strokeStyle = halo; ctx.strokeText(l.lv, 0, 0);
        ctx.fillStyle = main; ctx.fillText(l.lv, 0, 0); ctx.restore();
      }
    },
  };

  // ---------- storms ----------
  const storms = M.storms.map((s) => Object.assign({}, s, {
    startD: new Date(s.start), endD: new Date(s.end),
    pts: s.points.map((p) => Object.assign({}, p, { d: new Date(p.t) })),
  }));
  const trackGroup = L.layerGroup().addTo(map);
  const markerGroup = L.layerGroup().addTo(map);
  const trackObjs = {};
  const label = (s) => s.name || ('Low ' + s.id);

  function buildTracks() {
    trackGroup.clearLayers();
    for (const s of storms) {
      const ll = s.pts.map((p) => [p.lat, p.lon]);
      const col = s.bomb ? '#ff6a3d' : '#cfe8ff';
      const future = L.polyline(ll, { color: col, weight: 2, opacity: 0.6, dashArray: '2 7', lineCap: 'round' }).addTo(trackGroup);
      const past = L.polyline([], { color: col, weight: 3.5, opacity: 0.95 }).addTo(trackGroup);
      future.on('click', () => select(s.id)); past.on('click', () => select(s.id));
      const dots = s.pts.filter((p) => p.d.getUTCHours() % 12 === 0).map((p) =>
        L.circleMarker([p.lat, p.lon], { radius: 3.5, color: '#0a1626', weight: 1, fillColor: col, fillOpacity: 1 })
          .bindTooltip(`${fmtT(p.d)} UTC<br>${Math.round(p.p)} hPa · ${fmtWind(p.wind / 1)}`, { className: 'tt' })
          .on('click', () => select(s.id)).addTo(trackGroup));
      trackObjs[s.id] = { future, past, dots };
    }
  }

  function updateTracks() {
    const now = times[state.k];
    for (const s of storms) {
      const o = trackObjs[s.id];
      o.past.setLatLngs(s.pts.filter((p) => p.d <= now).map((p) => [p.lat, p.lon]));
      const sel = state.sel === s.id;
      o.future.setStyle({ weight: sel ? 3 : 2, opacity: sel ? 0.95 : 0.6 });
      o.past.setStyle({ weight: sel ? 5 : 3.5 });
    }
    markerGroup.clearLayers();
    if (state.tracks) for (const s of storms) {
      const p = s.pts.find((q) => +q.d === +now);
      if (!p) continue;
      const cls = 'lmark' + (s.bomb ? ' bomb' : '') + (state.sel === s.id ? ' sel' : '');
      const icon = L.divIcon({ className: '', iconSize: [26, 26], iconAnchor: [13, 13],
        html: `<div class="${cls}">L</div><div class="lval">${Math.round(p.p)}</div>` });
      L.marker([p.lat, p.lon], { icon, keyboard: false }).on('click', () => select(s.id)).addTo(markerGroup);
    }
    if (state.tracks) { if (!map.hasLayer(trackGroup)) trackGroup.addTo(map); } else map.removeLayer(trackGroup);
  }

  function renderList() {
    const el = $('#storm-list');
    $('#storm-count').textContent = '(' + storms.length + ')';
    el.innerHTML = '';
    if (!storms.length) { el.innerHTML = '<p style="color:var(--mute);font-size:13px">No closed lows detected in this forecast.</p>'; return; }
    for (const s of storms) {
      const d = document.createElement('div');
      d.className = 'card'; d.dataset.id = s.id; d.tabIndex = 0;
      d.innerHTML = `<b>${label(s)}${s.bomb ? '<span class="badge">BOMB</span>' : ''}<span class="badge live" hidden>ACTIVE</span></b>
        <span class="p">${Math.round(s.min_p)}<small> hPa</small></span>
        <span class="sub">${fmtDay(s.startD)} → ${fmtDay(s.endD)} · peak ${fmtWind(s.max_wind_kmh / 3.6)}</span>`;
      d.onclick = () => select(s.id);
      d.onkeydown = (e) => { if (e.key === 'Enter') select(s.id); };
      el.appendChild(d);
    }
  }
  function updateCards() {
    const now = times[state.k];
    document.querySelectorAll('.card').forEach((c) => {
      const s = storms.find((x) => x.id === c.dataset.id);
      c.classList.toggle('sel', state.sel === s.id);
      c.querySelector('.live').hidden = !(now >= s.startD && now <= s.endD);
    });
  }

  function episodeText(s) {
    const nm = (s.name || 'Low ' + s.id).toUpperCase();
    const a = fmtDay(s.startD), b = fmtDay(s.endD);
    return `${nm}\nActive: ${a} – ${b}\nMax wind: ${s.max_wind_kmh} km/h\nMin pressure: ${Math.round(s.min_p)} hPa\n(${M.model}, model-derived)`;
  }
  function renderDetail() {
    const el = $('#detail'), s = storms.find((x) => x.id === state.sel);
    if (!s) { el.hidden = true; return; }
    el.hidden = false;
    el.innerHTML = `<h2>Selected storm</h2>
      <input id="nm" placeholder="Name this storm (e.g. Storm Bert)" value="${s.name || ''}" aria-label="Storm name">
      <dl>
        <dt>Active (UTC)</dt><dd>${fmtT(s.startD)} → ${fmtT(s.endD)}</dd>
        <dt>Lowest pressure</dt><dd>${Math.round(s.min_p)} hPa · ${fmtT(new Date(s.min_p_time), { weekday: undefined })}</dd>
        <dt>Peak wind (≤500 km)</dt><dd>${fmtWind(s.max_wind_kmh / 3.6)}</dd>
        <dt>Max wave height</dt><dd>${s.max_swh == null ? '–' : s.max_swh.toFixed(1) + ' m'}</dd>
        <dt>Max deepening</dt><dd>${s.max_deepening == null ? '–' : Math.round(s.max_deepening) + ' hPa/24 h'}${s.bomb ? ' · explosive' : ''}</dd>
      </dl>
      <pre id="ep">${episodeText(s)}</pre>
      <button id="copy">Copy episode data</button>`;
    $('#nm').oninput = (e) => { s.name = e.target.value.trim() || null; $('#ep').textContent = episodeText(s); renderList(); updateCards(); updateTracks(); };
    $('#copy').onclick = async () => {
      try { await navigator.clipboard.writeText($('#ep').textContent); $('#copy').textContent = 'Copied'; }
      catch (e) { const r = document.createRange(); r.selectNode($('#ep')); getSelection().removeAllRanges(); getSelection().addRange(r); $('#copy').textContent = 'Selected, press Ctrl+C'; }
    };
  }
  function select(id, fly = true) {
    state.sel = id;
    renderDetail(); updateCards(); updateTracks(); writeHash();
    const s = storms.find((x) => x.id === state.sel);
    if (s && fly) {
      const b = L.latLngBounds(s.pts.map((p) => [p.lat, p.lon]));
      map.flyToBounds(b.pad(0.4), { paddingBottomRight: matchMedia('(max-width:820px)').matches ? [0, 260] : [370, 110], maxZoom: 6, duration: 0.8 });
    }
  }

  // ---------- time ----------
  function setTime(k) {
    state.k = clamp(k, 0, NT - 1);
    $('#slider').value = state.k;
    const lead = Math.round((times[state.k] - times[0]) / 3600000);
    $('#timelabel').innerHTML = `${fmtT(times[state.k])} UTC<span>${state.k === 0 ? 'analysis' : '+' + lead + ' h'}</span>`;
    field.schedule(); updateTracks(); updateCards(); writeHash();
  }
  let timer = null;
  function play(on) {
    state.playing = on; $('#btn-play').textContent = on ? '❚❚' : '▶';
    clearInterval(timer);
    if (on) timer = setInterval(() => setTime(state.k >= NT - 1 ? 0 : state.k + 1), 450);
  }
  function writeHash() {
    const p = new URLSearchParams({ t: state.k, r: state.raster });
    if (state.sel) p.set('s', state.sel);
    try { history.replaceState(null, '', '#' + p); } catch (e) { /* ignore */ }
  }

  // ---------- legend / readout ----------
  function renderLegend() {
    const el = $('#legend');
    if (state.raster === 'none') { el.hidden = true; return; }
    el.hidden = false;
    const m = MAPS[state.raster], isW = state.raster === 'wind';
    const conv = isW ? UNITS[state.units][1] : 1, unit = isW ? UNITS[state.units][0] : 'm';
    el.innerHTML = `<b>${m.label}</b><canvas width="150" height="10"></canvas><div class="ticks"><span>${Math.round(m.lo * conv)}</span><span>${Math.round((m.hi / 2) * conv)}</span><span>${Math.round(m.hi * conv)} ${unit}</span></div>`;
    const cv = el.querySelector('canvas'), cx = cv.getContext('2d');
    const bg = cx.createImageData(150, 1);
    for (let i = 0; i < 150; i++) { const li = Math.round(i / 149 * 255) * 4; for (let c = 0; c < 3; c++) bg.data[i * 4 + c] = m.lut[li + c]; bg.data[i * 4 + 3] = 255; }
    for (let y = 0; y < 10; y++) cx.putImageData(bg, 0, y);
  }
  map.on('mousemove', (e) => {
    const { lat, lng } = e.latlng, k = state.k;
    const p = sample('msl', k, lat, lng);
    if (p !== p) { $('#readout').textContent = ''; return; }
    const w = sample('wind', k, lat, lng), h = sample('swh', k, lat, lng);
    $('#readout').textContent = `${Math.abs(lat).toFixed(1)}°${lat >= 0 ? 'N' : 'S'} ${Math.abs(lng).toFixed(1)}°${lng >= 0 ? 'E' : 'W'} · ${Math.round(p)} hPa` +
      (w === w ? ' · ' + fmtWind(w) : '') + (h === h ? ' · ' + h.toFixed(1) + ' m' : '');
  });
  map.on('mouseout', () => { $('#readout').textContent = ''; });

  // ---------- wiring ----------
  $('#slider').max = NT - 1;
  $('#slider').oninput = (e) => setTime(+e.target.value);
  $('#btn-prev').onclick = () => { play(false); setTime(state.k - 1); };
  $('#btn-next').onclick = () => { play(false); setTime(state.k + 1); };
  $('#btn-play').onclick = () => play(!state.playing);
  document.addEventListener('keydown', (e) => {
    if (/INPUT|SELECT|TEXTAREA/.test(e.target.tagName) && e.target.type !== 'range') return;
    if (e.key === 'ArrowLeft') setTime(state.k - 1);
    else if (e.key === 'ArrowRight') setTime(state.k + 1);
    else if (e.key === ' ') { e.preventDefault(); play(!state.playing); }
  });
  document.querySelectorAll('#raster-seg button').forEach((b) => {
    if (!fields[b.dataset.raster] && b.dataset.raster !== 'none') b.disabled = true;
    b.onclick = () => { state.raster = b.dataset.raster; syncSeg(); renderLegend(); field.schedule(); writeHash(); };
  });
  function syncSeg() { document.querySelectorAll('#raster-seg button').forEach((b) => b.classList.toggle('on', b.dataset.raster === state.raster)); }
  $('#chk-iso').onchange = (e) => { state.iso = e.target.checked; field.schedule(); };
  $('#chk-tracks').onchange = (e) => { state.tracks = e.target.checked; updateTracks(); };
  $('#basemap').onchange = (e) => setBasemap(e.target.value);
  $('#units').onchange = (e) => { state.units = e.target.value; renderLegend(); renderList(); renderDetail(); updateCards(); };

  // ---------- init ----------
  $('#runinfo').textContent = `${M.model} · run ${M.run ? fmtT(new Date(M.run), { weekday: undefined }) + 'Z' : '?'} · ${NT} steps`;
  if (M.synthetic) $('#demo-banner').hidden = false;
  field.init(); buildTracks(); renderList(); syncSeg(); renderLegend(); setBasemap('land');
  map.fitBounds([[G.lat0 - G.dlat * (G.ny - 1), G.lon0], [G.lat0, G.lon0 + G.dlon * (G.nx - 1)]],
    { paddingBottomRight: matchMedia('(max-width:820px)').matches ? [0, 260] : [360, 110] });
  setTime(state.k);
  if (state.sel && storms.some((s) => s.id === state.sel)) select(state.sel, false); else state.sel = null;
  window.__atlas = { state, storms, contour, sample, setTime, select, M };  // for tests / console
})();
