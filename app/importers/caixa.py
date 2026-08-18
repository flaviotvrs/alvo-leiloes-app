"""
Importador da planilha de leilões da Caixa Econômica Federal.

Uso:
    from app.importers.caixa import importar_planilha_caixa
    from app.db import SessionLocal

    with SessionLocal() as session:
        importados, ignorados = importar_planilha_caixa("planilha.xlsx", session)
        session.commit()
        print(f"{importados} importados, {ignorados} já existiam.")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import IO

import pandas as pd
from sqlalchemy.orm import Session

from app.models import Edital, Imovel, ImportacaoPlanilha, StatusImportacao, TipoImovel
from app.parsers.descricao_imovel import parsear_descricao

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Mapeamento de colunas (nomes exatos da planilha Caixa)
# ---------------------------------------------------------------------------
COLUNAS: dict[str, str] = {
    "N° do imóvel":        "id_externo",
    "UF":                  "uf",
    "Cidade":              "cidade",
    "Bairro":              "bairro",
    "Endereço":            "endereco",
    "Preço":               "valor_minimo",
    "Valor de avaliação":  "valor_avaliacao",
    "Desconto":            "desconto_pct",
    "Financiamento":       "financiamento",
    "Descrição":           "descricao",
    "Modalidade de venda": "modalidade_venda",
    "Link de acesso":      "url_edital",
}

# Palavras-chave na descrição → tipo de imóvel
_TIPO_KEYWORDS: list[tuple[str, str]] = [
    ("APARTAMENTO", TipoImovel.residencial),
    ("APTO",        TipoImovel.residencial),
    ("CASA",        TipoImovel.residencial),
    ("RESIDENCIAL", TipoImovel.residencial),
    ("SALA",        TipoImovel.comercial),
    ("LOJA",        TipoImovel.comercial),
    ("COMERCIAL",   TipoImovel.comercial),
    ("GALPÃO",      TipoImovel.comercial),
    ("TERRENO",     TipoImovel.terreno),
    ("LOTE",        TipoImovel.terreno),
]


# ---------------------------------------------------------------------------
# Função principal
# ---------------------------------------------------------------------------

def importar_planilha_caixa(
    arquivo: str | Path | IO,
    session: Session,
    sheet_name: int | str = 0,
) -> tuple[int, int]:
    """Lê a planilha e persiste Imovel + Edital no banco.

    Retorna (importados, ignorados).
    Imóveis com id_externo já existente são ignorados (idempotente).
    """
    df = _ler_planilha(arquivo, sheet_name)
    df = _normalizar_colunas(df)

    importados = 0
    ignorados = 0

    for _, row in df.iterrows():
        id_externo = _str(row.get("id_externo"))
        if not id_externo:
            logger.warning("Linha sem N° do imóvel, ignorada.")
            ignorados += 1
            continue

        if session.query(Imovel).filter_by(fonte="caixa", id_externo=id_externo).first():
            ignorados += 1
            continue

        imovel = _construir_imovel(row, id_externo)
        session.add(imovel)
        session.flush()

        edital = _construir_edital(row, imovel.id)
        session.add(edital)

        importados += 1
        logger.debug("Importado imóvel Caixa %s", id_externo)

    return importados, ignorados


@dataclass
class ResultadoImportacao:
    """Snapshot do resultado, desacoplado da sessão/ORM: o registro em si é
    gravado no banco, mas o chamador não deve depender do objeto ORM (que
    expira os atributos após o commit e vira inacessível assim que a sessão
    fecha — `DetachedInstanceError`)."""

    status: str
    nome_arquivo: str
    usuario: str | None
    imoveis_importados: int | None
    imoveis_ignorados: int | None
    mensagem_erro: str | None
    finalizado_em: datetime


def importar_planilha_caixa_com_historico(
    arquivo: str | Path | IO,
    nome_arquivo: str,
    session: Session,
    usuario: str | None = None,
) -> ResultadoImportacao:
    """Executa `importar_planilha_caixa` registrando o resultado (sucesso ou
    erro) em `ImportacaoPlanilha`, para permitir conferir depois se cada
    upload rodou corretamente. Nunca propaga exceção — o erro vira parte do
    registro de histórico.
    """
    registro = ImportacaoPlanilha(
        nome_arquivo=nome_arquivo,
        usuario=usuario,
        status=StatusImportacao.erro,
    )
    try:
        importados, ignorados = importar_planilha_caixa(arquivo, session)
        registro.imoveis_importados = importados
        registro.imoveis_ignorados = ignorados
        registro.status = StatusImportacao.sucesso
    except PermissionError as e:
        session.rollback()
        registro.mensagem_erro = (
            f"Permissão negada ao ler o arquivo: {e}. No macOS isso costuma ser "
            "o app sem acesso à pasta (TCC) — libere em Ajustes do Sistema > "
            "Privacidade e Segurança > Arquivos e Pastas."
        )
        logger.exception("Falha de permissão ao importar planilha %s", nome_arquivo)
    except Exception as e:
        session.rollback()
        registro.mensagem_erro = str(e)
        logger.exception("Falha ao importar planilha %s", nome_arquivo)
    finally:
        registro.finalizado_em = datetime.now(timezone.utc).replace(tzinfo=None)
        session.add(registro)
        session.commit()

    return ResultadoImportacao(
        status=registro.status,
        nome_arquivo=registro.nome_arquivo,
        usuario=registro.usuario,
        imoveis_importados=registro.imoveis_importados,
        imoveis_ignorados=registro.imoveis_ignorados,
        mensagem_erro=registro.mensagem_erro,
        finalizado_em=registro.finalizado_em,
    )


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

def _ler_planilha(arquivo: str | Path | IO, sheet_name: int | str) -> pd.DataFrame:
    # `arquivo` pode ser um caminho (str/Path) ou um objeto tipo arquivo (ex: upload
    # do Streamlit) — nesse caso o nome original vem no atributo `.name`.
    nome = arquivo if isinstance(arquivo, (str, Path)) else getattr(arquivo, "name", "")
    if str(nome).lower().endswith(".csv"):
        # Planilha Caixa: latin-1, ponto-e-vírgula, 1ª linha é título (não cabeçalho)
        df = pd.read_csv(
            arquivo,
            sep=";",
            encoding="latin-1",
            skiprows=2,      # linha em branco + linha de título
            dtype=str,
            skipinitialspace=True,
        )
        df.columns = df.columns.str.strip()
        return df
    return pd.read_excel(arquivo, sheet_name=sheet_name, dtype=str)


def _normalizar_colunas(df: pd.DataFrame) -> pd.DataFrame:
    presentes = {c: v for c, v in COLUNAS.items() if c in df.columns}
    faltando = set(COLUNAS.keys()) - set(presentes.keys())
    if faltando:
        logger.warning("Colunas não encontradas na planilha: %s", sorted(faltando))
    return df.rename(columns=presentes)


def _construir_imovel(row: pd.Series, id_externo: str) -> Imovel:
    descricao = _str(row.get("descricao"))
    caracteristicas = parsear_descricao(descricao)
    if caracteristicas.parsing_incompleto:
        logger.warning(
            "Descrição do imóvel %s não bateu no formato conhecido: %r",
            id_externo,
            descricao,
        )

    return Imovel(
        fonte="caixa",
        id_externo=id_externo,
        url_edital=_str(row.get("url_edital")),
        tipo=_tipo_da_descricao(row.get("descricao")),
        endereco=_str(row.get("endereco")),
        bairro=_str(row.get("bairro")),
        cidade=_str(row.get("cidade")),
        uf=_str(row.get("uf")),
        descricao=descricao,
        area_total_m2=caracteristicas.area_total_m2,
        area_privativa_m2=caracteristicas.area_privativa_m2,
        area_terreno_m2=caracteristicas.area_terreno_m2,
        quartos=caracteristicas.quartos,
        salas=caracteristicas.salas,
        vagas_garagem=caracteristicas.vagas_garagem,
        possui_wc=caracteristicas.possui_wc,
        possui_cozinha=caracteristicas.possui_cozinha,
        descricao_parsing_incompleto=caracteristicas.parsing_incompleto,
    )


def _construir_edital(row: pd.Series, imovel_id: int) -> Edital:
    return Edital(
        imovel_id=imovel_id,
        valor_minimo=_decimal_br(row.get("valor_minimo")),
        valor_avaliacao=_decimal_br(row.get("valor_avaliacao")),
        desconto_pct=_desconto(row.get("desconto_pct")),
        financiamento=_str(row.get("financiamento")),
        modalidade_venda=_str(row.get("modalidade_venda")),
    )


def _tipo_da_descricao(descricao: object) -> str | None:
    if not descricao:
        return None
    upper = str(descricao).upper()
    for keyword, tipo in _TIPO_KEYWORDS:
        if keyword in upper:
            return tipo
    return None


def _str(valor: object) -> str | None:
    if valor is None:
        return None
    s = str(valor).strip()
    return s if s and s.lower() not in ("nan", "none", "") else None


def _decimal_br(valor: object):
    """Parseia valores monetários no formato brasileiro: R$ 1.234.567,89"""
    if valor is None:
        return None
    try:
        limpo = (
            str(valor)
            .replace("R$", "")
            .replace("\xa0", "")   # non-breaking space
            .replace(".", "")
            .replace(",", ".")
            .strip()
        )
        return float(limpo) if limpo and limpo not in ("nan", "") else None
    except (ValueError, AttributeError):
        return None


def _desconto(valor: object):
    """Parseia percentual de desconto: '20%' ou '0,20' → 20.0"""
    if valor is None:
        return None
    s = str(valor).replace("%", "").replace(",", ".").strip()
    try:
        v = float(s)
        return v * 100 if v < 1 else v  # normaliza fração para %
    except (ValueError, AttributeError):
        return None
