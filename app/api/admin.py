"""Área administrativa: login, alertas e coletas (telas HTML com formulários comuns).

Proteções:
- senha única ADMIN_PASSWORD, comparada em tempo constante, com atraso após erro;
- cookie de sessão assinado (app/security.py), HttpOnly, SameSite=Lax e Secure com HTTPS;
- todo POST confere a origem da requisição (Origin/Referer), contra CSRF.
"""

import logging
import time
from datetime import UTC, datetime
from typing import Annotated, Any
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from app.api.templating import display_timezone, get_templates
from app.config import Settings, get_settings
from app.db import get_session, get_sessionmaker
from app.geo import STATES, municipality_label, state_name
from app.models import Alert, CollectionTrigger
from app.notifiers.email import SmtpEmailSender
from app.notifiers.telegram import TelegramClient
from app.repositories import collection_runs
from app.scheduler import next_scheduled_runs
from app.schemas.alerts import AlertForm
from app.security import COOKIE_NAME, check_password, issue_token, verify_token
from app.services import alerts as service
from app.services.alerts import IneffectiveKeywordError
from app.services.locks import collection_running
from app.services.notifications import DigestContext, send_digests
from app.services.pipeline import run_pipeline

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", include_in_schema=False)

SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
LOGIN_FAILURE_DELAY_SECONDS = 1.0

FLASH_MESSAGES = {
    "created": "Alerta criado. {matched} licitação(ões) com propostas abertas já casam com ele.",
    "updated": "Alerta atualizado. {matched} licitação(ões) com propostas abertas casam com ele.",
    "deleted": "Alerta excluído.",
    "activated": "Alerta ativado.",
    "deactivated": "Alerta desativado: ele não recebe novas licitações nem resumos.",
    "digest": "Resumos enviados: {emails} e-mail(s), {telegram} mensagem(ns) no Telegram, "
    "{tenders} licitação(ões).",
    "digest_failed": "Alguns resumos falharam ({failures}); veja os logs. Enviados: "
    "{emails} e-mail(s), {telegram} mensagem(ns) no Telegram.",
    "collect_started": "Coleta iniciada. Ela roda em segundo plano: atualize esta página "
    "para acompanhar.",
    "collect_busy": "Já existe uma coleta em andamento. Aguarde ela terminar.",
}


class AdminLoginRequiredError(Exception):
    def __init__(self, next_path: str) -> None:
        self.next_path = next_path


class AdminDisabledError(Exception):
    pass


class ForbiddenOriginError(Exception):
    pass


def require_admin(request: Request, settings: SettingsDep) -> None:
    if not settings.admin_enabled:
        raise AdminDisabledError
    if not verify_token(settings, request.cookies.get(COOKIE_NAME)):
        raise AdminLoginRequiredError(request.url.path)


def require_same_origin(request: Request, settings: SettingsDep) -> None:
    """Rejeita POST vindo de outro site (CSRF). Sem Origin/Referer (fora do navegador), passa."""
    source = request.headers.get("origin") or request.headers.get("referer")
    if not source:
        return
    allowed = {request.headers.get("host", ""), urlsplit(settings.app_base_url).netloc}
    if urlsplit(source).netloc not in allowed:
        logger.warning("POST administrativo de origem não permitida", extra={"origin": source})
        raise ForbiddenOriginError


AdminDep = Depends(require_admin)
SameOriginDep = Depends(require_same_origin)


def _safe_next(value: str | None) -> str:
    """Só redireciona para dentro da área administrativa (evita open redirect)."""
    if value and value.startswith("/admin") and not value.startswith("//"):
        return value
    return "/admin/alertas"


def _redirect(path: str, **params: Any) -> RedirectResponse:
    query = f"?{urlencode(params)}" if params else ""
    return RedirectResponse(f"{path}{query}", status_code=status.HTTP_303_SEE_OTHER)


def _flash(request: Request) -> str | None:
    template = FLASH_MESSAGES.get(request.query_params.get("msg", ""))
    if template is None:
        return None
    counts = {
        key: int(value) if value.isdigit() else 0
        for key, value in request.query_params.items()
        if key != "msg"
    }
    try:
        return template.format(**counts)
    except KeyError:
        return None


# --- Login -----------------------------------------------------------------------------


@router.get("/login", response_class=HTMLResponse, name="admin_login")
def login_page(request: Request, settings: SettingsDep, next: str | None = None) -> Response:
    if not settings.admin_enabled:
        raise AdminDisabledError
    return get_templates().TemplateResponse(
        request, "admin/login.html", {"next": _safe_next(next), "error": None}
    )


