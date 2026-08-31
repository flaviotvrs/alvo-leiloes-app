"""
Importador da planilha de leilões da Caixa Econômica Federal.

A planilha é a fonte da verdade: cada importação reflete o estado atual dos
imóveis em leilão. Um imóvel que já existia no banco mas some de uma nova
importação é desativado (não retorna mais nas buscas por padrão, mas
continua no banco para preservar análises antigas); um imóvel que muda de
característica é atualizado com os dados da última planilha.

A Caixa disponibiliza uma planilha por UF, e o operador importa várias no
mesmo dia (uma por estado) — por isso a "fonte da verdade" e a desativação de
ausentes são aplicadas por UF, não por arquivo inteiro: importar a planilha
de SP não mexe nos imóveis de MG.

Cada planilha traz uma "Data de geração" na primeira linha. Ela é usada como
trava contra reimportação de arquivos desatualizados: se a data de geração da
planilha for anterior à última já aplicada para aquela UF, os dados dessa UF
na planilha são ignorados (uma importação antiga, feita por engano depois de
uma mais recente, não deve reverter dados já atualizados).

Uso:
    from app.importers.caixa import importar_planilha_caixa
    from app.db import SessionLocal

    with SessionLocal() as session:
        resultado = importar_planilha_caixa("planilha.xlsx", session)
        session.commit()
"""

from __future__ import annotations

import csv
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import IO

import pandas as pd
from sqlalchemy import func
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

_MARCADOR_DATA_GERACAO = "data de geração"
_PADRAO_DATA = re.compile(r"(\d{2})/(\d{2})/(\d{4})")
_LINHAS_CABECALHO_BUSCA = 10


# ---------------------------------------------------------------------------
# Função principal
# ---------------------------------------------------------------------------

@dataclass
class ResultadoLinhas:
    """Contagens de uma execução de `importar_planilha_caixa`."""

    criados: int = 0
    atualizados: int = 0
    desativados: int = 0
    ignorados: int = 0
    data_geracao: date | None = None
    ufs_processadas: list[str] = field(default_factory=list)
    ufs_ignoradas_planilha_antiga: list[str] = field(default_factory=list)


def importar_planilha_caixa(
    arquivo: str | Path | IO,
    session: Session,
    sheet_name: int | str = 0,
) -> ResultadoLinhas:
    """Lê a planilha e sincroniza Imovel + Edital no banco, usando a planilha
    como fonte da verdade (ver docstring do módulo).
    """
    df, data_geracao = _ler_planilha(arquivo, sheet_name)
    df = _normalizar_colunas(df)

    resultado = ResultadoLinhas(data_geracao=data_geracao)
    vistos_por_uf: dict[str, set[str]] = {}
    max_data_aplicada_por_uf: dict[str, date | None] = {}

    for _, row in df.iterrows():
        id_externo = _str(row.get("id_externo"))
        if not id_externo:
            logger.warning("Linha sem N° do imóvel, ignorada.")
            resultado.ignorados += 1
            continue

        uf = _str(row.get("uf"))

        if uf and data_geracao and _uf_esta_desatualizada(
            session, uf, data_geracao, max_data_aplicada_por_uf
        ):
            if uf not in resultado.ufs_ignoradas_planilha_antiga:
                resultado.ufs_ignoradas_planilha_antiga.append(uf)
            resultado.ignorados += 1
            continue

        if uf:
            vistos_por_uf.setdefault(uf, set()).add(id_externo)

        imovel_existente = (
            session.query(Imovel).filter_by(fonte="caixa", id_externo=id_externo).first()
        )
        if imovel_existente:
            _atualizar_imovel(imovel_existente, row, data_geracao)
            resultado.atualizados += 1
        else:
            imovel = _construir_imovel(row, id_externo, data_geracao)
            session.add(imovel)
            session.flush()
            session.add(_construir_edital(row, imovel.id))
            resultado.criados += 1

    resultado.ufs_processadas = sorted(vistos_por_uf.keys())

    if data_geracao:
        for uf, ids_vistos in vistos_por_uf.items():
            if uf in resultado.ufs_ignoradas_planilha_antiga:
                continue
            resultado.desativados += _desativar_ausentes(session, uf, ids_vistos)

    return resultado


