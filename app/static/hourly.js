/* Traffiqui Vision · tráfico por hora de cada día (Analítica) */
'use strict';

(() => {
  const $ = (s, r = document) => r.querySelector(s);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const pad2 = n => String(n).padStart(2, '0');
  const slot = h => `${pad2(h)}:00–${pad2(h + 1)}:00`;
  const fmt = v => v === null || v === undefined ? '' : Number.isInteger(v) ? String(v) : v.toLocaleString('es-VE', { maximumFractionDigits: 1 });
  const S = { params: 'range=today', area: 'store', metric: 'people', view: 'days', data: null, req: 0 };
  const WEEK_ORDER = [0, 1, 2, 3, 4, 5, 6]; // lunes primero

  async function load() {
    const id = ++S.req;
    try {
      const r = await fetch(`/api/store/hourly?${S.params}&area=${encodeURIComponent(S.area)}&metric=${S.metric}`);
      const body = await r.json();
      if (!r.ok) throw new Error(body.detail);
      if (id !== S.req) return; // llegó una respuesta más nueva
      S.data = body;
      fillAreas(body);
      render();
    } catch (e) { window.tqToast?.(e.message, true); }
  }

  function fillAreas(d) {
    const sel = $('#hArea');
    const key = d.areas.map(a => a.id).join('|');
    if (sel.dataset.key === key) return;
    sel.dataset.key = key;
    sel.innerHTML = '<option value="store">Toda la tienda</option>' + d.areas.map(a => `<option value="${esc(a.id)}">${esc(a.name)}</option>`).join('');
    sel.value = S.area;
  }

  function render() {
    const d = S.data; if (!d) return;
    const who = S.metric === 'buyers' ? 'personas que pasaron por caja' : 'personas';
    const s = d.selected;
    $('#hPeak').innerHTML = s.peak_hour === null
      ? `Sin ${who} registrados en <b>${esc(d.area_name)}</b> para este rango.`
      : `<b>${esc(d.area_name)}</b> · hora pico <span class="peak-pill">${slot(s.peak_hour)}</span> con <b>${fmt(s.peak_avg)}</b> ${who} por día en promedio
         ${s.top_hours.length > 1 ? `· le siguen ${s.top_hours.slice(1).map(h => `<b>${pad2(h)}h</b>`).join(' y ')}` : ''}
         · ${s.total} ${who} en ${d.n_days} día(s).`;

    // filas: cada día, o el promedio de cada día de la semana
    let rows;
    if (S.view === 'weekday') {
      rows = WEEK_ORDER.map(w => ({ label: d.weekdays[w], counts: s.weekday_avg[w] })).filter(r => r.counts.some(v => v !== null));
    } else {
      rows = d.days.map(x => ({ label: x.label, counts: x.counts })).reverse(); // el día más reciente arriba
    }
    const vals = rows.flatMap(r => r.counts.filter(v => v !== null));
    const max = Math.max(1e-9, ...vals);
    // columnas: de la primera a la última hora con datos (horario de la tienda), mínimo 8:00–20:00
    const used = [...Array(24).keys()].filter(h => rows.some(r => (r.counts[h] || 0) > 0));
    const h0 = Math.min(8, used.length ? used[0] : 8), h1 = Math.max(20, used.length ? used[used.length - 1] : 20);
    const hours = [...Array(h1 - h0 + 1).keys()].map(i => h0 + i);
    const colTot = hours.map(h => rows.reduce((t, r) => t + (r.counts[h] || 0), 0));
    const colMax = Math.max(...colTot);
    const cell = v => {
      if (!v) return '<td class="num cell"></td>';
      const k = v / max;
      return `<td class="num cell" style="background:${window.TQPlan.heatColor(k)};color:${k > 0.55 ? '#fff' : 'inherit'}" title="${fmt(v)} ${who}">${fmt(v)}</td>`;
    };
    $('#hTable').innerHTML = `<thead><tr><th>${S.view === 'weekday' ? 'Día (promedio)' : 'Día'}</th>${hours.map(h => `<th class="num ${h === s.peak_hour ? 'peak' : ''}">${pad2(h)}h</th>`).join('')}<th class="num">Total</th></tr></thead>
      <tbody>${rows.map(r => `<tr><th scope="row">${esc(r.label)}</th>${hours.map(h => cell(r.counts[h])).join('')}
        <td class="num"><b>${fmt(Math.round(r.counts.reduce((t, v) => t + (v || 0), 0) * 10) / 10)}</b></td></tr>`).join('')}</tbody>
      <tfoot><tr><th>${S.view === 'weekday' ? 'Suma' : 'Total'}</th>${hours.map((h, i) => `<td class="num ${colTot[i] === colMax && colMax ? 'peak' : ''}">${fmt(Math.round(colTot[i] * 10) / 10)}</td>`).join('')}<td></td></tr></tfoot>`;

    // hora pico de cada área
    const amax = Math.max(1e-9, ...d.areas.flatMap(a => a.avg_by_hour));
    $('#hPeaks').innerHTML = d.areas.length ? d.areas.map(a => `
      <tr data-harea="${esc(a.id)}" class="${a.id === S.area ? 'sel' : ''}">
        <td>${esc(a.name)}<div class="note">${esc(a.kind)}</div></td>
        <td>${a.peak_hour === null ? '–' : `<span class="peak-pill">${slot(a.peak_hour)}</span>`}</td>
        <td class="num"><b>${fmt(a.peak_avg)}</b></td>
        <td>${a.top_hours.slice(1).map(h => `${pad2(h)}h`).join(', ') || '–'}</td>
        <td class="num">${a.total}</td>
        <td><div class="spark" aria-label="Perfil por hora">${a.avg_by_hour.map((v, h) =>
          `<i style="height:${Math.round(100 * v / amax)}%" class="${h === a.peak_hour ? 'pk' : ''}" title="${pad2(h)}h · ${fmt(v)} por día"></i>`).join('')}</div></td>
      </tr>`).join('') : '<tr><td colspan="6" class="empty">Dibuja áreas en el Plano (pasillos, cajas…) y calibra una cámara para ver su hora pico.</td></tr>';
    $('#hPeaks').querySelectorAll('[data-harea]').forEach(tr => tr.addEventListener('click', () => {
      S.area = tr.dataset.harea; $('#hArea').value = S.area; load();
      $('#hourlyCard').scrollIntoView({ behavior: 'smooth', block: 'start' });
    }));
  }

  function init() {
    if ($('#hourlyCard').dataset.ready) return;
    $('#hourlyCard').dataset.ready = '1';
    $('#hArea').addEventListener('change', e => { S.area = e.target.value; load(); });
    document.querySelectorAll('[data-hmetric]').forEach(b => b.addEventListener('click', () => {
      S.metric = b.dataset.hmetric;
      document.querySelectorAll('[data-hmetric]').forEach(x => x.setAttribute('aria-pressed', String(x === b)));
      load();
    }));
    document.querySelectorAll('[data-hview]').forEach(b => b.addEventListener('click', () => {
      S.view = b.dataset.hview;
      document.querySelectorAll('[data-hview]').forEach(x => x.setAttribute('aria-pressed', String(x === b)));
      render();
    }));
  }

  // usa el mismo rango que el resto de la pestaña Analítica
  document.addEventListener('tq:analytics-range', ev => { init(); S.params = ev.detail.params; load(); });
})();
