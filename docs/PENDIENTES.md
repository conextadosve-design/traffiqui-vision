# Pendientes

Estado al 23-10-2026: `main` incluye los pull requests #2 (multisede, instalador, licencias) y #3 (detector
D-FINE, fase 2, alertas, copias, cuentas). 118 pruebas automáticas pasan; el instalador de Windows se genera
y se prueba solo en GitHub Actions (138 MB completo, 2 MB la actualización).

## Hecho recientemente

| Fecha | Qué | Dónde |
|---|---|---|
| 23-10-2026 | Interfaz rediseñada: ventana propia de Windows, pestañas por tarea, panel de la sede principal cómodo en el teléfono y guía de bienvenida | `app/static/`, `cloud/static/`, `app/launcher.py` |
| 23-10-2026 | En vivo automático: cada 3 s solo mientras alguien mira la sede, si no cada 30 s (~82 % menos peticiones) | `cloud/live.py`, `app/cloud_sync.py` |
| 23-10-2026 | Detector D-FINE (Apache-2.0) en ONNX: más preciso que YOLO11n y sin PyTorch ni Ultralytics | README §6, `tools/detector/` |
| 23-10-2026 | Fase 2 de la multisede: en vivo cada 3 s y analítica completa de cada sede desde la sede principal | `cloud/live.py`, `cloud/site_reports.py` |
| 23-10-2026 | Salud de cámaras: sin señal, tapada o movida, con "Aceptar posición" | `app/vision/health.py` |
| 23-10-2026 | Comparativas en % contra la semana anterior y el mismo día del mes pasado | `cloud/reports.py` |
| 23-10-2026 | Alertas: aforo, fila en caja (opcional), cámara y sede sin enviar datos, con historial | `app/alerts.py`, `cloud/live.py` |
| 23-10-2026 | Copias de seguridad diarias (7 diarias + 4 semanales) con carpeta extra opcional | `app/backup.py` |
| 23-10-2026 | Límite de intentos de inicio de sesión y recuperación de contraseña | `cloud/cuentas.py` |
| 23-10-2026 | Instalador en dos partes: base pesada + código; actualizaciones de pocos MB | `packaging/` |
| 22-10-2026 | Multisede (fase 1), todo local con Tailscale, instalador con modo tienda / sede principal, licencias firmadas | PR #2 |

## Antes de vender

- [x] **Licencia del detector**: cambiado a D-FINE (Apache-2.0) en ONNX; mejor precisión que YOLO11n (README, sección 6).
- [ ] **Medir la precisión en la tienda beta** (conteo manual contra el sistema) con el detector nuevo.
- [ ] **Términos de uso, política de privacidad y cartel** de aviso de cámaras para las tiendas.
- [ ] **Condiciones de la beta por escrito**: "gratis de por vida" solo para la tienda beta.
- [ ] **Alinear el PDF de invitación** con lo construido (PC en la tienda, Tailscale, "pasaron por caja").

## Distribución como programa de Windows (.exe)

- [x] **Instalador**: PyInstaller + Inno Setup, generado por GitHub Actions (ver `docs/INSTALACION.md`).
      Arranque automático al encender el PC, sin ventana de terminal (icono en la bandeja).
- [ ] **Clave pública de licencias**: Andrés ejecuta `python -m cloud.licencia crear-claves` una vez y sube
      `cloud/licencia_publica.txt`. Sin ella, los instaladores solo permiten 1 sede por empresa.
