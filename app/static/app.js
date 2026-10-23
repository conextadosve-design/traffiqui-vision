/* Traffiqui Vision · dashboard (JavaScript vanilla, sin build) */
'use strict';

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const ZONE_COLORS = ['#E0A526', '#1D7A64', '#286EA0', '#964678', '#C8783C', '#3C8282']; // igual que el servidor

let cfg = {};
let metrics = null;
let serverOnline = false;

// ---------------------------------------------------------------- utilidades
function toast(msg, isError = false) {
  const t = $('#toast');
  t.textContent = msg;
  t.classList.toggle('err', isError);
  t.classList.add('show');
  clearTimeout(toast._h);
  toast._h = setTimeout(() => t.classList.remove('show'), isError ? 6000 : 2200);
}

async function api(path, opts = {}) {
  let r;
  try {
    r = await fetch(path, opts);
  } catch {
    throw new Error('No hay conexión con el servidor. Revisa que la ventana de run.bat siga abierta.');
  }
  const body = (r.headers.get('content-type') || '').includes('json') ? await r.json() : null;
  if (!r.ok) throw new Error(body?.detail || `Error ${r.status} del servidor.`);
  return body;
}

async function patch(changes, okMsg = 'Guardado') {
  try {
    cfg = await api('/api/config', {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(changes),
    });
    syncControls();
    if (okMsg) toast(okMsg);
    return true;
  } catch (e) {
    toast(e.message, true);
    syncControls();
    return false;
  }
}

const debounced = {};
function patchLater(key, value, ms = 350) {
  clearTimeout(debounced[key]);
  debounced[key] = setTimeout(() => patch({ [key]: value }), ms);
}

const pad2 = n => String(n).padStart(2, '0');
const hhmm = ts => { const d = new Date(ts * 1000); return `${pad2(d.getHours())}:${pad2(d.getMinutes())}`; };
const fmtSecs = s => s >= 60 ? `${Math.floor(s / 60)} min ${Math.round(s % 60)} s` : `${Math.round(s)} s`;
const cssVar = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

// ---------------------------------------------------------------- pestañas
function showView(name) {
  $$('.tab').forEach(t => t.setAttribute('aria-selected', String(t.dataset.view === name)));
  $$('.view').forEach(v => { v.hidden = v.id !== `view-${name}`; });
  if (name === 'analytics') loadAnalytics();
  if (name === 'settings' && !$('#camSelect').dataset.loaded) scanCameras();
  if (name === 'live') requestAnimationFrame(redrawPending);
  document.dispatchEvent(new CustomEvent('tq:view', { detail: name }));
}
window.tqToast = (msg, isError) => toast(msg, isError);

/** Pregunta con un diálogo propio. Devuelve el texto (o true sin campo), o null si se cancela. */
window.tqAsk = (title, { value = '', text = '', input = true, okLabel = 'Aceptar' } = {}) => new Promise(resolve => {
  const d = $('#askDialog'), inp = $('#askInput');
  $('#askTitle').textContent = title;
  $('#askText').textContent = text;
  $('#askOk').textContent = okLabel;
  inp.hidden = !input;
  inp.required = input;
  inp.value = value;
  d.returnValue = '';
  d.onclose = () => resolve(d.returnValue === 'ok' ? (input ? inp.value.trim() : true) : null);
  d.showModal();
  if (input) { inp.focus(); inp.select(); }
});
window.tqConfirm = (text, okLabel = 'Sí, continuar') =>
  window.tqAsk('Confirmar', { text, input: false, okLabel }).then(v => v === true);
$('#askCancel').addEventListener('click', () => $('#askDialog').close('cancel'));
$$('.tab').forEach(t => t.addEventListener('click', () => showView(t.dataset.view)));

