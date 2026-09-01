"""Testa o importador da planilha Caixa.

A planilha é tratada como fonte da verdade (ver docstring de
app/importers/caixa.py): imóveis que somem de uma nova importação são
desativados, características que mudam são atualizadas, e uma planilha mais
antiga que a última já aplicada para uma UF é ignorada. Os testes de
sincronização (criação/atualização/desativação/trava por data) rodam contra o
Postgres local de desenvolvimento (mesmo banco usado pelas migrations, ver
tests/conftest.py) — usam UFs sintéticas (`ZZ`/`YY`, não correspondem a
nenhum estado real) para nunca colidir com dados reais importados (ex: MG).
"""

from __future__ import annotations

import io
from datetime import date

import pandas as pd
import pytest

from app.importers.caixa import (
    COLUNAS,
    _decimal_br,
    _desconto,
    _extrair_data_geracao,
    _ler_planilha,
    _localizar_linha_cabecalho,
    _tipo_da_descricao,
    importar_planilha_caixa,
    importar_planilha_caixa_com_historico,
)
from app.models import Edital, Imovel, StatusImportacao

FONTE = "caixa"
UFS_TESTE = ["ZZ", "YY"]


# ---------------------------------------------------------------------------
# Helpers de construção de planilha fake
# ---------------------------------------------------------------------------

def _linha(**overrides) -> dict:
    base = {
        "N° do imóvel":        "ID-0001",
        "UF":                  "ZZ",
        "Cidade":              "Cidade Teste",
        "Bairro":              "Bairro Teste",
        "Endereço":            "Rua Teste, 100",
        "Preço":               "100.000,00",
        "Valor de avaliação":  "120.000,00",
        "Desconto":            "16,67%",
        "Financiamento":       "Sim",
        "Descrição":           "CASA",
        "Modalidade de venda": "Leilão",
        "Link de acesso":      "http://x",
    }
    base.update(overrides)
    return base


def _planilha_fake(linhas: list[dict]) -> io.BytesIO:
    """.xlsx sem linha de título/data de geração (cabeçalho na 1ª linha)."""
    df = pd.DataFrame(linhas)
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    buf.seek(0)
    return buf


def _csv_fake(linhas: list[dict], data_geracao: str = "01/01/2026") -> io.BytesIO:
    """.csv no formato real da Caixa: linha em branco, título com 'Data de
    geração', cabeçalho, linha em branco, dados — tudo separado por ';'."""
    colunas = list(COLUNAS.keys())
    linha_titulo = f" Lista de Imóveis da Caixa;;Data de geração:;{data_geracao};;;;;;;"
    linha_cabecalho = " " + ";".join(colunas)
    linhas_dados = [
        " " + ";".join(str(l.get(c, "") or "") for c in colunas) for l in linhas
    ]
    texto = "\n".join(["", linha_titulo, linha_cabecalho, "", *linhas_dados]) + "\n"
    buf = io.BytesIO(texto.encode("latin-1"))
    buf.name = "planilha.csv"
    return buf


# ---------------------------------------------------------------------------
# Helpers unitários (sem I/O)
# ---------------------------------------------------------------------------

def test_decimal_br_formatos():
    assert _decimal_br("R$ 1.234.567,89") == 1_234_567.89
    assert _decimal_br("250.000,00") == 250_000.0
    assert _decimal_br("0") == 0.0
    assert _decimal_br(None) is None
    assert _decimal_br("nan") is None


def test_desconto_formatos():
    assert _desconto("20%") == 20.0
    assert _desconto("0,20") == 20.0
    assert _desconto("15,5%") == 15.5
    assert _desconto(None) is None


def test_tipo_da_descricao():
    assert _tipo_da_descricao("APARTAMENTO 2/4 BAIRRO X") == "residencial"
    assert _tipo_da_descricao("TERRENO SEM BENFEITORIAS") == "terreno"
    assert _tipo_da_descricao("SALA COMERCIAL ANDAR 3") == "comercial"
    assert _tipo_da_descricao("LOTE URBANO") == "terreno"
    assert _tipo_da_descricao(None) is None


# ---------------------------------------------------------------------------
# Leitura da planilha: cabeçalho + "Data de geração"
# ---------------------------------------------------------------------------

