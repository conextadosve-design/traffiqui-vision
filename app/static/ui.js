/* Traffiqui · piezas de interfaz comunes a la tienda y a la sede principal (/vendor/ui.js, sin build):
   - iconos: <svg class="i"><use href="#i-casa"/></svg> (el sprite se inserta al cargar)
   - subpestañas: botones .subtab[data-target] que muestran las tarjetas [data-group] de su grupo
   - tutorial de bienvenida: TQ.tour(clave, pasos) la primera vez; TQ.tour.open(...) desde el botón de ayuda */
'use strict';
(function () {
  const P = {
    vivo: 'M3 12h4l3-8 4 16 3-8h4',
    informes: 'M4 20V11M10 20V5M16 20v-8M21 20H3',
    caja: 'M3 4h2l2.4 11.2a1 1 0 0 0 1 .8h9.2a1 1 0 0 0 1-.8L20 8H6.2M9 20.5h.01M17 20.5h.01',
    cubo: 'M12 2.5l8.5 4.8v9.4L12 21.5l-8.5-4.8V7.3zM12 21.5V12M20.5 7.3L12 12 3.5 7.3',
    plano: 'M3 4h18v16H3zM3 10h8M11 4v16M15 14h6',
    ajustes: 'M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6',
    casa: 'M3 10.5L12 3l9 7.5V21h-6v-6H9v6H3z',
    tienda: 'M3.5 9L5 4h14l1.5 5M3.5 9v11h17V9M3.5 9h17M9.5 20v-6h5v6',
    alerta: 'M12 3l9.5 17h-19zM12 10v4M12 17.5h.01',
    campana: 'M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15zM10 20.5a2 2 0 0 0 4 0',
    personas: 'M9 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zM2.5 20a6.5 6.5 0 0 1 13 0M16 4.3a3.5 3.5 0 0 1 0 6.4M18 14a6.5 6.5 0 0 1 3.5 6',
    llave: 'M14.5 9.5a4.5 4.5 0 1 1-9 0 4.5 4.5 0 0 1 9 0zM13.5 12.5L21 20M18 17l2-2M16 15l2-2',
    escudo: 'M12 3l8 3v6c0 4.5-3.4 8-8 9-4.6-1-8-4.5-8-9V6zM8.5 12l2.5 2.5 4.5-5',
    correo: 'M3 5h18v14H3zM3 6l9 7 9-7',
    copia: 'M4 7c0-2 3.6-3.5 8-3.5S20 5 20 7s-3.6 3.5-8 3.5S4 9 4 7zM4 7v10c0 2 3.6 3.5 8 3.5s8-1.5 8-3.5V7M4 12c0 2 3.6 3.5 8 3.5s8-1.5 8-3.5',
    camara: 'M3 7h4l2-3h6l2 3h4v13H3zM12 17a4 4 0 1 0 0-8 4 4 0 0 0 0 8z',
    enlace: 'M10 14a4.5 4.5 0 0 0 6.4 0l3-3a4.5 4.5 0 0 0-6.4-6.4l-1 1M14 10a4.5 4.5 0 0 0-6.4 0l-3 3a4.5 4.5 0 0 0 6.4 6.4l1-1',
    conteo: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7v5l3 2',
    avanzado: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z',
    salir: 'M15 4h4a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1h-4M10 16l-4-4 4-4M6 12h11',
    mano: 'M7 11V6.5a1.5 1.5 0 0 1 3 0V11m0-1V4.5a1.5 1.5 0 0 1 3 0V11m0-.5V6a1.5 1.5 0 0 1 3 0v6m0-2.5a1.5 1.5 0 0 1 3 0V15a6 6 0 0 1-6 6h-1.5a6 6 0 0 1-4.6-2.2L4 14.5a1.6 1.6 0 0 1 2.4-2L7 13',
    movil: 'M7 2.5h10a1 1 0 0 1 1 1v17a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1v-17a1 1 0 0 1 1-1zM11 18.5h2',
    ojo: 'M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z',
    flecha: 'M5 12h14M13 6l6 6-6 6',
    descarga: 'M12 3v12M7 10l5 5 5-5M4 20h16',
    recargar: 'M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7',
    mas: 'M12 5v14M5 12h14',
    reloj: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7v5l3 2',
  };
  function sprite() {
    if (document.getElementById('tq-sprite')) return;
    const ns = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(ns, 'svg');
    svg.id = 'tq-sprite';
    svg.setAttribute('aria-hidden', 'true');
    svg.style.display = 'none';
    for (const [name, d] of Object.entries(P)) {
      const s = document.createElementNS(ns, 'symbol');
      s.id = `i-${name}`;
      s.setAttribute('viewBox', '0 0 24 24');
      const p = document.createElementNS(ns, 'path');
      p.setAttribute('d', d);
      s.appendChild(p);
      svg.appendChild(s);
    }
    document.body.prepend(svg);
  }
  const icon = (name, cls = '') => `<svg class="i ${cls}" aria-hidden="true"><use href="#i-${name}"/></svg>`;

  // ---- almacenamiento local que no falla (ventana privada, sitio bloqueado)
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch { /* sin almacenamiento: no pasa nada */ } },
  };

  // ---- subpestañas
  function subtabs(nav) {
    const btns = [...nav.querySelectorAll('.subtab')];
    const scope = document.querySelector(nav.dataset.scope || 'main');
    const key = `tq-sub-${nav.id || 'x'}`;
    const show = (target, remember = true) => {
      if (!btns.some(b => b.dataset.target === target)) target = btns[0]?.dataset.target;
      btns.forEach(b => b.setAttribute('aria-selected', String(b.dataset.target === target)));
      scope.querySelectorAll('[data-group]').forEach(el => { el.hidden = el.dataset.group !== target; });
      if (remember) store.set(key, target);
      document.dispatchEvent(new CustomEvent('tq:subtab', { detail: { nav: nav.id, target } }));
    };
    btns.forEach(b => {
      b.setAttribute('role', 'tab');
      b.addEventListener('click', () => show(b.dataset.target));
    });
    nav.setAttribute('role', 'tablist');
    show(store.get(key), false);
    return show;
  }

  // ---- tutorial de bienvenida
  let dlg = null;
  function tourOpen(steps, onDone) {
    if (!dlg) {
      dlg = document.createElement('dialog');
      dlg.className = 'tour';
      dlg.setAttribute('aria-labelledby', 'tourTitle');
      document.body.appendChild(dlg);
    }
    let i = 0;
    const render = () => {
      const s = steps[i], last = i === steps.length - 1;
      dlg.innerHTML = `
        <div class="tour-art">${icon(s.icon || 'ojo')}</div>
        <div class="tour-body">
          <div class="tour-step">Paso ${i + 1} de ${steps.length}</div>
          <h2 id="tourTitle">${s.title}</h2>
          <p>${s.text}</p>
        </div>
        <div class="tour-foot">
          <div class="tour-dots">${steps.map((_, j) => `<i class="${j === i ? 'on' : ''}"></i>`).join('')}</div>
          ${i ? '<button class="btn" data-t="back">Atrás</button>' : '<button class="btn" data-t="skip">Saltar</button>'}
          <button class="btn primary" data-t="next">${last ? 'Empezar' : 'Siguiente'}</button>
        </div>`;
      if (dlg.open) dlg.querySelector('[data-t="next"]').focus();
    };
    dlg.onclick = ev => {
      const t = ev.target.closest('[data-t]')?.dataset.t;
      if (t === 'next') { if (i < steps.length - 1) { i++; render(); } else dlg.close(); }
      if (t === 'back') { i--; render(); }
      if (t === 'skip') dlg.close();
    };
    dlg.onkeydown = ev => {
      if (ev.key === 'ArrowRight' && i < steps.length - 1) { i++; render(); }
      if (ev.key === 'ArrowLeft' && i > 0) { i--; render(); }
    };
    dlg.onclose = () => onDone && onDone();
    render();
    dlg.showModal();
    dlg.querySelector('[data-t="next"]').focus();
  }
  function tour(key, steps) {
    if (store.get(`tq-tour-${key}`)) return;
    tourOpen(steps, () => store.set(`tq-tour-${key}`, '1'));
  }
  tour.open = steps => tourOpen(steps);

  window.TQ = { icon, subtabs, tour, store };
  const init = () => {
    sprite();
    document.querySelectorAll('nav.subtabs').forEach(subtabs);
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