// ---------------------------------------------------------------- alertas
function renderAlerts() {
  const items = [];
  if (!serverOnline) {
    items.push(['El servidor no responde.', 'Revisa que la ventana de run.bat siga abierta. Si la cerraste, vuelve a ejecutar run.bat. Reintentando…']);
  } else if (metrics) {
    if (metrics.model_error) {
      items.push(['No se pudo cargar el modelo de detección.', metrics.model_error]);
    }
    if (!metrics.camera_connected) {
      items.push([metrics.camera_error || 'Cámara desconectada.',
        'Revisa el cable USB o que ninguna otra aplicación (Zoom, Teams, Cámara) esté usando la webcam. Se reintenta cada 3 s; también puedes elegir otra en Configuración.']);
    }
    for (const c of (metrics.cameras || []).filter(c => !c.primary && c.enabled && c.running && !c.connected)) {
      items.push([`«${c.name}» sin señal.`, c.error || 'Revisa la red, la URL RTSP y el usuario/contraseña de la cámara. Se reintenta cada 3 s.']);
    }
    for (const c of (metrics.cameras || []).filter(c => c.connected && ['tapada', 'movida'].includes(c.health?.state))) {
      items.push([`«${c.name}»: ${c.health.state === 'tapada' ? 'imagen tapada o a oscuras' : 'la cámara se movió'}.`,
        c.health.message + (c.health.state === 'movida' ? ' Configuración → Cámaras de la tienda → «Aceptar posición».' : '')]);
    }
    for (const a of (metrics.alerts || [])) items.push([a.title, a.message]);
  }
  $('#alerts').innerHTML = items.map(([t, d]) =>
    `<div class="alert" role="alert"><div><b>${esc(t)}</b><p>${esc(d)}</p></div></div>`).join('');
  const cam = $('#pillCam');
  cam.className = 'pill ' + (metrics && serverOnline ? (metrics.camera_connected ? 'ok' : 'bad') : '');
  cam.textContent = metrics?.camera_connected ? 'Cámara conectada' : 'Cámara sin señal';
  const srv = $('#pillServer');
  srv.className = 'pill ' + (serverOnline ? 'ok' : 'bad');
  srv.textContent = serverOnline ? 'En línea' : 'Sin conexión';
}

// ---------------------------------------------------------------- en vivo
function renderLive(m) {
  $('#kNow').textContent = m.people_now;
  $('#kPeak').textContent = (m.peak ? `Pico: ${m.peak} a las ${hhmm(m.peak_at)}` : 'Pico: –')
    + (m.store?.staff_now ? ` · ${m.store.staff_now} de personal (no cuentan)` : '');
  $('#kToday').textContent = m.unique_today;
  $('#kSession').textContent = `Sesión: ${m.unique_session}`;
  $('#kIn').textContent = m.entries;
  $('#kOut').textContent = m.exits;
  $('#kDwell').innerHTML = m.dwell.avg ? `${Math.round(m.dwell.avg)}<small> s</small>` : '–';
  $('#kMedian').textContent = m.dwell.median ? `Mediana: ${fmtSecs(m.dwell.median)}` : 'Mediana: –';
  $('#kFps').textContent = m.fps.toFixed(1);
  $('#kInfer').textContent = `${Math.round(m.infer_ms)} ms · ${m.backend}`;
  const st = m.store || {};
  $('#kBuyers').textContent = st.has_checkout ? m.buyers_today : '–';
  $('#kConv').textContent = st.has_checkout
    ? `% de las visitas: ${m.unique_today ? Math.round(100 * m.buyers_today / m.unique_today) : 0} %`
    : 'Marca la zona de cajas en el Plano';
  $('#kDoors').textContent = (st.doors || []).length ? `${st.entries} / ${st.exits}` : '–';
  $('#kDoorsSub').textContent = (st.doors || []).length ? 'entradas / salidas (sesión)' : 'Calibra la cámara de la entrada';
  $('#fpsTop').textContent = `${m.fps.toFixed(1)} FPS`;
  $('#peopleCount').textContent = m.people.length ? `(${m.people.length})` : '';
  $('#people').innerHTML = m.people.length
    ? m.people.map(p => {
      const g = (m.store?.people || []).find(x => x.gid === p.id) || {};
      const badge = g.staff ? '<span class="badge staff">Personal</span>' : g.buyer ? '<span class="badge ok">Pasó por caja</span>' : '';
      return `<span class="chip"><span class="dot" style="background:${esc(p.color)}"></span>ID ${p.id} · ${fmtSecs(p.seconds)}${
        (m.cameras || []).length > 1 ? `<small>${esc(p.camera_id)}</small>` : ''}${badge}</span>`;
    }).join('')
    : '<span class="empty">Nadie en cuadro.</span>';
  $('#liveZonesCard').hidden = !m.zones.length;
  $('#liveZones').innerHTML = m.zones.map(z =>
    `<tr><td>${esc(z.name)}</td><td class="num">${z.inside}</td><td class="num">${z.passed}</td><td class="num">${z.stopped}</td></tr>`).join('');
  $('#refStatus').textContent = m.reference_status;
}

