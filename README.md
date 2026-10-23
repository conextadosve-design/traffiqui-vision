# Traffiqui Vision · MVP de conteo y mapa de calor con webcam

> **Instalar en una tienda o en la sede principal con `Traffiqui-Setup.exe`:** ver
> [docs/INSTALACION.md](docs/INSTALACION.md). Este README explica la app de la tienda y cómo
> trabajar con el código.

Prototipo local de la parte de visión por computadora de **Traffiqui**, el SaaS de analítica de
tráfico físico para retail. Con una sola cámara (tu webcam) detecta personas, sigue a cada una con un
color propio, dibuja su recorrido con un rastro que se desvanece, cuenta entradas y salidas, mide
permanencia por zona, genera un mapa de calor y lo muestra en un dashboard web local.

Todo corre en **CPU**, en **Windows 10/11**, **sin internet** después de la primera instalación.
No se guarda video ni imágenes de personas.

---

## 1. Instalación en Windows (paso a paso)

1. **Instala Python 3.11** (o 3.12). Cualquiera de estas dos opciones:
   - Desde <https://www.python.org/downloads/>, marcando **"Add python.exe to PATH"**.
   - O en una terminal: `winget install Python.Python.3.11`
2. **Copia la carpeta `traffiqui-vision`** a una ruta **corta**, por ejemplo `C:\traffiqui-vision`
   (Windows limita las rutas a 260 caracteres; si la carpeta está muy anidada, `run.bat` avisa).
3. **Haz doble clic en `run.bat`** (con internet la primera vez). El script:
   - crea el entorno virtual `.venv`;
   - instala las dependencias de `requirements.txt` (versiones fijadas, ~200 MB, tarda unos minutos);
   - usa el detector de personas que ya viene en `models/` (D-FINE, ver sección 6);
   - arranca el servidor y abre <http://localhost:8000> en el navegador.
4. Las siguientes veces `run.bat` arranca directo y **sin internet**: solo reinstala si
   `requirements.txt` cambió.

Para cerrar: **Ctrl+C** en la ventana de `run.bat`. Se libera la cámara, se cierran los tracks
activos y se vacía la cola de escritura a SQLite.

Otras formas de arrancar:

```bat
run.bat --source demo.mp4    :: modo demo: lee un video en bucle (si no hay webcam)
run.bat --source 1           :: usar la cámara de índice 1
run.bat --port 8080          :: otro puerto
run.bat --setup              :: solo instalar, no arrancar
```

## 2. Uso del dashboard

### En vivo
- Video con overlays dibujados en el servidor: recuadro y rastro del color de cada persona, etiqueta
  `ID 7 | 42 s` (ID y tiempo en cámara), zonas, línea y mapa de calor.
- Panel lateral: personas ahora (con el pico y su hora), únicas hoy y de la sesión, entradas y salidas
  por la línea, permanencia promedio y mediana, FPS reales y detector en uso.
- Interruptores de capas: recuadros, rastros, mapa de calor, zonas, línea y privacidad.
- Lista de personas en cuadro: chip con su color, ID y tiempo.

### Cómo dibujar la línea virtual
1. Pulsa **Dibujar línea** (debajo del video).
2. Haz **2 clics** sobre el video: inicio y fin.
3. La flecha verde **"Entrada"** indica qué sentido cuenta como entrada. Si está al revés, pulsa
   **Invertir dirección**.

Una persona cuenta cuando pasa de un lado al otro **dentro del largo del segmento** y se aleja al menos
6 px de la línea. Por eso alguien parado encima de la línea no suma cruces de más.

### Cómo dibujar una zona
1. Pulsa **Dibujar zona**.
2. Haz clic en cada vértice del polígono.
3. Cierra con **doble clic** o **clic derecho** y escribe el nombre (por ejemplo "TV y audio" o "Caja").
4. Para renombrar o borrar zonas, ve a **Configuración → Línea y zonas**. `Esc` cancela un dibujo.

### Analítica
- Rango: **Hoy**, **Última hora** o **Personalizado**. Intervalo de 5, 15 o 60 minutos.
- Gráficos: ocupación en el tiempo, personas únicas por intervalo, distribución de permanencia y
  entradas contra salidas por hora.
- Tabla de zonas: cuántos pasaron, cuántos se detuvieron, tasa de detención y permanencia promedio.
- Mapa de calor acumulado del rango, sobre el cuadro de referencia de la cámara.
- **Exportar CSV**: separado por `;` y con coma decimal, para abrirlo directo en Excel en español.

