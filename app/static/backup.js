/* Traffiqui · copias de seguridad (la misma tarjeta en la tienda y en la sede principal) */
'use strict';

(() => {
  const $ = (s, r = document) => r.querySelector(s);
  const card = $('#backupCard');
  if (!card) return;
  const base = card.dataset.api || '/api/backup';
  const toast = (m, e) => (window.tqToast ? window.tqToast(m, e) : alert(m));

  async function api(path, opts = {}) {
    const r = await fetch(path, opts);
    const body = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(body.detail || `Error ${r.status} del servidor.`);
    return body;
  }
  const size = b => b > 1e6 ? `${(b / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1e3))} KB`;

  function render(st) {
    const last = st.copies[0];
    const when = st.last_ok ? new Date(st.last_ok * 1000).toLocaleString('es') : null;
    $('#backupInfo', card).textContent = st.last_error ? `Error: ${st.last_error}`
      : last ? `${when || last.date} · ${size(last.size)} · ${st.copies.length} copias guardadas en ${st.dir}`
      : 'Todavía no hay copias: la primera se hace unos minutos después de abrir Traffiqui.';
    $('#backupInfo', card).classList.toggle('warn', !!st.last_error);
    if (document.activeElement !== $('#backupExtra', card)) $('#backupExtra', card).value = st.extra_dir || '';
  }

  async function load() {
    try { render(await api(base)); } catch (e) { $('#backupInfo', card).textContent = e.message; }
  }

  $('#backupForm', card).addEventListener('submit', async ev => {
    ev.preventDefault();
    try {
      render(await api(base, { method: 'PUT', headers: { 'Content-Type': 'application/json' },
                               body: JSON.stringify({ extra_dir: $('#backupExtra', card).value }) }));
      toast('Carpeta guardada.');
    } catch (e) { toast(e.message, true); }
  });
  $('#backupNow', card).onclick = async ev => {
    ev.target.disabled = true;
    try { render(await api(`${base}/now`, { method: 'POST' })); toast('Copia hecha.'); }
    catch (e) { toast(e.message, true); }
    finally { ev.target.disabled = false; }
  };
  load();
  document.addEventListener('tq:view', ev => { if (ev.detail === 'settings') load(); });
})();