function connectWs() {
  const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`);
  ws.onopen = () => {
    if (!serverOnline) { serverOnline = true; reloadVideo(); loadConfig(); }
    renderAlerts();
  };
  ws.onmessage = ev => {
    metrics = JSON.parse(ev.data);
    window.tqLastMetrics = metrics;
    renderLive(metrics);
    renderCamSelector(metrics.cameras || []);
    renderAlerts();
    document.dispatchEvent(new CustomEvent('tq:metrics', { detail: metrics }));
  };
  ws.onclose = () => { serverOnline = false; renderAlerts(); setTimeout(connectWs, 2000); };
}

// ---- selector de cámara del video en vivo
let liveCam = null;
let camKey = '';
function renderCamSelector(cams) {
  const running = cams.filter(c => c.running);
  const key = running.map(c => `${c.id}:${c.name}`).join('|');
  $('#camSelBar').hidden = running.length < 2;
  if (key !== camKey) {
    camKey = key;
    $('#liveCam').innerHTML = running.map(c => `<option value="${esc(c.id)}">${esc(c.name)}${c.primary ? ' (principal)' : ''}</option>`).join('');
    if (!liveCam || !running.some(c => c.id === liveCam)) liveCam = running.find(c => c.primary)?.id || running[0]?.id || null;
    $('#liveCam').value = liveCam || '';
  }
  const cur = cams.find(c => c.id === liveCam);
  const primary = !cur || cur.primary;
  ['#btnDrawLine', '#btnDrawZone', '#btnInvert'].forEach(s => { $(s).disabled = !primary; });
  $('#liveCamNote').textContent = cur ? `${cur.fps.toFixed(1)} FPS · ${cur.calibrated ? 'calibrada' : 'sin calibrar'}${primary ? '' : ' · la línea y las zonas de imagen se dibujan en la cámara principal; para esta usa las áreas del Plano'}` : '';
}
function selectCamera(id) {
  liveCam = id;
  $('#liveCam').value = id;
  reloadVideo();
}
$('#liveCam').addEventListener('change', e => selectCamera(e.target.value));
window.tqSelectCamera = id => { showView('live'); selectCamera(id); };

function reloadVideo() { $('#video').src = `/video?${liveCam ? `cam=${encodeURIComponent(liveCam)}&` : ''}t=${Date.now()}`; }
$('#video').addEventListener('error', () => setTimeout(reloadVideo, 2000));

// ---- dibujo de línea y zonas sobre el video
const canvas = $('#drawCanvas');
const ctx = canvas.getContext('2d');
let drawMode = null;
let pts = [];

function startDraw(mode) {
  showView('live');
  drawMode = mode;
  pts = [];
  $('#stage').classList.add('drawing');
  $('#btnCancelDraw').hidden = false;
  $('#drawHint').textContent = mode === 'line'
    ? 'Haz 2 clics sobre el video: inicio y fin de la línea.'
    : 'Haz clic para agregar vértices. Doble clic o clic derecho para cerrar la zona.';
  redrawPending();
}
function stopDraw() {
  drawMode = null;
  pts = [];
  $('#stage').classList.remove('drawing');
  $('#btnCancelDraw').hidden = true;
  $('#drawHint').textContent = '';
  redrawPending();
}
function normPoint(ev) {
  const r = canvas.getBoundingClientRect();
  const c = v => Math.min(1, Math.max(0, v));
  return [+c((ev.clientX - r.left) / r.width).toFixed(4), +c((ev.clientY - r.top) / r.height).toFixed(4)];
}
function redrawPending() {
  canvas.width = canvas.clientWidth;
  canvas.height = canvas.clientHeight;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (!pts.length) return;
  const W = canvas.width, H = canvas.height;
  ctx.lineWidth = 2;
  ctx.strokeStyle = '#E0A526';
  ctx.fillStyle = 'rgba(224,165,38,.18)';
  ctx.setLineDash([6, 4]);
  ctx.beginPath();
  pts.forEach(([x, y], i) => (i ? ctx.lineTo(x * W, y * H) : ctx.moveTo(x * W, y * H)));
  if (drawMode === 'zone' && pts.length > 2) { ctx.closePath(); ctx.fill(); }
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle = '#E0A526';
  pts.forEach(([x, y]) => { ctx.beginPath(); ctx.arc(x * W, y * H, 5, 0, Math.PI * 2); ctx.fill(); });
}
async function closeZone() {
  if (pts.length < 3) { $('#drawHint').textContent = 'Una zona necesita al menos 3 puntos. Sigue haciendo clic.'; return; }
  const name = (await window.tqAsk('Nombre de la zona', { text: 'Por ejemplo "TV y audio" o "Caja".' })) || '';
  if (!name) { toast('Zona cancelada: falta el nombre.', true); stopDraw(); return; }
  const zones = [...(cfg.zones || []), { id: `z${Date.now().toString(36)}`, name: name.slice(0, 40), points: pts }];
  stopDraw();
  await patch({ zones, show_zones: true }, `Zona «${name}» guardada`);
}
canvas.addEventListener('click', async ev => {
  if (!drawMode) return;
  pts.push(normPoint(ev));
  redrawPending();
  if (drawMode === 'line' && pts.length === 2) {
    const line = { a: pts[0], b: pts[1], inverted: false };
    stopDraw();
    await patch({ line, show_line: true }, 'Línea guardada');
  }
});
canvas.addEventListener('dblclick', ev => {
  if (drawMode !== 'zone') return;
  ev.preventDefault();
  pts.pop(); // el segundo clic del doble clic ya agregó un punto repetido
  closeZone();
});
canvas.addEventListener('contextmenu', ev => { if (drawMode === 'zone') { ev.preventDefault(); closeZone(); } });
window.addEventListener('keydown', ev => { if (ev.key === 'Escape' && drawMode) stopDraw(); });
window.addEventListener('resize', redrawPending);

$('#btnDrawLine').onclick = () => startDraw('line');
$('#btnDrawZone').onclick = () => startDraw('zone');
$('#btnCancelDraw').onclick = stopDraw;
$$('[data-goto-draw]').forEach(b => b.addEventListener('click', () => startDraw(b.dataset.gotoDraw)));
const invertLine = () => cfg.line
  ? patch({ line: { ...cfg.line, inverted: !cfg.line.inverted } }, 'Dirección invertida')
  : toast('Primero dibuja una línea.', true);
$('#btnInvert').onclick = invertLine;
$('#btnInvert2').onclick = invertLine;
$('#btnDelLine').onclick = async () => {
  if (cfg.line && await window.tqConfirm('¿Borrar la línea? Los conteos guardados se conservan.', 'Borrar')) patch({ line: null }, 'Línea borrada');
};
$('#btnResetHeat').onclick = async () => {
  try { await api('/api/heatmap/reset', { method: 'POST' }); toast('Mapa de calor reiniciado'); }
  catch (e) { toast(e.message, true); }
};
$$('[data-heatmode]').forEach(b => b.addEventListener('click', () =>
  patch({ heatmap_mode: b.dataset.heatmode, show_heatmap: true }, b.dataset.heatmode === 'live' ? 'Calor en vivo' : 'Calor acumulado')));

// ---------------------------------------------------------------- controles ↔ configuración
$$('input[data-cfg]').forEach(el => el.addEventListener('change', () => patch({ [el.dataset.cfg]: el.checked }, null)));
$$('input[data-cfg-range]').forEach(el => {
  el.addEventListener('input', () => { setOutput(el.dataset.cfgRange, +el.value, el.dataset.unit); patchLater(el.dataset.cfgRange, +el.value); });
});
$$('input[data-cfg-radio]').forEach(el => el.addEventListener('change', () => el.checked && patch({ [el.dataset.cfgRadio]: el.value })));
$$('select[data-cfg-select]').forEach(el => el.addEventListener('change', () =>
  patch({ [el.dataset.cfgSelect]: 'num' in el.dataset ? +el.value : el.value })));
$('#resSelect').addEventListener('change', e => {
  const [width, height] = e.target.value.split('x').map(Number);
  patch({ width, height }, 'Resolución aplicada; la cámara se reabre');
});

function setOutput(key, v, unit = '') {
  $$(`output[data-for="${key}"]`).forEach(o => { o.textContent = `${v}${unit || ''}`; });
}

function syncControls() {
  $$('input[data-cfg]').forEach(el => { el.checked = !!cfg[el.dataset.cfg]; });
  $$('input[data-cfg-range]').forEach(el => {
    if (document.activeElement !== el) el.value = cfg[el.dataset.cfgRange];
    setOutput(el.dataset.cfgRange, cfg[el.dataset.cfgRange], el.dataset.unit);
  });
  $$('input[data-cfg-radio]').forEach(el => { el.checked = cfg[el.dataset.cfgRadio] === el.value; });
  $$('select[data-cfg-select]').forEach(el => { el.value = String(cfg[el.dataset.cfgSelect]); });
  $('#resSelect').value = `${cfg.width}x${cfg.height}`;
  $$('[data-heatmode]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.heatmode === cfg.heatmap_mode)));
  $('#lineInfo').textContent = cfg.line
    ? `Línea activa. La flecha verde del video marca la dirección de "entrada"${cfg.line.inverted ? ' (invertida)' : ''}.`
    : 'Sin línea. Dibújala con 2 clics sobre el video.';
  renderZoneList();
}

function renderZoneList() {
  const zones = cfg.zones || [];
  $('#zoneList').innerHTML = zones.length ? zones.map((z, i) => `
    <li><span class="swatch" style="background:${ZONE_COLORS[i % ZONE_COLORS.length]}"></span>
      <input type="text" value="${esc(z.name)}" data-zone-name="${esc(z.id)}" maxlength="40" aria-label="Nombre de la zona">
      <button class="btn danger" data-zone-del="${esc(z.id)}">Borrar</button></li>`).join('')
    : '<li class="empty">Sin zonas. Dibuja una con clics sobre el video.</li>';
  $$('[data-zone-name]').forEach(inp => inp.addEventListener('change', () => {
    const name = inp.value.trim();
    if (!name) { toast('El nombre de la zona no puede quedar vacío.', true); syncControls(); return; }
    patch({ zones: cfg.zones.map(z => (z.id === inp.dataset.zoneName ? { ...z, name } : z)) }, 'Zona renombrada');
  }));
  $$('[data-zone-del]').forEach(b => b.addEventListener('click', async () => {
    const z = cfg.zones.find(z => z.id === b.dataset.zoneDel);
    if (z && await window.tqConfirm(`¿Borrar la zona «${z.name}»? Su histórico se conserva.`, 'Borrar')) {
      patch({ zones: cfg.zones.filter(x => x.id !== z.id) }, 'Zona borrada');
    }
  }));
}

async function loadConfig() {
  try { cfg = await api('/api/config'); syncControls(); } catch (e) { toast(e.message, true); }
}

// ---------------------------------------------------------------- cámaras
async function scanCameras() {
  const sel = $('#camSelect');
  sel.innerHTML = '<option>Buscando…</option>';
  $('#camHelp').textContent = 'Buscando cámaras en los índices 0 a 5 (tarda unos segundos)…';
  try {
    const { cameras, demo_source } = await api('/api/cameras');
    sel.dataset.loaded = '1';
    sel.innerHTML = cameras.length
      ? cameras.map(c => `<option value="${c.index}">Cámara ${c.index}${c.in_use ? ' (en uso)' : ''}</option>`).join('')
      : '<option value="">No se encontró ninguna cámara</option>';
    if (cameras.length) sel.value = String(cfg.camera_index);
    $('#camHelp').textContent = demo_source
      ? `Modo demo: leyendo «${demo_source}» en bucle. Elige una cámara para usarla.`
      : cameras.length ? `${cameras.length} cámara(s) disponible(s).`
        : 'Conecta una webcam o inicia en modo demo con run.bat --source video.mp4';
  } catch (e) { $('#camHelp').textContent = e.message; }
}
$('#btnScanCams').onclick = scanCameras;
$('#btnTestCam').onclick = async () => {
  const idx = $('#camSelect').value;
  if (idx === '') return;
  const img = $('#camPreview');
  $('#camHelp').textContent = `Probando la cámara ${idx}…`;
  try {
    const r = await fetch(`/api/cameras/${idx}/test?t=${Date.now()}`);
    if (!r.ok) throw new Error((await r.json()).detail);
    img.src = URL.createObjectURL(await r.blob());
    img.hidden = false;
    $('#camHelp').textContent = `La cámara ${idx} responde. Si es la correcta, pulsa "Usar esta cámara".`;
  } catch (e) { img.hidden = true; $('#camHelp').textContent = e.message; }
};
$('#btnUseCam').onclick = () => {
  const idx = $('#camSelect').value;
  if (idx !== '') patch({ camera_index: +idx }, `Usando la cámara ${idx}`).then(() => setTimeout(scanCameras, 4000));
};

// ---------------------------------------------------------------- analítica
let range = 'today';
const charts = {};

$$('[data-range]').forEach(b => b.addEventListener('click', () => {
  range = b.dataset.range;
  $$('[data-range]').forEach(x => x.setAttribute('aria-pressed', String(x === b)));
  $('#customRange').hidden = range !== 'custom';
  // intervalo sugerido para cada rango (se puede cambiar después)
  const sel = $('#bucket'), cur = +sel.value;
  if (range === 'week' && cur < 60) sel.value = '60';
  if (range === 'month') sel.value = '1440';
  if ((range === 'today' || range === 'hour') && cur === 1440) sel.value = '15';
  if (range === 'custom' && !$('#rangeStart').value) {
    const d = new Date(), local = x => new Date(x - x.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
    $('#rangeEnd').value = local(d);
    $('#rangeStart').value = local(new Date(d - 3 * 3600 * 1000));
  }
  loadAnalytics();
}));
$('#bucket').addEventListener('change', loadAnalytics);
$('#btnRefresh').onclick = loadAnalytics;
$('#rangeStart').addEventListener('change', loadAnalytics);
$('#rangeEnd').addEventListener('change', loadAnalytics);

function rangeParams(withBucket = true) {
  const p = new URLSearchParams({ range });
  if (range === 'custom') { p.set('start', $('#rangeStart').value); p.set('end', $('#rangeEnd').value); }
  if (withBucket) p.set('bucket', $('#bucket').value);
  return p.toString();
}
$('#btnCsv').onclick = () => { location.href = `/api/analytics/export.csv?${rangeParams()}`; };
$('#btnRecapture').onclick = async () => {
  try {
    const r = await api('/api/reference/recapture', { method: 'POST' });
    toast(r.message);
    setTimeout(loadHeatmap, 11000);
  } catch (e) { toast(e.message, true); }
};

function chartTheme() {
  return {
    c1: cssVar('--chart-1'), c2: cssVar('--chart-2'), grid: cssVar('--grid'),
    muted: cssVar('--muted'), text: cssVar('--text'), surface: cssVar('--surface'),
  };
}

function baseOptions(th, { stacked = false, integer = true } = {}) {
  return {
    responsive: true, maintainAspectRatio: false, animation: false,
    interaction: { mode: 'index', intersect: false },
    plugins: {
      legend: { display: false }, // leyenda propia en HTML encima del gráfico
      tooltip: {
        backgroundColor: th.surface, titleColor: th.text, bodyColor: th.text, borderColor: th.grid,
        borderWidth: 1, padding: 10, boxPadding: 4, usePointStyle: true,
      },
    },
    scales: {
      x: { stacked, grid: { display: false }, border: { color: th.grid },
           ticks: { color: th.muted, maxRotation: 0, autoSkip: true, maxTicksLimit: 12 } },
      y: { stacked, beginAtZero: true, grid: { color: th.grid }, border: { display: false },
           ticks: { color: th.muted, precision: integer ? 0 : undefined } },
    },
  };
}

function upsertChart(id, config) {
  if (charts[id]) {
    charts[id].data = config.data;
    charts[id].options = config.options;
    charts[id].update();
  } else {
    charts[id] = new Chart($(`#${id}`), config);
  }
}

