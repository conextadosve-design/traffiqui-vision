/* Traffiqui · dibujo del plano de una sede en SVG (metros), con personas en vivo o mapa de calor */
'use strict';

window.tqPlan = (() => {
  const NS = 'http://www.w3.org/2000/svg';
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const BOX_FILL = { gondola: 'var(--plan-box)', furniture: 'var(--plan-box)', counter: 'var(--plan-box)',
                     fridge: 'var(--plan-fridge)', checkout: 'var(--plan-checkout)' };

  function pts(points) { return points.map(p => `${p[0]},${p[1]}`).join(' '); }

  function centroid(points) {
    const n = points.length;
    return [points.reduce((a, p) => a + p[0], 0) / n, points.reduce((a, p) => a + p[1], 0) / n];
  }

  /**
   * svg: elemento <svg>; plan: {width, depth, elements}; opts:
   *   areas  {nombre: personas dentro}  → colorea las áreas (en vivo)
   *   people [{x, y, color, staff}]     → un punto por persona
   *   heat   {rows, cols, cell_m, values} → mapa de calor (0–1)
   */
  function draw(svg, plan, opts = {}) {
    if (!plan) {
      svg.setAttribute('viewBox', '0 0 20 8');
      svg.innerHTML = '<text x="10" y="4" font-size="0.6" text-anchor="middle" fill="var(--muted)">La tienda todavía no envió su plano.</text>';
      return;
    }
    const W = plan.width || 20, D = plan.depth || 12, m = 0.4;
    svg.setAttribute('viewBox', `${-m} ${-m} ${W + 2 * m} ${D + 2 * m}`);
    svg.style.aspectRatio = `${W + 2 * m} / ${D + 2 * m}`;   // sin esto el navegador lo deja en 300 × 150
    const out = [`<rect x="0" y="0" width="${W}" height="${D}" fill="var(--plan-floor)"/>`];

    if (opts.heat) {
      const { rows, cols, cell_m: c, values } = opts.heat;
      for (let r = 0; r < rows; r++) for (let k = 0; k < cols; k++) {
        const v = values[r * cols + k];
        if (v > 0.02) out.push(`<rect x="${k * c}" y="${r * c}" width="${c + 0.01}" height="${c + 0.01}" fill="var(--plan-heat)" fill-opacity="${Math.min(0.9, 0.12 + v * 0.8).toFixed(2)}"/>`);
      }
    }
    const els = plan.elements || [];
    for (const e of els.filter(e => e.type === 'area')) {
      const inside = opts.areas ? (opts.areas[e.name] || 0) : null;
      const busy = inside ? Math.min(0.55, 0.12 + inside * 0.08) : 0;
      out.push(`<polygon points="${pts(e.points)}" fill="${inside ? 'var(--plan-busy)' : 'none'}" fill-opacity="${busy.toFixed(2)}"
        stroke="var(--plan-area)" stroke-width="0.04" stroke-dasharray="0.15 0.1"/>`);
    }
    for (const e of els) {
      if (e.type === 'wall' || e.type === 'divider') {
        out.push(`<polyline points="${pts(e.points)}" fill="none" stroke="var(--plan-wall)" stroke-width="${e.type === 'wall' ? Math.max(0.1, e.thickness || 0.15) : 0.08}" stroke-linejoin="round"/>`);
      } else if (e.type === 'door') {
        out.push(`<polyline points="${pts(e.points)}" fill="none" stroke="var(--brass)" stroke-width="0.22" stroke-linecap="round"/>`);
      } else if (BOX_FILL[e.type]) {
        out.push(`<rect x="${-e.w / 2}" y="${-e.d / 2}" width="${e.w}" height="${e.d}" rx="0.05" fill="${BOX_FILL[e.type]}"
          stroke="var(--plan-wall)" stroke-width="0.03" transform="translate(${e.x} ${e.y}) rotate(${e.rot || 0})"/>`);
      }
    }
    for (const e of els.filter(e => e.type === 'area')) {
      const [cx, cy] = centroid(e.points);
      const inside = opts.areas ? opts.areas[e.name] : null;
      out.push(`<text x="${cx}" y="${cy}" font-size="0.32" text-anchor="middle" fill="var(--text)" opacity="0.8">${esc(e.name)}${inside ? ` · ${inside}` : ''}</text>`);
    }
    for (const p of (opts.people || [])) {
      out.push(p.staff
        ? `<circle cx="${p.x}" cy="${p.y}" r="0.22" fill="none" stroke="var(--muted)" stroke-width="0.07"/>`
        : `<circle cx="${p.x}" cy="${p.y}" r="0.24" fill="${esc(p.color)}" stroke="var(--surface)" stroke-width="0.06"/>`);
    }
    svg.innerHTML = out.join('');
  }

  return { draw };
})();
