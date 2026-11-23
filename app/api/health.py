import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import __version__
from app.db import get_session

logger = logging.getLogger(__name__)
router = APIRouter(tags=["saúde"])


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    database: Literal["ok", "error"]
    version: str


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Verifica se a aplicação e o banco estão respondendo",
    responses={503: {"model": HealthResponse, "description": "Banco indisponível"}},
)
def health(response: Response, session: Annotated[Session, Depends(get_session)]) -> HealthResponse:
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        logger.exception("Falha ao verificar o banco de dados")
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(status="degraded", database="error", version=__version__)
    return HealthResponse(status="ok", database="ok", version=__version__)
