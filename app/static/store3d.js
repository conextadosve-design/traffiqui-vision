/* Traffiqui Vision · vista 3D de la tienda (Three.js local, sin build) */
import * as THREE from 'three';
import { OrbitControls } from '/static/vendor/three/OrbitControls.js';
import { CSS2DRenderer, CSS2DObject } from '/static/vendor/three/CSS2DRenderer.js';

const $ = (s, r = document) => r.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const cssVar = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const fmtSecs = s => s >= 60 ? `${Math.floor(s / 60)} min ${Math.round(s % 60)} s` : `${Math.round(s)} s`;
const pct = v => `${Math.round(v * 100)} %`;
const pad2 = n => String(n).padStart(2, '0');
const hh = ts => { const d = new Date(ts * 1000); return `${pad2(d.getHours())}h`; };

const METRICS = {
  passed: { label: 'Personas que pasaron', fmt: v => String(v) },
  penetration: { label: 'Penetración (% de visitantes)', fmt: pct },
  stop_rate: { label: 'Tasa de detención', fmt: pct },
  avg_dwell: { label: 'Permanencia promedio', fmt: fmtSecs },
  inside: { label: 'Personas ahora (en vivo)', fmt: v => String(v) },
};
const BOX_COLOR = { gondola: 0xe8dcc0, furniture: 0xc4ccd6, checkout: 0x9ccab9, fridge: 0xbcdcef, counter: 0xd8bea6 };

const S = {
  ready: false, plan: null, analytics: null, live: null, metric: 'passed', range: 'today',
  heatMode: 'range', heat: null, showHeat: true, showPeople: true, showLabels: true,
  renderer: null, labelRenderer: null, scene: null, camera: null, controls: null,
  groups: {}, people: new Map(), heatTex: null, raf: 0, visible: false,
};

// ---------------------------------------------------------------- escena
function initScene() {
  const host = $('#store3d');
  S.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
  S.renderer.setPixelRatio(Math.min(2, window.devicePixelRatio));
  host.appendChild(S.renderer.domElement);
  S.labelRenderer = new CSS2DRenderer();
  S.labelRenderer.domElement.className = 'label-layer';
  host.appendChild(S.labelRenderer.domElement);
  S.scene = new THREE.Scene();
  S.camera = new THREE.PerspectiveCamera(45, 1, 0.1, 500);
  S.controls = new OrbitControls(S.camera, S.renderer.domElement);
  S.controls.enableDamping = true;
  S.controls.maxPolarAngle = Math.PI / 2 - 0.05;
  S.scene.add(new THREE.HemisphereLight(0xffffff, 0x8a8f98, 1.6));
  const sun = new THREE.DirectionalLight(0xffffff, 1.4);
  sun.position.set(20, 30, 10);
  S.scene.add(sun);
  for (const k of ['floor', 'areas', 'objects', 'cams', 'people', 'labels']) { S.groups[k] = new THREE.Group(); S.scene.add(S.groups[k]); }
  new ResizeObserver(resize).observe(host);
  resize();
  S.ready = true;
}
function resize() {
  const host = $('#store3d'); if (!host || !S.renderer) return;
  const w = host.clientWidth, h = host.clientHeight;
  S.renderer.setSize(w, h);
  S.labelRenderer.setSize(w, h);
  S.camera.aspect = w / Math.max(1, h);
  S.camera.updateProjectionMatrix();
}
function loop() {
  S.raf = requestAnimationFrame(loop);
  S.controls.update();
  for (const p of S.people.values()) p.mesh.position.lerp(p.target, 0.25); // movimiento suave entre mensajes
  S.renderer.render(S.scene, S.camera);
  S.labelRenderer.render(S.scene, S.camera);
}
function clear(g) { while (g.children.length) { const c = g.children.pop(); c.geometry?.dispose?.(); c.material?.dispose?.(); if (c.element) c.element.remove(); } }

function label(text, x, y, z, cls = '') {
  const div = document.createElement('div');
  div.className = `l3d ${cls}`;
  div.innerHTML = text;
  const o = new CSS2DObject(div);
  o.position.set(x, y, z);
  return o;
}

