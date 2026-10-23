/* Traffiqui Vision · conexión con la sede principal (servidor central) */
'use strict';

(() => {
  const $ = (s, r = document) => r.querySelector(s);
  const toast = (m, e) => window.tqToast?.(m, e);

  async function api(path, opts = {}) {
    const r = await fetch(path, opts);
    const body = (r.headers.get('content-type') || '').includes('json') ? await r.json() : null;
    if (!r.ok) throw new Error(body?.detail || `Error ${r.status} del servidor.`);
    return body;
  }
  const json = (method, body) => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

  function ago(ts) {
    const s = Math.max(0, Math.round(Date.now() / 1000 - ts));
    if (s < 60) return `hace ${s} s`;
    if (s < 3600) return `hace ${Math.round(s / 60)} min`;
    return `el ${new Date(ts * 1000).toLocaleString('es')}`;
  }

  function render(st) {
    const pill = $('#cloudPill');
    const [cls, text] = !st.configured ? ['', 'Sin conectar']
      : st.state === 'ok' ? ['ok', 'Conectada']
      : st.state === 'blocked' ? ['bad', 'Bloqueada']
      : st.state === 'error' ? ['bad', 'Sin conexión']
      : ['warn', 'Conectando…'];
    pill.className = `pill ${cls}`;
    pill.textContent = text;
    const where = st.site ? `${st.site} · ${st.org}` : '';
    const last = st.last_ok ? `Último envío ${ago(st.last_ok)}.` : '';
    $('#cloudInfo').textContent = [where, st.message || last].filter(Boolean).join(' — ');
    if (st.configured && document.activeElement !== $('#cloudUrl')) $('#cloudUrl').value = st.url;
    $('#cloudKey').placeholder = st.key_hint ? `Clave guardada (${st.key_hint})` : 'tqs_…';
    $('#cloudConnect').textContent = st.configured ? 'Cambiar clave' : 'Conectar';
    $('#cloudSync').hidden = !st.configured;
    $('#cloudOff').hidden = !st.configured;
  }

  async function load() {
    try { render(await api('/api/cloud')); } catch (e) { $('#cloudInfo').textContent = e.message; }
  }

  function init() {
    if ($('#cloudCard').dataset.ready) return;
    $('#cloudCard').dataset.ready = '1';
    $('#cloudForm').addEventListener('submit', async ev => {
      ev.preventDefault();
      const btn = $('#cloudConnect');
      btn.disabled = true;
      try {
        render(await api('/api/cloud', json('PUT', { url: $('#cloudUrl').value, site_key: $('#cloudKey').value })));
        $('#cloudKey').value = '';
        toast('Tienda conectada con la sede principal.');
      } catch (e) { toast(e.message, true); }
      finally { btn.disabled = false; }
    });
    $('#cloudSync').onclick = async () => {
      try { await api('/api/cloud/sync', { method: 'POST' }); toast('Enviando…'); setTimeout(load, 2500); }
      catch (e) { toast(e.message, true); }
    };
    $('#cloudOff').onclick = async () => {
      if (!confirm('¿Desconectar esta tienda de la sede principal? Dejará de enviar datos hasta que la vuelvas a conectar.')) return;
      try { render(await api('/api/cloud', { method: 'DELETE' })); $('#cloudUrl').value = ''; }
      catch (e) { toast(e.message, true); }
    };
    setInterval(() => { if (!$('#view-settings').hidden) load(); }, 10000);
  }

  document.addEventListener('tq:view', ev => { if (ev.detail === 'settings') { init(); load(); } });
})();
