"""Configuração do Jinja2: pasta de templates e filtros de formatação brasileira."""

from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi.templating import Jinja2Templates
from jinja2 import pass_context

from app import formatting
from app.collectors.pncp.modalities import MODALITIES
from app.config import get_settings

APP_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"


def display_timezone() -> ZoneInfo:
    return ZoneInfo(get_settings().display_timezone)


@pass_context
def path_for(context: Any, name: str, /, **params: Any) -> str:
    """Caminho relativo ao site (ex.: /licitacoes/1).

    O url_for do Starlette gera URL absoluta, que sai com o esquema/host errados atrás de
    um proxy reverso se ele não repassar os cabeçalhos; o caminho funciona sempre.
    """
    return str(context["request"].app.url_path_for(name, **params))


@lru_cache
def get_templates() -> Jinja2Templates:
    templates = Jinja2Templates(directory=TEMPLATES_DIR)
    tz = display_timezone()
    env = templates.env
    env.filters["brl"] = formatting.format_brl
    env.filters["datetime_br"] = lambda value: formatting.format_datetime(value, tz)
    env.filters["date_br"] = lambda value: formatting.format_date(value, tz)
    env.filters["cnpj"] = formatting.format_cnpj
    env.globals["path_for"] = path_for
    env.globals["modalities"] = MODALITIES
    env.globals["display_timezone"] = str(tz)
    return templates