// ---------------------------------------------------------------- construcción desde el plano
function build() {
  const plan = S.plan; if (!plan || !S.ready) return;
  const dark = matchMedia('(prefers-color-scheme: dark)').matches;
  S.scene.background = new THREE.Color(cssVar('--bg') || (dark ? '#11171F' : '#F5F3EE'));
  for (const g of Object.values(S.groups)) clear(g);
  const W = plan.width, D = plan.depth;

  // piso: textura de canvas con el mapa de calor
  const canvas = document.createElement('canvas');
  canvas.width = Math.min(2048, Math.round(W * 40)); canvas.height = Math.min(2048, Math.round(D * 40));
  S.heatTex = new THREE.CanvasTexture(canvas);
  S.heatTex.colorSpace = THREE.SRGBColorSpace;
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(W, D), new THREE.MeshLambertMaterial({ map: S.heatTex }));
  floor.rotation.x = -Math.PI / 2;
  floor.position.set(W / 2, 0, D / 2);
  S.groups.floor.add(floor);
  paintFloor();

  for (const e of plan.elements) {
    if (e.type === 'wall' || e.type === 'divider') addSegments(e);
    else if (e.type === 'door') addDoor(e);
    else if (BOX_COLOR[e.type] !== undefined) addBox(e);
    else if (e.type === 'camera') addCamera(e);
  }
  buildAreas();
  if (!S.camera.userData.placed) resetView();
}

function addSegments(e) {
  const h = e.height ?? (e.type === 'wall' ? 3 : 1.5), t = Math.max(0.05, e.thickness ?? 0.15);
  const mat = new THREE.MeshLambertMaterial({ color: e.type === 'wall' ? 0x9aa3ad : 0xb8bec6, transparent: true, opacity: e.type === 'wall' ? 0.55 : 0.75 });
  for (let i = 0; i < e.points.length - 1; i++) {
    const [x1, y1] = e.points[i], [x2, y2] = e.points[i + 1];
    const len = Math.hypot(x2 - x1, y2 - y1); if (len < 0.01) continue;
    const m = new THREE.Mesh(new THREE.BoxGeometry(len + t, h, t), mat);
    m.position.set((x1 + x2) / 2, h / 2, (y1 + y2) / 2);
    m.rotation.y = -Math.atan2(y2 - y1, x2 - x1);
    S.groups.objects.add(m);
  }
}
function addDoor(e) {
  const [a, b] = [e.points[0], e.points[e.points.length - 1]];
  const len = Math.hypot(b[0] - a[0], b[1] - a[1]);
  const color = e.role === 'exit' ? 0xc8783c : 0x1d7a64; // salida aparte en naranja
  const m = new THREE.Mesh(new THREE.BoxGeometry(len, 0.03, 0.4), new THREE.MeshLambertMaterial({ color }));
  m.position.set((a[0] + b[0]) / 2, 0.02, (a[1] + b[1]) / 2);
  m.rotation.y = -Math.atan2(b[1] - a[1], b[0] - a[0]);
  S.groups.objects.add(m);
  S.groups.labels.add(label(esc(e.label || (e.role === 'exit' ? 'Salida' : 'Entrada')), m.position.x, 0.6, m.position.z,
                            e.role === 'exit' ? 'door exit' : 'door'));
}
function addBox(e) {
  const h = e.h ?? 1;
  const m = new THREE.Mesh(new THREE.BoxGeometry(e.w, h, e.d), new THREE.MeshLambertMaterial({ color: BOX_COLOR[e.type] }));
  m.position.set(e.x, h / 2, e.y);
  m.rotation.y = -(e.rot || 0) * Math.PI / 180;
  const edges = new THREE.LineSegments(new THREE.EdgesGeometry(m.geometry), new THREE.LineBasicMaterial({ color: 0x6b7280, transparent: true, opacity: 0.5 }));
  m.add(edges);
  S.groups.objects.add(m);
  const txt = e.category || (e.type !== 'gondola' ? e.label : '');
  if (txt) S.groups.labels.add(label(esc(txt), e.x, h + 0.25, e.y, 'cat'));
}
function addCamera(e) {
  const h = e.height ?? 2.8, a = (e.rot || 0) * Math.PI / 180;
  // el cono nace apuntando a +y: se acuesta hacia +x, se orienta como en el plano y se inclina al piso
  const cone = new THREE.Mesh(new THREE.ConeGeometry(0.25, 0.6, 16), new THREE.MeshLambertMaterial({ color: 0x17202b }));
  cone.rotation.z = -Math.PI / 2;
  const holder = new THREE.Group();
  holder.add(cone);
  holder.position.set(e.x, h, e.y);
  holder.rotation.y = -a;
  holder.rotateZ(-0.5);
  S.groups.cams.add(holder);
}

const RAMP = [[253, 240, 205], [237, 196, 102], [214, 140, 40], [160, 82, 22], [96, 42, 14]]; // secuencial, un tono cálido
function rampColor(v) {
  const x = Math.min(0.999, Math.max(0, v)) * (RAMP.length - 1), i = Math.floor(x), f = x - i;
  return new THREE.Color(...RAMP[i].map((s, k) => (s + (RAMP[i + 1][k] - s) * f) / 255));
}

