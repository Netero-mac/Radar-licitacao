from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.tender import Tender


class Alert(TimestampMixin, Base):
    """Interesse de uma empresa: palavras-chave, municípios e faixa de valor."""

    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(254))
    keywords: Mapped[list[str]] = mapped_column(ARRAY(String(120)))
    # Abrangência: UFs e/ou municípios (códigos IBGE). Uma licitação entra se for de uma das
    # UFs OU de um dos municípios; as duas listas vazias = todas as UFs coletadas.
    states: Mapped[list[str]] = mapped_column(ARRAY(String(2)), server_default=text("'{}'"))
    municipalities: Mapped[list[str]] = mapped_column(ARRAY(String(7)), server_default=text("'{}'"))
    min_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    max_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    telegram_chat_id: Mapped[str | None] = mapped_column(String(64))
    active: Mapped[bool] = mapped_column(server_default=text("true"))

    matches: Mapped[list["AlertMatch"]] = relationship(
        back_populates="alert", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        CheckConstraint(
            "min_value IS NULL OR max_value IS NULL OR min_value <= max_value",
            name="value_range",
        ),
        CheckConstraint("cardinality(keywords) > 0", name="has_keywords"),
    )


class AlertMatch(Base):
    """Licitação que casou com um alerta; notified_at fica nulo até o envio."""

    __tablename__ = "alert_matches"

    id: Mapped[int] = mapped_column(primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("alerts.id", ondelete="CASCADE"))
    tender_id: Mapped[int] = mapped_column(ForeignKey("tenders.id", ondelete="CASCADE"), index=True)
    matched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    alert: Mapped["Alert"] = relationship(back_populates="matches")
    tender: Mapped["Tender"] = relationship(back_populates="matches")

    __table_args__ = (UniqueConstraint("alert_id", "tender_id"),)
