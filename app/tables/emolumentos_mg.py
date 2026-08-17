"""
Tabela 4-2026 TJMG — Atos do Oficial de Registro de Imóveis
Item 5-e: Escritura pública / instrumento particular / título judicial com conteúdo financeiro.

Base de cálculo: valor de avaliação da repartição fazendária.
MVP usa valor de arremate como proxy (Nota VII do TJMG).
Valores já incluem ISSQN.

Fonte: processo.md § "Tabela de emolumentos de cartório (MG)"
"""

from decimal import Decimal

# (limite_superior_inclusive, emolumento_fixo)
# Para o último intervalo ≤ 3.700.000 o valor é fixo; acima disso aplica-se
# regra progressiva da Nota XVII (tratada separadamente).
_FAIXAS: list[tuple[Decimal, Decimal]] = [
    (Decimal("1400.00"),       Decimal("227.95")),
    (Decimal("2720.00"),       Decimal("371.84")),
    (Decimal("5440.00"),       Decimal("538.85")),
    (Decimal("7000.00"),       Decimal("745.98")),
    (Decimal("14000.00"),      Decimal("994.78")),
    (Decimal("28000.00"),      Decimal("1285.21")),
    (Decimal("42000.00"),      Decimal("1597.11")),
    (Decimal("56000.00"),      Decimal("1989.94")),
    (Decimal("70000.00"),      Decimal("2404.60")),
    (Decimal("105000.00"),     Decimal("3026.34")),
    (Decimal("140000.00"),     Decimal("3839.67")),
    (Decimal("175000.00"),     Decimal("4106.03")),
    (Decimal("210000.00"),     Decimal("4372.88")),
    (Decimal("280000.00"),     Decimal("4914.86")),
    (Decimal("350000.00"),     Decimal("5050.25")),
    (Decimal("420000.00"),     Decimal("5186.26")),
    (Decimal("560000.00"),     Decimal("5677.78")),
    (Decimal("700000.00"),     Decimal("5989.84")),
    (Decimal("840000.00"),     Decimal("6302.53")),
    (Decimal("1120000.00"),    Decimal("7046.73")),
    (Decimal("1400000.00"),    Decimal("7632.83")),
    (Decimal("1680000.00"),    Decimal("8219.92")),
    (Decimal("3200000.00"),    Decimal("8808.22")),
    (Decimal("3700000.00"),    Decimal("13034.69")),
]

# Nota XVII: acima de R$ 3.700.000, cada faixa adicional de R$ 500.000 acrescenta
# o mesmo incremento da última faixa. Usamos valor médio como estimativa conservadora.
_ACIMA_BASE = Decimal("13034.69")
_ACIMA_LIMITE = Decimal("3700000.00")
_ACIMA_FAIXA = Decimal("500000.00")
# Incremento por faixa de 500k (diferença entre as duas últimas faixas fixas / proporção)
# Conservadoramente, usamos o incremento da última transição escalado.
_ACIMA_INCREMENTO = Decimal("500.00")  # estimativa — sinalizar ao usuário como aproximado


def calcular_emolumentos(valor: Decimal) -> tuple[Decimal, bool]:
    """Retorna (emolumento, é_estimado).

    é_estimado=True quando o valor cai acima de R$ 3.700.000 (Nota XVII).
    """
    valor = Decimal(str(valor))

    for limite, emolumento in _FAIXAS:
        if valor <= limite:
            return emolumento, False

    # Acima de 3.700.000 — regra progressiva aproximada
    excedente = valor - _ACIMA_LIMITE
    faixas_extras = (excedente / _ACIMA_FAIXA).to_integral_value(rounding="ROUND_CEILING")
    estimado = _ACIMA_BASE + faixas_extras * _ACIMA_INCREMENTO
    return estimado, True
