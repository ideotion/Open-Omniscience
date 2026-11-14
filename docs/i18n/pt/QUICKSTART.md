<!-- pt: AI-drafted translation of docs/QUICKSTART.md (2026-11-13, R677), not yet reviewed by a native speaker; the English original is authoritative. Coverage: the whole document, 17 of 17 headings. Improve it with a pull request; corrections by native speakers are welcome. -->

# Início rápido — como executar o aplicativo

Este é o **núcleo confiável** (o aplicativo é um **alfa** honesto — `v0.5.0`, o
ciclo `0.5` da "mesa do investigador", marcado em 2026-10-26; o aplicativo em execução informa sua
versão exata): adicionar uma fonte → coletá-la de forma ética → armazenar com a procedência →
pesquisa booleana no texto completo → exportar. Local em primeiro lugar, somente loopback, sem contas.

---

## 0. O jeito fácil — um comando, depois dois cliques para executar

Se você só quer usar o aplicativo (sem precisar saber linha de comando depois):

**Linux / macOS** — em um terminal:

```bash
curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/HEAD/scripts/bootstrap.sh | bash
```

**Windows 11** — no PowerShell. Baixe o arquivo e *só depois* execute-o:

```powershell
irm https://raw.githubusercontent.com/ideotion/Open-Omniscience/HEAD/install.ps1 -OutFile $env:TEMP\oo-install.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File $env:TEMP\oo-install.ps1
```