def test_le_csv_extrai_data_de_geracao_e_colunas():
    buf = _csv_fake([_linha(**{"N° do imóvel": "TESTE-CSV-001"})], data_geracao="13/08/2026")
    df, data_geracao = _ler_planilha(buf, 0)

    assert data_geracao == date(2026, 8, 13)
    assert list(df.columns) == list(COLUNAS.keys())
    assert len(df) == 1
    assert df.iloc[0]["N° do imóvel"].strip() == "TESTE-CSV-001"


def test_xlsx_sem_linha_de_titulo_nao_tem_data_de_geracao():
    buf = _planilha_fake([_linha()])
    df, data_geracao = _ler_planilha(buf, 0)

    assert data_geracao is None
    assert len(df) == 1


def test_localizar_cabecalho_ignora_linhas_em_branco_e_titulo():
    linhas = [
        [],
        ["Lista de Imóveis da Caixa", "", "Data de geração:", "01/01/2026"],
        list(COLUNAS.keys()),
        [],
        ["ID-1", "ZZ"],
    ]
    assert _localizar_linha_cabecalho(linhas) == 2


def test_extrair_data_geracao_nao_encontrada_retorna_none():
    linhas = [list(COLUNAS.keys()), ["ID-1", "ZZ"]]
    assert _extrair_data_geracao(linhas) is None


# ---------------------------------------------------------------------------
# Parsing de características (via importação real, cabeçalho sem título)
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _isolar_ufs_teste(db_session):
    """Garante que nenhum teste desta suíte deixa (ou herda) resíduo nas UFs
    sintéticas usadas — nunca toca dados reais (ex: uf='MG')."""
    _limpar_ufs(db_session)
    yield
    _limpar_ufs(db_session)


def _limpar_ufs(session, ufs: list[str] = UFS_TESTE) -> None:
    imovel_ids = [
        row[0]
        for row in session.query(Imovel.id).filter(Imovel.fonte == FONTE, Imovel.uf.in_(ufs)).all()
    ]
    if imovel_ids:
        session.query(Edital).filter(Edital.imovel_id.in_(imovel_ids)).delete(synchronize_session=False)
        session.query(Imovel).filter(Imovel.id.in_(imovel_ids)).delete(synchronize_session=False)
    session.commit()


def _get(session, id_externo: str) -> Imovel:
    return session.query(Imovel).filter_by(fonte=FONTE, id_externo=id_externo).one()


def test_importa_linha_com_caracteristicas_da_descricao(db_session):
    linha = _linha(
        **{
            "N° do imóvel": "ID-CARACT",
            "Descrição": (
                "Apartamento, 78.72 de área total, 44.45 de área privativa, "
                "0.00 de área do terreno, 2 qto(s), WC, 1 sala(s), cozinha, "
                "1 vaga(s) de garagem."
            ),
        }
    )
    importar_planilha_caixa(_planilha_fake([linha]), db_session)

    imovel = _get(db_session, "ID-CARACT")
    assert float(imovel.area_total_m2) == 78.72
    assert float(imovel.area_privativa_m2) == 44.45
    assert imovel.area_terreno_m2 is None
    assert imovel.quartos == 2
    assert imovel.salas == 1
    assert imovel.vagas_garagem == 1
    assert imovel.possui_wc is True
    assert imovel.possui_cozinha is True
    assert imovel.descricao_parsing_incompleto is False


def test_importa_linha_com_descricao_fora_do_padrao_marca_incompleto(db_session):
    linha = _linha(**{"N° do imóvel": "ID-INCOMPLETO", "Descrição": "Formato totalmente diferente"})
    importar_planilha_caixa(_planilha_fake([linha]), db_session)

    imovel = _get(db_session, "ID-INCOMPLETO")
    assert imovel.descricao_parsing_incompleto is True
    assert imovel.area_total_m2 is None
    assert imovel.quartos is None


def test_linha_sem_numero_ignorada(db_session):
    linha = _linha(**{"N° do imóvel": ""})
    resultado = importar_planilha_caixa(_planilha_fake([linha]), db_session)

    assert resultado.criados == 0
    assert resultado.ignorados == 1


# ---------------------------------------------------------------------------
# Planilha como fonte da verdade: criação, atualização, desativação
# ---------------------------------------------------------------------------

