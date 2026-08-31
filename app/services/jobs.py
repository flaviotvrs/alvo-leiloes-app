"""
Fila de jobs de agentes extratores (ver docs/arquitetura-tecnica.md §2).

Estados: pendente → em_execucao → concluido | falhou | requer_revisao
Retry: tentativas += 1 em falha; volta a pendente com backoff 2**tentativas
minutos até estourar max_tentativas, quando vira falhou definitivamente.

Este módulo só faz acesso a dado (fila + envelopes) — a lógica de cada agente
(o que fazer com o job) vive em app/agents/<agente>/.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ExtractionEnvelope, ExtractionJob, StatusJob


def _agora() -> datetime:
    """UTC naive — consistente com as colunas DateTime (sem timezone) do schema."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def criar_job(
    session: Session,
    imovel_id: int,
    agente_tipo: str,
    input_ref: dict | None = None,
    user_id: str | None = None,
) -> ExtractionJob:
    job = ExtractionJob(
        imovel_id=imovel_id,
        agente_tipo=agente_tipo,
        input_ref=input_ref,
        user_id=user_id,
    )
    session.add(job)
    session.commit()
    return job


def reivindicar_proximo_job(session: Session, agente_tipo: str) -> ExtractionJob | None:
    """Pega o próximo job pendente e disponível, marcando-o em_execucao.

    Usa FOR UPDATE SKIP LOCKED para que workers concorrentes nunca peguem o
    mesmo job — ver docs/arquitetura-tecnica.md §2.2.
    """
    stmt = (
        select(ExtractionJob)
        .where(
            ExtractionJob.agente_tipo == agente_tipo,
            ExtractionJob.status == StatusJob.pendente,
            ExtractionJob.disponivel_em <= _agora(),
        )
        .order_by(ExtractionJob.criado_em)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    job = session.execute(stmt).scalar_one_or_none()
    if job is None:
        return None

    job.status = StatusJob.em_execucao
    job.iniciado_em = _agora()
    session.commit()
    return job


def marcar_concluido(session: Session, job: ExtractionJob, envelope_dict: dict) -> ExtractionEnvelope:
    """Grava o envelope como um novo registro (nunca sobrescreve um anterior —
    mesma lógica de versionamento de AnaliseFinanceira.versao)."""
    ultima_versao = (
        session.execute(
            select(ExtractionEnvelope.versao)
            .where(
                ExtractionEnvelope.imovel_id == job.imovel_id,
                ExtractionEnvelope.agente_tipo == job.agente_tipo,
            )
            .order_by(ExtractionEnvelope.versao.desc())
            .limit(1)
        ).scalar_one_or_none()
        or 0
    )

    envelope = ExtractionEnvelope(
        job_id=job.id,
        imovel_id=job.imovel_id,
        agente_tipo=job.agente_tipo,
        versao_agente=envelope_dict["versao_agente"],
        versao=ultima_versao + 1,
        fonte=envelope_dict.get("fonte"),
        campos=envelope_dict["campos"],
        campos_nao_encontrados=envelope_dict.get("campos_nao_encontrados"),
        observacoes_agente=envelope_dict.get("observacoes_agente"),
    )
    session.add(envelope)

    job.status = StatusJob.concluido
    job.finalizado_em = _agora()
    session.commit()
    return envelope


def marcar_falhou(session: Session, job: ExtractionJob, erro: str) -> None:
    job.tentativas += 1
    job.erro = erro

    if job.tentativas < job.max_tentativas:
        job.status = StatusJob.pendente
        job.disponivel_em = _agora() + timedelta(minutes=2**job.tentativas)
    else:
        job.status = StatusJob.falhou
        job.finalizado_em = _agora()

    session.commit()


def buscar_ultimo_envelope(session: Session, imovel_id: int, agente_tipo: str) -> ExtractionEnvelope | None:
    stmt = (
        select(ExtractionEnvelope)
        .where(
            ExtractionEnvelope.imovel_id == imovel_id,
            ExtractionEnvelope.agente_tipo == agente_tipo,
        )
        .order_by(ExtractionEnvelope.versao.desc())
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()


def buscar_job_em_andamento(session: Session, imovel_id: int, agente_tipo: str) -> ExtractionJob | None:
    """Job pendente ou em_execucao mais recente — evita a UI criar um job duplicado."""
    stmt = (
        select(ExtractionJob)
        .where(
            ExtractionJob.imovel_id == imovel_id,
            ExtractionJob.agente_tipo == agente_tipo,
            ExtractionJob.status.in_([StatusJob.pendente, StatusJob.em_execucao]),
        )
        .order_by(ExtractionJob.criado_em.desc())
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()


def buscar_ultimo_job(session: Session, imovel_id: int, agente_tipo: str) -> ExtractionJob | None:
    """Último job (qualquer status) — usado pela UI pra mostrar falha mais recente."""
    stmt = (
        select(ExtractionJob)
        .where(
            ExtractionJob.imovel_id == imovel_id,
            ExtractionJob.agente_tipo == agente_tipo,
        )
        .order_by(ExtractionJob.criado_em.desc())
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()