O Windows Defender pode colocar o arquivo em quarentena mesmo assim — ele não é assinado e é novo. Isso é um
falso positivo; a [§C](#c-no-windows-11-powershell) explica exatamente por quê e oferece um
caminho sem script que nada consegue bloquear.

O suporte ao Windows é mais limitado que o do Linux, e a diferença está dita com clareza na
[§C](#c-no-windows-11-powershell) — leia antes de confiar nele.

> **Inspecione antes de confiar.** Enviar um script direto para o seu shell executa código na sua
> máquina. Os dois são propositalmente pequenos — leia-os antes, se quiser
> ([scripts/bootstrap.sh](../scripts/bootstrap.sh), [install.ps1](../install.ps1)).
> Eles verificam se há git + Python 3.13, clonam este repositório em `~/open-omniscience`
> (`%USERPROFILE%\Open-Omniscience` no Windows) e passam o controle ao
> instalador do repositório. Você também pode clonar por conta própria e executar `./install.sh` / `install.ps1`.

O `install.sh` **não faz perguntas** — **não há menu de componentes**. Um único comando instala
o conjunto padrão sensato:

| Instalado por padrão | O que você recebe |
|----------------------|--------------|
| **Núcleo (Core)** *(sempre)* | coleta · armazenamento com procedência · pesquisa booleana · exportação |
| **Análise** | palavras-chave · comparação de enquadramento · sentimento |
| **Compressão (Compression)** | armazenamento do corpus em disco mais rápido |

A configuração do LLM local / Ollama **não** faz parte do instalador — ela fica inteiramente na
aba **Configurações → IA** do aplicativo (veja a §E). Substitua o conjunto instalado com a
variável de ambiente `OO_COMPONENTS="…"` (por exemplo, `OO_COMPONENTS="analysis,nlp"`); executar
`./install.sh` de novo é idempotente e só instala o que estiver faltando.

**Em seguida, ele abre sozinho.** O instalador cria um atalho **Open Omniscience** (menu de
aplicativos + Área de Trabalho (Desktop)) e abre o aplicativo no seu navegador. Para iniciá-lo de novo mais tarde:

- abra o menu de aplicativos e procure **Open Omniscience**, **ou**
- clique duas vezes no ícone **Open Omniscience** na sua **Área de Trabalho**.

Uma pequena janela de terminal aparece, o aplicativo inicia e o seu navegador abre em
**http://127.0.0.1:8000**. **Feche essa janela (ou use o botão de desligar
na barra superior) para parar o aplicativo.** (No macOS, o atalho é `Open Omniscience.command` na sua
Área de Trabalho; no Windows, é um atalho na Área de Trabalho + menu Iniciar criado pelo `install.ps1`.)

**Primeira execução.** Numa instalação nova, o aplicativo conduz você por uma configuração curta, feita uma só vez,
*antes* da interface principal: **escolha seu idioma → leia e aceite os termos legais**
(recusar **desinstala** o aplicativo, mediante confirmação digitada) **→ crie a senha
do seu corpus**. O corpus é **criptografado em repouso por padrão** (SQLCipher 4) e **não
há recuperação** para uma senha perdida (perder a senha custa o tempo de coletar de novo — o
corpus é reconstruído a partir da web). Depois, o aplicativo inicia **offline (modo avião)**;
ficar online passa por **um único pop-up de consentimento**, que nomeia a ação e mostra os IPs das suas
interfaces locais antes que qualquer requisição saia.

Prefere o terminal? `cd ~/open-omniscience && ./scripts/launch.sh` faz o mesmo.

**Verificar ou remover mais tarde:**
```bash
./install.sh --check        # health report: Python, data dir, database, LLM, launcher
#   (same as: open-omniscience doctor)
./install.sh --uninstall    # remove the virtualenv + launcher; your data is kept
                            #   (it asks separately, defaulting to NO, before deleting data)
```

---

## A. Numa AppVM Debian do Qubes OS (o alvo)

O Qubes redefine o sistema de arquivos raiz de uma AppVM a cada inicialização; só `/home` (e
`/usr/local`, `/rw`) persistem. Por isso, os pacotes do sistema vão na **TemplateVM**, e o
aplicativo + o virtualenv + o banco de dados ficam em `/home` na **AppVM**.

**1. Na TemplateVM (uma vez):**
```bash
sudo ./install.sh --template      # installs python3.13, venv, git, sqlite3, ...
```
Desligue a TemplateVM e depois **reinicie a AppVM** para que os pacotes fiquem visíveis.

**2. Na AppVM (como seu usuário, sem sudo):**
```bash
./install.sh                      # promptless: Core + Analysis + Compression, then auto-launches
# Qubes AppVM (unattended, creates the launcher, no prompts): Core + Analysis + Compression
./install.sh --appvm
```

**3. Execute-o (escuta apenas em 127.0.0.1):**
Clique duas vezes no atalho **Open Omniscience** (menu de aplicativos / Área de Trabalho) ou:
```bash
cd ~/open-omniscience && ./scripts/launch.sh    # starts the app + opens the browser
```
Abra **http://127.0.0.1:8000** no navegador da AppVM.

O servidor nunca escuta fora do loopback. Para ficar totalmente offline depois de uma execução, desconecte a
NetVM da AppVM — a interface não tem dependências externas e continua funcionando com os dados armazenados.

---

## B. Execução local de desenvolvimento (qualquer Linux com Python 3.13)

```bash
python3.13 -m venv .venv && . .venv/bin/activate
pip install -e ".[analysis,dev]"
pytest -q                          # full test suite
open-omniscience                   # serve at http://127.0.0.1:8000
```

Variáveis de ambiente úteis: `OO_DATA_DIR` (onde ficam o banco SQLite + os dados), `OO_HOST`/`OO_PORT`,
`OO_FETCH_MIN_INTERVAL` (intervalo de cortesia por host, em segundos).

### No Tails

Debian/Ubuntu/Tails distribuem o `venv`/`ensurepip` da biblioteca padrão num **pacote apt separado**, então
`python3 -m venv` falha até que ele seja instalado. O `install.sh` agora o instala
**automaticamente** — no Tails, isso exige uma **senha de administração** (defina-a na
Tela de Boas-vindas; ela vem desativada por padrão) e uma **conexão Tor** funcionando (o apt baixa pelo
Tor). Desative isso com `OO_NO_APT=1` se preferir executar o apt você mesmo.

Duas ressalvas honestas específicas do Tails:

- **Versão do Python.** O Tails é Debian 12 → **Python 3.11**, mas o aplicativo exige **3.13**.
  Você precisa ter um interpretador 3.13 disponível e apontar o instalador para ele
  (`OO_PYTHON=python3.13 ./install.sh`); o 3.13 e o seu pacote `python3.13-venv` **não** estão
  nos repositórios padrão do Tails.
- **Amnésia.** Tudo o que for instalado via apt — e todo o `.venv` — é **perdido ao reiniciar**, a menos que
  esteja no Armazenamento Persistente: adicione o pacote do venv em **Armazenamento Persistente → Software
  Adicional** (Persistent Storage → Additional Software) e mantenha o checkout + `OO_DATA_DIR` no volume persistente.

### Atualizar um banco de dados existente

Instalações novas criam o esquema automaticamente (`init_db()`), e o banco de dados é
marcado na linha de base de migração atual. Quando uma versão futura mudar o
esquema, atualize um banco de dados existente com:
```bash
alembic upgrade head
```
`alembic check` informa se os modelos e as migrações estão em sincronia (a CI verifica isso).

---

## C. No Windows 11 (PowerShell)

**Situação honesta do suporte — leia isto primeiro.** Cada execução da CI comprova três coisas no
`windows-latest`: a instalação das dependências, a **verificação de inicialização** (o aplicativo inteiro é importado)
e a **criptografia em repouso do SQLCipher** — esta última numa via *bloqueante*, então a
criptografia não é um palpite. Nada além disso está comprovado. A **via de pytest do Windows
trava** (execuções recentes concluídas ficaram em `pytest` por 3h21m e ~6h, contra 18 minutos
no macOS), e **ninguém clicou pela interface no Windows**. Portanto: espere que a instalação
e a abertura funcionem, trate tudo o que vem depois da inicialização como não verificado e, por favor, relate o que
quebrar. O Linux continua sendo o critério de lançamento.

### 1. Instalar

Abra o **PowerShell** (não são necessários direitos de administrador, a menos que o próprio Python precise ser
instalado). Baixe o instalador, leia-o se quiser e depois execute-o:

```powershell
irm https://raw.githubusercontent.com/ideotion/Open-Omniscience/HEAD/install.ps1 -OutFile $env:TEMP\oo-install.ps1
notepad $env:TEMP\oo-install.ps1                                     # optional: see what you are about to run
powershell -NoProfile -ExecutionPolicy Bypass -File $env:TEMP\oo-install.ps1 -Extras analysis
```

Ele instala o Git e o Python 3.13 via `winget` apenas se estiverem faltando, clona em
`%USERPROFILE%\Open-Omniscience`, cria um `.venv` e verifica o resultado
importando o aplicativo real. Remova a opção `-Extras` para o conjunto padrão mais completo, ou veja
as [Opções do instalador](#opções-do-instalador).

Já clonou? Execute-o no lugar — ele detecta o próprio checkout e pula a clonagem:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

> **Por que não uma única linha `irm … | iex`?** Porque baixar código remoto e executá-lo
> direto da memória é a forma mais comum de distribuir malware no Windows, então
> o Defender classifica esse formato como hostil, seja qual for o conteúdo do script. Gravar o arquivo
> em disco primeiro tem menos chance de ser bloqueado e é mais honesto — você pode ler o que
> vai ser executado antes.

### 2. Se o Windows Defender colocar o instalador em quarentena

Ele pode apagar o `install.ps1` assim que o vê. Isso é um **falso positivo**, e você não deve
acreditar só na nossa palavra — eis exatamente por que acontece, para que você possa julgar:

- O arquivo é **não assinado e novo**, então a reputação na nuvem do Defender nunca o viu.
  Desconhecido + não assinado já basta, por si só, para disparar as heurísticas de aprendizado de máquina; o
  nome da detecção normalmente termina em `!ml`.
- O **formato** dele é de instalador: ele chama um gerenciador de pacotes, relê o `PATH` do
  registro, cria atalhos no menu Iniciar, e o seu caminho `-Uninstall` apaga
  diretórios. Os droppers fazem essas mesmas coisas. O classificador avalia o formato, não a intenção.

O que ele *não* contém, e que você mesmo pode conferir em ~500 linhas legíveis: nenhum
`Invoke-Expression`, nenhuma carga codificada ou ofuscada, nenhum `WebClient`, nenhuma janela
oculta e nenhum download além deste repositório.

Três caminhos possíveis, do melhor para o pior:

1. **Use o caminho sem script** — a [Instalação manual](#instalação-manual-sem-script) abaixo.
   Os mesmos comandos que o instalador executa, sem arquivo para colocar em quarentena. Isso sempre funciona.
2. **Relate o falso positivo** à Microsoft em
   <https://www.microsoft.com/en-us/wdsi/filesubmission> (escolha *Software developer*).
   Normalmente isso é resolvido em um ou dois dias e corrige o problema para todos que instalarem
   depois de você — não só para você.
3. **Exclua a pasta** (Segurança do Windows → Proteção contra vírus e ameaças → Gerenciar
   configurações → Exclusões). Saiba o que está trocando antes de fazer isso: uma exclusão faz o
   Defender deixar de verificar essa pasta *por completo*, para tudo, por tempo indeterminado — não só
   para este arquivo. A máquina é sua, a decisão é sua; não vamos fingir que isso não tem custo.

A correção honesta do nosso lado é a assinatura de código, que ainda não temos.

### 3. Executar

O instalador cria um atalho **Open Omniscience** na sua **Área de Trabalho** e no
**menu Iniciar**. Clique duas vezes nele: uma janela de terminal aparece, e o seu navegador abre em
**http://127.0.0.1:8000** assim que o aplicativo de fato responder. Feche essa janela (ou use o
botão de desligar do aplicativo) para pará-lo.

Pelo terminal: `scripts\launch.cmd`.

### 4. Primeira execução

O mesmo fluxo único de todas as plataformas: **escolha seu idioma → leia e aceite os
termos legais → crie a senha do seu corpus**. O corpus é **criptografado em repouso por
padrão** e **não há recuperação** para uma senha perdida. Depois, o aplicativo inicia
**offline (modo avião)**; ficar online passa por **um único pop-up de consentimento**.

### Opções do instalador

| Opção | O que faz |
|------|--------------|
| *(nenhuma)* | Núcleo + `analysis,compression,columnar`, depois verifica e cria os atalhos |
| `-Path <dir>` | Instala em outro lugar que não `%USERPROFILE%\Open-Omniscience` |
| `-Extras "analysis"` | Escolhe os extras do pip (`""` para somente o núcleo) |
| `-Ref <branch>` | Clona um branch ou tag específico |
| `-NoPython` | Nunca instala Git/Python automaticamente; em vez disso, falha com instruções |
| `-NoLauncher` | Não cria os atalhos da Área de Trabalho / menu Iniciar |
| `-Check` | Relatório de saúde (o mesmo que `open-omniscience doctor`) |
| `-Uninstall` | Remove o `.venv` + os atalhos; os dados são mantidos, salvo confirmação separada |
| `-Yes` | Responde sim às perguntas (modo autônomo) |

Somente `analysis` está comprovado no Windows pela CI. Se o conjunto padrão mais completo não
conseguir ser instalado, o script **volta para `analysis` e avisa** em vez de falhar
em silêncio ou fingir que os extras foram instalados.

### Instalação manual (sem script)

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

### Observações específicas do Windows

- **Política de execução.** A política padrão bloqueia `.\.venv\Scripts\Activate.ps1`.
  Nada aqui precisa dele: chame `.venv\Scripts\python.exe` pelo caminho e o problema inteiro
  desaparece. `-ExecutionPolicy Bypass` na linha de comando cobre o próprio instalador.
- **O `python` que abre a Microsoft Store.** Um Windows 11 recém-instalado vem com um
  stub de alias de execução chamado `python.exe` que abre a Store em vez de executar
  código. O instalador o ignora (um stub não imprime nenhuma versão) e usa o inicializador
  `py -3.13`. Se você instalar manualmente, prefira `py -3.13` a `python`.
- **Onde ficam os seus dados.** Como isto é um checkout do código-fonte, o corpus, as chaves
  de assinatura e as configurações vão para **`<repo>\data`** — não para `%APPDATA%`. Defina `OO_DATA_DIR` para colocá-los
  em outra unidade.
- **Permissões de pasta.** No Linux, o diretório de dados é restrito ao seu usuário
  (`chmod 0700`); essa chamada não tem efeito no Windows, então a pasta herda as ACLs
  comuns do Windows. Num PC compartilhado, restrinja `<repo>\data` você mesmo. O banco de dados
  do corpus continua criptografado em repouso de qualquer forma.
- **SmartScreen / Defender.** Nada aqui tem assinatura de código, então o Windows trata tudo
  como desconhecido: o SmartScreen pode alertar sobre o atalho, e o Defender pode colocar
  o `install.ps1` em quarentena de imediato — veja a
  [§2](#2-se-o-windows-defender-colocar-o-instalador-em-quarentena) para entender o que é isso e o que
  fazer. A verificação em tempo real também deixa o primeiro `pip install` visivelmente mais lento.
- **Porta.** Defina `OO_PORT` antes de abrir o aplicativo para sair da 8000; `scripts\launch.cmd`
  respeita essa variável.
- **Arquitetura (x64 / ARM64 / 32 bits).** Detectada e tratada pelo instalador; eis
  o que ele está decidindo. O que determina se o `pip install` dá certo não é a
  máquina, mas quais wheels existem para a plataforma do *interpretador*. Medido no
  PyPI em 2026-08-23, para o CPython 3.13, em todo o conjunto de dependências deste projeto:

  | interpretador | wheels |
  |---|---|
  | `win-amd64` | **todas as dependências.** A única arquitetura completa. |
  | `win-arm64` | todas menos três — `cryptography` (núcleo), `httptools` (núcleo, via `uvicorn[standard]`) e `statsmodels` (`analysis`) |
  | `win32` | `cryptography` não publica nenhuma |

  O Windows on ARM executa binários x64 de forma transparente, então um **interpretador x64 é a resposta
  certa também no ARM64** — não um meio-termo, e sim o conjunto completo. Por isso, o `install.ps1`
  prefere `win-amd64` em todos os casos e obtém um se a máquina não tiver:
  winget com a arquitetura indicada, depois winget no escopo do usuário, depois o CPython x64
  autocontido da Python Software Foundation a partir do nuget.org — verificado contra
  o SHA-512 que o nuget atesta para ele, descompactado em
  `%LOCALAPPDATA%\Open-Omniscience\python-x64`, sem precisar de elevação, de mudança no PATH
  nem de entrada no registro. Ele fica **fora** do checkout de propósito: é um recurso da
  máquina, então sobrevive à exclusão da pasta do aplicativo (caso contrário, o `.venv` criado sobre ele
  quebraria) e um segundo checkout com `-Path` o reaproveita. `-Uninstall` o remove. Uma divergência de hash, ou uma
  versão para a qual o nuget não atesta nenhum hash, é **recusada**.

  Se todas as etapas falharem, você recebe uma parada com a solução de um único download, e não uma compilação
  de Rust de vinte minutos que termina em `linker link.exe not found`.

  Um `.venv` existente é **examinado, não apenas encontrado**: ele mantém a versão e a plataforma de wheel
  do interpretador que o criou, então um que tenha sobrado de uma execução anterior com um
  Python diferente é substituído em vez de reaproveitado — caso contrário, tudo o que foi descrito acima seria
  desfeito em silêncio no último passo. Um que corresponda é reaproveitado sem alterações. Executar o
  instalador de novo é, portanto, a solução para uma instalação incompleta; nada precisa ser apagado à
  mão.

  - **Por que uma instalação nativa ARM64 não é ativada automaticamente.** Ela exigiria fixar o `cryptography`
    em 46.0.0–46.0.3, a única série com wheels ARM64. Essa versão tem
    **13 registros de alerta de segurança em aberto** (incluindo um sobre o OpenSSL vinculado estaticamente, corrigido na
    48.0.1). Este aplicativo assina evidências; instalar isso sem avisar seria teatro de
    segurança. Se a sua máquina realmente tiver o Visual Studio Build Tools **e** um conjunto de ferramentas
    Rust, `-AllowSourceBuilds` compila os três nativamente — uma escolha explícita,
    nunca um padrão.
  - **O Windows de 32 bits não é suportado**, e isso é um limite real, não uma barreira arbitrária:
    o `cryptography` não distribui nenhum wheel `win32`. É necessário o Windows de 64 bits.

---

## D. O ciclo completo (interface ou API)

> **As fontes já vêm configuradas.** Na primeira execução (ou durante `install.sh --appvm`)
> os catálogos curados (`configs/sources.yml` com ~3.200 veículos de interesse público, mais
> os catálogos de mercados, de espectro político e de direito/PI — **~3.395 domínios únicos no
> total**) são carregados automaticamente — então você pode começar a ingerir imediatamente.
> (Esses números **variam** conforme os catálogos crescem; o número real é o que
> `configs/*.yml` contém no momento.) Recarregar é idempotente. Desative o carregamento automático com
> `OO_AUTOSEED=0`; recarregue manualmente com `python scripts/seed_sources.py` ou
> `POST /api/sources/seed-defaults`. URLs de feeds e políticas de robots mudam com o tempo; o
> coletor ético recusa tudo o que não consegue confirmar, então reduza/amplie a lista conforme
> a sua investigação.

**Na interface:** **fique online** uma vez (o botão do modo avião → um único pop-up de consentimento) e
a **coleta acontece sozinha** em segundo plano — estratificada entre idiomas e etiquetas de
fontes, respeitando o robots e com limite de taxa. Depois, **pesquise em Explorar** (a aba da barra lateral; pressionar
Enter na omnibarra, barra superior ou Ctrl/⌘-K, abre Explorar em uma nova aba do navegador) — a análise dos artigos correspondentes aparece abaixo dos
resultados, onde você filtra, lê, executa consultas booleanas e **exporta** (CSV/JSON, apêndice de
métodos, evidência assinada). Você ainda pode adicionar uma fonte e *Ingerir* (*Ingest*) um único feed ou URL
manualmente em **Configurações → Avançado → Coleta / Fontes**.

**Pela API:**
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

O esquema da API legível por máquina está em **http://127.0.0.1:8000/openapi.json**. A página interativa do Swagger vem desativada por padrão (ela carrega recursos de servidores de terceiros); um desenvolvedor pode iniciar o aplicativo com `OO_API_DOCS=1` para tê-la em `/docs`.

---

## E. Recursos de análise

Todos funcionam localmente em primeiro lugar e avisam claramente quando falham (nunca inventam nada). Esquemas completos em `/openapi.json`.

**LLM local (Ollama).** Configure-o em **Configurações → IA**: um instalador do Ollama
integrado ao aplicativo e **com verificação de checksum** (Linux), além de uma **fila de download de modelos** (progresso
real em bytes, cancelamento), um seletor de modelo ativo e um painel de prompts editáveis. Ou instale
o Ollama você mesmo a partir de **ollama.com** e `ollama pull llama3.2:3b`. Os downloads de modelos saem
pela **clearnet através do processo do Ollama** (não pelo caminho Tor do aplicativo) — isso é informado no
consentimento. A pílula do LLM na barra superior mostra o status ao vivo (clique nela para abrir Configurações → IA); cada
resultado de pesquisa tem os botões **Resumir** e **Traduzir**. API:
```bash
curl http://127.0.0.1:8000/api/llm/health          # {available, installed_models}
curl -X POST http://127.0.0.1:8000/api/llm/articles/1/summarize -d '{}'  # persisted with provenance
```
Se o Ollama não estiver em execução, essas chamadas retornam HTTP 503 com uma mensagem clara — não um resumo falso.

**Preços de commodities + correlação honesta.**
```bash
curl -X POST http://127.0.0.1:8000/api/commodities/Nd/prices -H 'Content-Type: application/json' \
  -d '{"points":[{"observed_on":"2026-01-01","price":100,"unit":"kg"}]}'
curl 'http://127.0.0.1:8000/api/commodities/Nd/correlation?query=neodymium'
```
A correlação retorna um coeficiente real + valor-p + n calculados pelo scipy (Pearson/Spearman),
com a ressalva "correlação ≠ causalidade"; sobreposição insuficiente → `insufficient_data`.

**Monitoramento.** `POST /api/monitoring/health` faz verificações reais de
acessibilidade (através do coletor ético); `GET /api/monitoring/anomalies` sinaliza
picos de volume de artigos por z-score. **E-mail:** `POST /api/sources/{id}/ingest-email`
(IMAP) incorpora as mensagens ao mesmo corpus pesquisável.

**Verificação de metadados de imagem.** `POST /api/verify/image-metadata`
(envie uma imagem) retorna o formato, as dimensões, o EXIF e o GPS, com observações
factuais simples (por exemplo, presença de etiqueta de software de edição, ausência de data/hora de captura). O escopo é
declarado com honestidade como *verificações de metadados* — **não** detecção de deepfake/manipulação (isso era
inventado e foi colocado em quarentena fora da árvore de trabalho; veja
[docs/QUARANTINE_ARCHIVE.md](QUARANTINE_ARCHIVE.md)).

**Pacotes de evidência assinados.** O botão **Exportar evidência assinada** da janela de análise
(ou `POST /api/reports/evidence`) produz um pacote com raiz de Merkle,
assinado com Ed25519. Qualquer pessoa pode verificá-lo offline, sem este aplicativo:
```bash
python scripts/verify_evidence.py evidence-bundle.json   # exit 0 = verified
```

**Cadeia de custódia.** O painel **Cadeia de custódia** da interface registra a procedência assinada
e à prova de adulteração, e permite alternar o seu comportamento em tempo de execução:
assinaturas pós-quânticas, modo de ancoragem (`local` offline vs. ancorado no Bitcoin via
**OpenTimestamps**) e registro automático na ingestão. Essas opções são *preferências* — o
painel mostra o estado **efetivo**, então nada afirma estar ligado quando o seu extra
não está instalado. API:
```bash
curl http://127.0.0.1:8000/api/custody/settings                       # effective state
curl -X PUT http://127.0.0.1:8000/api/custody/settings \
  -H 'Content-Type: application/json' -d '{"pqc_enabled": true}'
curl -X POST http://127.0.0.1:8000/api/custody/log -H 'Content-Type: application/json' \
  -d '{"item_id":"article:1","item_hash":"<sha256>","action":"ingest"}'
curl 'http://127.0.0.1:8000/api/custody/export' > custody-bundle.json  # offline-verifiable
python scripts/verify_custody.py custody-bundle.json                   # exit 0 = verified
```
Modelo completo, modelo de ameaças e ressalvas de privacidade: [USER_MANUAL.md](USER_MANUAL.md).

---

## O que a "ingestão ética" garante

- O robots.txt é baixado, guardado em cache por host e **falha fechado**: se não puder ser
  confirmado (erro de rede, tempo esgotado, 5xx ou um 401/403 restrito), a URL **não** é
  baixada.
- Um intervalo mínimo por host é aplicado (respeitando o `Crawl-delay`).
- Um único caminho de download, um User-Agent que identifica o aplicativo (no modo protegido, um genérico, exceto nas requisições de API e de dumps aos servidores da Wikimedia), somente HTML para artigos — nenhum desvio direto.
- A extração usa o trafilatura; se nenhum corpo de artigo real for encontrado, nada é armazenado
  (nenhuma linha inventada "No Title / No Content").
- Todo artigo armazenado carrega a procedência: fonte, URL original, URL canônica,
  hash do conteúdo (usado para deduplicação), horário do download.