function areaValues() {
  const vals = {};
  const src = S.metric === 'inside' ? (S.live?.areas || []) : (S.analytics?.areas || []);
  for (const a of src) vals[a.id] = a[S.metric] ?? 0;
  return vals;
}

function buildAreas() {
  clear(S.groups.areas);
  for (const o of [...S.groups.labels.children]) if (o.userData.area) { S.groups.labels.remove(o); o.element.remove(); }
  const vals = areaValues(), max = Math.max(1e-9, ...Object.values(vals));
  for (const e of S.plan.elements.filter(x => x.type === 'area')) {
    const shape = new THREE.Shape(e.points.map(([x, y]) => new THREE.Vector2(x, y)));
    const v = vals[e.id] ?? 0;
    const m = new THREE.Mesh(new THREE.ShapeGeometry(shape), new THREE.MeshBasicMaterial({
      color: rampColor(v / max), transparent: true, opacity: S.showHeat ? 0.45 : 0.8, side: THREE.DoubleSide, depthWrite: false }));
    m.rotation.x = Math.PI / 2; // (x, y) del plano → (x, z) del 3D
    m.position.y = 0.02;
    S.groups.areas.add(m);
    const c = e.points.reduce((a, p) => [a[0] + p[0] / e.points.length, a[1] + p[1] / e.points.length], [0, 0]);
    const l = label(`<b>${esc(e.name)}</b><span>${METRICS[S.metric].fmt(v)}</span>`, c[0], 0.3, c[1], 'area');
    l.userData.area = true;
    S.groups.labels.add(l);
  }
  S.groups.labels.visible = S.showLabels;
  renderLegend(max);
}

function paintFloor() {
  if (!S.heatTex) return;
  const cv = S.heatTex.image, ctx = cv.getContext('2d'), W = S.plan.width, D = S.plan.depth;
  ctx.fillStyle = cssVar('--surface') || '#ffffff';
  ctx.fillRect(0, 0, cv.width, cv.height);
  // grilla de 1 m
  ctx.strokeStyle = cssVar('--grid') || '#e5e1d8'; ctx.lineWidth = 1;
  for (let x = 0; x <= W; x++) { const px = x / W * cv.width; ctx.beginPath(); ctx.moveTo(px, 0); ctx.lineTo(px, cv.height); ctx.stroke(); }
  for (let y = 0; y <= D; y++) { const py = y / D * cv.height; ctx.beginPath(); ctx.moveTo(0, py); ctx.lineTo(cv.width, py); ctx.stroke(); }
  const h = S.heat;
  if (S.showHeat && h && h.rows) {
    const cw = h.cell / W * cv.width, ch = h.cell / D * cv.height;
    for (let r = 0; r < h.rows; r++) for (let c = 0; c < h.cols; c++) {
      const v = h.values[r * h.cols + c];
      if (v < 0.03) continue;
      const col = window.TQPlan.heatColor(v);
      ctx.globalAlpha = Math.min(0.9, 0.2 + v * 0.75);
      ctx.fillStyle = col;
      ctx.fillRect(c * cw, r * ch, cw + 1, ch + 1);
    }
    ctx.globalAlpha = 1;
  }
  S.heatTex.needsUpdate = true;
}

function resetView(top = false) {
  const W = S.plan.width, D = S.plan.depth, r = Math.max(W, D);
  S.controls.target.set(W / 2, 0, D / 2);
  if (top) S.camera.position.set(W / 2, r * 1.35, D / 2 + 0.01);
  else S.camera.position.set(W / 2 - r * 0.15, r * 0.85, D + r * 0.55);
  S.camera.userData.placed = true;
  S.controls.update();
}

