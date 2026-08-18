# Processo de Garimpo e Análise de Viabilidade — Leilões Imobiliários Extrajudiciais
> **Projeto: Alvo Leilões**

> Documento vivo. Objetivo: mapear o processo ponta a ponta (prospecção → pós-arremate) para depois fatiar em MVPs de automação. Itens marcados **[TBD]** ainda precisam de input. Itens marcados **[VERIFICAR]** são pontos jurídicos/técnicos que assumi com base em conhecimento geral e merecem confirmação. **v2 — incorpora respostas do usuário e o checklist pessoal de leilões extrajudiciais.**

---

## 0. Visão geral do pipeline

```
1. PROSPECÇÃO        → onde e como os leilões/imóveis são descobertos
2. TRIAGEM RÁPIDA     → filtro grosseiro (vale a pena olhar com calma?)
3. ANÁLISE DOCUMENTAL → edital, matrícula, processos
4. ANÁLISE JURÍDICA   → riscos, ônus, modalidade, desocupação
5. ANÁLISE FINANCEIRA → viabilidade econômica
6. SCORE/DECISÃO      → consolidação → participa ou não
7. LANCE/ARREMATE     → checklist de preparação, execução do lance
8. PÓS-ARREMATE [futuro] → imissão na posse, desocupação, reforma, revenda
```

---

## 1. Prospecção

**Objetivo:** descobrir ofertas de leilão extrajudicial que se encaixam no perfil de interesse.

**Tipo de tarefa:** coleta (Zukerman via scraping; **Caixa via planilha — mais simples que scraping**).

**Definido:**
- **MVP: 2 fontes** — leiloeiro **Caixa** e **Zukerman**. Expansão para outras fontes fica para depois do MVP.
- **Caixa disponibiliza uma planilha com todos os imóveis em leilão** — para essa fonte não é preciso construir scraper, só um importador de planilha. Reduz bastante o esforço de engenharia da primeira fonte.
- Filtro **geográfico parametrizável** pelo usuário (não fixo em BH/MG).
- Filtro de **tipo de imóvel parametrizável** (residencial, comercial, terreno).

**Ponto de atenção que segue valendo:** cada leiloeiro tem formato próprio — o parsing de Zukerman provavelmente não reaproveita muita coisa da planilha da Caixa; tratar como dois conectores independentes. **[VERIFICAR quando a planilha chegar]:** ela provavelmente cobre os campos de prospecção/triagem, mas os campos mais finos do edital (responsabilidade por dívidas, foro/laudêmio, vaga de garagem) devem seguir vindo do edital individual em PDF de cada imóvel.

---

## 2. Triagem rápida

**Objetivo:** eliminar rapidamente ofertas óbvias de "não vale a pena".

**Tipo de tarefa:** análise (parcialmente automatizável com regras simples + score preliminar).

**Definido — filtros parametrizáveis pelo usuário:**
- Valor mínimo do lance (piso e **teto** — hoje limitado pelo capital disponível)
- Valor de mercado estimado (preferência atual por imóveis "populares"/mais baratos)
- Região de interesse
- Tipo de imóvel

**Método para valor de mercado grosseiro nesta fase [definido]:** hoje não é calculado de cabeça nessa etapa; quando não for possível estimar valor de mercado por comparáveis/registros, usar **R$/m² médio da região** como fallback.

---

## 3. Análise documental

