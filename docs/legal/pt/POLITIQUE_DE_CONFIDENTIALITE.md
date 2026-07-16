# Política de Privacidade (RGPD)

> **Tradução automática (rascunho) — pendente de revisão nativa. A versão francesa
> ([`../POLITIQUE_DE_CONFIDENTIALITE.md`](../POLITIQUE_DE_CONFIDENTIALITE.md)) é o texto
> juridicamente autêntico.**

> ⚠️ **Aviso importante — rascunho de trabalho, não é aconselhamento jurídico.** Este
> documento é um **rascunho de trabalho (modelo)** fornecido a título informativo. **Não
> constitui aconselhamento nem consulta jurídica** e não foi validado por um profissional
> do direito qualificado. Deve ser **revisto, completado e validado por um profissional
> qualificado** antes de qualquer publicação. As menções entre parênteses retos
> **[À COMPLÉTER: …]** e **[À VÉRIFIER: …]** assinalam informações ainda a fornecer ou a
> confirmar.

**Versão:** 1.0-draft
**Data de entrada em vigor:** 2026-07-16
**Contacto:** open-omniscience@ideotion.com

---

## 1. Princípio orientador: ausência de tratamento pelo Editor

**Open Omniscience** («o Software») é um **software livre «local-first»**. **O Editor
(Ideotion) não recolhe, não aloja e não trata quaisquer dados pessoais** dos Utilizadores
e **não explora qualquer servidor**. **Não há conta, nem registo, nem serviço em linha,
nem telemetria.** **100 % dos tratamentos** realizados por meio do Software são executados
**localmente, na máquina do Utilizador**.

Por conseguinte:

- o Editor **não é responsável pelo tratamento nem subcontratante** dos dados tratados
  pelo Utilizador por meio do Software;
- o Editor **não tem acesso** a nenhum dos dados do Utilizador;
- a presente política tem um valor **informativo**: explica o funcionamento do Software e
  **as obrigações que recaem sobre o Utilizador** quando este trata dados pessoais.

## 2. Ausência de telemetria e de recolha (verificável)

A conceção do Software garante, **por construção**:

- **nenhuma telemetria**, nenhum rastreador, nenhum identificador de utilização;
- um **arranque sem qualquer chamada de rede**; um **interruptor de rede («modo avião»)**
  na interface corta todo o tráfego de saída;
- as **únicas** ligações de rede são as que **o Utilizador desencadeia** para recolher
  fontes (através do componente de obtenção «ética») e, se for o caso, a utilização
  **local** de um modelo de IA (Ollama) que **não sai da máquina**;
- sendo o código **livre (GPL v3)**, este comportamento é **auditável por qualquer
  pessoa**.

> *Nota de coerência:* estas afirmações refletem o estado documentado do Software (ver o
> `README`, [`../../SECURITY.md`](../../SECURITY.md) e [`../../ETHICS.md`](../../ETHICS.md)).
> Qualquer alteração futura que introduzisse uma transmissão de dados deveria ser
> documentada aqui **antes** da sua entrada em serviço. [À VÉRIFIER: confirmar a ausência
> de telemetria em cada versão publicada.]

## 3. Dados técnicos tratados localmente pelo Software

O Software armazena, **apenas na máquina do Utilizador**, os dados necessários ao seu
funcionamento: o corpus recolhido, os metadados de proveniência, o índice de pesquisa, as
definições, os registos locais, as chaves de assinatura e o **registo local de
consentimento** (versão aceite + data e hora ISO 8601). Estes dados **permanecem sob o
controlo exclusivo do Utilizador** e nunca são transmitidos ao Editor.

## 4. O Utilizador, único responsável pelo tratamento

Quando os conteúdos que o Utilizador recolhe, importa ou analisa **contêm dados pessoais**
(por exemplo nomes, declarações atribuídas, imagens, identificadores), o Utilizador atua
como **responsável pelo tratamento** na aceção do **Règlement (UE) 2016/679 (RGPD)** e da
**loi n° 78-17 du 6 janvier 1978 relative à l'informatique, aux fichiers et aux libertés
(«Loi Informatique et Libertés»)**, alterada.

