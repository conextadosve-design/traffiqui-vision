/* Traffiqui · sede principal: sedes, licencia y usuarios */
'use strict';

(() => {
  const $ = (s, r = document) => r.querySelector(s);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  let data = null;

  let toastTimer;
  function toast(msg, isError) {
    const t = $('#toast');
    t.textContent = msg; t.hidden = false; t.className = `toast show${isError ? ' err' : ''}`;
    clearTimeout(toastTimer); toastTimer = setTimeout(() => { t.className = 'toast'; }, 5000);
  }

  async function api(path, method = 'GET', body) {
    const r = await fetch(path, body === undefined ? { method } :
      { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    if (r.status === 401) { location.href = '/login'; throw new Error('Sesión cerrada.'); }
    const out = await r.json();
    if (!r.ok) throw new Error(out.detail || `Error ${r.status} del servidor.`);
    return out;
  }

  function ago(ts) {
    if (!ts) return 'todavía no se ha conectado';
    const s = Math.max(0, Math.round(Date.now() / 1000 - ts));
    if (s < 3600) return `último envío hace ${Math.max(1, Math.round(s / 60))} min`;
    if (s < 86400) return `último envío hace ${Math.round(s / 3600)} h`;
    return `último envío el ${new Date(ts * 1000).toLocaleDateString('es')}`;
  }

  function showKey(name, key) {
    $('#keyTitle').textContent = `Clave de «${name}»`;
    $('#keyValue').textContent = key;
    $('#keyBox').hidden = false;
    $('#keyBox').scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  function render() {
    const d = data, lic = d.org.license;
    $('#orgName').textContent = d.org.name;
    const active = d.sites.filter(s => s.status === 'active').length;
    $('#licenseSummary').textContent = `${active} de ${lic.sites_allowed} activas`;

    $('#addresses').innerHTML = d.addresses.length ? d.addresses.map(a => `
      <div class="addr ${a.kind}"><code>${esc(a.url)}</code>
        <span class="note">${a.kind === 'tailscale' ? 'Tailscale · úsala en las tiendas' : 'red local · solo tiendas en esta misma red'}</span></div>`).join('')
      : '<p class="note">No se encontró ninguna dirección de red.</p>';
    if (!d.addresses.some(a => a.kind === 'tailscale')) {
      $('#addresses').insertAdjacentHTML('beforeend',
        '<p class="note warn">Tailscale no está activo en este PC: las tiendas de otras ubicaciones no podrán conectarse.</p>');
    }

    $('#sitesList').innerHTML = d.sites.length ? d.sites.map(s => {
      const state = s.status === 'suspended' ? ['bad', 'Suspendida']
        : s.status === 'pending' ? ['bad', 'Pendiente']
        : s.over_license ? ['bad', 'Fuera de la licencia']
        : s.online ? ['ok', 'En línea'] : ['', 'Sin conexión'];
      const actions = [
        `<button class="btn small" data-key="${s.id}">Nueva clave</button>`,
        s.status === 'active' ? `<button class="btn small danger" data-suspend="${s.id}">Suspender</button>`
          : `<button class="btn small" data-activate="${s.id}">Reactivar</button>`,
      ].join(' ');
      return `<tr><td class="site-name">${esc(s.name)}<div class="note">${ago(s.last_sync_at)}</div></td>
        <td><span class="state ${state[0]}">${state[1]}</span></td>
        <td>${s.key_hint ? `<code>…${esc(s.key_hint)}</code>` : '–'}</td><td class="num nowrap">${actions}</td></tr>`;
    }).join('') : '<tr><td colspan="4" class="empty">Todavía no hay sedes. Agrega la primera aquí abajo.</td></tr>';

    $('#licenseText').innerHTML = lic.code && !lic.error
      ? `Tu licencia permite <b>${lic.sites_allowed} sede${lic.sites_allowed > 1 ? 's' : ''}</b>${lic.expires ? `, hasta el ${esc(lic.expires)}` : ''}.`
      : `Sin licencia puedes tener <b>${lic.free_sites} sede</b>.${lic.error ? ` <span class="warn">${esc(lic.error)}</span>` : ''}`;
    $('#licenseHelp').textContent = `Para agregar sedes, contacta con ${lic.contact}: te enviará un código para pegar aquí.`;

    $('#usersList').innerHTML = d.users.map(u => {
      const site = d.sites.find(s => s.id === u.site_id);
      const sees = u.role === 'hq' ? 'Todas las sedes' : `Solo ${esc(site?.name || 'una sede')}`;
      const btn = u.id === d.me ? '<span class="note">tú</span>'
        : `<button class="btn small${u.active ? ' danger' : ''}" data-user="${u.id}" data-active="${u.active ? 0 : 1}">${u.active ? 'Desactivar' : 'Activar'}</button>`;
      return `<tr><td>${esc(u.name)}</td><td>${esc(u.email)}</td><td>${sees}</td>
        <td><span class="state ${u.active ? 'ok' : ''}">${u.active ? 'Activo' : 'Desactivado'}</span></td><td class="num">${btn}</td></tr>`;
    }).join('');
    $('#uSite').innerHTML = d.sites.map(s => `<option value="${s.id}">${esc(s.name)}</option>`).join('');
  }

  async function load() {
    try { data = await api('/api/manage'); render(); }
    catch (e) { toast(e.message, true); }
  }

  async function act(fn, okMsg) {
    try { const out = await fn(); if (okMsg) toast(okMsg); await load(); return out; }
    catch (e) { toast(e.message, true); }
  }

  async function init() {
    const me = await api('/api/me');
    $('#userName').textContent = me.name;
    if (me.role !== 'hq') { location.href = '/'; return; }
    $('#logout').onclick = async () => { await fetch('/api/auth/logout', { method: 'POST' }); location.href = '/login'; };

    $('#siteForm').addEventListener('submit', async ev => {
      ev.preventDefault();
      const out = await act(() => api('/api/manage/sites', 'POST', { name: $('#siteName').value }), 'Sede creada.');
      if (out) { $('#siteName').value = ''; showKey(out.name, out.key); }
    });
    $('#sitesList').addEventListener('click', async ev => {
      const b = ev.target.closest('button'); if (!b) return;
      const site = data.sites.find(s => String(s.id) === (b.dataset.key || b.dataset.suspend || b.dataset.activate));
      if (b.dataset.key) {
        if (!confirm(`¿Generar una clave nueva para «${site.name}»? La actual deja de funcionar y habrá que pegar la nueva en esa tienda.`)) return;
        const out = await act(() => api(`/api/manage/sites/${site.id}/key`, 'POST'));
        if (out) showKey(site.name, out.key);
      } else if (b.dataset.suspend) {
        if (!confirm(`¿Suspender «${site.name}»? Dejará de recibir sus datos hasta que la reactives.`)) return;
        act(() => api(`/api/manage/sites/${site.id}/suspend`, 'POST'), 'Sede suspendida.');
      } else if (b.dataset.activate) {
        act(() => api(`/api/manage/sites/${site.id}/activate`, 'POST'), 'Sede reactivada.');
      }
    });
    $('#keyCopy').onclick = async () => {
      try { await navigator.clipboard.writeText($('#keyValue').textContent); toast('Clave copiada.'); }
      catch { toast('Selecciona la clave y cópiala con Ctrl+C.', true); }
    };
    $('#licenseForm').addEventListener('submit', async ev => {
      ev.preventDefault();
      const out = await act(() => api('/api/manage/license', 'POST', { code: $('#licenseCode').value }));
      if (out) { $('#licenseCode').value = ''; toast(`Licencia guardada: ${out.sites_allowed} sedes.`); }
    });
    $('#uRole').onchange = () => { $('#uSite').hidden = $('#uRole').value !== 'site'; };
    $('#userForm').addEventListener('submit', async ev => {
      ev.preventDefault();
      const body = { name: $('#uName').value, email: $('#uEmail').value, password: $('#uPass').value,
                     role: $('#uRole').value, site_id: Number($('#uSite').value) || null };
      const out = await act(() => api('/api/manage/users', 'POST', body), 'Usuario creado.');
      if (out) $('#userForm').reset();
    });
    $('#usersList').addEventListener('click', ev => {
      const b = ev.target.closest('button[data-user]'); if (!b) return;
      act(() => api(`/api/manage/users/${b.dataset.user}/active`, 'POST', { active: b.dataset.active === '1' }));
    });
    load();
    setInterval(load, 30000);
  }

  init().catch(e => toast(e.message, true));
})();
