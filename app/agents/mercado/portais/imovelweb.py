"""
Busca de comparáveis no ImovelWeb via Playwright.

✅ Validado ao vivo nesta sessão: a URL `{tipo}-venda-{bairro}-{cidade}.html`
retorna resultados reais e corretamente filtrados por bairro (confirmado:
busca por "centro-belo-horizonte" devolveu especificamente imóveis no bairro
Centro, com título e contagem de resultados coerentes). Seletor de card
`div[data-posting-type]` confirmado presente (30 cards na página testada).
"""

from __future__ import annotations

from app.agents.mercado.aggregate import CaracteristicasImovel
from app.agents.mercado.portais.base import PaginaRenderizada, navegar_e_capturar, pagina_playwright, slugificar

FONTE = "imovelweb"

_TIPO_IMOVELWEB = {
    "residencial": "apartamentos",
    "comercial": "locais-comerciais",
    "terreno": "terrenos",
}

_SELETORES_CARDS = ("div[data-posting-type]",)


def _montar_url(caract: CaracteristicasImovel) -> str:
    tipo = _TIPO_IMOVELWEB.get(caract.tipo or "residencial", _TIPO_IMOVELWEB["residencial"])
    cidade = slugificar(caract.cidade)
    bairro = slugificar(caract.bairro)

    local = f"{bairro}-{cidade}" if bairro else cidade
    return f"https://www.imovelweb.com.br/{tipo}-venda-{local}.html"


def buscar(caract: CaracteristicasImovel) -> PaginaRenderizada:
    url = _montar_url(caract)
    with pagina_playwright() as page:
        html = navegar_e_capturar(page, url, _SELETORES_CARDS)
    return PaginaRenderizada(fonte=FONTE, url=url, html=html)
