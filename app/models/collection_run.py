from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enums import CollectionStatus, CollectionTrigger, enum_values


class CollectionRun(Base):
    """Registro de cada execução da coleta no PNCP."""

    __tablename__ = "collection_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[CollectionStatus] = mapped_column(
        Enum(CollectionStatus, name="collection_status", values_callable=enum_values),
        server_default=CollectionStatus.RUNNING.value,
    )
    trigger: Mapped[CollectionTrigger] = mapped_column(
        Enum(CollectionTrigger, name="collection_trigger", values_callable=enum_values)
    )
    date_from: Mapped[date] = mapped_column(Date)
    date_to: Mapped[date] = mapped_column(Date)
    pages_fetched: Mapped[int] = mapped_column(server_default=text("0"))
    tenders_new: Mapped[int] = mapped_column(server_default=text("0"))
    tenders_updated: Mapped[int] = mapped_column(server_default=text("0"))
    error_message: Mapped[str | None] = mapped_column(Text)