// ---------------------------------------------------------------- personas en vivo
function updatePeople() {
  const g = S.groups.people;
  const live = (S.live?.people || []).filter(p => p.x !== null && p.confirmed);
  const keep = new Set();
  for (const p of live) {
    keep.add(p.gid);
    let o = S.people.get(p.gid);
    if (!o) {
      const mesh = new THREE.Mesh(new THREE.CapsuleGeometry(0.22, 1.1, 4, 12), new THREE.MeshLambertMaterial({ color: p.color }));
      mesh.position.set(p.x, 0.77, p.y);
      const tag = label(`ID ${p.gid}`, 0, 1.0, 0, 'person');
      tag.element.style.setProperty('--c', p.color);
      mesh.add(tag);
      g.add(mesh);
      o = { mesh, target: new THREE.Vector3(p.x, 0.77, p.y) };
      S.people.set(p.gid, o);
    }
    o.target.set(p.x, 0.77, p.y);
    const tag = o.mesh.children[0]?.element;
    if (tag) tag.textContent = p.staff ? `ID ${p.gid} · personal` : p.buyer ? `ID ${p.gid} · comprador` : `ID ${p.gid}`;
    o.mesh.material.opacity = p.staff ? 0.35 : 1;
    o.mesh.material.transparent = !!p.staff;
  }
  for (const [gid, o] of S.people) if (!keep.has(gid)) {
    g.remove(o.mesh); o.mesh.traverse(c => c.element?.remove()); o.mesh.geometry.dispose(); S.people.delete(gid);
  }
  g.visible = S.showPeople;
  $('#s3dLive').textContent = `${S.live?.people_now ?? 0} persona(s) en la tienda ahora · ${live.length} ubicada(s) en el plano`;
}

// ---------------------------------------------------------------- datos
function params() {
  const p = new URLSearchParams({ range: S.range });
  if (S.range === 'custom') { p.set('start', $('#s3dStart').value); p.set('end', $('#s3dEnd').value); }
  return p.toString();
}
async function loadData() {
  try {
    const [plan, a, heat] = await Promise.all([
      fetch('/api/floorplan').then(r => r.json()),
      fetch(`/api/store/analytics?${params()}`).then(async r => { const b = await r.json(); if (!r.ok) throw new Error(b.detail); return b; }),
      fetch(`/api/store/heatmap?${params()}&mode=${S.heatMode}`).then(r => r.json()),
    ]);
    const planChanged = JSON.stringify(plan) !== JSON.stringify(S.plan);
    S.plan = plan; S.analytics = a; S.heat = heat;
    if (planChanged) build(); else { buildAreas(); paintFloor(); }
    renderPanels();
  } catch (e) { window.tqToast?.(e.message, true); }
}

// ---------------------------------------------------------------- paneles
function renderLegend(max) {
  const m = METRICS[S.metric];
  const top = max > 1e-6 ? m.fmt(max) : 'sin datos aún';
  $('#s3dLegend').innerHTML = `<span>${esc(m.label)}</span><i class="ramp"></i><span class="ends"><em>0</em><em>${top}</em></span>`;
}
function renderPanels() {
  const a = S.analytics; if (!a) return;
  const m = S.metric === 'inside' ? 'passed' : S.metric;
  const rows = [...a.areas].sort((x, y) => (y[m] ?? 0) - (x[m] ?? 0));
  const max = Math.max(1e-9, ...rows.map(r => r[m] ?? 0));
  $('#s3dRanking').innerHTML = rows.length ? rows.map((r, i) => `
    <tr><td class="num">${i + 1}</td><td>${esc(r.name)}<div class="note">${esc(r.kind)}</div></td>
      <td class="num"><div class="bar-cell"><span style="width:${Math.round(70 * (r[m] ?? 0) / max)}px"></span>${METRICS[m].fmt(r[m] ?? 0)}</div></td>
      <td class="num">${r.passed}</td><td class="num">${pct(r.penetration)}</td><td class="num">${pct(r.stop_rate)}</td><td class="num">${fmtSecs(r.avg_dwell)}</td></tr>`).join('')
    : '<tr><td colspan="7" class="empty">Dibuja áreas (pasillos) en la pestaña Plano y calibra al menos una cámara.</td></tr>';
  $('#s3dTotals').innerHTML = `<b>${a.totals.unique}</b> personas únicas · permanencia en tienda ${fmtSecs(a.totals.avg_dwell)} (mediana ${fmtSecs(a.totals.median_dwell)})`;
  $('#s3dTrans').innerHTML = a.transitions.length ? a.transitions.map(t => `<li><span>${esc(t.from)} → ${esc(t.to)}</span><b>${t.count}</b></li>`).join('') : '<li class="empty">Aún no hay movimientos entre áreas.</li>';
  $('#s3dPaths').innerHTML = a.paths.length ? a.paths.map(p => `<li><span>${esc(p.path)}</span><b>${p.count}</b></li>`).join('') : '<li class="empty">Aún no hay recorridos de 2 áreas o más.</li>';
  const ah = a.area_by_hour, hmax = Math.max(1, ...ah.rows.flatMap(r => r.counts));
  const hours = ah.hours.map((h, i) => ({ h, i })).filter(({ i }) => ah.rows.some(r => r.counts[i] > 0));
  // en rangos de varios días el servidor agrupa por hora del día (00h–23h, suma de los días)
  const head = h => ah.mode === 'hour_of_day' ? `${pad2(h)}h` : hh(h);
  $('#s3dMatrixNote').textContent = ah.mode === 'hour_of_day' ? 'Suma de todos los días del rango, por hora del día.' : '';
  $('#s3dMatrix').innerHTML = hours.length ? `<thead><tr><th>Área</th>${hours.map(({ h }) => `<th class="num">${head(h)}</th>`).join('')}</tr></thead><tbody>${
    ah.rows.map(r => `<tr><td>${esc(r.name)}</td>${hours.map(({ i }) => {
      const v = r.counts[i]; const c = window.TQPlan.heatColor(v / hmax);
      return `<td class="num cell" style="background:${v ? c : 'transparent'};color:${v / hmax > 0.55 ? '#fff' : 'inherit'}" title="${esc(r.name)} · ${v} persona(s)">${v || ''}</td>`;
    }).join('')}</tr>`).join('')}</tbody>` : '<tbody><tr><td class="empty">Sin visitas a áreas en este rango.</td></tr></tbody>';
  const reid = a.reid;
  $('#s3dReid').innerHTML = reid.local_tracks
    ? `${reid.relinked} de ${reid.local_tracks} detecciones nuevas se reconocieron como una persona ya vista
       (${Object.entries(reid.by_reason).filter(([k]) => k !== 'nueva').map(([k, n]) => `${esc(k)}: ${n}`).join(', ') || 'ninguna'}).`
    : 'Sin datos de reidentificación en este rango.';
}

