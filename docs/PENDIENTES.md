# Pendientes

## Antes de vender

- [ ] **Licencia del detector**: Ultralytics YOLO11 es AGPL-3.0 (ver README, sección 13). Para vender Traffiqui hay
      que comprar la licencia empresarial de Ultralytics o cambiar a un detector Apache-2.0 (YOLOX, RTMDet, RT-DETR).

## Distribución como programa de Windows (.exe)

- [x] **Instalador**: PyInstaller + Inno Setup, generado por GitHub Actions (ver `docs/INSTALACION.md`).
      Arranque automático al encender el PC, sin ventana de terminal (icono en la bandeja).
- [ ] **Clave pública de licencias**: Andrés ejecuta `python -m cloud.licencia crear-claves` una vez y sube
      `cloud/licencia_publica.txt`. Sin ella, los instaladores solo permiten 1 sede por empresa.
- [ ] **Probar el instalador en un PC real** de tienda y de sede principal (cámaras, Tailscale, firewall).
- [ ] **Separar base pesada y código**: Python + OpenVINO/PyTorch + modelo se instalan una vez;
      las actualizaciones solo traen el código (pocos MB). Valorar usar solo OpenVINO para reducir tamaño.
- [x] **Datos fuera del programa**: `C:\ProgramData\Traffiqui`; actualizar o reinstalar no borra nada.
      Las bases se migran solas al arrancar.
- [ ] **Copias de seguridad** automáticas de `C:\ProgramData\Traffiqui` en la sede principal.

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
- [ ] Ver el panel completo de una tienda (cámaras, plano) desde la sede principal: fase 2 de la multisede.