### Configuración
Cámara (buscar índices 0–5, **Probar**, **Usar esta cámara**), resolución, detector (preciso o rápido), confianza,
duración del rastro (1–10 s), punto de seguimiento (**centro** o **base** = pies, lo correcto con una
cámara cenital en tienda), duración mínima para contar a una persona, espera de un track perdido, vida
media del mapa de calor, umbral de "se detuvo" y privacidad. **Todo se guarda en SQLite y se aplica
sin reiniciar.**

## 3. Tienda completa: plano, varias cámaras, reidentificación y 3D

Todo lo de las secciones anteriores sigue igual con una sola webcam. Esta parte agrega lo necesario para
llevarlo a una tienda con CCTV y varios pasillos, **sin cambiar el sistema**: la primera cámara sigue
siendo la "principal" (línea y zonas sobre su imagen) y las demás se suman.

### Paso 1 · Dibujar el croquis (pestaña **Plano**)
1. En el panel derecho, con nada seleccionado, pon el **ancho y el fondo del local en metros** (mídelos
   con cinta o con un medidor láser: con medidas reales todo lo demás sale en metros reales).
2. Dibuja con la barra izquierda:
   - **Pared**, **Divisor**: clic en cada esquina; doble clic, Enter o Esc para terminar.
   - **Puerta**: clic en los 2 extremos.
   - **Góndola**, **Mueble**, **Caja**, **Nevera**, **Mostrador**: clic para colocarlo con medidas
     estándar o arrastra para dibujarlo a medida. Después ajusta ancho, fondo, alto, rotación,
     nombre y **categoría** (lo que se exhibe: "Analgésicos", "Bebidas"…).
   - **Área (pasillo)**: clic en cada vértice y doble clic para cerrarla. Es lo que se **mide**: pasillos,
     cabeceras, zona de cajas, entrada, mostrador.
   - **Cámara**: dónde está montada y hacia dónde mira (es la referencia visual).
3. **Generar góndolas…** crea en un paso una fila de góndolas paralelas **con sus pasillos ya marcados
   como áreas** (cantidad, largo, ancho, ancho de pasillo, orientación y posición).
4. Atajos: Supr borra, Ctrl+Z / Ctrl+Y deshacer y rehacer, Ctrl+D duplica, flechas mueven (Mayús = 1 m),
   rueda del mouse = zoom, arrastrar el fondo = desplazar. Se guarda solo.

### Paso 2 · Agregar las cámaras (Configuración → **Cámaras de la tienda**)
- **Webcam USB** (índice 0, 1…), **CCTV/IP por RTSP** o **video** de prueba. Ejemplos de RTSP (usa el
  *substream*, de baja resolución, que alcanza para contar y consume mucho menos CPU):
  - Hikvision: `rtsp://usuario:clave@IP:554/Streaming/Channels/102`
  - Dahua: `rtsp://usuario:clave@IP:554/cam/realmonitor?channel=1&subtype=1`
- **FPS máx.** por cámara (8 por defecto): con varias cámaras en una PC, 5–8 FPS por cámara alcanza para
  medir flujo y reparte el CPU. La contraseña de la URL nunca se muestra en la interfaz ni en los logs.
- Se aplican **sin reiniciar**. En En vivo aparece un selector para ver cada cámara.

### Paso 3 · Calibrar cada cámara (botón **Calibrar**)
La calibración convierte "pies de la persona en la imagen" en "posición en metros en el plano"
(homografía).
1. Marca un punto **del piso** en la imagen de la cámara y luego **el mismo punto** en el plano.
2. Repite al menos **4 veces**, con puntos bien separados (idealmente cerca de las 4 esquinas de la
   imagen) y sin que 3 queden en línea recta. Sirven esquinas de baldosas, la base de una góndola o una
   cruz con cinta en el piso. Con más de 4 puntos se usa RANSAC y el error medio indica la calidad.
3. Guarda. El área sombreada en azul en el plano es lo que ve la cámara. Con "Dibujar las áreas del plano
   sobre el video" activado, los pasillos se dibujan encima del video: si coinciden con el piso real,
   la calibración está bien.
4. En cada área del plano puedes marcar **qué cámaras la miden**. Sin marcar, la mide cualquier
   cámara calibrada que la vea.

### Paso 4 · Ver la tienda (pestaña **Tienda 3D**)
- Modelo 3D del croquis: paredes, góndolas con su categoría, cajas, neveras, cámaras y entrada.
- **Piso con mapa de calor** del rango (Hoy, Última hora, Personalizado) o en vivo.
- **Pasillos coloreados** por la métrica elegida: personas que pasaron, **penetración** (% de los
  visitantes que entró al pasillo), tasa de detención, permanencia o personas ahora.
