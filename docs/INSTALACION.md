# Instalación con Traffiqui-Setup.exe

Un solo instalador para todos los PCs. Al instalar se elige qué es ese PC:

| Modo | Dónde | Qué hace | Panel |
|---|---|---|---|
| **Tienda** | PC de cada tienda, con las cámaras | Cuenta personas y envía sus números a la sede principal | http://localhost:8000 |
| **Sede principal** | PC de gerencia / marketing | Recibe los datos de todas las tiendas y los muestra juntos | http://localhost:9000 |

Nada se publica en internet: las tiendas llegan al PC de la sede principal por **Tailscale**, una red
privada cifrada. Solo los equipos que agregues a esa red pueden verlo.

```
 Tienda Chacao ─┐
 Tienda Altamira ┼──  Tailscale (red privada)  ──  PC de la sede principal  ◄── gerencia y marketing
 Tienda …       ─┘
```

## 1. Conseguir el instalador

GitHub → pestaña **Actions** → **Instalador de Windows** → **Run workflow**. Tarda unos 15–20 minutos.
Al terminar, abre la ejecución y descarga en la sección *Artifacts* (vienen en .zip):

| Archivo | Para qué |
|---|---|
| **Traffiqui-Setup-x.y.z.exe** | Instalar por primera vez (o cuando una actualización pida la "base" nueva). Unos 150–250 MB. |
| **Traffiqui-Actualizacion-x.y.z.exe** | Actualizar un PC que ya tiene Traffiqui: solo cambia el código (pocos MB). Conserva datos y configuración. |

El programa instalado tiene dos partes: la **base** (Python, librerías y modelos, casi nunca cambia) y el
**código** (`{programa}\codigo`, cambia en cada versión). Si una versión necesita una base nueva
(`packaging/BASE_VERSION`), la actualización lo detecta y pide el instalador completo.

Para una versión oficial, crea una etiqueta (`git tag v1.0.0 && git push origin v1.0.0`): el instalador se
publica además en **Releases**.

> Windows mostrará "Windows protegió su PC" porque el instalador todavía no está firmado digitalmente:
> **Más información → Ejecutar de todas formas**. Ver `PENDIENTES.md` (certificado de firma de código).

## 2. Sede principal (una vez por cliente)

1. **Tailscale**: instálalo desde https://tailscale.com/download y entra con la cuenta de la empresa.
2. **Traffiqui**: ejecuta el instalador y elige **La sede principal**. Se abre el navegador.
3. **Primer uso**: escribe el nombre de la empresa (igual que en su licencia), tu nombre, correo y contraseña.
4. **Licencia**: en *Sedes y usuarios → Licencia*, pega el código que te dio Traffiqui. Sin código se
   puede tener 1 sede.
5. **Sedes**: crea cada tienda y **copia su clave** (`tqs_…`); solo se muestra una vez.
6. Apunta la **dirección para las tiendas** que aparece arriba (la de Tailscale, `http://100.x.y.z:9000`).
7. **Usuarios**: agrega a gerencia y marketing ("Todas las sedes") o a encargados ("Solo una sede").
8. **Código de recuperación**: al terminar el primer uso aparece un código `TQR-…`. **Guárdalo**: si se olvida
   la contraseña, con él se pone una nueva (*¿Olvidaste tu contraseña?* en la pantalla de entrada). Con el
   correo configurado (*Sedes y usuarios → Correo saliente*) también llega un enlace por email.
9. **Copias de seguridad**: se hacen solas cada día. Elige una **carpeta extra** en otro disco o en
   OneDrive / Google Drive (*Sedes y usuarios → Copias de seguridad*).

Cada sede tiene su página (clic en su nombre en el Resumen): **en vivo** (plano con las personas, cámaras,
cajas y alertas) y **analítica** completa (comparativas con la semana anterior y el mes pasado, áreas,
recorridos, cajas, puertas y mapa de calor). Las **alertas** (aforo, fila en caja, cámara caída, tapada o
movida, sede sin enviar datos) aparecen arriba del Resumen.

El instalador abre el puerto 9000 del firewall de Windows solo para Tailscale y la red local.

Para que gerencia o marketing entren desde **otro PC o portátil**: instalan Tailscale con la misma cuenta y
abren en el navegador la dirección de Tailscale del paso 6. No necesitan instalar Traffiqui.

## 3. Cada tienda

1. **Tailscale**: instálalo y entra con **la misma cuenta** que la sede principal.
2. **Traffiqui**: ejecuta el instalador y elige **Una tienda**.
3. Configura las cámaras, el plano y las zonas como siempre (ver README).
4. **Configuración → Sede principal**: pega la dirección de Tailscale y la clave de la sede → **Conectar**.
5. **Configuración → General**: aforo máximo y fila en caja para las alertas (opcionales), y el detector
   (preciso o rápido si el PC tiene muchas cámaras). En *Cámaras de la tienda* se ve la salud de cada
   cámara; si una se movió a propósito, "Aceptar posición".

Si se corta internet, la tienda sigue contando y envía lo pendiente al volver. Si el PC de la sede principal
está apagado, igual.

## 4. Licencias (solo para el administrador de Traffiqui)

Las licencias impiden que un cliente active más sedes de las que pagó: el servidor está en su PC, así que
el límite lo pone un código firmado que solo tú puedes generar.

**Una sola vez** (en tu PC, con el repositorio):

```bat
python -m cloud.licencia crear-claves --privada C:\TraffiquiLicencias\clave-privada.txt
```

Guarda una **copia de seguridad** de `clave-privada.txt` y no la compartas: quien la tenga puede fabricar
licencias. El comando escribe `cloud/licencia_publica.txt`; súbelo a GitHub y genera un instalador nuevo.
Hasta entonces los instaladores solo permiten 1 sede por empresa.

**Por cada venta o ampliación**:

```bat
python -m cloud.licencia emitir "Farmacias Sol" 3 --privada C:\TraffiquiLicencias\clave-privada.txt
python -m cloud.licencia emitir "Farmacias Sol" 5 --vence 2027-12-31 --privada C:\TraffiquiLicencias\clave-privada.txt
```

Envía al cliente el código `TQ1.…`. El nombre de la empresa debe coincidir con el que escribió en el
primer uso (no importan mayúsculas ni espacios de más).

## 5. Dónde quedan los datos

`C:\ProgramData\Traffiqui`: base de datos de la tienda (`traffiqui.db`) o de la sede principal
(`sede-principal.db`), el modo elegido (`modo.json`), los registros (`logs\traffiqui.log`) y las copias
diarias (`copias\`). Desinstalar o actualizar no los borra.

**Restaurar una copia**: cierra Traffiqui (icono de la bandeja → Salir), abre el `.zip` de la copia, copia los
archivos `.db` a `C:\ProgramData\Traffiqui` reemplazando los actuales y vuelve a abrir Traffiqui.

Para cambiar de modo, vuelve a ejecutar el instalador y elige el otro.
