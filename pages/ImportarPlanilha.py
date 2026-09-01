"""
Upload da planilha de leilões da Caixa + histórico de importações.

PONTO DE RESTRIÇÃO FUTURA: esta página deve ficar restrita a administradores
quando o controle de acesso for implementado — hoje qualquer usuário da
instância consegue disparar uma importação.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app.db import SessionLocal, USER_ID
from app.importers.caixa import importar_planilha_caixa_com_historico
from app.models import ImportacaoPlanilha, StatusImportacao

st.set_page_config(page_title="Importar Planilha", page_icon="📥", layout="wide")

# ── CSS: oculta botões de toolbar exceto fullscreen ───────────────────────────
st.markdown("""
<style>
[data-testid="stElementToolbarButton"]:not([title*="screen"]):not([title*="tela"]) {
    display: none !important;
}
</style>
""", unsafe_allow_html=True)

st.title("Importar planilha — Caixa")
st.caption("🔒 Página de administração — restrição de acesso a implementar em versão futura.")

# ── Upload ───────────────────────────────────────────────────────────────────
arquivo = st.file_uploader(
    "Planilha de leilões da Caixa (.csv ou .xlsx)",
    type=["csv", "xlsx"],
    help="Baixe em leiloes.caixa.gov.br e envie o arquivo aqui.",
)

if st.button("Importar", type="primary", disabled=arquivo is None):
    arquivo.seek(0)
    with SessionLocal() as session:
        registro = importar_planilha_caixa_com_historico(
            arquivo, arquivo.name, session, usuario=USER_ID
        )

    if registro.status == StatusImportacao.sucesso:
        data_fmt = registro.data_geracao.strftime("%d/%m/%Y") if registro.data_geracao else "não identificada"
        st.success(
            f"Importação concluída (planilha de {data_fmt}): "
            f"{registro.imoveis_importados} novo(s), "
            f"{registro.imoveis_atualizados} atualizado(s), "
            f"{registro.imoveis_desativados} desativado(s) por não constarem mais na planilha, "
            f"{registro.imoveis_ignorados} linha(s) ignorada(s)."
        )
        if registro.avisos:
            st.warning(registro.avisos)
    else:
        st.error(f"Falha na importação: {registro.mensagem_erro}")

st.divider()

# ── Histórico ────────────────────────────────────────────────────────────────
st.subheader("Histórico de importações")


def _carregar_historico() -> list[ImportacaoPlanilha]:
    with SessionLocal() as session:
        return (
            session.query(ImportacaoPlanilha)
            .order_by(ImportacaoPlanilha.iniciado_em.desc())
            .limit(100)
            .all()
        )


historico = _carregar_historico()

if not historico:
    st.caption("Nenhuma importação registrada ainda.")
else:
    df_historico = pd.DataFrame([
        {
            "Status":      "✅ Sucesso" if h.status == StatusImportacao.sucesso else "❌ Erro",
            "Data/hora":   h.iniciado_em.strftime("%d/%m/%Y %H:%M") if h.iniciado_em else "—",
            "Geração":     h.data_geracao.strftime("%d/%m/%Y") if h.data_geracao else "—",
            "UFs":         h.ufs_processadas or "—",
            "Arquivo":     h.nome_arquivo,
            "Usuário":     h.usuario or "—",
            "Novos":       str(h.imoveis_importados) if h.imoveis_importados is not None else "—",
            "Atualizados": str(h.imoveis_atualizados) if h.imoveis_atualizados is not None else "—",
            "Desativados": str(h.imoveis_desativados) if h.imoveis_desativados is not None else "—",
            "Ignorados":   str(h.imoveis_ignorados) if h.imoveis_ignorados is not None else "—",
            "Avisos":      h.avisos or "—",
            "Erro":        h.mensagem_erro or "—",
        }
        for h in historico
    ])
    st.dataframe(df_historico, use_container_width=True, hide_index=True)
