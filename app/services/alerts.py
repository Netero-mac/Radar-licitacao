"""Regras dos alertas: cadastro e cruzamento com as licitações.

Uma licitação casa com um alerta ativo quando:
- alguma palavra-chave encontra o objeto (mesma busca da tela: sem acento, com flexões,
  aceita "frase exata" e -exclusão);
- é de uma das UFs ou de um dos municípios do alerta (listas vazias = tudo o que é coletado);
- o valor estimado está na faixa do alerta (licitação sem valor informado também entra).
"""

import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models import Alert, AlertMatch
from app.repositories import alerts as repository
from app.repositories.alerts import AlertStats
from app.schemas.alerts import AlertForm

logger = logging.getLogger(__name__)


class IneffectiveKeywordError(ValueError):
    """Palavra-chave que nunca encontraria nada (só palavras vazias como "de", "para")."""

    def __init__(self, keywords: list[str]) -> None:
        self.keywords = keywords
        super().__init__(
            "sem efeito na busca (use palavras com significado): " + ", ".join(keywords)
        )


def list_alerts(session: Session) -> list[AlertStats]:
    return repository.list_with_stats(session)


def get_alert(session: Session, alert_id: int) -> Alert | None:
    return repository.get(session, alert_id)


def _check_keywords(session: Session, form: AlertForm) -> None:
    ineffective = repository.ineffective_keywords(session, form.keywords)
    if ineffective:
        raise IneffectiveKeywordError(ineffective)


def _apply(alert: Alert, form: AlertForm) -> None:
    for field, value in form.model_dump().items():
        setattr(alert, field, value)


def _backfill(session: Session, alert: Alert, now: datetime) -> int:
    """Casa o alerta com as licitações que ainda aceitam propostas.

    Assim o primeiro resumo de um alerta recém-criado já traz o que está aberto.
    """
    if not alert.active:
        return 0
    return repository.create_matches(session, alert_id=alert.id, proposals_open_at=now)


def create_alert(
    session: Session, form: AlertForm, now: datetime | None = None
) -> tuple[Alert, int]:
    """Cadastra o alerta e devolve (alerta, licitações abertas que já casam)."""
    _check_keywords(session, form)
    alert = Alert()
    _apply(alert, form)
    session.add(alert)
    session.flush()
    matched = _backfill(session, alert, now or datetime.now(UTC))
    session.commit()
    logger.info("Alerta criado", extra={"alert_id": alert.id, "matched": matched})
    return alert, matched


def update_alert(
    session: Session, alert: Alert, form: AlertForm, now: datetime | None = None
) -> int:
    """Atualiza o alerta e recalcula os casamentos que ainda não foram enviados.

    O que já foi notificado permanece (não é reenviado nem apagado do histórico).
    """
    _check_keywords(session, form)
    _apply(alert, form)
    session.flush()
    repository.delete_unsent_matches(session, alert.id)
    matched = _backfill(session, alert, now or datetime.now(UTC))
    session.commit()
    logger.info("Alerta atualizado", extra={"alert_id": alert.id, "matched": matched})
    return matched


def set_active(session: Session, alert: Alert, active: bool, now: datetime | None = None) -> None:
    alert.active = active
    session.flush()
    if active:
        _backfill(session, alert, now or datetime.now(UTC))
    session.commit()


def delete_alert(session: Session, alert: Alert) -> None:
    session.delete(alert)
    session.commit()
    logger.info("Alerta excluído", extra={"alert_id": alert.id})


def recent_matches(session: Session, alert_id: int) -> list[AlertMatch]:
    return repository.recent_matches(session, alert_id)


def match_new_tenders(session: Session, created_since: datetime) -> int:
    """Depois de uma coleta: cruza as licitações novas com todos os alertas ativos."""
    created = repository.create_matches(session, tenders_created_since=created_since)
    session.commit()
    logger.info(
        "Cruzamento com alertas concluído",
        extra={"created_since": created_since.isoformat(), "matches": created},
    )
    return created
