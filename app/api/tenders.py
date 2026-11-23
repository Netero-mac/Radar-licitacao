"""API JSON de licitações (documentada em /docs)."""

from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.templating import display_timezone
from app.collectors.pncp.modalities import MODALITIES
from app.db import get_session
from app.schemas.tenders import TenderDetail, TenderFilters, TenderPage
from app.services import tenders as service

router = APIRouter(prefix="/api", tags=["licitações"])

SessionDep = Annotated[Session, Depends(get_session)]
TimezoneDep = Annotated[ZoneInfo, Depends(display_timezone)]


class Municipality(BaseModel):
    ibge_code: str
    name: str


class Modality(BaseModel):
    code: int
    name: str


@router.get(
    "/tenders",
    response_model=TenderPage,
    summary="Lista licitações com busca e filtros",
    description=(
        "Licitações mais recentes primeiro. A busca `q` usa o full-text search do PostgreSQL "
        "em português e ignora acentos (`manutencao` encontra `manutenção`). Os filtros de "
        "data são dias no fuso America/Cuiaba. Valores monetários vêm como texto decimal "
        '(ex.: `"5260541.6000"`) para não perder precisão; datas em UTC (ISO 8601).'
    ),
)
def list_tenders(
    filters: Annotated[TenderFilters, Query()], session: SessionDep, tz: TimezoneDep
) -> TenderPage:
    return service.search(session, filters, tz)


@router.get(
    "/tenders/{tender_id}",
    response_model=TenderDetail,
    summary="Detalhe de uma licitação",
    responses={404: {"description": "Licitação não encontrada"}},
)
def get_tender(tender_id: int, session: SessionDep) -> TenderDetail:
    detail = service.get_detail(session, tender_id)
    if detail is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Licitação não encontrada")
    return detail


@router.get(
    "/municipalities",
    response_model=list[Municipality],
    summary="Municípios com licitações coletadas (valores aceitos em `municipality`)",
)
def list_municipalities(session: SessionDep) -> list[Municipality]:
    return [
        Municipality(ibge_code=code, name=name) for code, name in service.municipalities(session)
    ]


@router.get(
    "/modalities",
    response_model=list[Modality],
    summary="Modalidades de contratação (valores aceitos em `modality`)",
)
def list_modalities() -> list[Modality]:
    return [Modality(code=code, name=name) for code, name in MODALITIES.items()]
