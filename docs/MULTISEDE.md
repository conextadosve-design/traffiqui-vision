# Multisede: diseño

Una empresa con varias tiendas (sedes) y una **sede principal** (marketing y gerencia) que ve el
consolidado de todas, el tiempo real de cada una y su registro completo. Cada sede nueva se paga aparte.

Decisiones tomadas:
- **Todo local, nada publicado en internet** (primera etapa): un solo instalador `Traffiqui-Setup.exe`
  con dos modos, *tienda* y *sede principal*. El servidor central es el **PC de la sede principal**.
- **Conexión por Tailscale**: red privada cifrada entre las tiendas y la sede principal, sin abrir puertos
  del router. Guía paso a paso: [INSTALACION.md](INSTALACION.md).
- **Tiempo real = cifras y 3D**, nunca vídeo. De la tienda solo salen números y posiciones en el plano.
- **Cobro por sede con licencias firmadas**: el cliente paga (pago móvil, Zelle, Binance, transferencia) y
  Andrés le envía un código de licencia con el número de sedes (`cloud/licencia.py`). Como el servidor
  está en el PC del cliente, el límite no puede ser un interruptor en ese PC: lo pone el código, que solo
  se puede generar con la clave privada de Andrés.
- **Reportes**: panel web siempre al día, correo automático y exportación a Excel.

## Arquitectura

```
 Tienda A (Traffiqui, modo tienda)     Tienda B (Traffiqui, modo tienda)
 cámaras + conteo + agente  ──┐        cámaras + conteo + agente ──┐
                              │    Tailscale (red privada)          │
                              ▼                                     ▼
               ┌────────────────────────────────────────────────────┐
               │  PC de la sede principal (Traffiqui, modo sede     │
               │  principal): servidor central en el puerto 9000    │
               │  FastAPI + SQLite (C:\ProgramData\Traffiqui)       │
               │  · recibe datos · usuarios y sedes · licencia      │
               └────────────────────────────────────────────────────┘
                        ▲
                        │ navegador (en ese PC o por Tailscale)
            Gerencia y marketing
```

El mismo código de `cloud/` sirve más adelante para un servidor propio en internet (con PostgreSQL),
si algún día se quiere: no hay nada atado al PC de la sede principal.

- **La app de cada tienda no cambia**: sigue contando y guardando en su SQLite, y funciona sin internet.
  Se le añade un **agente de sincronización** que envía los datos al servidor central.
- **Si se corta internet**, el agente acumula y se pone al día al volver. No se pierde nada.
- El arranque (`app/launcher.py`) elige el modo según `C:\ProgramData\Traffiqui\modo.json`, que escribe el
  instalador; un icono en la bandeja abre el panel o cierra el programa.

## Quién ve qué

| Rol | Ve | Puede |
|---|---|---|
| **Administrador** (Andrés) | — | Emite los códigos de licencia (`python -m cloud.licencia emitir`) |
| **Sede principal** (gerencia y marketing) | Todas las sedes de su empresa | Consolidado, crear / suspender sedes y sus claves (hasta lo que permita la licencia), usuarios |
| **Encargado de sede** | Solo su sede | Tiempo real y registro de su sede |

## Datos que se sincronizan

Solo números, nunca imágenes (tampoco el cuadro de referencia de la cámara):

| Qué | Cada cuánto | Para qué |
|---|---|---|
| Estado en vivo: personas ahora, entradas/salidas, filas en caja, posiciones en el plano | 1–2 s | Tiempo real y 3D |
| Personas (`global_tracks`), cruces de puertas, visitas a áreas, ocupación | ~1 min, en lotes | Registro completo y reportes |
| Mapa de calor del plano (grillas de 5 min) | 5 min | Mapa de calor histórico |
| Plano de la tienda | Al cambiar | Vista 3D en la nube |

Cada fila lleva sede + sesión + id local, así que reenviar un lote no duplica datos.

## Panel de la sede principal

- **Consolidado**: visitas totales y por sede, hora punta, % que pasa por caja, permanencia,
  ranking y comparativa entre sedes, evolución por día/semana/mes.
