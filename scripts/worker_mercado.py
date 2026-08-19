"""
Worker do agente mercado-extractor — roda fora do Streamlit (GitHub Actions
com cron, ver .github/workflows/worker-mercado.yml), já que o Streamlit
Community Cloud não hospeda processo contínuo.

Esvazia a fila de jobs pendentes de "mercado-extractor" numa execução e
encerra — o cron cuida da recorrência.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Permite rodar como `python scripts/worker_mercado.py` (de qualquer diretório)
# sem depender de PYTHONPATH externo — script solto fora do pacote `app`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agents.mercado import runner
from app.config import WORKER_LOG_LEVEL
from app.db import SessionLocal, aplicar_migrations
from app.services import jobs as jobs_service

AGENTE_TIPO = "mercado-extractor"

_NIVEL = getattr(logging, WORKER_LOG_LEVEL, logging.INFO)
logging.basicConfig(level=_NIVEL, format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    # Idempotente — garante o schema em dia mesmo se o worker rodar antes do
    # Streamlit ter sido aberto ao menos uma vez após um deploy novo.
    aplicar_migrations()  # também restaura os loggers de app.* (ver app/db.py)

    # "app" é o ancestral comum de todos os loggers de app.agents.mercado.* —
    # setar o nível aqui propaga pra eles sem precisar tocar em cada módulo.
    logging.getLogger("app").setLevel(_NIVEL)
    logger.setLevel(_NIVEL)

    processados = 0
    with SessionLocal() as session:
        while True:
            job = jobs_service.reivindicar_proximo_job(session, AGENTE_TIPO)
            if job is None:
                break

            logger.info("Processando job %s (imovel_id=%s)", job.id, job.imovel_id)
            try:
                envelope_dict = runner.processar(session, job)
                jobs_service.marcar_concluido(session, job, envelope_dict)
                logger.info("Job %s concluído", job.id)
            except Exception as e:
                logger.exception("Job %s falhou", job.id)
                jobs_service.marcar_falhou(session, job, str(e))
            processados += 1

    logger.info("Worker encerrado — %d job(s) processado(s)", processados)


if __name__ == "__main__":
    main()
