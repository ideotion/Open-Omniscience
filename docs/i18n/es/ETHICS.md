<!-- es: Translation of docs/ETHICS.md written by AI (2026-11-19, R677; native review dropped by R721, 2026-11-14); it may contain mistakes, and the English original is authoritative. Coverage: the whole document, 50 of 50 headings. Corrections are welcome as a pull request. -->

# Directrices éticas de Open Omniscience

> **Estado (revisado el 2026-10-08):** el software es una **alfa** funcional y probada
> (`v0.5.0`: consulte el README del repositorio para ver lo que funciona hoy; la redacción de la época 0.0.9 que sigue se
> conserva como registro histórico del momento en que estas directrices entraron en vigor). Las primeras versiones llevaban aquí un
> aviso de «no funcional»; dejó de ser cierto y se retiró:
> estas directrices están **en vigor ahora**, no son una referencia para el futuro.
> *Nota histórica:* las primeras versiones conceptuales (anteriores a 0.0.4) partieron
> del copiador de sitios web HTTrack; el código actual es una reescritura completa y
> no comparte código con él.

Este documento expone los **principios éticos, los requisitos de cumplimiento y las buenas prácticas** para usar Open Omniscience y contribuir a él. El respeto de estas directrices es **obligatorio** para todos los usuarios y desarrolladores.

Open Omniscience se adhiere a la **Carta de Múnich**, un conjunto fundamental de principios para periodistas adoptado en 1971. Esos principios se integran a continuación para guiar el uso ético de esta plataforma.

---

## 📜 Carta de Múnich: Declaración de deberes y derechos

### Preámbulo
El derecho a la información, a la libertad de expresión y de crítica es uno de los derechos fundamentales de la humanidad. Todos los derechos y deberes de quienes usan Open Omniscience emanan del derecho del público a conocer los hechos y las opiniones. La responsabilidad de los usuarios ante el público prevalece sobre cualquier otra responsabilidad, en particular ante los empleadores y los poderes públicos. La misión de informar comporta necesariamente límites que los usuarios deben imponerse espontáneamente. Tal es el objeto de la declaración de deberes formulada a continuación.

Un usuario de Open Omniscience solo puede respetar estos deberes en el ejercicio de su uso si existen efectivamente condiciones de independencia y de dignidad profesional. Tal es el objeto de la siguiente declaración de derechos.

---

### 📋 Declaración de deberes
Las obligaciones esenciales de los usuarios de Open Omniscience dedicados a recopilar, editar y analizar información son:

1. **Respeto a la verdad:**
   Respetar la verdad, cualesquiera que sean las consecuencias para uno mismo, en razón del derecho del público a conocer la verdad.

2. **Defender la libertad de información:**
   Defender la libertad de información, de comentario y de crítica.

3. **Verificar las fuentes:**
   Publicar únicamente hechos cuyo origen se conozca; no suprimir informaciones esenciales ni alterar textos y documentos.

4. **Métodos leales:**
   No emplear métodos desleales para obtener informaciones, fotografías o documentos.

5. **Respetar la vida privada:**
   Obligarse a respetar la vida privada de las personas.

6. **Corregir las inexactitudes:**
   Rectificar toda información publicada que resulte ser inexacta.

7. **Secreto profesional:**
   Guardar el secreto profesional y no divulgar la fuente de las informaciones obtenidas confidencialmente.

8. **Evitar las faltas profesionales:**
   Considerar como faltas profesionales graves:
   - El plagio
   - La calumnia, la difamación y las acusaciones sin fundamento
   - La aceptación de cualquier forma de soborno a cambio de publicar o de suprimir una información

9. **Separación de la publicidad y la propaganda:**
   No confundir nunca el uso de Open Omniscience con la venta de publicidad o con actividades de propaganda, y rechazar cualquier consigna, directa o indirecta, de los anunciantes.

10. **Resistir las presiones:**
    Resistir toda presión y aceptar órdenes únicamente de personas responsables comprometidas con el uso ético de la plataforma.

---

### 📜 Declaración de derechos

Los usuarios de Open Omniscience reivindican:

1. **Libre acceso a la información:**
   El libre acceso a todas las fuentes de información y el derecho a investigar libremente todos los hechos que condicionan la vida pública. Por ello, el secreto de los asuntos públicos o privados solo puede oponerse a los usuarios en casos excepcionales y por motivos claramente expresados.

