<!-- pt: Translation of docs/CONTRIBUTING.md written by AI (2026-11-19, R677; native review dropped by R721, 2026-11-14); it may contain mistakes, and the English original is authoritative. Coverage: the whole document, 15 of 15 headings. Corrections are welcome as a pull request. -->

# Como contribuir

Obrigado por ajudar. O princípio orientador é a **honestidade**: uma funcionalidade deve fazer o
que afirma, ou não é publicada. Nada de resultados fabricados, nada de pontuações de confiança
falsas, nada de degradação silenciosa — veja [DESIGN.md](DESIGN.md) §3.

## Configuração

```bash
python3.13 -m venv .venv && . .venv/bin/activate
pip install -e ".[analysis,dev]"
pytest -q          # full suite, a few minutes
```

`pyproject.toml` continua sendo a única fonte de verdade para as dependências (instalamos a
versão mais recente dentro dos limites mínimos para que a CI detecte cedo quebras vindas de
upstream). Para uma **instalação reprodutível / de release** existe um lock fixado por hash,
derivado dele:

```bash
pip install -r requirements.lock          # exact, hash-verified core + analysis pins
# regenerate after a dependency change:
pip-compile --generate-hashes --extra analysis -o requirements.lock pyproject.toml
```

**Isto está integrado ao `./install.sh`, não é apenas um comando a executar manualmente.** O
caminho de instalação online (`pip_install()`) usa `requirements.lock` automaticamente sempre que
ele está presente, foi gerado para o Python que você está executando e cobre todos os componentes
solicitados (`OO_COMPONENTS`) — verificado contra o próprio cabeçalho `pip-compile ... --extra=...`
do lock, nunca mantido à mão. Quando alguma dessas condições não se cumpre (o lock está
desatualizado para o seu Python, pede um componente com o qual o lock não foi gerado, ou uma
fixação não se resolve nesta plataforma), ele recorre à resolução comum baseada nos limites
mínimos `pip install -e ".[...]"`, com uma mensagem bem visível explicando por que o caminho
auditado não foi usado — `OO_USE_LOCK=0` desativa o lock incondicionalmente. **Tal como
distribuído, o lock cobre apenas `--extra analysis`**, enquanto o conjunto de componentes padrão
do próprio `install.sh` é `analysis,compression,columnar` — portanto uma execução padrão e não
assistida de `./install.sh` recorre hoje à resolução baseada nos limites mínimos
(compression/columnar não estão na cobertura do lock). Execute
`OO_COMPONENTS=analysis ./install.sh` para usar o caminho auditado tal como está, ou amplie a
cobertura do lock com `pip-compile --extra analysis --extra compression --extra
columnar ...` para que o caminho de instalação padrão também passe a usar o lock.

O **pacote offline/isolado da rede** (`scripts/build_offline_bundle.sh`, consumido pelo caminho
offline `--no-index` do `install.sh` para o alvo Qubes/Tails) **ainda não está ligado ao lock** —
ele continua a resolver do zero a partir dos limites mínimos do `pyproject.toml` a cada
compilação. É uma lacuna conhecida e em aberto, não um descuido: tornar o pacote offline também
baseado no lock (`pip download --require-hashes -r requirements.lock`, mantendo a resolução
baseada em `$SPEC` como alternativa para os extras que o lock não cobre) está registrado como
trabalho futuro.

## Fluxo de trabalho

- **Python 3.13**, um único `pyproject.toml` (sem requirements.txt).
- Lint/formatação com **ruff**; verificação de tipos com **mypy**: `make lint && make typecheck`.
- Toda alteração termina verde: `make check` (ruff + pytest). Adicione um teste de comportamento
  para cada comportamento novo; corrija ou coloque em quarentena — não deixe código que funciona
  pela metade no caminho de importação.
- Faça commits em incrementos pequenos e honestos, com mensagens que digam *o quê e por quê*.
- Alterações de esquema passam pelo Alembic (`alembic revision --autogenerate`); a CI executa
  `alembic check` para detectar divergências entre modelo e migração.

## O registro de entregas: um arquivo por linha

Não acrescente linhas a `docs/ledger/shipped.csv`. A verificação de merge do GitHub ignora a regra
`merge=union` do arquivo, então uma linha acrescentada por cada PR fazia com que todo PR aberto
entrasse em conflito após cada merge. Em vez disso, adicione UM arquivo novo:

    python scripts/ledger_shipped.py new --date 2026-09-30 --area tests --item "..." \
        --status "shipped (draft)" --refs "PR #1240" --key-paths "src/a.py; tests/b.py" --summary "..."

