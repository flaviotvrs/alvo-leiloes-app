# Roadmap de MVPs — Alvo Leilões
> **Projeto: Alvo Leilões**

> Documentação de projeto. Complementa `processo-alvo-leiloes.md` (modelo do processo), `mvp1-alvo-leiloes.md` (spec do MVP 1) e `interface-agentes.md` (contrato extrator ↔ juiz).

---

## MVP 1 — Pipeline financeiro determinístico (em implementação)

**Escopo:** ingestão de imóveis (planilha da Caixa + scraping Zukerman) + calculadora de viabilidade financeira automática, com as tabelas de emolumentos MG e ITBI já levantadas. Inputs sem automação viável (valor de mercado, IPTU, condomínio) ficam como coleta manual guiada.

**Fora de escopo, propositalmente:** matrícula, processos judiciais, checklist jurídico, score consolidado, checklist do dia do leilão, pós-arremate.

**Por que primeiro:** é a base determinística de que tudo depois depende (o agente juiz consome o resultado dessa calculadora como uma das entradas) e gera valor imediato mesmo sem nenhuma automação de agentes.

---

## MVP 2 — Agente de valor de mercado

**Escopo:** agente que busca e agrega comparáveis de mercado (ImovelWeb, VivaReal, Netimóveis) por região/tipo/metragem, substituindo o input manual de valor de mercado da calculadora do MVP 1.

**Por que antes da matrícula:** melhora a **triagem**, que roda sobre todo imóvel candidato — não só os que sobrevivem até a análise documental. É alavancagem maior por unidade de esforço do que investir primeiro na matrícula, que só entra depois que um imóvel já passou no corte financeiro. Reordenação feita depois do MVP 1 estar em implementação, com esse racional validado.

**Detalhes completos:** `mvp2-alvo-leiloes.md`

---

## MVP 3 — Agente de matrícula (extração documental)

**Escopo:** automatizar a leitura da matrícula do imóvel (formatos variados, muitas vezes PDF-imagem) — agente extrator com visão, seguindo o catálogo de campos já esboçado (ônus/gravames, averbação de consolidação, notificação de purgação de mora, indícios de usucapião/ocupação, etc.). Inclui a infraestrutura de fila/orquestração de agentes (`arquitetura-tecnica.md` §2), que também serve de base para o MVP 2.

**Fora de escopo nesta fase:** débitos de prefeitura (IPTU) como agente de navegação genérico — com apenas 10 municípios de interesse mapeados, scrapers pontuais por município tendem a compensar mais que um agente genérico; condomínio e processos judiciais seguem manuais.

**O que permanece determinístico, não vira agente:** a calculadora financeira em si, e qualquer fonte já estruturada (planilha da Caixa, editais com template fixo por leiloeiro).

**Pré-requisito prático:** matrículas e editais reais gerados pelo uso do MVP 1, para validar/ajustar o catálogo de campos do agente extrator de matrícula — não é algo pra desenhar no vácuo.

**Detalhes completos:** `mvp3-alvo-leiloes.md`

---

## MVP 4 — Agente juiz / decisão consolidada

**Escopo:** consumir o resultado da calculadora financeira (MVP 1) + as extrações estruturadas dos agentes (MVP 2 e MVP 3), aplicar as regras de decisão do usuário (margem mínima 20%, risco jurídico dealbreaker = usucapião, riscos aceitáveis = anulação por vício formal) e devolver um veredito: `aprovado` / `reprovado` / `revisão humana necessária`.

**Contrato de dados já definido** em `interface-agentes.md` — envelope comum de extrator, entrada e saída do juiz.

**Observação de implementação:** o agente juiz pode começar como função determinística simples aplicando essas regras sobre o JSON estruturado — só evolui para agente de fato (LLM) se a lógica de ponderação ficar complexa demais para regras explícitas.

---

## Fora de escopo em todos os MVPs acima (retomar depois)

- Pós-arremate (pagamento/formalização, imissão na posse, reforma, revenda)
- Checklist operacional do dia do leilão (lance máximo, forma de pagamento)
- Expansão de fontes de leilão além de Caixa e Zukerman

---

## Nota de arquitetura para o MVP 1

Ao desenhar o modelo de dados do MVP 1, manter um identificador estável de imóvel (`imovel_id`) desde já — os MVPs seguintes vão acumular resultados de múltiplos agentes/fontes ligados a esse mesmo identificador, e evitar recriá-lo a cada importação facilita a integração futura.