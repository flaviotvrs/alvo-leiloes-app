"""Testes da lógica pura de agregação do agente mercado-extractor."""

from decimal import Decimal

from app.agents.mercado.aggregate import (
    Comparavel,
    CaracteristicasImovel,
    agregar,
    campos_edital_ausentes,
    filtrar_comparaveis,
    montar_envelope,
)

MIN_CONFIANCA_ALTA = 3


def _caract(**overrides) -> CaracteristicasImovel:
    base = dict(
        tipo="residencial",
        bairro="Centro",
        cidade="Belo Horizonte",
        area_privativa_m2=Decimal("80"),
        quartos=2,
        vagas_garagem=1,
    )
    base.update(overrides)
    return CaracteristicasImovel(**base)


def _comp(valor, metragem, fonte="imovelweb") -> Comparavel:
    return Comparavel(fonte=fonte, link="https://example.com", valor=Decimal(str(valor)), metragem=Decimal(str(metragem)))


# ── campos_edital_ausentes ───────────────────────────────────────────────────

def test_campos_edital_ausentes_nenhum():
    assert campos_edital_ausentes(_caract()) == []

def test_campos_edital_ausentes_alguns():
    assert campos_edital_ausentes(_caract(quartos=None, vagas_garagem=None)) == ["quartos", "vagas_garagem"]


# ── filtrar_comparaveis ──────────────────────────────────────────────────────

def test_filtrar_remove_sem_metragem_ou_valor_zero():
    brutos = [_comp(300_000, 80), _comp(0, 80), Comparavel("x", "y", Decimal("100000"), None)]
    assert filtrar_comparaveis(brutos, _caract()) == [brutos[0]]

def test_filtrar_remove_outlier_de_preco():
    normais = [_comp(300_000, 80), _comp(310_000, 82), _comp(290_000, 78)]
    outlier = _comp(50_000_000, 80)  # R$/m² muito acima da mediana
    filtrados = filtrar_comparaveis(normais + [outlier], _caract())
    assert outlier not in filtrados
    assert len(filtrados) == 3


# ── agregar — comparáveis diretos ────────────────────────────────────────────

def test_agregar_com_comparaveis_suficientes_confianca_alta():
    comparaveis = [_comp(300_000, 80), _comp(310_000, 82), _comp(295_000, 79)]
    r = agregar(comparaveis, _caract(), MIN_CONFIANCA_ALTA)
    assert r.metodo == "comparaveis_diretos"
    assert r.regiao_baixa_liquidez is False
    assert r.confianca == Decimal("1.00")
    assert r.requer_revisao_humana is False
    assert r.valor_m2_estimado is not None
    assert r.valor_total_estimado == r.valor_m2_estimado * Decimal("80")

def test_agregar_com_poucos_comparaveis_confianca_reduzida():
    comparaveis = [_comp(300_000, 80)]
    r = agregar(comparaveis, _caract(), MIN_CONFIANCA_ALTA)
    assert r.metodo == "comparaveis_diretos"
    assert Decimal("0") < r.confianca < Decimal("1")

def test_agregar_campos_ausentes_reduz_confianca():
    comparaveis = [_comp(300_000, 80), _comp(310_000, 82), _comp(295_000, 79)]
    completo = agregar(comparaveis, _caract(), MIN_CONFIANCA_ALTA)
    incompleto = agregar(comparaveis, _caract(quartos=None, vagas_garagem=None), MIN_CONFIANCA_ALTA)
    assert incompleto.confianca < completo.confianca
    assert incompleto.campos_edital_ausentes == ["quartos", "vagas_garagem"]


# ── agregar — fallback índice regional ───────────────────────────────────────

def test_agregar_sem_diretos_cai_no_indice_regional():
    indice = [_comp(3_500, 1, fonte="indice_regional")]  # R$/m² direto
    r = agregar([], _caract(), MIN_CONFIANCA_ALTA, comparaveis_indice_regional=indice)
    assert r.metodo == "fallback_m2_regiao"
    assert r.regiao_baixa_liquidez is True
    assert r.valor_m2_estimado == Decimal("3500")
    assert r.confianca > Decimal("0")

def test_agregar_sem_diretos_e_sem_indice_regional_fica_zerado_e_requer_revisao():
    r = agregar([], _caract(), MIN_CONFIANCA_ALTA, comparaveis_indice_regional=[])
    assert r.metodo == "fallback_m2_regiao"
    assert r.regiao_baixa_liquidez is True
    assert r.valor_m2_estimado is None
    assert r.valor_total_estimado is None
    assert r.confianca == Decimal("0")
    assert r.requer_revisao_humana is True


# ── montar_envelope ───────────────────────────────────────────────────────────

def test_montar_envelope_formato_e_campos_catalogo():
    comparaveis = [_comp(300_000, 80), _comp(310_000, 82), _comp(295_000, 79)]
    resultado = agregar(comparaveis, _caract(), MIN_CONFIANCA_ALTA)
    envelope = montar_envelope(resultado, imovel_id=42, fonte_meta={"tipo": "busca_portais"})

    assert envelope["agente"] == "mercado-extractor"
    assert envelope["imovel_id"] == 42
    assert envelope["campos_nao_encontrados"] == []

    nomes_campos = {c["campo"] for c in envelope["campos"]}
    assert nomes_campos == {
        "valor_m2_estimado",
        "valor_total_estimado",
        "comparaveis",
        "metodo",
        "campos_edital_ausentes",
        "regiao_baixa_liquidez",
    }
    for campo in envelope["campos"]:
        assert "confianca" in campo
        assert "evidencia" in campo
        assert "requer_revisao_humana" in campo

def test_montar_envelope_valor_none_nao_vira_campo_nao_encontrado():
    resultado = agregar([], _caract(), MIN_CONFIANCA_ALTA, comparaveis_indice_regional=[])
    envelope = montar_envelope(resultado, imovel_id=1, fonte_meta={})
    assert envelope["campos_nao_encontrados"] == []
    valor_total = next(c for c in envelope["campos"] if c["campo"] == "valor_total_estimado")
    assert valor_total["valor"] is None
    assert valor_total["requer_revisao_humana"] is True