### 3.1 Edital do leilão
**O que extrair (atualizado com checklist):**
- Valor mínimo 1ª praça, 2ª praça (ou praça única) e datas de cada uma
- Comissão do leiloeiro (% e base de cálculo)
- Condições de pagamento (à vista, parcelado, FGTS/financiamento)
- Modalidade do leilão (extrajudicial — marcar no dado para não misturar com judicial)
- **Responsabilidade por dívidas anteriores de condomínio e IPTU** — se ficam com o credor ou passam ao arrematante; se for do arrematante, valor deve alimentar a análise financeira
- **Se o imóvel é foreiro** (terreno de marinha/enfiteuse) — de quem é a responsabilidade pelo foro e laudêmio atrasados **[NOVO — item do checklist que eu não tinha mapeado]**
- Ônus e gravames mencionados no próprio edital
- Existência de ação judicial do devedor contra o credor fiduciário — e o que o edital diz sobre evicção de direitos nesse caso
- **Se o edital inclui vaga(s) de garagem** — verificar se têm matrícula própria ou se estão na mesma matrícula do imóvel **[NOVO]**
- **De quem é a responsabilidade por dar baixa em algum ônus/gravame pendente** **[NOVO]**

### 3.2 Matrícula do imóvel
**O que extrair (atualizado com checklist):**
- Metragem/descrição oficial — **cruzar com a descrição do edital** (checklist item 4.3)
- Vaga de garagem: matrícula própria ou vinculada
- Ônus e gravames
- **Averbação da consolidação da propriedade em nome do credor fiduciário**
- **Registro de que os devedores foram notificados para purgar a mora** — ausência disso é risco de nulidade (ver seção 4)

**Fluxo definido:** o leiloeiro já disponibiliza uma versão inicial da matrícula no edital, mas ela pode estar desatualizada até a data do leilão. Processo:
1. Iniciar a análise com a matrícula do edital.
2. Perto da data do leilão, emitir matrícula atualizada (fonte: **RI Digital — ridigital.org.br**) e comparar com a inicial para identificar mudanças relevantes (novo ônus, nova ação, etc.)

Isso é um **sub-processo de 2 passos** (matrícula inicial → matrícula de confirmação pré-leilão), relevante para o desenho do MVP: o sistema precisa lembrar de re-emitir a matrícula próximo à data do leilão, não só na prospecção.

### 3.3 Processos judiciais
**O que extrair:**
- Processo de execução que originou o leilão
- Ações judiciais do devedor contra o credor fiduciário — andamento e se há trânsito em julgado (se houver, não há mais possibilidade de recurso — reduz o risco)
- Outras ações que possam afetar posse/propriedade (usucapião, disputa de herança)

**Definido:** por ora, **inspeção manual** — automação de consulta a tribunais fica para uma fase futura.

### 3.4 Procedimento do leilão (checklist de conferência — [NOVO bloco, incorporado do checklist pessoal])
Itens de verificação cruzada entre edital, matrícula e prática:
- Registro da alienação fiduciária + averbação da consolidação em nome do credor (exceto se for dação em pagamento)
- Notificação dos devedores para purgar a mora (na matrícula)
- Descrição do imóvel: edital bate com a matrícula?
- Confirmar com o leiloeiro se os devedores foram notificados **das datas dos leilões** — exceto em oportunidades pós-leilão (venda direta / terceiro leilão), onde não há essa obrigatoriedade
- Ocupação do imóvel: checar tanto no edital quanto **na prática** (nem sempre bate)
- Atenção a **contrato de gaveta** como sinal de risco adicional de ocupação/regularização

---

## 4. Análise jurídica

1. **Modalidade e base legal** — Lei 9.514/97 (alienação fiduciária), foco do escopo atual.

2. **Ônus que sobrevivem ao arremate — [confirmado por pesquisa]:** ao contrário do leilão judicial (onde há proteção legal — STJ Tema 1134, out/2024), **no leilão extrajudicial não existe proteção automática contra dívidas de IPTU/condomínio anteriores**. Bate exatamente com o item 2.3/4.5 do seu checklist: é o **edital** que define se essas dívidas ficam com o credor ou vão para o arrematante — e essa é uma variável que muda leilão a leilão, não uma regra fixa. O software deve **extrair essa cláusula específica do edital** (não assumir um padrão) e alimentar a análise financeira de acordo.

