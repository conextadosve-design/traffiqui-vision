/* Traffiqui Vision · editor del croquis de la tienda (SVG, en metros)
 *
 * Pensado para quien no dibuja planos: pasos guiados, herramientas con atajos,
 * selección múltiple, alinear / distribuir, medidas visibles, imán a esquinas,
 * capas que se ocultan o bloquean, imagen de fondo para calcar y plantillas.
 * Cada caja (checkout) genera sola su "zona del cliente" (cuenta para "pasó por caja")
 * y su "zona del cajero" (marca al personal), que la siguen al moverla o rotarla.
 */
'use strict';

(() => {
  const NS = 'http://www.w3.org/2000/svg';
  const $ = (s, r = document) => r.querySelector(s);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const uid = () => Math.random().toString(36).slice(2, 10);
  const r2 = v => Math.round(v * 100) / 100;
  const deg = a => a * Math.PI / 180;
  const clone = o => JSON.parse(JSON.stringify(o));

  // ------------------------------------------------------------------ catálogo
  const TYPES = {
    wall:      { shape: 'segment', name: 'Pared', layer: 'structure', thickness: 0.15, h: 3.0 },
    divider:   { shape: 'segment', name: 'Divisor', layer: 'structure', thickness: 0.08, h: 1.5 },
    door:      { shape: 'segment', name: 'Puerta', layer: 'structure', thickness: 0.1, h: 0 },
    gondola:   { shape: 'box', name: 'Góndola', layer: 'furniture', w: 1.0, d: 4.0, h: 1.8 },
    furniture: { shape: 'box', name: 'Mueble', layer: 'furniture', w: 1.2, d: 1.2, h: 1.0 },
    checkout:  { shape: 'box', name: 'Caja', layer: 'furniture', w: 1.4, d: 0.7, h: 1.0 },
    fridge:    { shape: 'box', name: 'Nevera', layer: 'furniture', w: 2.0, d: 0.8, h: 2.0 },
    counter:   { shape: 'box', name: 'Mostrador', layer: 'furniture', w: 3.0, d: 0.7, h: 1.1 },
    area:      { shape: 'polygon', name: 'Área', layer: 'areas' },
    camera:    { shape: 'point', name: 'Cámara', layer: 'cameras', h: 2.8 },
  };
  const LAYERS = { background: 'Imagen de fondo', structure: 'Paredes y puertas', furniture: 'Mobiliario y cajas', areas: 'Áreas de análisis', cameras: 'Cámaras' };
  const AREA_KINDS = { pasillo: 'Pasillo', cabecera: 'Cabecera', caja: 'Zona de cajas (cliente paga aquí)', personal: 'Zona de personal (solo empleados)', entrada: 'Entrada', mostrador: 'Mostrador', otro: 'Otro' };
  const AREA_COLORS = { pasillo: '#E0A526', cabecera: '#1D7A64', caja: '#286EA0', personal: '#8A8F98', entrada: '#3C8282', mostrador: '#964678', otro: '#8A8F98' };
  const BOX_FILL = { gondola: '#D9C8A3', furniture: '#B9C3CF', checkout: '#7FB9A4', fridge: '#B8D8EC', counter: '#D8B9A0' };
  const DOOR_ROLES = { both: 'Entrada y salida', entry: 'Solo entrada', exit: 'Solo salida' };
  const DOOR_COLORS = { both: '#1D7A64', entry: '#1D7A64', exit: '#C8783C' };
  const SIDES = { front: 'Frente', back: 'Atrás', left: 'Izquierda', right: 'Derecha' };
  const PRESETS = {
    gondola: [['Estándar 1 × 4 m', 1, 4], ['Corta 1 × 2 m', 1, 2], ['Larga 1 × 6 m', 1, 6], ['Cabecera 1.2 × 0.6', 1.2, 0.6], ['Isla 2 × 2 m', 2, 2]],
    checkout: [['Caja simple 1.4 × 0.7', 1.4, 0.7], ['Caja con banda 2.5 × 0.8', 2.5, 0.8]],
    fridge: [['Nevera 2 puertas', 1.4, 0.8], ['Nevera 3 puertas', 2.1, 0.8], ['Congelador horizontal', 2, 0.9]],
    counter: [['Mostrador 3 m', 3, 0.7], ['Mostrador 5 m', 5, 0.7]],
  };

  // herramientas: [id, nombre, atajo, grupo, ícono (path SVG 16×16)]
  const TOOLS = [
    ['select', 'Seleccionar', 'V', 'Navegar', 'M3 2l9 5-4 1-2 4z'],
    ['hand', 'Mover vista', 'H', 'Navegar', 'M5 8V3.5a1 1 0 012 0V7m0-4a1 1 0 012 0v4m0-3a1 1 0 012 0v4m0-2a1 1 0 012 0v4c0 3-2 4-4 4H7c-2 0-3-1-4-3l-1-2a1 1 0 012-1l1 1'],
    ['room', 'Habitación', 'T', 'Estructura', 'M2 2h12v12H2z'],
    ['wall', 'Pared', 'W', 'Estructura', 'M2 13L8 3l6 10'],
    ['divider', 'Divisor', 'D', 'Estructura', 'M2 8h12'],
    ['door', 'Entrada', 'E', 'Estructura', 'M3 14V2h7v12M8 8h.01M10 14h4'],
    ['exit', 'Salida (opcional)', 'S', 'Estructura', 'M6 14H2V2h4M10 5l3 3-3 3M13 8H6'],
    ['gondola', 'Góndola', 'G', 'Mobiliario', 'M5 1h6v14H5zM5 5h6M5 9h6'],
    ['furniture', 'Mueble / isla', 'M', 'Mobiliario', 'M2 5h12v6H2zM4 11v3M12 11v3'],
    ['checkout', 'Caja (cobro)', 'C', 'Mobiliario', 'M2 6h12v7H2zM5 3h6v3M5 9h2'],
    ['fridge', 'Nevera', 'N', 'Mobiliario', 'M4 1h8v14H4zM4 6h8M6 3v1M6 8v2'],
    ['counter', 'Mostrador', 'O', 'Mobiliario', 'M1 6h14v4H1zM3 10v4M13 10v4'],
    ['area-rect', 'Área (rectángulo)', 'A', 'Áreas', 'M2 3h12v10H2z'],
    ['area', 'Área (libre)', 'P', 'Áreas', 'M2 12l3-9 6 2 3 7-7 2z'],
    ['staff-rect', 'Zona de personal', 'Z', 'Áreas', 'M2 3h12v10H2zM5 6l6 4M11 6l-6 4'],
    ['camera', 'Cámara', 'K', 'Cámaras', 'M2 5h8v6H2zM10 7l4-2v6l-4-2'],
  ];

  const state = {
    plan: null, tool: 'select', sel: new Set(), draft: null, snap: true, history: [], future: [],
    cameras: [], footprints: {}, saving: null, dirty: false, clipboard: null, space: false,
    layers: { background: { visible: true, locked: true }, structure: { visible: true, locked: false },
              furniture: { visible: true, locked: false }, areas: { visible: true, locked: false }, cameras: { visible: true, locked: false } },
    snapHit: null, measure: null,
  };
  try { Object.assign(state.layers, JSON.parse(localStorage.getItem('tqPlanLayers') || '{}')); } catch { /* sin almacenamiento */ }

  // ------------------------------------------------------------------ geometría
  function boxCorners(e) {
    const c = Math.cos(deg(e.rot || 0)), s = Math.sin(deg(e.rot || 0)), hw = e.w / 2, hd = e.d / 2;
    return [[-hw, -hd], [hw, -hd], [hw, hd], [-hw, hd]].map(([x, y]) => [e.x + x * c - y * s, e.y + x * s + y * c]);
  }
  const toWorld = (e, lx, ly) => {
    const c = Math.cos(deg(e.rot || 0)), s = Math.sin(deg(e.rot || 0));
    return [r2(e.x + lx * c - ly * s), r2(e.y + lx * s + ly * c)];
  };
  const toLocal = (e, x, y) => {
    const c = Math.cos(-deg(e.rot || 0)), s = Math.sin(-deg(e.rot || 0)), dx = x - e.x, dy = y - e.y;
    return [dx * c - dy * s, dx * s + dy * c];
  };
  function elPoints(e) {
    const T = TYPES[e.type];
    if (T.shape === 'segment' || T.shape === 'polygon') return e.points;
    if (T.shape === 'box') return boxCorners(e);
    return [[e.x - 0.3, e.y - 0.3], [e.x + 0.3, e.y + 0.3]];
  }
  function bbox(e) {
    const p = elPoints(e), xs = p.map(q => q[0]), ys = p.map(q => q[1]);
    return { x0: Math.min(...xs), y0: Math.min(...ys), x1: Math.max(...xs), y1: Math.max(...ys) };
  }
  const centroid = arr => arr.reduce((a, p) => [a[0] + p[0] / arr.length, a[1] + p[1] / arr.length], [0, 0]);
  const pts = arr => arr.map(p => p.join(',')).join(' ');
  const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);
  function svgPoint(svg, ev) {
    const p = svg.createSVGPoint();
    p.x = ev.clientX; p.y = ev.clientY;
    const q = p.matrixTransform(svg.getScreenCTM().inverse());
    return [q.x, q.y];
  }
  function el(tag, attrs = {}, parent) {
    const n = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) if (v !== undefined && v !== null && v !== false) n.setAttribute(k, v);
    if (parent) parent.appendChild(n);
    return n;
  }
  const fmtM = v => `${(Math.round(v * 100) / 100).toLocaleString('es-VE')} m`;

  // ------------------------------------------------------------------ zonas automáticas de cada caja
  function checkoutZonePolys(box) {
    const side = box.customer_side || 'front', depth = box.zone_depth ?? 1.2, extra = box.zone_extra ?? 0.2;
    const cd = box.cashier_depth ?? 0.9, hw = box.w / 2, hd = box.d / 2;
    const rect = (cx, cy, w, d) => [[cx - w / 2, cy - d / 2], [cx + w / 2, cy - d / 2], [cx + w / 2, cy + d / 2], [cx - w / 2, cy + d / 2]]
      .map(([x, y]) => toWorld(box, x, y));
    const along = { front: [0, 1], back: [0, -1], right: [1, 0], left: [-1, 0] }[side];
    const make = (dir, dd) => along[0] === 0
      ? rect(0, dir * (hd + dd / 2), box.w + 2 * extra, dd)
      : rect(dir * (hw + dd / 2), 0, dd, box.d + 2 * extra);
    const sgn = along[0] || along[1];
    return { customer: make(sgn, depth), cashier: make(-sgn, cd) };
  }

  function syncCheckoutZones() {
    const p = state.plan;
    const boxes = p.elements.filter(e => e.type === 'checkout');
    const ids = new Set(boxes.map(b => b.id));
    // zonas huérfanas (su caja se borró)
    p.elements = p.elements.filter(e => !(e.type === 'area' && e.checkout_id && !ids.has(e.checkout_id)));
    for (const b of boxes) {
      const polys = checkoutZonePolys(b);
      for (const role of ['customer', 'cashier']) {
        let z = p.elements.find(e => e.type === 'area' && e.checkout_id === b.id && e.zone_role === role);
        const wanted = role === 'customer' || b.cashier_zone !== false;
        if (!wanted) { if (z) p.elements = p.elements.filter(e => e !== z); continue; }
        const autoName = `${b.label || 'Caja'} · ${role === 'customer' ? 'cliente' : 'cajero'}`;
        if (!z) {
          z = { id: uid(), type: 'area', kind: role === 'customer' ? 'caja' : 'personal', checkout_id: b.id, zone_role: role,
                cameras: [], auto: true, auto_name: true, name: autoName, points: polys[role] };
          p.elements.push(z);
        }
        if (z.auto !== false) z.points = polys[role];
        if (z.auto_name !== false) z.name = autoName;
        z.kind = role === 'customer' ? 'caja' : 'personal';
      }
    }
  }

  // ------------------------------------------------------------------ dibujo (compartido con calibración y 3D)
  function render(svg, plan, opts = {}) {
    svg.innerHTML = '';
    const W = plan.width, D = plan.depth, pad = 1;
    if (!svg.dataset.vb || opts.fit) svg.setAttribute('viewBox', `${-pad} ${-pad} ${W + 2 * pad} ${D + 2 * pad}`);
    svg.dataset.vb = '1';
    const sel = opts.selected instanceof Set ? opts.selected : new Set(opts.selected ? [opts.selected] : []);
    const layers = opts.layers || null;
    const defs = el('defs', {}, svg);
    const hatch = el('pattern', { id: `hatch-${svg.id}`, width: 0.3, height: 0.3, patternUnits: 'userSpaceOnUse', patternTransform: 'rotate(45)' }, defs);
    el('line', { x1: 0, y1: 0, x2: 0, y2: 0.3, stroke: '#8A8F98', 'stroke-width': 0.08 }, hatch);
    const root = el('g', {}, svg);
    el('rect', { x: 0, y: 0, width: W, height: D, class: 'pl-floor' }, root);

    const bg = plan.background;
    if (bg && opts.background !== false && (!layers || layers.background.visible)) {
      el('image', { href: bg.data, x: bg.x || 0, y: bg.y || 0, width: bg.w, height: bg.w * (bg.aspect || 0.75),
                    opacity: bg.opacity ?? 0.5, preserveAspectRatio: 'none', class: 'pl-bg' }, root);
    }
    const grid = el('g', { class: 'pl-grid' }, root);
    for (let x = 0; x <= W + 1e-6; x += 1) el('line', { x1: x, y1: 0, x2: x, y2: D, class: x % 5 === 0 ? 'major' : '' }, grid);
    for (let y = 0; y <= D + 1e-6; y += 1) el('line', { x1: 0, y1: y, x2: W, y2: y, class: y % 5 === 0 ? 'major' : '' }, grid);
    const sc = el('g', { class: 'pl-scale' }, root);
    for (let x = 0; x <= W; x += 5) { const t = el('text', { x, y: -0.25 }, sc); t.textContent = `${x} m`; }
    for (let y = 5; y <= D; y += 5) { const t = el('text', { x: -0.2, y: y + 0.1, 'text-anchor': 'end' }, sc); t.textContent = `${y}`; }

    if (opts.heat) drawHeat(root, opts.heat);
    if (opts.footprints) for (const [cid, fp] of Object.entries(opts.footprints)) if (fp.length >= 3) el('polygon', { points: pts(fp), class: 'pl-footprint', 'data-cam': cid }, root);

    const groups = {};
    for (const k of ['areas', 'structure', 'furniture', 'cameras']) {
      const hidden = layers && !layers[k].visible, locked = layers && layers[k].locked;
      groups[k] = el('g', { class: `pl-layer${locked ? ' locked' : ''}`, 'data-layer': k, visibility: hidden ? 'hidden' : null }, root);
    }
    for (const e of plan.elements) drawElement(groups[TYPES[e.type].layer], e, { ...opts, plan, sel, svgId: svg.id });
    if (opts.interactive && sel.size === 1) {
      const e = plan.elements.find(x => sel.has(x.id));
      if (e && !(layers && layers[TYPES[e.type].layer].locked)) drawHandles(root, e);
    }
    return root;
  }

  function drawHeat(root, heat) {
    const g = el('g', { class: 'pl-heat' }, root);
    for (let r = 0; r < heat.rows; r++) for (let c = 0; c < heat.cols; c++) {
      const v = heat.values[r * heat.cols + c];
      if (v < 0.04) continue;
      el('rect', { x: c * heat.cell, y: r * heat.cell, width: heat.cell + 0.01, height: heat.cell + 0.01, fill: heatColor(v), 'fill-opacity': Math.min(0.85, 0.25 + v * 0.7) }, g);
    }
  }
  function heatColor(v) { // secuencial de un solo tono cálido: crema → latón → marrón rojizo
    const stops = [[253, 236, 190], [224, 165, 38], [196, 96, 24], [122, 40, 18]];
    const x = Math.min(0.999, Math.max(0, v)) * (stops.length - 1), i = Math.floor(x), f = x - i;
    return `rgb(${stops[i].map((s, k) => Math.round(s + (stops[i + 1][k] - s) * f)).join(',')})`;
  }

  function drawElement(parent, e, opts) {
    const T = TYPES[e.type];
    const isSel = opts.sel.has(e.id);
    const g = el('g', { class: `pl-el pl-${e.type}${isSel ? ' sel' : ''}${e.zone_role ? ` zone-${e.zone_role}` : ''}`, 'data-id': e.id }, parent);
    const labels = opts.labels !== false;
    if (T.shape === 'segment') {
      const color = e.type === 'door' ? DOOR_COLORS[e.role || 'both'] : null;
      el('polyline', { points: pts(e.points), 'stroke-width': Math.max(0.05, e.thickness || T.thickness), class: 'body', stroke: color }, g);
      el('polyline', { points: pts(e.points), class: 'hit' }, g);
      if (e.type === 'door') drawDoorArrow(g, e, opts.plan, color, labels);
      if (isSel && opts.interactive) segmentDims(g, e.points, false);
    } else if (T.shape === 'polygon') {
      const kind = e.kind || 'pasillo';
      const fill = kind === 'personal' ? `url(#hatch-${opts.svgId})` : AREA_COLORS[kind];
      el('polygon', { points: pts(e.points), class: 'body', fill, stroke: AREA_COLORS[kind] }, g);
      if (labels) {
        const c = centroid(e.points);
        const t = el('text', { x: c[0], y: c[1], class: `pl-label area${e.zone_role ? ' zone' : ''}` }, g);
        t.textContent = e.zone_role === 'customer' ? `${e.name} · cliente paga aquí`.replace(' · cliente · cliente', ' · cliente') : e.name;
        if (opts.areaValues && opts.areaValues[e.id] !== undefined) {
          const v = el('text', { x: c[0], y: c[1] + 0.5, class: 'pl-label value' }, g); v.textContent = opts.areaValues[e.id];
        }
      }
      if (isSel && opts.interactive) segmentDims(g, e.points, true);
    } else if (T.shape === 'box') {
      el('polygon', { points: pts(boxCorners(e)), class: 'body', fill: BOX_FILL[e.type] }, g);
      if (e.type === 'checkout') { // marca del lado del cliente
        const p = checkoutZonePolys(e).customer, c = centroid(p), m = centroid(boxCorners(e));
        el('line', { x1: m[0], y1: m[1], x2: (m[0] + c[0]) / 2, y2: (m[1] + c[1]) / 2, class: 'co-arrow' }, g);
      }
      if (labels && (e.label || e.category)) {
        const vertical = Math.abs(e.d) > Math.abs(e.w) * 1.5 && !((e.rot || 0) % 180);
        const t = el('text', { x: e.x, y: e.y, class: 'pl-label box', transform: vertical ? `rotate(-90 ${e.x} ${e.y})` : null }, g);
        t.textContent = e.type === 'checkout' ? (e.label || 'Caja') : (e.category || e.label);
      }
      if (isSel && opts.interactive) {
        const [a, b, c] = boxCorners(e);
        dimLabel(g, [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2], fmtM(e.w), -0.25);
        dimLabel(g, [(b[0] + c[0]) / 2, (b[1] + c[1]) / 2], fmtM(e.d), 0.25);
      }
    } else if (T.shape === 'point') {
      const L = 3, fov = deg(e.fov || 90), a = deg(e.rot || 0);
      const p1 = [e.x + L * Math.cos(a - fov / 2), e.y + L * Math.sin(a - fov / 2)], p2 = [e.x + L * Math.cos(a + fov / 2), e.y + L * Math.sin(a + fov / 2)];
      el('polygon', { points: pts([[e.x, e.y], p1, p2]), class: 'fov' }, g);
      el('circle', { cx: e.x, cy: e.y, r: 0.3, class: 'body' }, g);
      if (labels) {
        const cam = (opts.cameras || state.cameras).find(c => c.id === e.camera_id);
        const t = el('text', { x: e.x, y: e.y - 0.5, class: 'pl-label cam' }, g); t.textContent = cam ? cam.name : 'Cámara sin asignar';
      }
    }
  }

  function drawDoorArrow(g, e, plan, color, labels) {
    const a = e.points[0], b = e.points[e.points.length - 1], m = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
    const len = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1;
    let n = [-(b[1] - a[1]) / len, (b[0] - a[0]) / len];
    if (n[0] * (plan.width / 2 - m[0]) + n[1] * (plan.depth / 2 - m[1]) < 0) n = [-n[0], -n[1]];
    if (e.flip) n = [-n[0], -n[1]];
    const tip = [m[0] + n[0] * 0.9, m[1] + n[1] * 0.9];
    el('line', { x1: m[0], y1: m[1], x2: tip[0], y2: tip[1], class: 'door-arrow', stroke: color }, g);
    el('polygon', { points: pts([[tip[0] + n[0] * 0.25, tip[1] + n[1] * 0.25], [tip[0] - n[1] * 0.18, tip[1] + n[0] * 0.18], [tip[0] + n[1] * 0.18, tip[1] - n[0] * 0.18]]), fill: color }, g);
    if (labels) {
      const t = el('text', { x: m[0] - n[0] * 0.45, y: m[1] - n[1] * 0.45, class: 'pl-label door', fill: color }, g);
      t.textContent = e.label || (e.role === 'exit' ? 'Salida' : 'Entrada');
    }
  }
  function dimLabel(g, p, text, off = 0) {
    const t = el('text', { x: p[0], y: p[1] + off, class: 'pl-dim' }, g); t.textContent = text;
  }
  function segmentDims(g, points, closed) {
    const n = points.length;
    for (let i = 0; i < (closed ? n : n - 1); i++) {
      const a = points[i], b = points[(i + 1) % n];
      if (dist(a, b) > 0.3) dimLabel(g, [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2], fmtM(dist(a, b)));
    }
  }
  function drawHandles(root, e) {
    const T = TYPES[e.type], g = el('g', { class: 'pl-handles' }, root);
    if (T.shape === 'segment' || T.shape === 'polygon') {
      e.points.forEach((p, i) => el('circle', { cx: p[0], cy: p[1], r: 0.2, class: 'handle', 'data-vertex': i }, g));
    } else if (T.shape === 'box') {
      const c = boxCorners(e)[2];
      el('circle', { cx: c[0], cy: c[1], r: 0.22, class: 'handle', 'data-resize': '1' }, g);
      const top = toWorld(e, 0, -e.d / 2 - 0.7), mid = toWorld(e, 0, -e.d / 2);
      el('line', { x1: mid[0], y1: mid[1], x2: top[0], y2: top[1], class: 'rot-line' }, g);
      el('circle', { cx: top[0], cy: top[1], r: 0.2, class: 'handle rot', 'data-rotate': '1' }, g);
    }
  }

  // ------------------------------------------------------------------ estado y guardado
  const svg = () => $('#planSvg');
  const plan = () => state.plan;
  const byId = id => plan().elements.find(e => e.id === id);
  const selected = () => plan().elements.filter(e => state.sel.has(e.id));
  const layerOf = e => TYPES[e.type].layer;
  const isLocked = e => state.layers[layerOf(e)].locked || !state.layers[layerOf(e)].visible;

  const snapshot = () => JSON.stringify({ ...plan(), background: undefined }); // la imagen de fondo no entra al historial
  function restore(json) { const bg = plan().background; state.plan = JSON.parse(json); if (bg) state.plan.background = bg; }
  function pushHistory() { state.history.push(snapshot()); if (state.history.length > 100) state.history.shift(); state.future = []; }
  function undo() { if (!state.history.length) return; state.future.push(snapshot()); restore(state.history.pop()); pruneSel(); changed(true, false); }
  function redo() { if (!state.future.length) return; state.history.push(snapshot()); restore(state.future.pop()); pruneSel(); changed(true, false); }
  function pruneSel() { for (const id of [...state.sel]) if (!byId(id)) state.sel.delete(id); }

  function changed(save = true, sync = true) {
    if (sync) syncCheckoutZones();
    redraw();
    renderProps();
    renderList();
    renderSteps();
    if (save) scheduleSave();
  }
  function scheduleSave() {
    state.dirty = true;
    setStatus('Guardando…');
    clearTimeout(state.saving);
    state.saving = setTimeout(save, 700);
  }
  async function save() {
    try {
      const r = await fetch('/api/floorplan', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(plan()) });
      const body = await r.json();
      if (!r.ok) throw new Error(body.detail || 'No se pudo guardar el plano.');
      state.dirty = false;
      setStatus('Guardado ✓');
      document.dispatchEvent(new CustomEvent('tq:floorplan', { detail: body }));
    } catch (e) { setStatus(e.message, true); }
  }
  function setStatus(msg, err = false) { const s = $('#planStatus'); if (s) { s.textContent = msg; s.classList.toggle('err', err); } }

  function redraw() {
    if (!svg() || !plan()) return;
    const vb = svg().getAttribute('viewBox');
    render(svg(), plan(), { selected: state.sel, footprints: state.footprints, interactive: true, layers: state.layers });
    if (vb) svg().setAttribute('viewBox', vb);
    drawOverlay();
    updateZoom();
  }
  function drawOverlay() {
    const s = svg(), g = el('g', { class: 'pl-draft' }, s), d = state.draft;
    if (d?.kind === 'points' && d.points.length) {
      const all = d.cursor ? [...d.points, d.cursor] : d.points;
      el(d.type === 'area' ? 'polygon' : 'polyline', { points: pts(all) }, g);
      d.points.forEach(p => el('circle', { cx: p[0], cy: p[1], r: 0.12 }, g));
      if (d.cursor) { const a = d.points[d.points.length - 1]; dimLabel(g, [(a[0] + d.cursor[0]) / 2, (a[1] + d.cursor[1]) / 2], fmtM(dist(a, d.cursor))); }
    } else if (d?.kind === 'rect' && d.cursor) {
      const [x0, y0] = d.start, [x1, y1] = d.cursor;
      el('rect', { x: Math.min(x0, x1), y: Math.min(y0, y1), width: Math.abs(x1 - x0), height: Math.abs(y1 - y0) }, g);
      dimLabel(g, [(x0 + x1) / 2, Math.min(y0, y1) - 0.1], `${fmtM(Math.abs(x1 - x0))} × ${fmtM(Math.abs(y1 - y0))}`);
    } else if (d?.kind === 'band' && d.cursor) {
      const [x0, y0] = d.start, [x1, y1] = d.cursor;
      el('rect', { x: Math.min(x0, x1), y: Math.min(y0, y1), width: Math.abs(x1 - x0), height: Math.abs(y1 - y0), class: 'band' }, g);
    } else if (d?.kind === 'measure' && d.points.length) {
      const all = d.cursor ? [...d.points, d.cursor] : d.points;
      el('polyline', { points: pts(all), class: 'measure' }, g);
    }
    if (state.snapHit) el('circle', { cx: state.snapHit[0], cy: state.snapHit[1], r: 0.18, class: 'snap-hit' }, g);
  }

  // ------------------------------------------------------------------ imán
  function snapPoint(p, ev, exclude = new Set()) {
    state.snapHit = null;
    if (ev?.altKey) return [r2(p[0]), r2(p[1])];
    if (state.snap) {
      let best = null, bd = 0.35;
      for (const e of plan().elements) {
        if (exclude.has(e.id) || isLocked(e)) continue;
        const cand = TYPES[e.type].shape === 'box' ? boxCorners(e) : TYPES[e.type].shape === 'point' ? [] : e.points;
        for (const q of cand) { const dd = dist(p, q); if (dd < bd) { bd = dd; best = q; } }
      }
      for (const q of [[0, 0], [plan().width, 0], [plan().width, plan().depth], [0, plan().depth]]) { const dd = dist(p, q); if (dd < bd) { bd = dd; best = q; } }
      if (best) { state.snapHit = best; return [r2(best[0]), r2(best[1])]; }
      const g = plan().grid || 0.5;
      return [r2(Math.round(p[0] / g) * g), r2(Math.round(p[1] / g) * g)];
    }
    return [r2(p[0]), r2(p[1])];
  }

  // ------------------------------------------------------------------ herramientas
  const HINTS = {
    select: 'Clic para seleccionar · Shift+clic suma · arrastra el piso para seleccionar varios · arrastra para mover.',
    hand: 'Arrastra para desplazar la vista. Rueda del mouse = zoom.',
    room: 'Arrastra un rectángulo: se crean las 4 paredes. Después marca la entrada con "Entrada".',
    wall: 'Clic en cada esquina. Doble clic, Enter o Esc para terminar. El imán engancha las esquinas.',
    divider: 'Clic en cada punto del divisor. Doble clic, Enter o Esc para terminar.',
    door: 'Clic en los 2 extremos de la entrada (sobre la pared). La flecha apunta hacia adentro.',
    exit: 'Opcional: clic en los 2 extremos de una salida distinta de la entrada.',
    gondola: 'Clic para colocar una góndola estándar o arrastra para dibujarla a medida. R rota 90°.',
    furniture: 'Clic para colocar un mueble o isla, o arrastra a medida.',
    checkout: 'Clic para colocar una caja: se crean solas la zona del CLIENTE (azul) y la del CAJERO (gris rayado).',
    fridge: 'Clic para colocar una nevera, o arrastra a medida.',
    counter: 'Clic para colocar un mostrador, o arrastra a medida.',
    'area-rect': 'Arrastra un rectángulo para crear un área de análisis (pasillo, cabecera…).',
    area: 'Clic en cada vértice. Doble clic o Enter para cerrar el área.',
    'staff-rect': 'Arrastra la zona donde solo entra el personal (detrás de un mostrador, depósito). Quien esté ahí no cuenta como cliente.',
    camera: 'Clic donde está montada la cámara. Después elige cuál es y hacia dónde mira.',
    measure: 'Escalar la imagen de fondo: clic en 2 puntos de una medida que conozcas (por ejemplo una pared).',
  };
  function setTool(t) {
    if (state.draft?.kind === 'points') finishDraft(); else state.draft = null;
    state.tool = t;
    document.querySelectorAll('[data-ptool]').forEach(b => b.classList.toggle('active', b.dataset.ptool === t));
    $('#planHint').textContent = HINTS[t] || '';
    svg()?.setAttribute('data-tool', t);
    redraw();
  }

  function newName(type) {
    const n = plan().elements.filter(e => e.type === type).length + 1;
    return `${TYPES[type].name} ${n}`;
  }
  function finishDraft() {
    const d = state.draft;
    state.draft = null;
    if (!d || d.kind !== 'points') { redraw(); return; }
    const need = d.type === 'area' ? 3 : 2;
    if (d.points.length < need) { redraw(); return; }
    pushHistory();
    const e = { id: uid(), type: d.type, points: d.points };
    if (d.type === 'area') Object.assign(e, { name: nextAreaName(), kind: 'pasillo', cameras: [] });
    else { e.thickness = TYPES[d.type].thickness; e.height = TYPES[d.type].h; }
    if (d.type === 'door') addDoorProps(e, d.role);
    plan().elements.push(e);
    state.sel = new Set([e.id]);
    changed();
    if (d.type === 'area') askName(e);
  }
  function addDoorProps(e, role) {
    e.role = role || 'both';
    e.label = e.role === 'exit' ? 'Salida' : 'Entrada';
    e.flip = false;
    if (e.role === 'exit') {
      plan().elements.filter(x => x.type === 'door' && x !== e && (x.role || 'both') === 'both').forEach(x => { x.role = 'entry'; });
      window.tqToast?.('Salida agregada. Las entradas quedaron como "Solo entrada" (se puede cambiar).');
    }
  }
  const nextAreaName = () => `Pasillo ${plan().elements.filter(e => e.type === 'area' && !e.checkout_id).length + 1}`;
  function askName(e) {
    window.tqAsk?.('Nombre del área', { value: e.name, text: 'Por ejemplo "Pasillo 3 · Bebidas", "Cabecera promo" o "Depósito".' })
      .then(name => { if (name) { pushHistory(); e.name = name; e.auto_name = false; changed(); } });
  }

  function addBox(type, x, y, w, d) {
    const T = TYPES[type];
    pushHistory();
    const e = { id: uid(), type, x: r2(x), y: r2(y), w: r2(w ?? T.w), d: r2(d ?? T.d), h: T.h, rot: 0, label: newName(type), category: '' };
    if (type === 'checkout') Object.assign(e, { customer_side: 'front', zone_depth: 1.2, zone_extra: 0.2, cashier_zone: true, cashier_depth: 0.9 });
    plan().elements.push(e);
    state.sel = new Set([e.id]);
    changed();
  }
  function addRectArea(x0, y0, x1, y1, kind) {
    pushHistory();
    const e = { id: uid(), type: 'area', kind, cameras: [], name: kind === 'personal' ? `Zona de personal ${plan().elements.filter(a => a.kind === 'personal' && !a.checkout_id).length + 1}` : nextAreaName(),
                points: [[x0, y0], [x1, y0], [x1, y1], [x0, y1]].map(p => p.map(r2)) };
    plan().elements.push(e);
    state.sel = new Set([e.id]);
    changed();
    askName(e);
  }
  function addRoom(x0, y0, x1, y1) {
    pushHistory();
    const [a, b] = [Math.min(x0, x1), Math.max(x0, x1)], [c, d] = [Math.min(y0, y1), Math.max(y0, y1)];
    const e = { id: uid(), type: 'wall', thickness: 0.15, height: 3, points: [[a, c], [b, c], [b, d], [a, d], [a, c]] };
    plan().elements.push(e);
    state.sel = new Set([e.id]);
    changed();
    window.tqToast?.('Paredes creadas. Ahora marca la entrada con la herramienta "Entrada".');
  }
  function addCamera(x, y) {
    pushHistory();
    const used = new Set(plan().elements.filter(e => e.type === 'camera').map(e => e.camera_id));
    const free = state.cameras.find(c => !used.has(c.id));
    const e = { id: uid(), type: 'camera', x: r2(x), y: r2(y), rot: 0, fov: 90, height: 2.8, camera_id: free ? free.id : '' };
    plan().elements.push(e);
    state.sel = new Set([e.id]);
    changed();
  }

  function moveElement(e, dx, dy) {
    const T = TYPES[e.type];
    if (e.checkout_id && e.auto !== false) return; // las zonas automáticas siguen a su caja
    if (T.shape === 'segment' || T.shape === 'polygon') e.points = e.points.map(([x, y]) => [r2(x + dx), r2(y + dy)]);
    else { e.x = r2(e.x + dx); e.y = r2(e.y + dy); }
  }
  function removeSelected() {
    if (!state.sel.size) return;
    pushHistory();
    const ids = new Set(state.sel);
    plan().elements = plan().elements.filter(e => !ids.has(e.id));
    state.sel.clear();
    changed();
  }
  function copySel() {
    const els = selected().filter(e => !e.checkout_id);
    if (els.length) { state.clipboard = clone(els); window.tqToast?.(`${els.length} elemento(s) copiado(s)`); }
  }
  function paste(offset = 1) {
    if (!state.clipboard?.length) return;
    pushHistory();
    const add = clone(state.clipboard).map(e => {
      e.id = uid();
      moveElement(e, offset, offset);
      if (e.type === 'camera') e.camera_id = '';
      if (TYPES[e.type].shape === 'box' && e.label) e.label = newName(e.type);
      if (e.type === 'area') { e.name = `${e.name} (copia)`; e.auto_name = false; }
      return e;
    });
    plan().elements.push(...add);
    state.sel = new Set(add.map(e => e.id));
    state.clipboard = clone(add);
    changed();
  }
  const duplicate = () => { copySel(); paste(); };
  function rotateSel(delta) {
    const boxes = selected().filter(e => TYPES[e.type].shape === 'box' || e.type === 'camera');
    if (!boxes.length) return;
    pushHistory();
    boxes.forEach(e => { e.rot = (((e.rot || 0) + delta) % 360 + 360) % 360; });
    changed();
  }

  // alinear / distribuir
  function align(mode) {
    const els = selected().filter(e => !(e.checkout_id && e.auto !== false));
    if (els.length < 2) return;
    pushHistory();
    const bb = els.map(bbox);
    const all = { x0: Math.min(...bb.map(b => b.x0)), x1: Math.max(...bb.map(b => b.x1)), y0: Math.min(...bb.map(b => b.y0)), y1: Math.max(...bb.map(b => b.y1)) };
    els.forEach((e, i) => {
      const b = bb[i];
      const dx = { left: all.x0 - b.x0, right: all.x1 - b.x1, hcenter: (all.x0 + all.x1) / 2 - (b.x0 + b.x1) / 2 }[mode] ?? 0;
      const dy = { top: all.y0 - b.y0, bottom: all.y1 - b.y1, vcenter: (all.y0 + all.y1) / 2 - (b.y0 + b.y1) / 2 }[mode] ?? 0;
      moveElement(e, dx, dy);
    });
    changed();
  }
  function distribute(axis) {
    const els = selected().filter(e => !(e.checkout_id && e.auto !== false));
    if (els.length < 3) return;
    pushHistory();
    const items = els.map(e => ({ e, b: bbox(e) })).sort((p, q) => axis === 'x' ? p.b.x0 - q.b.x0 : p.b.y0 - q.b.y0);
    const size = it => axis === 'x' ? it.b.x1 - it.b.x0 : it.b.y1 - it.b.y0;
    const start = axis === 'x' ? items[0].b.x0 : items[0].b.y0;
    const end = axis === 'x' ? items.at(-1).b.x1 : items.at(-1).b.y1;
    const gap = (end - start - items.reduce((s, it) => s + size(it), 0)) / (items.length - 1);
    let cur = start;
    for (const it of items) {
      const from = axis === 'x' ? it.b.x0 : it.b.y0;
      moveElement(it.e, axis === 'x' ? cur - from : 0, axis === 'y' ? cur - from : 0);
      cur += size(it) + gap;
    }
    changed();
  }
  function sameSize() {
    const boxes = selected().filter(e => TYPES[e.type].shape === 'box');
    if (boxes.length < 2) return;
    pushHistory();
    boxes.slice(1).forEach(e => { e.w = boxes[0].w; e.d = boxes[0].d; e.h = boxes[0].h; });
    changed();
  }
  function aisleBetween() {
    const [a, b] = selected().filter(e => TYPES[e.type].shape === 'box');
    if (!a || !b) return;
    const A = bbox(a), B = bbox(b);
    let rect;
    if (A.x1 <= B.x0 || B.x1 <= A.x0) { // una al lado de la otra: pasillo vertical
      const [l, r] = A.x1 <= B.x0 ? [A, B] : [B, A];
      rect = [l.x1, Math.max(l.y0, r.y0), r.x0, Math.min(l.y1, r.y1)];
    } else if (A.y1 <= B.y0 || B.y1 <= A.y0) { // una sobre la otra: pasillo horizontal
      const [t, d] = A.y1 <= B.y0 ? [A, B] : [B, A];
      rect = [Math.max(t.x0, d.x0), t.y1, Math.min(t.x1, d.x1), d.y0];
    }
    if (!rect || rect[2] - rect[0] < 0.2 || rect[3] - rect[1] < 0.2) { window.tqToast?.('Las dos piezas deben estar enfrentadas y separadas para crear un pasillo entre ellas.', true); return; }
    addRectArea(rect[0], rect[1], rect[2], rect[3], 'pasillo');
  }

  // ------------------------------------------------------------------ eventos del lienzo
  let drag = null;
  function hitElement(target) {
    const g = target.closest?.('.pl-el');
    if (!g) return null;
    const e = byId(g.dataset.id);
    return e && !isLocked(e) ? e : null;
  }
  function startPan(ev) {
    const vb = svg().viewBox.baseVal;
    drag = { mode: 'pan', start: [ev.clientX, ev.clientY], vb: [vb.x, vb.y, vb.width, vb.height] };
  }

  function onDown(ev) {
    const s = svg();
    s.setPointerCapture(ev.pointerId);
    if (ev.button === 1 || state.space || state.tool === 'hand') { ev.preventDefault(); startPan(ev); return; }
    if (ev.button !== 0) return;
    const raw = svgPoint(s, ev);
    const t = state.tool;
    if (t === 'measure') {
      const p = [r2(raw[0]), r2(raw[1])];
      state.draft = state.draft?.kind === 'measure' ? state.draft : { kind: 'measure', points: [] };
      state.draft.points.push(p);
      if (state.draft.points.length === 2) finishMeasure();
      else redraw();
      return;
    }
    if (t === 'select') {
      const tg = ev.target;
      const one = state.sel.size === 1 ? byId([...state.sel][0]) : null;
      if (tg.dataset.vertex !== undefined && one) {
        const i = +tg.dataset.vertex;
        const min = one.type === 'area' ? 3 : 2;
        if (ev.altKey) {
          if (one.points.length > min) { pushHistory(); one.points.splice(i, 1); if (one.checkout_id) one.auto = false; changed(); }
          return;
        }
        pushHistory(); drag = { mode: 'vertex', i, e: one }; return;
      }
      if (tg.dataset.resize && one) { pushHistory(); drag = { mode: 'resize', e: one }; return; }
      if (tg.dataset.rotate && one) { pushHistory(); drag = { mode: 'rotate', e: one }; return; }
      const e = hitElement(tg);
      if (e) {
        if (ev.shiftKey) {
          state.sel.has(e.id) ? state.sel.delete(e.id) : state.sel.add(e.id);
          changed(false, false);
          return;
        }
        if (!state.sel.has(e.id)) state.sel = new Set([e.id]);
        pushHistory();
        const p = snapPoint(raw, ev, state.sel);
        drag = { mode: 'move', last: p, moved: false };
        changed(false, false);
        return;
      }
      if (!ev.shiftKey) state.sel.clear();
      state.draft = { kind: 'band', start: raw, cursor: raw, add: ev.shiftKey };
      changed(false, false);
      return;
    }
    const p = snapPoint(raw, ev);
    if (['wall', 'divider', 'door', 'exit', 'area'].includes(t)) {
      const type = t === 'exit' ? 'door' : t;
      if (!state.draft || state.draft.kind !== 'points') state.draft = { kind: 'points', type, role: t === 'exit' ? 'exit' : 'both', points: [] };
      const last = state.draft.points.at(-1);
      if (!last || last[0] !== p[0] || last[1] !== p[1]) state.draft.points.push(p);
      // cerrar el área tocando el primer punto
      if (type === 'area' && state.draft.points.length > 3 && dist(p, state.draft.points[0]) < 0.3) { state.draft.points.pop(); finishDraft(); return; }
      if (type === 'door' && state.draft.points.length === 2) finishDraft(); else redraw();
      return;
    }
    if (t === 'camera') { addCamera(p[0], p[1]); return; }
    state.draft = { kind: 'rect', type: t, start: p, cursor: null };
  }

  function onMove(ev) {
    const s = svg(), raw = svgPoint(s, ev);
    $('#planCursor').textContent = `x ${raw[0].toFixed(2)} m · y ${raw[1].toFixed(2)} m`;
    if (drag?.mode === 'pan') {
      const rect = s.getBoundingClientRect(), k = drag.vb[2] / rect.width;
      s.setAttribute('viewBox', `${drag.vb[0] - (ev.clientX - drag.start[0]) * k} ${drag.vb[1] - (ev.clientY - drag.start[1]) * k} ${drag.vb[2]} ${drag.vb[3]}`);
      return;
    }
    if (state.draft) {
      state.draft.cursor = state.draft.kind === 'band' || state.draft.kind === 'measure' ? raw : snapPoint(raw, ev);
      redraw();
      return;
    }
    if (!drag) {
      if (state.tool !== 'select') { snapPoint(raw, ev); redraw(); }
      return;
    }
    const e = drag.e;
    if (drag.mode === 'move') {
      const p = snapPoint(raw, ev, state.sel);
      const dx = p[0] - drag.last[0], dy = p[1] - drag.last[1];
      if (dx || dy) { selected().forEach(x => moveElement(x, dx, dy)); drag.last = p; drag.moved = true; syncCheckoutZones(); redraw(); }
    } else if (drag.mode === 'vertex') {
      e.points[drag.i] = snapPoint(raw, ev, new Set([e.id]));
      if (e.checkout_id) e.auto = false;
      redraw();
    } else if (drag.mode === 'resize') {
      const [lx, ly] = toLocal(e, raw[0], raw[1]);
      const g = ev.altKey || !state.snap ? 0.01 : 0.1;
      e.w = Math.max(0.2, r2(Math.round(Math.abs(lx) * 2 / g) * g));
      e.d = Math.max(0.2, r2(Math.round(Math.abs(ly) * 2 / g) * g));
      syncCheckoutZones(); redraw();
    } else if (drag.mode === 'rotate') {
      let a = Math.atan2(raw[1] - e.y, raw[0] - e.x) * 180 / Math.PI + 90;
      if (!ev.shiftKey) a = Math.round(a / 15) * 15;
      e.rot = ((Math.round(a) % 360) + 360) % 360;
      syncCheckoutZones(); redraw();
    }
  }

  function onUp() {
    const d = state.draft;
    if (d?.kind === 'band') {
      state.draft = null;
      const [x0, y0] = d.start, [x1, y1] = d.cursor;
      const box = { x0: Math.min(x0, x1), x1: Math.max(x0, x1), y0: Math.min(y0, y1), y1: Math.max(y0, y1) };
      if (box.x1 - box.x0 > 0.1 || box.y1 - box.y0 > 0.1) {
        for (const e of plan().elements) {
          if (isLocked(e)) continue;
          const b = bbox(e);
          if (b.x0 >= box.x0 && b.x1 <= box.x1 && b.y0 >= box.y0 && b.y1 <= box.y1) state.sel.add(e.id);
        }
      }
      changed(false, false);
      return;
    }
    if (d?.kind === 'rect') {
      state.draft = null;
      const [x0, y0] = d.start, [x1, y1] = d.cursor || d.start;
      const big = Math.abs(x1 - x0) >= 0.3 && Math.abs(y1 - y0) >= 0.3;
      const [a, b, c, e] = [Math.min(x0, x1), Math.min(y0, y1), Math.max(x0, x1), Math.max(y0, y1)];
      if (d.type === 'room') { if (big) addRoom(a, b, c, e); else redraw(); return; }
      if (d.type === 'area-rect' || d.type === 'staff-rect') { if (big) addRectArea(a, b, c, e, d.type === 'staff-rect' ? 'personal' : 'pasillo'); else redraw(); return; }
      if (big) addBox(d.type, (a + c) / 2, (b + e) / 2, c - a, e - b); else addBox(d.type, x0, y0);
      return;
    }
    if (drag) {
      const was = drag; drag = null;
      if (was.mode === 'pan') return;
      if (was.mode === 'move' && !was.moved) { state.history.pop(); return; }
      changed();
    }
  }

  function onDblClick(ev) {
    if (state.draft?.kind === 'points') { finishDraft(); return; }
    if (state.tool !== 'select' || state.sel.size !== 1) return;
    const e = byId([...state.sel][0]);
    if (!e || !['segment', 'polygon'].includes(TYPES[e.type].shape)) return;
    // agregar un vértice en el borde más cercano al doble clic
    const p = svgPoint(svg(), ev), n = e.points.length, closed = TYPES[e.type].shape === 'polygon';
    let best = -1, bd = 0.6;
    for (let i = 0; i < (closed ? n : n - 1); i++) {
      const a = e.points[i], b = e.points[(i + 1) % n], L2 = (b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2 || 1;
      const t = Math.max(0, Math.min(1, ((p[0] - a[0]) * (b[0] - a[0]) + (p[1] - a[1]) * (b[1] - a[1])) / L2));
      const q = [a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])], dd = dist(p, q);
      if (dd < bd) { bd = dd; best = i; }
    }
    if (best < 0) return;
    pushHistory();
    e.points.splice(best + 1, 0, [r2(p[0]), r2(p[1])]);
    if (e.checkout_id) e.auto = false;
    changed();
  }

  function zoomBy(k, center) {
    const s = svg(), vb = s.viewBox.baseVal;
    const [x, y] = center || [vb.x + vb.width / 2, vb.y + vb.height / 2];
    const w = Math.min(Math.max(vb.width * k, 2), 800), h = vb.height * (w / vb.width);
    s.setAttribute('viewBox', `${x - (x - vb.x) * (w / vb.width)} ${y - (y - vb.y) * (h / vb.height)} ${w} ${h}`);
    updateZoom();
  }
  function onWheel(ev) { ev.preventDefault(); zoomBy(ev.deltaY > 0 ? 1.15 : 1 / 1.15, svgPoint(svg(), ev)); }
  function fit() { const s = svg(); if (s && plan()) { s.setAttribute('viewBox', `-1 -1 ${plan().width + 2} ${plan().depth + 2}`); updateZoom(); } }
  function updateZoom() {
    const s = svg(), z = $('#planZoom');
    if (!s || !z || !plan()) return;
    z.textContent = `${Math.round(100 * (plan().width + 2) / s.viewBox.baseVal.width)} %`;
  }

  const KEYMAP = Object.fromEntries(TOOLS.map(t => [t[2].toLowerCase(), t[0]]));
  function onKey(ev) {
    if ($('#view-plan').hidden || ['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement?.tagName) || document.querySelector('dialog[open]')) return;
    const k = ev.key.toLowerCase(), ctrl = ev.ctrlKey || ev.metaKey;
    if (ev.key === ' ') { state.space = true; ev.preventDefault(); return; }
    if (ctrl && k === 'z') { ev.preventDefault(); ev.shiftKey ? redo() : undo(); return; }
    if (ctrl && k === 'y') { ev.preventDefault(); redo(); return; }
    if (ctrl && k === 'd') { ev.preventDefault(); duplicate(); return; }
    if (ctrl && k === 'c') { copySel(); return; }
    if (ctrl && k === 'v') { ev.preventDefault(); paste(); return; }
    if (ctrl && k === 'a') { ev.preventDefault(); state.sel = new Set(plan().elements.filter(e => !isLocked(e)).map(e => e.id)); changed(false, false); return; }
    if (ctrl) return;
    if (ev.key === 'Escape') { if (state.draft?.kind === 'points') finishDraft(); else { state.draft = null; state.sel.clear(); setTool('select'); changed(false, false); } return; }
    if (ev.key === 'Enter' && state.draft?.kind === 'points') { finishDraft(); return; }
    if ((ev.key === 'Delete' || ev.key === 'Backspace') && state.sel.size) { ev.preventDefault(); removeSelected(); return; }
    if (ev.key === '?') { openHelp(); return; }
    if (k === 'r' && state.sel.size) { rotateSel(ev.shiftKey ? -90 : 90); return; }
    if (ev.key.startsWith('Arrow') && state.sel.size) {
      ev.preventDefault();
      const st = ev.shiftKey ? 1 : 0.1;
      const [dx, dy] = { arrowleft: [-st, 0], arrowright: [st, 0], arrowup: [0, -st], arrowdown: [0, st] }[k];
      pushHistory(); selected().forEach(e => moveElement(e, dx, dy)); changed();
      return;
    }
    if (KEYMAP[k]) setTool(KEYMAP[k]);
  }

  // ------------------------------------------------------------------ panel de propiedades
  const field = (label, html, cls = '') => `<label class="pp-field ${cls}"><span>${label}</span>${html}</label>`;
  const num = (key, v, step = 0.1, min = 0) => `<input type="number" data-prop="${key}" value="${v ?? ''}" step="${step}" min="${min}">`;

  function renderProps() {
    const box = $('#planProps');
    if (!box || !plan()) return;
    const els = selected();
    let html = '';
    if (!els.length) html = localProps();
    else if (els.length > 1) html = multiProps(els);
    else html = singleProps(els[0]);
    box.innerHTML = html;
    bindProps(box, els);
  }

  function localProps() {
    const p = plan(), bg = p.background;
    return `<h3>Local</h3>
      ${field('Nombre', `<input type="text" data-plan="name" value="${esc(p.name)}" maxlength="60">`)}
      <div class="pp-row">${field('Ancho (m)', `<input type="number" data-plan="width" value="${p.width}" step="0.5" min="2">`)}
      ${field('Fondo (m)', `<input type="number" data-plan="depth" value="${p.depth}" step="0.5" min="2">`)}</div>
      ${field('Grilla del imán', `<select data-plan="grid">${[0.1, 0.25, 0.5, 1].map(g => `<option value="${g}" ${g === p.grid ? 'selected' : ''}>${g} m</option>`).join('')}</select>`)}
      <button class="btn" id="ppPerimeter">Crear paredes en el borde del local</button>
      ${bg ? `<h3 style="margin-top:14px">Imagen de fondo</h3>
        <div class="pp-row">${field('X (m)', `<input type="number" data-bg="x" value="${bg.x || 0}" step="0.1">`)}${field('Y (m)', `<input type="number" data-bg="y" value="${bg.y || 0}" step="0.1">`)}${field('Ancho (m)', `<input type="number" data-bg="w" value="${bg.w}" step="0.1" min="0.5">`)}</div>
        ${field(`Opacidad`, `<input type="range" data-bg="opacity" min="0.1" max="1" step="0.05" value="${bg.opacity ?? 0.5}">`)}
        <div class="pp-actions"><button class="btn" id="ppMeasure">Escalar con una medida conocida</button><button class="btn danger" id="ppBgDel">Quitar imagen</button></div>` : ''}
      <p class="note">Selecciona algo para editarlo. Con Shift+clic o arrastrando sobre el piso seleccionas varios para alinearlos o moverlos juntos.</p>`;
  }

  function multiProps(els) {
    const boxes = els.filter(e => TYPES[e.type].shape === 'box');
    return `<h3>${els.length} elementos seleccionados</h3>
      <div class="pp-sub">Alinear</div>
      <div class="pp-grid3">
        <button class="btn" data-align="left">◧ Izquierda</button><button class="btn" data-align="hcenter">◫ Centro</button><button class="btn" data-align="right">◨ Derecha</button>
        <button class="btn" data-align="top">⬒ Arriba</button><button class="btn" data-align="vcenter">⊟ Medio</button><button class="btn" data-align="bottom">⬓ Abajo</button>
      </div>
      <div class="pp-sub">Distribuir y ajustar</div>
      <div class="pp-actions">
        <button class="btn" data-dist="x" ${els.length < 3 ? 'disabled' : ''}>Repartir en horizontal</button>
        <button class="btn" data-dist="y" ${els.length < 3 ? 'disabled' : ''}>Repartir en vertical</button>
        <button class="btn" id="ppSame" ${boxes.length < 2 ? 'disabled' : ''}>Igualar tamaño</button>
        <button class="btn primary" id="ppAisle" ${boxes.length !== 2 ? 'disabled' : ''} title="Selecciona 2 góndolas enfrentadas">Crear pasillo entre las 2</button>
      </div>
      <div class="pp-actions"><button class="btn" id="ppRot">Rotar 90° (R)</button><button class="btn" id="ppDup">Duplicar (Ctrl+D)</button><button class="btn danger" id="ppDel">Borrar (Supr)</button></div>`;
  }

  function singleProps(e) {
    const T = TYPES[e.type];
    let html = `<h3>${e.type === 'area' ? (e.zone_role === 'customer' ? 'Zona del cliente (caja)' : e.zone_role === 'cashier' ? 'Zona del cajero' : 'Área de análisis') : T.name}</h3>`;
    if (T.shape === 'box') {
      html += field('Nombre', `<input type="text" data-prop="label" value="${esc(e.label)}" maxlength="40">`);
      if (e.type !== 'checkout') html += field('Categoría (lo que se exhibe)', `<input type="text" data-prop="category" value="${esc(e.category)}" maxlength="40" placeholder="Ej.: Analgésicos, Bebidas, Lácteos">`);
      if (PRESETS[e.type]) html += `<div class="pp-sub">Medidas rápidas</div><div class="pp-chips">${PRESETS[e.type].map(([n, w, d], i) => `<button class="chip-btn" data-preset="${i}">${n}</button>`).join('')}</div>`;
      html += `<div class="pp-row">${field('Ancho (m)', num('w', e.w))}${field('Fondo (m)', num('d', e.d))}${field('Alto (m)', num('h', e.h))}</div>`;
      html += `<div class="pp-row">${field('X (m)', num('x', e.x, 0.1, -100))}${field('Y (m)', num('y', e.y, 0.1, -100))}${field('Rotación (°)', num('rot', e.rot || 0, 15, -360))}</div>`;
      if (e.type === 'checkout') {
        html += `<div class="pp-sub">Zona donde se para el cliente para pagar</div>
          ${field('Lado del cliente', `<select data-prop="customer_side">${Object.entries(SIDES).map(([k, v]) => `<option value="${k}" ${k === (e.customer_side || 'front') ? 'selected' : ''}>${v}</option>`).join('')}</select>`)}
          <div class="pp-row">${field('Profundidad (m)', num('zone_depth', e.zone_depth ?? 1.2))}${field('Margen a los lados (m)', num('zone_extra', e.zone_extra ?? 0.2))}</div>
          <label class="switch"><input type="checkbox" data-propbool="cashier_zone" ${e.cashier_zone !== false ? 'checked' : ''}>Zona del cajero (personal) del otro lado</label>
          ${e.cashier_zone !== false ? field('Profundidad zona del cajero (m)', num('cashier_depth', e.cashier_depth ?? 0.9)) : ''}
          <p class="note">Quien acumule el tiempo configurado en la zona <b>azul</b> cuenta como <b>pasó por esta caja</b>.
            Quien se pare en la zona <b>gris rayada</b> (detrás) se marca como <b>personal</b> y no cuenta en las estadísticas.</p>`;
      }
    } else if (T.shape === 'segment') {
      if (e.type === 'door') {
        html += field('Nombre', `<input type="text" data-prop="label" value="${esc(e.label)}" maxlength="40">`);
        html += field('Función', `<select data-prop="role">${Object.entries(DOOR_ROLES).map(([k, v]) => `<option value="${k}" ${k === (e.role || 'both') ? 'selected' : ''}>${v}</option>`).join('')}</select>`);
        html += `<label class="switch"><input type="checkbox" data-propbool="flip" ${e.flip ? 'checked' : ''}>Invertir lado interior</label>`;
        html += `<p class="note">La flecha apunta hacia adentro del local: cruzar en ese sentido es una <b>entrada</b>; al revés, una <b>salida</b>.</p>`;
      } else {
        html += `<div class="pp-row">${field('Grosor (m)', num('thickness', e.thickness, 0.05))}${field('Alto (m)', num('height', e.height, 0.1))}</div>`;
      }
      const len = e.points.slice(1).reduce((s, p, i) => s + dist(e.points[i], p), 0);
      html += `<p class="note">Largo total ${fmtM(len)} · ${e.points.length} puntos. Arrastra los círculos para mover esquinas,
        <b>doble clic</b> en el borde agrega un punto y <b>Alt+clic</b> en un punto lo borra.</p>`;
    } else if (T.shape === 'polygon') {
      html += field('Nombre', `<input type="text" data-prop="name" value="${esc(e.name)}" maxlength="40">`);
      if (!e.checkout_id) html += field('Tipo', `<select data-prop="kind">${Object.entries(AREA_KINDS).map(([k, v]) => `<option value="${k}" ${k === (e.kind || 'pasillo') ? 'selected' : ''}>${v}</option>`).join('')}</select>`);
      html += `<div class="pp-field"><span>Cámaras que miden esta área</span>${camChecks(e)}</div>`;
      if (e.checkout_id) {
        const co = byId(e.checkout_id);
        html += `<p class="note">Pertenece a <b>${esc(co?.label || 'Caja')}</b>. ${e.auto !== false ? 'Se ajusta sola cuando mueves, rotas o cambias el tamaño de la caja.' :
          'La editaste a mano: ya no sigue a la caja.'}</p>`;
        if (e.auto === false) html += '<button class="btn" id="ppAuto">Volver a la zona automática</button>';
      } else if (e.kind === 'caja') {
        html += '<p class="note"><b>Zona de cajas:</b> quien acumule aquí el tiempo configurado cuenta como "pasó por caja". Es mejor usar la herramienta <b>Caja</b>, que la crea sola en el lado correcto.</p>';
      } else if (e.kind === 'personal') {
        html += '<p class="note"><b>Zona de personal:</b> quien pase aquí el tiempo configurado (15 s por defecto) se marca como personal y no cuenta en las estadísticas.</p>';
      }
    } else if (T.shape === 'point') {
      html += field('Cámara real', `<select data-prop="camera_id"><option value="">— sin asignar —</option>${state.cameras.map(c => `<option value="${esc(c.id)}" ${c.id === e.camera_id ? 'selected' : ''}>${esc(c.name)} (${esc(c.id)})</option>`).join('')}</select>`);
      html += `<div class="pp-row">${field('Orientación (°)', num('rot', e.rot || 0, 15, -360))}${field('Apertura (°)', num('fov', e.fov || 90, 5, 10))}${field('Altura (m)', num('height', e.height ?? 2.8, 0.1))}</div>`;
      html += '<p class="note">Es la referencia visual. Lo que convierte la imagen en metros es la <b>calibración</b> (Configuración → Cámaras de la tienda).</p>';
    }
    const canDup = !e.checkout_id;
    html += `<div class="pp-actions">${T.shape === 'box' ? '<button class="btn" id="ppRot">Rotar 90° (R)</button>' : ''}
      ${canDup ? '<button class="btn" id="ppDup">Duplicar (Ctrl+D)</button>' : ''}<button class="btn danger" id="ppDel">Borrar (Supr)</button></div>`;
    return html;
  }
  function camChecks(e) {
    if (!state.cameras.length) return '<span class="note">No hay cámaras configuradas.</span>';
    return state.cameras.map(c => `<label class="radio"><input type="checkbox" data-cam-check value="${esc(c.id)}" ${(e.cameras || []).includes(c.id) ? 'checked' : ''}>${esc(c.name)}</label>`).join('')
      + '<span class="note">Sin marcar = la mide cualquier cámara calibrada que la vea.</span>';
  }

  function bindProps(box, els) {
    const e = els.length === 1 ? els[0] : null;
    const on = (sel, fn) => { const n = box.querySelector(sel); if (n) n.onclick = fn; };
    on('#ppDup', duplicate);
    on('#ppDel', removeSelected);
    on('#ppRot', () => rotateSel(90));
    on('#ppSame', sameSize);
    on('#ppAisle', aisleBetween);
    on('#ppAuto', () => { pushHistory(); e.auto = true; changed(); });
    on('#ppPerimeter', () => addRoom(0, 0, plan().width, plan().depth));
    on('#ppMeasure', () => setTool('measure'));
    on('#ppBgDel', () => { delete plan().background; changed(); });
    box.querySelectorAll('[data-align]').forEach(b => { b.onclick = () => align(b.dataset.align); });
    box.querySelectorAll('[data-dist]').forEach(b => { b.onclick = () => distribute(b.dataset.dist); });
    box.querySelectorAll('[data-preset]').forEach(b => b.addEventListener('click', () => {
      const [, w, d] = PRESETS[e.type][+b.dataset.preset];
      pushHistory(); e.w = w; e.d = d; changed();
    }));
    box.querySelectorAll('[data-prop]').forEach(inp => inp.addEventListener('change', () => {
      if (!e) return;
      pushHistory();
      const k = inp.dataset.prop;
      e[k] = inp.type === 'number' ? (inp.value === '' ? 0 : +inp.value) : inp.value;
      if (k === 'name') { e.name = String(e.name).trim() || 'Área'; e.auto_name = false; }
      changed();
    }));
    box.querySelectorAll('[data-propbool]').forEach(cb => cb.addEventListener('change', () => {
      if (!e) return;
      pushHistory(); e[cb.dataset.propbool] = cb.checked; changed();
    }));
    box.querySelectorAll('[data-cam-check]').forEach(cb => cb.addEventListener('change', () => {
      if (!e) return;
      pushHistory();
      const set = new Set(e.cameras || []);
      cb.checked ? set.add(cb.value) : set.delete(cb.value);
      e.cameras = [...set];
      changed();
    }));
    box.querySelectorAll('[data-plan]').forEach(inp => inp.addEventListener('change', () => {
      pushHistory();
      const k = inp.dataset.plan;
      plan()[k] = k === 'name' ? inp.value : +inp.value;
      if (k === 'width' || k === 'depth') fit();
      changed();
    }));
    box.querySelectorAll('[data-bg]').forEach(inp => inp.addEventListener(inp.type === 'range' ? 'input' : 'change', () => {
      plan().background[inp.dataset.bg] = +inp.value;
      redraw();
      scheduleSave();
    }));
  }

  // ------------------------------------------------------------------ pasos, capas y lista
  const STEPS = [
    { title: 'Medidas', tool: null, done: p => p.width !== 20 || p.depth !== 12 || p.elements.length > 3,
      help: 'Pon el ancho y el fondo reales del local en el panel derecho (con nada seleccionado). Si tienes un croquis o una foto del plano, cárgalo con "Imagen de fondo" para calcarlo.' },
    { title: 'Paredes y entrada', tool: 'room', done: p => p.elements.some(e => e.type === 'wall') && p.elements.some(e => e.type === 'door'),
      help: 'Con "Habitación" arrastras el contorno del local. Marca la entrada con "Entrada" y, si es otra puerta, la salida con "Salida".' },
    { title: 'Muebles', tool: 'gondola', done: p => p.elements.some(e => ['gondola', 'furniture', 'fridge', 'counter'].includes(e.type)),
      help: 'Coloca góndolas, neveras y mostradores. "Generar góndolas…" crea una fila completa con sus pasillos. Selecciona varias para alinearlas o repartirlas.' },
    { title: 'Cajas', tool: 'checkout', done: p => p.elements.some(e => e.type === 'checkout'),
      help: 'Coloca cada caja de cobro. Se crea sola la zona donde se para el CLIENTE (cuenta para "pasó por caja") y la del CAJERO (personal). Ajusta el lado del cliente en el panel.' },
    { title: 'Pasillos y áreas', tool: 'area-rect', done: p => p.elements.some(e => e.type === 'area' && !e.checkout_id),
      help: 'Marca lo que quieres medir: pasillos, cabeceras, la zona de entrada. Tip: selecciona 2 góndolas y pulsa "Crear pasillo entre las 2".' },
    { title: 'Cámaras', tool: 'camera', done: p => p.elements.some(e => e.type === 'camera'),
      help: 'Ubica cada cámara y asígnale la cámara real. Después calíbrala en Configuración → Cámaras de la tienda.' },
  ];
  let openStep = null;
  function renderSteps() {
    const box = $('#planSteps'); if (!box || !plan()) return;
    const p = plan();
    const next = STEPS.findIndex(s => !s.done(p));
    box.innerHTML = `<ol class="steps">${STEPS.map((s, i) => `<li><button class="step ${s.done(p) ? 'done' : ''} ${i === next ? 'next' : ''} ${openStep === i ? 'open' : ''}" data-step="${i}">
        <span class="n">${s.done(p) ? '✓' : i + 1}</span>${s.title}</button></li>`).join('')}</ol>
      ${openStep !== null ? `<div class="step-help"><b>${openStep + 1}. ${STEPS[openStep].title}:</b> ${STEPS[openStep].help}
        ${STEPS[openStep].tool ? `<button class="btn primary" data-steptool="${STEPS[openStep].tool}">Usar la herramienta</button>` : ''}
        <button class="btn" data-stepclose>Cerrar</button></div>` : ''}`;
    box.querySelectorAll('[data-step]').forEach(b => b.addEventListener('click', () => { openStep = openStep === +b.dataset.step ? null : +b.dataset.step; renderSteps(); }));
    box.querySelectorAll('[data-steptool]').forEach(b => b.addEventListener('click', () => setTool(b.dataset.steptool)));
    box.querySelector('[data-stepclose]')?.addEventListener('click', () => { openStep = null; renderSteps(); });
  }

  function renderLayers() {
    const box = $('#planLayers'); if (!box) return;
    box.innerHTML = Object.entries(LAYERS).map(([k, name]) => {
      const L = state.layers[k];
      return `<div class="layer-row"><span class="grow">${name}</span>
        <button class="icon-btn ${L.visible ? '' : 'off'}" data-lvis="${k}" title="${L.visible ? 'Ocultar' : 'Mostrar'}">${L.visible ? '👁' : '—'}</button>
        <button class="icon-btn ${L.locked ? 'on' : ''}" data-llock="${k}" title="${L.locked ? 'Desbloquear' : 'Bloquear (no se puede seleccionar)'}">${L.locked ? '🔒' : '🔓'}</button></div>`;
    }).join('');
    const persist = () => { try { localStorage.setItem('tqPlanLayers', JSON.stringify(state.layers)); } catch { /* */ } };
    box.querySelectorAll('[data-lvis]').forEach(b => b.addEventListener('click', () => { const L = state.layers[b.dataset.lvis]; L.visible = !L.visible; persist(); renderLayers(); pruneLockedSel(); changed(false, false); }));
    box.querySelectorAll('[data-llock]').forEach(b => b.addEventListener('click', () => { const L = state.layers[b.dataset.llock]; L.locked = !L.locked; persist(); renderLayers(); pruneLockedSel(); changed(false, false); }));
  }
  function pruneLockedSel() { for (const id of [...state.sel]) { const e = byId(id); if (!e || isLocked(e)) state.sel.delete(id); } }

  function renderList() {
    const box = $('#planList'); if (!box || !plan()) return;
    const groups = { structure: [], furniture: [], areas: [], cameras: [] };
    for (const e of plan().elements) groups[layerOf(e)].push(e);
    const label = e => e.type === 'area' ? e.name : e.type === 'door' ? (e.label || 'Puerta') : e.type === 'wall' ? `Pared (${e.points.length - 1} tramos)` :
      e.type === 'divider' ? 'Divisor' : e.type === 'camera' ? (state.cameras.find(c => c.id === e.camera_id)?.name || 'Cámara sin asignar') : (e.label || TYPES[e.type].name);
    const swatch = e => e.type === 'area' ? AREA_COLORS[e.kind || 'pasillo'] : BOX_FILL[e.type] || (e.type === 'door' ? DOOR_COLORS[e.role || 'both'] : '#8A8F98');
    $('#planCount').textContent = `(${plan().elements.length})`;
    box.innerHTML = Object.entries(groups).filter(([, a]) => a.length).map(([k, arr]) => `
      <details ${k === 'areas' || k === 'furniture' ? 'open' : ''}><summary>${LAYERS[k]} <small>${arr.length}</small></summary>
        <ul>${arr.map(e => `<li data-el="${e.id}" class="${state.sel.has(e.id) ? 'sel' : ''}"><span class="swatch" style="background:${swatch(e)}"></span>
          <span class="grow">${esc(label(e))}</span><small>${e.type === 'area' ? esc(AREA_KINDS[e.kind || 'pasillo'].split(' (')[0]) : esc(e.category || '')}</small></li>`).join('')}</ul></details>`).join('')
      || '<p class="empty">El plano está vacío. Empieza por el paso 1.</p>';
    box.querySelectorAll('[data-el]').forEach(li => li.addEventListener('click', ev => {
      const id = li.dataset.el;
      if (ev.shiftKey) state.sel.has(id) ? state.sel.delete(id) : state.sel.add(id); else state.sel = new Set([id]);
      changed(false, false);
    }));
  }

  // ------------------------------------------------------------------ imagen de fondo
  function loadBackground(file) {
    if (!file) return;
    const img = new Image();
    img.onload = () => {
      const max = 2000, k = Math.min(1, max / Math.max(img.width, img.height));
      const cv = document.createElement('canvas');
      cv.width = Math.round(img.width * k); cv.height = Math.round(img.height * k);
      cv.getContext('2d').drawImage(img, 0, 0, cv.width, cv.height);
      const data = cv.toDataURL('image/jpeg', 0.82);
      plan().background = { data, x: 0, y: 0, w: plan().width, aspect: cv.height / cv.width, opacity: 0.5 };
      state.layers.background.visible = true;
      state.sel.clear();
      changed();
      URL.revokeObjectURL(img.src);
      window.tqToast?.('Imagen cargada. Escálala con "Escalar con una medida conocida" en el panel derecho.');
    };
    img.onerror = () => window.tqToast?.('No se pudo leer la imagen. Usa JPG o PNG.', true);
    img.src = URL.createObjectURL(file);
  }
  async function finishMeasure() {
    const [a, b] = state.draft.points;
    state.draft = null;
    setTool('select');
    const measured = dist(a, b), bg = plan().background;
    if (!bg || measured < 0.05) return;
    const real = parseFloat(String(await window.tqAsk('Medida real', { text: `Marcaste ${fmtM(measured)} en el plano. ¿Cuántos metros mide en la realidad?`, value: '' }) || '').replace(',', '.'));
    if (!(real > 0)) return;
    const k = real / measured;
    // escalar la imagen manteniendo fijo el primer punto marcado
    bg.x = r2(a[0] - (a[0] - (bg.x || 0)) * k);
    bg.y = r2(a[1] - (a[1] - (bg.y || 0)) * k);
    bg.w = r2(bg.w * k);
    changed();
    window.tqToast?.('Imagen escalada. Ahora puedes calcar las paredes y muebles encima.');
  }

  // ------------------------------------------------------------------ plantillas
  function walls(W, D, gap) {
    const [g0, g1] = gap;
    return [{ id: uid(), type: 'wall', thickness: 0.15, height: 3, points: [[g1, D], [W, D], [W, 0], [0, 0], [0, D], [g0, D]] }];
  }
  const door = (a, b, role, label) => ({ id: uid(), type: 'door', points: [a, b], role, label, flip: false });
  const gond = (x, y, w, d, cat, i) => ({ id: uid(), type: 'gondola', x, y, w, d, h: 1.8, rot: 0, label: `Góndola ${i}`, category: cat });
  const co = (x, y, i, side = 'front', rot = 0) => ({ id: uid(), type: 'checkout', x, y, w: 1.4, d: 0.7, h: 1, rot, label: `Caja ${i}`, category: '',
    customer_side: side, zone_depth: 1.2, zone_extra: 0.2, cashier_zone: true, cashier_depth: 0.9 });
  const area = (name, kind, x0, y0, x1, y1) => ({ id: uid(), type: 'area', name, kind, cameras: [], points: [[x0, y0], [x1, y0], [x1, y1], [x0, y1]] });
  const TEMPLATES = [
    { name: 'Local vacío', desc: 'Solo paredes y una entrada.', w: null, d: null, build: (W, D) => [...walls(W, D, [W / 2 - 1.5, W / 2 + 1.5]), door([W / 2 - 1.5, D], [W / 2 + 1.5, D], 'both', 'Entrada')] },
    { name: 'Farmacia pequeña', desc: '10 × 8 m · mostrador con zona de personal, 2 cajas, 3 góndolas y una nevera.', w: 10, d: 8, build: (W, D) => [
      ...walls(W, D, [4, 6.5]), door([4, D], [6.5, D], 'both', 'Entrada'),
      { id: uid(), type: 'counter', x: 5, y: 1.2, w: 6, d: 0.7, h: 1.1, rot: 0, label: 'Mostrador', category: 'Medicamentos' },
      area('Detrás del mostrador', 'personal', 2, 0.15, 8, 0.85), area('Frente al mostrador', 'mostrador', 2, 1.55, 8, 2.8),
      gond(2, 4.8, 0.9, 3, 'Cuidado personal', 1), gond(4.6, 4.8, 0.9, 3, 'Bebés', 2), gond(7.2, 4.8, 0.9, 3, 'Vitaminas', 3),
      { id: uid(), type: 'fridge', x: 9.4, y: 4.5, w: 0.8, d: 2, h: 2, rot: 0, label: 'Nevera', category: 'Bebidas' },
      co(1.5, 7, 1, 'back'), co(8.5, 7, 2, 'back'),
      area('Pasillo 1', 'pasillo', 2.45, 3.3, 4.15, 6.3), area('Pasillo 2', 'pasillo', 5.05, 3.3, 6.75, 6.3)] },
    { name: 'Minimercado', desc: '20 × 12 m · 6 góndolas con pasillos, neveras al fondo, 3 cajas y salida separada.', w: 20, d: 12, build: (W, D) => {
      const els = [...walls(W, D, [2, 5]), door([2, D], [5, D], 'entry', 'Entrada'), door([15, D], [18, D], 'exit', 'Salida')];
      for (let i = 0; i < 6; i++) els.push(gond(4 + i * 2.4, 4.5, 0.9, 5, '', i + 1));
      for (let i = 0; i < 5; i++) els.push(area(`Pasillo ${i + 1}`, 'pasillo', 4.45 + i * 2.4, 2, 5.95 + i * 2.4, 7));
      els.push(area('Pasillo de neveras', 'pasillo', 1, 1, 19, 1.9));
      for (let i = 0; i < 4; i++) els.push({ id: uid(), type: 'fridge', x: 3 + i * 4.5, y: 0.55, w: 3.5, d: 0.8, h: 2, rot: 0, label: `Nevera ${i + 1}`, category: ['Lácteos', 'Bebidas', 'Carnes', 'Congelados'][i] });
      for (let i = 0; i < 3; i++) els.push(co(9.5 + i * 3, 9.5, i + 1, 'front'));
      return els;
    } },
  ];
  function openTemplates() {
    $('#tplList').innerHTML = TEMPLATES.map((t, i) => `<button class="tpl" data-tpl="${i}"><b>${t.name}</b><span>${t.desc}</span></button>`).join('');
    $('#tplList').querySelectorAll('[data-tpl]').forEach(b => b.addEventListener('click', () => {
      const t = TEMPLATES[+b.dataset.tpl];
      pushHistory();
      if (t.w) { plan().width = t.w; plan().depth = t.d; }
      plan().elements = t.build(plan().width, plan().depth);
      state.sel.clear();
      $('#tplDialog').close();
      fit();
      changed();
      window.tqToast?.(`Plantilla "${t.name}" aplicada. Ajusta medidas y nombres a tu local (Ctrl+Z para deshacer).`);
    }));
    $('#tplDialog').showModal();
  }

  // ------------------------------------------------------------------ generador de góndolas
  function generate(ev) {
    ev.preventDefault();
    const f = new FormData($('#genForm'));
    const n = Math.max(1, Math.min(40, +f.get('n'))), len = +f.get('len'), gw = +f.get('gw'), aisle = +f.get('aisle');
    const x0 = +f.get('x0'), y0 = +f.get('y0'), h = +f.get('h'), vertical = f.get('dir') === 'v';
    const outer = f.get('outer') === 'on', makeAreas = f.get('areas') === 'on', cat = (f.get('cat') || '').trim();
    pushHistory();
    let k = plan().elements.filter(e => e.type === 'area' && !e.checkout_id).length + 1;
    const els = [], step = gw + aisle;
    for (let i = 0; i < n; i++) {
      const off = i * step;
      els.push({ id: uid(), type: 'gondola', x: r2(vertical ? x0 + off + gw / 2 : x0 + len / 2), y: r2(vertical ? y0 + len / 2 : y0 + off + gw / 2),
                 w: r2(vertical ? gw : len), d: r2(vertical ? len : gw), h, rot: 0, label: `Góndola ${i + 1}`, category: cat ? `${cat} ${i + 1}` : '' });
    }
    if (makeAreas) {
      const rect = off => vertical ? [[x0 + off, y0], [x0 + off + aisle, y0], [x0 + off + aisle, y0 + len], [x0 + off, y0 + len]]
        : [[x0, y0 + off], [x0 + len, y0 + off], [x0 + len, y0 + off + aisle], [x0, y0 + off + aisle]];
      const offs = [];
      if (outer) offs.push(-aisle);
      for (let i = 0; i < n - 1; i++) offs.push(i * step + gw);
      if (outer) offs.push((n - 1) * step + gw);
      for (const off of offs) {
        const p = rect(off).map(([x, y]) => [r2(Math.max(0, Math.min(plan().width, x))), r2(Math.max(0, Math.min(plan().depth, y)))]);
        els.push({ id: uid(), type: 'area', name: `Pasillo ${k++}`, kind: 'pasillo', cameras: [], points: p });
      }
    }
    plan().elements.push(...els);
    $('#genDialog').close();
    state.sel = new Set(els.filter(e => e.type === 'gondola').map(e => e.id));
    changed();
    window.tqToast?.(`Se crearon ${n} góndolas${makeAreas ? ' y sus pasillos' : ''}. Quedaron seleccionadas: arrástralas para ubicarlas.`);
  }

  // ------------------------------------------------------------------ barra de herramientas y ayuda
  function renderTools() {
    const box = $('#planTools'); if (!box) return;
    let group = '';
    box.innerHTML = TOOLS.map(([id, name, key, g, icon]) => {
      const head = g !== group ? `<div class="tool-group">${g}</div>` : '';
      group = g;
      return `${head}<button class="tool" data-ptool="${id}" title="${name} (${key})">
        <svg viewBox="0 0 16 16" aria-hidden="true"><path d="${icon}"/></svg><span>${name}</span><kbd>${key}</kbd></button>`;
    }).join('');
    box.querySelectorAll('[data-ptool]').forEach(b => b.addEventListener('click', () => setTool(b.dataset.ptool)));
  }
  function openHelp() {
    $('#planHelpList').innerHTML = TOOLS.map(([, name, key]) => `<span><kbd>${key}</kbd> ${name}</span>`).join('') +
      ['Ctrl+Z / Ctrl+Y · deshacer / rehacer', 'Ctrl+C / Ctrl+V · copiar / pegar', 'Ctrl+D · duplicar', 'Ctrl+A · seleccionar todo',
       'R · rotar 90° (Shift+R al revés)', 'Flechas · mover 10 cm (Shift = 1 m)', 'Supr · borrar', 'Esc · terminar / soltar'].map(t => `<span>${t}</span>`).join('');
    $('#planHelp').showModal();
  }

  // ------------------------------------------------------------------ carga e inicio
  async function loadCameras() {
    try {
      const [cams, fps] = await Promise.all([fetch('/api/cams').then(r => r.json()), fetch('/api/cams/footprints').then(r => r.json())]);
      state.cameras = cams.cameras;
      state.footprints = fps;
    } catch { /* sin cámaras el editor sigue funcionando */ }
  }
  async function load() {
    state.plan = await (await fetch('/api/floorplan')).json();
    await loadCameras();
    state.history = []; state.future = [];
    const before = JSON.stringify(state.plan.elements);
    syncCheckoutZones();
    fit();
    changed(false, false);
    if (JSON.stringify(state.plan.elements) !== before) {
      scheduleSave(); // cajas sin sus zonas (planos de versiones anteriores): se guardan ya creadas
      window.tqToast?.('Se crearon las zonas del cliente y del cajero de cada caja.');
    } else setStatus('Guardado ✓');
  }

  function init() {
    const s = svg(); if (!s || s.dataset.ready) return;
    s.dataset.ready = '1';
    renderTools();
    renderLayers();
    s.addEventListener('pointerdown', onDown);
    s.addEventListener('pointermove', onMove);
    s.addEventListener('pointerup', onUp);
    s.addEventListener('dblclick', onDblClick);
    s.addEventListener('wheel', onWheel, { passive: false });
    s.addEventListener('contextmenu', ev => { if (state.draft?.kind === 'points') { ev.preventDefault(); finishDraft(); } });
    window.addEventListener('keydown', onKey);
    window.addEventListener('keyup', ev => { if (ev.key === ' ') state.space = false; });
    $('#planUndo').onclick = undo;
    $('#planRedo').onclick = redo;
    $('#planFit').onclick = fit;
    $('#planZoomIn').onclick = () => zoomBy(1 / 1.25);
    $('#planZoomOut').onclick = () => zoomBy(1.25);
    $('#planSnap').addEventListener('change', e => { state.snap = e.target.checked; });
    $('#planGen').onclick = () => $('#genDialog').showModal();
    $('#genForm').addEventListener('submit', generate);
    $('#genCancel').onclick = () => $('#genDialog').close();
    $('#planTemplates').onclick = openTemplates;
    $('#tplCancel').onclick = () => $('#tplDialog').close();
    $('#planBgBtn').onclick = () => $('#planBgFile').click();
    $('#planBgFile').addEventListener('change', e => { loadBackground(e.target.files[0]); e.target.value = ''; });
    $('#planHelpBtn').onclick = openHelp;
    $('#planHelpClose').onclick = () => $('#planHelp').close();
    window.addEventListener('beforeunload', ev => { if (state.dirty) { save(); ev.preventDefault(); } });
    setTool('select');
    load();
  }

  document.addEventListener('tq:view', ev => { if (ev.detail === 'plan') { init(); if (state.plan) loadCameras().then(() => changed(false, false)); } });
  document.addEventListener('tq:cameras', () => { loadCameras().then(() => { if (state.plan) changed(false, false); }); });

  window.TQPlan = { render, heatColor, AREA_COLORS, TYPES, boxCorners, svgPoint, checkoutZonePolys, get plan() { return state.plan; }, reload: load };
})();
