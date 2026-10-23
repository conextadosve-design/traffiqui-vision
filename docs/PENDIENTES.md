# Pendientes

## Antes de vender

- [x] **Licencia del detector**: cambiado a D-FINE (Apache-2.0) en ONNX; mejor precisión que YOLO11n (README, sección 6).
- [ ] **Medir la precisión en la tienda beta** (conteo manual contra el sistema) con el detector nuevo.

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
- [ ] **Condiciones por escrito** de cuándo se suspende o vence una licencia, coherentes con el "acceso gratis
      de por vida" prometido a la tienda beta.

## Actualizaciones automáticas

- [ ] **Comprobar versión nueva** junto con la licencia; descarga en segundo plano e instalación fuera de horario.
- [ ] **Vuelta atrás automática** a la versión anterior si la nueva no arranca.
- [ ] **Firma de las actualizaciones** con clave propia (la app rechaza lo que no esté firmado).
      Certificado de firma de código para evitar el aviso de Windows (~100–300 USD/año).
- [ ] **Canales beta y estable**; ver desde el panel qué versión tiene cada tienda.
- [x] **Publicación automática** con GitHub Actions al crear una etiqueta `v…` (Release con el instalador).

## Acceso remoto

- [x] Las tiendas envían sus cifras a la sede principal por Tailscale.
- [x] Vista completa de cada tienda desde la sede principal (en vivo y analítica): fase 2 de la multisede.
- [ ] Ver el vídeo de una cámara desde la sede principal (hoy, a propósito, solo viajan números).

## Cuentas y seguridad

- [x] Límite de intentos de inicio de sesión (5 por correo, 20 por IP, 15 min).
- [x] Recuperación de contraseña: código de recuperación, enlace por correo (SMTP opcional) y reseteo por la sede principal.

## Alertas

- [x] Aforo, fila en caja (opcional), cámara sin señal / tapada / movida y sede sin enviar datos, con historial.
- [ ] Avisos de alertas por correo o WhatsApp (hoy se ven en el panel).