// ---------------------------------------------------------------- controles
function bindControls() {
  $('#s3dMetric').innerHTML = Object.entries(METRICS).map(([k, v]) => `<option value="${k}">${v.label}</option>`).join('');
  $('#s3dMetric').addEventListener('change', e => { S.metric = e.target.value; buildAreas(); renderPanels(); });
  document.querySelectorAll('[data-s3drange]').forEach(b => b.addEventListener('click', () => {
    S.range = b.dataset.s3drange;
    document.querySelectorAll('[data-s3drange]').forEach(x => x.setAttribute('aria-pressed', String(x === b)));
    $('#s3dCustom').hidden = S.range !== 'custom';
    if (S.range === 'custom' && !$('#s3dStart').value) {
      const local = x => new Date(x - x.getTimezoneOffset() * 60000).toISOString().slice(0, 16), d = new Date();
      $('#s3dEnd').value = local(d); $('#s3dStart').value = local(new Date(d - 3 * 3600e3));
    }
    loadData();
  }));
  $('#s3dStart').addEventListener('change', loadData);
  $('#s3dEnd').addEventListener('change', loadData);
  document.querySelectorAll('[data-s3dheat]').forEach(b => b.addEventListener('click', () => {
    S.heatMode = b.dataset.s3dheat;
    document.querySelectorAll('[data-s3dheat]').forEach(x => x.setAttribute('aria-pressed', String(x === b)));
    loadData();
  }));
  $('#s3dHeat').addEventListener('change', e => { S.showHeat = e.target.checked; paintFloor(); buildAreas(); });
  $('#s3dPeople').addEventListener('change', e => { S.showPeople = e.target.checked; S.groups.people.visible = S.showPeople; });
  $('#s3dLabels').addEventListener('change', e => { S.showLabels = e.target.checked; S.groups.labels.visible = S.showLabels; });
  $('#s3dTop').onclick = () => resetView(true);
  $('#s3dPersp').onclick = () => resetView(false);
  $('#s3dRefresh').onclick = loadData;
  $('#s3dCsv').onclick = () => { location.href = `/api/analytics/export.csv?${params()}`; };
}

let refreshTimer = 0;
document.addEventListener('tq:view', async ev => {
  const show = ev.detail === 'store';
  S.visible = show;
  if (!show) { cancelAnimationFrame(S.raf); S.raf = 0; clearInterval(refreshTimer); return; }
  if (!S.ready) { initScene(); bindControls(); }
  await loadData();
  resize();
  if (!S.raf) loop();
  clearInterval(refreshTimer);
  refreshTimer = setInterval(() => { if (S.range !== 'custom') loadData(); }, S.heatMode === 'live' ? 5000 : 30000);
});
document.addEventListener('tq:metrics', ev => {
  S.live = ev.detail.store;
  if (!S.visible || !S.ready) return;
  updatePeople();
  if (S.metric === 'inside') buildAreas();
});
document.addEventListener('tq:floorplan', () => { if (S.visible) loadData(); else S.plan = null; });
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => { if (S.plan) build(); });