/* En "Hoy" se omiten los intervalos vacíos antes del primer dato (deja al menos 1 h visible). */
function trimLeading(d) {
  if (range !== 'today') return d;
  const size = d.range.bucket_minutes * 60;
  const firstData = [
    d.occupancy.findIndex(o => o.avg !== null),
    d.unique.findIndex(u => u.count > 0),
  ].filter(i => i >= 0);
  let from = firstData.length ? Math.min(...firstData) : d.occupancy.length;
  from = Math.max(0, Math.min(from, d.occupancy.length - Math.ceil(3600 / size)));
  const t0 = d.occupancy[from]?.t ?? 0;
  const hourFrom = d.line_by_hour.findIndex(r => r.t + 3600 > t0);
  return { ...d, occupancy: d.occupancy.slice(from), unique: d.unique.slice(from),
           line_by_hour: d.line_by_hour.slice(Math.max(0, hourFrom)) };
}

let lastAnalytics = null;
function drawCharts(raw) {
  const d = trimLeading(raw);
  const th = chartTheme();
  const bar = (label, data, color) => ({ label, data, backgroundColor: color, borderRadius: 4, borderSkipped: 'start', maxBarThickness: 28, borderColor: th.surface, borderWidth: { left: 1, right: 1 } });
  const labels = d.occupancy.map(o => bucketLabel(o.t, d));

  upsertChart('chOcc', {
    type: 'line',
    data: { labels, datasets: [
      { label: 'Promedio', data: d.occupancy.map(o => o.avg), borderColor: th.c2, backgroundColor: th.c2, borderWidth: 2, pointRadius: 0, pointHoverRadius: 5, tension: .25, spanGaps: false },
      { label: 'Máximo', data: d.occupancy.map(o => o.max), borderColor: th.c1, backgroundColor: th.c1, borderWidth: 2, pointRadius: 0, pointHoverRadius: 5, stepped: 'middle', spanGaps: false },
    ] },
    options: baseOptions(th, { integer: false }),
  });
  upsertChart('chUnique', {
    type: 'bar',
    data: { labels: d.unique.map(u => bucketLabel(u.t, d)), datasets: [bar('Personas únicas', d.unique.map(u => u.count), th.c2)] },
    options: baseOptions(th),
  });
  upsertChart('chDwell', {
    type: 'bar',
    data: { labels: Object.keys(d.dwell.buckets), datasets: [bar('Personas', Object.values(d.dwell.buckets), th.c2)] },
    options: baseOptions(th),
  });
  upsertChart('chLine', {
    type: 'bar',
    data: { labels: d.line_by_hour.map(r => bucketLabel(r.t, { range: { ...d.range, bucket_minutes: 60 } })), datasets: [
      bar('Entradas', d.line_by_hour.map(r => r.in), th.c1),
      bar('Salidas', d.line_by_hour.map(r => r.out), th.c2),
    ] },
    options: baseOptions(th),
  });
}

