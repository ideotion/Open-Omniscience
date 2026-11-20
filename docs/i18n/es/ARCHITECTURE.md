<!-- es: Translation of docs/ARCHITECTURE.md written by AI (2026-11-19, R677; native review dropped by R721, 2026-11-14); it may contain mistakes, and the English original is authoritative. Coverage: the whole document, 28 of 28 headings. Corrections are welcome as a pull request. -->

# Arquitectura y referencia técnica

El complemento técnico del Manual de usuario: la base de datos y su configuración, el mapa de la API HTTP y la internacionalización.

## Contenido
- [Configuración de la base de datos de Open Omniscience](#configuración-de-la-base-de-datos-de-open-omniscience)
- [Referencia de la API](#referencia-de-la-api)
- [Internacionalización (i18n): hacer la aplicación multilingüe](#internacionalización-i18n-hacer-la-aplicación-multilingüe)


---

## Configuración de la base de datos de Open Omniscience

> **Estado (verificado en la auditoría v0.0.7, `docs/archive/audits/00_BASELINE.md`):** la capa de base de datos
> **funciona y está probada**: el servidor arranca, crea y usa el almacén SQLite, aplica las migraciones
> de Alembic, y el conjunto completo de pruebas (más de 800) pasa contra ella. El antiguo aviso de «concepto temprano,
> no funcional» que figuraba aquí describía un estado anterior a la reconstrucción y llevaba mucho tiempo
> desfasado.

### 🗃️ SQLite: el almacén admitido

SQLite es el **backend por defecto y el único admitido y probado**. Se ajusta al diseño del producto:
local primero y con un solo operador.

- **Ninguna configuración:** la base de datos se crea automáticamente en el primer arranque, en
  `<data dir>/open_omniscience.db`. El directorio de datos es `OO_DATA_DIR` si está definido; si no, el directorio
  `data/` del repositorio en una copia del código fuente; si no, `$XDG_DATA_HOME/open-omniscience` (consulte `src/paths.py`).
- **Ajustada automáticamente:** el motor aplica el modo de diario `WAL`, `foreign_keys=ON`,
  `busy_timeout=30000` y `synchronous=NORMAL` en cada conexión
  (`src/database/session.py`); no necesita definirlos usted mismo.
- **La búsqueda de texto completo** es **FTS5** de SQLite (`article_fts`, de contenido externo, mantenida sincronizada por
  disparadores: `src/database/fts.py`).
- **Cambie la ubicación** con la variable de entorno `DATABASE_URL` (**no** edite
  los archivos fuente): `DATABASE_URL=sqlite:////absolute/path/to/your.db`
- **Mantenimiento:** un `sqlite3 <db> "VACUUM;"` ocasional recupera espacio (la auditoría v0.0.7
  también eliminó un índice redundante que ocupaba ~63 % del archivo en corpus grandes; ejecute `make
  migrate` una vez tras actualizar para eliminarlo de las bases de datos existentes).

### 🐘 PostgreSQL: andamiaje experimental, NO admitido

La honestidad por encima de las aspiraciones (hallazgo de auditoría ARCH-06): la capa del motor *reconoce* un
`DATABASE_URL` de PostgreSQL (agrupación de conexiones mediante `DB_POOL_SIZE`/`DB_MAX_OVERFLOW`), **pero**

- **la búsqueda de texto completo no existe en PostgreSQL**: la configuración de FTS5 no hace nada a propósito en
  motores distintos de SQLite, por lo que la pestaña Búsqueda quedaría inservible;
- el conjunto de pruebas nunca se ejecuta contra PostgreSQL y ninguna CI lo cubre;
- ningún despliegue publicado lo ha usado.

Considere PostgreSQL como **un andamiaje no probado para un posible futuro**, no como una opción que pueda
elegir hoy. Si algún día la escala con varios escritores se convierte en un requisito real, el punto de la hoja de ruta es una
ruta de búsqueda `tsvector` más una matriz de CI para PostgreSQL; hasta que eso llegue, esta página no
fingirá lo contrario.

### 🔄 Migraciones

Alembic está configurado en la **raíz del repositorio** (`alembic.ini`, `migrations/`). Alembic se
instala con la aplicación (es una dependencia del núcleo: no requiere instalación aparte).

- **Las bases de datos nuevas** se crean completas (`create_all` + FTS) y se marcan con la cabeza de
  migración actual automáticamente al arrancar.
- **Actualizar una base de datos existente:**
  ```bash
  make migrate          # = alembic upgrade head, from the repo root
  ```
- **Crear una migración** (colaboradores): edite `src/database/models.py` y luego
  ```bash
  alembic revision --autogenerate -m "your message"
  alembic upgrade head
  ```
  y revise el archivo generado: la autogeneración omite las tablas virtuales FTS (que residen en
  `src/database/fts.py` y se aplican al arrancar).
- **Revertir:** `alembic downgrade -1`.

---

### 📊 Esquema de la base de datos

#### Tablas:

##### `sources`
| Columna | Tipo | Descripción |
|--------|------|-------------|
| `id` | INTEGER | Clave primaria |
| `name` | STRING(100) | Nombre de la fuente (p. ej., "BBC News") |
| `domain` | STRING(255) | Dominio de la fuente (p. ej., "bbc.com") |
| `rss_url` | STRING(500) | URL del canal RSS (si existe) |
| `rate_limit_ms` | INTEGER | Intervalo entre peticiones en milisegundos |
| `enabled` | BOOLEAN | Si la fuente está activa para la recopilación |
| `priority` | INTEGER | Nivel de prioridad (1 = alta, 3 = baja) |
| `tags` | STRING(500) | Lista de etiquetas separadas por comas |

##### `articles`
| Columna | Tipo | Descripción |
|--------|------|-------------|
| `id` | INTEGER | Clave primaria |
| `url` | STRING(1000) | URL original del artículo |
| `canonical_url` | STRING(1000) | URL canonicalizada (para la detección de duplicados) |
| `source_id` | INTEGER | Clave foránea hacia `sources` |
| `title` | STRING(500) | Título del artículo |
| `content` | TEXT | Texto completo del artículo |
| `published_at` | DATETIME | Fecha/hora de publicación (formato ISO) |
| `language` | STRING(10) | Código de idioma (p. ej., "en", "fr") |
| `hash` | STRING(64) | Hash SHA-256 del contenido (para la detección de duplicados) |
| `created_at` | DATETIME | Marca de tiempo de la ingesta del artículo |

> Las columnas anteriores son los campos principales; el esquema real (`src/database/models.py`)
> y las migraciones de Alembic en `migrations/versions/` son la fuente de verdad.
> `articles` también contiene campos de procedencia y análisis (autor, word_count, región,
> país, sentimiento) y una columna de contenido comprimido.

##### Otras tablas (consulte los modelos / las migraciones para las columnas completas)

| Tabla | Función |
|-------|---------|
| `source_groups`, `source_metadata`, `source_group_association` | Agrupación de fuentes + metadatos geográficos/robots |
| `commodity_prices` | Precios observados (símbolo, fecha, precio, moneda, **unidad**, mercado, fuente): gráficos + correlación precio↔noticias |
| `market_extraction_rules` | Regla por fuente (selector CSS / atributo / regex) que localiza el precio de un instrumento en una página; categoría financial/stock/commodity |
| `keywords` | Término distinto de palabra clave/entidad (normalizado, idioma, `is_entity`/`entity_type`, procedencia **`extractor`**) |
| `keyword_mentions` | Una por (artículo, palabra clave): recuento + desplazamiento del primer carácter + `observed_on`/`country`/`city` desnormalizados; alimenta las tendencias, asociaciones, contexto y mapa de Perspectivas |
| `wiki_pages` | Una página de Wikipedia seguida en una edición lingüística; guarda **una sola** referencia de texto completo comprimida |
| `wiki_revisions` | Una edición seguida: **diff + variación de bytes con signo** + indicadores/etiquetas (no una copia nueva), puntuaciones ORES opcionales, indicador honesto de edición grande + motivos |
| `article_analyses` | Resultados derivados del LLM (resumen/traducción) con la procedencia del modelo y del prompt |
| `keyword_categories`, `external_sources`, `article_links`, … | Categorización de palabras clave + seguimiento de enlaces y relaciones entre fuentes |

#### Índices:
- `idx_article_hash`: Índice único sobre `hash` (para la detección de duplicados).
- `idx_article_canonical_url`: Índice sobre `canonical_url` (para las búsquedas por URL).
- `idx_article_source_id`: Índice sobre `source_id` (para las consultas por fuente).
- `idx_article_content`: Índice sobre `content` (para la búsqueda de texto completo).

---

### 🔍 Búsqueda de texto completo

La búsqueda de texto completo **ya está construida y conectada**: no hay nada que activar. El almacén
contiene una tabla FTS5 de contenido externo (`article_fts`) mantenida sincronizada por disparadores; consulte
`src/database/fts.py` para el esquema y `search_ids` en `src/api/main.py` para la ruta de
consulta (resolución solo de identificadores en el orden final; las filas completas se cargan únicamente para la página).

Esta sección proponía antes una receta de «considere crear una tabla virtual» para SQLite y una
receta `to_tsvector` para PostgreSQL. Ambas eran erróneas: la de SQLite describía cómo construir a
mano una tabla que la aplicación incluye y mantiene (con un nombre *distinto*, de modo que seguirla habría
producido un segundo índice sin mantenimiento), y PostgreSQL no tiene aquí ninguna ruta de búsqueda,
lo que la sección del almacén, más arriba, indica como el primer motivo por el que no es un backend admitido.

---

### 📉 Supervisión y mantenimiento

- **Comprobar el tamaño de la base de datos**:
  ```bash
  ls -lh data/open_omniscience.db
  ```
- **Comprobar el tamaño de las tablas**:
  ```bash
  sqlite3 data/open_omniscience.db "SELECT name, COUNT(*) FROM sqlite_master WHERE type='table';"
  ```
  En un almacén **cifrado**, la CLI `sqlite3` no puede abrir el archivo en absoluto (esa es
  precisamente su finalidad): use las superficies de Ajustes → Diagnóstico de la aplicación, que leen el almacén
  a través de la misma fábrica de conexiones protegida que usa la propia aplicación.

---

### 🚨 Resolución de problemas

#### Problemas habituales:

##### SQLite:
- **"Database is locked"**:
  - SQLite solo admite un escritor a la vez. El modo WAL está activado por defecto
    (`src/database/session.py`) y una compuerta de escritor único para todo el proceso
    (`src/database/writer.py`) serializa las escrituras de la aplicación, por lo que la ingesta y la
    importación simultáneas ya no chocan. Un bloqueo persistente significa que otro *proceso* está escribiendo.

- **"Too many open files"**:
  - SQLite abre una conexión nueva para cada hilo. Limite el número de hilos o use agrupación de conexiones.

- **"Relation does not exist" / "no such table"**:
  - Ejecute las migraciones: `alembic upgrade head`.

---

### 📌 Buenas prácticas

1. **Haga las copias de seguridad desde la aplicación, no con `cp`**:
   - Use Ajustes → Copia de seguridad (o `GET /api/database/backup` para una instantánea coherente).
     Copiar `open_omniscience.db` a mano **no** es una copia de seguridad: el almacén funciona en modo
     WAL, por lo que al archivo activo le falta lo que todavía esté en `-wal`, y en el almacén
     **cifrado** por defecto un archivo copiado es inútil sin la frase de contraseña y no lleva ningún
     compromiso de integridad. La ruta propia de la aplicación hace un checkpoint, transmite y firma.

2. **Pruebe las migraciones**:
   - Pruebe siempre las migraciones sobre una copia de seguridad de su base de datos antes de aplicarlas en producción.

3. **Supervise el rendimiento**:
   - Ajustes → Diagnóstico contiene el registro de consultas lentas, el registro de latencia de las peticiones y el
     informe de la compuerta de escritura; la CLI `sqlite3` funciona sobre un almacén en texto plano.

4. **Optimice las consultas**:
   - `EXPLAIN QUERY PLAN` es la herramienta. Tenga en cuenta que SQLite escribe `SCAN` **tanto** para un recorrido
     simple de la tabla como para un recorrido solo por índice: un `SCAN <table> USING [COVERING] INDEX …` está
     bien; la señal de alarma es un `SCAN <table>` simple sin `USING`
     (`src/monitoring/slowquery.py` clasifica exactamente según eso).

5. **Limite la conservación de datos**:
   - Archive o elimine periódicamente los artículos antiguos para mantener la base de datos manejable.
   - Ejemplo: eliminar los artículos de más de 1 año:
     ```python
     from datetime import datetime, timedelta
     one_year_ago = datetime.now(timezone.utc) - timedelta(days=365)
     session.query(Article).filter(Article.published_at < one_year_ago).delete()
     session.commit()
     ```

---
*Copyright © 2026 Ideotion. Licenciado bajo la Licencia Pública General de GNU v3.0
o posterior (GPL-3.0-or-later): consulte [LICENSE](../LICENSE). Esto es software libre;
puede redistribuirlo y modificarlo en esos términos.*


---

## Referencia de la API

La referencia de la API, siempre exacta y actualizada, la genera la propia aplicación:

- **Swagger UI / ReDoc:** desactivadas por defecto (cargan recursos desde hosts de terceros); inicie la aplicación con `OO_API_DOCS=1` para tener http://127.0.0.1:8000/docs y `/redoc`
- **JSON de OpenAPI:** http://127.0.0.1:8000/openapi.json

La aplicación solo escucha en loopback y (para un único usuario local) no requiere autenticación.

### Grupos de endpoints

Este es un **mapa de los grupos principales, no una lista exhaustiva**: el
`/openapi.json` en vivo (arriba) es siempre la referencia. Los routers se conectan en
`src/api/main.py` mediante `include_router(...)`; los grupos marcados **[analysis]** requieren
el extra `[analysis]` (la aplicación arranca igualmente sin él, con esos endpoints desactivados).

| Prefijo | Qué hace |
|--------|--------------|
| `GET /api/health` | Estado de funcionamiento + versión |
| `GET /api/articles`, `/api/articles/export` | Búsqueda booleana de texto completo (FTS5) + exportación CSV/JSON |
| `POST /api/ingest`, `/api/sources/{id}/ingest`, `/api/sources/{id}/ingest-email` | Ingesta ética: URL única, canal RSS, buzón IMAP |
| `… /api/sources`, `/api/sources/...` | Gestión de fuentes + grupos + metadatos |
| `POST /api/sources/seed-defaults` | Carga los catálogos de fuentes seleccionados (noticias + mercados + catálogo mundial generado) |
| `GET /api/database/stats`, `/coverage`, `/countries` | Recuentos de filas del corpus + tamaño en disco; cobertura por país; recuentos de fuentes por país + palabras clave temáticas |
| `GET /api/database/backup` | Descarga de una instantánea coherente de SQLite (solo almacén SQLite en texto plano; se rechaza para una petición procedente de otro sitio o de un Host al que la protección contra DNS rebinding no sirve, y, con un nombre distinto de loopback, para una petición que no indica la página de la que procede salvo que envíe `X-OO-Download: 1`; una a la vez por proceso, escrita en una carpeta privada `.oo-backup-*` junto a la base de datos y eliminada cuando termina la descarga o se detiene el proceso (una interrupción forzada la deja para el barrido del siguiente arranque, que elimina de inmediato la carpeta de un propietario desaparecido); 507 cuando el volumen de datos no puede contenerla) |
| `POST /api/database/v2/restore/preview`, `/v2/restore/commit`, `/api/backup/v2/*` | Restauración **solo aditiva** mediante el artefacto firmado `oo-backup-2`: previsualizar el plan de fusión y luego confirmarlo. La restauración **nunca sobrescribe su corpus**: fusiona sin duplicados y conserva los valores locales en caso de conflicto (la ruta destructiva de sustitución se eliminó el 2026-06-13) |
| `GET/PUT /api/settings` | Preferencias de la GUI (tema, límite de resultados por defecto) |
| `… /api/scheduler/...` | Recopilación en segundo plano: estado, inicio, parada, ejecutar ahora, configuración. Desde el ciclo `0.4` la recopilación se ejecuta en **carriles en paralelo** (`rss` / `crawl` / `markets` / `wiki` / `law`), no en un único modo del planificador; almacenamiento por carril en `… /api/storage/...`, y la pestaña **Fuentes vivas** lee `… /api/living/...` (lo que ha cambiado en Wikipedia, la legislación y los mapas) |
| `… /api/markets/rules`, `/rules/{id}/run`, `/overview` | Reglas de extracción de precios por fuente + una ejecución de «prueba» + vista general de Mercados |
| `GET /api/markets/feeds`, `POST /feeds/{key}/import`, `/feeds/import-url` | Catálogo de canales oficiales de precios en CSV + importación (FRED/World Bank/EIA) + importación desde una URL personalizada |
| `GET /api/catalog/export.csv`, `/template.csv`, `/columns`, `POST /api/catalog/import` | Exportación CSV de la lista de fuentes / plantilla / columnas / importación con actualización por dominio |
| `… /api/insights/...` | Analítica de palabras clave y entidades: estado, reindexación, principales, en tendencia, tendencia, asociaciones (PMI), contexto, mapa |
| `GET /api/timemap`, `/timemap/range` | Señales espaciotemporales en un mapa + eje temporal (anclas + corpus geocodificado + riesgos/fechas mencionadas opcionales); `?kinds`, ventana `?start`/`?end` en años fraccionarios, `?hazards`, `?articles`, `?mentions`, `?days` |
| `… /api/article-dates/...` | Fechas extraídas mencionadas en el texto de los artículos como etiquetas por artículo que una persona puede confirmar: listar/extraer por artículo, confirmar/rechazar, indexación por lotes, filtro del corpus por fecha |
| `GET/POST /api/llm/...` | LLM local (Ollama): estado, modelos, generación, resumen de un artículo |
| `… /api/commodities/...` | Precios de materias primas (importación / CSV / lista) + correlación honesta precio↔noticias |
| `POST /api/analysis/...` | Estadística con rigor científico: prueba t, correlación, ANOVA, Mann-Whitney, IC |
| `GET /api/monitoring/...` | Estado real de disponibilidad de las fuentes + anomalías del volumen del corpus |
| `POST /api/verify/image-metadata` | Extracción honesta de EXIF/metadatos de imágenes |
| `POST /api/reports/evidence`, `/evidence/verify` | Paquetes de pruebas firmados y a prueba de manipulaciones |
| `POST /api/custody/log`, `GET /api/custody/{item}`, `.../verify`, `POST /api/custody/export`, `POST /api/custody/verify` | Registro de cadena de custodia firmado, de solo anexado y encadenado por hash + verificación sin conexión |
| `GET/PUT /api/custody/settings` | Preferencias de custodia en tiempo de ejecución (firma poscuántica, modo de anclaje, registro automático): informa del estado *efectivo*, teniendo en cuenta la disponibilidad |
| `POST /api/custody/anchor`, `GET /api/custody/providers` | Anclar una raíz de Merkle (local / OpenTimestamps) + disponibilidad de los proveedores |
| `POST /api/custody/reconcile` | Escribe las entradas INGEST que un fallo dejó pendientes, cada una marcada como tardía en sus metadatos firmados; `scan` cuenta los huecos anteriores y `record_gaps` los pone en cola (2026-09-24, CUST-1) |
| `… /api/keywords/...`, `/api/analysis/articles/similarity` | **[analysis]** Extracción de palabras clave + similitud entre artículos |
| `GET /api/search/omni` | Barra de búsqueda federada basada en índices (FTS5 de artículos + palabras clave + fuentes + wiki/legislación) |
| `… /api/jobs/...` | Agregación de tareas del gestor de tareas (pasada de recopilación, descarga en curso, cola de volcados de wiki + reordenación) |
| `… /api/system/...` | Constantes vitales del sistema + estado de la red/consentimiento (interruptor de corte en modo avión, IP de las interfaces locales) |
| `… /api/safety/...` | Controles de seguridad: interruptor de corte, compuerta de descubrimiento, restauración desde un artefacto cifrado |
| `… /api/briefing/...` | Productores del resumen de Inicio (tarjetas escalonadas por nivel de evidencia; método+advertencia+n) |
| `… /api/insights/...`, `/api/insights/who`, `/where` | Analítica de palabras clave/entidades + agregación Quién/Dónde de todo el corpus |
| `… /api/links/...` (shared, preview) | Análisis de enlaces salientes compartidos / grafo de citas + diálogo local de vista previa de enlaces |
| `… /api/events/...`, `/api/events/astronomy`, `/climate` | Eventos de la agenda, incluida la astronomía calculada localmente (Meeus) + tabla de El Niño |
| `POST /api/weather/context` | Extracto acotado y consentido del reanálisis de Open-Meteo para corroborar |
| `… /api/law/...` | Flujo de cambios de la legislación y las fuentes primarias seguidas |
| `… /api/integrity/...` | Señales de eco / coordinación / linaje |
| `… /api/annotations/...` | Anotaciones locales de artículos, opcionalmente firmadas |
| `… /api/wiki/...` | Ediciones de Wikipedia, páginas seguidas, descarga/lectura de volcados, sincronización con el corpus |
| `… /api/hazards/...`, `/api/timemap` | Capas de riesgos + mapa espaciotemporal |
| `GET /unlock`, `POST /api/unlock`, `/create-db`, `/doctor`, `/encrypt-db` | Cifrado en reposo: pantalla de desbloqueo al arrancar bloqueado, creación de un almacén cifrado/en texto plano, comprobación de la cabecera, herramienta de cifrado unidireccional |

Los routers marcados **[analysis]** (materias primas, estadística, palabras clave, encuadre)
requieren el extra `[analysis]`; sin él, la aplicación arranca igualmente con el
núcleo y esos endpoints quedan desactivados.

Notas de comportamiento:
- La ingesta descarga únicamente a través del descargador ético (robots.txt con cierre por defecto, frecuencia
  limitada); los endpoints del LLM devuelven **503** si Ollama no está disponible (nunca una respuesta falsa).
- Verificación de pruebas: proporcione la clave pública del firmante para demostrar la procedencia, no solo la
  integridad (consulte [QUICKSTART](QUICKSTART.md) y `scripts/verify_evidence.py`).
- Los ajustes de custodia son *preferencias*, no garantías: `GET/PUT /api/custody/settings`
  informan siempre del estado **efectivo** (preferencia **y** disponibilidad de la biblioteca), de modo que
  la firma poscuántica / OpenTimestamps nunca aparecen activados cuando falta el extra que los
  sustenta. El anclaje usa por defecto el proveedor `local` sin conexión; OpenTimestamps y
  el anclaje en cadenas públicas llevan una advertencia de privacidad (consulte
  [CHAIN_OF_CUSTODY](USER_MANUAL.md)).


---

## Internacionalización (i18n): hacer la aplicación multilingüe

> Objetivo: **toda la interfaz** (y, con el tiempo, la **documentación**) disponible en ~una
> docena de idiomas, para ampliar el acceso abierto hacia «casi todos los seres humanos». Hecho a la
> manera del proyecto: **sin conexión, sin CDN, sin API de traducción en tiempo de ejecución, sin telemetría**, y
> **con honestidad** sobre la calidad de la traducción (no publicamos conjeturas automáticas como si fueran
> autorizadas).

---

### La docena de idiomas (conjunto de la Fase 1)

Elegidos por su alcance (hablantes nativos y de segunda lengua) y para incluir deliberadamente el
Sur Global (según el objetivo antisesgo de `ROADMAP.md`):

| Código | Idioma | Nombre nativo | Escritura / dirección | Estado |
|---|---|---|---|---|
| `en` | Inglés | English | LTR | **origen** (completo) |
| `fr` | Francés | Français | LTR | **completo** (avalado) |
| `es` | Español | Español | LTR | **completo** (avalado) |
| `de` | Alemán | Deutsch | LTR | **completo** (avalado) |
| `zh` | Chino (mandarín) | 中文 | LTR | completo (traducido, ciclo `0.4`; aún no avalado) |
| `hi` | Hindi | हिन्दी | LTR | completo (traducido, ciclo `0.4`; aún no avalado) |
| `ar` | Árabe | العربية | **RTL** | completo (traducido, ciclo `0.4`; aún no avalado) |
| `bn` | Bengalí | বাংলা | LTR | completo (traducido, ciclo `0.4`; aún no avalado) |
| `ru` | Ruso | Русский | LTR | completo (traducido, ciclo `0.4`; aún no avalado) |
| `pt` | Portugués | Português | LTR | completo (traducido, ciclo `0.4`; aún no avalado) |
| `id` | Indonesio | Bahasa Indonesia | LTR | completo (traducido, ciclo `0.4`; aún no avalado) |
| `ja` | Japonés | 日本語 | LTR | completo (traducido, ciclo `0.4`; aún no avalado) |

Próximas incorporaciones sencillas por su alcance: **suajili (`sw`)**, **urdu (`ur`, RTL)**, italiano
(`it`), turco (`tr`), vietnamita (`vi`).

**Postura de honestidad.** Un *esbozo* hace que un idioma sea **seleccionable desde ya** y recurre al
inglés para cualquier cadena sin traducir: una configuración regional parcial nunca rompe la interfaz (este es
el mecanismo del que parte cualquier configuración regional futura: `it`, `tr`, `vi`, …). Marcamos cada configuración regional como `complete | draft | stub`. El mantenedor
solo publica lo que puede avalar; todo lo demás se completa mediante la **contribución
de la comunidad** (así es precisamente como el código abierto amplía el acceso).

---

### Arquitectura (sin conexión, sin dependencias)

`src/static/i18n.js` + `src/static/locales/<code>.json`. Sin paso de compilación, sin red.

- **El inglés es la clave.** Los archivos de configuración regional asocian la **cadena de interfaz en inglés → su traducción**
  (p. ej., `"Search the corpus": "Rechercher dans le corpus"`). Esto nos permite adaptar la
  interfaz existente sin etiquetar cada elemento, y mantiene el inglés como fuente
  canónica.
- **`OOI18N.setLang(code)`** carga `locales/<code>.json`, guarda la elección en
  `localStorage` (`oo.lang`), define `document.documentElement.lang` y `dir` (RTL para
  `ar`/`ur`) y luego **`apply()`** recorre el DOM, traduciendo los nodos de texto cuyo texto
  recortado coincide con una clave, además de los atributos `placeholder`/`title`/`aria-label`. Las cadenas
  desconocidas se dejan tal cual (recurso al inglés): nunca se rompe nada.
- **El contenido dinámico** (datos: títulos de artículos, nombres de fuentes, recuentos) **nunca** se
  traduce: solo la interfaz. La interfaz renderizada por JS (paleta de comandos, panel lateral) llama a
  `OOI18N.apply()` después de renderizarse.
- Cada configuración regional lleva `_meta` (`name`, `native`, `dir`, `status`).

#### Integración (Fase 2: publicada; Desk se ha retirado desde entonces)

Dos líneas en `index.html` (y, antes de su retirada el 2026-06-10, en `desk.html`),
y después un selector de idioma:

```html
<script src="/static/i18n.js"></script>
<!-- after first render and on each view change: --> OOI18N.apply();
```

El selector de **Idioma** está en Ajustes y llama a `OOI18N.setLang(code)`,
guardado junto con las demás preferencias locales de la interfaz.

---

### Documentación en muchos idiomas

Los documentos son largos y la calidad de la traducción importa más que en las cadenas cortas de la interfaz, por lo que:

- Estructura: `docs/i18n/<code>/<DOC>.md` replica `docs/`.
- **Los documentos en inglés siguen siendo los canónicos**; las traducciones son trabajo de la comunidad o del mantenedor,
  cada una marcada con su fecha de traducción y el commit en inglés al que corresponde.
- **No** traducimos automáticamente los documentos para presentarlos como autorizados: eso
  violaría el principio de honestidad del proyecto. Se empieza por los documentos de mayor valor y más cortos
  (QUICKSTART, el recorrido «Lo que verá primero», ETHICS) en cada idioma.

---

### Flujo de contribución (acceso abierto por diseño)

1. Copie `locales/en.json` → `locales/<code>.json`, traduzca los valores y defina `_meta.status`.
2. Para los idiomas RTL, defina `_meta.dir: "rtl"`.
3. Ejecute la comprobación (prevista) de cobertura de claves: informa de las claves que faltan o sobran respecto a `en.json`.
4. Envíe su contribución. Las claves sin traducir simplemente recurren al inglés hasta que se completen.

---

### Estado

**Fase 1 (hecha):** el motor i18n (`i18n.js`), la estructura de configuraciones regionales para los 12
idiomas y las traducciones de referencia completas para **en/fr/es/de**.

**Fase 1b (hecha, `0.4.0`):** las cadenas de interfaz restantes se convirtieron en claves y se
tradujeron a **los doce** idiomas (consulte `CHANGES.md` 0.4.0), de modo que cada
configuración regional de `src/static/locales/*.json` contiene ahora el conjunto completo de claves (verificado:
12 archivos, 6.991 claves cada uno, ninguna ausente). La honestidad no cambia: los nombres son
nombres propios y no se traducen, y una configuración regional parcial sigue recurriendo al
inglés en lugar de romperse.

**Fase 2 (hecha, pendiente de una prueba real en navegador):** `i18n.js` se incluye en
`index.html` (y lo estaba en `desk.html` hasta la retirada de Desk el 2026-06-10); hay un
selector de **Idioma** (`#oo-lang-select`) en Ajustes, conectado automáticamente; la interfaz renderizada dinámicamente se traduce automáticamente mediante
un `MutationObserver` con antirrebote (sin llamadas a `apply()` dispersas); volver al inglés
restaura los originales; RTL mediante `<html dir>`. La estructura y la sintaxis están validadas, pero
el comportamiento aún debería comprobarse a simple vista en un navegador.

**Fase 3 (siguiente):** ampliar `en.json` al catálogo *completo* de cadenas (actualmente
cubre la interfaz más usada), completar las configuraciones regionales en esbozo (comunidad) y pulir
el diseño RTL para `ar`/`ur`.


## Contrato de exportación (versionado)

Las exportaciones legibles por máquina llevan un contrato estable y autodescriptivo (esquema `oo-export-1`,
0.0.8 parte 2 / RM-15) para que los procesos posteriores nunca tengan que adivinar:

- **JSON** (`/api/articles/export?format=json`, `/api/links/export.json`): un sobre:
  `{export_schema, kind, app_version, generated_at, query, count, articles|data}`. El objeto
  `query` es la selección generadora literal; la procedencia viaja con los datos.
- **CSV** (`/api/articles/export?format=csv`): sin línea de comentario (rompería a los lectores ingenuos);
  el mismo sobre viaja como cabeceras HTTP (`X-OO-Export-Schema`, `X-OO-App-Version`,
  `X-OO-Generated-At`, `X-OO-Query`). Las columnas conservan su orden, y una columna nueva solo se
  añade al final: `Fetched From Host` (punto 61 de la cola), el host desde el que se descargó la página tras
  sus redirecciones, vacío cuando no se registró; la exportación JSON lo lleva como `fetched_host`.
- **Grafo de citas** (`/api/links/export.graphml`, `.json`): el grafo de quién cita a quién
  (artículos almacenados → dominios registrables externos). **Solo recuentos: ninguna credibilidad
  inferida, ninguna puntuación**; la advertencia va incrustada en el propio archivo. GraphML se abre en
  Gephi/yEd/NetworkX.

Los cambios de esquema incrementan `oo-export-N`; los campos existentes nunca se reutilizan en silencio para otro fin. Un campo
añadido junto a ellos (una columna CSV al final, una clave JSON nueva) deja los campos de todos los lectores existentes
donde estaban, por lo que no incrementa el esquema.