@dataclass
class ResultadoImportacao:
    """Snapshot do resultado, desacoplado da sessão/ORM: o registro em si é
    gravado no banco, mas o chamador não deve depender do objeto ORM (que
    expira os atributos após o commit e vira inacessível assim que a sessão
    fecha — `DetachedInstanceError`)."""

    status: str
    nome_arquivo: str
    usuario: str | None
    data_geracao: date | None
    imoveis_importados: int | None
    imoveis_atualizados: int | None
    imoveis_desativados: int | None
    imoveis_ignorados: int | None
    avisos: str | None
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
        resultado = importar_planilha_caixa(arquivo, session)
        registro.data_geracao = resultado.data_geracao
        registro.ufs_processadas = ", ".join(resultado.ufs_processadas) or None
        registro.imoveis_importados = resultado.criados
        registro.imoveis_atualizados = resultado.atualizados
        registro.imoveis_desativados = resultado.desativados
        registro.imoveis_ignorados = resultado.ignorados
        registro.status = StatusImportacao.sucesso

        avisos = []
        if not resultado.data_geracao:
            avisos.append(
                "Data de geração não encontrada na planilha — imóveis ausentes "
                "não foram desativados."
            )
        if resultado.ufs_ignoradas_planilha_antiga:
            avisos.append(
                "Planilha mais antiga que a última já aplicada para: "
                + ", ".join(resultado.ufs_ignoradas_planilha_antiga)
                + " — dados dessas UFs nesta planilha foram ignorados."
            )
        registro.avisos = " ".join(avisos) or None
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
        data_geracao=registro.data_geracao,
        imoveis_importados=registro.imoveis_importados,
        imoveis_atualizados=registro.imoveis_atualizados,
        imoveis_desativados=registro.imoveis_desativados,
        imoveis_ignorados=registro.imoveis_ignorados,
        avisos=registro.avisos,
        mensagem_erro=registro.mensagem_erro,
        finalizado_em=registro.finalizado_em,
    )


# ---------------------------------------------------------------------------
# Sincronização: atualização, desativação e trava por data de geração
# ---------------------------------------------------------------------------

def _uf_esta_desatualizada(
    session: Session,
    uf: str,
    data_geracao: date,
    cache: dict[str, date | None],
) -> bool:
    """True se já existe, para essa UF, um imóvel oriundo de uma planilha
    mais recente que `data_geracao` — sinal de que esta planilha é antiga."""
    if uf not in cache:
        cache[uf] = session.query(func.max(Imovel.data_planilha_origem)).filter_by(
            fonte="caixa", uf=uf
        ).scalar()
    max_data_aplicada = cache[uf]
    return max_data_aplicada is not None and data_geracao < max_data_aplicada


def _desativar_ausentes(session: Session, uf: str, ids_vistos: set[str]) -> int:
    """Desativa (não apaga) imóveis ativos dessa UF que não vieram na
    importação atual — a planilha é a fonte da verdade."""
    ausentes = (
        session.query(Imovel)
        .filter_by(fonte="caixa", uf=uf, ativo=True)
        .filter(~Imovel.id_externo.in_(ids_vistos))
        .all()
    )
    agora = datetime.now(timezone.utc).replace(tzinfo=None)
    for imovel in ausentes:
        imovel.ativo = False
        imovel.desativado_em = agora
    return len(ausentes)


# ---------------------------------------------------------------------------
# Leitura da planilha (CSV ou XLSX) + extração de cabeçalho e data de geração
# ---------------------------------------------------------------------------

def _ler_planilha(arquivo: str | Path | IO, sheet_name: int | str) -> tuple[pd.DataFrame, date | None]:
    # `arquivo` pode ser um caminho (str/Path) ou um objeto tipo arquivo (ex: upload
    # do Streamlit) — nesse caso o nome original vem no atributo `.name`.
    nome = arquivo if isinstance(arquivo, (str, Path)) else getattr(arquivo, "name", "")
    if str(nome).lower().endswith(".csv"):
        linhas = _linhas_csv(arquivo)
    else:
        raw = pd.read_excel(arquivo, sheet_name=sheet_name, header=None, dtype=str)
        linhas = raw.values.tolist()
    return _montar_dataframe(linhas)


def _linhas_csv(arquivo: str | Path | IO) -> list[list[str]]:
    # Planilha Caixa: latin-1, separador ponto-e-vírgula, linhas com números de
    # campo variáveis (título, cabeçalho e dados têm larguras diferentes) — por
    # isso usamos o módulo `csv` em vez de `pd.read_csv`, que exige que todas as
    # linhas tenham a mesma quantidade de campos.
    if isinstance(arquivo, (str, Path)):
        conteudo = Path(arquivo).read_bytes()
    else:
        arquivo.seek(0)
        conteudo = arquivo.read()
    texto = conteudo.decode("latin-1")
    return list(csv.reader(texto.splitlines(), delimiter=";"))


