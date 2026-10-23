/* Traffiqui · sede principal: una sede en vivo y su analítica completa */
'use strict';

(() => {
  const $ = (s, r = document) => r.querySelector(s);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const cssVar = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const num = x => (x ?? 0).toLocaleString('es');
  const pct = x => `${Math.round((x || 0) * 100)} %`;
  const slot = h => h === null || h === undefined ? '–' : `${String(h).padStart(2, '0')}–${String((h + 1) % 24).padStart(2, '0')} h`;
  const sid = Number(location.pathname.split('/').pop());
  let range = 'today', plan = null, last = null;
  const charts = {};

  function secs(s) {
    if (s === null || s === undefined) return '–';
    s = Math.round(s);
    return s < 60 ? `${s} s` : `${Math.floor(s / 60)} min ${String(s % 60).padStart(2, '0')} s`;
  }
  function ago(ts) {
    if (!ts) return 'nunca';
    const s = Math.max(0, Math.round(Date.now() / 1000 - ts));
    if (s < 60) return `hace ${s} s`;
    if (s < 3600) return `hace ${Math.round(s / 60)} min`;
    if (s < 86400) return `hace ${Math.round(s / 3600)} h`;
    return `el ${new Date(ts * 1000).toLocaleDateString('es')}`;
  }
  /** "▲ 12 % vs semana ant. · ▼ 3 % vs mes pasado" */
  function cmpText(c, key, unit = '%') {
    if (!c) return '';
    const part = (v, label) => v === null || v === undefined ? `– ${label}`
      : `${v > 0 ? '▲' : v < 0 ? '▼' : '='} ${Math.abs(v).toLocaleString('es')} ${unit} ${label}`;
    return `${part(c.week?.[key], 'vs semana ant.')} · ${part(c.month?.[key], 'vs mes pasado')}`;
  }

  let toastTimer;
  function toast(msg, isError) {
    const t = $('#toast');
    t.textContent = msg; t.hidden = false; t.className = `toast show${isError ? ' err' : ''}`;
    clearTimeout(toastTimer); toastTimer = setTimeout(() => { t.className = 'toast'; }, 4000);
  }
  async function api(path, opts) {
    const r = await fetch(path, opts);
    if (r.status === 401) { location.href = '/login'; throw new Error('Sesión cerrada.'); }
    const body = await r.json();
    if (!r.ok) throw new Error(body.detail || `Error ${r.status} del servidor.`);
    return body;
  }

  // ---------------------------------------------------------------- en vivo
  async function loadLive() {
    let d;
    try { d = await api(`/api/sites/${sid}/live`); } catch (e) { toast(e.message, true); return; }
    plan = d.floorplan || plan;
    $('#siteName').textContent = d.site.name;
    document.title = `Traffiqui · ${d.site.name}`;
    const L = d.live;
    const st = d.site.status !== 'active' ? ['bad', d.site.status === 'suspended' ? 'Suspendida' : 'Pendiente']
      : L ? ['ok', 'En vivo'] : ['bad', `Sin datos en vivo · último envío ${ago(d.site.last_sync_at)}`];
    $('#siteState').className = `state ${st[0]}`;
    $('#siteState').textContent = st[1];
    $('#liveOff').hidden = !!L;
    // la tienda envía al ritmo que le pidió la sede principal; si venía de 30 s, el primer envío rápido tarda hasta 30 s
    const slow = L && L.next_s > d.next_s;
    $('#liveAge').textContent = L ? `actualizado ${ago(L.ts)} · cada ${slow ? `${L.next_s} s, pasando a ${d.next_s} s` : `${d.next_s} s`}` : '';
    if (!L) {
      tqPlan.draw($('#livePlan'), plan, {});
      return;
    }
    $('#lNow').textContent = num(L.people_now);
    $('#lPeak').textContent = L.peak ? `Pico: ${L.peak}${L.peak_at ? ` a las ${new Date(L.peak_at * 1000).toLocaleTimeString('es', { hour: '2-digit', minute: '2-digit' })}` : ''}` : '';
    $('#lToday').textContent = num(L.unique_today);
    $('#lCheckout').textContent = num(L.checkout_today);
    $('#lCheckoutSub').textContent = L.unique_today ? `${pct(L.checkout_today / L.unique_today)} de las visitas` : '';
    $('#lDoors').textContent = `${num(L.entries)} / ${num(L.exits)}`;
    $('#lDwell').textContent = secs(L.dwell?.avg);
    $('#lStaff').textContent = L.staff_now ? `${L.staff_now} del personal ahora (no cuentan)` : 'en la tienda';
    const inside = Object.fromEntries((L.areas || []).map(a => [a.name, a.inside]));
    tqPlan.draw($('#livePlan'), plan, { areas: inside, people: L.people });
    $('#planNote').textContent = (L.people || []).length
      ? `${L.people.length} persona(s) ubicadas en el plano. Las que ve una cámara sin calibrar cuentan, pero no aparecen aquí.`
      : 'Nadie en el plano ahora mismo.';
    $('#liveAlerts').innerHTML = (L.alerts || []).length
      ? L.alerts.map(a => `<li><b>${esc(a.title)}</b><span class="note">${esc(a.message)} · desde ${ago(a.since)}</span></li>`).join('')
      : '<li class="empty">Sin alertas.</li>';
    $('#liveCams').innerHTML = (L.cameras || []).map(c => {
      const h = c.health || {};
      const [cls, txt] = !c.enabled ? ['', 'Deshabilitada'] : !c.connected ? ['bad', 'Sin señal']
        : h.state === 'tapada' ? ['bad', 'Tapada u oscura'] : h.state === 'movida' ? ['bad', 'Se movió']
        : h.state === 'ok' ? ['ok', `${c.fps} FPS`] : ['', 'Comprobando…'];
      return `<li><span>${esc(c.name)}</span><span class="state ${cls}">${txt}</span></li>`;
    }).join('') || '<li class="empty">Sin cámaras.</li>';
    const cajas = (L.areas || []).filter(a => a.kind === 'caja');
    $('#liveCajas').innerHTML = cajas.length
      ? cajas.map(a => `<li><span>${esc(a.name)}</span><b>${a.inside} en fila</b></li>`).join('')
      : '<li class="empty">Esta tienda no tiene cajas marcadas en el plano.</li>';
  }

  // ---------------------------------------------------------------- analítica
  function params() {
    const p = new URLSearchParams({ range });
    if (range === 'custom') { p.set('start', $('#start').value); p.set('end', $('#end').value); }
    return p;
  }

  async function loadReport() {
    if (range === 'custom' && (!$('#start').value || !$('#end').value)) return;
    try { last = await api(`/api/sites/${sid}/report?${params()}`); renderReport(last); }
    catch (e) { toast(e.message, true); }
  }

  function renderReport(d) {
    const s = d.summary, c = d.compare;
    $('#aVisits').textContent = num(s.visits);
    $('#aVisitsCmp').textContent = cmpText(c, 'visits');
    $('#aCheckout').textContent = num(s.checkout);
    $('#aCheckoutCmp').textContent = s.visits ? `${pct(s.checkout_rate)} de las visitas · ${cmpText(c, 'checkout_rate_pts', 'pts')}` : '';
    $('#aDwell').textContent = secs(s.avg_dwell);
    $('#aDwellCmp').textContent = cmpText(c, 'avg_dwell');
    $('#aPeak').textContent = slot(s.peak_hour);
    $('#aPeakSub').textContent = s.peak_hour !== null ? `${num(s.peak_hour_visits)} visitas en esa hora` : '';
    $('#aMax').textContent = num(s.max_occupancy);
    $('#areasTable').innerHTML = d.areas.length ? d.areas.map(a => `<tr><td>${esc(a.name)}</td><td class="num"><b>${num(a.people)}</b></td>
      <td class="num">${pct(a.stop_rate)}</td><td class="num">${secs(a.avg_seconds)}</td></tr>`).join('')
      : '<tr><td colspan="4" class="empty">Sin visitas a áreas en este rango (o la tienda no tiene áreas en el plano).</td></tr>';
    $('#transList').innerHTML = d.transitions.length
      ? d.transitions.map(t => `<li><span>${esc(t.from)} → ${esc(t.to)}</span><b>${num(t.count)}</b></li>`).join('')
      : '<li class="empty">Sin recorridos entre áreas en este rango.</li>';
    $('#cajasTable').innerHTML = d.checkouts.length ? d.checkouts.map(k => `<tr><td>${esc(k.name)}</td><td class="num">${num(k.people)}</td>
      <td class="num">${pct(k.share)}</td><td class="num">${secs(k.avg_seconds)}</td></tr>`).join('')
      : '<tr><td colspan="4" class="empty">Nadie pasó por caja en este rango.</td></tr>';
    $('#doorsTable').innerHTML = d.doors.length ? d.doors.map(k => `<tr><td>${esc(k.name)}</td><td class="num">${num(k.in)}</td>
      <td class="num">${num(k.out)}</td></tr>`).join('') : '<tr><td colspan="3" class="empty">Sin cruces de puertas.</td></tr>';
    tqPlan.draw($('#heatPlan'), plan, { heat: d.heatmap });
    $('#heatNote').textContent = d.heatmap ? 'Más intenso = más tiempo con gente.' : 'Sin mapa de calor en este rango (hace falta al menos una cámara calibrada).';
    drawCharts(d);
  }

  function drawCharts(d) {
    const th = { grid: cssVar('--grid'), muted: cssVar('--muted'), text: cssVar('--text'), surface: cssVar('--surface'), c1: cssVar('--chart-1') };
    const base = {
      locale: 'es', responsive: true, maintainAspectRatio: false, animation: false,
      interaction: { mode: 'index', intersect: false },
      plugins: { legend: { display: false }, tooltip: { backgroundColor: th.surface, titleColor: th.text, bodyColor: th.text, borderColor: th.grid, borderWidth: 1, padding: 10 } },
      scales: {
        x: { grid: { display: false }, border: { color: th.grid }, ticks: { color: th.muted, maxRotation: 0, autoSkip: true, maxTicksLimit: 12 } },
        y: { beginAtZero: true, grid: { color: th.grid }, border: { display: false }, ticks: { color: th.muted, precision: 0 } },
      },
    };
    $('#seriesTitle').textContent = d.range.unit === 'hour' ? 'Visitas por hora' : 'Visitas por día';
    const sets = {
      chSeries: { type: 'line', data: { labels: d.labels, datasets: [{ label: 'Visitas', data: d.summary.series, borderColor: th.c1,
        backgroundColor: th.c1, borderWidth: 2, pointRadius: d.labels.length > 40 ? 0 : 3, pointBorderColor: th.surface, pointBorderWidth: 2, tension: .25 }] } },
      chHours: { type: 'bar', data: { labels: [...Array(24).keys()].map(h => `${String(h).padStart(2, '0')}h`),
        datasets: [{ label: 'Visitas', data: d.summary.by_hour_of_day, backgroundColor: th.c1, borderRadius: 4, borderSkipped: 'start', maxBarThickness: 22 }] } },
    };
    for (const [id, cfg] of Object.entries(sets)) {
      if (charts[id]) charts[id].destroy();
      charts[id] = new Chart($(`#${id}`), { ...cfg, options: base });
    }
  }

  async function init() {
    const me = await api('/api/me');
    $('#userName').textContent = me.name;
    $('#orgName').textContent = me.org_name || '';
    $('#navManage').hidden = me.role !== 'hq';
    $('#logout').onclick = async () => { await fetch('/api/auth/logout', { method: 'POST' }); location.href = '/login'; };
    document.querySelectorAll('[data-range]').forEach(b => b.addEventListener('click', () => {
      range = b.dataset.range;
      document.querySelectorAll('[data-range]').forEach(x => x.setAttribute('aria-pressed', String(x === b)));
      $('#custom').hidden = range !== 'custom';
      if (range === 'custom' && !$('#start').value) {
        const iso = x => new Date(x - x.getTimezoneOffset() * 60000).toISOString().slice(0, 10), now = new Date();
        $('#end').value = iso(now); $('#start').value = iso(new Date(now - 6 * 86400e3));
      }
      loadReport();
    }));
    $('#start').addEventListener('change', loadReport);
    $('#end').addEventListener('change', loadReport);
    $('#refresh').onclick = loadReport;
    await loadLive();
    loadReport();
    setInterval(loadLive, 3000);
    setInterval(() => { if (range !== 'custom') loadReport(); }, 60000);
    matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => last && renderReport(last));
  }

  init().catch(e => toast(e.message, true));
})();