Como tal, **cabe ao Utilizador** cumprir, em particular, as seguintes obrigações:

### 4.1. Base jurídica e minimização

- determinar uma **base jurídica** apropriada (por exemplo o **interesse legítimo**,
  respeitando a **ponderação** face aos direitos dos titulares);
- aplicar os princípios de **minimização**, **limitação da finalidade** e **limitação da
  conservação**.

### 4.2. Dados de categorias especiais

- exercer uma **vigilância reforçada** relativamente às **categorias especiais de dados**
  (alegada origem racial ou étnica, opiniões políticas, convicções, saúde, orientação
  sexual, dados biométricos ou genéticos, etc.) abrangidas pelo **article 9 du RGPD**,
  cujo tratamento é **em princípio proibido** salvo exceção aplicável.

### 4.3. Transparência e direitos dos titulares

- assegurar, na medida exigida, a **transparência** para com os titulares;
- permitir o exercício dos seus **direitos**: **acesso, retificação, apagamento («direito a
  ser esquecido»), limitação, oposição e portabilidade**.

### 4.4. Pedidos de apagamento

Qualquer pedido de apagamento ou de retificação relativo a conteúdos recolhidos pelo
Utilizador é da **responsabilidade do Utilizador** (que detém e controla os dados
localmente). **O Editor não pode tratar qualquer pedido deste tipo**, por não ter acesso
aos dados. Para facilitar esta obrigação, o Software permite ao Utilizador **pesquisar e
apagar** conteúdos do seu corpus local.

### 4.5. Isenção «jornalística»

Quando o tratamento for efetuado para **fins jornalísticos** ou de **expressão e
informação**, o Utilizador pode, em determinadas condições, beneficiar das **adaptações**
previstas no **article 85 du RGPD** e nas disposições correspondentes da **Loi Informatique
et Libertés**. Esta isenção **não dispensa** do cumprimento dos princípios essenciais e
**deve ser apreciada caso a caso**; insere-se na **apreciação e na responsabilidade do
Utilizador**. [À VÉRIFIER: referências precisas das disposições nacionais que transpõem o
article 85.]

## 5. Resultados produzidos por IA e dados pessoais

Os resultados produzidos ou assistidos por IA (resumos, traduções, extração de entidades,
análise de sentimento, etc.) podem **mencionar ou inferir** informações relativas a
pessoas. São **probabilísticos e falíveis** (ver o **artigo 7.º das
[Condições de Utilização](CGU.md)**) e **não constituem nem uma constatação nem uma
acusação**. A sua produção, a sua conservação e, sobretudo, a sua **eventual difusão**
inserem-se na **responsabilidade do Utilizador** como responsável pelo tratamento e autor
editorial.

## 6. Segurança

O Software oferece medidas de segurança **locais** (por exemplo a **cifragem em repouso**
via SQLCipher, a execução limitada à interface de loopback). A **implementação e a
solidez** destas medidas, bem como a **segurança física e lógica** da máquina, cabem ao
Utilizador. A cifragem em repouso protege um ficheiro **apreendido ou copiado**, **não**
uma sessão em execução comprometida, e **não oferece qualquer recuperação** da frase-passe.

## 7. Autoridade de controlo

Em França, a autoridade de controlo competente é a **Commission nationale de
l'informatique et des libertés (CNIL)**. O Utilizador, na sua qualidade de responsável
pelo tratamento, é o **ponto de contacto** da autoridade de controlo para os tratamentos
que efetua.

## 8. Contacto

Tendo a presente política um valor **informativo** (não tratando o Editor quaisquer
dados), nenhum pedido de exercício de direitos pode ser satisfeito pelo Editor. Para
qualquer **questão relativa a este documento**: **open-omniscience@ideotion.com**.

---

*Documentos relacionados: [Condições de Utilização](CGU.md) · [Menções Legais](MENTIONS_LEGALES.md) · [Carta de Utilização Aceitável](CHARTE_USAGE.md) · [Índice](README.md). Ver também [`../../SECURITY.md`](../../SECURITY.md) e [`../../ETHICS.md`](../../ETHICS.md).*
