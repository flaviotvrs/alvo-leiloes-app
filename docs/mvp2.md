# MVP 2 — Alvo Leilões

> **Projeto: Alvo Leilões**

> Baseado em `processo-alvo-leiloes.md`, `roadmap-mvps.md` e `interface-agentes.md`. Segundo incremento — primeiro agente extrator de fato implementado, escolhido por alavancar a **triagem** (roda sobre todo imóvel candidato, não só os que avançam pra análise documental).

---

## 1. Objetivo do MVP 2

Substituir o input manual de **valor de mercado** da calculadora do MVP 1 por um agente que busca e agrega comparáveis reais (ImovelWeb, VivaReal, Netimóveis), filtrando por características do imóvel (tipo, região, metragem). Isso melhora a precisão da triagem financeira logo na entrada do funil, antes de qualquer investimento em análise documental/jurídica.

**Por que este é o MVP 2 e não a matrícula:** a matrícula só importa pros imóveis que já passaram no corte financeiro — o agente de mercado atua uma etapa antes, sobre *todo* imóvel candidato. Mais alavancagem por unidade de esforço nesta fase do projeto.

**Não é objetivo do MVP 2:** análise jurídica, matrícula, ou decisão consolidada (agente juiz). Continua sendo só a calculadora financeira, agora com um input a menos pra você preencher manualmente.

---

## 2. Por que isso também é um agente, não um scraper simples

Diferente da planilha da Caixa (dado estruturado), estimar valor de mercado envolve julgamento, não só extração:
- Buscar em 3 fontes diferentes, cada uma com layout próprio
- Decidir quais anúncios são **comparáveis de verdade** (região, metragem, tipo — e possivelmente estado de conservação, que nem sempre está claro no anúncio)
- Lidar com **regiões de baixa liquidez**, onde pode haver poucos ou nenhum comparável direto — aí entra o fallback de R$/m² médio da região que já tínhamos definido no processo
- Agregar isso num valor único com algum grau de confiança, não só devolver uma lista de links

Segue o mesmo contrato de dados que já definimos em `interface-agentes.md` — o agente `mercado-extractor` devolve um envelope com `campos`, `confiança` e `evidência`, igual aos outros agentes extratores.

**Decisão de escopo — input vem do edital, não da matrícula:** ler a matrícula certamente ajudaria a refinar as características do imóvel usadas na busca de comparáveis, mas isso criaria uma dependência do MVP 3 antes mesmo dele existir. Para começar, o agente usa só as características que já vêm do **edital** (metragem, quartos, vagas de garagem, tipo). Editais nem sempre especificam tudo — quando um campo característico não vem informado, isso **não bloqueia a busca**, mas **reduz a confiança do resultado** e fica sinalizado explicitamente no envelope (ver `campos_edital_ausentes` no modelo de dados abaixo). Isso é consistente com o princípio que já vínhamos seguindo: o agente sinaliza incerteza em vez de fingir precisão que não tem.

**Dependência a resolver no MVP 1/parser de edital:** o modelo `Edital` do MVP 1 hoje só tem `metragem` explicitamente listada — vale confirmar se o parser (Caixa/Zukerman) também consegue extrair **quartos** e **vagas de garagem** quando o edital informar. Se não vier desses campos, é uma extensão pequena e não-destrutiva do modelo de dados do MVP 1 (campos novos, opcionais), não uma revisão do que já está pronto.

---

## 3. Escopo

### Dentro do MVP 2
1. **Agente `mercado-extractor`** — dado um imóvel com as características **vindas do edital** (tipo, região, metragem, quartos, vagas de garagem — quando informados), busca comparáveis nas 3 fontes e devolve:
   - `valor_m2_estimado`
   - `valor_total_estimado`
   - `comparaveis` (lista: fonte, link, valor, metragem — a evidência do envelope)
   - `metodo` (`comparaveis_diretos` | `fallback_m2_regiao`) — sinaliza quando teve que cair no fallback por falta de comparáveis
   - `campos_edital_ausentes` (lista, ex: `["quartos", "vagas_garagem"]`) — quais características não vieram do edital e por isso a busca foi feita com menos precisão
   - `confianca` — reduzida proporcionalmente à quantidade/importância dos campos ausentes, não só pela quantidade de comparáveis encontrados
