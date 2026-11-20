<!-- pt: Translation of docs/ETHICS.md written by AI (2026-11-19, R677; native review dropped by R721, 2026-11-14); it may contain mistakes, and the English original is authoritative. Coverage: the whole document, 50 of 50 headings. Corrections are welcome as a pull request. -->

# Diretrizes éticas do Open Omniscience

> **Situação (verificada novamente em 2026-10-08):** o software é um **alfa** funcional e testado
> (`v0.5.0` — consulte o README do repositório para saber o que funciona hoje; a redação da época 0.0.9 abaixo é
> mantida como registro histórico de quando estas diretrizes entraram em vigor). As primeiras versões traziam aqui um
> aviso de "não funcional"; isso deixou de ser verdade e foi removido —
> estas diretrizes **estão em vigor agora**, e não são uma referência para o futuro.
> *Nota histórica:* as primeiríssimas versões conceituais (anteriores à 0.0.4) partiram
> do copiador de sites HTTrack; o código atual é uma reescrita completa e
> não compartilha nenhum código com ele.

Este documento descreve os **princípios éticos, os requisitos de conformidade e as boas práticas** para usar o Open Omniscience e contribuir com ele. A observância destas diretrizes é **obrigatória** para todos os usuários e desenvolvedores.

O Open Omniscience está alinhado com a **Carta de Munique**, um conjunto fundamental de princípios para jornalistas adotado em 1971. Esses princípios estão integrados abaixo para orientar o uso ético desta plataforma.

---

## 📜 Carta de Munique: Declaração dos Deveres e dos Direitos

### Preâmbulo
O direito à informação, à liberdade de expressão e de crítica é um dos direitos fundamentais da humanidade. Todos os direitos e deveres de quem usa o Open Omniscience decorrem do direito do público de ser informado sobre fatos e opiniões. A responsabilidade dos usuários perante o público prevalece sobre qualquer outra responsabilidade, em particular perante empregadores e autoridades públicas. A missão de informar inclui necessariamente restrições que os usuários devem impor espontaneamente a si mesmos. Esse é o objeto da declaração de deveres formulada abaixo.

Um usuário do Open Omniscience só pode respeitar esses deveres no exercício de seu uso se existirem efetivamente condições de independência e de dignidade profissional. Esse é o objeto da declaração de direitos que se segue.

---

### 📋 Declaração dos Deveres
As obrigações essenciais dos usuários do Open Omniscience envolvidos na coleta, edição e análise de informações são:

1. **Respeito à verdade:**
   Respeitar a verdade, sejam quais forem as consequências para si próprio, em razão do direito do público de conhecer a verdade.

2. **Defender a liberdade de informação:**
   Defender a liberdade de informação, de comentário e de crítica.

3. **Verificar as fontes:**
   Relatar apenas fatos cuja origem seja conhecida; não suprimir informações essenciais nem alterar textos e documentos.

4. **Métodos leais:**
   Não empregar métodos desleais para obter informações, fotografias ou documentos.

5. **Respeitar a privacidade:**
   Obrigar-se ao respeito da vida privada.

6. **Corrigir imprecisões:**
   Retificar qualquer informação publicada que se revele inexata.

7. **Sigilo profissional:**
   Guardar o sigilo profissional e não divulgar a fonte das informações obtidas em confiança.

8. **Evitar faltas profissionais:**
   Considerar faltas profissionais graves:
   - O plágio
   - A calúnia, a difamação, a injúria e as acusações sem fundamento
   - A aceitação de suborno, sob qualquer forma, em troca da publicação ou da supressão de uma informação

9. **Separação da publicidade e da propaganda:**
   Nunca confundir o uso do Open Omniscience com a venda de publicidade ou com atividades de propaganda, e recusar qualquer instrução direta ou indireta de anunciantes.

10. **Resistir a pressões:**
    Resistir a toda pressão e aceitar instruções apenas de pessoas responsáveis alinhadas com o uso ético da plataforma.

---

### 📜 Declaração dos Direitos

Os usuários do Open Omniscience reivindicam:

1. **Livre acesso à informação:**
   O livre acesso a todas as fontes de informação e o direito de investigar livremente todos os fatos que condicionam a vida pública. Por isso, o sigilo de assuntos públicos ou privados só pode ser oposto aos usuários em casos excepcionais e por motivos claramente expressos.

