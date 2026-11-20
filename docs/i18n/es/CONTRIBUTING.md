<!-- es: Translation of docs/CONTRIBUTING.md written by AI (2026-11-19, R677; native review dropped by R721, 2026-11-14); it may contain mistakes, and the English original is authoritative. Coverage: the whole document, 15 of 15 headings. Corrections are welcome as a pull request. -->

# Contribuir

Gracias por ayudar. El principio rector es la **honestidad**: una funcionalidad debe hacer lo que
afirma, o no se publica. Nada de resultados fabricados, nada de puntuaciones de confianza falsas,
nada de degradación silenciosa — véase [DESIGN.md](DESIGN.md) §3.

## Instalación

```bash
python3.13 -m venv .venv && . .venv/bin/activate
pip install -e ".[analysis,dev]"
pytest -q          # full suite, a few minutes
```

`pyproject.toml` sigue siendo la única fuente de verdad para las dependencias (instalamos la
versión más reciente por encima de los mínimos para que la CI detecte pronto las roturas de los
proyectos de origen). Para una **instalación reproducible / de publicación** existe un archivo de
bloqueo fijado por hash, derivado de él:

```bash
pip install -r requirements.lock          # exact, hash-verified core + analysis pins
# regenerate after a dependency change:
pip-compile --generate-hashes --extra analysis -o requirements.lock pyproject.toml
```

**Esto está integrado en `./install.sh`, no es solo un comando que se ejecuta a mano.** La ruta de
instalación en línea (`pip_install()`) usa `requirements.lock` automáticamente siempre que esté
presente, se haya generado para el Python que está ejecutando y cubra cada componente solicitado
(`OO_COMPONENTS`) — comprobado frente a la propia cabecera `pip-compile ... --extra=...` del
archivo de bloqueo, nunca mantenido a mano. Cuando alguna de esas condiciones no se cumple (el
archivo de bloqueo está desfasado para su Python, pide un componente con el que no se generó, o
una fijación no se resuelve en esta plataforma), recurre a la resolución ordinaria basada en
mínimos, `pip install -e ".[...]"`, con un mensaje claro que explica por qué no se usó la ruta
auditada — `OO_USE_LOCK=0` desactiva el archivo de bloqueo incondicionalmente. **Tal como se
publica, el archivo de bloqueo solo cubre `--extra analysis`**, mientras que el conjunto de
componentes por defecto de `install.sh` es `analysis,compression,columnar` — así que una ejecución
por defecto y desatendida de `./install.sh` recurre hoy a la resolución basada en mínimos
(compression/columnar no están cubiertos por el archivo de bloqueo). Ejecute
`OO_COMPONENTS=analysis ./install.sh` para usar la ruta auditada en su estado actual, o amplíe la
cobertura del archivo de bloqueo con `pip-compile --extra analysis --extra compression --extra
columnar ...` para que la ruta de instalación por defecto también se base en el bloqueo.

El **paquete sin conexión / aislado de la red** (`scripts/build_offline_bundle.sh`, usado por la
ruta sin conexión `--no-index` de `install.sh` para el destino Qubes/Tails) **todavía no está
conectado al archivo de bloqueo** — sigue resolviendo de nuevo a partir de los mínimos de
`pyproject.toml` cada vez que se construye. Es una carencia conocida y abierta, no un descuido:
hacer que el paquete sin conexión también se base en el bloqueo
(`pip download --require-hashes -r requirements.lock`, manteniendo la resolución basada en `$SPEC`
como alternativa para los extras que el archivo de bloqueo no cubra) figura como trabajo
pendiente.

## Flujo de trabajo

- **Python 3.13**, un único `pyproject.toml` (sin requirements.txt).
- Lint/formato con **ruff**; comprobación de tipos con **mypy**: `make lint && make typecheck`.
- Todo cambio termina en verde: `make check` (ruff + pytest). Añada una prueba de comportamiento
  para el comportamiento nuevo; corrija o ponga en cuarentena — no deje código a medio funcionar
  en la ruta de importación.
- Haga commits en incrementos pequeños y honestos, con mensajes que digan *qué y por qué*.
- Los cambios de esquema pasan por Alembic (`alembic revision --autogenerate`); la CI ejecuta
  `alembic check` para detectar desajustes entre modelo y migración.

## El registro de entregas: un archivo por fila

No añada nada al final de `docs/ledger/shipped.csv`. La comprobación de fusión de GitHub ignora la
regla `merge=union` del archivo, de modo que una fila añadida por cada PR ponía en conflicto todas
las PR abiertas después de cada fusión. En su lugar, añada UN archivo nuevo:

    python scripts/ledger_shipped.py new --date 2026-09-30 --area tests --item "..." \
        --status "shipped (draft)" --refs "PR #1240" --key-paths "src/a.py; tests/b.py" --summary "..."

