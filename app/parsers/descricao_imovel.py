"""
Parser determinístico para a coluna "Descrição" da planilha Caixa.

O texto é gerado por template, sempre no formato:
    "Tipo, X.XX de área total, X.XX de área privativa, X.XX de área do
    terreno, N qto(s), WC, N sala(s), cozinha, N vaga(s) de garagem."

com os componentes após a área do terreno opcionais e em quantidade
variável. Por ser um formato estruturado (não linguagem natural livre),
usamos regex em vez de um agente de IA.

Confiança é binária: bateu no formato conhecido (backbone: tipo + 3 áreas)
ou não. Quando não bate, `parsing_incompleto=True` sinaliza a linha para
revisão manual em vez de devolver todos os campos como null silenciosamente.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_BACKBONE = re.compile(
    r"^(?P<tipo>[^,]+),\s*"
    r"(?P<area_total>\d+(?:\.\d+)?)\s+de área total,\s*"
    r"(?P<area_privativa>\d+(?:\.\d+)?)\s+de área privativa,\s*"
    r"(?P<area_terreno>\d+(?:\.\d+)?)\s+de área do terreno",
    re.IGNORECASE,
)

_QUARTOS = re.compile(r"(\d+)\s*qto\(s\)", re.IGNORECASE)
_SALAS = re.compile(r"(\d+)\s*sala\(s\)", re.IGNORECASE)
_VAGAS = re.compile(r"(\d+)\s*vaga\(s\)\s*de\s*garagem", re.IGNORECASE)
_WC = re.compile(r"\bWC\b", re.IGNORECASE)
_COZINHA = re.compile(r"\bcozinha\b", re.IGNORECASE)


@dataclass
class DescricaoImovel:
    tipo: str | None = None
    area_total_m2: float | None = None
    area_privativa_m2: float | None = None
    area_terreno_m2: float | None = None
    quartos: int | None = None
    salas: int | None = None
    vagas_garagem: int | None = None
    possui_wc: bool | None = None
    possui_cozinha: bool | None = None
    parsing_incompleto: bool = False


def parsear_descricao(descricao: str | None) -> DescricaoImovel:
    """Extrai tipo, áreas e cômodos da descrição estruturada da Caixa.

    Se o texto não bater no formato conhecido, devolve
    `parsing_incompleto=True` em vez de campos null silenciosos.
    """
    if not descricao or not descricao.strip():
        return DescricaoImovel(parsing_incompleto=True)

    match = _BACKBONE.match(descricao.strip())
    if not match:
        return DescricaoImovel(parsing_incompleto=True)

    resultado = DescricaoImovel(
        tipo=match.group("tipo").strip(),
        area_total_m2=_area_ou_none(match.group("area_total")),
        area_privativa_m2=_area_ou_none(match.group("area_privativa")),
        area_terreno_m2=_area_ou_none(match.group("area_terreno")),
    )

    m = _QUARTOS.search(descricao)
    if m:
        resultado.quartos = int(m.group(1))

    m = _SALAS.search(descricao)
    if m:
        resultado.salas = int(m.group(1))

    m = _VAGAS.search(descricao)
    if m:
        resultado.vagas_garagem = int(m.group(1))

    resultado.possui_wc = bool(_WC.search(descricao))
    resultado.possui_cozinha = bool(_COZINHA.search(descricao))

    return resultado


def _area_ou_none(valor: str) -> float | None:
    area = float(valor)
    return area if area > 0 else None