- **Personas en vivo** como figuras de su color, con su ID global.
- **Ranking de áreas** ("¿qué pasillo tiene más flujo?"), **movimientos entre áreas** (A → B),
  **recorridos frecuentes** (A → B → C), y la matriz **personas por área y hora**.
- Botones Vista 3D y Desde arriba. Todo se exporta al CSV.

### Entrada, salida y "pasaron por caja"
- **Entrada** y **Salida** (barra del Plano). Si la gente entra y sale por la misma puerta, basta con una
  **Entrada** con función "Entrada y salida": cuenta según el sentido de cruce. Si hay una **salida
  aparte** (por ejemplo, después de las cajas), dibújala con **Salida**: queda como "Solo salida" y las
  entradas pasan a "Solo entrada". La flecha de cada puerta apunta al **interior** del local. El lado se
  detecta solo, y si queda al revés, marca "Invertir lado interior". Los cruces se cuentan en el plano
  (hace falta que una cámara calibrada vea la puerta) y solo cuando la persona ya está confirmada.
- **Zona de cajas**: un área del plano con tipo "Zona de cajas". Quien **acumule ahí 20 s** (configurable
  en Configuración; se suman todas sus visitas a cajas) cuenta como **pasó por caja**. En En vivo y en
  Tienda 3D se marca como "Pasó por caja".
- Pestaña **Pasaron por caja**: % que pasó por caja; **pasaron por caja**, **no pasaron** (solo transitaron) y
  **total**, con personas, % del total, permanencia promedio y mediana, áreas distintas visitadas, % que
  se detuvo en algún área, tiempo en cajas y cuántos siguen en la tienda. Además: pasaron y no pasaron
  por caja, por hora, permanencia por grupo, **qué pasillos recorre cada grupo** (y la diferencia en
  puntos), entradas y salidas por puerta, y quién está en la tienda ahora y en qué estado.
- **No mide compras**: el sistema no ve los tickets, solo quién estuvo en la zona de cajas. Alguien que
  espera a un acompañante en la fila cuenta, y quien paga muy rápido (menos de 20 s) no. Ajusta el umbral observando la tienda real, y
  si es posible compáralo con los tickets del POS de esa hora.

### Cajas por separado y personal
- Cada **Caja** del plano crea sola dos zonas que la siguen al moverla, rotarla o cambiarle el tamaño:
  - **Zona del cliente** (azul, "cliente paga aquí"): quien acumule ahí el tiempo configurado
    **pasó por caja**, y se **asigna a esa caja**. Si pasó por varias cajas, cuenta la caja donde
    más tiempo estuvo. En el panel eliges el lado (frente, atrás, izquierda o derecha), la profundidad y
    el margen.
  - **Zona del cajero** (gris rayado, opcional): quien se pare ahí es **personal**.
- **Zona de personal** (herramienta Z): para áreas solo de empleados, como detrás del mostrador o el
  depósito. Quien pase ahí 15 s (configurable) queda marcado como personal.
- **Más de 4 horas** en el sistema (configurable, 0 = desactivado) también marca a la persona como
  personal: trabajadores y personal extra.
- El personal **se excluye de todas las estadísticas de clientes**: personas únicas, pasaron por caja,
  % que pasó por caja, permanencia, áreas, recorridos, puertas y ocupación. Si ya había contado como
  "pasó por caja", se le quita. En Pasaron por caja se muestra cuántos se excluyeron y por qué, y en vivo aparece con el badge
  "Personal".
- La pestaña Pasaron por caja muestra **cada caja**: personas en fila ahora, cuántas entraron a la zona,
  cuántas se asignan a esa caja, su % del total y el tiempo promedio en caja.
- El tiempo en cajas cuenta "dentro de al menos una zona de caja": si dos zonas se superponen, no se
  duplica.
- **Límite de la regla de 4 h:** depende de que la persona conserve su ID. Si un empleado se va al
  depósito (fuera de cámara) más tiempo que la ventana de re-entrada, vuelve con un ID nuevo y el reloj
  empieza de cero. Por eso conviene marcar las **zonas de personal**: detectan al instante a quien está
  detrás de la caja o del mostrador.

### Editor del plano: lo esencial
- **Pasos guiados** arriba (Medidas → Paredes y entrada → Muebles → Cajas → Pasillos → Cámaras), con
  ✓ cuando cada uno está listo y una explicación al hacer clic.
- **Herramientas con atajos** (V seleccionar, H mover vista, T habitación, W pared, D divisor, E entrada,
  S salida, G góndola, M mueble, C caja, N nevera, O mostrador, A área rectangular, P área libre, Z zona
  de personal, K cámara). La tecla **?** muestra todos.