2. **Recusar a subordinação antiética:**
   O direito de recusar a subordinação a qualquer coisa contrária à política geral do Open Omniscience, bem como qualquer subordinação que não esteja claramente implicada por essa política.

3. **Consciência e convicção:**
   Um usuário não pode ser obrigado a praticar um ato ou a expressar uma opinião contrária às suas convicções ou à sua consciência.

4. **Transparência na tomada de decisões:**
   A comunidade deve ser informada de todas as decisões importantes que possam influenciar o projeto. Deve, no mínimo, ser consultada antes que se tome uma decisão definitiva sobre qualquer assunto relacionado à direção do projeto.

5. **Remuneração justa e independência:**
   Tendo em conta suas funções e responsabilidades, os contribuidores têm direito a reconhecimento e a condições que garantam a segurança material e moral de seu trabalho, bem como a independência econômica.

---

## 🌍 Princípios fundamentais do Open Omniscience

1. **Respeito aos termos das fontes:** Sempre cumprir as diretivas do `robots.txt` e os termos de serviço dos sites raspados.
2. **Limitação de taxa:** O caminho único de busca (`EthicalFetcher`) impõe um intervalo
   mínimo entre requisições por host e adquire um bloqueio por host, de modo que apenas uma requisição a um dado
   host esteja em andamento a cada momento.
   - Padrão: **1 requisição por segundo por host** — o `min_interval_s` em
     `EthicalFetcher`, definido pela variável de ambiente `OO_FETCH_MIN_INTERVAL`.
   - Quando o `robots.txt` de um host publica um **`Crawl-delay`**, ele é respeitado: o
     intervalo efetivo é `max(min_interval, Crawl-delay)`.
   - (O `rate_limit_ms` por fonte em `sources.yml` é um campo de dados, **não** está ligado ao
     intervalo do buscador; as duas alavancas acima são as que de fato limitam o ritmo.)
3. **Transparência:** A atividade de busca é registrada localmente para a própria
   revisão do operador — veredictos por fonte/feed em `data/source_preflight.jsonl` e
   `data/feed_preflight.jsonl`, resultados de testes de campo em `data/field_test.jsonl` e
   erros do aplicativo em `data/app_errors.jsonl`. Esses arquivos permanecem na máquina e são reunidos,
   **apenas mediante clique**, no **pacote de depuração** de Configurações → diagnóstico — nunca
   transmitidos automaticamente. (Não existe `audit/scrape_log.csv`; esse foi um projeto inicial
   substituído pela postura local-first e sem telemetria.)
4. **Minimização de dados:** Coletar e armazenar apenas os dados necessários à funcionalidade central da plataforma (URL, título, conteúdo, metadados).
5. **Uso não malicioso:** O Open Omniscience não deve ser usado para:
   - Spam ou assédio.
   - Atividades ilegais (por exemplo, invasão de sistemas, violação de direitos autorais).
   - Exploração comercial sem permissão.
6. **Identificação do User-Agent:** Usar uma string de User-Agent clara e identificável. O bot
   envia `OpenOmniscienceBot/{version} (+https://github.com/ideotion/Open-Omniscience; ethical research crawler)`
   (buscas protegidas/roteadas por Tor enviam, em vez disso, um UA genérico de navegador, para se confundirem com o tráfego comum).
7. **Limitação por IP:** Evitar rajadas de requisições a partir de um único IP. Respeitar o uso justo dos servidores.

---

## ✅ Lista de verificação de conformidade

