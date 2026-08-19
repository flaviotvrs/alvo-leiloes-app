"""
Lógica pura de agregação do agente mercado-extractor — sem I/O (sem Playwright,
sem chamada de LLM, sem banco). Dataclass-in, dataclass-out, no estilo de
app/calculators/viabilidade.py.

Regras (docs/mvp2.md §2-4, docs/interface-agentes.md §1-2):
    - metodo = "comparaveis_diretos" quando há comparáveis usáveis nos 3 portais
      principais; "fallback_m2_regiao" quando cai pro índice regional (4ª fonte).
    - regiao_baixa_liquidez = True sempre que caiu no fallback, mesmo que o
      índice regional tenha encontrado dado (não é a mesma coisa que confiança 0).
    - confianca é reduzida tanto pela quantidade de comparáveis quanto pela
      quantidade de características do edital ausentes (campos_edital_ausentes)
      — não só uma das duas coisas.
    - valor: null + confiança baixa é "tentei e não achei nada confiável", uma
      informação diferente de campo silenciosamente ausente.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

logger = logging.getLogger(__name__)

VERSAO_AGENTE = "0.1.0"

_CARACTERISTICAS_DO_EDITAL = ("tipo", "quartos", "vagas_garagem")

# Comparáveis com R$/m² fora dessa banda em torno da mediana são descartados
# como outlier (anúncio com erro de digitação, imóvel muito atípico, etc.).
_BANDA_OUTLIER_MIN = Decimal("0.5")
_BANDA_OUTLIER_MAX = Decimal("2.0")

# Cada característica do edital ausente reduz a confiança nesse tanto.
_PENALIDADE_POR_CAMPO_AUSENTE = Decimal("0.15")

# Multiplicador extra de penalidade quando o valor vem do índice regional
# (fallback), já que é uma média de região, não um comparável direto do imóvel.
_PENALIDADE_FALLBACK = Decimal("0.7")

LIMIAR_REVISAO_HUMANA = Decimal("0.5")


@dataclass
class Comparavel:
    fonte: str
    link: str
    valor: Decimal
    metragem: Decimal | None


@dataclass
class CaracteristicasImovel:
    tipo: str | None
    bairro: str | None
    cidade: str | None
    area_privativa_m2: Decimal | None
    quartos: int | None
    vagas_garagem: int | None
    uf: str | None = None


@dataclass
class ResultadoAgregacao:
    valor_m2_estimado: Decimal | None
    valor_total_estimado: Decimal | None
    metodo: str  # "comparaveis_diretos" | "fallback_m2_regiao"
    comparaveis_usados: list[Comparavel]
    campos_edital_ausentes: list[str]
    regiao_baixa_liquidez: bool
    confianca: Decimal
    requer_revisao_humana: bool


def campos_edital_ausentes(caract: CaracteristicasImovel) -> list[str]:
    return [c for c in _CARACTERISTICAS_DO_EDITAL if getattr(caract, c) is None]


def filtrar_comparaveis(brutos: list[Comparavel], caract: CaracteristicasImovel) -> list[Comparavel]:
    """Remove comparáveis sem dado suficiente e outliers de preço por m².

    O filtro por região/tipo já acontece na busca em si (query por portal) —
    aqui só se garante que o que sobrou é minimamente consistente entre si.
    """
    usaveis = [c for c in brutos if c.valor > 0 and c.metragem and c.metragem > 0]
    if len(usaveis) < len(brutos):
        descartados = [c for c in brutos if c not in usaveis]
        logger.debug(
            "filtrar_comparaveis: %d de %d descartado(s) por valor/metragem ausente ou zero: %s",
            len(brutos) - len(usaveis), len(brutos), [(c.fonte, c.valor, c.metragem) for c in descartados],
        )

    if len(usaveis) < 2:
        logger.debug("filtrar_comparaveis: só %d usável(is) — pulando filtro de outlier (precisa de ao menos 2)", len(usaveis))
        return usaveis

    razoes = sorted(c.valor / c.metragem for c in usaveis)
    mediana = razoes[len(razoes) // 2]
    piso, teto = mediana * _BANDA_OUTLIER_MIN, mediana * _BANDA_OUTLIER_MAX
    resultado = [c for c in usaveis if piso <= (c.valor / c.metragem) <= teto]

    if len(resultado) < len(usaveis):
        excluidos = [c for c in usaveis if c not in resultado]
        logger.debug(
            "filtrar_comparaveis: banda de outlier R$/m² [%.2f, %.2f] (mediana %.2f) excluiu %d de %d: %s",
            piso, teto, mediana, len(usaveis) - len(resultado), len(usaveis),
            [(c.fonte, c.valor, c.metragem, round(c.valor / c.metragem, 2)) for c in excluidos],
        )

    return resultado


def agregar(
    comparaveis_diretos: list[Comparavel],
    caract: CaracteristicasImovel,
    min_confianca_alta: int,
    comparaveis_indice_regional: list[Comparavel] | None = None,
) -> ResultadoAgregacao:
    ausentes = campos_edital_ausentes(caract)
    if ausentes:
        logger.debug("Características ausentes no edital (reduzem confiança): %s", ausentes)

    diretos_filtrados = filtrar_comparaveis(comparaveis_diretos, caract)

    if diretos_filtrados:
        metodo = "comparaveis_diretos"
        regiao_baixa_liquidez = False
        usados = diretos_filtrados
        confianca = _calcular_confianca(len(usados), min_confianca_alta, ausentes)
        logger.debug("agregar: %d comparável(is) direto(s) usável(is) — método=comparaveis_diretos", len(usados))
    else:
        metodo = "fallback_m2_regiao"
        regiao_baixa_liquidez = True
        usados = filtrar_comparaveis(comparaveis_indice_regional or [], caract)
        if usados:
            confianca = _calcular_confianca(len(usados), min_confianca_alta, ausentes) * _PENALIDADE_FALLBACK
            logger.debug("agregar: 0 comparáveis diretos, %d via índice regional — método=fallback_m2_regiao", len(usados))
        else:
            confianca = Decimal("0")
            logger.debug("agregar: 0 comparáveis diretos e 0 no índice regional — sem dado utilizável, confiança 0")

    valor_m2, valor_total = _calcular_valores(usados, caract)
    confianca = confianca.quantize(Decimal("0.01"))
    logger.debug("agregar: valor_m2_estimado=%s valor_total_estimado=%s confianca=%s", valor_m2, valor_total, confianca)

    return ResultadoAgregacao(
        valor_m2_estimado=valor_m2,
        valor_total_estimado=valor_total,
        metodo=metodo,
        comparaveis_usados=usados,
        campos_edital_ausentes=ausentes,
        regiao_baixa_liquidez=regiao_baixa_liquidez,
        confianca=confianca,
        requer_revisao_humana=confianca < LIMIAR_REVISAO_HUMANA,
    )


def montar_envelope(resultado: ResultadoAgregacao, imovel_id: int, fonte_meta: dict) -> dict:
    """Monta o envelope no formato comum (docs/interface-agentes.md §1)."""
    comparaveis_valor = [
        {"fonte": c.fonte, "link": c.link, "valor": float(c.valor), "metragem": float(c.metragem) if c.metragem else None}
        for c in resultado.comparaveis_usados
    ]

    def _campo(nome: str, valor, evidencia: str) -> dict:
        return {
            "campo": nome,
            "valor": valor,
            "confianca": float(resultado.confianca),
            "evidencia": evidencia,
            "requer_revisao_humana": resultado.requer_revisao_humana,
        }

    n = len(resultado.comparaveis_usados)
    evidencia_valores = (
        f"{n} comparável(is) usados via {resultado.metodo}."
        if n
        else "Nenhum comparável usável encontrado (nem direto, nem índice regional)."
    )

    campos = [
        _campo(
            "valor_m2_estimado",
            float(resultado.valor_m2_estimado) if resultado.valor_m2_estimado is not None else None,
            evidencia_valores,
        ),
        _campo(
            "valor_total_estimado",
            float(resultado.valor_total_estimado) if resultado.valor_total_estimado is not None else None,
            evidencia_valores,
        ),
        _campo("comparaveis", comparaveis_valor, f"{n} comparável(is) listados como evidência."),
        _campo("metodo", resultado.metodo, f"Método escolhido: {resultado.metodo}."),
        _campo(
            "campos_edital_ausentes",
            resultado.campos_edital_ausentes,
            "Características não informadas no edital: " + (", ".join(resultado.campos_edital_ausentes) or "nenhuma") + ".",
        ),
        _campo(
            "regiao_baixa_liquidez",
            resultado.regiao_baixa_liquidez,
            "Caiu no fallback de índice regional." if resultado.regiao_baixa_liquidez else "Comparáveis diretos disponíveis.",
        ),
    ]

    return {
        "agente": "mercado-extractor",
        "versao_agente": VERSAO_AGENTE,
        "imovel_id": imovel_id,
        "fonte": fonte_meta,
        "extraido_em": datetime.now(timezone.utc).isoformat(),
        "campos": campos,
        "campos_nao_encontrados": [],
        "observacoes_agente": None,
    }


def _calcular_confianca(n_comparaveis: int, min_confianca_alta: int, ausentes: list[str]) -> Decimal:
    if n_comparaveis <= 0:
        base = Decimal("0")
    elif n_comparaveis >= min_confianca_alta:
        base = Decimal("1")
    else:
        base = max(Decimal("0.3"), Decimal(n_comparaveis) / Decimal(min_confianca_alta))

    penalidade = _PENALIDADE_POR_CAMPO_AUSENTE * len(ausentes)
    return max(Decimal("0"), base - penalidade)


def _calcular_valores(
    comparaveis: list[Comparavel], caract: CaracteristicasImovel
) -> tuple[Decimal | None, Decimal | None]:
    com_metragem = [c for c in comparaveis if c.metragem]
    if com_metragem:
        razoes = [c.valor / c.metragem for c in com_metragem]
        valor_m2 = sum(razoes) / len(razoes)
    else:
        valor_m2 = None

    if valor_m2 is not None and caract.area_privativa_m2:
        valor_total = valor_m2 * caract.area_privativa_m2
    elif comparaveis:
        valor_total = sum(c.valor for c in comparaveis) / len(comparaveis)
    else:
        valor_total = None

    return valor_m2, valor_total
