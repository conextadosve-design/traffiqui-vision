/* Traffiqui Cloud · panel consolidado de la sede principal */
'use strict';

(() => {
  const $ = (s, r = document) => r.querySelector(s);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const cssVar = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const pct = x => `${Math.round((x || 0) * 100)} %`;
  const num = x => (x ?? 0).toLocaleString('es');
  const slot = h => h === null || h === undefined ? '–' : `${String(h).padStart(2, '0')}–${String((h + 1) % 24).padStart(2, '0')} h`;
  const MAX_LINES = 6;   // más sedes: las 5 con más visitas + "Otras"
  let range = 'today', me = null, orgId = null, last = null;
  const charts = {};

  function secs(s) {
    if (s === null || s === undefined) return '–';
    s = Math.round(s);
    return s < 60 ? `${s} s` : `${Math.floor(s / 60)} min ${String(s % 60).padStart(2, '0')} s`;
  }

  function ago(ts) {
    if (!ts) return 'nunca';
    const s = Math.max(0, Math.round(Date.now() / 1000 - ts));
    if (s < 90) return 'hace 1 min';
    if (s < 3600) return `hace ${Math.round(s / 60)} min`;
    if (s < 86400) return `hace ${Math.round(s / 3600)} h`;
    return `el ${new Date(ts * 1000).toLocaleDateString('es')}`;
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

  function params() {
    const p = new URLSearchParams({ range });
    if (range === 'custom') { p.set('start', $('#start').value); p.set('end', $('#end').value); }
    if (me.role === 'admin') p.set('org_id', orgId);
    return p;
  }

  async function load() {
    if (me.role === 'admin' && !orgId) return;
    if (range === 'custom' && (!$('#start').value || !$('#end').value)) return;
    try {
      last = await api(`/api/report?${params()}`);
      render(last);
      $('#updated').textContent = `Actualizado ${new Date().toLocaleTimeString('es', { hour: '2-digit', minute: '2-digit' })}`;
    } catch (e) { toast(e.message, true); }
  }

  // ---- colores: siguen a la sede (orden por id), no a su posición en el ranking -----------
  function colorMap(sites) {   // solo las sedes con línea propia (máximo 6 colores, sin repetir)
    const ids = sites.map(s => s.id).sort((a, b) => a - b);
    return Object.fromEntries(ids.map((id, i) => [id, i]));
  }

  /** "▲ 12 %" / "▼ 3 %" / "–" */
  function delta(v, unit = '%') {
    if (v === null || v === undefined) return '<span class="delta">–</span>';
    const cls = v > 0 ? 'up' : v < 0 ? 'down' : '';
    return `<span class="delta ${cls}">${v > 0 ? '▲' : v < 0 ? '▼' : '='} ${Math.abs(v).toLocaleString('es')} ${unit}</span>`;
  }
  const cmpLine = (c, key, unit) => c ? `${delta(c.week?.[key], unit)} vs semana ant. · ${delta(c.month?.[key], unit)} vs mes pasado` : '';

  async function loadAlerts() {
    try {
      const d = await api('/api/alerts');
      const items = d.alerts;
      $('#alertsCard').hidden = !items.length;
      $('#alertsCount').textContent = items.length ? `(${items.length})` : '';
      $('#alertsList').innerHTML = items.map(a => `<li><b><a href="/sede/${a.site_id}">${esc(a.site)}</a> · ${esc(a.message)}</b>
        <span class="note">desde ${ago(a.started_at)}${a.ack_by ? ` · vista por ${esc(a.ack_by)}` : ` · <button class="btn small" data-ack="${a.id}">Marcar como vista</button>`}</span></li>`).join('');
    } catch (e) { /* el resumen sigue funcionando */ }
  }

  function render(d) {
    const t = d.totals;
    $('#orgName').textContent = d.org.name;
    $('#tVisits').textContent = num(t.visits);
    $('#tVisitsSub').textContent = `${num(t.entries)} entradas por puertas`;
    $('#tCheckout').textContent = num(t.checkout);
    $('#tCheckoutSub').textContent = `${pct(t.checkout_rate)} de las visitas`;
    $('#tVisitsCmp').innerHTML = cmpLine(d.compare, 'visits');
    $('#tCheckoutCmp').innerHTML = cmpLine(d.compare, 'checkout');
    $('#tDwellCmp').innerHTML = cmpLine(d.compare, 'avg_dwell');
    $('#tDwell').textContent = secs(t.avg_dwell);
    $('#tPeak').textContent = slot(t.peak_hour);
    $('#tOnline').textContent = `${t.sites_online} de ${t.sites_active}`;
    $('#tOnlineSub').textContent = [t.sites_online === t.sites_active ? 'todas enviando datos' : 'revisa las que no envían',
      t.sites_pending ? `${t.sites_pending} pendiente${t.sites_pending > 1 ? 's' : ''} de pago` : ''].filter(Boolean).join(' · ');

    const cmap = colorMap(lineSites(d));
    $('#sitesTable').innerHTML = d.sites.length ? d.sites.map(s => {
      const state = s.status !== 'active' ? ['bad', s.status === 'pending' ? 'Pendiente de pago' : 'Suspendida']
        : s.online ? ['ok', 'En línea'] : ['bad', 'Sin conexión'];
      const since = s.status === 'active' && !s.online ? ` <small>· ${ago(s.last_sync_at)}</small>` : '';
      const sw = s.id in cmap ? `<span class="swatch" style="background:var(--series-${cmap[s.id] + 1})"></span>` : '';
      return `<tr>
        <td class="site-name">${sw}<a href="/sede/${s.id}">${esc(s.name)}</a></td>
        <td><span class="state ${state[0]}">${state[1]}${since}</span></td>
        <td class="num"><b>${num(s.visits)}</b></td><td class="num">${delta(s.compare?.week?.visits)}</td>
        <td class="num">${delta(s.compare?.month?.visits)}</td><td class="num">${num(s.checkout)}</td>
        <td class="num">${s.visits ? pct(s.checkout_rate) : '–'}</td><td class="num">${secs(s.avg_dwell)}</td>
        <td class="num">${slot(s.peak_hour)}</td><td class="num">${num(s.entries)}</td><td class="num">${num(s.max_occupancy)}</td></tr>`;
    }).join('') : '<tr><td colspan="11" class="empty">Todavía no hay sedes. Créalas en <a href="/sedes">Sedes y usuarios</a>.</td></tr>';
    drawCharts(d, cmap);
  }

  const active = d => d.sites.filter(s => s.status === 'active');   // solo las activas tienen línea

  function lineSites(d) {
    const sites = active(d);
    if (sites.length <= MAX_LINES) return sites;
    return [...sites].sort((a, b) => b.visits - a.visits).slice(0, MAX_LINES - 1);
  }

  function drawCharts(d, cmap) {
    const th = { grid: cssVar('--grid'), muted: cssVar('--muted'), text: cssVar('--text'), surface: cssVar('--surface'),
                 c1: cssVar('--chart-1') };
    const base = {
      locale: 'es', responsive: true, maintainAspectRatio: false, animation: false,
      interaction: { mode: 'index', intersect: false },
      plugins: { legend: { display: false }, tooltip: { backgroundColor: th.surface, titleColor: th.text, bodyColor: th.text,
        borderColor: th.grid, borderWidth: 1, padding: 10, usePointStyle: true } },
      scales: {
        x: { grid: { display: false }, border: { color: th.grid }, ticks: { color: th.muted, maxRotation: 0, autoSkip: true, maxTicksLimit: 12 } },
        y: { beginAtZero: true, grid: { color: th.grid }, border: { display: false }, ticks: { color: th.muted, precision: 0 } },
      },
    };

    const lines = lineSites(d);
    const series = lines.map(s => ({ label: s.name, data: s.series, color: cssVar(`--series-${cmap[s.id] + 1}`) }));
    if (active(d).length > MAX_LINES) {
      const others = active(d).filter(s => !lines.includes(s));
      series.push({ label: `Otras ${others.length} sedes`, color: th.muted,
                    data: d.labels.map((_, i) => others.reduce((a, s) => a + s.series[i], 0)) });
    }
    $('#seriesTitle').textContent = d.range.unit === 'hour' ? 'Visitas por hora y sede' : 'Visitas por día y sede';
    $('#seriesLegend').innerHTML = series.length > 1
      ? series.map(s => `<span><i style="background:${s.color}"></i>${esc(s.label)}</span>`).join('') : '';
    const sets = {
      chSeries: { type: 'line', data: { labels: d.labels, datasets: series.map(s => ({
        label: s.label, data: s.data, borderColor: s.color, backgroundColor: s.color, borderWidth: 2,
        pointRadius: d.labels.length > 40 ? 0 : 3, pointHoverRadius: 5, pointBorderColor: th.surface, pointBorderWidth: 2,
        tension: .25 })) } },
      chHours: { type: 'bar', data: { labels: [...Array(24).keys()].map(h => `${String(h).padStart(2, '0')}h`),
        datasets: [{ label: 'Visitas', data: d.totals.by_hour_of_day, backgroundColor: th.c1, borderRadius: 4,
                     borderSkipped: 'start', maxBarThickness: 22 }] } },
    };
    for (const [id, cfg] of Object.entries(sets)) {
      if (charts[id]) charts[id].destroy();
      charts[id] = new Chart($(`#${id}`), { ...cfg, options: base });
    }
  }

  async function init() {
    me = await api('/api/me');
    $('#userName').textContent = me.name;
    $('#nav').hidden = me.role !== 'hq';
    if (me.role === 'admin') {
      const sel = $('#orgSelect');
      sel.hidden = false;
      sel.innerHTML = me.orgs.map(o => `<option value="${o.id}">${esc(o.name)}</option>`).join('');
      orgId = me.orgs[0]?.id ?? null;
      sel.onchange = () => { orgId = Number(sel.value); load(); };
      if (!orgId) $('#sitesTable').innerHTML = '<tr><td colspan="11" class="empty">Todavía no hay empresas.</td></tr>';
    }
    document.querySelectorAll('[data-range]').forEach(b => b.addEventListener('click', () => {
      range = b.dataset.range;
      document.querySelectorAll('[data-range]').forEach(x => x.setAttribute('aria-pressed', String(x === b)));
      $('#custom').hidden = range !== 'custom';
      if (range === 'custom' && !$('#start').value) {
        const iso = x => new Date(x - x.getTimezoneOffset() * 60000).toISOString().slice(0, 10), now = new Date();
        $('#end').value = iso(now); $('#start').value = iso(new Date(now - 6 * 86400e3));
      }
      load();
    }));
    $('#start').addEventListener('change', load);
    $('#end').addEventListener('change', load);
    $('#refresh').onclick = load;
    $('#logout').onclick = async () => { await fetch('/api/auth/logout', { method: 'POST' }); location.href = '/login'; };
    setInterval(() => { if (range !== 'custom') load(); }, 60000);
    $('#alertsList').addEventListener('click', async ev => {
      const b = ev.target.closest('[data-ack]'); if (!b) return;
      try { await api(`/api/alerts/${b.dataset.ack}/ack`, { method: 'POST' }); loadAlerts(); } catch (e) { toast(e.message, true); }
    });
    loadAlerts();
    setInterval(loadAlerts, 20000);
    matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => last && render(last));
    load();
  }

  init().catch(e => toast(e.message, true));
})();
