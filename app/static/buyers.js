/* Traffiqui Vision · pasaron por caja vs. no pasaron */
'use strict';

(() => {
  const $ = (s, r = document) => r.querySelector(s);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const cssVar = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const pad2 = n => String(n).padStart(2, '0');
  const hhmm = ts => { const d = new Date(ts * 1000); return `${pad2(d.getHours())}:${pad2(d.getMinutes())}`; };
  const pct = v => `${Math.round((v || 0) * 100)} %`;
  const secs = s => !s ? '–' : s >= 60 ? `${Math.floor(s / 60)} min ${Math.round(s % 60)} s` : `${Math.round(s)} s`;
  let range = 'today';
  let last = null;
  const charts = {};

  function params() {
    const p = new URLSearchParams({ range });
    if (range === 'custom') { p.set('start', $('#bStart').value); p.set('end', $('#bEnd').value); }
    return p.toString();
  }

  async function load() {
    try {
      const r = await fetch(`/api/store/buyers?${params()}`);
      const body = await r.json();
      if (!r.ok) throw new Error(body.detail);
      last = body;
      render(body);
    } catch (e) { window.tqToast?.(e.message, true); }
  }

  function render(d) {
    const g = d.groups;
    $('#bNoCheckout').hidden = d.has_checkout;
    $('#bSecs').textContent = d.buyer_seconds;
    $('#bConv').textContent = g.total.count ? pct(d.conversion) : '–';
    $('#bConvSub').textContent = `${g.buyers.count} de ${g.total.count} personas pasaron ≥ ${d.buyer_seconds} s por caja`;
    $('#bBuy').textContent = g.buyers.count;
    $('#bBuySub').textContent = `${pct(g.buyers.share)} del total · ${secs(g.buyers.avg_dwell)} en tienda`;
    $('#bNon').textContent = g.non_buyers.count;
    $('#bNonSub').textContent = `${pct(g.non_buyers.share)} del total · ${secs(g.non_buyers.avg_dwell)} en tienda`;
    $('#bTot').textContent = g.total.count;
    $('#bTotSub').textContent = `Entradas por puertas: ${d.entries} · salidas: ${d.exits}`;

    const rows = [
      ['Personas', x => x.count],
      ['% del total', x => pct(x.share)],
      ['Permanencia promedio en la tienda', x => secs(x.avg_dwell)],
      ['Permanencia mediana', x => secs(x.median_dwell)],
      ['Áreas visitadas (promedio)', x => x.avg_areas || '–'],
      ['Se detuvieron en algún área', x => pct(x.stop_rate)],
      ['Tiempo promedio en cajas', x => secs(x.avg_checkout)],
      ['Todavía en la tienda', x => x.in_progress],
    ];
    $('#bTable').innerHTML = rows.map(([label, f]) =>
      `<tr><td>${label}</td><td class="num">${f(g.buyers)}</td><td class="num">${f(g.non_buyers)}</td><td class="num"><b>${f(g.total)}</b></td></tr>`).join('');

    $('#bAreas').innerHTML = d.areas.length ? d.areas.map(a => {
      const diff = a.buyers_pct - a.non_buyers_pct;
      return `<tr><td>${esc(a.name)}<div class="note">${esc(a.kind)}</div></td>
        <td class="num"><div class="bar-cell"><span style="width:${Math.round(60 * a.buyers_pct)}px"></span>${pct(a.buyers_pct)} <small>(${a.buyers})</small></div></td>
        <td class="num"><div class="bar-cell"><span class="alt" style="width:${Math.round(60 * a.non_buyers_pct)}px"></span>${pct(a.non_buyers_pct)} <small>(${a.non_buyers})</small></div></td>
        <td class="num">${diff > 0 ? '+' : ''}${Math.round(diff * 100)} pts</td></tr>`;
    }).join('') : '<tr><td colspan="4" class="empty">Dibuja áreas en el Plano para ver qué pasillos recorre cada grupo.</td></tr>';

    const live = {};
    for (const a of (window.tqLastMetrics?.store?.areas || [])) if (a.kind === 'caja') live[a.id] = a.inside;
    $('#bCheckouts').innerHTML = d.checkouts.length ? d.checkouts.map(c => `<tr><td>${esc(c.name)}</td>
        <td class="num">${live[c.id] ?? '–'}</td><td class="num">${c.people}</td><td class="num"><b>${c.buyers}</b></td>
        <td class="num"><div class="bar-cell"><span style="width:${Math.round(60 * c.share)}px"></span>${pct(c.share)}</div></td>
        <td class="num">${secs(c.avg_seconds)}</td></tr>`).join('')
      : '<tr><td colspan="6" class="empty">No hay cajas en el plano. Usa la herramienta "Caja": crea sola la zona donde se para el cliente.</td></tr>';
    $('#bStaff').textContent = d.staff.count;
    $('#bStaffWhy').innerHTML = Object.entries(d.staff.by_reason).map(([k, n]) => `<li><span>${esc(k)}</span><b>${n}</b></li>`).join('');
    $('#bStaffNote').textContent = d.staff.count
      ? 'Se detectan por pasar más del tiempo configurado en el sistema o por estar en una zona de personal (detrás de la caja o del mostrador).'
      : 'Nadie fue marcado como personal en este rango.';

    $('#bDoors').innerHTML = d.doors.length
      ? d.doors.map(x => `<tr><td>${esc(x.name)}</td><td class="num">${x.in}</td><td class="num">${x.out}</td></tr>`).join('')
      : '<tr><td colspan="3" class="empty">Sin cruces de puertas. Marca la entrada (y la salida, si es otra) en el Plano y calibra la cámara que las ve.</td></tr>';
    drawCharts(d);
  }

  function drawCharts(d) {
    const th = { c1: cssVar('--chart-1'), c2: cssVar('--chart-2'), grid: cssVar('--grid'), muted: cssVar('--muted'),
                 text: cssVar('--text'), surface: cssVar('--surface') };
    const base = {
      responsive: true, maintainAspectRatio: false, animation: false,
      interaction: { mode: 'index', intersect: false },
      plugins: { legend: { display: false }, tooltip: { backgroundColor: th.surface, titleColor: th.text, bodyColor: th.text, borderColor: th.grid, borderWidth: 1, padding: 10 } },
      scales: {
        x: { grid: { display: false }, border: { color: th.grid }, ticks: { color: th.muted, maxRotation: 0, autoSkip: true, maxTicksLimit: 12 } },
        y: { beginAtZero: true, grid: { color: th.grid }, border: { display: false }, ticks: { color: th.muted, precision: 0 } },
      },
    };
    const bar = (label, data, color) => ({ label, data, backgroundColor: color, borderRadius: 4, borderSkipped: 'start', maxBarThickness: 26 });
    // en "Hoy" se omiten las horas vacías antes del primer dato
    let hours = d.by_hour;
    const first = hours.findIndex(h => h.buyers || h.non_buyers || h.entries || h.exits);
    if (range === 'today' && first > 0) hours = hours.slice(Math.max(0, first - 1));
    // en semana / mes se muestra por día (por hora serían cientos de barras)
    const long = d.range.end - d.range.start > 36 * 3600;
    const series = long ? d.by_day.map(x => ({ label: x.label, buyers: x.buyers, non_buyers: x.non_buyers }))
      : hours.map(h => ({ label: hhmm(h.t), buyers: h.buyers, non_buyers: h.non_buyers }));
    $('#bHourTitle').textContent = long ? 'Pasaron y no pasaron por caja, por día' : 'Pasaron y no pasaron por caja, por hora';
    const sets = {
      chBuyHour: { labels: series.map(s => s.label), datasets: [bar('Pasaron por caja', series.map(s => s.buyers), th.c1), bar('No pasaron', series.map(s => s.non_buyers), th.c2)] },
      chBuyDwell: { labels: Object.keys(d.groups.total.dwell_buckets), datasets: [
        bar('Pasaron por caja', Object.values(d.groups.buyers.dwell_buckets), th.c1),
        bar('No pasaron', Object.values(d.groups.non_buyers.dwell_buckets), th.c2)] },
    };
    for (const [id, data] of Object.entries(sets)) {
      if (charts[id]) { charts[id].data = data; charts[id].options = base; charts[id].update(); }
      else charts[id] = new Chart($(`#${id}`), { type: 'bar', data, options: base });
    }
  }

  function renderLive(m) {
    const people = (m.store?.people || []).filter(p => p.confirmed);
    const status = p => p.staff ? ['staff', 'Personal'] : p.buyer ? ['ok', 'Pasó por caja'] : p.checkout_s > 0 ? ['', `En caja ${Math.round(p.checkout_s)} s`] : ['', 'Transitando'];
    $('#bLive').innerHTML = people.length ? people.map(p => { const [cls, txt] = status(p); return `
      <span class="chip"><span class="dot" style="background:${esc(p.color)}"></span>ID ${p.gid}
        <span class="badge ${cls}">${txt}</span></span>`; }).join('')
      : '<span class="empty">Nadie en la tienda.</span>';
  }

  function init() {
    if ($('#view-buyers').dataset.ready) return;
    $('#view-buyers').dataset.ready = '1';
    document.querySelectorAll('[data-brange]').forEach(b => b.addEventListener('click', () => {
      range = b.dataset.brange;
      document.querySelectorAll('[data-brange]').forEach(x => x.setAttribute('aria-pressed', String(x === b)));
      $('#bCustom').hidden = range !== 'custom';
      if (range === 'custom' && !$('#bStart').value) {
        const local = x => new Date(x - x.getTimezoneOffset() * 60000).toISOString().slice(0, 16), now = new Date();
        $('#bEnd').value = local(now); $('#bStart').value = local(new Date(now - 3 * 3600e3));
      }
      load();
    }));
    $('#bStart').addEventListener('change', load);
    $('#bEnd').addEventListener('change', load);
    $('#bRefresh').onclick = load;
    $('#bCsv').onclick = () => { location.href = `/api/analytics/export.csv?${params()}`; };
    setInterval(() => { if (!$('#view-buyers').hidden && range !== 'custom') load(); }, 30000);
    matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => last && drawCharts(last));
  }

  document.addEventListener('tq:view', ev => { if (ev.detail === 'buyers') { init(); load(); } });
  document.addEventListener('tq:metrics', ev => { if (!$('#view-buyers').hidden) renderLive(ev.detail); });
})();
