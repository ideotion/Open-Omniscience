<!-- es: AI-drafted translation of docs/USER_MANUAL.md (2026-11-13, R677), not yet reviewed by a native speaker; the English original is authoritative. Coverage: the whole document, 124 of 124 headings. Improve it with a pull request; corrections by native speakers are welcome. -->

# Open Omniscience — Manual de usuario

*Una plataforma de inteligencia de código abierto, ética y local para el periodismo
de investigación.* Este manual es la guía práctica y completa: qué es la aplicación, cómo
instalarla y ejecutarla, y un recorrido por **cada pestaña, control, ajuste y flujo de trabajo**,
seguido de una referencia técnica (ubicación de los datos, variables de entorno, la API
HTTP completa) y de la resolución de problemas.

> **En una frase:** Open Omniscience reúne de forma ética noticias (además de ediciones
> de Wikipedia y precios de mercado) en una única base de datos SQLite en *su* equipo,
> con búsqueda, sin duplicados y con la procedencia registrada; le permite analizarlas
> (búsqueda, tendencias, mapas, encuadre, resúmenes con un LLM local) y puede producir
> **pruebas firmadas criptográficamente y verificables sin conexión** de lo que contenía
> y cuándo.

**Compromisos de diseño que determinan todo lo que sigue:**

- **Local y privado.** Todo se ejecuta en `127.0.0.1` (solo loopback). Sin
  cuentas, sin telemetría, nada sale de su equipo: el único tráfico saliente
  es el del rastreador ético que obtiene las fuentes que usted le indica (y, si lo
  acepta expresamente, Wikipedia/OpenTimestamps/Ollama).
- **Solo cifras honestas.** Cada cifra es un `COUNT(*)` real, un tamaño real en bytes
  en disco o un agregado estadístico real con su tamaño de muestra y su advertencia. La
  aplicación prefiere mostrar un error antes que inventar un valor. (Se eliminaron varias
  funciones anteriores de «detección por IA» que falseaban puntuaciones; véase `docs/HISTORY.md`.)
- **Ingesta ética.** Una sola vía de obtención. `robots.txt` se respeta **con cierre por
  defecto (fail-closed)** (ante la duda, *no* se obtiene nada), cada servidor tiene un
  límite de frecuencia y no se guarda nada si no se extrajo el cuerpo real de un artículo.

---

## Índice

