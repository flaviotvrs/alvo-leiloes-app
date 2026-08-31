"""
4ª fonte — índice de preço médio por região (FipeZap), usada só como fallback
quando os 3 portais principais não retornam comparáveis diretos usáveis
(docs/mvp2.md §2, decisão de escopo do MVP 2).

⚠ CONFIRMADO QUEBRADO nesta sessão: `zapimoveis.com.br/fipezap/` e
`zapimoveis.com.br/fipezap/belo-horizonte/` devolvem 404 — o índice FipeZap
não está hospedado num path por cidade dentro do site principal do ZAP como
a URL abaixo assume. A pesquisa em https://www.fipezap.com.br/ (domínio
próprio, aparentemente hoje o home do índice) precisa ser refeita do zero —
provavelmente publica só um relatório mensal por região metropolitana (não
por cidade/bairro individual), possivelmente como PDF/planilha, não uma
página de busca navegável. Antes de usar este módulo em produção, validar se
o FipeZap sequer cobre as cidades de interesse do usuário (risco #2 do plano)
e ajustar `_montar_url`/`_SELETORES_CARDS` de acordo. Até lá, este fallback
sempre vai cair no caminho de "sem cobertura" (lista vazia de comparáveis),
que a lógica de agregação (app/agents/mercado/aggregate.py) já trata
corretamente: confiança 0 + requer_revisao_humana=True, não um número
inventado — então o comportamento é seguro, só não é útil ainda.
"""

from __future__ import annotations

from app.agents.mercado.aggregate import CaracteristicasImovel
from app.agents.mercado.portais.base import PaginaRenderizada, navegar_e_capturar, pagina_playwright, slugificar

FONTE = "indice_regional"

_SELETORES_CARDS = (
    "[data-testid='fipezap-index-table']",
    "main",
)


def _montar_url(caract: CaracteristicasImovel) -> str:
    cidade = slugificar(caract.cidade)
    return f"https://www.zapimoveis.com.br/fipezap/{cidade}/" if cidade else "https://www.zapimoveis.com.br/fipezap/"


def buscar(caract: CaracteristicasImovel) -> PaginaRenderizada:
    url = _montar_url(caract)
    with pagina_playwright() as page:
        html = navegar_e_capturar(page, url, _SELETORES_CARDS)
    return PaginaRenderizada(fonte=FONTE, url=url, html=html)