Esto escribe `docs/ledger/shipped.d/<date>-<slug>.csv` (la cabecera del registro más una fila).
Ninguna otra PR puede entrar en conflicto con un archivo que no toca.
`python scripts/ledger_shipped.py check` verifica cada fragmento; las notas de versión y las
pruebas de invariantes del repositorio leen primero `shipped.csv` y después los fragmentos.
`ledger_shipped.py fold` añade los fragmentos a `shipped.csv` en binario y los elimina; es para el
mantenedor o para una publicación, nunca para una PR de funcionalidad. `refs` debe ser el número de
PR real, no `PR pending` (una prueba falla si no).

## Lecciones y entradas del registro de entregas: un archivo cada una

La misma convención cubre los dos grandes archivos históricos. Una lección es UN archivo,
`docs/ledger/lessons.d/<date>-<slug>.md` (`python scripts/lessons.py --new SLUG`); una entrada
literal del registro de entregas es UN archivo, `docs/ledger/shipped_log.d/<date>-<slug>.md`
(`python scripts/ledger_fold.py new-log SLUG`). Nunca añada nada a `LESSONS.md` ni a
`SHIPPED_LOG.md` y nunca edite `_LESSONS_LINE_CEILING`: cada PR que lo hacía entraba en conflicto
con todas las demás. Un fragmento empieza por `## <date> — title`, termina con un salto de línea y
está en UTF-8 con finales de línea LF; una lección (no una entrada del registro de entregas) no
tiene un segundo encabezado y se mantiene por debajo de 200 líneas (eso acota el tamaño de una
entrada); `python scripts/ledger_fold.py check` (y `tests/test_ledger_fragments.py`) la valida,
rechaza los marcadores provisionales `#NNNN` y `PR pending`, y `lessons.py <words>` también busca
en los fragmentos. `ledger_fold.py fold` los fusiona en los archivos históricos en una publicación
y nunca es para una PR de funcionalidad.

## Archivos de idioma y conflictos de fusión

Los 12 archivos `src/static/locales/*.json` se mantienen **ordenados** (`_meta` primero, luego las
claves por orden de punto de código), de modo que dos PR que añaden cadenas las insertan en lugares
distintos y se fusionan limpiamente. Después de añadir cadenas, ejecute
`python scripts/locales_merge.py`; ordena los archivos y los comprueba (`--check` solo verifica;
`tests/test_locales_merge.py` falla con claves desordenadas o duplicadas).

Si `git merge origin/main` deja marcadores de conflicto en los archivos de idioma, ejecute el mismo
script: conserva ambos lados de cada bloque, ordena y se detiene indicando la clave si ambos lados
dieron a una misma clave textos distintos (una contradicción real que decidir).
`docs/ledger/shipped.csv` está en `merge=union` en `.gitattributes`, algo que respeta un
`git merge` local pero no la fusión web de GitHub ni el botón de actualizar la rama: fusione main
localmente y luego compruebe que no haya filas `(date, area, item)` duplicadas.

## Normas

- Procedencia en todas partes: los datos almacenados llevan fuente + marca de tiempo + hash.
- Cualquier número mostrado a un usuario debe provenir de un método real con una incertidumbre
  declarada (`src/analysis`), nunca de una constante.
- La ingesta pasa por el único descargador ético (robots con fallo cerrado, frecuencia limitada).
- El código fabricado o muerto va en `quarantine/` (documentado), no en `src/`.

## Código de conducta

Al participar, acepta respetar el [Código de conducta](CODE_OF_CONDUCT.md)
(Contributor Covenant 2.1). Comunique sus inquietudes en privado a open-omniscience@ideotion.com.

## Licencia

Las contribuciones están bajo **GPL-3.0-or-later** (véase [LICENSE](../LICENSE)).

---

# Política de versiones

Cómo se versiona el proyecto — con una madurez deliberadamente subestimada.