1. [Instalación y primer inicio](#1-instalación-y-primer-inicio)
2. [El recorrido de 60 segundos](#2-el-recorrido-de-60-segundos)
3. [Las herramientas, una por una](#3-las-herramientas-una-por-una)
   - [Inicio](#30-inicio) · [Actividad y Administrador de tareas](#30a-actividad-y-el-administrador-de-tareas) ·
     [Flujo](#30b-flujo) ·
     [Explorar: búsqueda](#31-búsqueda) · [Explorar: el análisis](#31a-análisis-la-ventana-de-corpus) · [Recopilar](#32-recopilar-en-ajustes--avanzado--recopilación) ·
     [Fuentes](#33-fuentes-en-ajustes--avanzado--fuentes) · [Biblioteca](#34-biblioteca) · [Mercados](#35-mercados) ·
     [Índices](#35a-índices) · [Perspectivas](#36-perspectivas) ·
     [Mapa del mundo](#36a-mapa-del-mundo) · [Agenda](#36b-agenda) ·
     [Fuentes vivas](#36b-fuentes-vivas) · [Clima](#36c-clima) · [Observatorio](#36d-observatorio) ·
     [Wikipedia](#37-wikipedia-en-ajustes--wikipedia) ·
     [Evidencia y custodia](#38-pruebas-y-custodia) · [Ajustes](#39-ajustes) ·
     [Ayuda y documentación](#310-ayuda-y-documentación)
4. [Flujos de trabajo habituales (guía práctica)](#4-flujos-de-trabajo-habituales-guía-práctica)
5. [Referencia técnica](#5-referencia-técnica)
   - [Dónde se guardan sus datos](#51-dónde-se-guardan-sus-datos) ·
     [Variables de entorno](#52-variables-de-entorno) ·
     [Extras opcionales](#53-complementos-opcionales) ·
     [La API HTTP](#54-la-api-http) ·
     [Memoria en un equipo pequeño](#55a-la-memoria-en-un-equipo-pequeño--el-único-límite-real)
6. [Resolución de problemas](#6-solución-de-problemas)
7. [Glosario](#7-glosario)

---

## 1. Instalación y primer inicio

Open Omniscience está pensada para **Python 3.13** en Linux basado en Debian (está diseñada
para una AppVM Debian de **Qubes OS**, pero funciona en cualquier Linux moderno). Es una
aplicación local para un solo usuario.

### Lo más fácil: el instalador de una línea

```bash
curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/HEAD/scripts/bootstrap.sh | bash
```

Esto clona el repositorio y ejecuta `./install.sh`, que **funciona sin intervención: no pregunta nada**.
Instala el conjunto predeterminado — **Núcleo (Core)** (rastrear, almacenar, buscar, exportar) más el
extra **Análisis (Analysis)** (estadísticas, análisis de palabras clave y entidades, correlación con
los mercados mediante scipy/scikit-learn; spaCy opcional para un verdadero reconocimiento de entidades
nombradas) más la compresión —, después crea un lanzador **Open Omniscience** en el menú de
aplicaciones y en el Escritorio, y **abre automáticamente** la aplicación en su navegador en
`http://127.0.0.1:8000`. (Defina `OO_COMPONENTS` para cambiar el conjunto de componentes.) Resumir
y traducir en el propio equipo requiere un modelo local: instale **Ollama** desde **Ajustes → IA**
(instalador verificado dentro de la aplicación) o desde ollama.com. Puede volver a ejecutar
`install.sh` en cualquier momento.

> Inspeccione siempre un script antes de pasarlo a un intérprete de comandos. El
> [`bootstrap.sh`](../scripts/bootstrap.sh) es muy breve; también puede clonar el repositorio
> y ejecutar `./install.sh` usted mismo.

**En Qubes:** ejecute `sudo ./install.sh --template` dentro de la TemplateVM, reinicie la
AppVM y luego ejecute `./install.sh` en la AppVM.

### Instalación manual / para desarrolladores

```bash
python3.13 -m venv .venv && . .venv/bin/activate
pip install -e ".[analysis,dev]"     # core + analysis + test tooling
pytest -q                            # full suite should be green
open-omniscience                     # serves http://127.0.0.1:8000
```

En el primer inicio la aplicación **carga automáticamente un catálogo mundial (~3400 dominios
únicos de noticias, mercados, el conjunto del espectro político y portales oficiales de derecho
y propiedad intelectual)** para que tenga algo que ingerir de inmediato, inicializa la base de
datos SQLite y el índice FTS y (si está activado) pone en marcha el planificador en segundo plano.

### La página del primer inicio (idioma → condiciones → frase de contraseña)

En una **instalación nueva**, lo primero que ve es la página de configuración autónoma y sin
conexión en `/unlock`, con tres pasos **antes de que se abra la aplicación**:

1. **Elija su idioma**: escoja entre los 12 idiomas de la interfaz; toda la página
   cambia al instante y su elección se mantiene en la aplicación.
2. **Lea y acepte los documentos legales** (se muestran en su idioma; la versión francesa es
   la que hace fe). Pulse **Aceptar y continuar** para seguir, o **Rechazar**: rechazar
   **desinstala la aplicación** (un subpanel que pide escribir una confirmación garantiza que un
   clic accidental nunca borre nada).
3. **Cree la frase de contraseña de su corpus.** Las bases de datos nuevas se **cifran en disco
   con SQLCipher de forma predeterminada**, así que aquí elige **LA frase de contraseña** (se
   introduce dos veces para confirmarla). Es un único secreto estable, como un identificador de
   usuario, **sin recuperación y sin ninguna alternativa de descifrado**: perder la frase de
   contraseña cuesta tiempo de recopilación, porque el corpus se reconstruye desde la web. La
   justificación completa y el modelo de amenazas honesto están en
   [Ajustes → Avanzado → Seguridad](#39-ajustes).

En **los inicios posteriores** el almacén ya está creado, así que pasa directamente a una única
solicitud de **desbloqueo** con la misma frase de contraseña. Las ejecuciones sin interfaz o mediante
scripts la proporcionan con `OO_DB_PASSPHRASE`; funcionar sin cifrado sigue siendo una elección
explícita (`OO_DB_PLAINTEXT=1`).

### La configuración guiada y la pantalla de Inicio

Una vez dentro, una **configuración guiada (guided setup)** única dentro de la aplicación (un
cuadro de diálogo por pasos) puede acompañarle en sus primeras elecciones: se abre en un paso
**Idioma** y termina en un paso **Finalizar** que indica que la aplicación **arranca sin conexión**
y ofrece un botón *«Conectarse y empezar a recopilar»*. Conectarse siempre pasa por la ventana
emergente de consentimiento de red (véase más abajo): la guía solo le invita; nunca se conecta
por su cuenta. Puede volver a ejecutarla en cualquier momento desde **Ajustes → General → «Volver a
ejecutar la guía de primer inicio».**

Después, la aplicación se abre en **Inicio**, que empieza por su **Resumen**, un flujo de
**Pistas** honestas (véase [3.0 Inicio](#30-inicio)), por encima de una franja compacta **de un
vistazo (at-a-glance)** con recuentos en directo. No necesita cargar nada a mano: el catálogo
seleccionado **se carga automáticamente al arrancar**, y al conectarse **la recopilación empieza
automáticamente**, tras lo cual **Búsqueda** ya contiene artículos reales.

**La estructura.** La navegación está en una **barra lateral izquierda**: una **lista plana** de las
herramientas de datos: **Inicio · Flujo · Explorar · Perspectivas · Observatorio · Mapa del mundo ·
Gobiernos · Agenda · Clima · Índices · Materias primas *(avanzado)* · Fuentes vivas · Biblioteca** (en la
profundidad de interfaz **Esencial** solo Inicio y Flujo están fijados y el resto queda detrás de
una fila rotulada **Mostrar más**; véase [3.](#3-las-herramientas-una-por-una)) (se contrae a una franja de
iconos en ventanas estrechas, pero nunca desaparece). Un botón **Ajustes** se encuentra en la
**parte inferior de la barra lateral** (con el botón para contraerla), y una **barra superior
mínima** encima del contenido contiene:

- **La barra de búsqueda / de comandos (⌘K / Ctrl-K).** Escriba para saltar a cualquier herramienta,
  ejecutar una acción habitual, abrir cualquier documento o hacer una búsqueda federada en sus datos
  (véase [3.1 Búsqueda](#31-búsqueda)). La búsqueda completa, con su análisis, es la pestaña **Explorar**.
- **Estado en directo (Live status)**: un punto de estado del backend y una píldora **LLM** (haga clic
  en ella para abrir Ajustes → IA).
- **Administrador de tareas**: un botón que abre la [ventana del administrador de tareas](#30a-actividad-y-el-administrador-de-tareas).
- **Modo avión**: el único interruptor de red (un pictograma de avión cuyo *relleno* indica el
  estado; relleno = sin conexión). En el primer inicio, mientras está sin conexión, una pequeña
  indicación lo señala y le invita a conectarse cuando esté listo.
- **Selector de idioma**: los 12 idiomas en un solo menú (la bandera es solo una pista; el nombre
  en el propio idioma es el identificador). Un clic vuelve a traducir toda la interfaz.
- **Ayuda (?)**: abre el lector de documentación integrado (este manual y las demás guías), con
  búsqueda y totalmente sin conexión. (Las páginas interactivas Swagger/ReDoc están desactivadas de forma predeterminada; véase §5.4.)
- **Apagar (botón de encendido)**: detiene el servidor de forma limpia; sus datos no se tocan y la
  interfaz se sustituye por un aviso de «puede cerrar esta pestaña». (Esto *no* es desinstalar ni
  borrar.)

**Ajustes** se abre desde el **botón Ajustes de la parte inferior de la barra lateral** (la paleta
de comandos también lleva directamente allí); véase [3.9 Ajustes](#39-ajustes).
**Apariencia (Appearance)** (**Ajustes → Gráficos**) ofrece **14 temas de color + Sistema**, color de
acento, densidad, un selector de tipografías incluidas y el contraído de la barra lateral. Todo se
guarda localmente; no se transmite nada.

### Novedades recientes (ciclo de pruebas en vivo 0.0.8, junio de 2026)

> **Instantánea histórica.** Esta sección describe la aplicación tal como era en el ciclo 0.0.8
> (junio de 2026); la aplicación ha evolucionado desde entonces. `CLAUDE.md` es la fuente de verdad
> actualizada de lo que se publicó después; consulte `docs/ledger/shipped.csv` para el índice.

- **El interruptor de red es un conmutador de modo avión (barra superior):** un pictograma de
  avión constante cuyo **relleno indica el estado**: relleno significa sin conexión activado
  (toda nueva solicitud de red se rechaza al instante; una solicitud ya en curso puede
  terminar). **Cada vuelta a la conexión pregunta primero**: una única ventana emergente de
  consentimiento indica qué acción necesita la red y enumera las **direcciones de interfaz
  locales** de su equipo (leídas de las propias tablas del kernel, nunca mediante una llamada de
  red; la aplicación evita deliberadamente consultar un servicio de «cuál es mi IP», porque eso
  ya sería tráfico). Más allá de esas direcciones locales, internet ve la dirección pública que
  presente su proveedor de acceso o su VPN. Iniciar una pasada de recopilación, importar feeds de
  mercado, añadir una página de Wikipedia vigilada o descargar un volcado pasan todos por el
  mismo consentimiento cuando está sin conexión, y el conmutador se redibuja de inmediato en cada
  transición: nunca espera al siguiente sondeo.

  **El modo avión es una garantía a nivel de socket, no solo una convención por llamada.** Como
  consentimiento informado sobre la protección *propia* de la aplicación: mientras el modo avión
  está activado, la aplicación instala una **protección para todo el proceso** sobre las
  llamadas de socket de bajo nivel (`getaddrinfo` / `create_connection` / `connect`), de modo que
  **cualquier** intento de alcanzar una dirección que no sea de loopback —desde cualquier ruta
  de código, una biblioteca de terceros o una precarga de DNS— lanza un error antes de usar el
  socket real. Loopback (127/8, ::1, `localhost`) y los sockets Unix siempre pasan, así que el
  propio servidor de la aplicación, un Ollama local y la base de datos en archivo siguen
  funcionando. Es transparente mientras está conectado (coste cero durante la recopilación).
  Defina `OO_AIRPLANE_SOCKET_GUARD=0` para desactivarla (para un despliegue poco habitual que
  redirige el loopback a otro lugar).
- **Mapa mental por capas y nube de palabras (Perspectivas):** un verdadero mapa mental radial
  (centro → ramas → hojas hacia fuera) en tres capas de zoom (palabras clave ↔ familias ↔
  supergrupos), con una nube de palabras como segunda vista, un control de espectro de fechas,
  un deslizador de tamaño de texto y ⛶ Ampliar. El tamaño de letra siempre codifica el volumen
  de artículos compartidos.
- **Supergrupos predefinidos:** un conjunto inicial incluido (elaborado a partir de registros
  reales de campo) se carga al arrancar; sus propias ediciones y eliminaciones siempre prevalecen.
- **El Mapa del mundo es ahora un mapa coroplético (ooMap):** la pestaña sombrea los países según
  una dimensión medida (fuentes · artículos · menciones de palabras clave · tono), con controles
  dentro del mapa para la medida, la granularidad país↔continente, una superposición de Lugares,
  una capa de Señales con un deslizador de momento enfocado, una capa de IP de servidores, zoom
  con la rueda, desplazamiento arrastrando y ⛶ Ampliar. Véase [3.6a](#36a-mapa-del-mundo).
- **Fechas de acontecimientos, lugares, personas y organizaciones extraídos del texto:** el
  extractor de fechas lee seis idiomas, formatos numéricos y expresiones ancladas
  («ayer», días de la semana sueltos, «11 de junio»); el extractor de lugares encuentra
  ciudades del nomenclátor y nombres de países; el extractor de entidades muestra **personas**
  y **organizaciones** como dos clases deliberadamente separadas (un nombre precedido de un
  tratamiento y una sigla repetida responden a preguntas distintas; cada entrada registra
  qué regla la encontró). Todo ello alimenta la cabecera de metadatos del lector de artículos,
  que separa **«Desde la fuente»** de **«Deducido por esta aplicación — menos fiable»**
  (recuadro discontinuo): las extracciones son candidatos léxicos con el fragmento de origen,
  nunca hechos confirmados.
- **Exportaciones de palabras clave por idioma:** el registro de palabras clave de diagnóstico
  se limita a 5000 palabras clave *por idioma dominante*, de modo que los vocabularios de
  idiomas minoritarios nunca quedan desplazados del análisis por el volumen en inglés.
- **Volcados de Wikipedia sin conexión:** la lista de ediciones vuelve a cargarse correctamente
  y admite selección múltiple: descargue varias ediciones de idioma en una sola ejecución en cola.
- **17 temas y fuentes de código abierto incluidas:** nueve combinaciones de color nuevas (Arctic,
  Solar, Forest, Aubergine, Garnet, Cyber, Mist, Dawn, Mint) se suman al conjunto original,
  y seis tipografías SIL-OFL vienen ahora **dentro de la aplicación** (Cantarell, Inter,
  Outfit, Manrope, JetBrains Mono, Source Serif 4; véase
  `src/static/fonts/README.md`): nada que descargar, ninguna solicitud de fuentes sale nunca
  de su equipo. Algunos temas van emparejados con una fuente (Arctic→Inter,
  Cyber→Outfit, Sepia/Paper→Source Serif); el nuevo selector de **Tipografía** en
  Ajustes → Gráficos permite sustituir cualquiera de ellas, y el lector de artículos usa la
  serif incluida. Los controles de formulario (deslizadores, casillas, desplegables nativos)
  también siguen ahora el tema.

**Una nota sobre «FOOS».** Las pestañas del navegador que abre la aplicación (investigaciones de
Pistas, el lector local de artículos) llevan el sufijo **«· FOOS» — Free Open OmniScience**: lo
bastante corto para barras de pestañas estrechas y a la vez identificable. Es el nombre de
trabajo de la versión alfa; puede que más adelante llegue un cambio de nombre definitivo.

**Un icono, una interfaz.** El instalador crea **un lanzador** — **Open
Omniscience** → `http://127.0.0.1:8000/` —, una aplicación con barra lateral fácil de descubrir y
personalizable que se adapta con fluidez al tamaño de su ventana (la barra lateral se repliega a
una franja de iconos en ventanas más estrechas). Una segunda interfaz experimental («Desk») existió
en ciclos anteriores y se retiró en la 0.0.8; su historia está en
[`DESIGN.md`](DESIGN.md).

**Funcionamiento en segundo plano, con el navegador cerrado.** La aplicación vive en la ventana de
su lanzador, no en la pestaña del navegador. Puede cerrar el navegador en cualquier momento: la
recopilación, las descargas de Wikipedia y de mapas, las copias de seguridad en una carpeta o
unidad, las importaciones, los trabajos de IA (descargas de modelos, detección de idioma, las
comprobaciones de IA) y el archivo de diagnóstico siguen ejecutándose. Esta es la forma de dejar
un equipo recopilando durante días ahorrando la memoria que ocupa un navegador (a menudo de 0,5 a
1 GB, lo que importa en una máquina virtual pequeña).

Mientras la aplicación se ejecuta, la ventana del lanzador muestra un **panel**, y este permanece
ahí mientras la aplicación siga en marcha: hay una sola ventana, igual en Linux, macOS y Windows.
En la parte superior indica si la aplicación está bloqueada, el estado de la red y de la
recopilación, la memoria y la CPU del servidor, y lo que se está ejecutando en ese momento. Debajo
hay un **registro de actividad**: una línea con hora por cada cosa que ocurre (la recopilación
empieza o se detiene, una descarga llega al 40 %, termina una copia de seguridad, la red pasa a
sin conexión, la aplicación deja de responder y vuelve a responder), añadidas una tras otra
mientras la aplicación siga en marcha, la más reciente abajo. Desplácese hacia atrás con las teclas
de flecha, PgUp y PgDn o la rueda del ratón; End vuelve a la línea más reciente. Haga clic en los
botones o pulse la tecla indicada en cada uno:

- **Abrir la interfaz (Open UI) (o)** vuelve a abrir la aplicación en su navegador.
- **Pausar la recopilación (Pause collection) (p)** detiene la recopilación y pone la aplicación en
  modo avión. Para reanudar, abra la interfaz: conectarse siempre pasa por su ventana de
  consentimiento, nunca por el terminal.
- **Mensajes del servidor (Server messages) (l)** muestra los mensajes propios del servidor (no en
  Windows); pulse cualquier tecla para volver.
- **Detener la aplicación (Stop app) (s)** detiene la aplicación, tras una segunda pulsación. Indica
  los trabajos que terminarían.

El panel no se cierra por sí solo mientras la aplicación se ejecuta, ni siquiera cuando está
ocupada o el equipo estuvo en suspensión y la aplicación tarda en responder: indica cuánto tiempo
lleva la aplicación en silencio y sigue intentándolo. Termina cuando termina la aplicación.
El panel nunca le pide su frase de contraseña: si la aplicación está bloqueada, lo indica, y usted
la desbloquea en el navegador. Cerrar la ventana del lanzador o pulsar Ctrl-C sigue deteniendo la
aplicación, como antes. Defina `OO_PANEL=0` para arrancar sin el panel. Las herramientas de IA que
responden en la página (resumir o traducir en bloque, extracción de palabras clave con IA,
ejecuciones de prompts) también continúan una vez cerrada la pestaña, y aparecen en el panel. Para
detener una, abra la interfaz y pulse **Detener** en su fila del administrador de tareas, o
**Cancelar** en la página (el botón Detener la aplicación del propio panel detiene toda la
aplicación): se detiene tras el artículo en curso, y los artículos ya procesados quedan
guardados. El índice de palabras clave de los artículos que Perspectivas aún no ha indexado también
se pone al día por sí solo mientras la aplicación está inactiva. Solo dos cosas necesitan que la
pestaña siga abierta: una subida que esté enviando desde el navegador y un archivo que el navegador
esté descargando. En Windows el panel se abre en una ventana propia (cerrarla no detiene la
aplicación). Necesita el módulo curses de Python, que Windows obtiene del paquete windows-curses: el
instalador lo añade en PC con Intel y AMD, y en una instalación hecha antes de esta versión puede
añadirlo con `.venv\Scripts\python -m pip install windows-curses` en la carpeta de la aplicación.
Windows en ARM aún no tiene una compilación de este paquete, así que allí la aplicación arranca sin
el panel.

---

## 2. El recorrido de 60 segundos

El ciclo básico es:

> **Elegir/añadir una fuente → Recopilar → Explorar (buscar y analizar) → Exportar / firmar.**

1. **Ajustes → Avanzado → Fuentes**: ya hay cargado un catálogo mundial; añada las suyas si lo desea.
2. **Ajustes → Avanzado → Recopilación**: obtenga el feed RSS de una fuente o pegue la URL de un solo artículo.
   O deje que el **planificador (scheduler)** lo haga automáticamente a intervalos. Recopilar necesita la
   red: el botón de avión de la barra superior debe estar desactivado, y desactivarlo le pide
   confirmación primero.
3. **Inicio** y **Flujo**: lea lo que ha llegado: Inicio como señales medidas (Pistas), Flujo como
   una sucesión simple de artículos.
4. **Explorar**: búsqueda booleana de texto completo en todo lo que ha reunido; el
   análisis de los artículos coincidentes aparece debajo de los resultados.
5. **Perspectivas / Observatorio / Mapa del mundo / Gobiernos / Agenda / Clima / Índices /
   Materias primas / Fuentes vivas**: vistas opcionales sobre el corpus y sobre datos
   públicos (patrones, espacio-tiempo, derecho, fechas, registros climáticos, precios, qué cambió).
6. **Exportar**: CSV/JSON, o un **paquete de evidencia firmado** que cualquiera puede verificar
   sin conexión.

Elija cualquier herramienta en la barra lateral, o simplemente pulse **⌘K / Ctrl-K** y escriba
adónde quiere ir. Para un breve paseo por las pestañas de la barra lateral en su profundidad de
interfaz, elija **Hacer el recorrido** (Ajustes → General, Ayuda y documentación, o la paleta de comandos).
Solo empieza cuando usted lo pide, no cambia nada y no guarda constancia de haberse ejecutado. La vista activa se actualiza sola en directo (cada pocos segundos) mientras está en
pantalla, y las acciones se confirman con pequeñas notificaciones emergentes en la esquina.
Las acciones destructivas siempre preguntan primero.

---

## 3. Las herramientas, una por una

La barra lateral es una **lista plana** de las herramientas de datos (de arriba abajo):

- **Inicio · Flujo · Explorar · Perspectivas · Observatorio · Mapa del mundo · Gobiernos · Agenda ·
  Clima · Índices · Materias primas *(avanzado)* · Fuentes vivas · Biblioteca**, más el botón **Ajustes**
  en la parte inferior de la barra lateral. La Ayuda se abre desde el botón **?** de la barra superior.
  No hay una pestaña «Recopilar»: la recopilación está en Ajustes.
- **Explorar** es una sola página: el cuadro de búsqueda arriba y el análisis de los artículos
  coincidentes debajo de los resultados en cuanto una búsqueda responde (véanse [3.1](#31-búsqueda) y
  [3.1a](#31a-análisis-la-ventana-de-corpus)). Una palabra clave
  en la que se haga clic dentro de la aplicación abre su análisis en esta página; una palabra clave en el
  lector de artículos, el botón **Abrir el corpus ↗** de una Pista de Inicio y la tecla Enter en la
  omnibarra (omnibar) lo abren en Explorar en una **nueva pestaña del navegador**.
- La **Profundidad de la interfaz** (Ajustes → General) cambia lo que la barra lateral *fija*, nunca
  lo que puede alcanzar. En **Esencial** solo Inicio y Flujo están fijados y las demás pestañas quedan
  detrás de una fila rotulada **Mostrar más**; **Estándar** y **Completo** muestran todas las pestañas. La
  paleta de comandos (Ctrl/⌘-K) alcanza todas las pestañas en cualquier profundidad.

**Primero el contenido.** La barra lateral muestra los *datos*; las superficies de adquisición y
mantenimiento están en **Ajustes**: **Recopilar** (el planificador + la ingesta manual), **Fuentes**
(el catálogo), **Wikipedia** (seguimiento de cambios + volcados sin conexión), **Evidencia y custodia**
y la **mesa de integridad de fuentes (source-integrity desk)** se alcanzan todas desde Ajustes
(documentadas en sus propias subsecciones más abajo). Ajustes se abre desde el **botón de la parte
inferior de la barra lateral**; la paleta de comandos también lleva directamente allí.

Algunos nombres cambiaron para ser más sencillos (los controles son los mismos): **Ingesta (Ingest) → Recopilar**,
**Base de datos → Biblioteca**, **Derecho mundial → Gobiernos** (ahora con las subpestañas **Países · Mapa ·
Derecho**), **Mercados → Materias primas** (con **Índices** separado). Salte a cualquier herramienta con
la paleta de comandos (Ctrl/⌘-K).

### 3.0 Inicio

**Para qué sirve:** su **resumen informativo**: un flujo de triaje más orientación.

- **Resumen (el flujo):** la aplicación reúne y mide en segundo plano y luego
  presenta posibles noticias como **Pistas** (el nombre en pantalla de las tarjetas del resumen)
  agrupadas en categorías editoriales (*en auge, sobrerrepresentado, infrarrepresentado, investigar,
  revisar el encuadre, vigilar, contexto, integridad de los datos*). Cada Pista es **una señal
  medida + enlaces a la evidencia + una advertencia**: nunca un veredicto, y **no hay ninguna
  «puntuación de confianza»** (prohibida en el código).
- **Tarjetas giratorias: la advertencia está en el reverso.** Una Pista es una **tarjeta giratoria
  de dos caras**: el **anverso** es la pista de un vistazo; **haga clic en ella (o pulse Enter)** y
  gira para mostrar un **reverso** que contiene **la advertencia, el método, por qué se activó, la
  evidencia y un botón «Abrir el corpus ↗»** (que abre el conjunto exacto de artículos de esa Pista en
  una nueva ventana de análisis). La advertencia está en el DOM de forma predeterminada, justo al
  lado de la acción: nunca se oculta tras un interruptor de interfaz tranquila. **+ Añadir al borrador**
  fija una Pista; **Descartar** la oculta (es reversible). El flujo está en caché (instantáneo) y **se
  actualiza solo**: se recalcula en segundo plano tras cada pasada de rastreo y vuelve a sondear por
  su cuenta; no hay botón Actualizar.
- **Borrador de boletín:** las Pistas fijadas + sus notas, exportadas como **Markdown** en el que
  cada afirmación ya lleva sus enlaces a la fuente, su método y su advertencia: periodismo
  reproducible. Para una copia firmada de los artículos subyacentes, use Evidencia y custodia.
- **Diseño centrado en el contenido:** una franja compacta **de un vistazo** está fijada arriba
  (recuentos en directo + si la recopilación automática está en marcha), y las Pistas de abajo
  pueden filtrarse por **familia** mediante subpestañas verticales (una vista predeterminada **«Todas
  las pistas»**, más una pestaña por categoría con su propio tono de color). El catálogo seleccionado
  se carga automáticamente y la recopilación empieza al conectarse, así que un Inicio vacío
  simplemente muestra un estado vacío honesto, sin tarjeta de bienvenida. *(Se eliminaron el antiguo
  saludo de portada y la fila de «Acciones rápidas»: Inicio se abre directamente en el Resumen.)*

### 3.0a Actividad y el Administrador de tareas

**Para qué sirve:** ver —y dirigir— todo lo que la aplicación hace en segundo plano, desde
cualquier pestaña.

- Un **indicador de actividad** en la barra superior se ilumina mientras hay trabajo en curso (una
  pasada de recopilación, un volcado de Wikipedia, una importación de mercado); a su lado hay un
  botón permanente del **administrador de tareas** (sigue accesible incluso cuando la aplicación está
  inactiva).
- Abra el **Administrador de tareas**: una ventana propiamente dicha (no una ventana emergente) con
  cinco subpestañas:
  - **En curso**: cada trabajo en ejecución: la pasada de recopilación, cada volcado de Wikipedia
    que se está descargando, la obtención en curso (mostrada solo como DOMINIO), el bucle de
    inactividad y cualquier descarga en pausa o fallida. Cada trabajo muestra su progreso real y los
    controles aplicables: **Detener** una pasada de recopilación (esto también activa el interruptor
    de corte de red, así que queda sin conexión; el botón lo indica) y **Pausar/Cancelar** un volcado.
    Ningún tiempo restante ni velocidad inventados: solo el progreso real en bytes que informa el
    propietario del trabajo.
  - **Cola**: trabajos que esperan su turno: la cola de volcados de Wikipedia de descarga única, en
    orden, con controles **↑ / ↓** para reordenarla (adelantar un volcado francés pequeño a uno
    inglés enorme).
  - **Programación**: los datos reales del planificador: estado (en marcha / inactivo / detenido),
    progreso de la pasada actual (solo el dominio), cadencia, última ejecución y la hora de la
    próxima ejecución que da el propio backend, mostrada como tiempo relativo honesto (el método
    está en la burbuja al pasar el ratón; nunca una cuenta atrás inventada).
  - **Cobertura**: alcance y actualidad del rastreo por etiqueta (qué parte de cada tema/etiqueta
    toca realmente su recopilación y lo reciente que es), para que pueda ver las lagunas.
  - **Sistema**: constantes vitales del proceso en directo (CPU, RAM, velocidad de descarga). *(Las
    constantes vitales se trasladaron aquí desde la barra superior.)*
- La ventana lee **en directo de los sistemas que realizan el trabajo**, así que nunca puede
  contradecir lo que realmente está ocurriendo: no hay estado paralelo.

### 3.0b Flujo

**Para qué sirve:** leer su corpus como una **sucesión** en lugar de como un conjunto de señales
medidas. Inicio le dice qué destacó; el Flujo simplemente le entrega artículos, uno tras
otro, y le deja desplazarse.

- **Dos órdenes, ambos explícitos.** **Más recientes primero** es la fecha de publicación, la más
  reciente arriba. **Mezclado** es un orden fijo elegido por una **semilla**: la posición de un
  artículo depende de su id y de esa semilla y **de nada más**. Cada página lleva su propia línea de
  método que indica cuál de los dos está leyendo.
- **La mezcla es una ayuda para hojear, no un sistema de recomendación.** **No hay ninguna
  puntuación de interacción de ningún tipo**: nada mide qué abrió, cuánto tiempo se quedó ni qué
  se saltó, y **no se guarda ni se consulta ningún historial de lectura**. Dos personas con la misma
  semilla y el mismo corpus ven el mismo orden. Esa frase forma parte del texto del método que
  imprime la página, así que no puede dejar de ser cierta sin que se note.
- **Lo que queda fuera, contado.** El Flujo muestra los artículos que **no están en cuarentena**
  y cuya **fuente ha sido calificada**. Ambas exclusiones se **cuentan con exactitud** y se
  muestran en la primera página, de modo que un flujo corto sobre un corpus lleno se lee como
  *«sus fuentes aún no han sido calificadas»* —algo sobre lo que se puede actuar— y no como *«no
  tiene nada»*, que sería falso. Esos dos recuentos describen el corpus y no la página, así que
  se calculan una vez y no cambian al desplazarse.
- **Dónde se quedó.** El desplazamiento conserva su posición entre sesiones guardando **un único
  marcador de posición** en su navegador: una semilla y un solo cursor, nunca una lista de lo que
  leyó. **Ajustes → General → Historial de desplazamiento del flujo** tiene los dos controles:
  **Volver a mezclar** (una semilla nueva, un orden nuevo, vuelta al principio) y **Empezar desde arriba**
  (mismo orden, posición borrada).
- **La laguna honesta de cada orden.** La recopilación sigue en marcha mientras se desplaza, y cada
  orden pasa por alto de forma distinta los artículos recién llegados: en **Mezclado** pueden quedar
  *por debajo* del punto al que ha llegado (volver a mezclar los alcanza), y en **Más recientes
  primero** llegan *por encima* (volver arriba los alcanza). La página indica cuál se aplica.
- **Cada tarjeta** muestra el título, la fuente, la fecha y las **tres palabras clave principales
  propias** del artículo: las palabras clave de ese artículo, no de lo que haya buscado. **Leer más**
  despliega el resumen **en el mismo lugar**; el título abre el artículo en el lector local.

### 3.1 Búsqueda

**Para qué sirve:** encontrar artículos en su corpus. La búsqueda es la mitad superior de la
pestaña **Explorar** de la barra lateral; el análisis de los artículos coincidentes
([3.1a](#31a-análisis-la-ventana-de-corpus)) aparece justo debajo de los resultados, sin ningún
botón que pulsar. Una búsqueda sin palabras y sin filtro simplemente enumera todos los artículos y
no analiza nada.

- **Consulta booleana**: admite `AND` / `OR` / `NOT`, `"exact phrases"` y
  paréntesis con la precedencia correcta, p. ej.
  `(climate OR energy) AND policy NOT opinion`. Se apoya en SQLite FTS5 y está totalmente
  parametrizada (sin inyección).
- **Las palabras en árabe, chino y japonés se encuentran se escriban como se escriban.** Una palabra
  árabe coincide con o sin signos vocálicos y sea cual sea su grafía de alef, teh
  marbuta o alef maksura (أحمد encuentra احمد, مدرسة encuentra مدرسه), y una palabra china o japonesa
  se encuentra dentro de un texto más largo (东京 encuentra un artículo que dice 东京大学).
  El chino se divide en palabras con jieba en toda instalación; el japonés con sudachipy, que
  viene con el extra opcional `[segmentation]`. Los artículos indexados antes de esta versión
  se siguen encontrando como siempre, y también se encuentran por palabra una vez que se ha
  ejecutado **Reindexar la búsqueda** (Ajustes → Avanzado → Diagnóstico).
- **Filtros:** Fuente (nombre exacto), Idioma (un código como `en`) y un control de **rango de
  tiempo**: campos de fecha Desde/Hasta, una barra de rango que se puede arrastrar y preajustes rápidos
  (1M · 6M · 1Y · 5Y · All); es el *mismo* control que se usa en Mercados, Perspectivas y la
  ventana de Análisis. Si se deja en su extensión completa no excluye nada; acótelo para limitar la
  búsqueda a un periodo. Todos son opcionales.
- **Búsqueda** ejecuta la consulta; la tabla de resultados muestra **Título · Fuente · Publicado ·
  Idioma**, y un recuento (`N result(s)`, y cuántos se muestran si están truncados).
- **Acciones por fila:** **abrir** (una copia limpia y sin conexión del artículo guardado),
  **fuente ↗** (la URL original), **Resumir** y **Traducir** (LLM local, si
  Ollama está disponible).
- **Exportaciones:** **Exportar CSV**, **Exportar JSON** y **Exportar evidencia firmada**: un
  paquete firmado y a prueba de manipulaciones exactamente con los artículos que coinciden con su
  consulta (véase [Evidencia y custodia](#38-pruebas-y-custodia)). Primero abre una revisión: cuántos
  artículos y fuentes, qué contiene el archivo, que está sin cifrar y qué clave firma;
  guardar es un clic más, y el mensaje posterior enumera los miembros del archivo y la
  clave que debe entregar al destinatario. También hay un **Apéndice de métodos** (un registro
  reproducible de la consulta + el método).
- **Ejecuciones del modelo local sobre todas las coincidencias:** **Resumir todo** / **Traducir todo**
  ponen en cola una ejecución en segundo plano de su modelo local sobre cada artículo coincidente
  (guardada con el modelo + la fecha y, al ser resultado de IA, nunca incorporada al índice de
  palabras clave de confianza); **Ejecutar extractor** ejecuta uno de sus extractores de IA
  personalizados sobre el conjunto; **Sintetizar resultados** abre una ventana donde elige hasta 20
  miembros y obtiene una única pasada del modelo local, con citas, sobre ellos (véase el análisis
  en profundidad). Las ejecuciones se ponen en cola y se pueden cancelar; los mismos controles están
  en la ventana de análisis.

> **Dos formas de entrar.** Abra **Explorar** desde la barra lateral, o escriba en la omnibarra y elija
> *«Ejecutar la búsqueda booleana completa»*: ambas llevan a la misma página con la consulta ya rellenada.

**La omnibarra (Ctrl/⌘-K), desde cualquier lugar:** la paleta de comandos es también una
búsqueda federada en sus datos. A partir de dos caracteres escritos muestra los tres primeros
resultados por grupo —**artículos** (FTS booleana completa), **palabras clave** (cada una abre
su ventana de corpus), **fuentes**, **páginas de Wikipedia vigiladas**, **textos de Wikipedia
guardados en este equipo** (versiones anteriores y textos de páginas cambiadas que conserva el
apartado de Wikipedia; véase 3.7) y **documentos jurídicos seguidos**—, con el *total real* de cada
grupo indicado en su encabezado. Todo se apoya en índices y se busca solo en este equipo; una
consulta a medio escribir nunca es un error. Elegir *«Ejecutar la búsqueda booleana completa»* le
lleva a esta pestaña con la consulta ya rellenada, así que todas las capacidades anteriores quedan a
un paso.

### 3.1a Análisis: la ventana de corpus

**Para qué sirve:** convertir un *conjunto* de artículos, o una sola palabra clave, en un objeto
de análisis que puede leer desde todos los ángulos. Una palabra clave es un corpus; un solo artículo
es un corpus de uno. El análisis está en la página **Explorar**, debajo de los resultados de
búsqueda. Aparece cuando usted:

- ejecuta una búsqueda en Explorar (o elige *«Ejecutar la búsqueda booleana completa»* en la omnibarra),
- pulsa **Enter** en la omnibarra (esto abre Explorar en una nueva pestaña del navegador),
- hace clic en una **palabra clave** en cualquier lugar (Perspectivas, el reverso de una Pista o el lector, donde se abre en una nueva pestaña del navegador),
- hace clic en una **Pista de Inicio** (su «Abrir el corpus ↗» abre el conjunto *exacto* de artículos, en una nueva pestaña del navegador), o
- hace clic en el título de un gráfico de materia prima / en **Analizar ↗**.

Cuando se abre un análisis desde otro lugar (una palabra clave, una Pista, una materia prima), la
lista de búsqueda se aparta y la página indica de quién es el análisis que muestra, de modo que la
lista y el análisis nunca describen sin avisar dos conjuntos distintos de artículos. Varios análisis
conviven como **pestañas con nombre** en una franja superior; cada una lleva como título su consulta
y muestra el **número de artículos** sobre el que se calculó. Las subpestañas son:

- **Resumen**: una síntesis del conjunto de un vistazo.
- **Palabras clave**: la tabla clasificada de palabras clave (coocurrencia real / n / PMI, sin puntuación).
- **Tendencia**: la evolución de menciones/volumen en el tiempo, dibujada con el conjunto de
  herramientas de gráficos interactivo compartido (zoom con la rueda, desplazamiento arrastrando,
  lectura exacta al pasar el ratón; resolución completa dentro de la ventana, y los tramos escasos se
  muestran honestamente como barras + una advertencia de corpus incipiente en lugar de una curva
  fingida).
- **Mapa mental**: un mapa radial determinista de palabras clave (centro → ramas, siempre hacia fuera).
- **Artículos**: los artículos miembros (paginados). Columnas: **Título · Fuente ·
  Publicado · Palabra clave principal**, y cada encabezado de columna es el **control de ordenación**:
  haga clic en uno para ordenar por él y vuelva a hacer clic para invertir el orden; la flecha marca la
  columna vigente. Los nombres se abren de la A a la Z, y las fechas y los recuentos empezando por el
  mayor. La misma elección está en los selectores **Ordenar por / Orden** encima de la lista, porque
  son los mismos dos campos: hay exactamente una ordenación en esta ventana, así que nada puede
  anular su elección sin avisar. *(La ordenación estaba antes en **Avanzado**, a tres subpestañas de la
  única lista que la usa.)*

  **Palabra clave principal** es la palabra clave PROPIA más mencionada de este artículo, con su
  recuento, calculada cuando se indexó el artículo; es una pregunta distinta del recuento de la palabra
  clave *buscada*, que es el botón aparte `↕ "term" count`. Cuando varias palabras clave empatan en ese
  recuento, la fila indica **empatadas**, porque la que se nombra es simplemente la primera de ellas y
  llamarla la palabra clave principal afirmaría una clasificación que el recuento nunca estableció. Un
  artículo al que la reindexación aún no ha llegado muestra **—**, nunca un 0: le falta una medición,
  no le faltan palabras clave.

  Cada fila se abre en el **lector sin conexión**, cuya propia barra de pestañas es **Leer · Resumen ·
  Traducción · Palabras clave · Mapa mental · Sentimiento · Relacionados · Fuente · Enlaces**: ahí es
  donde lo lee, ve su **fuente original** (el texto visible del enlace es la URL completa)
  y ejecuta **Resumen / Traducción** con el modelo local. Esas tres cosas se repetían antes como una
  flecha por fila y dos botones por fila; se trasladaron a la única página que puede mostrar realmente
  el resultado. **Resumir todo / Traducir todo** en bloque no cambian en la fila de acciones de abajo.
  Las copias casi idénticas llevan la etiqueta «N copias = una sola voz».
- **Cuándo/Dónde/Quién**: las fechas, los lugares y las personas/organizaciones que menciona el
  conjunto, como **facetas** en las que se puede hacer clic; al hacer clic en un valor se **profundiza**
  solo en los artículos que lo mencionan (una ventana de análisis refinada). Deducido del texto, nunca
  confirmado.
- **Enlaces**: qué artículos miembros **comparten enlaces salientes**. Esto saca a la luz a propósito
  la *estructura de origen compartido*: tres artículos que citan un mismo origen son una sola fuente
  con tres sombreros, así que la convergencia cuenta como corroboración solo cuando las vías son
  independientes. El objetivo son las *fuentes de las fuentes*.
- **Relacionados**: copias casi idénticas entre fuentes («N copias = una sola voz») y orígenes
  compartidos, cada uno con un **«Ramificar a un nuevo corpus →»** que crea una nueva ventana de
  análisis sobre exactamente esos artículos.
- **Sentimiento**: tono por fuente (VADER; se muestra la advertencia de que solo funciona en inglés).
- **Fuentes**: la procedencia descriptiva de los medios del conjunto.
- **Competitivo**: cómo se comparan los medios del conjunto (volumen / tono / momento /
  énfasis; descriptivo, nunca un ganador ni una puntuación).
- **Precio**: *(solo cuando la ventana se creó a partir de una materia prima)* la curva de precios
  superpuesta a la cobertura de su corpus en un eje temporal compartido (coocurrencia, nunca
  causalidad), cada serie en su propia escala con unidades reales.
- **Avanzado**: acote el conjunto por **fuente · idioma · rango de fechas**; una etiqueta «Filtrado»
  y un resumen muestran lo que está activo. (La ordenación se trasladó a la pestaña Artículos, arriba.)

La fila de acciones contiene **Apéndice de métodos**, **Exportar evidencia firmada**, **Sintetizar
resultados** (la ventana de selección de miembros) y las ejecuciones del modelo local en cola
**Resumir todo / Traducir todo / Ejecutar extractor**: el mismo conjunto que la búsqueda de arriba.

### 3.2 Recopilar *(en Ajustes → Avanzado → Recopilación)*

> **Dónde está ahora.** La recopilación es una superficie de adquisición, así que salió de la
> barra lateral y pasó a **Ajustes → Avanzado → Recopilación** (el contenido primero). Los controles no han cambiado.

**Para qué sirve:** incorporar artículos al corpus, de forma automática o manual.

**A. Ingesta automática (el planificador).** Un proceso en segundo plano que ingiere según un
temporizador. Controles:

- **Iniciar / Detener / Recopilar ahora**: funcionar de forma continua, detenerse o ejecutar una sola pasada
  de inmediato. La etiqueta de estado muestra `running` / `running — scrape in progress` /
  `stopped` y la hora de la próxima ejecución; la línea de abajo muestra el recuento de la última ejecución.
- **Intervalo (minutos)** y un control deslizante de **Velocidad de recopilación** (un objetivo de velocidad de descarga). La
  aplicación mide su propia velocidad real de descarga y aumenta o reduce el número de servidores
  consultados a la vez para ajustarse a su objetivo, y se modera automáticamente cuando la CPU, la memoria o el único
  proceso de escritura cifrada pasan a ser el límite; la cortesía con cada servidor nunca se sacrifica a cambio de velocidad.
  *(No hay un límite de «máximo de fuentes por ejecución»: con el tiempo se cubren todas las fuentes, así que ninguna
  queda desatendida.)*
- **Modo:** *Canales RSS*, *Rastreo recursivo*, *Mercados (reglas de precios)* o *Wikipedia
  (páginas vigiladas)*. Al elegir **rastreo** aparecen **Profundidad de rastreo** y **Páginas máx. /
  fuente** (el rastreador se mantiene dentro del dominio propio de cada fuente, respeta robots.txt
  en modo de fallo cerrado, tiene un límite de frecuencia y unos límites estrictos: *descubre* artículos,
  no hace copias espejo de sitios).
- **Selección:** **Idiomas**, **Tipos de fuente** y **Etiquetas/palabras clave (coincide cualquiera) (Tags/keywords (match any))**
  acotan qué fuentes toca una ejecución. **Previsualizar objetivos** muestra exactamente cuántas
  fuentes coinciden (con un desglose por idioma y tipo) *antes* de ejecutar.
- **Iniciar automáticamente al arrancar** + **Guardar la programación** conservan la configuración.

**B. Ingesta manual.**

- **Ingerir el feed RSS de una fuente**: elija una fuente y haga clic en **Obtener feed**.
- **…o ingiere la URL de un solo artículo**: pegue una URL y haga clic en **Ingerir URL**.

En ambos casos la línea de resultado muestra un recuento: guardados, duplicados omitidos, bloqueados por
robots, etc. La obtención es siempre ética (robots en modo de fallo cerrado, límite de frecuencia).

### 3.3 Fuentes *(en Ajustes → Avanzado → Fuentes)*

> **Dónde está ahora.** Al igual que Recopilar, el catálogo de fuentes pasó a **Ajustes →
> Avanzado → Fuentes** (el contenido primero). Los controles no han cambiado.

**Para qué sirve:** registrar y seleccionar los medios de los que se recopila.

- **Añadir una fuente:** Nombre, Dominio, URL del RSS, Etiquetas → **Añadir fuente**. O bien **Sembrar
  fuentes iniciales** para registrar el conjunto seleccionado de interés público.
- **Gestionar fuentes (tabla):** filtre por texto de búsqueda, país, idioma, tipo, etiqueta
  y estado de activación. Las columnas se pueden **ordenar** (Nombre, Dominio, Tipo, País, Idioma,
  Prioridad (Priority), Artículos). En la propia tabla puede cambiar la **Prioridad** (1–3), activar o desactivar **Activadas**
  y **Eliminar** (con confirmación). Paginada, con un recuento `N source(s)`.
- **Importar / Exportar (CSV):** **Exportar todo (CSV)**, **Descargar plantilla** e
  **Importar CSV**. Columnas: `name`, `domain` (obligatorias), más `rss_url`,
  `source_type`, `country` (2 letras), `language`, `region`, `tags`
  (separadas por comas), `priority` (1–3), `rate_limit_ms`, `enabled`,
  `reliability_score` (1–10). La importación **inserta o actualiza por dominio**: se crean las filas nuevas
  y se actualizan las existentes, y **las filas incorrectas se notifican, no se descartan en silencio**.

#### Calificación de fuentes: el filtro de admisión

**Activar una fuente no basta por sí solo**: una fuente solo se *recopila* una vez que
ha sido **calificada**. Cada fuente lleva uno de tres sellos categóricos, nunca
una puntuación de calidad:

- **sin juzgar** (unqualified): aún no evaluada (el valor por defecto para una fuente descubierta, citada o añadida
  a mano);
- **calificado** (qualified): superó una pequeña obtención de prueba que comprobó la *validez de la extracción* (prosa
  real frente a una extracción rota o basura, p. ej. una página de menú de navegación o un muro de pago); a partir de ahí
  se incorpora a la recopilación habitual;
- **descalificado** (disqualified): las páginas extraídas en la prueba parecían estructuralmente rotas, no
  simplemente «aburridas» o escuetas (el estilo nunca se juzga, solo si llegó o no texto real
  de un artículo).

**El catálogo seleccionado que viene con la aplicación está calificado desde el principio** (decisión del
responsable del proyecto, 2026-09-10). Sus filas —los catálogos de noticias, espectro, mercados y derecho revisados a mano—
llevan un sello cuya *base* es el propio catálogo, que se muestra en el panel de procedencia de la fuente
como **calificado · por catálogo**, y se incorporan a la recopilación desde el primer día en lugar de esperar
su turno detrás de la cola de descubrimiento. El sello no es una medición y nunca se presenta como
tal: se vuelve a comprobar con el **mismo plazo de tres meses que cualquier fuente calificada** (véase más abajo),
una nueva comprobación fallida descalifica la fuente exactamente igual que a cualquier otra, nunca sobrescribe un veredicto al que esta instancia
ya haya llegado, y la exportación de calificaciones cuenta esas
filas aparte y nunca las distribuye como veredictos obtenidos. Las fuentes descubiertas, citadas y añadidas a mano
siguen pasando la prueba.

Un **proceso en segundo plano ejecuta automáticamente algunas de estas comprobaciones de prueba en cada pasada
de recopilación con conexión** (una obtención de «unos pocos artículos», acotada, consentida y en red, que se rechaza
en modo avión, exactamente igual que cualquier otra acción de red). En una instalación nueva con
muchas fuentes recién sembradas o descubiertas, ese goteo puede dejar una cola pendiente real: **Ajustes
→ Fuentes → «Cualificación de fuentes»** muestra el panel y un botón **«Cualificar la cola pendiente»**
que ejecuta la *misma* evaluación en bloque, como tarea cancelable del administrador de tareas, para
ponerse al día más rápido.

**La cola de calificación** (Avanzado → Controles de calidad) muestra lo que juzgarán las próximas pasadas,
en orden: **primero las fuentes nuevas** (nunca juzgadas, o probadas sin suficientes artículos
todavía) y después las fuentes a las que les toca una nueva comprobación. Una fuente nueva siempre es más urgente que una
nueva comprobación (decisión R94). El panel indica también cuántas fuentes calificadas están esperando y cuándo
entra la siguiente en la cola.

**Cuántas fuentes juzga una pasada** crece con el equipo (decisión R95): el número de
Ajustes → Avanzado → Controles de calidad (*Fuentes a juzgar en cada pasada de recopilación*) y las
*nuevas comprobaciones de calificación por pasada* del planificador (que se fijan mediante la configuración del planificador, `PUT /api/scheduler/config`;
no hay ningún control en Ajustes para ello) son un mínimo, y mientras el *presupuesto de calificación automático* está activado (el valor por defecto) cada pasada juzga tantas
fuentes nuevas y nuevas comprobaciones como permitan la memoria y los núcleos del equipo, sin un techo fijo. Un
ajuste por debajo de los valores por defecto, o 0, se respeta tal cual; al desactivar el modo automático los números quedan fijados
exactamente. Cada candidata se juzga sobre sus artículos más recientes, tantos como quepan en la memoria
disponible (al menos 2000), y la pasada indica a cuántas candidatas se aplicó ese límite.

**En un equipo pequeño** (con menos memoria que el mínimo de análisis de la aplicación), una pasada juzga las candidatas
frente a una **muestra de los 20 000 artículos más recientes** en lugar del corpus completo, y el
veredicto registra que se basó en una muestra (decisión R93). Antes, esos equipos se saltaban todas las
pasadas en silencio y nunca se calificaba ninguna fuente. Si ni siquiera la muestra cabe, la pasada
lo indica y no se inicia.

Una **fuente descalificada tiene una segunda oportunidad**: nunca se elimina, y el reloj
(nunca una reimportación ni una nueva cita) es lo único que desencadena una nueva comprobación:
1 mes después de la primera descalificación, duplicándose hasta un máximo de 6 meses (1 → 2 → 4 →
6), y volviendo al inicio en cuanto una nueva comprobación se supera. **Por eso una fuente recién añadida o
descalificada hace poco puede quedarse activada pero sin recopilar durante hasta seis
meses** sin recoger nada: si una fuente que usted añadió parece no aportar nunca artículos, compruebe la etiqueta
de calificación de su fila (véase más abajo).

**Dónde quedó el recuento de calificación:** el recuadro de la Biblioteca que antes mostraba una sola
cifra de «Fuentes» ahora muestra **tres cifras honestas y sin solapamientos**: *Fuentes
(en recopilación) (Sources (collecting))* (activadas **y** calificadas), *Fuentes pendientes de calificación (activadas) (Sources awaiting qualification (enabled))*
y *Candidatas descubiertas* (todavía desactivadas; véase más abajo), porque mezclarlas en
un único número hacía que una cola de descubrimiento generada por la máquina, de decenas de miles de candidatas,
se leyera como si la aplicación ya estuviera recopilando de todas ellas.

#### Nueva verificación: un sello no dura para siempre

Un veredicto es una medición, y una medición envejece. **Un sello de calificado se vuelve a comprobar
aproximadamente cada tres meses** (decisión R94, 2026-09-29) (el ajuste `qualification_recheck_per_pass` del planificador, solo por la API; 0
desactiva la nueva verificación). La nueva comprobación usa un intervalo fijo, no la escala de duplicación
de las descalificadas: la duplicación expresa una esperanza decreciente tras fallos repetidos y no tiene
sentido después de un éxito.

**Lo que una nueva comprobación puede y no puede ver, dicho con claridad:** juzga una fuente sobre todo su
historial almacenado, así que detecta una fuente que está rota *en general*, y **no**
notará una fuente que empeoró hace poco si años de buenos artículos pesan más que los
recientes. Su valor real es otro, y conviene conocerlo: una fuente admitida muy pronto,
con solo uno o dos artículos, se juzgó cuando todavía no había un corpus suficiente con el que
compararla; la nueva comprobación es la primera vez que se mide frente a una referencia
real.

Las nuevas comprobaciones tienen su **propio** presupuesto, independiente del que admite candidatas nuevas.
No es un detalle menor: mientras compartían presupuesto, una instalación con una gran cola de
fuentes sin examinar dedicaba todas las plazas a candidatas nuevas, y ninguna nueva comprobación —incluida
la segunda oportunidad de las descalificadas descrita arriba— llegaba a ejecutarse.

#### Los veredictos viajan: copias de seguridad e instalaciones nuevas

El trabajo de calificación hecho en una instancia **no se pierde al mover o fusionar corpus**.

- **Importar una copia de seguridad** trae consigo sus veredictos. Una fuente que el corpus entrante juzgó
  llega juzgada. Una fuente que *esta* instancia nunca ha juzgado **adopta** el
  veredicto entrante, en ambos sentidos, de modo que una fuente que otra instancia encontró rota no
  vuelve a entrar discretamente en la cola de prueba aquí. Un veredicto al que llegó *esta* instancia siempre prevalece:
  un corpus importado nunca puede anular el juicio de su propio equipo, en ninguno de los dos
  sentidos.
  El sello inicial del propio catálogo no es un veredicto de ese tipo: un veredicto *medido* importado
  lo sustituye. Cuando una fuente que solo lleva el sello del catálogo tiene un juicio importado más reciente
  de *descalificado*, el siguiente arranque la retira de la recopilación y la incluye en los
  diagnósticos; cuando el veredicto de su propio equipo no coincide con el importado, se conserva el suyo y la
  fuente se vuelve a comprobar antes de tiempo en su propia pasada de calificación.
- **Una instalación nueva parte de lo que midieron instancias anteriores.** La aplicación incluye
  `configs/source_qualification.yml`, una lista generada de veredictos, y los adopta en el
  primer arranque para las fuentes que nunca ha juzgado. Una fuente **ausente** de ese archivo simplemente
  llega sin juzgar y la juzga la primera pasada de calificación de la propia instalación, exactamente
  como antes de que existiera el archivo; así, el catálogo incluido es en la práctica dos listas: las
  fuentes ya calificadas por la aplicación y las que aún están por calificar.

Un veredicto adoptado se registra como **heredado**, no como algo que este equipo haya medido,
y conserva la fecha en que se alcanzó originalmente, de modo que nada se presenta nunca como si su
instalación lo hubiera medido. Lo que empieza de cero es el propio reloj de nuevas comprobaciones de su equipo: corre desde
el día en que adoptó el veredicto, no desde el día en que otro lo obtuvo. Por tanto, una primera descarga es
tranquila, y de eso se trata: un catálogo incluido siempre tiene más antigüedad que el intervalo de tres meses
cuando llega a usted, así que contar desde la fecha original haría que cada
instalación nueva volviera a calificar todo el catálogo el primer día, que es exactamente el trabajo que el
archivo incluido existe para ahorrar.

Esa contrapartida es deliberada y tiene un coste que conviene decir: la actualidad del catálogo
incluido ya no es algo que cada instalación restablezca por sí misma. Se
restablece cuando una nueva versión incluye una capa de veredictos regenerada a partir de instancias que *sí* han hecho
la nueva verificación. La exportación que se describe abajo informa de la antigüedad de sus veredictos, de modo que ese envejecimiento
es visible y no silencioso.

#### Devolver al proyecto los veredictos de su instancia

`GET /api/diagnostics/source-qualification-export` informa de lo que su instancia sabe sobre
sus fuentes incluidas —cuántas están calificadas, cuántas descalificadas, cuántas siguen
pendientes— y `?fmt=yaml` devuelve esa misma lista como el propio archivo de capa.
`scripts/merge_source_qualification.py` combina exportaciones de varias instancias en una sola.

Si ya reunió **paquetes de todos los diagnósticos** (all-diagnostics bundles) de esas instancias, no necesita
volver atrás y exportar de nuevo: el paquete contiene esa misma exportación como uno de sus miembros, y
`--from-bundle` la lee directamente del zip. Las dos vías son intercambiables y se pueden
combinar libremente en una misma ejecución:

```
python scripts/merge_source_qualification.py laptop-export.json \
    --from-bundle oo-all-diagnostics-desktop.zip \
    --from-bundle oo-all-diagnostics-server.zip
```

El informe impreso indica cuántas instancias fusionó y por qué vía. Un paquete cuyo
miembro de exportación no se completó se nombra, con el motivo que registró esa instancia; nunca
se omite en silencio, porque una capa que usted cree basada en tres instancias y que en realidad
se basa en dos es peor que un error.

Hay dos cosas que deliberadamente no hace. Nunca **resuelve un desacuerdo**: si una
instancia calificó un dominio que otra descalificó, eso se notifica para que lo revise una persona,
porque elegir un ganador automáticamente distribuiría a todas las instalaciones un veredicto que nadie revisó.
Y nunca cuenta un veredicto **heredado** como corroboración: importar una misma copia de seguridad en
ocho equipos es una medición vista ocho veces, no ocho mediciones.

#### Rastro de descubrimiento y recuento de citas calificadas

Haga clic en la fila de una fuente para **desplegar su rastro de descubrimiento**: **dónde se encontró**
(el canal de citas, el catálogo, referencias de Wikipedia, …) y, en el caso de una
fuente descubierta por citas, el **primer artículo que la citó** (con un enlace tanto
al artículo como a la fuente que cita). Al lado, un **recuento de citas calificadas** cuenta
los dominios que *esta* fuente cita a su vez, desglosados en **calificados / descalificados /
pendientes / no registrados**; cada número se puede pulsar y despliega la lista exacta.

Se trata de un **dato descriptivo, nunca un veredicto sobre ninguna de las dos fuentes**: citar un
dominio descalificado no es una culpa (un medio sano enlaza habitualmente a empresas,
plataformas o páginas rotas sobre las que simplemente *informa*), y citar muchos dominios
calificados tampoco es un aval (a una agencia de noticias la cita todo el mundo; un
centro de blanqueo de información puede citar fuentes reputadas a propósito). Léalo como una pista que
investigar, igual que cualquier otra señal medida en esta aplicación es una pista y no una
puntuación.

#### Idiomas que aún no podemos analizar: desactivados por defecto (conservados)

El motor de palabras clave y análisis solo puede **gestionar** idiomas para los que existe una *lista de palabras vacías*
y cuya escritura **separa las palabras con espacios**. La lista de referencia está en un único
módulo —[`src/analytics/managed.py`](../src/analytics/managed.py) (`MANAGED_LANGUAGES`)—,
que leen tanto el filtrado de fuentes como el informe del motor dentro de la aplicación, de modo que el manual no puede
desviarse del código. Según ese módulo, el conjunto gestionado es: **en, fr, de, es, it, pt, nl,
ru, ar, hu, id, sv, da, nb, no, pl, sr, sl, el, bg, hi, bn, fa, ur, uk, ro, cs, sk, ca,
sw, az, et, tr, fi, bs, hr**. Un idioma **que no** esté en ese conjunto sigue *dividiéndose en tokens*, pero sus
palabras funcionales (los equivalentes de «el/de/y») se cuelan como falsas palabras clave. **ja y th no están
segmentados** a menos que se instale el extra opcional `[segmentation]`: no tienen
espacios entre palabras, así que sin un segmentador la extracción de palabras clave falla por completo, haya o no
lista de palabras vacías. **zh** estaba en la misma situación hasta que jieba pasó a ser una dependencia básica en
0.4; está segmentado y, por tanto, gestionado en todas las instalaciones.

Por eso, recopilar material en esos idiomas produce **palabras clave basura** que:

- **contaminan los análisis**: las falsas palabras clave distorsionan asociaciones, tendencias y
  supergrupos, y
- **inflan el corpus**: cada agregación (Perspectivas, Grupos, el mapa mental) paga
  el coste de cientos de miles de filas sin sentido, lo que supone una lentitud real
  en corpus grandes.

Así que, por diseño: **una fuente nueva en un idioma no gestionado se siembra *desactivada***. Se
**conserva** (nunca se elimina) y se puede **volver a activar** por completo: puede seguir leyendo esos
medios, y en cuanto se añada una lista de palabras vacías para su idioma, puede volver a
activarlos. Es una contrapartida honesta: preferimos *no recopilar* lo que *desfiguraríamos*
antes que presentar análisis poco fiables. Un `enabled: true` **explícito** en una importación CSV
siempre prevalece (se respeta su selección), y una fuente cuyo idioma es **desconocido**
sigue activada (nunca desactivamos lo que no podemos clasificar).

**Para aplicarlo a un corpus existente:** Ajustes → Avanzado → Fuentes muestra cuántas fuentes activadas
están en idiomas no gestionados (y cuáles) y ofrece **«Desactivar fuentes en idiomas que aún no podemos analizar»**,
una acción en bloque reversible que las desactiva
(conservándolas). Puede volver a activar cualquiera de ellas en cualquier momento desde la tabla de fuentes.

### 3.4 Biblioteca

*(Llamada **Base de datos** antes de la 0.05.)*

**Para qué sirve:** una mirada honesta a lo que realmente tiene y a hasta dónde llegan sus
fuentes.

- **Estadísticas de la base de datos (Database stats):** recuentos animados y en directo (artículos, fuentes, dominios únicos,
  …), además del motor y del **tamaño en disco y la ruta** de la base de datos. Cada
  cifra es un recuento real o un tamaño real en bytes: nada es una estimación.
- **Cobertura mundial:** cuántos países alcanza su catálogo de fuentes, medido
  frente a ISO 3166: `covered/total countries`, `coverage %`, el número de países *no* cubiertos
  y el número de países con cobertura «escasa» (por debajo del umbral). Los países se almacenan como códigos ISO-2
  en minúsculas y **se muestran con su nombre completo** (una única capa de conversión,
  `src/catalog/countries.py`). Un bloque de **Equilibrio regional** compara las fuentes y los países cubiertos
  de cada continente con los mínimos de trabajo de
  `configs/catalog_targets.yml` (aspiraciones claramente etiquetadas, redactadas a partir de la
  forma real del catálogo), más una **protección contra la concentración** en los países principales: la métrica de la 0.0.9
  para reducir el sesgo centrado en EE. UU. La tabla enumera cada país con su región, su número de fuentes
  y unas **etiquetas de palabras clave temáticas** (procedentes de las etiquetas de las fuentes). **Haga clic en un país o en una
  palabra clave** para ir a Fuentes filtradas exactamente por esas fuentes. Un informe de carencias
  nombra los países que aún no tienen ninguna fuente. El panel se actualiza en directo (no hace falta un botón
  de actualizar); la misma métrica está disponible sin conexión mediante
  `python scripts/catalog_coverage_report.py`.

### 3.5 Mercados

**Para qué sirve:** seguir precios **reales** de materias primas, divisas y energía y
relacionarlos con el volumen de noticias.

- **Panel de tendencias del mercado (Market trends dashboard):** una tarjeta por serie de precios: símbolo, % de variación, último
  precio (divisa/unidad), número de puntos y un minigráfico. Un control de **intervalo de tiempo**
  —campos de fecha Desde/Hasta, una barra de intervalo que se puede arrastrar y ajustes rápidos (1M · 6M · 1Y ·
  5Y · All)— reajusta todas las tarjetas a una ventana exacta de inicio y fin (no a una lista fija de
  escalas); la serie completa se dibuja siempre con resolución completa dentro de ella, nunca
  reducida. Haga clic en una tarjeta para ver un gráfico completo y
  una **correlación precio↔noticias** (coeficiente real de Pearson/Spearman, valor p y
  tamaño de la muestra; nunca un número inventado). Las fuentes oficiales seleccionadas **se actualizan
  automáticamente en segundo plano** mientras tiene conexión (no hay botón de cargar o
  actualizar); el panel tiene además **subpestañas por categoría**, un selector de vista **Tarjetas/Familias**, una
  superposición **Comparar** (con un selector de escala Absoluta/Indexado/Log) y un eje temporal compartido.
- **Configurar fuentes de datos** (desplegable; la mayoría de los usuarios no lo necesitará):
  - **Fuentes de precios oficiales** (FRED, que incluye la **«Pink Sheet» del Banco Mundial**
    y las series de la **EIA**): **Importar** con un clic, además de **Gráfico**.
  - **Reglas de extracción de precios:** añada una regla (Fuente, Símbolo, Etiqueta, URL de la página, **selector
    CSS**, atributo/regex opcional, divisa, unidad, mercado). La regla de oro:
    **un número solo se guarda donde su selector realmente encuentra uno: nunca
    se adivina.** Use **Probar** para obtener la página una vez y ver el valor exacto encontrado, o
    el motivo exacto por el que no coincidió, antes de confiar en la regla.
  - **Feed personalizado (cualquier URL CSV):** apunte a cualquier CSV (la asignación por defecto es columna 1 =
    fecha, columna 2 = valor, la convención de FRED); los valores que faltan se omiten, nunca
    se guardan como cero.

Consulte [`docs/USER_MANUAL.md`](USER_MANUAL.md) para la referencia completa de las reglas de extracción.

### 3.5a Índices

**Para qué sirve:** **índices** bursátiles mundiales (S&P 500, NASDAQ, Dow Jones,
VIX, Nikkei 225 …), que se mantienen **separados de las Materias primas**, porque un índice es un
índice, no una materia prima.

- Un panel de series de índices con los mismos gráficos detallados y de resolución completa que
  Materias primas (subpestañas por categoría, filtro por etiqueta, superposición Comparar, vista Familias, un
  eje temporal compartido). Las fuentes oficiales seleccionadas (FRED, Stooq) **se actualizan automáticamente en
  segundo plano** mientras tiene conexión; no hay botón de importar o actualizar.
- Cada fuente lleva un **veredicto honesto propio** cuando no se puede obtener:
  *rechazada* ≠ *prohibida por robots* ≠ *serie muerta* ≠ *inaccesible* ≠ *sin conexión*, de modo que
  una fuente bloqueada falla de forma visible en lugar de mostrar un número falso. A través de Tor algunas
  fuentes las bloquea el servidor; el veredicto dice exactamente eso (véase §5.5).

### 3.6 Perspectivas

**Para qué sirve:** análisis de palabras clave y entidades sobre el **texto de los artículos
ingeridos**. *(Requiere el extra `[analysis]`; el reconocimiento real de entidades nombradas es
opcional mediante el extra `[nlp]` de spaCy.)*

- **Estado e indexación:** una etiqueta muestra `indexed/total articles · keywords (entities)
  · mentions · remaining`. **La indexación es automática**: sigue a la ingesta y, cuando usted
  abre Perspectivas, una actualización silenciosa en segundo plano despeja cualquier pendiente que quede (el recuento
  de «pendientes» baja a 0 por sí solo). **No hay botón «Indexar corpus» (Index corpus)**: se
  eliminó en favor de la indexación automática. Las personas, organizaciones y lugares se mantienen como
  unidades únicas; la indexación se puede reanudar y la barra se actualiza en directo. *(Desactive la indexación
  automática con `OO_NO_INDEX=1`.)*
- Ocho subpestañas:
  - **Explorar**: escriba una palabra clave o una entidad (p. ej. *inflación*, *Emmanuel Macron*,
    *Rio Tinto*) para obtener: una línea de **tendencia** a lo largo del tiempo; un **mapa mental de asociaciones**
    (términos que aparecen juntos, ordenados por PMI: grosor de la arista = coaparición, distancia =
    fuerza; haga clic en un nodo para recentrarlo); una tabla de **encuadre** (en qué difiere el
    tono de cada medio, mediante VADER, con los términos que destaca); y fragmentos **en contexto**
    con enlaces a la fuente, el lugar y la fecha.
  - **Tendencias**: **En aumento** (las palabras clave que más crecen, ventana reciente frente a ventana de referencia) y
    **Top** (las más mencionadas), más tres ventanas predefinidas (24h · semana · mes) una al
    lado de la otra, filtrables por tipo (términos/entidades/personas/organizaciones/lugares) y país. Haga clic en cualquier
    término para explorarlo; haga clic en ✕ para excluirlo.
  - **Fuentes**: las fuentes en tendencia en todo su corpus.
  - **Familias**: familias de palabras clave (variantes morfológicas agrupadas).
  - **Grupos**: supergrupos (conceptos paraguas duraderos) y **anillos** entre idiomas
    (un concepto y sus traducciones o sinónimos), editables.
  - **Mapa**: el mapa coroplético ooMap sobre su corpus (el mismo componente que la pestaña Mapa
    del mundo).
  - **Convergencia**: coaparición espacio-temporal de solo lectura: artículos que convergen en el mismo
    **lugar** dentro de una ventana temporal en torno a la fecha del suceso mencionado. La independencia se mide
    por **fuentes distintas** (una sola fuente muy prolífica no puede fabricar una); cada grupo
    lleva la advertencia «coaparición, nunca causalidad: una invitación a leer, no una prueba».
  - **Vigilancias**: sus condiciones guardadas de tipo «si ocurre esto, vigilar»: una consulta FTS local + un
    umbral + una ventana. Cuando el corpus incorpora suficientes artículos nuevos que coinciden, aparece una **Pista
    de vigilancia** en Inicio. Solo local, sin notificaciones, sin red, sin telemetría;
    crear / activar / editar / eliminar, con un historial de coincidencias.

Cada cifra es un agregado real con su tamaño de muestra y una advertencia. Consulte
[`docs/USER_MANUAL.md`](USER_MANUAL.md). Para ajustar qué palabras clave aparecen, use el
[filtro de palabras clave en Ajustes](#39-ajustes).

### 3.6a Mapa del mundo

**Para qué sirve:** ver *dónde* se sitúa su corpus: un **mapa coroplético** («Cobertura
mundial») que sombrea cada país según una dimensión medida de sus datos, con capas opcionales
de lugares, señales y ubicación de servidores. Está construido sobre un único componente de mapa reutilizable
(**ooMap**), y todos los controles están **dentro del mapa** (la convención de Google Maps):
zoom ＋/－, zoom con la rueda, desplazamiento arrastrando, ⛶ ampliar y los selectores de capa y de medida.

- **La medida del coroplético (selector dentro del mapa):** cambie lo que colorea los países entre
  **Fuentes · Artículos · Menciones de palabras clave · Tono medio**. Los recuentos usan una escala secuencial;
  **Tono medio** usa una escala **divergente** (positivo ↔ negativo en torno a cero) y lleva
  la advertencia de que **VADER solo funciona en inglés**, además del `n` de artículos puntuados: un país sin ningún
  artículo puntuado en inglés muestra «sin datos», nunca un neutro inventado.
- **Sin datos ≠ cero, con honestidad:** un país sin datos localizados se dibuja con un **patrón de rayado**
  etiquetado «sin datos», visualmente distinto de un cero real. Los territorios pequeños que el contorno
  simplificado no puede dibujar aparecen como **puntos**; las fuentes sin país **se cuentan pero
  nunca se sitúan** («N not mapped»).
- **Granularidad (selector dentro del mapa):** ver por **País** o agregar por **Continente**
  (una suma para los recuentos, una media ponderada por `n` para el tono, nunca una media de medias; un continente
  desconocido es, con honestidad, «sin datos»).
- **Capa de lugares:** active **Lugares** para situar las ubicaciones de las que *hablan*
  sus artículos (a partir del Cuándo/Dónde/Quién extraído en la ingesta, en una coordenada de nomenclátor) como
  marcadores huecos cuyo tamaño depende de la dispersión de artículos, con la advertencia **«Deducido del texto, nunca
  confirmado.»**.
- **Capa de señales + momento enfocado:** active **Señales** para situar sucesos espacio-temporales fechables
  (anclas seleccionadas, artículos del corpus, fechas extraídas) como puntos coloreados según su tipo; un
  **control deslizante de momento enfocado** recorre el tiempo (confirmado = relleno, futuro/no confirmado = un
  anillo discontinuo, que se desvanece con la distancia en el tiempo). Haga clic en un marcador para ver un panel de detalle: fecha,
  lugar, fuente, enlace oficial, **«Encontrar cobertura en su corpus»** y una lista **«Cerca en
  espacio y tiempo»** que deja claro que la coaparición *«no es una conexión ni una
  causa. Usted juzga.»*
- **Capa de IP de servidores:** opcionalmente, muestre las **ubicaciones de los servidores** de las
  fuentes, geolocalizadas sin conexión, con la advertencia honesta de que se trata de un nodo de CDN o un servidor anycast, **no** de una prueba
  del origen real del editor (y no disponible a través de Tor, donde el socket es el
  proxy, no el servidor).
- **Las costas y fronteras vienen incluidas:** la geometría de países y costas se distribuye con la aplicación
  (Natural Earth, simplificada): no hay nada que generar y no se inventa ninguna frontera.

Las fechas *de las que trata* una noticia se convierten también en **etiquetas de fecha por artículo**: abra el lector
sin conexión de un artículo para verlas enumeradas, **confirme o rechace** cada candidata, o **extráigalas** a petición;
el corpus se puede filtrar entonces por una fecha mencionada (`GET /api/article-dates/by-date`).
El extractor es de alta precisión: los años sueltos y los periodos vagos no se extraen, pero
las **palabras relativas ancladas** («ayer») y los **días de la semana sueltos** sí.

### 3.6b Agenda

**Para qué sirve:** un calendario de sucesos fechados: lo que está por venir, con fuentes y con honestidad.

- Una **cuadrícula mensual** (que empieza en lunes; nombres de meses y días en el idioma de su interfaz) es la
  vista por defecto, con las vistas **Semana · Trimestre · Semestre · Año · Década · Lista**
  junto a ella (una barra de navegación compartida). Los días con sucesos están marcados; haga clic en un día para ver los
  detalles y en el título de un suceso para abrirlo en el corpus.
- **Sucesos deducidos (de sus artículos):** las fechas futuras *mencionadas* en varios
  artículos aparecen como una capa **deducida** distinta y filtrable: cada entrada muestra una
  etiqueta «deducido · nunca confirmado» y los recuentos de artículos y fuentes, y su título abre
  el conjunto exacto de artículos. Solo recuentos, nunca un veredicto.
- **Astronomía, calculada localmente:** las cuatro fases principales de la luna (nueva, cuarto creciente, llena, cuarto menguante) y los equinoccios y solsticios se
  calculan en este equipo (algoritmos de Meeus, verificados frente a valores publicados en
  almanaques); cada entrada indica su **método y precisión** en la burbuja emergente.
  Las estaciones se nombran **con honestidad respecto al hemisferio**: nunca un «verano» a secas.
- **Contexto climático:** un conjunto de datos incluido de episodios de El Niño / La Niña (convención ONI
  del NOAA CPC); cualquier entrada que aún espere una verificación cruzada en la red abierta lleva una
  marca de verificación pendiente.
- **Las fechas móviles se marcan como tales**: la aplicación nunca inventa un día exacto para un
  suceso cuya fecha cambia cada año.
- **Los calendarios** (fuentes iCal de festivos, religiosas o astronómicas) se suscriben en
  **Ajustes → Agenda**, no aquí: la pestaña muestra los datos y la infraestructura está en
  Ajustes. Después se mantienen al día por sí solos: mientras la recopilación está activada, se importan
  los sucesos nuevos y cada fuente se vuelve a comprobar por turnos, unas pocas por pasada. Una fuente que falla se
  vuelve a comprobar al cabo de 1 mes, luego de 2, 4 y 6 —**con un tope, de modo que nunca se da por perdida
  una fuente de forma permanente**— y el recuento por pasada se puede ver en la **pestaña Programación del
  administrador de tareas**. Nada de esto se ejecuta al arrancar ni sin conexión. El propio **catálogo** de unas 500 fuentes
  (veredictos, carpetas de proveedores duplicados, añadir su propio `.ics`) es infraestructura y
  está en **Ajustes → Avanzado → Directorio de calendarios**.
- **Si el archivo de sucesos importados está tan dañado que no se puede leer nada de él** (cortado,
  JSON no válido o un error de lectura del disco en Linux o macOS), la Agenda lo lee como vacío y el registro
  lo indica. Antes de que el siguiente guardado lo sustituya (una importación, una restauración, eliminar una fuente), la aplicación conserva una vez el archivo dañado,
  sin cambios, como `calendar_feed_imports.json.damaged` en su carpeta de datos, para usted o para una
  herramienta de recuperación; un segundo daño nunca sobrescribe esa primera copia. No forma parte de una
  copia de seguridad. Puede eliminarlo usted mismo en cualquier momento. Un archivo en el que solo algunas entradas están dañadas
  se sigue leyendo: esas entradas se dejan fuera, el registro las cuenta y no se hace ninguna copia. Un
  archivo vacío tampoco se copia: no contiene nada que recuperar.

### 3.6b Fuentes vivas

La pestaña **Fuentes vivas** muestra lo que cambió en las fuentes que siguen cambiando
después de recopilarlas: Wikipedia, derecho y mapas, una subpestaña para cada una. Todo lo que contiene
se lee de este equipo; no se obtiene nada de la red para dibujarlo.

- **Wikipedia:** cuántas páginas sigue el flujo en directo, cuántos cambios
  notificó en los últimos 30 días y **de cuántos guardó el texto** («2 de 4»:
  dentro de un presupuesto, guarda algunos y cuenta el resto), el punto hasta el que cada
  fuente se leyó sin interrupción y los huecos que sabe que se perdió. Debajo, cada
  cambio, del más reciente al más antiguo; **Mostrar diff** abre la diferencia guardada cuando llegó el cambio.
  Un cambio que solo se contó lo indica y no tiene diferencia. Las páginas que sigue
  a mano (Ajustes → Wikipedia) también aparecen: elija una para leer sus revisiones
  seguidas. Cada versión a uno y otro extremo de la comparación tiene su propio botón **Añadir al
  corpus**: añade esa versión exacta como artículo independiente, con la fecha en que la wiki la
  creó, y lo indica cuando su corpus ya la contiene o contiene las mismas palabras. Una versión
  cuyo texto no se guardó no se puede añadir, y su botón explica por qué. Así es como una
  revisión guardada con **Seguir ahora** llega a su corpus, ya que la búsqueda todavía no las
  lee. Cuando el **recorrido de páginas** está activado (véase abajo), un grupo *Recorrido de páginas* indica qué
  está haciendo (recorriendo; en pausa, y por qué; o esperando a que pase un rechazo de la wiki) y,
  por edición, las páginas que ha enumerado **de las que cuenta la propia edición como artículos**
  («1 234 000 de 2 700 000»). Son dos recuentos, nunca un porcentaje: cada edición
  cuenta sus artículos a su manera, así que la primera cifra puede superar a la segunda. Cuando
  la obtención de las **otras páginas modificadas** está activada (véase abajo), un grupo *Otras páginas modificadas*
  (encima del del recorrido) cuenta las páginas que tienen un texto, las páginas modificadas que aún esperan
  el suyo, los textos obtenidos y las páginas que desde entonces han pasado a ser páginas que el flujo
  sigue, también por edición, e indica cuándo se detiene: al alcanzar una proporción indicada del
  presupuesto de almacenamiento, un valor por defecto propuesto que la aplicación muestra, no una decisión tomada.
- **Derecho:** los documentos que sigue el rastreador de legislación, la comprobación más reciente y la más antigua, y
  cada cambio real (una nueva comprobación que no cambió nada no se cuenta) con su
  diferencia guardada y un enlace a su copia local.
- **Mapas:** sus regiones de mapa descargadas, cuáles están en pausa o han fallado y por qué, y
  el espacio que ocupan.

La actualidad se muestra como fechas, nunca se juzga: lo reciente que tiene que ser algo depende de
la noticia. Los presupuestos se muestran, pero se fijan en **Ajustes → Datos y copia de seguridad**.

### 3.6c Clima

**Para qué sirve:** leer seis registros publicados sobre el clima y la Tierra junto a su corpus,
cada uno exactamente como lo publicó su editor. La pestaña tiene una subpestaña por conjunto de datos:

- **Temperatura**: NASA GISTEMP v4: *anomalías* de la temperatura global mensuales y anuales
  (diferencias respecto de la media de 1951-1980, en °C, no temperaturas).
- **Hielo marino**: NSIDC Sea Ice Index v3: la extensión diaria del hielo marino ártico o antártico, en
  millones de km².
- **El Niño**: el Índice Oceánico de El Niño (ONI) de la NOAA: la anomalía trimestral de la temperatura de la superficie
  del mar en la región Niño 3.4 del Pacífico.
- **Terremotos**: el catálogo del USGS: terremotos de magnitud 6,0 o superior en todo el mundo,
  contados por mes desde enero de 1973, con la mayor magnitud de cada mes.
- **Emisiones y energía**: Our World in Data: cifras anuales de emisiones y energía por
  país y región; cada columna conserva las condiciones de su productor original.
- **Estación meteorológica**: NOAA GHCN-Daily: temperatura, precipitación y nieve diarias en
  **una** estación, elegida por su identificador de 11 caracteres (por ejemplo `USW00094728`, Central Park
  de Nueva York). Una estación describe un lugar, no una región ni el clima.

**Cómo obtiene los datos.** No se descarga nada hasta que usted lo pide. Cada subpestaña tiene su propio
botón **Obtener del editor** (que pasa a decir **Actualizar desde el editor** cuando ya hay algo
guardado; en **Estación meteorológica** se escribe un identificador de estación y se pulsa **Obtener estación**, y después
**Actualizar esta estación**), que nombra el servidor al que se conecta. Pasa por la misma ventana de consentimiento que cualquier
otra acción de red y se rechaza mientras el modo avión está activado. La obtención se ejecuta en
segundo plano; el administrador de tareas la muestra. Leer lo que ya está guardado no hace ninguna llamada
de red.

**En qué puede confiar.** Cada subpestaña nombra su fuente, su licencia, su método y cuándo
lo obtuvo este equipo por última vez. Una nueva obtención guarda solo los valores nuevos o que el
editor revisó: los valores anteriores se pueden seguir leyendo, y los periodos que el editor dejó de servir
se cuentan, nunca se eliminan. Una celda vacía es un hueco publicado, nunca un cero. Nada de lo que hay aquí es
una previsión, una puntuación ni una valoración de riesgo.

### 3.6d Observatorio

**Para qué sirve:** ver todo su corpus de un vistazo, dibujado como un cielo nocturno. Cada
**galaxia** es un grupo de palabras clave relacionadas; cada sector del círculo es uno de doce dominios
temáticos.

- El **ángulo** indica solo el dominio. El lugar que ocupa una galaxia dentro de su sector procede de un
  hash estable, de modo que no se mueve entre visitas y no significa nada por sí mismo.
- La **distancia al centro** indica la medida que usted elija, con anillos etiquetados.
  El **tamaño de la estrella** se dibuja como superficie (menciones) y es una indicación secundaria.
- El **color** muestra el idioma o la lente de **Tendencia**; nunca es la única señal.
  Las líneas de constelación unen galaxias que comparten una palabra clave miembro, nunca galaxias que
  simplemente parecen cercanas.
- La **tabla ordenada** bajo el cielo enumera todas las galaxias por completo, incluidas las que el
  cielo no puede situar. La tabla es la vista canónica; el cielo es una segunda forma de leerla.
  Una línea encima de ella cuenta lo que la imagen deja fuera (galaxias aún no observadas y
  palabras clave que no pertenecen a ninguna galaxia).
- El mismo corpus dibuja siempre el mismo cielo, así que un cambio que usted vea es un cambio en sus
  datos. No hay ninguna puntuación compuesta.

### 3.7 Wikipedia *(en Ajustes → Wikipedia)*

> **Dónde se encuentra ahora.** El seguimiento de cambios de Wikipedia y las herramientas de volcados
> sin conexión se trasladaron a **Ajustes → Wikipedia** (el contenido primero); las páginas vigiladas
> siguen apareciendo en la búsqueda general y en el análisis como cualquier artículo. Los controles no han cambiado.

**Para qué sirve:** vigilar páginas concretas de Wikipedia y **señalar las ediciones
sospechosas**: los datos son las *ediciones*, no una copia del artículo.

- Añada una página para vigilarla indicando la **Edición** (código de idioma, p. ej. `en`, `fr`, `ar`),
  el **título del artículo (Article title)** y, opcionalmente, una etiqueta de **Lista de seguimiento**. La aplicación guarda **una
  sola instantánea de referencia** y después solo las **diferencias/deltas** de cada nueva edición, de modo que los cambios
  cosméticos no cuestan casi nada.
- **Seguir ahora** (opcionalmente **usando puntuaciones ORES**) descarga las revisiones nuevas y señala
  las grandes o sospechosas: grandes variaciones de tamaño, etiquetas de reversión o vaciado, ediciones anónimas,
  ráfagas de ediciones y, si se activa, las puntuaciones de aprendizaje automático de ORES (dañina/buena fe). Las candidatas
  se *le presentan para que usted las juzgue*; nada se etiqueta como «desinformación».
- **Cambios marcados** enumera las ediciones (Cuándo · Edición · Página · Editor · Δ bytes ·
  Motivos · ORES), con un visor de **Diferencias** y un enlace **en vivo (live)** a Wikipedia.
  Puede filtrar por *solo marcados* y por edición.

**Las páginas vigiladas son artículos del corpus (las decisiones sobre fuentes vivas, explicadas):**
cada página que vigila se incorpora también a su corpus como artículo, bajo una fuente por
edición («Wikipedia (en)»), de modo que aparece en la **búsqueda general, las palabras clave y
Cuándo×Dónde×Quién como cualquier otro artículo**. Las decisiones que la aplicación toma por usted,
a la vista: (1) lo que ven la búsqueda y la analítica es siempre la **versión más reciente**
que ha descargado el rastreador, y se registra el identificador exacto de la revisión a la que
corresponde; (2) el **texto completo de cada revisión rastreada se guarda en este
equipo**: las versiones anteriores pueden reconstruirse con exactitud (analítica anclada a una versión,
sin reproducir diferencias), con el coste, dicho con franqueza, de que el almacenamiento crece con la
actividad de edición; (3) el texto analizado es wikitexto reducido a texto plano, nunca
presentado como si fuera el artículo renderizado. Todo se queda en local; el historial de
cambios sigue disponible por página, y la pestaña **Fuentes vivas** lo muestra
([3.6b](#36b-fuentes-vivas)).

**El presupuesto de almacenamiento del canal (150 GB por defecto, usted puede reducirlo):** el canal de Wikipedia
deja de guardar texto al alcanzar el total que usted fijó en el asistente de primer uso (o en **Ajustes →
Almacenamiento**, junto al cálculo frente al espacio libre en disco de este equipo). El valor por defecto es
**150 GB** desde la decisión del 2026-09-29, frente a los 20 GB anteriores; redúzcalo a 20 GB, o a cualquier valor
de hasta 1 GB como mínimo, si el disco es pequeño. Una instalación que ya pasó por el asistente
conserva la cifra que aceptó; una que nunca vio el asistente sigue el nuevo valor por defecto
hasta que usted fije el suyo.

**El recorrido de páginas (desactivado salvo que usted lo active):** el flujo en directo solo se entera
de las páginas que alguien edita, así que la mayor parte de una enciclopedia nunca le llega. Al marcar
**Recorrer también todos los títulos de artículos** (Ajustes → Wikipedia, en *El flujo de edición
en directo*) se listan todos los artículos de las ediciones que eligió, 50 títulos por solicitud, una
solicitud cada vez, entre las propias lecturas del flujo, durante varios días. Guarda de cada
página el título, el tamaño, la revisión más reciente y el identificador de Wikidata, nunca su texto, dentro del mismo
presupuesto de almacenamiento, y nunca la convierte en una página que el flujo siga por completo. Solo
funciona mientras funciona el flujo en directo, por la misma conexión: el modo avión, o el
modo protegido sin un proxy utilizable, lo hacen **esperar** (nunca se conecta directamente), y a un
wiki que le pide ir más despacio se le vuelve a consultar tras una pausa que se duplica hasta una
hora. Tras un reinicio, cada edición se reanuda donde se detuvo. Su progreso aparece en **Fuentes
vivas** y en el administrador de tareas.

**Por qué el recorrido puede esperar detrás del primer vaciado del flujo.** El flujo guarda lo que ha recibido en
un vaciado cada 30 segundos; el índice de búsqueda, la descarga de otras páginas modificadas y el recorrido funcionan
en el tiempo *posterior* a cada vaciado. Un vaciado descarga el texto de las páginas seguidas que cambiaron,
y con un retraso acumulado (un flujo reanudado horas atrás) eso supone miles de solicitudes corteses, así que el
vaciado tiene ahora un **límite de 20 segundos para descargar textos**, repartido entre las ediciones
(la primera edición rota en cada vaciado). Cada cambio se sigue registrando; un texto al que no se llega a
tiempo se cuenta como *aplazado* y **un vaciado posterior lo descarga**: primero las páginas que nunca se guardaron,
después las que llevan más tiempo sin comprobarse (hasta 200 páginas por edición y por vaciado; `text_backlog` en el
informe del vaciado indica cuántas *encontró* esperando la puesta al día, lo que no equivale a cuántas descargó). Esas páginas
se intentan antes que los cambios más recientes de la edición dentro de su parte de tiempo. Una página que falló o fue
rechazada queda apartada de la puesta al día durante 5 minutos, de modo que una que el servicio rechaza una y otra vez no
se pide cada 30 segundos. El cliente
hace una solicitud por segundo, así que un vaciado descarga unos veinte textos: con miles de textos
aplazados, la puesta al día tarda horas, no un solo vaciado. El límite restringe cuándo puede *empezar* una descarga: una
que ya está en curso termina primero (cada conexión o lectura espera hasta 30 segundos), así que un vaciado puede
durar algo más de 20 segundos. Mientras el recorrido de páginas está activado, se reserva el 30 % del tiempo de inactividad, de modo que la descarga de otras páginas modificadas
no puede usarlo todo. El estado (`/api/scheduler/status`, el bloque `wiki_lane.service.drain`)
indica en qué punto está el vaciado: la etapa (`hot-sets` o `feeds`), la edición, cuánto tiempo lleva
en este vaciado y cuántos vaciados han fallado seguidos y por qué.

**Cómo leer la W de la barra superior.** La W es el interruptor del **flujo**, no del recorrido: el
recorrido es la casilla de arriba, y solo funciona mientras funciona el flujo. La pequeña marca en la
esquina de la W indica por su forma lo que hace el flujo: un punto relleno significa conectado y recibiendo;
un anillo significa *elegido pero no conectado* (el modo avión lo retiene, o no se ha iniciado en esta
sesión); un anillo con un punto significa que intenta conectarse y falla, y lo reintenta por sí solo; un guion significa en pausa;
una cruz significa detenido. Pase el cursor por encima para leerlo en palabras, incluido si el recorrido de páginas está activado. Un clic
en un anillo **inicia** el flujo (usted confirma una vez el paso a en línea); un clic en un punto o en un anillo
con un punto lo **pone en pausa**; Mayús+clic lo detiene. Ajustes → Wikipedia muestra las mismas dos líneas
en palabras encima de las ediciones. Ambos se actualizan cuando usted se conecta o se desconecta, y cuando marca
o desmarca el recorrido.

**Las otras páginas modificadas (desactivado salvo que usted lo active):** el flujo en directo guarda
el texto de las páginas que sigue y solo cuenta los cambios que notifica en todas las
demás páginas. Al marcar **Obtener también el texto de otras páginas modificadas** (Ajustes →
Wikipedia, junto a la casilla del recorrido) se descarga también el texto más reciente de esas otras páginas,
50 páginas por solicitud, empezando por la que lleva más tiempo esperando. Una página editada diez veces
mientras esperaba cuesta una sola descarga, de su estado actual. La aplicación guarda el texto **más reciente y el
anterior** de cada página, y una página eliminada después conserva el texto que tenía. Estos
textos **se quedan en el archivo propio del canal, no en su corpus**; el cuadro de búsqueda los encuentra
(consulte *Buscar en lo que guarda el canal*, más abajo). Se detienen cuando el archivo del canal ocupa el **90 % de su presupuesto de almacenamiento**, para que el
resto quede para las páginas que sigue el flujo; esa proporción es un valor por defecto propuesto, no una
decisión firme, y Fuentes vivas la muestra. Solo funciona mientras funciona el flujo en directo, por la
misma conexión y con las mismas esperas que el recorrido: el modo avión, o el modo protegido
sin un proxy utilizable, lo hacen esperar (nunca se conecta directamente), y a un wiki que le pide
ir más despacio se le vuelve a consultar tras una pausa que se duplica hasta una hora.

**Un fallo o una actualización no hacen perder la ejecución.** Todo lo que guarda el canal se escribe en
pequeños pasos de todo o nada, así que un fallo (o cerrar la aplicación a la fuerza) pierde como mucho el paso en curso; el
recorrido se reanuda desde su marcador y el flujo desde la última posición que guardó. Lo que sí
se detiene es el propio canal: la aplicación siempre arranca **sin conexión**, así que tras un reinicio no se
descarga nada hasta que usted vuelva a conectarse con el botón de avión, lo que reanuda la ejecución si estaba activada y la deja desactivada si estaba desactivada (Inicio muestra una línea mientras la ejecución espera). No se pierde nada mientras espera
(el historial propio del flujo abarca aproximadamente una semana). Fuentes vivas → Wikipedia → Flujo
en directo muestra **Funcionamiento hasta ahora** (las horas en las que esta instalación guardó o solicitó algo,
contadas a través de los reinicios, con el número de paradas) y, cuando el canal se ha quedado en silencio, una
línea **Detenido** con cuánto tiempo y desde cuándo. Las mismas cifras figuran en el informe de la ventana de
prueba de resistencia como `wiki_lane.run`. Una parada indica que el canal no dio señales de vida durante tres o más
horas, no el porqué: un fallo, una actualización, el modo avión y una aplicación cerrada se ven igual.

**Buscar en lo que guarda el canal:** el canal mantiene un índice de búsqueda de los textos que
guarda, en el mismo archivo y dentro del mismo presupuesto de almacenamiento. El texto **más reciente** de una
página modificada se indexa completo, título incluido. Cada **versión anterior** (el texto anterior de una
página modificada, y cada versión de una página que sigue el flujo salvo
la más reciente, que ya es su artículo del corpus) se indexa por las **líneas que eliminó una edición
posterior**: el resto está en la versión más nueva, donde ya se encuentra.
Así, una búsqueda cuyas palabras estén en parte en líneas conservadas y en parte en líneas eliminadas no encuentra
ninguna de las dos versiones, y toda lista de estos resultados lo indica. El índice se construye mientras
funciona el flujo en directo, antes de las descargas y durante como mucho la mitad de su tiempo de inactividad, y
una búsqueda indica cuántos textos siguen esperando a ser indexados; un texto que no puede leerse
se aparta y se vuelve a intentar la próxima vez que arranque el canal. El chino, el japonés y el
árabe se segmentan y normalizan exactamente igual que en el índice propio de su corpus, y las palabras en hindi y
bengalí se mantienen enteras. En el cuadro de búsqueda (Ctrl/⌘-K) estos resultados aparecen bajo
**Textos de Wikipedia guardados en este equipo**, junto a los resultados de su corpus y nunca clasificados
entre ellos, cada uno con su edición, qué texto es (el texto más reciente o el anterior de una página
modificada, o una versión anterior de una página que sigue el flujo) y su fecha.
Al abrir uno se muestra el texto de esa versión, dónde se guarda y su dirección completa en
Wikipedia; **Añadir al corpus** añade esa versión exacta como artículo propio, con la fecha en que
el wiki la creó, y lo indica cuando su corpus ya la contiene, o contiene las mismas palabras, en lugar de guardarlas dos veces.
Fuera de esto, nada del canal llega a su corpus.
La página **Explorar** enumera esos mismos resultados en una sección propia debajo de los resultados de su
corpus, cada uno con el pasaje que coincidió y su propio botón **Añadir al corpus**.
Encima indica qué se ha buscado: solo los textos que el canal de Wikipedia
guarda en este equipo, nunca la propia Wikipedia, con las páginas y ediciones de las que proceden,
cuántos textos siguen esperando al índice y si la descarga de otras páginas
modificadas está desactivada. Así, una lista vacía significa que los textos del canal no contienen sus
palabras, no que Wikipedia no las contenga. Las versiones que **Seguir ahora** (Ajustes → Wikipedia)
guarda para las páginas vigiladas también están en esta búsqueda: permanecen en la base de datos de su corpus,
y el índice del canal, en su propio archivo, las lee de la misma manera (cada versión anterior por
las líneas que eliminó la siguiente versión guardada, la más reciente completa salvo que su artículo
del corpus ya sea esa versión). Aparecen bajo el mismo encabezado, marcadas como
guardadas por el rastreador de páginas, y **Añadir al corpus** añade esa versión exacta como cualquier
otra; la búsqueda indica cuántas páginas rastreadas leyó. Una página que usted sigue y rastrea a la vez puede
mostrar una versión una vez por cada almacén: los dos almacenes se leen por separado, y ninguno depende del
otro. Los volcados descargados no están en esta búsqueda: su texto
se encuentra en el grupo Wikipedia del cuadro de búsqueda. Una consulta se interpreta igual en ambas listas (`salt*`,
`NEAR(salt works, 5)`, `title:salt`), pero los filtros que describen artículos (los
cuadros Fuente, Idioma y Hora, y `source:`, `author:`, `url:`, `tag:` y
`title:=`) no alcanzan a estos textos, y la sección lo indica siempre que se aplica alguno.
Las exportaciones, la ventana de análisis y las acciones masivas actúan sobre su corpus; un texto de Wikipedia
se incorpora a ellas una vez que usted lo añade.

**Un elemento a través de las ediciones, y las páginas más vistas** (Fuentes vivas → Wikipedia, en la
parte inferior). Dos vistas que solo leen lo que este equipo ya guarda; ninguna descarga nada.
*Un elemento a través de las ediciones*: escriba un elemento de Wikidata (Q42) o pulse una de las sugerencias (los
elementos cuyas páginas acumularon más cambios registrados por el flujo esta semana) y una tabla muestra, para
cada edición que sigue, la página de esa edición, su **tamaño en bytes de wikitexto** (leído una vez,
cuando el recorrido de páginas llegó a la página), cuándo se leyó y los **cambios que este equipo
registró en los últimos siete días**. Una edición sin página indica el motivo: el recorrido no se ha ejecutado
para ella, no la ha terminado (y hasta dónde llegó, por lo que el elemento podría estar ahí), o la terminó
y no encontró ninguna. El recuento de cambios es lo que el flujo en directo registró en este equipo; para una edición de la que
no ha registrado nada, indica «desconocido», porque eso no equivale a cero. La barra junto a un tamaño es ese tamaño respecto al mayor de la pantalla,
desde cero; no se calcula nada más, y las ediciones son artículos distintos, no
traducciones. El recorrido de páginas está desactivado hasta que usted lo activa (Ajustes → Wikipedia), así que en una
instancia que no ha hecho el recorrido todavía no hay nada que comparar y la tabla lo indica.
*Páginas más vistas junto a su corpus*: la propia lista de la fuente con las páginas más vistas de su
último día (posición y número de visitas tal como los dio; se conservan las cincuenta primeras filas), cada una junto al
número de artículos de **su corpus** que mencionan el título como frase, publicados ese
día UTC y en los siete días que terminan en él. Es **un solo día, no una serie**: la lista se
sobrescribe cada día y no se guarda ningún historial de visitas por página. Los recuentos son los de su corpus,
es decir, lo que este equipo recopiló, no la prensa en general; un título puede ser ambiguo o escribirse
de otra forma en otro idioma; los artículos procedentes de Wikipedia y los que están en cuarentena no se cuentan;
una fila a la que el recuento no llegó dentro de su límite de tiempo, o cuyo título no tiene palabras que el índice de búsqueda pueda encontrar (un «-» aislado), indica «no contado», con el motivo al pasar el cursor; las sugerencias solo leen las 400 páginas más modificadas de la semana. Las dos cifras se muestran
una junto a otra y nunca se combinan.

Las pesadas **referencias de texto completo sin conexión** (volcados de ediciones enteras) son *independientes* y se encuentran
en **Ajustes → Wikipedia**; no las necesita para el seguimiento de cambios. Consulte
[`docs/USER_MANUAL.md`](USER_MANUAL.md).

**Leer un volcado descargado (sin conexión):** las nuevas descargas de volcados usan el
formato *multistream*, y el pequeño índice que lo acompaña se descarga con ellas: ese
par permite el acceso directo al volcado. En **Ajustes → Wikipedia → Leer una página de un
volcado descargado**, elija una edición lista, escriba el título de una página y la aplicación recorre
el índice, descomprime un pequeño bloque en su desplazamiento de bytes y muestra el
**wikitexto en bruto** de la página, todo en este equipo y con las estadísticas del recorrido a la vista.
Lo que lee es una *instantánea a fecha del volcado*, no el artículo en vivo; se ofrece una
coincidencia de título sin distinguir mayúsculas y minúsculas, y se indica como tal. Los archivos antiguos de flujo único
no permiten acceso aleatorio: la aplicación lo indica y sugiere volver a descargarlos.
La **lista de idiomas de los volcados se limita a los idiomas de la aplicación** (los 12 idiomas
de la interfaz más los idiomas del corpus que admiten los analizadores); el selector de edición de las
páginas vigiladas, más arriba, mantiene la lista completa.

### 3.7a Gobiernos

**Para qué sirve:** la pestaña lateral **Gobiernos** (el ancla del código sigue siendo `law`, la
etiqueta es «Gobiernos») reúne datos oficiales por país y sigue cómo cambia el **derecho**.
Tiene seis subpestañas:

- **Países**: **estadísticas oficiales** por país del Banco Mundial (PIB,
  población, esperanza de vida, trabajo, finanzas públicas + índices habituales). **Cargar datos estándar
  por país** las descarga (en línea, sujeto a consentimiento). Cada valor es la cifra publicada por un productor,
  **nunca una puntuación de credibilidad**; un **valor ausente es una laguna publicada,
  no un cero**; los productores se muestran, **nunca se promedian**. Cada cifra lleva su unidad, y
  al pasar el cursor sobre cada indicador se explica qué mide; dos que parecen errores y no lo son:
  las suscripciones móviles pueden superar las 100 por cada 100 personas (hay quien tiene varias SIM) y la tasa bruta
  de escolarización puede superar el 100 % (cuenta a los repetidores y a los alumnos que superan la edad teórica).
- **Comparar**: dos países lado a lado, cada indicador en una fila alineada. Se trata de una
  **presentación**, no de un cálculo: muestra la última cifra publicada de cada país y
  el año al que corresponde, y donde un país no tiene cifra la celda se muestra como una **laguna**.
  Nunca resta, clasifica ni puntúa el par: la comparación la hace usted.
- **Grupos**: agregados y bloques, en dos **enfoques** entre los que se puede alternar:
  - *Publicado* muestra los agregados que publica el propio productor (los de «Ingreso alto»,
    «África subsahariana», «Unión Europea», etc., del Banco Mundial). Primero se abre una lista
    seleccionada; **Mostrar todo** la amplía al conjunto completo. Son las cifras propias del productor,
    no las nuestras. **Las regiones del Banco Mundial no son continentes**: «África subsahariana»
    excluye a Egipto, Libia, Túnez, Argelia y Marruecos, que están en su región de Oriente Medio y
    Norte de África, así que este enfoque **no tiene ninguna cifra para África como continente** y lo
    dice, en lugar de componer una que parecería oficial.
  - *Calculado (Computed)* agrega nosotros mismos los países miembros, y muestra **varias estrategias lado
    a lado** (media ponderada por población, media simple, ponderada por PIB, mediana y un total
    cuando tiene sentido), para que vea cuánto depende la respuesta del método
    en lugar de recibir una sola cifra. No se clasifica nada y ninguna estrategia se declara
    la mejor. Solo se ofrece un **total** para los indicadores en los que sumar tiene sentido
    (población, PIB, población activa); para un porcentaje, una tasa o una esperanza de vida se
    **rechaza mostrando el motivo**, porque sumar porcentajes produce una cifra que nadie
    ha medido. Cada cifra indica su **cobertura** y su **dispersión** (mín./máx./n):
    un titular de bloque que oculta un rango de diez veces es cierto y engañoso, así que el rango lo acompaña.
    Cuando faltan miembros, el agregado se **rechaza por defecto**; puede
    publicarlo de todos modos, y entonces el resultado se etiqueta como parcial y nombra exactamente qué
    miembros faltan. La composición de los bloques cambia con el tiempo (los BRICS tuvieron cinco miembros hasta
    2024; la UE perdió al Reino Unido en 2020), así que cada cifra de bloque indica la **composición
    vigente** con la que se calculó, y un bloque cuya lista de miembros aún no podemos documentar con una fuente lo dice
    claramente en lugar de mostrar una cifra.
- **Mapa**: un **mapa de coropletas ooMap** de un indicador seleccionable, con un selector de año e
  historial; haga clic en un país para abrir su detalle en la subpestaña Países.
- **Derecho**: seguimiento del **derecho** (leyes, boletines oficiales, registros de propiedad intelectual) a partir de fuentes oficiales
  de todo el mundo, observando cómo cambia con el tiempo (los *cambios son los datos*). Es un **espejo
  de investigación**, nunca la fuente oficial y **no constituye asesoramiento jurídico**: cada registro enlaza
  a su boletín oficial. Por defecto se carga un catálogo mundial de fuentes oficiales reales
  (`legislation.gov.uk`, EUR-Lex, Légifrance, govinfo, WIPO Lex, USPTO, EPO, …).
  **Rastrear cambios ahora** descarga los documentos seguidos mediante el descargador
  ético, guardando una referencia y después **diferencias** fieles, con una marca para los cambios grandes; **Cambios
  legales señalados** los enumera (jurisdicción · título · Δ bytes · motivos) con las diferencias y
  un enlace a la fuente oficial. El resumen también muestra una Pista de **legislación modelo**
  cuando aparece un texto casi idéntico en varias jurisdicciones.
- **Estadísticas**: el directorio de productores y las cifras brutas fechadas por versión que hay detrás de las otras
  subpestañas, además de **Añadir las series al corpus** (véase más abajo).

**Las estadísticas en la búsqueda normal.** Una cifra que nadie puede encontrar no está realmente en su corpus,
así que cada **serie** (un indicador para un país, a lo largo de todos los años disponibles) puede también
materializarse como un **Artículo** normal. Entonces sigue los caminos habituales: la búsqueda encuentra
«esperanza de vida Francia», sus palabras llegan a las tendencias y a las Pistas, y aparece en el Flujo
como cualquier otra cosa, sin ningún cuadro de búsqueda especial que recordar. Conviene saber cuatro cosas:

- Es **un Artículo por indicador y por país**, no uno por revisión. Una cifra de 1991
  corregida actualiza el Artículo existente en lugar de añadir una casi copia, así que volver a ejecutar el
  trabajo no cuesta nada ni añade nada.
- Los Artículos están **etiquetados como lo que son**: la fuente dice «Estadísticas oficiales
  (Banco Mundial)» y la clase de procedencia es `statistics`, de modo que puede incluirlos o excluirlos
  de cualquier vista, y las comprobaciones de coordinación que buscan muchos medios repitiéndose entre
  sí no pueden confundir miles de filas con la misma forma con un acuerdo.
- El cuerpo dice deliberadamente **solo el tema y las cifras**, con una **laguna publicada
  mostrada como laguna**. Repetir el nombre del productor y el código de serie de la máquina en cada
  uno de los ~9800 Artículos situaba «World Bank» en lo más alto de la clasificación de palabras clave
  de todo el corpus (el andamiaje por encima de lo que realmente trata su corpus), así que no se hace.
- Para encontrarlos **por productor** en lugar de por tema, filtre por la fuente o por la
  etiqueta `statistics`; para buscar uno **por código de serie**, use la subpestaña Estadísticas, que
  responde con exactitud en lugar de por coincidencia de texto.

Materializarlos es un trabajo en segundo plano que se inicia desde **Gobiernos → Estadísticas**; se puede
reanudar y cancelar, y no retrasa la recopilación.

### 3.8 Pruebas y custodia

*(Se accede desde **Ajustes → Avanzado → Seguridad**; «Cadena de custodia» es el título del panel; salió
de la barra lateral en la reorganización centrada en el contenido.)*

**Para qué sirve:** demostrar, ante un tercero escéptico y sin conexión, que su corpus
contenía *este* elemento, con *este* contenido, en *este* momento, y que el registro no ha
cambiado desde entonces. **No** es un sistema para denunciantes ni de tipo SecureDrop; aquí una «fuente» es un
medio de comunicación, no una persona confidencial.

El panel tiene tres partes:

- **Ajustes y estado (Settings & status).** Interruptores para **Firmas poscuánticas** (añaden una firma ML-DSA /
  FIPS-204 junto a Ed25519), **Anclaje con OpenTimestamps** (anclaje en
  Bitcoin como prueba independiente de la fecha), **Registro automático al ingerir** (añade una entrada
  firmada en cada ingesta correcta) y una etiqueta de **Actor predeterminado**. Algo fundamental: el
  estado muestra siempre el estado **efectivo**, no solo su deseo: si activa PQC
  u OpenTimestamps pero la biblioteca necesaria no está instalada, indica *«solicitado,
  biblioteca no instalada»* y se queda solo en Ed25519 / local: **nunca muestra una luz verde
  que no pueda respaldar.** También se muestra la protección de la clave (`aes256gcm-scrypt` cuando se dispone de
  una frase de contraseña, procedente de `OO_KEY_PASSPHRASE` o de la frase de contraseña de la base de datos; `plaintext-0600` en caso contrario; y `pkcs8-pbkdf2`
  o `plaintext-0600` con una frase de contraseña disponible, para una clave anterior a 0.6 que aún no se ha podido volver a cifrar,
  lo que indica lo que realmente contiene su archivo).
- **Ver y verificar la cadena (View & verify chain).** Introduzca el identificador de un elemento (p. ej. `article:42`) para **Ver cadena**
  (secuencia, acción, actor, hora, algoritmo de firma), **Verificar** (vuelve a comprobar los enlaces
  de la cadena, los hashes, las firmas y las marcas de tiempo) o **Exportar paquete** (un
  archivo verificable sin conexión).
- **Anclar raíz de Merkle (Anchor Merkle root).** Pegue una raíz de Merkle para anclarla mediante el proveedor configurado.

> **Advertencia de privacidad que se muestra en la aplicación:** anclar en una cadena de bloques pública publica un
> hash de forma permanente y revela su IP y sus horarios a los operadores de los servidores de calendario. Es preferible
> lo local + OpenTimestamps a monederos en cadena con fondos; enrute a través de Tor (`HTTPS_PROXY`)
> si necesita anonimato; o quédese solo en local (la opción por defecto no filtra nada).

**OpenTimestamps y el modo avión.** En el modo OpenTimestamps, a una entrada de ingesta cuyo
envío rechazó el interruptor general de red (un Stop durante la recopilación) no se le da una
prueba solo local en su lugar, porque esa prueba sería permanente: la entrada queda pendiente,
y se escribe más tarde, marcada como tardía, con su anclaje. La cola de pendientes no tiene límite de tamaño, y
al final de cada pasada de recopilación se escriben como mucho 200 de ellas, cada entrada con hasta tres
envíos a servidores de calendario realizados mientras el registro de custodia está bloqueado para escritura. Así, un gran retraso acumulado
ralentiza durante un tiempo el final de las pasadas de recopilación una vez que vuelve a estar en línea.
Mientras el interruptor siga activado, la escritura de las entradas pendientes («Registrarlas, marcadas como tardías», o
`POST /api/custody/reconcile`) se detiene en el primer rechazo e indica que lo rechazó el interruptor general;
las entradas siguen pendientes. Una simple comprobación de huecos sigue respondiendo, y su bloque `drained`
informa de `refused_offline`.

Verifique un paquete en cualquier lugar, sin esta aplicación:

```bash
python scripts/verify_custody.py custody_bundle.json [--pin]
python scripts/verify_evidence.py bundle.json [signer_pubkey]
```

El diseño completo, y exactamente lo que cada mecanismo demuestra y lo que **no** demuestra, está
en [`docs/USER_MANUAL.md`](USER_MANUAL.md). *(Una revisión prevista para que
esta pestaña sea a prueba de errores y en gran parte automática se recoge en
[`docs/ROADMAP.md`](archive/roadmaps/DESIGN_MEMORY_pre-0.2.md).)*

### 3.8a Integridad de las fuentes

*(El panel de integridad de fuentes se trasladó a **Ajustes → Avanzado → Seguridad → «Abrir el panel de integridad
de fuentes»**; la coordinación ahora también se muestra automáticamente: como Pistas en Inicio, en la vista
**Relacionados** de la ventana de análisis y como insignias en línea «N copias = una voz» en las listas de artículos
y en el lector.)*

**Para qué sirve:** ver la *estructura* que hay detrás de sus fuentes y decidir, usted mismo,
qué señal cuenta. Deliberadamente **no hay puntuación de confianza**: una sola cifra
incorporaría sesgos y silenciaría a las fuentes pequeñas, extranjeras, nuevas o disidentes. Guía completa:
[`docs/USER_MANUAL.md`](USER_MANUAL.md).

- **Antiamplificación (se propone → usted decide):** *Buscar coordinación* encuentra
  avalanchas de casi duplicados publicados de forma sincronizada en muchas fuentes, con sus pruebas
  (texto compartido, sincronía, servidor). Por defecto solo se **anotan**: nunca se agrupan
  en silencio. **Aplicar agrupación** cuenta una red como **una sola voz** (en cualquier recuento que
  mida el consenso); sigue marcada, y **Expandir (revertir)** restaura exactamente la vista original en igualdad
  de condiciones. Nunca se agrupa nada sin su intervención. Las Pistas de cámara de eco en Inicio
  ofrecen la misma acción.
- **Perfil de la fuente:** un panel de dimensiones medidas (coordinación, novedad
  (origina o se hace eco), capacidad de producción, datos de transparencia, historial), cada una con
  su método y su advertencia, y **ninguna puntuación compuesta**.
- **Anotaciones compartidas (red de confianza):** redacte hechos descriptivos y discutibles sobre
  las fuentes (propiedad, orientación, coordinación, rectificaciones); **expórtelos** como un paquete
  **firmado**; **importe** los paquetes en los que decida confiar. *¿Quién dijo qué?* muestra
  todas las atribuciones de una fuente y pone de relieve las **discrepancias**, sin promediarlas nunca en una cifra.
  Consulte [`docs/USER_MANUAL.md`](USER_MANUAL.md).

### 3.9 Ajustes

**Para qué sirve:** preferencias, las superficies de adquisición y el mantenimiento, organizados
en **nueve** secciones mediante una subnavegación: **Gráficos · General · Tarjetas · IA · Wikipedia ·
OpenStreetMap · Agenda · Datos y copia de seguridad · Avanzado**.
Abra Ajustes desde el **botón situado al pie de la barra lateral**; la paleta de comandos también
lleva directamente aquí. Todo se guarda localmente; sin telemetría.

El uso cotidiano no necesita nada de **Avanzado**: la mecánica de la recopilación, la gestión de fuentes, la
depuración de palabras clave, el directorio de productores de estadísticas, el catálogo de feeds de calendario, el
puesto de diagnóstico, **Seguridad** y **Desinstalar y borrar** están todos allí, en **secciones plegadas que solo
cargan sus datos cuando usted abre una** (el catálogo de fuentes por sí solo puede contener decenas de miles
de filas). Seguridad era antes una subpestaña propia; ahora es la penúltima sección de Avanzado,
con las dos acciones irreversibles —**Borrado de emergencia** y **Desinstalar la aplicación**— separadas
en una sección propia (**Desinstalar y borrar**), para que ninguna de las dos pueda alcanzarse por error
mientras lee sobre el cifrado. No se perdió nada en ninguno de los dos traslados: cada control
que estaba en la subpestaña Seguridad sigue ahí, bajo los mismos encabezados. **Recopilar** y **Fuentes** se
describen más arriba ([3.2](#32-recopilar-en-ajustes--avanzado--recopilación),
[3.3](#33-fuentes-en-ajustes--avanzado--fuentes)) y se accede a ellos a través de Avanzado;
**Wikipedia** ([3.7](#37-wikipedia-en-ajustes--wikipedia)) conserva su propia sección.
Las **cifras** oficiales no están aquí en absoluto: son datos, así que viven en
**Gobiernos → Estadísticas**.

- **Gráficos (Apariencia):** temas, color de acento, densidad, **tipografía**
  y barra lateral expandida/contraída. (No hay control deslizante de tamaño de texto: solo escalaba el
  elemento raíz, del que casi nada en la hoja de estilos heredaba, así que no hacía nada.
  Use el zoom de su propio navegador: lo escala todo, incluidas las partes que un control
  limitado a la raíz nunca podía alcanzar.) Esta sección también contiene la galería de **Interfaces alternativas**
  (marcada como *Experimental*): ocho aspectos opcionales —**Aurora, Atlas, Command, Field,
  Focus, Terminal, Canvas, Editorial**— sobre los mismos datos y con las mismas garantías de
  honestidad; al elegir uno, la página se recarga para aplicarlo. (El antiguo panel flotante "Personalizar"
  es ahora esta sección de pleno derecho.)
- **Tarjetas (Pistas en Inicio):** todos los productores de Pistas que la aplicación puede ejecutar, agrupados por su familia
  (*En aumento · Sobrecontado · Infracontado · Merece investigación · Revisar el encuadre · Seguir observando ·
  Contexto · Integridad de datos*). Desactive cualquiera y dejará de aparecer; eso no cambia nada
  de los artículos en sí, solo qué avisos llegan a su Inicio. Cuando una Pista tiene
  umbrales, ahora son visibles y ajustables, cada uno con un **rango seguro** declarado, una
  nota de una línea sobre lo que produce moverlo y un botón **Restablecer**. Siempre puede hacer una Pista
  *más estricta*; los límites inferiores existen para que una Pista nunca pueda afirmar más de lo que sus pruebas
  respaldan: la comprobación de inundación, por ejemplo, no bajará del umbral p<0.05,
  porque por debajo de él la prueba ya no puede distinguir un aumento real de una variación ordinaria. Todo
  valor fuera de un rango se corrige **y se informa**, nunca se ajusta en silencio.
- **Preferencias (General):** **Tema** (Sistema/Oscuro/Claro), **idioma** y **Resultados de
  búsqueda por defecto**.
- **Filtrado de palabras clave (Avanzado → Palabras clave):** las palabras funcionales "tontas" (the, you, not, …) se eliminan mediante una
  lista de palabras vacías multilingüe integrada. Ajústela: fije la **Longitud mínima de palabra clave**, marque **Descartar
  términos puramente numéricos**, active o desactive la lista integrada de palabras vacías y mantenga una lista de **Palabras clave
  excluidas** (una por línea o separadas por comas). Excluir oculta un término
  en todas partes, pero es reversible: las menciones guardadas se conservan. (También puede hacer clic en ✕
  junto a cualquier palabra clave en Perspectivas.)
- **Bases de referencia sin conexión de Wikipedia:** elija una **edición lingüística** de una **lista plana**
  (primero los idiomas de su interfaz, después las ediciones más grandes), donde cada opción empieza por el
  **nombre nativo** (autónimo): las ediciones se basan en el idioma, no en el país, así que no
  hay agrupación por continentes. Cada edición que admite volcado muestra un **tamaño aproximado
  en línea** (`~X GB`, de una tabla fechada incluida en la aplicación, sin ninguna llamada de red adicional) para que pueda juzgar
  antes de descargar; el tamaño exacto se lee cuando comienza la descarga. **Descargar** se puede
  reanudar (pausa/reanudación + una tabla de progreso). Estos volcados sin conexión son pesados y
  opcionales, y sirven solo para leer y buscar sin conexión; el seguimiento de cambios en vivo (la
  pestaña Wikipedia) no los necesita.
- **IA (LLM local):** un recuadro **Configurar la IA local** en la parte superior expone en un solo lugar todo el
  plan que queda por hacer —qué backend usará este equipo (vLLM cuando una GPU NVIDIA
  dedicada puede servirlo, Ollama en caso contrario), qué falta por instalar y los
  tamaños de descarga— y lo ejecuta con **un solo botón** tras **un solo** consentimiento. Se oculta
  cuando ya no queda nada por hacer; los controles por componente que hay debajo no
  cambian, así que puede seguir haciendo cada paso usted mismo. Debajo: el backend activo
  y **por qué** se eligió, los modelos instalados y un catálogo seleccionado y fechado, **descargar** un
  modelo (una tarea de descarga **en cola**: de una en una, cancelable, con el progreso en bytes
  en vivo; los bytes pasan por la internet abierta mediante el proceso de Ollama, **no** por Tor, como se indica en
  la solicitud de consentimiento), **eliminar** uno y fijar el **modelo activo**.
  La **idoneidad del hardware** se indica una sola vez, aquí, con lo que significa para usted: la
  inferencia local solo se rechaza por defecto por debajo de un mínimo (menos de 4 núcleos de CPU, o menos
  de 6 GB de RAM, sin acelerador); funcionar sin GPU dedicada, con una tarjeta de poca
  VRAM o en un Mac pequeño de memoria unificada es una **advertencia sobre lo que cabe
  esperar**, no un rechazo. **Nunca es un bloqueo**: una casilla vuelve a activar la IA, y
  la información sigue visible en ambos casos. **Iniciar** la IA local se hace con la **píldora de IA** (AI pill)
  de la barra superior, desde cualquier pantalla.
  Un editor de **"Comportamiento y prompts"** expone los cuatro prompts de sistema editables
  (resumen / traducción / síntesis / extracción de palabras clave) y el tiempo durante el que el modelo se mantiene cargado.
  Esos cuatro prompts **se incluyen en los doce idiomas de la interfaz**, de modo que un lector en francés o
  en japonés obtiene un resumen escrito en su idioma y no un trabajo en inglés;
  el editor muestra el texto integrado para **su** idioma, y el prompt exacto utilizado
  queda registrado con cada resultado. Su propio prompt, si escribe uno, se usa **exactamente
  como usted lo escribió**, en el idioma en que lo haya escrito. Una lista de **Extractores personalizados**
  le permite definir prompts gestionados que escriben metadatos derivados por IA (etiquetados como
  *poco fiables*, nunca en el índice de palabras clave de confianza).
  Cuando Ollama no está presente, aparece un **instalador integrado en la aplicación** (Linux/Debian): descarga
  el script de instalación oficial, lo verifica contra el resumen sha256 certificado por GitHub, muestra
  un paso de elevación de privilegios visible y lo ejecuta, negándose ante cualquier discrepancia del resumen. macOS/Windows
  reciben una indicación honesta hacia ollama.com/download.
- **Estadísticas: el directorio de productores (Avanzado → Estadísticas oficiales):** un
  directorio descriptivo de productores de estadísticas gubernamentales e internacionales. Las
  **cifras** en sí son datos, así que viven en **Gobiernos → Estadísticas**,
  no en Ajustes. Cada productor lleva la **misma advertencia descriptiva de fuente con
  postura** —una cifra oficial declara la agencia que la produce y su postura—, **nunca una
  etiqueta de "controvertido", un veredicto ni una puntuación por fuente**. Puede **añadirlos a sus fuentes**: un productor cuya
  sección de noticias/prensa se conoce se activa y se recopila desde allí, mientras que uno cuya
  dirección aún no se ha investigado se añade desactivado, en lugar de rastrear su portal de
  datos, y **obtener cifras oficiales** de puntos de acceso documentados para máquinas
  (World Bank API / Eurostat SDMX), guardadas con su procedencia completa y una **edición** (vintage) de
  pleno derecho (volver a obtenerlas crea una fila nueva, nunca sobrescribe). Los productores se muestran **uno al
  lado de otro, nunca promediados**, y una vista **Triangular** (Triangulate) señala las celdas que mezclan unidades,
  ajustes estacionales o años base incomparables. **Comprobar anomalías de revisión** señala, de forma puramente
  retrospectiva, una cifra guardada cuya edición más reciente movió un valor pasado de forma inusualmente lejana
  respecto al propio historial de revisiones de esa serie (sin puntuación). La obtención sale por el transporte que
  usted haya configurado y se rechaza en modo avión.
- **OpenStreetMap:** elija una región del mapa (con una estimación fechada en `~GB`) y descárguela
  como una tarea del administrador de tareas reanudable y que se puede pausar (sujeta a la única ventana de consentimiento de red).
- **Boletines:** importe boletines como artículos, **anonimizados en la ingesta** (el
  destinatario nunca se guarda, las repeticiones del destinatario se ocultan, los tokens de rastreo se eliminan
  y los envoltorios de rastreo del lado del servidor se señalan; **nunca se descarga nada**, así que importar
  nunca puede revelar que usted abrió un mensaje o hizo clic). Tres vías:
  - **Elegir archivos .eml** (Choose .eml files): una pequeña carga de varios archivos.
  - **Importar una carpeta entera**: indique una carpeta de este equipo; cada `.eml` que contenga
    se importa como una **tarea en segundo plano que se puede pausar y reanudar** (visible en el administrador de tareas) que
    escala a archivos de más de 20 GB, omitiendo los mensajes ya importados.
  - **Extraer de un buzón (IMAP/POP3)**: extrae en vivo de un buzón, con una
    advertencia visible en el momento de usarlo (TLS hacia el proveedor, su IP es visible, **no** pasa por
    Tor, las credenciales no se guardan). Con TLS, el certificado del servidor debe coincidir con su nombre
    y proceder de una autoridad en la que su equipo confíe; de lo contrario la extracción se rechaza antes de
    enviar su contraseña, y el mensaje explica por qué. A través de la API, una extracción con
    `use_ssl` en false (normalmente en el puerto 143/110) primero pasa a STARTTLS con la
    misma comprobación, y se rechaza si el servidor no lo ofrece: su contraseña nunca se
    envía sin cifrar.
  - **¿A qué editor pertenece cada boletín?**: los boletines importados están actualmente
    todos en una única fuente común. `GET /api/newsletters/publisher-preview` muestra cómo QUEDARÍA una
    clasificación por editor para los boletines que ya tiene: cada dominio
    remitente, cuántos mensajes llegaron desde él y a qué fuente existente corresponde (un
    eTLD+1 real de una Public Suffix List incluida en la aplicación, de modo que `email.bbc.com` corresponde a `bbc.com`, con
    las plataformas de boletines tratadas al revés, para que dos publicaciones de Substack nunca
    se fundan en un único "Substack"). Es **solo una vista previa**: no se asocia ni se mueve nada y,
    cuando las pruebas no permiten decidir, lo dice en lugar de adivinar.
  - **Eliminar newsletters importadas**: borra todos los artículos de boletines importados (.eml +
    buzón) del corpus activo, para sustituir un conjunto defectuoso por una reimportación limpia
    (la restauración es aditiva, así que dejar los boletines fuera de una copia de seguridad nunca los elimina; esto
    sí).
- **Datos y copia de seguridad: la Exportación / Importación unificada:** un solo lugar para hacer copia de seguridad de todo, con
  **cualquier tamaño de base de datos**. **Exportar / Copia…** abre un diálogo: elija una **carpeta de destino
  o una unidad**, marque qué incluir (corpus, boletines importados, modelos LLM locales,
  mapas sin conexión, volcados de Wikipedia) e indique una **frase de contraseña**: el corpus cifrado se transmite
  a esa carpeta como **volúmenes autenticados de forma independiente más paridad Reed-Solomon** (de modo que
  un volumen perdido o dañado, incluso uno del corpus, se puede reconstruir), y los grandes datos públicos
  (modelos / mapas / volcados) se copian **tal cual**. **No hay límite de tamaño** y el archivo nunca
  se mantiene entero en la RAM. La frase de contraseña **no tiene recuperación**: perderla significa que la
  copia de seguridad del corpus no se puede abrir.
  - **Cada exportación crea su propia carpeta fechada.** El destino que elige es la carpeta PADRE:
    dentro de ella, cada exportación crea `YYYYMMDDHHMM_OpenOmniscience_Backup`, con la fecha y la hora locales
    en que empezó la exportación, para que las carpetas se ordenen en el orden en que las hizo. Una segunda
    exportación en el mismo minuto recibe `_2`, `_3`, etc. En una carpeta existente **nunca se
    escribe**, así que una copia anterior en la misma unidad no puede resultar dañada por una posterior.
  - **Cada exportación es una copia de seguridad completa y nueva.** No se reutiliza nada de una anterior, así que una
    exportación cuesta el tiempo y el espacio de todo lo que seleccionó, y a cambio cada
    byte de esa carpeta lo escribió esa única pasada.
  - **Verificar tras escribir** (Verify after writing) (activado por defecto). Cuando llega el último volumen, cada volumen se
    vuelve a leer del destino y su suma de verificación se compara con la registrada cuando se
    escribió. Lee cada byte una segunda vez, lo que aproximadamente duplica lo que tarda una
    exportación en una unidad lenta; es lo único que detecta una unidad que aceptó
    la escritura y guardó otra cosa. El panel de finalización indica entonces **"Verificado"** (Verified)
    y, si no lo indica, dice cuál de los cuatro motivos se aplica: la verificación estaba
    desactivada, se canceló, el conjunto no se pudo volver a leer, o **falló**, y nombra los
    volúmenes.
  - **`BACKUP_SUMMARY.md`** se escribe junto a `volumes.json` al final de cada exportación:
    los mismos datos que muestra el panel de finalización: volúmenes, bytes, filas por tabla con
    los artículos primero, archivos copiados por categoría, tiempo transcurrido, destino, estado del cifrado,
    versiones del esquema y de la aplicación, el resultado de la verificación y las líneas de atribución que se aplican a
    lo que contiene la copia. Está ahí para que la carpeta se explique por sí misma en una unidad extraíble
    años después, cuando el panel que decía todo esto haya desaparecido hace tiempo. Es una descripción,
    no una firma: `volumes.json` lleva las sumas de verificación por volumen que prueban los bytes.
    **Es también el único archivo de esa carpeta que no está cifrado**: el corpus es
    ilegible sin su frase de contraseña, y este resumen es texto plano a su lado, que dice
    cuántos artículos, fuentes y documentos seguidos contiene el corpus. Ese es el compromiso
    que asume el archivo, se declara en el propio archivo, y puede borrarlo si que la carpeta
    se explique por sí misma le importa menos que no decir nada a quien encuentre la unidad.
  - **Las exportaciones nunca se programan.** No hay exportación automática ni periódica, y no hay ninguna
    prevista: una exportación es un **acto deliberado**, porque escribe su corpus en un lugar
    que usted eligió, en un momento que usted eligió.
  **Importar…** apunta a una carpeta, encuentra lo que se puede importar en ella (una copia de seguridad que restaurar,
  datos grandes o boletines) y lo restaura. **La restauración es solo aditiva**:
  **complementa** su corpus y **nunca lo sustituye**; nada de lo que ya tiene se
  sobrescribe, los duplicados se detectan bit a bit, y ante un valor en conflicto **se conserva el
  suyo local y se informan ambos**, nunca se promedian.
  - **Informes de importación.** Tanto una restauración por fusión como una importación de boletines desde una carpeta
    escriben automáticamente un **informe persistente** en el disco al terminar (en la unidad
    ARTÍCULOS, nunca una suma de filas entre tablas que parezca millones de artículos cuando en
    realidad son filas de muchas tablas): cuántos artículos entraron, cuántos se
    descartaron por no ser artículos (vea **Filtrado de no artículos**, más abajo) y el
    "trabajo inducido" que deja pendiente (p. ej., cuántas fuentes recién importadas siguen
    esperando cualificación, vea [§3.3](#33-fuentes-en-ajustes--avanzado--fuentes)). El propio
    informe viaja en su **próxima** copia de seguridad cifrada, así que acompaña al corpus. Se puede
    descargar mediante `GET /api/backup/import-reports` (lista) y
    `GET /api/backup/import-reports/{filename}` (como JSON, o `?format=md` para una
    versión legible en Markdown); todavía no hay una pantalla específica en la aplicación para ello,
    así que use esos puntos de acceso (o el navegador) para leer uno.
  - **Filtrado de no artículos.** Cada restauración por fusión e importación de boletines desde una carpeta
    revisa automáticamente los artículos que acaba de traer y **pone en cuarentena** —conservados,
    nunca borrados, y de forma reversible— los que cumplan los mismos criterios de validez de extracción
    que usa la prueba de cualificación de fuentes (una página de menú de navegación, una lista de enlaces, un
    raspado fallido). Un artículo en cuarentena queda excluido de la búsqueda y de los análisis, pero
    permanece en la base de datos y viaja en sus copias de seguridad; el recuento figura en el informe de importación.
  > **Vías heredadas / de migración (conservadas para copias antiguas).** Un panel aparte restaura un
  > archivo **antiguo de un solo fichero `oo-backup-2`** con la misma **vista previa** de fusión aditiva
  > (nuevo / duplicado / conflicto) antes de **Aplicar** (Apply) (sobre una copia preparada y verificada, con intercambio atómico
  > y una instantánea `pre-restore-*.db` guardada junto a la base de datos). Una instantánea sin procesar **Descargar copia de seguridad (.db)**
  > (API de copia de seguridad en línea de SQLite) está guardada en *"Herramienta de copia antigua…"* (Older backup tool…) para uso
  > manual. **La restauración destructiva que "sustituía su corpus" se eliminó por completo**: ningún flujo
  > puede sobrescribir sus datos, y restaurar una copia de seguridad **cifrada** nunca descifra en silencio
  > su corpus.
- **Mantenimiento (panel de Diagnóstico):** **Limpiar palabras clave (reindexar y luego podar)** y
  **Reindexar todo el corpus** ejecutan una **tarea en segundo plano que se puede pausar, con un cursor persistente**
  (sobrevive al cierre de la pestaña o a un reinicio y continúa donde se detuvo). Ejecute la limpieza después de
  una actualización del motor de palabras clave para aplicar las listas de palabras vacías y familias más recientes a los artículos existentes.
  **Unificar formas de palabras clave (estudios → estudio)**, a su lado, hace la única parte de esa limpieza
  que necesita la lematización sin volver a leer ningún artículo: las palabras clave indexadas antes de que se añadiera
  la lematización mantienen "studies" separado del "study" que usan los artículos nuevos, y la unificación clasifica esas
  menciones antiguas bajo la forma base exactamente como lo haría una reindexación. Después fija el idioma de cada
  palabra clave a partir de los idiomas de sus menciones. Las frases, los nombres y las palabras clave que usan sus
  familias o grupos nunca se unifican. Es una tarea que se puede pausar en el administrador de tareas, e
  **Informe de unificación (.json)** muestra lo que contó la última unificación completada y sus unificaciones más grandes.
  Una unificación no se puede deshacer; una poda posterior elimina las palabras clave que dejó vacías.
  **Reindexar la búsqueda (árabe, chino, japonés)** indexa los artículos escritos antes de esta
  versión del mismo modo que los nuevos, para que los artículos antiguos en árabe, chino y japonés también se encuentren por
  palabra. Lee cada artículo una vez y solo reindexa aquellos cuya entrada de búsqueda
  cambiaría; es una tarea que se puede pausar en el administrador de tareas, e **Informe de reindexación de la búsqueda (.json)**
  muestra cuántos comprobó y reindexó, por escritura. Vuelva a ejecutarla después de actualizar jieba o
  el diccionario japonés: los artículos que el nuevo diccionario divide de otra forma se
  reindexan, y el informe nombra las versiones con las que se ejecutó.
- **Instrumentación temporal de prueba de campo (ciclo de prueba en vivo 0.0.8).** Durante este
  ciclo, la aplicación ejercita automáticamente cada superficie de red una vez *dentro de sus
  propias pasadas de recopilación* (verificación de feeds de calendario en lotes educados, las importaciones de feeds
  de mercados e índices, un seguimiento legal, un seguimiento de wiki) y registra cada
  resultado literalmente en `data/field_test.jsonl`, incluido en el paquete de depuración.
  **Propósito:** mejora continua de las listas de fuentes, feeds y calendarios
  de la instalación por defecto a partir de veredictos reales: el responsable del proyecto reinstala,
  recorre la aplicación y comparte el paquete con el desarrollo. **Está desactivada por
  defecto desde la 0.1**: actívela para un ciclo de prueba en vivo con `OO_FIELD_TEST=1`.
  La aplicación nunca transmite nada: los registros permanecen en este equipo hasta que *usted*
  los descarga y los comparte. El arranque sigue siendo totalmente sin conexión en cualquier caso.
- **Registro de diagnóstico:** una síntesis compartible de cómo ve la aplicación su corpus, generada
  solo cuando usted hace clic, con solo recuentos y estructuras (nunca puntuaciones), y solo usted decide quién
  recibe el archivo. El panel tiene UN botón **Diagnóstico**, su casilla **Exhaustivo** y dos pequeños enlaces, **Todas las palabras clave** y **Guardar de nuevo el último Diagnóstico**; cada uno de los demás registros de esta tabla es un **miembro del archivo de Diagnóstico**, no un botón
  propio (varios contienen más de un informe: `selftests.json` lleva las trece autopruebas de mecanismos
  con un veredicto cada una, `storage.json` las lecturas de huella, composición, volumen y persistencia,
  `contention.json` la compuerta de escritura y la atribución de bloqueos, `ai-runs.json` los resultados de las últimas tareas de IA,
  `run-journal.json` el resumen y sus líneas sin procesar; el `merged.replaces` de un miembro fusionado en el manifiesto
  nombra los archivos que sustituyó, de modo que un archivo antiguo se pueda leer frente a uno nuevo):

  | Exportación o miembro del archivo | Qué es |
  |---|---|
  | **Diagnóstico** (y su casilla **Exhaustivo**) | UN archivo con todo lo que esta instalación puede decir de sí misma, construido en segundo plano (la aplicación sigue siendo utilizable) y luego entregado: **un archivo** cuando cabe en 4 MB; si no, **archivos numerados de 4 MB como máximo cada uno** (`…-part-03-of-12.zip`) más un pequeño `…-manifest.zip` que lista cada archivo con su tamaño y su SHA-256. Cada archivo se abre por sí solo en cualquier herramienta de descompresión. **Rápido** (Quick) (el modo por defecto) escribe primero los registros, con la recopilación aún en marcha, y luego tantos análisis de su corpus como quepan en diez minutos, empezando por los más cortos; un análisis que no cupo queda **nombrado en el archivo** como no ejecutado, con el motivo, nunca descartado en silencio. **Exhaustivo** (la casilla junto al botón, que vuelve a estar vacía cada vez que se abre el panel) ejecuta todos los análisis, cada uno hasta cinco minutos, con la recopilación en pausa mientras se ejecutan (de 27 a 47 minutos medidos en un corpus grande). El `manifest.json` del archivo dice qué modo se ejecutó, el equipo en que se ejecutó (compilación, versiones de bibliotecas, nivel de memoria, los nombres de los interruptores `OO_*` que estaban definidos, nunca sus valores) y, para cada miembro, su área (memoria, almacenamiento, base de datos, sesiones, ejecuciones, palabras clave, interfaz, fuentes, IA, autopruebas, compilación). Vea "Guardar los archivos numerados" más abajo |
  | **Guardar de nuevo el último Diagnóstico** (un enlace bajo el botón, que aparece cuando existe una compilación) | el mismo archivo terminado, guardado de nuevo (escriba antes un número de parte en "Empezar en la parte número" y empezará ahí, para que pueda reenviar solo las que no se pudieron subir). Solo reutiliza un archivo que usted ya haya construido; nunca inicia una compilación nueva. Si un registro individual es demasiado grande para caber en un archivo, se corta en los límites entre registros en piezas numeradas, y el manifiesto dice cuáles (un corte por bytes, `.part0001of0003`, es el último recurso y se nombra en `volumes.json`) |
  | **Todas las palabras clave** (un enlace) | la lista por palabra clave: todas las palabras clave del corpus (no solo las principales por idioma), sin límite de tamaño total, en archivos numerados de 4 MB como máximo cada uno. Los primeros archivos contienen las 5000 principales de cada idioma, así que, si no puede enviarlos todos, envíelos en orden numérico. Se escribe en el disco por lotes, de modo que la memoria de la aplicación se mantiene estable sea cual sea el tamaño del corpus; un corpus grande genera muchos archivos (la página dice cuántos antes de que guarde ninguno) y tarda minutos, y la exportación se detiene con un mensaje claro (y elimina sus archivos parciales, cuando la unidad lo permite) si falta memoria o disco. Todo lo demás que contenía el registro de palabras clave está, cuando la compilación de Diagnóstico lo ejecutó, en el archivo de Diagnóstico como `keyword-log-digest.json`: las familias (las 1000 principales impresas, todas las familias contadas en el resumen del archivo), sus correcciones, los supergrupos, la concentración por fuente, los candidatos a palabra vacía y a anillo y los recuentos del corpus, tal como los contenía el registro de palabras clave, más las 100 palabras clave principales por menciones con el número de las omitidas. Una compilación Rápida en un corpus grande puede nombrar el resumen como no ejecutado porque no cupo en los diez minutos (marque **Exhaustivo**), un equipo sin memoria suficiente lo nombra como rechazado, y un resumen que supera su propio límite de cinco minutos se nombra como omitido (Exhaustivo mantiene ese límite); en esos casos, este enlace es el camino hacia las palabras clave, y su propio resumen se construye sobre todas las palabras clave, no solo sobre las 5000 primeras de cada idioma. En un equipo con poca memoria que aun así ejecuta el resumen, las familias se agrupan solo sobre las primeras palabras clave de cada idioma, y el archivo lo indica y remite a este enlace. No hay botón para guardar de nuevo el último conjunto de archivos de palabras clave: después de recargar la página, pulse el enlace para construir un conjunto nuevo |
  | **Autoprueba de palabras clave (.json)** | una comprobación con casos de referencia de que la preselección de palabras clave sigue funcionando (p. ej., *WHO* ≠ *who*) |
  | **Informe del motor de palabras clave (.json)** | composición, precisión de entidades, cobertura de traducciones/etiquetas, estado por idioma |
  | **Curva de crecimiento de palabras clave / (.json)** | palabras clave distintas acumuladas frente a palabras añadidas (¿se está saturando el vocabulario?) |
  | **Diagnóstico de tarjetas de inicio (.json)** | ¿cada Pista de Inicio abre su corpus exacto o una alternativa aproximada? |
  | **Registro de extracción de fechas (.json)** | cobertura del etiquetado de fechas |
  | **Ocupación de meses (.json)** (Month occupancy (.json)) | de los nombres de mes que descarta el filtro de palabras clave, cuántos formaban realmente parte de una fecha: las pruebas para decidir si ese filtro debería tener en cuenta las fechas |
  | **Registro de red (.json)** | resultados de las obtenciones con veredictos según el transporte |
  | **Informe de rendimiento / Prueba de escalado / Banco de la acumulación (.json)** | tiempos y comprobaciones de escalado |
  | **Paquete de depuración (.json)** | un paquete de soporte consolidado |

  **Guardar los archivos numerados.** La página dice cuántos archivos están listos ("13 archivos de 4 MB como máximo están listos (manifiesto: 1, partes numeradas: 12)")
  y los entrega a su navegador **de cinco en cinco por clic**, el manifiesto primero, porque cinco es lo que admite un mensaje de subida y un clic es lo que hace que un
  navegador acepte una descarga. Puede que su navegador le pregunte una vez si permite varias descargas: permítalas. Tras los cinco primeros, el botón dice "Guardar los 5 siguientes";
  "Guardar todos los demás" se ofrece siempre que quedan más de cinco archivos, para un solo clic que lo hace todo. Un paquete de cinco archivos o menos, que es el caso habitual, lo
  entrega la propia página a su navegador cuando termina la compilación (el clic que la inició ya quedó muy atrás); "Guardar de nuevo el último Diagnóstico" envía otra vez los mismos archivos. La página solo puede *pedir a su navegador* que guarde
  un archivo, así que dice "Se pidió a su navegador que guardara 5 de 13 archivos", nunca que están guardados: mire en su carpeta de descargas (un navegador que rechazó la
  pregunta sobre varias descargas no guarda nada y no se lo dice a la página). Mientras los archivos están en camino, los botones aparecen en gris y un segundo clic no hace
  nada. Cada archivo ocupa como máximo 4 000 000 bytes (el tamaño en el que divide esta aplicación) y se abre por sí solo, así que puede enviar algunos ahora y
  el resto más tarde. Para enviar de nuevo solo algunos archivos, escriba un número de parte en "Empezar en la parte número" y pulse "Guardar desde esta parte": entrega cinco archivos
  a partir de esa parte (el manifiesto no se vuelve a guardar), y un número posterior a la última parte empieza en la última y lo indica. Un número que usted escriba en la misma casilla también indica a
  "Guardar de nuevo el último Diagnóstico" dónde empezar (un número que la propia página escribió allí se ignora, así que "de nuevo" con la casilla sin tocar
  empieza en el manifiesto). Enviar de nuevo una parte no mueve "Guardar los 5 siguientes": continúa desde el archivo más lejano ya entregado al navegador. Escribir un número por delante de los archivos ya guardados se salta los
  intermedios (el recuento de la línea de estado dice cuántos se pidieron); escriba el número de la primera parte que falta para llenar el hueco.
  Un conjunto está completo cuando están presentes todos los nombres desde `…-part-01-of-NN` hasta `…-part-NN-of-NN` y su SHA-256 coincide con el
  manifiesto. Para leer un conjunto con el script de análisis, indíquele la carpeta (o cualquier archivo de ella): `python scripts/analyze_keyword_log.py <folder>`;
  nombra las partes que faltan o que difieren del manifiesto, se salta una parte dañada y lee el resto.

  El mismo panel también ejecuta el **enriquecimiento de fuentes** local (deducir etiquetas temáticas a partir de su
  corpus) y pasadas de **Wikidata** con consentimiento (tipos de fuente, descubrimiento de fuentes nuevas).
- **Seguridad y uso en riesgo (Avanzado → Seguridad):** herramientas para periodistas que trabajan bajo
  presión, cada una etiquetada con su **límite honesto**:
  - **Cifrado en reposo (por defecto para los corpus nuevos).** Las bases de datos nuevas se
    cifran en disco con SQLCipher 4: en cada inicio, la aplicación pide **LA
    frase de contraseña**, un único secreto estable, como un identificador de usuario (`OO_DB_PASSPHRASE` para
    ejecuciones con scripts o sin interfaz). **No hay recuperación ni alternativa de
    descifrado**: perder la frase de contraseña cuesta tiempo de recopilación de nuevo, porque el
    corpus se reconstruye desde la web; no contiene nada personal más allá de lo que se
    extrajo y dedujo de fuentes públicas. Los corpus existentes en texto plano siguen
    funcionando sin cambios; **Ajustes → Avanzado → Seguridad → "Cifrar este corpus…"** convierte
    uno *in situ* (consentimiento explícito, verificación completa antes del intercambio y una
    instantánea en texto plano conservada deliberadamente como vía de escape: bórrela cuando
    haya desbloqueado correctamente). El **doctor** (`GET /api/system/doctor`,
    y el mismo panel) certifica el estado *real* de cada almacén leyendo las
    cabeceras de los archivos (corpus, registro de custodia, claves de firma), nunca por suposición.
    **El límite honesto:** el cifrado en reposo protege un *archivo incautado o
    copiado*. No puede proteger una sesión en ejecución comprometida (la clave reside en
    memoria mientras la aplicación se ejecuta), y es independiente del cifrado de disco completo
    solo si las dos frases de contraseña son distintas. El funcionamiento en texto plano sigue disponible
    como opción explícita (`OO_DB_PLAINTEXT=1`): la aplicación nunca muestra una pantalla de bloqueo
    sobre un archivo en texto plano, porque eso sería seguridad fabricada.
    Las copias de seguridad de un corpus cifrado funcionan sin cambios: los miembros del artefacto son
    portables, el propio envoltorio del artefacto cifrado los protege en reposo,
    y las restauraciones conservan el cifrado de su corpus (verificado mediante pruebas).
  - **Copia de seguridad cifrada**: una instantánea protegida con frase de contraseña (AES-256-GCM + scrypt).
    Una frase de contraseña perdida o errónea significa que el archivo no se puede abrir: no hay recuperación.
    Para recuperar una copia de seguridad cifrada, use la **restauración por fusión aditiva** en
    **Datos y copia de seguridad** (más arriba): muestra una vista previa y luego complementa su corpus sin
    sustituirlo nunca, y nunca descifra en silencio su almacén activo. *(La antigua restauración destructiva
    que sustituía con una copia cifrada se eliminó.)*
  - **Mantenimiento de la base de datos**: *Compactar la base de datos (VACUUM)* reconstruye el archivo de la base
    de datos: recupera el espacio que dejan las eliminaciones (mostrado como “Espacio
    recuperable”, una lectura real de `PRAGMA freelist_count`) y desfragmenta los índices.
    Tarda un tiempo proporcional al tamaño del archivo y pausa las escrituras de la recopilación
    mientras se ejecuta; el resultado informa de los bytes realmente liberados y de la duración. Nunca
    interpreta ni elimina datos. Construye la copia compactada en memoria
    (escribirla en un archivo temporal corrompe un archivo cifrado con el tamaño de página de la aplicación,
    medido), así que primero comprueba que el equipo tiene memoria para ello
    (unas 1,25 veces la parte del archivo que está en uso, además de la memoria libre
    que la aplicación siempre reserva para sí misma) y espacio en la unidad (unas dos veces
    la parte en uso, más el tamaño del registro del archivo), y cuando falta alguna de las dos
    dice cuál, con las cifras, y no empieza. Una cifra que no pudo
    leer no se comprueba, y también lo dice.
  - **Modo de recolección de red**: *Transparente* (por defecto; educado, nombra la herramienta en el
    User-Agent) o *Protegido* (las obtenciones web de la aplicación pasan por un proxy que **usted** ejecuta,
    p. ej. Tor, con un User-Agent genérico). La única excepción de User-Agent son las peticiones de la API
    y de volcados de la aplicación a los servidores de Wikimedia (sus funciones de Wikipedia, Wikidata y volcados):
    la política de API de Wikimedia pide que cada herramienta se identifique, así que en modo protegido esas
    peticiones siguen llevando el User-Agent propio de la herramienta, a través del mismo proxy y solo por
    https. Cualquier otra cosa obtenida de un sitio de Wikimedia (un artículo recopilado como cualquier otra
    página) recibe el genérico. Tres cosas se conectan directamente incluso en modo protegido, como
    indica para cada una el texto emergente de la ventana de consentimiento de red: la extracción del buzón de boletines,
    el anclaje con OpenTimestamps y las descargas de la IA local.
    El modo protegido **no puede garantizar el anonimato**: usted mismo debe ejecutar el proxy y confiar
    en él; se niega a activarse sin una URL de proxy. Los proxies SOCKS como Tor no necesitan
    instalar nada más.
  Las dos acciones **irreversibles** están una sección más abajo, en **Avanzado →
  Desinstalar y borrar**, deliberadamente lejos de todo lo anterior:

  - **Borrado de emergencia**: borra de forma irreversible el corpus, las claves y las cachés de este equipo
    (con doble confirmación). **Límite:** sobrescribir in situ *no* garantiza
    que los datos sean irrecuperables en SSD/flash; para eso, use cifrado de disco completo (LUKS/Qubes/Tails)
    y destruya la clave. También hay una CLI `panic` y un modo de ejecución `--ephemeral`
    (datos solo en RAM, borrados al salir).
  - **Desinstalar la aplicación**: elimina el **entorno virtual** (virtualenv) y los **lanzadores de escritorio** de la aplicación,
    y luego detiene el servidor (confirmación escribiendo). Sus **datos se conservan** (use antes el Borrado de emergencia para
    destruirlos); la carpeta de la aplicación se deja en su sitio para que la borre manualmente. Equivale a
    `./install.sh --uninstall` o al icono de escritorio **“Desinstalar Open Omniscience”** (Uninstall Open Omniscience) que el
    instalador crea junto a los dos lanzadores de la aplicación.

  La gobernanza y las líneas rojas de doble uso que delimitan todo esto están en
  [`GOVERNANCE.md`](GOVERNANCE.md) (también en **Ayuda y documentación**).

### 3.10 Ayuda y documentación

**Para qué sirve:** leer la documentación **dentro de la aplicación**, sin conexión. Una
lista a la izquierda selecciona un documento (este **Manual de usuario** es el predeterminado; los demás
profundizan en temas concretos), que se muestra a la derecha con **búsqueda en la página**. Ábrala
desde el **?** de la barra superior o desde la paleta de comandos ("Abrir el manual de usuario" (Open the User Manual)). El
esquema de la API sin procesar está en `/openapi.json`.

---

## 4. Flujos de trabajo habituales (guía práctica)

**Reunir noticias sobre un tema y buscar en ellas**
1. **Ajustes → Avanzado → Fuentes** → confirme que las fuentes pertinentes están activadas (filtre por país/etiqueta).
2. **Ajustes → Avanzado → Recopilación** → haga clic en **Obtener feed** en cada fuente, o configure el
   **programador (scheduler)** en modo RSS con sus **Etiquetas / palabras clave (Tags/keywords)** y pulse **Iniciar** (o simplemente conéctese
   — la recopilación se ejecuta automáticamente).
3. Busque desde la **omnibarra (omnibar)** → consulta booleana → **Exportar CSV/JSON** si lo necesita.

**Vigilar un tema de forma continua en segundo plano**
1. **Ajustes → Avanzado → Recopilación** → programador en **Modo: Canales RSS**, defina **Idiomas**/**Etiquetas**,
   **Previsualizar objetivos**, fije un **Intervalo**, marque **Iniciar automáticamente al arrancar** y pulse
   **Guardar (Save)**.
2. Si lo desea, active **Evidencia y custodia → Registro automático al ingerir** para que cada captura se
   firme en cuanto llega.

**Obtener una prueba de un artículo que resista ante un tribunal o un editor**
1. Busque el artículo o los artículos desde la omnibarra.
2. **Exportar evidencia firmada** (o **Evidencia y custodia → Exportar paquete** para un elemento).
3. Entregue al destinatario el paquete y `scripts/verify_evidence.py` /
   `verify_custody.py`; este lo verifica sin conexión, sin tener que confiar en usted ni en esta herramienta.
4. Para una prueba independiente de la *fecha y hora*, active **OpenTimestamps** y ancle la raíz de Merkle
   del paquete (tenga en cuenta la advertencia de privacidad).

**Vigilar un artículo de Wikipedia controvertido para detectar manipulaciones**
1. **Ajustes → Wikipedia** → añada la página (edición + título), marque **usar puntuaciones ORES**,
   **Seguir ahora**.
2. Revise los **Cambios marcados**; abra **Diferencias** en todo lo que parezca sospechoso.

**Seguir el precio de una materia prima frente a las noticias**
1. **Materias primas** — los canales seleccionados ya se actualizan automáticamente en segundo plano;
   para el precio de una página concreta, añada una **regla de extracción de precios** y pulse **Probar**.
2. Haga clic en la tarjeta de la serie → lea el gráfico y la **correlación** con una consulta de noticias.

**Trasladar (o fusionar) su corpus a otro equipo**
1. **Ajustes → Datos y copia de seguridad → Exportar / Copia…** — elija una carpeta o unidad de destino y
   una frase de contraseña; el corpus se transfiere como volúmenes cifrados + paridad (de cualquier tamaño).
2. En el otro equipo, **Ajustes → Datos y copia de seguridad → Importar…** — indique esa carpeta y
   restaure. La restauración es aditiva: complementa el corpus de ese equipo y nunca
   lo sustituye, así que también puede usarla para *fusionar* dos corpus. Una copia antigua de un solo archivo
   `oo-backup-2` no necesita nada especial: el análisis de Importar la encuentra esté donde esté dentro de la
   carpeta que indique y la ofrece como elemento propio, de modo que las copias antiguas siguen pudiendo restaurarse.

**Copiar la carpeta entera — una forma de pleno derecho de trasladar o hacer copia de seguridad**

Las herramientas de la aplicación existen para añadir lo que una copia de archivos no puede hacer (un manifiesto firmado, una paridad que
repara un volumen dañado, una fusión aditiva de dos corpus, una restauración selectiva). No son
un paso obligatorio. Copiar la carpeta de datos es una vía admitida para cualquier tamaño, y es
la adecuada para trasladar un equipo completo:

1. **Detenga la aplicación** — con el botón de encendido de la barra superior, o con Ctrl-C en su terminal. Esto no
   es opcional: una copia hecha mientras se ejecuta puede capturar un WAL a medio escribir.
2. Copie la carpeta **data** entera (§5.1 — `<app folder>/data/`, o la que indique `OO_DATA_DIR`).
   No la carpeta de la aplicación/código: el código se puede reinstalar, los datos no.
3. En el otro equipo, coloque la carpeta donde quiera y haga que `OO_DATA_DIR` apunte a ella —
   o, en una instalación completamente nueva, elija esa carpeta en el paso del primer arranque (§5.1).

El corpus sigue cifrado en reposo durante la copia, y las claves viajan dentro de la carpeta,
así que **la frase de contraseña es lo único que debe llevar por separado**. Desde 2026-08, los pesos de la IA local
también se guardan en la carpeta de datos, así que una copia los lleva también — y eso es lo que la convierte
en un verdadero traslado del equipo completo y no solo del corpus.

---

## 5. Referencia técnica

### 5.1 Dónde se guardan sus datos

Lo determina `src/paths.py`, en este orden de prioridad:

1. **`OO_DATA_DIR`** si está definida (siempre tiene prioridad).
2. **Copia del código fuente** — si se ejecuta desde un repositorio con permiso de escritura (instalación de desarrollo/editable/en el `$HOME`
   de Qubes), los datos se guardan en `<repo>/data/`.
3. **Por usuario** — en otro caso, XDG: `$XDG_DATA_HOME/open-omniscience` o
   `~/.local/share/open-omniscience`.

El caso 2 es el normal en una instalación con `install.sh`: el instalador clona un
árbol con permiso de escritura, así que sus datos están en `<app folder>/data/` y la ruta XDG del caso 3
nunca se crea. Que no esté cuando la busque no es un error.

**Elegir la carpeta en el primer arranque.** La primera vez que inicia la aplicación —
después de los pasos de idioma y avisos legales, antes de definir la frase de contraseña — le pregunta dónde
debe guardarse su corpus. Mantener la opción predeterminada es un solo clic. Si elige otra
carpeta (una unidad externa, por ejemplo), la aplicación crea una carpeta llamada **`OOS data`**
dentro de ella y registra la elección en `oo.env`, en la raíz de la instalación, que
`scripts/launch.sh` lee en cada arranque.

Dos aspectos de ese paso son deliberados y conviene conocerlos:

* **Solo aparece en una instalación completamente nueva.** Una vez que existe un corpus, la aplicación se niega
  a cambiar el ajuste, porque no puede mover lo que ya está allí: las claves,
  el registro de custodia y el almacén de modelos seguirían el nuevo ajuste mientras el corpus
  se quedaba atrás, y el siguiente arranque encontraría una carpeta vacía y ofrecería
  configurarla. Trasladar un corpus existente es la simple copia de carpeta descrita en §4 («Copiar la
  carpeta entera») — detenga la aplicación, copie la carpeta de datos y haga que `OO_DATA_DIR` apunte
  a la copia.
* **Elegir otra carpeta termina la configuración y le pide que vuelva a iniciar la aplicación.**
  En ese momento no se ha creado nada; la carpeta solo surte efecto en el siguiente
  arranque, así que continuar en la misma sesión pondría el corpus en la carpeta antigua
  mientras la elección registrada apuntaba a la nueva.

Se le avisa, sin bloquearle, si la carpeta es inusual: una carpeta que ya contiene un
corpus (continuar lo abre en lugar de crear uno nuevo), un sistema de archivos
en RAM (todo lo que se escriba allí se pierde al reiniciar) o poco espacio libre, con
la cifra. Solo se rechaza una carpeta en la que la aplicación realmente no puede escribir.

**Si se desconecta la unidad.** Una carpeta elegida de este modo recibe un pequeño archivo marcador,
`.oos-volume`, cuyo identificador también se registra en `oo.env` (`OO_DATA_VOLUME_ID`). La aplicación
lo lee cada dos segundos mientras se ejecuta. Si la unidad desaparece:

* La aplicación registra la desconexión en el disco interno (en
  `~/.local/state/open-omniscience/`, ya que no puede escribir en la unidad ausente).
  El paquete de diagnóstico incluye ese registro, y el siguiente arranque lo menciona cuando
  explica cómo terminó la sesión anterior.
* La recopilación se pausa y una ventana le pide que vuelva a conectar la unidad en 30 segundos.
  Si vuelve la misma unidad, la aplicación se reinicia para volver a abrir sus datos (un corpus
  cifrado vuelve a pedir su frase de contraseña). No puede simplemente continuar: la conexión
  a la base de datos se fija al iniciarse la aplicación.
* Pasados esos 30 segundos, una segunda cuenta atrás cierra la aplicación limpiamente en otros 30
  segundos; **Cerrar ahora** lo hace de inmediato. Volver a conectar la unidad durante esta segunda cuenta atrás
  sigue reiniciando la aplicación en su lugar.
* Lo que se estuviera escribiendo en los últimos instantes antes de la desconexión puede perderse. La
  base de datos en sí sigue siendo coherente: SQLite deshace una escritura inacabada la próxima
  vez que se abre.

Si inicia la aplicación mientras la unidad no está conectada, no crea una carpeta vacía
en su lugar: muestra una página de «su unidad de datos no está conectada», vuelve a comprobarlo
cada pocos segundos y abre la aplicación en cuanto vuelve la unidad. Una unidad
distinta montada en la misma ruta se reconoce como distinta (su marcador no
coincide). Si borró la carpeta a propósito, elimine las líneas `OO_DATA_DIR` y
`OO_DATA_VOLUME_ID` de `oo.env` para empezar de nuevo con un corpus nuevo y vacío.
El borrado de emergencia lo hace por usted. Si el sistema monta la unidad en una ruta nueva
tras volver a conectarla, la aplicación no puede encontrarla allí: ciérrela y haga que `OO_DATA_DIR` en
`oo.env` apunte a la nueva ruta.

En ese directorio encontrará: `open_omniscience.db` (el corpus, SQLite/WAL),
`app_settings.json` (tema, límite de resultados), `custody_settings.json` (preferencias
de custodia), las claves de custodia, los volcados de Wikipedia descargados, las instantáneas
`pre-restore-*.db` que haya y `models/` — los pesos de la IA local, que se guardan dentro del propio
directorio de datos de la aplicación y no en el directorio de cada motor:

| ruta | qué contiene |
| --- | --- |
| `models/ollama/` | El almacén de modelos de Ollama (`OLLAMA_MODELS` apunta aquí) |
| `models/huggingface/hub/models--<org>--<name>/` | Los pesos de vLLM, una carpeta por repositorio (`HF_HOME` apunta a `models/huggingface`) |
| `cache/` | Las cachés de cálculo del servidor vLLM — kernels de Triton, torch Inductor, la caché JIT de CUDA, las raíces de caché y configuración propias de vLLM. Se crea en el primer arranque, se puede borrar sin riesgo (se vuelve a crear) y puede ocupar varios GB |
| `vllm_start_attempts.jsonl` | Cada arranque y cada salida del servidor vLLM, con las palabras exactas del fallo. Se guarda **aquí** y no dentro del entorno de vLLM para que reinstalar vLLM — lo primero que intenta casi todo el mundo cuando un servidor no arranca — no borre el registro de por qué fallaba |
| `vllm_failed_starts/` | El registro completo de cada uno de los últimos arranques **fallidos**. El registro en vivo del servidor se sobrescribe en el siguiente intento, y un bucle de reintentos lo sobrescribe en menos de un minuto, así que se hace una copia en el momento en que se detecta que un arranque ha fallado. Unos pocos cientos de KB como máximo |

Si usted mismo define `OLLAMA_MODELS`, `HF_HOME` o cualquiera de las variables de caché
(`XDG_CACHE_HOME`, `TRITON_CACHE_DIR`, `TORCHINDUCTOR_CACHE_DIR`,
`CUDA_CACHE_PATH`, `VLLM_CACHE_ROOT`, `VLLM_CONFIG_ROOT`), su valor siempre tiene prioridad:
la aplicación vuelve a exportar su valor en lugar de sustituirlo. La redirección se aplica
solo al **servidor**: la instalación de vLLM sigue usando la caché de wheels normal de pip, así que
reinstalar no vuelve a descargar varios GB que ya tiene. Los pesos descargados **antes** del 2026-08-04
siguen en el propio `~/.cache/huggingface/hub/` de Hugging Face; Ajustes → IA los señala
e indica adónde moverlos, y no se mueve ni se borra nada por usted.

### 5.2 Variables de entorno

> **Nota de honestidad:** esta tabla recoge lo esencial para quien opera la aplicación — **no** es cada
> variable de entorno que el código puede leer (una auditoría contó unas ~259 referencias a variables
> de entorno en el código). Que una variable falte en esta tabla se debe a la
> brevedad del manual, no a que la variable no exista.

| Variable | Finalidad |
|---|---|
| `OO_DATA_DIR` | Sustituye el directorio de datos (véase más arriba). |
| `OO_HOST` / `OO_PORT` | Dirección/puerto de escucha (predeterminado `127.0.0.1:8000`). |
| `OO_AUTOSEED` | Carga el catálogo mundial en el primer arranque (activado de forma predeterminada; `0` para desactivarlo). |
| `OO_NO_SCHEDULER` | Defina `1` para que el programador en segundo plano no se inicie nunca automáticamente; la aplicación arranca entonces conectada en lugar de en modo avión. La protección de sockets del modo avión se instala de todos modos (solo `OO_AIRPLANE_SOCKET_GUARD=0` la omite), así que activar el modo avión más tarde sigue bloqueando las conexiones externas a nivel de socket (las pocas excepciones residuales se enumeran en SECURITY.md). |
| `OO_NO_INDEX` | Defina `1` para omitir la indexación automática de Perspectivas. |
| `OO_CUSTODY_ON_INGEST` | Valor predeterminado heredado para el registro automático de custodia al ingerir (la preferencia de la interfaz lo sustituye una vez guardada). |
| `OO_KEY_PASSPHRASE` | Cifra en reposo las claves privadas de custodia (AES-256-GCM mediante scrypt). Sin ella, las envuelve la frase de contraseña de la base de datos; sin ninguna de las dos, las claves se escriben `0600` en claro y se indican honestamente como `plaintext-0600`. |
| `OO_FETCH_TIMEOUT` / `OO_FETCH_MIN_INTERVAL` | Ajustan el tiempo de espera del recolector ético y el intervalo mínimo por host. |
| `OO_LLM_MODEL` / `OO_OLLAMA_URL` (o `OLLAMA_BASE_URL`) | Modelo local predeterminado y punto de acceso de Ollama. |
| `OO_ALLOW_BIG_SCANS` | Defina `1` para ejecutar los análisis en segundo plano de todo el corpus en un equipo por debajo del mínimo de memoria (véase [La memoria en un equipo pequeño](#55a-la-memoria-en-un-equipo-pequeño--el-único-límite-real)). El veredicto indica entonces que usted lo ha forzado. |
| `OO_CKPT_GATE_TIMEOUT_S` | Cuánto espera el punto de control del WAL entre pasadas a la compuerta de escritor único antes de registrar honestamente que lo omite y seguir adelante (predeterminado `30`). `0` restablece la antigua espera sin límite (el punto de control propio de la protección de almacenamiento sigue esperando como máximo 30 s a la compuerta de escritura, en un hilo propio, de modo que una reanudación forzada sigue vigilada). |
| `OO_STORAGE_GUARD` | Defina `0` para desactivar la protección de almacenamiento (sin muestreo, sin pausa). La protección pausa la recopilación por sí sola cuando el registro de escritura anticipada (write-ahead log) de la base de datos ha crecido por encima de un límite calculado según su equipo o la unidad está casi llena, y la reanuda por sí sola; «Reanudar de todos modos» en el aviso fuerza la recopilación mientras el límite sigue vigente, y termina por sí solo si el espacio libre cae demasiado o no se puede leer, si una escritura falla por falta de espacio o si se supera un segundo límite. La misma pausa retiene, mientras dura, la reindexación en segundo plano que completa una importación interrumpida y la creación única de los índices de la lista de artículos (sus filas en el administrador de tareas lo indican, y continúan por sí solas; «Reanudar de todos modos» fuerza la recopilación, no estas tareas). |
| `OO_DAMAGE_GUARD` | Defina `0` para desactivar la pausa que sigue a un informe de la base de datos sobre daños en uno de sus archivos de datos (el informe se sigue registrando en `database-damage.json` en su carpeta de datos, y el aviso indica entonces que la pausa está desactivada). Sin ella, ni la recopilación, ni las tareas de mantenimiento, ni el carril de Wikipedia (cada uno solo en su propio archivo) escriben en un archivo que la base de datos declara dañado hasta que usted vuelva a iniciar la recopilación (en el archivo de Wikipedia: hasta que desactive y vuelva a activar la obtención de Wikipedia). Una pausa establecida por la comprobación de arranque (véase `OO_BOOT_VERIFY`) solo termina cuando las tablas que nombró la comprobación vuelven a leerse sin errores; cualquier otra pausa termina, y vuelve a detenerse en la primera lectura fallida si el daño sigue ahí. Independiente de `OO_STORAGE_GUARD`. |
| `OO_BOOT_VERIFY` | Defina `0` para desactivar la comprobación de sus archivos de datos que se ejecuta al arrancar, mientras la aplicación sigue desconectada, tras una detención inesperada (y tras una comprobación anterior que quedó inacabada o encontró daños): cada tabla se lee una vez con `PRAGMA quick_check` de SQLite, una tabla cada vez, en una conexión de solo lectura, de modo que la comprobación no escribe nada propio. Una tabla, la lista de tablas o la comprobación de páginas que informe de daños se lee una segunda vez en una conexión nueva y solo cuenta como daño si la segunda lectura coincide: una segunda lectura distinta, o que no se puede hacer, la deja sin comprobar con el motivo, y no se pausa ni se repara nada por ello. En un archivo cifrado, cuando no se pudo responder por una tabla (SQLCipher lanza un error genérico para muchas páginas dañadas), también pide una vez la comprobación de páginas propia de SQLCipher (`PRAGMA cipher_integrity_check`, aproximadamente un segundo por cada 230 MB) y registra qué páginas fallan su autenticación (un archivo de más de 4 GiB no se somete a esa comprobación de páginas, porque más allá de ese punto lee bytes equivocados; el registro lo indica y el archivo no se declara sin errores); un archivo con páginas que fallan está dañado, y un archivo cuyas páginas pasan todas sigue sin declararse sin errores mientras haya una tabla sin respuesta. Una página que no pudo leer en absoluto (una unidad que falla) se cuenta aparte y no constituye por sí sola un hallazgo, y salir mientras se ejecuta esa comprobación no consume uno de los tres intentos. La recopilación espera hasta que termina; un archivo que encuentra dañado se pausa (véase `OO_DAMAGE_GUARD`), y volver a iniciar la recopilación vuelve a leer las tablas que nombró antes de levantar la pausa (en el archivo de Wikipedia, lo hace desactivar y volver a activar la obtención de Wikipedia). Una comprobación que no puede terminar no se vuelve a intentar tras tres arranques seguidos, y la aplicación lo indica (la retención dura en todos los arranques normales hasta que la aplicación vuelva a detenerse de forma inesperada, lo que es un nuevo motivo para comprobar); eso nunca borra un hallazgo: un archivo que una comprobación anterior encontró dañado sigue en pausa hasta que las tablas que nombró se lean sin errores (o se sustituya el archivo). El resultado de cada archivo está en `database-damage.json` en su carpeta de datos. |
| `OO_BOOT_REPAIR` | Defina `0` para desactivar la reparación de un archivo de biblioteca dañado (y, con ella, la eliminación descrita más abajo). De forma predeterminada, cuando la comprobación de arranque (véase `OO_BOOT_VERIFY`) lee una tabla de su archivo de biblioteca como dañada, la aplicación repara el archivo en ese arranque, mientras sigue desconectada y antes de que la recopilación escriba nada: copia todas las filas que todavía puede leer, tabla por tabla, en un archivo nuevo junto al original, reconstruye los índices y el índice de búsqueda, comprueba el archivo nuevo con la misma lectura por tabla y solo entonces pasa a usarlo. Las filas de páginas que no se pudieron leer no están en el archivo nuevo; el aviso indica cuántas entradas se copiaron y cuántas no se pudieron leer, y en qué tablas estaban. Las filas cuya fila padre no se pudo leer se conservan, nunca se eliminan, y se cuentan por tabla; cuando una tabla, de otro modo, asignaría el número de una fila perdida a la siguiente fila guardada, la reparación añade UNA fila de relleno marcada «(lost …)» en el número perdido más alto (es una fila visible, y el índice de búsqueda la encuentra con esa marca), y el aviso nombra esas tablas. Todo lo que la aplicación guarda espera mientras trabaja (la reparación necesita la compuerta de escritura, que está activada de forma predeterminada: con `OO_WRITE_GATE=0` se niega y lo indica), y si, aun así, se guardó algo en el archivo mientras se hacía la copia, la copia se descarta y se rehace en el siguiente arranque en lugar de sustituir el archivo pasando por encima de ese guardado. Necesita el espacio libre del archivo completo más su registro más la reserva que mantiene la protección del disco, y una unidad que pueda dar a un archivo un segundo nombre (un enlace duro); indica cuál de esas condiciones falta y no cambia nada cuando falta alguna. Solo se repara el archivo de biblioteca, y solo después de que la propia comprobación de ese arranque haya encontrado daños: los archivos de Wikipedia y de leyes se pausan como antes pero no se reparan, un archivo que se encuentra dañado mientras la aplicación se ejecuta se comprueba en el siguiente arranque y se repara entonces si la comprobación lo confirma, y una tabla que la comprobación no pudo leer no constituye un hallazgo. **El archivo dañado se conserva, no se borra:** la reparación le da un segundo nombre junto al archivo nuevo, `<name>.damaged-<date and time>.<ending>` (con su registro bajo el mismo nombre y `-wal`), porque puede contener todavía filas que la copia no pudo leer, para una herramienta de recuperación. **La aplicación elimina ese único archivo 30 días después de que el archivo nuevo se leyera sin errores por primera vez**, en el primer arranque en esa fecha o después, nunca mientras se esté ejecutando una reparación o una comprobación ni mientras se vuelva a informar de daños en la biblioteca; el aviso de reparación y el zip de Diagnóstico indican su tamaño, dónde está y la fecha, y tras la eliminación indican que se eliminó y qué tamaño tenía. Si la propia unidad no pudo leer una página de su archivo de biblioteca (el aviso indica cuántas páginas), la aplicación no elimina ese archivo en absoluto, porque una unidad que falla puede ser la causa de que no se pudieran leer las páginas: permanece hasta que usted mismo lo elimine, y el aviso le indica que compruebe la unidad. Con `OO_BOOT_REPAIR=0` la eliminación está desactivada y el aviso lo indica. Puede eliminarlo usted mismo en cualquier momento. Solo borra el archivo que la reparación apartó (debe estar en su carpeta de datos, ser un archivo normal, con ese nombre exacto y ser el mismo archivo que registró la reparación) y nada más; si algo de eso no se cumple, no elimina nada, lo indica y no vuelve a intentarlo. Una reparación que empezó y no terminó se vuelve a intentar en el siguiente arranque; a dos arranques seguidos que terminaron a mitad de reparación no les sigue un tercero hasta que se actualice la aplicación (el registro es `database-repair-attempt.json` en su carpeta de datos). El registro de cada reparación (la fecha, los recuentos, el nombre del archivo y, cuando ocurra, su eliminación) está en `database-damage.json`; conserva las diez últimas, y la aplicación nunca elimina un archivo conservado cuyo registro haya salido de esas diez. |
| `OO_ARTICLE_INDEXES` | Defina `0` para dejar sin crear los dos índices de la lista de artículos. De forma predeterminada, la aplicación los crea una vez, en el primer arranque tras una actualización, mientras sigue desconectada: uno para el filtro de idioma y otro para ordenar por título, de modo que ambos sigan siendo rápidos a medida que crece la biblioteca (ocupan unos 190 MB por cada 1,5 millones de artículos). En una biblioteca grande en una unidad lenta, la creación puede tardar unos minutos; aparece en el administrador de tareas como «Creando los índices de la lista de artículos», todo lo que la aplicación guarda espera hasta que termina, y necesita dos cosas que mide primero y sobre las que avisa, sin empezar, cuando falta alguna: unos 400 bytes de espacio libre por artículo en la unidad donde está su archivo de datos, y memoria para ordenar los títulos (unos 300 bytes por artículo, en memoria y nunca escritos en un archivo temporal, más la memoria libre que la aplicación siempre reserva para sí misma; indica las cifras). Un arranque que termina a mitad de la creación la vuelve a empezar; a dos arranques seguidos que terminan a mitad de la creación (el equipo se quedó sin memoria o sin corriente) no les sigue un tercer intento hasta que se actualice la aplicación, porque una creación que por sí misma hace caer la aplicación no debe convertirse en un arranque que nunca termina (su registro es `article-indexes-attempt.json` en su carpeta de datos; borrarlo permite a la aplicación volver a intentarlo, y cerrar la aplicación de la forma normal devuelve el intento). Con el interruptor desactivado, o tras una negativa que se repite, cada arranque dedica una fracción de segundo a comparar la versión de la base de datos con sus tablas. Con el interruptor desactivado, la lista funciona como antes, solo que más lenta en esas dos opciones. |
| `OO_WAL_HIGH_MB` / `OO_DISK_RESERVE_MB` | Sustituyen los dos límites calculados de la protección de almacenamiento por una cifra en MB: el tamaño del registro de escritura anticipada a partir del cual se pausa la recopilación, y el espacio libre por debajo del cual se pausa (predeterminado: calculado según su equipo; los límites aparecen en el aviso que la protección muestra en el administrador de tareas mientras retiene la recopilación). |
| `OO_STORAGE_GUARD_TRIP_AFTER` / `OO_STORAGE_GUARD_RESUME_AFTER` | Cuántas muestras consecutivas (con unos cinco segundos de separación) activan y liberan la protección (predeterminado `2` y `2`). |
| `OO_WRITE_GATE_WARN_S` | Registra una advertencia, con el nombre del hilo que la retiene y una pila de llamadas, cuando una sola escritura retiene la compuerta más tiempo que este (predeterminado `60`); la advertencia se escribe cuando se detecta la retención, así que su cifra es al menos el umbral y no la duración de la retención. Cuando termina una retención así, el registro recibe una segunda línea, `write gate released after 61.3s by 'name'` (la duración real, con una precisión de una décima de segundo, en lugar de 61,3; las retenciones de menos de un segundo nunca la reciben). `OO_WRITE_GATE_WATCHDOG=0` desactiva por completo la vigilancia. |
| `OO_REINDEX_HOLD_TARGET_S` | Cuánto tiempo puede retener un lote de una reindexación la compuerta de escritor único antes de confirmar y dejar pasar a un escritor en espera (predeterminado `10`). Se aplica a la reindexación en segundo plano de los artículos importados, a la tarea de reindexación de todo el corpus (cuando `OO_REINDEX_COMMIT_BATCH` es mayor que 1) y a la reindexación que cierra una restauración. Confirma antes aún, en el siguiente artículo después de que otra escritura se ponga en cola tras ella, una vez que el lote ha retenido la compuerta al menos un segundo (así que una retención puede superar el objetivo en el artículo en curso más la confirmación, y un escritor que siempre está en cola le cuesta a la reindexación aproximadamente una confirmación por segundo en lugar de una por artículo). El ancho del lote (`OO_IMPORT_REINDEX_COMMIT_BATCH`, `OO_REINDEX_COMMIT_BATCH`) sigue siendo el máximo, y con un ancho de `1` cada artículo se confirma por sí solo, así que no hay lote que el objetivo pueda terminar antes (el informe de la restauración y el progreso de la tarea de reindexación siguen nombrando el objetivo vigente). `0` es la regla antigua: confirmar solo al alcanzar el ancho del lote. Un valor que no sea un número de segundos igual o mayor que cero mantiene el predeterminado. |
| `OO_HEAVY_TAIL_WAIT_S` | Cuánto esperan el uno al otro el recálculo del resumen de Inicio y el carril de mantenimiento en segundo plano, en lugar de ejecutarse a la vez (predeterminado `900`). `0` espera indefinidamente. |
| `HTTPS_PROXY` | Encamina el tráfico saliente (p. ej., OpenTimestamps) a través de un proxy/Tor. |

### 5.3 Complementos opcionales

Se instalan con `pip install -e ".[extra]"`:

- **`analysis`** — estadísticas, análisis de palabras clave/entidades, correlación con mercados.
- **`nlp`** — modelos de spaCy para un reconocimiento real de entidades con nombre en Perspectivas.
- **`pqc`** — firma poscuántica ML-DSA para la Cadena de custodia.
- **`timestamping`** — anclaje con OpenTimestamps (Bitcoin).
- **`dev`** — herramientas de pruebas/lint.

Si falta un complemento, la función que depende de él **falla de forma visible** (un error claro o
un `503`, un estado honesto de «no instalado») — nunca simula la capacidad en silencio.

### 5.4 La API HTTP

La aplicación es un servidor FastAPI en `127.0.0.1:8000`; la interfaz web es un único
`index.html` sin dependencias servido en `/`. El esquema legible por máquina está en **`/openapi.json`**. Las páginas interactivas de Swagger (`/docs`) y ReDoc
(`/redoc`) están **desactivadas de forma predeterminada**: hacen que el navegador descargue scripts, estilos y una fuente de hosts
de terceros, así que un desarrollador que las quiera inicia la aplicación con `OO_API_DOCS=1`. Métricas de Prometheus en `/metrics`. **No hay autenticación**, por diseño
(solo bucle local, un único usuario). Todos los puntos de acceso tienen **límite de solicitudes** (aproximadamente: lecturas
100/h, escrituras/exportaciones 50/h, borrados 20/h, importaciones masivas 10/h; `429` con
`Retry-After` cuando se supera).

Un inventario resumido (consulte `/openapi.json`, o `/docs` con `OO_API_DOCS=1`, para el esquema autorizado y siempre actualizado, y
`docs/ARCHITECTURE.md` para la descripción en prosa):

**Núcleo y búsqueda** — `GET /api/health`; `GET /api/articles` (FTS + filtros);
`GET /api/articles/export` (csv|json); `GET /api/articles/{id}/view` (HTML sin conexión);
`GET /api/sources`.

**Ingesta** — `POST /api/sources/seed-defaults`;
`POST /api/sources/{id}/ingest`; `POST /api/sources/{id}/ingest-email` (IMAP);
`POST /api/ingest` (una sola URL).

**Fuentes y catálogo** — CRUD completo en `/api/sources/…` (incl. operaciones por lotes, grupos,
grupos por etiqueta, metadatos, descubrimiento, importación/exportación YAML, estadísticas, búsqueda); catálogo
CSV en `/api/catalog/sources`, `/export.csv`, `/template.csv`, `POST /import`.

**Programador** — `GET /api/scheduler/status|config|targets`;
`PUT /api/scheduler/config`; `POST /api/scheduler/start|stop|run-now`.

**Base de datos y copia de seguridad** — `GET /api/database/stats|coverage|countries`;
`GET /api/database/backup` (instantánea `.db` en bruto; con un nombre que usted haya incluido en `OO_ALLOWED_HOSTS`, una solicitud que no indique de qué página procede debe añadir la cabecera `X-OO-Download: 1`, como hace `curl -H "X-OO-Download: 1" …`; escribir la dirección en un navegador, o abrir un marcador, con un nombre de ese tipo en HTTP simple no envía nada de lo que un navegador añadiría en bucle local o HTTPS, así que ahí se rechaza). Las copias de seguridad las **crean** los motores
de transmisión: volúmenes cifrados + paridad en `POST /api/backup/v2/volumes/start` (+ `/restore`,
`/cancel`, `GET /volumes/status`) y la copia de carpeta para grandes volúmenes de datos en
`POST /api/backup/folder/start` (+ `/plan`, `/restore`, `/{action}`, `GET /folder/status`).
La restauración de un archivo antiguo de un solo fichero es la **fusión aditiva**:
`POST /api/backup/v2/restore/preview`, `POST /api/backup/v2/restore/commit`,
`GET /api/backup/v2/batches`. *(Se eliminaron los destructivos `POST /api/database/restore` y
`/api/safety/restore/encrypted`.)*

**Sistema y red** — `GET /api/system/vitals|network|interfaces`;
`POST /api/system/network` (interruptor del modo avión); `GET /api/system/doctor|lock-state`;
`POST /api/system/unlock|create-db|encrypt-db`. **Tareas / administrador de tareas** —
`GET /api/jobs`; `POST /api/jobs/dumps/reorder`; `POST /api/jobs/{id}/cancel`.

**Mapa mundial** — `GET /api/timemap` (señales espacio-temporales; `?kinds`, ventana `?start`/`?end`
en años fraccionarios, `?hazards`, `?articles`, `?mentions`, `?days`); `GET /api/timemap/range`.

**Etiquetas de fecha de los artículos** — `GET/POST /api/article-dates/article/{id}` (listar / extraer);
`POST /api/article-dates/{tag_id}/confirm|reject`; `POST /api/article-dates/index`;
`GET /api/article-dates/by-date`.

**Perspectivas** — `GET/PUT /api/insights/filter`; `POST /api/insights/exclude|include`;
`GET /api/insights/status`; `POST /api/insights/reindex`;
`GET /api/insights/top|trending|trend|associations|context|map`; agregados de
**Cuándo×Dónde×Quién** sobre todo el corpus en `GET /api/insights/who|where`.
**Encuadre** — `GET /api/framing`.

**Búsqueda (omnibarra)** — `GET /api/search/omni` (federación basada en índices sobre artículos,
palabras clave, fuentes, Wikipedia vigilada y leyes seguidas).

**Enlaces** — `GET /api/links/shared` (qué artículos del conjunto comparten enlaces salientes, con
notas de independencia); `GET /api/links/preview` (extracción local para la vista previa de enlaces).

**Eventos de la agenda** — `GET /api/events/calendars|feeds|imported`;
`GET /api/events/astronomy` (fases lunares calculadas localmente — luna nueva, cuarto creciente, luna llena, cuarto menguante — + equinoccios/solsticios, verificados con
un almanaque) y `GET /api/events/climate` (conjunto de datos de El Niño incluido). **Contexto meteorológico** —
`POST /api/weather/context` (fragmentos de reanálisis de Open-Meteo guiados por el corpus, con consentimiento).

**Mercados y materias primas** — `/api/markets/rules` (CRUD + `/run`),
`/api/markets/overview|series|feeds`, `/api/markets/feeds/{key}/import`,
`/import-all`, `/import-url`; `/api/commodities/{symbol}/prices` (+ `/import-csv`,
`/correlation`).

**Gobiernos** — indicadores del Banco Mundial por país + el mapa coroplético, de solo lectura
salvo la única obtención con consentimiento: `GET /api/governments/indicators|map|country/{iso}`;
`POST /api/governments/load-standard` (+ `/load-standard/status`, una tarea en segundo plano).
**Legislación mundial** — leyes, boletines oficiales y registros de propiedad intelectual seguidos, una réplica para investigación (nunca asesoramiento
jurídico): `GET /api/law/status|documents|documents/{id}|documents/{id}/view|changes`;
`POST /api/law/documents` (añadir un documento por URL — se obtiene de inmediato);
`DELETE /api/law/documents/{id}` (dejar de seguirlo; el historial se conserva); `POST /api/law/track`
(obtener ahora todos los documentos vigilados) y `/api/law/seed` (volver a cargar el catálogo mundial).
Un documento seguido se convierte en un artículo del corpus de pleno derecho y que se puede buscar (Cuándo×Dónde×Quién,
palabras clave) junto a las noticias recopiladas, con su historial de modificaciones como una capa vinculada.

**Wikipedia** — `GET /api/wiki/status|pages|changes`; `POST /api/wiki/pages`,
`/track-now`, `/pages/{id}/track`; `GET /api/wiki/revisions/{id}`;
`GET /api/wiki/languages` (una lista **plana, con los idiomas de la interfaz primero**, en la que cada opción empieza por el
nombre nativo; `region` se conserva solo como metadato descriptivo — sin `groups` por continente;
`?scope=dumps` añade estimaciones de tamaño `~GB` en línea); volcados en `/api/wiki/dumps…`.

**Cadena de custodia** — `POST /api/custody/log`; `GET /api/custody/{item}` (+
`/verify`); `POST /api/custody/verify`; `GET /api/custody/export`;
`GET /api/custody/providers`; `POST /api/custody/anchor`;
`GET/PUT /api/custody/settings`; `POST /api/custody/reconcile` (una entrada INGEST que
no se pudo escribir cuando se guardó su artículo se pone en cola y se escribe más tarde, al final
de la siguiente pasada de recopilación mientras el registro automático esté activado, marcada como tardía en sus propios metadatos firmados --
la pestaña Cadena de custodia las cuenta, y su
botón «Buscar entradas de ingesta faltantes» cuenta los huecos más antiguos sin registrar nada
hasta que pulse «Registrarlas, marcadas como tardías»). **Evidencia** — `POST /api/reports/evidence`
(+ `/verify`).

**LLM (Ollama local)** — `GET /api/llm/health|models`; `POST /api/llm/generate`;
`POST /api/llm/articles/{id}/summarize|translate`.

**Otros** — `/api/analysis/*` (pruebas t, correlación, ANOVA, …);
`/api/keywords/*` (utilidades de extracción); `/api/monitoring/health|anomalies`;
`POST /api/verify/image-metadata` (EXIF/GPS).

### 5.5 Uso a través de Tor

La aplicación funciona a través de Tor (modo de obtención Protegido (Protected) → un proxy Tor que usted ejecuta), con un
alcance honestamente menor — medido, no supuesto (registro en vivo del 2026-06-12: 32 de 50
fuentes predeterminadas importadas a través de Tor en una pasada):

- **Los rechazos de conexiones concretas son normales, no fatales.** Algunos hosts rechazan algunos
  nodos de salida de Tor: en la misma ejecución, se importaron 21/28 series de FRED mientras otras fallaban.
  Por eso los fallos de los canales llevan un **veredicto que tiene en cuenta el transporte** — *rechazado*
  («conexión rechazada/restablecida — a través de Tor suele ser el rechazo de un único nodo de
  salida; un reintento a menudo usa otro circuito») no es *robots
  lo prohíbe* (la política declarada del host, que respetamos y nunca reintentamos ni
  eludimos), no es *serie muerta* (HTTP 404 — la entrada del catálogo necesita un
  sustituto; reintentar no sirve de nada), no es *inalcanzable*. Los fallos
  transitorios se reintentan una vez automáticamente; el botón **Reintentar los canales fallidos**
  vuelve a ejecutar exactamente los que honestamente se pueden reintentar.
- **El bloqueo de Tor por parte de un host es decisión del host.** Lo mostramos; nunca eludimos
  robots, bloqueos ni CAPTCHA. Prefiera los puntos de acceso oficiales que toleran Tor cuando
  existan.
- **Las descargas de modelos no funcionan a través de Tor.** Ollama descarga sus modelos por internet
  abierto mediante su propio proceso (instalar/descargar desde **Ajustes → IA**); disponer de una conexión
  a internet abierto que funcione es un requisito previo declarado para descargar un modelo. Una vez descargado, la inferencia
  se hace en bucle local y no se ve afectada. *(Hay previsto un kit de LLM sin conexión empaquetado, pero aún no se ha publicado.)*
- **Si la instalación de vLLM se interrumpe a medias**, casi siempre se debe a que se agota el tiempo de una descarga
  de uno de los wheels muy grandes — solo torch ocupa unos 500 MB. El mensaje lo
  nombra, y los wheels ya descargados quedan en caché, así que volver a iniciar la instalación la reanuda
  en lugar de empezar de cero. En una conexión tan lenta que sigue fallando, aumente
  `UV_HTTP_TIMEOUT` (en segundos) antes de iniciar la aplicación.
- **Si el servidor vLLM arranca y se cae una y otra vez**, el motivo queda registrado tanto si
  lo estaba mirando como si no: cada arranque y cada salida se anotan en
  `vllm_start_attempts.jsonl` con las palabras exactas del fallo, y el registro completo de
  cada uno de los últimos arranques fallidos se guarda en `vllm_failed_starts/` — ambos en el
  directorio de datos, así que reinstalar vLLM no los borra. Ambos van incluidos en la exportación
  **Diagnóstico → todos los diagnósticos (all diagnostics)**, así que la respuesta está en el paquete y no es
  algo que haya que captar en directo.
- **El anonimato sigue siendo responsabilidad suya**: el modo Protegido no puede garantizar
  el anonimato — usted ejecuta el proxy y confía en él; lo que hace la aplicación es encaminar sus obtenciones
  web a través de él con un User-Agent genérico, salvo en sus solicitudes de API y de volcados
  a los servidores de Wikimedia, que siguen nombrando la herramienta (la política de la API de Wikimedia
  lo pide). La descarga del buzón de boletines, el anclaje con OpenTimestamps y
  las descargas de la IA local se conectan directamente.

---

### 5.5a La memoria en un equipo pequeño — el único límite real

La aplicación ya se reduce por sí sola en un equipo pequeño: por debajo de **4 GB de RAM**, o con
menos de **1 GB libre**, usa una caché de base de datos más pequeña y menos conexiones
en el pool, limita cuántas fuentes obtiene a la vez y **pausa los análisis en segundo plano
de todo el corpus** (la cualificación de fuentes). Se lo indica, con las
cifras, junto al estado de la recopilación en Ajustes → Avanzado → Recopilación.

**Digamos el coste en voz alta:** en un equipo con un corpus grande y poca memoria
libre, esto puede significar que la cualificación de fuentes nunca se ejecute allí. Es el coste
del ajuste, no un fallo. Para ejecutarlos de todos modos, inicie la aplicación con
`OO_ALLOW_BIG_SCANS=1` — el veredicto indica entonces que usted lo ha forzado, y
sigue indicando que el equipo es pequeño, porque el forzado cambia lo que la
aplicación *hace*, nunca lo que *midió*.

#### Una vista pesada se detiene antes de poder tumbar la aplicación

Las lecturas analíticas pesadas (la mayoría de las vistas de Perspectivas, el Observatorio, las fuentes
más citadas, el paquete de diagnóstico) ya se ejecutan con un límite de tiempo. Además
vigilan la memoria disponible mientras la base de datos les entrega filas. Si baja al
mínimo de la protección de memoria (**256 MB** de forma predeterminada, `OO_MEM_GUARD_AVAIL_MB`), la lectura
se detiene y la vista explica por qué, con las cifras: *«se detuvo esta lectura tras
12 s: el equipo casi se había quedado sin memoria (180 MB disponibles, en o por debajo del
mínimo de 256 MB que usa la protección de memoria) ...»*. Una lectura solicitada cuando la memoria ya
está así de baja no empieza, y en su lugar indica *«no se inició esta lectura»*.
Vuelva a abrir la vista cuando la memoria se haya recuperado; no se ha perdido nada,
porque una lectura no cambia nada.

**Lo que no hace:** es una parada, no un límite. Ve lo que crece mientras se están
leyendo filas, que es donde crece una vista que carga una tabla entera, y
nada más. `OO_READ_MEMORY_STOP=0` la desactiva sin tocar la protección.

#### Cuando la memoria sigue agotada, la aplicación se detiene sola y lo dice

La protección de memoria pausa la nueva recopilación cuando escasea la memoria. Una pausa no
devuelve lo que la aplicación ya retiene, así que en un equipo pequeño la memoria puede quedarse en
el mínimo durante muchos minutos y entonces el sistema operativo mata la aplicación sin
explicar por qué. Ahora, en su lugar, la aplicación se cierra sola. Solo lo hace cuando se cumple **todo**
lo siguiente: la protección ha estado activa durante la totalidad de los últimos **5 minutos**
(`OO_MEM_STOP_WINDOW_S`), al menos nueve de cada diez de sus lecturas estaban en o por debajo de
**64 MB** disponibles (`OO_MEM_STOP_AVAIL_MB`), ninguna superaba 128 MB, ningún intervalo entre
lecturas fue mayor que una décima parte de la ventana (30 s), y esta aplicación retiene al menos un tercio de
la memoria del equipo (si otra cosa la retiene, detenerse no liberaría nada,
y la aplicación no se detiene). Una recuperación, aunque sea breve, o pulsar iniciar o
reanudar vacía la ventana.

Antes de detenerse, conserva lo que sabe: una instantánea de lo que estaba haciendo cada hilo,
una línea en el registro de sesiones y `memory_stop.json` junto a sus datos
(cifras y nombres de pasos, como máximo 8 KB). Luego se cierra por la misma vía que
el botón de encendido. Sus datos guardados no se tocan; primero espera hasta un minuto
a que termine una importación en curso, una tarea en segundo plano que retenga el corpus o una escritura en la base de datos
en curso (una restauración o un traslado de la unidad de datos se registran como en curso pero
no se esperan como tales), indica en el registro si aún quedaba alguna, y lo que no pudo
terminar en ese tiempo queda sin terminar.
Mientras se ejecuta, el administrador
de tareas indica *«La aplicación se detiene sola porque la memoria siguió agotada»*.
En el siguiente arranque, la fila **Sesiones** de la pestaña Sistema indica *«Se detuvo sola —
la memoria siguió agotada»* (pase el cursor por encima para ver la advertencia), un mensaje que se muestra una sola vez dice lo
mismo, y el zip de Diagnóstico incluye el registro. **Lo que termina es lo que se estaba
ejecutando; usted lo vuelve a iniciar.** `OO_MEM_STOP=0` desactiva la detención y mantiene la
pausa.

#### Por qué la aplicación no puede simplemente limitar su propia memoria

No hay una forma honesta de que un programa se imponga a sí mismo un límite de memoria:

- **Linux ignora `RLIMIT_RSS`.** Existe en la API y no hace nada.
- **`RLIMIT_AS` limita el *espacio de direcciones*, no la memoria en uso.** Las bibliotecas que usa esta
  aplicación (DuckDB, numpy) reservan mucho más espacio de direcciones virtual del que llegan a
  tocar, así que un límite al espacio de direcciones provoca `MemoryError` en código no relacionado mucho
  antes de que el proceso sea realmente grande. La aplicación no fija deliberadamente ninguno de los dos, y una
  prueba hace fallar la compilación si alguna vez se añade uno.

#### El límite que sí funciona: ejecutarla en un cgroup

En Linux con systemd, inicie la aplicación con un límite de memoria estricto:

```bash
systemd-run --user --scope -p MemoryMax=3G -p MemorySwapMax=0 \
  ~/open-omniscience/scripts/launch.sh
```

**Lo que esto aporta, honestamente:** convierte un *bloqueo del escritorio* en un *reinicio limpio
de la aplicación*. Sin límite, un equipo que se queda sin memoria recurre al intercambio hasta quedar
inutilizable para todo — el navegador, el terminal, el escritorio — y puede que tenga
que apagarlo y encenderlo. Con un límite, el núcleo mata **esta aplicación** en su lugar, y
solo esta aplicación.

**Lo que cuesta:** la aplicación muere a mitad de trabajo, sin oportunidad de ordenar nada.

**Por qué su corpus está a salvo de todos modos:** la base de datos funciona en modo WAL con
`synchronous=NORMAL`, así que una interrupción forzada solo puede perder trabajo que nunca se confirmó.
Todo lo confirmado está en el disco, y el registro de escritura anticipada se vuelve a aplicar la próxima
vez que desbloquee. **No se pierde nada de lo que ya había recopilado.**

Una **copia de seguridad** interrumpida de este modo es otra cuestión: queda incompleta.
Pero no se le concede confianza en silencio: cada volumen lleva una suma de verificación en el
manifiesto, y el propio paso de verificación de la copia las comprueba todas y nombra las que
faltan o no coinciden. Ejecute una verificación (o simplemente vuelva a hacer la copia)
antes de fiarse de una que se interrumpió.

Elija `MemoryMax` en torno al **60–75 % de la RAM total**, dejando espacio para el
escritorio y el navegador. `MemorySwapMax=0` es la mitad que evita la saturación por intercambio:
sin ella, la aplicación todavía puede hacer que el equipo se arrastre por el intercambio antes de alcanzar
el límite.

Si no usa systemd, lo mismo está disponible mediante Docker/Podman
(`--memory=3g --memory-swap=3g`) o un `memory.max` de cgroup v2 sin más.

#### Después de un fallo: lo que puede decirle el siguiente arranque

Cuando la aplicación muere o falla, la ventana del lanzador ahora permanece abierta e indica
cómo terminó: `SIGKILL` es la señal habitual de un mecanismo que mata procesos por falta de memoria. Una detención
normal (el propio botón Detener de la aplicación, cerrar la ventana, cerrar la sesión) cierra la
ventana como antes.

El siguiente arranque indica entonces cómo terminó la sesión anterior, en **Ajustes →
Avanzado → Diagnóstico → Análisis de la sesión** y en `session-forensics.json`
dentro del archivo de Diagnóstico, a partir de cualquiera de estos testigos que haya respondido:

- el registro del lanzador con el estado de salida (`diagnostics/launcher_exits.jsonl`);
- el registro del núcleo, que nombra las terminaciones por falta de memoria del propio núcleo;
- las líneas de registro de los mecanismos de espacio de usuario que matan procesos por falta de memoria (systemd-oomd, earlyoom,
  nohang) y de systemd-coredump que nombran la aplicación. Estas nunca aparecen en el
  registro del núcleo, y systemd-oomd nombra el cgroup de la aplicación en lugar de su proceso;
- una traza de fallo de cada hilo cuando el código nativo aborta
  (`diagnostics/crash_trace.log`).

Las lecturas de registros son locales y de solo lectura, y solo conservan las líneas sobre esta aplicación.
`OO_NO_KERNEL_LOG=1` las desactiva; `OO_CRASH_TRACE=0` desactiva la traza.
Los mecanismos que matan procesos por falta de memoria escriben en el diario del sistema, que solo pueden leer los miembros de `adm` o
`systemd-journal` (`wheel` en Fedora); cuando su usuario no puede, el informe
lo indica en lugar de declarar vacío el registro. Si no hay ningún testigo, el informe
dice que el final es desconocido, nunca que fue limpio.

El mismo informe indica de qué estaba compuesta la memoria en el pico de la sesión. Cuando
ese pico se produjo con la memoria ya demasiado escasa para leer el montículo de C de forma segura, que es
lo habitual justo antes de un fallo por falta de memoria, también muestra el pico anterior más reciente
que sí pudo leerlo, con su propio tamaño y hora. También indica
qué estaba haciendo cada hilo (su nombre, el código de la aplicación que ejecutaba y la CPU
que usaba) en dos tipos de momento: cuando la memoria disponible bajó del 15 % de la RAM
(como máximo 1 GB), primero al cruzar ese umbral y de nuevo en cada nuevo mínimo, y cuando la
aplicación creó un millón o más de objetos de Python en cinco segundos, como máximo una vez
cada cinco minutos. Las ocho instantáneas más recientes se guardan en
`session_pressure.json` en la carpeta de datos, y permanecen en este equipo como
el resto del diagnóstico.

## 5.6 Límites conocidos y advertencias honestas

La honestidad por construcción implica decir lo que la herramienta *no* puede decirle, no solo
lo que sí puede. Estos son los límites permanentes de los métodos (el «barrido de advertencias»
de la auditoría 07). Ninguno es un fallo; cada uno condiciona cómo leer un resultado.

- **Los recuentos de palabras clave y tendencias son léxicos, no semánticos.** Miden con qué
  frecuencia aparecen las palabras, no lo que se quiso decir. La negación («no es una crisis»),
  las citas, el sarcasmo y la ironía se cuentan al pie de la letra. El volumen es cobertura,
  nunca importancia ni verdad.
- **El sentimiento/tono es VADER, un método basado en un léxico inglés.** Las puntuaciones de
  artículos que no están en inglés no son fiables; las superficies de Sentimiento y de Encuadre
  lo advierten y muestran la proporción puntuada en inglés. El tono es una señal medible, nunca
  un veredicto de que un medio sea parcial.
- **Los resúmenes y traducciones de un LLM son productos del modelo.** Un modelo local puede ser
  fluido y equivocarse. Cada celda generada lleva la etiqueta «verificar con el artículo
  almacenado»; trate su resultado como una pista y contrástelo con el texto original que usted
  recopiló.
- **Un artículo largo se divide, no se recorta.** La ventana de contexto de un modelo es finita.
  Cuando pide un resumen o una traducción de un artículo que no cabe, la aplicación lo divide por
  los límites de párrafo y procesa cada parte: una traducción es la unión de las partes, y un
  resumen es el resumen de cada parte, resumidas después en conjunto. En ambos casos el resultado
  lo indica («traducido en N partes», «resumen jerárquico sobre N partes»), porque un resumen en
  dos pasos es un producto distinto de uno hecho de una sola pasada, y usted debe saber cuál está
  leyendo. Nunca se detiene a mitad sin avisar: una traducción truncada parece exactamente una
  completa. Los barridos en segundo plano (la extracción de quién/dónde/cuándo) SÍ truncan los
  artículos largos, y dejan constancia de ello («se analizaron los primeros N de M caracteres»),
  para que una extracción escasa nunca se confunda con un artículo escaso.
- **La IA en segundo plano es un solo carril, y su trabajo va primero.** Los barridos que usted
  activa se ejecutan de uno en uno sobre el único backend local, en lugar de competir por él.
  Cualquier cosa que pida usted mismo (una traducción masiva, la ejecución manual de un barrido)
  pausa ese carril mientras dura, y este se reanuda por sí solo después; nada pierde su turno. En
  un equipo donde la inferencia local no es práctica, el carril está desactivado por defecto, con
  el motivo indicado, y aun así puede activarlo.
- **La aplicación es solo de texto.** Analiza el texto de los artículos. Las imágenes solo
  ofrecen honestidad sobre EXIF/metadatos (ninguna afirmación forense ni de detección de
  deepfakes); no hay análisis de audio ni de vídeo. Una afirmación que solo existe en un vídeo o
  una imagen queda fuera de lo que la herramienta puede ver.
- **El japonés y el tailandés necesitan el extra opcional `[segmentation]`.** La extracción de
  palabras clave se basa en la separación por espacios salvo que haya instalado un segmentador de
  palabras. El chino se segmenta en todas las instalaciones (jieba, dependencia básica desde la
  0.4); el análisis de palabras clave en japonés y tailandés es prácticamente inoperante sin el
  extra (janome, pythainlp), aunque la interfaz se ofrezca en esos idiomas, y la búsqueda en
  japonés solo se divide en palabras con el sudachipy del extra. El conjunto **gestionado**
  (segmentado por espacios, con una lista de palabras vacías) se define en
  [`src/analytics/managed.py`](../src/analytics/managed.py); la *profundidad analítica* varía
  según el idioma, y las escrituras sin segmentar son la mayor carencia actual.
- **Sesgo de supervivencia de los sitios permisivos.** Como robots.txt se aplica en modo de fallo
  cerrado (si no puede confirmarse, la URL no se descarga), el corpus sobrerrepresenta los sitios que *permiten* el rastreo e
  infrarrepresenta estructuralmente el periodismo de pago o que restringe el rastreo. Esto no se
  puede «arreglar» de forma ética: se mitiga dando preferencia a las API y archivos oficiales, y
  se advierte aquí para que lea la cobertura en consecuencia.
- **Su registro empieza cuando empezó a recopilar.** Las tendencias y las señales «en ascenso»
  están limitadas por su ventana de recopilación; la herramienta no tiene historial anterior a su
  comienzo. Los volcados de Wikipedia y (en el futuro) los archivos amplían el pasado; por lo
  demás, lea los resultados de un corpus joven con las advertencias de n mostrada.
- **Wikipedia arrastra sus propios sesgos sistémicos.** La Wikipedia vigilada o ingerida importa
  los sesgos editoriales y de cobertura, bien documentados, de cada edición. Las fuentes por
  edición (`xx.wikipedia.org`) permiten filtrarla, y puede triangularse como cualquier otra
  fuente: nunca es un oráculo.
- **El sesgo de selección del catálogo se mide, no se oculta.** El catálogo de fuentes es un
  conjunto seleccionado por personas y en proceso de dejar de centrarse en EE. UU.; la vista
  **Cobertura mundial** muestra qué países están y cuáles no están representados, para que vea la
  forma de lo que está (y no está) recopilando.

---

## 6. Solución de problemas

- **La página no carga.** Compruebe que el proceso está en marcha y escuchando en
  `127.0.0.1:8000` (o en su `OO_HOST`/`OO_PORT`). El indicador de estado de la cabecera pasa a
  `offline` si la API no está accesible.
- **La búsqueda está vacía.** Todavía no ha recopilado nada: **conéctese** con el botón de modo
  avión (una sola ventana de consentimiento) y la recopilación empieza automáticamente; la vía
  manual es **Ajustes → Avanzado → Recopilación → Obtener feed**.
- **Una ingesta no guardó nada.** Suele ser lo correcto y lo ético: la página puede estar
  bloqueada por `robots.txt` (en modo de fallo cerrado), limitada por frecuencia, ser un duplicado o no
  tener un cuerpo extraíble. El recuento del resultado le dice cuál es el caso.
- **Faltan controles de Perspectivas/Mercados o dan error.** El extra `[analysis]` no está
  instalado: vuelva a ejecutar `install.sh` (el extra de análisis se instala por defecto).
- **El indicador del LLM dice sin conexión.** Ollama no está en marcha o no es accesible;
  inícielo o defina `OLLAMA_BASE_URL`. Resumir/traducir devuelven un `503` claro cuando no está
  disponible.
- **La custodia muestra «solicitado, biblioteca no instalada».** Instale el extra `pqc` y/o
  `timestamping`; el estado efectivo cambiará en cuanto la biblioteca esté presente.
- **La restauración rechazó mi archivo / la vista previa no permite Aplicar.** Es así por
  diseño: debe ser una copia de seguridad auténtica de Open Omniscience, y **Aplicar (Apply)**
  sigue desactivado si falla la verificación preparada. Su corpus actual no se toca en ningún
  caso; la restauración solo *añade*, nunca reemplaza.
- **El volcado de Wikipedia es enorme.** `enwiki` ocupa decenas de GB. Use primero **Estimar
  tamaño (Estimate size)**; la mayoría de las ediciones son mucho más pequeñas, y no necesita un
  volcado para el seguimiento de cambios.

---

## 7. Glosario

- **Corpus**: su base de datos SQLite local de artículos reunidos.
- **Procedencia**: el origen almacenado de cada elemento (fuente, URL, URL canónica, hash del
  contenido, hora de obtención), que se usa para la deduplicación y la confianza.
- **FTS5**: la búsqueda de texto completo de SQLite, que hace posibles las consultas booleanas.
- **Obtención ética**: la vía única de obtención, que respeta robots.txt y limita la frecuencia.
- **Cadena de custodia**: registro solo de adición, encadenado por hashes y firmado, que prueba
  la integridad, la procedencia y la fecha de un elemento.
- **Paquete de evidencia**: una exportación firmada, con raíz de Merkle y verificable sin
  conexión, de los artículos seleccionados.
- **OpenTimestamps**: una forma de anclar un hash en Bitcoin como prueba independiente de que
  «existía a más tardar» en un bloque dado.
- **ML-DSA**: esquema de firma poscuántica FIPS-204 (usado en modo *híbrido* junto con Ed25519).
- **ORES**: el servicio de aprendizaje automático de Wikimedia que puntúa las ediciones según su
  daño potencial o buena fe.
- **PMI**: información mutua puntual; ordena con qué fuerza coaparecen dos términos más allá del
  azar (el «mapa mental» de Perspectivas).
- **VADER**: un evaluador de tono/sentimiento basado en un léxico (la vista de «encuadre» de
  Perspectivas).

---

*Véase también:* [QUICKSTART](QUICKSTART.md) · [CHAIN_OF_CUSTODY](USER_MANUAL.md) ·
[INSIGHTS](USER_MANUAL.md) · [MARKETS](USER_MANUAL.md) · [WIKIPEDIA](USER_MANUAL.md) ·
[DATABASE](ARCHITECTURE.md) · [API_DOCUMENTATION](ARCHITECTURE.md) ·
[SECURITY](SECURITY.md) · [PRODUCT_SYNTHESIS](DESIGN.md) ·
[OPEN_QUESTIONS](archive/roadmaps/DESIGN_MEMORY_pre-0.2.md).

*© 2026 Ideotion — creado para el periodismo de investigación, con honestidad. GPLv3.*

---

# Análisis detallado de las funciones

Referencia detallada de cada herramienta, reunida a partir de las antiguas guías por función. El recorrido de las partes 1–6 anteriores sigue siendo la orientación más rápida; esta parte es el detalle.

**En esta parte:**
- [El informe de Inicio: inteligencia en forma de «tarjetas» honestas](#el-informe-de-inicio-inteligencia-en-forma-de-tarjetas-honestas)
- [Integridad de las fuentes y antiamplificación](#integridad-de-las-fuentes-y-antiamplificación)
- [Anotaciones de fuentes compartidas: firmadas, portables y federadas por confianza](#anotaciones-de-fuentes-compartidas-firmadas-portables-y-federadas-por-confianza)
- [Perspectivas: análisis de palabras clave y entidades](#perspectivas-análisis-de-palabras-clave-y-entidades)
- [Seguimiento de cambios en Wikipedia](#seguimiento-de-cambios-en-wikipedia)
- [Derecho mundial: seguimiento de cambios en leyes, boletines oficiales y PI](#derecho-mundial-seguimiento-de-cambios-en-leyes-boletines-oficiales-y-pi)
- [Mercados: inteligencia financiera, bursátil y de materias primas/tierras raras](#mercados-información-financiera-bursátil-y-de-materias-primastierras-raras)
- [Cadena de custodia](#cadena-de-custodia)


---

## El informe de Inicio: inteligencia en forma de «tarjetas» honestas

> **Estado:** `0.06` Fase A (la columna vertebral de la interfaz): publicada y probada. El plan por
> fases está en [`ROADMAP.md` → "0.06 — The Intelligence Layer"](archive/roadmaps/DESIGN_MEMORY_pre-0.2.md); el
> *qué y por qué*, en [`ROADMAP.md`](archive/roadmaps/DESIGN_MEMORY_pre-0.2.md).

La pestaña **Inicio** ya no es solo un conjunto de estadísticas de un vistazo. Es un **canal de
triaje**: la aplicación recopila y mide en segundo plano y luego presenta *posibles noticias* como
**tarjetas, que en pantalla se muestran como «Pistas»** (este capítulo dice «tarjeta» para el
mecanismo interno; la etiqueta de la interfaz es «Pista»). La aplicación hace la recopilación;
**usted juzga**. Cada tarjeta es **una señal medible + los enlaces de evidencia + una
advertencia**, clasificada en una categoría editorial, y se presenta como una **tarjeta
reversible de dos caras** (anverso = la pista; reverso = advertencia + método + evidencia +
«Abrir el corpus»).

Una tarjeta **saca a la luz una señal; nunca emite un veredicto.** No hay «parcial», ni
«propaganda», ni «verdadero/falso», y, por diseño y *por imposición en el código*, **ninguna
puntuación compuesta de confianza** (véase «Garantías de honestidad» más abajo).

---

### Lo que ve

El informe agrupa las tarjetas en **categorías** (en orden de presentación):

| Categoría | Significa | Uso editorial |
|---|---|---|
| **En ascenso** | algo se mueve / es nuevo | candidatas a pista |
| **Sobrecontado** | las fuentes coinciden demasiado rápido / de forma demasiado uniforme | desmontar el coro |
| **Infracontado** | algo se movió pero poco o nadie lo cubrió | sacar a la luz el vacío |
| **Merece investigación** | las fuentes o los datos discrepan | profundizar |
| **Revisar el encuadre** | el mismo hecho encuadrado de formas opuestas | verificar la afirmación |
| **Seguir observando** | un cambio que merece atención (p. ej., un registro remodelado) | vigilar |
| **Contexto** | antecedentes / autoauditoría / hechos permanentes | contextualizar |
| **Integridad de datos** | señales de higiene sobre el propio corpus | corregir el flujo de datos |

La tríada que las sustenta es el motor: **convergencia → sobrecontado**, **divergencia →
investigar/desmentir**, **ausencia → infracontado**.

Cada Pista (el nombre en pantalla de una tarjeta del informe) muestra en su **anverso** su
**título**, un **resumen** de una línea y la **señal medida** (p. ej., `growth_ratio = 4.2`,
`n=6`). **Haga clic en ella (o pulse Enter) para darle la vuelta:** el **reverso** contiene la
**advertencia**, el **método** (exactamente cómo se calculó la cifra y lo que *no* significa), por
qué se activó, los **enlaces de evidencia** que remiten a su corpus y un botón **«Abrir el corpus
↗»**. La advertencia está en el DOM por defecto, en la cara del reverso, de igual rango, justo al
lado de la acción, nunca detrás de un interruptor de interfaz tranquila. Esa es la idea: **la
transparencia es la interfaz.**

> **Vista igualitaria.** En esta versión cada fuente se cuenta una vez y **ninguna fuente se
> desamplifica**. La capa de integridad de fuentes / antiamplificación (agrupar avalanchas
> coordinadas en actores únicos, ponderar por novedad) es la siguiente fase y está **guiada por
> el usuario**: la aplicación *propondrá* y usted *dispondrá*. Hasta entonces el informe es,
> honestamente, la vista bruta de trato igualitario.

---

### El ciclo tarjeta → borrador → boletín

El ciclo que da sentido a todo es visible desde el primer día:

1. En cualquier tarjeta, haga clic en **+ Añadir al borrador**.
2. Abra el panel **Borrador de boletín**; añada su propia nota a cada tarjeta fijada.
3. **Exportar a Markdown** (o **Copiar**). Cada afirmación sale **con sus enlaces a las fuentes,
   su método y su advertencia**: periodismo reproducible por diseño.

Para obtener una copia *firmada y a prueba de manipulaciones* de los artículos subyacentes,
exporte un **paquete de evidencia** desde **Evidencia y custodia**: los justificantes pueden
acompañar a su número.

---

### Cómo se producen las tarjetas (Briefing v0)

Cada tarjeta la crea un **productor**: una función `corpus → [Card]`. Los productores combinan
análisis que *ya devuelven cifras reales*: no se inventa nada. Un productor al que le faltan sus
datos de entrada o una dependencia opcional `[analysis]` **no devuelve nada y registra el
motivo** (degradación visible); nunca fabrica una tarjeta.

| Tarjeta | Categoría | Basada en | Estado |
|---|---|---|---|
| **«X» va en aumento** | en ascenso | `insights.trending` (cociente entre el periodo reciente y el anterior) | ya |
| **Encuadres divergentes** | revisar el encuadre | tono VADER por fuente de un término en tendencia | ya¹ |
| **Registro remodelado** | seguir observando | detección de ediciones grandes/marcadas en Wikipedia | ya |
| **Precio ↔ relato (Price ↔ narrative)** | contexto | correlación honesta con scipy (coef. + p + n) | ya¹ |
| **Datos obsoletos** | integridad de datos | `last_run_at` / `last_status` de la regla de extracción de mercados | ya |
| **Autoauditoría de la dieta informativa (Diet self-audit)** | contexto | `signals.concentration` (Gini + proporción de las 3 primeras sobre sus fuentes) | ya |
| **Cámara de eco** | sobrecontado | grafo de actores de `signals.coordination` (casi duplicados + sincronía + host) | nuevo |
| **Señal aislada** | infracontado | grupo de casi duplicados de una sola fuente que no tuvo eco | nuevo |
| **Capacidad inverosímil (Capacity implausible)** | investigar | artículos/día frente a la mediana del corpus | nuevo |
| **Perfil emocional** | contexto | léxico de emociones sobre las ventanas de contexto de una palabra clave | nuevo² |
| **Pulso de PI / jurídico (IP / legal pulse)** | contexto | términos de PI/jurídicos en alza en el corpus de noticias | incipiente |
| **Cambio de propiedad** | investigar | lenguaje de operaciones (adquirido/fusión/desinversión) en noticias recientes | incipiente |
| **Linaje de una noticia** | contexto | `signals.lineage`: un grupo de casi duplicados ordenado por hora de publicación + atribución a agencia | nuevo |
| **Asesor de cobertura** | contexto | `signals.concentration` sobre el país/idioma de sus fuentes (sesgo, no un tope) | nuevo |
| **Comprobación meteorológica disponible (Weather check available)** | investigar | `analytics.corroboration`: términos de fenómenos climáticos × lugares deducidos × fechas de los artículos | nuevo |

¹ Necesita el extra `[analysis]` (VADER / scipy). Sin él, esas tarjetas simplemente no
aparecen; el resto del informe sigue funcionando.
² Usa un léxico de emociones; se incluye una **muestra** mínima en inglés; apunte
`OO_EMOTION_LEXICON` a un léxico JSON más completo para un uso serio (solo inglés).

Las tarjetas de **cámara de eco**, **señal aislada** y **capacidad inverosímil** proceden de la
capa de integridad de fuentes: véase [`USER_MANUAL.md`](USER_MANUAL.md). Las tarjetas de cámara de
eco incluyen una acción *Agrupar en un solo actor* (antiamplificación guiada por el usuario:
propone → usted dispone).

La **autoauditoría de la dieta informativa** usa la primera primitiva pura del sustrato compartido
[`src/signals/`](../src/signals/): la **concentración** (coeficiente de Gini + proporción de las
N primeras). Son *las mismas matemáticas* previstas para la concentración de la propiedad de los
medios (FUTURE_DEVELOPMENTS §1) y la prominencia de personas (§4): un solo motor, muchos ámbitos.

El **linaje de una noticia** rastrea una noticia replicada hasta su **fuente primaria**: para un
grupo de casi duplicados en muchos medios, ordena las piezas por hora de publicación y detecta la
**atribución a agencia** explícita («según Reuters», «(AFP)»), de modo que la información original
quede en primer plano frente a los ecos derivados. El límite es honesto: *«lo más temprano que
vimos» ≠ «la verdad»*; saca a la luz la estructura y la persona juzga. El **asesor de cobertura**
pone de relieve el **sesgo geográfico/lingüístico de su propia colección** (p. ej., «~80% de lo
que ha recopilado procede de un solo país») como una sugerencia amable para ampliarla: nunca
filtra ni limita nada; un corpus sesgado sesga todas las señales derivadas, así que ver el sesgo
es precisamente lo que importa.

La **comprobación meteorológica disponible** es la primera tarjeta de tipo *si ocurre esto,
sugerir aquello*: cuando varios de sus artículos mencionan la misma palabra de fenómeno climático
(sequía, inundación, ola de calor…, una lista inicial seleccionada en 12 idiomas,
`configs/corroboration_rules.yml`) junto con el mismo lugar deducido dentro de una misma ventana
temporal, la tarjeta **ofrece** obtener datos meteorológicos independientes exactamente para ese
lugar y esa ventana. La tarjeta en sí se calcula localmente (y lo dice), y no se obtiene nada
hasta que hace clic en **Obtener el contexto meteorológico**, que pasa por la misma ventana de
consentimiento de red que cualquier otra acción en línea. Lo que se recibe es un fragmento acotado
de **reanálisis** de Open-Meteo (CC BY 4.0, con la atribución visible): una *estimación de un
modelo*, no el registro de una estación; puede **corroborar o cuestionar** lo que dicen los
artículos, nunca probarlo. El fragmento se guarda en caché en el disco, de modo que volver a
leerlo después no requiere conexión; el estado de la caché y la hora de obtención se muestran
siempre.

---

### Rendimiento: precalcular, guardar en caché, servir desde la caché

El informe **nunca se calcula en cada solicitud**. El planificador en segundo plano lo actualiza
después de cada rastreo y escribe una caché (`briefing_cache.json` en su directorio de datos);
Inicio lee la caché y carga al instante. Se **actualiza solo**: se recalcula en segundo plano
después de cada pasada e Inicio vuelve a consultarlo por su cuenta (se muestra un aviso de
progreso mientras se actualiza); no hay botón manual de Actualizar. Los descartes
(`briefing_dismissed.json`) y el borrador (`briefing_draft.json`) son pequeños archivos JSON
locales: de un solo usuario, local primero, nunca se transmiten.

---

### Garantías de honestidad (en el código, no solo en la documentación)

FUTURE_DEVELOPMENTS §6 prohíbe una puntuación automatizada única de confianza/calidad (incrusta la
visión del mundo de quien puntúa en una cifra falsamente objetiva y *acabará* clasificando mal a
fuentes pequeñas, extranjeras, nuevas o disidentes). Esa prohibición se impone de forma
**mecánica**:

- `src/briefing/card.py:assert_no_score_fields()` rechaza cualquier campo de `Card` cuyo nombre
  sugiera una puntuación compuesta (`score`, `trust_score`, `credibility`, `rating`,
  `verdict`, …). Se ejecuta al importar y una prueba verifica que se cumple.
- El valor numérico que lleva una tarjeta está en `signal` como **una sola magnitud medida con un
  método declarado** (un cociente de crecimiento, un valor de Gini, un coeficiente de
  correlación), nunca una puntuación mezclada a partir de dimensiones inconmensurables.
- **Mostrar, no suprimir.** Descartar es reversible; cualquier futura reducción de peso será
  transparente, ajustable, desactivada por defecto y reversible.

---

### API

Todo bajo `/api/briefing` (solo loopback, como el resto de la aplicación):

| Método y ruta | Finalidad |
|---|---|
| `GET /api/briefing` | el canal en caché, agrupado por categoría (`?force=true` para recalcular) |
| `POST /api/briefing/refresh` | recalcular ahora |
| `POST /api/briefing/dismiss` · `/restore` · `/dismissed/clear` | gestionar los descartes |
| `GET /api/briefing/draft` | el borrador actual (tarjetas fijadas + notas + título) |
| `POST /api/briefing/draft/add` · `DELETE /api/briefing/draft/{id}` | fijar / desfijar una tarjeta |
| `PUT /api/briefing/draft/note` · `/title` · `POST /draft/clear` | editar el borrador |
| `GET /api/briefing/draft/export.md` | el Markdown que lleva la evidencia |

---

### Hoja de ruta (estado)

Las fases A–D están publicadas: la columna vertebral de tarjetas e informe (A), el sustrato
completo `src/signals/` (concentración, casi duplicados/coordinación, novedad) (B), el perfil de
integridad de fuentes + la antiamplificación guiada por el usuario (C, véase
[`USER_MANUAL.md`](USER_MANUAL.md)) y los paquetes de anotaciones firmadas de origen colaborativo
(D, véase [`USER_MANUAL.md`](USER_MANUAL.md)). La fase E publica las verticales componibles como
tarjetas (emoción, noticias de PI/jurídicas); las **verticales de seguimiento de cambios en
fuentes primarias de derecho y PI** (ingiriendo `legislation.gov.uk`, EUR-Lex, patentes/registros
de causas) siguen siendo el siguiente paso documentado: reutilizan los motores existentes de
seguimiento de cambios y de casi duplicados/correlación, pero requieren fuentes externas en vivo.
Véanse las fases B–E de [`ROADMAP.md`](archive/roadmaps/DESIGN_MEMORY_pre-0.2.md).


---

## Integridad de las fuentes y antiamplificación

> **Estado:** `0.06` Fase C: publicada y probada. La piedra angular de la capa de inteligencia
> (FUTURE_DEVELOPMENTS §6). Se complementa con [`USER_MANUAL.md`](USER_MANUAL.md) y
> [`USER_MANUAL.md`](USER_MANUAL.md).

Las demás herramientas sacan a la luz señales; **esta decide qué señal cuenta**, *sin convertirse
en árbitro de la verdad*. Es la respuesta al problema de «si entra basura, sale basura».

### La sorpresa: tratar a todas las fuentes por igual **no** es neutral

Las tendencias, la prominencia, la sincronía y «lo que se cubre» **cuentan medios y volumen**. Así
que el trato igualitario a los medios, aplicado a una métrica de volumen, lleva incorporado un
sesgo: *gana quien más produce.* Un actor con muchos recursos que pone en marcha 40 medios (o
granjas de trolls, o fábricas de contenido) convierte capital directamente en un consenso aparente
y **diluye** hasta la nada las noticias honestas de una sola fuente. No hacer nada no es neutral:
subvenciona a quien inunda.

La solución no es *puntuar* las fuentes. Es definir la neutralidad sobre la **unidad** correcta:
trato igualitario a los *actores independientes ponderados por la información nueva que aportan*,
no a los *medios*. **Contar cuentas títere como voces es un error de medición, no neutralidad.**

### Qué se mide (y qué está prohibido)

Nos situamos estrictamente en la mitad **permitida** de la distinción del §6:

- **(A) Puntuación de veracidad / calidad** («¿es esta fuente veraz / buena?»): **prohibido
  automatizarla.** Incrusta la visión del mundo de quien puntúa en una cifra falsamente objetiva y
  *acabará* puntuando a la baja también a una fuente buena pero poco habitual.
- **(B) Señales de autenticidad / estructura** («¿es esta fuente lo que dice ser? ¿un nodo de una
  red coordinada? ¿*origina* o solo *hace eco*? ¿su producción está dentro de la capacidad humana?
  ¿es transparente sobre quién la dirige?»): estos son, en buena medida, **hechos estructurales
  medibles.** Todo el diseño se sitúa aquí.

#### El motor compartido (`src/signals/`)

| Primitiva | Mide | Sustenta |
|---|---|---|
| `concentration` | Gini + proporción de las N primeras | concentración de la propiedad/de la dieta informativa, prominencia |
| `near_dup` | grupos de casi duplicados con MinHash + LSH | detección de eco / sindicación |
| `coordination` | grafo de actores a partir de casi duplicados + sincronía al unísono + host compartido | agrupación de actores |
| `novelty` | proporción de secuencias de palabras nuevas para el corpus | ponderación de quién origina frente a quién hace eco |

Las cuatro son **puras** (sin BD, sin red), están probadas con pruebas de propiedades y llevan
método + advertencia.

### La antiamplificación está **guiada por el usuario** (propone → usted dispone)

La antiamplificación **nunca** es una transformación silenciosa que la aplicación realiza y que
usted se limita a *deshacer*: eso convertiría a la aplicación en el árbitro que el §6 prohíbe.

- **Por defecto = «igualitario pero consciente».** La vista bruta de trato igualitario es la
  referencia; una avalancha coordinada se **anota sobre ella** (la tarjeta de *cámara de eco*), no
  se agrupa.
- **Usted aplica una agrupación**, por grupo o de forma global. Solo entonces una red coordinada se
  reduce a **una sola voz** en cualquier recuento que mida consenso (cuántas voces independientes
  transmiten una noticia).
- **Toda agrupación aplicada queda marcada y es reversible.** Un clic la despliega en sus
  miembros; revertirla reproduce **exactamente** los recuentos igualitarios brutos. *Nunca se
  aplica una agrupación sin una acción explícita suya*, algo que impone una prueba.

Este es el **panel de integridad de fuentes** (Ajustes → Avanzado → Seguridad → «Abrir el panel de
integridad de fuentes»): *Buscar coordinación* enumera los actores propuestos con su evidencia
(texto compartido, sincronía al unísono, host compartido); *Aplicar agrupación* / *Expandir
(revertir)* son decisión suya. Las Pistas de cámara de eco de Inicio incluyen la misma acción
*Agrupar en un solo actor*.

### El perfil de la fuente: dimensiones medidas, **sin puntuación compuesta**

Por cada fuente, un panel de señales *medidas* y, **deliberadamente, ninguna cifra única de
confianza** (la «B» prohibida). Una puntuación de 0 a 100 es una falsa precisión sobre dimensiones
inconmensurables, manipulable según la ley de Goodhart, un punto único de captura, y *acabará*
clasificando mal a fuentes pequeñas / extranjeras / nuevas / disidentes. La prohibición se impone
en el código (el perfil devuelve `no_composite_score: true` y una prueba verifica que no haya
ninguna clave agregada `*score*`).

Dimensiones (cada una con su propio método + advertencia):

- **Coordinación**: pertenencia a un actor, con quién y cuántas noticias compartidas.
- **Novedad**: ¿esta fuente origina o sobre todo hace eco? (en relación con *su* corpus).
- **Capacidad de producción**: artículos/día frente a la mediana del corpus (una *pregunta*, no un
  veredicto; las agencias de noticias y las grandes redacciones son legítimamente prolíficas).
- **Transparencia**: país, idioma, etiquetas de propiedad/orientación (reputacionales,
  discutibles, editables) y el `reliability_score` que fija el operador (no se calcula aquí).
- **Historial**: lo que esta fuente ha aportado a su corpus.

Usted decide qué dimensiones pesan en *su* vista: desactivado por defecto, reversible, con la
vista igualitaria bruta siempre a un clic.

### Nuevas tarjetas del informe procedentes de esta capa

- **Cámara de eco** (sobrecontado): una noticia transmitida por N fuentes coordinadas.
- **Señal aislada** (infracontado): una noticia sustancial de una sola fuente que no tuvo eco.
- **Capacidad inverosímil** (investigar): una fuente que publica muy por encima de la norma del
  corpus.

### API

| Método y ruta | Finalidad |
|---|---|
| `GET /api/integrity/profile?source=` | el panel de señales medidas sin puntuación compuesta |
| `GET /api/integrity/actors` | actores coordinados propuestos, cada uno marcado como aplicado/no aplicado |
| `GET /api/integrity/prominence` | prominencia de una noticia en voces independientes, bruta frente a agrupada |
| `POST /api/integrity/collapse/apply` · `/revert` | aplicar / deshacer una agrupación (por actor) |
| `POST /api/integrity/collapse/apply_all` · `/revert_all` | agrupar / restablecer globalmente |

### Límites honestos (con nombre)

- **Carrera armamentística / Goodhart**: toda señal publicada es un objetivo de optimización; esto
  es defensa en profundidad, nunca una pretensión de exhaustividad.
- **Las fusiones erróneas perjudican a inocentes**: la detección es de alta precisión, sesgada
  hacia agrupar *de menos*, siempre muestra la evidencia y siempre es reversible.
- **Captura**: publicamos *mecanismos, no veredictos*; lo predeterminado es la vista igualitaria
  transparente; usted puede anularlo todo.
- **El objetivo** no es «detectar toda la basura» (imposible, y afirmarlo sería lo deshonesto),
  sino **quitarle a la basura su ventaja mecánica** para que la jugada de las 40 agencias *deje de
  compensar*.


---

## Anotaciones de fuentes compartidas: firmadas, portables y federadas por confianza

> **Estado:** `0.06` Fase D: publicada y probada. La respuesta a escala para el perfil de la
> fuente (FUTURE_DEVELOPMENTS §6). Se complementa con [`USER_MANUAL.md`](USER_MANUAL.md).

El perfil de la fuente le permite a *usted* decidir qué dimensiones pesan. Pero **nadie puede
evaluar de forma neutral miles de fuentes en solitario**, así que la ponderación debe ser
**colectiva**. La manera honesta, local primero y no centralizada de hacerlo son los **paquetes de
anotaciones firmados y compartibles**.

- Usted publica sus anotaciones de fuentes (etiquetas de coordinación, hechos de
  propiedad/transparencia, etiquetas de orientación, correcciones, notas) como un **paquete firmado
  con custodia, verificable y portable** (reutilizando el mismo firmante híbrido Ed25519 + ML-DSA
  de la cadena de custodia: *mutualización*, no una segunda pila criptográfica).
- Otros usuarios **importan** los paquetes en los que deciden confiar: una **red de confianza**
  voluntaria, **nunca** una autoridad central.
- La agregación es **transparente**: siempre ve *quién afirmó qué*, y **la discrepancia se muestra,
  no se promedia** en una cifra oculta.

Sin servidor, sin cuentas, sin puntuación global: **federación mediante intercambio firmado.**

### Qué es (y qué no es) una anotación

Una anotación es un **hecho o etiqueta descriptivo y discutible** sobre una fuente. Tipos:
`ownership`, `leaning`, `coordination-tag`, `transparency-fact`, `correction`, `note`.
**Nunca** es una puntuación compuesta de confianza/calidad: eso está prohibido, por diseño y en el
código (un tipo no válido como `trust-score` se rechaza).

### Modelo de confianza: lo que una firma prueba y lo que no

Cada paquete incorpora la **identidad pública** del autor y una firma sobre el manifiesto
canónico. La verificación **fija** la clave incorporada, de modo que un ataque de manipular y
volver a firmar no puede *suplantar* al autor original: solo produce un autor **distinto**. Por
tanto, un paquete verificado siempre se atribuye fielmente a la clave que lo firmó, sea cual sea.
Después usted decide *en qué claves confiar*; solo se agregan las anotaciones de los autores de
confianza.

Esto es **red de confianza, no prueba de exactitud**: confiar en un autor significa «quiero ver
sus afirmaciones», no «sus afirmaciones son ciertas». La discrepancia entre autores de confianza se
le presenta para que usted juzgue; nunca se resuelve por usted.

### Cómo usarlo (el panel de integridad de fuentes: Ajustes → Avanzado → Seguridad)

1. **Redacte** anotaciones (objetivo + tipo + valor) en *Anotaciones compartidas*.
2. **Exportar paquete firmado** → un archivo JSON que puede publicar o compartir.
3. **Importar paquete…** → la aplicación **verifica la firma** antes de almacenarlo (un paquete no
   válido se rechaza, de forma visible) y luego muestra al autor en *Autores de confianza* con un
   interruptor de confianza.
4. **¿Quién dijo qué?** → reúne todas las afirmaciones sobre una fuente, suyas y de los autores de
   confianza, con las atribuciones y las discrepancias visibles.

Retirar la confianza a un autor excluye sus anotaciones; eliminarlo las borra limpiamente.

### API

| Método y ruta | Finalidad |
|---|---|
| `GET /api/annotations/mine` · `POST` · `DELETE /mine/{i}` | las anotaciones redactadas por usted |
| `POST /api/annotations/export` | un paquete firmado y portable con sus anotaciones |
| `POST /api/annotations/import` | verificar + almacenar un paquete importado (se rechaza si no es válido) |
| `GET /api/annotations/authors` · `PUT /authors/trust` · `DELETE /authors/{id}` | la red de confianza |
| `GET /api/annotations/for?target=` | agregación transparente: quién afirmó qué |

### Restricciones de honestidad

- **Sin promedios, sin cifra de consenso, sin puntuación.** La agregación devuelve afirmaciones
  atribuidas y nombra la *discrepancia*; nunca reduce el desacuerdo a una cifra.
- **Local primero.** Todo es un archivo en su directorio de datos; nada se transmite y no hay
  servidor ni cuenta.
- **Discutible por construcción.** Cada anotación es una etiqueta o un hecho sobre el que usted y
  otros pueden discrepar, de forma visible.


---

## Perspectivas: análisis de palabras clave y entidades

### Propósito

Convertir el corpus unificado, de un simple cuadro de búsqueda, en un instrumento de análisis. Las
palabras clave y las entidades se extraen del **texto de los artículos ingeridos**, se almacenan
con sus apariciones y su contexto, y se presentan para que un periodista de investigación pueda
preguntar: *¿de qué se habla, dónde, cuándo, quién lo dice y junto con qué?*

Todo lo que hay aquí es un **agregado real** sobre datos almacenados, con un método y un tamaño de
muestra declarados: nunca una puntuación fabricada (PRODUCT_SYNTHESIS §3.5).

### Cómo funciona

```
ingest an article ──► extract (baseline / opt-in spaCy) ──► KeywordMention rows
                          terms + entities, offsets        (count + first offset +
                                                            denormalised date/country/city)
                                                                   │
                          Insights tab / /api/insights  ◄──────────┘
                          trends · associations (PMI) · context · map
```

- **Extracción** (`src/analytics/extract.py`): **términos** temáticos en n-gramas (filtrados de
  palabras vacías) más **entidades** (personas, empresas/organizaciones, lugares) como unidades
  únicas. El extractor básico (sin dependencias) detecta las entidades como secuencias de varias
  palabras con Mayúscula Inicial y asigna un tipo `person`/`org`/`location` solo a partir de un
  nomenclátor (si no, el honesto genérico `entity`); un extra opcional **spaCy** `[nlp]` añade
  reconocimiento real de entidades `PERSON`/`ORG`/`GPE`. Cada palabra clave registra **qué
  extractor la etiquetó**: un tipo de entidad es una *afirmación etiquetada por X*, no una verdad
  de referencia. Funciona mejor con escrituras delimitadas por espacios; la segmentación de
  CJK/árabe es un paso posterior conocido.
- **Almacenamiento** (`src/analytics/store.py`): un `KeywordMention` por (artículo, palabra
  clave): número de apariciones + posición del primer carácter (la frase de contexto se extrae del
  artículo almacenado al leerlo, para que la BD siga siendo ligera) + `observed_on` / `country` /
  `city` desnormalizados a partir de la fuente. La indexación se ejecuta en la ingesta en la medida
  de lo posible (extractor básico rápido, sin bloquear si falla). La indexación es **automática**:
  cualquier atraso se resuelve con una puesta al día silenciosa en segundo plano cuando abre
  Perspectivas (el recuento de «pendientes» baja a 0 por sí solo); no hay botón «Indexar corpus
  (Index corpus)». Una reindexación completa del corpus existente está disponible en **Ajustes →
  Avanzado → Diagnóstico** («Reindexar todo el corpus» / «Limpiar palabras clave») como tarea en
  segundo plano que se puede pausar.

### Funciones (pestaña Perspectivas + `/api/insights`)

| Vista | Endpoint | Qué muestra |
|------|----------|---------------|
| Explorar — tendencia | `GET /trend?term=&bucket=` | Volumen de menciones a lo largo del tiempo (día/semana/mes), con la palabra clave resuelta + su tipo |
| Explorar — mapa mental | `GET /associations?term=` | Palabras clave que coaparecen, ordenadas por **PMI** (información mutua puntual), con tamaños de muestra + una advertencia de «asociación ≠ causalidad»; haga clic en un nodo para recentrar |
| Explorar — contexto | `GET /context?term=` | Fragmentos de menciones recientes extraídos del texto de los artículos, con enlaces al artículo/fuente + país/ciudad/fecha |
| Tendencias | `GET /trending`, `GET /top` | Términos en ascenso (**cociente** reciente frente a anterior, una medida etiquetada) y términos principales, filtrables por ventana / tipo / país |
| Mapa | `GET /map?days=&kind=` | Palabras clave principales **por país y por ciudad** (señal regional basada en la fuente) |
| Indexación | `GET /status`, `POST /reindex?limit=` | Recuentos de indexados/pendientes; relleno del corpus por bloques |

Filtros de `kind`: `term`, `entity`, `person`, `org`, `location`.

### Garantías de honestidad

- Las tendencias y los términos principales son recuentos reales; «en ascenso» es un **cociente**
  definido entre periodo reciente y anterior, explícitamente *no* una prueba de significación.
- Las asociaciones usan **PMI** sobre la coaparición en artículos, y se devuelven con `n` y la
  advertencia de que las muestras pequeñas son ruidosas.
- Los tipos de entidad llevan la procedencia del extractor; el extractor básico nunca afirma un
  tipo preciso de persona/organización/lugar que no pueda justificar.
- La región en el mapa es el país/ciudad de la **fuente** (la señal fiable). La vista Mapa incluye
  ahora un **SVG equirrectangular interactivo** (zoom/desplazamiento, nombres de ciudades al
  ampliar) que sitúa las ciudades según su lat/lon real tomada de un **nomenclátor**: se incluye
  una pequeña muestra (`configs/cities.sample.yml`); el conjunto completo se genera a partir de
  Wikidata (`scripts/build_city_gazetteer.py` → `configs/cities.yml`). Una ciudad sin
  correspondencia en el nomenclátor conserva sus datos de palabras clave pero **no tiene posición
  en el mapa** (nunca una ubicación fabricada). Las tablas de países/ciudades siguen junto al mapa.


---

## Seguimiento de cambios en Wikipedia

### Propósito

Wikipedia es terreno disputado: los artículos se editan continuamente, y en la era de los LLM
eliminar o reescribir la historia es más fácil que nunca. Esta herramienta trata cada **edición
lingüística** de Wikipedia como una fuente seguida cuyas *ediciones* son los datos, para que un
periodista pueda **detectar y documentar** cambios a gran escala o revisionistas; por ejemplo,
probar que una frase existía en una fecha determinada y que una cuenta determinada la eliminó.

> Las ediciones son por **idioma** (`en`, `fr`, `ar`, `ru`, `zh`, …), no por país (no existe una
> Wikipedia nacional); la interfaz relaciona los idiomas con los países.

### Por qué esto no es una ingesta de «artículos normales»

Los artículos cambian con el tiempo, así que no pueden almacenarse como filas `Article` de una
sola vez. De ello se derivan dos decisiones de diseño:

1. **Usar la API Action de MediaWiki, no el rastreo de páginas**: `revisions`,
   `recentchanges` (con diferencias de bytes) y `compare` (diferencias calculadas por el
   servidor). Es la vía eficiente, respetuosa con las condiciones de uso y orientada a los cambios.
2. **Almacenar diferencias, no copias repetidas**: se guarda **una** versión de referencia
   comprimida del texto completo por página (`wiki_pages.baseline_text`); cada edición posterior es
   una fila de `wiki_revisions` que contiene **la diferencia + la variación de bytes con signo +
   marcas**, nunca el artículo nuevo completo. Cualquier versión histórica puede reconstruirse
   aplicando de nuevo las diferencias.

**Esto responde a la cuestión de la redundancia y el espacio en disco:** una edición cosmética es
una diferencia minúscula que lleva la marca `minor` de MediaWiki y se filtra con un umbral de
tamaño/edición menor, así que no cuesta casi nada. El almacenamiento crece con la **actividad de
edición en las páginas vigiladas**, no con el corpus de artículos de varios GB: nunca necesita el
volcado completo para el seguimiento.

### Detección de ediciones a gran escala o sospechosas (con honestidad)

`src/wiki/flagging.py` marca una edición y registra **códigos de motivo**: saca a la luz
*candidatas*, no declara «desinformación»:

- `large_removal` / `large_addition`: variación de bytes por encima de un umbral
- `revert` / `blank`: etiquetas de cambio de MediaWiki (`mw-reverted`, `mw-undo`, `mw-blank`…)
- `anon_large`: una edición mediana o mayor desde una IP anónima
- `burst`: muchas ediciones a una misma página en un intervalo corto
- `ores_damaging`: probabilidad opcional de «dañina» según **ORES de Wikimedia**, presentada como
  una afirmación *etiquetada por ORES* (como nuestra procedencia de entidades)

Las ediciones cosméticas menores nunca se marcan. Cada edición marcada se documenta con su
diferencia + procedencia (revid, editor, marca de tiempo), lo que se conecta con la **cadena de
custodia** existente para obtener evidencia firmada y con sello de tiempo.

### Dos subsistemas claramente separados (experiencia de usuario)

1. **Vigilar y seguir** (ligero, inmediato, el predeterminado): una lista de seguimiento de
   páginas / categorías por edición lingüística; consulta las revisiones con el planificador
   integrado; almacena revisiones + diferencias + marcas; un visor de diferencias + una cronología
   por página. Sin descarga masiva.
2. **Base de referencia sin conexión** (pesada, opcional): está en **Ajustes → Bases de referencia
   sin conexión de Wikipedia** (deliberadamente apartada del seguimiento ligero). Una **lista
   seleccionable de ediciones lingüísticas** (seleccionada, de mayor a menor, con el nombre propio
   de cada idioma y un nivel de tamaño aproximado) sustituye la introducción de códigos en texto
   libre; el tamaño exacto actual del volcado se lee del servidor cuando se pide (`Estimate size`),
   y después se puede descargar / pausar / reanudar / eliminar. La lista procede de
   `GET /api/wiki/languages`; el descargador sigue aceptando cualquier código de edición. (Tamaño
   real: el texto actual de enwiki ocupa ≈ 22 GB comprimido; el historial completo ocupa
   terabytes, y solo hace falta para diferencias históricas sin conexión.)

### Estado

- **Hecho:** esquema (`wiki_pages`, `wiki_revisions`; migración `d4e5f6a7b8c9`); el analizador de
  la API de MediaWiki + el cliente en vivo (`mediawiki.py`, `client.py`); la lógica de marcado de
  ediciones (`flagging.py`); el cliente de ORES (`ores.py`); el orquestador de seguimiento
  (`track.py`, almacenamiento de base de referencia + diferencias); el modo `wiki` del
  planificador; la **API** (`/api/wiki/*`) y **Ajustes → Wikipedia** (lista de seguimiento,
  seguir ahora, canal de cambios marcados, visor de diferencias); el **descargador de bases de
  referencia sin conexión** (`dumps.py`: por idioma, reanudable, con sondeo de tamaño), ahora
  controlado por un **selector de idioma** (`languages.py`, `GET /api/wiki/languages`) trasladado
  a **Ajustes → Bases de referencia sin conexión de Wikipedia**. Toda la lógica pura y la
  orquestación tienen pruebas unitarias con datos de prueba (sin red).
- **Siguiente:** enlazar las diferencias de wiki con el análisis de palabras clave de
  Perspectivas; flujo opcional completo de EventStreams; exportación como evidencia de una
  diferencia marcada mediante la cadena de custodia.

### Ética

Toda obtención respeta la política de uso de la API de MediaWiki (User-Agent identificativo,
`maxlag`, límites de frecuencia), lo que es más considerado que el rastreo de páginas. Solo
almacenamos datos públicos de revisiones; no se obtiene nada hasta que se ejecuta el seguimiento.


---

## Derecho mundial: seguimiento de cambios en leyes, boletines oficiales y PI

> **Estado:** `0.06` Fase E: publicada. La vertical del §5: una «Wikipedia del derecho».
> Reutiliza el motor de seguimiento de cambios (`src/wiki`) y los motores compartidos de
> `src/signals/`.

Reunir el **derecho** (leyes, legislación, boletines oficiales, registros de PI) a partir de
fuentes oficiales de todo el mundo, y **seguir cómo cambia con el tiempo**. El derecho es público en
muchos países y cambia mediante enmiendas, así que los datos *son la diferencia*: qué cambió y
cuándo.

### Activado por defecto: un catálogo mundial de fuentes oficiales reales

`configs/legal_sources.yml` incluye un conjunto seleccionado y mundial de **fuentes primarias
oficiales reales**: bases de datos legislativas nacionales (`legislation.gov.uk`, EUR-Lex,
Légifrance, `gesetze-im-internet.de`, `congress.gov`/`govinfo.gov`, `legislation.gov.au`,
`indiacode.nic.in`, `elaws.e-gov.go.jp`, `law.go.kr`, …), boletines oficiales, oficinas de PI
(WIPO Lex, USPTO, EPO, EUIPO, JPO, …) y sistemas abiertos de jurisprudencia y de presentación de
documentos (CourtListener, SEC EDGAR). En el primer arranque se cargan como fuentes ordinarias
**ingeribles y consultables** (`source_type` legal/ip), de modo que pasan por el *mismo* flujo
ético que las noticias.

Un subconjunto seleccionado de **documentos de derecho consolidado** estables y conocidos (p. ej.,
la Human Rights Act del Reino Unido, el RGPD de la UE, la Constitución de EE. UU.) viene
registrado de serie para el **seguimiento de cambios**.

### Cómo funciona el seguimiento (reutiliza el motor de Wikipedia)

Para cada documento seguido, la primera obtención correcta es la **base de referencia** inmutable
(«el derecho tal como estaba en la fecha X»). Cada obtención posterior cuyo *texto visible
normalizado* difiera registra una revisión con la variación de bytes, una **diferencia** unificada
y acotada respecto de la base de referencia, y una **marca de cambio grande** honesta (que
reutiliza los umbrales de marcado de la wiki). Ejecútelo desde la **pestaña Gobiernos → subpestaña
Derecho** («Rastrear cambios ahora») o con el planificador en segundo plano (modo `law`). Toda
obtención pasa por la vía **ética, con robots.txt en modo de fallo cerrado**.

### Leer una ley desde el XML del propio editor (fuentes estructuradas)

Una página web hay que *reconstruirla* como texto: quitar la navegación, el formulario de búsqueda,
el aviso de cookies, y confiar en que lo que queda sea la ley. Eso funciona, y es lo que hace el
rastreador con la mayoría de las fuentes, pero en una ocasión la copia almacenada de una ley del Reino Unido
empezaba con el propio formulario de búsqueda del portal, y todo lo que se derivó de ella (una "persona"
llamada "Personal Acts", una "organización" llamada "PART") procedía de un texto que nunca estuvo en la ley.

Cuando un editor sirve su **propio XML**, nada de eso ocurre: el archivo no contiene elementos de página,
porque el archivo no es una página. Open Omniscience puede leer directamente el CLML de
`legislation.gov.uk`, que además aporta dos cosas que una página no puede dar:

- **Disposiciones con direcciones citables.** Cada sección se lee junto con la ruta de Parte/Capítulo
  que la contiene, de modo que un cambio puede indicarse como *"cambió la sección 12 de la Parte 2"* y no
  como un recuento de bytes. Las secciones se emparejan por esa dirección y nunca por su posición;
  de lo contrario, insertar una sola sección haría aparecer todo el resto de la ley como modificado.
- **Fechas que significan lo que dicen.** La promulgación, el punto de consolidación y la fecha en que
  *nosotros* la descargamos son tres campos distintos, sin ningún relleno de uno a otro. Una fecha que el
  documento no indica se muestra como desconocida, nunca se completa a partir de otra. (Por eso una
  ley rastreada no muestra fecha de publicación salvo que el propio documento la proporcione: la única
  fecha disponible era el día en que consultamos la página, y una fecha de consulta no es una fecha
  de publicación.)

La comparación por secciones es **complementaria y experimental**: el diff de texto ordinario sigue
decidiendo si se registra una revisión y sigue llevando la marca de cambio importante. Y hay un
límite que se declara en lugar de disimularse: una sección que se *renumera y reescribe*
en la misma modificación se notifica como una supresión más una adición, porque emparejarla con
su versión anterior obligaría a adivinar cuál de dos secciones con números distintos es "la
misma, editada".

**Lo que todavía no existe:** nada descarga aún esos documentos XML automáticamente. Leer
el corpus jurídico completo de una jurisdicción supone recorrer la lista que publica el propio editor
(el Reino Unido enumera todas sus leyes; Francia enumera 76 códigos), y esa enumeración no está construida.
Mientras no lo esté, el conjunto rastreado sigue siendo el seleccionado, y el informe de cobertura indica
con honestidad "cobertura desconocida" en lugar de presentar un recuento de documentos rastreados como
si fuera el corpus entero.

### Comprobar que las correcciones de leyes llegaron a sus datos

Dos correcciones relativas a las leyes se aplican **en silencio, en la siguiente descarga correcta
de un documento**: los elementos de página se vuelven a leer a partir de una referencia almacenada, y se
borra una fecha de publicación que en realidad era una fecha de consulta. Ambas son correctas, y un
documento cuyo portal es inaccesible nunca se corrige, que es justamente el caso que conviene conocer.

El informe **law-ingest** (incluido en el paquete de todos los diagnósticos, o por separado) responde a
eso a partir de los datos almacenados, sin ninguna llamada de red: qué registró la última comprobación de
cada documento rastreado (un recuento por resultado, como sin cambios, releído, error o aplazado, y el
resultado y la hora del último intento de cada documento), y si algún artículo jurídico todavía lleva una
fecha de publicación que no debería tener. Un documento cuya última comprobación falló merece una
revisión, pero el informe no puede saber si se releyó alguna vez antes de empezar a fallar:
eso no se registra. El propio recuento de relecturas solo cuenta los documentos cuya consulta más
reciente fue la relectura, así que en una instalación donde todos los documentos se han corregido
tiende de nuevo hacia cero.

También informa de los **restos de elementos de página**: texto de navegación que sigue presente en un
cuerpo almacenado. Interprételo como una *medición*, no como un veredicto: la limpieza de elementos de
página elimina deliberadamente solo lo que el marcado declara como tal y deja el resto, porque una regla
basada en coincidencias de texto también borraría los títulos de sección de la propia ley. Es normal que
queden restos tras una relectura correcta; la cifra indica cuántos elementos de página no declarados hay
en su corpus, y la lista de marcadores es un mínimo, así que cero significa "ninguno de estos", nunca
"ningún elemento de página".

### Tarjetas de resumen a partir del corpus jurídico

- **Ley modificada** (Law changed) (vigilancia): un cambio marcado en un documento jurídico rastreado.
- **Legislación modelo** (investigar): texto jurídico casi idéntico en dos o más
  jurisdicciones (el motor de casi duplicados §1/§2), un patrón de difusión medible.

Además, como el texto jurídico forma parte del corpus unificado, la correlación **ley ↔ noticias** y la
analítica de palabras clave funcionan sobre él como con cualquier otra fuente.

### API

| Método y ruta | Finalidad |
|---|---|
| `GET /api/law/status` | cobertura: documentos por jurisdicción, totales de cambios/marcas |
| `GET /api/law/documents` | documentos rastreados (opcionalmente `?jurisdiction=`) |
| `GET /api/law/documents/{id}` | un documento con su historial de cambios (diffs) |
| `GET /api/law/changes` | cambios jurídicos recientes (marcados), del más nuevo al más antiguo |
| `POST /api/law/track` | descargar ahora todos los documentos vigilados (descargador ético) |
| `POST /api/law/seed` | (re)sembrar el catálogo mundial + registrar documentos |

### Límites de honestidad (lo jurídico tiene mucho en juego)

- **No es asesoramiento jurídico ni la fuente oficial.** La copia agregada es un
  *espejo de investigación*; cada registro enlaza con el boletín oficial, y la interfaz lo indica.
  Rastrear y mostrar; nunca interpretar la legalidad ni juzgar una ley.
- **"Público" ≠ "libremente redistribuible".** Las licencias varían incluso cuando el texto es público:
  cada una se respeta y se atribuye, con la procedencia almacenada y robots en modo de cierre ante fallos (como para las noticias).
- **Alcance honesto.** "Todos los países" es el horizonte, no la v1: el catálogo es amplio pero
  seleccionado, y el seguimiento de cambios se hace mediante diff de texto normalizado (los portales de texto consolidado dan
  la señal más limpia). Cuando un editor sirve XML estructurado, hay diffs por sección
  disponibles (véase más arriba): hoy CLML; Akoma Ntoso / ELI todavía no se leen. La herramienta indica
  cuál tiene para cada documento y se niega a adivinar: un documento que no puede analizar
  estructuralmente conserva el diff de texto en lugar de presentarse como si tuviera secciones.
- **La traducción** (mediante el LLM local) es una ayuda aparte, claramente etiquetada; nunca una
  traducción jurídica oficial.


---

## Mercados: información financiera, bursátil y de materias primas/tierras raras

Open Omniscience incluye un **catálogo mundial y seleccionado de fuentes de mercado**, de modo que
está listo para ingerir información sobre los mercados financieros desde el primer momento, y una pestaña **Materias primas** que
convierte páginas *configuradas* en una serie de precios real, representable en gráficos y correlacionada con las noticias.

Este documento explica qué viene incluido, qué no, y por qué, porque aquí
el límite honesto importa más que una larga lista de funciones.

### Qué viene incluido (listo para usar tal cual)

`configs/markets_sources.yml` se siembra automáticamente junto con el catálogo de noticias
(`configs/sources.yml`) en el primer inicio y mediante **Ajustes → Avanzado → Fuentes → Sembrar
fuentes iniciales**. Contiene unas ~110 entradas seleccionadas, identificadas por un dominio principal
estable:

- **Bolsas de valores** de todo el mundo (América, Europa, Asia-Pacífico,
  Oriente Medio, África): NYSE, Nasdaq, LSE, Euronext, Deutsche Börse, JPX, HKEX,
  SSE/SZSE, NSE/BSE India, SGX, ASX, B3, Tadawul, JSE y muchas más.
- **Bolsas de materias primas / metales / energía / derivados**: CME Group, ICE, LME,
  SHFE, DCE, ZCE, INE, **GFEX** (futuros de tierras raras y silicio industrial), MCX,
  Eurex, MGEX.
- **Fuentes de precios/datos de materias primas y tierras raras**: Shanghai Metals Market, Kitco,
  USGS, World Bank Pink Sheet, EIA, IEA, OPEC, Fastmarkets, Argus, Benchmark
  Mineral Intelligence, S&P Global Commodity Insights.
- **Editores de noticias y datos financieros**: Bloomberg, Reuters, FT, WSJ, CNBC,
  MarketWatch, Nikkei Asia, Caixin y otros.

Son **fuentes** ordinarias: alimentan el corpus unificado a través del mismo
descargador ético (robots.txt con cierre ante fallos, velocidad limitada). Cada una lleva un
`source_type` (`stock_exchange` / `commodity` / `financial`), región, país y
etiquetas, de modo que puede filtrarlas en **Ajustes → Avanzado → Fuentes** y asociarles reglas de precio en
**Materias primas**.

> Los feeds RSS se dejan en blanco a propósito para estas entradas (una URL de feed incorrecta
> solo genera ruido). Ingiéralas con el rastreador recursivo, o añada un feed RSS verificado
> para cada fuente desde **Ajustes → Avanzado → Fuentes**.

### Obtener cifras de precios reales

Solo se produce una serie de precios cuando usted le indica a la aplicación **exactamente dónde está la
cifra**: no hay lectura mágica de páginas, por diseño. Dos vías honestas:

#### 1. Reglas de extracción por página (pestaña Materias primas → "Configurar fuentes de datos")

*(Los feeds y las reglas de extracción se encuentran en una sección plegada, "Configurar fuentes de datos" (Configure data sources), de
la pestaña Materias primas; los propios feeds seleccionados se actualizan automáticamente en
segundo plano.)*

Añada una regla (fuente, símbolo, URL de la página, **selector CSS**, atributo /
expresión regular de valor opcionales, moneda, unidad) y pulse **Probar**. La prueba descarga la página una vez y
muestra el valor *exacto* encontrado, o el motivo *exacto* por el que no hubo coincidencia, para que pueda
ajustar el selector con información real. Las reglas que coinciden almacenan un `CommodityPrice`
por día, que leen los gráficos integrados y la correlación precio↔noticias.

Plantillas para copiar: `configs/market_rules.example.yml`.

**Advertencia (léala):** la mayoría de las páginas de bolsas y cotizaciones muestran los precios con JavaScript,
así que la cifra *no* está en el HTML estático que recibe el descargador y un selector no
encontrará nada. Por eso **no** se incluyen selectores que funcionen: adivinarlos
supondría cifras inventadas. Las páginas generadas en el servidor (muchos sitios oficiales/estadísticos,
algunas tablas de datos) funcionan bien; los widgets de cotización generados en el cliente, no.

#### 2. Feeds CSV oficiales (recomendado: fiable, incluye un catálogo)

Para un historial numérico fiable, importe una serie CSV legible por máquina de una
fuente oficial. Esta es la vía fiable, y la aplicación incluye un catálogo inicial
(`configs/commodity_feeds.yml`) que puede importar con un clic desde
**Materias primas → Configurar fuentes de datos → Fuentes de precios oficiales**, o mediante la API:

```
GET  /api/markets/feeds                # list curated feeds + how many points each has
POST /api/markets/feeds/{key}/import   # import one (e.g. copper, wti_crude, brent_crude)
POST /api/markets/feeds/import-url      # import ANY CSV URL you supply (user-customizable)
```

**Proveedor principal: FRED** (Banco de la Reserva Federal de St. Louis): un punto de acceso CSV estable,
sin clave de API, `https://fred.stlouisfed.org/graph/fredgraph.csv?id=<ID>`,
que **redistribuye las series de materias primas del "Pink Sheet" del Banco Mundial** (los
identificadores "Global price of …": cobre `PCOPPUSDM`, brent `POILBREUSDM`, etc.) y
las series energéticas de la **EIA** (`DCOILWTICO`, `DHHNGSP`, …). La primera columna es la fecha,
la segunda el valor; los valores ausentes (`.`) se omiten y nunca se almacenan como cero. La importación
es idempotente por `(symbol, market, date)`.

**Fuentes comparables** que puede añadir como feed personalizado (URL + nombres de columna opcionales):
- **Banco Mundial**, Commodity Markets ("Pink Sheet"): el `.xlsx` está en
  <https://www.worldbank.org/en/research/commodity-markets>; las mismas series en
  CSV limpio llegan a través de los feeds de FRED citados arriba.
- **EIA de EE. UU.**, datos abiertos de energía: <https://www.eia.gov/opendata/>
- **FMI**, precios de materias primas primarias: <https://www.imf.org/en/Research/commodity-prices>
- **USGS**, datos de materias primas minerales (tierras raras): <https://www.usgs.gov/centers/national-minerals-information-center>

La correspondencia de columnas por defecto es columna 1 = fecha, columna 2 = valor (la convención
de FRED); indique `date_column` / `value_column` explícitamente para otras disposiciones.

También existe una vía de carga directa de archivo para un CSV que ya tenga:

```
POST /api/commodities/{symbol}/prices/import-csv      (multipart file upload)
```

> Si un proveedor cambia el nombre de una serie o la retira, la importación falla **de forma visible** (error
> HTTP / ninguna fila utilizable) en lugar de inventar datos: corrija la URL en
> `configs/commodity_feeds.yml` o use un feed personalizado.

### ¿Por qué no hay precios extraídos automáticamente desde el primer día?

Porque una cifra sin origen verificable es peor que ninguna cifra. Todo en
esta herramienta está construido para que una cifra mostrada al usuario proceda de una
medición real: un selector que realmente coincidió, o un CSV que realmente se
importó. El catálogo le da las *fuentes* al instante; usted decide, página por página, cuándo
un precio es lo bastante fiable como para registrarlo.


---

## Cadena de custodia

Open Omniscience hace una afirmación probatoria deliberadamente *acotada y honesta*:

> **Este corpus contenía _este_ elemento, con _este_ contenido, registrado en _este_
> momento, y el registro no se ha alterado desde entonces; y aquí está la prueba
> criptográfica, que usted mismo puede comprobar, sin conexión, sin confiar en esta herramienta.**

Esto es realmente útil para un periodista de investigación: le protege frente a
"usted se lo inventó", "usted lo antedató" o "usted lo editó discretamente a
posteriori", y le permite demostrar que informó de algo *antes* de que una página fuente
se modificara o se borrara. **No** es un sistema de envío para denunciantes (como
SecureDrop), y una "fuente" en esta herramienta es un *medio de comunicación*, no una fuente humana
confidencial. Tenga en cuenta ese alcance al razonar sobre la protección.

Este documento describe los mecanismos reales (`src/custody/`, `src/reporting/`) y
explica de forma explícita lo que cada uno demuestra y lo que **no** demuestra.

---

### Las tres propiedades, y cómo obtenemos cada una con honestidad

| Propiedad | Mecanismo | Qué demuestra | Qué **no** demuestra |
|---|---|---|---|
| **Integridad** | Firmas Ed25519 (+ ML‑DSA opcional) sobre una serialización canónica; raíz de Merkle sobre todos los campos de procedencia | Los bytes no han cambiado desde la firma; todo queda cubierto, no solo el contenido | — |
| **Procedencia** | **Fijar** la clave pública conocida del firmante | El registro lo firmó *ese* firmante | Nada, si no fija una clave: una firma válida por sí sola solo significa "firmado por la clave incluida en el paquete" |
| **Tiempo** | `local` (autodeclarado) **u** OpenTimestamps (anclado en Bitcoin) | Local: una hora que afirma la herramienta. OTS: el contenido existía *a más tardar* en un bloque de Bitcoin | La hora local no demuestra nada a un tercero; OTS demuestra un *límite superior* de tiempo, no el momento exacto |

Nos negamos a falsear cualquiera de ellas. Si no se puede obtener una marca de tiempo real de un tercero
(sin conexión, o la biblioteca no está instalada), el código lanza un error en lugar de inventar una
hora, que es el modo de fallo que prohíbe la carta del proyecto (PRODUCT_SYNTHESIS §3.7).

---

### Componentes

#### 1. Paquetes de evidencia firmados — `src/reporting/evidence.py`
Una exportación en un momento dado de los artículos seleccionados, cada uno con su procedencia y un hash
del contenido, unidos por una **raíz de Merkle con separación de dominio** y una **firma Ed25519**.
Verifíquelos sin conexión con `scripts/verify_evidence.py <bundle.json> [signer_pubkey]`.
Expuesto en `POST /api/reports/evidence` y `/api/reports/evidence/verify`.

La clave de firma se guarda en `keys/evidence_ed25519.pem` dentro de su carpeta de datos. En un almacén
cifrado queda envuelta bajo su frase de contraseña (una clave creada antes se envuelve, sin cambios, la primera vez
que una exportación la carga con el almacén desbloqueado), de modo que una copia de la carpeta de datos por sí sola no puede firmar en
su nombre; sin frase de contraseña permanece en `0600` en claro. Si una copia de seguridad restaurada trajo una clave envuelta
bajo la frase de contraseña de otra instalación, una exportación de evidencia y todas las copias de seguridad (una copia de seguridad firma su manifiesto
con esta clave) indican que no pueden abrirla y no reemplazan nada: use la frase de contraseña bajo la que se envolvió,
o aparte el archivo para que se genere una clave nueva (los paquetes firmados con la clave antigua siguen verificándose con
su clave pública). Perder la frase de contraseña supone perder la clave; no hay recuperación.

#### 2. Firmas híbridas — `src/custody/signing.py`
Combina **Ed25519** (rápida, clásica) con **ML‑DSA** (FIPS 204, poscuántica,
la sucesora estandarizada de CRYSTALS‑Dilithium). Dos reglas hacen que esto sea honesto:

- **Etiquetas honestas.** Una firma se etiqueta como `hybrid` solo cuando realmente se usó una clave
  ML‑DSA. Sin el extra `pqc` instalado, la firma produce una firma `ed25519`
  y lo indica: nunca afirma una resistencia cuántica que no produjo.
- **Híbrido significa Y.** Una firma `hybrid` solo se verifica si **ambos** componentes
  se verifican. Un verificador que carece de la biblioteca poscuántica no puede comprobar la mitad
  ML‑DSA y por tanto **falla de forma visible**: nunca da por buena en silencio solo la mitad
  clásica. (Un esquema que acepta *cualquiera* de las dos firmas no vale nada en cuanto se rompe la
  clásica.)

Las claves privadas se cifran en reposo con AES‑256‑GCM bajo una clave derivada con scrypt
cuando la aplicación dispone de una frase de contraseña (`OO_KEY_PASSPHRASE`, o en su defecto la frase de contraseña
de la base de datos); en caso contrario se escriben en `0600` en claro y el nivel de protección
se indica con veracidad como `plaintext-0600`.

#### 3. Registro de custodia — `src/custody/log.py`
Un libro de registro SQLite de **solo anexado**. Cada acción (`ingest`, `access`, `export`,
`redact`, …) se convierte en una entrada **encadenada por hash** a su predecesora,
**firmada** y **con marca de tiempo**. `verify()` vuelve a comprobar el orden de la secuencia, los eslabones de la cadena,
los hashes de cada entrada, las firmas y los resúmenes de las marcas de tiempo. Las exportaciones se verifican sin conexión:

```bash
python scripts/verify_custody.py custody_bundle.json [--pin]
```

REST: `POST /api/custody/log`, `GET /api/custody/{item}`, `.../verify`,
`GET /api/custody/export`, `POST /api/custody/verify`.

Registro automático opcional en la ingesta: establezca `OO_CUSTODY_ON_INGEST=1`
(`Config.custody_on_ingest`). Está **desactivado por defecto**: es una elección probatoria explícita
con un pequeño coste de firma por artículo, no un comportamiento silencioso siempre activo.
Es tolerante a fallos (fail‑open): un error de custodia nunca interrumpe la ingesta.

#### 4. Anclaje — `src/custody/anchor.py`
Publica una raíz de Merkle ante un testigo externo para que su momento de existencia no dependa
de su propio reloj ni de su propia clave:

- **`local`** (por defecto, sin conexión): registra la raíz en un libro de anclajes local. Solo demuestra
  que *esta herramienta* la almacenó: auditoría interna, no prueba ante terceros.
- **`opentimestamps`** (red): ancla un hash opaco en Bitcoin. Sin monedero,
  sin comisión, verificable de forma independiente. Sin conexión, recurre a un error explícito de *no disponible*,
  nunca a un recibo falso.
- **`ethereum` / `ipfs` / `arweave`**: declarados pero **no implementados**. Se
  niegan con un error claro en lugar de publicarse como esbozos cuyo `verify()` siempre
  devuelve false.

REST: `POST /api/custody/anchor`, `GET /api/custody/providers`.

#### 5. Ajustes — `src/custody/settings.py` (configurables desde la interfaz gráfica)
El comportamiento de la custodia lo controla el operador en tiempo de ejecución, no solo mediante env/YAML.
Las preferencias se guardan en `custody_settings.json` dentro del directorio de datos y se editan
desde el panel **Cadena de custodia** de la interfaz web (o la API REST):

- **`pqc_enabled`**: solicita la firma híbrida Ed25519 + ML‑DSA.
- **`anchoring_mode`**: `local` (por defecto) u `opentimestamps`.
- **`auto_log_on_ingest`**: añade una entrada firmada en cada ingesta correcta
  (por defecto sigue el antiguo indicador `OO_CUSTODY_ON_INGEST` hasta que se guarde una preferencia).
- **`default_actor`**: etiqueta de actor opcional para las entradas registradas automáticamente.

**Invariante de honestidad.** Un interruptor es una *solicitud*, no una garantía. La API y la interfaz gráfica
siempre muestran el estado **efectivo** (preferencia **Y** disponibilidad de la biblioteca):
si PQC está activado pero `pqcrypto` no está instalado, el firmante sigue siendo solo Ed25519
y la interfaz lo indica: nunca muestra una luz verde de "híbrido" que no pueda respaldar. Lo mismo
ocurre con OpenTimestamps sin el extra `timestamping`.

REST: `GET /api/custody/settings`, `PUT /api/custody/settings`.

Un flujo típico de "máxima prueba":

```
export evidence bundle  ->  take its merkle_root  ->  POST /api/custody/anchor
  (POST /api/reports/evidence)                         {merkle_root, "opentimestamps"}
```

---

### ⚠️ Privacidad: el anclaje puede desanonimizarle

Anclar en una cadena de bloques **pública** es una **publicación permanente** de un hash y una
marca de tiempo. El hash en sí no revela nada del contenido, pero el *acto* de
enviarlo revela su IP y el momento a los operadores de los calendarios/RPC, y un monedero
en la cadena con fondos crea un rastro de dinero. Para quien necesite anonimato:

- Prefiera **local + OpenTimestamps** a los monederos de cadenas públicas.
- Encamine los envíos a OpenTimestamps a través de **Tor** (p. ej. `HTTPS_PROXY`).
- O prescinda por completo del anclaje externo y confíe en las marcas de tiempo locales + la firma.

La confidencialidad y el anclaje en cadenas públicas están en tensión. La configuración
por defecto (proveedor local sin conexión, hora local autodeclarada) no filtra nada.

---

### Lo que deliberadamente **no** construimos

- **Ninguna TSA RFC‑3161 falsa.** Devolver `datetime.now()` y llamarlo "marca de tiempo
  de confianza" es teatro. Use OpenTimestamps (real) o local (etiquetado con honestidad).
- **Ninguna firma híbrida con semántica O.** Véase "Híbrido significa Y" más arriba.
- **Ningún demonio de integridad en segundo plano siempre activo, ningún almacén de claves sin cifrar anunciado
  como "cifrado".** Las claves indican cómo están protegidas; la verificación se hace a petición.

### El modelo de amenazas en un párrafo

La herramienta funciona como **un único usuario local, solo en loopback, en Qubes** (véase
`docs/SECURITY.md`). El sistema de custodia defiende la *integridad y la procedencia de
su propio rastro de evidencias* frente a manipulaciones posteriores y frente a acusaciones de "se lo ha
inventado". No protege, ni puede proteger, por sí solo la identidad de una fuente humana,
y un anclaje ingenuo en cadenas públicas puede *perjudicar* activamente el anonimato; por eso el anclaje es
opcional, está desactivado por defecto (sin conexión) y se acompaña de la advertencia anterior.


---

# Lo que se publicó en 0.0.8: el ciclo de la hoja de ruta

> **Instantánea histórica, véase CLAUDE.md.** Este es un registro puntual del ciclo 0.0.8;
> no se mantiene al día con versiones posteriores. `docs/ledger/OPEN_QUEUE.md` + `docs/ledger/`
> son las fuentes de verdad vigentes sobre lo que se ha publicado desde entonces.

Todo lo que sigue está disponible ya, íntegramente desde la interfaz del navegador. Cada función indica su
límite honesto allí donde aparece.

## Recetas de investigación (Inicio) y el panel `/investigate`

El resumen de **Inicio** vigila ahora su propio corpus en busca de **señales espacio-temporales** y genera tarjetas,
todas calculadas localmente, nunca desde la red:

- **Promesas vencidas**: un artículo mencionaba una fecha que estaba *en el futuro* cuando se
  publicó; esa fecha ya ha llegado. Es momento de preguntar qué ocurrió en realidad.
- **Estallido de guerra de ediciones**: una página de Wikipedia que usted rastrea se está editando a ≥3× su propio ritmo
  semanal reciente; su registro público está en movimiento.
- **Región en silencio**: un país que le aportaba artículos con regularidad (casi)
  dejó de hacerlo. La advertencia viene incluida: esto mide *su corpus*, no la región; un feed
  caído parece idéntico a un silencio real, así que compruebe primero las fuentes.
- **Fuentes candidatas pendientes de revisión** (Source candidates await review): véase *Candidatas descubiertas* más abajo.

Las tarjetas con un botón **"Abrir investigación ↗"** abren un panel dedicado **en una nueva
pestaña del navegador** (la aplicación principal sigue funcionando; puede abrir varios a la vez). El panel
reúne automáticamente los paneles relacionados (el artículo original con sus fragmentos de procedencia, una
búsqueda de seguimiento ya rellenada, la lista de revisiones almacenada, el contexto de cobertura), muestra
literalmente la advertencia de la tarjeta en la parte superior y termina con una franja **"Profundizar"** en la que cada
sugerencia es una acción normal con sus parámetros a la vista. Todo el estado de la página reside en
su URL: guárdela en marcadores, vuelva a abrirla, compártala entre sus propios equipos.

Desactive recetas concretas en **Ajustes → Tarjetas**, donde ahora aparecen junto a todas las
demás Pistas que esta aplicación puede generar, agrupadas por familia: el mismo interruptor, aplicado a todas ellas.

## Apéndice de métodos

El botón **Apéndice de métodos** (en la página de búsqueda y en la fila de acciones de la ventana de
análisis) descarga un documento Markdown que registra *cómo* se obtuvo su selección actual:
la versión de la aplicación, la consulta booleana literal, los recuentos de resultados, el contexto del corpus y una
fila de procedencia por artículo (título · fuente · publicación · URL · SHA-256 del contenido). Solo
registra la selección y no afirma ninguna conclusión: las afirmaciones analíticas siguen siendo suyas,
contrastables con las filas. Pensado para veredictos de verificación de datos y revisión por pares; combínelo con un
paquete de evidencia firmado (Evidencia y custodia) cuando necesite documento + prueba a la vez.

## Sintetizar resultados

**Sintetizar resultados** (en la página de búsqueda y en la ventana de análisis) abre una ventana en
dos pasos: obtiene un conjunto de candidatos, le muestra los artículos coincidentes con sus metadatos
y le permite **elegir hasta 20 miembros** (los primeros ≤20 vienen marcados); después ejecuta UNA
pasada del modelo local sobre exactamente esos y devuelve los hechos compartidos, los puntos de desacuerdo y las
preguntas abiertas, citando los artículos miembros por número. El resultado incluye el corpus sintetizado
completo con los metadatos de cada artículo y enlaces al lector, y opciones de **exportación** (Copiar, .md, o
abrir como página independiente). La síntesis se almacena con la procedencia de modelo + versión del prompt
por cada artículo miembro, y la advertencia la acompaña: es una ayuda a la lectura limitada a los
miembros listados, nunca un veredicto. Requiere Ollama, como las demás funciones de LLM;
sin él recibe un mensaje honesto de "no accesible".

## Exportaciones versionadas y el grafo de citas

- Las exportaciones legibles por máquina llevan ahora un contrato estable (`oo-export-1`): las exportaciones JSON son
  envoltorios autodescriptivos (esquema, versión de la aplicación, fecha de generación, la consulta exacta, recuento);
  las columnas CSV mantienen su orden, con la misma procedencia que las cabeceras HTTP `X-OO-*`. La última
  columna, **Fetched From Host** (Host de descarga) (`fetched_host` en JSON), es el host desde el que realmente se
  descargó la página tras sus redirecciones; está vacía para un artículo almacenado antes de que se registrara.
- El **grafo de citas** (qué dominios externos citan sus artículos almacenados, solo recuentos,
  sin credibilidad inferida) se exporta como GraphML (`/api/links/export.graphml`) para
  Gephi/yEd/NetworkX, o como JSON.

## Registro de ejecuciones del planificador y la exportación a carpeta local (Recopilar)

Cada ejecución del planificador, con éxito o con fallo, añade una línea a un registro de ejecuciones local y auditable
(`scheduler_runs.jsonl`), de modo que el corpus puede responder a "¿qué se ejecutó mientras estaba fuera?". Opcionalmente,
indique una ruta de **Exportación a carpeta local** en la tarjeta del planificador de Recopilar: cada ejecución escribirá entonces el
delta de artículos nuevos como un archivo JSON con envoltorio en esa carpeta local, para que su propio proceso lo
vigile. En blanco = desactivado (por defecto); nada nuevo = ningún archivo.

## Candidatas descubiertas (Fuentes)

La aplicación sugiere ahora fuentes por sí misma, **solo sin conexión**: dominios que sus artículos almacenados
citan repetidamente, y medios del catálogo incluido para países que su corpus cubre poco.
Las sugerencias quedan en espera, nunca se aplican: cada una lleva su evidencia en el panel **Candidatas
descubiertas** (Ajustes → Avanzado → Fuentes), las ejecuciones están limitadas por el presupuesto de descubrimiento del planificador y
se registran en el registro de ejecuciones, y una tarjeta de Inicio le avisa cuando hay candidatas pendientes de revisión.
**Aceptar** (Promote) crea una fuente *desactivada* que usted todavía tiene que activar; **Descartar** se recuerda
y nunca se vuelve a sugerir. La búsqueda por tema basada en DuckDuckGo sigue siendo aparte, está **desactivada por
defecto** y protegida tras Ajustes → Avanzado → Seguridad (véase más abajo).

## El descubrimiento externo por tema es opcional (Ajustes → Avanzado → Seguridad)

*Descubrimiento por tema* es la única función que **envía una consulta de búsqueda en texto libre a un motor
de búsqueda**: envía su consulta de tema a DuckDuckGo. (Las demás acciones en línea, como la recopilación,
las descargas de mercados/estadísticas, las descargas de modelos de Ollama u OpenTimestamps, también requieren consentimiento y se nombran;
esta es la que transmite una consulta que usted escribió.) Está **desactivada por defecto** y
se niega con un mensaje honesto
hasta que active **Ajustes → Avanzado → Seguridad → Descubrimiento externo por tema** ("Tu consulta
sale de esta máquina"). El descubrimiento de feeds RSS para fuentes que usted mismo añadió sigue en la
vía local de descarga ética y no se ve afectado.

## Idiomas

La interfaz incluye ahora **traducciones completas en 12 idiomas** (English, العربية, বাংলা,
Deutsch, Español, Français, हिन्दी, Bahasa Indonesia, 日本語, Português, Русский, 中文),
con disposición de derecha a izquierda para el árabe. Elija el suyo en el selector de idioma; las
traducciones son primeros borradores generados por máquina: las correcciones son contribuciones bienvenidas
(véase `docs/ARCHITECTURE.md` → Internationalisation).
