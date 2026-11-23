"""Ponto de entrada da aplicação FastAPI."""

from urllib.parse import urlencode

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api import admin, dashboard, health, pages, tenders
from app.api.templating import STATIC_DIR, get_templates
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


async def admin_login_required_handler(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, admin.AdminLoginRequiredError)
    return RedirectResponse(f"/admin/login?{urlencode({'next': exc.next_path})}", status_code=303)


async def admin_disabled_handler(request: Request, exc: Exception) -> Response:
    return get_templates().TemplateResponse(
        request,
        "message.html",
        {
            "title": "Área administrativa desativada",
            "message": "Defina ADMIN_PASSWORD e SECRET_KEY no arquivo .env e reinicie a "
            "aplicação para cadastrar alertas.",
        },
        status_code=503,
    )


async def forbidden_origin_handler(request: Request, exc: Exception) -> Response:
    return get_templates().TemplateResponse(
        request,
        "message.html",
        {
            "title": "Requisição bloqueada",
            "message": "O formulário foi enviado de outro site. Por segurança, a operação "
            "não foi realizada.",
        },
        status_code=403,
    )


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
    app.include_router(dashboard.router)
    app.include_router(pages.router)
    app.include_router(admin.router)
    app.add_exception_handler(admin.AdminLoginRequiredError, admin_login_required_handler)
    app.add_exception_handler(admin.AdminDisabledError, admin_disabled_handler)
    app.add_exception_handler(admin.ForbiddenOriginError, forbidden_origin_handler)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


app = create_app()