- [ ] **Probar el instalador en un PC real** de tienda y de sede principal (cámaras, Tailscale, firewall).
- [x] **Separar base pesada y código**: base (Python, librerías, modelos) + `codigo\`; instalador de
      actualización de pocos MB con control de versión de la base (`packaging/BASE_VERSION`). Sin PyTorch.
- [x] **Datos fuera del programa**: `C:\ProgramData\Traffiqui`; actualizar o reinstalar no borra nada.
      Las bases se migran solas al arrancar.
- [x] **Copias de seguridad** automáticas diarias (tienda y sede principal), con carpeta extra opcional.
- [ ] **Asistente guiado** en la tienda: cámara → plano → puerta → cajas → prueba de conteo.
- [ ] **Diagnóstico de conexión** con la sede principal (Tailscale, clave, firewall) con mensajes claros.

## Licencias

- [x] **Licencia de sedes firmada** (Ed25519): número de sedes por empresa y fecha de vencimiento opcional;
      se pega en el panel de la sede principal (`cloud/licencia.py`, `docs/INSTALACION.md`).
- [ ] **Suspender a distancia**: con todo local no hay un servidor de Traffiqui al que preguntar. Mientras
      tanto, licencias con vencimiento (`--vence`) que se renuevan al pagar: si no se renuevan, al vencer
      la empresa vuelve a 1 sede. Si se quiere apagar del todo, hará falta un servidor de licencias en internet.
- [ ] **Aviso de vencimiento** en el panel de la sede principal desde 15 días antes: "Tu licencia vence en N días,
      contacta con Andrés Sandoval (0412 755 9087)".
- [ ] **Periodo de gracia** de unos días tras el vencimiento antes de limitar las sedes, por si el pago se retrasa.
- [ ] **Registro de licencias emitidas**: cada `python -m cloud.licencia emitir` se anota en un Excel/CSV en el PC del
      administrador (empresa, sedes, vencimiento, fecha de emisión) para llevar el control de renovaciones.
- [ ] **Licencia en las tiendas**: hoy una tienda funciona sola sin licencia (solo el envío a la sede
      principal está limitado). Decidir si la app de tienda también debe pedir licencia.

## Reportes (fase 3 de la multisede)

- [ ] **Resumen automático por correo**: diario, semanal o mensual, cada usuario elige; usa el correo saliente
      que ya se configura en *Sedes y usuarios*.
- [ ] **Excel consolidado**: hoja de resumen + una hoja por sede, para el rango elegido.
- [ ] **Conversión real**: subir las ventas por hora (Excel) y calcular ventas ÷ visitas.

## Alertas

- [x] Aforo, fila en caja (opcional), cámara sin señal / tapada / movida y sede sin enviar datos, con historial.
- [ ] Avisos de alertas por correo o WhatsApp (hoy se ven en el panel).

## Actualizaciones automáticas

- [x] **Actualizaciones de pocos MB** (`Traffiqui-Actualizacion-x.y.z.exe`): se instalan a mano por ahora.
- [ ] **Comprobar versión nueva** y descargar en segundo plano; instalación fuera de horario.
- [ ] **Vuelta atrás automática** a la versión anterior si la nueva no arranca.
- [ ] **Firma de las actualizaciones** con clave propia (la app rechaza lo que no esté firmado).
      Certificado de firma de código para evitar el aviso de Windows (~100–300 USD/año).
- [ ] **Canales beta y estable**; ver desde el panel qué versión tiene cada tienda.
- [x] **Publicación automática** con GitHub Actions al crear una etiqueta `v…` (Release con el instalador).

## Acceso remoto

- [x] Las tiendas envían sus cifras a la sede principal por Tailscale.
- [x] Vista completa de cada tienda desde la sede principal (en vivo y analítica): fase 2 de la multisede.
- [ ] Tienda 3D de cada sede desde la sede principal (hoy se ve el plano 2D en vivo y el mapa de calor).
- [ ] Ver el vídeo de una cámara desde la sede principal (hoy, a propósito, solo viajan números).
- [x] Panel de la sede principal pensado para el teléfono (pestañas abajo, tablas en tarjetas) e instalable con «Añadir a pantalla de inicio».
- [ ] Notificaciones en el teléfono (requiere HTTPS: llegará con el panel en la nube).

## Cuentas y seguridad

- [x] Límite de intentos de inicio de sesión (5 por correo, 20 por IP, 15 min).
- [x] Recuperación de contraseña: código de recuperación, enlace por correo (SMTP opcional) y reseteo por la sede principal.
- [ ] Registro de actividad: quién cambió qué y cuándo.

## Repositorio

- [ ] **Pull request #1** (`scripts/setup_cloud.sh`, PyPI si download.pytorch.org está bloqueado): ya no aplica
      porque el proyecto no usa PyTorch y choca con `main`. Cerrarlo sin fusionar.