3. **Foro e laudêmio (imóvel foreiro) — [NOVO, do checklist]:** mesma lógica do item acima — responsabilidade pelo pagamento de atrasados depende do que o edital define. Precisa virar campo extraído do edital também, não regra fixa.

4. **Purgação da mora / direito de preferência — [confirmado por pesquisa]:** desde a Lei 13.465/2017, não há mais purgação da mora após a consolidação da propriedade — só direito de preferência do antigo devedor para arrematar o próprio imóvel, até o 2º leilão. A ausência de notificação do devedor para purgar a mora (que deve constar na matrícula, conforme seu checklist 3.4) é motivo de nulidade — por isso esse é um item de verificação, não só um dado informativo.

5. **Ocupação e risco de usucapião — [seu maior risco percebido, confirmado]:** você identificou isso como o risco mais crítico (ocupante de longa data reivindicando usucapião), mais do que anulação por vício formal — que você trata como aceitável porque não gera perda financeira, só perda de tempo. Isso é uma informação importante para o **score**: risco de anulação por vício ≠ risco de usucapião no peso da decisão, mesmo que ambos sejam "riscos jurídicos". Vale considerar dois níveis de risco separados no modelo de score, não um único campo "risco jurídico".

6. **Vaga de garagem com matrícula independente — [NOVO, do checklist]:** se a vaga tem matrícula própria e não está incluída no edital, isso é um risco/gap a sinalizar (você pode arrematar o imóvel sem a vaga).

---

## 5. Análise financeira

| # | Item | Status | Observação |
|---|------|--------|------------|
| 1 | Valor mínimo (1ª/2ª praça) | ✅ Resolvido | Extraído do edital |
| 2 | Valor de mercado | ✅ Definido | Comparáveis via **ImovelWeb, VivaReal ou Netimóveis**, filtrando por características do imóvel; fallback: R$/m² médio da região quando faltar comparável |
| 3 | Valor de registro em cartório | ✅ Definido | Tabela de emolumentos MG 2026 (a receber em PDF) — faixas por valor de arrematação |
| 4 | ITBI | **TBD (parcial)** | Sem fonte única de alíquotas; MVP começa com tabela fixa para municípios de interesse imediato e expande manualmente |
| 5 | Comissão do leiloeiro | ✅ Conceito ok | Vem do edital |
| 6a | IPTU em débito | **Depende do edital + consulta manual assistida** | Responsabilidade depende do edital (item 4 da seção jurídica); valor só via site da prefeitura por nº de inscrição — coleta manual guiada por tutorial |
| 6b | Condomínio em débito | **Depende do edital + consulta manual** | Responsabilidade depende do edital; valor só via contato com administradora/síndico |
| 6c | **Foro/laudêmio atrasados** (se foreiro) | **Depende do edital** | Mesma lógica: depende do edital |
| 7 | IPTU mensal atual | **Consulta manual assistida** | Site da prefeitura por nº de inscrição — mesmo fluxo do item 6a |
| 8 | Condomínio mensal atual | **Consulta manual** | Via administradora/síndico |
| 9 | Ocupação/estado de conservação | **TBD** | Checar edital **e** prática (podem divergir) |
| 10 | Comissão do corretor na revenda | ✅ Conceito ok | Parâmetro configurável (ex: 5–6%) |
| 11 | IR sobre ganho de capital | **TBD** | Fórmula fixa (15–22,5% conforme faixa) |
| 12 | **Custo de carregamento (novo item, definido)** | **Definido** | Prazo padrão de **12 meses** entre arremate e revenda (parametrizável), com IPTU + condomínio incidindo nesse período como custo |

**Regra de decisão definida:** margem mínima de lucro esperada = **20%**. Abaixo disso, não participa — independente de outros fatores.

---

## 6. Score / Decisão consolidada

**Regras definidas:**
- Risco jurídico alto = **descarta** (corte binário, não ponderado hoje)
- **Mas:** risco de anulação por vício formal é tratado como **aceitável** (só custa tempo); risco de **usucapião por ocupação de longa data** é o dealbreaker real
- Margem mínima de lucro: **20%**

