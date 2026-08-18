# Arquitetura Técnica — Alvo Leilões
> **Projeto: Alvo Leilões**

> Complementa `roadmap-mvps.md` e `interface-agentes.md`. Este documento registra a arquitetura em camadas do sistema (determinístico + agentes extratores + agente juiz) e o desenho de fila/orquestração dos agentes.

---

## 1. Visão geral em camadas

```
                    ┌───────────────────────────────┐
                    │        Fontes externas         │
                    │ Editais, matrícula, débitos,   │
                    │ mercado                        │
                    └───────────┬─────────┬──────────┘
                                │         │
                 ┌──────────────▼──┐   ┌──▼───────────────┐
                 │ Importador Caixa │   │ Scraper Zukerman  │
                 │ Planilha, sem     │   │ Parsing de site   │
                 │ scraping          │   │                   │
                 └──────────┬────────┘   └────────┬──────────┘
                            └──────────┬───────────┘
                                       ▼
                        ┌───────────────────────────┐
                        │      Banco de dados         │
                        │ Imovel · Edital ·           │
                        │ AnaliseFinanceira            │
                        └──────────┬───────┬───────────┘
                                   │       │
                ┌──────────────────▼─┐   ┌─▼────────────────────────┐
                │ Calculadora          │   │ Agentes extratores (IA)  │
                │ financeira           │   │ Fontes não padronizadas  │
                │ Regras + tabelas fixas│  │                          │
                └──────────┬───────────┘   └─────────┬────────────────┘
                           └───────────┬──────────────┘
                                       ▼
                            ┌───────────────────────┐
                            │      Agente juiz         │
                            │ Aplica regras do usuário │
                            └───────────┬───────────────┘
                                        ▼
                            ┌───────────────────────────────┐
                            │      Interface do usuário       │
                            │ Aprovado · Reprovado ·          │
                            │ Revisão humana                  │
                            └───────────────────────────────┘
```

**Camadas (cor no diagrama original):**
- **Cinza (bordas do sistema):** fontes externas e interface do usuário.
- **Azul (100% determinístico):** ingestão (importador Caixa, scraper Zukerman), banco de dados, calculadora financeira. É exatamente o escopo do **MVP 1**, roda ponta a ponta sem depender de nenhuma camada de IA.
- **Roxo (agentes extratores de IA):** camada que resolve fontes não padronizadas — começando pelo agente de valor de mercado (**MVP 2**), depois o agente de matrícula (**MVP 3**).
- **Coral (agente juiz):** consolida o resultado da calculadora + os dados extraídos pelos agentes, aplica as regras do usuário (margem mínima 20%, riscos dealbreaker) e decide. Escopo do **MVP 3**. Pode nascer como função determinística simples e só evoluir para agente de IA se a lógica de ponderação ficar complexa demais para regras explícitas.

**Princípio de integração:** não há chamada direta entre a camada de agentes extratores e a calculadora financeira — toda comunicação passa pelo **banco de dados**, amarrada pelo `imovel_id`. Isso permite que os agentes rodem de forma assíncrona (tempos de execução muito diferentes entre si) sem travar o restante do pipeline, e é o que torna possível ligar a camada de agentes depois, sem refatorar o que já estiver pronto no MVP 1.

---

## 2. Fila e orquestração dos agentes extratores

Os agentes extratores (matrícula, débitos de prefeitura, e futuramente mercado) não devem ser chamados de forma síncrona e bloqueante — os tempos de execução variam muito entre eles (ler uma matrícula com bom scan é rápido; navegar um site de prefeitura pode falhar e precisar de nova tentativa). O desenho abaixo trata cada extração como um **job assíncrono em fila**.

### 2.1 Modelo de job

