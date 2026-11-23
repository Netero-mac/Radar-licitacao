from typing import TYPE_CHECKING

from sqlalchemy import Enum, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import Sphere, enum_values

if TYPE_CHECKING:
    from app.models.tender import Tender


class Agency(TimestampMixin, Base):
    """Órgão ou entidade pública que publica contratações."""

    __tablename__ = "agencies"

    id: Mapped[int] = mapped_column(primary_key=True)
    cnpj: Mapped[str] = mapped_column(String(14), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    sphere: Mapped[Sphere] = mapped_column(
        Enum(Sphere, name="agency_sphere", values_callable=enum_values)
    )

    tenders: Mapped[list["Tender"]] = relationship(back_populates="agency")
