"""
Orquestração do agente mercado-extractor: carrega o imóvel, consulta os 3
portais principais (+ índice regional como fallback), agrega e monta o
envelope pronto para app.services.jobs.marcar_concluido.

Falha de um portal individual (bloqueio, timeout, mudança de layout) não
derruba o job inteiro — os outros portais ainda contam. Só derruba o job (pra
entrar no retry/backoff da fila) quando NENHUMA fonte responde, o que indica
um problema de infraestrutura (Playwright quebrado, sem rede) e não um
resultado legítimo de "sem comparáveis".

Logs em nível DEBUG (WORKER_LOG_LEVEL=DEBUG) mostram, por portal: URL
consultada, tamanho do conteúdo capturado, quantos comparáveis o LLM extraiu
e quantos sobreviveram ao filtro de agregação — é o caminho mais direto pra
entender por que um portal "retornou dado" mas não virou valor final.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.agents.mercado import aggregate, extrator_llm
from app.agents.mercado.aggregate import CaracteristicasImovel
from app.agents.mercado.portais import imovelweb, indice_regional, netimoveis, vivareal
from app.config import MIN_COMPARAVEIS_CONFIANCA_ALTA
from app.models import ExtractionJob, Imovel

logger = logging.getLogger(__name__)

_PORTAIS_DIRETOS = (imovelweb, vivareal, netimoveis)


def processar(session: Session, job: ExtractionJob) -> dict:
    imovel = session.get(Imovel, job.imovel_id)
    if imovel is None:
        raise ValueError(f"Imóvel {job.imovel_id} não encontrado")

    caract = _construir_caracteristicas(imovel)
    logger.debug(
        "Características do imóvel %s: tipo=%s uf=%s cidade=%s bairro=%s area=%s quartos=%s vagas=%s",
        imovel.id, caract.tipo, caract.uf, caract.cidade, caract.bairro,
        caract.area_privativa_m2, caract.quartos, caract.vagas_garagem,
    )

    fontes_consultadas: list[dict] = []
    comparaveis_diretos = []
    sucessos = 0

    for portal in _PORTAIS_DIRETOS:
        try:
            pagina = portal.buscar(caract)
            logger.debug("[%s] URL consultada: %s (conteúdo capturado: %d caracteres)", portal.FONTE, pagina.url, len(pagina.html))

            comps = extrator_llm.extrair_comparaveis(pagina, caract)
            logger.debug(
                "[%s] LLM extraiu %d comparável(is): %s",
                portal.FONTE, len(comps),
                [(c.valor, c.metragem) for c in comps] if comps else "nenhum",
            )
            comparaveis_diretos.extend(comps)
            fontes_consultadas.append({"portal": portal.FONTE, "url": pagina.url, "comparaveis_extraidos": len(comps)})
            sucessos += 1
        except Exception as e:  # falha de um portal não derruba os outros
            logger.warning("[%s] falhou: %s", portal.FONTE, e)
            fontes_consultadas.append({"portal": portal.FONTE, "erro": str(e)})

    logger.debug("Total de comparáveis diretos brutos (3 portais somados): %d", len(comparaveis_diretos))

    filtrados_diretos = aggregate.filtrar_comparaveis(comparaveis_diretos, caract)
    logger.debug("Após filtro de agregação (metragem/valor válidos + outliers): %d restantes", len(filtrados_diretos))

    comparaveis_indice_regional = None
    if not filtrados_diretos:
        logger.info("Nenhum comparável direto usável após filtro — consultando índice regional (fallback)")
        try:
            pagina = indice_regional.buscar(caract)
            logger.debug("[%s] URL consultada: %s (conteúdo capturado: %d caracteres)", indice_regional.FONTE, pagina.url, len(pagina.html))

            comparaveis_indice_regional = extrator_llm.extrair_comparaveis(pagina, caract)
            logger.debug("[%s] LLM extraiu %d comparável(is)", indice_regional.FONTE, len(comparaveis_indice_regional))
            fontes_consultadas.append({
                "portal": indice_regional.FONTE, "url": pagina.url,
                "comparaveis_extraidos": len(comparaveis_indice_regional),
            })
            sucessos += 1
        except Exception as e:
            logger.warning("[%s] falhou: %s", indice_regional.FONTE, e)
            comparaveis_indice_regional = []
            fontes_consultadas.append({"portal": indice_regional.FONTE, "erro": str(e)})

    if sucessos == 0:
        raise RuntimeError(f"Nenhuma fonte respondeu: {fontes_consultadas}")

    resultado = aggregate.agregar(
        comparaveis_diretos,
        caract,
        MIN_COMPARAVEIS_CONFIANCA_ALTA,
        comparaveis_indice_regional=comparaveis_indice_regional,
    )
    logger.info(
        "Resultado imóvel %s: metodo=%s valor_m2=%s valor_total=%s confianca=%s comparaveis_usados=%d campos_ausentes=%s",
        imovel.id, resultado.metodo, resultado.valor_m2_estimado, resultado.valor_total_estimado,
        resultado.confianca, len(resultado.comparaveis_usados), resultado.campos_edital_ausentes,
    )

    fonte_meta = {"tipo": "busca_portais", "referencia": fontes_consultadas}
    return aggregate.montar_envelope(resultado, imovel.id, fonte_meta)


def _construir_caracteristicas(imovel: Imovel) -> CaracteristicasImovel:
    return CaracteristicasImovel(
        tipo=imovel.tipo,
        bairro=imovel.bairro,
        cidade=imovel.cidade,
        area_privativa_m2=imovel.area_privativa_m2 or imovel.area_total_m2,
        quartos=imovel.quartos,
        vagas_garagem=imovel.vagas_garagem,
        uf=imovel.uf,
    )
