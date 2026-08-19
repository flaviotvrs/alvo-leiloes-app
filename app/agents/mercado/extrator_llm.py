"""
Extração de comparáveis estruturados a partir do conteúdo renderizado de um
portal, via LLM (não HTML parsing determinístico — layout varia demais entre
os 3 portais + índice regional para valer a pena manter seletores de dado).

Modelo/provedor é configurável (app/config.MERCADO_EXTRACTOR_LLM_MODEL) via
litellm, para poder trocar por custo/qualidade sem mudar código.
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal, InvalidOperation

import litellm

from app.agents.mercado.aggregate import CaracteristicasImovel, Comparavel
from app.agents.mercado.portais.base import PaginaRenderizada
from app.config import MERCADO_EXTRACTOR_LLM_MODEL

logger = logging.getLogger(__name__)

# HTML renderizado pode ser grande — limite grosseiro de caracteres pra
# controlar custo de tokens (a maior parte do ruído de portal é markup/CSS,
# não conteúdo relevante pro LLM).
_MAX_CHARS_CONTEUDO = 60_000

_FERRAMENTA_REPORTAR_COMPARAVEIS = {
    "type": "function",
    "function": {
        "name": "reportar_comparaveis",
        "description": "Reporta os anúncios comparáveis encontrados na página, se houver.",
        "parameters": {
            "type": "object",
            "properties": {
                "comparaveis": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "link": {
                                "type": "string",
                                "description": (
                                    "URL direta do anúncio individual — copiada literalmente da linha "
                                    "'URL do anúncio:' correspondente no texto, nunca a URL de busca."
                                ),
                            },
                            "valor": {"type": "number", "description": "Preço de venda anunciado, em reais"},
                            "metragem": {
                                "type": ["number", "null"],
                                "description": "Área privativa/útil em m², null se não informada",
                            },
                        },
                        "required": ["link", "valor", "metragem"],
                    },
                }
            },
            "required": ["comparaveis"],
        },
    },
}


def _montar_prompt(caract: CaracteristicasImovel) -> str:
    return f"""Você está analisando o resultado de uma busca por imóveis à venda, pra
estimar o valor de mercado de um imóvel específico usado como parâmetro.

Características do imóvel-alvo:
- tipo: {caract.tipo or "não informado"}
- bairro: {caract.bairro or "não informado"}
- cidade: {caract.cidade or "não informado"}
- área privativa: {caract.area_privativa_m2 or "não informada"} m²
- quartos: {caract.quartos if caract.quartos is not None else "não informado"}
- vagas de garagem: {caract.vagas_garagem if caract.vagas_garagem is not None else "não informado"}

No conteúdo da página abaixo, identifique só os anúncios que são comparáveis
de verdade a esse imóvel-alvo (mesmo tipo, mesma região, metragem parecida —
tolerância de aproximadamente ±30%). Ignore anúncios de tipo ou região muito
diferente, anúncios em destaque/patrocinados de outras cidades, e qualquer
elemento de navegação/propaganda que não seja um anúncio de imóvel.

Se a página não tiver nenhum anúncio comparável (ex: sem resultados, bloqueio
de acesso, captcha, região sem cobertura), reporte uma lista vazia — não
invente um valor.

Cada anúncio no texto abaixo começa com uma linha "URL do anúncio: <url>".
No campo `link` de cada item, copie exatamente essa URL (sem alterar) —
NUNCA reutilize a URL da página de busca citada logo abaixo, e nunca invente
uma URL. Se a linha disser "URL do anúncio: não disponível", deixe o campo
`link` como string vazia em vez de inventar algo."""


def extrair_comparaveis(pagina: PaginaRenderizada, caract: CaracteristicasImovel) -> list[Comparavel]:
    conteudo = pagina.html[:_MAX_CHARS_CONTEUDO]
    if len(pagina.html) > _MAX_CHARS_CONTEUDO:
        logger.debug(
            "[%s] conteúdo truncado de %d para %d caracteres antes de mandar pro LLM",
            pagina.fonte, len(pagina.html), _MAX_CHARS_CONTEUDO,
        )
    logger.debug("[%s] chamando %s (conteúdo enviado: %d caracteres)", pagina.fonte, MERCADO_EXTRACTOR_LLM_MODEL, len(conteudo))

    resposta = litellm.completion(
        model=MERCADO_EXTRACTOR_LLM_MODEL,
        messages=[
            {"role": "user", "content": _montar_prompt(caract) + f"\n\n--- Conteúdo da página ({pagina.url}) ---\n{conteudo}"},
        ],
        tools=[_FERRAMENTA_REPORTAR_COMPARAVEIS],
        tool_choice={"type": "function", "function": {"name": "reportar_comparaveis"}},
    )

    tool_calls = resposta.choices[0].message.tool_calls
    if not tool_calls:
        logger.warning("[%s] LLM não retornou tool_call — resposta bruta: %s", pagina.fonte, resposta.choices[0].message.content)
        return []

    dados = json.loads(tool_calls[0].function.arguments)
    brutos = dados.get("comparaveis", [])
    logger.debug("[%s] LLM reportou %d item(ns) bruto(s): %s", pagina.fonte, len(brutos), brutos)

    validos = [item for item in brutos if _item_valido(item)]
    if len(validos) < len(brutos):
        logger.debug(
            "[%s] %d de %d item(ns) descartado(s) por dado inválido (valor ausente/zero): %s",
            pagina.fonte, len(brutos) - len(validos), len(brutos),
            [item for item in brutos if not _item_valido(item)],
        )
    sem_metragem = sum(1 for item in validos if not item.get("metragem"))
    if sem_metragem:
        logger.debug("[%s] %d de %d item(ns) válido(s) sem metragem informada — serão descartados no filtro de agregação", pagina.fonte, sem_metragem, len(validos))

    return [_para_comparavel(item, pagina.fonte) for item in validos]


def _item_valido(item: dict) -> bool:
    try:
        return Decimal(str(item["valor"])) > 0
    except (KeyError, InvalidOperation, TypeError):
        return False


def _para_comparavel(item: dict, fonte: str) -> Comparavel:
    metragem = item.get("metragem")
    return Comparavel(
        fonte=fonte,
        link=item.get("link", ""),
        valor=Decimal(str(item["valor"])),
        metragem=Decimal(str(metragem)) if metragem else None,
    )
