"""
Tela de detalhe do imóvel + calculadora de viabilidade.

Design para futura substituição de inputs manuais por agentes:
  Os inputs são coletados em `_coletar_inputs_manuais()`, que retorna um dict
  padronizado com uma chave "fonte" (atualmente "manual"). No pós-MVP 1, cada
  campo poderá ser preenchido por um agente autônomo — bastará trocar a função
  de coleta sem alterar a calculadora ou o modelo de persistência.
"""

from __future__ import annotations

from decimal import Decimal

import pandas as pd
import streamlit as st
from sqlalchemy import or_
from sqlalchemy.orm import joinedload

from app.calculators.viabilidade import (
    COMISSAO_CORRETOR_DEFAULT,
    COMISSAO_LEILOEIRO_DEFAULT,
    MARGEM_MINIMA_DEFAULT,
    MESES_CARREGAMENTO_DEFAULT,
    EntradaViabilidade,
    ResultadoViabilidade,
    calcular,
)
from app.db import SessionLocal, USER_ID
from app.models import AnaliseFinanceira, Imovel


# ── Funções auxiliares ────────────────────────────────────────────────────────

def _fmt(v, prefixo="R$ ") -> str:
    if v is None:
        return "—"
    return f"{prefixo}{float(v):,.2f}"


def _coletar_inputs_manuais(dados: dict) -> dict:
    """Coleta os inputs necessários via formulário e retorna dict padronizado.

    Chave "fonte"="manual" para rastreabilidade de origem dos valores.

    PONTO DE INJEÇÃO DE AGENTE (pós-MVP 1):
        Substituir esta função por uma que consulte agentes autônomos,
        mantendo o mesmo contrato de retorno (mesmo dict, mesma chave "fonte").
        A UI atual pode permanecer como modo de revisão/override.
    """
    valor_mercado = st.number_input(
        "Valor de mercado estimado (R$)",
        min_value=0.0,
        value=float(dados["valor_avaliacao"] or 0),
        step=1_000.0,
        format="%.2f",
        help=(
            f"Busque comparáveis no ImovelWeb, VivaReal ou Netimóveis para imóveis "
            f"similares em {dados['bairro']}, {dados['cidade']}. "
            "Alternativa: R$/m² médio da região × metragem."
        ),
    )

    # Dívidas e carregamento
    st.markdown("**Dívidas e carregamento** — zere os campos que não couberem ao arrematante")
    c1, c2 = st.columns(2)
    with c1:
        iptu_debito = st.number_input(
            "IPTU em débito (R$)", min_value=0.0, value=0.0, step=100.0,
            help="Débito total de IPTU que será assumido pelo arrematante. Zere se ficar com o credor/vendedor.",
        )
        iptu_mensal = st.number_input(
            "IPTU mensal (R$)", min_value=0.0, value=0.0, step=10.0,
            help="Prefeitura online → inscrição municipal → valor anual ÷ 12.",
        )
    with c2:
        condominio_debito = st.number_input(
            "Condomínio em débito (R$)", min_value=0.0, value=0.0, step=100.0,
            help="Débito total de condomínio assumido pelo arrematante. Zere se ficar com o credor/vendedor.",
        )
        condominio_mensal = st.number_input(
            "Condomínio mensal (R$)", min_value=0.0, value=0.0, step=50.0,
            help="Entre em contato com a administradora ou síndico.",
        )

    # Custos adicionais pós-arremate
    st.divider()
    st.markdown("**Custos adicionais pós-arremate** — deixe zero se não aplicável")
    c3, c4 = st.columns(2)
    with c3:
        custo_advogado = st.number_input(
            "Advogado — imissão na posse (R$)", min_value=0.0, value=0.0, step=500.0,
            help="Honorários de advogado para processo de imissão na posse caso o imóvel esteja ocupado.",
        )
        custo_reforma = st.number_input(
            "Estimativa de reforma (R$)", min_value=0.0, value=0.0, step=1_000.0,
            help="Estimativa dos gastos necessários para colocar o imóvel em condições de venda.",
        )
    with c4:
        outros_custos = st.number_input(
            "Outros custos (R$)", min_value=0.0, value=0.0, step=500.0,
            help="Ex: negociação com ocupante, caminhão de mudança, taxas diversas.",
        )
        outros_custos_descricao = st.text_input(
            "Descrição dos outros custos",
            placeholder="Ex: negociação com ocupante + mudança",
        )

    with st.expander("Parâmetros avançados"):
        c5, c6, c7 = st.columns(3)
        with c5:
            meses = st.number_input("Meses de carregamento", 1, 60, MESES_CARREGAMENTO_DEFAULT)
        with c6:
            corretor = st.number_input(
                "Comissão corretor (%)", 0.0, 10.0, float(COMISSAO_CORRETOR_DEFAULT), step=0.5,
            )
        with c7:
            margem = st.number_input(
                "Margem mínima (%)", 0.0, 100.0, float(MARGEM_MINIMA_DEFAULT), step=1.0,
            )

    return {
        "fonte":                    "manual",
        "valor_mercado":            valor_mercado,
        "iptu_debito":              iptu_debito,
        "condominio_debito":        condominio_debito,
        "iptu_mensal":              iptu_mensal,
        "condominio_mensal":        condominio_mensal,
        "custo_advogado":           custo_advogado,
        "custo_reforma":            custo_reforma,
        "outros_custos":            outros_custos,
        "outros_custos_descricao":  outros_custos_descricao,
        "meses_carregamento":       int(meses),
        "comissao_corretor":        corretor,
        "margem_minima":            margem,
    }