- **Habitación**: arrastra el contorno y se crean las 4 paredes. **Áreas rectangulares** con un arrastre.
- **Selección múltiple** (Shift+clic, o arrastrar sobre el piso): mover juntos, **alinear**,
  **repartir**, igualar tamaño, rotar 90° (R), duplicar (Ctrl+D), copiar y pegar (Ctrl+C / Ctrl+V).
- **Crear pasillo entre 2 góndolas**: selecciónalas y un botón crea el área exacta entre ambas.
- **Medidas visibles** mientras dibujas y en lo seleccionado. **Imán** a esquinas y a la grilla (Alt lo
  desactiva). Asa para **rotar** y asa para **cambiar el tamaño**.
- Doble clic en el borde de un área o pared **agrega un vértice**; Alt+clic en un vértice lo **borra**.
- **Capas** (paredes, mobiliario, áreas, cámaras, fondo) que se ocultan o se **bloquean**: por ejemplo,
  bloquea las áreas para mover muebles sin seleccionarlas por error.
- **Imagen de fondo** para **calcar**: carga una foto del croquis o del plano y escálala marcando una
  medida conocida (por ejemplo, una pared de 8 m).
- **Plantillas**: local vacío, farmacia pequeña (mostrador con zona de personal) y minimercado (entrada y
  salida separadas, góndolas con pasillos, neveras y 3 cajas).
- Lista de **elementos** agrupada por capa: un clic selecciona.

### Rangos y tráfico por hora de cada día
- Analítica, Pasaron por caja y Tienda 3D tienen los rangos **Hoy**, **Última hora**, **Semana** (últimos 7
  días, incluido hoy), **Mes** (últimos 30 días) y **Personalizado**. En semana y mes el intervalo de los
  gráficos sube solo (1 hora o 1 día) y las etiquetas muestran el día. Pasaron por caja se ve por día y la
  matriz de Tienda 3D se agrupa por hora del día.
- En **Analítica → Tráfico por hora de cada día**:
  - Una tabla **día × hora** (00h–23h) para **toda la tienda** o para **un área**: personas distintas
    que entraron en cada hora. Más oscuro = más tráfico.
  - **Personas** o solo **Pasaron por caja**.
  - **Cada día** o **Promedio por día de la semana**, por ejemplo "los sábados a las 11 h vienen 14
    personas en promedio".
  - **Hora pico de cada área**: la hora de más tráfico, cuántas personas por día en esa hora, las otras
    horas fuertes y un perfil del día completo. Un clic en un área la abre en la tabla de arriba.
- El CSV incluye la tabla día × hora de la tienda y el promedio por hora de cada área.

### Reidentificación: la misma persona entre cámaras
Cada cámara sigue a las personas con su propio ByteTrack. Un módulo de **fusión** decide cuándo un
track nuevo es alguien que ya conocemos y le da un **ID global** (mismo número y mismo color en todas las
cámaras):

| Caso | Cómo se decide |
|---|---|
| **Superposición** | Otra cámara la ve en este momento en el mismo punto del plano (< 0.9 m). Es lo más confiable: diseña la cobertura con 10–20 % de solape entre cámaras vecinas. |
| **Traspaso** | Se perdió hace poco (≤ 8 s, configurable) en otra cámara, a una distancia alcanzable caminando (≤ 2 m/s + 1 m) y con ropa parecida. |
| **Re-entrada** | Salió y volvió a la misma cámara en ≤ 20 s (configurable) con ropa parecida. Funciona aun sin calibrar: en la prueba con la webcam ya une a quien sale y vuelve. |

La "ropa parecida" es un histograma de color del torso y las piernas, **no la cara**. Vive solo en
memoria y se descarta al terminar el track. Si dos candidatos quedan casi empatados, **no se une a
ninguno**: es preferible contar una persona de más que mezclar a dos. En Tienda 3D se muestra cuántas
detecciones se unieron por cada motivo, y en la base queda cada unión (`track_links`) para auditar la
precisión.

**Expectativa realista:** con cámaras cenitales que se superponen, la mayoría de los traspasos se resuelve
por posición y es muy confiable. Sin superposición depende de la ropa. Uniformes del personal, ropa
parecida (todos de negro), grupos y mala iluminación generan errores. **Mide la precisión** con una
caminata de prueba antes de presentar números, y considera excluir al personal (zonas de trabajo).

