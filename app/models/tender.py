from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import Computed, DateTime, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.agency import Agency
    from app.models.alert import AlertMatch

# Configuração de busca criada na migration inicial: dicionário portuguese + unaccent.
SEARCH_CONFIG = "pt_unaccent"


class Tender(TimestampMixin, Base):
    """Contratação publicada no PNCP."""

    __tablename__ = "tenders"

    id: Mapped[int] = mapped_column(primary_key=True)
    pncp_control_number: Mapped[str] = mapped_column(String(50), unique=True)
    agency_id: Mapped[int] = mapped_column(ForeignKey("agencies.id", ondelete="RESTRICT"))
    unit_name: Mapped[str | None] = mapped_column(String(255))
    municipality_name: Mapped[str] = mapped_column(String(120))
    municipality_ibge_code: Mapped[str] = mapped_column(String(7), index=True)
    state: Mapped[str] = mapped_column(String(2), index=True)
    object_description: Mapped[str] = mapped_column(Text)
    search_vector: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed(
            f"to_tsvector('{SEARCH_CONFIG}'::regconfig, coalesce(object_description, ''))",
            persisted=True,
        ),
        deferred=True,
    )
    modality_code: Mapped[int] = mapped_column(index=True)
    modality_name: Mapped[str] = mapped_column(String(120))
    status_code: Mapped[int]
    status: Mapped[str] = mapped_column(String(60))
    estimated_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    proposals_open_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    proposals_close_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    pncp_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_url: Mapped[str] = mapped_column(String(500))
    raw_data: Mapped[dict[str, Any]] = mapped_column(JSONB)

    agency: Mapped["Agency"] = relationship(back_populates="tenders")
    matches: Mapped[list["AlertMatch"]] = relationship(back_populates="tender")

    __table_args__ = (Index("ix_tenders_search_vector", "search_vector", postgresql_using="gin"),)
