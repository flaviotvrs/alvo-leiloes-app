"""
Busca de comparáveis no Netimóveis via Playwright.

⚠ CONFIRMADO QUEBRADO nesta sessão (dois problemas, não um): os seletores
usados antes eram ambos errados —
  - `article` bate com o painel de FILTROS da barra lateral, não com cards.
  - `.card-imovel` bate com os cards certos (4 na página testada), mas o
    conteúdo interno é só placeholder de loading (`class="... animated-bg"`,
    divs `title`/`subtitle`/`value` vazias) — os dados reais aparentemente
    carregam via uma chamada JS separada que não termina de renderizar nem
    com `wait_until="networkidle"` + 2s de espera extra. Sem investigar as
    requests de rede da página pra achar o endpoint/mecanismo real (fora do
    escopo desta sessão), não há seletor de HTML renderizado que resolva
    isso — por ora este módulo captura a página inteira (sem seletor de
    card) e deixa o extrator_llm tentar achar algo útil nela, sabendo que
    provavelmente vai reportar 0 comparáveis até isso ser investigado.
"""

from __future__ import annotations

from app.agents.mercado.aggregate import CaracteristicasImovel
from app.agents.mercado.portais.base import PaginaRenderizada, navegar_e_capturar, pagina_playwright, slug_estado, slugificar

FONTE = "netimoveis"

_TIPO_NETIMOVEIS = {
    "residencial": "apartamento",
    "comercial": "sala-comercial",
    "terreno": "terreno",
}

_SELETORES_CARDS: tuple[str, ...] = ()


def _montar_url(caract: CaracteristicasImovel) -> str:
    tipo = _TIPO_NETIMOVEIS.get(caract.tipo or "residencial", _TIPO_NETIMOVEIS["residencial"])
    estado = slug_estado(caract.uf)
    cidade = slugificar(caract.cidade)
    bairro = slugificar(caract.bairro)

    partes = ["https://www.netimoveis.com/venda", estado, cidade]
    if bairro:
        partes.append(bairro)
    partes.append(tipo)
    return "/".join(p for p in partes if p)


def buscar(caract: CaracteristicasImovel) -> PaginaRenderizada:
    url = _montar_url(caract)
    with pagina_playwright() as page:
        html = navegar_e_capturar(page, url, _SELETORES_CARDS)
    return PaginaRenderizada(fonte=FONTE, url=url, html=html)
