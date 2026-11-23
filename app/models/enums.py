from enum import StrEnum


class Sphere(StrEnum):
    MUNICIPAL = "municipal"
    STATE = "estadual"
    FEDERAL = "federal"
    DISTRICT = "distrital"


class CollectionStatus(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class CollectionTrigger(StrEnum):
    SCHEDULED = "scheduled"
    MANUAL = "manual"
    CLI = "cli"


def enum_values(enum_cls: type[StrEnum]) -> list[str]:
    """Faz o SQLAlchemy gravar o valor (ex.: 'municipal') e não o nome do membro."""
    return [member.value for member in enum_cls]
