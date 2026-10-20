/* Traffiqui Vision · cámaras de la tienda y calibración imagen ↔ plano */
'use strict';

(() => {
  const $ = (s, r = document) => r.querySelector(s);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const toast = (m, e) => window.tqToast?.(m, e);
  let cams = [];

  async function api(path, opts = {}) {
    const r = await fetch(path, opts);
    const body = (r.headers.get('content-type') || '').includes('json') ? await r.json() : null;
    if (!r.ok) throw new Error(body?.detail || `Error ${r.status} del servidor.`);
    return body;
  }
  const json = (method, body) => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

  // ------------------------------------------------------------------ lista
  async function load() {
    try {
      cams = (await api('/api/cams')).cameras;
      render();
      document.dispatchEvent(new CustomEvent('tq:cameras', { detail: cams }));
    } catch (e) { $('#camsList').innerHTML = `<tr><td colspan="6" class="empty">${esc(e.message)}</td></tr>`; }
  }

  function statusPill(c) {
    if (!c.enabled) return '<span class="pill">Deshabilitada</span>';
    if (!c.connected) return `<span class="pill bad" title="${esc(c.error || '')}">Sin señal</span>`;
    return `<span class="pill ok">${c.fps.toFixed(1)} FPS</span>`;
  }

  function render() {
    $('#camsList').innerHTML = cams.map(c => `
      <tr data-cam="${esc(c.id)}">
        <td><input type="text" value="${esc(c.name)}" data-f="name" maxlength="40" aria-label="Nombre">
            <div class="note">${esc(c.id)}${c.primary ? ' · principal' : ''}</div></td>
        <td><input type="text" value="${esc(c.source)}" data-f="source" aria-label="Fuente" ${c.source.includes('***') ? 'placeholder="(con contraseña)"' : ''}>
            <div class="note">${{ usb: 'Webcam USB', stream: 'Stream RTSP/HTTP', file: 'Video (demo)' }[c.kind]}</div></td>
        <td><input type="number" value="${c.max_fps}" min="0" max="30" step="1" data-f="max_fps" aria-label="FPS máximos" style="width:5em"></td>
        <td>${statusPill(c)}${c.error && c.enabled ? `<div class="note err">${esc(c.error)}</div>` : ''}</td>
        <td>${c.calibrated ? `<span class="pill ok">Calibrada · ±${(c.calibration_error_m ?? 0).toFixed(2)} m</span>` : '<span class="pill">Sin calibrar</span>'}</td>
        <td class="cam-actions">
          <button class="btn" data-a="calib">Calibrar</button>
          <button class="btn" data-a="view">Ver</button>
          ${c.primary ? '' : `<label class="switch"><input type="checkbox" data-f="enabled" ${c.enabled ? 'checked' : ''}>Activa</label>
          <button class="btn danger" data-a="del">Borrar</button>`}
        </td>
      </tr>`).join('');
    $('#camsList').querySelectorAll('[data-f]').forEach(inp => inp.addEventListener('change', async () => {
      const id = inp.closest('tr').dataset.cam, f = inp.dataset.f;
      if (f === 'source' && inp.value.includes('***')) { toast('Escribe la URL completa con usuario y contraseña para cambiarla.', true); return render(); }
      const v = f === 'enabled' ? inp.checked : f === 'max_fps' ? +inp.value : inp.value;
      try { await api(`/api/cams/${id}`, json('PATCH', { [f]: v })); toast('Cámara actualizada'); }
      catch (e) { toast(e.message, true); }
      setTimeout(load, 1500);
    }));
    $('#camsList').querySelectorAll('[data-a]').forEach(b => b.addEventListener('click', async () => {
      const id = b.closest('tr').dataset.cam, cam = cams.find(c => c.id === id);
      if (b.dataset.a === 'calib') openCalibration(cam);
      if (b.dataset.a === 'view') { window.tqSelectCamera?.(id); }
      if (b.dataset.a === 'del' && await window.tqConfirm(`¿Borrar «${cam.name}»? Su histórico se conserva.`, 'Borrar')) {
        try { await api(`/api/cams/${id}`, { method: 'DELETE' }); toast('Cámara borrada'); load(); } catch (e) { toast(e.message, true); }
      }
    }));
  }

  async function addCamera(ev) {
    ev.preventDefault();
    const f = new FormData($('#camAddForm'));
    const kind = f.get('kind');
    let source = String(f.get('source') || '').trim();
    if (kind === 'usb' && !/^\d+$/.test(source)) { toast('Para una webcam USB escribe su índice: 0, 1, 2…', true); return; }
    if (kind === 'stream' && !/^(rtsps?|https?):\/\//i.test(source)) { toast('La URL debe empezar con rtsp:// (o http://).', true); return; }
    try {
      await api('/api/cams', json('POST', { name: String(f.get('name') || '').trim() || undefined, source, max_fps: +f.get('max_fps') }));
      $('#camAddForm').reset();
      toast('Cámara agregada; se conecta en unos segundos');
      setTimeout(load, 2500);
    } catch (e) { toast(e.message, true); }
  }

  function onKindChange() {
    const k = $('#camKind').value, inp = $('#camSource');
    inp.placeholder = { usb: '1', stream: 'rtsp://usuario:clave@192.168.1.64:554/Streaming/Channels/102', file: 'C:\\videos\\pasillo.mp4' }[k];
  }

  // ------------------------------------------------------------------ calibración
  const cal = { cam: null, image: [], plan: [], waiting: 'image', size: null };

  async function openCalibration(cam) {
    cal.cam = cam;
    const cfg = await api('/api/config');
    const full = cfg.cameras.find(c => c.id === cam.id);
    cal.image = (full?.calibration?.image || []).map(p => [...p]);
    cal.plan = (full?.calibration?.plan || []).map(p => [...p]);
    cal.waiting = cal.image.length > cal.plan.length ? 'plan' : 'image';
    $('#calTitle').textContent = `Calibrar «${cam.name}»`;
    $('#calResult').textContent = cam.calibrated ? `Calibración actual: error medio ${(cam.calibration_error_m ?? 0).toFixed(2)} m.` : '';
    $('#calDialog').showModal();
    await refreshSnapshot();
    drawPlan();
    renderPairs();
  }

  async function refreshSnapshot() {
    const img = $('#calImg');
    try {
      const r = await fetch(`/api/cams/${cal.cam.id}/snapshot?t=${Date.now()}`);
      if (!r.ok) throw new Error((await r.json()).detail);
      img.src = URL.createObjectURL(await r.blob());
      await img.decode();
      drawImagePoints();
    } catch (e) { toast(e.message, true); }
  }

  function drawImagePoints() {
    const img = $('#calImg'), cv = $('#calCanvas');
    cv.width = img.clientWidth; cv.height = img.clientHeight;
    const ctx = cv.getContext('2d');
    ctx.clearRect(0, 0, cv.width, cv.height);
    cal.image.forEach(([u, v], i) => marker(ctx, u * cv.width, v * cv.height, i + 1, i < cal.plan.length));
  }
  function marker(ctx, x, y, n, paired) {
    ctx.beginPath(); ctx.arc(x, y, 9, 0, Math.PI * 2);
    ctx.fillStyle = paired ? '#1D7A64' : '#E0A526'; ctx.fill();
    ctx.lineWidth = 2; ctx.strokeStyle = '#fff'; ctx.stroke();
    ctx.fillStyle = '#fff'; ctx.font = 'bold 11px Segoe UI, sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText(String(n), x, y + 0.5);
  }

  function drawPlan(footprint) {
    const svg = $('#calPlan'), plan = window.TQPlan.plan;
    if (!plan) return;
    window.TQPlan.render(svg, plan, { fit: true, footprints: footprint ? { [cal.cam.id]: footprint } : null, labels: true });
    const NS = 'http://www.w3.org/2000/svg';
    cal.plan.forEach(([x, y], i) => {
      const c = document.createElementNS(NS, 'circle');
      c.setAttribute('cx', x); c.setAttribute('cy', y); c.setAttribute('r', 0.3); c.setAttribute('class', 'cal-pt');
      svg.appendChild(c);
      const t = document.createElementNS(NS, 'text');
      t.setAttribute('x', x); t.setAttribute('y', y + 0.12); t.setAttribute('class', 'cal-num'); t.textContent = i + 1;
      svg.appendChild(t);
    });
  }

  function renderPairs() {
    const n = Math.min(cal.image.length, cal.plan.length);
    $('#calStep').innerHTML = cal.waiting === 'image'
      ? `<b>Punto ${cal.image.length + 1}:</b> haz clic en un punto del <b>piso</b> en la imagen de la cámara.`
      : `<b>Punto ${cal.image.length}:</b> ahora haz clic en <b>ese mismo lugar</b> en el plano.`;
    $('#calPairs').innerHTML = cal.image.map((p, i) => `<li>${i + 1}. imagen (${p[0].toFixed(2)}, ${p[1].toFixed(2)}) → ${cal.plan[i] ? `plano (${cal.plan[i][0].toFixed(2)} m, ${cal.plan[i][1].toFixed(2)} m)` : '<i>falta en el plano</i>'}</li>`).join('');
    $('#calSave').disabled = n < 4 || cal.image.length !== cal.plan.length;
    $('#calCount').textContent = `${n} par(es) · mínimo 4`;
  }

  function onImageClick(ev) {
    if (cal.waiting !== 'image') { toast('Primero marca en el plano el punto anterior.', true); return; }
    const r = $('#calCanvas').getBoundingClientRect();
    cal.image.push([+((ev.clientX - r.left) / r.width).toFixed(4), +((ev.clientY - r.top) / r.height).toFixed(4)]);
    cal.waiting = 'plan';
    drawImagePoints(); renderPairs();
  }
  function onPlanClick(ev) {
    if (cal.waiting !== 'plan') { toast('Primero marca el punto en la imagen de la cámara.', true); return; }
    const [x, y] = window.TQPlan.svgPoint($('#calPlan'), ev);
    const plan = window.TQPlan.plan;
    if (x < 0 || y < 0 || x > plan.width || y > plan.depth) { toast('Ese punto queda fuera del local.', true); return; }
    cal.plan.push([+x.toFixed(2), +y.toFixed(2)]);
    cal.waiting = 'image';
    drawPlan(); drawImagePoints(); renderPairs();
  }
  function undoPoint() {
    if (cal.image.length > cal.plan.length) cal.image.pop(); else { cal.plan.pop(); cal.image.pop(); }
    cal.waiting = 'image';
    drawPlan(); drawImagePoints(); renderPairs();
  }
  async function saveCalibration() {
    try {
      const r = await api(`/api/cams/${cal.cam.id}/calibration`, json('PUT', { image: cal.image, plan: cal.plan }));
      $('#calResult').innerHTML = `Calibración guardada. Error medio: <b>${r.error_m.toFixed(2)} m</b>${r.error_m > 0.5 ? ' (alto: revisa que todos los puntos estén sobre el piso)' : ''}. El área sombreada del plano es lo que ve la cámara.`;
      drawPlan(r.footprint);
      toast('Calibración guardada');
      load();
    } catch (e) { toast(e.message, true); }
  }
  async function clearCalibration() {
    if (!await window.tqConfirm('¿Quitar la calibración de esta cámara? Dejará de medir áreas del plano.', 'Quitar')) return;
    try { await api(`/api/cams/${cal.cam.id}/calibration`, { method: 'DELETE' }); cal.image = []; cal.plan = []; cal.waiting = 'image'; drawPlan(); drawImagePoints(); renderPairs(); load(); toast('Calibración quitada'); }
    catch (e) { toast(e.message, true); }
  }

  function init() {
    if ($('#camsCard').dataset.ready) return;
    $('#camsCard').dataset.ready = '1';
    $('#camAddForm').addEventListener('submit', addCamera);
    $('#camKind').addEventListener('change', onKindChange);
    onKindChange();
    $('#camsRefresh').onclick = load;
    $('#calCanvas').addEventListener('click', onImageClick);
    $('#calPlan').addEventListener('click', onPlanClick);
    $('#calUndo').onclick = undoPoint;
    $('#calClear').onclick = () => { cal.image = []; cal.plan = []; cal.waiting = 'image'; drawPlan(); drawImagePoints(); renderPairs(); };
    $('#calSnap').onclick = refreshSnapshot;
    $('#calSave').onclick = saveCalibration;
    $('#calRemove').onclick = clearCalibration;
    $('#calClose').onclick = () => $('#calDialog').close();
    window.addEventListener('resize', () => { if ($('#calDialog').open) drawImagePoints(); });
  }

  document.addEventListener('tq:view', async ev => {
    if (ev.detail !== 'settings') return;
    init();
    if (!window.TQPlan.plan) await window.TQPlan.reload();
    load();
  });
  window.TQCams = { load, get list() { return cams; } };
})();