2. **Infraestrutura de fila/orquestração** — implementar agora o desenho de `arquitetura-tecnica.md` §2 (tabela de jobs no Postgres, worker com retry/backoff), já que este é o primeiro agente de fato do projeto. Essa infra é reaproveitada integralmente pelo MVP 3 (matrícula).
3. **Integração com a calculadora do MVP 1** — o resultado do agente populariza automaticamente o campo `valor_mercado` da `AnaliseFinanceira`, mas mantendo a opção de **você sobrescrever manualmente** se discordar (o agente sugere, não trava).

### Fora de escopo
- Matrícula, processos judiciais, IPTU (seguem como estavam)
- Agente juiz
- Qualquer lógica de negociação/precificação de revenda — isso é só para a etapa de triagem/viabilidade de compra

---

## 4. Modelo de dados (incremento sobre o MVP 1)

Reaproveita as tabelas já desenhadas para agentes extratores (`arquitetura-tecnica.md` §2.1 e `interface-agentes.md` §1):

**ExtractionJob** (`agente_tipo = 'mercado-extractor'`) — mesmo schema já definido.

**ExtractionEnvelope** — campos específicos do `mercado-extractor`, a acrescentar no catálogo do `interface-agentes.md`:
`valor_m2_estimado`, `valor_total_estimado`, `comparaveis` (lista), `metodo`, `campos_edital_ausentes` (lista), `regiao_baixa_liquidez` (bool, true quando caiu no fallback)

**Configuração (parametrizável, não fixa no código):** `min_comparaveis_confianca_alta` (default: 3)

---

## 5. Fluxo de uso

1. Imóvel passa pela ingestão do MVP 1 (Caixa/Zukerman) e entra na triagem.
2. Você filtra por região e lance inicial (os filtros de triagem já definidos no MVP 1) e identifica um imóvel de interesse.
3. Você aciona manualmente a busca de valor de mercado para aquele imóvel (ação deliberada, não automática — mantém o custo de uso do agente sob controle) → cria um job `mercado-extractor`.
4. Worker processa (agente de navegação sobre ImovelWeb/VivaReal/Netimóveis), grava o `ExtractionEnvelope`.
5. Calculadora do MVP 1 usa `valor_total_estimado` automaticamente; você vê o valor sugerido + os comparáveis que sustentam ele (evidência) e pode ajustar se discordar.
6. Imóveis em região de baixa liquidez (`regiao_baixa_liquidez: true`) ficam sinalizados — o valor ainda é calculado (via fallback R$/m²), mas com confiança mais baixa, pra você saber que aquele número merece mais cautela.

---

## 6. Critérios de sucesso

- O valor estimado pelo agente fica razoavelmente próximo do que você estimaria manualmente, numa amostra de imóveis que você já conhece bem.
- A triagem fica mais rápida — menos imóveis "esperando" você preencher valor de mercado manualmente antes de saber se vale seguir olhando.
- Os comparáveis mostrados são realmente comparáveis (não, por exemplo, um imóvel de tipo ou região muito diferente) — esse é o ponto onde o agente mais provavelmente vai errar no início, vale revisar de perto nas primeiras rodadas.
- Quando o edital vem incompleto (sem quartos/vagas, por exemplo), isso fica visível no `campos_edital_ausentes` e reflete numa confiança mais baixa — não numa estimativa "normal" que esconde a limitação.

---

## 7. Decisões fechadas

1. **Anti-scraping nos 3 portais:** confirmado — nenhum permite scraping direto. O `mercado-extractor` será um **agente de navegação** (mesma categoria de solução que cogitamos pra prefeituras), não um scraper de HTML. Isso reforça o "IA" do nome do agente — não é opcional, é a única forma viável de acessar essas fontes.
2. **Mínimo de comparáveis para confiança alta:** **3**, mas **parametrizável** (não fixo no código) — dá pra ajustar depois com base na experiência real, sem precisar mexer em lógica, só em configuração.
3. **Disparo da busca:** **manual, por ação do usuário no imóvel de interesse** — não roda automaticamente pra todo imóvel que entra na triagem. Isso é uma mudança importante em relação ao fluxo de uso original (seção 5 abaixo, que precisa ser corrigida): você só aciona o agente depois de já ter filtrado por região e lance inicial, mantendo o consumo de tokens do agente controlado. Esse padrão de "ação deliberada por ter custo" é o mesmo princípio que já usamos pra emissão de matrícula via RI Digital (MVP 3) — vale manter consistente nos dois lugares.