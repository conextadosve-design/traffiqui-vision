/* Sede principal: guía de bienvenida (la primera vez) y botón «?» para verla de nuevo. Usa /vendor/ui.js. */
'use strict';
(function () {
  const STEPS = [
    { icon: 'tienda', title: 'Bienvenido a la sede principal',
      text: 'Aquí ves todas tus tiendas juntas: cuántas personas entran, cuántas pasan por caja y cómo va cada sede comparada con la semana anterior.' },
    { icon: 'casa', title: 'Resumen',
      text: 'Arriba, los totales de todas las sedes y las alertas. Abajo, el ranking de sedes. Elige hoy, la semana o el mes con los botones de arriba.' },
    { icon: 'vivo', title: 'Cada sede, en vivo',
      text: 'Toca el nombre de una sede para ver su plano con las personas en tiempo real, sus cámaras y cajas, y toda su analítica.' },
    { icon: 'campana', title: 'Alertas',
      text: 'Si una tienda supera el aforo, tiene fila larga en caja, una cámara deja de ver o la sede deja de enviar datos, aparece un aviso arriba del Resumen.' },
    { icon: 'ajustes', title: 'Administrar',
      text: 'Crea las sedes y copia su clave para conectarlas, agrega usuarios (gerencia o encargados), pega tu licencia y revisa las copias de seguridad.' },
    { icon: 'movil', title: 'También en tu teléfono',
      text: 'Instala Tailscale en el teléfono con la misma cuenta, abre la dirección de este PC y usa «Añadir a pantalla de inicio»: tendrás Traffiqui como una app más.' },
  ];
  const btn = document.getElementById('helpBtn');
  if (btn) btn.onclick = () => TQ.tour.open(STEPS);
  setTimeout(() => TQ.tour('sede', STEPS), 700);
})();