```json
{
  "job_id": "uuid",
  "imovel_id": "caixa-12345",
  "agente_tipo": "matricula-extractor",
  "status": "pendente",
  "prioridade": "normal",
  "tentativas": 0,
  "max_tentativas": 3,
  "input_ref": { "tipo": "pdf", "referencia": "s3://.../matricula_12345.pdf" },
  "criado_em": "2026-08-14T18:00:00Z",
  "iniciado_em": null,
  "finalizado_em": null,
  "resultado": null,
  "erro": null
}
```

**Estados possíveis:** `pendente` → `em_execucao` → `concluido` | `falhou` | `requer_revisao`.

`requer_revisao` aqui é diferente do veredito `revisao_humana_necessaria` do agente juiz (seção 4 de `interface-agentes.md`) — este é sobre a **execução do job em si** ter falhado de um jeito que não vale reprocessar automaticamente (ex: arquivo corrompido, site fora do ar por tempo demais). O agente juiz nunca vê um job nesse estado sem contexto — ele recebe a ausência do dado como "campo não encontrado", que já é tratado no envelope de extração.

### 2.2 Fila: Postgres antes de infraestrutura dedicada

Para a escala do projeto (uso pessoal, dezenas de imóveis por vez, não milhares simultâneos), uma **tabela de jobs no próprio Postgres**, com um worker que faz polling, é suficiente e evita adicionar Redis/SQS/Celery antes de precisar:

- Worker consulta jobs com `status = 'pendente'` (com `SELECT ... FOR UPDATE SKIP LOCKED` para evitar dois workers pegarem o mesmo job)
- Marca como `em_execucao`, processa, grava resultado, atualiza status
- Se falhar: incrementa `tentativas`; se `tentativas < max_tentativas`, volta pra `pendente` com backoff (ex: 2ⁿ minutos); se estourar o limite, vira `falhou`

**Quando migrar para algo mais robusto (Celery+Redis, ou AWS SQS, já que você tem familiaridade com AWS):** se o volume crescer a ponto de precisar de múltiplos workers concorrentes de verdade, prioridade dinâmica entre filas, ou processamento distribuído entre máquinas. Não é o caso do MVP 2 — vale começar simples e só trocar quando a tabela de jobs no Postgres virar gargalo mensurável.

### 2.3 Concorrência e limites por fonte

Cada tipo de agente tem uma restrição prática diferente:

- **`matricula-extractor`**: geralmente limitado pelo custo/rate-limit da API de visão usada (não pelo site de terceiros) — pode processar vários jobs em paralelo, dentro do limite da API.
- **`prefeitura-debitos-extractor`**: precisa de **limite de concorrência por município/domínio** — navegar de forma agressiva no site de uma prefeitura pequena pode disparar bloqueio por excesso de requisições. Um worker por domínio, com um pequeno intervalo entre requisições ao mesmo site, evita esse problema.

### 2.4 Idempotência e versionamento

Reprocessar o mesmo `imovel_id` + `agente_tipo` (ex: você pede pra re-emitir a matrícula perto da data do leilão, como já definimos no processo) não deve sobrescrever o resultado anterior sem rastro — o mesmo princípio de **`AnaliseFinanceira` versionável** que já está no modelo de dados do MVP 1 se aplica aqui: cada execução gera um novo registro de resultado, ligado ao mesmo `imovel_id`, permitindo comparar "o que mudou entre a matrícula do edital e a matrícula atualizada".

### 2.5 Observabilidade mínima

Vale acompanhar desde o início, mesmo que de forma simples (uma query, não precisa de dashboard):
- Tempo médio de execução por tipo de agente
- Taxa de falha por tipo de agente e por fonte (ex: site de qual prefeitura falha mais)
- Quantos jobs estão em `requer_revisao` esperando ação manual

Isso é o que vai indicar, na prática, quando vale investir em infraestrutura de fila mais robusta (seção 2.2) — não uma decisão a priori.

---

## Registro de mudanças

- Documento criado a partir da discussão de arquitetura técnica (diagrama em camadas + desenho de fila/orquestração dos agentes extratores).