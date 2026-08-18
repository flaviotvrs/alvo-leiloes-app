# Interface Agentes Extratores ↔ Agente Juiz
> **Projeto: Alvo Leilões**

> Rascunho inicial de contrato de dados. Pensado pra ser JSON simples, fácil de versionar e testar contra casos reais assim que o MVP 1 (determinístico) estiver rodando.

---

## Princípio de design

Dois papéis bem separados:

- **Agente extrator** (um por fonte não-padronizada: matrícula, débitos de prefeitura, processos judiciais...): transforma fonte não-estruturada em **dados estruturados + confiança + evidência**. Nunca decide "aprova ou reprova" — só relata o que encontrou e o quanto confia naquilo.
- **Agente juiz**: consome os dados estruturados de todos os extratores + o resultado da calculadora financeira (determinística, já existe no MVP 1) + as suas regras de decisão, e produz um veredito. **Decide sozinho só quando o sinal é inequívoco**; caso contrário, escala pra você.

---

## 1. Envelope comum — saída de qualquer agente extrator

```json
{
  "agente": "matricula-extractor",
  "versao_agente": "0.1.0",
  "imovel_id": "caixa-12345",
  "fonte": {
    "tipo": "pdf_escaneado",
    "referencia": "s3://.../matricula_12345.pdf",
    "paginas_analisadas": [1, 2, 3]
  },
  "extraido_em": "2026-08-14T18:00:00Z",
  "campos": [
    {
      "campo": "averbacao_consolidacao_propriedade",
      "valor": true,
      "confianca": 0.93,
      "evidencia": "Av.7: consolidação da propriedade em nome de [credor] em 12/03/2025, conforme art. 26 §7º Lei 9.514/97.",
      "requer_revisao_humana": false
    },
    {
      "campo": "notificacao_purgacao_mora",
      "valor": null,
      "confianca": 0.35,
      "evidencia": "Não foi possível localizar averbação explícita de notificação nas páginas fornecidas.",
      "requer_revisao_humana": true
    }
  ],
  "campos_nao_encontrados": ["laudemio_valor"],
  "observacoes_agente": "Qualidade do scan baixa na página 3 — trecho de ônus parcialmente ilegível."
}
```

**Regras do envelope:**
- `valor: null` + `confianca` baixa é diferente de "campo não encontrado" — significa que o agente tentou, achou algo ambíguo, e está sinalizando isso explicitamente (não é a mesma coisa que silêncio).
- `evidencia` é sempre um trecho curto da fonte, não uma reafirmação do agente — é o que permite você conferir em 10 segundos sem reabrir o PDF inteiro.
- `requer_revisao_humana` é decidido pelo próprio agente extrator com base num limiar de confiança por campo (campos "dealbreaker" como usucapião/ocupação devem ter limiar mais alto que campos informativos).

---

## 2. Catálogo de campos por agente (ponto de partida)

### `matricula-extractor`
`metragem`, `descricao_bate_com_edital`, `onus_gravames` (lista), `averbacao_consolidacao_propriedade`, `notificacao_purgacao_mora`, `vaga_garagem_matricula_propria`, `indicios_usucapiao_ou_ocupacao_longa`, `data_contrato_original` (relevante pro ponto do Tema 1288/regra pré-2017 que já mapeamos)

### `mercado-extractor`
`valor_m2_estimado`, `valor_total_estimado`, `comparaveis` (lista: fonte, link, valor, metragem), `metodo` (`comparaveis_diretos` | `fallback_m2_regiao`), `campos_edital_ausentes` (lista — características do edital que faltaram, ex: quartos/vagas, e por isso reduziram a confiança), `regiao_baixa_liquidez` (bool)

### `prefeitura-debitos-extractor`
`municipio`, `inscricao_imovel`, `iptu_debito_valor`, `iptu_mensal_valor`, `condominio_debito_valor` (raramente disponível — normalmente fica marcado como não encontrado, já que depende de síndico/administradora)

### `processos-judiciais-extractor` (fase futura)
`processo_execucao_numero`, `acoes_devedor_contra_credor` (lista), `transito_em_julgado` (bool), `risco_evicao_mencionado_no_edital`

---

## 3. Entrada do agente juiz

```json
{
  "imovel_id": "caixa-12345",
  "analise_financeira": {
    "margem_pct": 24.3,
    "margem_valor": 61200.00,
    "resultado": "viavel",
    "fonte": "calculadora-mvp1"
  },
  "extracoes": [
    { "...envelope do matricula-extractor..." },
    { "...envelope do prefeitura-debitos-extractor..." }
  ],
  "regras_usuario": {
    "margem_minima_pct": 20,
    "riscos_dealbreaker": ["indicios_usucapiao_ou_ocupacao_longa"],
    "riscos_aceitaveis": ["anulacao_por_vicio_formal", "notificacao_purgacao_mora_ausente"],
    "limiar_confianca_minimo": 0.7
  }
}
```

A calculadora financeira entra como **mais uma fonte de dado estruturado**, não como algo especial — o juiz trata `analise_financeira.resultado` como um sinal a mais junto com os riscos jurídicos, mas segue a regra dura que você já definiu: margem abaixo do mínimo descarta, independente do resto.

---

## 4. Saída do agente juiz

```json
{
  "imovel_id": "caixa-12345",
  "veredito": "revisao_humana_necessaria",
  "motivo_principal": "Campo dealbreaker 'indícios de usucapião' não pôde ser confirmado com confiança suficiente na matrícula.",
  "riscos_identificados": [
    {
      "campo": "notificacao_purgacao_mora",
      "confianca": 0.35,
      "classificacao": "risco_aceitavel_mas_incerto",
      "evidencia": "Não foi possível localizar averbação explícita nas páginas fornecidas."
    }
  ],
  "campos_pendentes_revisao": ["notificacao_purgacao_mora", "laudemio_valor"],
  "resumo_para_usuario": "Margem financeira de 24,3% (acima do mínimo de 20%). Não encontrei indícios claros de usucapião na matrícula, mas a notificação de purgação de mora não pôde ser confirmada — vale seu olhar antes de decidir."
}
```

**Três veredictos possíveis, não dois:**
- `aprovado` — margem ok e nenhum risco dealbreaker com confiança relevante
- `reprovado` — margem abaixo do mínimo, ou risco dealbreaker confirmado com alta confiança
- `revisao_humana_necessaria` — quando algum campo crítico ficou abaixo do `limiar_confianca_minimo`. Esse terceiro estado é o que evita o agente juiz "forçar" uma decisão binária em cima de dado incerto — e é especialmente importante pro seu caso, já que o risco que mais te preocupa (usucapião) é justamente o mais difícil de confirmar com certeza a partir de uma matrícula.

---

## Próximos passos quando for implementar

1. Validar o catálogo de campos do `matricula-extractor` contra 3–5 matrículas reais assim que tiver exemplos (formatos variam muito, o catálogo provavelmente vai precisar de ajuste).
2. Definir o `limiar_confianca_minimo` por campo, não um valor único global — "notificação de purgação de mora" e "indícios de usucapião" provavelmente merecem limiares mais altos que "metragem", por exemplo.
3. O agente juiz pode começar como uma função determinística simples (não precisa ser LLM) aplicando as regras acima sobre o JSON — só evolui pra agente de fato se a lógica de ponderação ficar complexa demais para regras explícitas.