### Rendimiento con varias cámaras en esta PC
Cada cámara usa su propio detector (~85 ms por cuadro con el detector preciso en un Xeon de 4 núcleos;
~45 ms con el rápido). Con 2–3 cámaras por PC conviene limitar cada una a 5–8 FPS, o pasar al detector
rápido en Configuración. Para más, la arquitectura permite repartir las cámaras en
varios equipos (un mini PC cada 4–6 cámaras) o usar un equipo con GPU.
### Trabajar en la nube (sesiones de Claude)
El código vive en GitHub y se puede programar desde una sesión de Claude en la nube. La nube **no tiene
acceso a tus cámaras**: sirve para cambiar código, correr los tests y revisar la analítica con datos de
prueba. El video en vivo y la calibración se prueban en la PC de la tienda.
- Instalación en la nube (Linux): `bash scripts/setup_cloud.sh`. Instala las dependencias (OpenCV
  sin pantalla) y corre los tests.
- Para traer los cambios a la PC: `git pull` dentro de la carpeta y luego `run.bat`, que reinstala
  solo si cambió `requirements.txt`.

### Salud de cámaras, alertas y copias de seguridad
- **Salud de cada cámara** (Configuración → Cámaras de la tienda): *sin señal*, *tapada u oscura* (sin contraste
  ni bordes durante 10 s) o *se movió* (los bordes fijos de la escena ya no coinciden con su referencia durante
  30 s; la referencia, solo bordes, se guarda en `datos/camaras/`). Tras recolocar una cámara a propósito,
  "Aceptar posición" (y recalibrarla si cuenta en el plano).
- **Alertas** (Configuración → General): aforo máximo y fila larga en caja (0 = desactivadas), más las cámaras
  con problemas. Se ven arriba del panel y viajan a la sede principal, que guarda su historial.
- **Copias de seguridad**: una al día de cada base, en `datos/copias/` (7 diarias y 4 semanales), con una
  carpeta extra opcional (otro disco, OneDrive o Google Drive).

### Multisede: conectar la tienda con la sede principal
Configuración → **Sede principal**: pega la dirección del servidor central y la **clave de la sede** (empieza por
`tqs_`) que te da el administrador al activar la sede. Desde ese momento la app envía cada 30 s sus números
(personas, puertas, áreas, ocupación y mapa de calor del plano) al servidor, donde gerencia y marketing ven
todas las sedes juntas. Nunca se envía video ni imágenes. Sin internet la tienda sigue funcionando igual y
envía lo pendiente al volver. Instalación de la sede principal y de las tiendas: [docs/INSTALACION.md](docs/INSTALACION.md);
diseño: [docs/MULTISEDE.md](docs/MULTISEDE.md).

## 4. Qué significa cada métrica

| Métrica | Definición |
|---|---|
| **Personas ahora** | Tracks visibles en el cuadro actual que ya duran al menos 1 s. |
| **Únicas (sesión / hoy)** | Tracks distintos que duraron ≥ 1 s. Es una **aproximación**: ver Limitaciones. |
| **Pico de ocupación** | Máximo de "personas ahora" y la hora en que ocurrió. En Analítica sale del máximo de cada ventana de 5 s. |
| **Permanencia** | Tiempo entre la primera y la última vez que se vio el track. Promedio, mediana y rangos <10 s, 10–30 s, 30–60 s, 1–3 min y >3 min. Cuenta tracks ya terminados. |
| **Entradas / Salidas** | Cruces de la línea virtual en cada sentido. |
| **Zona: pasaron** | Personas distintas que estuvieron dentro del polígono. |
| **Zona: se detuvieron** | Las que sumaron ≥ 10 s dentro (configurable). |
| **Tasa de detención** | Se detuvieron ÷ pasaron. |
| **Zona: permanencia promedio** | Tiempo total dentro de la zona por persona, promediado. |
| **Mapa en vivo** | Posiciones con decaimiento: el calor se enfría a la mitad cada 30 s (configurable). |
| **Mapa acumulado** | Todas las posiciones desde que arrancó la app o desde el último reinicio del mapa. En Analítica, las del rango elegido. |

**Filtros de calidad:** confianza mínima 0.45; un track cuenta como persona solo si dura al menos 1 s.
Si alguien cruza la línea antes de cumplir ese segundo, el cruce queda pendiente y se cuenta cuando se
confirma. Una salida de zona se confirma recién tras 1 s afuera, para que un parpadeo del detector en el
borde no corte la visita.

## 5. Limitaciones conocidas

- **La reidentificación es aproximada.** Si alguien vuelve después de la ventana de re-entrada (20 s
  por defecto), cambia de cámara fuera de la ventana de traspaso, o su ropa se ve muy distinta con otra
  luz, recibe un **ID nuevo** y se cuenta otra vez. "Personas únicas" sigue siendo una cota superior,
  aunque más cercana a la real que sin reidentificación (sección 3).
