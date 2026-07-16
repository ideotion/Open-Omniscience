# Política de Privacidad (RGPD)

> **Traducción automática (borrador) — pendiente de revisión nativa. La versión
> francesa ([`../POLITIQUE_DE_CONFIDENTIALITE.md`](../POLITIQUE_DE_CONFIDENTIALITE.md))
> es el texto jurídicamente auténtico.**

> ⚠️ **Aviso importante — documento redactado sin validación jurídica profesional, de
> forma permanente.** Este documento es un **documento de trabajo** redactado a título
> informativo por el propio Editor. **No constituye un asesoramiento ni una consulta
> jurídica.** **Open Omniscience es un proyecto libre, gratuito y sin fines
> comerciales, realizado sin presupuesto**: este documento **no será revisado ni
> validado por un profesional del derecho** — se trata de una decisión asumida, y no
> de una etapa simplemente aplazada. Las menciones entre corchetes
> **[À COMPLÉTER: …]** y **[À VÉRIFIER: …]** señalan información dejada
> voluntariamente sin completar, o no verificada de forma independiente por un
> profesional.

**Versión:** 1.0
**Fecha de entrada en vigor:** 2026-07-16
**Contacto:** open-omniscience@ideotion.com

---

## 1. Principio rector: ausencia de tratamiento por el Editor

**Open Omniscience** («el Software») es un **software libre «local-first»**. **El Editor
(Ideotion) no recoge, no aloja y no trata ningún dato personal** de los Usuarios y **no
explota ningún servidor**. **No hay cuenta, ni registro, ni servicio en línea, ni
telemetría.** El **100 % de los tratamientos** realizados mediante el Software se
ejecuta **localmente, en la máquina del Usuario**.

En consecuencia:

- el Editor **no es ni responsable del tratamiento ni encargado** de los datos tratados
  por el Usuario mediante el Software;
- el Editor **no tiene acceso** a ninguno de los datos del Usuario;
- la presente política tiene un valor **informativo**: explica el funcionamiento del
  Software y **las obligaciones que recaen en el Usuario** cuando trata datos
  personales.

## 2. Ausencia de telemetría y de recogida (verificable)

El diseño del Software garantiza, **por construcción**:

- **ninguna telemetría**, ningún rastreador, ningún identificador de uso;
- un **arranque sin ninguna llamada de red**; un **interruptor de red («modo avión»)**
  en la interfaz corta todo el tráfico saliente;
- las **únicas** conexiones de red son las que **el Usuario desencadena** para recopilar
  fuentes (mediante el componente de obtención «ética») y, en su caso, el uso **local**
  de un modelo de IA (Ollama) que **no sale de la máquina**;
- al ser el código **libre (GPL v3)**, este comportamiento es **auditable por
  cualquiera**.

> *Nota de coherencia:* estas afirmaciones reflejan el estado documentado del Software
> (véanse el `README`, [`../../SECURITY.md`](../../SECURITY.md) y
> [`../../ETHICS.md`](../../ETHICS.md)). Cualquier evolución futura que introdujera una
> transmisión de datos, de la índole que fuere, debería documentarse aquí **antes** de su
> puesta en servicio. **Punto de vigilancia permanente (a reverificar en cada versión,
> antes de cualquier actualización del campo «Versión» indicado más arriba): reconfirmar
> la ausencia de telemetría en el código efectivamente publicado.**

## 3. Datos técnicos tratados localmente por el Software

El Software almacena, **únicamente en la máquina del Usuario**, los datos necesarios
para su funcionamiento: el corpus recopilado, los metadatos de procedencia, el índice de
búsqueda, los ajustes, los registros locales, las claves de firma y el **registro local
de consentimiento** (versión aceptada + fecha y hora ISO 8601). Estos datos **permanecen
bajo el control exclusivo del Usuario** y nunca se transmiten al Editor.

## 4. El Usuario, único responsable del tratamiento

Cuando los contenidos que el Usuario recopila, importa o analiza **contienen datos
personales** (por ejemplo nombres, declaraciones atribuidas, imágenes, identificadores),
el Usuario actúa como **responsable del tratamiento** en el sentido del **Règlement (UE)
2016/679 (RGPD)** y de la **loi n° 78-17 du 6 janvier 1978 relative à l'informatique,
aux fichiers et aux libertés («Loi Informatique et Libertés»)**, modificada.

Como tal, **corresponde al Usuario** cumplir en particular las obligaciones siguientes:

### 4.1. Base jurídica y minimización

- determinar una **base jurídica** apropiada (por ejemplo el **interés legítimo**,
  respetando la **ponderación** frente a los derechos de los interesados);
- aplicar los principios de **minimización**, **limitación de la finalidad** y
  **limitación de la conservación**.

### 4.2. Datos de categorías especiales

- ejercer una **vigilancia reforzada** respecto de las **categorías especiales de
  datos** (presunto origen racial o étnico, opiniones políticas, convicciones, salud,
  orientación sexual, datos biométricos o genéticos, etc.) contempladas en el
  **article 9 du RGPD**, cuyo tratamiento está **en principio prohibido** salvo
  excepción aplicable.

### 4.3. Transparencia y derechos de los interesados

- garantizar, en la medida exigida, la **transparencia** hacia los interesados;
- permitir el ejercicio de sus **derechos**: **acceso, rectificación, supresión
  («derecho al olvido»), limitación, oposición y portabilidad**.

### 4.4. Solicitudes de supresión

Cualquier solicitud de supresión o de rectificación relativa a contenidos recopilados
por el Usuario es **responsabilidad del Usuario** (que posee y controla los datos
localmente). **El Editor no puede tramitar ninguna solicitud de este tipo**, al no tener
acceso a los datos. Para facilitar esta obligación, el Software permite al Usuario
**buscar y suprimir** contenidos de su corpus local.

### 4.5. Exención «periodística»

Cuando el tratamiento se realice con **fines periodísticos** o de **expresión e
información**, el Usuario podrá, en determinadas condiciones, acogerse a las
**adaptaciones** previstas en el **article 85 du RGPD** y en las disposiciones
correspondientes de la **Loi Informatique et Libertés**. Esta exención **no exime** del
cumplimiento de los principios esenciales y **debe evaluarse caso por caso**; corresponde
a la **apreciación y a la responsabilidad del Usuario**. La transposición nacional figura
en el **artículo 80 de la loi n° 78-17 du 6 janvier 1978** (en su redacción dada por la
ordonnance del 12 de diciembre de 2018), que excluye, con carácter derogatorio y en la
medida necesaria para conciliar la protección de datos con la libertad de expresión e
información, la aplicación de determinadas disposiciones del RGPD a los tratamientos
realizados, en particular, a efectos del ejercicio, con carácter profesional, de la
actividad de periodista.

## 5. Resultados producidos por IA y datos personales

Los resultados producidos o asistidos por IA (resúmenes, traducciones, extracción de
entidades, análisis de sentimiento, etc.) pueden **mencionar o inferir** información
relativa a personas. Son **probabilísticos y falibles** (véase el **artículo 7 de las
[Condiciones de Uso](CGU.md)**) y **no constituyen ni una constatación ni una
acusación**. Su producción, su conservación y, sobre todo, su **eventual difusión**
recaen en la **responsabilidad del Usuario** como responsable del tratamiento y autor
editorial.

## 6. Seguridad

El Software ofrece medidas de seguridad **locales** (por ejemplo el **cifrado en
reposo** mediante SQLCipher, la ejecución limitada a la interfaz de bucle local). La
**implementación y la solidez** de estas medidas, así como la **seguridad física y
lógica** de la máquina, recaen en el Usuario. El cifrado en reposo protege un archivo
**incautado o copiado**, **no** una sesión en ejecución comprometida, y **no ofrece
ninguna recuperación** de la frase de contraseña.

## 7. Autoridad de control

En Francia, la autoridad de control competente es la **Commission nationale de
l'informatique et des libertés (CNIL)**. El Usuario, en su condición de responsable del
tratamiento, es el **punto de contacto** de la autoridad de control para los tratamientos
que lleva a cabo.

## 8. Contacto

Al tener la presente política un valor **informativo** (sin que el Editor trate dato
alguno), ninguna solicitud de ejercicio de derechos puede ser satisfecha por el Editor.
Para cualquier **consulta relativa a este documento**: **open-omniscience@ideotion.com**.

---

*Documentos relacionados: [Condiciones de Uso](CGU.md) · [Aviso Legal](MENTIONS_LEGALES.md) · [Carta de Uso Aceptable](CHARTE_USAGE.md) · [Índice](README.md). Véanse también [`../../SECURITY.md`](../../SECURITY.md) y [`../../ETHICS.md`](../../ETHICS.md).*