function renderAnalytics(d) {
  const t = d.totals;
  $('#tUnique').textContent = t.unique;
  $('#tIn').textContent = t.entries;
  $('#tOut').textContent = t.exits;
  $('#tPeak').textContent = t.peak;
  $('#tPeakAt').textContent = t.peak_at ? `a las ${hhmm(t.peak_at)}` : '';
  $('#tDwell').innerHTML = d.dwell.avg ? `${Math.round(d.dwell.avg)}<small> s</small>` : '–';
  $('#tMedian').textContent = d.dwell.median ? `Mediana: ${fmtSecs(d.dwell.median)}` : '';
  const maxPassed = Math.max(1, ...d.zones.map(z => z.passed));
  $('#zoneTable').innerHTML = d.zones.length ? d.zones.map(z => `
    <tr><td>${esc(z.name)}</td>
      <td class="num"><div class="bar-cell"><span style="width:${Math.round(60 * z.passed / maxPassed)}px"></span>${z.passed}</div></td>
      <td class="num">${z.stopped}</td>
      <td class="num">${Math.round(z.stop_rate * 100)} %</td>
      <td class="num">${fmtSecs(z.avg_dwell)}</td></tr>`).join('')
    : '<tr><td colspan="5" class="empty">Sin visitas a zonas en este rango. Dibuja zonas en la pestaña En vivo.</td></tr>';
  drawCharts(d);
}

