"""Testa o importador da planilha Caixa com um DataFrame sintético."""

import io
from unittest.mock import MagicMock, call

import pandas as pd
import pytest

from app.importers.caixa import (
    COLUNAS,
    _decimal_br,
    _desconto,
    _tipo_da_descricao,
    importar_planilha_caixa,
    importar_planilha_caixa_com_historico,
)
from app.models import Edital, Imovel, StatusImportacao


def _planilha_fake(linhas: list[dict]) -> io.BytesIO:
    """Gera um .xlsx em memória com as colunas reais da Caixa."""
    df = pd.DataFrame(linhas)
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    buf.seek(0)
    return buf


# ---------------------------------------------------------------------------
# Helpers unitários
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
# Integração com session mockada
# ---------------------------------------------------------------------------

def _session_mock_sem_duplicata():
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = None
    session.flush.side_effect = lambda: None
    return session


def test_importa_linha_basica():
    linha = {
        "N° do imóvel":       "MG-12345",
        "UF":                 "MG",
        "Cidade":             "Belo Horizonte",
        "Bairro":             "Pampulha",
        "Endereço":           "Av. Antônio Carlos, 100",
        "Preço":              "R$ 250.000,00",
        "Valor de avaliação": "R$ 300.000,00",
        "Desconto":           "16,67%",
        "Financiamento":      "FGTS/Financiamento",
        "Descrição":          "APARTAMENTO 2/4 COM VAGA",
        "Modalidade de venda":"Licitação Aberta",
        "Link de acesso":     "https://leiloes.caixa.gov.br/edital/MG-12345",
    }
    session = _session_mock_sem_duplicata()
    importados, ignorados = importar_planilha_caixa(_planilha_fake([linha]), session)

    assert importados == 1
    assert ignorados == 0

    imovel: Imovel = session.add.call_args_list[0][0][0]
    assert imovel.fonte == "caixa"
    assert imovel.id_externo == "MG-12345"
    assert imovel.tipo == "residencial"
    assert imovel.cidade == "Belo Horizonte"
    assert imovel.uf == "MG"

    edital: Edital = session.add.call_args_list[1][0][0]
    assert float(edital.valor_minimo) == 250_000.0
    assert float(edital.valor_avaliacao) == 300_000.0
    assert float(edital.desconto_pct) == pytest.approx(16.67, rel=1e-2)
    assert edital.financiamento == "FGTS/Financiamento"
    assert edital.modalidade_venda == "Licitação Aberta"


def test_importa_linha_com_caracteristicas_da_descricao():
    linha = {
        "N° do imóvel":       "MG-99999",
        "UF":                 "MG", "Cidade": "BH", "Bairro": "X",
        "Endereço":           "Rua A", "Preço": "100.000,00",
        "Valor de avaliação": "120.000,00", "Desconto": "16%",
        "Financiamento":      "Sim",
        "Descrição": (
            "Apartamento, 78.72 de área total, 44.45 de área privativa, "
            "0.00 de área do terreno, 2 qto(s), WC, 1 sala(s), cozinha, "
            "1 vaga(s) de garagem."
        ),
        "Modalidade de venda": "Leilão", "Link de acesso": "http://x",
    }
    session = _session_mock_sem_duplicata()
    importar_planilha_caixa(_planilha_fake([linha]), session)

    imovel: Imovel = session.add.call_args_list[0][0][0]
    assert float(imovel.area_total_m2) == 78.72
    assert float(imovel.area_privativa_m2) == 44.45
    assert imovel.area_terreno_m2 is None
    assert imovel.quartos == 2
    assert imovel.salas == 1
    assert imovel.vagas_garagem == 1
    assert imovel.possui_wc is True
    assert imovel.possui_cozinha is True
    assert imovel.descricao_parsing_incompleto is False


def test_importa_linha_com_descricao_fora_do_padrao_marca_incompleto():
    linha = {
        "N° do imóvel":       "MG-88888",
        "UF":                 "MG", "Cidade": "BH", "Bairro": "X",
        "Endereço":           "Rua A", "Preço": "100.000,00",
        "Valor de avaliação": "120.000,00", "Desconto": "16%",
        "Financiamento":      "Sim",
        "Descrição":          "Formato totalmente diferente do esperado",
        "Modalidade de venda": "Leilão", "Link de acesso": "http://x",
    }
    session = _session_mock_sem_duplicata()
    importar_planilha_caixa(_planilha_fake([linha]), session)

    imovel: Imovel = session.add.call_args_list[0][0][0]
    assert imovel.descricao_parsing_incompleto is True
    assert imovel.area_total_m2 is None
    assert imovel.quartos is None


