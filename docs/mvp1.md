# MVP 1 — Alvo Leilões

> Baseado em `docs/processo-alvo-leiloes.md`. Este documento é o corte de escopo do primeiro incremento entregável.

---

## 1. Objetivo do MVP 1

Substituir a parte hoje mais manual e repetitiva do seu processo — **abrir edital por edital da Caixa e da Zukerman, extrair os números e rodar a calculadora de viabilidade** — por um fluxo onde você entra com um imóvel/edital e sai com **um veredito financeiro pronto** (margem, viável ou não pelos seus critérios de 20%), com o mínimo de digitação manual possível.

**Não é objetivo do MVP 1:** análise jurídica automatizada, score de risco, matrícula, ou decisão consolidada. Isso é matéria de MVPs seguintes — aqui o foco é **dinheiro**: "esse imóvel dá lucro de pelo menos 20% ou não?".

---

## 2. Escopo

### Dentro do MVP 1
1. **Ingestão de imóveis — Caixa (via planilha) e Zukerman (via scraping)**
   - Caixa disponibiliza uma **planilha com todos os imóveis em leilão** — para essa fonte, o MVP 1 não precisa de scraper: basta um **importador de planilha** (ler o arquivo, mapear colunas para o modelo `Edital`/`Imovel`). Isso reduz drasticamente o esforço de engenharia da fonte Caixa.
   - Zukerman segue precisando de scraping/parsing de site, já que não há planilha equivalente conhecida até agora.
   - Extração automática dos campos financeiros relevantes de cada fonte (ver modelo de dados)
   - **[VERIFICAR]:** a planilha da Caixa provavelmente cobre bem os campos de **prospecção/triagem** (endereço, tipo, valores de praça, datas) — mas os campos mais "finos" do edital (responsabilidade por dívidas de condomínio/IPTU, foro e laudêmio, vaga de garagem com matrícula própria) normalmente só aparecem no **edital individual** de cada imóvel, não na planilha-lista. Precisamos confirmar quando você tiver a planilha em mãos: se for só a lista, o fluxo vira "planilha para prospecção + abrir o edital individual (PDF) só dos imóveis que passarem na triagem" — o que ainda é uma baita economia de esforço, já que você deixa de abrir edital de imóvel que nem passaria no filtro.
2. **Filtros de triagem parametrizáveis**
   - Região, tipo de imóvel, faixa de valor mínimo (piso/teto)
3. **Calculadora de viabilidade automática**, aplicando:
   - Valor mínimo de arremate (do edital)
   - Comissão do leiloeiro (do edital)
   - Emolumentos de cartório MG (tabela fixa 2026, a partir do seu PDF)
   - ITBI (tabela fixa inicial — municípios de interesse imediato)
   - Comissão do corretor na revenda (parametrizável, default 5–6%)
   - IR sobre ganho de capital (fórmula fixa)
   - Custo de carregamento: IPTU + condomínio mensal × prazo parametrizável (default 12 meses)
   - Margem mínima de corte: 20% (parametrizável)
4. **Inputs manuais assistidos** (o sistema pede, você preenche, mas guiado):
   - Valor de mercado — você cola um link ou valor de referência do ImovelWeb/VivaReal/Netimóveis (comparáveis), ou usa o fallback R$/m² se preferir
   - IPTU/condomínio mensal e em débito — tela com tutorial ("acesse [link da prefeitura], busque pela inscrição X, informe o valor") + campo para você digitar o resultado
5. **Resultado:** por imóvel, um resumo com todos os custos, valor de mercado, margem líquida estimada em % e R$, e um "viável / não viável" segundo o corte de 20%

### Fora do MVP 1 (fica para depois)
- Matrícula (extração, comparação inicial x atualizada via RI Digital)
- Processos judiciais
- Checklist jurídico (edital x matrícula, notificação de devedores, usucapião etc.)
- Score consolidado (financeiro + jurídico)
- Checklist operacional do dia do leilão
- Pós-arremate

---

## 3. Modelo de dados (rascunho)

**Imovel**
- fonte (`caixa` | `zukerman`)
- id_externo / url do edital
- tipo (residencial | comercial | terreno)
- endereço, cidade, região
- metragem
- descrição do edital

**Edital**
- data_1a_praca, valor_1a_praca
- data_2a_praca, valor_2a_praca (ou praça única)
- comissao_leiloeiro (%)
- responsabilidade_divida_iptu (`credor` | `arrematante` | `não informado`)
- responsabilidade_divida_condominio (`credor` | `arrematante` | `não informado`)
- imovel_foreiro (bool) + responsabilidade_foro_laudemio
- condicoes_pagamento (texto/enum)
- possui_vaga_garagem_separada (bool) — sinalizador, sem tratamento financeiro no MVP 1

