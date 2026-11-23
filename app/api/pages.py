"""Telas HTML (Jinja2 + HTMX).

A listagem funciona sem JavaScript (formulário GET comum). Com HTMX, os filtros e a
paginação trocam só o bloco de resultados: a requisição chega com o cabeçalho HX-Request
e devolvemos apenas o template parcial.
"""

from typing import Annotated
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.api.templating import display_timezone, get_templates
from app.db import get_session
from app.schemas.tenders import TenderFilters
from app.services import tenders as service

router = APIRouter(include_in_schema=False)

SessionDep = Annotated[Session, Depends(get_session)]
TimezoneDep = Annotated[ZoneInfo, Depends(display_timezone)]


def _is_partial(request: Request) -> bool:
    # Na restauração do histórico o HTMX pede a página inteira.
    return (
        request.headers.get("HX-Request") == "true"
        and request.headers.get("HX-History-Restore-Request") != "true"
    )


@router.get("/", response_class=HTMLResponse, name="tender_list")
def tender_list(request: Request, session: SessionDep, tz: TimezoneDep) -> HTMLResponse:
    filters, errors = TenderFilters.from_query_lenient(dict(request.query_params))
    result = service.search(session, filters, tz)

    def page_url(page: int) -> str:
        query = urlencode(filters.query_params(page=page))
        return f"{request.url.path}?{query}" if query else request.url.path

    context = {
        "filters": filters,
        "errors": errors,
        "result": result,
        "page_url": page_url,
    }
    if _is_partial(request):
        response = get_templates().TemplateResponse(request, "tenders/_results.html", context)
    else:
        context["municipalities"] = service.municipalities(session)
        response = get_templates().TemplateResponse(request, "tenders/list.html", context)
    # Mesma URL, conteúdos diferentes (página inteira x parcial): não misturar em cache.
    response.headers["Vary"] = "HX-Request"
    return response


@router.get("/licitacoes/{tender_id}", response_class=HTMLResponse, name="tender_detail")
def tender_detail(tender_id: int, request: Request, session: SessionDep) -> HTMLResponse:
    detail = service.get_detail(session, tender_id)
    if detail is None:
        return get_templates().TemplateResponse(
            request, "not_found.html", {"message": "Licitação não encontrada."}, status_code=404
        )
    return get_templates().TemplateResponse(request, "tenders/detail.html", {"tender": detail})