2. **Rechazar la subordinación contraria a la ética:**
   El derecho a negarse a cualquier subordinación contraria a la línea general de Open Omniscience, así como a cualquier subordinación que esa línea no implique claramente.

3. **Conciencia y convicción:**
   No se puede obligar a un usuario a realizar un acto ni a expresar una opinión contrarios a sus convicciones o a su conciencia.

4. **Transparencia en la toma de decisiones:**
   La comunidad debe ser informada de todas las decisiones importantes que puedan influir en el proyecto. Debe, como mínimo, ser consultada antes de que se adopte una decisión definitiva sobre cualquier asunto relativo a la orientación del proyecto.

5. **Reconocimiento justo e independencia:**
   Habida cuenta de sus funciones y responsabilidades, los colaboradores tienen derecho a un reconocimiento y a unas condiciones que garanticen la seguridad material y moral de su trabajo, así como su independencia económica.

---

## 🌍 Principios fundamentales de Open Omniscience

1. **Respeto de las condiciones de las fuentes:** Cumplir siempre las directivas de `robots.txt` y las condiciones de servicio de los sitios web recopilados.
2. **Limitación de la frecuencia:** La ruta única de descarga (`EthicalFetcher`) impone un
   intervalo mínimo entre peticiones por host y toma un bloqueo por host, de modo que nunca
   hay más de una petición en curso a la vez hacia un mismo host.
   - Por defecto: **1 petición por segundo y por host**: el `min_interval_s` de
     `EthicalFetcher`, fijado a partir de la variable de entorno `OO_FETCH_MIN_INTERVAL`.
   - Cuando el `robots.txt` de un host publica un **`Crawl-delay`**, se respeta: el
     intervalo efectivo es `max(min_interval, Crawl-delay)`.
   - (El `rate_limit_ms` por fuente de `sources.yml` es un campo de datos, **no** está
     conectado al intervalo del descargador; las dos palancas anteriores son las que realmente limitan.)
3. **Transparencia:** La actividad de descarga se registra localmente para que el operador
   la revise: los veredictos por fuente/canal en `data/source_preflight.jsonl` y
   `data/feed_preflight.jsonl`, los resultados de las pruebas de campo en `data/field_test.jsonl` y
   los errores de la aplicación en `data/app_errors.jsonl`. Permanecen en la máquina y se agrupan,
   **solo con un clic**, en el **paquete de depuración** de Ajustes → diagnóstico, y
   nunca se transmiten automáticamente. (No existe `audit/scrape_log.csv`; era un diseño temprano
   que la postura local primero y sin telemetría sustituyó.)
4. **Minimización de datos:** Recopilar y almacenar únicamente los datos necesarios para la funcionalidad esencial de la plataforma (URL, título, contenido, metadatos).
5. **Uso no malicioso:** Open Omniscience no debe utilizarse para:
   - Spam o acoso.
   - Actividades ilegales (p. ej., piratería informática, infracción de derechos de autor).
   - Explotación comercial sin permiso.
6. **Identificación mediante User-Agent:** Usar una cadena User-Agent clara e identificable. El bot
   envía `OpenOmniscienceBot/{version} (+https://github.com/ideotion/Open-Omniscience; ethical research crawler)`
   (las descargas protegidas o enrutadas por Tor envían en su lugar un UA de navegador genérico, para pasar desapercibidas).
7. **Limitación por IP:** Evitar ráfagas de peticiones desde una misma IP. Respetar el uso razonable de los servidores.

---

## ✅ Lista de verificación de cumplimiento