**AnaliseFinanceira** (por imóvel, versionável — você pode rodar de novo se atualizar um input manual)
- valor_mercado (input manual ou fallback R$/m²)
- fonte_valor_mercado
- valor_registro_cartorio (calculado via tabela)
- valor_itbi (calculado via tabela)
- iptu_debito, condominio_debito (manuais, condicionados à responsabilidade do edital)
- iptu_mensal, condominio_mensal (manuais)
- meses_carregamento (default 12, parametrizável)
- comissao_corretor_revenda (% parametrizável)
- ir_ganho_capital (calculado)
- margem_liquida_pct, margem_liquida_valor (calculado)
- margem_minima_corte (default 20%, parametrizável)
- resultado (`viável` | `não viável`)

**TabelaEmolumentosMG** (estática, carregada do PDF fornecido — Tabela 4-2026 TJMG, item 5-e) — faixas de valor → emolumento (tabela completa em `processo-radar-de-leiloes.md`)
**TabelaITBI** (estática, por município) — confirmada para Belo Horizonte (3%, com isenções), Contagem (3%), Betim (3%) e Sete Lagoas (2,5%); ainda faltam Juatuba, Mateus Leme, Igarapé, Lagoa Santa, Florestal e Itaúna — a levantar manualmente direto nos sites das prefeituras

---

## 4. Fluxo de uso (usuário)

1. Você importa a planilha da Caixa (upload manual, sem agendamento) e/ou o sistema roda o scraping da Zukerman sob demanda → lista de imóveis novos
2. Você aplica filtros (região, tipo, faixa de valor) → lista reduzida
3. Você abre um imóvel → sistema já mostra os campos extraídos do edital
4. Sistema pede os inputs manuais assistidos (valor de mercado, IPTU/condomínio) com o tutorial de onde buscar
5. Você preenche → sistema calcula automaticamente e mostra o veredito (margem % e viável/não viável)
6. Você decide se avança para análise jurídica (manual, fora do MVP 1) ou descarta

---

## 5. Arquitetura de alto nível (proposta)

```
[Importador de Planilha Caixa]  [Scraper Zukerman]
              \                       /
               v                     v
              [Normalizador] → mapeia ambas para o modelo Edital/Imovel
                        |
                        v
                [Banco de dados] (imóveis, editais, análises)
                        |
                        v
                [API/Backend] → regras de cálculo (tabelas fixas + fórmulas)
                        |
                        v
                [Interface] → lista de imóveis, filtros, tela de input assistido, resultado
```

**Sugestão pragmática para não travar em engenharia:** o importador de planilha da Caixa e o scraper da Zukerman são bem mais simples de construir separadamente do que tentar generalizar — a planilha, em particular, é essencialmente leitura de arquivo (bem mais rápido de entregar que scraping), então faz sentido priorizá-la como primeira fonte a funcionar ponta a ponta no MVP.

---

## 6. Critérios de sucesso do MVP 1

- Você consegue rodar a análise de um imóvel novo da Caixa ou Zukerman em muito menos tempo do que hoje (o benchmark é: quanto tempo leva hoje, manualmente, do edital até saber a margem?)
- O número de campos que você ainda precisa digitar manualmente é pequeno e claramente sinalizado (valor de mercado, IPTU, condomínio)
- O veredito de viabilidade bate com o que você calcularia manualmente hoje

---

## 7. Decisões fechadas

1. **Tabela de emolumentos MG:** recebida (Tabela 4-2026 TJMG) e incorporada — item 5-e da tabela é a referência para o registro da consolidação/arrematação.
2. **Municípios ITBI v1:** Belo Horizonte, Contagem, Betim, Juatuba, Mateus Leme, Igarapé, Lagoa Santa, Sete Lagoas, Florestal, Itaúna. Alíquota já confirmada para 4 deles (BH, Contagem, Betim, Sete Lagoas) — os outros 6 ficam como tarefa de levantamento manual antes do lançamento do MVP (não bloqueiam o desenvolvimento, só o cadastro de dados).
3. **Frequência do scraping:** sob demanda, na v1 (sem agendamento automático por enquanto).
4. **Stack técnica:** em aberto para escolher pela agilidade de desenvolvimento, não pelo que você já conhece. **Proposta:** Python para os scrapers/parsers de edital (ecossistema mais maduro para scraping e parsing de PDF/HTML) + um backend simples (pode ser o próprio Python, evitando polyglot desnecessário num MVP sob demanda sem agendamento) + banco Postgres (você já tem familiaridade via AWS) + frontend simples (uma SPA leve ou até uma planilha/Streamlit para a v1, já que é uso pessoal, não multiusuário). Isso evita over-engineering: dá pra sempre migrar partes para Java/Spring depois se o projeto crescer e precisar de mais robustez.
