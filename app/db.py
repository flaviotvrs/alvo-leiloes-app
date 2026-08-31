import logging
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]
USER_ID: str = os.environ.get("APP_USER_ID", "default")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)


def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def aplicar_migrations() -> None:
    """Aplica migrations pendentes. Chamada no startup do app (idempotente)."""
    from alembic.config import Config
    from alembic import command as alembic_command
    cfg = Config("alembic.ini")
    alembic_command.upgrade(cfg, "head")
    _restaurar_loggers_apos_alembic()


def _restaurar_loggers_apos_alembic() -> None:
    """alembic usa logging.config.fileConfig() internamente, que por padrão
    desabilita todo logger pré-existente não listado em alembic.ini — sem
    isso, loggers do próprio projeto (app.*, __main__) ficam silenciados
    depois de qualquer chamada a aplicar_migrations()."""
    for nome, obj in list(logging.Logger.manager.loggerDict.items()):
        if isinstance(obj, logging.Logger) and (nome == "__main__" or nome.startswith("app.")):
            obj.disabled = False