Ele grava `docs/ledger/shipped.d/<date>-<slug>.csv` (o cabeçalho do registro mais uma linha).
Nenhum outro PR pode entrar em conflito com um arquivo que não toca.
`python scripts/ledger_shipped.py check` verifica cada fragmento; as notas de release e os testes
de invariantes do repositório leem primeiro `shipped.csv` e depois os fragmentos.
`ledger_shipped.py fold` acrescenta os fragmentos a `shipped.csv` em modo binário e os apaga; é
para o mantenedor ou para uma release, nunca para um PR de funcionalidade. `refs` deve ser o
número real do PR, não `PR pending` (um teste falha nesse caso).

## Lições e entradas do registro de entregas: um arquivo cada

A mesma convenção vale para os dois grandes arquivos históricos. Uma lição é UM arquivo,
`docs/ledger/lessons.d/<date>-<slug>.md` (`python scripts/lessons.py --new SLUG`); uma entrada
literal do registro de entregas é UM arquivo, `docs/ledger/shipped_log.d/<date>-<slug>.md`
(`python scripts/ledger_fold.py new-log SLUG`). Nunca acrescente a `LESSONS.md` ou
`SHIPPED_LOG.md` e nunca edite `_LESSONS_LINE_CEILING`: cada PR que fazia isso entrava em conflito
com todos os outros. Um fragmento começa com `## <date> — title`, termina com uma quebra de linha e
está em UTF-8 com finais de linha LF; uma lição (não uma entrada do registro de entregas) não tem
segundo título e fica abaixo de 200 linhas (isso limita o tamanho de uma entrada);
`python scripts/ledger_fold.py check` (e `tests/test_ledger_fragments.py`) a valida, recusa os
marcadores `#NNNN` e `PR pending`, e `lessons.py <words>` também pesquisa os fragmentos.
`ledger_fold.py fold` os incorpora aos arquivos históricos numa release e nunca é para um PR de
funcionalidade.

## Arquivos de localização e conflitos de merge

Os 12 arquivos `src/static/locales/*.json` são mantidos **ordenados** (`_meta` primeiro, depois as chaves em ordem de ponto de código), de modo que dois PRs que adicionam strings as inserem em lugares diferentes e fazem merge sem conflito. Depois de adicionar strings, execute `python scripts/locales_merge.py`; ele ordena os arquivos e os verifica (`--check` apenas verifica; `tests/test_locales_merge.py` falha com chaves fora de ordem ou duplicadas).

Se `git merge origin/main` deixar marcadores de conflito nos arquivos de localização, execute o mesmo script: ele mantém os dois lados de cada trecho, ordena e para, indicando a chave, se os dois lados deram textos diferentes para a mesma chave (uma contradição real a decidir). `docs/ledger/shipped.csv` é `merge=union` em `.gitattributes`, o que um `git merge` local respeita, mas o merge pela web do GitHub e o botão de atualizar o branch não: faça o merge de main localmente e depois verifique se há linhas `(date, area, item)` duplicadas.

## Padrões

- Proveniência em todo lugar: os dados armazenados levam fonte + carimbo de data/hora + hash.
- Qualquer número mostrado a um usuário deve vir de um método real com incerteza declarada
  (`src/analysis`), nunca de uma constante.
- A ingestão passa pelo único fetcher ético (robots com falha fechada, com limite de taxa).
- Código fabricado/morto pertence a `quarantine/` (documentado), não a `src/`.

## Código de conduta

Ao participar, você concorda em respeitar o [Código de Conduta](CODE_OF_CONDUCT.md)
(Contributor Covenant 2.1). Relate preocupações em privado a open-omniscience@ideotion.com.

## Licença

As contribuições estão sob **GPL-3.0-or-later** (veja [LICENSE](../LICENSE)).

---

# Política de versionamento

Como o projeto é versionado — com a maturidade deliberadamente subestimada.