Antes de raspar uma nova fonte, verifique o seguinte:
- [ ] O domínio **não** está na [Lista de sites a não raspar](#lista-de-sites-a-não-raspar).
- [ ] O arquivo `robots.txt` permite a raspagem (verifique [https://{domain}/robots.txt](https://{domain}/robots.txt)).
- [ ] A fonte **não** exige autenticação nem implica contornar paywalls.
- [ ] Os limites de taxa estão configurados para evitar **>1 requisição por segundo** por padrão (ajuste para domínios sensíveis).
- [ ] A string de User-Agent identifica o Open Omniscience (`OpenOmniscienceBot/{version}`).
- [x] Os veredictos de busca são registrados localmente (`data/*_preflight.jsonl`) e expostos
  mediante clique pelo pacote de depuração de Configurações — nunca transmitidos automaticamente.

---

## 🚫 Lista de sites a não raspar

Esta lista é uma **orientação para o operador**, e não uma lista de bloqueio aplicada mecanicamente: o aplicativo
não traz um bloqueio embutido desses domínios. A proteção no nível do código é o **robots.txt
fail-closed** no caminho único `EthicalFetcher` — uma fonte cujo `robots.txt` não possa
ser obtido ou não permita claramente a URL é recusada, e não raspada. Ainda assim, os operadores devem
usar o próprio discernimento e evitar as categorias abaixo ao adicionar fontes:

### Conteúdo com paywall


### Plataformas de redes sociais


### Dados privados ou sensíveis
- Bases de dados governamentais (por exemplo, `*.gov`, `*.mil`, salvo se explicitamente públicas)
- Prontuários médicos (por exemplo, `*.health`, `*.medical`)
- Registros financeiros (por exemplo, `*.bank`, `*.finance`, salvo se públicos)
- Repositórios de dados pessoais (por exemplo, `*.personal`, `*.private`)

### Restrições técnicas
- Domínios com **limitação de taxa agressiva** (por exemplo, `github.com`, `stackoverflow.com`).
- Domínios que **bloqueiam raspadores** (por exemplo, sites protegidos por `cloudflare.com` sem contorno).
- **Fontes acessíveis só por API** (por exemplo, `twitter.com/api`, `reddit.com/api` — use as APIs oficiais).

> **Nota:** Esta lista não é exaustiva. Os usuários devem exercer **diligência** e **julgamento crítico** ao adicionar novas fontes. Na dúvida, **não raspe**. 

---

## 📊 Auditoria e prestação de contas

A atividade de busca é registrada **localmente**, para a própria revisão do operador, e é compartilhada
**apenas mediante clique** — nunca transmitida automaticamente (sem telemetria; local-first por concepção). O
mecanismo real (o projeto inicial `audit/scrape_log.csv` foi substituído por este):

- **Veredictos de pré-verificação** — os resultados de acessibilidade/robots/transporte por fonte e por feed
  são acrescentados a `data/source_preflight.jsonl` e
  `data/feed_preflight.jsonl` (cada linha: carimbo de data/hora, fonte/domínio, o veredicto
  sensível ao transporte e o motivo honesto). Eles alimentam a experiência "Repetir feeds com falha" e os
  veredictos por feed de Índices/mercados.
- **Resultados de testes de campo** — quando o modo de teste de campo está ativado, os exercícios das superfícies de busca são
  gravados literalmente em `data/field_test.jsonl`.
- **Erros do aplicativo** — limitados em `data/app_errors.jsonl` (as linhas mais recentes são mantidas).

### Compartilhamento para suporte

Não há CSV/`errors.log` enviado automaticamente. O operador pode gerar um **pacote de depuração**
(Configurações → diagnóstico) que reúne os logs JSONL acima e os diagnósticos de palavras-chave/rede;
ele é gravado em disco e compartilhado somente por ação explícita do operador.
Este é o protocolo do mantenedor: percorra o aplicativo clicando e depois entregue o pacote.

---

## 🔒 Privacidade e proteção de dados

- **Nenhum rastreamento de usuários:** O Open Omniscience **não** coleta nem armazena:
  - IPs de usuários
  - Históricos de pesquisa
  - Dados pessoais
- **Somente local:** Todos os dados permanecem na máquina do usuário. Nenhuma dependência de nuvem por padrão.
- **Criptografia em repouso (ativada por padrão):** Novos corpora são criados **criptografados** com
  SQLCipher, protegidos por uma frase-senha que o usuário escolhe no primeiro uso. Usar um
  banco de dados em **texto claro** é uma desistência explícita que exige a confirmação digitada do
  risco declarado. **Não há recuperação** para uma frase-senha esquecida (o corpus é
  reconstituível por nova raspagem, por isso não se acrescenta chave de recuperação nem segunda superfície de decifração).
  O modelo de ameaça é uma máquina apreendida ou copiada que está **desligada** — e não uma
  sessão comprometida já em execução (consulte `SECURITY.md`).
- **Conformidade com o RGPD:** Ao raspar fontes sediadas na UE:
  - Anonimize os dados pessoais (por exemplo, nomes, e-mails) no conteúdo armazenado.
  - Respeite o direito ao apagamento (exclua os dados mediante solicitação).

---

## 🌍 Considerações jurídicas

- **Direitos autorais:** Respeite as leis de direitos autorais. Raspe e armazene conteúdo apenas para:
  - Análise **pessoal, não comercial**.
  - **Uso legítimo** (*fair use*) (por exemplo, crítica, comentário, pesquisa).
  - **Fins transformativos** (por exemplo, agregação para jornalismo investigativo).
- **Conformidade com o RGPD:** Ao processar dados de cidadãos da UE:
  - Minimize a coleta de dados pessoais.
  - Ofereça um meio para que as pessoas solicitem a exclusão de seus dados.
- **Jurisdição:** Os usuários são responsáveis por cumprir as leis de sua jurisdição, incluindo:
  - **Computer Fraud and Abuse Act (CFAA)** (EUA)
  - **Regulamento Geral sobre a Proteção de Dados (RGPD)** (UE)
  - **Leis de direitos autorais** (diversos países)

---

## 🛡️ Salvaguardas técnicas

Para prevenir abusos e garantir uma raspagem ética, o Open Omniscience implementa as seguintes salvaguardas:

1. **Limitação de taxa:**
   - Padrão: 1 requisição por segundo por host (`min_interval_s`, a partir de `OO_FETCH_MIN_INTERVAL`).
   - O `Crawl-delay` do robots de um host é respeitado quando é maior; uma requisição por host de cada vez.

2. **Conformidade com o robots.txt:**
   - Verifica automaticamente o `robots.txt` antes de raspar.
   - Respeita as diretivas `Disallow`.

3. **Identificação do User-Agent:**
   - Envia `OpenOmniscienceBot/{version} (+https://github.com/ideotion/Open-Omniscience; ethical research crawler)`.
   - As buscas protegidas (roteadas por Tor) enviam um UA genérico de navegador para não serem destacadas.

4. **Tratamento de erros:**
   - Repete as requisições que falharam com recuo exponencial.
   - Registra todos os erros para revisão.

5. **Detecção de duplicatas:**
   - Usa a canonicalização de URLs e o hash do conteúdo para evitar raspagens redundantes.

6. **Trilhas de auditoria:**
   - Registra todas as atividades de raspagem para fins de transparência e prestação de contas.

---

## 📐 Métricas honestas — nenhuma pontuação fabricada

Honestidade por construção: o aplicativo nunca apresenta uma **pontuação composta de confiança / qualidade /
credibilidade**. Cada sinal que ele calcula traz seu método, uma ressalva e seu
*n*; um cartão que tentasse exibir uma pontuação combinada é rejeitado mecanicamente pelo
esquema de cartões. As colunas de pontuação inativas (`credibility_score`, `political_bias`) são mantidas
NULL e nunca são serializadas em nenhuma resposta da API.

**Uma exceção intencional e restrita — `reliability_score`.** Este campo `1–10` por fonte
é **metadado de proveniência declarado pelo operador**: um número que *você* (o operador)
define por fonte via configuração ou importação de CSV. Ele **nunca é calculado, nunca recebe valor padrão
e nunca é derivado dos dados dos artigos** pelo aplicativo — o antigo padrão fabricado `=5`
foi removido (anulado pela migração `f4b5c6d7e8a9`). Por ser uma afirmação sua
(e não um veredicto fabricado pela ferramenta), ele é exibido na lista de fontes e
rotulado **"definido pelo operador, não calculado"** onde quer que apareça; um cartão do briefing
continua sem poder apresentá-lo como pontuação. Um invariante do repositório
(`tests/test_repo_invariants.py::test_reliability_score_is_operator_set_never_computed`)
garante isso, para que ele não se torne discretamente um veredicto de qualidade calculado.

---

## 📢 Como denunciar violações

Se você encontrar ou suspeitar de uso antiético do Open Omniscience:
1. **Interrompa** imediatamente a atividade violadora.
2. **Documente** o incidente (por exemplo, capturas de tela, logs, carimbos de data/hora).
3. **Denuncie** aos mantenedores por meio de:
   - [GitHub Issues](https://github.com/ideotion/Open-Omniscience/issues) (para denúncias públicas)
   - E-mail: `open-omniscience@ideotion.com` (para denúncias sensíveis)

---

## 📅 Revisão e atualizações

Este documento será **revisado e atualizado regularmente** para refletir:
- Novos desafios éticos (por exemplo, conteúdo gerado por IA, deepfakes).
- Requisitos legais (por exemplo, mudanças nas leis de direitos autorais ou de proteção de dados).
- Retorno da comunidade (por exemplo, relatos de uso indevido ou sugestões de melhoria).

### Histórico de versões
| Versão | Data       | Alterações                                                              |
|---------|------------|-------------------------------------------------------------------------|
| 1.0     | 2026-05-07 | Versão inicial. Adicionadas a Lista de sites a não raspar, o registro de auditoria e as notas sobre o RGPD. |
| 1.1     | 2026-05-07 | Adicionadas a identificação do User-Agent, a limitação por IP e as salvaguardas técnicas. |

---

## 📌 Boas práticas para contribuidores

1. **Teste de forma ética:**
   - Sempre teste a raspagem em pequena escala antes de ampliá-la.
   - Use `localhost` ou ambientes de homologação sempre que possível.

2. **Documente as fontes:**
   - Adicione comentários em `sources.yml` explicando por que uma fonte foi incluída/excluída.
   - Anote quaisquer requisitos especiais de raspagem (por exemplo, seletores personalizados).

3. **Respeite os pedidos de exclusão:**
   - Se uma fonte pedir para ser removida, atenda imediatamente.
   - Adicione o domínio à Lista de sites a não raspar.

4. **Minimize o impacto:**
   - Raspe fora dos horários de pico sempre que possível.
   - Armazene as respostas em cache para evitar requisições repetidas pelo mesmo conteúdo.

5. **Mantenha-se atualizado:**
   - Verifique regularmente se houve mudanças no `robots.txt`.
   - Acompanhe as atualizações legais (por exemplo, novas leis de direitos autorais).

---
**Lembre-se:** A raspagem ética não é apenas uma obrigação legal — é uma **responsabilidade moral**. Ao usar o Open Omniscience, você se compromete a respeitar estes princípios.

---

# Conformidade, licenciamento e avisos de terceiros

O complemento jurídico e de atribuição dos princípios éticos acima.

**Nesta parte:**
- [Guia de conformidade com a GPLv3](#guia-de-conformidade-com-a-gplv3)
- [Avisos e atribuições de terceiros](#avisos-e-atribuições-de-terceiros)


---

## Guia de conformidade com a GPLv3

Esta seção descreve a conformidade do Open Omniscience com a GNU General
Public License Versão 3 (GPLv3). Ela se aplica ao software funcional tal como distribuído.

---

### 📜 Licença do Open Omniscience

**Licença:** GNU General Public License Versão 3 (GPLv3)  
**Direitos autorais:** © 2026 Ideotion  
**Arquivo de licença:** [LICENSE](../LICENSE)

O Open Omniscience é integralmente licenciado sob a GPLv3, que concede aos usuários as
seguintes liberdades (o software é um pré-alfa funcional e testado — elas se aplicam desde já):

1. **Liberdade 0:** A liberdade de executar o programa para qualquer propósito
2. **Liberdade 1:** A liberdade de estudar como o programa funciona e de modificá-lo
3. **Liberdade 2:** A liberdade de redistribuir cópias
4. **Liberdade 3:** A liberdade de distribuir versões modificadas

---

### ✅ Lista de verificação de conformidade com a GPLv3

#### Para o projeto Open Omniscience

- [x] **Arquivo de licença**: O texto completo da GPLv3 está incluído em [LICENSE](../LICENSE)
- [x] **Disponibilidade do código-fonte**: Todo o código-fonte está publicamente disponível neste repositório
- [x] **Avisos de direitos autorais**: Os módulos de código-fonte trazem um aviso `Copyright (C) 2026 Ideotion`;
  a [LICENSE](../LICENSE) do projeto rege a obra como um todo
- [x] **Cabeçalhos de licença**: A maioria dos módulos de código-fonte traz um cabeçalho no estilo SPDX `GPL-3.0-or-later`
  (alguns marcadores de pacote `__init__.py` vazios e alguns módulos pequenos
  não o trazem). A GPLv3 **não** exige um cabeçalho por arquivo — o arquivo [LICENSE](../LICENSE) é
  a referência para toda a obra; os avisos por módulo são uma cortesia, e não uma afirmação
  de que todo arquivo traga um
- [x] **Nenhuma restrição adicional**: Não se impõe nenhuma restrição além da GPLv3
- [x] **Versões modificadas**: Todas as modificações trazem avisos destacados (Seção 5a)
- [x] **Informações de instalação**: Não se aplica (não é um Produto de Usuário conforme definido na GPLv3)

---

### 📦 Conformidade na distribuição

#### Distribuição do código-fonte

Ao distribuir o código-fonte do Open Omniscience:

1. ✅ **Incluir o arquivo LICENSE**: O texto completo da licença GPLv3 deve ser incluído
2. ✅ **Incluir o ETHICS.md**: As atribuições de terceiros devem ser incluídas
3. ✅ **Preservar os cabeçalhos**: Todos os arquivos-fonte devem manter seus cabeçalhos GPLv3
4. ✅ **Preservar os direitos autorais**: Todos os avisos de direitos autorais devem ser preservados
5. ✅ **Documentar as alterações**: Quaisquer modificações devem ser documentadas

#### Distribuição binária

Ao distribuir o Open Omniscience em forma binária:

1. ✅ **Incluir o código-fonte**: É preciso fornecer o Código-Fonte Correspondente (Seção 6)
2. ✅ **Incluir a LICENSE**: O texto completo da GPLv3 deve ser incluído
3. ✅ **Incluir o ETHICS.md**: As atribuições de terceiros devem ser incluídas
4. ✅ **Documentar as alterações**: Quaisquer modificações devem ser documentadas
5. ✅ **Nenhuma restrição adicional**: Não é permitido acrescentar restrições além da GPLv3

#### Conformidade para Produtos de Usuário

Se o Open Omniscience for distribuído como parte de um Produto de Usuário (dispositivo de consumo):

1. ✅ **Informações de instalação**: É preciso fornecer informações para instalar versões modificadas (Seção 6)
2. ✅ **Disponibilidade do código-fonte**: É preciso fornecer o Código-Fonte Correspondente
3. ✅ **Nenhuma tivoização**: Não é permitido impedir os usuários de instalar versões modificadas

**Nota:** O Open Omniscience em si não é um Produto de Usuário, mas, se você o incorporar a um, esses requisitos se aplicam.

---

### 🔍 Etapas de verificação

#### Para desenvolvedores

1. **Verificar os cabeçalhos de licença**
   ```bash
   grep -r "GNU General Public License" src/ tests/ package/ scripts/
   ```

2. **Verificar o arquivo LICENSE**
   ```bash
   head -5 LICENSE
   ```

3. **Verificar o arquivo NOTICES**
   ```bash
   cat ETHICS.md
   ```

4. **Verificar a ausência de código proprietário**
   ```bash
   # Check for any non-GPLv3 licensed code in active project
   find . -path "./.git" -prune -o -path "./archive" -prune -o -type f -print
   ```

#### Para usuários

1. **Verificar a licença**
   ```bash
   cat LICENSE | head -5
   ```

2. **Revisar as atribuições**
   ```bash
   cat ETHICS.md
   ```

---

### 📝 Perguntas frequentes sobre conformidade

#### P: Posso usar o Open Omniscience para fins comerciais?
**R:** Sim! A GPLv3 permite o uso comercial. No entanto, quaisquer versões modificadas que você distribuir também devem ser licenciadas sob a GPLv3, e você deve fornecer o código-fonte.

#### P: Posso usar o Open Omniscience em software proprietário?
**R:** Não. A GPLv3 exige que as obras derivadas também sejam licenciadas sob a GPLv3. Você não pode incorporar o Open Omniscience a um aplicativo proprietário de código fechado.

#### P: Preciso publicar minhas modificações?
**R:** Somente se você as distribuir. Se você modificar o Open Omniscience para uso próprio e não o distribuir, não precisa publicar suas modificações.

#### P: E quanto às dependências Python?
**R:** As dependências Python (FastAPI, SQLAlchemy etc.) são obras separadas, com suas próprias licenças. A licença GPLv3 do Open Omniscience não as afeta. Consulte [ETHICS.md](ETHICS.md) para mais detalhes.

#### P: E quanto aos dados que eu raspo?
**R:** A licença GPLv3 se aplica apenas ao próprio software Open Omniscience, e não aos dados que você coleta. Você é responsável por cumprir os direitos autorais e os termos de serviço dos sites que raspa.

---

### 📞 Como relatar problemas de conformidade

Se você tiver dúvidas ou preocupações sobre a conformidade com a GPLv3:

- **E-mail:** open-omniscience@ideotion.com
- **GitHub:** https://github.com/ideotion/Open-Omniscience
- **GitHub Issues:** https://github.com/ideotion/Open-Omniscience/issues

---

### 📚 Recursos

- [Texto completo da licença GPLv3](../LICENSE)
- [Site oficial da GNU GPLv3](https://www.gnu.org/licenses/gpl-3.0.html)
- [Perguntas frequentes da GNU GPLv3](https://www.gnu.org/licenses/gpl-faq.html)
- [Avisos de terceiros](ETHICS.md)

---

**Última atualização:** 2026-06-14


---

## Avisos e atribuições de terceiros

Esta seção contém os avisos e as atribuições referentes a software e
bibliotecas de terceiros usados pelo Open Omniscience. (*Nota histórica:* as versões
conceituais anteriores à 0.0.4 partiram do HTTrack; o código atual é uma reescrita completa e
não resta nenhum código do HTTrack.)

---

### 📦 Dependências Python

O Open Omniscience **usa** os seguintes pacotes Python, cada um sob sua própria
licença. A lista de referência, mantida em uma única fonte, é [`pyproject.toml`](../pyproject.toml);
execute `pip show <package>` (ou `pip-licenses`) para confirmar a licença de qualquer
versão instalada. **Toda dependência é FOSS e compatível com a GPLv3** — esse é um
requisito de inclusão (consulte o invariante FOSS-only em `docs/DESIGN.md`).

**Núcleo (sempre instalado):**

| Pacote | Licença | Finalidade |
|---------|---------|---------|
| FastAPI | MIT | Framework de API web |
| Uvicorn | BSD-3-Clause | Servidor ASGI |
| Jinja2 | BSD-3-Clause | Templates no lado do servidor |
| SlowAPI | MIT | Limitação de taxa |
| Prometheus Client | Apache-2.0 | Endpoint de métricas |
| SQLAlchemy | MIT | ORM de banco de dados |
| Alembic | MIT | Migrações de esquema |
| sqlcipher3 | Zlib/BSD-style | Criptografia SQLCipher em repouso |
| Requests | Apache-2.0 | Cliente HTTP (buscador ético) |
| httpx | BSD-3-Clause | Cliente HTTP |
| BeautifulSoup4 | MIT | Análise de HTML |
| lxml | BSD-3-Clause | Análise de XML/HTML |
| feedparser | BSD-2-Clause | Análise de RSS/Atom |
| trafilatura | Apache-2.0 | Extração de artigos |
| Pydantic | MIT | Validação de dados |
| PyYAML | MIT | Leitura de configuração |
| Bleach | Apache-2.0 | Sanitização de HTML |
| bcrypt | Apache-2.0 | Primitiva de hash de senhas |
| defusedxml | PSF-2.0 | Proteção contra XML não confiável (dumps da Wikipedia) |
| cryptography | Apache-2.0 OR BSD-3-Clause | Assinaturas Ed25519 + árvores de Merkle |
| Pillow | HPND (MIT-CMU) | EXIF / metadados de imagens |
| python-dateutil | Apache-2.0 / BSD | Análise de datas |
| tenacity | Apache-2.0 | Novas tentativas / recuo |
| cachetools | MIT | Cache em memória |
| orjson | Apache-2.0 OR MIT (com um componente MPL-2.0) | JSON rápido |
| psutil | BSD-3-Clause | Sinais vitais do hardware |

**Extras opcionais (instalados sob demanda):**

| Extra | Pacotes | Licença | Finalidade |
|---|---|---|---|
| `analysis` | numpy, pandas, scipy, scikit-learn, statsmodels, networkx | BSD-3-Clause | Estatística / grafos |
| `analysis` | nltk | Apache-2.0 | Tokenização |
| `analysis` | vaderSentiment | MIT | Sentimento por léxico (somente inglês) |
| `nlp` | spaCy | MIT | Pipeline de PLN |
| `crypto` | python-gnupg | LGPL-3.0 | Integração com GPG |
| `pqc` | pqcrypto | MIT | Assinaturas pós-quânticas (ML-DSA) |
| `timestamping` | opentimestamps | LGPL-3.0 | Carimbos de tempo ancorados no Bitcoin |
| `compression` | zstandard, lz4 | BSD | Compressão de cópias de segurança |

O LLM local é o binário **externo Ollama** (MIT), acessado por HTTP via loopback
— nenhum peso de modelo nem biblioteca de inferência é incluído ou distribuído.

#### Notas de conformidade

- Cada dependência é uma **obra separada** sob sua própria licença; a GPLv3 do Open
  Omniscience não se estende a ela, e a licença dela não restringe
  o Open Omniscience.
- Todas as licenças listadas são **permissivas ou de copyleft fraco e compatíveis com a GPLv3**
  (os extras LGPL-3.0 `python-gnupg`/`opentimestamps` e o componente MPL-2.0
  do `orjson` são, cada um, compatíveis com a GPL-3.0). Ser FOSS e compatível com a GPLv3 é um
  requisito rígido de inclusão.
- Os usuários devem cumprir a licença individual de cada dependência; `pip show <pkg>`
  a exibe.

---

### 📄 Fontes tipográficas e ícones

| Recurso | Licença | Origem |
|----------|---------|--------|
| Ícone do projeto | MIT (original) | Incluído no projeto |
| Fontes incluídas — Inter, Outfit, Manrope, JetBrains Mono, Source Serif 4, Cantarell | SIL Open Font License 1.1 | `src/static/fonts/` (cada uma com seu `OFL-*.txt`) |

### 📦 Dados e recursos incluídos

Estes recursos que não são código estão incorporados ao repositório sob suas próprias licenças.
Registrados em `configs/external_artifacts.yml` (atualidade/atribuição acompanhadas ali).

| Recurso | Licença | Atribuição / notas |
|-------|---------|---------------------|
| Fontes (Inter · Outfit · Manrope · JetBrains Mono · Source Serif 4 · Cantarell) | SIL OFL 1.1 | `src/static/fonts/*.woff2`, texto da licença em `src/static/fonts/OFL-*.txt` |
| Alpine.js v3.14.1 (galeria de GUIs) | MIT | Incorporado localmente, fixado por sha256, sem CDN — `src/static/guis/vendor/alpine.min.js` |
| vaderSentiment 3.3.2 — três métodos do analisador adaptados para tempo linear | MIT | **Copyright (c) 2016 C.J. Hutto**; o aviso é reproduzido em `src/analytics/vader_linear.py`, que só é executado sobre o arquivo exato com que foi conferido (fixado por sha256) |
| DB-IP IP-to-Country Lite (geolocalização offline) | CC BY 4.0 | **Atribuição obrigatória:** "IP geolocation by DB-IP (https://db-ip.com) — CC BY 4.0" — `src/geo/data/dbip_country_lite.csv.gz` |
| stopwords-iso (listas multilíngues de palavras vazias) | MIT | `configs/stopwords_iso/*.txt` |
| Natural Earth (linhas costeiras + polígonos de países) | Domínio público | `src/static/world_outline.json`, `src/static/world_countries.json` |

---

### 📝 Fontes de dados

O Open Omniscience agrega dados de diversas fontes de notícias. Os usuários são responsáveis por:

1. Respeitar os **direitos autorais** do conteúdo raspado
2. Cumprir os **termos de serviço** de cada site
3. Seguir as diretivas do **robots.txt**
4. Observar as diretrizes de **raspagem ética** (consulte [ETHICS.md](ETHICS.md))

**Nota:** A licença GPLv3 do Open Omniscience **não** se aplica aos dados raspados com o software. Os usuários são os únicos responsáveis por garantir que o uso que fazem dos dados raspados cumpra todas as leis e regulamentações aplicáveis.

---

### 🔍 Verificação

Para verificar a conformidade com as licenças de terceiros:

1. **Dependências Python**: Execute `pip list` para ver todos os pacotes instalados e suas licenças
2. **Código-fonte**: Todo o código-fonte do Open Omniscience está disponível neste repositório

---

### 📞 Contato

Para dúvidas sobre licenças de terceiros ou conformidade:
- **E-mail:** open-omniscience@ideotion.com
- **GitHub:** https://github.com/ideotion/Open-Omniscience

---

**Última atualização:** 2026-06-14
