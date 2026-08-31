"""
Utilidades compartilhadas de navegação Playwright entre os módulos de portal.

Cada portal (imovelweb.py, vivareal.py, netimoveis.py, indice_regional.py) tem
sua própria lógica de URL/seletores — só o tipo de retorno e o boilerplate de
abrir/fechar browser são compartilhados aqui.

Status de validação ao vivo (feita nesta sessão, contra sites reais):
    - vivareal.py: URL a nível de cidade confirmada correta; filtro por
      bairro/tipo/quartos NÃO confirmado (ver aviso no próprio módulo).
    - imovelweb.py: URL + filtro por bairro confirmados corretos.
    - netimoveis.py: URL responde 200 e devolve cards reais, mas fidelidade
      do filtro por localização não pôde ser confirmada com confiança.
    - indice_regional.py: URL assumida (FipeZap) confirmada QUEBRADA (404) —
      precisa de nova investigação antes de ser útil (ver aviso no módulo).
Nenhum dos 4 encontrou bloqueio de anti-bot nesta sessão (sem captcha/desafio
observado com Playwright headless simples) — bom sinal pro risco #1 do plano,
mas uma única sessão de teste não é garantia de comportamento em produção.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator
from urllib.parse import urljoin

from playwright.sync_api import Browser, Page, sync_playwright

logger = logging.getLogger(__name__)

TIMEOUT_MS = 20_000
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
VIEWPORT = {"width": 1366, "height": 900}


@dataclass
class PaginaRenderizada:
    fonte: str
    url: str
    html: str


_ESTADOS_POR_UF = {
    "AC": "acre", "AL": "alagoas", "AP": "amapa", "AM": "amazonas", "BA": "bahia",
    "CE": "ceara", "DF": "distrito-federal", "ES": "espirito-santo", "GO": "goias",
    "MA": "maranhao", "MT": "mato-grosso", "MS": "mato-grosso-do-sul", "MG": "minas-gerais",
    "PA": "para", "PB": "paraiba", "PR": "parana", "PE": "pernambuco", "PI": "piaui",
    "RJ": "rio-de-janeiro", "RN": "rio-grande-do-norte", "RS": "rio-grande-do-sul",
    "RO": "rondonia", "RR": "roraima", "SC": "santa-catarina", "SP": "sao-paulo",
    "SE": "sergipe", "TO": "tocantins",
}


def slug_estado(uf: str | None) -> str:
    return _ESTADOS_POR_UF.get((uf or "").upper(), "")


def slugificar(texto: str | None) -> str:
    """'Belo Horizonte' -> 'belo-horizonte'. Aproximação simples (sem acentos,
    minúsculo, espaços viram hífen) — portais variam em como tratam exceções
    (siglas, "de"/"do" no nome do bairro), calibrar caso a caso se necessário."""
    if not texto:
        return ""
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", sem_acento.lower())).strip("-")


@contextmanager
def pagina_playwright() -> Iterator[Page]:
    with sync_playwright() as p:
        browser: Browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(user_agent=USER_AGENT, viewport=VIEWPORT, locale="pt-BR")
            page = context.new_page()
            page.set_default_timeout(TIMEOUT_MS)
            yield page
        finally:
            browser.close()


def navegar_e_capturar(page: Page, url: str, seletores_cards: tuple[str, ...]) -> str:
    """goto + log do status HTTP + captura de conteúdo — um 200 não significa
    necessariamente resultado real (pode ser uma página genérica de "não
    encontrado" servida com status 200, como observado com um dos portais
    nesta sessão); o status fica no log pra ajudar a diferenciar os casos."""
    resposta = page.goto(url, wait_until="domcontentloaded")
    logger.debug("navegar_e_capturar: GET %s -> status %s, url final %s", url, resposta.status if resposta else "?", page.url)
    return capturar_conteudo(page, seletores_cards)


def capturar_conteudo(page: Page, seletores_cards: tuple[str, ...], max_cards: int = 40) -> str:
    """Tenta capturar só os cards de anúncio (controle de custo de tokens na
    extração via LLM) — os seletores esperados casam repetidamente, um por
    anúncio na página de resultado, não um container único. Cai para o body
    inteiro se nenhum seletor bater — melhor mandar conteúdo demais pro LLM
    do que quebrar por um seletor errado.

    Usa inner_text(), não inner_html(): o HTML de um card real tem ordem de
    grandeza a mais de ruído (classes CSS, atributos, markup aninhado) do que
    o texto visível — capturado ao vivo nesta sessão, um único card do
    VivaReal tinha ~12KB de HTML contra menos de 1KB de texto equivalente.
    Com o limite de caracteres do LLM (extrator_llm._MAX_CHARS_CONTEUDO), a
    versão HTML deixava só 3-4 cards caberem no orçamento; texto puro deixa
    dezenas caberem, sem perder nenhuma informação relevante pra extração
    (preço/metragem/bairro já aparecem como texto visível no card).

    O texto puro não carrega o href do anúncio — por isso cada bloco de card
    é prefixado com uma linha "URL do anúncio: <url>" (href do próprio
    elemento, ou da primeira âncora dentro dele, resolvido pra absoluto).
    Sem isso, o único URL que sobra no contexto do LLM é o da página de
    busca (citado uma vez no prompt), e ele acaba reaproveitando essa mesma
    URL pra todo item — foi exatamente o que se observou em produção.
    """
    for seletor in seletores_cards:
        try:
            page.wait_for_selector(seletor, timeout=5_000)
            elementos = page.query_selector_all(seletor)
        except Exception as e:
            logger.debug("capturar_conteudo: seletor %r não bateu (%s)", seletor, e)
            continue
        if elementos:
            blocos = [
                f"URL do anúncio: {_href_do_card(el, page.url) or 'não disponível'}\n{el.inner_text()}"
                for el in elementos[:max_cards]
            ]
            logger.debug(
                "capturar_conteudo: seletor %r bateu com %d elemento(s) (usando até %d, %d caracteres de texto)",
                seletor, len(elementos), max_cards, sum(len(b) for b in blocos),
            )
            return "\n---\n".join(blocos)

    conteudo = page.inner_text("body")
    logger.debug("capturar_conteudo: nenhum seletor de %s bateu — caindo para texto do body inteiro (%d caracteres)", seletores_cards, len(conteudo))
    return conteudo


def _href_do_card(el, page_url: str) -> str | None:
    """Href do próprio elemento do card (quando ele é a âncora) ou da primeira
    âncora interna (quando o card só contém o link) — cobre os dois padrões
    observados nos portais sem precisar de seletor específico por site."""
    href = el.get_attribute("href")
    if not href:
        ancora = el.query_selector("a[href]")
        href = ancora.get_attribute("href") if ancora else None
    return urljoin(page_url, href) if href else None