- La línea virtual y las zonas dibujadas **sobre la imagen** funcionan solo en la cámara principal. Para
  las demás cámaras usa las **áreas del plano**, que funcionan con todas las cámaras calibradas.
- La calibración asume que el piso es plano y que la cámara no se mueve. Si alguien la golpea o la
  reorienta, hay que recalibrarla.
- **La precisión depende del ángulo de la cámara.** Una webcam frontal sirve para validar. En tienda
  conviene una cámara **cenital o en diagonal alta**, con el punto de seguimiento en **base (pies)**.
  Con la cámara frontal las personas se tapan entre sí y la "posición en el piso" del mapa de calor es
  solo aproximada.
- Personas muy lejanas o muy tapadas se detectan peor, sobre todo con el detector rápido.
- Las coordenadas de línea y zonas se guardan normalizadas (0–1). Si mueves la cámara, hay que
  redibujarlas.
- Si se cambia la resolución en medio de un intervalo, las posiciones del mapa de calor aún no
  guardadas de ese intervalo (máximo 5 min) se descartan.

## 6. Detector de personas y rendimiento

El detector es **D-FINE** (licencia **Apache-2.0**, se puede vender), exportado a ONNX y ejecutado con
`onnxruntime` en CPU: la app no necesita PyTorch. Hay dos modelos en `models/` (ver `models/LEEME.md`):

| Detector | Red | Precisión personas (AP, COCO) | ms por cuadro* |
|---|---|---|---|
| **Preciso** (por defecto) | D-FINE-S, 512 px | **0,540** | ~85 |
| Rápido | D-FINE-N, 512 px | 0,445 | ~45 |
| *Anterior: YOLO11n (AGPL-3.0)* | 480 px | 0,457 | ~21 |

\* Mediana en un Xeon de 4 núcleos a 2,1 GHz, solo CPU. Con la misma precisión que el detector anterior
(0,92 de las detecciones son personas de verdad), D-FINE-S encuentra el **80 %** de las personas frente
al 68 %: por eso la confianza mínima por defecto es 0,65.

Si los FPS bajan de 8: (1) limita los FPS máx. de cada cámara a 5–8; (2) usa 640×480 o el substream;
(3) cambia al detector rápido en Configuración; (4) cierra otras apps que usen CPU.

## 7. Probar otros detectores

`tools/detector/` (dependencias en `tools/detector/requirements.txt`, solo para desarrollo):

```bash
python tools/detector/exportar.py ustc-community/dfine-small-coco models/candidato --size 512
python tools/detector/evaluar.py coco_val.parquet --n 500 models/candidato.onnx models/detector-personas.onnx
```

`exportar.py` convierte modelos de Hugging Face (D-FINE, RT-DETRv2, RF-DETR…) al formato de la app;
`envolver_onnx.py` adapta un ONNX ya hecho; `evaluar.py` mide la precisión COCO (solo personas) y la
velocidad. Se evaluaron D-FINE N/S, DEIMv2-N, RF-DETR-N y RT-DETRv2-R18; D-FINE-S a 512 px dio el mejor
equilibrio entre acierto y velocidad en CPU.

## 8. Arquitectura

Tres hilos, para que el video no se congele:

1. **Captura** (`app/vision/capture.py`): lee la webcam con `cv2.VideoCapture(i, cv2.CAP_DSHOW)` y
   guarda **solo el último cuadro**. Si la cámara se desconecta, reintenta cada 3 s y el stream muestra
   "Cámara desconectada, reintentando…". Con `--source video.mp4` lee el archivo en bucle.
2. **Inferencia** (`app/vision/pipeline.py`): toma el último cuadro, corre el detector de personas
   (D-FINE en ONNX), aplica ByteTrack de `supervision`, actualiza métricas, mapa de calor y rastros, dibuja los
   overlays y codifica el JPEG una sola vez.
3. **Servidor** (`app/main.py`, FastAPI + Uvicorn): `/video` (MJPEG), `/ws` (métricas cada 1 s) y la API.

Además: un hilo **escritor de SQLite** que aplica las escrituras en lotes desde una cola (una
transacción por lote, cada ≤ 1 s) y un hilo de **muestreo** que guarda la ocupación cada 5 s y la
grilla del mapa de calor cada 5 min.

