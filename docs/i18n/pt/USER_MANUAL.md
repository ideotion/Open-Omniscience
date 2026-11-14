<!-- pt: AI-drafted translation of docs/USER_MANUAL.md (2026-11-13, R677), not yet reviewed by a native speaker; the English original is authoritative. Coverage: the whole document, 124 of 124 headings. Improve it with a pull request; corrections by native speakers are welcome. -->

# Open Omniscience — Manual do usuário

*Uma plataforma de inteligência de código aberto, ética e local-first para o jornalismo
investigativo.* Este manual é o guia acessível, de ponta a ponta: o que é o aplicativo, como
instalá-lo e executá-lo, e um passeio por **cada aba, controle, configuração e fluxo de trabalho**,
seguido de uma referência técnica (locais dos dados, variáveis de ambiente, a API HTTP
completa) e da solução de problemas.

> **Em uma frase:** o Open Omniscience reúne de forma ética notícias (e edições da
> Wikipedia, e preços de mercado) em um único banco de dados SQLite pesquisável, sem duplicatas
> e com a procedência rastreada, na *sua* máquina, permite analisá-lo (pesquisa, tendências, mapas,
> enquadramento, resumos por LLM local) e pode produzir **provas assinadas criptograficamente
> e verificáveis offline** do que ele continha e quando.

**Promessas de projeto que moldam tudo o que vem a seguir:**

- **Local-first e privado.** Tudo roda em `127.0.0.1` (somente loopback). Sem
  contas, sem telemetria, nada sai da sua máquina — o único tráfego de saída
  é o coletor ético buscando as fontes que você indica (e, se você aceitar,
  Wikipedia/OpenTimestamps/Ollama).
- **Somente números honestos.** Cada valor é um `COUNT(*)` real, um tamanho real em bytes
  no disco ou um agregado estatístico real, com o tamanho da amostra e a ressalva. O aplicativo
  prefere mostrar um erro a inventar um valor. (Vários recursos anteriores de "detecção por IA"
  que forjavam pontuações foram removidos — veja `docs/HISTORY.md`.)
- **Coleta ética.** Um único caminho de busca. O `robots.txt` é respeitado em modo **fail-closed**
  (na dúvida, ele *não* busca), cada host tem limite de taxa, e nada é
  armazenado se não tiver sido extraído o corpo real de um artigo.

---

## Sumário