def _montar_dataframe(linhas: list[list]) -> tuple[pd.DataFrame, date | None]:
    if not linhas:
        raise ValueError("Planilha vazia.")

    data_geracao = _extrair_data_geracao(linhas)
    cabecalho_idx = _localizar_linha_cabecalho(linhas)
    cabecalho = [(_str(c) or "") for c in linhas[cabecalho_idx]]
    n_colunas = len(cabecalho)

    dados = []
    for linha in linhas[cabecalho_idx + 1:]:
        if not linha or all(_str(c) is None for c in linha):
            continue
        linha_ajustada = list(linha[:n_colunas]) + [None] * (n_colunas - len(linha))
        dados.append(linha_ajustada)

    df = pd.DataFrame(dados, columns=cabecalho)
    return df, data_geracao


def _localizar_linha_cabecalho(linhas: list[list]) -> int:
    """Encontra a linha de cabeçalho procurando pelos nomes de coluna
    conhecidos — robusto a planilhas com ou sem linhas de título acima."""
    colunas_esperadas = list(COLUNAS.keys())
    limite = min(len(linhas), _LINHAS_CABECALHO_BUSCA)
    for i in range(limite):
        celulas = {(_str(c) or "").strip() for c in linhas[i]}
        acertos = sum(1 for col in colunas_esperadas if col in celulas)
        if acertos >= len(colunas_esperadas) // 2:
            return i
    raise ValueError(
        "Linha de cabeçalho não encontrada na planilha (colunas esperadas não "
        "localizadas nas primeiras linhas)."
    )


def _extrair_data_geracao(linhas: list[list]) -> date | None:
    """Lê a 'Data de geração' impressa na primeira linha da planilha da Caixa."""
    limite = min(len(linhas), _LINHAS_CABECALHO_BUSCA)
    for i in range(limite):
        linha_texto = " ".join(_str(c) or "" for c in linhas[i])
        if _MARCADOR_DATA_GERACAO in linha_texto.lower():
            m = _PADRAO_DATA.search(linha_texto)
            if not m:
                return None
            dia, mes, ano = m.groups()
            try:
                return date(int(ano), int(mes), int(dia))
            except ValueError:
                return None
    return None


def _normalizar_colunas(df: pd.DataFrame) -> pd.DataFrame:
    presentes = {c: v for c, v in COLUNAS.items() if c in df.columns}
    faltando = set(COLUNAS.keys()) - set(presentes.keys())
    if faltando:
        logger.warning("Colunas não encontradas na planilha: %s", sorted(faltando))
    return df.rename(columns=presentes)


# ---------------------------------------------------------------------------
# Construção / atualização de Imovel e Edital
# ---------------------------------------------------------------------------

def _campos_imovel(row: pd.Series) -> dict:
    descricao = _str(row.get("descricao"))
    caracteristicas = parsear_descricao(descricao)
    return dict(
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


def _construir_imovel(row: pd.Series, id_externo: str, data_geracao: date | None) -> Imovel:
    campos = _campos_imovel(row)
    if campos["descricao_parsing_incompleto"]:
        logger.warning(
            "Descrição do imóvel %s não bateu no formato conhecido: %r",
            id_externo,
            campos["descricao"],
        )
    return Imovel(
        fonte="caixa",
        id_externo=id_externo,
        ativo=True,
        data_planilha_origem=data_geracao,
        **campos,
    )


def _atualizar_imovel(imovel: Imovel, row: pd.Series, data_geracao: date | None) -> None:
    campos = _campos_imovel(row)
    if campos["descricao_parsing_incompleto"]:
        logger.warning(
            "Descrição do imóvel %s não bateu no formato conhecido: %r",
            imovel.id_externo,
            campos["descricao"],
        )
    for campo, valor in campos.items():
        setattr(imovel, campo, valor)
    imovel.ativo = True
    imovel.desativado_em = None
    imovel.data_planilha_origem = data_geracao

    if imovel.edital:
        _atualizar_edital(imovel.edital, row)
    else:
        imovel.edital = _construir_edital(row, imovel.id)


def _campos_edital(row: pd.Series) -> dict:
    return dict(
        valor_minimo=_decimal_br(row.get("valor_minimo")),
        valor_avaliacao=_decimal_br(row.get("valor_avaliacao")),
        desconto_pct=_desconto(row.get("desconto_pct")),
        financiamento=_str(row.get("financiamento")),
        modalidade_venda=_str(row.get("modalidade_venda")),
    )


def _construir_edital(row: pd.Series, imovel_id: int) -> Edital:
    return Edital(imovel_id=imovel_id, **_campos_edital(row))


def _atualizar_edital(edital: Edital, row: pd.Series) -> None:
    for campo, valor in _campos_edital(row).items():
        setattr(edital, campo, valor)


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
