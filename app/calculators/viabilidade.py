"""
Calculadora de viabilidade financeira para leilões de imóveis.

Fórmula:
    # Ganho de capital (base do IR):
    ganho_capital    = valor_mercado − comissao_corretor
                       − arremate − emolumentos − ITBI − comissao_leiloeiro − reforma
    ir               = max(0, ganho_capital) × aliquota_ir
    # Lucro após IR (equivalente a ganho × 0,85 quando não há outros custos):
    lucro_liquido    = ganho_capital − ir
                       − dividas − carregamento − advogado − outros_custos
    total_investido  = arremate + comissao_leiloeiro + emolumentos + ITBI
                       + dividas + carregamento + reforma + advogado + outros_custos
    margem_pct       = lucro_liquido / total_investido × 100
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from app.tables.emolumentos_mg import calcular_emolumentos
from app.tables.itbi import aliquota_itbi

_ZERO = Decimal("0")
_CENTAVO = Decimal("0.01")

COMISSAO_LEILOEIRO_DEFAULT = Decimal("5.00")
COMISSAO_CORRETOR_DEFAULT  = Decimal("5.50")
MESES_CARREGAMENTO_DEFAULT = 12
MARGEM_MINIMA_DEFAULT      = Decimal("20.00")


@dataclass
class EntradaViabilidade:
    valor_arremate: Decimal
    valor_mercado:  Decimal
    cidade:         str

    comissao_leiloeiro_pct: Decimal = field(default=COMISSAO_LEILOEIRO_DEFAULT)
    comissao_corretor_pct:  Decimal = field(default=COMISSAO_CORRETOR_DEFAULT)
    meses_carregamento:     int     = field(default=MESES_CARREGAMENTO_DEFAULT)
    margem_minima_pct:      Decimal = field(default=MARGEM_MINIMA_DEFAULT)

    # dívidas — sempre incluídas; usuário zera se não couber ao arrematante
    iptu_debito:       Decimal = field(default=_ZERO)
    condominio_debito: Decimal = field(default=_ZERO)

    # carregamento mensal
    iptu_mensal:       Decimal = field(default=_ZERO)
    condominio_mensal: Decimal = field(default=_ZERO)

    # custos adicionais pós-arremate
    custo_advogado:  Decimal = field(default=_ZERO)   # imissão na posse
    custo_reforma:   Decimal = field(default=_ZERO)   # reforma para revenda
    outros_custos:   Decimal = field(default=_ZERO)   # negociação, mudança, etc.


@dataclass
class ResultadoViabilidade:
    # custos de aquisição e posse
    valor_arremate:           Decimal
    comissao_leiloeiro_valor: Decimal
    emolumentos_cartorio:     Decimal
    itbi_valor:               Decimal
    dividas_assumidas:        Decimal
    custo_carregamento:       Decimal
    custo_advogado:           Decimal
    custo_reforma:            Decimal
    outros_custos:            Decimal

    # venda e impostos
    comissao_corretor_valor:  Decimal
    ganho_capital:            Decimal
    ir_ganho_capital:         Decimal

    # síntese
    total_investido:    Decimal
    total_custos:       Decimal
    lucro_liquido:      Decimal
    margem_liquida_pct: Decimal
    resultado:          str      # 'viavel' | 'nao_viavel'

    # metadados de confiança
    aliquota_itbi:        Decimal
    itbi_confirmado:      bool
    emolumentos_estimado: bool
    alertas:              list[str]


def calcular(entrada: EntradaViabilidade) -> ResultadoViabilidade:
    alertas: list[str] = []
    e = entrada

    arremate = _d(e.valor_arremate)
    mercado  = _d(e.valor_mercado)

    # ── comissão do leiloeiro ────────────────────────────────────────────────
    comissao_leiloeiro_valor = _pct(arremate, e.comissao_leiloeiro_pct)
    if e.comissao_leiloeiro_pct == COMISSAO_LEILOEIRO_DEFAULT:
        alertas.append("Comissão do leiloeiro não informada no edital — usando 5% como estimativa.")

    # ── emolumentos de cartório ──────────────────────────────────────────────
    emolumentos, emol_estimado = calcular_emolumentos(arremate)
    if emol_estimado:
        alertas.append("Valor acima de R$ 3.700.000: emolumentos calculados com estimativa (Nota XVII TJMG).")

    # ── ITBI ─────────────────────────────────────────────────────────────────
    aliq_itbi, itbi_confirmado = aliquota_itbi(e.cidade)
    itbi_valor = _pct(arremate, aliq_itbi * 100)
    if not itbi_confirmado:
        alertas.append(f"Alíquota de ITBI para '{e.cidade}' não confirmada — usando 3% como estimativa.")

    # ── dívidas e carregamento ───────────────────────────────────────────────
    dividas_assumidas  = _d(e.iptu_debito) + _d(e.condominio_debito)
    custo_carregamento = (_d(e.iptu_mensal) + _d(e.condominio_mensal)) * e.meses_carregamento

    # ── custos adicionais ────────────────────────────────────────────────────
    custo_advogado = _d(e.custo_advogado)
    custo_reforma  = _d(e.custo_reforma)
    outros_custos  = _d(e.outros_custos)

    # ── total investido ──────────────────────────────────────────────────────
    total_investido = (
        arremate
        + comissao_leiloeiro_valor
        + emolumentos
        + itbi_valor
        + dividas_assumidas
        + custo_carregamento
        + custo_advogado
        + custo_reforma
        + outros_custos
    )

    # ── venda e IR ───────────────────────────────────────────────────────────
    comissao_corretor_valor = _pct(mercado, e.comissao_corretor_pct)

    # Base do ganho de capital para IR:
    # mercado − (arremate + emolumentos + ITBI + comissão leiloeiro + reforma + comissão corretor)
    # Reforma reduz o ganho tributável pois é benfeitoria agregada ao imóvel.
    custo_ir      = arremate + emolumentos + itbi_valor + comissao_leiloeiro_valor + custo_reforma
    receita_ir    = mercado - comissao_corretor_valor
    ganho_capital = max(_ZERO, receita_ir - custo_ir)
    ir            = _calcular_ir(ganho_capital)

    # ── síntese ──────────────────────────────────────────────────────────────
    total_custos  = total_investido + comissao_corretor_valor + ir
    lucro_liquido = mercado - total_custos
    margem_pct    = (lucro_liquido / total_investido * 100).quantize(_CENTAVO, ROUND_HALF_UP)
    resultado     = "viavel" if margem_pct >= _d(e.margem_minima_pct) else "nao_viavel"

    return ResultadoViabilidade(
        valor_arremate=arremate,
        comissao_leiloeiro_valor=_r(comissao_leiloeiro_valor),
        emolumentos_cartorio=_r(emolumentos),
        itbi_valor=_r(itbi_valor),
        dividas_assumidas=_r(dividas_assumidas),
        custo_carregamento=_r(custo_carregamento),
        custo_advogado=_r(custo_advogado),
        custo_reforma=_r(custo_reforma),
        outros_custos=_r(outros_custos),
        comissao_corretor_valor=_r(comissao_corretor_valor),
        ganho_capital=_r(ganho_capital),
        ir_ganho_capital=_r(ir),
        total_investido=_r(total_investido),
        total_custos=_r(total_custos),
        lucro_liquido=_r(lucro_liquido),
        margem_liquida_pct=margem_pct,
        resultado=resultado,
        aliquota_itbi=aliq_itbi,
        itbi_confirmado=itbi_confirmado,
        emolumentos_estimado=emol_estimado,
        alertas=alertas,
    )


# ── IR sobre ganho de capital (pessoa física, Art. 21 Lei 8.981/95) ─────────

_FAIXAS_IR = [
    (Decimal("5000000"),  Decimal("0.15")),
    (Decimal("10000000"), Decimal("0.175")),
    (Decimal("30000000"), Decimal("0.20")),
]
_ALIQUOTA_IR_TOPO = Decimal("0.225")


def _calcular_ir(ganho: Decimal) -> Decimal:
    if ganho <= _ZERO:
        return _ZERO
    for limite, aliq in _FAIXAS_IR:
        if ganho <= limite:
            return ganho * aliq
    return ganho * _ALIQUOTA_IR_TOPO


def _d(v) -> Decimal:
    return Decimal(str(v)) if v is not None else _ZERO


def _pct(base: Decimal, pct: Decimal) -> Decimal:
    return base * _d(pct) / 100


def _r(v: Decimal) -> Decimal:
    return v.quantize(_CENTAVO, ROUND_HALF_UP)
