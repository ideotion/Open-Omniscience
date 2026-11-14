<!-- es: AI-drafted translation of docs/QUICKSTART.md (2026-11-13, R677), not yet reviewed by a native speaker; the English original is authoritative. Coverage: the whole document, 17 of 17 headings. Improve it with a pull request; corrections by native speakers are welcome. -->

# Inicio rápido — ejecutar la aplicación

Este es el **núcleo fiable** (la aplicación es una **alfa** honesta — `v0.5.0`, el
ciclo `0.5` «mesa del investigador», etiquetado el 2026-10-26; la aplicación en ejecución indica su
versión exacta): añadir una fuente → recopilarla de forma ética → almacenarla con su procedencia →
búsqueda booleana de texto completo → exportar. Local primero, solo en la interfaz de bucle local (loopback), sin cuentas.

---

## 0. La forma fácil — un comando y luego doble clic para ejecutar

Si solo quiere usar la aplicación (después no necesitará saber usar la línea de comandos):

**Linux / macOS** — en una terminal:

```bash
curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/HEAD/scripts/bootstrap.sh | bash
```

**Windows 11** — en PowerShell. Descárguelo *y después* ejecútelo:

```powershell
irm https://raw.githubusercontent.com/ideotion/Open-Omniscience/HEAD/install.ps1 -OutFile $env:TEMP\oo-install.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File $env:TEMP\oo-install.ps1
```

