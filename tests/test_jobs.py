"""Testes da fila de jobs (app/services/jobs.py) contra Postgres real (docker-compose).

reivindicar_proximo_job depende de concorrência real de linhas (FOR UPDATE
SKIP LOCKED) — não dá pra validar isso de forma confiável com mock.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

from app.db import SessionLocal
from app.models import StatusJob
from app.services import jobs as jobs_service

AGENTE = "mercado-extractor"


def test_criar_e_reivindicar_job(db_session, imovel_teste):
    job = jobs_service.criar_job(db_session, imovel_teste.id, AGENTE)
    assert job.status == StatusJob.pendente
    assert job.tentativas == 0

    reivindicado = jobs_service.reivindicar_proximo_job(db_session, AGENTE)
    assert reivindicado is not None
    assert reivindicado.id == job.id
    assert reivindicado.status == StatusJob.em_execucao
    assert reivindicado.iniciado_em is not None


def test_reivindicar_ignora_job_indisponivel_por_backoff(db_session, imovel_teste):
    job = jobs_service.criar_job(db_session, imovel_teste.id, AGENTE)
    job.disponivel_em = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=10)
    db_session.commit()

    assert jobs_service.reivindicar_proximo_job(db_session, AGENTE) is None


def test_reivindicar_ignora_job_de_outro_agente(db_session, imovel_teste):
    jobs_service.criar_job(db_session, imovel_teste.id, "prefeitura-debitos-extractor")
    assert jobs_service.reivindicar_proximo_job(db_session, AGENTE) is None


def test_reivindicar_concorrente_nao_pega_job_duplicado(db_session, imovel_teste):
    n_jobs = 6
    for _ in range(n_jobs):
        jobs_service.criar_job(db_session, imovel_teste.id, AGENTE)

    claimed_ids: list = []
    lock = threading.Lock()

    def worker():
        session = SessionLocal()
        try:
            while True:
                job = jobs_service.reivindicar_proximo_job(session, AGENTE)
                if job is None:
                    return
                with lock:
                    claimed_ids.append(job.id)
        finally:
            session.close()

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(claimed_ids) == n_jobs
    assert len(set(claimed_ids)) == n_jobs  # nenhum job reivindicado duas vezes


def test_marcar_falhou_incrementa_tentativas_e_aplica_backoff(db_session, imovel_teste):
    job = jobs_service.criar_job(db_session, imovel_teste.id, AGENTE)
    job.max_tentativas = 3
    db_session.commit()

    antes = datetime.now(timezone.utc).replace(tzinfo=None)
    jobs_service.marcar_falhou(db_session, job, "erro de teste")

    assert job.tentativas == 1
    assert job.status == StatusJob.pendente
    assert job.erro == "erro de teste"
    assert job.disponivel_em > antes + timedelta(minutes=1)  # backoff 2**1 min


def test_marcar_falhou_estoura_max_tentativas_vira_falhou(db_session, imovel_teste):
    job = jobs_service.criar_job(db_session, imovel_teste.id, AGENTE)
    job.max_tentativas = 2
    db_session.commit()

    jobs_service.marcar_falhou(db_session, job, "erro 1")
    assert job.status == StatusJob.pendente

    jobs_service.marcar_falhou(db_session, job, "erro 2")
    assert job.status == StatusJob.falhou
    assert job.tentativas == 2
    assert job.finalizado_em is not None


def test_marcar_concluido_grava_envelope_versionado_sem_sobrescrever(db_session, imovel_teste):
    job1 = jobs_service.criar_job(db_session, imovel_teste.id, AGENTE)
    envelope1 = jobs_service.marcar_concluido(
        db_session, job1, {"versao_agente": "0.1.0", "campos": [{"campo": "x", "valor": 1}]}
    )
    assert envelope1.versao == 1
    assert job1.status == StatusJob.concluido

    job2 = jobs_service.criar_job(db_session, imovel_teste.id, AGENTE)
    envelope2 = jobs_service.marcar_concluido(
        db_session, job2, {"versao_agente": "0.1.0", "campos": [{"campo": "x", "valor": 2}]}
    )
    assert envelope2.versao == 2

    ultimo = jobs_service.buscar_ultimo_envelope(db_session, imovel_teste.id, AGENTE)
    assert ultimo.versao == 2
    assert ultimo.campos[0]["valor"] == 2


def test_buscar_job_em_andamento(db_session, imovel_teste):
    assert jobs_service.buscar_job_em_andamento(db_session, imovel_teste.id, AGENTE) is None

    job = jobs_service.criar_job(db_session, imovel_teste.id, AGENTE)
    em_andamento = jobs_service.buscar_job_em_andamento(db_session, imovel_teste.id, AGENTE)
    assert em_andamento.id == job.id

    jobs_service.marcar_concluido(db_session, job, {"versao_agente": "0.1.0", "campos": []})
    assert jobs_service.buscar_job_em_andamento(db_session, imovel_teste.id, AGENTE) is None
