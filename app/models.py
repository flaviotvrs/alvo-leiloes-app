from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Fonte(str, enum.Enum):
    caixa = "caixa"
    zukerman = "zukerman"


class TipoImovel(str, enum.Enum):
    residencial = "residencial"
    comercial = "comercial"
    terreno = "terreno"


class ResponsabilidadeDivida(str, enum.Enum):
    credor = "credor"
    arrematante = "arrematante"
    nao_informado = "nao_informado"


class ResultadoAnalise(str, enum.Enum):
    viavel = "viavel"
    nao_viavel = "nao_viavel"


class StatusImportacao(str, enum.Enum):
    sucesso = "sucesso"
    erro = "erro"


class Imovel(Base):
    __tablename__ = "imoveis"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fonte: Mapped[str] = mapped_column(Enum(Fonte), nullable=False)
    id_externo: Mapped[str | None] = mapped_column(String(100))
    url_edital: Mapped[str | None] = mapped_column(String(500))

    tipo: Mapped[str | None] = mapped_column(Enum(TipoImovel))
    endereco: Mapped[str | None] = mapped_column(String(300))
    bairro: Mapped[str | None] = mapped_column(String(150))
    cidade: Mapped[str | None] = mapped_column(String(100))
    uf: Mapped[str | None] = mapped_column(String(2))
    regiao: Mapped[str | None] = mapped_column(String(100))
    cep: Mapped[str | None] = mapped_column(String(9))
    descricao: Mapped[str | None] = mapped_column(Text)

    # Campos extraídos da descrição (parser determinístico, ver app/parsers/descricao_imovel.py)
    area_total_m2: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    area_privativa_m2: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    area_terreno_m2: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    quartos: Mapped[int | None] = mapped_column(Integer)
    salas: Mapped[int | None] = mapped_column(Integer)
    vagas_garagem: Mapped[int | None] = mapped_column(Integer)
    possui_wc: Mapped[bool | None] = mapped_column(Boolean)
    possui_cozinha: Mapped[bool | None] = mapped_column(Boolean)
    descricao_parsing_incompleto: Mapped[bool] = mapped_column(Boolean, default=False)

    criado_em: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    edital: Mapped[Edital | None] = relationship(back_populates="imovel", uselist=False)
    analises: Mapped[list[AnaliseFinanceira]] = relationship(back_populates="imovel")

    __table_args__ = (UniqueConstraint("fonte", "id_externo", name="uq_imovel_fonte_externo"),)


class Edital(Base):
    __tablename__ = "editais"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    imovel_id: Mapped[int] = mapped_column(ForeignKey("imoveis.id"), unique=True)

    # Campos disponíveis na planilha Caixa
    valor_minimo: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))   # coluna "Preço"
    valor_avaliacao: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    desconto_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))    # coluna "Desconto"
    financiamento: Mapped[str | None] = mapped_column(String(100))         # coluna "Financiamento"
    modalidade_venda: Mapped[str | None] = mapped_column(String(100))      # coluna "Modalidade de venda"

    # Campos do edital individual (preenchidos depois, via PDF)
    data_1a_praca: Mapped[date | None] = mapped_column(Date)
    valor_1a_praca: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    data_2a_praca: Mapped[date | None] = mapped_column(Date)
    valor_2a_praca: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    comissao_leiloeiro: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))

    responsabilidade_divida_iptu: Mapped[str | None] = mapped_column(
        Enum(ResponsabilidadeDivida), default=ResponsabilidadeDivida.nao_informado
    )
    responsabilidade_divida_condominio: Mapped[str | None] = mapped_column(
        Enum(ResponsabilidadeDivida), default=ResponsabilidadeDivida.nao_informado
    )
    imovel_foreiro: Mapped[bool | None] = mapped_column(Boolean)
    responsabilidade_foro_laudemio: Mapped[str | None] = mapped_column(String(300))
    condicoes_pagamento: Mapped[str | None] = mapped_column(Text)
    possui_vaga_garagem_separada: Mapped[bool | None] = mapped_column(Boolean)

    imovel: Mapped[Imovel] = relationship(back_populates="edital")