def _exibir_resultado(r: ResultadoViabilidade, imovel_id: int, inputs: dict, dados: dict) -> None:
    st.divider()

    if r.resultado == "viavel":
        st.success(f"### ✓ VIÁVEL — {r.margem_liquida_pct:.1f}%")
    else:
        st.error(f"### ✗ NÃO VIÁVEL — {r.margem_liquida_pct:.1f}%")

    outros_label = inputs.get("outros_custos_descricao") or "Outros custos"
    linhas = [
        ("Arremate",                                          float(r.valor_arremate)),
        ("Comissão do leiloeiro",                            float(r.comissao_leiloeiro_valor)),
        ("Emolumentos de cartório",                          float(r.emolumentos_cartorio)),
        (f"ITBI ({dados['cidade']})",                        float(r.itbi_valor)),
        ("Dívidas assumidas (IPTU + condomínio em débito)",  float(r.dividas_assumidas)),
        (f"Carregamento ({inputs['meses_carregamento']} meses)", float(r.custo_carregamento)),
        ("Advogado — imissão na posse",                      float(r.custo_advogado)),
        ("Reforma",                                          float(r.custo_reforma)),
        (outros_label,                                        float(r.outros_custos)),
        ("Comissão corretor (venda)",                        float(r.comissao_corretor_valor)),
        ("IR sobre ganho de capital",                        float(r.ir_ganho_capital)),
    ]
    df_custos = pd.DataFrame(
        [l for l in linhas if l[1] != 0.0],
        columns=["Item", "Valor (R$)"],
    )

    c1, c2 = st.columns([3, 2])
    with c1:
        st.dataframe(
            df_custos.style.format({"Valor (R$)": "R$ {:,.2f}"}),
            use_container_width=True,
            hide_index=True,
        )
    with c2:
        st.metric("Total investido",  _fmt(r.total_investido))
        st.metric("Valor de mercado", _fmt(inputs["valor_mercado"]))
        st.metric(
            "Lucro líquido",
            _fmt(r.lucro_liquido),
            delta=f"{r.margem_liquida_pct:.1f}%",
            delta_color="normal" if r.resultado == "viavel" else "inverse",
        )

    if r.alertas:
        for alerta in r.alertas:
            st.warning(alerta)

    st.divider()
    if st.button("💾 Salvar análise", type="secondary"):
        _salvar_analise(r, imovel_id, inputs)