def test_cria_imoveis_novos(db_session):
    linhas = [_linha(**{"N° do imóvel": "ID-A"}), _linha(**{"N° do imóvel": "ID-B"})]
    resultado = importar_planilha_caixa(_csv_fake(linhas, data_geracao="01/01/2026"), db_session)

    assert resultado.criados == 2
    assert resultado.atualizados == 0
    assert resultado.desativados == 0
    assert resultado.data_geracao == date(2026, 1, 1)

    for id_externo in ("ID-A", "ID-B"):
        imovel = _get(db_session, id_externo)
        assert imovel.ativo is True
        assert imovel.data_planilha_origem == date(2026, 1, 1)
        assert imovel.edital is not None


def test_imovel_ausente_na_nova_planilha_e_desativado(db_session):
    importar_planilha_caixa(
        _csv_fake([_linha(**{"N° do imóvel": "ID-A"}), _linha(**{"N° do imóvel": "ID-B"})], "01/01/2026"),
        db_session,
    )

    resultado = importar_planilha_caixa(
        _csv_fake([_linha(**{"N° do imóvel": "ID-A"})], "02/01/2026"), db_session
    )

    assert resultado.desativados == 1
    assert resultado.atualizados == 1

    imovel_a = _get(db_session, "ID-A")
    assert imovel_a.ativo is True

    imovel_b = _get(db_session, "ID-B")
    assert imovel_b.ativo is False
    assert imovel_b.desativado_em is not None


def test_caracteristica_alterada_prevalece_a_ultima_importacao(db_session):
    importar_planilha_caixa(
        _csv_fake([_linha(**{"N° do imóvel": "ID-A", "Preço": "100.000,00"})], "01/01/2026"),
        db_session,
    )
    importar_planilha_caixa(
        _csv_fake([_linha(**{"N° do imóvel": "ID-A", "Preço": "150.000,00"})], "02/01/2026"),
        db_session,
    )

    imovel = _get(db_session, "ID-A")
    assert float(imovel.edital.valor_minimo) == 150_000.0
    assert imovel.data_planilha_origem == date(2026, 1, 2)


def test_imovel_desativado_reaparece_e_e_reativado(db_session):
    importar_planilha_caixa(
        _csv_fake([_linha(**{"N° do imóvel": "ID-A"}), _linha(**{"N° do imóvel": "ID-B"})], "01/01/2026"),
        db_session,
    )
    importar_planilha_caixa(_csv_fake([_linha(**{"N° do imóvel": "ID-A"})], "02/01/2026"), db_session)
    assert _get(db_session, "ID-B").ativo is False

    importar_planilha_caixa(
        _csv_fake([_linha(**{"N° do imóvel": "ID-A"}), _linha(**{"N° do imóvel": "ID-B"})], "03/01/2026"),
        db_session,
    )

    imovel_b = _get(db_session, "ID-B")
    assert imovel_b.ativo is True
    assert imovel_b.desativado_em is None
    assert imovel_b.data_planilha_origem == date(2026, 1, 3)


def test_planilha_mais_antiga_e_ignorada(db_session):
    importar_planilha_caixa(
        _csv_fake([_linha(**{"N° do imóvel": "ID-A", "Preço": "100.000,00"})], "10/01/2026"),
        db_session,
    )

    resultado = importar_planilha_caixa(
        _csv_fake(
            [_linha(**{"N° do imóvel": "ID-A", "Preço": "999.000,00"}), _linha(**{"N° do imóvel": "ID-NOVO"})],
            "05/01/2026",
        ),
        db_session,
    )

    assert resultado.ufs_ignoradas_planilha_antiga == ["ZZ"]
    assert resultado.criados == 0
    assert resultado.atualizados == 0
    assert resultado.ignorados == 2

    imovel = _get(db_session, "ID-A")
    assert float(imovel.edital.valor_minimo) == 100_000.0  # não sobrescrito
    assert imovel.data_planilha_origem == date(2026, 1, 10)  # planilha antiga não avança/retrocede a data

    with pytest.raises(Exception):
        _get(db_session, "ID-NOVO")  # nunca criado


def test_planilha_com_mesma_data_de_geracao_e_reaplicada(db_session):
    importar_planilha_caixa(
        _csv_fake([_linha(**{"N° do imóvel": "ID-A", "Preço": "100.000,00"})], "10/01/2026"),
        db_session,
    )
    resultado = importar_planilha_caixa(
        _csv_fake([_linha(**{"N° do imóvel": "ID-A", "Preço": "200.000,00"})], "10/01/2026"),
        db_session,
    )

    assert resultado.ufs_ignoradas_planilha_antiga == []
    assert resultado.atualizados == 1
    assert float(_get(db_session, "ID-A").edital.valor_minimo) == 200_000.0


