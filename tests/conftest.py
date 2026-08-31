"""Fixtures compartilhadas para testes que tocam o Postgres local (docker-compose).

Não usamos pytest-postgresql aqui: apesar de estar como dev dependency, ele
depende de binários do Postgres no PATH do host pra subir uma instância
efêmera, e este projeto só tem Postgres via Docker (docker-compose.yml) — o
mesmo banco local já usado pelas migrations. Os testes que precisam de
concorrência real (SELECT ... FOR UPDATE SKIP LOCKED) rodam contra esse banco
e limpam os próprios dados no teardown.
"""

from __future__ import annotations

import uuid

import pytest

from app.db import SessionLocal
from app.models import ExtractionEnvelope, ExtractionJob, Fonte, Imovel


@pytest.fixture
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def imovel_teste(db_session):
    imovel = Imovel(
        fonte=Fonte.caixa,
        id_externo=f"teste-{uuid.uuid4()}",
        tipo="residencial",
        cidade="Belo Horizonte",
        bairro="Centro",
    )
    db_session.add(imovel)
    db_session.commit()
    yield imovel

    db_session.rollback()
    db_session.query(ExtractionEnvelope).filter(ExtractionEnvelope.imovel_id == imovel.id).delete()
    db_session.query(ExtractionJob).filter(ExtractionJob.imovel_id == imovel.id).delete()
    db_session.query(Imovel).filter(Imovel.id == imovel.id).delete()
    db_session.commit()