def _salvar_analise(r: ResultadoViabilidade, imovel_id: int, inputs: dict) -> None:
    with SessionLocal() as session:
        versao = session.query(AnaliseFinanceira).filter_by(imovel_id=imovel_id).count() + 1
        analise = AnaliseFinanceira(
            imovel_id=imovel_id,
            versao=versao,
            user_id=USER_ID,
            fonte_valor_mercado=inputs["fonte"],
            valor_mercado=Decimal(str(inputs["valor_mercado"])),
            iptu_debito=Decimal(str(inputs["iptu_debito"])),
            condominio_debito=Decimal(str(inputs["condominio_debito"])),
            iptu_mensal=Decimal(str(inputs["iptu_mensal"])),
            condominio_mensal=Decimal(str(inputs["condominio_mensal"])),
            meses_carregamento=inputs["meses_carregamento"],
            custo_advogado=Decimal(str(inputs["custo_advogado"])),
            custo_reforma=Decimal(str(inputs["custo_reforma"])),
            outros_custos=Decimal(str(inputs["outros_custos"])),
            outros_custos_descricao=inputs["outros_custos_descricao"] or None,
            comissao_corretor_revenda=Decimal(str(inputs["comissao_corretor"])),
            margem_minima_corte=Decimal(str(inputs["margem_minima"])),
            valor_arremate=r.valor_arremate,
            valor_registro_cartorio=r.emolumentos_cartorio,
            valor_itbi=r.itbi_valor,
            custo_carregamento=r.custo_carregamento,
            ir_ganho_capital=r.ir_ganho_capital,
            total_custos=r.total_custos,
            margem_liquida_pct=r.margem_liquida_pct,
            margem_liquida_valor=r.lucro_liquido,
            resultado=r.resultado,
        )
        session.add(analise)
        session.commit()
    st.success(f"Análise v{versao} salva.")


# ── Página ────────────────────────────────────────────────────────────────────

st.set_page_config(page_title="Análise do Imóvel", page_icon="🔍", layout="wide")

# ── CSS: oculta botões de toolbar exceto fullscreen ───────────────────────────
st.markdown("""
<style>
[data-testid="stElementToolbarButton"]:not([title*="screen"]):not([title*="tela"]) {
    display: none !important;
}
</style>
""", unsafe_allow_html=True)

if st.button("← Lista"):
    st.query_params.clear()
    st.switch_page("streamlit_app.py")

# ── Resolução do imovel_id: query_params > session_state ─────────────────────
if "imovel_id" in st.query_params:
    try:
        imovel_id = int(st.query_params["imovel_id"])
        st.session_state["imovel_id"] = imovel_id
    except (ValueError, KeyError):
        st.error("ID de imóvel inválido na URL.")
        st.stop()
elif "imovel_id" in st.session_state:
    imovel_id = st.session_state["imovel_id"]
    st.query_params["imovel_id"] = str(imovel_id)
else:
    st.warning("Nenhum imóvel selecionado. Use a lista para navegar.")
    st.stop()

# Limpa resultado de outro imóvel para não vazar entre navegações
if st.session_state.get("resultado_imovel_id") != imovel_id:
    st.session_state.pop("resultado", None)
    st.session_state.pop("inputs_snapshot", None)
    st.session_state["resultado_imovel_id"] = imovel_id

with SessionLocal() as session:
    im = session.get(Imovel, imovel_id, options=[joinedload(Imovel.edital)])
    if not im or not im.edital:
        st.error("Imóvel não encontrado.")
        st.stop()
    id_externo = im.id_externo
    dados = {
        "endereco":        im.endereco,
        "bairro":          im.bairro,
        "cidade":          im.cidade,
        "uf":              im.uf,
        "tipo":            im.tipo,
        "url_edital":      im.url_edital,
        "valor_minimo":    im.edital.valor_minimo,
        "valor_avaliacao": im.edital.valor_avaliacao,
        "desconto_pct":    im.edital.desconto_pct,
        "modalidade":         im.edital.modalidade_venda,
        "financiamento":      im.edital.financiamento,
        "comissao_leiloeiro": im.edital.comissao_leiloeiro,
    }
    analises_salvas = (
        session.query(AnaliseFinanceira)
        .filter(
            AnaliseFinanceira.imovel_id == imovel_id,
            or_(AnaliseFinanceira.user_id == USER_ID, AnaliseFinanceira.user_id.is_(None)),
        )
        .order_by(AnaliseFinanceira.versao.desc())
        .all()
    )
    analises_salvas = [
        {
            "Versão":    a.versao,
            "Data":      a.criado_em.strftime("%d/%m/%Y %H:%M") if a.criado_em else "—",
            "Mercado":   f"R$ {float(a.valor_mercado):,.2f}" if a.valor_mercado else "—",
            "Reforma":   f"R$ {float(a.custo_reforma):,.2f}" if a.custo_reforma else "—",
            "Margem":    f"{float(a.margem_liquida_pct):.1f}%" if a.margem_liquida_pct else "—",
            "Resultado": "✓ Viável" if a.resultado == "viavel" else "✗ Não viável",
            "Fonte":     a.fonte_valor_mercado or "—",
        }
        for a in analises_salvas
    ]

