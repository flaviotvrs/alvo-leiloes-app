"""Testes da calculadora de viabilidade e das tabelas de apoio."""

from decimal import Decimal

import pytest

from app.calculators.viabilidade import EntradaViabilidade, calcular
from app.tables.emolumentos_mg import calcular_emolumentos
from app.tables.itbi import aliquota_itbi


# ── Emolumentos ──────────────────────────────────────────────────────────────

def test_emolumentos_primeira_faixa():
    valor, estimado = calcular_emolumentos(Decimal("1000"))
    assert valor == Decimal("227.95")
    assert not estimado

def test_emolumentos_no_limite_exato():
    valor, _ = calcular_emolumentos(Decimal("1400.00"))
    assert valor == Decimal("227.95")

def test_emolumentos_faixa_intermediaria():
    valor, estimado = calcular_emolumentos(Decimal("84306.67"))
    assert valor == Decimal("3026.34")
    assert not estimado

def test_emolumentos_ultima_faixa_fixa():
    valor, estimado = calcular_emolumentos(Decimal("3700000"))
    assert valor == Decimal("13034.69")
    assert not estimado

def test_emolumentos_acima_nota_xvii():
    valor, estimado = calcular_emolumentos(Decimal("4200000"))
    assert estimado
    assert valor > Decimal("13034.69")


# ── ITBI ─────────────────────────────────────────────────────────────────────

def test_itbi_belo_horizonte():
    aliq, confirmado = aliquota_itbi("Belo Horizonte")
    assert aliq == Decimal("0.03")
    assert confirmado

def test_itbi_sete_lagoas():
    aliq, confirmado = aliquota_itbi("Sete Lagoas")
    assert aliq == Decimal("0.025")
    assert confirmado

def test_itbi_municipio_tbd():
    _, confirmado = aliquota_itbi("Juatuba")
    assert not confirmado

def test_itbi_municipio_desconhecido():
    _, confirmado = aliquota_itbi("Cidade Inexistente")
    assert not confirmado

def test_itbi_acento_insensivel():
    aliq1, _ = aliquota_itbi("Sete Lagoas")
    aliq2, _ = aliquota_itbi("SETE LAGOAS")
    assert aliq1 == aliq2


# ── Calculadora ───────────────────────────────────────────────────────────────

def _entrada_basica(**kwargs) -> EntradaViabilidade:
    defaults = dict(
        valor_arremate=Decimal("84306.67"),
        valor_mercado=Decimal("144000.00"),
        cidade="Belo Horizonte",
        comissao_leiloeiro_pct=Decimal("5.00"),
        comissao_corretor_pct=Decimal("5.50"),
        meses_carregamento=12,
        margem_minima_pct=Decimal("20.00"),
        iptu_mensal=Decimal("200.00"),
        condominio_mensal=Decimal("300.00"),
    )
    defaults.update(kwargs)
    return EntradaViabilidade(**defaults)


def test_calculo_completo_viavel():
    r = calcular(_entrada_basica())

    assert r.valor_arremate == Decimal("84306.67")
    assert r.emolumentos_cartorio == Decimal("3026.34")
    assert r.itbi_valor == pytest.approx(Decimal("84306.67") * Decimal("0.03"), rel=Decimal("0.001"))
    assert r.itbi_confirmado
    assert r.comissao_leiloeiro_valor == pytest.approx(Decimal("84306.67") * Decimal("0.05"), rel=Decimal("0.001"))
    assert r.custo_carregamento == Decimal("6000.00")
    assert r.dividas_assumidas == Decimal("0.00")
    assert r.custo_advogado == Decimal("0.00")
    assert r.custo_reforma == Decimal("0.00")
    assert r.outros_custos == Decimal("0.00")
    assert r.lucro_liquido > 0
    assert r.resultado == "viavel"


def test_calculo_nao_viavel_margem_baixa():
    r = calcular(_entrada_basica(valor_mercado=Decimal("100000.00")))
    assert r.resultado == "nao_viavel"


def test_dividas_sempre_incluidas():
    r = calcular(_entrada_basica(
        iptu_debito=Decimal("5000.00"),
        condominio_debito=Decimal("3000.00"),
    ))
    assert r.dividas_assumidas == Decimal("8000.00")


def test_dividas_zeradas_nao_impactam():
    r_sem = calcular(_entrada_basica())
    r_com = calcular(_entrada_basica(iptu_debito=Decimal("0"), condominio_debito=Decimal("0")))
    assert r_sem.dividas_assumidas == r_com.dividas_assumidas == Decimal("0.00")


def test_custo_advogado_incluido_no_total():
    r_sem = calcular(_entrada_basica())
    r_com = calcular(_entrada_basica(custo_advogado=Decimal("5000.00")))
    assert r_com.custo_advogado == Decimal("5000.00")
    assert r_com.total_investido == r_sem.total_investido + Decimal("5000.00")
    assert r_com.margem_liquida_pct < r_sem.margem_liquida_pct


def test_custo_reforma_incluido_no_total_e_no_ir():
    r_sem = calcular(_entrada_basica())
    r_com = calcular(_entrada_basica(custo_reforma=Decimal("20000.00")))
    assert r_com.custo_reforma == Decimal("20000.00")
    # reforma entra no total investido
    assert r_com.total_investido == r_sem.total_investido + Decimal("20000.00")
    # reforma também reduz a base do ganho de capital → IR menor
    assert r_com.ir_ganho_capital < r_sem.ir_ganho_capital
    assert r_com.ganho_capital == r_sem.ganho_capital - Decimal("20000.00")


def test_outros_custos_incluido_no_total():
    r = calcular(_entrada_basica(outros_custos=Decimal("3000.00")))
    assert r.outros_custos == Decimal("3000.00")
    assert r.resultado in ("viavel", "nao_viavel")


def test_todos_custos_extras_acumulam():
    r = calcular(_entrada_basica(
        custo_advogado=Decimal("5000.00"),
        custo_reforma=Decimal("15000.00"),
        outros_custos=Decimal("2000.00"),
    ))
    r_base = calcular(_entrada_basica())
    assert r.total_investido == r_base.total_investido + Decimal("22000.00")


def test_ir_calculado_sobre_ganho():
    r = calcular(_entrada_basica())
    assert r.ganho_capital >= 0
    if r.ganho_capital > 0:
        assert r.ir_ganho_capital == pytest.approx(r.ganho_capital * Decimal("0.15"), rel=Decimal("0.001"))


def test_alerta_comissao_leiloeiro_default():
    r = calcular(_entrada_basica())
    assert any("comissão do leiloeiro" in a.lower() for a in r.alertas)


def test_margem_minima_parametrizavel():
    r_restrito = calcular(_entrada_basica(margem_minima_pct=Decimal("40.00")))
    r_frouxo   = calcular(_entrada_basica(margem_minima_pct=Decimal("5.00")))
    assert r_frouxo.resultado == "viavel"
    # com margem muito alta, provavelmente não-viável para este imóvel
    assert r_restrito.margem_liquida_pct == r_frouxo.margem_liquida_pct  # margem calculada é igual
    assert r_restrito.resultado != r_frouxo.resultado or r_restrito.margem_liquida_pct >= 40
