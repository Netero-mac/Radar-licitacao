"""Importa todos os models para que o Alembic enxergue o metadata completo."""

from app.models.agency import Agency
from app.models.alert import Alert, AlertMatch
from app.models.base import Base
from app.models.collection_run import CollectionRun
from app.models.enums import CollectionStatus, CollectionTrigger, Sphere
from app.models.tender import ACTIVE_STATUS_CODE, Tender

__all__ = [
    "ACTIVE_STATUS_CODE",
    "Agency",
    "Alert",
    "AlertMatch",
    "Base",
    "CollectionRun",
    "CollectionStatus",
    "CollectionTrigger",
    "Sphere",
    "Tender",
]
