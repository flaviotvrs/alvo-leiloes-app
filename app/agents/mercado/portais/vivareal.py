"""
Busca de comparáveis no VivaReal via Playwright.

✅ Validado ao vivo nesta sessão: a URL a nível de cidade
(/venda/{estado}/{cidade}/) retorna resultados reais e corretamente
localizados. Seletor de card correto confirmado: `[data-cy="rp-property-cd"]`
(30 cards com texto real de preço/metragem/bairro na página testada).

⚠ CORREÇÃO: a versão anterior deste módulo usava `article` como seletor de
card — esse seletor bate, mas com a seção de **links do rodapé do site**
("Encontre imóveis", "Alugar", "Comprar"...), não com os cards de anúncio.
Isso fazia o LLM (corretamente) reportar 0 comparáveis, mesmo a página tendo
resultados reais — só descoberto rodando com logs em nível DEBUG e inspecionando
o conteúdo de fato capturado pelo seletor, não só se ele "batia" com algo.

⚠ NÃO validado: filtro por bairro/tipo/quartos/área via path ou query string
— os padrões óbvios (`/bairro-{x}/`, `?quartos=`, `?tipos=`) testados nesta
sessão foram ignorados pelo site (a contagem de resultados não mudava),
sugerindo que o filtro real é aplicado via interação com o formulário (JS) ou
um esquema de query string não trivial. Por isso a busca aqui é só a nível de
cidade — a filtragem por bairro/tipo/quartos/metragem fica a cargo do
extrator_llm, que já recebe as características-alvo no prompt. Precisão pode
melhorar bastante se alguém investigar o esquema real de filtro (inspecionar
requests de rede ao usar o formulário do site) — deixado como próximo passo.
"""

from __future__ import annotations

from app.agents.mercado.aggregate import CaracteristicasImovel
from app.agents.mercado.portais.base import PaginaRenderizada, navegar_e_capturar, pagina_playwright, slug_estado, slugificar

FONTE = "vivareal"

_SELETORES_CARDS = ('[data-cy="rp-property-cd"]',)


def _montar_url(caract: CaracteristicasImovel) -> str:
    estado = slug_estado(caract.uf)
    cidade = slugificar(caract.cidade)
    if not estado or not cidade:
        return "https://www.vivareal.com.br/venda/"
    return f"https://www.vivareal.com.br/venda/{estado}/{cidade}/"


def buscar(caract: CaracteristicasImovel) -> PaginaRenderizada:
    url = _montar_url(caract)
    with pagina_playwright() as page:
        html = navegar_e_capturar(page, url, _SELETORES_CARDS)
    return PaginaRenderizada(fonte=FONTE, url=url, html=html)