**Implicação para o modelo de score [a definir juntos]:** o "risco jurídico" não deveria ser um único campo binário — pelo menos dois sub-scores fazem sentido: **risco de nulidade/atraso** (aceitável) vs. **risco de perda de direito sobre o imóvel** (usucapião, ocupação irregular — dealbreaker). Vale formalizar essa distinção antes de desenhar o MVP de score.

---

## 7. Lance / Arremate

**Definido:** você já tem um checklist próprio de preparação para o dia do leilão (lance máximo, forma de pagamento). Anexar/mesclar esse checklist aqui quando disponível — por ora o **checklist geral de leilões extrajudiciais que você enviou** já cobre boa parte da preparação documental (itens 1 a 5), mas pode ter passos operacionais do dia do leilão em si que ainda não capturamos (ex: como você registra o lance, prazo de pagamento após arrematação, etc.) — fica como TBD se você tiver algo além do que já foi documentado aqui.

---

## 8. Pós-arremate (escopo futuro)

Placeholder mantido:
- Pagamento e formalização (carta de arrematação, registro)
- Imissão na posse / desocupação
- Reforma (se necessária)
- Revenda (precificação, anúncio, corretor)

---

## Registro de mudanças

- **v1:** rascunho inicial (contexto, análise financeira, esqueleto jurídico/documental)
- **v2:** pipeline completo com 8 etapas; TBDs de prospecção, triagem, score e financeiro respondidos; correções jurídicas via pesquisa (Tema 1134 do STJ só vale para leilão judicial; purgação da mora pós-2017); checklist pessoal de leilões extrajudiciais incorporado (foro/laudêmio, vaga de garagem com matrícula própria, baixa de ônus, contrato de gaveta, fluxo de matrícula inicial → matrícula de confirmação via RI Digital)

## Itens resolvidos nesta rodada

- **Valor de mercado:** comparáveis via **ImovelWeb, VivaReal ou Netimóveis**, filtrando pelas características do imóvel (tipo, região, metragem). Isso vira mais uma fonte a "raspar" no MVP, junto com Caixa e Zukerman — só que como consulta pontual por imóvel, não como scraping de listagem completa.
- **Tabela de emolumentos de cartório (MG) — recebida e processada:** o PDF é a Tabela 4-2026 do TJMG (Atos do Oficial de Registro de Imóveis). O item mais relevante para o nosso cálculo é o **5-e (Escritura pública, instrumento particular e título judicial, com conteúdo financeiro)**, usado como parâmetro para o registro da consolidação da propriedade em nome do credor fiduciário (conforme NOTA VII da própria tabela) — é essa tabela de faixas que deve alimentar o custo de "registro em cartório" na calculadora:

  | Faixa de valor (R$) | Valor final ao usuário (R$, já com ISSQN) |
  |---|---|
  | até 1.400,00 | 227,95 |
  | 1.400,01 – 2.720,00 | 371,84 |
  | 2.720,01 – 5.440,00 | 538,85 |
  | 5.440,01 – 7.000,00 | 745,98 |
  | 7.000,01 – 14.000,00 | 994,78 |
  | 14.000,01 – 28.000,00 | 1.285,21 |
  | 28.000,01 – 42.000,00 | 1.597,11 |
  | 42.000,01 – 56.000,00 | 1.989,94 |
  | 56.000,01 – 70.000,00 | 2.404,60 |
  | 70.000,01 – 105.000,00 | 3.026,34 |
  | 105.000,01 – 140.000,00 | 3.839,67 |
  | 140.000,01 – 175.000,00 | 4.106,03 |
  | 175.000,01 – 210.000,00 | 4.372,88 |
  | 210.000,01 – 280.000,00 | 4.914,86 |
  | 280.000,01 – 350.000,00 | 5.050,25 |
  | 350.000,01 – 420.000,00 | 5.186,26 |
  | 420.000,01 – 560.000,00 | 5.677,78 |
  | 560.000,01 – 700.000,00 | 5.989,84 |
  | 700.000,01 – 840.000,00 | 6.302,53 |
  | 840.000,01 – 1.120.000,00 | 7.046,73 |
  | 1.120.000,01 – 1.400.000,00 | 7.632,83 |
  | 1.400.000,01 – 1.680.000,00 | 8.219,92 |
  | 1.680.000,01 – 3.200.000,00 | 8.808,22 |
  | 3.200.000,01 – 3.700.000,00 | 13.034,69 |
  | acima de 3.700.000,00 | 13.034,69 + faixas adicionais de R$500.000 (Nota XVII — regra progressiva, tratar como caso especial no MVP já que seus imóveis de interesse são "mais populares") |

  **[VERIFICAR]:** a NOTA VII diz que a base de cálculo é **o valor da avaliação da repartição fazendária** (não necessariamente o valor de arremate). Para o MVP, sugiro usar o valor de arremate como proxy inicial (mais fácil de obter automaticamente), sinalizando que pode haver pequena divergência frente ao valor oficial de avaliação.