Antes de recopilar una fuente nueva, verifique lo siguiente:
- [ ] El dominio **no** figura en la [Lista de sitios que no se deben recopilar](#lista-de-sitios-que-no-se-deben-recopilar).
- [ ] El archivo `robots.txt` permite la recopilación (compruebe [https://{domain}/robots.txt](https://{domain}/robots.txt)).
- [ ] La fuente **no** requiere autenticación ni obliga a sortear muros de pago.
- [ ] Los límites de frecuencia están configurados para evitar **más de 1 petición por segundo** por defecto (ajústelos para dominios sensibles).
- [ ] La cadena User-Agent identifica a Open Omniscience (`OpenOmniscienceBot/{version}`).
- [x] Los veredictos de descarga se registran localmente (`data/*_preflight.jsonl`) y se exponen
  con un clic a través del paquete de depuración de Ajustes; nunca se transmiten automáticamente.

---

## 🚫 Lista de sitios que no se deben recopilar

Esta lista es una **orientación para el operador**, no una lista de bloqueo aplicada mecánicamente: la aplicación
no incluye un bloqueo codificado de estos dominios. La protección a nivel de código es el **robots.txt
con cierre por defecto** en la ruta única `EthicalFetcher`: una fuente cuyo `robots.txt` no puede
descargarse o no autoriza claramente la URL se rechaza, no se recopila. Aun así, los operadores deben
ejercer su criterio y evitar las categorías siguientes al añadir fuentes:

### Contenido de pago


### Plataformas de redes sociales


### Datos privados o sensibles
- Bases de datos gubernamentales (p. ej., `*.gov`, `*.mil` salvo que sean explícitamente públicas)
- Historiales médicos (p. ej., `*.health`, `*.medical`)
- Registros financieros (p. ej., `*.bank`, `*.finance` salvo que sean públicos)
- Repositorios de datos personales (p. ej., `*.personal`, `*.private`)

### Restricciones técnicas
- Dominios con una **limitación de frecuencia agresiva** (p. ej., `github.com`, `stackoverflow.com`).
- Dominios que **bloquean a los recopiladores** (p. ej., sitios protegidos por `cloudflare.com` sin vía de acceso).
- **Fuentes solo accesibles por API** (p. ej., `twitter.com/api`, `reddit.com/api`: use en su lugar las API oficiales).

> **Nota:** Esta lista no es exhaustiva. Los usuarios deben actuar con la **debida diligencia** y con **juicio crítico** al añadir fuentes nuevas. En caso de duda, **no recopile**. 

---

## 📊 Auditoría y rendición de cuentas

La actividad de descarga se registra **localmente**, para que el operador la revise, y solo se comparte
**con un clic**: nunca se transmite automáticamente (sin telemetría; local primero por diseño). El
mecanismo real (el diseño temprano de `audit/scrape_log.csv` fue sustituido por este):

- **Veredictos de verificación previa**: los resultados de accesibilidad/robots/transporte por fuente y por canal
  se añaden a `data/source_preflight.jsonl` y
  `data/feed_preflight.jsonl` (cada línea: marca de tiempo, fuente/dominio, el veredicto
  según el transporte y el motivo honesto). Alimentan la función «Reintentar los canales fallidos» y los
  veredictos por canal de Índices/mercados.
- **Resultados de las pruebas de campo**: cuando el modo de prueba de campo está activado, los ejercicios sobre las superficies de descarga se
  escriben literalmente en `data/field_test.jsonl`.
- **Errores de la aplicación**: limitados en `data/app_errors.jsonl` (se conservan las líneas más recientes).

### Compartir para obtener ayuda

No existe ningún CSV/`errors.log` subido automáticamente. El operador puede generar un **paquete de depuración**
(Ajustes → diagnóstico) que reúne los registros JSONL anteriores junto con los diagnósticos de palabras clave/red;
se escribe en disco y solo se comparte por una acción explícita del operador.
Este es el protocolo del mantenedor: recorra la aplicación con clics y luego entregue el paquete.

---

## 🔒 Privacidad y protección de datos

- **Sin seguimiento de usuarios:** Open Omniscience **no** recopila ni almacena:
  - Las IP de los usuarios
  - Los historiales de búsqueda
  - Datos personales
- **Solo local:** Todos los datos permanecen en la máquina del usuario. Sin dependencia de la nube por defecto.
- **Cifrado en reposo (activado por defecto):** Los corpus nuevos se crean **cifrados** con
  SQLCipher, protegidos por una frase de contraseña que el usuario elige en el primer arranque. Usar una base de datos
  **en texto plano** es una exclusión explícita que exige confirmar por escrito el
  riesgo indicado. **No hay recuperación** posible de una frase de contraseña olvidada (el corpus puede
  reconstituirse volviendo a recopilar, por lo que no se añade ninguna clave de recuperación ni segunda vía de descifrado). El modelo de amenaza es una máquina incautada o copiada que está **apagada**, no una
  sesión comprometida que ya se está ejecutando (consulte `SECURITY.md`).
- **Cumplimiento del RGPD:** Si recopila fuentes con sede en la UE:
  - Anonimice los datos personales (p. ej., nombres, correos electrónicos) en el contenido almacenado.
  - Respete el derecho de supresión (borre los datos cuando se solicite).

---

## 🌍 Consideraciones jurídicas

- **Derechos de autor:** Respete la legislación sobre derechos de autor. Recopile y almacene contenido únicamente para:
  - Un análisis **personal y no comercial**.
  - Un **uso legítimo** (*fair use*) (p. ej., crítica, comentario, investigación).
  - **Fines transformadores** (p. ej., agregación para el periodismo de investigación).
- **Cumplimiento del RGPD:** Si trata datos de ciudadanos de la UE:
  - Minimice la recopilación de datos personales.
  - Ofrezca a las personas un medio para solicitar la supresión de sus datos.
- **Jurisdicción:** Los usuarios son responsables de cumplir las leyes de su jurisdicción, entre ellas:
  - **Computer Fraud and Abuse Act (CFAA)** (EE. UU.)
  - **Reglamento General de Protección de Datos (RGPD)** (UE)
  - **Leyes de derechos de autor** (varios países)

---

## 🛡️ Salvaguardas técnicas

Para prevenir los usos indebidos y garantizar una recopilación ética, Open Omniscience aplica las siguientes salvaguardas:

1. **Limitación de la frecuencia:**
   - Por defecto: 1 petición por segundo y por host (`min_interval_s`, a partir de `OO_FETCH_MIN_INTERVAL`).
   - Se respeta el `Crawl-delay` del robots de un host cuando es mayor; una sola petición por host a la vez.

2. **Cumplimiento de robots.txt:**
   - Comprueba automáticamente `robots.txt` antes de recopilar.
   - Respeta las directivas `Disallow`.

3. **Identificación mediante User-Agent:**
   - Envía `OpenOmniscienceBot/{version} (+https://github.com/ideotion/Open-Omniscience; ethical research crawler)`.
   - Las descargas protegidas (enrutadas por Tor) envían un UA de navegador genérico para no llamar la atención.

4. **Gestión de errores:**
   - Reintenta las peticiones fallidas con una espera exponencial.
   - Registra todos los errores para su revisión.

5. **Detección de duplicados:**
   - Usa la canonicalización de URL y el hash del contenido para evitar recopilaciones redundantes.

6. **Registros de auditoría:**
   - Registra todas las actividades de recopilación con fines de transparencia y rendición de cuentas.

---

## 📐 Métricas honestas: ninguna puntuación inventada

Honestidad por construcción: la aplicación nunca presenta una **puntuación compuesta de confianza / calidad /
credibilidad**. Cada señal que calcula lleva su método, una advertencia y su
*n*; una tarjeta que intentara publicar una puntuación combinada sería rechazada mecánicamente por el esquema
de tarjetas. Las columnas de puntuación latentes (`credibility_score`, `political_bias`) se mantienen
en NULL y nunca se serializan en ninguna respuesta de la API.

**Una excepción intencionada y acotada: `reliability_score`.** Este campo `1–10` por fuente
son **metadatos de procedencia declarados por el operador**: un número que *usted* (el operador)
fija para cada fuente mediante la configuración o una importación CSV. La aplicación **nunca lo calcula, nunca le asigna un valor por defecto
y nunca lo deriva de los datos de los artículos**: el antiguo valor por defecto inventado `=5`
se eliminó (puesto a NULL por la migración `f4b5c6d7e8a9`). Como es su propia
afirmación (no un veredicto fabricado por la herramienta), se muestra en la lista de fuentes
y se etiqueta como **«fijado por el operador, no calculado»** allí donde aparece; una tarjeta del resumen
nunca puede presentarlo como una puntuación. Un invariante del repositorio
(`tests/test_repo_invariants.py::test_reliability_score_is_operator_set_never_computed`)
lo mantiene así, de modo que no pueda convertirse discretamente en un veredicto de calidad calculado.

---

## 📢 Denunciar infracciones

Si observa o sospecha un uso no ético de Open Omniscience:
1. **Detenga** inmediatamente la actividad infractora.
2. **Documente** el incidente (p. ej., capturas de pantalla, registros, marcas de tiempo).
3. **Denúncielo** a los mantenedores a través de:
   - [GitHub Issues](https://github.com/ideotion/Open-Omniscience/issues) (para denuncias públicas)
   - Correo electrónico: `open-omniscience@ideotion.com` (para denuncias sensibles)

---

## 📅 Revisión y actualizaciones

Este documento se **revisará y actualizará periódicamente** para reflejar:
- Nuevos retos éticos (p. ej., contenido generado por IA, ultrafalsificaciones o *deepfakes*).
- Requisitos legales (p. ej., cambios en la legislación sobre derechos de autor o protección de datos).
- Las aportaciones de la comunidad (p. ej., denuncias de usos indebidos o sugerencias de mejora).

### Historial de versiones
| Versión | Fecha      | Cambios                                                                 |
|---------|------------|-------------------------------------------------------------------------|
| 1.0     | 2026-05-07 | Versión inicial. Se añadieron la Lista de sitios que no se deben recopilar, el registro de auditoría y las notas sobre el RGPD. |
| 1.1     | 2026-05-07 | Se añadieron la identificación mediante User-Agent, la limitación por IP y las salvaguardas técnicas. |

---

## 📌 Buenas prácticas para colaboradores

1. **Pruebe de forma ética:**
   - Pruebe siempre la recopilación a pequeña escala antes de ampliarla.
   - Use `localhost` o entornos de preproducción siempre que sea posible.

2. **Documente las fuentes:**
   - Añada comentarios en `sources.yml` que expliquen por qué se incluye o excluye una fuente.
   - Indique cualquier requisito especial de recopilación (p. ej., selectores personalizados).

3. **Respete las solicitudes de exclusión:**
   - Si una fuente pide ser retirada, cúmplalo de inmediato.
   - Añada el dominio a la Lista de sitios que no se deben recopilar.

4. **Minimice el impacto:**
   - Recopile en horas de menor actividad siempre que sea posible.
   - Almacene las respuestas en caché para evitar peticiones repetidas del mismo contenido.

5. **Manténgase al día:**
   - Compruebe periódicamente los cambios en `robots.txt`.
   - Siga la evolución legal (p. ej., nuevas leyes de derechos de autor).

---
**Recuerde:** La recopilación ética no es solo una obligación legal: es una **responsabilidad moral**. Al usar Open Omniscience, se compromete a respetar estos principios.

---

# Cumplimiento, licencias y avisos de terceros

El complemento jurídico y de atribuciones de los principios éticos anteriores.

**En esta parte:**
- [Guía de cumplimiento de la GPLv3](#guía-de-cumplimiento-de-la-gplv3)
- [Avisos y atribuciones de terceros](#avisos-y-atribuciones-de-terceros)


---

## Guía de cumplimiento de la GPLv3

Esta sección describe el cumplimiento por parte de Open Omniscience de la Licencia Pública
General de GNU versión 3 (GPLv3). Se aplica al software funcional tal como se distribuye.

---

### 📜 Licencia de Open Omniscience

**Licencia:** Licencia Pública General de GNU versión 3 (GPLv3)  
**Copyright:** © 2026 Ideotion  
**Archivo de licencia:** [LICENSE](../LICENSE)

Open Omniscience está íntegramente licenciado bajo la GPLv3, que otorga a los usuarios las
siguientes libertades (el software es una prealfa funcional y probada: se aplican ya):

1. **Libertad 0:** La libertad de ejecutar el programa con cualquier propósito
2. **Libertad 1:** La libertad de estudiar cómo funciona el programa y modificarlo
3. **Libertad 2:** La libertad de redistribuir copias
4. **Libertad 3:** La libertad de distribuir versiones modificadas

---

### ✅ Lista de verificación del cumplimiento de la GPLv3

#### Para el proyecto Open Omniscience

- [x] **Archivo de licencia**: El texto completo de la GPLv3 se incluye en [LICENSE](../LICENSE)
- [x] **Disponibilidad del código fuente**: Todo el código fuente está disponible públicamente en este repositorio
- [x] **Avisos de copyright**: Los módulos fuente llevan un aviso `Copyright (C) 2026 Ideotion`;
  el [LICENSE](../LICENSE) del proyecto rige la obra en su conjunto
- [x] **Cabeceras de licencia**: La mayoría de los módulos fuente llevan una cabecera de estilo SPDX `GPL-3.0-or-later`
  (algunos marcadores de paquete `__init__.py` vacíos y unos pocos módulos pequeños no la
  llevan). La GPLv3 **no** exige una cabecera por archivo: el archivo [LICENSE](../LICENSE) es
  el que rige toda la obra; los avisos por módulo son una cortesía, no una afirmación
  de que cada archivo lleve uno
- [x] **Ninguna restricción adicional**: No se impone ninguna restricción más allá de la GPLv3
- [x] **Versiones modificadas**: Todas las modificaciones llevan avisos visibles (Sección 5a)
- [x] **Información de instalación**: No aplicable (no es un Producto de Usuario según la definición de la GPLv3)

---

### 📦 Cumplimiento en la distribución

#### Distribución del código fuente

Al distribuir el código fuente de Open Omniscience:

1. ✅ **Incluir el archivo LICENSE**: Debe incluirse el texto completo de la licencia GPLv3
2. ✅ **Incluir ETHICS.md**: Deben incluirse las atribuciones de terceros
3. ✅ **Conservar las cabeceras**: Todos los archivos fuente deben conservar sus cabeceras GPLv3
4. ✅ **Conservar los avisos de copyright**: Deben conservarse todos los avisos de copyright
5. ✅ **Documentar los cambios**: Toda modificación debe documentarse

#### Distribución binaria

Al distribuir Open Omniscience en forma binaria:

1. ✅ **Incluir el código fuente**: Debe proporcionarse la Fuente Correspondiente (Sección 6)
2. ✅ **Incluir LICENSE**: Debe incluirse el texto completo de la GPLv3
3. ✅ **Incluir ETHICS.md**: Deben incluirse las atribuciones de terceros
4. ✅ **Documentar los cambios**: Toda modificación debe documentarse
5. ✅ **Ninguna restricción adicional**: No pueden añadirse restricciones más allá de la GPLv3

#### Cumplimiento para Productos de Usuario

Si Open Omniscience se distribuye como parte de un Producto de Usuario (dispositivo de consumo):

1. ✅ **Información de instalación**: Debe proporcionarse la información necesaria para instalar versiones modificadas (Sección 6)
2. ✅ **Disponibilidad del código fuente**: Debe proporcionarse la Fuente Correspondiente
3. ✅ **Sin tivoización**: No puede impedirse que los usuarios instalen versiones modificadas

**Nota:** Open Omniscience en sí no es un Producto de Usuario, pero si lo integra en uno, se aplican estos requisitos.

---

### 🔍 Pasos de verificación

#### Para desarrolladores

1. **Comprobar las cabeceras de licencia**
   ```bash
   grep -r "GNU General Public License" src/ tests/ package/ scripts/
   ```

2. **Verificar el archivo LICENSE**
   ```bash
   head -5 LICENSE
   ```

3. **Comprobar el archivo de AVISOS**
   ```bash
   cat ETHICS.md
   ```

4. **Verificar que no hay código propietario**
   ```bash
   # Check for any non-GPLv3 licensed code in active project
   find . -path "./.git" -prune -o -path "./archive" -prune -o -type f -print
   ```

#### Para usuarios

1. **Comprobar la licencia**
   ```bash
   cat LICENSE | head -5
   ```

2. **Revisar las atribuciones**
   ```bash
   cat ETHICS.md
   ```

---

### 📝 Preguntas frecuentes sobre el cumplimiento

#### P: ¿Puedo usar Open Omniscience con fines comerciales?
**R:** ¡Sí! La GPLv3 permite el uso comercial. Sin embargo, toda versión modificada que distribuya debe estar también licenciada bajo la GPLv3, y debe proporcionar el código fuente.

#### P: ¿Puedo usar Open Omniscience en software propietario?
**R:** No. La GPLv3 exige que las obras derivadas también se licencien bajo la GPLv3. No puede incorporar Open Omniscience a una aplicación propietaria de código cerrado.

#### P: ¿Tengo que publicar mis modificaciones?
**R:** Solo si las distribuye. Si modifica Open Omniscience para su propio uso y no lo distribuye, no necesita publicar sus modificaciones.

#### P: ¿Y las dependencias de Python?
**R:** Las dependencias de Python (FastAPI, SQLAlchemy, etc.) son obras independientes con sus propias licencias. La licencia GPLv3 de Open Omniscience no les afecta. Consulte [ETHICS.md](ETHICS.md) para más detalles.

#### P: ¿Y los datos que recopilo?
**R:** La licencia GPLv3 se aplica únicamente al propio software Open Omniscience, no a los datos que usted recopila. Usted es responsable de respetar los derechos de autor y las condiciones de servicio de los sitios web que recopila.

---

### 📞 Notificar problemas de cumplimiento

Si tiene preguntas o dudas sobre el cumplimiento de la GPLv3:

- **Correo electrónico:** open-omniscience@ideotion.com
- **GitHub:** https://github.com/ideotion/Open-Omniscience
- **GitHub Issues:** https://github.com/ideotion/Open-Omniscience/issues

---

### 📚 Recursos

- [Texto completo de la licencia GPLv3](../LICENSE)
- [Sitio web oficial de la GNU GPLv3](https://www.gnu.org/licenses/gpl-3.0.html)
- [Preguntas frecuentes sobre la GNU GPLv3](https://www.gnu.org/licenses/gpl-faq.html)
- [Avisos de terceros](ETHICS.md)

---

**Última actualización:** 2026-06-14


---

## Avisos y atribuciones de terceros

Esta sección contiene los avisos y atribuciones del software y las
bibliotecas de terceros que usa Open Omniscience. (*Nota histórica:* las versiones
conceptuales anteriores a 0.0.4 partieron de HTTrack; el código actual es una reescritura completa y
no queda en él ningún código de HTTrack.)

---

### 📦 Dependencias de Python

Open Omniscience **usa** los siguientes paquetes de Python, cada uno bajo su propia
licencia. La lista de referencia, en una única fuente, es [`pyproject.toml`](../pyproject.toml);
ejecute `pip show <package>` (o `pip-licenses`) para confirmar la licencia de cualquier
versión instalada. **Todas las dependencias son FOSS y compatibles con la GPLv3**: es un
requisito de inclusión (consulte el invariante «solo FOSS» en `docs/DESIGN.md`).

**Núcleo (siempre instalado):**

| Paquete | Licencia | Función |
|---------|---------|---------|
| FastAPI | MIT | Framework de API web |
| Uvicorn | BSD-3-Clause | Servidor ASGI |
| Jinja2 | BSD-3-Clause | Plantillas del lado del servidor |
| SlowAPI | MIT | Limitación de frecuencia |
| Prometheus Client | Apache-2.0 | Endpoint de métricas |
| SQLAlchemy | MIT | ORM de base de datos |
| Alembic | MIT | Migraciones de esquema |
| sqlcipher3 | Zlib/estilo BSD | Cifrado SQLCipher en reposo |
| Requests | Apache-2.0 | Cliente HTTP (descargador ético) |
| httpx | BSD-3-Clause | Cliente HTTP |
| BeautifulSoup4 | MIT | Análisis de HTML |
| lxml | BSD-3-Clause | Análisis de XML/HTML |
| feedparser | BSD-2-Clause | Análisis de RSS/Atom |
| trafilatura | Apache-2.0 | Extracción de artículos |
| Pydantic | MIT | Validación de datos |
| PyYAML | MIT | Lectura de la configuración |
| Bleach | Apache-2.0 | Saneamiento de HTML |
| bcrypt | Apache-2.0 | Primitiva de hash de contraseñas |
| defusedxml | PSF-2.0 | Endurecimiento frente a XML no fiable (volcados de Wikipedia) |
| cryptography | Apache-2.0 OR BSD-3-Clause | Firmas Ed25519 + árboles de Merkle |
| Pillow | HPND (MIT-CMU) | EXIF / metadatos de imágenes |
| python-dateutil | Apache-2.0 / BSD | Análisis de fechas |
| tenacity | Apache-2.0 | Reintentos / espera |
| cachetools | MIT | Caché en memoria |
| orjson | Apache-2.0 OR MIT (con un componente MPL-2.0) | JSON rápido |
| psutil | BSD-3-Clause | Constantes vitales del hardware |

**Extras opcionales (se instalan bajo demanda):**

| Extra | Paquetes | Licencia | Función |
|---|---|---|---|
| `analysis` | numpy, pandas, scipy, scikit-learn, statsmodels, networkx | BSD-3-Clause | Estadística / grafos |
| `analysis` | nltk | Apache-2.0 | Segmentación en tokens |
| `analysis` | vaderSentiment | MIT | Sentimiento por léxico (solo inglés) |
| `nlp` | spaCy | MIT | Cadena de procesamiento de PLN |
| `crypto` | python-gnupg | LGPL-3.0 | Integración con GPG |
| `pqc` | pqcrypto | MIT | Firmas poscuánticas (ML-DSA) |
| `timestamping` | opentimestamps | LGPL-3.0 | Sellos de tiempo anclados en Bitcoin |
| `compression` | zstandard, lz4 | BSD | Compresión de copias de seguridad |

El LLM local es el binario **externo de Ollama** (MIT), al que se accede por HTTP en loopback;
no se incluyen ni distribuyen pesos de modelos ni bibliotecas de inferencia.

#### Notas de cumplimiento

- Cada dependencia es una **obra independiente** bajo su propia licencia; la GPLv3 de Open
  Omniscience no se extiende a ella, y su licencia no restringe
  Open Omniscience.
- Todas las licencias enumeradas son **permisivas o de copyleft débil y compatibles con la GPLv3**
  (los extras LGPL-3.0 `python-gnupg`/`opentimestamps`, y el componente MPL-2.0
  de `orjson`, son todos compatibles con la GPL-3.0). FOSS + compatibilidad con la GPLv3 es un
  requisito de inclusión estricto.
- Los usuarios deben cumplir la licencia individual de cada dependencia; `pip show <pkg>`
  la muestra.

---

### 📄 Fuentes tipográficas e iconos

| Recurso | Licencia | Origen |
|----------|---------|--------|
| Icono del proyecto | MIT (original) | Incluido en el proyecto |
| Fuentes incluidas: Inter, Outfit, Manrope, JetBrains Mono, Source Serif 4, Cantarell | SIL Open Font License 1.1 | `src/static/fonts/` (cada una con su `OFL-*.txt`) |

### 📦 Datos y recursos incluidos

Estos recursos que no son código se incluyen en el repositorio bajo sus propias licencias.
Están registrados en `configs/external_artifacts.yml` (donde se sigue su actualidad y atribución).

| Recurso | Licencia | Atribución / notas |
|-------|---------|---------------------|
| Fuentes tipográficas (Inter · Outfit · Manrope · JetBrains Mono · Source Serif 4 · Cantarell) | SIL OFL 1.1 | `src/static/fonts/*.woff2`, texto de la licencia en `src/static/fonts/OFL-*.txt` |
| Alpine.js v3.14.1 (galería de GUI) | MIT | Incluido localmente, fijado por sha256, sin CDN: `src/static/guis/vendor/alpine.min.js` |
| vaderSentiment 3.3.2: tres métodos del analizador adaptados para tiempo lineal | MIT | **Copyright (c) 2016 C.J. Hutto**; el aviso se reproduce en `src/analytics/vader_linear.py`, que solo se ejecuta sobre el archivo exacto con el que se comprobó (fijado por sha256) |
| DB-IP IP-to-Country Lite (geolocalización sin conexión) | CC BY 4.0 | **Atribución obligatoria:** "IP geolocation by DB-IP (https://db-ip.com) — CC BY 4.0" — `src/geo/data/dbip_country_lite.csv.gz` |
| stopwords-iso (listas multilingües de palabras vacías) | MIT | `configs/stopwords_iso/*.txt` |
| Natural Earth (línea de costa + polígonos de países) | Dominio público | `src/static/world_outline.json`, `src/static/world_countries.json` |

---

### 📝 Fuentes de datos

Open Omniscience agrega datos de diversas fuentes de noticias. Los usuarios son responsables de:

1. Respetar los **derechos de autor** del contenido recopilado
2. Cumplir las **condiciones de servicio** de cada sitio web
3. Seguir las directivas de **robots.txt**
4. Observar las directrices de **recopilación ética** (consulte [ETHICS.md](ETHICS.md))

**Nota:** La licencia GPLv3 de Open Omniscience **no** se aplica a los datos recopilados con el software. Los usuarios son los únicos responsables de garantizar que el uso que hacen de los datos recopilados cumple todas las leyes y normativas aplicables.

---

### 🔍 Verificación

Para verificar el cumplimiento de las licencias de terceros:

1. **Dependencias de Python**: Ejecute `pip list` para ver todos los paquetes instalados y sus licencias
2. **Código fuente**: Todo el código fuente de Open Omniscience está disponible en este repositorio

---

### 📞 Contacto

Para preguntas sobre licencias de terceros o sobre el cumplimiento:
- **Correo electrónico:** open-omniscience@ideotion.com
- **GitHub:** https://github.com/ideotion/Open-Omniscience

---

**Última actualización:** 2026-06-14