def test_planilha_antiga_nao_desativa_imoveis_da_uf(db_session):
    importar_planilha_caixa(
        _csv_fake([_linha(**{"N° do imóvel": "ID-A"}), _linha(**{"N° do imóvel": "ID-B"})], "10/01/2026"),
        db_session,
    )

    resultado = importar_planilha_caixa(
        _csv_fake([_linha(**{"N° do imóvel": "ID-A"})], "05/01/2026"), db_session
    )

    assert resultado.desativados == 0
    assert _get(db_session, "ID-B").ativo is True


def test_ufs_sao_independentes_no_mesmo_dia(db_session):
    importar_planilha_caixa(
        _csv_fake([_linha(**{"N° do imóvel": "ID-A", "UF": "ZZ"})], "01/01/2026"), db_session
    )
    importar_planilha_caixa(
        _csv_fake([_linha(**{"N° do imóvel": "ID-X", "UF": "YY"})], "01/01/2026"), db_session
    )

    # a planilha de YY não vê (nem desativa) o imóvel de ZZ, e vice-versa
    assert _get(db_session, "ID-A").ativo is True
    assert _get(db_session, "ID-X").ativo is True

    resultado = importar_planilha_caixa(
        _csv_fake([_linha(**{"N° do imóvel": "ID-NOVO-YY", "UF": "YY"})], "02/01/2026"), db_session
    )

    assert resultado.desativados == 1  # só o ID-X (de YY) some; ID-A (ZZ) não é tocado
    assert _get(db_session, "ID-A").ativo is True
    assert _get(db_session, "ID-X").ativo is False


def test_sem_data_de_geracao_nao_desativa_ausentes(db_session):
    importar_planilha_caixa(
        _planilha_fake([_linha(**{"N° do imóvel": "ID-A"}), _linha(**{"N° do imóvel": "ID-B"})]),
        db_session,
    )
    resultado = importar_planilha_caixa(_planilha_fake([_linha(**{"N° do imóvel": "ID-A"})]), db_session)

    assert resultado.data_geracao is None
    assert resultado.desativados == 0
    assert _get(db_session, "ID-B").ativo is True


# ---------------------------------------------------------------------------
# Wrapper com histórico
# ---------------------------------------------------------------------------

def test_wrapper_com_historico_registra_sucesso(db_session):
    linhas = [_linha(**{"N° do imóvel": "ID-HIST-A"}), _linha(**{"N° do imóvel": "ID-HIST-B"})]
    registro = importar_planilha_caixa_com_historico(
        _csv_fake(linhas, data_geracao="15/01/2026"), "planilha.csv", db_session, usuario="flavio"
    )

    assert registro.status == StatusImportacao.sucesso
    assert registro.data_geracao == date(2026, 1, 15)
    assert registro.imoveis_importados == 2
    assert registro.imoveis_atualizados == 0
    assert registro.imoveis_desativados == 0
    assert registro.imoveis_ignorados == 0
    assert registro.nome_arquivo == "planilha.csv"
    assert registro.usuario == "flavio"
    assert registro.mensagem_erro is None


def test_wrapper_com_historico_avisa_planilha_antiga(db_session):
    importar_planilha_caixa(
        _csv_fake([_linha(**{"N° do imóvel": "ID-A"})], "10/01/2026"), db_session
    )
    registro = importar_planilha_caixa_com_historico(
        _csv_fake([_linha(**{"N° do imóvel": "ID-A"})], "05/01/2026"), "antiga.csv", db_session
    )

    assert registro.status == StatusImportacao.sucesso
    assert registro.avisos
    assert "ZZ" in registro.avisos


def test_wrapper_com_historico_registra_erro_sem_propagar_excecao(db_session):
    arquivo_invalido = io.BytesIO(b"isto nao e um xlsx valido")
    arquivo_invalido.name = "planilha.xlsx"

    registro = importar_planilha_caixa_com_historico(arquivo_invalido, "planilha.xlsx", db_session)

    assert registro.status == StatusImportacao.erro
    assert registro.mensagem_erro
    assert registro.imoveis_importados is None
    assert registro.finalizado_em is not None
