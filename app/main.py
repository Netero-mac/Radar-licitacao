"""Ponto de entrada da aplicação FastAPI."""

from fastapi import FastAPI

from app import __version__
from app.api import health
from app.config import get_settings
from app.logging_config import configure_logging


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)

    app = FastAPI(
        title="Radar de Licitações MT",
        description="Licitações de Mato Grosso coletadas do PNCP, com busca e alertas.",
        version=__version__,
    )
    app.include_router(health.router)
    return app


app = create_app()