def test_idempotente_duplicata():
    linha = {
        "N° do imóvel": "MG-12345",
        "UF": "MG", "Cidade": "BH", "Bairro": "X",
        "Endereço": "Rua A", "Preço": "100.000,00",
        "Valor de avaliação": "120.000,00", "Desconto": "16%",
        "Financiamento": "Sim", "Descrição": "CASA",
        "Modalidade de venda": "Leilão", "Link de acesso": "http://x",
    }
    session = MagicMock()
    # simula imóvel já existente
    session.query.return_value.filter_by.return_value.first.return_value = object()

    importados, ignorados = importar_planilha_caixa(_planilha_fake([linha]), session)

    assert importados == 0
    assert ignorados == 1
    session.add.assert_not_called()


def test_le_planilha_csv_via_upload_sem_path():
    """Reproduz o upload do Streamlit: objeto tipo arquivo com `.name`, não
    um `str`/`Path` — precisa ser detectado como CSV mesmo assim."""
    conteudo = (
        "\n"
        " Lista de Imóveis da Caixa;;Data de geração:;01/01/2026;;;;;;;\n"
        " N° do imóvel;UF;Cidade;Bairro;Endereço;Preço;Valor de avaliação;"
        "Desconto;Financiamento;Descrição;Modalidade de venda;Link de acesso\n"
        "\n"
        " TESTE-CSV-001 ;MG ;BH ;X ;Rua A ;100.000,00;120.000,00;16.67;Não;"
        "Apartamento, 78.72 de área total, 44.45 de área privativa, 0.00 de "
        "área do terreno,  2 qto(s), WC, 1 sala(s), cozinha, 1 vaga(s) de "
        "garagem.;Licitação Aberta;http://x\n"
    ).encode("latin-1")
    upload = io.BytesIO(conteudo)
    upload.name = "planilha.csv"  # atributo exposto pelo UploadedFile do Streamlit

    session = _session_mock_sem_duplicata()
    importados, ignorados = importar_planilha_caixa(upload, session)

    assert importados == 1
    imovel: Imovel = session.add.call_args_list[0][0][0]
    assert imovel.id_externo == "TESTE-CSV-001"
    assert imovel.quartos == 2


# ---------------------------------------------------------------------------
# Wrapper com histórico
# ---------------------------------------------------------------------------

def test_wrapper_com_historico_registra_sucesso():
    linha = {
        "N° do imóvel": "MG-77777",
        "UF": "MG", "Cidade": "BH", "Bairro": "X",
        "Endereço": "Rua A", "Preço": "100.000,00",
        "Valor de avaliação": "120.000,00", "Desconto": "16%",
        "Financiamento": "Sim", "Descrição": "CASA",
        "Modalidade de venda": "Leilão", "Link de acesso": "http://x",
    }
    session = _session_mock_sem_duplicata()

    registro = importar_planilha_caixa_com_historico(
        _planilha_fake([linha]), "planilha.xlsx", session, usuario="flavio"
    )

    assert registro.status == StatusImportacao.sucesso
    assert registro.imoveis_importados == 1
    assert registro.imoveis_ignorados == 0
    assert registro.nome_arquivo == "planilha.xlsx"
    assert registro.usuario == "flavio"
    assert registro.finalizado_em is not None
    assert registro.mensagem_erro is None
    session.commit.assert_called()


def test_wrapper_com_historico_registra_erro_sem_propagar_excecao():
    arquivo_invalido = io.BytesIO(b"isto nao e um xlsx valido")
    arquivo_invalido.name = "planilha.xlsx"
    session = _session_mock_sem_duplicata()

    registro = importar_planilha_caixa_com_historico(
        arquivo_invalido, "planilha.xlsx", session
    )

    assert registro.status == StatusImportacao.erro
    assert registro.mensagem_erro
    assert registro.imoveis_importados is None
    assert registro.finalizado_em is not None
    session.rollback.assert_called_once()
    session.commit.assert_called()


def test_linha_sem_numero_ignorada():
    linha = {
        "N° do imóvel": "", "UF": "MG", "Cidade": "BH", "Bairro": "X",
        "Endereço": "Rua A", "Preço": "100.000,00",
        "Valor de avaliação": "120.000,00", "Desconto": "16%",
        "Financiamento": "Sim", "Descrição": "CASA",
        "Modalidade de venda": "Leilão", "Link de acesso": "http://x",
    }
    session = _session_mock_sem_duplicata()
    importados, ignorados = importar_planilha_caixa(_planilha_fake([linha]), session)

    assert importados == 0
    assert ignorados == 1