class AnaliseFinanceira(Base):
    __tablename__ = "analises_financeiras"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    imovel_id: Mapped[int] = mapped_column(ForeignKey("imoveis.id"))
    versao: Mapped[int] = mapped_column(Integer, default=1)
    user_id: Mapped[str | None] = mapped_column(String(100))

    # inputs manuais — valor de mercado
    valor_mercado: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    fonte_valor_mercado: Mapped[str | None] = mapped_column(String(500))

    # inputs manuais — dívidas e carregamento
    iptu_debito: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    condominio_debito: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    iptu_mensal: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    condominio_mensal: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    meses_carregamento: Mapped[int] = mapped_column(Integer, default=12)

    # inputs manuais — custos adicionais pós-arremate
    custo_advogado: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    custo_reforma: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    outros_custos: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    outros_custos_descricao: Mapped[str | None] = mapped_column(String(300))

    # parâmetros
    comissao_corretor_revenda: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=5.5)
    margem_minima_corte: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=20.0)

    # calculados
    valor_arremate: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    valor_registro_cartorio: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    valor_itbi: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    custo_carregamento: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    ir_ganho_capital: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    total_custos: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    margem_liquida_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    margem_liquida_valor: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    resultado: Mapped[str | None] = mapped_column(Enum(ResultadoAnalise))

    criado_em: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    imovel: Mapped[Imovel] = relationship(back_populates="analises")


class ImportacaoPlanilha(Base):
    """Histórico de uploads de planilha, para conferir se cada importação rodou
    com sucesso (ex: um dia sem upload não passa despercebido)."""

    __tablename__ = "importacoes_planilha"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fonte: Mapped[str] = mapped_column(Enum(Fonte), nullable=False, default=Fonte.caixa)
    nome_arquivo: Mapped[str] = mapped_column(String(300))
    usuario: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(Enum(StatusImportacao), nullable=False)
    imoveis_importados: Mapped[int | None] = mapped_column(Integer)
    imoveis_ignorados: Mapped[int | None] = mapped_column(Integer)
    mensagem_erro: Mapped[str | None] = mapped_column(Text)

    iniciado_em: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    finalizado_em: Mapped[datetime | None] = mapped_column(DateTime)


class StatusJob(str, enum.Enum):
    pendente = "pendente"
    em_execucao = "em_execucao"
    concluido = "concluido"
    falhou = "falhou"
    requer_revisao = "requer_revisao"


class ExtractionJob(Base):
    """Job de execução de um agente extrator (fila em Postgres, ver docs/arquitetura-tecnica.md §2).

    Genérica por design — reaproveitada por qualquer agente futuro (matrícula, débitos
    de prefeitura...) via `agente_tipo`, não só o mercado-extractor do MVP 2.
    """

    __tablename__ = "extraction_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    imovel_id: Mapped[int] = mapped_column(ForeignKey("imoveis.id"), nullable=False)
    agente_tipo: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(Enum(StatusJob), nullable=False, default=StatusJob.pendente)
    prioridade: Mapped[str] = mapped_column(String(20), default="normal")
    tentativas: Mapped[int] = mapped_column(Integer, default=0)
    max_tentativas: Mapped[int] = mapped_column(Integer, default=3)
    input_ref: Mapped[dict | None] = mapped_column(JSONB)
    disponivel_em: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    criado_em: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    iniciado_em: Mapped[datetime | None] = mapped_column(DateTime)
    finalizado_em: Mapped[datetime | None] = mapped_column(DateTime)
    erro: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[str | None] = mapped_column(String(100))

    __table_args__ = (
        Index("ix_jobs_status_disponivel", "status", "disponivel_em"),
        Index("ix_jobs_imovel_agente", "imovel_id", "agente_tipo"),
    )


class ExtractionEnvelope(Base):
    """Resultado de um agente extrator, no formato do envelope comum (docs/interface-agentes.md §1).

    `campos` guarda a lista completa `[{campo, valor, confianca, evidencia, requer_revisao_humana}]`
    do envelope — genérica por agente, sem colunas específicas de mercado-extractor.
    """

    __tablename__ = "extraction_envelopes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("extraction_jobs.id"), nullable=False)
    imovel_id: Mapped[int] = mapped_column(ForeignKey("imoveis.id"), nullable=False)
    agente_tipo: Mapped[str] = mapped_column(String(50), nullable=False)
    versao_agente: Mapped[str] = mapped_column(String(20), nullable=False)
    versao: Mapped[int] = mapped_column(Integer, default=1)
    fonte: Mapped[dict | None] = mapped_column(JSONB)
    campos: Mapped[list] = mapped_column(JSONB, nullable=False)
    campos_nao_encontrados: Mapped[list | None] = mapped_column(JSONB)
    observacoes_agente: Mapped[str | None] = mapped_column(Text)
    extraido_em: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("ix_envelope_imovel_agente_versao", "imovel_id", "agente_tipo", "versao"),
    )
