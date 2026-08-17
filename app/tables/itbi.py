"""
Alíquotas de ITBI por município — levantamento inicial MVP 1.
Fonte: processo.md § "Alíquotas de ITBI"

Municípios marcados como TBD ainda precisam de confirmação manual no site da prefeitura.
"""

from decimal import Decimal

# Chave: nome do município em minúsculas sem acento (para match robusto).
# Valor: (aliquota, confirmada)
_TABELA: dict[str, tuple[Decimal, bool]] = {
    "belo horizonte": (Decimal("0.03"), True),
    "contagem":       (Decimal("0.03"), True),
    "betim":          (Decimal("0.03"), True),
    "sete lagoas":    (Decimal("0.025"), True),
    # TBD — não bloqueia desenvolvimento, só o cálculo desses municípios
    "juatuba":        (Decimal("0.03"), False),   # estimativa: usar 3% como fallback
    "mateus leme":    (Decimal("0.03"), False),
    "igarape":        (Decimal("0.03"), False),
    "lagoa santa":    (Decimal("0.03"), False),
    "florestal":      (Decimal("0.03"), False),
    "itauna":         (Decimal("0.03"), False),
}

_FALLBACK = (Decimal("0.03"), False)


def _normalizar(cidade: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFD", cidade.lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def aliquota_itbi(cidade: str) -> tuple[Decimal, bool]:
    """Retorna (aliquota, confirmada) para o município.

    confirmada=False significa que o valor é estimativa e deve ser alertado ao usuário.
    """
    return _TABELA.get(_normalizar(cidade), _FALLBACK)
