<!-- pt: Translation of docs/GOVERNANCE.md written by AI (2026-11-19, R677; native review dropped by R721, 2026-11-14); it may contain mistakes, and the English original is authoritative. Coverage: the whole document, 7 of 7 headings. Corrections are welcome as a pull request. -->

# Governança e uso aceitável

Open Omniscience é uma ferramenta para **responsabilizar o poder**, ajudando as pessoas a ver
com honestidade a *estrutura* da informação pública. Como essa capacidade é poderosa, este
documento declara claramente para que serve a ferramenta, as linhas que ela não ultrapassará e
como pretende continuar digna de confiança à medida que cresce. Isto faz parte da ética do
projeto, não é um pensamento de última hora.

## Para que serve

- **Jornalismo investigativo e pesquisa de interesse público** sobre mídia, instituições,
  mercados e legislação *publicados* — trazendo à tona estrutura mensurável (concentração de
  propriedade, coordenação/eco, novidade, enquadramento, mudança ao longo do tempo) para que um
  ser humano a julgue.
- **Proteção de fontes e reprodutibilidade** — local em primeiro lugar, capaz de funcionar
  offline, com proveniência à prova de adulteração para que as conclusões possam ser defendidas.
  O registro de cadeia de custódia encadeado por hash e assinado é **opcional** (desativado por
  padrão — acrescenta um pequeno custo de assinatura por artigo): ative-o em **Configurações →
  Cadeia de custódia → "Registro automático na ingestão"** (ou `OO_CUSTODY_ON_INGEST=1`)
  quando a integridade probatória importar para um caso. Até lá, a proveniência continua a
  acompanhar cada artigo (fonte, hora da captura, hash do conteúdo) e pacotes de evidências
  assinados podem ser produzidos sob demanda.

## Linhas vermelhas de uso duplo (ausentes por construção, não configuráveis)

As mesmas técnicas que expõem uma operação de influência coordenada poderiam, em mãos erradas,
ser apontadas contra pessoas comuns. A linha que mantém isto como instrumento de
*responsabilização* e não como ferramenta de *vigilância* é precisa, e é mantida na
**arquitetura**, não numa configuração que um usuário pudesse alterar:

1. **Nenhum rastreamento de indivíduos privados.** A ferramenta analisa *fontes publicadas*
   (veículos, instituições, documentos públicos). Ela **não** traça perfis de pessoas privadas,
   e `src/compliance/gdpr.py` é a salvaguarda. A proeminência mede a *cobertura de figuras
   públicas sobre as quais já se escreveu* — atenção, nunca importância ou mérito.
2. **Nenhuma identificação biométrica.** Nenhum reconhecimento de rosto, voz ou marcha. Nunca.
3. **Nenhuma ingestão de canais privados.** Nada de mensagens diretas, feeds privados,
   mensagens interceptadas ou dados não públicos. O corpus é construído a partir de fontes às
   quais o usuário pode ter acesso de forma lícita e ética.
4. **Nenhum veredito automatizado.** Nenhuma pontuação de verdade/credibilidade/"confiança",
   nenhum rótulo de "tendencioso"/"falso". A ferramenta apresenta *medições com método +
   ressalva*; o ser humano tira a conclusão. (Imposto no código: `assert_no_score_fields`.)
5. **Nenhum servidor central, contas ou telemetria.** Nada sai da máquina do usuário, exceto as
   buscas que ele próprio comanda. Não existe um pote de mel de dados de usuários para ser
   apreendido ou intimado.
6. **Nenhuma filtragem silenciosa ou redução de peso de fontes.** Os fatos de cobertura são
   *apresentados*; qualquer desamplificação é aplicada pelo usuário, sinalizada e reversível —
   apresentar, nunca impor.

Estas linhas são impostas até onde o código consegue: um teste de CI
(`tests/test_repo_invariants.py::test_red_lines_not_crossed`) faz a compilação falhar se
capacidades proibidas (reconhecimento biométrico, rastreamento de indivíduos) aparecerem na base
de código. Um teste é um alarme, não uma prova — a verdadeira garantia é a cultura e a revisão.

## Postura jurídica e ética

- Um **espelho de pesquisa**, não a fonte oficial, e **não aconselhamento jurídico**; cada
  registro remete à sua origem.
- **Acesso ético** por padrão: robots.txt com falha fechada, limites de taxa por host, um
  User-Agent identificável, atribuição e proveniência armazenadas. (Um usuário pode ativar a
  busca *Protegida* — proxy + UA genérico, exceto nas próprias requisições do aplicativo à
  Wikipédia, ao Wikidata e aos dumps da Wikimedia, cuja política de API pede que cada ferramenta
  se identifique — para proteger uma fonte ou a si mesmo ao investigar um alvo poderoso; este é
  o dever jornalístico de proteção das fontes, assumido deliberadamente e documentado, nunca o
  padrão silencioso.)
- **Respeitar licenças e direitos autorais**; armazenar a proveniência e o mínimo necessário;
  cumprir as obrigações de proteção de dados de cada jurisdição.

## Independência e financiamento

A ferramenta é deliberadamente **barata de operar** (local, sem infraestrutura) para que possa
continuar **independente**. Se o projeto algum dia receber financiamento, evitará a captura por
qualquer financiador ou agenda única, governará as decisões de forma transparente e nunca
distorcerá a definição de "desinformação" para agradar a um patrocinador. A escolha mais
política que este projeto faz é permanecer pequeno, local e impossível de capturar.

## Resistência ao uso indevido

Nenhuma ferramenta consegue impedir todo uso indevido, e não vamos fingir o contrário. Nossa
resistência é estrutural: as linhas vermelhas acima, o design local em primeiro lugar (nenhum
dado central para abusar em escala), a recusa em emitir vereditos e a abertura (qualquer pessoa
pode inspecionar, bifurcar e auditar). Se você acredita que o projeto está sendo conduzido para
além de uma linha vermelha, abra uma issue — essa possibilidade de contestação é o objetivo.

## Como as decisões são tomadas (intenção)

Hoje este é um projeto inicial, com um único mantenedor. Antes de uma versão alfa pública `0.1`,
pretendemos: uma **revisão externa de segurança e ética**, uma transição para uma **governança
com vários mantenedores** e tomada de decisão transparente, e um **pacto de contribuição** que
vincule os contribuidores às linhas vermelhas. Até lá, este documento é o compromisso oficial.
