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

1. **Servidor central + agente**: empresas, sedes, usuarios con contraseña, recepción de datos y
   panel consolidado básico.
2. **Tiempo real y vista de cada sede**: en vivo, analítica y 3D de cualquier sede.
3. **Reportes**: correo automático y Excel consolidado.
4. **Panel de administrador**: alta de empresas, solicitudes de sede, pagos, activar/suspender.

## Por decidir

- **Alojamiento** del servidor: un VPS (Hetzner, DigitalOcean: ~5–12 USD/mes) o Railway/Render.
- **Correo**: Resend o Brevo (tienen plan gratis para empezar) y un dominio propio.
- **Precio** de cada sede adicional (mensual o pago único).
- **Nombre "Compradores"** en la app local: cambiarlo a "Pasaron por caja", como en el PDF.