**En esta parte:**
- [Política de versiones](#política-de-versiones)


---

## Política de versiones

> **Subestimamos la madurez deliberadamente. Honestidad antes que bombo.** Es mejor que un usuario
> se lleve una grata sorpresa que una decepción por haber sido engañado. El número de versión es
> una promesa sobre la *madurez*, y mantenemos esa promesa prudente.

### La única fuente de verdad

La versión está en **un solo lugar: `pyproject.toml` (`[project] version`)**. Todo lo demás se
deriva de ahí:

- La aplicación en ejecución la lee de los metadatos del paquete instalado
  (`importlib.metadata.version("open-omniscience")`) — así `/api/health`, el `version=` de la API
  y la interfaz informan automáticamente de la versión *realmente* instalada.
- Ningún otro código fija una versión literal. Las pruebas comparan con los metadatos del paquete,
  no con una cadena (véase `tests/test_api_search.py`).
- El `README.md` de la raíz del repositorio indica la versión una vez, en su cabecera, y una
  salvaguarda de CI comprueba que coincide con el paquete
  (`tests/test_repo_invariants.py::test_readme_version_matches_package`).

**Para subir la versión, cambie solo `pyproject.toml`**, actualice la cabecera del README para que
coincida (la salvaguarda lo impone) y después ejecute `pip install -e .` para que se actualicen los
metadatos.

**Etiquete `vX.Y.Z` solo en un commit cuyo `pyproject.toml` ya indique `X.Y.Z`.** El flujo de
publicación (`.github/workflows/release.yml`) rechaza cualquier otra etiqueta antes de construir
nada, de modo que una etiqueta creada antes del cambio de versión publica una versión sin wheel,
sdist ni sumas de comprobación. El primer `v0.4.0` se creó así el 2026-09-28; la versión se fijó
después y la etiqueta se movió a ella (`docs/product/RELEASE_0.4_GATE.md` fila G). **Mover una
etiqueta requiere git:** el sitio web de GitHub no puede borrar ni mover una, y una versión
publicada allí reutiliza la etiqueta existente sin iniciar el flujo. Sin un clon local que pueda
hacer push, abra un Codespace en `main` y ejecute
`git fetch origin && git tag -f vX.Y.Z origin/main && git push -f origin vX.Y.Z`. Borre primero la
versión de GitHub si el flujo debe escribir las notas generadas: conserva las notas de una versión
existente y solo añade los archivos y las sumas de comprobación.

### La escala de madurez (dónde estamos, adónde vamos)

El software es joven y aún se está poniendo a prueba, así que se mantiene **por debajo de `1.0`**:

```
0.0.x  pre-alpha    the first, un-public pre-alpha iterations (0.0.4 .. 0.0.9).
0.x    alpha        ← we are here (0.5.0). Public, working, honestly-labelled — open
                     to feedback, but not yet consolidated (each cycle is still an
                     "honest about every limit, not finished" release, per the README
                     header — see it for the current cycle's exact status).
0.x    beta         once things consolidate (a deliberate, later maintainer call —
                     not implied by any particular `0.x` number crossing over from alpha).
1.0    release      an official, stable release.
```

**No** saltaremos a un número de versión que sugiera más madurez de la que existe (p. ej., `0.2`
no significa «20 % terminado» ni «casi beta» — es el recuento honesto de los ciclos alfa hasta
ahora). Cada ciclo es una iteración pequeña y real — no se afirma nada más.

### Correspondencia ciclo ↔ versión

Los ciclos de desarrollo (y sus ramas) llevan el nombre de la versión que producen, omitiendo los
ceros iniciales por brevedad:

| Nombre de rama / ciclo | Versión del paquete |
|---|---|
| `0.04` | `0.0.4` |
| `0.05` | `0.0.5` |
| `0.06` | `0.0.6` |
| `0.07` | `0.0.7` |
| `0.08` | `0.0.8` |
| `0.09` | `0.0.9` |
| `0.1`  | `0.1.0` |  (la rama del ciclo `0.09` se renombró `0.09 → 0.1` en el paso a alfa)
| `0.2`  | `0.2.0` |  (la rama del ciclo `0.1` se renombró `0.1 → 0.2` en el paso a 0.2)
| `main` | `0.2.0` → `0.3.0` → `0.4.0` → `0.5.0` |  (la rama del ciclo `0.2` se renombró `0.2 → main` el 2026-07-15 — la rama por defecto es ahora permanentemente `main`, y el nombre de la rama y la versión son independientes; `v0.2.0` se etiquetó tras la validación a escala con un corpus real, `v0.3.0` cerró el ciclo medido y verificado, `v0.4.0` cerró el ciclo de las fuentes vivas, y `main` indica ahora `0.5.0`, la versión del escritorio del investigador, etiquetada `v0.5.0`)

Así, «la capa de inteligencia `0.06`» significa «el trabajo que se publica en `0.0.6`». Cuando lea
una abreviatura de ciclo como `0.05` en la documentación, léala como `0.0.5`. Las PR llegan a
`main`, la rama del ciclo actual — no a ninguno de los nombres de rama numerados retirados que
aparecen arriba.

**Desde la primera alfa (`0.1.0`), la correspondencia es ciclo `0.N` ⇒ `v0.N.0`** — el ciclo
`0.2` se cerró con `v0.2.0`, el ciclo `0.3` con `v0.3.0`, el ciclo `0.4` con `v0.4.0`, el ciclo
`0.5` con `v0.5.0` (la única excepción es el ciclo consolidado `0.09`, que produjo `0.1.0`). Un
ciclo lleva el nombre de la versión que lo cierra — los archivos de control de publicación lo dicen
con sus propias palabras (`RELEASE_0.4_GATE.md` es «el inventario verificable para cerrar el ciclo
`0.4`») — y un número de versión puede *fijarse* a mitad de ciclo antes de la etiqueta (p. ej.,
`0.4.0` se fijó el 2026-09-28, para que la etiqueta se moviera a él; `0.5.0` se fijó en la PR de
cambio, y la etiqueta nombra su commit de fusión), por lo que la fecha de un encabezado del
registro de cambios y la fecha de su etiqueta pueden diferir.

### Por qué importa (el vínculo con los valores)

Este proyecto existe para ayudar a las personas a ver la información con honestidad. Una
herramienta que exagerara su propia madurez lo contradiría de raíz. Versionar con prudencia es la
misma disciplina que el resto del código: **afirmar solo lo que es real, y demostrarlo.**
