import streamlit as st
import pandas as pd
from sqlalchemy import text

from app.db import engine, USER_ID, aplicar_migrations

st.set_page_config(
    page_title="Alvo Leilões",
    page_icon="🏚",
    layout="wide",
)

# ── CSS: oculta botões de toolbar exceto fullscreen ───────────────────────────
# Usa exclusão por substring do title para funcionar em qualquer locale:
#   EN: "View fullscreen" (contém "screen")
#   PT: "Ver em tela cheia" (contém "tela")
st.markdown("""
<style>
[data-testid="stElementToolbarButton"]:not([title*="screen"]):not([title*="tela"]) {
    display: none !important;
}
</style>
""", unsafe_allow_html=True)

@st.cache_resource(show_spinner="Verificando banco de dados...")
def _init_db():
    aplicar_migrations()

_init_db()

st.title("Alvo Leilões")
st.caption("Triagem de imóveis em leilão")


@st.cache_data(ttl=300)
def carregar_imoveis() -> pd.DataFrame:
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT
                i.id,
                i.id_externo        AS num_imovel,
                i.cidade,
                i.bairro,
                i.tipo,
                i.endereco,
                i.url_edital,
                e.valor_minimo,
                e.valor_avaliacao,
                e.desconto_pct,
                e.modalidade_venda,
                e.financiamento
            FROM imoveis i
            JOIN editais e ON e.imovel_id = i.id
            ORDER BY i.cidade, i.bairro
        """)).fetchall()
    return pd.DataFrame(rows, columns=[
        "id", "num_imovel", "cidade", "bairro", "tipo",
        "endereco", "url_edital", "valor_minimo", "valor_avaliacao",
        "desconto_pct", "modalidade_venda", "financiamento",
    ])


def carregar_contagens_analises() -> dict:
    """Retorna {imovel_id: count} para o usuário atual. Sem cache — muda ao salvar."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT imovel_id, COUNT(*) AS cnt
            FROM analises_financeiras
            WHERE user_id = :uid OR user_id IS NULL
            GROUP BY imovel_id
        """), {"uid": USER_ID}).fetchall()
    return {row[0]: row[1] for row in rows}


df = carregar_imoveis()
contagens = carregar_contagens_analises()
df["analises"] = df["id"].map(contagens).fillna(0).astype(int)

# ── Filtros ───────────────────────────────────────────────────────────────────
# Padrão de persistência: sem key= nos widgets; valores salvos em chaves
# manuais de session_state (prefixo _f_) que sobrevivem à navegação entre páginas.
with st.sidebar:
    st.header("Filtros")

    opcoes_cidade = sorted(df["cidade"].dropna().unique())
    sel_cidade = st.multiselect(
        "Cidade",
        opcoes_cidade,
        default=[c for c in st.session_state.get("_f_cidade", []) if c in opcoes_cidade],
    )
    st.session_state["_f_cidade"] = sel_cidade

    df_para_bairro = df[df["cidade"].isin(sel_cidade)] if sel_cidade else df
    opcoes_bairro = sorted(df_para_bairro["bairro"].dropna().unique())
    sel_bairro = st.multiselect(
        "Bairro",
        opcoes_bairro,
        default=[b for b in st.session_state.get("_f_bairro", []) if b in opcoes_bairro],
    )
    st.session_state["_f_bairro"] = sel_bairro

    opcoes_tipo = sorted(df["tipo"].dropna().unique())
    sel_tipo = st.multiselect(
        "Tipo",
        opcoes_tipo,
        default=[t for t in st.session_state.get("_f_tipo", []) if t in opcoes_tipo],
    )
    st.session_state["_f_tipo"] = sel_tipo

    preco_vals = df["valor_minimo"].dropna().astype(float)
    preco_min_data = float(preco_vals.min()) if not preco_vals.empty else 0.0
    preco_max_data = float(preco_vals.max()) if not preco_vals.empty else 100_000.0
    if preco_min_data >= preco_max_data:
        preco_max_data = preco_min_data + 10_000.0
    saved_preco = st.session_state.get("_f_preco", (preco_min_data, preco_max_data))
    preco_default = (
        max(preco_min_data, min(float(saved_preco[0]), preco_max_data)),
        max(preco_min_data, min(float(saved_preco[1]), preco_max_data)),
    )
    sel_preco = st.slider(
        "Faixa de preço (R$)",
        min_value=preco_min_data,
        max_value=preco_max_data,
        value=preco_default,
        step=10_000.0,
        format="R$ %.0f",
    )
    st.session_state["_f_preco"] = sel_preco

    opcoes_modalidade = sorted(df["modalidade_venda"].dropna().unique())
    sel_modalidade = st.multiselect(
        "Modalidade",
        opcoes_modalidade,
        default=[m for m in st.session_state.get("_f_modalidade", []) if m in opcoes_modalidade],
    )
    st.session_state["_f_modalidade"] = sel_modalidade

    opcoes_analise = ["Todos", "Com análise", "Sem análise"]
    sel_analise = st.radio(
        "Análises",
        opcoes_analise,
        index=opcoes_analise.index(st.session_state.get("_f_analise", "Todos")),
        horizontal=True,
    )
    st.session_state["_f_analise"] = sel_analise

# ── Aplicar filtros ───────────────────────────────────────────────────────────
mask = pd.Series(True, index=df.index)
if sel_cidade:
    mask &= df["cidade"].isin(sel_cidade)
if sel_bairro:
    mask &= df["bairro"].isin(sel_bairro)
if sel_tipo:
    mask &= df["tipo"].isin(sel_tipo)

preco_float = df["valor_minimo"].astype(float)
mask &= (preco_float >= sel_preco[0]) & (preco_float <= sel_preco[1])

if sel_modalidade:
    mask &= df["modalidade_venda"].isin(sel_modalidade)

if sel_analise == "Com análise":
    mask &= df["analises"] > 0
elif sel_analise == "Sem análise":
    mask &= df["analises"] == 0

df_filt = df[mask].reset_index(drop=True)
st.caption(f"{len(df_filt)} imóveis encontrados")

# ── Tabela ────────────────────────────────────────────────────────────────────
df_display = pd.DataFrame({
    "📊":            df_filt["analises"].apply(lambda n: "📊" if n > 0 else ""),
    "N° do imóvel":  df_filt["num_imovel"],
    "Cidade":        df_filt["cidade"],
    "Bairro":        df_filt["bairro"],
    "Tipo":          df_filt["tipo"],
    "Preço":         df_filt["valor_minimo"].apply(lambda v: f"R$ {float(v):,.0f}" if v else "—"),
    "Desconto":      df_filt["desconto_pct"].apply(lambda v: f"{float(v):.1f}%" if v else "—"),
    "Modalidade":    df_filt["modalidade_venda"],
})

event = st.dataframe(
    df_display,
    use_container_width=True,
    on_select="rerun",
    selection_mode="single-row",
    hide_index=True,
)

if event.selection.rows:
    pos = event.selection.rows[0]
    row = df_filt.iloc[pos]
    st.info(f"**{row['num_imovel']}** — {row['endereco']}, {row['bairro']}, {row['cidade']}")
    if st.button("Abrir análise →", type="primary"):
        st.session_state["imovel_id"] = int(row["id"])
        st.switch_page("pages/Detalhe.py")