# ── Cabeçalho ────────────────────────────────────────────────────────────────
st.title(f"Imóvel {id_externo}")
st.caption(f"{dados['endereco']}, {dados['bairro']} — {dados['cidade']}/{dados['uf']}")

# ── Análises salvas ───────────────────────────────────────────────────────────
if analises_salvas:
    with st.expander(f"📊 Análises salvas ({len(analises_salvas)})", expanded=True):
        st.dataframe(
            pd.DataFrame(analises_salvas),
            use_container_width=True,
            hide_index=True,
        )
else:
    st.caption("Nenhuma análise salva para este imóvel ainda.")

with st.expander("Dados do edital", expanded=True):
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Preço mínimo", _fmt(dados["valor_minimo"]))
    c2.metric("Avaliação",    _fmt(dados["valor_avaliacao"]))
    c3.metric("Desconto",     f"{float(dados['desconto_pct']):.1f}%" if dados["desconto_pct"] else "—")
    c4.metric("Tipo",         dados["tipo"] or "—")
    c5, c6 = st.columns(2)
    c5.write(f"**Modalidade:** {dados['modalidade'] or '—'}")
    c5.write(f"**Financiamento:** {dados['financiamento'] or '—'}")
    if dados["url_edital"]:
        c6.link_button("Abrir edital original ↗", dados["url_edital"])

# ── Bloco 2 — Inputs ──────────────────────────────────────────────────────────
st.subheader("Inputs para a análise")
inputs = _coletar_inputs_manuais(dados)

# ── Bloco 3 — Cálculo ────────────────────────────────────────────────────────
if st.button("Calcular viabilidade", type="primary", disabled=inputs["valor_mercado"] <= 0):
    entrada = EntradaViabilidade(
        valor_arremate=Decimal(str(dados["valor_minimo"])),
        valor_mercado=Decimal(str(inputs["valor_mercado"])),
        cidade=dados["cidade"] or "",
        comissao_leiloeiro_pct=Decimal(str(dados["comissao_leiloeiro"] or COMISSAO_LEILOEIRO_DEFAULT)),
        comissao_corretor_pct=Decimal(str(inputs["comissao_corretor"])),
        meses_carregamento=inputs["meses_carregamento"],
        margem_minima_pct=Decimal(str(inputs["margem_minima"])),
        iptu_debito=Decimal(str(inputs["iptu_debito"])),
        condominio_debito=Decimal(str(inputs["condominio_debito"])),
        iptu_mensal=Decimal(str(inputs["iptu_mensal"])),
        condominio_mensal=Decimal(str(inputs["condominio_mensal"])),
        custo_advogado=Decimal(str(inputs["custo_advogado"])),
        custo_reforma=Decimal(str(inputs["custo_reforma"])),
        outros_custos=Decimal(str(inputs["outros_custos"])),
    )
    st.session_state["resultado"] = calcular(entrada)
    st.session_state["inputs_snapshot"] = inputs
    st.session_state["resultado_imovel_id"] = imovel_id

if "resultado" in st.session_state:
    _exibir_resultado(
        st.session_state["resultado"],
        imovel_id,
        st.session_state["inputs_snapshot"],
        dados,
    )