- **Cada sede**: las mismas vistas que la app local (en vivo, analítica, pasan por caja, Tienda 3D,
  tráfico por hora), en modo solo lectura.
- **Correo automático**: resumen diario, semanal o mensual (cada usuario elige), con enlace al panel.
- **Excel**: hoja de resumen + una hoja por sede, para el rango elegido.

## Sedes y cobro

1. El cliente paga las sedes que quiere; Andrés le envía un **código de licencia** (`TQ1.…`) con ese número.
2. En el panel de la sede principal, *Sedes y usuarios → Licencia*: pega el código.
3. Crea cada sede: queda **activa** y muestra su **clave** (`tqs_…`) una sola vez. Se pega en la app de esa tienda.
4. Más sedes que la licencia: el panel no deja crearlas y muestra el contacto de Andrés. Aunque alguien
   activara una sede por otra vía, el servidor rechaza los datos de las sedes que no entran en la licencia
   (cuentan las primeras en activarse).
5. **Suspender** una sede deja de aceptar sus datos y libera su cupo; **nueva clave** invalida la anterior.

Sin licencia, cada empresa puede tener 1 sede (`FREE_SITES` en `cloud/licencia.py`).

## Fases

1. ✅ **Servidor central + agente**: empresas, sedes, usuarios con contraseña, recepción de datos y
   panel consolidado.
1b. ✅ **Todo local con instalador**: modo tienda / sede principal, primer uso, gestión de sedes, usuarios y
   licencias desde el panel, Tailscale, instalador de Windows generado por GitHub Actions
   (`packaging/`, `.github/workflows/instalador-windows.yml`). Guía: [INSTALACION.md](INSTALACION.md).
2. **Tiempo real y vista de cada sede**: en vivo, analítica y 3D de cualquier sede. Los datos ya
   llegan desde la fase 1 (recorridos, áreas, mapa de calor del plano): falta construir las vistas.
3. **Reportes**: correo automático y Excel consolidado.

## Desarrollo

Código: `cloud/` (servidor de la sede principal), `app/cloud_sync.py` (agente de la tienda) y
`app/launcher.py` (arranque del programa instalado).

```bash
pip install -r requirements.txt -r cloud/requirements.txt
python -m app.launcher --modo sede-principal --sin-bandeja     # http://localhost:9000
python -m app.launcher --modo tienda --sin-bandeja             # http://localhost:8000
```

Con `TRAFFIQUI_DATA=carpeta` los datos van a esa carpeta en vez de `data/`. Para enseñarlo con datos
inventados: `python -m cloud.demo` crea la empresa "Demo" con 4 sedes y 30 días de datos (usuario
`demo@traffiqui.com`, contraseña `demo1234`).

`python -m cloud.admin` (crear empresas, sedes, usuarios, claves) sigue sirviendo para pruebas o para un
servidor propio con varias empresas; en el PC de un cliente todo se hace desde el panel.

Qué hay en el panel (`/`): totales de todas las sedes (visitas, pasaron por caja, permanencia, hora
punta, sedes en línea), tabla por sede con su estado (en línea / sin conexión desde hace… / suspendida)
y gráficas de visitas por sede y por hora del día. Rangos: hoy, semana, mes y personalizado. El
encargado de una sede solo ve la suya.

Seguridad: contraseñas con scrypt; la sesión es una cookie `httponly` y en la base solo se guarda su
hash; de la clave de sede también se guarda solo el hash. El primer uso (crear empresa y usuario) solo
se acepta desde el propio PC. El puerto 9000 solo se abre a Tailscale y a la red local. Pendiente:
límite de intentos de inicio de sesión y copias de seguridad automáticas de la base.

## Por decidir

- **Correo** para los reportes automáticos (fase 3): desde el PC de la sede principal, con una cuenta
  de correo de la empresa (SMTP) o un servicio como Resend / Brevo.
- **Precio** de cada sede adicional (mensual o pago único).
- ✅ **Nombre "Compradores"** en la app local: ahora "Pasaron por caja", como en el PDF. Los nombres
  internos (`buyers`, `is_buyer`, `buyer_seconds`) no cambian, para no romper bases ni datos existentes.
