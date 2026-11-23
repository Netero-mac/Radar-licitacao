"""Ponto de entrada da aplicação FastAPI."""

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api import health, pages, tenders
from app.api.templating import STATIC_DIR
from app.config import get_settings
from app.logging_config import configure_logging
from app.schemas.errors import translate_error


async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Mesmo formato do FastAPI (detail: [...]), com as mensagens em português."""
    assert isinstance(exc, RequestValidationError)
    detail = [
        {"type": error["type"], "loc": error["loc"], "msg": translate_error(error)}
        for error in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(detail)})


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)

    app = FastAPI(
        title="Radar de Licitações MT",
        description="Licitações de Mato Grosso coletadas do PNCP, com busca e alertas.",
        version=__version__,
    )
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.include_router(health.router)
    app.include_router(tenders.router)
    app.include_router(pages.router)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


app = create_app()
