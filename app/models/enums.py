from enum import StrEnum


class Sphere(StrEnum):
    MUNICIPAL = "municipal"
    STATE = "estadual"
    FEDERAL = "federal"
    DISTRICT = "distrital"
    # esferaId "N" no PNCP: consórcios, serviços sociais e outras entidades sem esfera.
    NOT_APPLICABLE = "nao_se_aplica"


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