- **Alíquotas de ITBI — levantamento inicial para os municípios que você listou:**

  | Município | Alíquota | Fonte |
  |---|---|---|
  | Belo Horizonte | 3% (com isenção para imóvel de baixo valor e faixa reduzida de 1,5% no 1º imóvel) | confirmada, legislação municipal |
  | Contagem | 3% | agregador (a confirmar na prefeitura) |
  | Betim | 3% | agregador (a confirmar na prefeitura) |
  | Sete Lagoas | 2,5% | agregador (a confirmar na prefeitura) |
  | Juatuba | **TBD** | não encontrada em fonte agregada — checar direto na prefeitura |
  | Mateus Leme | **TBD** | idem |
  | Igarapé | **TBD** | idem |
  | Lagoa Santa | **TBD** (site da prefeitura tem o regulamento do ITBI, mas a alíquota específica não veio na busca) | idem |
  | Florestal | **TBD** | idem |
  | Itaúna | **TBD** | idem |

  **Observação:** para os municípios menores, provavelmente vale a pena um passo manual de "levantar 1x e cadastrar na tabela fixa" em vez de tentar automatizar a descoberta — são poucos municípios e a alíquota muda raramente.

- **IPTU/condomínio (débito e mensal):** só é possível consultar no site da prefeitura, via **número de inscrição do imóvel** — não automatizável agora. Plano definido: o MVP fornece um **tutorial guiado** (ex: "acesse tal site, insira a inscrição X, copie o valor Y") e o usuário insere o resultado manualmente no sistema. Isso é uma etapa "assistida", não automatizada — vale marcar como um tipo de tarefa à parte no pipeline (nem coleta automática, nem decisão humana: é *coleta manual guiada*).

## Itens ainda em aberto [TBD]

- Alíquota de ITBI para Juatuba, Mateus Leme, Igarapé, Lagoa Santa, Florestal e Itaúna — checar direto no site de cada prefeitura
- Checklist operacional do dia do leilão (se houver algo além da preparação documental já coberta)
- Número de inscrição do imóvel: de onde vem esse dado — está no edital, na matrícula, ou precisa ser buscado separadamente na prefeitura?

## Próximos passos sugeridos

Com o processo bem mais fechado agora, o próximo passo natural é desenhar o **MVP 1**: scraping + parsing de edital da **Caixa e Zukerman**, extraindo os campos já mapeados (praças, valores, responsabilidade por dívidas, foro/laudêmio, vaga de garagem) + calculadora financeira com os parâmetros definidos (margem mínima 20%, prazo de carregamento 12 meses). Quer que eu já esboce esse MVP (escopo, campos de dados, arquitetura de alto nível)?