```
app/
  main.py              FastAPI: rutas, websocket, validación de configuración
  config.py            parámetros por defecto, seguros entre hilos
  vision/
    capture.py         hilo de captura con reconexión y modo demo
    pipeline.py        detección + tracking + overlays + cuadro de referencia
    trails.py          rastros con desvanecimiento por mezcla alfa
    heatmap.py         grilla, decaimiento por vida media, render con colormap TURBO
    counting.py        línea virtual, zonas y permanencia (lógica pura, testeable)
    metrics.py         une tracks con conteo y mapa de calor; dibuja zonas y línea
    colors.py          color determinístico por ID (proporción áurea en HSV)
    textdraw.py        texto con tildes sobre el video (Pillow)
    detector.py        detector de personas ONNX (onnxruntime)
    model.py           elige el modelo (preciso o rápido)
    health.py          salud de cada cámara: sin señal, tapada, movida
    plan.py            plano en metros, validación, homografía cámara → plano, huella de cámara
    fusion.py          ID global entre cámaras (superposición, traspaso, re-entrada), áreas, recorridos, calor del plano
  storage/
    db.py              esquema SQLite, escritor en lotes, muestreo
    analytics.py       consultas por rango, mapa acumulado, CSV
    store_analytics.py ranking de áreas, penetración, recorridos, área × hora, calor del plano
  static/              index.html, app.js, styles.css, chart.umd.min.js (Chart.js 4.4.6 local)
    plan-editor.js     editor del croquis (SVG) y generador de góndolas
    cameras.js         cámaras de la tienda y calibración imagen ↔ plano
    store3d.js         vista 3D (Three.js r169 local, en static/vendor/three)
tests/                 pytest, sin cámara
tools/detector/        exportar y evaluar detectores
packaging/             instalador de Windows (base + código aparte)
run.bat
```

### Rastros con desvanecimiento
Cada track guarda una cola de puntos `(x, y, t)`. Al dibujar, la posición se suaviza con una media
móvil de 4 puntos. Cada segmento recibe opacidad y grosor que bajan **linealmente** con su antigüedad
hasta 0 a los N segundos (3 s por defecto). La transparencia es **mezcla alfa real**: los segmentos se
agrupan en 6 niveles de opacidad; cada nivel se dibuja en una capa y se mezcla con `cv2.addWeighted`,
solo dentro del rectángulo que ocupan los rastros. Cuando la persona sale, su cola deja de crecer pero
se sigue dibujando hasta que el último punto envejece, así que el rastro no desaparece de golpe.

### Color por persona
`tono = (0.11 + id × 0.618…) mod 1`, saturación 0.85, brillo 0.95. La proporción áurea separa IDs
consecutivos al menos 0.38 de vuelta en la rueda de color. El texto de la etiqueta es blanco o negro
según el contraste WCAG con ese color.

## 9. Base de datos (SQLite)

Archivo: `data/traffiqui.db` (modo WAL). Marcas de tiempo en epoch (segundos).

| Tabla | Contenido |
|---|---|
| `sessions` | `started_at`, `ended_at`, `source`, `config_json` (configuración usada). `ended_at` se actualiza cada 5 s para que una sesión cortada tenga fin. |
| `tracks` | `session_id`, `track_id`, `first_seen`, `last_seen`, `duration`, `color`, `zones_json` (zonas visitadas). Una fila por persona confirmada. |
| `line_events` | `session_id`, `track_id`, `direction` (`in`/`out`), `ts`. |
| `zone_visits` | `session_id`, `track_id`, `zone_id`, `zone_name`, `enter_ts`, `exit_ts`, `duration`. |
| `occupancy_samples` | Cada 5 s: `people` (al cierre), `people_max` y `people_avg` de la ventana. |
| `heatmap_snapshots` | Cada 5 min: `ts_start`, `ts_end`, `rows`, `cols` y `grid` (numpy float32 comprimido con `savez_compressed`) con las posiciones **de ese intervalo**. El acumulado de un rango es la suma de sus fotos. |
| `config` | `key` → `value` (JSON). Línea, zonas y parámetros. Se recarga al iniciar. |
| `reference_frame` | Único cuadro de referencia (JPEG) para el mapa de calor. |
| `global_tracks` | Una fila por **persona** (ID global): `first_seen`, `last_seen`, `duration`, `cameras_json` y `areas_json` (su recorrido: áreas en orden de visita). |
| `track_links` | Cada track local de cada cámara y a qué ID global se unió, con el motivo (`nueva`, `superposición`, `traspaso`, `re-entrada`). Sirve para auditar la reidentificación. |
| `area_visits` | Visitas a las áreas del plano: `global_id`, `area_id`, `area_name`, entrada, salida, duración. |
| `area_transitions` | Cada paso de un área a otra (`from` → `to`) por persona. |
| `plan_heatmap_snapshots` | Cada 5 min: grilla del **plano** (celdas de 0.25 m) con las posiciones de ese intervalo. |
| `store_door_events` | Cada cruce de una puerta del plano: `global_id`, `door_id`, `door_name`, `direction` (`in` = entró, `out` = salió), `ts`. |
| `cloud_link` | Conexión con el servidor central (una fila): dirección, clave de la sede (nunca sale por la API local), `db_uid` y hasta dónde se envió cada tabla. |

