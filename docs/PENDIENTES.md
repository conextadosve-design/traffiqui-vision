# Pendientes

## Antes de vender

- [ ] **Licencia del detector**: Ultralytics YOLO11 es AGPL-3.0 (ver README, sección 13). Para vender Traffiqui hay
      que comprar la licencia empresarial de Ultralytics o cambiar a un detector Apache-2.0 (YOLOX, RTMDet, RT-DETR).

## Distribución como programa de Windows (.exe)

- [ ] **Instalador**: empaquetar con Nuitka (o PyInstaller) y crear el instalador con Velopack / Inno Setup.
      Arranque automático al encender el PC, sin ventana de terminal.
- [ ] **Separar base pesada y código**: Python + OpenVINO/PyTorch + modelo se instalan una vez;
      las actualizaciones solo traen el código (pocos MB). Valorar usar solo OpenVINO para reducir tamaño.
- [ ] **Datos fuera del programa**: base de datos, plano, cámaras y configuración en `C:\ProgramData\Traffiqui`,
      para que actualizar o reinstalar no borre nada. Migraciones de la base al arrancar.

## Licencias

- [ ] **Servidor de licencias** en la nube con panel: cada tienda activa / suspendida.
- [ ] **Comprobación en la app** al arrancar y cada pocas horas. Licencia firmada (Ed25519) con caducidad
      de unos días, para que una caída de internet no apague el sistema.
- [ ] **Pantalla de licencia suspendida** con el contacto (Andrés Sandoval, 0412 755 9087). Los datos guardados se conservan.
- [ ] **Condiciones por escrito** de cuándo se suspende una licencia, coherentes con el "acceso gratis de por vida"
      prometido a la tienda beta. Ajustar el PDF: la app se conecta a internet solo para validar la licencia.

## Actualizaciones automáticas

- [ ] **Comprobar versión nueva** junto con la licencia; descarga en segundo plano e instalación fuera de horario.
- [ ] **Vuelta atrás automática** a la versión anterior si la nueva no arranca.
- [ ] **Firma de las actualizaciones** con clave propia (la app rechaza lo que no esté firmado).
      Certificado de firma de código para evitar el aviso de Windows (~100–300 USD/año).
- [ ] **Canales beta y estable**; ver desde el panel qué versión tiene cada tienda.
- [ ] **Publicación automática** con GitHub Actions al crear una versión.

## Acceso remoto

- [ ] Ver el panel de cada tienda en remoto (Tailscale o Cloudflare Tunnel) o enviar resúmenes de cifras al servidor.
