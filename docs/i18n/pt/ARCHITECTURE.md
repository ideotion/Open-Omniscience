<!-- pt: Translation of docs/ARCHITECTURE.md written by AI (2026-11-19, R677; native review dropped by R721, 2026-11-14); it may contain mistakes, and the English original is authoritative. Coverage: the whole document, 28 of 28 headings. Corrections are welcome as a pull request. -->

# Arquitetura e referência técnica

O complemento técnico do Manual do Usuário: o banco de dados/configuração, o mapa da API HTTP e a internacionalização.

## Conteúdo
- [Configuração do banco de dados do Open Omniscience](#configuração-do-banco-de-dados-do-open-omniscience)
- [Referência da API](#referência-da-api)
- [Internacionalização (i18n) — tornar o aplicativo multilíngue](#internacionalização-i18n--tornar-o-aplicativo-multilíngue)


---

## Configuração do banco de dados do Open Omniscience

> **Situação (verificada na auditoria v0.0.7, `docs/archive/audits/00_BASELINE.md`):** a camada de banco de dados
> **funciona e é testada** — o servidor inicia, cria/usa o armazenamento SQLite, aplica as migrações do Alembic,
> e o conjunto completo de testes (800+) passa contra ele. O antigo aviso "conceito inicial —
> não funcional" que ficava aqui descrevia um estado anterior à reconstrução e estava
> desatualizado havia muito tempo.

### 🗃️ SQLite — o armazenamento suportado

O SQLite é o **backend padrão e o único suportado e testado**. Ele se ajusta ao projeto
local-first e de operador único do produto.

- **Configuração zero:** o banco de dados é criado automaticamente na primeira execução, em
  `<data dir>/open_omniscience.db`. O diretório de dados é `OO_DATA_DIR`, se definido; caso contrário, o
  `data/` do repositório numa cópia do código-fonte; caso contrário, `$XDG_DATA_HOME/open-omniscience` (consulte `src/paths.py`).
- **Ajustado automaticamente:** o motor aplica o modo de journal `WAL`, `foreign_keys=ON`,
  `busy_timeout=30000` e `synchronous=NORMAL` em cada conexão
  (`src/database/session.py`) — você não precisa defini-los.
- **A pesquisa de texto completo** é feita pelo **FTS5** do SQLite (`article_fts`, de conteúdo externo, mantida em sincronia por
  gatilhos — `src/database/fts.py`).
- **Altere o local** com a variável de ambiente `DATABASE_URL` (**não** edite
  arquivos de código-fonte): `DATABASE_URL=sqlite:////absolute/path/to/your.db`
- **Manutenção:** um `sqlite3 <db> "VACUUM;"` ocasional recupera espaço (a auditoria v0.0.7
  também removeu um índice redundante que ocupava cerca de 63% do arquivo em corpora grandes; execute `make
  migrate` uma vez após a atualização para removê-lo dos bancos de dados existentes).

### 🐘 PostgreSQL — estrutura experimental, NÃO suportada

Honestidade acima da aspiração (constatação de auditoria ARCH-06): a camada do motor *reconhece* uma
`DATABASE_URL` do PostgreSQL (pool de conexões via `DB_POOL_SIZE`/`DB_MAX_OVERFLOW`), **mas**

- **a pesquisa de texto completo não existe no PostgreSQL** — a configuração do FTS5 não faz deliberadamente nada em
  motores que não sejam SQLite, de modo que a aba Pesquisa ficaria inoperante;
- o conjunto de testes nunca é executado contra o PostgreSQL, e nenhuma CI o cobre;
- nenhuma implantação publicada o utilizou.

Trate o PostgreSQL como **uma estrutura não testada para um futuro possível**, e não como uma escolha que você possa
fazer hoje. Se a escala com múltiplos escritores algum dia se tornar um requisito real, o item do roadmap é um
caminho de pesquisa `tsvector` mais uma matriz de CI com PostgreSQL — até que isso chegue, esta página não vai
fingir.

### 🔄 Migrações

O Alembic está configurado na **raiz do repositório** (`alembic.ini`, `migrations/`). O Alembic é
instalado com o aplicativo (é uma dependência central — não há instalação separada).

- **Bancos de dados novos** são criados completos (`create_all` + FTS) e marcados com a
  versão mais recente das migrações automaticamente na inicialização.
- **Atualizar um banco de dados existente:**
  ```bash
  make migrate          # = alembic upgrade head, from the repo root
  ```
- **Criar uma migração** (contribuidores): edite `src/database/models.py` e depois
  ```bash
  alembic revision --autogenerate -m "your message"
  alembic upgrade head
  ```
  e revise o arquivo gerado — a geração automática não detecta as tabelas virtuais FTS (elas ficam em
  `src/database/fts.py`, aplicadas na inicialização).
- **Reverter:** `alembic downgrade -1`.

---

### 📊 Esquema do banco de dados

#### Tabelas:

##### `sources`
| Coluna | Tipo | Descrição |
|--------|------|-------------|
| `id` | INTEGER | Chave primária |
| `name` | STRING(100) | Nome da fonte (por exemplo, "BBC News") |
| `domain` | STRING(255) | Domínio da fonte (por exemplo, "bbc.com") |
| `rss_url` | STRING(500) | URL do feed RSS (se disponível) |
| `rate_limit_ms` | INTEGER | Intervalo entre requisições, em milissegundos |
| `enabled` | BOOLEAN | Se a fonte está ativa para raspagem |
| `priority` | INTEGER | Nível de prioridade (1 = alta, 3 = baixa) |
| `tags` | STRING(500) | Lista de etiquetas separadas por vírgula |

##### `articles`
| Coluna | Tipo | Descrição |
|--------|------|-------------|
| `id` | INTEGER | Chave primária |
| `url` | STRING(1000) | URL original do artigo |
| `canonical_url` | STRING(1000) | URL canonicalizada (para detecção de duplicatas) |
| `source_id` | INTEGER | Chave estrangeira para `sources` |
| `title` | STRING(500) | Título do artigo |
| `content` | TEXT | Conteúdo em texto completo do artigo |
| `published_at` | DATETIME | Data/hora de publicação (formato ISO) |
| `language` | STRING(10) | Código do idioma (por exemplo, "en", "fr") |
| `hash` | STRING(64) | Hash SHA-256 do conteúdo (para detecção de duplicatas) |
| `created_at` | DATETIME | Carimbo de data/hora em que o artigo foi ingerido |

> As colunas acima são os campos centrais; o esquema em vigor (`src/database/models.py`)
> e as migrações do Alembic em `migrations/versions/` são a fonte de verdade.
> `articles` também traz campos de proveniência/análise (author, word_count, region,
> country, sentiment) e uma coluna de conteúdo comprimido.

##### Outras tabelas (consulte os modelos / as migrações para ver todas as colunas)

| Tabela | Finalidade |
|-------|---------|
| `source_groups`, `source_metadata`, `source_group_association` | Agrupamento de fontes + metadados geográficos/de robots |
| `commodity_prices` | Pontos de preço observados (símbolo, data, preço, moeda, **unidade**, mercado, fonte) — gráficos + correlação preço↔notícias |
| `market_extraction_rules` | Regra por fonte (seletor CSS / atributo / regex) que localiza o preço de um instrumento em uma página; categoria financeiro/ação/commodity |
| `keywords` | Termo distinto de palavra-chave/entidade (normalizado, idioma, `is_entity`/`entity_type`, proveniência **`extractor`**) |
| `keyword_mentions` | Uma por (artigo, palavra-chave): contagem + deslocamento do primeiro caractere + `observed_on`/`country`/`city` desnormalizados — alimenta as tendências, associações, contexto e mapa de Análises |
| `wiki_pages` | Uma página da Wikipedia acompanhada em uma edição linguística; guarda **uma** linha de base comprimida do texto completo |
| `wiki_revisions` | Uma edição acompanhada: **diff + variação de bytes com sinal** + sinalizadores/etiquetas (não uma nova cópia), pontuações ORES opcionais, sinalização honesta de edição grande + motivos |
| `article_analyses` | Resultados derivados do LLM (resumo/tradução) com a proveniência do modelo + do prompt |
| `keyword_categories`, `external_sources`, `article_links`, … | Categorização de palavras-chave + acompanhamento de links/relações entre fontes |

#### Índices:
- `idx_article_hash`: Índice único em `hash` (para detecção de duplicatas).
- `idx_article_canonical_url`: Índice em `canonical_url` (para buscas por URL).
- `idx_article_source_id`: Índice em `source_id` (para consultas por fonte).
- `idx_article_content`: Índice em `content` (para pesquisa de texto completo).

---

### 🔍 Pesquisa de texto completo

A pesquisa de texto completo **já está construída e ligada** — não há nada a ativar. O armazenamento
traz uma tabela FTS5 de conteúdo externo (`article_fts`) mantida em sincronia por gatilhos; consulte
`src/database/fts.py` para o esquema e `search_ids` em `src/api/main.py` para o caminho da
consulta (resolução apenas por id na ordem final, com as linhas completas carregadas só para a página).

Esta seção oferecia uma receita "considere criar uma tabela virtual" para o SQLite e uma
receita `to_tsvector` para o PostgreSQL. Ambas estavam erradas: a do SQLite descrevia a construção
manual de uma tabela que o aplicativo já traz e mantém (com um nome *diferente*, de modo que segui-la
teria produzido um segundo índice, sem manutenção), e o PostgreSQL não tem caminho de pesquisa algum aqui,
o que a seção sobre o armazenamento acima aponta como o primeiro motivo pelo qual ele não é um backend suportado.

---

### 📉 Monitoramento e manutenção

- **Verificar o tamanho do banco de dados**:
  ```bash
  ls -lh data/open_omniscience.db
  ```
- **Verificar o tamanho das tabelas**:
  ```bash
  sqlite3 data/open_omniscience.db "SELECT name, COUNT(*) FROM sqlite_master WHERE type='table';"
  ```
  Num armazenamento **criptografado**, a CLI `sqlite3` não consegue abrir o arquivo de forma alguma (esse é
  justamente o objetivo) — use as superfícies de Configurações → Diagnóstico no aplicativo, que leem o armazenamento
  pela mesma fábrica de conexões protegida que o próprio aplicativo usa.

---

### 🚨 Solução de problemas

#### Problemas comuns:

##### SQLite:
- **"Database is locked"**:
  - O SQLite só permite um escritor de cada vez. O modo WAL está ativado por padrão
    (`src/database/session.py`) e uma barreira de escritor único em todo o processo
    (`src/database/writer.py`) serializa as gravações dentro do aplicativo, de modo que ingestão e
    importação simultâneas não colidem mais. Um bloqueio persistente significa que outro *processo* está gravando.

- **"Too many open files"**:
  - O SQLite abre uma nova conexão para cada thread. Limite o número de threads ou use um pool de conexões.

- **"Relation does not exist" / "no such table"**:
  - Execute as migrações: `alembic upgrade head`.

---

### 📌 Boas práticas

1. **Faça cópias de segurança pelo aplicativo, não com `cp`**:
   - Use Configurações → Cópia de segurança (ou `GET /api/database/backup` para um instantâneo consistente).
     Copiar `open_omniscience.db` à mão **não** é uma cópia de segurança: o armazenamento funciona em modo
     WAL, então o arquivo em uso não contém o que ainda está em `-wal`, e no armazenamento padrão
     **criptografado** um arquivo copiado é inútil sem a frase-senha e não traz nenhum
     compromisso de integridade. O caminho do próprio aplicativo faz o checkpoint, transmite e assina.

2. **Teste as migrações**:
   - Sempre teste as migrações em uma cópia de segurança do seu banco de dados antes de aplicá-las em produção.

3. **Monitore o desempenho**:
   - Configurações → Diagnóstico traz o log de consultas lentas, o log de latência das requisições e o
     relatório da barreira de gravação; a CLI `sqlite3` funciona num armazenamento em texto claro.

4. **Otimize as consultas**:
   - `EXPLAIN QUERY PLAN` é a ferramenta. Observe que o SQLite escreve `SCAN` **tanto** para uma varredura
     simples da tabela quanto para uma varredura só de índice — um `SCAN <table> USING [COVERING] INDEX …` é
     saudável; o sinal de alerta é um `SCAN <table>` simples, sem `USING`
     (`src/monitoring/slowquery.py` classifica exatamente por isso).

5. **Limite a retenção de dados**:
   - Arquive ou exclua regularmente os artigos antigos para manter o banco de dados administrável.
   - Exemplo: excluir os artigos com mais de 1 ano:
     ```python
     from datetime import datetime, timedelta
     one_year_ago = datetime.now(timezone.utc) - timedelta(days=365)
     session.query(Article).filter(Article.published_at < one_year_ago).delete()
     session.commit()
     ```

---
*Copyright © 2026 Ideotion. Licenciado sob a GNU General Public License v3.0
ou posterior (GPL-3.0-or-later) — consulte [LICENSE](../LICENSE). Este é um software livre;
você pode redistribuí-lo e modificá-lo nesses termos.*


---

## Referência da API

A referência da API em vigor, sempre exata, é gerada pelo próprio aplicativo:

- **Swagger UI / ReDoc:** desativados por padrão (carregam recursos de hosts de terceiros); inicie o aplicativo com `OO_API_DOCS=1` para ter http://127.0.0.1:8000/docs e `/redoc`
- **OpenAPI JSON:** http://127.0.0.1:8000/openapi.json

O aplicativo escuta apenas no loopback e (para um único usuário local) não exige autenticação.

### Grupos de endpoints

Este é um **mapa dos principais grupos, não uma lista exaustiva** — o
`/openapi.json` em vigor (acima) é sempre a referência. Os roteadores são ligados em
`src/api/main.py` via `include_router(...)`; os grupos marcados **[analysis]** exigem
o extra `[analysis]` (o aplicativo ainda inicia sem ele, com esses endpoints desativados).

| Prefixo | O que faz |
|--------|--------------|
| `GET /api/health` | Disponibilidade + versão |
| `GET /api/articles`, `/api/articles/export` | Pesquisa booleana de texto completo (FTS5) + exportação CSV/JSON |
| `POST /api/ingest`, `/api/sources/{id}/ingest`, `/api/sources/{id}/ingest-email` | Ingestão ética: URL única, feed RSS, caixa de correio IMAP |
| `… /api/sources`, `/api/sources/...` | Gestão de fontes + grupos + metadados |
| `POST /api/sources/seed-defaults` | Semeia os catálogos de fontes curados (notícias + mercados + catálogo mundial gerado) |
| `GET /api/database/stats`, `/coverage`, `/countries` | Contagens de linhas do corpus + tamanho em disco; cobertura por país; contagens de fontes por país + palavras-chave temáticas |
| `GET /api/database/backup` | Download de um instantâneo consistente do SQLite (apenas armazenamento SQLite em texto claro; recusado para uma requisição vinda de outro site ou de um Host que a proteção contra DNS rebinding não atende e, num nome que não seja loopback, para uma requisição que não indique a página de onde vem, a menos que envie `X-OO-Download: 1`; um de cada vez por processo, gravado numa pasta privada `.oo-backup-*` ao lado do banco de dados e removido quando o download termina ou o processo para (uma interrupção forçada a deixa para a varredura da próxima inicialização, que remove de imediato a pasta de um proprietário extinto), 507 quando o volume de dados não consegue contê-lo) |
| `POST /api/database/v2/restore/preview`, `/v2/restore/commit`, `/api/backup/v2/*` | Restauração **apenas aditiva** via o artefato assinado `oo-backup-2`: pré-visualize o plano de fusão e depois confirme. A restauração **nunca sobrescreve o seu corpus** — ela funde sem duplicar, mantendo os valores locais em caso de conflito (o caminho destrutivo de substituição foi removido em 2026-06-13) |
| `GET/PUT /api/settings` | Preferências da interface (tema, limite padrão de resultados) |
| `… /api/scheduler/...` | Coleta em segundo plano: estado, iniciar, parar, executar agora, configuração. Desde o ciclo `0.4`, a coleta funciona como **faixas lado a lado** (`rss` / `crawl` / `markets` / `wiki` / `law`), e não como um único modo do agendador — armazenamento por faixa em `… /api/storage/...`, e a aba **Fontes vivas** lê `… /api/living/...` (o que mudou na Wikipedia, na legislação e nos mapas) |
| `… /api/markets/rules`, `/rules/{id}/run`, `/overview` | Regras de extração de preço por fonte + uma execução de "teste" + visão geral de Mercados |
| `GET /api/markets/feeds`, `POST /feeds/{key}/import`, `/feeds/import-url` | Catálogo oficial de feeds de preços em CSV + importação (FRED/World Bank/EIA) + importação de URL personalizada |
| `GET /api/catalog/export.csv`, `/template.csv`, `/columns`, `POST /api/catalog/import` | Exportação / modelo / colunas da lista de fontes em CSV + importação com atualização por domínio |
| `… /api/insights/...` | Análise de palavras-chave e entidades: estado, reindexação, principais, em alta, tendência, associações (PMI), contexto, mapa |
| `GET /api/timemap`, `/timemap/range` | Sinais espaço-temporais num mapa + eixo de tempo (âncoras + corpus geocodificado + riscos/datas mencionadas opcionais); `?kinds`, janela de ano fracionário `?start`/`?end`, `?hazards`, `?articles`, `?mentions`, `?days` |
| `… /api/article-dates/...` | Datas extraídas do texto dos artigos como etiquetas por artigo confirmáveis por humanos: listar/extrair por artigo, confirmar/rejeitar, indexação em lote, filtro do corpus por data |
| `GET/POST /api/llm/...` | LLM local (Ollama): estado, modelos, geração, resumo de um artigo |
| `… /api/commodities/...` | Preços de commodities (importação / CSV / lista) + correlação honesta preço↔notícias |
| `POST /api/analysis/...` | Estatística com rigor científico: teste t, correlação, ANOVA, Mann-Whitney, IC |
| `GET /api/monitoring/...` | Saúde real da disponibilidade das fontes + anomalias de volume do corpus |
| `POST /api/verify/image-metadata` | Extração honesta de EXIF/metadados de imagens |
| `POST /api/reports/evidence`, `/evidence/verify` | Pacotes de provas assinados e com evidência de adulteração |
| `POST /api/custody/log`, `GET /api/custody/{item}`, `.../verify`, `POST /api/custody/export`, `POST /api/custody/verify` | Registro de cadeia de custódia assinado, só de acréscimo e encadeado por hash + verificação offline |
| `GET/PUT /api/custody/settings` | Preferências de custódia em tempo de execução (assinatura pós-quântica, modo de ancoragem, registro automático) — informa o estado *efetivo*, consciente da disponibilidade |
| `POST /api/custody/anchor`, `GET /api/custody/providers` | Ancorar uma raiz de Merkle (local / OpenTimestamps) + disponibilidade dos provedores |
| `POST /api/custody/reconcile` | Grava as entradas INGEST que uma falha deixou pendentes, cada uma marcada como tardia nos seus metadados assinados; `scan` conta lacunas mais antigas, `record_gaps` as enfileira (2026-09-24, CUST-1) |
| `… /api/keywords/...`, `/api/analysis/articles/similarity` | **[analysis]** Extração de palavras-chave + similaridade entre artigos |
| `GET /api/search/omni` | Omnibar federada baseada em índices (artigos FTS5 + palavras-chave + fontes + wiki/legislação) |
| `… /api/jobs/...` | Agregação de tarefas do gerenciador de tarefas (passada de coleta, busca em andamento, fila de dumps da wiki + reordenação) |
| `… /api/system/...` | Sinais vitais do sistema + estado/consentimento de rede (interruptor geral do modo avião, IPs das interfaces locais) |
| `… /api/safety/...` | Controles de segurança: interruptor geral, barreira de descoberta, restauração a partir de artefato criptografado |
| `… /api/briefing/...` | Produtores do briefing de Início (cartões por níveis de evidência; método+ressalva+n) |
| `… /api/insights/...`, `/api/insights/who`, `/where` | Análise de palavras-chave/entidades + agregação Quem/Onde em todo o corpus |
| `… /api/links/...` (shared, preview) | Análise de links de saída compartilhados / grafo de citações + diálogo local de pré-visualização de links |
| `… /api/events/...`, `/api/events/astronomy`, `/climate` | Eventos da Agenda, incluindo astronomia calculada localmente (Meeus) + tabela do El Niño |
| `POST /api/weather/context` | Fatia limitada e consentida da reanálise Open-Meteo para corroboração |
| `… /api/law/...` | Feed de mudanças de legislação/fontes primárias acompanhadas |
| `… /api/integrity/...` | Sinais de eco / coordenação / linhagem |
| `… /api/annotations/...` | Anotações de artigos locais, opcionalmente assinadas |
| `… /api/wiki/...` | Edições da Wikipedia, páginas acompanhadas, download/leitura de dumps, sincronização com o corpus |
| `… /api/hazards/...`, `/api/timemap` | Sobreposições de riscos + mapa espaço-temporal |
| `GET /unlock`, `POST /api/unlock`, `/create-db`, `/doctor`, `/encrypt-db` | Criptografia em repouso: tela de desbloqueio na inicialização bloqueada, criação de armazenamento criptografado/em texto claro, atestação do cabeçalho, ferramenta de criptografia de sentido único |

Os roteadores marcados **[analysis]** (commodities, estatística, palavras-chave, enquadramento)
exigem o extra `[analysis]`; sem ele, o aplicativo ainda inicia com o núcleo
e esses endpoints ficam desativados.

Notas de comportamento:
- A ingestão busca apenas pelo buscador ético (robots.txt fail-closed, com limitação
  de taxa); os endpoints de LLM retornam **503** se o Ollama não estiver disponível (nunca uma resposta falsa).
- Verificação de provas: passe a chave pública do signatário para provar a proveniência, e não apenas a
  integridade (consulte [QUICKSTART](QUICKSTART.md) e `scripts/verify_evidence.py`).
- As configurações de custódia são *preferências*, não garantias: `GET/PUT /api/custody/settings`
  sempre informam o estado **efetivo** (preferência **e** disponibilidade da biblioteca), de modo que
  pós-quântico / OpenTimestamps nunca aparecem ativados quando o extra correspondente está
  ausente. A ancoragem usa por padrão o provedor offline `local`; OpenTimestamps e a
  ancoragem em cadeia pública trazem um aviso de privacidade (consulte
  [CHAIN_OF_CUSTODY](USER_MANUAL.md)).


---

## Internacionalização (i18n) — tornar o aplicativo multilíngue

> Objetivo: a **interface inteira** (e, com o tempo, a **documentação**) disponível em cerca de
> uma dúzia de idiomas, para ampliar o acesso aberto rumo a "quase todos os seres humanos". Feito à
> maneira do projeto: **offline, sem CDN, sem API de tradução em tempo de execução, sem telemetria** e
> **honesto** quanto à qualidade da tradução (não distribuímos palpites de máquina como se fossem
> autoritativos).

---

### A dúzia de idiomas (conjunto da Fase 1)

Escolhidos pelo alcance (falantes nativos + de segunda língua) e para incluir deliberadamente o
Sul Global (conforme o objetivo antiviés do `ROADMAP.md`):

| Código | Idioma | Nome nativo | Escrita / direção | Situação |
|---|---|---|---|---|
| `en` | Inglês | English | LTR | **fonte** (completo) |
| `fr` | Francês | Français | LTR | **completo** (validado) |
| `es` | Espanhol | Español | LTR | **completo** (validado) |
| `de` | Alemão | Deutsch | LTR | **completo** (validado) |
| `zh` | Chinês (mandarim) | 中文 | LTR | completo (traduzido, ciclo `0.4`; ainda não validado) |
| `hi` | Híndi | हिन्दी | LTR | completo (traduzido, ciclo `0.4`; ainda não validado) |
| `ar` | Árabe | العربية | **RTL** | completo (traduzido, ciclo `0.4`; ainda não validado) |
| `bn` | Bengali | বাংলা | LTR | completo (traduzido, ciclo `0.4`; ainda não validado) |
| `ru` | Russo | Русский | LTR | completo (traduzido, ciclo `0.4`; ainda não validado) |
| `pt` | Português | Português | LTR | completo (traduzido, ciclo `0.4`; ainda não validado) |
| `id` | Indonésio | Bahasa Indonesia | LTR | completo (traduzido, ciclo `0.4`; ainda não validado) |
| `ja` | Japonês | 日本語 | LTR | completo (traduzido, ciclo `0.4`; ainda não validado) |

Próximas adições fáceis em termos de alcance: **suaíli (`sw`)**, **urdu (`ur`, RTL)**, italiano
(`it`), turco (`tr`), vietnamita (`vi`).

**Postura de honestidade.** Um *esboço* (stub) torna um idioma **selecionável desde já** e recorre ao
inglês para qualquer string não traduzida — uma localidade parcial nunca quebra a interface (este é
o mecanismo a partir do qual começa qualquer localidade futura — `it`, `tr`, `vi`, …). Marcamos cada localidade como `complete | draft | stub`. O mantenedor
só distribui o que pode validar; todo o resto é preenchido por **contribuição
da comunidade** (é exatamente assim que o código aberto amplia o acesso).

---

### Arquitetura (offline, sem dependências)

`src/static/i18n.js` + `src/static/locales/<code>.json`. Sem etapa de build, sem rede.

- **O inglês é a chave.** Os arquivos de localidade mapeiam a **string inglesa da interface → sua tradução**
  (por exemplo, `"Search the corpus": "Rechercher dans le corpus"`). Isso nos permite adaptar a
  interface existente sem marcar cada elemento e mantém o inglês como fonte
  canônica.
- **`OOI18N.setLang(code)`** carrega `locales/<code>.json`, persiste a escolha em
  `localStorage` (`oo.lang`), define `document.documentElement.lang` e `dir` (RTL para
  `ar`/`ur`) e depois **`apply()`** percorre o DOM — traduzindo os nós de texto cujo texto
  aparado corresponde a uma chave, além dos atributos `placeholder`/`title`/`aria-label`. Strings
  desconhecidas ficam como estão (recurso ao inglês) — nada jamais quebra.
- **O conteúdo dinâmico** (dados: títulos de artigos, nomes de fontes, contagens) **nunca** é
  traduzido — apenas a interface. A interface renderizada por JS (paleta de comandos, gaveta) chama
  `OOI18N.apply()` depois de renderizar.
- Cada localidade traz `_meta` (`name`, `native`, `dir`, `status`).

#### Como integrá-lo (Fase 2 — distribuída; o Desk foi desativado desde então)

Duas linhas em `index.html` (e, antes de sua desativação em 2026-06-10, em `desk.html`),
e depois um seletor de idioma:

```html
<script src="/static/i18n.js"></script>
<!-- after first render and on each view change: --> OOI18N.apply();
```

O seletor de **Idioma** fica em Configurações e chama `OOI18N.setLang(code)`,
persistido junto com as outras preferências locais da interface.

---

### Documentação em vários idiomas

Os documentos são longos e a qualidade da tradução importa mais do que para strings curtas da interface, portanto:

- Estrutura: `docs/i18n/<code>/<DOC>.md` espelha `docs/`.
- Os **documentos em inglês continuam canônicos**; as traduções são trabalho da comunidade/do mantenedor,
  cada uma marcada com a data da tradução e o commit em inglês que ela acompanha.
- **Não** traduzimos documentos automaticamente por máquina para apresentá-los como autoritativos — isso
  violaria o princípio de honestidade do projeto. Comece pelos documentos de maior valor e mais curtos
  (QUICKSTART, o tour "O que você verá primeiro", ETHICS) em cada idioma.

---

### Fluxo de contribuição (acesso aberto por concepção)

1. Copie `locales/en.json` → `locales/<code>.json`, traduza os valores, defina `_meta.status`.
2. Para idiomas RTL, defina `_meta.dir: "rtl"`.
3. Execute a verificação (planejada) de cobertura de chaves: informe as chaves faltantes/excedentes em relação a `en.json`.
4. Envie. As chaves não traduzidas simplesmente recorrem ao inglês até serem preenchidas.

---

### Situação

**Fase 1 (concluída):** o motor de i18n (`i18n.js`), a estrutura de localidades para todos os 12
idiomas e traduções de referência completas para **en/fr/es/de**.

**Fase 1b (concluída, `0.4.0`):** as strings restantes da interface receberam chaves e foram
traduzidas para **todos os doze** idiomas (consulte `CHANGES.md` 0.4.0), de modo que cada
localidade em `src/static/locales/*.json` traz agora o conjunto completo de chaves (verificado:
12 arquivos, 6.991 chaves cada, nenhuma faltando). A honestidade não mudou: nomes são
nomes próprios e não são traduzidos, e uma localidade parcial continua recorrendo ao
inglês em vez de quebrar.

**Fase 2 (concluída — aguardando uma verificação real em navegador):** `i18n.js` está incluído em
`index.html` (e esteve em `desk.html` até a desativação do Desk em 2026-06-10); um
seletor de **Idioma** (`#oo-lang-select`) está em Configurações e é ligado automaticamente; a interface renderizada dinamicamente é traduzida automaticamente por
um `MutationObserver` com debounce (sem chamadas `apply()` espalhadas); voltar ao inglês
restaura os originais; RTL via `<html dir>`. A estrutura/sintaxe estão validadas, mas
o comportamento ainda deve ser conferido num navegador.

**Fase 3 (próxima):** estender `en.json` ao catálogo *completo* de strings (atualmente ele
cobre a interface de maior tráfego), completar as localidades esboço (comunidade) e aprimorar o
layout RTL para `ar`/`ur`.


## Contrato de exportação (versionado)

As exportações legíveis por máquina trazem um contrato estável e autodescritivo (esquema `oo-export-1`,
0.0.8 parte 2 / RM-15), para que os pipelines a jusante nunca precisem adivinhar:

- **JSON** (`/api/articles/export?format=json`, `/api/links/export.json`): um envelope —
  `{export_schema, kind, app_version, generated_at, query, count, articles|data}`. O objeto
  `query` é a seleção geradora, literalmente; a proveniência acompanha os dados.
- **CSV** (`/api/articles/export?format=csv`): sem linha de comentário (ela quebraria leitores ingênuos);
  o mesmo envelope segue como cabeçalhos HTTP (`X-OO-Export-Schema`, `X-OO-App-Version`,
  `X-OO-Generated-At`, `X-OO-Query`). As colunas mantêm sua ordem, e uma nova coluna só é
  acrescentada ao final: `Fetched From Host` (item 61 da fila), o host do qual a página foi obtida após
  seus redirecionamentos, vazio quando não registrado; a exportação JSON o traz como `fetched_host`.
- **Grafo de citações** (`/api/links/export.graphml`, `.json`): o grafo de quem cita quem
  (artigos armazenados → domínios registráveis externos). **Apenas contagens — nenhuma credibilidade
  inferida, nenhuma pontuação**; a ressalva vem embutida no próprio arquivo. O GraphML abre no
  Gephi/yEd/NetworkX.

Mudanças de esquema incrementam `oo-export-N`; os campos existentes nunca são reaproveitados silenciosamente. Um campo
acrescentado ao lado deles (uma coluna CSV ao final, uma nova chave JSON) deixa os campos de todo leitor existente
onde estavam, portanto não incrementa o esquema.
