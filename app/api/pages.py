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
from app.geo import municipality_in_state
from app.schemas.tenders import TenderFilters
from app.services import tenders as service

router = APIRouter(include_in_schema=False)

SessionDep = Annotated[Session, Depends(get_session)]
TimezoneDep = Annotated[ZoneInfo, Depends(display_timezone)]


def _is_partial(request: Request) -> bool:
    """Só os resultados quando o HTMX mira o bloco #results.

    Trocar a UF recarrega o formulário inteiro (lista de municípios muda) e a restauração
    do histórico pede a página completa.
    """
    return (
        request.headers.get("HX-Request") == "true"
        and request.headers.get("HX-Target") == "results"
        and request.headers.get("HX-History-Restore-Request") != "true"
    )


@router.get("/", response_class=HTMLResponse, name="tender_list")
def tender_list(request: Request, session: SessionDep, tz: TimezoneDep) -> HTMLResponse:
    filters, errors = TenderFilters.from_query_lenient(dict(request.query_params))
    if (
        filters.state
        and filters.municipality
        and not municipality_in_state(filters.municipality, filters.state)
    ):
        # Município de outra UF (sobra de quando a UF foi trocada): descarta.
        filters = filters.model_copy(update={"municipality": None})
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
        states = service.states(session)
        context["states"] = states
        # Com várias UFs, a lista de municípios só aparece depois de escolher a UF.
        context["municipalities"] = (
            service.municipalities(session, filters.state)
            if filters.state or len(states) <= 1
            else []
        )
        response = get_templates().TemplateResponse(request, "tenders/list.html", context)
    # Mesma URL, conteúdos diferentes (página inteira x parcial): não misturar em cache.
    response.headers["Vary"] = "HX-Request, HX-Target"
    return response


@router.get("/licitacoes/{tender_id}", response_class=HTMLResponse, name="tender_detail")
def tender_detail(tender_id: int, request: Request, session: SessionDep) -> HTMLResponse:
    detail = service.get_detail(session, tender_id)
    if detail is None:
        return get_templates().TemplateResponse(
            request, "not_found.html", {"message": "Licitação não encontrada."}, status_code=404
        )
    return get_templates().TemplateResponse(request, "tenders/detail.html", {"tender": detail})
