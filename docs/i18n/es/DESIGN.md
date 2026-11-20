<!-- es: Translation of docs/DESIGN.md written by AI (2026-11-19, R677; native review dropped by R721, 2026-11-14); it may contain mistakes, and the English original is authoritative. Coverage: the whole document, 68 of 68 headings. Corrections are welcome as a pull request. -->

# Síntesis de diseño y de producto

Qué es la aplicación y qué no es, dónde vive ahora cada «pilar» original, el razonamiento de diseño de la interfaz gráfica y la estrategia de análisis de contenido. La referencia única de diseño.

## Contenido
- [Open-Omniscience — Síntesis de producto (qué debe hacer la aplicación)](#open-omniscience--síntesis-de-producto-qué-debe-hacer-la-aplicación)
- [Mapa de intenciones de los pilares — dónde vive ahora el propósito de cada pilar](#mapa-de-intenciones-de-los-pilares--dónde-vive-ahora-el-propósito-de-cada-pilar)
- [Rediseño de la interfaz — «0.05»](#rediseño-de-la-interfaz--005)
- [Dos interfaces, un argumento — «Console» frente a «Desk»](#dos-interfaces-un-argumento--console-frente-a-desk)
- [Estrategia de análisis de contenido — enlaces, uniformidad y la fuente original](#estrategia-de-análisis-de-contenido--enlaces-uniformidad-y-la-fuente-original)


---

## Open-Omniscience — Síntesis de producto (qué debe hacer la aplicación)

> **Estado:** Borrador para revisión. Este documento reúne el diseño *previsto*, disperso por la
> documentación del repositorio, en una especificación única, coherente y sin duplicados. Elimina
> deliberadamente la deriva entre versiones, el bombo publicitario y las afirmaciones de control de calidad no verificables. Describe el **producto objetivo**, no
> el código actual (en gran parte no funcional).
>
> Marcadores utilizados:
> - `⚠️ DECIDE:` un punto en el que los documentos de origen eran ambiguos o se contradecían — la decisión es suya.
> - `(P0/P1/P2)` una prioridad *sugerida* para esa capacidad (P0 = núcleo del MVP, P1 = importante, P2 = más adelante).

---

### 0. Contexto de despliegue (RESUELTO — condiciona todo lo que sigue)

Esta compilación apunta a **un entorno concreto y a un único usuario**. Estas respuestas ya están fijadas y resuelven
varios de los antiguos puntos `⚠️ DECIDE`.

- **Anfitrión:** Qubes OS, ejecutándose dentro de una **AppVM Debian** (basada en plantilla).
- **Python:** **3.13 como intérprete por defecto.**
- **Usuario:** un **único usuario principal (el propietario del proyecto)** — sin cuentas multiinquilino, sin RBAC.
- **Superficie:** **interfaz web + API REST ligadas solo a `127.0.0.1`** (loopback). Sin escuchas externas.
- **Postura de red:** local primero; salida solo durante el scraping o la descarga de modelos LLM; **nada entrante**.

#### 0.1 Qué cambia Qubes en el diseño

Qubes no es «simplemente Debian». Su modelo de seguridad y el ciclo de vida de las AppVM imponen restricciones estrictas que el
instalador y el entorno de ejecución **deben** respetar:

1. **La persistencia del sistema de archivos es selectiva.** En una AppVM, solo **`/home`, `/usr/local` y `/rw`**
   sobreviven a un reinicio; el sistema de archivos raíz se **restablece desde la TemplateVM en cada arranque**. Por tanto:
   - La aplicación, su virtualenv, la base de datos, los datos recopilados, los registros, el rastro de auditoría y cualquier modelo LLM
     descargado **deben residir en `/home/user/...`** (recomendado: `/home/user/open-omniscience`).
   - **Los paquetes `apt`/del sistema *no* persisten** si se instalan en la AppVM. Las dependencias del sistema deben
     instalarse **en la TemplateVM** (y reiniciar la AppVM), o incorporarse mediante los `bind-dirs` de Qubes.
     El instalador debe **separar**: «dependencias del sistema → TemplateVM» frente a «venv de Python + aplicación → `/home` de la AppVM».
2. **No se presupone una raíz persistente.** Los cambios en la raíz de la AppVM desaparecen al reiniciar. Hay que tratar la AppVM como:
   `/home` persistente, raíz efímera.
3. **Red a través de una NetVM.** La AppVM solo llega a internet a través de su qube de red/cortafuegos asignado.
   La aplicación debe **degradarse limpiamente sin conexión** y no presuponer nunca la conectividad.
4. **Sin GPU.** El paso de GPU es poco práctico en las configuraciones habituales de Qubes → **la inferencia LLM es solo por CPU**.
   Por defecto, **modelos pequeños** (p. ej. `gemma2:2b`, `llama3.2:3b`, `qwen2.5:1.5b`); los modelos grandes, a elección del usuario.
5. **El aislamiento físico / la división en varias VM es una opción *futura* de primer orden (no en la v1).** Qubes hace natural el patrón «scraping ético en un
   qube con red, análisis/almacenamiento en un qube bóveda sin conexión» mediante **qrexec/qubes-rpc**. La v1
   se ejecuta en **una sola AppVM**; la arquitectura debe mantener limpia la frontera de *obtención* para que una división posterior sea un
   cambio de despliegue, no una reescritura. (El repositorio ya contiene material residual en `src/qubes/rpc/` y
   `docs/QUBES_*` — que hay que revisar o sustituir, no dar por fiable.)

#### 0.2 Implicaciones de Python 3.13 (resuelve los conflictos de versiones de dependencias)

- **La pila central es compatible con 3.13:** FastAPI, uvicorn, SQLAlchemy 2.x, pydantic 2.x, requests, httpx,
  beautifulsoup4, feedparser, numpy, pandas, scipy, scikit-learn, statsmodels — todos publican wheels para 3.13.
- **El LLM local NO requiere ML pesado en Python.** Ollama es un **binario nativo independiente**; la aplicación se comunica
  con él **solo por HTTP**. La capacidad LLM completa funciona en 3.13 con solo `httpx`/`requests` — sin
  `torch`/`transformers` en la aplicación.
- **Las bibliotecas de ML pesadas salen del núcleo.** `torch`, `onnx`/`onnxruntime`, `tensorflow`,
  `pyAudioAnalysis` y la pila de deepfakes se **eliminan** en la v1 porque (a) actualmente son
  **fabricadas** (la «CNN de deepfakes» nunca ejecuta inferencia), (b) pesadas y **solo por CPU aquí**, y
  (c) un riesgo de wheel para 3.13 paquete por paquete (`pyAudioAnalysis` no tiene mantenimiento; `igraph`/`leidenalg`/`gensim`
  deben verificarse uno a uno antes de usarse). Toda futura funcionalidad de ML debe justificar su peso y demostrar que existe un wheel para 3.13.
- **Un único manifiesto de dependencias, fijado a 3.13.** Sustituir los seis archivos de requisitos discordantes por un único
  `pyproject.toml` en la raíz (`requires-python = ">=3.13"`) + extras opcionales (`[llm]`, `[analysis]`, `[dev]`).
  Eliminar los comentarios «correctivos» generados por IA y las fijaciones de versión imposibles.

#### 0.3 Modelo de seguridad para un único usuario local (simplifica los P0)

Como la única escucha es loopback y el único usuario es usted:
- **Autenticación:** no se requiere en la v1 *siempre que* el servidor se ligue estrictamente a `127.0.0.1` y nunca quede expuesto
  por una regla del cortafuegos de Qubes. (Más adelante puede añadirse un único token de API opcional si se usa un proxy.) Esto **resuelve**
  el hallazgo «endpoints sin autenticación» *para este despliegue* — eliminando la exposición de red en lugar de
  añadir RBAC.
- **`/metrics`:** solo loopback, como todo lo demás.
- **La seguridad del instalador sigue siendo obligatoria:** ningún `rm -rf` sin confirmar, ningún `curl | sh` sin verificar, no descartar nunca
  el stderr del gestor de paquetes — son problemas de corrección y seguridad con independencia de que haya un solo usuario.
- **Recursos del front-end alojados localmente** (sin Google Fonts / React por CDN) — necesario para el modo sin conexión/Qubes y
  para el principio de privacidad.

---

### 1. Definición en una frase

Open-Omniscience es una **plataforma de inteligencia de código abierto, local primero, para periodistas de investigación**
que agrega de forma ética numerosas fuentes de datos de todo el mundo en un **corpus único, consultable, con referencias cruzadas
y con trazabilidad de procedencia**, con **IA local** opcional para el análisis — y en la que cada resultado está
diseñado para ser **defendible científica y jurídicamente**.

### 2. Para quién es y qué trabajos le encargan

**Usuario principal:** un periodista de investigación, investigador o analista — probablemente trabajando solo o en una
pequeña redacción, a menudo sensible a la privacidad (fuentes que proteger), a veces en entornos restringidos o aislados físicamente.

**Trabajos principales por hacer:**
1. *«Recopilar todo lo relevante para mi investigación desde muchas fuentes, en un solo lugar, automáticamente.»*
2. *«Buscar y cruzar todo a la vez — artículos, mercados, correos — para encontrar conexiones.»*
3. *«Ayúdame a entender grandes volúmenes de texto»* (resumir, traducir, extraer entidades) — **sin
   enviar mis datos a nadie.**
4. *«Dime en qué puedo confiar — o desconfiar»* (verificar medios, señalar manipulaciones).
5. *«Demostrar de dónde viene esto y que no lo he alterado»* (procedencia para la publicación o un procedimiento judicial).
6. *«Avísame cuando algo cambie»* (una fuente deja de responder, un precio se dispara, surge una narrativa).

### 3. Principios rectores (los no negociables)

Son el núcleo de la intención y deben condicionar cada funcionalidad. Allí donde el código actual viole uno,
se trata de un defecto, no de una concesión.

1. **Local primero y capaz de funcionar sin conexión.** Se ejecuta íntegramente en la máquina o el servidor del usuario. Debe funcionar sin
   internet salvo durante el propio scraping. Apto para uso con aislamiento físico (con datos y modelos preparados de antemano).
2. **Respetuoso con la privacidad.** Sin telemetría. **Ningún dato del usuario sale nunca de la máquina** — en especial el procesamiento LLM
   (solo local, mediante Ollama). ✅ RESUELTO (§0): todos los recursos del front-end (fuentes tipográficas, bibliotecas JS) están
   **alojados localmente** — sin llamadas a CDN — requisito para la postura Qubes/sin conexión.
3. **100 % FOSS.** Todo el código y los modelos son de código abierto. ⚠️ DECIDE: la licencia es **GPLv3** en la raíz pero
   **AGPL-3.0** en el Pilar 3 — elegir una para todo el proyecto (AGPL es más estricta para el uso en red).
4. **Ético por construcción.** Respetar `robots.txt` y los límites de frecuencia, identificar el bot, solo datos públicos,
   no eludir nunca muros de pago ni usar credenciales para hacer scraping. **Fallar *cerrado*** — si no se puede verificar
   el cumplimiento, no se hace scraping.
5. **Resultados defendibles (científica y jurídicamente).** Todo resultado analítico lleva una incertidumbre honesta y
   una procedencia trazable. **Ningún número fabricado.** Una puntuación de confianza debe proceder de un método real, o
   no existir. La cadena de custodia debe ser real (firmada, a prueba de manipulaciones), no un simple archivo de registro.
6. **Corpus unificado.** Todo lo ingerido — noticias, datos financieros, materias primas, correo — vive en **una sola
   base de datos** y **se puede cruzar en una sola consulta**. Es la razón de ser del producto.
7. **Transparencia antes que un fallo elegante.** El sistema nunca debe degradarse en silencio hasta producir resultados inválidos.
   Modelo ausente, fuente bloqueada, dependencia no disponible → **estado visible y explícito**, nunca un
   marcador de posición silencioso.

### 4. El modelo mental central

```
        ┌─────────────────────────── INGESTION ───────────────────────────┐
        │  Web articles · RSS · Financial · Commodities · Email/Newsletters │
        │            (all ethically scraped / retrieved)                    │
        └───────────────────────────────┬───────────────────────────────────┘
                                         ▼
        ┌──────────────────── ONE UNIFIED, PROVENANCE-TRACKED STORE ────────┐
        │  articles · financial_data · commodity_data · emails · entities    │
        │  + links between them (article ↔ price move ↔ email ↔ entity)      │
        └───────────────────────────────┬───────────────────────────────────┘
                                         ▼
   ┌──────────── RETRIEVAL ────────────┐   ┌──────────── ANALYSIS (opt-in) ───────────┐
   │ Boolean / full-text search        │   │ Local LLM · verification · stats ·        │
   │ filters · cross-source correlation│   │ monitoring/alerts · correlation engines   │
   │ export (CSV/JSON) · reports       │   │ (every result: method + uncertainty)      │
   └───────────────────────────────────┘   └───────────────────────────────────────────┘
                                         ▼
                         GUI (search, dashboards, source mgmt, reports)
                         + REST API (everything available programmatically)
```

**La columna vertebral (ingesta → almacén unificado → búsqueda → exportación) debe ser sólida como una roca antes que cualquier pilar.**
Los pilares son *enriquecedores* que leen del almacén compartido y escriben de vuelta en él.

---

### 5. Alcance funcional, por área de capacidad

#### 5.1 Ingesta de datos (P0)
- **Tipos de fuente:** sitios web de noticias (HTML), feeds RSS/Atom. Más adelante: API, plataformas sociales, depósitos de archivos.
  ⚠️ DECIDE: el Pilar 4 enumera Twitter/X, Reddit, Telegram, Mastodon, S3/SFTP — confirmar cuáles (si alguno)
  entran realmente en el alcance y cuáles son aspiracionales.
- **Scraper ético (implementación única y compartida):** comprobación de robots.txt (en caché, consciente de http+https,
  **falla cerrado** ante la incertidumbre), limitación de frecuencia por fuente, User-Agent identificativo, reintentos con espera progresiva.
  **Una sola obtención por URL** — sin doble descarga, sin vía directa que lo eluda.
- **Deduplicación:** basada en hash del contenido + URL canónica; nunca almacenar dos veces el mismo artículo.
- **Normalización:** extraer de forma fiable título, autor, fecha de publicación, idioma, URL canónica y cuerpo del texto.
  ⚠️ DECIDE: una extracción real de noticias necesita reglas por sitio o una biblioteca (p. ej. del estilo de trafilatura); el
  enfoque genérico actual por CSS produce en silencio «No Title/No Content». Confirmar que adoptamos una extracción robusta.
- **Programación y actualizaciones incrementales:** nuevo scraping periódico, obtener solo el contenido nuevo o modificado, reanudar
  las ejecuciones interrumpidas.

#### 5.2 Almacén de datos unificado (P0)
- **Una sola base de datos** que contiene todos los tipos de entidad, con **tablas de enlace** explícitas que los conectan
  (artículo ↔ instrumento financiero, artículo ↔ materia prima, artículo ↔ correo, artículo ↔ entidad nombrada).
- **Campos de procedencia en cada registro:** fuente, marca de tiempo de obtención, URL original, hash del contenido,
  separación entre datos brutos y procesados.
- **Motores:** SQLite para un solo usuario/escritorio; PostgreSQL para servidor/uso concurrente.
  ⚠️ DECIDE: confirmar SQLite por defecto + Postgres opcional (los documentos mencionan ambos; también Redis para caché —
  ¿dentro o fuera?).
- **Registro de auditoría:** de solo adición, **a prueba de manipulaciones**, de cada ingesta y cada modificación.

#### 5.3 Búsqueda y recuperación (P0)
- **Búsqueda de texto completo** en todo el corpus.
- **Operadores booleanos** (`AND`/`OR`/`NOT`), **frases entre comillas** y **paréntesis con la precedencia
  correcta** — implementados con una gramática real o con el FTS nativo de la base de datos, no con apaños de cadenas.
- **Filtros estructurados:** fuente, intervalo de fechas, idioma, etiquetas/categoría, entidad, tipo de dato.
- **Paginación**, ordenación de resultados, fragmento/resaltado.
- **Exportación:** CSV y JSON (y ⚠️ DECIDE: ¿formatos PDF/informe?), fiel al conjunto de resultados filtrado.

#### 5.4 Referencias cruzadas y correlación (P1 — el elemento diferenciador)
- Pasar de cualquier registro a registros relacionados de otros tipos (artículo → empresas mencionadas → movimientos de precio
  cercanos a la fecha de publicación → correos relacionados).
- **Motores de correlación** (financiero/materias primas ↔ noticias) que presentan relaciones *candidatas* con una
  **medida honesta y definida** (e indican claramente que correlación ≠ causalidad). Ningún valor p fabricado.
- Vista centrada en la entidad: todo lo que el corpus sabe sobre una persona, organización, lugar o instrumento.

#### 5.5 Análisis con LLM local (P1)
- **Entorno de ejecución:** Ollama, totalmente local. Los modelos son intercambiables; incluir un valor por defecto pequeño y sensato que *exista
  realmente*. ⚠️ DECIDE: el valor por defecto actual `gemma4:e2b` y la mayoría de los modelos listados (Gemma 4, Llama 4, Qwen 3.5)
  son alucinados — sustituir el catálogo por etiquetas reales (p. ej. `gemma2:2b`, `llama3.2:3b`, `qwen2.5`,
  `phi3`).
- **Capacidades:** generar, conversar (con contexto), extraer (entidades/palabras clave/resúmenes/citas/enlaces),
  traducir (varios idiomas), analizar (sentimiento/tono/legibilidad; sesgo solo si está honestamente acotado),
  sintetizar (resúmenes, comparaciones, cronologías, informes), por lotes.
- **Degradarse de forma visible:** si Ollama o el modelo no están, decirlo — nunca devolver un análisis falso.

#### 5.6 Verificación y defensa contra el engaño — *Pilar 3* (P2, alcance por definir)
- **Intención:** detectar medios manipulados (deepfakes de imagen/vídeo/audio), técnicas de propaganda, sesgos
  cognitivos, bots y campañas coordinadas; validar metadatos (EXIF/ID3) y la coherencia entre modalidades.
- ⚠️ DECIDE (importante): hoy esto es **fabricado** — la «CNN de deepfakes» nunca ejecuta inferencia; las puntuaciones
  son heurísticas de desenfoque; la cobertura de sesgos y propaganda es en su mayor parte inalcanzable; «precisión >95%» es aspiracional.
  Elegir una opción:
  - **(a) Recortar** de momento el análisis forense de medios y ofrecer solo lo honesto (la validación de metadatos/EXIF es real
    y útil); **(b) Reconstruir** con modelos FOSS genuinos y evaluados, con precisión publicada; o
    **(c) Mantener** pero **etiquetar claramente como «heurística experimental, no prueba».**
  Mi recomendación: (a) ahora, (b) más adelante. Un análisis forense fabricado es el mayor riesgo, con diferencia, para una
  herramienta periodística o jurídica.

#### 5.7 Rigor científico — *Pilar 2* (P1)
- **Intención:** hacer defendibles las afirmaciones cuantitativas de la plataforma — pruebas estadísticas reales, intervalos
  de confianza, puntuación de reproducibilidad/linaje y «revisión por pares» mediante varios LLM locales que se contrastan entre sí.
- Este pilar es el implementado de forma más genuina (scipy/statsmodels reales). Mantenerlo, reforzarlo y convertirlo en el
  **guardián**: cualquier número que la aplicación muestre al usuario debe pasar por una presentación honesta de la incertidumbre.

#### 5.8 Supervisión y alertas en tiempo real — *Pilar 4* (P2)
- **Intención:** vigilancia continua de las fuentes; detección de anomalías, tendencias y patrones; enriquecimiento con inteligencia de amenazas;
  alertas multicanal (correo/webhook/chat) con reglas y escalado.
- ⚠️ DECIDE: las comprobaciones de estado actuales son simuladas (`sleep; return HEALTHY`) y la inteligencia de amenazas/STIX-TAXII
  no existe. Confirmar el alcance: una supervisión real de la disponibilidad de las fuentes + alertas de anomalías sobre el corpus es
  alcanzable y valiosa; STIX/TAXII, SMS/Twilio, Slack/Teams son pesados — ¿dentro o fuera?

#### 5.9 Inteligencia financiera — *Pilar 5* (P2, marcado al 0% en la documentación)
- **Intención:** hacer scraping de bolsas de todo el mundo (OHLC + fundamentales) desde fuentes web abiertas (sin API ni muros de pago),
  detectar fluctuaciones, patrones y anomalías, y **correlacionar los movimientos de precios con las noticias** en la base de datos compartida.
- ⚠️ DECIDE: esto es **solo diseño (0% construido)** pese al código de andamiaje ya confirmado en el repositorio. Confirmar que es un objetivo real
  y, en tal caso, su primer alcance realista (p. ej. un puñado de bolsas, OHLC diario, correlación con
  artículos) en lugar de «más de 50 bolsas / más de 10.000 empresas» desde el primer día. Nota: un scraping robusto de varias bolsas
  sin API es una tarea grande y frágil.

#### 5.10 Inteligencia sobre tierras raras / materias primas — *Pilar 6* (P2, marcado al 0% en la documentación)
- **Intención:** el mismo patrón que el Pilar 5 para los 17 elementos de tierras raras — precios, producción, inventario,
  correlacionados con acontecimientos geopolíticos o informativos; con previsiones.
- ⚠️ DECIDE: también es **solo diseño (0% construido)**. Confirmar el alcance y la prioridad frente al Pilar 5. (Corrección necesaria: el
  cálculo de unidades en la normalización de precios está actualmente equivocado en un factor de ~1000×, y la moneda no se convierte.)
  ⚠️ DECIDE: ¿entra la «previsión» en el alcance? Una previsión honesta con incertidumbre es difícil; se recomienda aplazarla.

#### 5.11 Inteligencia sobre correo y boletines (P1/P2)
- **Intención:** obtener mensajes por IMAP/POP3 y de fuentes de boletines (Substack/Mailchimp/RSS-a-correo), analizarlos y
  limpiarlos, gestionar los adjuntos (PDF/Office/imágenes con OCR), extraer entidades y redes de comunicación,
  e **incorporarlos al mismo corpus consultable**.
- **La privacidad y el consentimiento son primordiales aquí** (comunicaciones privadas): autorización explícita, almacenamiento cifrado
  de credenciales, minimización de datos, conservación/derecho al olvido.
- ⚠️ DECIDE: ¿integraciones con API de boletines (Substack/Mailchimp/etc.) o solo IMAP + RSS-a-correo para la v1?

#### 5.12 Interfaz gráfica / UX (P0 para el núcleo, P1+ para los paneles de los pilares)
- **Interfaz central:** interfaz de búsqueda, exploración de resultados, gestión de fuentes, exportación, paneles básicos.
- **Paneles de los pilares (más adelante):** mapas de calor y gráficos financieros, vistas de materias primas, supervisión/alertas, bandeja
  de correo, explorador de correlaciones.
- ✅ RESUELTO (§0): **interfaz web servida por FastAPI en `127.0.0.1:8000`; se abandona la aplicación de escritorio Tkinter**
  (eliminar `python3-tk`). Se abre en el navegador de la AppVM.
- ✅ RESUELTO (§0): el front-end es **JS puro + bibliotecas alojadas localmente (servidas desde `/static`)** — sin CDN.
  ⚠️ DECIDE (menor): ¿gráficos ligeros (p. ej. una pequeña biblioteca de gráficos alojada localmente) o ninguno en la v1?

#### 5.13 Informes y resultados defendibles (P1)
- Generar informes de investigación que agrupen los hallazgos **con su procedencia** (fuentes, marcas de tiempo,
  hashes, métodos, incertidumbre).
- **Cadena de custodia / integridad:** firma criptográfica + detección de manipulaciones en las pruebas exportadas
  (los módulos criptográficos existen pero no están conectados). Esto es lo que hace que la afirmación de «admisibilidad jurídica» sea
  real y no decorativa.

---

### 6. Requisitos no funcionales

- **Plataforma:** ✅ RESUELTO (§0) — la **AppVM Debian de Qubes OS** es el *único* destino soportado en la v1
  (compilado y probado allí). Debian 13 a secas puede funcionar, pero no es un objetivo; sin compromiso multiplataforma.
- **Python:** ✅ RESUELTO (§0) — **3.13**, de forma coherente en `pyproject.toml`, `.python-version` y
  cualquier CI. Eliminar las dependencias que no tengan wheels para 3.13 (ver §0.2).
- **Huella de instalación:** un **núcleo mínimo** de verdad (web + base de datos + búsqueda, ligero) separable de los extras
  opcionales (`[llm]`, `[analysis]`). **Un único** `pyproject.toml` — no seis manifiestos discordantes. El instalador
  respeta la persistencia de Qubes (§0.1): dependencias del sistema en la TemplateVM, venv+datos en `/home`.
- **Seguridad:** ✅ RESUELTO (§0) — un solo usuario local, **solo loopback**, así que sin RBAC. Sigue siendo obligatorio:
  acceso a la base de datos solo parametrizado (eliminar el «saneador» por lista de bloqueo), ningún secreto en el código, `/metrics` en loopback,
  y un **instalador seguro** (ningún `rm -rf` sin confirmar, ningún `curl | sh` sin verificar, no descartar nunca el stderr de los paquetes).
- **Rendimiento:** E/S no bloqueante para el trabajo de red y LLM; concurrencia acotada; la aplicación sigue respondiendo mientras
  hace scraping o inferencia. Supuestos **solo CPU** (sin GPU en Qubes). Objetivos definidos según los recursos realistas de la AppVM,
  no aspiracionales.
- **Sin conexión:** todos los recursos, fuentes tipográficas y modelos (descargados de antemano) en local; procedimiento documentado para operar con la
  NetVM desconectada una vez obtenidos los datos y los modelos.
- **Observabilidad:** registros estructurados (en `/home`), comprobaciones de estado honestas, métricas Prometheus en loopback —
  que reflejen el estado real.

### 7. Lo que explícitamente no es objetivo / queda fuera del alcance (propuesta — ajustar)

- No es un rastreador web ni un espejo de uso general (el linaje HTTrack es residual; abandonar ese enfoque).
- No es un scraper que eluda muros de pago, practique el relleno de credenciales o viole condiciones de servicio.
- No es un producto en la nube/SaaS; ninguna API de IA externa.
- ⚠️ DECIDE: ¿la previsión (5.10), la ingesta de redes sociales (5.8) y el análisis forense de medios (5.6) están dentro o fuera
  de la primera versión real?

### 8. Modelo de datos, procedencia y defendibilidad jurídica (transversal)

- Cada elemento almacenado: `{source, original_url, fetched_at, content_hash, raw_payload_ref, processing_log}`.
- Cada resultado derivado/analítico: `{method, version, inputs_ref, uncertainty/confidence_basis,
  computed_at}` — **la confianza nunca es una constante fija en el código.**
- Pruebas exportadas: opcionalmente **firmadas**, con un manifiesto verificable (hashes + Merkle/GPG) para que un
  tercero pueda confirmar su integridad. Este es el significado concreto de «Pilar 4: admisibilidad jurídica».

### 9. Decisiones (consolidadas)

**✅ Resueltas por el contexto de despliegue (§0):**
- **3. Despliegue y modelo de amenazas** → un solo usuario local, AppVM Debian de Qubes, solo loopback, sin RBAC.
- **7. Interfaz gráfica** → interfaz web en `127.0.0.1:8000`, JS puro, recursos alojados localmente; Tkinter abandonado.
- **8. Plataforma/Python** → AppVM Debian de Qubes, Python 3.13, SQLite por defecto (Postgres/Redis **fuera** en la v1).

**⚠️ Aún abiertas (la decisión es suya — se proponen valores por defecto sensatos):**
1. **Alcance del MVP:** *propuesta* — primero solo el Núcleo fiable (Fase 1), después el LLM. Confirmar.
2. **Estrategia de reconstrucción:** *propuesta* — rescatar las pocas partes buenas (modelos de base de datos, `ethical_scraper`,
   `async_db`, esqueleto FastAPI), eliminar los pilares fabricados y reconstruir el núcleo a su alrededor. Confirmar frente a
   empezar de cero.
4. **Análisis forense de medios (Pilar 3):** *propuesta* — **(a) recortar** deepfakes/propaganda/sesgos en la v1 (además
   hostiles a 3.13/CPU), **mantener** la validación real de metadatos/EXIF. Confirmar.
5. **Financiero (5) y materias primas (6):** *propuesta* — aplazar a la Fase 3 y construir **una sola** vertical fina.
   ¿Cuál primero?
6. **Correo:** *propuesta* — solo IMAP + RSS-a-correo en la v1; aplazar las integraciones con API de boletines. Confirmar.
9. **Licencia:** GPLv3 o AGPL-3.0 para todo el proyecto — aún falta una decisión.
10. **Confirmación de lo que queda fuera del alcance:** previsión, ingesta de redes sociales, STIX/TAXII, alertas por SMS/chat —
    *propuesta*: fuera en la v1.

### 10. Fases sugeridas (propuesta, no compromiso)

- **Fase 1 — Núcleo fiable:** ingesta ética → almacén unificado (con procedencia) → búsqueda booleana/
  de texto completo correcta → exportación → interfaz web mínima → pruebas reales. *Todo lo demás desactivado hasta que esto esté en verde.*
- **Fase 2 — LLM local + rigor científico:** conectar Ollama (modelos reales, degradación visible); convertir el Pilar 2
  en la barrera de honestidad para cualquier número mostrado.
- **Fase 3 — Una vertical + correlación:** elegir **o bien** financiero **o bien** materias primas, construir una porción fina pero
  real y demostrar de principio a fin la experiencia de correlación artículo↔datos.
- **Fase 4 — Supervisión/alertas, correo, verificación (primero los metadatos):** añadir los enriquecedores de uno en uno,
  cada uno funcionando de verdad y probado.
- **Fase 5 — Informes defendibles:** conectar una firma y una cadena de custodia reales a las exportaciones.

---

### 11. Estado de implementación (actual)

Lo que está construido y probado hoy, en relación con el alcance anterior (la intención no cambia; estas
notas indican dónde se encuentra ahora la realidad). Consulte los documentos de funcionalidades enlazados para más detalle.

- **Núcleo fiable (5.1–5.3, 5.13):** ✅ ingesta ética, almacén unificado con procedencia,
  búsqueda booleana FTS5, exportación CSV/JSON, cadena de custodia firmada.
- **Ingesta a escala (5.1):** ✅ **programador** integrado en la aplicación (iniciar/detener, intervalo, modos
  rss/crawl/markets) y un **rastreador recursivo acotado** (*descubrimiento* dentro del mismo dominio,
  robots con fallo cerrado, límites de profundidad/páginas) — no un espejo de uso general (§7 respetado).
- **Interfaz gráfica (5.12):** ✅ interfaz web con pestañas — Búsqueda · Ingesta · **Fuentes y base de datos** (estadísticas,
  gestión de fuentes, **cobertura mundial**) · **Mercados** · **Perspectivas** · Cadena de
  custodia · **Ajustes** (tema + copia de seguridad/restauración de SQLite). Sin dependencias, sin conexión.
- **Financiero y materias primas (5.9, 5.10):** ✅ vertical real y fina — **reglas de extracción** de precios
  por fuente, **feeds CSV oficiales** (FRED→Banco Mundial/EIA), gráficos y
  correlación honesta precio↔noticias. Cálculo de unidades corregido; números solo a partir de una regla verificada
  o de un CSV importado. Ver [USER_MANUAL.md](USER_MANUAL.md).
- **Cobertura mundial de fuentes:** ✅ catálogo de mercados empaquetado + un **generador
  derivado de datos** (Wikidata CC0) para medios de comunicación **e** instituciones por país, con un
  informe de cobertura. Importación/exportación CSV de la lista de fuentes. Ver
  [ROADMAP.md](archive/roadmaps/DESIGN_MEMORY_pre-0.2.md).
- **Referencias cruzadas y correlación (5.4):** ✅ **analítica de palabras clave y entidades** —
  extracción en la ingesta, almacén de menciones con contexto, tendencias, asociaciones PMI
  («mapa mental») y un mapa por país/ciudad. Ver [USER_MANUAL.md](USER_MANUAL.md).
- **Wikipedia como fuente seguida (nuevo):** 🚧 base del seguimiento de cambios (ediciones
  por idioma, almacenamiento de deltas, señalización de ediciones grandes/revisionismo incl. ORES) — esquema +
  analizador + señalización hechos; sondeo en vivo, pestaña y descargador sin conexión a continuación. Ver
  [USER_MANUAL.md](USER_MANUAL.md).
- **Verificación (5.6):** ✅ solo metadatos/EXIF de imagen honestos (el análisis forense fabricado
  sigue en cuarentena). **LLM (5.5)**, **supervisión/alertas (5.8)**, **correo (5.11)**:
  parciales/en cola.

---


---

## Mapa de intenciones de los pilares — dónde vive ahora el propósito de cada pilar

El diseño original organizaba la plataforma en seis «pilares». Esos árboles de pilares
sumaban ~50k líneas que la aplicación en ejecución nunca importaba — en su mayoría solo diseño o
fabricadas. **Su *intención* se ha conservado**: el propósito genuino de cada pilar
es ahora un módulo pequeño, honesto y probado dentro de `src/` (o está explícitamente aplazado).
Los árboles de pilares originales se conservan en `quarantine/pillars/` como referencia e
historial; no se borra nada.

| Pilar (intención) | Dónde vive ahora la intención | Estado |
|---|---|---|
| **1 — Ingesta de datos** (scraping ético → almacén unificado) | `src/ingest/` (fetcher, extract, pipeline, email) + `src/database/` | ✅ Real, probado |
| **2 — Rigor científico** (estadística honesta, incertidumbre) | `src/analysis/` (`statistical_tests`, `confidence_intervals`) + `POST /api/analysis/*` | ✅ **Se rescató el código genuino de scipy/statsmodels** + sus 60 pruebas |
| **3 — Defensa contra el engaño** (verificar medios) | `src/verification/metadata.py` (EXIF/metadatos honestos) + `POST /api/verify/image-metadata` | ✅ Alcance honesto. Los detectores de deepfakes/propaganda/sesgos eran fabricados → `quarantine/pillar3_analysis/` |
| **4 — Supervisión + admisibilidad jurídica** | `src/monitoring/` (disponibilidad real + anomalías) y `src/reporting/` + `src/crypto/` (pruebas firmadas con Merkle + Ed25519) | ✅ Real, probado |
| **5 — Inteligencia financiera** | *Aplazado.* El patrón queda demostrado por la reimplementación del Pilar 6; una vertical financiera puede reutilizar `src/commodity` + `src/analysis`. | ⏸ Solo diseño en origen (0%); aún no construido |
| **6 — Tierras raras / materias primas** | `src/commodity/` (precios, conversión de unidades correcta, correlación scipy **real**, importación CSV) + `POST /api/commodities/*` | ✅ Real, probado |

### Qué se rescató en este paso (Pilar 2)
- `src/analysis/statistical_tests.py` — pruebas t, ANOVA, chi cuadrado, Pearson/Spearman,
  Mann-Whitney, Wilcoxon, regresión, Tukey HSD (scipy/statsmodels). Cada resultado
  incluye estadístico, valor p, grados de libertad, tamaño del efecto y tamaño muestral.
- `src/analysis/confidence_intervals.py` — medias y proporciones (t/normal/Wilson/
  Clopper-Pearson/Agresti-Coull).
- Expuesto en `POST /api/analysis/{t-test,correlation,anova,mann-whitney,confidence-interval}`
  para que un periodista pueda comprobar si un patrón en sus datos es realmente significativo.
- Las suites de pruebas genuinas del Pilar 2 se trasladaron junto con el código (`tests/test_statistical_tests.py`,
  `tests/test_confidence_intervals.py`).

### Qué NO se rescató (y por qué)
- `peer_review` / `consensus` / `reproducibility` del Pilar 2 — especulativos o superficiales
  (p. ej. la reproducibilidad era una rúbrica que promediaba booleanos). Aparcados; se recuperarán con métodos
  reales si hace falta.
- Los detectores forenses del Pilar 3, la supervisión simulada y la inteligencia de amenazas del Pilar 4, los andamiajes de los Pilares
  5/6 — fabricados o solo diseño; las piezas honestas ya están en `src/`.

### Efecto neto
El repositorio refleja ahora lo que realmente se ejecuta: un núcleo activo de ~16k líneas (más la
estadística rescatada), con las ~50k líneas de pilares aspiracionales/fabricados aparcadas en
`quarantine/pillars/` en lugar de hacerse pasar por funcionalidades operativas.


---

## Rediseño de la interfaz — «0.05»

> Un rediseño desde cero de la interfaz de Open Omniscience, razonado desde el usuario
> hacia fuera. Este documento es el *porqué*; `src/static/index.html` es el *qué*.
> Léalo primero si quiere entender (o discutir) las decisiones.

---

### 0. El encargo, reformulado

Rediseñar toda la interfaz gráfica para una persona concreta: **un agente en busca de la verdad — un
investigador/periodista *poco amigo* de los ordenadores**, que quiere entender
el mundo tal como es realmente y comunicar sus hallazgos de forma creíble. El resultado debe ser
pulido, bello, adaptable, muy personalizable, sencillo *y* profundo, y lo bastante bueno
como para que un colega que mire por encima del hombro diga *«¿qué es esto? ¿me lo puedo
quedar?»*. Debe respetar lo que el proyecto ya es: **un solo usuario, solo loopback,
sin conexión primero, sin dependencias, sin telemetría**, regido por la **Carta de Múnich**
(verdad, verificación de las fuentes, privacidad, nada de propaganda).

#### Postura de ingeniería (y la concesión honesta)

La interfaz anterior es un único `index.html` de 2.200 líneas que conecta ~110 funciones con ~150
endpoints de la API. Esas funciones *funcionan y están probadas*. Una reescritura desde cero habría
producido un envoltorio más bonito con muchas probabilidades de botones rotos en silencio — justo lo
contrario de lo que necesita una herramienta cuyo principal argumento es la **honestidad**. Así que se trata de un
**rediseño total de todo lo que el usuario ve y toca** — lenguaje visual,
disposición, modelo de navegación, arquitectura de la información, nomenclatura, incorporación,
personalización y dos superficies totalmente nuevas (un panel de Inicio y un lector de
documentación integrado) — construido *sobre la capa de datos ya probada*, conservando todos los ID de elementos
originales para que nada retroceda. La ausencia de dependencias sigue siendo absoluta: **sin CDN, sin fuentes
web, sin framework** — un único archivo autónomo que funciona con la NetVM desconectada.

---

### 1. Personas (a quién servimos realmente)

**Amara — periodista de investigación, 44 años. Persona principal.**
Cubre la corrupción en la contratación pública. Reportera brillante, usuaria reacia de los ordenadores. Trabaja
en historias sensibles y es (con razón) muy desconfiada respecto a la vigilancia y la pérdida de datos.
*Necesita:* encontrar cosas rápido en su propio corpus; demostrar que un documento es auténtico e
inalterado; exportar algo que pueda entregar a un editor o a un tribunal; no sentirse nunca torpe.
*Teme:* perder trabajo, que la rastreen, la jerga, parecer una aficionada al lado de un colega «tecnológico».
*Condición de éxito:* abre la aplicación y sabe de inmediato qué hacer, y lo que
produce parece fiable *y lo es*.

**Daniel — investigador OSINT autónomo, 29 años. Persona avanzada.**
Semitécnico, rápido, usa el teclado, maneja muchas fuentes. *Necesita:* densidad, operaciones
por lotes, tendencias/asociaciones, correlaciones con los mercados, atajos de teclado, una paleta
de comandos. *Teme:* que lo lleven de la mano y lo ralenticen; funcionalidades ocultas.
*Condición de éxito:* nunca tiene que tocar el ratón y encuentra la potencia avanzada a mano.

**La hermana de la causa — la «agente», unos 50 años. Persona de valores.**
Desconfía de las grandes tecnológicas; quiere soberanía. *Necesita:* pruebas de que nada se comunica con el exterior; funcionamiento
sin conexión; explicaciones claras de lo que cada acción supone para su exposición en la red.
*Condición de éxito:* puede leer, en la propia aplicación, exactamente lo que hará y lo que no hará.

**Elliot — el editor, 38 años. Persona destinataria.**
Nunca abre la aplicación; *recibe* sus resultados. *Necesita:* exportaciones legibles y
verificables por sí mismas. La interfaz le sirve indirectamente: paquetes de pruebas, custodia
firmada, CSV/JSON limpios.

**Implicación de diseño:** diseñar en primer lugar para Amara (claridad, guía, confianza), añadir por capas la profundidad
de Daniel para que nunca le estorbe a ella (divulgación progresiva + paleta de comandos),
honrar la soberanía de la agente en los textos y en el comportamiento, y convertir los artefactos de Elliot
en ciudadanos de primera clase.

---

### 2. Principios de diseño (derivados, no prestados)

1. **Claridad antes que ingenio.** Verbos sencillos, etiquetas humanas, una sola acción principal
   evidente por pantalla. La jerga («ingesta», «corpus», «raíz de Merkle») se traduce o se
   explica en el propio texto, nunca se da por sabida.
2. **La confianza es el producto.** La verificabilidad, la procedencia y el «este número es real,
   no estimado» se muestran, no se entierran. La estética debe *sentirse* como un
   instrumento, no como un juguete.
3. **Divulgación progresiva.** Sencillo por defecto; la profundidad, a un clic. Los paneles
   avanzados se pliegan; los módulos poco usados pueden ocultarse por completo.
4. **Personalizable, porque la confianza es personal.** Temas, color de acento, densidad, tamaño de letra,
   disposición y *qué herramientas aparecen siquiera* los decide el usuario — y se guardan
   solo en local.
5. **Honestidad en la interfaz.** Si una capacidad depende de un extra opcional, la
   interfaz lo dice en lugar de fingir. Nada simula un éxito.
6. **Soberana por construcción.** Ninguna petición externa de ningún tipo. El aspecto se
   consigue con fuentes del sistema e iconos SVG dibujados a mano.
7. **Teclado primero es también accesibilidad primero.** Una paleta de comandos y atajos
   sirven a Daniel *y* hacen accesible toda la aplicación sin necesidad de manejar el ratón con precisión.

---

### 3. Análisis herramienta por herramienta — ventajas, inconvenientes, decisión

El antiguo conjunto de pestañas superiores: *Búsqueda · Ingesta · Fuentes · Base de datos · Mercados · Perspectivas ·
Wikipedia · Cadena de custodia · Ajustes.* Evaluadas una a una para nuestras personas.

| Pestaña antigua | Ventajas | Inconvenientes | **Decisión** |
|---|---|---|---|
| **Búsqueda** | El acto central. Todo el mundo la necesita. | Enterrada como una pestaña entre nueve; ninguna orientación para un usuario nuevo. | **Mantener y elevar.** Se convierte en el corazón, accesible al instante; un nuevo **Inicio** aporta orientación a su alrededor. |
| **Ingesta** | Necesaria para incorporar datos. | «Ingesta» es jerga de ingenieros; intimida; mezclaba el programador con la obtención manual. | **Mantener, renombrar → «Recopilar».** Empezar por la acción manual sencilla; el programador pasa a ser la «Recopilación automática», presentada como algo que se configura y se olvida. |
| **Fuentes** | Aquí reside la credibilidad; la procedencia empieza por el *dónde*. | Tablas densas; parecía administración, no periodismo. | **Mantener, replantear como «Fuentes» (la lista de temas y fuentes de su redacción).** Con un nuevo estilo para que se lea como una biblioteca, no como una consola de base de datos. |
| **Base de datos** | Recuentos en vivo honestos; copia de seguridad/restauración. | «Base de datos» no significa nada para Amara; ella tiene una *biblioteca/archivo*, no una base de datos. | **Mantener, renombrar → «Biblioteca».** Los mismos recuentos reales y la misma cobertura mundial, presentados como «lo que ha reunido». |
| **Mercados** | Potente para investigaciones del tipo «sigue el dinero». | Irrelevante para la mayoría de las historias; pesada, de nicho; estorbo para Amara. | **Mantener, marcar como avanzada, ocultable.** Fuera del recorrido crítico; un solo interruptor la elimina para quien no hace trabajo financiero. |
| **Perspectivas** | La vitrina visual — tendencias, asociaciones, mapa. El «guau». | Era una pestaña discreta en medio; infravalorada. | **Mantener y promocionar.** Es una funcionalidad estrella; recibe protagonismo y pulido. |
| **Wikipedia** | Encaja muy bien: «el mundo tal como es realmente», conocimiento sin conexión, detección de guerras de ediciones. | Dos cosas distintas (seguimiento en vivo frente a pesados volcados sin conexión) repartidas de forma confusa entre pestañas. | **Mantener.** El seguimiento se queda aquí; los volcados pesados se quedan en Ajustes, con enlaces cruzados claros (ya hecho en trabajos anteriores). |
| **Cadena de custodia** | El elemento diferenciador de la confianza. Es lo que hace que Elliot confíe en el resultado y que Amara parezca profesional. | Nombre en jerga jurídica; parecía una cámara acorazada que pocos abrirían. | **Mantener, renombrar → «Evidencia y custodia», promocionar.** Forma parte del momento «¡¿qué es esto?!». |
| **Ajustes** | Necesaria. | Era un cajón de sastre (preferencias + filtro de palabras clave + volcados + copia de seguridad). | **Mantener, reestructurar** en secciones (Apariencia · General · Wikipedia · Datos y copia de seguridad · Seguridad). *(0.07: el cajón Personalizar independiente se integró como la sección **Apariencia** — un solo lugar para el aspecto, menos elementos flotantes.)* |

#### Nuevas superficies añadidas

- **Inicio (panel).** *Justificación:* Amara necesita orientación, no un cuadro de búsqueda vacío.
  El estado de un vistazo (tamaño del corpus, fuentes, programador, última actividad), grandes acciones
  rápidas («Búsqueda», «Recopilar ahora», «Verificar un documento») y un estado vacío que
  enseña. Es la mayor mejora de usabilidad para la persona principal.
- **Lector de Ayuda / documentación.** El usuario pidió expresamente acceso directo al manual
  detallado. Una superficie de **Ayuda** de primer orden muestra el Manual de usuario (y otros documentos)
  *dentro* de la aplicación — con búsqueda, sin conexión, sin salir de la herramienta. También accesible desde
  la barra superior (`?`) y desde la paleta de comandos.

#### Arquitectura de la información resultante

La franja plana de 9 pestañas se convierte en una **barra lateral agrupada** (plegable a iconos), ordenada
según cómo fluye realmente el trabajo:

- **Investigar** — Inicio · Búsqueda · Perspectivas · Mapa temporal · Wikipedia · *Mercados (avanzado)*
- **Recopilar** — Recopilar · Fuentes · Biblioteca
- **Confianza** — Evidencia y custodia
- **Sistema** — Ajustes · Ayuda

Agrupar convierte «nueve desconocidos iguales» en «cuatro intenciones», que es como piensa Amara
(«quiero *encontrar* algo» / «quiero *reunir*» / «quiero *demostrar*»).

---

### 4. El «guau» — lo que hace que un periodista se incline hacia la pantalla

- **Un sistema visual coherente.** Un tema oscuro profundo de «tinta» por defecto, con un único
  acento seguro, un ritmo de espaciado generoso, una jerarquía tipográfica real, monoespaciada para
  datos/hashes, profundidad suave y movimiento contenido. Se lee como un *instrumento*, no como una
  *plantilla de panel*.
- **Paleta de comandos (Ctrl/⌘-K).** Escribir para saltar a cualquier lugar, ejecutar cualquier acción o abrir
  cualquier documento. Potencia para Daniel; un mapa de «¿qué puedo hacer aquí siquiera?» para Amara.
- **Controles de apariencia** (Ajustes → Apariencia; un cajón en vivo hasta la 0.06, integrado
  en Ajustes en la 0.07). Temas predefinidos (Ink, Slate, Midnight, Paper, Sepia,
  Terminal, High-contrast), muestras de color de acento, densidad, tamaño de letra, plegado de la barra lateral y
  **visibilidad de los módulos** — todo instantáneo, todo local, todo persistente.
- **Un Inicio que orienta**, una incorporación que enseña y estados vacíos que guían.
- **La confianza, hecha visible.** La custodia/verificación y el enfoque «medido, no estimado»
  forman parte de la estética, no de la letra pequeña.
- **Integridad total sin conexión.** Ninguna llamada de red para la interfaz — lo que en sí mismo es una
  funcionalidad que se puede *enseñar* a un colega preocupado por la seguridad.

---

### 5. Modelo de personalización

El aspecto se guarda en `localStorage` (`oo.ui`) — nunca se envía a ninguna parte — así que
es instantáneo y sobrevive sin conexión. Las preferencias funcionales (límite de resultados por defecto, tema
base) siguen guardándose en el servidor mediante `/api/settings`. Personalizable: tema
predefinido, color de acento, densidad, escala de letra, estado de la barra lateral y el conjunto de módulos
visibles. Unos valores por defecto sensatos hacen que un usuario que la abre por primera vez no tenga que tocar nada.

---

### 6. Lo que deliberadamente **no** hice (honestidad)

- **Ningún framework / paso de compilación / CDN.** Rompería el espíritu sin conexión, auditable y soberano
  a cambio de una ganancia cosmética. JS puro, un solo archivo, fuentes del sistema, SVG dibujado a mano.
- **Ninguna funcionalidad fabricada.** Cada botón corresponde a un endpoint real y operativo. Una capacidad
  que depende de un extra opcional sigue diciéndolo.
- **Ningún cambio silencioso en el backend** más allá de un endpoint de documentación aditivo, de solo lectura y con lista de permitidos
  (`/api/docs`) para alimentar el lector de Ayuda.
- **Los campos de idioma de texto libre siguieron siendo de texto libre** (ya anotado en OPEN_QUESTIONS);
  el rediseño no inventa desplegables que el backend no pueda respaldar.

---

### 7. Estado

`0.05` es ahora la **rama por defecto** del repositorio (línea principal); las líneas anteriores (0.04
y previas) permanecen en el historial de git. La paridad funcional se mantiene (mismos ID de elementos,
mismas conexiones); el cambio es todo lo que *rodea* a ese motor. La versión por defecto incluye
**dos** interfaces — Console (`/`) y Desk (`/desk`) — comparadas en
[`DESIGN.md`](DESIGN.md).


---

## Dos interfaces, un argumento — «Console» frente a «Desk»

> Usted pidió un argumento *contradictorio*: no una defensa del rediseño 0.05, sino
> un alegato honesto de que podría ser la interfaz **equivocada** para esta aplicación — y una
> alternativa concreta con la que ponerlo a prueba. Este documento es ese argumento. Las dos
> interfaces se distribuyen una junto a la otra para que pueda usar ambas con los mismos datos y juzgar por
> sí mismo.

---

### 0. Primero, volver a lo que esta aplicación es realmente

Antes de discutir sobre la interfaz, los no negociables (de `ETHICS.md`,
`DESIGN.md`, la Carta de Múnich):

- **Un usuario, una máquina, solo loopback, sin conexión primero.** Sin cuentas, sin nube,
  sin telemetría. A menudo se ejecuta en una AppVM de Qubes con el qube de red *desconectado*.
- **Un agente en busca de la verdad que no es amigo de los ordenadores.** Un investigador /
  periodista cuyo trabajo es *entender la realidad y comunicarla de forma creíble*.
- **El producto es la confianza.** Procedencia, verificación de las fuentes, «medido, no
  estimado», detección de manipulaciones. La Carta de Múnich (verdad, verificar las fuentes, proteger las
  fuentes, resistir a la propaganda) es la columna vertebral.
- **La soberanía como estética.** La herramienta debe *sentirse* como algo que pertenece al usuario,
  no a una plataforma.

Cualquier interfaz debe juzgarse con respecto a *eso*, no con respecto a «¿parece un
producto SaaS de 2025?».

---

### 1. El pliego de cargos contra «Console» (el rediseño 0.05)

Presentando en su versión más sólida el argumento de que la 0.05 va en la dirección equivocada:

1. **Viste una herramienta soberana con ropa del capitalismo de la vigilancia.** Barra lateral izquierda
   persistente, píldoras de estado, paleta de comandos, un cajón de personalización con ocho
   temas — es la gramática visual de Slack, Linear, Notion: *SaaS en la nube*. Para
   un usuario que desconfía de las grandes tecnológicas y trabaja en historias sensibles, esa gramática puede
   leerse como «otra aplicación que me vigila», socavando lo único que más importa
   aquí: la confianza. El aspecto lucha contra los valores.

2. **Optimiza para la demostración, no para el trabajo.** El encargo incluía «hacer que un
   periodista diga *¿me lo puedo quedar?*» — una reacción de cinco segundos por encima del hombro.
   Diseñar para eso empuja hacia el efectismo del panel (degradados, recuentos animados,
   un zoológico de temas) y aleja de la realidad tranquila, centrada en la lectura y los documentos, de
   la investigación. Las mejores herramientas para el trabajo profundo (un editor de texto, un cuaderno) son
   *sencillas*. Console puede ser impresionante y superficial.

3. **La personalización es un impuesto disfrazado de regalo.** Ocho temas, muestras de acento,
   densidad, escala de letra, ocultación por módulo. Para *Amara* (poco amiga de los ordenadores) cada
   una de estas opciones es una decisión que no quería tomar y una forma de configurar mal su herramienta.
   «Muy personalizable» respondía a la redacción del encargo y a la idea de generosidad del *diseñador*
   — pero una herramienta realmente sencilla es **decidida**: toma la decisión correcta
   para que el usuario no tenga que hacerlo. Elegir es carga cognitiva.

4. **La arquitectura de la información sigue siendo la del software, no la del usuario.** Console
   renombró y reagrupó las pestañas, pero el menú sigue siendo una lista de *módulos*
   (Búsqueda, Fuentes, Perspectivas, Mercados, Custodia…). Amara no piensa en módulos;
   piensa en un **caso**: «estoy siguiendo esta historia — reunir, leer, conectar, demostrar,
   publicar». Tanto la 0.04 como la 0.05 obligan al usuario a traducir su *trabajo* a las
   *funcionalidades* de la aplicación. Una navegación persistente de nueve destinos es un mapa del código fuente.

5. **La interfaz compite con el contenido.** Una barra lateral fija + una barra superior gastan permanentemente
   ~250px y una franja horizontal en *una navegación que el usuario utiliza dos segundos por
   sesión*. Lo que realmente hace — leer artículos, recorrer resultados, comparar
   diferencias — se queda con las sobras. Investigar es leer; Console atiende mal la
   lectura.

6. **El «guau» es prestado, no ganado.** Una paleta y unos temas son *lo mínimo exigible*
   en las aplicaciones modernas — impresionan precisamente porque son familiares. Las
   funcionalidades realmente diferenciadoras, las de «nunca había visto esto», son aquí la *sustancia*:
   la detección sin conexión de guerras de ediciones en Wikipedia, la custodia a prueba de manipulaciones, «cada número es un
   COUNT(\*) real». Console decora; no dramatiza lo que es realmente único.

Es una acusación seria. Merece una alternativa real, no una refutación.

---

### 2. En defensa de Console (para que el argumento sea justo)

- Una navegación persistente es **descubrible**: no hay nada oculto, lo que importa para un
  novato que aún no sabe lo que puede hacer la herramienta. Los modelos de centro y radios esconden
  la potencia detrás de un clic y una suposición.
- La personalización es **opcional**: los valores por defecto son sensatos; un usuario que ignora el cajón
  no pierde nada. Y los temas ayudan de verdad con la fatiga visual y las noches largas del
  trabajo, y con la accesibilidad (alto contraste, tamaño del texto) de usuarios *reales*.
- La «gramática SaaS» es también simplemente la **convención de usabilidad actual** — la gente sabe
  usarla desde el primer día. La novedad por la novedad tiene su propio coste.
- Sigue siendo **100 % sin conexión y sin dependencias**. La gramática es prestada; la
  sustancia (sin red, sin telemetría) no lo es.

Ambas posturas son legítimas. La forma de resolverlo no es discutir más — es
**construir la antítesis y usar ambas**.

---

### 3. La antítesis: «Desk»

Si Console es una **consola de operaciones amplia** (todo siempre a un clic,
máximamente flexible, gramática de aplicación moderna), **Desk** es la tesis opuesta:

> **El escritorio de un investigador: tranquilo, decidido, centrado en el contenido y enmarcado por la tarea.
> Casi sin interfaz. Un trabajo cada vez. La interfaz se aparta para dejar paso a la lectura
> y al pensamiento.**

Compromisos concretos en los que Desk *discrepa* deliberadamente de Console:

| Dimensión | Console (tesis) | Desk (antítesis) |
|---|---|---|
| Navegación | Barra lateral izquierda persistente (siempre visible) | **Sin navegación persistente.** La navegación es *a demanda* — un inicio tranquilo, una superposición «Ir a…» y ⌘K. La interfaz solo aparece cuando se la llama. |
| Punto de entrada | Un panel de estado | **Un inicio enmarcado por el trabajo:** «¿En qué está trabajando?» → Reunir · Buscar y leer · Conectar · Verificar y compartir. Enmarcado por la tarea del usuario, no por los módulos de la aplicación. |
| Personalización | 8 temas, acento, densidad, letra, interruptores de módulos | **Solo dos temas** (Paper / Ink), sin mandos. Decidida. La herramienta decide para que usted no tenga que hacerlo. |
| Estética | Consola de aplicación moderna (sans, píldoras, degradados) | **Editorial / impresa:** títulos con serifa, calidez de papel, márgenes generosos, medida de lectura. Se siente como una redacción, no como un SaaS. |
| Qué ocupa el espacio | Navegación + estado, después el contenido | **El contenido.** Una única columna de lectura centrada; las tablas y el lector de artículos disponen del espacio. |
| Señal de confianza | Una píldora de estado | Una línea persistente y discreta **«Local · Sin conexión · Nada sale de esta máquina»** — la soberanía declarada, no insinuada. |
| Reacción en la demostración | «¡Qué pulido!» | «…oh, esto es *tranquilo*. Y es todo mío.» Un «guau» más lento y más profundo. |

Lo que Desk **conserva** (porque es la razón de ser de la aplicación, no la interfaz): cada funcionalidad
y cada endpoint operativo. Desk y Console comparten exactamente el mismo motor y los
mismos paneles de contenido — difieren *solo* en el envoltorio, el modelo de navegación, el enfoque de la arquitectura de la información y la
estética. Es deliberado: mantiene el experimento controlado, de modo que lo que se compara es
**la filosofía**, no cuál de las dos resultó que conecté con más cuidado.

---

### 4. Cómo juzgarlas (rúbrica)

Puntúe cada una según los valores — no según su intuición de «cuál se ve mejor»:

1. **Confianza** — ¿cuál *se siente* como algo que le pertenece y no le traicionará?
2. **Calma frente a capacidad** — ¿cuál le deja pensar? ¿cuál hace que la potencia sea fácil de encontrar?
3. **Recorrido del novato** — ponga a *Amara* delante sin preparación: ¿cuál la lleva antes a un resultado, con
   menos miedo?
4. **Recorrido del usuario avanzado** — *Daniel* con el teclado: ¿cuál no le estorba?
5. **Lectura** — abra un artículo largo / un diff de Wikipedia en cada una. ¿Cuál es el mejor
   lugar para *leer*?
6. **La prueba de los 5 segundos** — enséñele cada una a un colega. ¿Cuál provoca «¿me la puedo quedar?» —
   y es esa la reacción que de verdad quiere optimizar?
7. **Encaje con el espíritu** — ¿en cuál confiaría para funcionar con la red desconectada en
   una bóveda Qubes?

---

### 5. Ventajas e inconvenientes previstos (mi apuesta honesta, por comprobar)

**Console** — *Ventajas:* descubrible, convencional, flexible, mandos de accesibilidad, brillo
en la demostración. *Inconvenientes:* cargada de interfaz, carga de decisiones, aire de SaaS genérico que puede erosionar la confianza,
arquitectura de la información aún centrada en los módulos.

**Desk** — *Ventajas:* tranquila, centrada en el contenido y la lectura, decidida (sin impuesto de configuración),
entrada enmarcada por la tarea, una estética que *refuerza* la soberanía y la confianza. *Inconvenientes:*
la potencia está a una llamada de distancia (un clic o una tecla), menos mandos de accesibilidad, menos
«impresionante» de entrada, la novedad tiene un pequeño coste de aprendizaje.

---

### 6. Mi recomendación (síntesis — provisional, pendiente de su prueba)

Espero que la respuesta correcta no sea ni Console pura ni Desk pura, sino una síntesis
que se apoye en el *encaje con los valores* de Desk y en la *descubribilidad* de Console:

- **Adoptar el inicio enmarcado por la tarea y la calma editorial de Desk** como ambiente por defecto. El
  enfoque por trabajos («reunir / leer / conectar / verificar») es la mayor corrección a la
  crítica de que «la arquitectura de la información es el código fuente».
- **Adoptar la contención de Desk en la personalización:** ofrecer dos temas excelentes
  (Paper/Ink) + un control de tamaño del texto para la accesibilidad, y **recortar** la proliferación de
  acento / densidad / ocultación de módulos. Aquí, ser decidido gana a ser configurable.
- **Conservar de Console una navegación *discreta y plegable*** por descubribilidad — pero
  plegada por defecto, para que el contenido vaya primero y la navegación esté ahí cuando se quiera.
- **Conservar ⌘K** (sirve tanto al novato como al usuario avanzado y es realmente útil).
- **Dramatizar la sustancia, no la interfaz:** convertir la custodia, la Wikipedia sin conexión y
  los «recuentos reales» en los protagonistas visuales — ese es el «guau» ganado.
- **Poner la línea de confianza por delante en todas partes** («nada sale de esta máquina»). Es
  la marca.

Pero eso es una hipótesis. Use ambas, puntúelas según el §4 y dígame dónde la realidad
se aparta de mi apuesta — después integraré el veredicto en una única 0.06.

> **VEREDICTO FINAL (mantenedor, 2026-06-10, tras el uso real):** la dialéctica está
> resuelta — **Desk se retira por completo. Una sola interfaz: la Console** (`/`).
> Dos iconos confundían más de lo que ayudaban; el conjunto de herramientas reducido de Desk hacía que
> funcionalidades ya publicadas (Mapa temporal, Agenda) parecieran perdidas; y la Console ya
> se adapta con fluidez al tamaño de la ventana (la barra lateral se repliega en una franja de iconos). El
> archivo `desk.html` se eliminó (sigue en el historial de git); `/desk` ahora
> redirige a `/`. Las mejores ideas de Desk — el inicio enmarcado por la tarea, ⌘K, la calma
> editorial — deberían integrarse en la Console con el tiempo, según el §6 anterior.

---

### 7. Ejecutar ambas a la vez

Las dos interfaces las sirve el mismo backend local con los mismos datos:

- **Console** → `http://127.0.0.1:8000/`  (la predeterminada)
- **Desk** → `http://127.0.0.1:8000/desk`

El instalador crea **dos iconos en el escritorio** — *Open Omniscience* (Console) y
*Open Omniscience — Desk* — para que pueda abrir cualquiera de las dos, o abrir ambas ventanas a la vez
y compararlas pestaña por pestaña con datos idénticos. Elija una ganadora (o pida la
síntesis) y volveremos a una sola en la 0.06.


---

## Estrategia de análisis de contenido — enlaces, uniformidad y la fuente original

> Estrategias concretas y escalonadas para la visión de [`ROADMAP.md`](archive/roadmaps/DESIGN_MEMORY_pre-0.2.md):
> usar los **enlaces** de los artículos para reunir lo que habla de lo mismo, poner de manifiesto la
> **uniformidad** de los medios y remontar la información hasta su **fuente original** — manteniendo
> **el poder en manos del usuario**, el análisis **transparente y local**, y sin dejar nunca
> que la herramienta se convierta en árbitro de la verdad (Carta de Múnich). Código abierto y
> sin conexión de principio a fin.

---

### 0. Dónde estamos (estado honesto)

La detección de enlaces en los artículos tiene **andamiaje, pero no está conectada**:

- ✅ **`src/services/link_analyzer/extractor.py`** (`LinkExtractor`) — extrae los enlaces
  del HTML, normaliza las URL, registra el texto del ancla y su posición, clasifica el *tipo* de enlace
  (interno/externo/imagen/…) y produce estadísticas de enlaces. ~500 líneas, con forma de unidad comprobable.
- ✅ **Esquema de base de datos** — `ArticleLink` (url, normalized_url, link_text, position,
  link_type, **classification** = source/reference/ad/social/navigation,
  `external_source_id`, `source_article_id`, is_working, http_status…),
  `ExternalSource` y `LinkClassificationRule`. Las relaciones están en su sitio
  (`Article.links`, `ExternalSource.links`).
- ✅ **Invocado en la ingesta** *(hecho — P0)* — `src/ingest/pipeline.py:_maybe_index_links`
  rellena `article_links` con los enlaces salientes **externos** (en la medida de lo posible, falla abierto;
  se excluyen internos/imágenes/anuncios/redes sociales/rastreadores según `ROADMAP.md`; sin duplicados + con tope).
- ✅ **API** *(hecho — P1)* — `src/api/link_analysis.py` (`/api/links`): `stats`,
  `top-cited` (por url|dominio, con ventana), `articles-by-link` (por url|dominio). Solo
  recuentos; nada se puntúa ni se juzga.
- ❌ **Aún sin interfaz** — ninguna vista de Perspectivas sobre el grafo de enlaces (P2, más abajo).

Así que P0/P1 están conectados; el trabajo pendiente es la interfaz y los análisis más profundos (P3/P4).

---

### 1. La idea central: los enlaces son un grafo de citas

Tratar cada artículo como un nodo y cada enlace saliente como una arista dirigida hacia una URL (y
hacia su dominio). Ese grafo responde exactamente a lo que usted preguntó:

- **«Reunir todos los artículos que hablan del mismo enlace».** = agrupar los artículos por la
  URL externa que citan → el **grado de entrada** de la URL es «cuántos de mis artículos apuntan
  aquí». Un grado de entrada alto = un **concentrador**: a menudo un documento primario, un despacho de agencia o una
  referencia muy comentada.
- **«Descubrir tendencias a través de los enlaces internos».** = observar el grado de entrada a lo largo del tiempo; una URL o
  un dominio cuyas citas se disparan es una *tendencia* basada en lo que los periodistas citan realmente,
  no solo en la frecuencia de las palabras clave.
- **«Rastrear la fuente original / primigenia».** = dentro de un grupo de artículos sobre una misma
  historia, el original es el nodo al que los demás **enlazan**, y/o el más temprano, y/o el
  que cita un **documento primario** (tribunal/gobierno/conjunto de datos). Los enlaces + las marcas de tiempo + la atribución
  a agencias permiten triangularlo.

Esto es *análisis de cocitación* — barato, transparente y explicable. Sin caja negra.

---

### 2. Estrategias escalonadas (cada una publicable por sí sola)

#### P0 — Conectar el extractor a la ingesta (hacer que el grafo exista)
- Llamar a `LinkExtractor` durante la ingesta sobre el HTML obtenido; guardar los enlaces salientes
  **externos** en `article_links` (omitir la navegación interna, los anuncios y — según
  `ROADMAP.md` — los enlaces a imágenes o binarios). Almacenar normalized_url + texto del ancla + tipo.
- Asociar el dominio de cada enlace externo a una `Source`/`ExternalSource` conocida cuando
  sea posible (para que «quién cita a quién» pueda agregarse por medios y por **propietarios**).
- Barato, determinista, sin conexión. No se obtiene nada más allá de lo que la ingesta ya obtuvo.

#### P1 — Agregación + API (responder a la pregunta del usuario)
Endpoints de solo lectura sobre el grafo:
- **`top-cited`** — las URL/dominios más citados en una ventana (la señal de tendencia).
- **`articles-by-link`** — dada una URL/dominio, todos los artículos del corpus que la citan
  («reunir todos los artículos que hablan del mismo enlace»).
- **`link-graph`** — nodos/aristas para un tema o una ventana, para la visualización.
- **`co-citation`** — artículos que citan las *mismas* fuentes externas (grupos candidatos de
  «misma historia»), con recuentos de solapamiento.

#### P2 — Interfaz: una vista «Enlaces y fuentes» en Perspectivas
- Una lista ordenada de los **enlaces/dominios más citados** (clic → todos los artículos que los citan).
- Un pequeño **grafo de citas** ampliable (reutilizar el enfoque SVG ya usado para el
  mapa de Perspectivas — ninguna dependencia nueva).
- Muestra siempre los **tamaños de muestra** («citado por 14 de sus artículos») — medido, no
  supuesto. El usuario hace clic, explora y decide.

#### P3 — Linaje de la fuente original
Para un grupo de artículos sobre una misma historia, presentar un **linaje**, ordenado por señales
(cada una mostrada, ninguna decisiva):
- grado de entrada (a quién enlazan los demás),
- marca de tiempo de publicación más temprana,
- atribución a agencias (AFP/Reuters/AP — ya etiquetamos `wire-agency`),
- presencia de un enlace a un **documento primario** (gobierno/tribunal/conjunto de datos/preprint).
Resultado: «documento primario → primera información → ecos», como una cadena que el usuario lee.

#### P4 — Uniformidad y eco (vinculado a la concentración de medios)
- **Detección de casi duplicados** (MinHash/SimHash, baratos) para señalar textos sindicados o copiados
  entre medios — se apoya en `src/ingestor/duplicate_detector.py`.
- **Puntuación de eco**: un grupo en el que muchos medios citan **una sola** fuente (o se citan entre sí en un
  bucle cerrado) y aportan pocos enlaces originales = eco alto. Citas diversas a fuentes primarias =
  información independiente.
- **Superposición de concentración**: ponderar el eco por la **propiedad** — si el grupo que hace eco corresponde
  a un mismo propietario/bloque (el caso de «~7 multimillonarios poseen ~90 %»), mostrarlo. Requiere el
  grafo de propiedad (Wikidata P127/P749 + manual), según `ROADMAP.md`.

---

### 3. Mantener el poder en manos del usuario (no negociable)

- **Mostrar, nunca suprimir.** Las puntuaciones de eco/linaje se *muestran y se pueden ordenar*; la herramienta
  nunca oculta ni relega automáticamente una fuente. Cualquier reducción de peso es un control del usuario
  explícito y reversible, **desactivado por defecto**.
- **Ninguna etiqueta de verdad.** «Lo primero que vimos» / «lo más citado» ≠ «verdadero». Mostramos la estructura
  (quién lo dijo primero, quién cita a quién, quién es dueño de quién) y nos detenemos ahí.
- **Todo explicable y local.** Cada número remite a filas que el usuario puede inspeccionar;
  ninguna llamada externa, ninguna caja negra de ML (hash + recuento + grado del grafo).
- **Código abierto y auditable.** Funciones puras, comprobables con pruebas unitarias, reglas de clasificación en
  datos (`LinkClassificationRule`) que el usuario puede editar.

---

### 4. Riesgos y límites honestos

- La extracción de enlaces solo es tan buena como el HTML obtenido (los muros de pago y el JS la limitan).
- Las convenciones de anclas y citas varían; un «según X» sin enlace se pierde (una
  pasada posterior de PLN podría ayudar, pero se empieza por lo sencillo).
- Los datos de propiedad son incompletos y están desfasados — deben poder atribuirse, no suponerse.
- La detección de casi duplicados a escala del corpus exige cuidado para seguir siendo barata en una sola máquina (hash,
  comparación por ventanas), no comparaciones O(n²) de texto completo.

### 5. Primer commit sugerido

Conectar **P0** (rellenar `article_links` en la ingesta) detrás de un ajuste, añadir los endpoints **P1
`articles-by-link`** y **`top-cited`**, y una lista mínima en Perspectivas. Solo con eso
se obtiene «reunir todos los artículos que citan el mismo enlace» y una tendencia basada en las citas
— la porción más pequeña de valor real, plenamente acorde con el espíritu del proyecto.
