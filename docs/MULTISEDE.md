# Multisede: diseño

Una empresa con varias tiendas (sedes) y una **sede principal** (marketing y gerencia) que ve el
consolidado de todas, el tiempo real de cada una y su registro completo. Cada sede nueva se paga aparte
y la activa el administrador (Andrés) a mano.

Decisiones tomadas:
- **Tiempo real = cifras y 3D**, nunca vídeo. De la tienda solo salen números y posiciones en el plano.
- **Cobro manual**: el cliente paga (pago móvil, Zelle, Binance, transferencia) y el administrador activa la sede.
- **Reportes**: panel web siempre al día, correo automático y exportación a Excel.

## Arquitectura

```
 Sede A (PC tienda)          Sede B (PC tienda)
 app actual + agente  ──┐   app actual + agente ──┐
                        │  HTTPS / WebSocket      │   (siempre sale de la tienda:
                        ▼                         ▼    no hay que abrir puertos)
               ┌──────────────────────────────────────┐
               │  Traffiqui Cloud (servidor central)  │
               │  FastAPI + PostgreSQL                │
               │  · recibe datos y tiempo real        │
               │  · usuarios, roles y sedes           │
               │  · reportes, correo, Excel           │
               └──────────────────────────────────────┘
                        ▲
                        │ navegador
            Sede principal (marketing y gerencia)
```

- **La app de cada tienda no cambia**: sigue contando y guardando en su SQLite, y funciona sin internet.
  Se le añade un **agente de sincronización** que envía los datos al servidor central.
- **Si se corta internet**, el agente acumula y se pone al día al volver. No se pierde nada.
- Es el mismo servidor que llevará las **licencias y actualizaciones** (ver `PENDIENTES.md`).

## Quién ve qué

| Rol | Ve | Puede |
|---|---|---|
| **Administrador** (Andrés) | Todas las empresas y sedes | Crear empresas, activar/suspender sedes, registrar pagos |
| **Sede principal** (gerencia y marketing) | Todas las sedes de su empresa | Consolidado, tiempo real y registro de cada sede, reportes, Excel, pedir sedes nuevas |
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

1. La sede principal pide una sede nueva desde el panel → queda **pendiente de pago**.
2. El cliente paga; el administrador registra el pago y **activa** la sede.
3. Al activarla se genera una **clave de sede**; se pone en la app de esa tienda y empieza a enviar datos.
4. El administrador puede **suspender** una sede: deja de recibir datos y desaparece de los reportes.

## Fases

1. ✅ **Servidor central + agente**: empresas, sedes, usuarios con contraseña, recepción de datos y
   panel consolidado (ver "Cómo usarlo").
2. **Tiempo real y vista de cada sede**: en vivo, analítica y 3D de cualquier sede. Los datos ya
   llegan desde la fase 1 (recorridos, áreas, mapa de calor del plano): falta construir las vistas.
3. **Reportes**: correo automático y Excel consolidado.
4. **Panel de administrador**: alta de empresas, solicitudes de sede, pagos, activar/suspender.
   Mientras tanto se hace con `python -m cloud.admin`.

## Cómo usarlo (fase 1)

Código: `cloud/` (servidor) y `app/cloud_sync.py` (agente dentro de la app de la tienda).

```bash
pip install -r cloud/requirements.txt
export TRAFFIQUI_CLOUD_DB=postgresql+psycopg://usuario:clave@host/traffiqui   # sin esto: SQLite en data/cloud.db
python -m cloud.main --host 0.0.0.0 --port 9000      # detrás de HTTPS (Caddy o nginx)
```

En desarrollo, sin HTTPS: `TRAFFIQUI_COOKIE_SECURE=0 python -m cloud.main`. Para enseñarlo con datos
inventados: `python -m cloud.demo` crea la empresa "Demo" con 4 sedes y 30 días de datos
(usuario `demo@traffiqui.com`, contraseña `demo1234`).

Alta de un cliente con la herramienta del administrador:

```bash
python -m cloud.admin crear-empresa "Farmacias Sol"                  # → empresa 1
python -m cloud.admin crear-sede 1 "Sede Chacao"                     # → sede 1, pendiente de pago
python -m cloud.admin activar-sede 1 --pago "Pago móvil 21/10 ref 1234"   # → muestra la clave tqs_…
python -m cloud.admin crear-usuario gerente@sol.com "Ana Pérez" hq --empresa 1
python -m cloud.admin crear-usuario encargado@sol.com "Luis" site --empresa 1 --sede 1
python -m cloud.admin suspender-sede 1      # deja de aceptar sus datos
python -m cloud.admin nueva-clave 1         # si la clave se filtró: la anterior deja de valer
python -m cloud.admin listar
```

La clave `tqs_…` se pega en la app de la tienda: Configuración → **Sede principal**.

Qué hay en el panel (`/`): totales de todas las sedes (visitas, pasaron por caja, permanencia, hora
punta, sedes en línea), tabla por sede con su estado (en línea / sin conexión desde hace… / pendiente
de pago / suspendida) y gráficas de visitas por sede y por hora del día. Rangos: hoy, semana, mes y
personalizado. El encargado de una sede solo ve la suya.

Seguridad: contraseñas con scrypt; la sesión es una cookie `httponly` (solo HTTPS en producción) y en
la base solo se guarda su hash; de la clave de sede también se guarda solo el hash. Pendiente antes de
producción: límite de intentos de inicio de sesión y copias de seguridad de la base.

## Por decidir

- **Alojamiento** del servidor: un VPS (Hetzner, DigitalOcean: ~5–12 USD/mes) o Railway/Render.
- **Correo**: Resend o Brevo (tienen plan gratis para empezar) y un dominio propio.
- **Precio** de cada sede adicional (mensual o pago único).
- ✅ **Nombre "Compradores"** en la app local: ahora "Pasaron por caja", como en el PDF. Los nombres
  internos (`buyers`, `is_buyer`, `buyer_seconds`) no cambian, para no romper bases ni datos existentes.