**Nesta parte:**
- [Política de versionamento](#política-de-versionamento)


---

## Política de versionamento

> **Subestimamos deliberadamente a maturidade. Honestidade acima do hype.** É melhor um usuário
> ser agradavelmente surpreendido do que enganado. O número de versão é uma promessa sobre a
> *maturidade*, e mantemos essa promessa conservadora.

### A única fonte de verdade

A versão fica em **um só lugar: `pyproject.toml` (`[project] version`)**. Todo o resto deriva
dela:

- O aplicativo em execução a lê dos metadados do pacote instalado
  (`importlib.metadata.version("open-omniscience")`) — assim `/api/health`, o `version=` da API e
  a interface informam automaticamente a versão *real* instalada.
- Nenhum outro código fixa um literal de versão. Os testes verificam contra os metadados do
  pacote, não contra uma string (veja `tests/test_api_search.py`).
- O `README.md` na raiz do repositório declara a versão uma vez, no seu cabeçalho, e uma
  verificação de CI garante que ela corresponde ao pacote
  (`tests/test_repo_invariants.py::test_readme_version_matches_package`).

**Para mudar a versão, altere apenas `pyproject.toml`**, atualize o cabeçalho do README para
corresponder (a verificação impõe isso) e depois execute `pip install -e .` para que os metadados
sejam atualizados.

**Crie a tag `vX.Y.Z` apenas num commit cujo `pyproject.toml` já indique `X.Y.Z`.** O workflow de
release (`.github/workflows/release.yml`) recusa qualquer outra tag antes de compilar qualquer
coisa, de modo que uma tag criada antes da mudança de versão publica uma release sem wheel, sdist
nem checksums. O primeiro `v0.4.0` foi criado dessa forma em 2026-09-28; a versão foi definida
depois e a tag foi movida para ela (`docs/product/RELEASE_0.4_GATE.md` linha G). **Mover uma tag
exige git:** o site do GitHub não consegue nem apagar nem mover uma tag, e uma release publicada lá
reutiliza a tag existente sem iniciar o workflow. Sem um clone local com permissão de push, abra
um Codespace em `main` e execute
`git fetch origin && git tag -f vX.Y.Z origin/main && git push -f origin vX.Y.Z`. Apague antes a
release do GitHub se o workflow tiver de escrever as notas geradas: ele mantém as notas de uma
release existente e só acrescenta os arquivos e os checksums.

### A escada de maturidade (onde estamos, para onde vamos)

O software é jovem e ainda está sendo posto à prova, por isso permanece **abaixo de `1.0`**:

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

**Não** vamos saltar para um número de versão que implique mais maturidade do que a que existe
(por exemplo, `0.2` não significa "20% pronto" nem "quase beta" — é a contagem honesta dos ciclos
alfa até agora). Cada ciclo é uma iteração pequena e real — nada mais é afirmado.

### Correspondência entre ciclo e versão

Os ciclos de desenvolvimento (e os seus branches) recebem o nome da versão que produzem, com os
zeros à esquerda omitidos por brevidade:

| Nome do branch / ciclo | Versão do pacote |
|---|---|
| `0.04` | `0.0.4` |
| `0.05` | `0.0.5` |
| `0.06` | `0.0.6` |
| `0.07` | `0.0.7` |
| `0.08` | `0.0.8` |
| `0.09` | `0.0.9` |
| `0.1`  | `0.1.0` |  (o branch do ciclo `0.09` foi renomeado `0.09 → 0.1` na passagem para alfa)
| `0.2`  | `0.2.0` |  (o branch do ciclo `0.1` foi renomeado `0.1 → 0.2` na passagem para 0.2)
| `main` | `0.2.0` → `0.3.0` → `0.4.0` → `0.5.0` |  (o branch do ciclo `0.2` foi renomeado `0.2 → main` em 2026-07-15 — o branch padrão agora é permanentemente `main`, e o nome do branch e a versão são independentes; `v0.2.0` recebeu a tag após a validação em escala com corpus real, `v0.3.0` encerrou o ciclo medido e verificado, `v0.4.0` encerrou o ciclo das fontes vivas, e `main` agora indica `0.5.0`, a release da mesa do investigador, com a tag `v0.5.0`)

Assim, "a camada de inteligência `0.06`" significa "o trabalho que é entregue em `0.0.6`". Quando
ler uma abreviação de ciclo como `0.05` na documentação, leia-a como `0.0.5`. Os PRs vão para
`main`, o branch do ciclo atual — não para nenhum dos nomes de branch numerados aposentados acima.

**Desde a primeira alfa (`0.1.0`), a correspondência é ciclo `0.N` ⇒ `v0.N.0`** — o ciclo `0.2`
foi encerrado com `v0.2.0`, o ciclo `0.3` com `v0.3.0`, o ciclo `0.4` com `v0.4.0`, o ciclo `0.5`
com `v0.5.0` (a única exceção é o ciclo consolidado `0.09`, que produziu `0.1.0`). Um ciclo recebe
o nome da release que o encerra — os arquivos de critérios de release dizem isso com as suas
próprias palavras (`RELEASE_0.4_GATE.md` é "o inventário verificável para encerrar o ciclo
`0.4`") — e um número de versão pode ser *definido* a meio do ciclo, antes da tag (por exemplo,
`0.4.0` foi definido em 2026-09-28, para que a tag fosse movida para ele; `0.5.0` foi definido no
PR de mudança de versão, e a tag aponta para o seu commit de merge), e é por isso que a data de um
título do changelog e a data da sua tag podem diferir.

### Por que isto importa (a ligação com os valores)

Este projeto existe para ajudar as pessoas a ver a informação com honestidade. Uma ferramenta que
exagerasse a sua própria maturidade contradiria isso pela raiz. O versionamento conservador é a
mesma disciplina do resto da base de código: **afirmar apenas o que é real, e prová-lo.**