`global_tracks` también guarda `is_buyer` (pasó por caja), `checkout_seconds` (tiempo en cajas),
`checkout_area_id` / `checkout_area` (caja a la que se asigna), `changed_at` (última escritura, para la sincronización), `stopped_any` (se detuvo en
alguna área) e `is_staff` / `staff_reason` (personal, excluido de todas las consultas de clientes). Estas columnas se agregan solas a una base existente al iniciar.

El plano (`floorplan`) y las cámaras (`cameras`, con su calibración) se guardan en `config`.

Los `track_id` se reinician en cada sesión, por eso la clave real es `(session_id, track_id)`.

## 10. Privacidad

- **Nunca se guarda video ni imágenes de personas.** El stream MJPEG solo vive en memoria.
- En disco hay únicamente números, coordenadas de la grilla y el **cuadro de referencia**. Ese cuadro
  se toma al iniciar, esperando hasta 10 s un momento **sin personas**. Si no lo hay, cada persona
  detectada se reemplaza por una mancha de color sin rasgos ni silueta. Botón para recapturar en
  Analítica.
- Interruptor **Privacidad**: desenfoca la mitad superior de cada recuadro (zona de la cara) en el
  stream en vivo.
- La vista **Probar** de cámara muestra un cuadro en el navegador y no lo guarda.

## 11. Tests

```bat
.venv\Scripts\python.exe -m pytest -q
```

Cubren, sin cámara: cruce de línea en ambas direcciones (más inversión, histéresis y cruce fuera del
segmento), punto dentro y fuera de polígonos (incluso cóncavos), permanencia por zona con tolerancia a
parpadeos, binning y decaimiento del mapa de calor, color estable por ID y distinto entre IDs
consecutivos, opacidad del rastro según antigüedad, persistencia en SQLite, consultas de analítica,
CSV y validación de la configuración. También: homografía (exacta con 4 puntos, rechazo de puntos
alineados, huella de cámara), unión por superposición, traspaso alcanzable o imposible por distancia,
rechazo por ropa distinta, re-entrada sin calibrar, empates ambiguos que no se unen, expiración de
IDs globales, descriptor de ropa, áreas del plano con cámaras asignadas, recorridos y calor en metros.

## 12. Solución de problemas

| Síntoma | Qué hacer |
|---|---|
| "Cámara desconectada, reintentando…" | Revisa el USB o cierra Zoom, Teams o la app Cámara, que bloquean la webcam. Se reintenta cada 3 s. En Configuración puedes elegir otra cámara. |
| "No se encontró Python 3.11 ni 3.12" | Instala Python (paso 1) y vuelve a abrir `run.bat`. |
| La instalación falla | Revisa la conexión (solo se necesita la primera vez). Si persiste, borra `.venv` y reintenta. |
| "La ruta de esta carpeta es muy larga" | Mueve la carpeta a `C:\traffiqui-vision`, borra `.venv` y vuelve a ejecutar `run.bat`. |
| "Error al cargar el modelo" | Falta `models/detector-personas.onnx`: vuelve a descargar el proyecto completo (o reinstala Traffiqui). |
| FPS bajos | Ver la sección 6. Con varias cámaras, baja los FPS máx. de cada una a 5. |
| Una cámara RTSP queda «Sin señal» | Prueba la URL en VLC (Medio → Abrir ubicación de red). Revisa usuario, contraseña, que la PC esté en la misma red y usa el substream. |
| Los pasillos dibujados sobre el video no coinciden con el piso | Recalibra con más puntos, todos sobre el piso y bien separados. |
| El puerto 8000 está ocupado | `run.bat --port 8080` |

## 13. Licencia y dependencias

- **Detector D-FINE: Apache-2.0** (pesos de `ustc-community` en Hugging Face, ver `models/LEEME.md`).
  Se puede distribuir y vender; hay que conservar el aviso de licencia y la atribución. Ultralytics
  (AGPL-3.0) ya no forma parte de la app.
- `supervision` está fijado en **0.30.9**, la última versión que incluye `sv.ByteTrack`. En 0.31 el
  tracker pasó al paquete aparte `trackers`, así que actualizar `supervision` requiere migrar.
- Chart.js 4.4.6 (MIT) se sirve desde `app/static/` para funcionar sin internet.
