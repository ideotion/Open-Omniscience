<!-- pt: Translation of docs/DESIGN.md written by AI (2026-11-19, R677; native review dropped by R721, 2026-11-14); it may contain mistakes, and the English original is authoritative. Coverage: the whole document, 68 of 68 headings. Corrections are welcome as a pull request. -->

# Síntese de design e de produto

O que o aplicativo é e o que não é, onde cada 'pilar' original vive agora, o raciocínio de design da GUI e a estratégia de análise de conteúdo. A referência única de design.

## Sumário
- [Open-Omniscience — Síntese do produto (o que o aplicativo deve fazer)](#open-omniscience--síntese-do-produto-o-que-o-aplicativo-deve-fazer)
- [Mapa de intenção dos pilares — onde vive agora o propósito de cada pilar](#mapa-de-intenção-dos-pilares--onde-vive-agora-o-propósito-de-cada-pilar)
- [Redesenho da GUI — "0.05"](#redesenho-da-gui--005)
- [Duas interfaces, um argumento — "Console" vs "Desk"](#duas-interfaces-um-argumento--console-vs-desk)
- [Estratégia de análise de conteúdo — links, uniformidade e a fonte original](#estratégia-de-análise-de-conteúdo--links-uniformidade-e-a-fonte-original)


---

## Open-Omniscience — Síntese do produto (o que o aplicativo deve fazer)

> **Status:** rascunho para revisão. Este documento consolida o design *pretendido*, espalhado por
> toda a documentação do repositório, em uma especificação única, coerente e sem duplicações. Ele remove
> deliberadamente a deriva entre versões, o exagero de marketing e as alegações de QA inverificáveis. Ele descreve o **produto-alvo**, não
> o código atual (em grande parte não funcional).
>
> Marcadores usados:
> - `⚠️ DECIDE:` um ponto em que os documentos de origem eram ambíguos ou se contradiziam — a decisão é sua.
> - `(P0/P1/P2)` uma prioridade *sugerida* para essa capacidade (P0 = núcleo do MVP, P1 = importante, P2 = mais tarde).

---

### 0. Contexto de implantação (RESOLVIDO — orienta tudo o que vem abaixo)

Esta build tem como alvo **um ambiente específico e um único usuário**. Estas respostas agora estão fixadas e resolvem
vários dos antigos pontos `⚠️ DECIDE`.

- **Host:** Qubes OS, rodando dentro de uma **AppVM Debian** (baseada em template).
- **Python:** **3.13 como interpretador padrão.**
- **Usuário:** um **único usuário principal (o dono do projeto)** — sem contas multilocatário, sem RBAC.
- **Superfície:** **interface web + API REST vinculadas somente a `127.0.0.1`** (loopback). Nenhum listener externo.
- **Postura de rede:** local-first; tráfego de saída apenas durante a coleta (scraping) e o download de LLM; **nenhuma entrada** de qualquer tipo.

#### 0.1 O que o Qubes muda no design

O Qubes não é "apenas Debian". Seu modelo de segurança e o ciclo de vida das AppVMs impõem restrições rígidas que o
instalador e o runtime **devem** respeitar:

1. **A persistência do sistema de arquivos é seletiva.** Em uma AppVM, apenas **`/home`, `/usr/local` e `/rw`**
   sobrevivem a uma reinicialização; o sistema de arquivos raiz é **restaurado a partir da TemplateVM a cada boot**. Portanto:
   - O aplicativo, seu virtualenv, o banco de dados, os dados coletados, os logs, a trilha de auditoria e quaisquer modelos de LLM
     baixados **devem ficar em `/home/user/...`** (recomendado: `/home/user/open-omniscience`).
   - **Pacotes `apt`/do sistema *não* persistem** se instalados na AppVM. As dependências do sistema devem ser
     instaladas **na TemplateVM** (e a AppVM reiniciada), ou trazidas via `bind-dirs` do Qubes.
     O instalador deve **separar**: "dependências do sistema → TemplateVM" vs "venv Python + aplicativo → `/home` da AppVM."
2. **Nenhuma suposição de raiz persistente.** Alterações na raiz da AppVM desaparecem na reinicialização. Trate a AppVM como:
   `/home` persistente, raiz efêmera.
3. **Rede via uma NetVM.** A AppVM só alcança a internet através da qube de rede/firewall que lhe foi
   atribuída. O aplicativo deve **degradar de forma limpa quando offline** e nunca presumir conectividade.
4. **Sem GPU.** O passthrough de GPU é impraticável em configurações típicas do Qubes → **a inferência de LLM é somente em CPU**.
   Padrão para **modelos pequenos** (ex.: `gemma2:2b`, `llama3.2:3b`, `qwen2.5:1.5b`); modelos grandes são opt-in.
5. **Air-gap / VMs separadas é uma opção *futura* de primeira classe (não na v1).** O Qubes torna natural o padrão "coleta ética em uma
   qube com rede, análise/armazenamento em uma qube-cofre offline" via **qrexec/qubes-rpc**. A v1
   roda em **uma AppVM**; a arquitetura deve manter limpa a fronteira de *busca* (fetch), para que uma separação posterior seja uma
   mudança de implantação, não uma reescrita. (O repositório já contém material vestigial em `src/qubes/rpc/` e
   `docs/QUBES_*` — a ser revisado/substituído, não confiável.)

#### 0.2 Implicações do Python 3.13 (resolve os conflitos de versão de dependências)

- **A stack principal é limpa para 3.13:** FastAPI, uvicorn, SQLAlchemy 2.x, pydantic 2.x, requests, httpx,
  beautifulsoup4, feedparser, numpy, pandas, scipy, scikit-learn, statsmodels — todos publicam wheels para 3.13.
- **O LLM local NÃO exige ML pesado em Python.** O Ollama é um **binário nativo separado**; o aplicativo conversa
  com ele **somente por HTTP**. A capacidade completa de LLM funciona no 3.13 apenas com `httpx`/`requests` — nada de
  `torch`/`transformers` no aplicativo.
- **Bibliotecas de ML pesadas saem do núcleo.** `torch`, `onnx`/`onnxruntime`, `tensorflow`,
  `pyAudioAnalysis` e a stack de deepfake são **removidos** na v1 porque são (a) atualmente
  **forjados** (a "CNN de deepfake" nunca executa inferência), (b) pesados e **somente CPU aqui**, e
  (c) um risco de wheel 3.13 pacote a pacote (`pyAudioAnalysis` não é mantido; `igraph`/`leidenalg`/`gensim`
  devem ser verificados um a um antes do uso). Qualquer recurso de ML futuro deve justificar seu peso e provar que há um wheel para 3.13.
- **Um único manifesto de dependências, fixado em 3.13.** Substituir os seis arquivos de requirements divergentes por um único
  `pyproject.toml` na raiz (`requires-python = ">=3.13"`) + extras opcionais (`[llm]`, `[analysis]`, `[dev]`).
  Apagar os comentários "corretivos" de IA e as fixações de versão impossíveis.

#### 0.3 Modelo de segurança para um único usuário local (simplifica os P0)

Como o único listener é o loopback e o único usuário é você:
- **Autenticação:** nenhuma exigida na v1, *desde que* o servidor se vincule estritamente a `127.0.0.1` e nunca seja exposto
  por uma regra de firewall do Qubes. (Um único token de API opcional pode ser adicionado mais tarde, se houver proxy.) Isso **resolve**
  a constatação "nenhuma autenticação nos endpoints" *para esta implantação* — removendo a exposição de rede em vez de
  adicionar RBAC.
- **`/metrics`:** somente loopback, como todo o resto.
- **A segurança do instalador continua obrigatória:** nada de `rm -rf` sem confirmação, nada de `curl | sh` não verificado, nunca descartar
  o stderr do gerenciador de pacotes — são questões de correção/segurança independentemente de haver um único usuário.
- **Recursos de front-end incluídos localmente (vendored)** (nada de Google Fonts / React por CDN) — necessário para o offline/Qubes e
  para o princípio de privacidade.

---

### 1. Definição em uma frase

O Open-Omniscience é uma **plataforma de inteligência de código aberto e local-first para jornalistas investigativos**
que agrega de forma ética muitas fontes de dados do mundo inteiro em um **corpus único, pesquisável, com referências cruzadas
e procedência rastreada**, com **IA local** opcional para análise — e em que cada resultado é
projetado para ser **defensável científica e juridicamente**.

### 2. Para quem é, e as tarefas para as quais o contratam

**Usuário principal:** um jornalista investigativo, pesquisador ou analista — provavelmente trabalhando sozinho ou em uma
pequena redação, muitas vezes sensível à privacidade (fontes a proteger), às vezes em ambientes restritos/isolados
(air-gapped).

**Principais tarefas a realizar (jobs-to-be-done):**
1. *"Reunir tudo o que é relevante para a minha investigação, de muitas fontes, em um só lugar, automaticamente."*
2. *"Pesquisar e cruzar tudo junto — artigos, mercados, e-mails — para encontrar conexões."*
3. *"Ajude-me a entender grandes volumes de texto"* (resumir, traduzir, extrair entidades) — **sem
   enviar meus dados a ninguém.**
4. *"Diga-me quando algo merece confiança — ou desconfiança"* (verificar mídias, sinalizar manipulação).
5. *"Provar de onde isto veio e que eu não o adulterei"* (procedência para publicação/fins jurídicos).
6. *"Avise-me quando algo mudar"* (uma fonte sai do ar, um preço dispara, uma narrativa surge).

### 3. Princípios orientadores (os inegociáveis)

Estes são o coração da intenção e devem restringir cada recurso. Onde o código atual viola um deles,
isso é um defeito, não uma concessão.

1. **Local-first e capaz de funcionar offline.** Roda inteiramente na máquina/servidor do usuário. Deve funcionar
   sem internet, exceto durante a própria coleta. Adequado para uso air-gapped (com dados/modelos pré-preparados).
2. **Preserva a privacidade.** Nenhuma telemetria. **Nenhum dado do usuário jamais sai da máquina** — especialmente o processamento
   por LLM (local, somente via Ollama). ✅ RESOLVIDO (§0): todos os recursos de front-end (fontes, bibliotecas JS) são
   **incluídos localmente** — nenhuma chamada a CDN — necessário para a postura Qubes/offline.
3. **100% FOSS.** Todo o código e todos os modelos são de código aberto. ⚠️ DECIDE: a licença é **GPLv3** na raiz, mas
   **AGPL-3.0** no Pilar 3 — escolher uma para todo o projeto (a AGPL é mais estrita para uso em rede).
4. **Ético por construção.** Respeitar o `robots.txt` e os limites de taxa, identificar o bot, somente dados públicos,
   nunca contornar paywalls nem usar credenciais para coletar. **Falhar *fechado*** — se a conformidade não puder ser
   verificada, não coletar.
5. **Resultados defensáveis (científica + juridicamente).** Cada resultado analítico traz uma incerteza honesta e
   uma procedência rastreável. **Nenhum número forjado.** Um índice de confiança deve vir de um método real, ou
   não existir. A cadeia de custódia deve ser real (assinada, com evidência de adulteração), não um simples arquivo de log.
6. **Corpus unificado.** Tudo o que é ingerido — notícias, dados financeiros, commodities, e-mail — vive em **um
   banco de dados** e pode ser **cruzado em uma única consulta**. Esta é a razão de ser do produto.
7. **Transparência em vez de falha graciosa.** O sistema nunca deve degradar silenciosamente para um resultado inválido.
   Modelo ausente, fonte bloqueada, dependência indisponível → **status visível e explícito**, nunca um
   espaço reservado silencioso.

### 4. O modelo mental central

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

**A espinha dorsal (ingestão → armazenamento unificado → pesquisa → exportação) deve ser sólida como rocha antes de qualquer pilar.**
Os pilares são *enriquecedores* que leem do armazenamento compartilhado e escrevem de volta nele.

---

### 5. Escopo funcional, por área de capacidade

#### 5.1 Ingestão de dados (P0)
- **Tipos de fonte:** sites de notícias (HTML), feeds RSS/Atom. Mais tarde: APIs, plataformas sociais, depósitos de arquivos.
  ⚠️ DECIDE: o Pilar 4 lista Twitter/X, Reddit, Telegram, Mastodon, S3/SFTP — confirmar quais (se algum)
  estão de fato no escopo vs. são aspiracionais.
- **Coletor ético (implementação única e compartilhada):** verificação do robots.txt (em cache, ciente de http+https,
  **fail-closed** em caso de incerteza), limite de taxa por fonte, User-Agent identificador, novas tentativas/backoff.
  **Uma busca por URL** — sem busca dupla, sem caminho bruto de contorno.
- **Desduplicação:** baseada em hash do conteúdo + URL canônica; nunca armazenar o mesmo artigo duas vezes.
- **Normalização:** extrair de forma confiável título, autor, data de publicação, idioma, URL canônica e texto do corpo.
  ⚠️ DECIDE: a extração real de notícias exige regras por site ou uma biblioteca (ex.: no estilo trafilatura); a
  abordagem atual de CSS genérico produz silenciosamente "No Title/No Content." Confirmar que adotamos uma extração robusta.
- **Agendamento e atualizações incrementais:** nova coleta periódica, buscar somente conteúdo novo/alterado, retomar
  execuções interrompidas.

#### 5.2 Armazenamento de dados unificado (P0)
- **Banco de dados único** contendo todos os tipos de entidade, com **tabelas de ligação** explícitas que os conectam
  (artigo ↔ instrumento financeiro, artigo ↔ commodity, artigo ↔ e-mail, artigo ↔ entidade nomeada).
- **Campos de procedência em cada registro:** fonte, carimbo de data/hora da busca, URL original, hash do conteúdo,
  separação entre bruto e processado.
- **Backends:** SQLite para uso monousuário/desktop; PostgreSQL para uso em servidor/concorrente.
  ⚠️ DECIDE: confirmar SQLite como padrão + Postgres opcional (os documentos mencionam ambos; e também Redis para cache —
  entra ou não?).
- **Log de auditoria:** registro apenas de acréscimo (append-only), **com evidência de adulteração**, de cada ingestão e mutação.

#### 5.3 Pesquisa e recuperação (P0)
- **Pesquisa de texto completo** em todo o corpus.
- **Operadores booleanos** (`AND`/`OR`/`NOT`), **frases entre aspas** e **parênteses com precedência
  correta** — implementados com uma gramática real ou com o FTS nativo do banco, não com gambiarras de strings.
- **Filtros estruturados:** fonte, intervalo de datas, idioma, tags/categoria, entidade, tipo de dado.
- **Paginação**, ranqueamento de resultados, trecho/destaque.
- **Exportação:** CSV e JSON (e ⚠️ DECIDE: formatos PDF/relatório?), fiel ao conjunto de resultados filtrado.

#### 5.4 Referências cruzadas e correlação (P1 — o diferencial)
- Navegar de qualquer registro para registros relacionados de outros tipos (artigo → empresas mencionadas → variações de preço
  perto da data de publicação → e-mails relacionados).
- **Motores de correlação** (financeiro/commodity ↔ notícias) que revelam relações *candidatas* com uma
  **medida honesta e definida** (e rotulam claramente que correlação ≠ causalidade). Nenhum valor-p forjado.
- Visão centrada em entidades: tudo o que o corpus sabe sobre uma pessoa/organização/lugar/instrumento.

#### 5.5 Análise por LLM local (P1)
- **Runtime:** Ollama, totalmente local. Os modelos são intercambiáveis; entregar um padrão pequeno e sensato que *realmente
  exista*. ⚠️ DECIDE: o padrão atual `gemma4:e2b` e a maioria dos modelos listados (Gemma 4, Llama 4, Qwen 3.5)
  são alucinados — substituir o catálogo por tags reais (ex.: `gemma2:2b`, `llama3.2:3b`, `qwen2.5`,
  `phi3`).
- **Capacidades:** gerar, conversar (com contexto), extrair (entidades/palavras-chave/resumos/citações/links),
  traduzir (vários idiomas), analisar (sentimento/tom/legibilidade; viés somente se honestamente delimitado),
  sintetizar (resumos, comparações, linhas do tempo, relatórios), em lote.
- **Degradar ruidosamente:** se o Ollama ou o modelo estiver ausente, dizê-lo — nunca devolver uma análise falsa.

#### 5.6 Verificação e defesa contra a desinformação — *Pilar 3* (P2, escopo a definir)
- **Intenção:** detectar mídias manipuladas (deepfakes de imagem/vídeo/áudio), técnicas de propaganda, vieses
  cognitivos, bots e campanhas coordenadas; validar metadados (EXIF/ID3) e a consistência entre modalidades.
- ⚠️ DECIDE (importante): hoje isto é **forjado** — a "CNN de deepfake" nunca executa inferência; as pontuações
  são heurísticas de desfoque; a cobertura de viés/propaganda é em grande parte inalcançável; "precisão >95%" é aspiracional.
  Escolher uma opção:
  - **(a) Cortar** a perícia de mídia por enquanto e entregar somente o que é honesto (a validação de metadados/EXIF é real
    e útil); **(b) Reconstruir** com modelos FOSS genuínos e avaliados, com precisão publicada; ou
    **(c) Manter**, mas **rotular claramente como "heurística experimental, não prova."**
  Minha recomendação: (a) agora, (b) mais tarde. Uma perícia forjada é o maior passivo isolado para uma
  ferramenta de jornalismo/jurídica.

#### 5.7 Rigor científico — *Pilar 2* (P1)
- **Intenção:** tornar defensáveis as afirmações quantitativas da plataforma — testes estatísticos reais, intervalos
  de confiança, pontuação de reprodutibilidade/linhagem e "revisão por pares" por meio de vários LLMs locais verificando-se mutuamente.
- Este pilar é o mais genuinamente implementado (scipy/statsmodels reais). Manter, reforçar e torná-lo o
  **porteiro**: qualquer número que o aplicativo mostre ao usuário deve passar por um relato honesto da incerteza.

#### 5.8 Monitoramento e alertas em tempo real — *Pilar 4* (P2)
- **Intenção:** vigilância contínua das fontes; detecção de anomalias/tendências/padrões; enriquecimento com inteligência de ameaças;
  alertas multicanal (e-mail/webhook/chat) com regras e escalonamento.
- ⚠️ DECIDE: as verificações de saúde atuais são simuladas (`sleep; return HEALTHY`) e a inteligência de ameaças/STIX-TAXII
  não existe. Confirmar o escopo: um monitoramento real da disponibilidade das fontes + alertas de anomalia sobre o corpus é
  viável e valioso; STIX/TAXII, SMS/Twilio, Slack/Teams são pesados — entram ou não?

#### 5.9 Inteligência financeira — *Pilar 5* (P2, marcado 0% nos documentos)
- **Intenção:** coletar dados de bolsas do mundo inteiro (OHLC + fundamentos) a partir de fontes abertas da web (sem APIs/paywalls),
  detectar flutuações/padrões/anomalias e **correlacionar movimentos de preço com notícias** no banco compartilhado.
- ⚠️ DECIDE: isto é **somente design (0% construído)**, apesar do código de esqueleto já commitado. Confirmar que é um alvo
  real e, se for, seu primeiro escopo realista (ex.: um punhado de bolsas, OHLC diário, correlação com
  artigos) em vez de "50+ bolsas / 10.000+ empresas" desde o primeiro dia. Nota: uma coleta robusta de várias bolsas
  sem APIs é uma empreitada grande e frágil.

#### 5.10 Inteligência sobre terras raras / commodities — *Pilar 6* (P2, marcado 0% nos documentos)
- **Intenção:** o mesmo padrão do Pilar 5 para os 17 elementos de terras raras — preços, produção, estoques,
  correlacionados a eventos geopolíticos/noticiosos; com previsão.
- ⚠️ DECIDE: também **somente design (0% construído)**. Confirmar o escopo e a prioridade em relação ao Pilar 5. (Correção necessária: a
  matemática de unidades na normalização de preços está atualmente errada em ~1000×, e a moeda não é convertida.)
  ⚠️ DECIDE: a "previsão" está no escopo? Previsão honesta, com incerteza, é difícil; recomenda-se adiar.

#### 5.11 Inteligência de e-mail e newsletters (P1/P2)
- **Intenção:** recuperar de IMAP/POP3 e de fontes de newsletters (Substack/Mailchimp/RSS-para-e-mail), analisar +
  limpar, tratar anexos (PDF/Office/imagens com OCR), extrair entidades e redes de comunicação,
  e **incorporá-los ao mesmo corpus pesquisável**.
- **Privacidade/consentimento são primordiais aqui** (comunicações privadas): autorização explícita, armazenamento
  criptografado de credenciais, minimização de dados, retenção/direito ao esquecimento.
- ⚠️ DECIDE: integrações com APIs de newsletters (Substack/Mailchimp/etc.) vs. apenas IMAP + RSS-para-e-mail na v1?

#### 5.12 GUI / UX (P0 para o núcleo, P1+ para os painéis dos pilares)
- **GUI principal:** interface de pesquisa, navegação nos resultados, gestão de fontes, exportação, painéis básicos.
- **Painéis dos pilares (mais tarde):** mapas de calor/gráficos financeiros, visões de commodities, monitoramento/alertas, caixa de entrada
  de e-mail, explorador de correlações.
- ✅ RESOLVIDO (§0): **interface web servida pelo FastAPI em `127.0.0.1:8000`; o aplicativo desktop em Tkinter é abandonado**
  (remover `python3-tk`). Abrir no navegador da AppVM.
- ✅ RESOLVIDO (§0): o front-end é **JS puro (vanilla) + bibliotecas incluídas localmente (servidas a partir de `/static`)** — sem CDN.
  ⚠️ DECIDE (menor): manter gráficos leves (ex.: uma pequena biblioteca de gráficos incluída localmente) vs. nenhum na v1.

#### 5.13 Relatórios e resultados defensáveis (P1)
- Gerar relatórios de investigação que reúnam as constatações **com sua procedência** (fontes, carimbos de data/hora,
  hashes, métodos, incerteza).
- **Cadeia de custódia / integridade:** assinatura criptográfica + evidência de adulteração nas provas exportadas
  (os módulos de criptografia existem, mas não estão conectados). É isso que torna real, e não decorativa, a alegação de
  "admissibilidade jurídica".

---

### 6. Requisitos não funcionais

- **Plataforma:** ✅ RESOLVIDO (§0) — **AppVM Debian do Qubes OS** é o *único* alvo suportado na v1
  (construído e testado ali). Um Debian 13 comum pode funcionar, mas não é um objetivo; nenhum compromisso multiplataforma.
- **Python:** ✅ RESOLVIDO (§0) — **3.13**, de forma consistente em `pyproject.toml`, `.python-version` e
  em qualquer CI. Abandonar dependências que não tenham wheels para 3.13 (ver §0.2).
- **Pegada de instalação:** um verdadeiro **núcleo mínimo** (web + banco + pesquisa, leve) separável dos
  extras opcionais (`[llm]`, `[analysis]`). **Um** `pyproject.toml` — não seis manifestos divergentes. O instalador
  respeita a persistência do Qubes (§0.1): dependências do sistema na TemplateVM, venv+dados em `/home`.
- **Segurança:** ✅ RESOLVIDO (§0) — único usuário local, **somente loopback**, portanto sem RBAC. Ainda obrigatórios:
  somente acesso parametrizado ao banco (apagar o "sanitizador" por lista de bloqueio), nenhum segredo no código, `/metrics` em loopback,
  e um **instalador seguro** (nada de `rm -rf` sem confirmação, nada de `curl | sh` não verificado, nunca descartar o stderr dos pacotes).
- **Desempenho:** E/S não bloqueante para o trabalho de rede/LLM; concorrência limitada; o aplicativo continua responsivo durante
  a coleta/inferência. Premissas **somente CPU** (sem GPU no Qubes). Metas definidas conforme os recursos realistas de uma AppVM,
  não aspiracionais.
- **Offline:** todos os recursos, fontes e modelos (baixados previamente) são locais; procedimento documentado para operar com a
  NetVM desconectada depois que os dados/modelos tiverem sido obtidos.
- **Observabilidade:** logs estruturados (em `/home`), verificações de saúde honestas, métricas Prometheus em loopback —
  refletindo o estado real.

### 7. Não objetivos explícitos / fora do escopo (proposta — ajustar)

- Não é um rastreador/espelho da web de uso geral (a linhagem HTTrack é vestigial; abandonar esse enquadramento).
- Não é um coletor que contorna paywalls, faz credential stuffing ou viola Termos de Serviço.
- Não é um produto em nuvem/SaaS; nenhuma API de IA externa.
- ⚠️ DECIDE: a previsão (5.10), a ingestão de redes sociais (5.8) e a perícia de mídia (5.6) entram ou não
  na primeira versão real?

### 8. Modelo de dados, procedência e defensabilidade jurídica (transversal)

- Cada item armazenado: `{source, original_url, fetched_at, content_hash, raw_payload_ref, processing_log}`.
- Cada resultado derivado/analítico: `{method, version, inputs_ref, uncertainty/confidence_basis,
  computed_at}` — **a confiança nunca é uma constante fixa no código.**
- Provas exportadas: opcionalmente **assinadas**, com um manifesto verificável (hashes + Merkle/GPG) para que um
  terceiro possa confirmar a integridade. Este é o significado concreto de "Pilar 4: Admissibilidade jurídica."

### 9. Decisões (consolidadas)

**✅ Resolvidas pelo contexto de implantação (§0):**
- **3. Implantação e modelo de ameaça** → único usuário local, AppVM Debian do Qubes, somente loopback, sem RBAC.
- **7. GUI** → interface web em `127.0.0.1:8000`, JS puro, recursos incluídos localmente; Tkinter abandonado.
- **8. Plataforma/Python** → AppVM Debian do Qubes, Python 3.13, SQLite como padrão (Postgres/Redis **fora** na v1).

**⚠️ Ainda em aberto (a decisão é sua — padrões sensatos propostos):**
1. **Escopo do MVP:** *proposta* — primeiro somente o Núcleo confiável (Fase 1), depois o LLM. Confirmar.
2. **Estratégia de reconstrução:** *proposta* — aproveitar as poucas partes boas (modelos do banco, `ethical_scraper`,
   `async_db`, esqueleto FastAPI), apagar os pilares forjados e reconstruir o núcleo em torno delas. Confirmar vs.
   começar do zero por completo.
4. **Perícia de mídia (Pilar 3):** *proposta* — **(a) cortar** deepfake/propaganda/viés na v1 (também
   hostis ao 3.13/CPU), **manter** a validação real de metadados/EXIF. Confirmar.
5. **Financeiro (5) e commodities (6):** *proposta* — adiar para a Fase 3, depois construir **uma** vertical enxuta.
   Qual primeiro?
6. **E-mail:** *proposta* — somente IMAP + RSS-para-e-mail na v1; adiar as integrações com APIs de newsletters. Confirmar.
9. **Licença:** GPLv3 vs AGPL-3.0 para todo o projeto — ainda precisa de uma decisão.
10. **Confirmação do que fica fora do escopo:** previsão, ingestão de redes sociais, STIX/TAXII, alertas por SMS/chat —
    *proposta*: fora na v1.

### 10. Faseamento sugerido (proposta, não compromisso)

- **Fase 1 — Núcleo confiável:** ingestão ética → armazenamento unificado (com procedência) → pesquisa booleana/
  de texto completo correta → exportação → GUI web mínima → testes reais. *Todo o resto desligado até isto estar verde.*
- **Fase 2 — LLM local + rigor científico:** conectar o Ollama (modelos reais, degradação ruidosa); fazer do Pilar 2
  o portão de honestidade para qualquer número exibido.
- **Fase 3 — Uma vertical + correlação:** escolher **ou** financeiro **ou** commodities, construir uma fatia enxuta mas
  real, provar de ponta a ponta a experiência de correlação artigo↔dados.
- **Fase 4 — Monitoramento/alertas, e-mail, verificação (metadados primeiro):** adicionar enriquecedores um de cada vez,
  cada um funcionando de verdade e testado.
- **Fase 5 — Relatórios defensáveis:** conectar assinatura real/cadeia de custódia às exportações.

---

### 11. Estado de implementação (atual)

O que está construído e testado hoje, mapeado ao escopo acima (a intenção não muda; estas
notas indicam onde a realidade está agora). Veja os documentos de recursos vinculados para detalhes.

- **Núcleo confiável (5.1–5.3, 5.13):** ✅ ingestão ética, armazenamento unificado com procedência,
  pesquisa booleana FTS5, exportação CSV/JSON, cadeia de custódia assinada.
- **Ingestão em escala (5.1):** ✅ **agendador** dentro do aplicativo (iniciar/parar, intervalo, modos
  rss/crawl/markets) e um **rastreador recursivo limitado** (*descoberta* no mesmo domínio,
  robots fail-closed, limites de profundidade/páginas) — não um espelho de uso geral (§7 respeitado).
- **GUI (5.12):** ✅ interface web com abas — Pesquisa · Ingestão · **Fontes e banco de dados** (estatísticas,
  gestão de fontes, **cobertura mundial**) · **Mercados** · **Análises** · Cadeia de
  custódia · **Configurações** (tema + backup/restauração do SQLite). Sem dependências, offline.
- **Financeiro e commodities (5.9, 5.10):** ✅ vertical real e enxuta — **regras de extração** de preços
  por fonte, **feeds CSV oficiais** (FRED→Banco Mundial/EIA), gráficos e
  correlação preço↔notícias honesta. Matemática de unidades corrigida; números somente a partir de uma regra verificada
  ou de um CSV importado. Veja [USER_MANUAL.md](USER_MANUAL.md).
- **Cobertura mundial de fontes:** ✅ catálogo de mercados empacotado + um **gerador derivado de dados**
  (Wikidata CC0) para veículos de mídia **e** instituições por país, com um
  relatório de cobertura. Importação/exportação CSV da lista de fontes. Veja
  [ROADMAP.md](archive/roadmaps/DESIGN_MEMORY_pre-0.2.md).
- **Referências cruzadas e correlação (5.4):** ✅ **análise de palavras-chave e entidades** —
  extração na ingestão, armazenamento de menções com contexto, tendências, associações PMI
  ("mapa mental") e um mapa por país/cidade. Veja [USER_MANUAL.md](USER_MANUAL.md).
- **Wikipedia como fonte rastreada (novo):** 🚧 base do rastreamento de alterações (edições por
  idioma, armazenamento de deltas, sinalização de grandes edições/revisionismo incl. ORES) — esquema +
  parser + sinalização prontos; sondagem ao vivo, aba e baixador offline a seguir. Veja
  [USER_MANUAL.md](USER_MANUAL.md).
- **Verificação (5.6):** ✅ somente EXIF/metadados de imagem honestos (a perícia forjada
  continua em quarentena). **LLM (5.5)**, **monitoramento/alertas (5.8)**, **e-mail (5.11)**:
  parciais/na fila.

---


---

## Mapa de intenção dos pilares — onde vive agora o propósito de cada pilar

O design original organizava a plataforma em seis "pilares". Essas árvores de pilares
somavam ~50 mil linhas que o aplicativo em execução nunca importava — em grande parte somente design ou
forjadas. **Sua *intenção* foi preservada**: o propósito genuíno de cada pilar
é agora um módulo pequeno, honesto e testado dentro de `src/` (ou foi explicitamente adiado).
As árvores de pilares originais são mantidas em `quarantine/pillars/` para referência e
histórico; nada é apagado.

| Pilar (intenção) | Onde a intenção vive agora | Status |
|---|---|---|
| **1 — Ingestão de dados** (coleta ética → armazenamento unificado) | `src/ingest/` (fetcher, extract, pipeline, email) + `src/database/` | ✅ Real, testado |
| **2 — Rigor científico** (estatística honesta, incerteza) | `src/analysis/` (`statistical_tests`, `confidence_intervals`) + `POST /api/analysis/*` | ✅ **Aproveitado o código genuíno de scipy/statsmodels** + seus 60 testes |
| **3 — Defesa contra a desinformação** (verificar mídias) | `src/verification/metadata.py` (EXIF/metadados honestos) + `POST /api/verify/image-metadata` | ✅ Escopo honesto. Os detectores de deepfake/propaganda/viés eram forjados → `quarantine/pillar3_analysis/` |
| **4 — Monitoramento + admissibilidade jurídica** | `src/monitoring/` (disponibilidade real + anomalias) e `src/reporting/` + `src/crypto/` (provas assinadas com Merkle + Ed25519) | ✅ Real, testado |
| **5 — Inteligência financeira** | *Adiado.* O padrão está comprovado pela reimplementação do Pilar 6; uma vertical financeira pode reutilizar `src/commodity` + `src/analysis`. | ⏸ Originalmente somente design (0%); ainda não construído |
| **6 — Terras raras / commodities** | `src/commodity/` (preços, conversão de unidades correta, correlação scipy **real**, importação CSV) + `POST /api/commodities/*` | ✅ Real, testado |

### O que foi aproveitado nesta etapa (Pilar 2)
- `src/analysis/statistical_tests.py` — testes t, ANOVA, qui-quadrado, Pearson/Spearman,
  Mann-Whitney, Wilcoxon, regressão, Tukey HSD (scipy/statsmodels). Cada resultado
  traz a estatística, o valor-p, os graus de liberdade, o tamanho do efeito e o tamanho da amostra.
- `src/analysis/confidence_intervals.py` — médias e proporções (t/normal/Wilson/
  Clopper-Pearson/Agresti-Coull).
- Exposto em `POST /api/analysis/{t-test,correlation,anova,mann-whitney,confidence-interval}`
  para que um jornalista possa verificar se um padrão em seus dados é realmente significativo.
- As suítes de testes genuínas do Pilar 2 foram transferidas junto com o código (`tests/test_statistical_tests.py`,
  `tests/test_confidence_intervals.py`).

### O que NÃO foi aproveitado (e por quê)
- `peer_review` / `consensus` / `reproducibility` do Pilar 2 — especulativos ou superficiais
  (ex.: a reprodutibilidade era uma rubrica de média de booleanos). Postos de lado; a reviver com métodos
  reais, se necessário.
- Os detectores periciais do Pilar 3, o monitoramento/inteligência de ameaças simulados do Pilar 4, os esqueletos dos Pilares
  5/6 — forjados ou somente design; as partes honestas já estão em `src/`.

### Efeito líquido
O repositório agora reflete o que de fato roda: um núcleo vivo de ~16 mil linhas (mais a
estatística aproveitada), com as ~50 mil linhas aspiracionais/forjadas dos pilares postas de lado em
`quarantine/pillars/` em vez de se fazerem passar por recursos funcionais.


---

## Redesenho da GUI — "0.05"

> Um redesenho completo da interface do Open Omniscience, pensado a partir do usuário
> para fora. Este documento é o *porquê*; `src/static/index.html` é o *quê*.
> Leia isto primeiro se quiser entender (ou contestar) as decisões.

---

### 0. A encomenda, reformulada

Redesenhar toda a GUI para uma pessoa específica: **um operativo em busca da verdade — um
investigador/jornalista que *não* gosta de computadores**, que quer entender
o mundo como ele realmente é e comunicar suas descobertas com credibilidade. O resultado deve ser
elegante, bonito, adaptável, altamente personalizável, simples *e* profundo, e bom
o bastante para que um colega olhando por cima do ombro diga *"o que é isso — posso ter
também?"* Deve respeitar o que o projeto já é: **monousuário, somente loopback,
offline-first, sem dependências, sem telemetria**, regido pela **Carta de Munique**
(verdade, verificação das fontes, privacidade, nada de propaganda).

#### Postura de engenharia (e a concessão honesta)

A interface anterior é um único `index.html` de 2.200 linhas que liga ~110 funções a ~150
endpoints da API. Essas funções *funcionam e são testadas*. Uma reescrita do zero teria
produzido uma casca mais bonita com grande chance de botões silenciosamente quebrados — o
exato oposto de uma ferramenta cujo argumento de venda inteiro é a **honestidade**. Então este é um
**redesenho total de tudo o que o usuário vê e toca** — linguagem visual,
layout, modelo de navegação, arquitetura da informação, nomenclatura, integração inicial (onboarding),
personalização e duas superfícies totalmente novas (um painel Início e um leitor de
documentação dentro do aplicativo) — construído *sobre a camada de dados comprovada*, com cada ID de elemento original
preservado para que nada regrida. A ausência de dependências continua absoluta: **nenhuma CDN, nenhuma fonte
web, nenhum framework** — um único arquivo autossuficiente que roda com a NetVM desconectada.

---

### 1. Personas (a quem de fato servimos)

**Amara — jornalista investigativa, 44 anos. Persona principal.**
Cobre corrupção em compras públicas. Repórter brilhante, usuária relutante de computador. Trabalha
em matérias sensíveis e é (com razão) paranoica com vigilância e perda de dados.
*Precisa:* encontrar coisas rapidamente em seu próprio corpus; provar que um documento é autêntico e
inalterado; exportar algo que possa entregar a um editor ou a um tribunal; nunca se sentir burra.
*Teme:* perder trabalho, ser rastreada, jargão, parecer amadora ao lado de um colega "da tecnologia".
*Condição de vitória:* ela abre o aplicativo e sabe imediatamente o que fazer, e o que ela
produz parece confiável e *é* confiável.

**Daniel — pesquisador OSINT freelancer, 29 anos. Persona avançada.**
Semitécnico, rápido, guiado pelo teclado, acompanha muitas fontes. *Precisa:* densidade, operações
em lote, tendências/associações, correlações de mercado, atalhos de teclado, uma paleta
de comandos. *Teme:* um acompanhamento passo a passo que o atrase; recursos escondidos.
*Condição de vitória:* ele nunca precisa tocar no mouse e encontra poder avançado à mão.

**A irmã de causa — a "operativa", na casa dos 50. Persona de valores.**
Desconfia das Big Techs; quer soberania. *Precisa:* prova de que nada "liga para casa"; funcionamento
offline; explicações simples do que cada ação faz com sua exposição na rede.
*Condição de vitória:* ela consegue ler, dentro do aplicativo, exatamente o que ele fará e o que não fará.

**Elliot — o editor, 38 anos. Persona destinatária.**
Nunca abre o aplicativo; *recebe* seus resultados. *Precisa:* exportações legíveis e
verificáveis por si mesmas. A interface o atende indiretamente: pacotes de provas, custódia
assinada, CSV/JSON limpos.

**Implicação de design:** liderar para Amara (clareza, orientação, confiança), acrescentar em camadas a
profundidade de Daniel para que nunca atrapalhe Amara (revelação progressiva + paleta de comandos),
honrar a soberania da operativa no texto e no comportamento, e tornar os
artefatos de Elliot cidadãos de primeira classe.

---

### 2. Princípios de design (derivados, não emprestados)

1. **Clareza acima de engenhosidade.** Verbos simples, rótulos humanos, uma ação principal óbvia
   por tela. O jargão ("ingestão", "corpus", "raiz de Merkle") é traduzido ou
   explicado no próprio texto, nunca pressuposto.
2. **A confiança é o produto.** A verificabilidade, a procedência e o "este número é real,
   não estimado" ficam à vista, não enterrados. A estética deve *parecer* um
   instrumento, não um brinquedo.
3. **Revelação progressiva.** Simples por padrão; a profundidade a um clique. Os painéis
   avançados se recolhem; módulos raramente usados podem ser totalmente ocultados.
4. **Personalizável, porque a confiança é pessoal.** Temas, cor de destaque, densidade, tamanho da fonte,
   layout e *quais ferramentas sequer aparecem* cabem ao usuário definir — e persistem
   somente localmente.
5. **Honestidade na interface.** Se uma capacidade depende de um extra opcional, a
   interface diz isso em vez de fingir. Nada simula sucesso.
6. **Soberano por construção.** Nenhuma requisição externa de qualquer tipo. O visual é
   obtido com fontes do sistema e ícones SVG feitos à mão.
7. **Teclado em primeiro lugar também é acessibilidade em primeiro lugar.** Uma paleta de comandos e atalhos
   servem a Daniel *e* tornam todo o aplicativo alcançável sem precisão no mouse.

---

### 3. Análise ferramenta por ferramenta — prós, contras, decisão

O antigo conjunto de abas superiores: *Search · Ingest · Sources · Database · Markets · Insights ·
Wikipedia · Chain of custody · Settings.* Avaliadas uma a uma para as nossas personas.

| Aba antiga | Prós | Contras | **Decisão** |
|---|---|---|---|
| **Pesquisa** | O ato central. Todos precisam dela. | Enterrada como uma aba entre nove; nenhuma orientação para um usuário novo. | **Manter e elevar.** Torna-se o coração, alcançável instantaneamente; um novo **Início** dá orientação em torno dela. |
| **Ingest** | Necessária para trazer os dados. | "Ingest" é jargão de engenheiro; intimidante; misturava agendador + busca manual. | **Manter, renomear → "Recolher."** Começar pela ação manual simples; o agendador vira "Coleta automática", apresentada como "configure e esqueça". |
| **Fontes** | A credibilidade vive aqui; a procedência começa pelo *onde*. | Tabelas densas; parecia administração, não jornalismo. | **Manter, reenquadrar como "Fontes" (a lista de pautas da sua redação).** Reestilizada para se ler como uma biblioteca, não como um console de banco de dados. |
| **Banco de dados** | Contagens ao vivo honestas; backup/restauração. | "Banco de dados" não significa nada para Amara; ela tem uma *biblioteca/arquivo*, não um BD. | **Manter, renomear → "Biblioteca."** As mesmas contagens reais e a mesma cobertura mundial, apresentadas como "o que você reuniu". |
| **Mercados** | Poderosa para investigações do tipo "siga o dinheiro". | Irrelevante para a maioria das matérias; pesada, de nicho; poluição visual para Amara. | **Manter, marcar como Avançada, ocultável.** Fora do caminho crítico; um único botão a remove para quem não faz trabalho financeiro. |
| **Análises** | A vitrine visual — tendências, associações, mapa. O "uau". | Era uma discreta aba do meio; subvalorizada. | **Manter e promover.** É um recurso de destaque; ganha proeminência e acabamento. |
| **Wikipédia** | Encaixe forte: "o mundo como ele realmente é", conhecimento offline, detecção de guerras de edição. | Duas coisas diferentes (rastreamento ao vivo vs. dumps offline pesados) espalhadas por abas de forma confusa. | **Manter.** O rastreamento fica aqui; os dumps pesados ficam em Configurações, com referências cruzadas claras (já feito em trabalho anterior). |
| **Cadeia de custódia** | O diferencial de confiança. É o que faz Elliot confiar no resultado e Amara parecer profissional. | Nome em juridiquês; parecia um cofre que poucos abririam. | **Manter, renomear → "Provas e custódia", promover.** Faz parte do momento "o que é isso?!". |
| **Configurações** | Necessária. | Era uma gaveta de bagunça (preferências + filtro de palavras-chave + dumps + backup). | **Manter, reestruturar** em seções (Aparência · Geral · Wikipédia · Dados e cópia de segurança · Segurança). *(0.07: a gaveta Personalizar, que era independente, foi incorporada como a seção **Aparência** — um único lugar para a aparência, menos elementos flutuantes.)* |

#### Novas superfícies adicionadas

- **Início (painel).** *Justificativa:* Amara precisa de orientação, não de uma caixa de pesquisa vazia.
  Status num relance (tamanho do corpus, fontes, agendador, última atividade), grandes ações
  rápidas ("Pesquisa", "Coletar agora", "Verificar um documento") e um estado vazio que
  ensina. É o maior ganho de usabilidade isolado para a persona principal.
- **Ajuda / leitor de documentação.** O usuário pediu explicitamente acesso direto ao manual
  detalhado. Uma superfície **Ajuda** de primeira classe exibe o Manual do usuário (e outros documentos)
  *dentro* do aplicativo — pesquisável, offline, sem sair da ferramenta. Também alcançável pela
  barra superior (`?`) e pela paleta de comandos.

#### Arquitetura da informação resultante

A faixa plana de 9 abas se torna uma **barra lateral agrupada** (recolhível em ícones), ordenada
segundo o fluxo real do trabalho:

- **Investigar** — Início · Pesquisa · Análises · Mapa temporal · Wikipédia · *Mercados (avançado)*
- **Recolher** — Recolher · Fontes · Biblioteca
- **Confiança** — Provas e custódia
- **Sistema** — Configurações · Ajuda

O agrupamento transforma "nove estranhos iguais" em "quatro intenções", que é como Amara
pensa ("quero *encontrar* algo" / "quero *reunir*" / "quero *provar*").

---

### 4. O "uau" — o que faz um jornalista se inclinar para a tela

- **Um sistema visual coerente.** Um tema escuro "tinta" profundo por padrão, com uma única
  cor de destaque confiante, um ritmo de espaçamento generoso, uma hierarquia tipográfica real, fonte monoespaçada para
  dados/hashes, profundidade suave e movimento contido. Ele se lê como *instrumento*, não como
  *modelo de dashboard*.
- **Paleta de comandos (Ctrl/⌘-K).** Digite para ir a qualquer lugar, executar qualquer ação ou abrir
  qualquer documento. Poder para Daniel; um mapa de "o que eu posso fazer aqui, afinal?" para Amara.
- **Controles de aparência** (Configurações → Aparência; uma gaveta ao vivo até a 0.06, incorporada
  às Configurações na 0.07). Predefinições de tema (Ink, Slate, Midnight, Paper, Sepia,
  Terminal, High-contrast), amostras de cor de destaque, densidade, tamanho da fonte, recolhimento da barra lateral
  e **visibilidade dos módulos** — tudo instantâneo, tudo local, tudo persistente.
- **Um Início que orienta**, uma integração inicial que ensina e estados vazios que guiam.
- **A confiança, tornada visível.** Custódia/verificação e o enquadramento "medido, não estimado"
  fazem parte da estética, não das letras miúdas.
- **Integridade offline total.** Nenhuma chamada de rede para a interface em si — o que é, por si só, um
  recurso que você pode *mostrar* a um colega preocupado com segurança.

---

### 5. Modelo de personalização

A aparência é armazenada em `localStorage` (`oo.ui`) — nunca enviada a lugar algum — por isso é
instantânea e sobrevive offline. As preferências funcionais (limite padrão de resultados, tema
base) continuam a persistir no lado do servidor via `/api/settings`. Personalizáveis: predefinição
de tema, cor de destaque, densidade, escala da fonte, estado da barra lateral e o conjunto de
módulos visíveis. Padrões sensatos significam que um usuário em primeira execução não mexe em nada disso.

---

### 6. O que eu deliberadamente **não** fiz (honestidade)

- **Nenhum framework / etapa de build / CDN.** Isso quebraria o ethos offline, auditável e soberano
  em troca de um ganho cosmético. JS puro, um único arquivo, fontes do sistema, SVG desenhado à mão.
- **Nenhum recurso forjado.** Cada botão corresponde a um endpoint real e funcional. Uma capacidade
  que depende de um extra opcional continua dizendo isso.
- **Nenhuma mudança silenciosa no backend** além de um endpoint de documentação aditivo, somente leitura e com lista de permissões
  (`/api/docs`) para alimentar o leitor da Ajuda.
- **Os campos de idioma em texto livre continuaram em texto livre** (já anotado em OPEN_QUESTIONS);
  o redesenho não inventa menus suspensos que o backend não consiga sustentar.

---

### 7. Status

A `0.05` é agora o **branch padrão** do repositório (linha principal); as linhas anteriores (0.04
e antes) permanecem no histórico do git. A paridade funcional é preservada (mesmos IDs de
elementos, mesma ligação); a mudança é tudo o que está *em volta* desse motor. O padrão entrega
**duas** interfaces — Console (`/`) e Desk (`/desk`) — comparadas em
[`DESIGN.md`](DESIGN.md).


---

## Duas interfaces, um argumento — "Console" vs "Desk"

> Você pediu um argumento *contraditório*: não uma defesa do redesenho 0.05, mas
> uma argumentação honesta de que ele pode ser a interface **errada** para este aplicativo — e uma
> alternativa concreta contra a qual testá-lo. Este documento é esse argumento. As duas
> interfaces são entregues lado a lado para que você possa usar ambas sobre os mesmos dados e julgar
> por si mesmo.

---

### 0. Primeiro, voltar ao que este aplicativo realmente é

Antes de discutir a interface, os inegociáveis (de `ETHICS.md`,
`DESIGN.md`, da Carta de Munique):

- **Um usuário, uma máquina, somente loopback, offline-first.** Sem contas, sem nuvem,
  sem telemetria. Frequentemente executado em uma AppVM do Qubes com a qube de rede *desconectada*.
- **Um operativo em busca da verdade que não gosta de computadores.** Um investigador /
  jornalista cujo trabalho é *entender a realidade e comunicá-la com credibilidade*.
- **O produto é a confiança.** Procedência, verificação das fontes, "medido, não
  estimado", evidência de adulteração. A Carta de Munique (verdade, verificar as fontes, proteger as
  fontes, resistir à propaganda) é a espinha dorsal.
- **A soberania como estética.** A ferramenta deve *parecer* pertencer ao usuário,
  não a uma plataforma.

Qualquer interface deve ser julgada em relação a *isso*, não em relação a "parece um
produto SaaS de 2025".

---

### 1. O libelo acusatório contra o "Console" (o redesenho 0.05)

Apresentando da forma mais forte possível o argumento de que a 0.05 é a direção errada:

1. **Ela veste uma ferramenta soberana com as roupas do capitalismo de vigilância.** Barra lateral
   esquerda persistente, pílulas de status, paleta de comandos, uma gaveta de personalização com oito
   temas — esta é a gramática visual do Slack, do Linear, do Notion: *SaaS em nuvem*. Para
   um usuário que desconfia das Big Techs e trabalha em matérias sensíveis, essa gramática pode
   ser lida como "mais um aplicativo que me vigia", minando a única coisa que mais importa
   aqui: a confiança. O visual luta contra os valores.

2. **Ela otimiza para a demonstração, não para o trabalho.** A encomenda incluía "fazer um
   jornalista dizer *posso ter também?*" — uma reação de cinco segundos por cima do ombro.
   Projetar para isso puxa em direção ao brilho de dashboard (gradientes, contagens animadas,
   zoológico de temas) e para longe da realidade silenciosa, de muita leitura e centrada em documentos, da
   investigação. As melhores ferramentas para trabalho profundo (um editor de texto, um caderno) são
   *simples*. O Console pode ser impressionante e raso.

3. **A personalização é um imposto disfarçado de presente.** Oito temas, amostras de cor de destaque,
   densidade, escala da fonte, ocultação por módulo. Para *Amara* (que não gosta de computadores) cada
   um deles é uma decisão que ela não queria e uma forma de configurar mal sua ferramenta.
   "Altamente personalizável" atendeu à redação da encomenda e à ideia de generosidade *do designer*
   — mas uma ferramenta genuinamente simples é **opinativa**: ela toma a decisão
   certa para que o usuário não precise. Escolha é carga cognitiva.

4. **A arquitetura da informação ainda é a do software, não a do usuário.** O Console
   renomeou e reagrupou as abas, mas o menu continua sendo uma lista de *módulos*
   (Pesquisa, Fontes, Análises, Mercados, Custódia…). Amara não pensa em módulos;
   ela pensa em um **caso**: "estou correndo atrás desta matéria — reunir, ler, conectar, provar,
   publicar." Tanto a 0.04 quanto a 0.05 obrigam o usuário a traduzir seu *trabalho* para os
   *recursos* do aplicativo. Uma navegação persistente com nove destinos é um mapa da base de código.

5. **A interface compete com o conteúdo.** Uma barra lateral fixa + barra superior gastam permanentemente
   ~250px e uma faixa horizontal com uma *navegação que o usuário usa por dois segundos por
   sessão*. O que ele de fato faz — ler artigos, percorrer resultados, comparar
   diffs — fica com as sobras. Investigar é ler; o Console atende mal à
   leitura.

6. **O "uau" é emprestado, não conquistado.** Uma paleta e temas são *o mínimo esperado*
   em aplicativos modernos — impressionantes justamente porque são familiares. Os recursos genuinamente
   diferenciadores, do tipo "nunca vi isso", aqui são a *substância*:
   detecção offline de guerras de edição na Wikipedia, custódia com evidência de adulteração, "cada número é um
   COUNT(\*) real". O Console decora; ele não dramatiza o que é de fato único.

É uma acusação séria. Merece uma alternativa real, não uma réplica.

---

### 2. Em defesa do Console (para que o argumento seja justo)

- Uma navegação persistente é **descobrível**: nada fica escondido, o que importa para um
  novato que ainda não sabe o que a ferramenta pode fazer. Modelos de hub-and-spoke escondem
  o poder atrás de um clique e de um palpite.
- A personalização é **opcional (opt-out)**: os padrões são sensatos; um usuário que ignora a gaveta
  não perde nada. E os temas realmente ajudam com a realidade de cansaço visual/madrugadas
  do trabalho, e com a acessibilidade (alto contraste, tamanho do texto) dos usuários *reais*.
- A "gramática SaaS" é também simplesmente a **convenção de usabilidade atual** — as pessoas sabem
  usá-la desde o primeiro dia. A novidade pela novidade tem seu próprio imposto.
- Ele continua **100% offline e sem dependências**. A gramática é emprestada; a
  substância (sem rede, sem telemetria) não é.

As duas posições são legítimas. A maneira de resolver isso não é discutir mais — é
**construir a antítese e usar as duas**.

---

### 3. A antítese: "Desk"

Se o Console é um **amplo console de operações** (tudo sempre a um clique,
flexível ao máximo, gramática de aplicativo moderno), o **Desk** é a tese oposta:

> **A mesa de um investigador: calma, opinativa, com o conteúdo em primeiro lugar e enquadrada por tarefas.
> Quase nenhuma interface ao redor. Uma tarefa de cada vez. A interface sai do caminho da leitura
> e do pensamento.**

Compromissos concretos em que o Desk deliberadamente *discorda* do Console:

| Dimensão | Console (tese) | Desk (antítese) |
|---|---|---|
| Navegação | Barra lateral esquerda persistente (sempre visível) | **Nenhuma navegação persistente.** A navegação é *sob demanda* — um início calmo, uma sobreposição "Ir para…" e ⌘K. A interface só aparece quando chamada. |
| Ponto de entrada | Um painel de status | **Um início enquadrado por tarefas:** "Em que você está trabalhando?" → Reunir · Encontrar e ler · Conectar · Verificar e compartilhar. Enquadrado pela tarefa do usuário, não pelos módulos do aplicativo. |
| Personalização | 8 temas, cor de destaque, densidade, fonte, interruptores de módulos | **Apenas dois temas** (Paper / Ink), sem botões de ajuste. Opinativo. A ferramenta decide para que você não precise. |
| Estética | Console de aplicativo moderno (sem serifa, pílulas, gradientes) | **Editorial / impressa:** títulos com serifa, calor de papel, margens generosas, largura de leitura. Parece uma redação, não um SaaS. |
| O que ganha o espaço | Navegação + status, depois o conteúdo | **O conteúdo.** Uma única coluna de leitura centralizada; as tabelas e o leitor de artigos ganham o espaço. |
| Sinal de confiança | Uma pílula de status | Uma linha persistente e discreta **"Local · Offline · Nada sai desta máquina"** — a soberania declarada, não insinuada. |
| Reação na demonstração | "Que elegante!" | "…ah, isto é *calmo*. E é tudo meu." Um tipo de uau mais lento e mais profundo. |

O que o Desk **mantém** (porque é a razão de ser do aplicativo, não interface): cada recurso
e cada endpoint funcional. Desk e Console compartilham exatamente o mesmo motor e os
mesmos painéis de conteúdo — eles diferem *apenas* na casca, no modelo de navegação, no enquadramento da arquitetura da informação
e na estética. Isso é deliberado: mantém o experimento controlado, de modo que o que você está
comparando é **a filosofia**, não qual dos dois eu por acaso conectei com mais cuidado.

---

### 4. Como julgá-los (rubrica)

Avalie cada um em relação aos valores — não ao seu instinto de "qual é mais bonito":

1. **Confiança** — qual deles *parece* pertencer a você e não vai traí-lo?
2. **Calma vs capacidade** — qual deles deixa você pensar? qual torna o poder fácil de encontrar?
3. **Percurso do novato** — coloque *Amara* diante dele sem preparo: qual a leva a um resultado mais rápido, com
   menos medo?
4. **Percurso avançado** — *Daniel* no teclado: qual sai do caminho dele?
5. **Leitura** — abra um artigo longo / um diff da Wikipedia em cada um. Qual é o melhor
   lugar para *ler*?
6. **O teste dos 5 segundos** — mostre cada um a um colega. Qual provoca "posso ter também?" —
   e é essa a reação para a qual você realmente quer otimizar?
7. **Adequação ao ethos** — em qual você confiaria para rodar com a rede desconectada em
   um cofre Qubes?

---

### 5. Prós / contras previstos (minha aposta honesta, a ser testada)

**Console** — *Prós:* descobrível, convencional, flexível, ajustes acessíveis, brilho na
demonstração. *Contras:* interface pesada, carga de decisões, sensação de SaaS genérico que pode corroer a confiança,
arquitetura da informação ainda centrada em módulos.

**Desk** — *Prós:* calmo, leitura/conteúdo em primeiro lugar, opinativo (sem imposto de configuração),
entrada enquadrada por tarefas, uma estética que *reforça* a soberania e a confiança. *Contras:*
o poder fica a uma chamada de distância (um clique/uma tecla), menos ajustes de acessibilidade, menos
"impressionante" de imediato, a novidade tem um pequeno custo de aprendizado.

---

### 6. Minha recomendação (síntese — provisória, à espera do seu teste)

Espero que a resposta certa **não seja nem o Console puro nem o Desk puro**, mas uma síntese
que se apoie na *adequação aos valores* do Desk e na *descobribilidade* do Console:

- **Adotar o início enquadrado por tarefas e a calma editorial do Desk** como clima padrão. O enquadramento
  por tarefas ("reunir / ler / conectar / verificar") é a maior correção isolada para a
  crítica de que "a arquitetura da informação é a base de código".
- **Adotar a contenção do Desk na personalização:** entregar dois temas excelentes
  (Paper/Ink) + um controle de tamanho do texto para acessibilidade, e **cortar** a proliferação de cor de destaque /
  densidade / ocultação de módulos. Aqui, opinativo vence configurável.
- **Manter do Console uma navegação *discreta e recolhível*** para a descobribilidade — mas
  recolhida por padrão, para que o conteúdo venha à frente e a navegação esteja lá quando desejada.
- **Manter o ⌘K** (ele serve tanto ao novato quanto ao usuário avançado e é genuinamente útil).
- **Dramatizar a substância, não a interface:** fazer da custódia, da Wikipedia offline e das
  "contagens reais" os heróis visuais — esse é o uau conquistado.
- **Pôr a linha de confiança à frente em toda parte** ("nada sai desta máquina"). Ela é a
  marca.

Mas isso é uma hipótese. Use os dois, avalie-os segundo o §4 e me diga onde a realidade
diverge da minha aposta — então incorporarei o veredito em uma única 0.06.

> **VEREDITO FINAL (mantenedor, 2026-06-10, após uso real):** a dialética está
> resolvida — **o Desk foi totalmente aposentado. Uma única interface: o Console** (`/`).
> Dois ícones confundiam mais do que ajudavam; o conjunto reduzido de ferramentas do Desk fazia
> recursos já entregues (Mapa temporal, Agenda) parecerem perdidos; e o Console já
> se adapta suavemente ao tamanho da janela (a barra lateral se retrai para uma faixa de ícones). O
> arquivo `desk.html` foi removido (ele vive no histórico do git); `/desk` agora
> redireciona para `/`. As melhores ideias do Desk — o início enquadrado por tarefas, o ⌘K, a calma
> editorial — devem ser incorporadas ao Console ao longo do tempo, conforme o §6 acima.

---

### 7. Executando os dois ao mesmo tempo

As duas interfaces são servidas pelo mesmo backend local, sobre os mesmos dados:

- **Console** → `http://127.0.0.1:8000/`  (o padrão)
- **Desk** → `http://127.0.0.1:8000/desk`

O instalador cria **dois ícones na área de trabalho** — *Open Omniscience* (Console) e
*Open Omniscience — Desk* — para que você possa abrir qualquer um deles, ou abrir as duas janelas juntas
e compará-las aba por aba sobre dados idênticos. Escolha um vencedor (ou peça a
síntese) e voltamos a uma só na 0.06.


---

## Estratégia de análise de conteúdo — links, uniformidade e a fonte original

> Estratégias concretas e escalonadas para a visão em [`ROADMAP.md`](archive/roadmaps/DESIGN_MEMORY_pre-0.2.md):
> usar os **links** dos artigos para reunir o que fala da mesma coisa, revelar a
> **uniformidade** da mídia e rastrear a informação até sua **fonte original** — mantendo
> o **usuário no comando**, a análise **transparente e local**, e nunca
> deixando a ferramenta se tornar árbitra da verdade (Carta de Munique). Código aberto e
> offline do início ao fim.

---

### 0. Onde estamos (status honesto)

A detecção de links em artigos está **com o esqueleto pronto, mas não conectada**:

- ✅ **`src/services/link_analyzer/extractor.py`** (`LinkExtractor`) — extrai links
  do HTML, normaliza URLs, registra o texto âncora + a posição, classifica o *tipo* de link
  (interno/externo/imagem/…) e produz estatísticas de links. ~500 linhas, em formato de unidade.
- ✅ **Esquema do banco** — `ArticleLink` (url, normalized_url, link_text, position,
  link_type, **classification** = source/reference/ad/social/navigation,
  `external_source_id`, `source_article_id`, is_working, http_status…),
  `ExternalSource` e `LinkClassificationRule`. Os relacionamentos estão no lugar
  (`Article.links`, `ExternalSource.links`).
- ✅ **Invocado na ingestão** *(feito — P0)* — `src/ingest/pipeline.py:_maybe_index_links`
  preenche `article_links` com os links **externos** de saída (melhor esforço, fail-open;
  interno/imagem/anúncio/social/rastreador excluídos conforme `ROADMAP.md`; sem duplicatas + com limite).
- ✅ **API** *(feito — P1)* — `src/api/link_analysis.py` (`/api/links`): `stats`,
  `top-cited` (por url|domínio, em janela), `articles-by-link` (por url|domínio). Somente
  contagens; nada é pontuado ou julgado.
- ❌ **Ainda sem interface** — nenhuma visão em Análises sobre o grafo de links (P2, abaixo).

Assim, P0/P1 estão conectados; o trabalho restante é a interface e as análises mais profundas (P3/P4).

---

### 1. A ideia central: os links são um grafo de citações

Trate cada artigo como um nó e cada link de saída como uma aresta dirigida para uma URL (e
para o seu domínio). Esse grafo responde exatamente ao que você perguntou:

- **"Reunir todos os artigos que falam do mesmo link."** = agrupar os artigos pela
  URL externa que citam → o **grau de entrada** da URL é "quantos dos meus artigos apontam
  para cá." Grau de entrada alto = um **hub**: muitas vezes um documento primário, uma matéria de agência ou uma
  referência muito discutida.
- **"Descobrir tendências por meio dos links internos."** = acompanhar o grau de entrada ao longo do tempo; uma URL ou
  domínio cujas citações disparam é uma *tendência* ancorada no que os repórteres de fato citam,
  e não apenas na frequência de palavras-chave.
- **"Rastrear a fonte original / primordial."** = dentro de um agrupamento de artigos sobre uma
  matéria, o original é o nó para o qual os outros **apontam**, e/ou o mais antigo, e/ou aquele
  que cita um **documento primário** (tribunal/governo/conjunto de dados). Links + carimbos de data/hora + atribuição
  a agências de notícias permitem triangulá-lo.

Isto é *análise de cocitação* — barata, transparente e explicável. Nenhuma caixa-preta.

---

### 2. Estratégias escalonadas (cada uma entregável por si só)

#### P0 — Conectar o extrator à ingestão (fazer o grafo existir)
- Chamar o `LinkExtractor` durante a ingestão sobre o HTML obtido; persistir os links **externos**
  de saída em `article_links` (ignorar a navegação interna, os anúncios e — conforme o
  `ROADMAP.md` — os links de imagens/binários). Armazenar normalized_url + texto âncora + tipo.
- Mapear o domínio de cada link externo para uma `Source`/`ExternalSource` conhecida sempre que
  possível (para que "quem cita quem" possa ser agregado por veículos e **proprietários**).
- Barato, determinístico, offline. Nada é buscado além do que a ingestão já buscou.

#### P1 — Agregação + API (responder à pergunta do usuário)
Endpoints somente leitura sobre o grafo:
- **`top-cited`** — as URLs/domínios mais citados em uma janela (o sinal de tendência).
- **`articles-by-link`** — dada uma URL/domínio, todos os artigos do corpus que a citam
  ("reunir todos os artigos que falam do mesmo link").
- **`link-graph`** — nós/arestas de um tema ou de uma janela, para visualização.
- **`co-citation`** — artigos que citam as *mesmas* fontes externas (agrupamentos candidatos
  de "mesma matéria"), com contagens de sobreposição.

#### P2 — Interface: uma visão "Links e fontes" em Análises
- Uma lista ordenada dos **links/domínios mais citados** (clique → todos os artigos que os citam).
- Um pequeno **grafo de citações** com zoom (reutilizar a abordagem SVG já usada no
  mapa de Análises — nenhuma dependência nova).
- Sempre mostra os **tamanhos de amostra** ("citado por 14 dos seus artigos") — medido, não
  adivinhado. O usuário clica, explora, decide.

#### P3 — Linhagem da fonte original
Para um agrupamento de artigos sobre uma matéria, apresentar uma **linhagem**, ordenada por sinais
(cada um mostrado, nenhum decisivo):
- grau de entrada (quem é apontado pelos outros),
- carimbo de data/hora de publicação mais antigo,
- atribuição a agência de notícias (AFP/Reuters/AP — já marcamos `wire-agency`),
- presença de um link para um **documento primário** (governo/tribunal/conjunto de dados/preprint).
Saída: "documento primário → primeira reportagem → ecos", como uma cadeia que o usuário lê.

#### P4 — Uniformidade e eco (ligado à concentração da mídia)
- **Detecção de quase-duplicatas** (MinHash/SimHash, baratos) para sinalizar texto sindicado/copiado
  entre veículos — baseia-se em `src/ingestor/duplicate_detector.py`.
- **Pontuação de eco**: um agrupamento em que muitos veículos citam **uma única** fonte (ou citam uns aos outros em um
  circuito fechado) e acrescentam poucos links originais = eco alto. Citações diversas de fontes primárias =
  reportagem independente.
- **Sobreposição de concentração**: ponderar o eco pela **propriedade** — se o agrupamento que ecoa corresponde
  a um único proprietário/bloco (o caso "~7 bilionários são donos de ~90%"), mostrar isso. Requer o
  grafo de propriedade (Wikidata P127/P749 + manual), conforme o `ROADMAP.md`.

---

### 3. Manter o usuário no comando (inegociável)

- **Mostrar, nunca suprimir.** As pontuações de eco/linhagem são *mostradas e ordenáveis*; a ferramenta
  nunca oculta nem rebaixa automaticamente uma fonte. Qualquer redução de peso é um controle explícito e reversível
  do usuário, **desligado por padrão**.
- **Nenhum rótulo de verdade.** "O mais antigo que vimos" / "o mais citado" ≠ "verdadeiro." Mostramos a estrutura
  (quem disse primeiro, quem cita quem, quem é dono de quem) e paramos aí.
- **Tudo explicável e local.** Cada número remete a linhas que o usuário pode inspecionar;
  nenhuma chamada externa, nenhuma caixa-preta de ML (hashing + contagem + grau no grafo).
- **Código aberto e auditável.** Funções puras, testáveis por unidade, regras de classificação em
  dados (`LinkClassificationRule`) que o usuário pode editar.

---

### 4. Riscos e limites honestos

- A extração de links é tão boa quanto o HTML obtido (paywalls/JS a limitam).
- As convenções de âncora/citação variam; um "segundo X" sem link escapa (uma
  passagem posterior de PLN poderia ajudar, mas começamos simples).
- Os dados de propriedade são irregulares e datados — devem ser atribuíveis, não adivinhados.
- A detecção de quase-duplicatas na escala do corpus exige cuidado para continuar barata em uma única máquina (hashing, comparação
  em janelas), e não comparações de texto completo em O(n²).

### 5. Primeiro commit sugerido

Conectar o **P0** (preencher `article_links` na ingestão) por trás de uma configuração, adicionar os endpoints **P1
`articles-by-link`** e **`top-cited`**, e uma lista mínima em Análises. Só isso
já entrega "reunir todos os artigos que citam o mesmo link" e uma tendência baseada em
citações — a menor fatia de valor real, totalmente em sintonia com o ethos.
