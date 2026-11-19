<!-- es: Translation of docs/GOVERNANCE.md written by AI (2026-11-19, R677; native review dropped by R721, 2026-11-14); it may contain mistakes, and the English original is authoritative. Coverage: the whole document, 7 of 7 headings. Corrections are welcome as a pull request. -->

# Gobernanza y uso aceptable

Open Omniscience es una herramienta para **pedir cuentas al poder** ayudando a las personas a ver
con honestidad la *estructura* de la información pública. Como esa capacidad es poderosa, este
documento expone con claridad para qué sirve la herramienta, las líneas que no cruzará y cómo
pretende seguir siendo digna de confianza a medida que crece. Esto forma parte de la ética del
proyecto, no es una idea de último momento.

## Para qué sirve

- **Periodismo de investigación e investigación de interés público** sobre medios, instituciones,
  mercados y textos legales *publicados* — haciendo visible una estructura medible (concentración
  de la propiedad, coordinación/eco, novedad, encuadre, cambio a lo largo del tiempo) para que una
  persona la juzgue.
- **Protección de fuentes y reproducibilidad** — local primero, utilizable sin conexión, con una
  procedencia que deja en evidencia cualquier manipulación, para que los hallazgos puedan
  defenderse. El registro de cadena de custodia, encadenado por hash y firmado, es **opcional**
  (desactivado por defecto — añade un pequeño coste de firma por artículo): actívelo en
  **Ajustes → Cadena de custodia → «Registrar automáticamente al ingerir»**
  (o `OO_CUSTODY_ON_INGEST=1`) cuando la integridad probatoria importe para un caso. Mientras
  tanto, la procedencia acompaña igualmente a cada artículo (fuente, hora de captura, hash del
  contenido) y pueden generarse paquetes de pruebas firmados bajo demanda.

## Líneas rojas de doble uso (ausentes por construcción, no configurables)

Las mismas técnicas que exponen una operación de influencia coordinada podrían, en malas manos,
dirigirse contra personas corrientes. La línea que hace de esto un instrumento de *rendición de
cuentas* y no una herramienta de *vigilancia* es precisa, y se mantiene en la **arquitectura**, no
en un ajuste que un usuario pudiera cambiar:

1. **Ningún seguimiento de particulares.** La herramienta analiza *fuentes publicadas* (medios,
   instituciones, documentos públicos). **No** elabora perfiles de personas privadas, y
   `src/compliance/gdpr.py` es la salvaguarda. La prominencia mide la *cobertura de figuras
   públicas sobre las que ya se ha escrito* — atención, nunca importancia ni mérito.
2. **Ninguna identificación biométrica.** Ningún reconocimiento facial, de voz ni de la forma de
   andar. Nunca.
3. **Ninguna ingesta de canales privados.** Nada de mensajes directos, feeds privados, mensajes
   interceptados ni datos no públicos. El corpus se construye a partir de fuentes a las que el
   usuario puede acceder de forma legal y ética.
4. **Ningún veredicto automatizado.** Ninguna puntuación de verdad, credibilidad o «confianza»,
   ninguna etiqueta de «sesgado»/«falso». La herramienta muestra *mediciones con método +
   salvedad*; la persona saca las conclusiones. (Impuesto en el código:
   `assert_no_score_fields`.)
5. **Ningún servidor central, cuentas ni telemetría.** Nada sale de la máquina del usuario salvo
   las descargas que él dirige. No hay un tarro de miel de datos de usuarios que incautar o
   reclamar por vía judicial.
6. **Ningún filtrado ni rebaja silenciosa de fuentes.** Los datos de cobertura se *muestran*;
   cualquier atenuación la aplica el usuario, queda señalada y es reversible — mostrar, nunca
   imponer.

Se imponen hasta donde el código puede: una prueba de CI
(`tests/test_repo_invariants.py::test_red_lines_not_crossed`) hace fallar la compilación si
aparecen en el código capacidades prohibidas (reconocimiento biométrico, seguimiento de
individuos). Una prueba es un cable trampa, no una demostración — la verdadera garantía son la
cultura y la revisión.

## Postura jurídica y ética

- Un **espejo de investigación**, no la fuente de referencia, y **no asesoramiento jurídico**;
  cada registro enlaza con su origen.
- **Acceso ético** por defecto: robots.txt con fallo cerrado, límites de frecuencia por host, un
  User-Agent que se identifica, atribución y procedencia almacenadas. (Un usuario puede activar la
  descarga *Protegida* — proxy + UA genérico, salvo en las solicitudes propias de la aplicación de
  Wikipedia, Wikidata y volcados a Wikimedia, cuya política de API pide que cada herramienta se
  identifique — para proteger a una fuente o protegerse a sí mismo al investigar a un objetivo
  poderoso; es el deber periodístico de protección de las fuentes, asumido deliberadamente y
  documentado, nunca el comportamiento silencioso por defecto.)
- **Respetar las licencias y los derechos de autor**; almacenar la procedencia y lo mínimo
  necesario; cumplir las obligaciones de protección de datos de cada jurisdicción.

## Independencia y financiación

La herramienta es deliberadamente **barata de ejecutar** (local, sin infraestructura) para poder
seguir siendo **independiente**. Si el proyecto acepta alguna vez financiación, evitará quedar
capturado por un único financiador o agenda, tomará sus decisiones de forma transparente y nunca
doblegará la definición de «desinformación» para complacer a un patrocinador. La decisión más
política que toma este proyecto es seguir siendo pequeño, local e imposible de capturar.

## Resistencia al uso indebido

Ninguna herramienta puede impedir todo uso indebido, y no fingiremos lo contrario. Nuestra
resistencia es estructural: las líneas rojas anteriores, el diseño local primero (sin datos
centrales de los que abusar a gran escala), la negativa a emitir veredictos y la apertura
(cualquiera puede inspeccionar, bifurcar y auditar). Si cree que el proyecto está siendo empujado
más allá de una línea roja, abra una incidencia — esa posibilidad de impugnación es precisamente el
objetivo.

## Cómo se toman las decisiones (intención)

Hoy es un proyecto temprano con un único mantenedor. Antes de una alfa pública `0.1` pretendemos:
una **revisión externa de seguridad y ética**, una transición hacia una **gobernanza con varios
mantenedores** con toma de decisiones transparente, y un **pacto de contribución** que vincule a
los colaboradores con las líneas rojas. Hasta entonces, este documento es el compromiso de
referencia.
