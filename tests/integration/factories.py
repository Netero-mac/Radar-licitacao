"""Criação de registros para os testes, com valores padrão realistas."""

from datetime import UTC, datetime
from decimal import Decimal
from itertools import count
from typing import Any

from sqlalchemy.orm import Session

from app.models import Agency, Sphere, Tender

_sequence = count(1)

RONDONOPOLIS = ("5107602", "Rondonópolis")
PEDRA_PRETA = ("5106372", "Pedra Preta")
CUIABA = ("5103403", "Cuiabá")


def make_agency(session: Session, **overrides: Any) -> Agency:
    n = next(_sequence)
    agency = Agency(
        **{
            "cnpj": f"{n:014d}",
            "name": f"Prefeitura Municipal {n}",
            "sphere": Sphere.MUNICIPAL,
            **overrides,
        }
    )
    session.add(agency)
    session.flush()
    return agency


def make_tender(
    session: Session,
    *,
    agency: Agency | None = None,
    municipality: tuple[str, str] = RONDONOPOLIS,
    **overrides: Any,
) -> Tender:
    n = next(_sequence)
    agency = agency or make_agency(session)
    code, name = municipality
    tender = Tender(
        **{
            "pncp_control_number": f"{agency.cnpj}-1-{n:06d}/2026",
            "agency": agency,
            "municipality_ibge_code": code,
            "municipality_name": name,
            "state": "MT",
            "object_description": f"Aquisição de material {n}",
            "modality_code": 6,
            "modality_name": "Pregão - Eletrônico",
            "status_code": 1,
            "status": "Divulgada no PNCP",
            "estimated_value": Decimal("10000.00"),
            "published_at": datetime(2026, 11, 18, 12, 0, tzinfo=UTC),
            "source_url": f"https://pncp.gov.br/app/editais/{agency.cnpj}/2026/{n}",
            "raw_data": {},
            **overrides,
        }
    )
    session.add(tender)
    session.flush()
    return tender