@router.post("/login", dependencies=[SameOriginDep])
def login(
    request: Request,
    settings: SettingsDep,
    password: Annotated[str, Form()] = "",
    next: Annotated[str, Form()] = "",
) -> Response:
    if not settings.admin_enabled:
        raise AdminDisabledError
    if not check_password(settings, password):
        client = request.client.host if request.client else "?"
        logger.warning("Senha de administrador incorreta", extra={"client": client})
        time.sleep(LOGIN_FAILURE_DELAY_SECONDS)  # torna tentativa e erro bem mais lenta
        return get_templates().TemplateResponse(
            request,
            "admin/login.html",
            {"next": _safe_next(next), "error": "Senha incorreta."},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    response = _redirect(_safe_next(next))
    response.set_cookie(
        COOKIE_NAME,
        issue_token(settings),
        max_age=settings.admin_session_hours * 3600,
        path="/admin",
        httponly=True,
        samesite="lax",
        # Secure quando o endereço público é HTTPS: com http:// o navegador descartaria o
        # cookie e o login falharia sem explicação.
        secure=settings.app_base_url.startswith("https://"),
    )
    return response


@router.post("/logout", dependencies=[SameOriginDep])
def logout() -> Response:
    response = _redirect("/admin/login")
    response.delete_cookie(COOKIE_NAME, path="/admin")
    return response


# --- Alertas ---------------------------------------------------------------------------


def _state_choices(settings: Settings) -> list[tuple[str, str]]:
    codes = settings.pncp_states or list(STATES)
    return [(code, state_name(code)) for code in codes]


def _form_values(alert: Alert | None = None) -> dict[str, Any]:
    if alert is None:
        return {"active": True, "states": []}
    return {
        "name": alert.name,
        "email": alert.email,
        "keywords": "\n".join(alert.keywords),
        "states": alert.states,
        "municipalities": "\n".join(municipality_label(code) for code in alert.municipalities),
        "min_value": "" if alert.min_value is None else alert.min_value,
        "max_value": "" if alert.max_value is None else alert.max_value,
        "telegram_chat_id": alert.telegram_chat_id or "",
        "active": alert.active,
    }


def _render_form(
    request: Request,
    settings: Settings,
    *,
    alert: Alert | None,
    values: dict[str, Any],
    errors: dict[str, str] | None = None,
    status_code: int = 200,
) -> Response:
    return get_templates().TemplateResponse(
        request,
        "admin/alert_form.html",
        {
            "alert": alert,
            "values": values,
            "errors": errors or {},
            "state_choices": _state_choices(settings),
            "telegram_enabled": settings.telegram_bot_token is not None,
        },
        status_code=status_code,
    )


FormStr = Annotated[str, Form()]


def alert_form_values(
    name: FormStr = "",
    email: FormStr = "",
    keywords: FormStr = "",
    states: Annotated[list[str], Form()] = [],  # noqa: B006 - padrão do FastAPI para Form
    municipalities: FormStr = "",
    min_value: FormStr = "",
    max_value: FormStr = "",
    telegram_chat_id: FormStr = "",
    active: Annotated[str | None, Form()] = None,
) -> dict[str, Any]:
    """Campos enviados pelo formulário de alerta, como texto (validados em AlertForm)."""
    return {
        "name": name,
        "email": email,
        "keywords": keywords,
        "states": states,
        "municipalities": municipalities,
        "min_value": min_value,
        "max_value": max_value,
        "telegram_chat_id": telegram_chat_id,
        "active": active is not None,
    }


FormValuesDep = Annotated[dict[str, Any], Depends(alert_form_values)]


@router.get("", dependencies=[AdminDep])
def admin_home() -> Response:
    return _redirect("/admin/alertas")


@router.get("/alertas", response_class=HTMLResponse, name="admin_alerts", dependencies=[AdminDep])
def alerts_page(request: Request, session: SessionDep, settings: SettingsDep) -> Response:
    return get_templates().TemplateResponse(
        request,
        "admin/alerts.html",
        {
            "rows": service.list_alerts(session),
            "flash": _flash(request),
            "flash_error": request.query_params.get("msg") == "digest_failed",
            "email_enabled": settings.smtp_host is not None,
            "telegram_enabled": settings.telegram_bot_token is not None,
            "municipality_label": municipality_label,
        },
    )


@router.get("/alertas/novo", response_class=HTMLResponse, dependencies=[AdminDep])
def new_alert_page(request: Request, settings: SettingsDep) -> Response:
    return _render_form(request, settings, alert=None, values=_form_values())


def _save(
    request: Request,
    session: Session,
    settings: Settings,
    alert: Alert | None,
    values: dict[str, Any],
) -> Response:
    form, errors = AlertForm.parse(values, settings.pncp_states)
    if form is not None:
        try:
            if alert is None:
                alert, matched = service.create_alert(session, form)
                return _redirect("/admin/alertas", msg="created", matched=matched)
            matched = service.update_alert(session, alert, form)
            return _redirect("/admin/alertas", msg="updated", matched=matched)
        except IneffectiveKeywordError as exc:
            session.rollback()
            errors = {"keywords": str(exc)}
    return _render_form(
        request,
        settings,
        alert=alert,
        values=values,
        errors=errors,
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
    )


@router.post("/alertas/novo", dependencies=[AdminDep, SameOriginDep])
def create_alert(
    request: Request, session: SessionDep, settings: SettingsDep, values: FormValuesDep
) -> Response:
    return _save(request, session, settings, None, values)


def _get_or_404(request: Request, session: Session, alert_id: int) -> Alert | Response:
    alert = service.get_alert(session, alert_id)
    if alert is None:
        return get_templates().TemplateResponse(
            request, "not_found.html", {"message": "Alerta não encontrado."}, status_code=404
        )
    return alert


@router.get("/alertas/{alert_id}", response_class=HTMLResponse, dependencies=[AdminDep])
def alert_detail_page(request: Request, alert_id: int, session: SessionDep) -> Response:
    alert = _get_or_404(request, session, alert_id)
    if not isinstance(alert, Alert):
        return alert
    return get_templates().TemplateResponse(
        request,
        "admin/alert_detail.html",
        {
            "alert": alert,
            "matches": service.recent_matches(session, alert.id),
            "municipality_label": municipality_label,
        },
    )


@router.get("/alertas/{alert_id}/editar", response_class=HTMLResponse, dependencies=[AdminDep])
def edit_alert_page(
    request: Request, alert_id: int, session: SessionDep, settings: SettingsDep
) -> Response:
    alert = _get_or_404(request, session, alert_id)
    if not isinstance(alert, Alert):
        return alert
    return _render_form(request, settings, alert=alert, values=_form_values(alert))


@router.post("/alertas/{alert_id}/editar", dependencies=[AdminDep, SameOriginDep])
def update_alert(
    request: Request,
    alert_id: int,
    session: SessionDep,
    settings: SettingsDep,
    values: FormValuesDep,
) -> Response:
    alert = _get_or_404(request, session, alert_id)
    if not isinstance(alert, Alert):
        return alert
    return _save(request, session, settings, alert, values)


@router.post("/alertas/{alert_id}/ativo", dependencies=[AdminDep, SameOriginDep])
def toggle_alert(
    request: Request,
    alert_id: int,
    session: SessionDep,
    active: Annotated[str, Form()] = "",
) -> Response:
    alert = _get_or_404(request, session, alert_id)
    if not isinstance(alert, Alert):
        return alert
    enable = active == "1"
    service.set_active(session, alert, enable)
    return _redirect("/admin/alertas", msg="activated" if enable else "deactivated")


@router.post("/alertas/{alert_id}/excluir", dependencies=[AdminDep, SameOriginDep])
def delete_alert(request: Request, alert_id: int, session: SessionDep) -> Response:
    alert = _get_or_404(request, session, alert_id)
    if not isinstance(alert, Alert):
        return alert
    service.delete_alert(session, alert)
    return _redirect("/admin/alertas", msg="deleted")


@router.post("/resumos/enviar", dependencies=[AdminDep, SameOriginDep])
def send_digests_now(session: SessionDep, settings: SettingsDep) -> Response:
    """Envia agora os resumos pendentes (útil para testar com o Mailpit)."""
    telegram = TelegramClient.from_settings(settings)
    try:
        report = send_digests(
            session,
            email_sender=SmtpEmailSender.from_settings(settings),
            telegram=telegram,
            ctx=DigestContext(settings.app_base_url, display_timezone(), settings.smtp_from),
        )
    finally:
        if telegram is not None:
            telegram.close()
    return _redirect(
        "/admin/alertas",
        msg="digest" if report.ok else "digest_failed",
        emails=report.emails_sent,
        telegram=report.telegram_messages_sent,
        tenders=report.tenders_notified,
        failures=len(report.failures),
    )


# --- Coletas ---------------------------------------------------------------------------


def manual_collection(settings: Settings) -> None:
    """Coleta + cruzamento com os alertas, em segundo plano (os resumos ficam no horário)."""
    try:
        result = run_pipeline(
            settings,
            get_sessionmaker(),
            trigger=CollectionTrigger.MANUAL,
            send_notifications=False,
        )
    except Exception:
        logger.exception("Falha na coleta manual")
        return
    if result.skipped:
        logger.warning("Coleta manual ignorada: outra coleta está em andamento")


@router.get(
    "/coletas", response_class=HTMLResponse, name="admin_collections", dependencies=[AdminDep]
)
def collections_page(request: Request, session: SessionDep, settings: SettingsDep) -> Response:
    now = datetime.now(UTC)
    context = {
        "runs": collection_runs.recent_runs(session),
        "running": collection_running(session.get_bind()),
        "next_runs": next_scheduled_runs(settings, now),
        "schedule_hours": settings.schedule_hours,
        "schedule_tz": settings.schedule_timezone,
        "flash": _flash(request),
        "flash_error": request.query_params.get("msg") == "collect_busy",
        "now": now,
    }
    return get_templates().TemplateResponse(request, "admin/collections.html", context)


@router.post("/coletas/agora", dependencies=[AdminDep, SameOriginDep])
def collect_now(
    session: SessionDep, settings: SettingsDep, background: BackgroundTasks
) -> Response:
    """Dispara a coleta em segundo plano. A trava no banco impede duas ao mesmo tempo."""
    if collection_running(session.get_bind()):
        return _redirect("/admin/coletas", msg="collect_busy")
    background.add_task(manual_collection, settings)
    return _redirect("/admin/coletas", msg="collect_started")