1. [Instalação e primeira execução](#1-instalação-e-primeira-execução)
2. [O passeio de 60 segundos](#2-o-passeio-de-60-segundos)
3. [As ferramentas, uma a uma](#3-as-ferramentas-uma-a-uma)
   - [Início](#30-início) · [Atividade e Gerenciador de tarefas](#30a-atividade-e-o-gerenciador-de-tarefas) ·
     [Fluxo](#30b-fluxo) ·
     [Explorar: pesquisa](#31-pesquisa) · [Explorar: a análise](#31a-análise--a-janela-de-corpora) · [Recolher](#32-coletar-em-configurações--avançado--coleta) ·
     [Fontes](#33-fontes-em-configurações--avançado--fontes) · [Biblioteca](#34-biblioteca) · [Mercados](#35-mercados) ·
     [Índices](#35a-índices) · [Análises](#36-análises) ·
     [Mapa-múndi](#36a-mapa-múndi) · [Agenda](#36b-agenda) ·
     [Fontes vivas](#36b-fontes-vivas) · [Clima](#36c-clima) · [Observatório](#36d-observatório) ·
     [Wikipédia](#37-wikipédia-em-configurações--wikipédia) ·
     [Provas e custódia](#38-provas-e-custódia) · [Configurações](#39-configurações) ·
     [Ajuda e documentação](#310-ajuda-e-documentação)
4. [Fluxos de trabalho comuns (como fazer)](#4-fluxos-de-trabalho-comuns-passo-a-passo)
5. [Referência técnica](#5-referência-técnica)
   - [Onde ficam os seus dados](#51-onde-ficam-os-seus-dados) ·
     [Variáveis de ambiente](#52-variáveis-de-ambiente) ·
     [Extras opcionais](#53-extras-opcionais) ·
     [A API HTTP](#54-a-api-http) ·
     [Memória em uma máquina pequena](#55a-memória-numa-máquina-pequena--o-único-teto-real)
6. [Solução de problemas](#6-solução-de-problemas)
7. [Glossário](#7-glossário)

---

## 1. Instalação e primeira execução

O Open Omniscience tem como alvo o **Python 3.13** em Linux baseado em Debian (foi projetado para
uma AppVM Debian do **Qubes OS**, mas roda em qualquer Linux moderno). É um aplicativo
local-first, de usuário único.

### O mais fácil: o instalador de uma linha

```bash
curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/HEAD/scripts/bootstrap.sh | bash
```

Isso clona o repositório e executa `./install.sh`, que é **transparente — não pergunta nada**.
Ele instala o conjunto padrão — **Core** (coletar, armazenar, pesquisar, exportar) mais o
extra **Analysis** (estatísticas, análise de palavras-chave/entidades, correlação de mercado via
scipy/scikit-learn; spaCy opcional para um reconhecimento real de entidades nomeadas) mais compressão —
depois cria um atalho **Open Omniscience** no menu de aplicativos e na Área de Trabalho e
**abre automaticamente** o aplicativo no seu navegador em `http://127.0.0.1:8000`. (Defina
`OO_COMPONENTS` para substituir o conjunto de componentes.) Resumir/traduzir no próprio dispositivo exige um
modelo local — instale o **Ollama** em **Configurações → IA** (instalador verificado dentro do aplicativo) ou
a partir de ollama.com. Execute `install.sh` de novo quando quiser.

> Sempre inspecione um script antes de enviá-lo a um shell. O
> [`bootstrap.sh`](../scripts/bootstrap.sh) é minúsculo; você também pode clonar o repositório
> e executar `./install.sh` você mesmo.

**No Qubes:** execute `sudo ./install.sh --template` dentro da TemplateVM, reinicie a
AppVM e depois execute `./install.sh` na AppVM.

### Instalação para desenvolvedores / manual

```bash
python3.13 -m venv .venv && . .venv/bin/activate
pip install -e ".[analysis,dev]"     # core + analysis + test tooling
pytest -q                            # full suite should be green
open-omniscience                     # serves http://127.0.0.1:8000
```

Na primeira execução, o aplicativo **carrega automaticamente um catálogo mundial (~3.400 domínios únicos
entre notícias, mercados, o conjunto do espectro político e portais oficiais de leis/PI)** para que você
tenha algo a coletar imediatamente, inicializa o banco de dados SQLite e o índice FTS
e (se ativado) inicia o agendador em segundo plano.

### A página da primeira execução (idioma → termos → senha)

Em uma **instalação nova**, a primeira coisa que você vê é a página de configuração autônoma e offline
em `/unlock`, em três etapas **antes de o aplicativo abrir**:

1. **Escolha o seu idioma** — escolha entre os 12 idiomas da interface; a página inteira
   muda na hora e a sua escolha é levada para o aplicativo.
2. **Leia e aceite os documentos legais** (exibidos no seu idioma; o francês é a versão
   de referência). **Aceitar e continuar (Accept and continue)** para prosseguir, ou **Recusar (Decline)** — recusar
   **desinstala o aplicativo** (um subpainel com confirmação digitada garante que um clique
   acidental nunca apague nada).
3. **Crie a senha do seu corpus.** Novos bancos de dados são **criptografados com SQLCipher no disco
   por padrão**, então você escolhe **A senha** aqui (digitada duas vezes para confirmar). Ela é
   um segredo único e estável, como um ID de usuário, **sem recuperação e sem alternativa
   de descriptografia** — uma senha perdida custa o tempo de coletar tudo de novo, porque o corpus é
   reconstruído a partir da web. A justificativa completa e o modelo de ameaças honesto estão em
   [Configurações → Avançado → Segurança](#39-configurações).

Nas **execuções seguintes**, o armazenamento já está criado, então você vai direto a um único
pedido de **desbloqueio** com a mesma senha. Execuções sem interface/por script a fornecem com
`OO_DB_PASSPHRASE`; operar sem criptografia continua sendo uma escolha explícita (`OO_DB_PLAINTEXT=1`).

### A configuração guiada e a tela Início

Depois de entrar, uma **configuração guiada (guided setup)** única dentro do aplicativo (uma caixa de diálogo em etapas) pode acompanhá-lo
nas primeiras escolhas: ela abre em uma etapa **Idioma** e termina em uma etapa **Concluir**
que informa que o aplicativo **inicia offline** e oferece um botão *"Ficar online e começar a
recolher"*. Ficar online sempre passa pela janela de consentimento de rede (abaixo) —
o guia apenas convida; ele nunca se conecta por conta própria. Você pode executá-lo de novo quando quiser
em **Configurações → Geral → "Executar novamente o guia de primeira execução."**

Depois disso, o aplicativo abre em **Início**, que começa pelo seu **Briefing** — um fluxo de
**Pistas** honestas (veja [3.0 Início](#30-início)) — acima de uma faixa compacta **de relance (at-a-glance)** com
contagens ao vivo. Você não precisa carregar nada à mão: o catálogo selecionado **é carregado automaticamente
na inicialização**, e ficar online **começa a coletar automaticamente**, depois do que a **Pesquisa**
passa a ter artigos reais.

**A estrutura.** A navegação fica em uma **barra lateral esquerda** — uma **lista simples** das ferramentas
de dados: **Início · Fluxo · Explorar · Análises · Observatório · Mapa-múndi · Governos ·
Agenda · Clima · Índices · Matérias-primas *(avançado)* · Fontes vivas · Biblioteca** (na
profundidade de interface **Essencial**, só Início e Fluxo ficam fixados e o resto fica atrás de uma
linha rotulada **Mostrar mais**; veja [3.](#3-as-ferramentas-uma-a-uma)) (ela se recolhe a uma faixa de ícones em janelas estreitas, mas nunca
desaparece). Um botão **Configurações** fica **no pé da barra lateral** (com o
botão de recolher), e uma **barra superior mínima** acima do conteúdo traz:

- **A barra de pesquisa / comandos (⌘K / Ctrl-K).** Digite para ir a qualquer ferramenta, executar uma ação
  comum, abrir qualquer documento — ou fazer uma pesquisa federada nos seus dados (veja [3.1 Pesquisa](#31-pesquisa)).
  A pesquisa completa, com a sua análise, é a aba **Explorar**.
- **Estado ao vivo** — um ponto de saúde do backend e uma pílula **LLM** (clique nela para abrir
  Configurações → IA).
- **Gerenciador de tarefas** — um botão que abre a [janela do gerenciador de tarefas](#30a-atividade-e-o-gerenciador-de-tarefas).
- **Modo avião** — o único interruptor de rede liga/desliga (um ícone de avião cujo *preenchimento* é o
  estado; preenchido = offline). Na primeira execução, enquanto offline, uma pequena dica aponta para
  ele e convida você a ficar online quando estiver pronto.
- **Seletor de idioma** — os 12 idiomas em um só menu (a bandeira é só uma pista; o
  nome nativo é o identificador). Um clique traduz de novo toda a interface.
- **Ajuda (?)** — abre o leitor de documentação dentro do aplicativo (este manual e os outros
  guias), pesquisável e totalmente offline. (As páginas interativas Swagger/ReDoc ficam desativadas por padrão, veja §5.4.)
- **Desligar (Shut down) (ícone de energia)** — para o servidor de forma limpa; os seus dados ficam intactos, e a interface
  é substituída por um aviso "você pode fechar esta aba". (Isto *não* é desinstalar nem
  apagar.)

**Configurações** abre pelo **botão Configurações no pé da barra lateral** (a
paleta de comandos também leva direto até lá); veja [3.9 Configurações](#39-configurações).
**Aparência** (**Configurações → Gráficos**) oferece **14 temas de cores + Sistema**, cor de destaque,
densidade, um seletor de fontes incluídas e o recolhimento da barra lateral. Tudo é
armazenado localmente; nada é transmitido.

### Novidades recentes (ciclo de teste ao vivo 0.0.8, junho de 2026)

> **Retrato histórico.** Esta seção descreve o aplicativo como era no ciclo 0.0.8
> (junho de 2026); o aplicativo evoluiu desde então. `CLAUDE.md` é a fonte de verdade atual
> sobre o que foi entregue depois — veja `docs/ledger/shipped.csv` para o índice.

- **O interruptor de rede é um botão de modo avião (barra superior):** um ícone de avião
  constante cujo **preenchimento é o estado** — preenchido significa offline ativado
  (toda nova requisição de rede é recusada na hora; uma requisição em andamento pode
  terminar). **Toda volta ao modo online pergunta antes**: uma única janela de
  consentimento diz qual ação precisa da rede e lista os **endereços das interfaces
  locais** da sua máquina (lidos das próprias tabelas do kernel — nunca uma chamada
  de rede; o aplicativo deliberadamente não consulta um serviço do tipo "qual é o meu IP", porque
  isso em si já seria tráfego). Além desses endereços locais, a internet
  vê o endereço público que o seu provedor ou VPN apresentar. Iniciar uma passagem de
  coleta, importar fluxos de mercado, adicionar uma página da Wikipedia acompanhada ou baixar
  um dump passam todos pelo mesmo consentimento quando offline, e o botão
  se redesenha imediatamente a cada transição — nunca espera a próxima consulta periódica.

  **O modo avião é uma garantia no nível do socket, não apenas uma convenção por chamada.** Como
  consentimento informado sobre a *própria* proteção do aplicativo: enquanto o modo avião está ativado, o
  aplicativo instala uma **proteção em todo o processo** sobre as chamadas de socket de baixo nível
  (`getaddrinfo` / `create_connection` / `connect`), de modo que **qualquer** tentativa de alcançar um
  endereço que não seja loopback — vinda de qualquer caminho de código, de uma biblioteca de terceiros ou de uma pré-busca de DNS —
  gera um erro antes de o socket real ser usado. Loopback (127/8, ::1, `localhost`) e sockets
  Unix sempre passam, então o próprio servidor do aplicativo, um Ollama local e o banco de dados
  em arquivo continuam funcionando. Ela é transparente enquanto você está online (custo zero durante a
  coleta). Defina `OO_AIRPLANE_SOCKET_GUARD=0` para desativá-la (para uma implantação exótica
  que encaminha o loopback para outro lugar).
- **Mapa mental em camadas e nuvem de palavras (Análises):** um verdadeiro mapa mental radial (centro →
  braços → folhas para fora) em três camadas de zoom (palavras-chave ↔ famílias ↔
  supergrupos), com uma nuvem de palavras como segunda visualização, um controle de espectro de datas, um
  controle deslizante de tamanho de texto e ⛶ Ampliar. O tamanho da fonte sempre codifica o volume de artigos em comum.
- **Supergrupos pré-criados:** um conjunto inicial incluído (redigido a partir de registros
  reais de campo) é carregado na inicialização; as suas próprias edições e exclusões sempre prevalecem.
- **O Mapa-múndi agora é um coroplético (ooMap):** a aba sombreia os países segundo uma
  dimensão medida (fontes · artigos · menções de palavras-chave · tom), com controles dentro do mapa para a
  medida, a granularidade país↔continente, uma sobreposição de Lugares, uma camada de Sinais com um
  controle deslizante de momento em foco, uma camada de IPs de servidores, zoom pela roda do mouse, arrastar para mover e ⛶ Ampliar. Veja
  [3.6a](#36a-mapa-múndi).
- **Datas de eventos, lugares, pessoas e organizações extraídos do texto:** o
  extrator de datas lê seis idiomas, formatos numéricos e expressões ancoradas
  ("ontem", dias da semana isolados, "11 de junho"); o extrator de locais encontra
  cidades do índice geográfico e nomes de países; o extrator de entidades destaca **pessoas**
  e **organizações** como duas classes deliberadamente separadas (um nome precedido de um
  tratamento honorífico e uma sigla repetida respondem a perguntas diferentes — cada entrada registra
  qual regra a encontrou). Tudo alimenta o cabeçalho de metadados do leitor de artigos, que
  separa **"Da fonte"** de **"Deduzido por esta aplicação — menos fiável"**
  (caixa tracejada): as extrações são candidatas lexicais com a procedência do trecho,
  nunca fatos confirmados.
- **Exportações de palavras-chave por idioma:** o registro de palavras-chave do diagnóstico se limita a 5.000
  palavras-chave *por idioma dominante*, de modo que os vocabulários de idiomas minoritários nunca são
  expulsos da análise pelo volume do inglês.
- **Dumps offline da Wikipedia:** a lista de edições volta a carregar corretamente e permite
  seleção múltipla — baixe várias edições em idiomas diferentes em uma única execução na fila.
- **17 temas e fontes de código aberto incluídas:** nove novas paletas (Arctic,
  Solar, Forest, Aubergine, Garnet, Cyber, Mist, Dawn, Mint) juntam-se ao conjunto
  original, e seis fontes SIL-OFL agora vêm **dentro do aplicativo** (Cantarell, Inter,
  Outfit, Manrope, JetBrains Mono, Source Serif 4 — veja
  `src/static/fonts/README.md`): nada para baixar, nenhuma requisição de fonte jamais
  sai da sua máquina. Alguns temas vêm com uma fonte (Arctic→Inter,
  Cyber→Outfit, Sepia/Paper→Source Serif); o novo seletor de **Tipo de letra** em
  Configurações → Gráficos substitui qualquer uma delas, e o leitor de artigos usa a
  serifada incluída. Os controles de formulário (controles deslizantes, caixas de seleção, menus suspensos nativos) agora
  também seguem o tema.

**Uma nota sobre “FOOS”.** As abas do navegador que o aplicativo abre (investigações de Pistas, o
leitor local de artigos) recebem o sufixo **“· FOOS” — Free Open OmniScience**: curto
o bastante para faixas de abas estreitas e ainda assim identificável. É o
nome de trabalho da fase alfa; um nome definitivo pode vir mais tarde.

**Um ícone, uma interface.** O instalador cria **um atalho** — **Open
Omniscience** → `http://127.0.0.1:8000/` — um aplicativo com barra lateral, fácil de descobrir e personalizável,
que se adapta suavemente ao tamanho da janela (a barra lateral se recolhe a uma faixa
de ícones em janelas mais estreitas). Uma segunda interface experimental ("Desk") existiu
em ciclos anteriores e foi aposentada na 0.0.8; a sua história está em
[`DESIGN.md`](DESIGN.md).

**Rodando em segundo plano, com o navegador fechado.** O aplicativo vive na janela do seu atalho,
não na aba do navegador. Você pode fechar o navegador a qualquer momento: a coleta,
os downloads da Wikipedia e de mapas, os backups para uma pasta ou unidade, as importações, as tarefas de IA (downloads
de modelos, detecção de idioma, as verificações de IA) e o arquivo de diagnóstico continuam
rodando. É assim que se deixa uma máquina coletando por dias, economizando a memória que um
navegador ocupa (muitas vezes de 0,5 a 1 GB, o que faz diferença em uma VM pequena).

Enquanto o aplicativo roda, a janela do atalho mostra um **painel**, que fica ali enquanto
o aplicativo estiver rodando: há uma única janela, igualmente no Linux, no macOS e no Windows. No topo, ele mostra
se o aplicativo está bloqueado, o estado da rede e da coleta, a memória e a CPU do servidor,
e o que está rodando agora. Abaixo disso há um **registro de atividade**: uma linha com horário para cada coisa
que acontece (a coleta começa ou para, um download chega a 40 %, um backup termina, a
rede fica offline, o aplicativo para de responder e volta a responder), acrescentadas uma após a outra
enquanto o aplicativo rodar, a mais recente embaixo. Role para trás com as teclas de seta, PgUp e
PgDn ou a roda do mouse; End volta à linha mais recente. Clique nos botões ou pressione a
tecla indicada em cada um:

- **Abrir a interface (Open UI) (o)** abre o aplicativo de novo no seu navegador.
- **Pausar a coleta (Pause collection) (p)** para de coletar e coloca o aplicativo em modo avião. Para retomar,
  abra a interface: ficar online sempre passa pela janela de consentimento dela, nunca pelo terminal.
- **Mensagens do servidor (Server messages) (l)** mostra as próprias mensagens do servidor (não no Windows); pressione qualquer tecla
  para voltar.
- **Parar o aplicativo (Stop app) (s)** para o aplicativo, após um segundo toque. Ele nomeia as tarefas que seriam encerradas.

O painel não se fecha sozinho enquanto o aplicativo roda, mesmo quando o aplicativo está ocupado ou o
computador estava em suspensão e o aplicativo demora a responder: ele diz há quanto tempo o aplicativo está
em silêncio e continua tentando. Ele termina quando o aplicativo termina.
O painel nunca pede a sua senha: se o aplicativo estiver bloqueado, ele avisa, e você o desbloqueia
no navegador. Fechar a janela do atalho ou pressionar Ctrl-C continua parando o aplicativo, como
antes. Defina `OO_PANEL=0` para iniciar sem o painel. As ferramentas de IA que respondem na página
(resumir ou traduzir em lote, extração de palavras-chave por IA, execuções de prompts) também continuam depois que a
aba é fechada, e aparecem no painel. Para parar uma delas, abra a interface e pressione **Parar**
na linha dela no gerenciador de tarefas, ou **Cancelar** na página (o Parar o aplicativo do próprio painel para
o aplicativo inteiro): ela para depois do artigo em andamento, e os artigos já concluídos continuam
armazenados. O índice de palavras-chave dos artigos que as Análises ainda não indexaram também se atualiza
sozinho enquanto o aplicativo está ocioso. Só duas coisas exigem que a aba continue aberta: um envio que você está
fazendo pelo navegador e um arquivo que o navegador está baixando. No
Windows, o painel abre em uma janela própria (fechá-la não para o aplicativo). Ele precisa
do módulo curses do Python, que o Windows obtém do pacote windows-curses: o instalador
o adiciona em PCs Intel e AMD, e em uma instalação feita antes desta versão você pode adicioná-lo com
`.venv\Scripts\python -m pip install windows-curses` na pasta do aplicativo. O Windows em ARM
ainda não tem uma versão compilada dele, então ali o aplicativo inicia sem o painel.

---

## 2. O passeio de 60 segundos

O ciclo principal é:

> **Escolher/adicionar uma fonte → Recolher → Explorar (pesquisar e analisar) → Exportar / assinar.**

1. **Configurações → Avançado → Fontes** — um catálogo mundial já vem carregado; adicione as suas próprias se quiser.
2. **Configurações → Avançado → Coleta** — busque o feed RSS de uma fonte ou cole a URL de um único artigo.
   Ou deixe o **agendador** fazer isso automaticamente em um intervalo. Coletar exige a
   rede: o botão de avião na barra superior precisa estar desligado, e desligá-lo pede a sua confirmação
   antes.
3. **Início** e **Fluxo** — leia o que chegou: Início como sinais medidos (Pistas), Fluxo como
   uma sequência simples de artigos.
4. **Explorar** — pesquisa booleana de texto completo em tudo o que você reuniu; a
   análise dos artigos correspondentes aparece embaixo dos resultados.
5. **Análises / Observatório / Mapa-múndi / Governos / Agenda / Clima / Índices /
   Matérias-primas / Fontes vivas** — visualizações opcionais sobre o corpus e sobre dados
   públicos (padrões, espaço-tempo, leis, datas, registros climáticos, preços, o que mudou).
6. **Exportar** — CSV/JSON, ou um **pacote de provas assinado** que qualquer pessoa pode verificar
   offline.

Escolha qualquer ferramenta na barra lateral, ou simplesmente pressione **⌘K / Ctrl-K** e digite aonde
quer ir. Para um passeio curto pelas abas da barra lateral na sua profundidade de interface,
escolha **Fazer o tour** (Configurações → Geral, Ajuda e documentação, ou a paleta de comandos).
Ele só começa quando você pede, não altera nada e não guarda registro de ter sido executado. A visualização ativa se atualiza sozinha ao vivo (a cada poucos segundos) enquanto está na
tela, e as ações são confirmadas com pequenas notificações no canto.
Ações destrutivas sempre perguntam antes.

---

## 3. As ferramentas, uma a uma

A barra lateral é uma **lista simples** das ferramentas de dados (de cima para baixo):

- **Início · Fluxo · Explorar · Análises · Observatório · Mapa-múndi · Governos · Agenda ·
  Clima · Índices · Matérias-primas *(avançado)* · Fontes vivas · Biblioteca** — mais o botão **Configurações**
  no pé da barra lateral. A Ajuda abre pelo botão **?** na barra superior.
  Não existe uma aba "Recolher": a coleta fica em Configurações.
- **Explorar** é uma única página: a caixa de pesquisa no topo e a análise dos artigos
  correspondentes embaixo dos resultados assim que uma pesquisa retorna (veja [3.1](#31-pesquisa) e
  [3.1a](#31a-análise--a-janela-de-corpora)). Uma palavra-chave
  clicada dentro do aplicativo abre a sua análise nesta página; uma palavra-chave no leitor de artigos,
  o **Abrir o corpus ↗** de uma Pista do Início e Enter na omnibar a abrem em Explorar em uma
  **nova aba do navegador**.
- A **Profundidade da interface** (Configurações → Geral) muda o que a barra lateral *fixa*, nunca o que
  você consegue alcançar. Em **Essencial**, só Início e Fluxo ficam fixados e as outras abas ficam
  atrás de uma linha rotulada **Mostrar mais**; **Padrão** e **Completo** listam todas as abas. A
  paleta de comandos (Ctrl/⌘-K) alcança todas as abas em qualquer profundidade.

**O conteúdo em primeiro lugar.** A barra lateral mostra os *dados*; as superfícies de aquisição e manutenção
ficam em **Configurações**: **Recolher** (o agendador + a coleta manual), **Fontes**
(o catálogo), **Wikipédia** (acompanhamento de alterações + dumps offline), **Provas e custódia**
e a **mesa de integridade das fontes (source-integrity desk)** são todos acessados a partir de Configurações (documentados nas suas próprias
subseções abaixo). Configurações abre pelo **botão no pé da barra lateral**; a
paleta de comandos também leva direto até lá.

Alguns nomes mudaram para ficar mais simples (os controles são os mesmos): **Ingest → Recolher**,
**Database → Biblioteca**, **World law → Governos** (agora com as subabas **Países · Mapa · Direito**),
**Mercados → Matérias-primas** (com **Índices** separado). Vá a qualquer ferramenta com
a paleta de comandos (Ctrl/⌘-K).

### 3.0 Início

**Para que serve:** o seu **briefing** — um fluxo de triagem mais orientação.

- **Briefing (o fluxo):** o aplicativo reúne e mede em segundo plano, depois
  destaca histórias candidatas como **Pistas** (o nome na tela para os cartões do briefing),
  agrupadas em categorias editoriais (*em alta, supernoticiado, subnoticiado, investigar,
  verificar o enquadramento, acompanhar, contexto, integridade dos dados*). Cada Pista é **um sinal
  medido + links de evidências + uma ressalva** — nunca um veredito, e **não existe "pontuação de
  confiança"** (proibida no código).
- **Cartões que viram — o aviso fica no verso.** Uma Pista é um **cartão de dois lados que vira**:
  a **frente** é a pista de relance; **clique nele (ou pressione Enter)** e ele vira para um
  **verso** que traz **a ressalva, o método, o motivo do disparo, as evidências e um botão
  "Abrir o corpus ↗"** (que abre o conjunto exato de artigos daquela Pista em uma nova janela
  de análise). A ressalva está no DOM por padrão, logo ao lado da ação — nunca fica
  escondida atrás de um botão de modo calmo. **+ Adicionar ao rascunho** fixa uma Pista; **Dispensar** a oculta
  (reversível). O fluxo fica em cache (instantâneo) e **se atualiza sozinho** — ele é recalculado em
  segundo plano após cada passagem de coleta e consulta de novo por conta própria; não há botão Atualizar.
- **Rascunho de newsletter:** Pistas fixadas + as suas notas, exportadas em **Markdown**, em que
  cada afirmação já traz os seus links de fonte, método e ressalva — jornalismo
  reprodutível. Para uma cópia assinada dos artigos subjacentes, use Provas e custódia.
- **Layout com o conteúdo em primeiro lugar:** uma faixa compacta **de relance** fica fixada no topo (contagens
  ao vivo + se a coleta automática está rodando), e as Pistas abaixo podem ser filtradas
  por **família** através de subabas verticais (uma lente padrão **"Todas as pistas"**, mais uma aba por
  categoria, cada uma com a sua cor). O catálogo selecionado é carregado automaticamente e a coleta começa quando você
  fica online, então um Início vazio simplesmente mostra um estado vazio honesto — sem cartão de boas-vindas. *(A
  antiga saudação de destaque e a linha de "Ações rápidas" foram removidas — Início abre direto no
  Briefing.)*

### 3.0a Atividade e o Gerenciador de tarefas

**Para que serve:** ver — e conduzir — tudo o que o aplicativo está fazendo em
segundo plano, a partir de qualquer aba.

- Um **indicador de atividade** na barra superior se acende enquanto há trabalho em andamento (uma passagem de coleta, um
  dump da Wikipedia, uma importação de mercado); um botão persistente de **gerenciador de tarefas** fica ao lado dele
  (continua acessível mesmo quando o aplicativo está ocioso).
- Abra o **Gerenciador de tarefas** — uma janela de verdade (não um balão) com cinco subabas:
  - **Em curso** — cada tarefa em execução: a passagem de coleta, cada dump da Wikipedia sendo baixado,
    a busca em andamento (mostrada apenas como DOMÍNIO), o ciclo ocioso e qualquer download
    pausado/com falha. Cada tarefa mostra o seu progresso real e os controles aplicáveis — **Parar** uma
    passagem de coleta (isso também aciona o interruptor geral de rede, então você fica offline; o
    botão avisa isso) e **Pausar/Cancelar** um dump. Nenhuma previsão de término ou taxa inventada — só o
    progresso real em bytes informado pelo responsável pela tarefa.
  - **Fila** — tarefas aguardando a vez: a fila de download único de dumps da Wikipedia, em
    ordem, com controles **↑ / ↓** para reordená-la (passe um pequeno dump francês à frente de um
    enorme dump inglês).
  - **Agendamento** — os fatos reais do agendador: estado (rodando / ocioso / parado),
    progresso da passagem atual (só o domínio), cadência, última execução e o horário da próxima execução
    informado pelo próprio backend, mostrado como tempo relativo honesto (o método está no balão ao passar o mouse —
    nunca uma contagem regressiva inventada).
  - **Cobertura** — alcance e atualidade da coleta por etiqueta (quanto de cada tema/etiqueta a sua
    coleta está de fato alcançando, e quão atualizado está), para que você veja as lacunas.
  - **Sistema** — sinais vitais do processo ao vivo (CPU, RAM, taxa de download). *(Os sinais vitais vieram para cá,
    saindo da barra superior.)*
- A janela lê **ao vivo dos sistemas responsáveis pelo trabalho**, então nunca pode
  divergir do que está de fato acontecendo — nenhum estado paralelo.

### 3.0b Fluxo

**Para que serve:** ler o seu corpus como uma **sequência** em vez de um conjunto de sinais
medidos. Início diz o que se destacou; o Fluxo apenas entrega artigos, um após o
outro, e deixa você rolar.

- **Duas ordens, ambas declaradas.** **Mais recentes primeiro** é a data de publicação, a mais recente no topo.
  **Embaralhada** é uma ordem fixa escolhida por uma **semente**: a posição de um artigo depende
  do seu id e dessa semente e de **nada mais**. Cada página traz a sua própria linha de método
  dizendo qual das duas você está lendo.
- **O embaralhamento é uma ajuda para navegar, não um recomendador.** Não há **nenhuma pontuação de engajamento
  de qualquer tipo** — nada mede o que você abriu, quanto tempo ficou ou o que você
  pulou, e **nenhum histórico de leitura é guardado ou consultado**. Duas pessoas com a mesma
  semente e o mesmo corpus veem a mesma ordem. Essa frase faz parte do texto de método
  que a página imprime, então ela não pode deixar de ser verdadeira sem que se perceba.
- **O que fica de fora, contado.** O Fluxo mostra os artigos que **não estão em quarentena**
  e cuja **fonte foi qualificada**. As duas exclusões são **contadas com exatidão** e
  mostradas na primeira página, de modo que um fluxo curto em um corpus cheio se lê como *"as suas fontes ainda não
  foram qualificadas"* — o que permite agir — em vez de *"você não tem nada"*,
  o que seria falso. Essas duas contagens descrevem o corpus e não a página, então
  são calculadas uma vez e não mudam enquanto você rola.
- **Onde você parou.** A rolagem mantém a sua posição entre sessões guardando **um
  marcador de posição** no seu navegador — uma semente e um único cursor, nunca uma lista do que
  você leu. **Configurações → Geral → Histórico de deslocamento do fluxo** tem os dois controles:
  **Embaralhar de novo** (uma nova semente, uma nova ordem, de volta ao início) e **Começar do topo**
  (mesma ordem, posição apagada).
- **A lacuna honesta de cada ordem.** A coleta continua rodando enquanto você rola, e cada
  ordem deixa escapar os artigos recém-chegados de um jeito diferente: em **Embaralhada** eles podem cair *abaixo*
  do ponto que você alcançou (baralhar de novo os alcança), e em **Mais recentes primeiro** eles
  chegam *acima* dele (voltar ao topo os alcança). A página diz qual caso se aplica.
- **Cada cartão** mostra o título, a fonte, a data e as **três principais palavras-chave do próprio
  artigo** — as palavras-chave daquele artigo, não do que você pesquisou. **Ler mais**
  expande o resumo **no próprio lugar**; o título abre o artigo no leitor local.

### 3.1 Pesquisa

**Para que serve:** encontrar artigos no seu corpus. A Pesquisa é a metade de cima da aba
**Explorar** na barra lateral; a análise dos artigos encontrados
([3.1a](#31a-análise--a-janela-de-corpora)) aparece logo embaixo dos resultados, sem
botão para apertar. Uma pesquisa sem palavras e sem filtro simplesmente lista todos os artigos e
não analisa nada.

- **Consulta booleana** — aceita `AND` / `OR` / `NOT`, `"exact phrases"` e
  parênteses com a precedência correta, por exemplo
  `(climate OR energy) AND policy NOT opinion`. Baseada no SQLite FTS5 e totalmente
  parametrizada (sem injeção).
- **Palavras em árabe, chinês e japonês são encontradas seja qual for a forma de escrita.** Uma palavra
  árabe corresponde com ou sem sinais vocálicos e qualquer que seja a grafia do alef, do teh
  marbuta ou do alef maksura (أحمد encontra احمد, مدرسة encontra مدرسه), e uma palavra chinesa ou japonesa
  é encontrada dentro de um trecho de texto mais longo (东京 encontra um artigo que diz 东京大学).
  O chinês é dividido em palavras pelo jieba em todas as instalações; o japonês pelo sudachipy, que
  vem com o extra opcional `[segmentation]`. Os artigos indexados antes desta versão
  continuam sendo encontrados como sempre foram, e passam a ser encontrados também por palavra depois que **Reindexar
  a pesquisa (Re-index search)** (Configurações → Avançado → Diagnóstico) for executado.
- **Filtros:** Fonte (nome exato), Idioma (código como `en`) e um controle de **intervalo de
  tempo** — campos de data De/Até, uma barra de intervalo arrastável e atalhos rápidos
  (1M · 6M · 1Y · 5Y · All) — o *mesmo* controle usado em Mercados, Análises e na
  janela de Análise. Deixado em toda a sua extensão, ele não exclui nada; estreite-o para limitar a
  pesquisa a um período. Tudo opcional.
- **Pesquisa** executa a consulta; a tabela de resultados mostra **Título · Fonte · Publicado ·
  Idioma** e uma contagem (`N result(s)`, e quantos são mostrados se a lista estiver truncada).
- **Ações por linha:** **abrir** (uma cópia offline limpa do artigo armazenado),
  **fonte ↗** (a URL original), **Resumir** e **Traduzir** (LLM local, se o
  Ollama estiver disponível).
- **Exportações:** **Exportar CSV**, **Exportar JSON** e **Exportar evidência assinada** — um
  pacote assinado, que revela adulterações, contendo exatamente os artigos que correspondem à sua consulta (veja
  [Provas e custódia](#38-provas-e-custódia)). Ele abre primeiro uma revisão: quantos
  artigos e fontes, o que o arquivo contém, que ele não é criptografado e qual chave assina;
  salvar é mais um clique, e a mensagem seguinte lista os membros do arquivo e a
  chave a entregar ao destinatário. Há também um **Apêndice de métodos** (um registro reprodutível da
  consulta + método).
- **Execuções do modelo local sobre todos os resultados:** **Resumir tudo** / **Traduzir tudo** colocam na fila
  uma execução em segundo plano do seu modelo local sobre cada artigo encontrado (armazenada com o modelo +
  a data e — por ser saída de IA — nunca incluída no índice de palavras-chave confiável); **Executar
  extrator** executa um dos seus extratores de IA personalizados sobre o conjunto; **Sintetizar resultados**
  abre uma janela em que você escolhe até 20 membros e obtém uma passagem única, com citações, do modelo local sobre
  eles (veja o aprofundamento). As execuções ficam na fila e podem ser canceladas; os mesmos controles estão na
  janela de análise.

> **Dois caminhos de entrada.** Abra **Explorar** pela barra lateral, ou digite na omnibar e escolha
> *"Executar a pesquisa booleana completa"*: os dois levam à mesma página com a consulta já preenchida.

**A omnibar (Ctrl/⌘-K), de qualquer lugar:** a paleta de comandos também é uma
pesquisa federada nos seus dados. A partir de dois caracteres digitados, ela mostra os três primeiros
resultados por grupo — **artigos** (FTS booleana completa), **palavras-chave** (cada uma abre
a janela do seu corpus), **fontes**, **páginas da Wikipedia acompanhadas**, **textos da Wikipedia
guardados nesta máquina** (versões antigas e textos de páginas alteradas que a seção Wikipedia guarda,
veja 3.7) e **documentos legais acompanhados** — com o *total real* de cada grupo indicado no seu cabeçalho.
Tudo se apoia em índices e é pesquisado somente nesta máquina; uma consulta digitada pela
metade nunca é um erro. Escolher *"Executar a pesquisa booleana completa"* leva você a
esta aba com a consulta já preenchida, de modo que todos os recursos acima ficam a um passo
de distância.

### 3.1a Análise — a janela de corpora

**Para que serve:** transformar um *conjunto* de artigos, ou uma única palavra-chave, em um objeto
de análise que você pode ler de todos os ângulos. Uma palavra-chave é um corpus; um único artigo é um corpus
de um só. A análise fica na página **Explorar**, embaixo dos resultados da pesquisa. Ela
aparece quando você:

- executa uma pesquisa em Explorar (ou escolhe *"Executar a pesquisa booleana completa"* na omnibar),
- pressiona **Enter** na omnibar (isso abre Explorar em uma nova aba do navegador),
- clica em uma **palavra-chave** em qualquer lugar (Análises, o verso de uma Pista ou o leitor, onde ela abre em uma nova aba do navegador),
- clica em uma **Pista do Início** (o seu "Abrir o corpus ↗" abre o conjunto *exato* de artigos, em uma nova aba do navegador), ou
- clica no título do gráfico de uma matéria-prima / **Analisar ↗**.

Quando uma análise é aberta a partir de outro lugar (uma palavra-chave, uma Pista, uma matéria-prima), a
lista de pesquisa é posta de lado e a página diz de quem é a análise que está mostrando, de modo que a lista e
a análise nunca descrevam silenciosamente dois conjuntos diferentes de artigos. Várias análises
coexistem como **abas nomeadas** em uma faixa no topo; cada uma tem como título a sua consulta e mostra a
**contagem de artigos** sobre a qual foi calculada. As subabas são:

- **Visão geral** — um resumo do conjunto em um relance.
- **Palavras-chave** — a tabela ordenada de palavras-chave (coocorrência real / n / PMI, sem pontuação).
- **Tendência** — a tendência de menções/volume ao longo do tempo, desenhada com o kit compartilhado de gráficos
  interativos (zoom pela roda do mouse, arrastar para mover, passar o mouse para uma leitura exata; resolução completa dentro da
  janela, com os trechos esparsos mostrados honestamente como barras + uma ressalva de corpus inicial em vez
  de uma curva forjada).
- **Mapa mental** — um mapa radial determinístico de palavras-chave (centro → braços, sempre para fora).
- **Artigos** — os artigos membros (paginados). Colunas: **Título · Fonte ·
  Publicado · Palavra-chave principal**, e cada cabeçalho de coluna é o **controle de ordenação** — clique em um
  para ordenar por ele, clique de novo para inverter; a seta marca a coluna em vigor. Os nomes
  abrem de A a Z, as datas e contagens abrem com o maior primeiro. A mesma escolha está nos menus
  **Ordenar por / Ordem** acima da lista, porque são os mesmos dois campos: há
  exatamente uma ordenação nesta janela, então nada pode substituir a sua escolha sem que se perceba. *(A
  ordenação ficava antes em **Avançado**, a três subabas da única lista que a usa.)*

  **Palavra-chave principal** é a palavra-chave mais mencionada DO PRÓPRIO artigo, com a sua contagem, calculada
  quando o artigo foi indexado — uma pergunta diferente da contagem da palavra-chave *pesquisada*,
  que é o botão separado `↕ "term" count`. Quando várias palavras-chave empatam nessa contagem,
  a linha diz **empatadas**, porque a que aparece é simplesmente a primeira delas, e chamá-la
  de palavra-chave principal afirmaria uma classificação que a contagem nunca fez. Um artigo que a reindexação ainda
  não alcançou mostra **—**, nunca 0: falta-lhe uma medição, não
  palavras-chave.

  Cada linha abre no **leitor offline**, cuja própria barra de abas é **Ler · Resumo ·
  Tradução · Palavras-chave · Mapa mental · Sentimento · Relacionados · Fonte · Links** — é ali
  que você o lê, vê a sua **fonte original** (o texto visível do link é a URL
  completa) e executa **Resumo / Tradução** no modelo local. Esses três antes eram
  repetidos como uma seta por linha e dois botões por linha; eles foram para a única página que
  consegue de fato mostrar o resultado. **Resumir tudo / Traduzir tudo** em lote continuam iguais na
  linha de ações abaixo. Cópias quase idênticas recebem o selo "N cópias = uma voz".
- **Quando/Onde/Quem** — as datas, lugares e pessoas/organizações que o conjunto menciona, como **facetas**
  clicáveis; clicar em um valor **aprofunda** apenas nos artigos que o mencionam (uma janela de
  análise refinada). Deduzido do texto, nunca confirmado.
- **Links** — quais artigos membros **compartilham links de saída**. Isso revela
  de propósito a *estrutura de origem comum*: três artigos que citam uma mesma origem são uma fonte
  usando três chapéus, então a convergência só conta como corroboração quando os caminhos são
  independentes. O objetivo são as *fontes das fontes*.
- **Relacionados** — cópias quase idênticas entre fontes ("N cópias = uma voz") e origens
  comuns, cada uma com um **"Ramificar para um novo corpus →"** que cria uma nova janela de análise
  exatamente sobre esses artigos.
- **Sentimento** — o tom por fonte (VADER; a ressalva de que só funciona em inglês é exibida).
- **Fontes** — a procedência descritiva dos veículos do conjunto.
- **Competitivo** — como os veículos do conjunto se comparam (volume / tom / momento /
  ênfase — descritivo, nunca um vencedor ou uma pontuação).
- **Preço** — *(só quando a janela foi iniciada a partir de uma matéria-prima)* a curva de preço
  sobreposta à cobertura do seu corpus em um eixo de tempo compartilhado (coocorrência, nunca causalidade),
  cada série na sua própria escala, em unidades reais.
- **Avançado** — delimite o conjunto por **fonte · idioma · intervalo de datas**; um selo "Filtrado"
  e um resumo mostram o que está ativo. (A ordenação foi para a aba Artigos, acima.)

A linha de ações traz **Apêndice de métodos**, **Exportar evidência assinada**, **Sintetizar
resultados** (a janela de seleção de membros) e as execuções do modelo local em fila **Resumir tudo / Traduzir tudo / Executar
extrator** — o mesmo conjunto da pesquisa acima.

### 3.2 Coletar *(em Configurações → Avançado → Coleta)*

> **Onde fica agora.** A coleta é uma superfície de aquisição, por isso saiu da
> barra lateral e foi para **Configurações → Avançado → Coleta** (conteúdo em primeiro lugar). Os controles não mudaram.

**Para que serve:** trazer artigos para o corpus — de forma automática ou manual.

**A. Ingestão automática (o agendador).** Um processo em segundo plano que faz a ingestão
em intervalos regulares. Controles:

- **Iniciar / Parar / Coletar agora** — executar continuamente, interromper ou fazer uma única passagem
  imediatamente. A etiqueta de status mostra `running` / `running — scrape in progress` /
  `stopped` e o horário da próxima execução; a linha abaixo mostra o balanço da última execução.
- **Intervalo (minutos)** e um controle deslizante **Velocidade de coleta** (uma meta de taxa de download). O
  aplicativo mede sua própria taxa real de download e aumenta ou diminui o número de hosts
  simultâneos para acompanhar a sua meta, recuando automaticamente quando a CPU, a memória ou o único
  gravador criptografado se torna o limite; a cortesia com cada host nunca é trocada por velocidade.
  *(Não existe um limite de "máximo de fontes por execução" — com o tempo todas as fontes são cobertas, então nenhuma
  fica sem vez.)*
- **Modo:** *Feeds RSS*, *Rastreamento recursivo*, *Mercados (regras de preços)* ou *Wikipédia (páginas vigiadas)*.
  Escolher **rastreamento** exibe **Profundidade de rastreamento** e **Páginas máx. / fonte**
  (o rastreador fica dentro do próprio domínio de cada fonte, respeita o robots.txt
  com bloqueio por padrão em caso de dúvida, tem limite de taxa e limites rígidos — ele *descobre* artigos, não
  espelha sites).
- **Alvos:** **Idiomas**, **Tipos de fonte** e **Tags / palavras-chave (qualquer uma)**
  restringem quais fontes uma execução toca. **Pré-visualizar alvos** mostra exatamente quantas
  fontes correspondem (com detalhamento por idioma e tipo) *antes* de você executar.
- **Iniciar automaticamente ao abrir** + **Guardar agendamento** salvam a configuração.

**B. Ingestão manual.**

- **Ingerir o feed RSS de uma fonte** — escolha uma fonte e clique em **Buscar feed**.
- **…ou ingira a URL de um único artigo** — cole uma URL e clique em **Ingerir URL**.

De qualquer forma, a linha de resultado mostra um balanço: armazenados, duplicados ignorados, bloqueados pelo
robots etc. A busca é sempre ética (robots com bloqueio por padrão, limite de taxa).

### 3.3 Fontes *(em Configurações → Avançado → Fontes)*

> **Onde fica agora.** Assim como Coletar, o catálogo de fontes foi para **Configurações →
> Avançado → Fontes** (conteúdo em primeiro lugar). Os controles não mudaram.

**Para que serve:** registrar e organizar os veículos de onde você coleta.

- **Adicionar uma fonte:** Nome, Domínio, URL do RSS, Tags → **Adicionar fonte**. Ou **Semear
  fontes iniciais** para registrar o conjunto selecionado de interesse público.
- **Gerenciar fontes (tabela):** filtre por texto de busca, país, idioma, tipo, tag
  e estado de ativação. As colunas são **ordenáveis** (Nome, Domínio, Tipo, País, Idioma,
  Prioridade (Priority), Artigos). Na própria linha você pode alterar a **Prioridade** (1–3), ativar ou desativar **Ativadas**
  e **Excluir** (com confirmação). Paginada, com uma contagem `N source(s)`.
- **Importar / Exportar (CSV):** **Exportar tudo (CSV)**, **Baixar modelo** e
  **Importar CSV**. Colunas: `name`, `domain` (obrigatórias), além de `rss_url`,
  `source_type`, `country` (2 letras), `language`, `region`, `tags`
  (separadas por vírgula), `priority` (1–3), `rate_limit_ms`, `enabled`,
  `reliability_score` (1–10). A importação **faz upsert por domínio** — linhas novas são criadas,
  as existentes são atualizadas — e **linhas com erro são relatadas, não descartadas em silêncio**.

#### Qualificação de fontes — a porta de admissão

**Ativar uma fonte não basta por si só** — uma fonte só é *coletada* depois
de ser **qualificada**. Toda fonte leva um de três carimbos categóricos, nunca
uma pontuação de qualidade:

- **não julgada** (unqualified) — ainda não avaliada (o padrão para uma fonte descoberta, citada ou adicionada
  à mão);
- **qualificado** — passou por uma pequena busca de teste que verificou a *validade da extração* (prosa
  real versus uma raspagem quebrada/lixo, por exemplo uma página de menu de navegação ou um paywall) — agora
  entra na coleta regular;
- **desqualificado** — as páginas extraídas no teste pareciam estruturalmente quebradas, não
  apenas "chatas" ou concisas (o estilo nunca é julgado, apenas se algum texto real de artigo
  voltou).

**O catálogo selecionado que acompanha o aplicativo já vem qualificado** (decisão do
mantenedor de 2026-09-10). Suas linhas — os catálogos de notícias, espectro, mercados e direito verificados à mão —
levam um carimbo cuja *base* é o próprio catálogo, exibido no painel de proveniência da fonte
como **qualificado · por catálogo**, e entram na coleta desde o primeiro dia em vez de esperar
sua vez atrás da fila de descobertas. O carimbo não é uma medição e nunca se apresenta como
tal: é reverificado no **mesmo relógio de três meses de toda fonte qualificada** (abaixo),
uma reverificação que falha desqualifica a fonte exatamente como qualquer outra, um veredito que esta instância
já alcançou nunca é sobrescrito por ele, e a exportação de qualificação conta essas
linhas à parte e nunca as distribui como vereditos conquistados. Fontes descobertas, citadas e adicionadas à mão
continuam passando pelo teste.

Um **processo em segundo plano executa algumas dessas verificações de teste automaticamente a cada passagem de coleta
online** (uma busca limitada, consentida e em rede de "poucos artigos" — recusada
no modo avião, exatamente como qualquer outra ação de rede). Numa instalação nova com
muitas fontes recém-semeadas/descobertas, esse gotejamento pode deixar uma fila pendente real: **Configurações
→ Fontes → "Qualificação de fontes"** mostra o painel e um botão **"Qualificar a fila pendente"**
que executa a *mesma* avaliação em lote, como uma tarefa cancelável do gerenciador de tarefas, para
pôr o atraso em dia mais rápido.

**A fila de qualificação** (Avançado → Controlos de qualidade) mostra o que as próximas passagens vão
avaliar, em ordem: **fontes novas primeiro** (nunca avaliadas, ou tentadas ainda sem artigos suficientes),
depois as fontes cuja reverificação está vencida. Uma fonte nova é sempre mais urgente que uma
reverificação (decisão R94). O painel também diz quantas fontes qualificadas estão esperando e quando
a próxima entra na fila.

**Quantas fontes uma passagem avalia** cresce com a máquina (decisão R95): o número em
Configurações → Avançado → Controlos de qualidade (*Fontes a avaliar em cada passagem de recolha*) e as
*reverificações de qualificação por passagem* (qualification re-checks per pass) do agendador (definidas pela configuração do agendador, `PUT /api/scheduler/config`;
não há controle em Configurações para isso) são um mínimo, e enquanto o *orçamento automático de qualificação* (qualification budget auto) estiver ligado (o padrão) cada passagem avalia tantas
fontes novas e reverificações quanto a memória e os núcleos da máquina suportarem, sem teto fixo. Um
valor abaixo dos padrões, ou 0, é mantido como informado; desligar o modo automático fixa os números
exatamente. Cada candidata é avaliada com base nos seus artigos mais recentes, tantos quanto a memória disponível
comportar (no mínimo 2.000), e a passagem diz a quantas candidatas esse limite se aplicou.

**Numa máquina pequena** (menos memória que o mínimo de varredura do aplicativo), uma passagem avalia as candidatas
contra uma **amostra dos 20.000 artigos mais recentes** em vez do corpus inteiro, e o
veredito registra que foi feito por amostragem (decisão R93). Antes disso, essas máquinas pulavam todas as
passagens em silêncio e nenhuma fonte era qualificada. Se nem a amostra couber, a passagem
avisa e não começa.

Uma **fonte desqualificada ganha uma segunda chance** — nunca é excluída, e o relógio
(nunca uma reimportação nem uma nova citação) é a única coisa que dispara uma reverificação:
1 mês após a primeira desqualificação, dobrando até um teto de 6 meses (1 → 2 → 4 →
6), e zerando no momento em que uma reverificação passa. **É por isso que uma fonte recém-adicionada ou
recentemente desqualificada pode ficar ativada-mas-não-coletada por até seis
meses** sem coletar nada — verifique a etiqueta de qualificação na linha dela (abaixo) se uma
fonte que você adicionou parece nunca contribuir com artigos.

**Para onde foi a contagem de qualificação:** o bloco da Biblioteca que antes mostrava um único
número de "Fontes" agora mostra **três números honestos e sem sobreposição** — *Fontes
(coletando)* (Sources (collecting)) (ativadas **e** qualificadas), *Fontes aguardando qualificação (ativadas)* (Sources awaiting qualification (enabled))
e *Candidatas descobertas* (ainda desativadas — veja abaixo) — porque juntá-los num
único número fazia uma fila de descobertas gerada pela máquina, com dezenas de milhares de candidatas,
parecer como se o aplicativo já estivesse coletando de todas elas.

#### Reverificação — um carimbo não dura para sempre

Um veredito é uma medição, e uma medição envelhece. **Um carimbo de qualificado é reverificado
mais ou menos a cada três meses** (decisão R94, 2026-09-29) (a configuração `qualification_recheck_per_pass` do agendador, só pela API; 0
desliga a reverificação). A reverificação tem intervalo fixo, não a progressão em dobro da escada
dos desqualificados — dobrar expressa uma esperança cada vez menor após falhas repetidas e não significa
nada depois de um sucesso.

**O que uma reverificação consegue e não consegue ver, dito com clareza:** ela julga uma fonte por todo o seu
histórico armazenado, então detecta uma fonte que está *amplamente* quebrada, e **não**
percebe uma fonte que piorou recentemente se anos de bons artigos pesarem mais que os
recentes. Seu valor real é outro e vale a pena conhecer: uma fonte admitida muito cedo,
com apenas um ou dois artigos, foi julgada quando ainda não havia corpus suficiente para
compará-la — a reverificação é a primeira vez que ela é medida contra uma base de
referência real.

As reverificações têm seu **próprio** orçamento, separado daquele que admite novas candidatas.
Isso não é um detalhe: enquanto compartilhavam um orçamento, uma instalação com uma grande fila de
fontes não examinadas gastava todas as vagas com novas candidatas, e nenhuma reverificação — incluindo a
segunda chance dos desqualificados descrita acima — chegava de fato a rodar.

#### Os vereditos viajam: cópias de segurança e uma instalação nova

O trabalho de qualificação feito numa instância **não se perde quando você move ou mescla corpora**.

- **Importar uma cópia de segurança** traz os vereditos dela. Uma fonte que o corpus importado julgou
  chega julgada. Uma fonte que *esta* instância nunca julgou **adota** o veredito
  importado — nos dois sentidos, então uma fonte que outra instância considerou quebrada não
  volta discretamente à fila de teste aqui. Um veredito que *esta* instância alcançou sempre vence:
  um corpus importado nunca pode derrubar o julgamento da sua própria máquina, em nenhum
  sentido.
  O carimbo inicial do próprio catálogo não é um veredito desse tipo: um veredito *medido* importado
  o substitui. Quando uma fonte que ainda tem apenas o carimbo do catálogo recebe um julgamento importado
  mais recente de *desqualificado*, a próxima inicialização a retira da coleta e a lista nos
  diagnósticos; quando o veredito da sua própria máquina discorda da importação, o seu é mantido e a
  fonte é reverificada antes do prazo pela sua própria passagem de qualificação.
- **Uma instalação nova começa a partir do que instâncias anteriores mediram.** O aplicativo vem com
  `configs/source_qualification.yml`, uma lista gerada de vereditos, e os adota na
  primeira inicialização para as fontes que nunca julgou. Uma fonte **ausente** desse arquivo simplesmente
  vem não julgada e é avaliada pela primeira passagem de qualificação da própria instalação, exatamente
  como antes de o arquivo existir — então o catálogo distribuído é, na prática, duas listas: as
  fontes já qualificadas pelo aplicativo e as que ainda faltam.

Um veredito adotado é registrado como **herdado**, não como algo que esta máquina mediu,
e mantém a data em que foi originalmente alcançado — então nada jamais parece ter sido medido pela
sua instalação. O que começa do zero é o relógio de reverificação da sua própria máquina: ele conta a partir
do dia em que você adotou o veredito, não do dia em que outra pessoa o conquistou. Um primeiro download é
portanto silencioso, e essa é a ideia — um catálogo distribuído é sempre mais antigo que o intervalo
de três meses quando chega até você, então contar a partir da data original faria toda
instalação nova requalificar o catálogo inteiro no primeiro dia, que é exatamente o trabalho que o
arquivo distribuído existe para poupar.

Essa troca é deliberada e tem um custo que vale declarar: a atualidade do catálogo
distribuído deixa de ser algo que cada instalação restabelece por conta própria. Ela é
restabelecida quando uma nova versão sai com uma sobreposição recortada de novo a partir de instâncias que *fizeram*
a reverificação. A exportação abaixo informa a idade dos seus vereditos, para que essa defasagem
fique visível em vez de silenciosa.

#### Devolvendo os vereditos da sua instância

`GET /api/diagnostics/source-qualification-export` informa o que a sua instância sabe sobre
as fontes distribuídas — quantas estão qualificadas, quantas desqualificadas, quantas ainda
pendentes — e `?fmt=yaml` retorna essa mesma lista como o próprio arquivo de sobreposição.
`scripts/merge_source_qualification.py` combina exportações de várias instâncias numa só.

Se você já coletou **pacotes de todos os diagnósticos** (all-diagnostics bundles) dessas instâncias, não precisa
voltar e exportar de novo: o pacote traz essa mesma exportação como um membro, e
`--from-bundle` a lê direto do zip. Os dois caminhos são intercambiáveis e
podem ser misturados livremente numa mesma execução:

```
python scripts/merge_source_qualification.py laptop-export.json \
    --from-bundle oo-all-diagnostics-desktop.zip \
    --from-bundle oo-all-diagnostics-server.zip
```

O relatório impresso diz quantas instâncias foram mescladas e por qual caminho. Um pacote cujo
membro de exportação não foi concluído é nomeado, com o motivo que aquela instância registrou — ele
nunca é pulado em silêncio, porque uma sobreposição que você acredita apoiar-se em três instâncias e
na verdade se apoia em duas é pior que um erro.

Há duas coisas que ele deliberadamente não faz. Nunca **resolve uma divergência**: se uma
instância qualificou um domínio que outra desqualificou, isso é relatado para que uma pessoa
examine, porque escolher automaticamente um vencedor distribuiria a todas as instalações um veredito que ninguém revisou.
E nunca conta um veredito **herdado** como corroboração — importar uma cópia de segurança em
oito máquinas é uma medição vista oito vezes, não oito medições.

#### Trilha de descoberta e contagem de citações qualificadas

Clique na linha de uma fonte para **expandir sua trilha de descoberta**: **onde ela foi encontrada**
(o canal de citações, o catálogo, referências da Wikipédia, …) e, para uma
fonte descoberta por citação, o **primeiro artigo que a citou** (com link tanto para
o artigo quanto para a fonte que citou). Ao lado, uma **contagem de citações qualificadas** conta
os domínios que *esta* fonte cita, divididos em **qualificados / desqualificados /
pendentes / não registrados** — cada número é clicável e se expande na lista exata.

Isso é um **fato descritivo, nunca um veredito sobre qualquer das fontes** — citar um
domínio desqualificado não é culpa (um veículo saudável costuma linkar empresas,
plataformas ou páginas quebradas sobre as quais está apenas *noticiando*), e citar muitos domínios
qualificados também não é um aval (uma agência de notícias é citada por todos; um
centro de lavagem pode citar fontes respeitáveis de propósito). Leia isso como uma pista a
investigar, do mesmo jeito que todo outro sinal medido neste aplicativo é uma pista, não uma
pontuação.

#### Idiomas que ainda não conseguimos analisar — desativados por padrão (mantidos)

O mecanismo de palavras-chave/análise só consegue **gerenciar** idiomas para os quais existe uma *lista de palavras vazias* (stoplist)
e cuja escrita é **segmentada por espaços**. A lista oficial fica num único
módulo — [`src/analytics/managed.py`](../src/analytics/managed.py) (`MANAGED_LANGUAGES`)
— que é lido tanto pelo filtro de fontes quanto pelo relatório do mecanismo dentro do aplicativo, então o manual não
pode divergir do código. Segundo esse módulo, o conjunto gerenciado é: **en, fr, de, es, it, pt, nl,
ru, ar, hu, id, sv, da, nb, no, pl, sr, sl, el, bg, hi, bn, fa, ur, uk, ro, cs, sk, ca,
sw, az, et, tr, fi, bs, hr**. Um idioma **fora** desse conjunto ainda é *tokenizado*, mas suas
palavras funcionais (equivalentes a "o/de/e") vazam como falsas palavras-chave. **ja e th não são
segmentados** a menos que o extra opcional `[segmentation]` esteja instalado — eles não têm
espaços entre as palavras, então sem um segmentador a extração de palavras-chave fica totalmente quebrada, independentemente
de qualquer stoplist. **zh** estava na mesma situação até o jieba se tornar uma dependência central na
0.4; ele é segmentado e, portanto, gerenciado, em toda instalação.

Coletar material nesses idiomas, portanto, produz **palavras-chave lixo** que:

- **poluem a análise** — falsas palavras-chave distorcem associações, tendências e
  supergrupos, e
- **incham o corpus** — toda agregação (Análises, Grupos, o mapa mental) paga
  o custo de centenas de milhares de linhas sem sentido, o que é uma perda real de
  desempenho em corpora grandes.

Portanto, por design: **uma fonte nova num idioma não gerenciado é semeada *desativada***. Ela é
**mantida** (nunca excluída) e totalmente **reativável** — você ainda pode ler esses
veículos, e no momento em que uma stoplist para o idioma deles for adicionada, você os reativa.
É uma troca honesta: preferimos *não coletar* o que iríamos *estropiar*
a apresentar análises pouco confiáveis. Um `enabled: true` **explícito** numa importação CSV
sempre vence (sua curadoria é respeitada), e uma fonte cujo idioma é **desconhecido**
continua ativada (nunca desativamos o que não conseguimos classificar).

**Para aplicar isso a um corpus existente:** Configurações → Avançado → Fontes mostra quantas fontes ativadas
estão em idiomas não gerenciados (e quais) e oferece **"Desativar fontes em idiomas que ainda não podemos analisar"**
— uma ação em lote reversível que as desativa
(mantidas). Reative qualquer uma delas a qualquer momento pela tabela de fontes.

### 3.4 Biblioteca

*(Chamada de **Banco de dados** antes da 0.05.)*

**Para que serve:** uma visão honesta do que você realmente tem e de até onde suas
fontes alcançam.

- **Estatísticas do banco de dados (Database stats):** contagens ao vivo e animadas (artigos, fontes, domínios únicos,
  …), além do backend e do **tamanho em disco e caminho** do banco de dados. Todo
  número é uma contagem ou tamanho em bytes real — nada estimado.
- **Cobertura mundial:** quantos países seu catálogo de fontes alcança, medido
  em relação à ISO 3166 — `covered/total countries`, `coverage %`, a contagem *não* coberta
  e a contagem "fina" (abaixo do limiar). Os países são armazenados como códigos ISO-2
  em minúsculas e **exibidos pelos nomes completos** (uma única camada de conversão,
  `src/catalog/countries.py`). Um bloco **Equilíbrio regional** compara as fontes e os países cobertos
  de cada continente com os pisos de trabalho em
  `configs/catalog_targets.yml` (aspirações claramente rotuladas, esboçadas a partir do
  formato real do catálogo), além de uma **proteção contra concentração** no país principal — a métrica
  da 0.0.9 para descentralizar dos EUA. A tabela lista cada país com sua região, contagem de
  fontes e **etiquetas de palavras-chave temáticas** (a partir das tags das fontes). **Clique num país ou numa
  palavra-chave** para ir a Fontes filtradas exatamente para essas fontes. Um relatório de lacunas
  nomeia os países que ainda não têm fonte. O painel se atualiza ao vivo (sem necessidade de botão
  de atualizar); a mesma métrica está disponível offline via
  `python scripts/catalog_coverage_report.py`.

### 3.5 Mercados

**Para que serve:** acompanhar preços **reais** de commodities / moedas / energia e
relacioná-los ao volume de notícias.

- **Painel de tendências de mercado (Market trends dashboard):** um cartão por série de preços — símbolo, variação %, último
  preço (moeda/unidade), número de pontos e um minigráfico. Um controle de **intervalo de tempo**
  — campos de data De/Até, uma barra de intervalo arrastável e predefinições rápidas (1M · 6M · 1Y ·
  5Y · Tudo) — remodela todos os cartões por uma janela exata de início/fim (não uma lista fixa de
  escalas); a série completa é sempre desenhada em resolução total dentro dela, nunca
  reduzida. Clique num cartão para ver um gráfico completo e
  uma **correlação preço↔notícias** (coeficiente real de Pearson/Spearman, valor-p e
  tamanho da amostra — nunca um número chutado). Os feeds oficiais selecionados **se atualizam
  automaticamente em segundo plano** enquanto você está online (não há botão de carregar/atualizar);
  o painel também tem **subabas de categoria**, uma alternância de visualização **Cartões/Famílias**, uma
  sobreposição **Comparar** (com alternância de escala Absoluta/Indexado/Log) e um eixo de tempo compartilhado.
- **Configurar fontes de dados** (recolhível — a maioria dos usuários não vai precisar):
  - **Feeds de preços oficiais** (FRED, que traz a **"Pink Sheet" do Banco Mundial**
    e séries da **EIA**): **Importar** com um clique, além de **Gráfico**.
  - **Regras de extração de preços (Price-extraction rules):** adicione uma regra (Fonte, Símbolo, Rótulo, URL da página, **seletor
    CSS**, atributo/regex opcional, moeda, unidade, mercado). A regra de ouro:
    **um número só é armazenado onde o seu seletor realmente encontra um — nunca
    chutado.** Use **Testar** para buscar a página uma vez e ver o valor exato encontrado, ou
    o motivo exato pelo qual não correspondeu, antes de confiar nela.
  - **Feed personalizado (qualquer URL CSV):** aponte para qualquer CSV (o mapeamento padrão é coluna 1 =
    data, coluna 2 = valor, a convenção do FRED); valores ausentes são ignorados, nunca
    armazenados como zero.

Veja [`docs/USER_MANUAL.md`](USER_MANUAL.md) para a referência completa das regras de extração.

### 3.5a Índices

**Para que serve:** **índices** de bolsas de valores do mundo (S&P 500, NASDAQ, Dow Jones,
VIX, Nikkei 225 …) — mantidos **separados de Matérias-primas**, porque um índice é um
índice, não uma commodity.

- Um painel de séries de índices com os mesmos gráficos detalhados e em resolução total de
  Matérias-primas (subabas de categoria, filtro por tag, sobreposição Comparar, visualização Famílias, um eixo
  de tempo compartilhado). Os feeds oficiais selecionados (FRED, Stooq) **se atualizam automaticamente em
  segundo plano** enquanto você está online — não há botão de importar/atualizar.
- Cada feed traz um **veredito honesto por feed** quando não pode ser buscado —
  *recusado* ≠ *proibido pelo robots* ≠ *série extinta* ≠ *inacessível* ≠ *offline* — então
  um feed bloqueado degrada de forma visível em vez de mostrar um número falso. Via Tor alguns
  feeds são bloqueados pelo host; o veredito diz exatamente isso (veja §5.5).

### 3.6 Análises

**Para que serve:** análise de palavras-chave e entidades sobre o **texto dos artigos
ingeridos**. *(Requer o extra `[analysis]`; o reconhecimento real de entidades nomeadas é
opcional, via o extra `[nlp]` do spaCy.)*

- **Status e indexação:** uma etiqueta mostra `indexed/total articles · keywords (entities)
  · mentions · remaining`. **A indexação é automática** — ela acompanha a ingestão, e quando você
  abre Análises uma complementação silenciosa em segundo plano limpa qualquer pendência restante (a contagem
  "remaining" desce até 0 sozinha). **Não há botão "Index corpus"** — ele foi
  removido em favor da indexação automática. Pessoas, organizações e lugares são mantidos como
  unidades únicas; a indexação pode ser retomada e a barra se atualiza ao vivo. *(Desative a indexação
  automática com `OO_NO_INDEX=1`.)*
- Oito subabas:
  - **Explorar** — digite uma palavra-chave ou entidade (ex.: *inflação*, *Emmanuel Macron*,
    *Rio Tinto*) para obter: uma linha de **tendência** ao longo do tempo; um **mapa mental de associações**
    (termos coocorrentes ordenados por PMI — largura da aresta = coocorrência, distância =
    força; clique num nó para recentralizar); uma tabela de **enquadramento** (como o tom de cada veículo
    difere, via VADER, com os termos que ele enfatiza); e trechos **em contexto**
    com links de fonte/lugar/data.
  - **Tendências** — **Em alta** (palavras-chave que crescem mais rápido, janela recente vs. janela de referência) e
    **Top** (mais mencionadas), além de três janelas predefinidas (24h · semana · mês) lado a
    lado, filtráveis por tipo (termos/entidades/pessoas/organizações/lugares) e país. Clique em qualquer
    termo para explorá-lo; clique em ✕ para excluí-lo.
  - **Fontes** — fontes em alta em todo o seu corpus.
  - **Famílias** — famílias de palavras-chave (variantes morfológicas agrupadas).
  - **Grupos** — supergrupos (conceitos-guarda-chuva duradouros) e **anéis** multilíngues
    (um conceito e suas traduções/sinônimos), editáveis.
  - **Mapa** — o mapa coroplético ooMap sobre o seu corpus (o mesmo componente da aba
    Mapa-múndi).
  - **Convergência** — coocorrência espaço-temporal somente leitura: artigos que convergem para o mesmo
    **lugar** dentro de uma janela de tempo na data do evento mencionado. A independência é medida
    por **fontes distintas** (uma única fonte prolixa não consegue fabricar uma); todo agrupamento
    traz o aviso "coocorrência, nunca causalidade — um convite à leitura, não uma prova".
  - **Monitoramentos** — suas condições salvas do tipo "se isto, então vigiar": uma consulta FTS local + um
    limiar + uma janela. Quando o corpus ganha artigos novos correspondentes suficientes, uma **pista de
    monitoramento** (watch Lead) aparece no Início. Somente local, sem notificações, sem rede, sem telemetria;
    criar / ativar / editar / excluir, com um histórico de correspondências.

Todo número é um agregado real com seu tamanho de amostra e um aviso. Veja
[`docs/USER_MANUAL.md`](USER_MANUAL.md). Para ajustar quais palavras-chave aparecem, use o
[filtro de palavras-chave em Configurações](#39-configurações).

### 3.6a Mapa-múndi

**Para que serve:** ver *onde* o seu corpus vive — um **mapa coroplético** ("Cobertura
mundial") que sombreia cada país por uma dimensão medida dos seus dados, com camadas opcionais
de lugares, sinais e localização de servidores. Ele é construído sobre um componente de mapa reutilizável
(**ooMap**), e todos os controles ficam **dentro do mapa** (a convenção do Google Maps):
zoom ＋/－, zoom pela roda do mouse, arrastar para mover, ⛶ ampliar, e os seletores de camada/medida.

- **A medida do coroplético (seletor no mapa):** troque o que colore os países entre
  **Fontes · Artigos · Menções de palavras-chave · Tom médio**. As contagens usam uma escala sequencial;
  **Tom médio** usa uma escala **divergente** (positivo ↔ negativo em torno de zero) e traz
  o aviso **VADER somente em inglês** mais o `n` de artigos pontuados — um país sem nenhum
  artigo em inglês pontuado mostra "sem dados", nunca um neutro fabricado.
- **Sem dados honesto ≠ zero:** um país sem dados localizados aparece com um **padrão hachurado**
  rotulado "sem dados", visualmente distinto de um zero real. Territórios pequenos que o contorno
  grosseiro não consegue desenhar aparecem como **pontos**; fontes sem país são **contadas, mas
  nunca posicionadas** ("N not mapped").
- **Granularidade (alternância no mapa):** veja por **País** ou agregue por **Continente**
  (uma soma para contagens, uma média ponderada por `n` para o tom — nunca uma média de médias; um continente
  desconhecido é honestamente "sem dados").
- **Sobreposição de lugares:** ative **Lugares** para traçar os locais *de que* seus artigos *falam*
  (a partir do Quando/Onde/Quem extraído na ingestão, numa coordenada de gazetteer) como
  marcadores vazados dimensionados pela dispersão de artigos — com o aviso **"Deduzido do texto, nunca
  confirmado."**.
- **Camada de sinais + momento em foco:** ative **Sinais** para traçar eventos espaço-temporais
  datáveis (âncoras selecionadas, artigos do corpus, datas extraídas) como pontos coloridos por tipo; um
  **controle deslizante de momento em foco** percorre o tempo (confirmado = preenchido, futuro/não confirmado = um
  anel tracejado, esmaecendo com a distância no tempo). Clique num marcador para um painel de detalhes — data,
  lugar, fonte, link oficial, **"Encontrar cobertura no seu corpus"**, e uma lista **"Próximo no
  espaço e tempo"** que deixa explícito que a coocorrência *"não é uma conexão nem uma
  causa. Você julga."*
- **Camada de IPs de servidores:** opcionalmente mostre as **localizações dos servidores** das
  fontes, geolocalizadas offline — com o aviso honesto de que isso é um nó de borda de CDN / host anycast, **não** uma prova
  da verdadeira origem do editor (e indisponível via Tor, onde o socket é o
  proxy, não o servidor).
- **Litorais e fronteiras vêm incluídos:** a geometria de países/litorais acompanha o aplicativo
  (Natural Earth, simplificada) — nada a construir, nenhuma fronteira inventada.

As datas *de que* uma matéria trata também viram **tags de data por artigo**: abra o leitor offline
de um artigo para vê-las listadas, **confirmar ou rejeitar** cada candidata, ou **extrair** sob demanda;
o corpus pode então ser filtrado por uma data mencionada (`GET /api/article-dates/by-date`).
O extrator é de alta precisão: anos soltos e períodos vagos não são extraídos, mas
**palavras relativas ancoradas** ("ontem") e **dias da semana soltos** são.

### 3.6b Agenda

**Para que serve:** um calendário de eventos datados — o que está por vir, com fontes e de forma honesta.

- Uma **grade mensal** (começando na segunda-feira; nomes de meses/dias no idioma da sua interface) é a
  visualização padrão, com as visualizações **Semana · Trimestre · Semestre · Ano · Década · Lista**
  ao lado (uma barra de navegação compartilhada). Os dias com eventos ficam marcados; clique num dia para ver os
  detalhes, e clique no título de um evento para abri-lo no corpus.
- **Eventos deduzidos (dos seus artigos):** datas futuras *mencionadas* em vários
  artigos aparecem como uma camada **deduzido** distinta e filtrável — cada entrada mostra uma
  etiqueta "deduzido · nunca confirmado" e as contagens de artigos/fontes, e seu título abre
  o conjunto exato de artigos. Somente contagens, nunca um veredito.
- **Astronomia, calculada localmente:** as quatro fases principais da Lua (nova, quarto crescente, cheia, quarto minguante) e os equinócios/solstícios são
  calculados nesta máquina (algoritmos de Meeus, verificados contra valores publicados
  em almanaques); cada entrada informa seu **método e precisão** no balão de dica.
  As estações são nomeadas **de forma honesta quanto ao hemisfério** — nunca um "verão" sem mais.
- **Contexto climático:** um conjunto de dados incluído de episódios de El Niño / La Niña (convenção ONI do
  NOAA CPC); qualquer entrada que ainda aguarde uma verificação cruzada via clearnet traz uma
  marca de verificação pendente.
- **Datas móveis são marcadas como tal** — o aplicativo nunca inventa um dia exato para um
  evento cuja data muda a cada ano.
- **Calendários** (fontes iCal de feriados / religiosas / astronômicas) são assinados em
  **Configurações → Agenda**, não aqui — a aba mostra os dados, a infraestrutura fica em
  Configurações. Depois disso eles se mantêm atualizados sozinhos: enquanto a coleta está ativa, novos eventos são
  importados e cada feed é reverificado por vez, alguns por passagem. Um feed que falha é
  reverificado após 1 mês, depois 2, 4 e 6 — **com teto, então um feed nunca é descartado
  para sempre** — e o balanço por passagem fica visível na **aba Agendamento do gerenciador
  de tarefas**. Nada disso roda na inicialização nem offline. O **catálogo** de ~500 feeds em si
  (vereditos, pastas de provedores duplicados, adicionar seu próprio `.ics`) é infraestrutura e
  fica em **Configurações → Avançado → Diretório de calendários**.
- **Se o arquivo de eventos importados estiver danificado a ponto de nada nele poder ser lido** (cortado,
  JSON inválido ou um erro de leitura do disco no Linux ou macOS), a Agenda o lê como vazio e o log
  informa isso. Antes que o próximo salvamento o substitua (uma importação, uma restauração, a remoção de um feed), o aplicativo guarda o arquivo danificado uma vez,
  sem alterações, como `calendar_feed_imports.json.damaged` na sua pasta de dados, para você ou para uma
  ferramenta de recuperação; um segundo dano nunca sobrescreve essa primeira cópia. Ela não faz parte de uma
  cópia de segurança. Você pode removê-la quando quiser. Um arquivo com apenas algumas entradas danificadas
  ainda é lido: essas entradas ficam de fora, o log as conta e nenhuma cópia é feita. Um
  arquivo vazio também não é copiado: não contém nada a recuperar.

### 3.6b Fontes vivas

A aba **Fontes vivas** mostra o que mudou nas fontes que continuam mudando
depois que você as coleta: Wikipédia, direito e mapas, uma subaba para cada. Tudo nela
é lido desta máquina; nada é buscado para desenhá-la.

- **Wikipédia:** quantas páginas o fluxo ao vivo acompanha, quantas mudanças ele
  relatou nos últimos 30 dias e **para quantas armazenou o texto** ("2 de 4":
  sob um orçamento, ele armazena algumas e conta o resto), o ponto até o qual todo
  feed foi lido sem interrupção, e quaisquer lacunas que ele sabe que perdeu. Abaixo disso, cada
  mudança, da mais recente para a mais antiga; **Mostrar diff** abre o diff armazenado quando a mudança chegou.
  Uma mudança que foi apenas contada diz isso e não tem diff. As páginas que você acompanha
  manualmente (Configurações → Wikipédia) também são listadas: escolha uma para ler as revisões
  acompanhadas. Cada versão em qualquer ponta da comparação tem seu próprio **Adicionar ao
  corpus**: ele adiciona aquela versão exata como um artigo próprio, datado de quando a wiki a
  criou, e avisa quando o seu corpus já contém essa versão ou as mesmas palavras. Uma versão
  cujo texto não foi armazenado não pode ser adicionada, e o botão dela diz por quê. É assim que uma
  revisão armazenada por **Acompanhar agora** chega ao seu corpus, já que a busca ainda não as
  lê. Quando o **percurso de páginas** (page walk) está ligado (abaixo), um grupo *Percurso de páginas* diz o que ele
  está fazendo (percorrendo; pausado, e por quê; ou esperando passar uma recusa da wiki) e,
  por edição, as páginas que ele listou **em relação à própria contagem de artigos da edição**
  ("1 234 000 de 2 700 000"). São duas contagens, nunca uma porcentagem: cada edição
  conta seus artigos à sua maneira, então o primeiro número pode ultrapassar o segundo. Quando
  a busca das **outras páginas alteradas** está ligada (abaixo), um grupo *Outras páginas alteradas*
  (acima do grupo do percurso) conta as páginas que têm um texto, as páginas alteradas que ainda esperam
  pelo seu, os textos buscados e as páginas que desde então passaram a ser páginas que o fluxo
  acompanha, também por edição, e diz quando para: numa parcela declarada do orçamento de
  armazenamento, um padrão proposto que o aplicativo mostra, e não uma decisão.
- **Direito:** os documentos que o rastreador de leis acompanha, a verificação mais recente e a mais antiga, e
  cada mudança real (uma reverificação que não mudou nada não é contada) com seu
  diff armazenado e um link para a sua cópia local.
- **Mapas:** suas regiões de mapa baixadas, quais estão pausadas ou falharam e por quê, e
  o espaço que ocupam.

A atualidade é mostrada como datas, nunca julgada: o quão recente é recente o bastante depende da
matéria. Os orçamentos são mostrados, mas definidos em **Configurações → Dados e cópia de segurança**.

### 3.6c Clima

**Para que serve:** ler seis registros publicados de clima e da Terra ao lado do seu corpus,
cada um exatamente como o editor o publicou. A aba tem uma subaba por conjunto de dados:

- **Temperatura** — NASA GISTEMP v4: *anomalias* de temperatura global mensais e anuais
  (diferenças em relação à média de 1951-1980, em °C, não temperaturas).
- **Gelo marinho** — NSIDC Sea Ice Index v3: a extensão diária do gelo marinho do Ártico ou da Antártida, em
  milhões de km².
- **El Niño** — o Oceanic Niño Index da NOAA: a anomalia trimestral da temperatura da superfície do mar
  na região Niño 3.4 do Pacífico.
- **Sismos** — o catálogo do USGS: terremotos de magnitude 6,0 ou mais no mundo todo,
  contados por mês desde janeiro de 1973, com a maior magnitude de cada mês.
- **Emissões e energia** — Our World in Data: números anuais de emissões e energia por
  país e região, cada coluna mantendo os termos do seu produtor original.
- **Estação meteorológica** — NOAA GHCN-Daily: temperatura, precipitação e neve diárias em
  **uma** estação, escolhida pelo seu id de 11 caracteres (por exemplo `USW00094728`, Central Park
  em Nova York). Uma estação descreve um lugar, não uma região nem o clima.

**Como busca os dados.** Nada é baixado até você pedir. Cada subaba tem seu próprio botão
**Obter do editor** (ele passa a dizer **Atualizar a partir do editor** depois que algo
está armazenado; em **Estação meteorológica** você digita um id de estação e pressiona **Obter estação**, depois
**Atualizar esta estação**), que nomeia o servidor que contata. Ele passa pelo mesmo popup de consentimento de toda
outra ação de rede e é recusado enquanto o modo avião estiver ligado. A busca roda em
segundo plano; o gerenciador de tarefas a mostra. Ler o que já está armazenado não faz nenhuma chamada
de rede.

**Com o que você pode contar.** Cada subaba nomeia sua fonte, sua licença, seu método e quando
esta máquina a buscou pela última vez. Uma nova busca armazena apenas valores novos ou que o
editor revisou: os valores anteriores continuam legíveis, e os períodos que o editor deixou de servir
são contados, nunca excluídos. Uma célula vazia é uma lacuna publicada, nunca um zero. Nada aqui é
uma previsão, uma pontuação ou uma classificação de risco.

### 3.6d Observatório

**Para que serve:** ver todo o seu corpus de uma vez, desenhado como um céu noturno. Cada
**galáxia** é um grupo de palavras-chave relacionadas; cada fatia do círculo é um de doze
domínios temáticos.

- O **ângulo** carrega apenas o domínio. A posição de uma galáxia dentro da sua fatia é um hash
  estável, então ela fica no mesmo lugar entre visitas e não significa nada por si só.
- A **distância ao centro** carrega a única medida que você escolher, com anéis rotulados.
  O **tamanho da estrela** é desenhado como área (menções) e é uma pista secundária.
- A **cor** mostra o idioma, ou a lente **Tendência**; ela nunca é o único sinal.
  As linhas de constelação ligam galáxias que compartilham uma palavra-chave membro, nunca galáxias que
  apenas parecem próximas.
- A **tabela ordenada** abaixo do céu lista todas as galáxias por completo, inclusive as que o
  céu não consegue posicionar. A tabela é a visão canônica; o céu é uma segunda maneira de lê-la.
  Uma linha acima dela conta o que a imagem deixa de fora (galáxias ainda não observadas e
  palavras-chave fora de qualquer galáxia).
- O mesmo corpus sempre desenha o mesmo céu, então uma mudança que você vê é uma mudança nos seus
  dados. Não há pontuação composta.

### 3.7 Wikipédia *(em Configurações → Wikipédia)*

> **Onde fica agora.** O acompanhamento de mudanças da Wikipédia e as ferramentas de dumps offline foram
> transferidos para **Configurações → Wikipédia** (o conteúdo em primeiro lugar); as páginas vigiadas continuam aparecendo na
> pesquisa geral e na análise como qualquer artigo. Os controles não mudaram.

**Para que serve:** vigiar páginas específicas da Wikipédia e **sinalizar edições
suspeitas** — os dados são as *edições*, não uma cópia do artigo.

- Adicione uma página para vigiar indicando a **Edição** (código de idioma, p. ex. `en`, `fr`, `ar`),
  o **Título do artigo (Article title)** e, opcionalmente, um rótulo de **Lista de vigiados**. O aplicativo guarda **um
  instantâneo de referência** e depois apenas as **diferenças/deltas** de cada nova edição — assim, mudanças
  cosméticas quase não custam nada.
- **Acompanhar agora** (opcionalmente **usando pontuações ORES** (using ORES scores)) busca as novas revisões e sinaliza
  as grandes ou suspeitas: grandes variações de tamanho, marcas de reversão/apagamento, edições anônimas,
  rajadas de edições e — se ativado — as pontuações de aprendizado de máquina ORES de dano/boa-fé. Os candidatos
  são *apresentados para que você os julgue*; nada é rotulado como "desinformação".
- **Mudanças sinalizadas** lista as edições (Quando · Edição · Página · Editor · Δ bytes ·
  Motivos · ORES), com um visualizador de **Diferenças** e um link **ao vivo** (live) para a Wikipédia.
  Filtre por *apenas sinalizadas* e por edição.

**As páginas vigiadas são artigos do corpus (as escolhas da fonte viva, declaradas):**
toda página que você vigia também entra no seu corpus como um artigo sob uma fonte
por edição ("Wikipedia (en)"), de modo que aparece na **pesquisa geral, nas palavras-chave e
no Quando×Onde×Quem como qualquer outro artigo**. As escolhas que o aplicativo faz por você,
de forma visível: (1) o que a pesquisa e as análises veem é sempre a **versão mais recente**
que o rastreador obteve, e o id exato da revisão a que ela corresponde fica
registrado; (2) o **texto completo de cada revisão acompanhada é guardado nesta
máquina** — as versões anteriores continuam exatamente reconstituíveis (análises ancoradas
na versão, sem reaplicar diffs), ao custo honesto de um armazenamento que cresce com a
atividade de edição; (3) o texto analisado é wikitexto reduzido a texto simples — nunca
apresentado como se fosse o artigo renderizado. Tudo fica local; o histórico de
mudanças continua disponível por página, e a aba **Fontes vivas** o mostra
([3.6b](#36b-fontes-vivas)).

**O orçamento de armazenamento da via (150 GB por padrão, você pode reduzi-lo):** a via da Wikipédia
para de guardar texto ao atingir o total que você definiu no assistente da primeira execução (ou em **Configurações →
Armazenamento**, ao lado do cálculo em relação ao espaço livre em disco desta máquina). O padrão é
**150 GB** desde a decisão de 2026-09-29, antes 20 GB; reduza-o para 20 GB, ou para qualquer valor
até 1 GB, se o disco for pequeno. Uma instalação que já passou pelo assistente
mantém o número que aceitou; uma que nunca viu o assistente segue o novo padrão
até você definir o seu.

**O percurso de páginas (desligado até você ligá-lo):** o fluxo ao vivo só fica sabendo
das páginas que alguém edita, de modo que a maior parte de uma enciclopédia nunca chega até ele. Marcar
**Percorrer também todos os títulos de artigos.** (Configurações → Wikipédia, em *O fluxo de edição
ao vivo*) lista todos os artigos das edições que você escolheu, 50 títulos por requisição, uma
requisição de cada vez, entre as leituras do próprio fluxo, durante vários dias. Ele guarda de cada
página o título, o tamanho, a revisão mais recente e o id do Wikidata, nunca o seu texto, dentro do mesmo
orçamento de armazenamento, e nunca a transforma em uma página que o fluxo acompanha por inteiro. Ele
só funciona enquanto o fluxo ao vivo está em execução, pela mesma conexão: o modo avião, ou o
modo protegido sem um proxy utilizável, o fazem **esperar** (ele nunca se conecta diretamente), e uma
wiki que pede para ir mais devagar é consultada de novo após uma pausa que dobra até uma
hora. Uma reinicialização retoma cada edição de onde parou. O seu progresso aparece em **Fontes
vivas** e no gerenciador de tarefas.

**Por que o percurso pode esperar atrás da primeira descarga do fluxo.** O fluxo guarda o que ouviu em
uma descarga a cada 30 segundos; o índice de pesquisa, a obtenção de outras páginas alteradas e o percurso funcionam
no tempo *após* cada descarga. Uma descarga obtém o texto das páginas acompanhadas que mudaram,
e diante de um acúmulo (um fluxo retomado horas atrás) isso significa milhares de requisições educadas, por isso a
descarga agora tem um **limite de 20 segundos para obter textos**, repartido entre as edições
(a primeira edição muda a cada descarga). Toda mudança continua sendo registrada; um texto não alcançado a
tempo é contado como *adiado* e **uma descarga posterior o obtém**: primeiro as páginas nunca guardadas, depois
as que estão há mais tempo sem verificação (até 200 páginas por edição por descarga; `text_backlog` no relatório da
descarga diz quantas a recuperação *encontrou* esperando, o que não é o mesmo que obtidas). Essas páginas
são tentadas antes das mudanças mais recentes da edição, dentro da sua parcela de tempo. Uma página que falhou ou foi
recusada fica de fora da recuperação por 5 minutos, para que uma que o serviço continua recusando não seja
pedida a cada 30 segundos. O cliente
faz uma requisição por segundo, então uma descarga obtém cerca de vinte textos: diante de milhares de textos
adiados, a recuperação leva horas, não uma descarga. O limite define quando uma obtenção pode *começar*: uma
já em andamento termina primeiro (cada conexão ou leitura espera até 30 segundos), então uma descarga pode
passar um pouco dos 20 segundos. Enquanto o percurso de páginas está ligado, ele fica com 30% do tempo ocioso, de modo que a obtenção de outras páginas alteradas
não pode usar todo ele. O status (`/api/scheduler/status`, o bloco `wiki_lane.service.drain`)
diz onde está a descarga: a etapa (`hot-sets` ou `feeds`), a edição, há quanto tempo ela
está nesta descarga e quantas descargas falharam seguidas e por quê.

**Como ler o W na barra superior.** O W é o interruptor do **fluxo**, não do percurso: o
percurso é a caixa de seleção acima, e só funciona enquanto o fluxo funciona. A pequena marca no
canto do W diz pela forma o que o fluxo está fazendo: um ponto cheio é conectado e recebendo;
um anel é *escolhido, mas não conectado* (o modo avião o retém, ou ele ainda não começou nesta
sessão); um anel com um ponto é conectando e falhando, tentando de novo por conta própria; um traço é pausado;
uma cruz é parado. Passe o mouse sobre ele para ver em palavras, inclusive se o percurso de páginas está ligado. Um clique
em um anel **inicia** o fluxo (você confirma uma vez a ida para online); um clique em um ponto ou em um anel
com ponto o **pausa**; Shift+clique o para. Configurações → Wikipédia mostra as mesmas duas linhas
em palavras acima das edições. Ambos se atualizam quando você fica online ou offline, e quando você marca
ou desmarca o percurso.

**As outras páginas alteradas (desligado até você ligá-lo):** o fluxo ao vivo guarda
o texto das páginas que acompanha e apenas conta as mudanças que relata em todas as
outras páginas. Marcar **Obter também o texto de outras páginas alteradas.** (Configurações →
Wikipédia, ao lado da caixa do percurso) obtém também o texto mais recente dessas outras páginas,
50 páginas por requisição, primeiro a página que esperou mais tempo. Uma página editada dez vezes
enquanto esperava custa uma obtenção, do estado em que está agora. O aplicativo guarda de cada página o texto
**mais recente e o anterior**, e uma página apagada depois mantém o texto que tinha. Esses
textos **ficam no arquivo próprio da via, não no seu corpus**; a caixa de pesquisa os encontra
(veja *Pesquisar o que a via guarda*, abaixo). Eles param quando o arquivo da via ocupa **90% do seu orçamento de armazenamento**, para que o
restante fique para as páginas que o fluxo acompanha; essa parcela é um padrão proposto, não uma
decisão, e Fontes vivas a mostra. Isso só funciona enquanto o fluxo ao vivo está em execução, pela
mesma conexão e com as mesmas esperas do percurso: o modo avião, ou o modo protegido
sem um proxy utilizável, o fazem esperar (ele nunca se conecta diretamente), e uma wiki que pede
para ir mais devagar é consultada de novo após uma pausa que dobra até uma hora.

**Uma falha ou uma atualização não faz perder a execução.** Tudo o que a via guarda é gravado em
pequenas etapas de tudo-ou-nada, de modo que uma falha (ou encerrar o aplicativo à força) perde no máximo a etapa em andamento; o
percurso retoma a partir do seu marcador e o fluxo a partir da última posição que guardou. O que de fato
para é a própria via: o aplicativo sempre começa **offline**, então, após uma reinicialização, nada é
obtido até você ficar online de novo com o botão do avião, que retoma a execução se ela estava ligada e a deixa desligada se estava desligada (o Início mostra uma linha enquanto a execução espera). Nada se perde durante a espera
(o histórico do próprio fluxo alcança cerca de uma semana para trás). Fontes vivas → Wikipédia → Fluxo
ao vivo mostra **Funcionamento até agora** (as horas em que esta instalação guardou ou pediu algo,
contadas através das reinicializações, com o número de paradas) e, quando a via fica silenciosa, uma
linha **Parado** com há quanto tempo e desde quando. Os mesmos números aparecem no relatório da
janela de teste prolongado como `wiki_lane.run`. Uma parada diz que a via não deu sinal de vida por três ou mais
horas, não o motivo: uma falha, uma atualização, o modo avião e um aplicativo fechado parecem iguais.

**Pesquisar o que a via guarda:** a via mantém um índice de pesquisa dos textos que
guarda, no mesmo arquivo e dentro do mesmo orçamento de armazenamento. O texto **mais recente** de uma página
alterada é indexado por inteiro, título incluído. Toda **versão mais antiga** (o texto anterior
de uma página alterada, e cada versão de uma página que o fluxo acompanha, exceto
a mais recente, que já é o seu artigo do corpus) é indexada pelas **linhas que uma edição
posterior removeu**: o restante dela está na versão mais nova, onde já é encontrado.
Assim, uma pesquisa cujas palavras estão em parte em linhas mantidas e em parte em linhas removidas não encontra
nenhuma das versões, e toda lista desses resultados diz isso. O índice é construído enquanto o
fluxo ao vivo está em execução, antes das obtenções e por no máximo metade do tempo ocioso delas, e
uma pesquisa diz quantos textos ainda esperam por ele; um texto que não pode ser lido
é posto de lado e tentado de novo na próxima vez que a via iniciar. Chinês, japonês e
árabe são segmentados e normalizados exatamente como no índice do seu próprio corpus, e as palavras em hindi e
bengali ficam inteiras. Na caixa de pesquisa (Ctrl/⌘-K) esses resultados aparecem sob
**Textos da Wikipédia guardados nesta máquina**, ao lado dos resultados do seu corpus e nunca classificados
junto com eles, cada um indicando a sua edição, que texto é (o texto mais recente ou
anterior de uma página alterada, ou uma versão anterior de uma página que o fluxo acompanha) e a sua data.
Abrir um deles mostra o texto dessa versão, onde ele está guardado e o seu endereço completo na
Wikipédia; **Adicionar ao corpus** adiciona exatamente essa versão como um artigo próprio, datado de quando
a wiki a criou, e avisa quando o seu corpus já a contém ou contém as mesmas palavras,
em vez de guardá-las duas vezes. Nada da via chega ao seu corpus de outra forma.
A página **Explorar** lista os mesmos resultados em uma seção própria abaixo dos resultados do seu
corpus, cada um com o trecho que correspondeu e o seu próprio botão **Adicionar ao corpus**.
Acima deles, ela diz o que foi pesquisado: apenas os textos que a via da Wikipédia
guarda nesta máquina, nunca a própria Wikipédia, com as páginas e edições de onde eles
vêm, quantos textos ainda esperam pelo índice e se a obtenção de outras
páginas alteradas está desligada. Assim, uma lista vazia significa que os textos da via não contêm as suas
palavras, não que a Wikipédia não as contenha. As versões que **Acompanhar agora** (Configurações → Wikipédia)
guarda para as páginas vigiadas também estão nesta pesquisa: elas ficam no banco de dados do seu corpus,
e o índice da via, no seu próprio arquivo, as lê da mesma maneira (cada versão mais antiga pelas
linhas que a versão guardada seguinte removeu, a mais recente por inteiro, a menos que o artigo do seu corpus
já seja essa versão). Elas aparecem sob o mesmo título, marcadas como
guardadas pelo rastreador de páginas, e **Adicionar ao corpus** adiciona exatamente essa versão como qualquer
outra; a pesquisa diz quantas páginas acompanhadas leu. Uma página que você ao mesmo tempo segue e acompanha pode
listar uma versão uma vez para cada armazenamento: os dois armazenamentos são lidos separadamente, e nenhum depende do
outro. Os dumps baixados não estão nesta pesquisa: o texto deles
é encontrado no grupo Wikipédia da caixa de pesquisa. Uma consulta é lida da mesma maneira nas duas listas (`salt*`,
`NEAR(salt works, 5)`, `title:salt`), mas os filtros que descrevem artigos (as caixas
Fonte, Idioma e Hora, e `source:`, `author:`, `url:`, `tag:` e
`title:=`) não alcançam esses textos, e a seção diz isso sempre que um deles está definido.
As exportações, a janela de análise e as ações em massa funcionam sobre o seu corpus; um texto da Wikipédia
passa a fazer parte delas quando você o adiciona.

**Um item através das edições, e as páginas mais vistas** (Fontes vivas → Wikipédia, na
parte de baixo). Duas visualizações que só leem o que esta máquina já guarda; nenhuma delas faz obtenções.
*Um item através das edições*: digite um item do Wikidata (Q42) ou clique em uma das sugestões (os
itens cujas páginas tiveram mais mudanças registradas pelo fluxo nesta semana) e uma tabela mostra, para
cada edição que você segue, a página dessa edição, o seu **tamanho em bytes de wikitexto** (lido uma vez,
quando o percurso de páginas chegou à página), quando foi lido, e as **mudanças que esta máquina
registrou nos últimos sete dias**. Uma edição sem página diz por quê: o percurso não foi executado
para ela, não a terminou (e até onde chegou, então o item pode estar lá), ou a terminou
e não encontrou nenhuma. A contagem de mudanças é o que o fluxo ao vivo registrou nesta máquina; para uma edição na qual ele
não registrou nada, ela mostra "desconhecido", porque isso não é o mesmo que zero. A barra ao lado de um tamanho é esse tamanho dividido pelo maior que está na tela,
a partir de zero; nada mais é calculado, e as edições são artigos separados, não
traduções. O percurso de páginas fica desligado até você ligá-lo (Configurações → Wikipédia), então em uma
instância que não fez o percurso ainda não há nada para comparar e a tabela diz isso.
*Páginas mais vistas ao lado do seu corpus*: a lista da própria fonte com as páginas mais vistas do seu
dia mais recente (posição e número de visualizações tal como ela os forneceu; as primeiras cinquenta linhas são mantidas), cada uma ao lado
do número de artigos do **seu corpus** que mencionam o título como frase, publicados naquele
dia UTC e nos sete dias que terminam nele. É **um dia, não uma série**: a lista é
sobrescrita todos os dias e nenhum histórico de visualizações por página é mantido. As contagens são do seu corpus,
que é o que esta máquina coletou, não a imprensa; um título pode ser ambíguo ou escrito
de outra forma em outro idioma; artigos vindos da Wikipédia e artigos em quarentena não são contados;
uma linha que a contagem não alcançou dentro do seu limite de tempo, ou cujo título não tem palavras que o índice de pesquisa consiga encontrar (um "-" sozinho), mostra "não contado", com o motivo ao passar o mouse; as sugestões leem apenas as 400 páginas mais alteradas da semana. Os dois números ficam lado
a lado e nunca são combinados.

As pesadas **bases de texto completo offline** (dumps de edições inteiras) são *separadas* e ficam
em **Configurações → Wikipédia** — você não precisa delas para acompanhar mudanças. Veja
[`docs/USER_MANUAL.md`](USER_MANUAL.md).

**Ler um dump baixado (offline):** os novos downloads de dumps usam o
formato *multistream*, e o pequeno índice que os acompanha é baixado junto — esse
par torna o dump pesquisável por posição. Em **Configurações → Wikipédia → Ler uma página de um
dump transferido**, escolha uma edição pronta, digite o título de uma página, e o aplicativo percorre
o índice, descompacta um pequeno bloco na posição em bytes indicada e mostra o
**wikitexto bruto** da página — inteiramente nesta máquina, com as estatísticas da varredura exibidas.
O que você lê é um *instantâneo na data do dump*, não o artigo ao vivo; uma
correspondência de título sem distinção entre maiúsculas e minúsculas é oferecida e identificada como tal. Arquivos antigos de fluxo único
não permitem acesso aleatório — o aplicativo diz isso e sugere baixar de novo.
A **lista de idiomas dos dumps se limita aos idiomas do aplicativo** (os 12 idiomas da
interface mais os idiomas de corpus que os analisadores suportam); o seletor de edição
das páginas vigiadas acima mantém a lista completa.

### 3.7a Governos

**Para que serve:** a aba **Governos** da barra lateral (a âncora no código continua sendo `law`, o
rótulo é "Governos") reúne dados oficiais por país e acompanha como o **direito**
muda. Ela tem seis subabas:

- **Países** — **estatísticas oficiais** por país do Banco Mundial (PIB,
  população, expectativa de vida, trabalho, finanças públicas + índices comuns). **Carregar dados padrão
  por país** os obtém (online, sujeito a consentimento). Cada valor é um número publicado por um produtor,
  **nunca uma pontuação de credibilidade**; um **valor ausente é uma lacuna publicada,
  não zero**; os produtores são mostrados, **nunca é feita uma média entre eles**. Cada número traz a sua unidade, e
  a dica de cada indicador explica o que ele mede — dois que parecem erros e não são:
  as assinaturas de celular podem passar de 100 por 100 pessoas (as pessoas têm vários chips) e a
  taxa bruta de matrícula escolar pode passar de 100% (ela conta repetentes e alunos acima da idade).
- **Comparar** — dois países lado a lado, cada indicador como uma linha alinhada. Isto é uma
  **exibição**, não um cálculo: mostra o número publicado mais recente de cada país e
  o ano a que ele pertence, e onde um país não tem número a célula aparece como uma **lacuna**.
  Nunca subtrai, classifica nem pontua o par — a comparação cabe a você.
- **Grupos** — agregados e blocos, em duas **lentes** entre as quais você alterna:
  - *Publicado* mostra os agregados que o próprio produtor publica (os "Renda alta",
    "África Subsaariana", "União Europeia" do Banco Mundial e assim por diante). Uma lista curta selecionada
    abre primeiro; **Mostrar tudo** expande para o conjunto completo. Esses são os números do próprio
    produtor, não os nossos. **As regiões do Banco Mundial não são continentes** — a "África Subsaariana"
    exclui Egito, Líbia, Tunísia, Argélia e Marrocos, que ficam na sua região Oriente Médio e
    Norte da África, então esta lente **não tem nenhum número para a África continental** e diz
    isso em vez de montar um que pareceria oficial.
  - *Calculado* (Computed) agrega nós mesmos os países membros, e mostra **várias estratégias lado
    a lado** (média ponderada pela população, média simples, ponderada pelo PIB, mediana e um total
    quando ele tem sentido) para que você veja o quanto a resposta depende do método,
    em vez de receber um único número. Nada é classificado e nenhuma estratégia é chamada de
    melhor. Um **total** só é oferecido para indicadores em que somar tem sentido
    (população, PIB, força de trabalho); para uma porcentagem, uma taxa ou uma expectativa de vida ele é
    **recusado com o motivo exibido**, porque somar porcentagens produz um número que ninguém
    mediu. Cada número informa a sua **cobertura** e a sua **dispersão** (mín/máx/n) —
    um número de destaque de um bloco que esconde uma variação de dez vezes é verdadeiro e enganoso, por isso a variação vai
    junto com ele. Onde faltam membros, o agregado é **recusado por padrão**; você pode
    publicá-lo mesmo assim, e o resultado é então identificado como parcial e indica exatamente quais
    membros faltam. A composição dos blocos muda com o tempo (o BRICS tinha cinco membros até
    2024; a UE perdeu o Reino Unido em 2020), então cada número de bloco informa a **composição
    de referência** com que foi calculado, e um bloco cuja lista de membros ainda não conseguimos obter de uma fonte diz
    isso claramente em vez de mostrar um número.
- **Mapa** — um **coroplético ooMap** de um indicador selecionável, com um seletor de
  ano/histórico; clique em um país para abrir o seu detalhe na subaba Países.
- **Direito** — acompanhamento do **direito** (leis, diários oficiais, registros de propriedade intelectual) a partir de fontes oficiais
  do mundo todo, observando como ele muda ao longo do tempo (as *mudanças são os dados*). Um **espelho
  de pesquisa**, nunca a fonte oficial de referência e **não é aconselhamento jurídico** — cada registro tem um link
  de volta ao seu diário oficial. Um catálogo mundial de fontes oficiais reais
  (`legislation.gov.uk`, EUR-Lex, Légifrance, govinfo, WIPO Lex, USPTO, EPO, …) vem carregado
  por padrão. **Acompanhar alterações agora** obtém os documentos acompanhados através do
  coletor ético, guardando uma referência e depois **diferenças** honestas com um sinalizador de grande mudança; **Mudanças
  legais sinalizadas** as lista (jurisdição · título · Δ bytes · motivos) com as diferenças e
  um link para a fonte oficial. O resumo também apresenta uma Pista de **legislação-modelo**
  quando um texto quase idêntico aparece em várias jurisdições.
- **Estatísticas** — o diretório de produtores e os números brutos com data de referência por trás das outras
  subabas, mais **Adicionar as séries ao corpus** (abaixo).

**Estatísticas na pesquisa comum.** Um número que ninguém consegue encontrar não está de fato no seu corpus,
então cada **série** — um indicador para um país, ao longo de todos os anos disponíveis — também pode ser
materializada como um **Artigo** comum. Ela então percorre os caminhos normais: a pesquisa encontra
"life expectancy France", as suas palavras chegam às tendências e às Pistas, e ela aparece no Fluxo
como qualquer outra coisa, sem uma caixa de pesquisa especial para lembrar. Vale a pena saber quatro coisas:

- É **um Artigo por indicador por país**, não um por revisão. Um número de 1991
  corrigido atualiza o Artigo existente em vez de acrescentar uma quase cópia, então executar de novo a
  tarefa não custa nada e não acrescenta nada.
- Os Artigos são **identificados pelo que são** — a fonte diz "Official statistics
  (World Bank)" e a classe de procedência é `statistics` — então você pode incluí-los ou
  excluí-los de qualquer visualização, e as verificações de coordenação que procuram muitos veículos repetindo uns aos
  outros não podem confundir milhares de linhas de mesmo formato com concordância.
- O corpo diz deliberadamente **apenas o assunto e os números**, com uma **lacuna publicada
  mostrada como lacuna**. Repetir o nome do produtor e o código de série da máquina em cada
  um de ~9.800 Artigos colocou "World Bank" no topo da classificação de palavras-chave de todo o
  corpus — a estrutura de apoio superando aquilo de que o seu corpus realmente trata —, por isso isso não é feito.
- Para encontrá-los **por produtor** em vez de por assunto, filtre pela fonte ou pela
  etiqueta `statistics`; para procurar um **por código de série**, use a subaba Estatísticas, que
  responde de forma exata em vez de por correspondência de texto.

Materializá-los é uma tarefa em segundo plano que você inicia em **Governos → Estatísticas**; ela pode ser
retomada, pode ser cancelada e não atrasa a coleta.

### 3.8 Provas e custódia

*(Acessado por **Configurações → Avançado → Segurança** — "Cadeia de custódia" é o título do painel; ele saiu
da barra lateral na reformulação centrada no conteúdo.)*

**Para que serve:** provar — a um terceiro cético, offline — que o seu corpus
continha *este* item, com *este* conteúdo, *neste* momento, e que o registro não
mudou desde então. **Não** é um sistema para denunciantes/SecureDrop; uma "fonte" aqui é um
veículo de notícias, não uma pessoa confidencial.

O painel tem três partes:

- **Configurações e status.** Interruptores para **Assinaturas pós-quânticas** (acrescentar uma assinatura ML-DSA /
  FIPS-204 ao lado da Ed25519), **Ancoragem OpenTimestamps** (ancorar no
  Bitcoin para uma prova de tempo independente), **Registro automático na ingestão** (acrescentar uma entrada assinada
  a cada ingestão bem-sucedida) e um rótulo de **Ator padrão**. O essencial: o
  status sempre mostra o estado **efetivo**, não apenas o seu desejo: se você ativar PQC
  ou OpenTimestamps mas a biblioteca necessária não estiver instalada, ele diz *"solicitado,
  biblioteca não instalada"* e continua apenas com Ed25519/local — **ele nunca mostra uma luz verde
  que não pode sustentar.** A proteção da chave também é mostrada (`aes256gcm-scrypt` quando uma frase-senha está
  disponível, vinda de `OO_KEY_PASSPHRASE` ou da frase-senha do banco de dados; `plaintext-0600` caso contrário; e `pkcs8-pbkdf2`
  ou `plaintext-0600` com uma frase-senha disponível, para uma chave de antes da 0.6 que ainda não pôde ser reencapsulada,
  o que diz o que o seu arquivo realmente contém).
- **Ver e verificar a cadeia.** Insira um id de item (p. ex. `article:42`) para **Ver cadeia**
  (sequência, ação, ator, hora, algoritmo de assinatura), **Verificar** (verifica de novo os elos da cadeia,
  hashes, assinaturas, carimbos de tempo) ou **Exportar pacote** (um
  arquivo verificável offline).
- **Ancorar a raiz Merkle (Anchor Merkle root).** Cole uma raiz Merkle para ancorá-la pelo provedor configurado.

> **Aviso de privacidade exibido no aplicativo:** ancorar em uma blockchain pública publica um
> hash permanentemente e revela o seu IP/horário aos operadores dos calendários. Prefira
> local + OpenTimestamps a carteiras on-chain com fundos; passe pelo Tor (`HTTPS_PROXY`)
> se precisar de anonimato; ou fique apenas no local (o padrão não vaza nada).

**OpenTimestamps e o modo avião.** No modo OpenTimestamps, uma entrada de ingestão cujo
envio foi recusado pelo interruptor geral da rede (um Parar durante a coleta) não recebe em seu lugar uma
prova apenas local, porque essa prova seria permanente: a entrada fica devida,
e é gravada depois, marcada como tardia, com a sua âncora. A fila de devidas não tem limite de tamanho, e
o fim de cada passagem de coleta grava no máximo 200 delas, cada entrada com até três
envios a calendários feitos enquanto o registro de custódia está reservado para gravação. Assim, um grande acúmulo
deixa mais lento o fim das passagens de coleta por um tempo, depois que você volta a ficar online.
Enquanto o interruptor ainda está acionado, a gravação das entradas devidas ("Registrá-las, marcadas como tardias", ou
`POST /api/custody/reconcile`) para na primeira recusa e diz que o interruptor geral a recusou;
as entradas continuam devidas. Uma verificação de lacunas sozinha ainda responde, e o seu bloco `drained`
informa `refused_offline`.

Verifique um pacote em qualquer lugar, sem este aplicativo:

```bash
python scripts/verify_custody.py custody_bundle.json [--pin]
python scripts/verify_evidence.py bundle.json [signer_pubkey]
```

O projeto completo — e exatamente o que cada mecanismo prova e **não** prova — está
em [`docs/USER_MANUAL.md`](USER_MANUAL.md). *(Uma reformulação planejada para tornar
esta aba à prova de leigos e em grande parte automática está registrada em
[`docs/ROADMAP.md`](archive/roadmaps/DESIGN_MEMORY_pre-0.2.md).)*

### 3.8a Integridade das fontes

*(O painel de integridade das fontes foi transferido para **Configurações → Avançado → Segurança → "Abrir o painel de integridade
das fontes"**; a coordenação agora também é apresentada automaticamente — como Pistas no Início, na visualização
**Relacionados** da janela de análise e como selos "N cópias = uma voz" nas listas de artigos
e no leitor.)*

**Para que serve:** ver a *estrutura* por trás das suas fontes — e decidir, você mesmo,
qual sinal conta. Não há, deliberadamente, **nenhuma pontuação de confiança**; um único número
embutiria vieses e silenciaria fontes pequenas, estrangeiras, novas ou dissidentes. Guia completo:
[`docs/USER_MANUAL.md`](USER_MANUAL.md).

- **Antiamplificação (propor → você decide):** *Buscar coordenação* encontra
  enxurradas de quase duplicatas publicadas em sincronia por muitas fontes, com as suas provas
  (texto compartilhado, horário, host). Por padrão elas são apenas **anotadas** — nunca
  agrupadas silenciosamente. **Aplicar agrupamento** para contar uma rede como **uma voz** (em qualquer contagem que
  meça consenso); ela continua sinalizada, e **Expandir (reverter)** restaura exatamente a visão bruta
  de pesos iguais. Nada é jamais agrupado sem uma ação sua. As Pistas de câmara de eco no Início
  trazem a mesma ação.
- **Perfil da fonte:** um painel de dimensões medidas — coordenação, novidade
  (origina vs ecoa), capacidade de produção, fatos de transparência, histórico — cada uma com
  o seu método e a sua ressalva, e **nenhuma pontuação composta**.
- **Anotações compartilhadas (rede de confiança):** escreva fatos descritivos e contestáveis sobre
  fontes (propriedade, inclinação, coordenação, correções); **exporte-os** como um pacote
  **assinado**; **importe** os pacotes em que você escolher confiar. *Quem disse o quê?* mostra
  todas as atribuições de uma fonte e destaca a **divergência** — nunca reduzida a um número por média.
  Veja [`docs/USER_MANUAL.md`](USER_MANUAL.md).

### 3.9 Configurações

**Para que serve:** preferências, as superfícies de aquisição e a manutenção — organizadas
em **nove** seções por uma subnavegação: **Gráficos · Geral · Cartões · IA · Wikipédia ·
OpenStreetMap · Agenda · Dados e cópia de segurança · Avançado**.
Abra as Configurações pelo **botão no rodapé da barra lateral**; a paleta de comandos também
leva direto até aqui. Tudo é armazenado localmente; sem telemetria.

O uso do dia a dia não precisa de nada em **Avançado**: a mecânica da coleta, a gestão de fontes, a curadoria
de palavras-chave, o diretório de produtores de estatísticas, o catálogo de feeds de calendário, a central de
diagnóstico, **Segurança** e **Desinstalar e apagar** ficam todos lá, em **seções recolhidas que só
carregam seus dados quando você abre uma delas** (só o catálogo de fontes pode ter dezenas de milhares
de linhas). Segurança era antes uma subaba própria; agora é a penúltima seção de Avançado,
e as duas ações irreversíveis — **Apagamento de emergência** e **Desinstalar o aplicativo** — foram separadas
numa seção só delas (**Desinstalar e apagar**), para que nenhuma possa ser acionada por engano
enquanto você lê sobre criptografia. Nada se perdeu em nenhuma das mudanças: todo controle
que estava na subaba Segurança continua lá, sob os mesmos títulos. **Recolher** e **Fontes** estão
documentados acima ([3.2](#32-coletar-em-configurações--avançado--coleta),
[3.3](#33-fontes-em-configurações--avançado--fontes)) e são acessados por Avançado;
**Wikipédia** ([3.7](#37-wikipédia-em-configurações--wikipédia)) mantém sua própria seção.
Os **números** oficiais não ficam aqui de jeito nenhum — eles são dados, por isso ficam em
**Governos → Estatísticas**.

- **Gráficos (Aparência):** temas, cor de destaque, densidade, **tipo de letra**
  e barra lateral expandida/recolhida. (Não há controle deslizante de tamanho do texto: ele só ampliava o
  elemento raiz, do qual quase nada na folha de estilos herdava, então não fazia nada.
  Use o zoom do seu próprio navegador — ele amplia tudo, inclusive as partes que um controle
  aplicado só à raiz nunca alcançaria.) Esta seção também abriga a galeria de **Interfaces alternativas**
  (marcada como *Experimental*): oito aparências opcionais — **Aurora, Atlas, Command, Field,
  Focus, Terminal, Canvas, Editorial** — sobre os mesmos dados e com as mesmas garantias de
  honestidade; escolher uma recarrega a página para aplicá-la. (A antiga gaveta flutuante "Personalizar" agora
  é esta seção de primeira classe.)
- **Cartões (Pistas no Início):** todos os produtores de Pistas que o app pode executar, agrupados por família
  (*Em alta · Sobrecontado · Subcontado · A investigar · Verificar o enquadramento · Continuar a observar ·
  Contexto · Integridade dos dados*). Desligue qualquer um e ele deixa de aparecer — isso não muda nada
  nos próprios artigos, só quais sugestões chegam ao seu Início. Quando uma Pista tem
  limiares, eles agora ficam visíveis e ajustáveis, cada um com um **intervalo seguro** declarado, uma
  nota de uma linha sobre o efeito de alterá-lo e um botão **Redefinir**. Você sempre pode tornar uma Pista
  *mais rigorosa*; os limites inferiores existem para que uma Pista nunca afirme mais do que suas evidências
  sustentam — a verificação de inundação, por exemplo, não desce abaixo do limiar de p<0.05,
  porque abaixo dele o teste já não consegue distinguir um surto real de uma variação comum. Qualquer
  valor fora de um intervalo é corrigido **e informado**, nunca ajustado em silêncio.
- **Preferências (Geral):** **Tema** (Sistema/Escuro/Claro), **idioma** e **Resultados de pesquisa
  predefinidos**.
- **Filtragem de palavras-chave (Avançado → Palavras-chave):** palavras funcionais "vazias" (o, você, não, …) são removidas por uma
  lista de palavras vazias multilíngue embutida. Ajuste-a: defina o **comprimento mínimo da palavra-chave**, **descarte
  termos puramente numéricos**, ative ou desative a lista embutida e mantenha uma lista de **palavras-chave
  excluídas** (uma por linha ou separadas por vírgula). Excluir oculta um termo
  em todo lugar, mas é reversível — as menções armazenadas são mantidas. (Você também pode clicar em ✕
  ao lado de qualquer palavra-chave em Análises.)
- **Bases de referência offline da Wikipédia:** escolha uma **edição de idioma** numa **lista simples**
  (primeiro os idiomas da sua interface, depois as maiores edições), com cada opção começando pelo
  **nome nativo** (autônimo) — as edições se baseiam em idiomas, não em países, por isso
  não há agrupamento por continente. Cada edição que tem dump disponível mostra um **tamanho aproximado
  em linha** (`~X GB`, de uma tabela datada embutida — zero rede adicional), para que você possa avaliar
  antes de baixar; o tamanho exato é lido quando o download começa. **Baixar** pode ser
  retomado (pausar/retomar + uma tabela de progresso). Esses dumps offline são pesados e
  opcionais, e servem apenas para leitura/pesquisa offline — o acompanhamento de mudanças ao vivo (a
  aba Wikipédia) não precisa deles.
- **IA (LLM local) [AI (local LLM)]:** uma caixa **Configurar IA local** no topo apresenta todo o plano
  restante num só lugar — qual backend esta máquina vai usar (vLLM onde uma GPU NVIDIA
  dedicada puder servi-lo, Ollama nos demais casos), o que ainda falta instalar e os
  tamanhos de download — e o executa com **um só botão** após **um só** consentimento. Ela se oculta
  quando não resta nada a fazer; os controles por componente abaixo dela não mudam,
  então você ainda pode fazer cada passo por conta própria. Abaixo disso: o backend ativo
  e **por que** ele foi escolhido, os modelos instalados e um catálogo curado e datado, **baixar** um
  modelo (uma tarefa de download **em fila** — uma de cada vez, cancelável, com progresso de bytes
  ao vivo; os bytes trafegam pela clearnet através do processo do Ollama, **não** pelo Tor — informado no
  pedido de consentimento), **remover** um modelo e definir o **modelo ativo**.
  A **adequação do hardware** é declarada uma única vez, aqui, junto com o que ela significa para você: a
  inferência local só é recusada por padrão abaixo de um piso (menos de 4 núcleos de CPU, ou menos
  de 6 GB de RAM, sem acelerador); rodar sem GPU dedicada, com uma placa de
  pouca VRAM ou num Mac pequeno de memória unificada gera um **aviso sobre o que
  esperar**, não uma recusa. **Nunca é um bloqueio** — uma caixa de seleção reativa a IA, e
  a explicação continua visível em qualquer caso. **Iniciar** a IA local é feito pela **pílula de IA**
  da barra superior, a partir de qualquer tela.
  Um editor **"Comportamento e prompts"** expõe os quatro prompts de sistema editáveis
  (resumo / tradução / síntese / extração de palavras-chave) e o tempo de permanência do modelo na memória.
  Esses quatro prompts **vêm nos doze idiomas da interface**, de modo que um leitor francês ou
  japonês recebe um resumo escrito no seu idioma, e não um trabalho em inglês;
  o editor mostra o texto embutido para o **seu** idioma, e o prompt exato usado
  fica registrado junto com cada resultado. O seu próprio prompt, se você escrever um, é usado **exatamente
  como você o escreveu**, no idioma em que o escreveu. Uma lista de **Extratores personalizados**
  permite definir prompts gerenciados que gravam metadados derivados por IA (rotulados como
  *não confiáveis*, nunca o índice confiável de palavras-chave).
  Quando o Ollama não está presente, aparece um **instalador dentro do app** (Linux/Debian): ele baixa
  o script de instalação oficial, verifica-o contra o resumo sha256 atestado do GitHub, mostra
  uma etapa visível de elevação de privilégios e o executa — recusando-se diante de qualquer divergência de resumo. macOS/Windows
  recebem uma indicação honesta para ollama.com/download.
- **Estatísticas — o diretório de produtores (Avançado → Estatísticas oficiais):** um
  diretório descritivo de produtores de estatísticas governamentais + internacionais. Os
  próprios **números** são dados, por isso ficam em **Governos → Estatísticas**,
  não nas Configurações. Todo produtor traz o **mesmo aviso descritivo de fonte com
  posicionamento** — um número oficial informa a agência que o produziu e seu posicionamento — **nunca um
  rótulo, veredito ou pontuação de "controverso" por fonte**. Você pode **adicioná-los às suas fontes** — um produtor cuja
  seção de notícias/imprensa é conhecida é ativado e coletado a partir dela, enquanto um cujo
  endereço ainda não foi pesquisado é adicionado desativado, em vez de ter seu portal de dados
  rastreado — e **obter números oficiais** de endpoints de máquina documentados
  (API do Banco Mundial / SDMX do Eurostat), armazenados com toda a sua procedência e uma **safra**
  (vintage) de primeira classe (uma nova obtenção é uma nova linha, nunca uma sobrescrita). Os produtores são mostrados **lado a
  lado, nunca em média**, e uma visão **Triangular [Triangulate]** sinaliza células que misturam unidades
  incomparáveis / ajuste sazonal / anos-base. **Verificar anomalias de revisão** sinaliza, de forma puramente
  retrospectiva, um número armazenado cuja safra mais recente alterou um valor passado de forma incomumente grande
  em relação ao próprio histórico de revisões daquela série (sem pontuação). A obtenção sai pelo transporte
  que você configurou e é recusada no modo avião.
- **OpenStreetMap:** escolha uma região do mapa (com uma estimativa datada em `~GB`) e baixe-a
  como uma tarefa retomável e pausável do gerenciador de tarefas (sujeita ao único popup de consentimento de rede).
- **Boletins:** importe boletins como artigos — **anonimizados na ingestão** (o
  destinatário nunca é armazenado, ecos do destinatário são ocultados, tokens de rastreamento são removidos
  e invólucros de rastreamento do lado do servidor são sinalizados; **nada é baixado nunca**, então importar
  jamais pode revelar que você abriu ou clicou). Três caminhos:
  - **Escolher arquivos .eml [Choose .eml files]** — um pequeno envio de vários arquivos.
  - **Importar uma pasta inteira** — aponte para uma pasta nesta máquina; todo `.eml` dentro dela
    é importado como uma **tarefa em segundo plano pausável e retomável** (visível no gerenciador de tarefas) que
    dá conta de arquivos de mais de 20 GB, pulando as mensagens já importadas.
  - **Extrair de uma caixa de correio (IMAP/POP3)** — puxe ao vivo de uma caixa de correio, com um aviso
    visível no momento do uso (TLS até o provedor, seu IP fica visível, **não** passa pelo
    Tor, as credenciais não são armazenadas). Sobre TLS, o certificado do servidor tem de corresponder ao nome dele
    e vir de uma autoridade em que o seu computador confia; caso contrário, a extração é recusada antes
    de a sua senha ser enviada, e a mensagem explica por quê. Pela API, uma extração com
    `use_ssl` definido como false (geralmente na porta 143/110) primeiro faz o upgrade com STARTTLS sob a
    mesma verificação, e é recusada se o servidor não o oferecer: a sua senha nunca é
    enviada sem criptografia.
  - **A qual editora pertence cada boletim?** — todos os boletins importados atualmente
    ficam numa única fonte-contêiner. `GET /api/newsletters/publisher-preview` mostra como SERIA
    um arquivamento por editora para os boletins que você já tem: cada domínio
    remetente, quantas mensagens vieram dele e a qual fonte existente ele corresponde (um
    eTLD+1 real de uma Public Suffix List embutida — assim `email.bbc.com` corresponde a `bbc.com` — com
    as plataformas de boletins tratadas ao contrário, para que duas publicações do Substack nunca
    se fundam num único "Substack"). É **apenas uma prévia**: nada é vinculado nem movido, e
    onde as evidências não decidem, ela diz isso em vez de adivinhar.
  - **Remover newsletters importadas** — exclui do corpus ativo todos os artigos de boletins importados (.eml +
    caixa de correio), para substituir um conjunto defeituoso por uma reimportação limpa
    (a restauração é apenas aditiva, então deixar os boletins fora de um backup nunca os remove — isto
    remove).
- **Dados e cópia de segurança — a Exportação / Importação unificada:** um só lugar para fazer backup de tudo, com
  **qualquer tamanho de banco de dados**. **Exportar / Cópia…** abre uma caixa de diálogo: escolha uma **pasta de destino
  ou unidade**, marque o que incluir (corpus, boletins importados, modelos LLM locais,
  mapas offline, dumps da Wikipédia) e informe uma **frase-senha** — o corpus criptografado é transmitido
  para essa pasta como **volumes autenticados de forma independente, mais paridade Reed-Solomon** (assim
  um volume perdido/corrompido, mesmo um volume do corpus, pode ser reconstruído), e os grandes blobs públicos
  (modelos / mapas / dumps) são copiados **como estão**. **Não há limite de tamanho** e o arquivo
  nunca é mantido inteiro na RAM. A frase-senha **não tem recuperação** — uma frase-senha perdida significa que o
  backup do corpus não pode ser aberto.
  - **Cada exportação cria sua própria pasta datada.** O destino que você escolhe é a pasta PAI:
    dentro dela, cada exportação cria `YYYYMMDDHHMM_OpenOmniscience_Backup` — a data e a hora
    locais em que a exportação começou, para que as pastas fiquem ordenadas na ordem em que você as criou. Uma segunda
    exportação no mesmo minuto recebe `_2`, `_3` e assim por diante. Uma pasta existente **nunca recebe
    gravações**, então um backup anterior na mesma unidade não pode ser danificado por um posterior.
  - **Toda exportação é um backup novo e completo.** Nada é reaproveitado de um anterior, então uma
    exportação custa o tempo e o espaço de tudo o que você selecionou — e, em troca, cada
    byte daquela pasta foi gravado por aquela única passagem.
  - **Verificar após gravar [Verify after writing]** (ativado por padrão). Quando o último volume chega, cada volume é
    relido do destino e sua soma de verificação é comparada com a registrada quando ele
    foi gravado. Isso lê cada byte uma segunda vez, o que mais ou menos dobra o tempo de uma
    exportação numa unidade lenta; é a única coisa que detecta uma unidade que aceitou
    a gravação e armazenou outra coisa. O painel de conclusão então mostra **"Verificado" [Verified]** —
    e, se não mostrar, diz qual dos quatro motivos se aplica: a verificação estava
    desligada, foi cancelada, o conjunto não pôde ser relido, ou ela **falhou**, e nomeia os
    volumes.
  - **`BACKUP_SUMMARY.md`** é gravado ao lado de `volumes.json` no fim de toda exportação:
    os mesmos fatos que o painel de conclusão mostra — volumes, bytes, linhas por tabela com
    os artigos primeiro, arquivos copiados por categoria, tempo decorrido, destino, estado da criptografia,
    versões do esquema e do app, o resultado da verificação e as linhas de atribuição que se aplicam ao
    conteúdo do backup. Ele existe para que a pasta se explique sozinha numa unidade removível
    anos depois, quando o painel que declarou tudo isso já tiver sumido há muito tempo. É uma descrição,
    não uma assinatura: `volumes.json` traz as somas de verificação por volume que comprovam os bytes.
    **Ele também é o único arquivo daquela pasta que não é criptografado** — o corpus é
    ilegível sem a sua frase-senha, e este resumo é texto simples ao lado dele, dizendo
    quantos artigos, fontes e documentos acompanhados o corpus contém. Essa é a troca
    que o arquivo faz, ela está declarada no próprio arquivo, e você pode excluí-lo se a pasta
    se explicar sozinha importar menos para você do que não dizer nada a quem encontrar a unidade.
  - **As exportações nunca são agendadas.** Não há exportação automática ou programada e nenhuma está
    planejada — uma exportação é um **ato deliberado**, porque grava o seu corpus num lugar
    que você escolheu, num momento que você escolheu.
  **Importar…** aponta para uma pasta, encontra o que pode ser importado dentro dela (um backup a restaurar,
  dados grandes ou boletins) e o restaura. **A restauração é apenas aditiva** — ela
  **complementa** o seu corpus e **nunca o substitui**: nada do que você já tem é
  sobrescrito, duplicatas são detectadas bit a bit, e um valor conflitante **mantém o seu
  valor local e informa ambos**, nunca faz média.
  - **Relatórios de importação.** Tanto uma mesclagem de restauração quanto uma importação de boletins por pasta
    gravam automaticamente um **relatório persistido** em disco ao final (na unidade de
    ARTIGOS — nunca uma soma de linhas entre tabelas que parece milhões de artigos quando
    na verdade são linhas de muitas tabelas) — quantos artigos entraram, quantos foram
    filtrados como não artigos (veja **Triagem de não artigos**, abaixo) e o
    "trabalho induzido" que ela deixa para trás (por exemplo, quantas fontes recém-importadas ainda
    aguardam qualificação; veja [§3.3](#33-fontes-em-configurações--avançado--fontes)). O próprio
    relatório vai junto no seu **próximo** backup criptografado, então ele viaja com o corpus. Ele pode ser
    baixado via `GET /api/backup/import-reports` (lista) e
    `GET /api/backup/import-reports/{filename}` (como JSON, ou `?format=md` para uma
    versão legível em Markdown) — ainda não há uma tela dedicada no app para isso,
    então use esses endpoints (ou o navegador) para ler um relatório.
  - **Triagem de não artigos.** Toda mesclagem de restauração e toda importação de boletins por pasta
    examina automaticamente os artigos que acabou de trazer e **coloca em quarentena** — mantidos,
    nunca excluídos, e de forma reversível — os que correspondem aos mesmos critérios de validade de extração
    usados no teste de qualificação de fontes (uma página de menu de navegação, uma lista de links, uma
    raspagem quebrada). Um artigo em quarentena fica excluído da pesquisa e das análises, mas
    continua no banco de dados e vai junto nos seus backups; a contagem está no relatório de importação.
  > **Caminhos legados / de migração (mantidos para backups mais antigos).** Um painel separado restaura um
  > arquivo **antigo de arquivo único `oo-backup-2`** com a mesma **prévia** da mesclagem aditiva
  > (novo / duplicado / conflito) antes de **Aplicar** (sobre uma cópia preparada e verificada, troca atômica,
  > com um instantâneo `pre-restore-*.db` guardado ao lado do banco de dados). Um instantâneo bruto de **Transferir cópia de segurança (.db)**
  > (API de backup online do SQLite) fica guardado em *"Ferramenta de backup antiga… [Older backup tool…]"* para
  > uso manual. **A restauração destrutiva que "substitui o seu corpus" foi removida por completo** — nenhum fluxo
  > pode sobrescrever os seus dados, e restaurar um backup **criptografado** nunca descriptografa silenciosamente
  > o seu corpus.
- **Manutenção (painel de Diagnóstico) [Diagnostics panel]:** **Limpar palavras-chave (reindexar e depois remover)** e
  **Reindexar todo o corpus** executam uma **tarefa em segundo plano pausável, com cursor persistido**
  (ela sobrevive ao fechamento da aba ou a um reinício e continua de onde parou). Execute a limpeza após
  uma atualização do motor de palavras-chave para aplicar as listas de palavras vazias/famílias mais novas aos artigos existentes.
  **Unificar formas de palavras-chave (estudos → estudo)**, ao lado, faz a única parte dessa limpeza
  de que a lematização precisa, sem reler nenhum artigo: palavras-chave indexadas antes de a lematização
  ser adicionada mantêm "studies" separado do "study" que os artigos novos usam, e a unificação arquiva essas
  menções antigas sob a forma base exatamente como uma reindexação faria. Em seguida, ela define o
  idioma de cada palavra-chave a partir dos idiomas das suas menções. Frases, nomes e palavras-chave que suas
  famílias ou grupos usam nunca são unificados. É uma tarefa pausável no gerenciador de tarefas, e
  **Relatório de unificação (.json)** mostra o que a última unificação concluída contou e as suas maiores unificações.
  Uma unificação não pode ser desfeita; uma remoção posterior elimina as palavras-chave que ela esvaziou.
  **Reindexar a pesquisa (árabe, chinês, japonês)** indexa os artigos escritos antes desta
  versão do mesmo jeito que os novos, para que artigos mais antigos em árabe, chinês e japonês também sejam encontrados por
  palavra. Ela lê cada artigo uma vez e reindexa apenas aqueles cuja entrada de pesquisa
  mudaria; é uma tarefa pausável no gerenciador de tarefas, e **Relatório de reindexação da pesquisa (.json)**
  mostra quantos artigos ela verificou e reindexou, por escrita. Execute-a de novo após atualizar o jieba ou
  o dicionário japonês: os artigos que o novo dicionário divide de forma diferente são
  reindexados, e o relatório informa as versões com que ela rodou.
- **Instrumentação temporária de teste de campo (ciclo de testes ao vivo 0.0.8).** Durante este
  ciclo, o app exercita automaticamente cada superfície de rede uma vez *dentro das suas
  próprias passagens de coleta* (verificação de feeds de calendário em lotes educados, as importações de feeds
  de mercados e índices, um acompanhamento de legislação, um acompanhamento de wiki) e registra cada
  resultado literalmente em `data/field_test.jsonl`, incluído no pacote de depuração.
  **Objetivo:** aperfeiçoamento recorrente das listas de fontes, feeds e calendários da instalação padrão
  a partir de veredictos reais — o mantenedor reinstala,
  clica por tudo e compartilha o pacote com o desenvolvimento. **Ela está desligada por
  padrão desde a 0.1** — ative-a para um ciclo de testes ao vivo com `OO_FIELD_TEST=1`.
  Nada é transmitido pelo app, nunca: os logs ficam nesta máquina até que *você* os
  baixe e compartilhe. A inicialização continua totalmente offline em qualquer caso.
- **Registo de diagnóstico:** uma síntese compartilhável de como o app enxerga o seu corpus — gerada
  só quando você clica, apenas contagens e estruturas (nunca pontuações), e só você decide quem
  recebe o arquivo. O painel tem UM botão **Diagnóstico**, sua caixa **Completo** e dois pequenos links, **Todas as palavras-chave** e **Guardar de novo o último Diagnóstico**; todos os outros logs desta tabela são **membros do arquivo de Diagnóstico**, não um botão
  próprio (vários contêm mais de um relatório: `selftests.json` traz os treze autotestes de mecanismos,
  cada um com um veredicto, `storage.json` as leituras de ocupação, composição, volume e persistência,
  `contention.json` a barreira de gravação e a atribuição de travamentos, `ai-runs.json` os resultados das últimas tarefas de IA,
  `run-journal.json` o resumo e as suas linhas brutas; o `merged.replaces` de um membro mesclado no manifesto
  nomeia os arquivos que ele substituiu, para que um arquivo antigo possa ser lido em comparação com um novo):

  | Exportação ou membro do arquivo | O que é |
  |---|---|
  | **Diagnóstico** (e sua caixa **Completo**) | UM arquivo com tudo o que esta instalação pode dizer sobre si mesma, montado em segundo plano (o app continua utilizável) e depois entregue: **um único arquivo** quando cabe em 4 MB, caso contrário **arquivos numerados de no máximo 4 MB cada** (`…-part-03-of-12.zip`) mais um pequeno `…-manifest.zip` que lista cada arquivo com seu tamanho e SHA-256. Cada arquivo abre sozinho em qualquer ferramenta de descompactação. **Rápido [Quick]** (o padrão) grava primeiro os registros, com a coleta ainda em andamento, e depois tantas varreduras do seu corpus quanto couberem em dez minutos, das mais curtas para as mais longas; uma varredura que não coube é **nomeada no arquivo** como não executada, com o motivo, nunca descartada em silêncio. **Completo** (a caixa ao lado do botão, vazia de novo toda vez que o painel abre) executa todas as varreduras, cada uma por até cinco minutos, com a coleta pausada enquanto elas rodam (de 27 a 47 minutos medidos num corpus grande). O `manifest.json` do arquivo diz qual modo rodou, a máquina em que rodou (build, versões das bibliotecas, nível de memória, os nomes das chaves `OO_*` que estavam definidas, nunca os seus valores) e, para cada membro, a sua área (memória, armazenamento, banco de dados, sessões, execuções, palavras-chave, interface, fontes, IA, autotestes, build). Veja "Salvar os arquivos numerados" abaixo |
  | **Guardar de novo o último Diagnóstico** (um link sob o botão, mostrado quando já existe uma montagem) | o mesmo arquivo concluído, salvo de novo (digite antes um número de parte em "Começar na parte número" e ele começa ali, para que você possa reenviar só as partes cujo envio falhou). Ele só reaproveita um arquivo que você já montou — nunca inicia uma nova montagem. Se um único log for grande demais para caber num arquivo, ele é cortado nos limites dos registros em pedaços numerados, e o manifesto diz quais (um corte por bytes, `.part0001of0003`, é o último recurso e é nomeado em `volumes.json`) |
  | **Todas as palavras-chave** (um link) | a lista por palavra-chave: todas as palavras-chave do corpus (não só as principais de cada idioma), sem limite de tamanho total, em arquivos numerados de no máximo 4 MB cada. Os primeiros arquivos contêm as 5.000 principais de cada idioma, então, se você não puder enviar todos, envie-os na ordem numérica. Ela é gravada em disco um lote de cada vez, de modo que a memória do app fica estável qualquer que seja o tamanho do corpus; um corpus grande gera muitos arquivos (a página diz quantos antes de você salvar qualquer um) e leva minutos, e a exportação para com uma mensagem clara (e remove os seus arquivos parciais, quando a unidade permite) se faltar memória ou disco. Todo o resto que o log de palavras-chave continha está, quando a montagem do Diagnóstico o executou, no arquivo de Diagnóstico como `keyword-log-digest.json`: as famílias (as 1.000 principais impressas, toda família contada no resumo do arquivo), as suas correções, os supergrupos, a concentração por fonte, os candidatos a palavra vazia e a anel e as contagens do corpus, tal como o log de palavras-chave os continha, mais as 100 principais palavras-chave por menções, com o número das que ficaram de fora. Uma montagem Rápida num corpus grande pode nomear o resumo como não executado porque ele não coube nos dez minutos (marque **Completo**), um computador sem memória suficiente o nomeia como recusado, e um resumo que ultrapassa o seu próprio limite de cinco minutos é nomeado como pulado (o modo Completo mantém esse limite); este link é então o caminho até as palavras-chave, e o seu próprio resumo é montado sobre todas as palavras-chave, não só as primeiras 5.000 de cada idioma. Num computador com pouca memória que ainda assim executa o resumo, as famílias são agrupadas apenas sobre as primeiras palavras-chave de cada idioma, e o arquivo diz isso e aponta para este link. Não há botão para salvar de novo o último conjunto de arquivos de palavras-chave: depois de recarregar a página, clique no link para montar um novo conjunto |
  | **Autoteste de palavras-chave (.json)** | uma verificação com casos de referência de que a pré-seleção de palavras-chave continua se comportando bem (por exemplo, *WHO* ≠ *who*) |
  | **Relatório do motor de palavras-chave (.json)** | composição, precisão de entidades, cobertura de tradução/etiquetas, estado por idioma |
  | **Curva de crescimento de palavras-chave / (.json)** | palavras-chave distintas acumuladas vs. palavras adicionadas (o vocabulário está saturando?) |
  | **Diagnóstico dos cartões iniciais (.json)** | cada Pista do Início abre o seu corpus exato ou um substituto aproximado? |
  | **Registro de extração de datas (.json)** | cobertura da marcação de datas |
  | **Ocupação de meses (.json) [Month occupancy (.json)]** | dos nomes de meses que o filtro de palavras-chave descarta, quantos de fato faziam parte de uma data — a evidência para decidir se esse filtro deveria passar a reconhecer datas |
  | **Registro de rede (.json)** | resultados das obtenções com veredictos sensíveis ao transporte |
  | **Relatório de desempenho / Benchmark de escalabilidade / Benchmark do rollup (.json)** | tempos e verificações de escalabilidade |
  | **Pacote de depuração (.json)** | um pacote de suporte consolidado |

  **Salvar os arquivos numerados.** A página diz quantos arquivos estão prontos ("13 arquivos de no máximo 4 MB cada estão prontos (manifesto: 1, partes numeradas: 12)")
  e os entrega ao seu navegador **cinco por clique**, o manifesto primeiro, porque cinco é o que uma mensagem de envio comporta e um clique é o que faz um
  navegador aceitar um download. O seu navegador pode pedir uma vez para permitir vários downloads: permita. Depois dos cinco primeiros, o botão passa a dizer "Guardar os 5 seguintes";
  "Guardar todos os restantes" é oferecido sempre que restam mais de cinco arquivos, para um único clique que faz tudo. Um pacote de cinco arquivos ou menos, que é o caso comum, é
  entregue ao seu navegador pela própria página quando a montagem termina (o clique que a iniciou já ficou para trás há muito tempo); "Guardar de novo o último Diagnóstico" envia os mesmos arquivos de novo. A página só pode *pedir ao seu navegador* que salve
  um arquivo, por isso ela diz "Pedido ao seu navegador para salvar 5 de 13 arquivos", nunca que eles foram salvos: confira a sua pasta de downloads (um navegador que recusou a
  pergunta sobre vários downloads não salva nada e não avisa a página). Enquanto os arquivos estão a caminho, os botões ficam acinzentados, e um segundo clique não faz
  nada. Todo arquivo tem no máximo 4.000.000 bytes (o tamanho em que este app divide) e abre sozinho, então você pode enviar alguns agora e
  o resto depois. Para reenviar só alguns arquivos, digite um número de parte em "Começar na parte número" e clique em "Guardar a partir desta parte": ele entrega cinco arquivos
  a partir daquela parte (o manifesto não é salvo de novo), e um número além da última parte começa na última e avisa isso. Um número que você digita na mesma caixa também indica
  a "Guardar de novo o último Diagnóstico" onde começar (um número que a própria página escreveu ali é ignorado, então "de novo" com a caixa intocada
  começa pelo manifesto). Reenviar uma parte não move "Guardar os 5 seguintes": ele continua a partir do arquivo mais adiantado já entregue ao navegador. Digitar um número à frente dos arquivos já salvos pula os que estão
  no meio (a contagem na linha de estado diz quantos foram pedidos); digite o número da primeira parte que falta para preencher a lacuna.
  Um conjunto está completo quando todos os nomes de `…-part-01-of-NN` a `…-part-NN-of-NN` estão presentes e o SHA-256 de cada um confere com o
  manifesto. Para ler um conjunto com o script de análise, passe a ele a pasta (ou qualquer arquivo dela): `python scripts/analyze_keyword_log.py <folder>` — ele
  nomeia as partes que faltam ou que divergem do manifesto, pula uma parte danificada e lê o resto.

  O mesmo painel também executa o **enriquecimento de fontes** local (deduzir etiquetas de tema a partir do seu
  corpus) e passagens consentidas pelo **Wikidata** (tipos de fonte, descoberta de novas fontes).
- **Segurança e uso em situação de risco (Avançado → Segurança):** ferramentas para jornalistas que trabalham sob
  pressão, cada uma rotulada com o seu **limite honesto**:
  - **Criptografia em repouso (padrão para corpora novos).** Bancos de dados novos são
    criptografados em disco com SQLCipher 4: a cada início, o app pede **A
    frase-senha** — um segredo estável, como um ID de usuário (`OO_DB_PASSPHRASE` para
    execuções por script/sem interface). **Não há recuperação nem alternativa
    de descriptografia**: uma frase-senha perdida custa o tempo de recoletar, porque o
    corpus é reconstruído a partir da web — ele não contém nada pessoal além do que foi
    raspado e deduzido de fontes públicas. Os corpora em texto simples existentes continuam
    funcionando sem alteração; **Configurações → Avançado → Segurança → "Criptografar este corpus…"** converte
    um deles *no próprio lugar* (consentimento explícito, verificação completa antes da troca e um
    instantâneo deliberado em texto simples guardado como sua saída de emergência — exclua-o depois
    de desbloquear com sucesso). O **doctor** (`GET /api/system/doctor`,
    e o mesmo painel) atesta o estado *real* de cada armazenamento lendo os
    cabeçalhos dos arquivos — corpus, registro de custódia, chaves de assinatura — nunca por suposição.
    **O limite honesto:** a criptografia em repouso protege um *arquivo apreendido ou
    copiado*. Ela não pode proteger uma sessão em execução comprometida (a chave fica na
    memória enquanto o app roda), e ela só é independente da criptografia de disco inteiro
    se as duas frases-senha forem diferentes. A operação em texto simples continua disponível
    como escolha explícita (`OO_DB_PLAINTEXT=1`) — o app nunca mostra uma tela de
    bloqueio sobre um arquivo em texto simples, porque isso seria segurança fabricada.
    Os backups de um corpus criptografado funcionam sem alteração: os membros do artefato são
    portáveis, o próprio envelope do artefato criptografado os protege em repouso,
    e as restaurações preservam a criptografia do seu corpus (verificado por testes).
  - **Backup criptografado** — um instantâneo protegido por frase-senha (AES-256-GCM + scrypt).
    Uma frase-senha perdida ou errada significa que o arquivo não pode ser aberto: não há recuperação.
    Para trazer de volta um backup criptografado, use a **restauração por mesclagem aditiva** em
    **Dados e cópia de segurança** (acima) — ela mostra uma prévia e depois complementa o seu corpus sem nunca
    substituí-lo, e nunca descriptografa silenciosamente o seu armazenamento ativo. *(A antiga restauração destrutiva
    com substituição criptografada foi removida.)*
  - **Manutenção do banco de dados** — *Compactar banco de dados (VACUUM)* reconstrói o arquivo
    do banco de dados: recupera o espaço que as exclusões deixam para trás (mostrado como “Espaço
    recuperável”, uma leitura real de `PRAGMA freelist_count`) e desfragmenta os índices.
    Leva um tempo proporcional ao tamanho do arquivo e pausa as gravações da coleta
    enquanto roda; o resultado informa os bytes realmente liberados e a duração. Ela
    nunca interpreta nem remove dados. Ela monta a cópia compactada na memória
    (gravá-la num arquivo temporário corrompe um arquivo criptografado com o tamanho de página
    do app, medido), por isso primeiro verifica se o computador tem memória para isso
    (cerca de 1,25 vez a parte do arquivo que está em uso, além da memória livre
    que o app sempre reserva para si) e espaço na unidade (cerca do dobro
    da parte em uso, mais o tamanho do log do arquivo), e, quando falta qualquer um dos dois,
    diz qual, com os números, e não começa. Um valor que ela não conseguiu
    ler não é verificado, e ela diz isso também.
  - **Modo de coleta na rede** — *Transparente* (padrão; educado, nomeia a ferramenta no
    User-Agent) ou *Protegido* (as obtenções web do app passam por um proxy que **você** executa,
    por exemplo o Tor, com um User-Agent genérico). A única exceção de User-Agent são as requisições de API
    e de dumps do app aos servidores da Wikimedia (os seus recursos de Wikipédia, Wikidata e dumps):
    a política de API da Wikimedia pede que cada ferramenta se identifique, então, no modo protegido, essas
    requisições ainda levam o User-Agent próprio da ferramenta, pelo mesmo proxy e somente por
    https. Qualquer outra coisa obtida de um site da Wikimedia (um artigo coletado como qualquer outra
    página) recebe o genérico. Três coisas se conectam diretamente mesmo no modo protegido, como
    o texto ao passar o mouse na janela de consentimento de rede diz para cada uma: a extração da caixa de correio de boletins,
    a ancoragem OpenTimestamps e os downloads da IA local.
    O modo protegido **não pode garantir anonimato** — você precisa executar o proxy e confiar nele
    por conta própria; ele se recusa a ser ativado sem uma URL de proxy. Proxies SOCKS como o Tor não precisam
    de nada extra instalado.
  As duas ações **irreversíveis** ficam uma seção mais abaixo, em **Avançado →
  Desinstalar e apagar**, deliberadamente longe de tudo o que está acima:

  - **Apagamento de emergência** — exclui de forma irreversível o corpus, as chaves e os caches desta máquina
    (com dupla confirmação). **Limite:** sobrescrever no próprio lugar *não* garante
    que os dados sejam irrecuperáveis em SSD/flash — para isso, use criptografia de disco inteiro (LUKS/Qubes/Tails)
    e destrua a chave. Há também uma CLI `panic` e um modo de execução `--ephemeral`
    (dados só na RAM, apagados ao sair).
  - **Desinstalar o aplicativo** — remove o **ambiente virtual (virtualenv)** e os **atalhos da área de trabalho** do app,
    e depois para o servidor (confirmação por digitação). Os seus **dados são mantidos** (use primeiro o Apagamento de emergência para
    destruí-los); a pasta do app fica no lugar para ser excluída manualmente. Equivale a
    `./install.sh --uninstall` ou ao ícone **“Desinstalar o Open Omniscience” [Uninstall Open Omniscience]** na área de trabalho que o
    instalador cria ao lado dos dois atalhos do app.

  A governança e as linhas vermelhas de uso duplo que delimitam tudo isso estão em
  [`GOVERNANCE.md`](GOVERNANCE.md) (também em **Ajuda e documentação**).

### 3.10 Ajuda e documentação

**Para que serve:** ler a documentação **dentro do app**, offline. Uma
lista à esquerda seleciona um documento (este **Manual do usuário** é o padrão; os outros
se aprofundam em assuntos específicos), exibido à direita com **localizar na página**. Abra-a
pelo **?** na barra superior ou pela paleta de comandos ("Abrir o Manual do usuário" [Open the User Manual]). O
esquema bruto da API fica em `/openapi.json`.

---

## 4. Fluxos de trabalho comuns (passo a passo)

**Reunir notícias sobre um tema e pesquisá-las**
1. **Configurações → Avançado → Fontes** → confirme que as fontes relevantes estão ativadas (filtre por país/tag).
2. **Configurações → Avançado → Coleta** → clique em **Buscar feed** fonte por fonte, ou configure o
   **agendador** no modo RSS com as suas **Tags / palavras-chave (Tags/keywords)** e clique em **Iniciar** (ou simplesmente fique online
   — a coleta é executada automaticamente).
3. Pesquise pela **omnibar** → consulta booleana → **Exportar CSV/JSON** se precisar.

**Monitorar continuamente um assunto em segundo plano**
1. **Configurações → Avançado → Coleta** → no agendador, **Modo: Feeds RSS**, defina **Idiomas**/**Tags**,
   **Pré-visualizar alvos**, defina um **Intervalo**, marque **Iniciar automaticamente ao abrir**,
   **Salvar (Save)**.
2. Se quiser, ative **Provas e custódia → Registro automático na ingestão** para que cada captura seja
   assinada assim que chega.

**Produzir uma prova de um artigo defensável diante de um tribunal ou de um editor**
1. Pesquise o(s) artigo(s) pela omnibar.
2. **Exportar evidência assinada** (ou **Provas e custódia → Exportar pacote** para um item).
3. Entregue ao destinatário o pacote e `scripts/verify_evidence.py` /
   `verify_custody.py`; ele faz a verificação offline, sem precisar confiar em você nem nesta ferramenta.
4. Para uma prova independente de *data e hora*, ative o **OpenTimestamps** e ancore a raiz de Merkle
   do pacote (atenção ao aviso de privacidade).

**Vigiar um artigo contestado da Wikipedia em busca de adulterações**
1. **Configurações → Wikipédia** → adicione a página (edição + título), marque **usar pontuações ORES**,
   **Acompanhar agora**.
2. Revise as **Mudanças sinalizadas**; abra **Diferenças** em tudo o que parecer suspeito.

**Acompanhar o preço de uma matéria-prima em relação às notícias**
1. **Matérias-primas** — os feeds selecionados já se atualizam automaticamente em segundo plano;
   para o preço de uma página específica, adicione uma **regra de extração de preços** e clique em **Testar**.
2. Clique no cartão da série → leia o gráfico e a **correlação** com uma consulta de notícias.

**Mover (ou mesclar) o seu corpus para outra máquina**
1. **Configurações → Dados e cópia de segurança → Exportar / Cópia…** — escolha uma pasta/unidade de destino e
   uma senha; o corpus sai em fluxo como volumes criptografados + paridade (de qualquer tamanho).
2. Na outra máquina, **Configurações → Dados e cópia de segurança → Importar…** — aponte para essa pasta e
   restaure. A restauração é aditiva — ela complementa o corpus daquela máquina e nunca o
   substitui, então você também pode usá-la para *mesclar* dois corpora. Um arquivo único antigo
   `oo-backup-2` não exige nada de especial: a varredura de Importar encontra um em qualquer nível
   dentro da pasta indicada e o oferece como um item à parte, de modo que os backups antigos continuam restauráveis.

**Copiar a pasta inteira — uma forma de primeira classe de mover ou fazer backup**

As ferramentas do aplicativo existem para acrescentar o que uma cópia de arquivos não faz (um manifesto assinado, paridade que
repara um volume danificado, uma mesclagem aditiva de dois corpora, uma restauração seletiva). Elas
não são uma barreira pela qual você precise passar. Copiar a pasta de dados é um caminho com suporte em qualquer tamanho, e é
o caminho certo para mudar uma máquina por inteiro:

1. **Pare o aplicativo** — o botão de desligar na barra superior, ou Ctrl-C no terminal dele. Isto
   não é opcional: uma cópia feita enquanto ele roda pode pegar um WAL escrito pela metade.
2. Copie a pasta **data** inteira (§5.1 — `<app folder>/data/`, ou aquela para onde `OO_DATA_DIR`
   aponta). Não a pasta do aplicativo/código: o código pode ser reinstalado, os dados não.
3. Na outra máquina, coloque a pasta onde quiser e aponte `OO_DATA_DIR` para ela —
   ou, numa instalação nova, escolha essa pasta na etapa do primeiro lançamento (§5.1).

O corpus continua criptografado em repouso durante a cópia, e as chaves viajam dentro da pasta,
então **a senha é a única coisa que você precisa levar separadamente**. Desde 2026-08 os pesos
da IA local também ficam na pasta de dados, então a cópia os leva junto — e é isso que faz dela
uma verdadeira mudança da máquina inteira, e não apenas do corpus.

---

## 5. Referência técnica

### 5.1 Onde ficam os seus dados

Determinado por `src/paths.py`, nesta ordem de precedência:

1. **`OO_DATA_DIR`** se estiver definida (sempre prevalece).
2. **Checkout do código-fonte** — se o aplicativo roda a partir de um repositório gravável (dev/editável/instalação no
   `$HOME` do Qubes), os dados ficam em `<repo>/data/`.
3. **Por usuário** — caso contrário, XDG: `$XDG_DATA_HOME/open-omniscience` ou
   `~/.local/share/open-omniscience`.

O caso 2 é o normal para uma instalação feita com `install.sh`: o instalador clona uma
árvore gravável, então os seus dados ficam em `<app folder>/data/` e o caminho XDG do caso 3
nunca é criado. Não é um bug se você for procurá-lo e ele não existir.

**Escolher a pasta no primeiro lançamento.** Na primeira vez que você inicia o aplicativo —
depois das etapas de idioma e jurídica, antes de definir a senha — ele pergunta onde
o seu corpus deve ficar. Manter o padrão é um clique. Se você escolher outra
pasta (um disco externo, por exemplo), o aplicativo cria uma pasta chamada **`OOS data`**
dentro dela e registra a escolha em `oo.env` na raiz da instalação, que
`scripts/launch.sh` lê a cada início.

Duas coisas sobre essa etapa são deliberadas e vale a pena conhecê-las:

* **Ela só aparece numa instalação nova.** Quando já existe um corpus, o aplicativo se recusa
  a mudar a configuração, porque não consegue mover o que já está lá: as chaves,
  o registro de custódia e o depósito de modelos seguiriam a nova configuração enquanto o corpus
  ficaria para trás, e o início seguinte encontraria uma pasta vazia e ofereceria criar uma.
  Mover um corpus existente é a simples cópia de pasta descrita em §4 ("Copiar a
  pasta inteira") — pare o aplicativo, copie a pasta de dados, aponte `OO_DATA_DIR`
  para a cópia.
* **Escolher outra pasta encerra a configuração e pede que você inicie o aplicativo de novo.**
  Nada foi criado nesse momento; a pasta só passa a valer no início
  seguinte, então continuar na mesma sessão colocaria o corpus na pasta antiga
  enquanto a escolha registrada apontaria para a nova.

Você é avisado, não bloqueado, se a pasta for incomum: uma pasta que já contém um
corpus (continuar abre esse corpus em vez de criar um novo), um sistema de arquivos
em RAM (tudo o que for escrito ali se perde ao reiniciar), ou pouco espaço livre, com
o número. Só uma pasta em que o aplicativo realmente não consegue escrever é recusada.

**Se a unidade for desconectada.** Uma pasta escolhida dessa forma recebe um pequeno arquivo marcador,
`.oos-volume`, cujo identificador também é registrado em `oo.env` (`OO_DATA_VOLUME_ID`). O aplicativo
o lê a cada dois segundos enquanto roda. Se a unidade sumir:

* O aplicativo registra a desconexão no disco interno (em
  `~/.local/state/open-omniscience/`, já que não consegue escrever na unidade ausente).
  O pacote de diagnóstico leva esse registro, e o início seguinte o cita quando
  explica como a sessão anterior terminou.
* A coleta é pausada e uma janela pede que você reconecte a unidade em até 30 segundos.
  Se a mesma unidade voltar, o aplicativo reinicia para reabrir os seus dados (um
  corpus criptografado pede a senha de novo). Ele não pode simplesmente continuar: a conexão
  com o banco de dados é fixada quando o aplicativo inicia.
* Passados esses 30 segundos, uma segunda contagem regressiva fecha o aplicativo de forma limpa em mais 30
  segundos; **Fechar agora** faz isso na hora. Reconectar durante essa segunda contagem
  ainda faz o aplicativo reiniciar em vez de fechar.
* O que estava sendo escrito nos últimos instantes antes da desconexão pode se perder. O
  banco de dados em si continua consistente: o SQLite desfaz uma escrita inacabada na próxima
  vez que é aberto.

Se você iniciar o aplicativo com a unidade desconectada, ele não cria uma pasta vazia
no lugar dela: mostra uma página "A sua unidade de dados não está ligada", verifica
de novo a cada poucos segundos e abre o aplicativo assim que a unidade volta. Uma unidade
diferente montada no mesmo caminho é reconhecida como diferente (o marcador dela não
corresponde). Se você apagou a pasta de propósito, remova as linhas `OO_DATA_DIR` e
`OO_DATA_VOLUME_ID` de `oo.env` para recomeçar com um corpus novo e vazio.
A limpeza de emergência faz isso por você. Se o sistema montar a unidade num novo caminho
depois de reconectá-la, o aplicativo não consegue encontrá-la ali: feche-o e aponte `OO_DATA_DIR` em
`oo.env` para o novo caminho.

Nesse diretório você encontrará: `open_omniscience.db` (o corpus, SQLite/WAL),
`app_settings.json` (tema, limite de resultados), `custody_settings.json` (preferências
de custódia), as chaves de custódia, os dumps da Wikipedia baixados, eventuais instantâneos
`pre-restore-*.db` e `models/` — os pesos da IA local, que ficam dentro do próprio
diretório de dados do aplicativo e não na pasta pessoal de cada backend:

| caminho | o quê |
| --- | --- |
| `models/ollama/` | O depósito de modelos do Ollama (`OLLAMA_MODELS` aponta para cá) |
| `models/huggingface/hub/models--<org>--<name>/` | Os pesos do vLLM, uma pasta por repositório (`HF_HOME` aponta para `models/huggingface`) |
| `cache/` | Os caches de computação do servidor vLLM — kernels Triton, torch Inductor, o cache JIT da CUDA, as raízes de cache e de configuração do próprio vLLM. Criados na primeira execução, podem ser apagados com segurança (são recriados) e podem chegar a vários GB |
| `vllm_start_attempts.jsonl` | Cada início e cada saída do servidor vLLM, com as próprias palavras da falha. Guardado **aqui** e não dentro do ambiente do vLLM para que reinstalar o vLLM — a primeira coisa que a maioria das pessoas tenta quando um servidor não inicia — não apague o registro do motivo da falha |
| `vllm_failed_starts/` | O registro completo de cada um dos últimos inícios **com falha**. O registro do servidor em execução é sobrescrito pela tentativa seguinte, e um ciclo de novas tentativas o sobrescreve em menos de um minuto, então uma cópia é feita no momento em que se constata que um início falhou. Algumas centenas de KB no máximo |

Definir você mesmo `OLLAMA_MODELS`, `HF_HOME` ou qualquer uma das variáveis de cache
(`XDG_CACHE_HOME`, `TRITON_CACHE_DIR`, `TORCHINDUCTOR_CACHE_DIR`,
`CUDA_CACHE_PATH`, `VLLM_CACHE_ROOT`, `VLLM_CONFIG_ROOT`) sempre prevalece —
o aplicativo reexporta o seu valor em vez de sobrescrevê-lo. O redirecionamento vale apenas para
o **servidor**: instalar o vLLM continua usando o cache normal de wheels do pip, então
reinstalar não baixa de novo os vários GB que ele já tem. Os pesos baixados **antes** de 2026-08-04
continuam no `~/.cache/huggingface/hub/` do próprio Hugging Face; Configurações → IA informa
quais são e diz para onde movê-los, e nada é movido nem apagado por você.

### 5.2 Variáveis de ambiente

> **Nota de honestidade:** esta tabela lista o essencial para quem opera o aplicativo — ela **não** traz todas as
> variáveis de ambiente que o código pode ler (uma auditoria contou ~259 referências a variáveis de ambiente
> no código). Uma variável ausente desta tabela reflete a
> concisão do manual, não uma afirmação de que a variável não existe.

| Variável | Finalidade |
|---|---|
| `OO_DATA_DIR` | Substitui o diretório de dados (veja acima). |
| `OO_HOST` / `OO_PORT` | Endereço/porta de escuta (padrão `127.0.0.1:8000`). |
| `OO_AUTOSEED` | Preenche o catálogo mundial na primeira execução (ativado por padrão; `0` para desativar). |
| `OO_NO_SCHEDULER` | Defina `1` para nunca iniciar automaticamente o agendador em segundo plano; o aplicativo então inicia online em vez de em modo avião. A proteção de sockets do modo avião é instalada de qualquer forma (só `OO_AIRPLANE_SOCKET_GUARD=0` a deixa de fora), então ativar o modo avião mais tarde ainda bloqueia as conexões externas no nível do socket (as poucas exceções restantes estão listadas em SECURITY.md). |
| `OO_NO_INDEX` | Defina `1` para pular a indexação automática de Análises. |
| `OO_CUSTODY_ON_INGEST` | Padrão legado para o registro automático de custódia na ingestão (a preferência da interface o substitui depois de salva). |
| `OO_KEY_PASSPHRASE` | Criptografa em repouso as chaves privadas de custódia (AES-256-GCM via scrypt). Sem ela, a senha do banco de dados as protege; sem nenhuma das duas, as chaves são gravadas `0600` em texto claro e informadas honestamente como `plaintext-0600`. |
| `OO_FETCH_TIMEOUT` / `OO_FETCH_MIN_INTERVAL` | Ajustam o tempo limite do coletor ético e o intervalo mínimo por host. |
| `OO_LLM_MODEL` / `OO_OLLAMA_URL` (ou `OLLAMA_BASE_URL`) | Modelo local padrão e endpoint do Ollama. |
| `OO_ALLOW_BIG_SCANS` | Defina `1` para executar as varreduras do corpus inteiro em segundo plano numa máquina abaixo do piso de memória (veja [Memória numa máquina pequena](#55a-memória-numa-máquina-pequena--o-único-teto-real)). O veredito então informa que você o contornou. |
| `OO_CKPT_GATE_TIMEOUT_S` | Quanto tempo o checkpoint do WAL entre passagens espera pela porta de escritor único antes de registrar um salto honesto e seguir adiante (padrão `30`). `0` restaura a antiga espera sem limite (o checkpoint da própria proteção de armazenamento ainda espera no máximo 30 s pela porta de escrita, numa thread própria, de modo que uma retomada forçada continua vigiada). |
| `OO_STORAGE_GUARD` | Defina `0` para desligar a proteção de armazenamento (sem amostragem, sem pausa). A proteção pausa a coleta por conta própria quando o log de escrita antecipada (write-ahead log) do banco de dados passa de um limite calculado para a sua máquina ou quando a unidade está quase cheia, e a retoma por conta própria; "Retomar mesmo assim" no aviso força a coleta enquanto o limite ainda está valendo, e termina sozinho se o espaço livre cair demais ou não puder ser lido, se uma escrita falhar por falta de espaço ou se um segundo limite for ultrapassado. A mesma pausa segura, enquanto durar, a reindexação em segundo plano que conclui uma importação interrompida e a criação única dos índices da lista de artigos (as linhas deles no gerenciador de tarefas dizem isso, e elas continuam sozinhas; "Retomar mesmo assim" força a coleta, não estas). |
| `OO_DAMAGE_GUARD` | Defina `0` para desligar a pausa que se segue a um relatório do banco de dados sobre danos num dos seus arquivos de dados (o relatório em si continua registrado em `database-damage.json` na sua pasta de dados, e o aviso então diz que a pausa está desligada). Sem isso, um arquivo que o banco de dados declara danificado não recebe escritas da coleta, das etapas de manutenção nem da via da Wikipedia (cada uma apenas para o seu próprio arquivo) até que você inicie a coleta de novo (o arquivo da Wikipedia: até que você desligue e ligue de novo a busca na Wikipedia). Uma pausa definida pela verificação de início (veja `OO_BOOT_VERIFY`) só termina quando as tabelas citadas pela verificação voltam a ser lidas sem erro; qualquer outra pausa termina, e para de novo na primeira leitura com falha se o dano ainda estiver lá. Independente de `OO_STORAGE_GUARD`. |
| `OO_BOOT_VERIFY` | Defina `0` para desligar a verificação dos seus arquivos de dados executada no início, enquanto o aplicativo ainda está offline, após uma parada inesperada (e após uma verificação anterior ter ficado inacabada ou ter encontrado danos): cada tabela é lida uma vez com o `PRAGMA quick_check` do SQLite, uma tabela de cada vez, numa conexão somente leitura, de modo que a verificação não escreve nada por conta própria. Uma tabela, a lista de tabelas ou a verificação de páginas que relata dano é lida uma segunda vez numa nova conexão e só conta como dano quando a segunda leitura concorda: uma segunda leitura que difere, ou que não pode ser feita, deixa a tabela não verificada com o motivo, e nada é pausado nem reparado por causa disso. Num arquivo criptografado, quando não foi possível responder por uma tabela (o SQLCipher gera um erro genérico para muitas páginas danificadas), ela também pede uma vez a verificação de páginas do próprio SQLCipher (`PRAGMA cipher_integrity_check`, cerca de um segundo a cada 230 MB) e registra quais páginas falham na autenticação (um arquivo maior que 4 GiB não é submetido a essa verificação de páginas, porque ela lê os bytes errados além desse ponto; o registro diz isso e o arquivo não é declarado íntegro); um arquivo com páginas que falham está danificado, e um arquivo cujas páginas passam todas ainda não é declarado íntegro enquanto uma tabela ficar sem resposta. Uma página que não pôde ser lida de forma alguma (uma unidade com defeito) é contada à parte e não é, por si só, uma constatação, e sair do aplicativo enquanto essa verificação roda não gasta uma das três tentativas. A coleta espera até ela terminar; um arquivo que ela encontra danificado é pausado (veja `OO_DAMAGE_GUARD`), e iniciar a coleta de novo relê as tabelas que ela citou antes de liberar a pausa (para o arquivo da Wikipedia, desligar e ligar de novo a busca na Wikipedia faz isso). Uma verificação que não consegue terminar não é tentada de novo após três inícios seguidos, e o aplicativo diz isso (a suspensão dura por todos os inícios normais até a próxima parada inesperada do aplicativo, que é um novo motivo para verificar); isso nunca apaga uma constatação: um arquivo que uma verificação anterior encontrou danificado continua pausado até que as tabelas citadas sejam lidas sem erro (ou o arquivo seja substituído). O resultado de cada arquivo está em `database-damage.json` na sua pasta de dados. |
| `OO_BOOT_REPAIR` | Defina `0` para desligar o reparo de um arquivo de biblioteca danificado (e, com ele, a remoção descrita abaixo). Por padrão, quando a verificação de início (veja `OO_BOOT_VERIFY`) lê uma tabela do seu arquivo de biblioteca como danificada, o aplicativo repara o arquivo nesse início, enquanto ainda está offline e antes que a coleta escreva qualquer coisa: ele copia todas as linhas que ainda consegue ler, tabela por tabela, para um novo arquivo ao lado, reconstrói os índices e o índice de pesquisa, verifica o novo arquivo com a mesma leitura por tabela e só então passa a usá-lo. As linhas em páginas que não puderam ser lidas não estão no novo arquivo; o aviso diz quantas entradas foram copiadas e quantas não puderam ser lidas, e em quais tabelas estavam. As linhas cuja linha-mãe não pôde ser lida são mantidas, nunca removidas, e contadas por tabela; quando uma tabela, de outra forma, entregaria o número de uma linha perdida à próxima linha salva, o reparo acrescenta UMA linha de preenchimento marcada «(lost …)» no maior número perdido (é uma linha visível, e o índice de pesquisa a encontra por essa marca), e o aviso cita essas tabelas. Tudo o que o aplicativo salva espera enquanto ele trabalha (o reparo precisa da porta de escrita, que vem ativada por padrão: com `OO_WRITE_GATE=0` ele recusa e diz isso), e se algo mesmo assim foi salvo no arquivo enquanto a cópia era feita, a cópia é descartada e refeita no início seguinte em vez de ser colocada no lugar por cima desse salvamento. Ele precisa do espaço livre do arquivo inteiro mais o seu log mais a reserva que a proteção de disco mantém, e de uma unidade capaz de dar a um arquivo um segundo nome (um link físico, hard link); ele diz qual dessas coisas falta e não muda nada quando falta alguma. Só o arquivo de biblioteca é reparado, e só depois que a verificação deste início encontrou danos: os arquivos da Wikipedia e de leis são pausados como antes, mas não reparados, um arquivo encontrado danificado enquanto o aplicativo roda é verificado no início seguinte e reparado então se a verificação o confirmar, e uma tabela que a verificação não conseguiu ler não é uma constatação. **O arquivo danificado é mantido, não apagado:** o reparo lhe dá um segundo nome ao lado do novo arquivo, `<name>.damaged-<date and time>.<ending>` (com o seu log sob o mesmo nome e `-wal`), porque ele ainda pode conter linhas que a cópia não conseguiu ler, para uma ferramenta de recuperação. **O aplicativo remove esse único arquivo 30 dias depois de o novo arquivo ter sido lido sem erro pela primeira vez**, no primeiro início nessa data ou depois dela, nunca enquanto um reparo ou uma verificação estiver em andamento nem enquanto a biblioteca for de novo relatada como danificada; o aviso de reparo e o zip de Diagnóstico dizem o tamanho dele, onde está e a data, e depois da remoção dizem que ele foi removido e qual era o tamanho. Se a própria unidade não conseguiu ler uma página do seu arquivo de biblioteca (o aviso diz quantas páginas), o aplicativo não remove esse arquivo de forma alguma, porque uma unidade com defeito pode ser o motivo de as páginas não terem sido lidas: ele fica até que você mesmo o remova, e o aviso diz para verificar a unidade. Com `OO_BOOT_REPAIR=0` a remoção fica desligada e o aviso diz isso. Você mesmo pode removê-lo a qualquer momento. Ela apaga apenas o arquivo que o reparo separou (ele precisa estar na sua pasta de dados, ser um arquivo comum, ter exatamente esse nome e ser o mesmo arquivo registrado pelo reparo) e nada mais; se qualquer uma dessas condições não se cumprir, ela não remove nada, diz isso e não tenta de novo. Um reparo que começou e não terminou é tentado de novo no início seguinte; dois inícios seguidos que terminaram no meio de um reparo não são seguidos de um terceiro até que o aplicativo seja atualizado (o registro é `database-repair-attempt.json` na sua pasta de dados). O registro de cada reparo (a data, as contagens, o nome do arquivo e, quando ocorrer, a sua remoção) está em `database-damage.json`; ele guarda os dez últimos, e um arquivo mantido cujo registro saiu desses dez nunca é removido pelo aplicativo. |
| `OO_ARTICLE_INDEXES` | Defina `0` para deixar sem criar os dois índices da lista de artigos. Por padrão o aplicativo os cria uma vez, no primeiro início após uma atualização, enquanto ainda está offline: um para o filtro de idioma e outro para a ordenação por título, para que os dois continuem rápidos à medida que a biblioteca cresce (eles ocupam cerca de 190 MB a cada 1,5 milhão de artigos). Numa biblioteca grande numa unidade lenta a criação pode levar alguns minutos; ela aparece no gerenciador de tarefas como "Criando os índices da lista de artigos", tudo o que o aplicativo salva espera até que termine, e ela precisa de duas coisas que mede antes e sobre as quais avisa, sem começar, quando qualquer uma delas é insuficiente: cerca de 400 bytes de espaço livre por artigo na unidade onde está o seu arquivo de dados, e memória para a ordenação dos títulos (cerca de 300 bytes por artigo, mantidos na memória e nunca gravados num arquivo temporário, mais a memória livre que o aplicativo sempre reserva para si; ele informa os números). Um início que termina no meio da criação a recomeça; dois inícios seguidos que terminam no meio da criação (o computador ficou sem memória ou sem energia) não são seguidos de uma terceira tentativa até que o aplicativo seja atualizado, porque uma criação que derruba o próprio aplicativo não pode se tornar um início que nunca termina (o registro disso é `article-indexes-attempt.json` na sua pasta de dados; apagá-lo deixa o aplicativo tentar de novo, e sair do aplicativo da forma normal devolve a tentativa). Com o interruptor desligado, ou após uma recusa que se repete, cada início gasta uma fração de segundo comparando a versão do banco de dados com as suas tabelas. Com o interruptor desligado a lista funciona como antes, só que mais devagar nessas duas opções. |
| `OO_WAL_HIGH_MB` / `OO_DISK_RESERVE_MB` | Substituem os dois limites calculados da proteção de armazenamento por um número de MB: o tamanho do log de escrita antecipada a partir do qual a coleta pausa, e o espaço livre abaixo do qual ela pausa (padrão: calculado para a sua máquina; os limites aparecem no aviso que a proteção mostra no gerenciador de tarefas enquanto segura a coleta). |
| `OO_STORAGE_GUARD_TRIP_AFTER` / `OO_STORAGE_GUARD_RESUME_AFTER` | Quantas amostras consecutivas (com cerca de cinco segundos de intervalo) acionam e liberam a proteção (padrão `2` e `2`). |
| `OO_WRITE_GATE_WARN_S` | Registra um aviso, com o nome da thread que está segurando e uma pilha de chamadas, quando uma única escrita segura a porta por mais tempo do que isto (padrão `60`); o aviso é gravado quando a retenção é percebida, então o número dele é no mínimo o limiar e não a duração da retenção. Quando uma retenção dessas termina, o log recebe uma segunda linha, `write gate released after 61.3s by 'name'` (a duração real, com precisão de um décimo de segundo, no lugar de 61,3; retenções de menos de um segundo nunca a recebem). `OO_WRITE_GATE_WATCHDOG=0` desliga totalmente essa vigilância. |
| `OO_REINDEX_HOLD_TARGET_S` | Quanto tempo um lote de reindexação pode segurar a porta de escritor único antes de confirmar (commit) e deixar entrar um escritor que esteja esperando (padrão `10`). Vale para a reindexação em segundo plano dos artigos importados, para a tarefa de reindexação do corpus inteiro (quando `OO_REINDEX_COMMIT_BATCH` é maior que 1) e para a reindexação que conclui uma restauração. Ele confirma ainda mais cedo, no artigo seguinte depois que outra escrita entra na fila atrás dele, assim que o lote tiver segurado a porta por pelo menos um segundo (então uma retenção pode passar do alvo pelo artigo em andamento e pela confirmação, e um escritor sempre na fila custa à reindexação cerca de uma confirmação por segundo, e não uma por artigo). A largura do lote (`OO_IMPORT_REINDEX_COMMIT_BATCH`, `OO_REINDEX_COMMIT_BATCH`) continua sendo o teto, e com largura `1` cada artigo é confirmado sozinho, então não há lote para o alvo encerrar antes (o relatório da restauração e o progresso da tarefa de reindexação ainda citam o alvo em vigor). `0` é a regra antiga: confirmar apenas na largura do lote. Um valor que não seja um número de segundos igual ou maior que zero mantém o padrão. |
| `OO_HEAVY_TAIL_WAIT_S` | Quanto tempo o recálculo do resumo do Início e a via de manutenção em segundo plano esperam um pelo outro em vez de rodar ao mesmo tempo (padrão `900`). `0` espera indefinidamente. |
| `HTTPS_PROXY` | Encaminha o tráfego de saída (por exemplo, OpenTimestamps) por um proxy/Tor. |

### 5.3 Extras opcionais

Instale com `pip install -e ".[extra]"`:

- **`analysis`** — estatística, análises de palavras-chave/entidades, correlação com mercados.
- **`nlp`** — modelos spaCy para um reconhecimento real de entidades nomeadas em Análises.
- **`pqc`** — assinatura pós-quântica ML-DSA para a Cadeia de custódia.
- **`timestamping`** — ancoragem OpenTimestamps (Bitcoin).
- **`dev`** — ferramentas de teste/lint.

Se faltar um extra, o recurso que depende dele **degrada de forma visível** (um erro claro ou
um `503`, um status honesto de "não instalado") — ele nunca finge a capacidade em silêncio.

### 5.4 A API HTTP

O aplicativo é um servidor FastAPI em `127.0.0.1:8000`; a interface web é um único
`index.html` sem dependências, servido em `/`. O esquema legível por máquina fica em **`/openapi.json`**. As páginas interativas Swagger (`/docs`) e ReDoc
(`/redoc`) ficam **desligadas por padrão**: elas fazem o navegador buscar scripts, estilos e uma fonte em hosts
de terceiros, então um desenvolvedor que as queira inicia o aplicativo com `OO_API_DOCS=1`. Métricas Prometheus em `/metrics`. **Não há autenticação**, por concepção
(somente loopback, um único usuário). Todos os endpoints têm **limite de taxa** (aproximadamente: leituras
100/h, escritas/exportações 50/h, exclusões 20/h, importações em lote 10/h; `429` com
`Retry-After` quando o limite é ultrapassado).

Um inventário resumido (consulte `/openapi.json`, ou `/docs` com `OO_API_DOCS=1`, para o esquema oficial e sempre atual, e
`docs/ARCHITECTURE.md` para a descrição em texto):

**Núcleo e pesquisa** — `GET /api/health`; `GET /api/articles` (FTS + filtros);
`GET /api/articles/export` (csv|json); `GET /api/articles/{id}/view` (HTML offline);
`GET /api/sources`.

**Ingestão** — `POST /api/sources/seed-defaults`;
`POST /api/sources/{id}/ingest`; `POST /api/sources/{id}/ingest-email` (IMAP);
`POST /api/ingest` (uma única URL).

**Fontes e catálogo** — CRUD completo em `/api/sources/…` (incl. operações em lote, grupos,
grupos baseados em tags, metadados, descoberta, importação/exportação YAML, estatísticas, pesquisa); catálogo
CSV em `/api/catalog/sources`, `/export.csv`, `/template.csv`, `POST /import`.

**Agendador** — `GET /api/scheduler/status|config|targets`;
`PUT /api/scheduler/config`; `POST /api/scheduler/start|stop|run-now`.

**Banco de dados e backup** — `GET /api/database/stats|coverage|countries`;
`GET /api/database/backup` (instantâneo `.db` bruto; sob um nome que você listou em `OO_ALLOWED_HOSTS`, uma requisição que não indica de qual página vem precisa acrescentar o cabeçalho `X-OO-Download: 1`, como faz `curl -H "X-OO-Download: 1" …`; digitar o endereço num navegador, ou abrir um favorito, num nome desse tipo em HTTP simples não envia nada do que um navegador acrescentaria em loopback ou em HTTPS, então é recusado ali). Os backups são **criados** pelos motores
de fluxo contínuo: volumes criptografados + paridade em `POST /api/backup/v2/volumes/start` (+ `/restore`,
`/cancel`, `GET /volumes/status`) e a cópia de pasta para grandes volumes de dados em
`POST /api/backup/folder/start` (+ `/plan`, `/restore`, `/{action}`, `GET /folder/status`).
A restauração de um arquivo único mais antigo é a **mesclagem aditiva**:
`POST /api/backup/v2/restore/preview`, `POST /api/backup/v2/restore/commit`,
`GET /api/backup/v2/batches`. *(Os destrutivos `POST /api/database/restore` e
`/api/safety/restore/encrypted` foram removidos.)*

**Sistema e rede** — `GET /api/system/vitals|network|interfaces`;
`POST /api/system/network` (alternância do modo avião); `GET /api/system/doctor|lock-state`;
`POST /api/system/unlock|create-db|encrypt-db`. **Tarefas / gerenciador de tarefas** —
`GET /api/jobs`; `POST /api/jobs/dumps/reorder`; `POST /api/jobs/{id}/cancel`.

**Mapa-múndi** — `GET /api/timemap` (sinais de espaço-tempo; `?kinds`, janela `?start`/`?end`
em anos fracionários, `?hazards`, `?articles`, `?mentions`, `?days`); `GET /api/timemap/range`.

**Tags de data dos artigos** — `GET/POST /api/article-dates/article/{id}` (listar / extrair);
`POST /api/article-dates/{tag_id}/confirm|reject`; `POST /api/article-dates/index`;
`GET /api/article-dates/by-date`.

**Análises** — `GET/PUT /api/insights/filter`; `POST /api/insights/exclude|include`;
`GET /api/insights/status`; `POST /api/insights/reindex`;
`GET /api/insights/top|trending|trend|associations|context|map`; agregações
**Quando×Onde×Quem** do corpus inteiro em `GET /api/insights/who|where`.
**Enquadramento** — `GET /api/framing`.

**Pesquisa (omnibar)** — `GET /api/search/omni` (federação apoiada em índices sobre artigos,
palavras-chave, fontes, páginas vigiadas da Wikipedia e leis acompanhadas).

**Links** — `GET /api/links/shared` (quais artigos do conjunto compartilham links de saída, com
notas de independência); `GET /api/links/preview` (extração local de pré-visualização de link).

**Eventos da agenda** — `GET /api/events/calendars|feeds|imported`;
`GET /api/events/astronomy` (fases da lua calculadas localmente — nova, quarto crescente, cheia, quarto minguante — + equinócios/solstícios, verificados com
o almanaque) e `GET /api/events/climate` (conjunto de dados do El Niño incluído). **Contexto meteorológico** —
`POST /api/weather/context` (fatias de reanálise Open-Meteo guiadas pelo corpus, com consentimento).

**Mercados e matérias-primas** — `/api/markets/rules` (CRUD + `/run`),
`/api/markets/overview|series|feeds`, `/api/markets/feeds/{key}/import`,
`/import-all`, `/import-url`; `/api/commodities/{symbol}/prices` (+ `/import-csv`,
`/correlation`).

**Governos** — indicadores do Banco Mundial por país + o mapa coroplético, somente leitura
exceto a única busca consentida: `GET /api/governments/indicators|map|country/{iso}`;
`POST /api/governments/load-standard` (+ `/load-standard/status`, uma tarefa em segundo plano).
**Direito mundial** — leis/diários oficiais/registros de propriedade intelectual acompanhados, um espelho de pesquisa (nunca aconselhamento
jurídico): `GET /api/law/status|documents|documents/{id}|documents/{id}/view|changes`;
`POST /api/law/documents` (adiciona um documento por URL — buscado imediatamente);
`DELETE /api/law/documents/{id}` (para de acompanhar; o histórico é mantido); `POST /api/law/track`
(busca agora todos os documentos vigiados) e `/api/law/seed` (preenche de novo o catálogo mundial).
Um documento acompanhado torna-se um artigo de primeira classe do corpus, pesquisável (Quando×Onde×Quem,
palavras-chave), ao lado das notícias coletadas, com o seu histórico de alterações como uma camada vinculada.

**Wikipedia** — `GET /api/wiki/status|pages|changes`; `POST /api/wiki/pages`,
`/track-now`, `/pages/{id}/track`; `GET /api/wiki/revisions/{id}`;
`GET /api/wiki/languages` (uma lista **plana, com os idiomas da interface primeiro**, cada opção começando pelo
nome nativo; `region` é mantido apenas como metadado descritivo — sem `groups` por continente;
`?scope=dumps` acrescenta estimativas de tamanho `~GB` em linha); dumps em `/api/wiki/dumps…`.

**Cadeia de custódia** — `POST /api/custody/log`; `GET /api/custody/{item}` (+
`/verify`); `POST /api/custody/verify`; `GET /api/custody/export`;
`GET /api/custody/providers`; `POST /api/custody/anchor`;
`GET/PUT /api/custody/settings`; `POST /api/custody/reconcile` (uma entrada INGEST que
não pôde ser gravada quando o seu artigo foi armazenado entra numa fila e é gravada mais tarde, ao fim
da próxima passagem de coleta enquanto o registro automático estiver ativado, marcada como tardia nos seus próprios metadados assinados --
a aba Cadeia de custódia as conta, e o seu
botão "Procurar entradas de ingestão ausentes" conta as lacunas mais antigas sem registrar nada
até que você clique em "Registrá-las, marcadas como tardias"). **Evidência** — `POST /api/reports/evidence`
(+ `/verify`).

**LLM (Ollama local)** — `GET /api/llm/health|models`; `POST /api/llm/generate`;
`POST /api/llm/articles/{id}/summarize|translate`.

**Outros** — `/api/analysis/*` (testes t, correlação, ANOVA, …);
`/api/keywords/*` (utilitários de extração); `/api/monitoring/health|anomalies`;
`POST /api/verify/image-metadata` (EXIF/GPS).

### 5.5 Usar pelo Tor

O aplicativo funciona pelo Tor (modo de coleta Protegido → um proxy Tor que você executa), com um
alcance honestamente menor — medido, não suposto (registro real de 2026-06-12: 32 de 50
fontes padrão importadas pelo Tor numa passagem):

- **Recusas por conexão são normais, não fatais.** Alguns hosts recusam algumas
  saídas do Tor: na mesma execução, 21/28 séries do FRED foram importadas enquanto outras falharam.
  É por isso que as falhas de feed trazem um **veredito que leva em conta o transporte** — *recusado*
  ("conexão recusada/reiniciada — pelo Tor isto costuma ser a recusa de uma única
  saída; uma nova tentativa frequentemente cai num circuito diferente") não é *robots
  proíbe* (a política declarada do host, que respeitamos e nunca tentamos de novo nem
  contornamos), não é *série extinta* (HTTP 404 — a entrada do catálogo precisa de uma
  substituta; tentar de novo não adianta), não é *inacessível*. Falhas
  passageiras são tentadas de novo uma vez automaticamente; o botão **Repetir feeds com falha**
  executa de novo exatamente as que, honestamente, podem ser repetidas.
- **O bloqueio do Tor por um host é escolha do host.** Nós o mostramos; nunca contornamos
  robots, bloqueios ou CAPTCHAs. Prefira endpoints oficiais que tolerem o Tor quando
  existirem.
- **O download de modelos não funciona pelo Tor.** O Ollama baixa os seus modelos pela internet
  aberta (clearnet) através do seu próprio processo (instalar/baixar em **Configurações → IA**); um caminho
  pela clearnet que funcione é um pré-requisito declarado para baixar um modelo. Depois de baixado, a inferência
  é em loopback e não é afetada. *(Um kit de LLM offline empacotado está planejado, ainda não foi lançado.)*
- **Se a instalação do vLLM for interrompida no meio**, quase sempre é um download que estourou o tempo
  limite num dos wheels muito grandes — só o torch tem cerca de 500 MB. A mensagem o
  cita, e os wheels já baixados ficam em cache, então iniciar a instalação de novo retoma
  em vez de começar do zero. Numa conexão lenta o bastante para continuar falhando, aumente
  `UV_HTTP_TIMEOUT` (em segundos) antes de abrir o aplicativo.
- **Se o servidor vLLM inicia e morre repetidamente**, o motivo fica registrado, quer
  você estivesse olhando ou não: cada início e cada saída vão para
  `vllm_start_attempts.jsonl` com as próprias palavras da falha, e o registro completo de
  cada um dos últimos inícios com falha é guardado em `vllm_failed_starts/` — ambos no
  diretório de dados, de modo que reinstalar o vLLM não os apaga. Os dois vão junto na
  exportação **Diagnóstico → todos os diagnósticos (all diagnostics)**, então a resposta está no pacote, e não é
  algo que você precise flagrar ao vivo.
- **O anonimato continua sob a sua responsabilidade**: o modo Protegido não pode garantir
  anonimato — você executa o proxy e confia nele; a parte do aplicativo é encaminhar as suas buscas
  na web por ele com um User-Agent genérico, exceto nas requisições de API e de dumps
  aos servidores da Wikimedia, que continuam identificando a ferramenta (a política de API da Wikimedia
  pede isso). A coleta da caixa de correio de newsletters, a ancoragem OpenTimestamps e
  os downloads da IA local conectam-se diretamente.

---

### 5.5a Memória numa máquina pequena — o único teto real

O aplicativo já se reduz sozinho numa máquina pequena: abaixo de **4 GB de RAM**, ou com
menos de **1 GB livre**, ele usa um cache de banco de dados menor e menos conexões
no pool, limita quantas fontes busca ao mesmo tempo e **pausa as varreduras do
corpus inteiro em segundo plano** (qualificação de fontes). Ele avisa isso, com os
números, ao lado do estado da coleta em Configurações → Avançado → Coleta.

**Dizendo o custo em voz alta:** numa máquina com um corpus grande e pouca memória
livre, isso pode significar que a qualificação de fontes nunca roda ali. Esse é o custo
da configuração, não uma falha. Para executá-las mesmo assim, inicie o aplicativo com
`OO_ALLOW_BIG_SCANS=1` — o veredito então informa que você o contornou, e
continua informando que a máquina é pequena, porque o contorno muda o que o
aplicativo *faz*, nunca o que ele *mediu*.

#### Uma visualização pesada para antes de poder derrubar o aplicativo

As leituras analíticas pesadas (a maioria das visualizações de Análises, o Observatório, as fontes
mais citadas, o pacote de diagnóstico) já rodam com um limite de tempo. Elas também
vigiam a memória disponível enquanto o banco de dados lhes entrega as linhas. Se ela cair até o
piso da proteção de memória (**256 MB** por padrão, `OO_MEM_GUARD_AVAIL_MB`), a leitura
é interrompida e a visualização diz por quê, com os números: *"stopped this read after
12s: the machine was nearly out of memory (180 MB available, at or below the
256 MB floor the memory guard uses) ..."* (leitura interrompida após 12 s: a máquina estava quase sem memória — 180 MB disponíveis, no piso de 256 MB usado pela proteção de memória ou abaixo dele). Uma leitura pedida quando a memória
já está tão baixa não começa, e diz *"did not start this read"* (esta leitura não foi iniciada)
em vez disso. Abra a visualização de novo quando a memória se recuperar; nada se perdeu,
porque uma leitura não altera nada.

**O que ela não faz:** é uma parada, não um teto. Ela vê o que cresce enquanto as linhas
estão sendo lidas, que é onde cresce uma visualização que carrega uma tabela inteira, e
nada mais. `OO_READ_MEMORY_STOP=0` a desliga sem mexer na proteção.

#### Quando a memória continua esgotada, o aplicativo para sozinho e diz isso

A proteção de memória pausa novas coletas quando a memória está curta. Uma pausa não
devolve o que o aplicativo já tem em mãos, então numa máquina pequena a memória pode ficar no
piso por muitos minutos e então o sistema operacional mata o aplicativo sem
dizer por quê. Agora o aplicativo se encerra por conta própria em vez disso. Ele só faz isso quando **todas**
estas condições se cumprem: a proteção ficou acionada durante todos os últimos **5 minutos**
(`OO_MEM_STOP_WINDOW_S`), pelo menos nove em cada dez das suas leituras ficaram em
**64 MB** disponíveis ou menos (`OO_MEM_STOP_AVAIL_MB`), nenhuma ficou acima de 128 MB, nenhum intervalo entre
leituras foi maior que um décimo da janela (30 s), e este aplicativo ocupa pelo menos um terço
da memória da máquina (se outra coisa a ocupa, parar não liberaria nada,
e o aplicativo não para). Uma recuperação, mesmo breve, ou clicar em iniciar ou
retomar esvazia a janela.

Antes de parar, ele guarda o que sabe: um instantâneo do que cada thread estava
fazendo, uma linha no registro de sessões e `memory_stop.json` ao lado dos seus dados
(números e nomes de etapas, no máximo 8 KB). Depois ele se encerra pelo mesmo caminho que
o botão de desligar. Os seus dados salvos não são tocados; ele primeiro espera até um minuto
que termine uma importação em andamento, uma tarefa em segundo plano que esteja segurando o corpus ou uma escrita no banco de dados
em curso (uma restauração ou uma mudança da unidade de dados é registrada como em andamento, mas
não é esperada como tal), diz no registro se ainda havia uma, e o que não pôde
terminar nesse tempo fica inacabado.
Enquanto isso acontece, o gerenciador
de tarefas diz *"O aplicativo está parando por conta própria porque a memória continuou esgotada"*.
No início seguinte, a linha **Sessões** da aba Sistema diz *"Parou por conta própria —
a memória continuou esgotada"* (passe o mouse para ver a ressalva), uma mensagem única diz o
mesmo, e o zip de Diagnóstico leva o registro. **O que termina é o que estava
rodando; você o inicia de novo.** `OO_MEM_STOP=0` desliga a parada e mantém a
pausa.

#### Por que o aplicativo não pode simplesmente limitar a própria memória

Não há forma honesta de um programa impor a si mesmo um teto de memória:

- **`RLIMIT_RSS` é ignorado pelo Linux.** Ele existe na API e não faz nada.
- **`RLIMIT_AS` limita o *espaço de endereçamento*, não a memória em uso.** Bibliotecas que este aplicativo
  usa (DuckDB, numpy) reservam muito mais espaço de endereçamento virtual do que chegam a
  tocar, então um limite de espaço de endereçamento gera `MemoryError` em código sem relação muito
  antes de o processo ficar realmente grande. O aplicativo deliberadamente não define nenhum dos dois, e um
  teste faz a compilação falhar se algum deles for acrescentado.

#### O teto que funciona: executá-lo num cgroup

No Linux com systemd, inicie o aplicativo com um limite rígido de memória:

```bash
systemd-run --user --scope -p MemoryMax=3G -p MemorySwapMax=0 \
  ~/open-omniscience/scripts/launch.sh
```

**O que isso garante, honestamente:** transforma um *travamento da área de trabalho* num *reinício
limpo do aplicativo*. Sem limite, uma máquina que fica sem memória usa a swap até ficar
inutilizável para tudo — o navegador, o terminal, a área de trabalho — e você pode
ter de desligá-la e ligá-la de novo. Com um limite, o kernel mata **este aplicativo** em vez disso, e
só este aplicativo.

**O que isso custa:** o aplicativo é morto no meio do trabalho, sem chance de arrumar as coisas.

**Por que o seu corpus está seguro mesmo assim:** o banco de dados roda em modo WAL com
`synchronous=NORMAL`, então uma morte só pode perder trabalho que nunca foi confirmado.
Tudo o que foi confirmado está no disco, e o log de escrita antecipada é reaplicado na próxima
vez que você desbloquear. **Nada do que você já tinha coletado se perde.**

Um **backup** interrompido dessa forma é outra história: ele fica incompleto.
Mas ele não é aceito como confiável em silêncio — cada volume leva uma soma de verificação no
manifesto, e a própria etapa de verificação do backup confere todas elas e cita as que
estão faltando ou não correspondem. Execute uma verificação (ou simplesmente faça o backup de novo)
antes de confiar num backup que foi interrompido.

Escolha `MemoryMax` em torno de **60–75 % da RAM total**, deixando espaço para a
área de trabalho e o navegador. `MemorySwapMax=0` é a metade que impede a sobrecarga de swap:
sem ela, o aplicativo ainda pode arrastar a máquina pela swap até ela quase parar antes de o limite ser
atingido.

Se você não usa systemd, o mesmo está disponível pelo Docker/Podman
(`--memory=3g --memory-swap=3g`) ou por um `memory.max` simples do cgroup v2.

#### Depois de uma falha: o que o próximo início pode lhe dizer

Quando o aplicativo é morto ou falha, a janela do lançador agora continua aberta e diz
como ele terminou: `SIGKILL` é a marca habitual de um eliminador por falta de memória. Uma parada
comum (o próprio botão Parar do aplicativo, fechar a janela, encerrar a sessão) fecha a
janela como antes.

O início seguinte então diz como a sessão anterior terminou, em **Configurações →
Avançado → Diagnóstico → Análise da sessão** e em `session-forensics.json`
dentro do arquivo de Diagnóstico, a partir de qualquer uma destas testemunhas que tenha respondido:

- o registro do lançador sobre o status de saída (`diagnostics/launcher_exits.jsonl`);
- o log do kernel, que cita as mortes por falta de memória feitas pelo próprio kernel;
- as linhas de log dos eliminadores de memória em espaço de usuário (systemd-oomd, earlyoom,
  nohang) e do systemd-coredump que citam o aplicativo. Elas nunca aparecem no
  log do kernel, e o systemd-oomd cita o cgroup do aplicativo em vez do seu processo;
- um rastreamento de falha de cada thread quando o código nativo aborta
  (`diagnostics/crash_trace.log`).

As leituras de log são locais e somente leitura, e só guardam as linhas sobre este aplicativo.
`OO_NO_KERNEL_LOG=1` as desliga; `OO_CRASH_TRACE=0` desliga o rastreamento.
Os eliminadores de memória escrevem no journal do sistema, que só os membros de `adm` ou
`systemd-journal` (`wheel` no Fedora) podem ler; quando o seu usuário não pode, o relatório
diz isso em vez de dizer que o log está vazio. Sem nenhuma testemunha, o relatório
diz que o fim é desconhecido, nunca que foi limpo.

O mesmo relatório diz de que era composta a memória no pico da sessão. Quando
esse pico ocorreu com a memória já curta demais para ler o heap de C com segurança, o que
costuma acontecer logo antes de uma falha por falta de memória, ele também mostra o pico
anterior mais recente que conseguiu lê-lo, com o tamanho e o horário desse pico. Ele também diz
o que cada thread estava fazendo (o nome, o código do aplicativo que executava e a CPU
que usava) em dois tipos de momento: quando a memória disponível caiu abaixo de 15% da RAM
(no máximo 1 GB), primeiro no momento da travessia e de novo a cada nova mínima, e quando o
aplicativo criou um milhão ou mais de objetos Python em cinco segundos, no máximo uma vez
a cada cinco minutos. Os oito instantâneos mais recentes são guardados em
`session_pressure.json` na pasta de dados, e ficam neste computador como
o restante do diagnóstico.

## 5.6 Limites conhecidos e divulgações honestas

Honestidade por construção significa dizer o que a ferramenta *não consegue* informar, e não só
o que ela consegue. Estes são os limites permanentes dos métodos (a "varredura de
divulgação" da audit-07). Nenhum deles é um bug; cada um molda a forma de ler um resultado.

- **As contagens de palavras-chave/tendências são léxicas, não semânticas.** Elas medem a frequência
  com que as palavras aparecem, não o que se quis dizer. Negação ("não é uma crise"), citação,
  sarcasmo e ironia são contados ao pé da letra. Volume é cobertura, nunca
  importância nem verdade.
- **Sentimento/tom é o VADER, um método baseado em léxico inglês.** As pontuações de artigos
  que não estão em inglês não são confiáveis; as telas de Sentimento e de Enquadramento divulgam isso e
  mostram a parcela pontuada em inglês. O tom é um sinal mensurável, nunca um veredito
  de que um veículo é tendencioso.
- **Resumos/traduções de LLM são artefatos do modelo.** Um modelo local pode ser
  fluente e estar errado. Cada célula gerada traz o rótulo "verifique com o artigo
  armazenado"; trate o resultado como uma pista e confira-o com o texto original
  que você coletou.
- **Um artigo longo é dividido, não cortado.** A janela de contexto de um modelo é finita. Quando
  você pede um resumo ou uma tradução de um artigo que não cabe nela, o
  app o divide nos limites de parágrafo e processa cada parte — uma tradução é
  a junção das partes, e um resumo é o resumo de cada parte, depois resumidas
  em conjunto. Em ambos os casos o resultado diz isso ("traduzido em N partes", "resumo
  hierárquico sobre N partes"), porque um resumo em duas etapas é um artefato diferente
  de um feito numa só passada, e você deve saber qual está lendo. Ele nunca para no meio
  do caminho em silêncio: uma tradução truncada parece exatamente igual a uma completa.
  As varreduras em segundo plano (a extração de quem/onde/quando) TRUNCAM, sim, artigos longos, e
  registram que o fizeram — "analisados os primeiros N de M caracteres" — para que uma extração
  pobre nunca seja confundida com um artigo pobre.
- **A IA em segundo plano é uma única fila, e o seu trabalho vem primeiro.** As varreduras que você ativa
  rodam uma de cada vez no único backend local, em vez de disputá-lo.
  Tudo o que você mesmo pede — uma tradução em massa, uma execução manual de varredura — pausa
  essa fila enquanto dura, e ela retoma sozinha depois; nada perde
  seu lugar. Numa máquina em que a inferência local é inviável, a fila fica desligada por
  padrão, com o motivo informado, e você ainda pode ligá-la.
- **O app trabalha só com texto.** Ele analisa o texto dos artigos. As imagens têm apenas
  transparência de EXIF/metadados (nenhuma alegação forense/de deepfake); não há análise de áudio ou vídeo.
  Uma alegação que existe apenas num vídeo ou numa imagem está fora do que a ferramenta
  consegue ver.
- **Japonês e tailandês precisam do extra opcional `[segmentation]`.** A extração de palavras-chave
  depende da tokenização por espaços, a menos que um segmentador de palavras esteja instalado. O chinês é
  segmentado em toda instalação (jieba, uma dependência central desde a 0.4); a análise de palavras-chave
  em japonês e tailandês praticamente não funciona sem o extra (janome, pythainlp), mesmo
  que a interface seja oferecida nesses idiomas, e a pesquisa em japonês só é dividida em palavras
  com o sudachipy do extra. O conjunto **gerenciado**
  (segmentado por espaços, com uma lista de palavras vazias) é definido em
  [`src/analytics/managed.py`](../src/analytics/managed.py); a *profundidade analítica* varia
  conforme o idioma, e as escritas sem segmentação são a maior lacuna atual.
- **Viés de sobrevivência dos hosts permissivos.** Como o robots.txt é fail-closed (fecha em caso de falha), o
  corpus super-representa sites que *permitem* rastreamento e
  sub-representa estruturalmente o jornalismo com paywall ou que restringe rastreamento. Isso não pode ser
  "corrigido" de forma ética — é atenuado dando preferência a APIs/arquivos oficiais e é
  divulgado aqui para que você leia a cobertura de acordo.
- **O seu registro começa quando você começou a coletar.** As tendências e os sinais de "em alta"
  ficam limitados à sua janela de coleta; a ferramenta não tem histórico de antes de você
  começar. Os dumps da Wikipedia e os (futuros) arquivos estendem o passado; fora isso, leia
  os resultados de um corpus jovem com as ressalvas de n exibido.
- **A Wikipedia carrega seus próprios vieses sistêmicos.** A Wikipedia acompanhada/ingerida
  importa os desvios editoriais e de cobertura, bem documentados, de cada edição.
  As fontes por edição (`xx.wikipedia.org`) a mantêm filtrável, e ela pode ser
  triangulada como qualquer outra fonte — nunca um oráculo.
- **O viés de seleção do catálogo é medido, não escondido.** O catálogo de fontes é um
  conjunto curado por pessoas, com uma descentralização dos EUA em andamento; a visão **Cobertura mundial**
  mostra quais países estão e quais não estão representados, para que você veja a forma
  do que está (e do que não está) coletando.

---

## 6. Solução de problemas

- **A página não carrega.** Confirme que o processo está rodando e escutando em
  `127.0.0.1:8000` (ou no seu `OO_HOST`/`OO_PORT`). O indicador de saúde no cabeçalho passa a
  `offline` se a API não estiver acessível.
- **A pesquisa está vazia.** Você ainda não coletou nada — **fique online** com o botão do
  avião (um único pop-up de consentimento) e a coleta começa automaticamente; o caminho manual é
  **Configurações → Avançado → Coleta → Buscar feed**.
- **Uma ingestão não armazenou nada.** Isso muitas vezes é correto e ético: a página pode estar
  bloqueada pelo `robots.txt` (fail-closed), ter limite de taxa, ser uma duplicata ou não ter
  corpo extraível. O balanço do resultado diz qual foi o caso.
- **Os controles de Análises/Mercados estão faltando ou dando erro.** O extra `[analysis]`
  não está instalado — execute `install.sh` de novo (o extra de análise é instalado por padrão).
- **O indicador do LLM diz offline.** O Ollama não está rodando/acessível; inicie-o ou defina
  `OLLAMA_BASE_URL`. Resumir/traduzir retornam um `503` claro quando ele está indisponível.
- **A custódia mostra "solicitado, biblioteca não instalada".** Instale o extra `pqc` e/ou
  `timestamping`; o estado efetivo muda assim que a biblioteca estiver presente.
- **A restauração recusou meu arquivo / a prévia não deixa Aplicar (Apply).** É proposital — o arquivo precisa ser um
  backup genuíno do Open Omniscience, e **Aplicar** fica desativado se a verificação
  preparada falhar. O seu corpus atual não é tocado em nenhum dos casos; a restauração só
  *acrescenta*, nunca substitui.
- **O dump da Wikipedia é enorme.** O `enwiki` tem dezenas de GB. Use **Estimar tamanho (Estimate size)** primeiro;
  a maioria das edições é bem menor, e você não precisa de um dump para acompanhar alterações.

---

## 7. Glossário

- **Corpus** — o seu banco de dados SQLite local com os artigos coletados.
- **Proveniência** — a origem armazenada de cada item (fonte, URL, URL canônica,
  hash do conteúdo, hora da busca), usada para deduplicação e confiança.
- **FTS5** — a pesquisa de texto completo do SQLite, que sustenta as consultas booleanas.
- **Busca ética** — o caminho único de busca, que respeita o robots.txt e tem limite de taxa.
- **Cadeia de custódia** — registro somente de acréscimo, encadeado por hash e assinado, que comprova a
  integridade, a proveniência e o horário de um item.
- **Pacote de provas** — uma exportação assinada, com raiz de Merkle e verificável offline, de
  artigos selecionados.
- **OpenTimestamps** — um modo de ancorar um hash no Bitcoin como prova independente de que
  algo "existia no mais tardar" em um bloco.
- **ML-DSA** — esquema de assinatura pós-quântica FIPS-204 (usado no modo *híbrido*
  junto com o Ed25519).
- **ORES** — o serviço de ML da Wikimedia que pontua edições quanto a dano / boa-fé.
- **PMI** — informação mútua pontual (pointwise mutual information); classifica o quanto dois termos coocorrem
  além do acaso (o "mapa mental" de Análises).
- **VADER** — um avaliador de tom/sentimento baseado em léxico (a visão de "enquadramento" de Análises).

---

*Veja também:* [QUICKSTART](QUICKSTART.md) · [CHAIN_OF_CUSTODY](USER_MANUAL.md) ·
[INSIGHTS](USER_MANUAL.md) · [MARKETS](USER_MANUAL.md) · [WIKIPEDIA](USER_MANUAL.md) ·
[DATABASE](ARCHITECTURE.md) · [API_DOCUMENTATION](ARCHITECTURE.md) ·
[SECURITY](SECURITY.md) · [PRODUCT_SYNTHESIS](DESIGN.md) ·
[OPEN_QUESTIONS](archive/roadmaps/DESIGN_MEMORY_pre-0.2.md).

*© 2026 Ideotion — feito para o jornalismo investigativo, com honestidade. GPLv3.*

---

# Aprofundamento dos recursos

Referência detalhada de cada ferramenta, consolidada a partir dos antigos guias por recurso. O passeio das Partes 1–6 acima continua sendo a orientação mais rápida; esta parte traz os detalhes.

**Nesta parte:**
- [O briefing de Início — inteligência em "cartões" honestos](#o-briefing-de-início--inteligência-em-cartões-honestos)
- [Integridade das fontes e antiamplificação](#integridade-das-fontes-e-antiamplificação)
- [Anotações de fontes compartilhadas — assinadas, portáteis, federadas pela confiança](#anotações-de-fontes-compartilhadas--assinadas-portáteis-federadas-pela-confiança)
- [Análises — análise de palavras-chave e entidades](#análises--análise-de-palavras-chave-e-entidades)
- [Acompanhamento de alterações da Wikipedia](#acompanhamento-de-alterações-da-wikipedia)
- [Direito mundial — acompanhamento de alterações de leis, diários oficiais e PI](#direito-mundial--acompanhamento-de-alterações-de-leis-diários-oficiais-e-pi)
- [Mercados: inteligência financeira, de bolsas de valores e de commodities/terras raras](#mercados-inteligência-financeira-de-bolsas-de-valores-e-de-matérias-primasterras-raras)
- [Cadeia de custódia](#cadeia-de-custódia)


---

## O briefing de Início — inteligência em "cartões" honestos

> **Status:** `0.06` Fase A (a espinha dorsal da interface) — entregue e testada. O plano em fases
> está em [`ROADMAP.md` → "0.06 — The Intelligence Layer"](archive/roadmaps/DESIGN_MEMORY_pre-0.2.md); o
> *o quê e porquê* em [`ROADMAP.md`](archive/roadmaps/DESIGN_MEMORY_pre-0.2.md).

A aba **Início** deixou de ser apenas estatísticas de relance. Ela é um **feed de triagem**: o
app coleta e mede em segundo plano e depois apresenta *possíveis matérias* como
**cartões — exibidos na tela como "Pistas"** (este capítulo diz "cartão" para o mecanismo
interno; o rótulo na interface é "Pista"). O app faz a coleta; **quem julga é você**. Cada cartão
é **um sinal mensurável + os links de evidência + uma ressalva**, classificado num grupo
editorial, e é apresentado como um **cartão de dois lados que se vira** (frente = a pista; verso = ressalva +
método + evidência + "Abrir o corpus").

Um cartão **mostra um sinal; ele nunca emite um veredito.** Não existe "tendencioso", nem
"propaganda", nem "verdadeiro/falso", e — por design e *imposto no código* — **nenhuma pontuação
composta de confiança** (veja "Salvaguardas de honestidade" abaixo).

---

### O que você vê

O briefing agrupa os cartões em **grupos** (na ordem de exibição):

| Grupo | Significa | Uso editorial |
|---|---|---|
| **Em alta** | algo está se movendo / é novo | candidatos a pauta |
| **Sobrecontado** | as fontes concordam rápido demais / de forma uniforme demais | desmontar o coro |
| **Subcontado** | algo se moveu, mas pouca gente/ninguém cobriu | revelar a lacuna |
| **A investigar** | as fontes ou os dados divergem | aprofundar |
| **Verificar o enquadramento** | o mesmo acontecimento enquadrado de formas opostas | verificar a alegação |
| **Continuar a observar** | uma mudança que merece atenção (por exemplo, um registro remodelado) | monitorar |
| **Contexto** | pano de fundo / autoauditoria / fatos permanentes | contextualizar |
| **Integridade dos dados** | sinais de higiene sobre o próprio corpus | corrigir o pipeline |

A tríade por trás deles é o motor: **convergência → sobrecontado**, **divergência →
investigar/desmentir**, **ausência → subcontado**.

Cada Pista (o nome na tela de um cartão do briefing) mostra o seu **título**, um
**resumo** de uma linha e o **sinal medido** (por exemplo, `growth_ratio = 4.2`, `n=6`) na
**frente**. **Clique nele (ou pressione Enter) para virá-lo:** o **verso** traz a
**ressalva**, o **método** (exatamente como o número foi calculado e o que ele *não*
significa), por que ele foi disparado, os **links de evidência** de volta ao seu corpus e um botão **"Abrir o corpus
↗"**. A ressalva está no DOM por padrão, na face de trás, de igual peso, logo ao lado da
ação — nunca atrás de um interruptor de interface calma. É esse o ponto: **a transparência é a
interface.**

> **Vista igualitária.** Nesta versão cada fonte é contada uma vez e **nenhuma fonte é
> desamplificada**. A camada de integridade das fontes / antiamplificação (agrupar
> enxurradas coordenadas em atores únicos, ponderar pela novidade) é a próxima fase e é
> **guiada pelo usuário** — o app vai *propor*, você vai *decidir*. Até lá o
> briefing é, honestamente, a visão bruta de tratamento igual.

---

### O ciclo cartão → rascunho → boletim

O ciclo que dá retorno é visível desde o primeiro dia:

1. Em qualquer cartão, clique em **+ Adicionar ao rascunho**.
2. Abra o painel **Rascunho de boletim**; acrescente sua própria nota a cada cartão fixado.
3. **Exportar Markdown** (ou **Copiar**). Cada afirmação sai **com seus links de fonte,
   método e ressalva** — jornalismo reproduzível por design.

Para uma cópia *assinada e à prova de adulteração* dos artigos de base, exporte um **pacote
de provas** em **Provas e custódia** — os comprovantes podem acompanhar a sua edição.

---

### Como os cartões são produzidos (Briefing v0)

Cada cartão é feito por um **produtor**: uma função `corpus → [Card]`. Os produtores combinam
análises que *já retornam números reais* — nada é inventado. Um produtor a quem
faltem as entradas ou uma dependência opcional `[analysis]` **não retorna nada e registra
o porquê** (degradação ruidosa); ele nunca fabrica um cartão.

| Cartão | Grupo | Baseado em | Status |
|---|---|---|---|
| **“X” está em alta** | em alta | `insights.trending` (razão entre o período recente e o anterior) | agora |
| **Enquadramentos divergentes** | verificar o enquadramento | tom VADER por fonte de um termo em alta | agora¹ |
| **Registro remodelado** | continuar a observar | detecção de edições grandes/sinalizadas na Wikipedia | agora |
| **Preço ↔ narrativa (Price ↔ narrative)** | contexto | correlação honesta do scipy (coef + p + n) | agora¹ |
| **Dados desatualizados** | integridade dos dados | `last_run_at` / `last_status` da regra de extração de mercado | agora |
| **Autoauditoria da dieta (Diet self-audit)** | contexto | `signals.concentration` (Gini + parcela das 3 maiores entre as suas fontes) | agora |
| **Câmara de eco** | sobrecontado | grafo de atores de `signals.coordination` (quase-duplicata + sincronia + host) | novo |
| **Sinal isolado** | subcontado | agrupamento de quase-duplicatas de uma única fonte que não ecoou | novo |
| **Capacidade implausível** | investigar | artigos/dia em comparação com a mediana do corpus | novo |
| **Perfil emocional** | contexto | léxico de emoções sobre as janelas de contexto de uma palavra-chave | novo² |
| **Pulso PI / jurídico (IP / legal pulse)** | contexto | termos de PI/jurídicos em alta no corpus de notícias | incipiente |
| **Mudança de controle** | investigar | linguagem de verbos de negócio (adquiriu/fusão/desinvestiu) nas notícias recentes | incipiente |
| **Linhagem de uma notícia** | contexto | `signals.lineage` — um agrupamento de quase-duplicatas ordenado pela hora de publicação + atribuição a agência | novo |
| **Consultor de cobertura** | contexto | `signals.concentration` sobre o país/idioma das suas fontes (desvio, não um limite) | novo |
| **Verificação meteorológica disponível (Weather check available)** | investigar | `analytics.corroboration` — termos de eventos climáticos × lugares deduzidos × datas dos artigos | novo |

¹ Requer o extra `[analysis]` (VADER / scipy). Sem ele esses cartões simplesmente não
aparecem — o resto do briefing continua funcionando.
² Usa um léxico de emoções; é fornecida uma **amostra** mínima em inglês — aponte
`OO_EMOTION_LEXICON` para um léxico JSON mais completo para uso sério (somente inglês).

Os cartões de **câmara de eco**, **sinal isolado** e **capacidade implausível** vêm da
camada de integridade das fontes — veja [`USER_MANUAL.md`](USER_MANUAL.md). Os cartões de câmara de eco trazem
a ação *Agrupar num só ator* (antiamplificação guiada pelo usuário — o app propõe → você decide).

A **Autoauditoria da dieta** usa a primeira primitiva pura do substrato compartilhado
[`src/signals/`](../src/signals/): **concentração** (coeficiente de Gini + parcela
dos N maiores). É a *mesma matemática* prevista para a concentração da propriedade da mídia
(FUTURE_DEVELOPMENTS §1) e para a proeminência de pessoas (§4) — um só motor, muitos domínios.

A **Linhagem de uma notícia** rastreia uma notícia ecoada até sua **fonte primária**: para um agrupamento
de quase-duplicatas em muitos veículos, ela ordena as peças pela hora de publicação e detecta
**atribuições explícitas a agências** ("segundo a Reuters", "(AFP)"), para que a reportagem original fique em primeiro plano
em relação aos ecos derivados. A linha divisória é honesta: *"o mais antigo que vimos" ≠ "a verdade"* — ela
revela a estrutura; quem julga é a pessoa. O **Consultor de cobertura** mostra o **desvio**
geográfico/linguístico **na sua própria coleta** (por exemplo, "~80% do que você coletou vem de um só país") como
uma sugestão gentil para ampliar — ele nunca filtra nem limita nada; um corpus enviesado enviesa todos
os sinais derivados, então enxergar o desvio é justamente o ponto.

A **Verificação meteorológica disponível** é o primeiro cartão do tipo *se-isto-então-sugira*: quando vários dos seus
artigos mencionam a mesma palavra de evento climático (seca, enchente, onda de calor… — uma lista-semente
curada em 12 idiomas, `configs/corroboration_rules.yml`) junto com o mesmo lugar deduzido
dentro de uma mesma janela de tempo, o cartão **oferece** buscar dados meteorológicos independentes para
exatamente esse lugar e essa janela. O próprio cartão é calculado localmente — e diz isso — e
nada é buscado até você clicar em **Obter o contexto meteorológico**, que passa pelo
mesmo pop-up de consentimento de rede de qualquer outra ação online. O que volta é uma fatia limitada
de **reanálise** do Open-Meteo (CC BY 4.0, atribuição exibida): uma *estimativa de modelo*, não um
registro de estação — ela pode **corroborar ou contestar** o que os artigos dizem, nunca prová-lo.
A fatia fica em cache no disco, então relê-la depois funciona offline; o estado do cache e
a hora da busca são sempre exibidos.

---

### Desempenho — pré-calcular, armazenar em cache, servir do cache

O briefing **nunca é calculado a cada requisição**. O agendador em segundo plano o atualiza
após cada coleta e grava um cache (`briefing_cache.json` na sua pasta de dados);
o Início lê o cache e carrega instantaneamente. Ele **se atualiza sozinho** — recalcula em
segundo plano após cada passagem, e o Início consulta de novo por conta própria (uma faixa de progresso aparece
enquanto uma atualização roda); não há botão manual de Atualizar. As dispensas
(`briefing_dismissed.json`) e o rascunho (`briefing_draft.json`) são pequenos arquivos JSON
locais — de um único usuário, local-first, nunca transmitidos.

---

### Salvaguardas de honestidade (no código, não só na documentação)

O FUTURE_DEVELOPMENTS §6 proíbe uma pontuação automatizada única de confiança/qualidade (ela embute a
visão de mundo de quem pontua num número falsamente objetivo e *vai* classificar mal fontes pequenas, estrangeiras,
novas ou dissidentes). Essa proibição é imposta **mecanicamente**:

- `src/briefing/card.py:assert_no_score_fields()` rejeita qualquer campo de `Card` cujo nome
  sugira uma pontuação composta (`score`, `trust_score`, `credibility`, `rating`,
  `verdict`, …). Ele roda na importação e um teste garante que isso se mantém.
- O valor numérico que um cartão carrega fica em `signal` como **uma única grandeza medida com um
  método declarado** — uma razão de crescimento, um valor de Gini, um coeficiente de correlação — nunca uma
  pontuação misturada sobre dimensões incomensuráveis.
- **Mostrar, não suprimir.** A dispensa é reversível; qualquer redução de peso futura será
  transparente, ajustável, desligada por padrão e reversível.

---

### API

Tudo sob `/api/briefing` (somente loopback, como o resto do app):

| Método e caminho | Finalidade |
|---|---|
| `GET /api/briefing` | o feed em cache, agrupado por grupo (`?force=true` para recalcular) |
| `POST /api/briefing/refresh` | recalcular agora |
| `POST /api/briefing/dismiss` · `/restore` · `/dismissed/clear` | gerenciar as dispensas |
| `GET /api/briefing/draft` | o rascunho atual (cartões fixados + notas + título) |
| `POST /api/briefing/draft/add` · `DELETE /api/briefing/draft/{id}` | fixar / desafixar um cartão |
| `PUT /api/briefing/draft/note` · `/title` · `POST /draft/clear` | editar o rascunho |
| `GET /api/briefing/draft/export.md` | o Markdown acompanhado das evidências |

---

### Roteiro (status)

As fases A–D foram entregues: a espinha dorsal de cartões + briefing (A), o substrato completo `src/signals/`
— concentração, quase-duplicatas/coordenação, novidade (B), o perfil de integridade das fontes +
antiamplificação guiada pelo usuário (C, veja [`USER_MANUAL.md`](USER_MANUAL.md)) e os pacotes
de anotações assinadas colaborativas (D, veja [`USER_MANUAL.md`](USER_MANUAL.md)). A fase E entrega as
verticais combináveis como cartões (emoção, notícias de PI/jurídicas); as **verticais de acompanhamento de alterações
de fontes primárias de direito / PI** (ingerindo `legislation.gov.uk`, EUR-Lex, patentes/processos)
continuam sendo o próximo passo documentado — elas reaproveitam os motores existentes de acompanhamento de alterações e
de quase-duplicatas/correlação, mas exigem fontes externas ao vivo. Veja
[`ROADMAP.md`](archive/roadmaps/DESIGN_MEMORY_pre-0.2.md), fases B–E.


---

## Integridade das fontes e antiamplificação

> **Status:** `0.06` Fase C — entregue e testada. A pedra angular da camada de
> inteligência (FUTURE_DEVELOPMENTS §6). Funciona em conjunto com [`USER_MANUAL.md`](USER_MANUAL.md) e
> [`USER_MANUAL.md`](USER_MANUAL.md).

As outras ferramentas mostram sinais; **esta decide qual sinal conta** — *sem
se tornar árbitra da verdade*. É a resposta ao problema do "lixo entra, lixo sai".

### A surpresa: tratar todas as fontes da mesma forma **não** é neutro

Tendências, proeminência, sincronia e "o que está sendo coberto" **contam veículos e volume**.
Por isso, o tratamento igual dos veículos, aplicado a uma métrica de volume, tem um viés embutido:
*quem produz mais, ganha.* Um ator com muitos recursos que cria 40 veículos (ou
fazendas de trolls, ou fábricas de conteúdo) converte capital diretamente em consenso aparente e
**dilui** até sumir as matérias honestas de uma única fonte. Não fazer nada não é neutro —
é subsidiar quem inunda.

A solução não é *pontuar* fontes. É definir a neutralidade sobre a **unidade**
certa: tratamento igual de *atores independentes ponderados pela informação nova que
contribuem*, e não de *veículos*. **Contar fantoches como vozes é um erro de
medição, não neutralidade.**

### O que é medido (e o que é proibido)

Ficamos estritamente na metade **permitida** da distinção do §6:

- **(A) Pontuação de veracidade / qualidade** — "esta fonte é verdadeira / boa?" — é
  **proibido automatizar.** Ela embute a visão de mundo de quem pontua num número falsamente
  objetivo e *vai*, mais cedo ou mais tarde, rebaixar também uma fonte boa mas incomum.
- **(B) Sinais de autenticidade / estrutura** — "esta fonte é o que diz ser? um
  nó de uma rede coordenada? ela *origina* ou só *ecoa*? sua produção está
  dentro da capacidade humana? ela é transparente sobre quem a administra?" — estes são, em grau
  real, **fatos estruturais mensuráveis.** Todo o design fica aqui.

#### O motor compartilhado (`src/signals/`)

| Primitiva | Mede | Sustenta |
|---|---|---|
| `concentration` | Gini + parcela dos N maiores | concentração de propriedade/de dieta, proeminência |
| `near_dup` | agrupamentos de quase-duplicatas por MinHash + LSH | detecção de eco / sindicação |
| `coordination` | grafo de atores a partir de quase-duplicatas + sincronia rígida + host compartilhado | agrupamento de atores |
| `novelty` | parcela de shingles de palavras novos para o corpus | ponderação origina-vs-ecoa |

As quatro são **puras** (sem banco de dados, sem rede), testadas por propriedades, e carregam método + ressalva.

### A antiamplificação é **guiada pelo usuário** (o app propõe → você decide)

A antiamplificação **nunca** é uma transformação silenciosa que o app executa e que você apenas
*desfaz* — isso tornaria o app o árbitro que o §6 proíbe.

- **Padrão = "igual, mas consciente".** A visão bruta de tratamento igual é a referência; uma
  enxurrada coordenada é **anotada sobre ela** (o cartão de *câmara de eco*), não agrupada.
- **Você aplica um agrupamento**, por agrupamento ou globalmente. Só então uma rede
  coordenada se dobra em **uma só voz** em qualquer contagem que mede consenso (quantas
  vozes independentes carregam uma matéria).
- **Todo agrupamento aplicado continua sinalizado e reversível.** Um clique o expande em seus
  membros; reverter reproduz as contagens brutas iguais **exatamente**. *Nenhum agrupamento é jamais
  aplicado sem uma ação explícita sua* — imposto por um teste.

Este é o **painel de integridade das fontes** (Configurações → Avançado → Segurança → "Abrir o painel de integridade das fontes"):
*Buscar coordenação* lista os atores propostos com suas evidências (texto compartilhado,
sincronia rígida, host compartilhado); *Aplicar agrupamento* / *Expandir (reverter)* ficam à sua escolha.
As Pistas de câmara de eco no Início trazem a mesma ação *Agrupar num só ator*.

### O perfil da fonte — dimensões medidas, **nenhuma pontuação composta**

Para cada fonte, um painel de sinais *medidos* — e **deliberadamente nenhum número único de
confiança** (o "B" proibido). Uma pontuação de 0–100 é uma falsa precisão sobre dimensões
incomensuráveis, manipulável segundo a lei de Goodhart, um ponto único de captura, e *vai* classificar mal
fontes pequenas / estrangeiras / novas / dissidentes. A proibição é imposta no código (o perfil
retorna `no_composite_score: true` e um teste garante que não há chave agregada `*score*`).

Dimensões (cada uma com seu próprio método + ressalva):

- **Coordenação** — pertencimento a um ator, com quem, quantas matérias compartilhadas.
- **Novidade** — esta fonte origina ou na maior parte ecoa? (em relação ao *seu* corpus).
- **Capacidade de produção** — artigos/dia em comparação com a mediana do corpus (uma *pergunta*, não um veredito;
  agências de notícias e grandes redações são legitimamente prolíficas).
- **Transparência** — país, idioma, etiquetas de propriedade/orientação (reputacionais,
  contestáveis, editáveis) e o `reliability_score` definido pelo operador (não calculado aqui).
- **Histórico** — o que esta fonte contribuiu para o seu corpus.

Você pondera quais dimensões importam na *sua* visão — desligado por padrão, reversível, com a
visão bruta igual sempre a um clique de distância.

### Novos cartões de briefing desta camada

- **Câmara de eco** (sobrecontado) — uma matéria veiculada por N fontes coordenadas.
- **Sinal isolado** (subcontado) — uma matéria substancial de uma única fonte que não ecoou.
- **Capacidade implausível** (investigar) — uma fonte que publica muito acima da norma do corpus.

### API

| Método e caminho | Finalidade |
|---|---|
| `GET /api/integrity/profile?source=` | o painel de sinais medidos sem pontuação composta |
| `GET /api/integrity/actors` | atores coordenados propostos, cada um sinalizado como aplicado/não aplicado |
| `GET /api/integrity/prominence` | proeminência da matéria em vozes independentes, bruta vs agrupada |
| `POST /api/integrity/collapse/apply` · `/revert` | aplicar / desfazer um agrupamento (por ator) |
| `POST /api/integrity/collapse/apply_all` · `/revert_all` | agrupar / redefinir globalmente |

### Limites honestos (nomeados)

- **Corrida armamentista / Goodhart** — todo sinal publicado é um alvo de otimização; isto é
  defesa em profundidade, nunca uma alegação de completude.
- **Fusões indevidas prejudicam inocentes** — a detecção é de alta precisão, inclinada a
  agrupar *de menos*, sempre com as evidências exibidas, sempre reversível.
- **Captura** — entregamos *mecanismos, não vereditos*; o padrão é a visão igual
  transparente; você pode sobrepor tudo.
- **O objetivo** não é "detectar todo o lixo" (impossível, e alegá-lo seria o gesto
  desonesto), mas **tirar do lixo sua vantagem mecânica**, para que a jogada das 40 agências
  *deixe de compensar*.


---

## Anotações de fontes compartilhadas — assinadas, portáteis, federadas pela confiança

> **Status:** `0.06` Fase D — entregue e testada. A resposta de escala ao perfil da
> fonte (FUTURE_DEVELOPMENTS §6). Funciona em conjunto com [`USER_MANUAL.md`](USER_MANUAL.md).

O perfil da fonte permite que *você* pondere quais dimensões importam. Mas **ninguém consegue avaliar
com neutralidade milhares de fontes sozinho** — então a ponderação precisa ser **coletiva**. A
forma honesta, local-first e não centralizada de fazer isso são **pacotes de anotações
assinados e compartilháveis**.

- Você publica suas anotações de fontes — etiquetas de coordenação, fatos de propriedade/transparência,
  etiquetas de orientação, correções, notas — como um **pacote assinado pela custódia, verificável e
  portátil** (reaproveitando o mesmo assinador híbrido Ed25519 + ML-DSA da cadeia de custódia —
  *mutualização*, não uma segunda pilha criptográfica).
- Outros usuários **importam** os pacotes em que escolhem confiar — uma **rede de confiança** opcional,
  **nunca** uma autoridade central.
- A agregação é **transparente**: você sempre vê *quem afirmou o quê*, e **a divergência é
  mostrada, não transformada em média** num número oculto.

Sem servidor, sem contas, sem pontuação global — **federação por troca assinada.**

### O que uma anotação é (e o que não é)

Uma anotação é um **fato ou etiqueta descritivo e contestável** sobre uma fonte. Tipos:
`ownership`, `leaning`, `coordination-tag`, `transparency-fact`, `correction`, `note`.
Ela **nunca** é uma pontuação composta de confiança/qualidade — isso é proibido, por design e no
código (um tipo inválido como `trust-score` é rejeitado).

### Modelo de confiança — o que uma assinatura prova e o que não prova

Cada pacote embute a **identidade pública** do autor e uma assinatura sobre o manifesto
canônico. A verificação **fixa** a chave embutida, de modo que um ataque de adulterar-e-reassinar não consegue
*se passar* pelo autor original — ele apenas produz um autor **diferente**. Um
pacote verificado é, portanto, sempre atribuído com veracidade à chave que o assinou, seja ela qual for.
Você então decide *em quais chaves confiar*; só as anotações de autores confiáveis são agregadas.

Isto é **rede de confiança, não prova de correção**: confiar num autor significa "quero
ver as afirmações dele", não "as afirmações dele são verdadeiras". A divergência entre autores confiáveis
é mostrada para você julgar, nunca resolvida no seu lugar.

### Como usar (o painel de integridade das fontes — Configurações → Avançado → Segurança)

1. **Crie** anotações (alvo + tipo + valor) em *Anotações compartilhadas*.
2. **Exportar pacote assinado** → um arquivo JSON que você pode publicar ou compartilhar.
3. **Importar pacote…** → o app **verifica a assinatura** antes de armazená-lo (um pacote
   inválido é recusado, de forma ruidosa) e depois lista o autor em *Autores confiáveis* com um
   interruptor de confiança.
4. **Quem disse o quê?** → agrega todas as afirmações sobre uma fonte feitas por você + pelos autores
   confiáveis, com as atribuições e as divergências exibidas.

Deixar de confiar num autor exclui as anotações dele; remover um autor as apaga de forma limpa.

### API

| Método e caminho | Finalidade |
|---|---|
| `GET /api/annotations/mine` · `POST` · `DELETE /mine/{i}` | as anotações que você criou |
| `GET /api/annotations/export` | um pacote assinado e portátil das suas anotações |
| `POST /api/annotations/import` | verificar + armazenar um pacote importado (recusado se inválido) |
| `GET /api/annotations/authors` · `PUT /authors/trust` · `DELETE /authors/{id}` | a rede de confiança |
| `GET /api/annotations/for?target=` | agregação transparente — quem afirmou o quê |

### Restrições de honestidade

- **Nada de média, nada de número de consenso, nada de pontuação.** A agregação retorna afirmações
  atribuídas e nomeia a *divergência*; ela nunca reduz a discordância a um número.
- **Local-first.** Tudo é um arquivo na sua pasta de dados; nada é transmitido e
  não há servidor nem conta.
- **Contestável por construção.** Cada anotação é uma etiqueta/um fato sobre o qual você e outras pessoas podem
  discordar — de forma visível.


---

## Análises — análise de palavras-chave e entidades

### Intenção

Transformar o corpus unificado de uma caixa de pesquisa num instrumento analítico. Palavras-chave
e entidades são extraídas do **texto dos artigos ingeridos**, armazenadas com suas
ocorrências e contexto, e apresentadas para que um jornalista investigativo possa perguntar:
*do que se está falando, onde, quando, por quem e junto com o quê?*

Tudo aqui é um **agregado real** sobre os dados armazenados, com método e tamanho de amostra
declarados — nunca uma pontuação fabricada (PRODUCT_SYNTHESIS §3.5).

### Como funciona

```
ingest an article ──► extract (baseline / opt-in spaCy) ──► KeywordMention rows
                          terms + entities, offsets        (count + first offset +
                                                            denormalised date/country/city)
                                                                   │
                          Insights tab / /api/insights  ◄──────────┘
                          trends · associations (PMI) · context · map
```

- **Extração** (`src/analytics/extract.py`): **termos** de n-gramas temáticos
  (filtrados por palavras vazias) mais **entidades** — pessoas, empresas/organizações, lugares — como
  unidades únicas. A extração básica (sem dependências) detecta entidades como sequências de várias palavras
  com Iniciais Maiúsculas e atribui um tipo `person`/`org`/`location` somente a partir de um
  gazetteer (dicionário geográfico; caso contrário, o honesto `entity` genérico); um extra opcional **spaCy** `[nlp]`
  acrescenta um NER real de `PERSON`/`ORG`/`GPE`. Cada palavra-chave registra **qual extrator
  a rotulou** — um tipo de entidade é uma *afirmação rotulada-por-X*, não uma verdade de referência.
  Funciona melhor com escritas delimitadas por espaços; a segmentação de CJK/árabe é uma etapa posterior conhecida.
- **Armazenamento** (`src/analytics/store.py`): um `KeywordMention` por (artigo,
  palavra-chave) — contagem de ocorrências + deslocamento do primeiro caractere (a frase de contexto é recortada
  do artigo armazenado na leitura, para que o banco de dados continue enxuto) + `observed_on` / `country` / `city`
  desnormalizados a partir da fonte. A indexação roda em regime de melhor esforço na
  ingestão (básica e rápida, fail-open). A indexação é **automática** — qualquer pendência é eliminada
  por um complemento silencioso em segundo plano quando você abre Análises (a contagem de "restantes" chega a 0
  sozinha); não existe botão "Indexar corpus (Index corpus)". Uma reindexação completa do corpus existente
  está disponível em **Configurações → Avançado → Diagnóstico** ("Reindexar todo o corpus" / "Limpar
  palavras-chave") como uma tarefa em segundo plano que pode ser pausada.

### Funções (aba Análises + `/api/insights`)

| Visão | Endpoint | O que mostra |
|------|----------|---------------|
| Explorar — tendência | `GET /trend?term=&bucket=` | Volume de menções ao longo do tempo (dia/semana/mês), com a palavra-chave resolvida + o tipo |
| Explorar — mapa mental | `GET /associations?term=` | Palavras-chave coocorrentes classificadas por **PMI** (informação mútua pontual) com tamanhos de amostra + uma ressalva "associação ≠ causalidade"; clique num nó para recentralizar |
| Explorar — contexto | `GET /context?term=` | Trechos recentes de menções recortados do texto dos artigos, com links para o artigo/a fonte + país/cidade/data |
| Tendências | `GET /trending`, `GET /top` | Termos em alta (**razão** entre o período recente e o anterior, uma medida rotulada) e termos principais, filtráveis por janela / tipo / país |
| Mapa | `GET /map?days=&kind=` | Principais palavras-chave **por país e por cidade** (sinal regional baseado na fonte) |
| Indexação | `GET /status`, `POST /reindex?limit=` | Contagens de indexados/restantes; preenchimento retroativo do corpus em blocos |

Filtros de `kind`: `term`, `entity`, `person`, `org`, `location`.

### Garantias de honestidade

- Tendências/principais são contagens reais; "em alta" é uma **razão** definida entre recente e anterior,
  explicitamente *não* um teste de significância.
- As associações usam **PMI** sobre a coocorrência em artigos, retornadas com `n` e a
  ressalva de que amostras pequenas são ruidosas.
- Os tipos de entidade carregam a proveniência do extrator; a extração básica nunca alega um tipo preciso de
  pessoa/organização/lugar que não consiga justificar.
- A região no mapa é o país/a cidade **da fonte** (o sinal confiável). A
  visão Mapa agora inclui um **SVG equirretangular interativo** (zoom/arrastar, rótulos
  de cidades ao aproximar) que posiciona as cidades pela latitude/longitude reais a partir de um **gazetteer**: uma pequena
  amostra acompanha o app (`configs/cities.sample.yml`); o conjunto completo é gerado a partir do
  Wikidata (`scripts/build_city_gazetteer.py` → `configs/cities.yml`). Uma cidade sem
  correspondência no gazetteer mantém seus dados de palavras-chave, mas **nenhuma posição no mapa** (nunca uma
  localização fabricada). As tabelas de país/cidade continuam ao lado do mapa.


---

## Acompanhamento de alterações da Wikipedia

### Intenção

A Wikipedia é um território disputado: os artigos são editados continuamente, e na era dos LLMs
apagar ou reescrever a história ficou mais fácil do que nunca. Esta ferramenta trata cada
**edição linguística** da Wikipedia como uma fonte acompanhada cujas *edições* são os dados, para que
um jornalista possa **detectar e documentar** alterações em grande escala ou revisionistas —
por exemplo, provar que uma frase existia numa determinada data e foi removida por uma determinada
conta.

> As edições são por **idioma** (`en`, `fr`, `ar`, `ru`, `zh`, …), não
> por país (não existe Wikipedia nacional); a interface associa idiomas a países.

### Por que isto não é a ingestão de "artigos comuns"

Os artigos mudam com o tempo, então não podem ser armazenados como linhas `Article` de uma só vez.
Daí decorrem duas escolhas de design:

1. **Usar a MediaWiki Action API, não a raspagem de páginas** — `revisions`,
   `recentchanges` (com deltas de bytes) e `compare` (diffs calculados no servidor). Este
   é o caminho eficiente, compatível com os termos de uso e orientado a alterações.
2. **Armazenar deltas, não recópias** — manter **uma** referência de texto completo comprimida
   por página (`wiki_pages.baseline_text`); cada edição posterior é uma linha `wiki_revisions`
   com o **diff + delta de bytes com sinal + sinalizações**, nunca o novo artigo
   inteiro. Qualquer versão histórica pode ser reconstruída reaplicando os diffs.

**Isto responde à questão de redundância/disco:** uma edição cosmética é um diff minúsculo
com a sinalização `minor` do MediaWiki e é filtrada por um limite de tamanho/edição menor, então
quase não custa nada. O armazenamento cresce com a **atividade de edição nas páginas acompanhadas**, não
com o corpus de artigos de vários GB — você nunca precisa do dump completo para acompanhar.

### Detectando edições em grande escala / suspeitas (com honestidade)

`src/wiki/flagging.py` sinaliza uma edição e registra **códigos de motivo** — ele mostra
*candidatas*, não declara "desinformação":

- `large_removal` / `large_addition` — delta de bytes acima de um limite
- `revert` / `blank` — etiquetas de alteração do MediaWiki (`mw-reverted`, `mw-undo`, `mw-blank`…)
- `anon_large` — uma edição média ou maior feita por um IP anônimo
- `burst` — muitas edições numa página em pouco tempo
- `ores_damaging` — probabilidade opcional de "dano" do **Wikimedia ORES**, apresentada
  como uma afirmação *rotulada-pelo-ORES* (como a proveniência das nossas entidades)

Edições cosméticas menores nunca são sinalizadas. Cada edição sinalizada é documentada com seu
diff + proveniência (revid, editor, data e hora), o que se conecta à
**cadeia de custódia** existente para obter provas assinadas/com carimbo de tempo.

### Dois subsistemas claramente separados (experiência de uso)

1. **Vigiar e acompanhar (Watch & track)** (leve, instantâneo, o padrão): uma lista de vigiados de páginas /
   categorias por edição linguística; consulta as revisões no agendador do app; armazena
   revisões + diffs + sinalizações; um visualizador de diffs + uma linha do tempo por página. Sem download em massa.
2. **Base de referência offline (Offline baseline)** (pesado, opcional): fica em **Configurações → Bases de referência
   offline da Wikipédia** (deliberadamente fora do caminho do acompanhamento leve). Uma
   **lista selecionável de edições linguísticas** (curada, das maiores para as menores, com o nome de cada
   idioma na própria língua e uma faixa aproximada de tamanho) substitui a digitação livre do código; o
   tamanho exato atual do dump é lido do servidor sob demanda (`Estimate size`),
   e depois vem baixar / pausar / retomar / apagar. A lista vem de
   `GET /api/wiki/languages`; o baixador continua aceitando qualquer código de edição.
   (Tamanho na realidade: o enwiki de texto atual ≈ 22 GB comprimido; o histórico completo ocupa
   terabytes — só necessário para diffs históricos offline.)

### Status

- **Feito:** esquema (`wiki_pages`, `wiki_revisions`; migração `d4e5f6a7b8c9`);
  o parser da API do MediaWiki + o cliente ao vivo (`mediawiki.py`, `client.py`); a
  lógica de sinalização de edições (`flagging.py`); o cliente ORES (`ores.py`); o
  orquestrador de acompanhamento (`track.py`, armazenamento de referência + deltas); o modo `wiki` do agendador;
  a **API** (`/api/wiki/*`) e **Configurações → Wikipédia** (lista de vigiados, acompanhar agora,
  feed de alterações sinalizadas, visualizador de diffs); o **baixador de bases de referência offline**
  (`dumps.py` — por idioma, retomável, sondagem de tamanho), agora conduzido por um **seletor
  de idioma** (`languages.py`, `GET /api/wiki/languages`) realocado para **Configurações →
  Bases de referência offline da Wikipédia**. Toda a lógica pura + a orquestração têm testes unitários com
  fixtures (sem rede).
- **Próximo:** vincular os diffs da wiki à análise de palavras-chave de Análises; o
  firehose opcional do EventStreams; exportação de um diff sinalizado como prova via cadeia de custódia.

### Ética

Toda busca respeita a política de uso da API do MediaWiki (User-Agent identificável,
`maxlag`, limites de taxa) — mais respeitoso do que a raspagem. Armazenamos apenas dados públicos
de revisão; nada é buscado até o acompanhamento rodar.


---

## Direito mundial — acompanhamento de alterações de leis, diários oficiais e PI

> **Status:** `0.06` Fase E — entregue. A vertical do §5: uma "Wikipedia do direito".
> Reaproveita o motor de acompanhamento de alterações (`src/wiki`) e os motores compartilhados de `src/signals/`.

Reunir o **direito** — leis, legislação, diários oficiais, registros de PI — de
fontes oficiais do mundo inteiro, e **acompanhar como ele muda ao longo do tempo**. O direito é público em
muitos países e muda por emenda, então os dados *são o diff*: o que mudou e quando.

### Ativado por padrão — um catálogo mundial de fontes oficiais reais

`configs/legal_sources.yml` traz um conjunto curado, de alcance mundial, de **fontes primárias
oficiais reais** — bases nacionais de legislação (`legislation.gov.uk`, EUR-Lex, Légifrance,
`gesetze-im-internet.de`, `congress.gov`/`govinfo.gov`, `legislation.gov.au`,
`indiacode.nic.in`, `elaws.e-gov.go.jp`, `law.go.kr`, …), diários oficiais, escritórios de PI
(WIPO Lex, USPTO, EPO, EUIPO, JPO, …) e sistemas abertos de jurisprudência/registros (CourtListener,
SEC EDGAR). Na primeira execução elas são semeadas como fontes comuns **ingeríveis e pesquisáveis**
(`source_type` legal/ip), de modo que passam pelo *mesmo* pipeline ético que as notícias.

Um subconjunto curado de **documentos de direito consolidado** estáveis e bem conhecidos (por exemplo, o Human
Rights Act do Reino Unido, o RGPD da UE, a Constituição dos EUA) já vem registrado para **acompanhamento de alterações**
de fábrica.

### Como funciona o acompanhamento (reaproveita o motor da Wikipedia)

Para cada documento acompanhado, a primeira busca bem-sucedida é a **referência** imutável
("a lei tal como estava na data X"). Cada busca posterior cujo *texto visível normalizado*
seja diferente registra uma revisão com o delta de bytes, um **diff** unificado limitado em relação à
referência e uma **sinalização de grande alteração** honesta (reaproveitando os limites de sinalização da wiki).
Execute-o a partir da **aba Governos → subaba Direito** ("Acompanhar alterações agora") ou pelo
agendador em segundo plano (modo `law`). Toda busca passa pelo caminho **ético,
fail-closed quanto ao robots.txt**.

### Lendo uma lei a partir do próprio XML do editor (fontes estruturadas)

Uma página web precisa ser *reconstruída* em texto: retirar a navegação, o formulário de busca,
o banner de cookies, e torcer para que o que sobra seja a Lei. Isso funciona, e é o que o
rastreador faz para a maioria das fontes — mas a cópia armazenada de uma Lei do Reino Unido certa vez começava com o
próprio formulário de busca do portal, e tudo o que foi derivado dela (uma pessoa "Personal Acts", uma
organização "PART") veio de um texto que nunca esteve na Lei.

Quando um editor disponibiliza o **próprio XML**, nada disso se aplica: não há elementos de página
no arquivo, porque o arquivo não é uma página. O Open Omniscience consegue ler
diretamente o CLML do `legislation.gov.uk`, o que oferece ainda duas coisas que uma página não oferece:

- **Dispositivos com endereços citáveis.** Cada seção é lida com o caminho de Parte/Capítulo
  acima dela, de modo que uma alteração pode ser relatada como *"a seção 12 da Parte 2 mudou"* em vez de
  como uma contagem de bytes. As seções são associadas por esse endereço e nunca pela posição —
  do contrário, inserir uma seção faria todo o restante da Lei ser relatado como emendado.
- **Datas que significam o que dizem.** Promulgação, ponto de consolidação e a data em que *nós*
  a buscamos são três campos separados, sem nenhum substituindo o outro. Uma data que o documento
  não declara é mostrada como desconhecida, nunca preenchida a partir de outra. (É por isso que uma
  lei rastreada não mostra data de publicação a menos que o próprio documento forneça uma: a única
  data disponível era o dia em que consultamos a página, e uma data de consulta não é uma data
  de publicação.)

A comparação por seção é **aditiva e experimental**: o diff de texto comum continua
decidindo se uma revisão é registrada e continua carregando o sinalizador de alteração grande. E um
limite é declarado em vez de disfarçado — uma seção que é *renumerada e reescrita*
na mesma emenda é relatada como uma remoção mais uma adição, porque associá-la à
sua versão anterior significaria adivinhar qual de duas seções com números diferentes é "a
mesma, editada".

**O que ainda não existe:** nada busca esses documentos XML automaticamente ainda. Ler
o corpus jurídico completo de uma jurisdição significa percorrer a lista do próprio editor (o Reino Unido
lista todas as Leis; a França lista 76 códigos), e essa enumeração não foi construída. Até que seja,
o conjunto rastreado continua sendo o curado, e o relatório de cobertura diz honestamente
"cobertura desconhecida" em vez de apresentar uma contagem de documentos rastreados como se fosse o
corpus inteiro.

### Verificando se as correções de leis chegaram aos seus dados

Duas correções de leis se aplicam **silenciosamente, na próxima busca bem-sucedida de um documento**: os elementos de página são
relidos a partir de uma base armazenada, e uma data de publicação que na verdade era uma data de consulta é
apagada. Ambas estão corretas — e um documento cujo portal está inacessível nunca é corrigido, que
é exatamente o caso que vale a pena conhecer.

O relatório **law-ingest** (no pacote de todos os diagnósticos, ou isoladamente) responde a isso a partir de
dados armazenados, sem nenhuma chamada de rede: o que a última verificação de cada documento rastreado registrou (uma
contagem por resultado, como inalterado, relido, erro ou adiado, e o resultado de cada documento
e a hora da última tentativa), e se algum artigo de lei ainda carrega uma
data de publicação que não deveria. Um documento cuja última verificação falhou merece ser
examinado, mas o relatório não consegue dizer se ele foi relido uma vez antes de começar a falhar:
isso não é registrado. A própria contagem de releituras conta apenas documentos cuja consulta mais recente
foi a releitura, então, numa instalação em que todos os documentos foram corrigidos, ela tende de volta
a zero.

Ele também relata **resíduo de elementos de página** — texto de navegação ainda presente num corpo armazenado. Leia
isso como uma *medição*, não como um veredito: a remoção dos elementos de página remove deliberadamente apenas o que
a marcação declara ser elemento de página e deixa o resto, porque uma regra de correspondência de texto
apagaria também os próprios títulos de seção de uma Lei. Resíduo após uma releitura correta é esperado;
o número indica quanto de elementos de página não declarados há no seu corpus, e a lista de marcadores é
um piso, então zero significa "nenhum destes", nunca "nenhum elemento de página".

### Cartões de briefing a partir do corpus jurídico

- **Lei alterada (Law changed)** (vigiar) — uma alteração sinalizada num documento jurídico rastreado.
- **Legislação-modelo** (investigar) — texto jurídico quase idêntico em duas ou mais
  jurisdições (o mecanismo de quase-duplicatas §1/§2), um padrão de difusão mensurável.

Além disso, como o texto jurídico está no corpus unificado, a correlação **lei ↔ notícias** e
a análise de palavras-chave funcionam sobre ele como sobre qualquer outra fonte.

### API

| Método e caminho | Finalidade |
|---|---|
| `GET /api/law/status` | cobertura: documentos por jurisdição, totais de alterações/sinalizações |
| `GET /api/law/documents` | documentos rastreados (opcionalmente `?jurisdiction=`) |
| `GET /api/law/documents/{id}` | um documento com seu histórico de alterações (diffs) |
| `GET /api/law/changes` | alterações jurídicas recentes (sinalizadas), as mais novas primeiro |
| `POST /api/law/track` | buscar agora todos os documentos vigiados (buscador ético) |
| `POST /api/law/seed` | (re)semear o catálogo mundial + registrar documentos |

### Restrições de honestidade (a lei envolve muito em jogo)

- **Não é aconselhamento jurídico, nem a fonte oficial.** A cópia agregada é um
  *espelho de pesquisa*; cada registro remete ao diário oficial, e a interface diz isso.
  Rastrear e expor; nunca interpretar a legalidade nem julgar uma lei.
- **"Público" ≠ "livremente redistribuível".** As licenças variam mesmo quando o texto é público —
  cada uma é respeitada, atribuída, com a proveniência armazenada, robots com falha fechada (como para as notícias).
- **Delimitar o escopo com honestidade.** "Todos os países" é a estrela-guia, não a v1: o catálogo é amplo, mas
  curado, e o rastreamento de alterações é feito por diff de texto normalizado (portais de texto consolidado dão
  o sinal mais limpo). Quando um editor disponibiliza XML estruturado, há diffs por seção
  (veja acima) — CLML hoje; Akoma Ntoso / ELI ainda não são lidos. A ferramenta diz
  o que tem para cada documento e se recusa a adivinhar: um documento que ela não consegue analisar
  estruturalmente mantém o diff de texto em vez de ser relatado como se tivesse seções.
- **Tradução** (via o LLM local) é um auxílio separado e claramente identificado — nunca uma
  tradução jurídica oficial.


---

## Mercados: inteligência financeira, de bolsas de valores e de matérias-primas/terras raras

O Open Omniscience vem com um **catálogo mundial e curado de fontes de mercado**, de modo que
já está pronto para ingerir a cobertura dos mercados financeiros desde o início, e com uma aba **Matérias-primas** que
transforma páginas *configuradas* numa série de preços real, representável em gráfico, correlacionada com as notícias.

Este documento explica o que vem pré-empacotado, o que não vem e por quê — porque o
limite honesto aqui importa mais do que uma longa lista de recursos.

### O que vem pré-empacotado (pronto para usar como está)

`configs/markets_sources.yml` é semeado automaticamente junto com o catálogo de notícias
(`configs/sources.yml`) na primeira execução e via **Configurações → Avançado → Fontes → Semear fontes iniciais**.
Ele contém ~110 entradas curadas, identificadas por um domínio principal
estável:

- **Bolsas de valores e de títulos** do mundo todo (Américas, Europa, Ásia-Pacífico,
  Oriente Médio, África) — NYSE, Nasdaq, LSE, Euronext, Deutsche Börse, JPX, HKEX,
  SSE/SZSE, NSE/BSE Índia, SGX, ASX, B3, Tadawul, JSE e muitas outras.
- **Bolsas de matérias-primas / metais / energia / derivativos** — CME Group, ICE, LME,
  SHFE, DCE, ZCE, INE, **GFEX** (futuros de terras raras e silício industrial), MCX,
  Eurex, MGEX.
- **Fontes de preços/dados de matérias-primas e terras raras** — Shanghai Metals Market, Kitco,
  USGS, World Bank Pink Sheet, EIA, IEA, OPEC, Fastmarkets, Argus, Benchmark
  Mineral Intelligence, S&P Global Commodity Insights.
- **Editores de notícias e dados financeiros** — Bloomberg, Reuters, FT, WSJ, CNBC,
  MarketWatch, Nikkei Asia, Caixin e outros.

Estas são **fontes** comuns: alimentam o corpus unificado pelo mesmo
buscador ético (robots.txt com falha fechada, taxa limitada). Cada uma tem um
`source_type` (`stock_exchange` / `commodity` / `financial`), região, país e
tags, para que você possa filtrá-las em **Configurações → Avançado → Fontes** e associar regras de preço em
**Matérias-primas**.

> Os feeds RSS ficam intencionalmente em branco para estas entradas (uma URL de feed errada é
> apenas ruído). Ingira-as com o rastreador recursivo, ou adicione um feed RSS verificado
> por fonte em **Configurações → Avançado → Fontes**.

### Obtendo números de preço reais

Uma série de preços só é produzida onde você diz ao aplicativo **exatamente onde o número
está** — não há leitura mágica de páginas, por concepção. Dois caminhos honestos:

#### 1. Regras de extração por página (aba Matérias-primas → "Configurar fontes de dados")

*(Os feeds e as regras de extração ficam numa seção recolhida "Configurar fontes de dados" na
aba Matérias-primas; os próprios feeds curados são atualizados automaticamente em
segundo plano.)*

Adicione uma regra (fonte, símbolo, URL da página, **seletor CSS**, atributo opcional /
regex de valor, moeda, unidade) e pressione **Testar**. O teste busca a página uma vez e
mostra o valor *exato* encontrado — ou o motivo *exato* pelo qual não houve correspondência — para que você possa
ajustar o seletor com um retorno real. As regras que encontram correspondência armazenam um `CommodityPrice`
por dia, que os gráficos embutidos e a correlação preço↔notícias leem.

Modelos para copiar: `configs/market_rules.example.yml`.

**Ressalva (leia isto):** a maioria das páginas de bolsas/cotações exibe os preços com JavaScript,
então o número *não* está no HTML estático que o buscador recebe e um seletor não vai
encontrar nada. É por isso que seletores funcionais **não** vêm pré-configurados — adivinhá-los
significaria números fabricados. Páginas renderizadas no servidor (muitos sites oficiais/estatísticos,
algumas tabelas de dados) funcionam bem; widgets de cotação fortemente renderizados no cliente, não.

#### 2. Feeds CSV oficiais (recomendado — confiável, vem com um catálogo)

Para um histórico numérico confiável, importe uma série CSV legível por máquina de uma
fonte oficial. Este é o caminho confiável, e o aplicativo vem com um catálogo inicial
(`configs/commodity_feeds.yml`) que você pode importar com um clique em
**Matérias-primas → Configurar fontes de dados → Feeds de preços oficiais**, ou via a API:

```
GET  /api/markets/feeds                # list curated feeds + how many points each has
POST /api/markets/feeds/{key}/import   # import one (e.g. copper, wti_crude, brent_crude)
POST /api/markets/feeds/import-url      # import ANY CSV URL you supply (user-customizable)
```

**Provedor principal — FRED** (Federal Reserve Bank of St. Louis): um endpoint CSV estável,
sem chave de API, `https://fred.stlouisfed.org/graph/fredgraph.csv?id=<ID>`,
que **redistribui as séries de matérias-primas do "Pink Sheet" do Banco Mundial** (os
IDs "Global price of …" — cobre `PCOPPUSDM`, brent `POILBREUSDM` etc.) e
séries de energia da **EIA** (`DCOILWTICO`, `DHHNGSP`, …). A primeira coluna é a data,
a segunda o valor; valores ausentes (`.`) são ignorados, nunca armazenados como zero. A importação
é idempotente por `(symbol, market, date)`.

**Fontes comparáveis** que você pode adicionar como feed personalizado (URL + nomes de colunas opcionais):
- **Banco Mundial** Commodity Markets ("Pink Sheet"): o `.xlsx` está em
  <https://www.worldbank.org/en/research/commodity-markets>; as mesmas séries em
  CSV limpo vêm pelos feeds do FRED acima.
- Dados abertos de energia da **EIA dos EUA**: <https://www.eia.gov/opendata/>
- Preços de matérias-primas primárias do **FMI** (Primary Commodity Prices): <https://www.imf.org/en/Research/commodity-prices>
- Dados de matérias-primas minerais do **USGS** (terras raras): <https://www.usgs.gov/centers/national-minerals-information-center>

O mapeamento de colunas padrão é coluna 1 = data, coluna 2 = valor (a convenção
do FRED); indique `date_column` / `value_column` explicitamente para outros layouts.

Há também um caminho de envio direto de arquivo para um CSV que você já tem:

```
POST /api/commodities/{symbol}/prices/import-csv      (multipart file upload)
```

> Se um provedor renomear ou descontinuar uma série, a importação falha **ruidosamente** (erro
> HTTP / nenhuma linha utilizável) em vez de inventar dados — corrija a URL em
> `configs/commodity_feeds.yml` ou use um feed personalizado.

### Por que não há preços extraídos automaticamente desde o primeiro dia?

Porque um número sem origem verificável é pior do que nenhum número. Tudo nesta
ferramenta é construído para que um valor mostrado ao usuário venha de uma
medição real: um seletor que realmente encontrou correspondência, ou um CSV que foi realmente
importado. O catálogo lhe dá as *fontes* instantaneamente; você decide, página por página, quando
um preço é confiável o bastante para ser registrado.


---

## Cadeia de custódia

O Open Omniscience faz uma alegação probatória deliberadamente *estreita e honesta*:

> **Este corpus continha _este_ item, com _este_ conteúdo, registrado _neste_
> momento, e o registro não foi alterado desde então — e aqui está a prova
> criptográfica que você mesmo pode verificar, offline, sem confiar nesta ferramenta.**

Isso é realmente útil para um jornalista investigativo: defende contra
"você fabricou isto", "você antedatou isto" ou "você editou isto discretamente
depois", e permite mostrar que você noticiou algo *antes* de uma página de origem ser
alterada ou apagada. **Não** é um sistema de envio para denunciantes (como o
SecureDrop), e uma "fonte" nesta ferramenta é um *veículo de notícias*, não uma fonte
humana confidencial. Tenha esse escopo em mente ao raciocinar sobre proteção.

Este documento descreve os mecanismos reais (`src/custody/`, `src/reporting/`) e
é explícito sobre o que cada um prova e **não** prova.

---

### As três propriedades, e como obtemos cada uma honestamente

| Propriedade | Mecanismo | O que prova | O que **não** prova |
|---|---|---|---|
| **Integridade** | Assinaturas Ed25519 (+ ML‑DSA opcional) sobre uma serialização canônica; raiz de Merkle sobre todos os campos de proveniência | Os bytes não mudaram desde a assinatura; tudo é coberto, não apenas o conteúdo | — |
| **Proveniência** | **Fixação** da chave pública conhecida do signatário | O registro foi assinado por *aquele* signatário | Nada, se você não fixar uma chave — uma assinatura válida por si só significa apenas "assinado pela chave embutida no pacote" |
| **Tempo** | `local` (autodeclarado) **ou** OpenTimestamps (ancorado no Bitcoin) | Local: um horário que a ferramenta afirma. OTS: o conteúdo existia *no mais tardar* em um bloco do Bitcoin | O horário local não prova nada a terceiros; o OTS prova um *teto* de tempo, não o momento exato |

Recusamo-nos a falsificar qualquer uma delas. Se um carimbo de tempo real de terceiros não puder ser obtido
(offline, ou a biblioteca não está instalada), o código gera um erro em vez de inventar um
horário — o modo de falha que a carta do projeto proíbe (PRODUCT_SYNTHESIS §3.7).

---

### Componentes

#### 1. Pacotes de provas assinados — `src/reporting/evidence.py`
Uma exportação, num ponto do tempo, de artigos selecionados, cada um com sua proveniência e um hash
do conteúdo, unidos por uma **raiz de Merkle com separação de domínio** e uma **assinatura Ed25519**.
Verifique offline com `scripts/verify_evidence.py <bundle.json> [signer_pubkey]`.
Exposto em `POST /api/reports/evidence` e `/api/reports/evidence/verify`.

A chave de assinatura fica em `keys/evidence_ed25519.pem` na sua pasta de dados. Num armazenamento
criptografado, ela é envolvida pela sua frase-senha (uma chave criada antes é envolvida, inalterada, na primeira vez
que uma exportação a carrega com o armazenamento desbloqueado), de modo que uma cópia apenas da pasta de dados não consegue assinar
como você; sem frase-senha, ela permanece `0600` em claro. Se um backup restaurado trouxe uma chave envolvida
pela frase-senha de outra instalação, uma exportação de provas e todo backup (um backup assina seu manifesto
com esta chave) dizem que não conseguem abri-la e não substituem nada: use a frase-senha com que ela foi envolvida,
ou mova o arquivo para outro lugar para que uma nova chave seja criada (pacotes assinados com a chave antiga continuam sendo verificados com
a chave pública dela). Uma frase-senha perdida faz perder a chave; não há recuperação.

#### 2. Assinaturas híbridas — `src/custody/signing.py`
Combina **Ed25519** (rápido, clássico) com **ML‑DSA** (FIPS 204, pós-quântico,
o sucessor padronizado do CRYSTALS‑Dilithium). Duas regras tornam isso honesto:

- **Rótulos honestos.** Uma assinatura é rotulada `hybrid` somente quando uma chave ML‑DSA foi
  realmente usada. Sem o extra `pqc` instalado, a assinatura produz uma assinatura `ed25519`
  e diz isso — nunca alega uma resistência quântica que não produziu.
- **Híbrido significa E.** Uma assinatura `hybrid` só é verificada se **ambos** os componentes
  forem verificados. Um verificador que não tem a biblioteca pós-quântica não consegue checar a metade
  ML‑DSA e, portanto, **falha ruidosamente** — nunca aprova silenciosamente apenas com a metade
  clássica. (Um esquema que aceita *qualquer uma* das assinaturas não vale nada assim que a
  clássica for quebrada.)

As chaves privadas são criptografadas em repouso com AES‑256‑GCM sob uma chave derivada por scrypt
quando o aplicativo tem uma frase-senha (`OO_KEY_PASSPHRASE`, ou então a frase-senha
do banco de dados); caso contrário, são gravadas `0600` em claro e o nível de proteção
é informado com veracidade como `plaintext-0600`.

#### 3. Registro de custódia — `src/custody/log.py`
Um livro-razão SQLite **somente de acréscimo**. Cada ação (`ingest`, `access`, `export`,
`redact`, …) torna-se uma entrada **encadeada por hash** à sua antecessora,
**assinada** e **com carimbo de tempo**. `verify()` recheca a ordem da sequência, os elos da cadeia,
os hashes por entrada, as assinaturas e os resumos dos carimbos de tempo. As exportações são verificadas offline:

```bash
python scripts/verify_custody.py custody_bundle.json [--pin]
```

REST: `POST /api/custody/log`, `GET /api/custody/{item}`, `.../verify`,
`GET /api/custody/export`, `POST /api/custody/verify`.

Registro automático opcional na ingestão: defina `OO_CUSTODY_ON_INGEST=1`
(`Config.custody_on_ingest`). Ele vem **desativado por padrão** — uma escolha probatória explícita,
com um pequeno custo de assinatura por artigo, não um comportamento silencioso sempre ativo.
Ele falha aberto: um erro de custódia nunca interrompe a ingestão.

#### 4. Ancoragem — `src/custody/anchor.py`
Publica uma raiz de Merkle numa testemunha externa, para que o momento de sua existência não dependa
do seu próprio relógio ou da sua chave:

- **`local`** (padrão, offline): registra a raiz num livro de âncoras local. Prova
  apenas que *esta ferramenta* a armazenou — auditoria interna, não prova de terceiros.
- **`opentimestamps`** (rede): ancora um hash opaco no Bitcoin. Sem carteira,
  sem taxa, verificável de forma independente. Recorre a um erro explícito de *indisponível*
  quando offline — nunca um recibo falso.
- **`ethereum` / `ipfs` / `arweave`**: declarados, mas **não implementados**. Eles
  recusam com um erro claro em vez de serem entregues como stubs cujo `verify()` sempre
  retorna falso.

REST: `POST /api/custody/anchor`, `GET /api/custody/providers`.

#### 5. Configurações — `src/custody/settings.py` (configurável pela interface)
O comportamento de custódia é controlado pelo operador em tempo de execução, não apenas via env/YAML.
As preferências persistem em `custody_settings.json` no diretório de dados e são editadas
no painel **Cadeia de custódia** da interface web (ou pela API REST):

- **`pqc_enabled`** — solicita assinatura híbrida Ed25519 + ML‑DSA.
- **`anchoring_mode`** — `local` (padrão) ou `opentimestamps`.
- **`auto_log_on_ingest`** — acrescenta uma entrada assinada a cada ingestão bem-sucedida
  (assume o valor do sinalizador legado `OO_CUSTODY_ON_INGEST` até que uma preferência seja salva).
- **`default_actor`** — rótulo de ator opcional para entradas registradas automaticamente.

**Invariante de honestidade.** Uma opção é um *pedido*, não uma garantia. A API e a interface
sempre exibem o estado **efetivo** (preferência **E** disponibilidade da biblioteca):
se o PQC estiver ativado mas o `pqcrypto` não estiver instalado, o signatário continua apenas com Ed25519
e a interface diz isso — ela nunca mostra uma luz verde de "hybrid" que não pode sustentar. O mesmo
vale para o OpenTimestamps sem o extra `timestamping`.

REST: `GET /api/custody/settings`, `PUT /api/custody/settings`.

Um fluxo típico de "prova máxima":

```
export evidence bundle  ->  take its merkle_root  ->  POST /api/custody/anchor
  (POST /api/reports/evidence)                         {merkle_root, "opentimestamps"}
```

---

### ⚠️ Privacidade: a ancoragem pode desanonimizar você

Ancorar numa blockchain **pública** é **publicação permanente** de um hash e de um
carimbo de tempo. O hash em si não revela nada sobre o conteúdo, mas o *ato* de
enviá-lo revela seu IP e o horário aos operadores de calendário/RPC, e uma carteira
on-chain com fundos cria um rastro financeiro. Para quem precisa de anonimato:

- Prefira **local + OpenTimestamps** a carteiras de blockchain pública.
- Encaminhe os envios ao OpenTimestamps pelo **Tor** (por exemplo, `HTTPS_PROXY`).
- Ou dispense totalmente a ancoragem externa e conte com carimbos de tempo locais + assinatura.

Confidencialidade e ancoragem em blockchain pública estão em tensão. A configuração
padrão (provedor local offline, horário local autodeclarado) não vaza nada.

---

### O que deliberadamente **não** construímos

- **Nenhuma TSA RFC‑3161 falsa.** Retornar `datetime.now()` e chamá-lo de "carimbo de tempo
  confiável" é teatro. Use o OpenTimestamps (real) ou o local (honestamente rotulado).
- **Nenhuma assinatura híbrida com semântica OU.** Veja "Híbrido significa E" acima.
- **Nenhum daemon de integridade sempre ativo em segundo plano, nenhum armazenamento de chaves não criptografado anunciado
  como "criptografado".** As chaves dizem como estão protegidas; a verificação é sob demanda.

### Modelo de ameaças em um parágrafo

A ferramenta roda como **um único usuário local, somente em loopback, no Qubes** (veja
`docs/SECURITY.md`). O sistema de custódia defende a *integridade e a proveniência da
sua própria trilha de provas* contra adulterações posteriores e contra contestações do tipo "você inventou isso".
Ele não protege, e não pode proteger, por si só a identidade de uma fonte humana,
e a ancoragem ingênua em blockchain pública pode ativamente *prejudicar* o anonimato — por isso a ancoragem é
opcional, vem offline por padrão e é entregue com o aviso acima.


---

# O que foi entregue na 0.0.8 — o ciclo do roteiro

> **Retrato histórico, veja CLAUDE.md.** Este é um registro pontual do ciclo 0.0.8;
> não é mantido em relação às versões posteriores. `docs/ledger/OPEN_QUEUE.md` + `docs/ledger/`
> são as fontes de verdade vivas sobre o que foi entregue desde então.

Tudo abaixo está disponível agora, inteiramente pela interface no navegador. Cada recurso declara seu
limite honesto onde aparece.

## Receitas de investigação (Início) e o painel `/investigate`

O briefing do Início agora vigia o seu próprio corpus em busca de **sinais de espaço-tempo** e gera cartões —
todos calculados localmente, nunca a partir da rede:

- **Promessas vencidas** — um artigo mencionou uma data que estava *no futuro* quando foi
  publicado; essa data agora chegou. Hora de perguntar o que realmente aconteceu.
- **Surto de guerra de edições** — uma página da Wikipedia que você rastreia está sendo editada a ≥3× sua própria taxa
  semanal recente; seu registro público está em movimento.
- **Região silenciosa** — um país que produzia artigos para você de forma confiável (quase)
  parou. A ressalva vem embutida: isto mede *o seu corpus*, não a região — um feed
  morto parece idêntico a um silêncio real, então verifique as fontes primeiro.
- **Fontes candidatas aguardam revisão (Source candidates await review)** — veja *Candidatas descobertas* abaixo.

Cartões com um botão **"Abrir investigação ↗"** abrem um painel dedicado **numa nova
aba do navegador** (o aplicativo principal continua funcionando; abra vários ao mesmo tempo). O painel
monta automaticamente os painéis relacionados — o artigo original com seus trechos de proveniência, uma
busca de acompanhamento pré-preenchida, a lista de revisões armazenada, o contexto de cobertura —, traz a
ressalva do cartão literalmente no topo e termina com uma faixa **"Aprofundar"** em que cada
sugestão é uma ação normal com seus parâmetros mostrados. Todo o estado da página fica na
sua URL: salve-a nos favoritos, reabra-a, compartilhe-a entre as suas próprias máquinas.

Desative receitas individuais em **Configurações → Cartões**, onde agora ficam ao lado de todas as
outras Pistas que este aplicativo pode gerar, agrupadas por família — a mesma opção, aplicada a todas elas.

## Apêndice de métodos

O botão **Apêndice de métodos** (na página de busca e na linha de ações da janela de análise)
baixa um documento Markdown que registra *como* a sua seleção atual foi produzida:
a versão do aplicativo, a consulta booleana literal, as contagens de resultados, o contexto do corpus e uma
linha de proveniência por artigo (título · fonte · publicado · URL · SHA-256 do conteúdo). Ele
registra apenas a seleção e não afirma nenhuma conclusão — as afirmações analíticas continuam sendo suas,
verificáveis em relação às linhas. Feito para veredictos de checagem de fatos e revisão por pares; combine-o com um
pacote de provas assinado (Provas e custódia) quando precisar de documento + prova juntos.

## Sintetizar resultados

**Sintetizar resultados** (na página de busca e na janela de análise) abre uma janela em
duas etapas: busca um conjunto de candidatos, mostra os artigos correspondentes com seus metadados
e permite **escolher até 20 membros** (os primeiros ≤20 vêm pré-marcados); depois executa UMA
passada do modelo local sobre exatamente esses e retorna fatos comuns, pontos de desacordo e
perguntas em aberto, citando os artigos membros pelo número. O resultado traz o corpus sintetizado
completo, com os metadados de cada artigo e links para o leitor, e opções de **exportação** (Copiar, .md ou
abrir como página independente). A síntese é armazenada com a proveniência de modelo + versão do prompt
por artigo membro, e a ressalva a acompanha: isto é ajuda de leitura apenas sobre os
membros listados — nunca um veredito. Requer o Ollama, como os outros recursos de LLM;
sem ele, você recebe uma mensagem honesta de "não acessível".

## Exportações versionadas e o grafo de citações

- As exportações legíveis por máquina agora seguem um contrato estável (`oo-export-1`): as exportações JSON são
  envelopes autodescritivos (esquema, versão do aplicativo, data de geração, a consulta exata, contagem);
  as colunas CSV mantêm sua ordem, com a mesma proveniência dos cabeçalhos HTTP `X-OO-*`. A última
  coluna, **Fetched From Host** (`fetched_host` no JSON), é o host de onde a página foi efetivamente
  buscada após seus redirecionamentos; fica vazia para um artigo armazenado antes de esse dado ser registrado.
- O **grafo de citações** — quais domínios externos os seus artigos armazenados citam, apenas contagens,
  sem credibilidade inferida — é exportado como GraphML (`/api/links/export.graphml`) para
  Gephi/yEd/NetworkX, ou JSON.

## Registro de execuções do agendador e a exportação para pasta local (Recolher)

Cada execução do agendador — sucesso ou falha — acrescenta uma linha a um registro de execuções local e auditável
(`scheduler_runs.jsonl`), para que o corpus possa responder "o que rodou enquanto eu estava fora?". Opcionalmente,
defina um caminho de **Exportação para pasta local** no cartão do agendador de Recolher: cada execução então grava o
delta de novos artigos como um arquivo JSON em envelope nessa pasta local, para que o seu próprio pipeline
o observe. Em branco = desativado (o padrão); nada novo = nenhum arquivo.

## Candidatas descobertas (Fontes)

O aplicativo agora sugere fontes por conta própria — **apenas offline**: domínios que os seus artigos armazenados
citam repetidamente, e veículos do catálogo empacotado para países que o seu corpus cobre pouco.
As sugestões ficam em espera, nunca são aplicadas: cada uma traz sua evidência no painel **Candidatas
descobertas** (Configurações → Avançado → Fontes), as execuções são limitadas pelo orçamento de descoberta do agendador e
registradas no registro de execuções, e um cartão no Início avisa quando há candidatas aguardando revisão.
**Promover (Promote)** cria uma fonte *desativada* que você ainda precisa ativar; **Dispensar** é lembrado
e nunca é sugerido de novo. A busca por tema com DuckDuckGo continua separada, **desativada por
padrão**, e protegida em Configurações → Avançado → Segurança (veja abaixo).

## A descoberta externa por tema é opcional (Configurações → Avançado → Segurança)

*Descoberta por tema* é o único recurso que **envia uma consulta de busca em texto livre a um mecanismo
de busca**: ele envia a sua consulta de tema ao DuckDuckGo. (As outras ações online — coleta,
buscas de mercado/estatísticas, downloads de modelos do Ollama, OpenTimestamps — também são consentidas e nomeadas;
esta é a que transmite uma consulta que você digitou.) Ela vem **desativada por padrão** e
recusa com uma mensagem honesta
até que você ative **Configurações → Avançado → Segurança → Descoberta externa por tema** ("Sua consulta
sai desta máquina"). A descoberta de feeds RSS para fontes que você mesmo adicionou continua no
caminho local de busca ética e não é afetada.

## Idiomas

A interface agora vem com **traduções completas em 12 idiomas** (English, العربية, বাংলা,
Deutsch, Español, Français, हिन्दी, Bahasa Indonesia, 日本語, Português, Русский, 中文),
incluindo layout da direita para a esquerda para o árabe. Escolha o seu no seletor de idioma; as
traduções são primeiros rascunhos gerados por máquina — correções são contribuições bem-vindas
(veja `docs/ARCHITECTURE.md` → Internationalisation).