Es posible que Windows Defender ponga el archivo en cuarentena de todos modos: no está firmado y es nuevo. Se trata de un
falso positivo; la [§C](#c-en-windows-11-powershell) explica exactamente por qué y le ofrece una
vía sin script que nada puede eliminar.

La compatibilidad con Windows es más limitada que con Linux, y la diferencia se explica claramente en la
[§C](#c-en-windows-11-powershell): léala antes de confiar en ella.

> **Inspeccione antes de confiar.** Canalizar un script hacia su shell ejecuta código en su
> equipo. Ambos son deliberadamente pequeños; léalos antes si lo desea
> ([scripts/bootstrap.sh](../scripts/bootstrap.sh), [install.ps1](../install.ps1)).
> Comprueban que estén git y Python 3.13, clonan este repositorio en `~/open-omniscience`
> (`%USERPROFILE%\Open-Omniscience` en Windows) y pasan el control al instalador
> incluido en el repositorio. También puede clonarlo usted mismo y ejecutar `./install.sh` / `install.ps1`.

`install.sh` **no hace preguntas**: **no hay menú de componentes**. Un solo comando instala
el conjunto predeterminado razonable:

| Instalado por defecto | Lo que obtiene |
|----------------------|--------------|
| **Núcleo** *(siempre)* | recopilación · almacenamiento con procedencia · búsqueda booleana · exportación |
| **Análisis** | palabras clave · comparación de enfoques · sentimiento |
| **Compresión** | almacenamiento en disco del corpus más rápido |

La configuración del LLM local / Ollama **no** forma parte del instalador: se encuentra por completo en la
pestaña **Ajustes → IA** de la aplicación (véase §E). Cambie el conjunto instalado con la
variable de entorno `OO_COMPONENTS="…"` (p. ej. `OO_COMPONENTS="analysis,nlp"`); volver a ejecutar
`./install.sh` es idempotente y solo instala lo que falta.

**Después se inicia automáticamente.** El instalador crea un lanzador **Open Omniscience** (menú de
aplicaciones + Escritorio) y abre la aplicación en su navegador. Para iniciarla de nuevo más tarde:

- abra su menú de aplicaciones y busque **Open Omniscience**, **o**
- haga doble clic en el icono **Open Omniscience** de su **Escritorio**.

Aparece una pequeña ventana de terminal, la aplicación se inicia y su navegador se abre en
**http://127.0.0.1:8000**. **Cierre esa ventana (o use el botón de encendido / apagado de la barra
superior) para detener la aplicación.** (En macOS el lanzador es `Open Omniscience.command` en su
Escritorio; en Windows es un acceso directo en el Escritorio y en el menú Inicio creado por `install.ps1`.)

**Primer inicio.** En una instalación nueva, la aplicación le guía por una breve configuración única
*antes* de la interfaz principal: **elija su idioma → lea y acepte las condiciones legales**
(rechazarlas **desinstala** la aplicación, previa confirmación escrita) **→ cree la frase de contraseña
de su corpus**. El corpus está **cifrado en reposo por defecto** (SQLCipher 4) y **no hay
recuperación** posible si pierde la frase de contraseña (perderla le cuesta tiempo de nueva recopilación: el
corpus se reconstruye a partir de la web). A continuación, la aplicación arranca **sin conexión (modo avión)**;
pasar a modo en línea requiere **una ventana de consentimiento** que nombra la acción y muestra las IP de sus
interfaces locales antes de que salga cualquier solicitud.

¿Prefiere la terminal? `cd ~/open-omniscience && ./scripts/launch.sh` hace lo mismo.

**Comprobarla o eliminarla más adelante:**
```bash
./install.sh --check        # health report: Python, data dir, database, LLM, launcher
#   (same as: open-omniscience doctor)
./install.sh --uninstall    # remove the virtualenv + launcher; your data is kept
                            #   (it asks separately, defaulting to NO, before deleting data)
```

---

## A. En una AppVM Debian de Qubes OS (el entorno de referencia)

Qubes restablece el sistema de archivos raíz de una AppVM en cada arranque; solo `/home` (y
`/usr/local`, `/rw`) persisten. Por eso los paquetes del sistema van en la **TemplateVM**, y la
aplicación + el entorno virtual + la base de datos residen en `/home` dentro de la **AppVM**.

**1. En la TemplateVM (una sola vez):**
```bash
sudo ./install.sh --template      # installs python3.13, venv, git, sqlite3, ...
```
Apague la TemplateVM y después **reinicie la AppVM** para que los paquetes sean visibles.

**2. En la AppVM (con su usuario, sin sudo):**
```bash
./install.sh                      # promptless: Core + Analysis + Compression, then auto-launches
# Qubes AppVM (unattended, creates the launcher, no prompts): Core + Analysis + Compression
./install.sh --appvm
```

**3. Ejecútela (escucha solo en 127.0.0.1):**
Haga doble clic en el lanzador **Open Omniscience** (menú de aplicaciones / Escritorio), o bien:
```bash
cd ~/open-omniscience && ./scripts/launch.sh    # starts the app + opens the browser
```
Abra **http://127.0.0.1:8000** en el navegador de la AppVM.

El servidor nunca escucha fuera de la interfaz de bucle local. Para quedarse totalmente sin conexión después de una ejecución, desconecte la
NetVM de la AppVM: la interfaz no tiene dependencias externas y sigue funcionando con los datos almacenados.

---

## B. Ejecución local de desarrollo (cualquier Linux con Python 3.13)

```bash
python3.13 -m venv .venv && . .venv/bin/activate
pip install -e ".[analysis,dev]"
pytest -q                          # full test suite
open-omniscience                   # serve at http://127.0.0.1:8000
```

Variables de entorno útiles: `OO_DATA_DIR` (dónde residen la base de datos SQLite + los datos), `OO_HOST`/`OO_PORT`,
`OO_FETCH_MIN_INTERVAL` (pausa de cortesía por host, en segundos).

### En Tails

Debian/Ubuntu/Tails distribuyen `venv`/`ensurepip` de la biblioteca estándar en un **paquete apt aparte**, por lo que
`python3 -m venv` falla hasta que se instala. `install.sh` ahora lo instala
**automáticamente**: en Tails eso requiere una **contraseña de administración** (configúrela en la
pantalla de bienvenida; está desactivada por defecto) y una **conexión a Tor** operativa (apt descarga a través de
Tor). Desactívelo con `OO_NO_APT=1` si prefiere ejecutar apt usted mismo.

Dos advertencias honestas propias de Tails:

- **Versión de Python.** Tails es Debian 12 → **Python 3.11**, pero la aplicación requiere **3.13**.
  Debe tener disponible un intérprete 3.13 e indicárselo al instalador
  (`OO_PYTHON=python3.13 ./install.sh`); 3.13 y su paquete `python3.13-venv` **no** están
  en los repositorios predeterminados de Tails.
- **Amnesia.** Todo lo instalado con apt —y el `.venv` completo— **se pierde al reiniciar** a menos que
  resida en el Almacenamiento Persistente: añada el paquete de venv mediante **Almacenamiento Persistente → Software
  adicional**, y mantenga el repositorio clonado + `OO_DATA_DIR` en el volumen persistente.

### Actualizar una base de datos existente

Las instalaciones nuevas crean el esquema automáticamente (`init_db()`), y la base de datos queda
marcada con la línea base de migración actual. Cuando una versión futura cambie el
esquema, actualice una base de datos existente con:
```bash
alembic upgrade head
```
`alembic check` indica si los modelos y las migraciones están sincronizados (la CI lo vigila).

---

## C. En Windows 11 (PowerShell)

**Estado honesto de la compatibilidad: lea esto primero.** Cada ejecución de la CI demuestra tres cosas en
`windows-latest`: la instalación de dependencias, la **comprobación de arranque** (toda la aplicación se importa)
y el **cifrado en reposo con SQLCipher**, este último en una línea *bloqueante*, de modo que el
cifrado no es una suposición. Nada más allá de eso está demostrado. La **línea pytest de Windows
se cuelga** (ejecuciones recientes completadas permanecieron en `pytest` 3h21m y ~6h, frente a 18 minutos
en macOS), y **nadie ha recorrido la interfaz haciendo clic en Windows**. Así que: espere que la instalación
y el inicio funcionen, considere todo lo posterior al arranque como no verificado y, por favor, informe de lo que
falle. Linux sigue siendo el criterio para publicar versiones.

### 1. Instalación

Abra **PowerShell** (no necesita derechos de administrador salvo que haya que instalar el propio
Python). Descargue el instalador, léalo si lo desea y después ejecútelo:

```powershell
irm https://raw.githubusercontent.com/ideotion/Open-Omniscience/HEAD/install.ps1 -OutFile $env:TEMP\oo-install.ps1
notepad $env:TEMP\oo-install.ps1                                     # optional: see what you are about to run
powershell -NoProfile -ExecutionPolicy Bypass -File $env:TEMP\oo-install.ps1 -Extras analysis
```

Instala Git y Python 3.13 mediante `winget` solo si faltan, clona en
`%USERPROFILE%\Open-Omniscience`, crea un `.venv` y verifica el resultado
importando la aplicación real. Quite la opción `-Extras` para obtener el conjunto predeterminado más completo, o consulte
[Opciones del instalador](#opciones-del-instalador).

¿Ya lo ha clonado? Ejecútelo ahí mismo: detecta su propio repositorio clonado y omite la clonación:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

> **¿Por qué no una sola línea `irm … | iex`?** Porque descargar código remoto y ejecutarlo
> directamente desde la memoria es la forma más habitual de distribuir malware en Windows, así que
> Defender califica ese patrón como hostil sea cual sea el contenido del script. Guardar primero el archivo
> en disco tiene menos probabilidades de ser bloqueado y es más honesto: puede leerlo
> antes de que se ejecute.

### 2. Si Windows Defender pone el instalador en cuarentena

Puede que elimine `install.ps1` nada más verlo. Es un **falso positivo**, y no debería
fiarse de nuestra palabra: aquí está exactamente por qué ocurre, para que usted juzgue:

- El archivo **no está firmado y es nuevo**, así que la reputación en la nube de Defender nunca lo ha visto.
  Desconocido + sin firmar basta por sí solo para activar la heurística de aprendizaje automático; el
  nombre de la detección suele terminar en `!ml`.
- Su **forma** es la de un instalador: llama a un gestor de paquetes, vuelve a leer `PATH` del
  registro, crea accesos directos en el menú Inicio y su ruta `-Uninstall` elimina
  directorios. Los droppers hacen esas mismas cosas. El clasificador evalúa la forma, no la intención.

Lo que *no* contiene, y que usted mismo puede comprobar en unas ~500 líneas legibles: ni
`Invoke-Expression`, ni carga codificada u ofuscada, ni `WebClient`, ni ventanas
ocultas, ni ninguna descarga aparte de este repositorio.

Tres maneras de continuar, de la mejor a la peor:

1. **Use la vía sin script**: la [Instalación manual](#instalación-manual-sin-script) que figura más abajo.
   Los mismos comandos que ejecuta el instalador, sin ningún archivo que poner en cuarentena. Esto siempre funciona.
2. **Notifique el falso positivo** a Microsoft en
   <https://www.microsoft.com/en-us/wdsi/filesubmission> (elija *Software developer*).
   Suele resolverse en uno o dos días y lo corrige para todos los que instalen
   después de usted, no solo para usted.
3. **Excluya la carpeta** (Seguridad de Windows → Protección antivirus y contra amenazas → Administrar
   la configuración → Exclusiones). Conozca la contrapartida antes de hacerlo: una exclusión hace que
   Defender deje de analizar esa carpeta *por completo*, para todo, indefinidamente, no solo
   para este archivo. Es su equipo y su decisión; no vamos a fingir que no tiene coste.

La solución honesta por nuestra parte es la firma de código, que todavía no tenemos.

### 3. Ejecución

El instalador crea un acceso directo **Open Omniscience** en su **Escritorio** y en el
**menú Inicio**. Haga doble clic en él: aparece una ventana de terminal y su navegador se abre en
**http://127.0.0.1:8000** en cuanto la aplicación responde realmente. Cierre esa ventana (o use el
botón de encendido de la aplicación) para detenerla.

Desde una terminal: `scripts\launch.cmd`.

### 4. Primer inicio

El mismo proceso único que en todas las plataformas: **elija su idioma → lea y acepte las
condiciones legales → cree la frase de contraseña de su corpus**. El corpus está **cifrado en reposo por
defecto** y **no hay recuperación** posible si pierde la frase de contraseña. A continuación, la aplicación arranca
**sin conexión (modo avión)**; pasar a modo en línea requiere **una ventana de consentimiento**.

### Opciones del instalador

| Opción | Qué hace |
|------|--------------|
| *(ninguna)* | Núcleo + `analysis,compression,columnar`, después verifica y crea los lanzadores |
| `-Path <dir>` | Instala en otro lugar distinto de `%USERPROFILE%\Open-Omniscience` |
| `-Extras "analysis"` | Elige los extras de pip (`""` solo para el núcleo) |
| `-Ref <branch>` | Clona una rama o etiqueta concreta |
| `-NoPython` | Nunca instala Git/Python automáticamente; en su lugar falla con instrucciones |
| `-NoLauncher` | Omite los accesos directos del Escritorio / menú Inicio |
| `-Check` | Informe de estado (igual que `open-omniscience doctor`) |
| `-Uninstall` | Elimina `.venv` + los lanzadores; los datos se conservan salvo confirmación aparte |
| `-Yes` | Responde sí a las preguntas (modo desatendido) |

Solo `analysis` está demostrado en Windows por la CI. Si el conjunto predeterminado más completo no se
instala, el script **recurre a `analysis` y lo indica**, en lugar de fallar
en silencio o fingir que los extras se instalaron.

### Instalación manual (sin script)

```powershell
# 1. Prerequisites -- skip either line if you already have it
winget install --id Git.Git -e --source winget
winget install --id Python.Python.3.13 -e --source winget --scope user

# 2. Find the interpreter. winget frequently installs Python WITHOUT adding it to
#    PATH, so `python` and `py` can still resolve to nothing on a freshly restarted
#    machine. This reads the record the installer itself writes (PEP 514) -- the same
#    one py.exe uses -- so it answers whatever PATH says:
Get-ChildItem 'HKCU:\SOFTWARE\Python','HKLM:\SOFTWARE\Python' -Recurse -ErrorAction SilentlyContinue |
  Where-Object PSChildName -eq 'InstallPath' |
  ForEach-Object { (Get-ItemProperty $_.PSPath).'(default)' }

$py = "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe"   # or whatever that printed

# 3. Clone
git clone --depth 1 https://github.com/ideotion/Open-Omniscience.git $HOME\Open-Omniscience
cd $HOME\Open-Omniscience

# 4. Virtual environment. Everything is called by full path on purpose: activating a
#    venv needs Activate.ps1, which the default execution policy blocks.
& $py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[analysis]"

# 5. Verify -- the exact check CI's Windows lane runs
.\.venv\Scripts\python.exe -c "from src.api.main import app; print(sum(1 for _ in app.routes))"

# 6. Run
.\.venv\Scripts\open-omniscience.exe
```

### Notas específicas de Windows

- **Directiva de ejecución.** La directiva predeterminada bloquea `.\.venv\Scripts\Activate.ps1`.
  Nada de lo aquí descrito lo necesita: llame a `.venv\Scripts\python.exe` por su ruta y el problema
  desaparece por completo. `-ExecutionPolicy Bypass` en la línea de comandos cubre el propio instalador.
- **El `python` que abre Microsoft Store.** Un Windows 11 recién instalado incluye un
  alias de ejecución de relleno llamado `python.exe` que abre la Store en lugar de ejecutar
  código. El instalador lo ignora (un alias de relleno no muestra ninguna versión) y usa el lanzador `py -3.13`.
  Si instala manualmente, prefiera `py -3.13` a `python`.
- **Dónde residen sus datos.** Como se trata de un repositorio de código fuente clonado, el corpus, las claves de
  firma y los ajustes se guardan en **`<repo>\data`**, no en `%APPDATA%`. Defina `OO_DATA_DIR` para
  ubicarlos en otra unidad.
- **Permisos de carpeta.** En Linux, el directorio de datos queda restringido a su usuario
  (`chmod 0700`); esa llamada no tiene efecto en Windows, por lo que la carpeta hereda las ACL
  habituales de Windows. En un PC compartido, restrinja usted mismo `<repo>\data`. La propia base de datos
  del corpus sigue cifrada en reposo en cualquier caso.
- **SmartScreen / Defender.** Nada de esto tiene firma de código, así que Windows lo trata todo
  como desconocido: SmartScreen puede advertir sobre el lanzador y Defender puede poner directamente en cuarentena
  `install.ps1`; consulte la
  [§2](#2-si-windows-defender-pone-el-instalador-en-cuarentena) para saber qué es y qué
  hacer al respecto. El análisis en tiempo real también ralentiza notablemente el primer `pip install`.
- **Puerto.** Defina `OO_PORT` antes de iniciar para no usar el 8000; `scripts\launch.cmd`
  lo respeta.
- **Arquitectura (x64 / ARM64 / 32 bits).** El instalador la detecta y la gestiona; aquí
  se explica lo que decide. Lo que determina si `pip install` tiene éxito no es la
  máquina, sino qué wheels existen para la plataforma del *intérprete*. Medido en
  PyPI el 2026-08-23, para CPython 3.13, en todo el conjunto de dependencias de este proyecto:

  | intérprete | wheels |
  |---|---|
  | `win-amd64` | **todas las dependencias.** La única arquitectura completa. |
  | `win-arm64` | todas salvo tres: `cryptography` (núcleo), `httptools` (núcleo, a través de `uvicorn[standard]`) y `statsmodels` (`analysis`) |
  | `win32` | `cryptography` no publica ninguna |

  Windows en ARM ejecuta binarios x64 de forma transparente, así que un **intérprete x64 es la respuesta
  correcta también en ARM64**: no es un compromiso, es el conjunto completo. Por eso `install.ps1`
  prefiere `win-amd64` en todas partes y conseguirá uno si la máquina no lo tiene:
  winget indicando la arquitectura, después winget en ámbito de usuario y, por último, el CPython x64
  autónomo de la Python Software Foundation desde nuget.org, verificado con
  el SHA-512 que nuget certifica para él, descomprimido en
  `%LOCALAPPDATA%\Open-Omniscience\python-x64`, sin necesidad de elevación de privilegios, ni de cambiar PATH,
  ni de ninguna entrada en el registro. Se ubica **fuera** del repositorio clonado a propósito: es un recurso de la
  máquina, por lo que sobrevive a la eliminación de la carpeta de la aplicación (de lo contrario, el `.venv` construido sobre él
  dejaría de funcionar) y un segundo repositorio clonado con `-Path` lo reutiliza. `-Uninstall` lo elimina. Una discrepancia del hash, o una
  versión para la que nuget no certifica ningún hash, provoca un **rechazo**.

  Si fallan todos los escalones, el proceso se detiene indicándole la solución con una sola descarga, no una compilación
  de Rust de veinte minutos que acaba en `linker link.exe not found`.

  Un `.venv` existente se **examina, no solo se detecta**: conserva la versión y la plataforma de wheels
  del intérprete que lo creó, de modo que uno que haya quedado de una ejecución anterior con un
  Python distinto se sustituye en lugar de reutilizarse; de lo contrario, todo lo anterior se
  desharía en silencio en el último paso. Uno que coincida se reutiliza tal cual. Volver a ejecutar el
  instalador es, por tanto, la solución para una instalación a medias; no hay que eliminar nada
  a mano.

  - **Por qué no se habilita automáticamente una instalación nativa ARM64.** Requeriría fijar `cryptography`
    en 46.0.0–46.0.3, la única serie con wheels para ARM64. Esa versión tiene
    **13 registros de avisos de seguridad abiertos** (incluido uno de OpenSSL enlazado estáticamente, corregido en
    48.0.1). Esta aplicación firma evidencias; instalar eso sin decir nada sería teatro de
    seguridad. Si su máquina tiene realmente Visual Studio Build Tools **y** una cadena de herramientas de
    Rust, `-AllowSourceBuilds` compila las tres de forma nativa: una elección explícita,
    nunca una opción predeterminada.
  - **Windows de 32 bits no es compatible**, y se trata de un límite real, no de una restricción arbitraria:
    `cryptography` no distribuye ninguna wheel `win32`. Se requiere Windows de 64 bits.

---

## D. El ciclo completo (interfaz o API)

> **Las fuentes vienen preconfiguradas.** En el primer inicio (o durante `install.sh --appvm`)
> los catálogos seleccionados (`configs/sources.yml` ~3200 medios de interés público, más
> los catálogos de mercados, espectro político y derecho/PI — **~3395 dominios únicos en
> total**) se cargan automáticamente, así que puede empezar a recopilar de inmediato.
> (Estas cifras **varían** a medida que crecen los catálogos; la cifra real es la que
> contenga en ese momento `configs/*.yml`.) Volver a cargarlos es idempotente. Desactive la carga automática con
> `OO_AUTOSEED=0`; vuelva a cargarlos manualmente con `python scripts/seed_sources.py` o
> `POST /api/sources/seed-defaults`. Las URL de los feeds y las políticas de robots cambian con el tiempo; el
> recolector ético rechaza todo lo que no puede confirmar, así que depure o amplíe la lista según
> su investigación.

**En la interfaz:** **pase a modo en línea** una vez (el interruptor del modo avión → una ventana de consentimiento) y
**la recopilación funciona sola** en segundo plano: estratificada por idiomas y etiquetas de
fuentes, respetando robots.txt y con límite de frecuencia. Después, **busque en Explorar** (la pestaña de la barra lateral; pulsar
Intro en la omnibarra, barra superior o Ctrl/⌘-K, abre Explorar en una nueva pestaña del navegador): el análisis de los artículos coincidentes aparece debajo de los
resultados, donde puede filtrar, leer, ejecutar consultas booleanas y **exportar** (CSV/JSON, apéndice
de métodos, evidencia firmada). Aún puede añadir una fuente e *Ingerir (Ingest)* manualmente un solo feed o una URL
desde **Ajustes → Avanzado → Recopilación / Fuentes**.

**Mediante la API:**
```bash
# add a source
curl -X POST http://127.0.0.1:8000/api/sources/ -H 'Content-Type: application/json' \
  -d '{"name":"Example News","domain":"example.com","rss_url":"https://example.com/feed.xml"}'

# ingest its feed (ethical: robots.txt respected fail-closed, rate-limited)
curl -X POST http://127.0.0.1:8000/api/sources/1/ingest

# or ingest a single article URL under that source
curl -X POST http://127.0.0.1:8000/api/ingest -H 'Content-Type: application/json' \
  -d '{"source_id":1,"url":"https://example.com/some-article"}'

# Boolean full-text search (AND / OR / NOT, "phrases", parentheses)
curl 'http://127.0.0.1:8000/api/articles?query=(climate OR energy) AND policy NOT opinion'

# export the filtered set
curl 'http://127.0.0.1:8000/api/articles/export?format=csv&query=climate'
```

El esquema de la API legible por máquina está en **http://127.0.0.1:8000/openapi.json**. La página interactiva de Swagger está desactivada por defecto (carga recursos desde hosts de terceros); un desarrollador puede iniciar la aplicación con `OO_API_DOCS=1` para tenerla en `/docs`.

---

## E. Capacidades de análisis

Todas funcionan en local primero y, cuando se degradan, lo hacen de forma visible (nunca inventan nada). Esquemas completos en `/openapi.json`.

**LLM local (Ollama).** Configúrelo desde **Ajustes → IA**: un instalador de Ollama integrado en la aplicación
y **verificado por suma de comprobación** (Linux), más una **cola de descarga de modelos** (progreso real en
bytes, cancelable), un selector del modelo activo y un panel de instrucciones editables. O instale
Ollama usted mismo desde **ollama.com** y `ollama pull llama3.2:3b`. Las descargas de modelos salen
por **la red abierta (clearnet) a través del proceso de Ollama** (no por la ruta Tor de la aplicación), lo cual se informa
al pedir el consentimiento. La pastilla LLM de la barra superior muestra el estado en tiempo real (haga clic en ella para abrir Ajustes → IA); cada
resultado de búsqueda tiene los botones **Resumir** y **Traducir**. API:
```bash
curl http://127.0.0.1:8000/api/llm/health          # {available, installed_models}
curl -X POST http://127.0.0.1:8000/api/llm/articles/1/summarize -d '{}'  # persisted with provenance
```
Si Ollama no está en ejecución, estas llamadas devuelven HTTP 503 con un mensaje claro, no un resumen falso.

**Precios de materias primas + correlación honesta.**
```bash
curl -X POST http://127.0.0.1:8000/api/commodities/Nd/prices -H 'Content-Type: application/json' \
  -d '{"points":[{"observed_on":"2026-01-01","price":100,"unit":"kg"}]}'
curl 'http://127.0.0.1:8000/api/commodities/Nd/correlation?query=neodymium'
```
La correlación devuelve un coeficiente real + valor p + n calculados con scipy (Pearson/Spearman),
con la advertencia «correlación ≠ causalidad»; si el solapamiento es demasiado escaso → `insufficient_data`.

**Monitorización.** `POST /api/monitoring/health` realiza comprobaciones reales de accesibilidad
(a través del recolector ético); `GET /api/monitoring/anomalies` señala
picos en el volumen de artículos mediante la puntuación z. **Correo electrónico:** `POST /api/sources/{id}/ingest-email`
(IMAP) incorpora los mensajes al mismo corpus consultable.

**Verificación de metadatos de imágenes.** `POST /api/verify/image-metadata`
(suba una imagen) devuelve su formato, dimensiones, EXIF y GPS junto con observaciones
factuales sencillas (p. ej., presencia de una etiqueta de software de edición, ausencia de marca de tiempo de captura). Su alcance se limita
honestamente a *comprobaciones de metadatos*: **no** es detección de deepfakes ni de manipulaciones (eso era
inventado y se puso en cuarentena fuera del árbol de trabajo; véase
[docs/QUARANTINE_ARCHIVE.md](QUARANTINE_ARCHIVE.md)).

**Paquetes de evidencia firmados.** El botón **Exportar evidencia firmada** de la
ventana de análisis (o `POST /api/reports/evidence`) genera un paquete con raíz de Merkle y
firmado con Ed25519. Cualquiera puede verificarlo sin conexión, sin esta aplicación:
```bash
python scripts/verify_evidence.py evidence-bundle.json   # exit 0 = verified
```

**Cadena de custodia.** El panel **Cadena de custodia** de la interfaz registra una procedencia firmada
y a prueba de manipulaciones, y le permite cambiar su comportamiento en tiempo de ejecución:
firmas poscuánticas, modo de anclaje (`local` sin conexión o **OpenTimestamps**
anclado en Bitcoin) y registro automático durante la ingesta. Los interruptores son *preferencias*: el
panel muestra el estado **efectivo**, de modo que nada afirma estar activado cuando su componente adicional
no está instalado. API:
```bash
curl http://127.0.0.1:8000/api/custody/settings                       # effective state
curl -X PUT http://127.0.0.1:8000/api/custody/settings \
  -H 'Content-Type: application/json' -d '{"pqc_enabled": true}'
curl -X POST http://127.0.0.1:8000/api/custody/log -H 'Content-Type: application/json' \
  -d '{"item_id":"article:1","item_hash":"<sha256>","action":"ingest"}'
curl 'http://127.0.0.1:8000/api/custody/export' > custody-bundle.json  # offline-verifiable
python scripts/verify_custody.py custody-bundle.json                   # exit 0 = verified
```
Modelo completo, modelo de amenazas y advertencias de privacidad: [USER_MANUAL.md](USER_MANUAL.md).

---

## Lo que garantiza la «ingesta ética»

- robots.txt se descarga, se guarda en caché por host y **falla en modo cerrado**: si no puede
  confirmarse (error de red, tiempo de espera agotado, 5xx o un 401/403 restringido), la URL
  **no** se descarga.
- Se impone un intervalo mínimo por host (respetando `Crawl-delay`).
- Una sola ruta de descarga, un User-Agent identificativo (en modo protegido, uno genérico, salvo en las solicitudes de API y de volcados a los servidores de Wikimedia), solo HTML para los artículos: ningún acceso directo sin control.
- La extracción usa trafilatura; si no se encuentra un cuerpo de artículo real, no se almacena nada
  (ninguna fila inventada del tipo «No Title / No Content»).
- Cada artículo almacenado lleva su procedencia: fuente, URL original, URL canónica,
  hash del contenido (usado para eliminar duplicados) y fecha de descarga.