function loadHeatmap() {
  $('#heatImg').src = `/api/analytics/heatmap.png?${rangeParams(false)}&t=${Date.now()}`;
  $('#heatRangeLabel').textContent = RANGE_LABELS[range];
}
const RANGE_LABELS = { today: 'hoy', hour: 'última hora', week: 'últimos 7 días', month: 'últimos 30 días', custom: 'rango personalizado' };

async function loadAnalytics() {
  try {
    lastAnalytics = await api(`/api/analytics?${rangeParams()}`);
    // el servidor sube el intervalo si el rango es muy largo para el elegido
    const used = String(lastAnalytics.range.bucket_minutes);
    if ($('#bucket').value !== used) { $('#bucket').value = used; toast('Para este rango se usa un intervalo más grande.'); }
    renderAnalytics(lastAnalytics);
    loadHeatmap();
    document.dispatchEvent(new CustomEvent('tq:analytics-range', { detail: { range, params: rangeParams(false) } }));
  } catch (e) { toast(e.message, true); }
}

/** Etiqueta de un intervalo: solo hora si el rango es de un día; con fecha si abarca varios. */
const WD = ['dom', 'lun', 'mar', 'mié', 'jue', 'vie', 'sáb'];
function bucketLabel(ts, d) {
  const multi = d.range.end - d.range.start > 36 * 3600;
  const x = new Date(ts * 1000), day = `${WD[x.getDay()]} ${pad2(x.getDate())}/${pad2(x.getMonth() + 1)}`;
  if (d.range.bucket_minutes >= 1440) return day;
  return multi ? `${day} ${hhmm(ts)}` : hhmm(ts);
}

// refresco automático de la analítica (rangos relativos) cada minuto
setInterval(() => { if (!$('#view-analytics').hidden && range !== 'custom') loadAnalytics(); }, 60000);
// los colores de los gráficos cambian con el modo claro/oscuro
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => lastAnalytics && drawCharts(lastAnalytics));

// ---------------------------------------------------------------- inicio
loadConfig();
connectWs();
