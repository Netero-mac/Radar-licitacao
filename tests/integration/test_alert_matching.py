from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Alert, AlertMatch, Tender
from app.repositories import alerts as repository
from app.schemas.alerts import AlertForm
from app.services import alerts as service
from tests.integration.factories import (
    CUIABA,
    PEDRA_PRETA,
    RONDONOPOLIS,
    make_alert,
    make_tender,
)

NOW = datetime(2026, 11, 22, 15, 0, tzinfo=UTC)
LONG_AGO = datetime(2000, 1, 1, tzinfo=UTC)


def _match_all(session: Session) -> int:
    return service.match_new_tenders(session, created_since=LONG_AGO)


def _matched(session: Session, alert: Alert) -> set[int]:
    stmt = select(AlertMatch.tender_id).where(AlertMatch.alert_id == alert.id)
    return set(session.scalars(stmt))


# --- Palavras-chave --------------------------------------------------------------------


def test_palavra_chave_ignora_acento_caixa_e_plural(db_session: Session) -> None:
    alert = make_alert(db_session, keywords=["manutencao de computador"])
    hit = make_tender(
        db_session, object_description="MANUTENÇÃO PREVENTIVA DE COMPUTADORES E NOTEBOOKS"
    )
    make_tender(db_session, object_description="Aquisição de gêneros alimentícios")

    _match_all(db_session)

    assert _matched(db_session, alert) == {hit.id}


def test_basta_uma_palavra_chave_casar(db_session: Session) -> None:
    alert = make_alert(db_session, keywords=["impressora", "ar condicionado"])
    printer = make_tender(db_session, object_description="Locação de impressoras")
    ac = make_tender(db_session, object_description="Instalação de condicionador de ar")
    make_tender(db_session, object_description="Pavimentação asfáltica")

    _match_all(db_session)

    assert _matched(db_session, alert) == {printer.id, ac.id}


def test_frase_exata_e_exclusao(db_session: Session) -> None:
    alert = make_alert(db_session, keywords=['"ar condicionado" -veicular'])
    building = make_tender(db_session, object_description="Manutenção de ar condicionado split")
    make_tender(db_session, object_description="Ar condicionado veicular para ambulâncias")
    make_tender(db_session, object_description="Condicionado ao ar livre")  # ordem diferente

    _match_all(db_session)

    assert _matched(db_session, alert) == {building.id}


# --- Abrangência -----------------------------------------------------------------------


def test_municipio(db_session: Session) -> None:
    alert = make_alert(db_session, municipalities=[RONDONOPOLIS[0], PEDRA_PRETA[0]])
    roo = make_tender(db_session, municipality=RONDONOPOLIS, object_description="Manutenção")
    pp = make_tender(db_session, municipality=PEDRA_PRETA, object_description="Manutenção")
    make_tender(db_session, municipality=CUIABA, object_description="Manutenção")

    _match_all(db_session)

    assert _matched(db_session, alert) == {roo.id, pp.id}


def test_uf_ou_municipio(db_session: Session) -> None:
    alert = make_alert(db_session, states=["MS"], municipalities=[RONDONOPOLIS[0]])
    roo = make_tender(db_session, municipality=RONDONOPOLIS, object_description="Manutenção")
    ms = make_tender(
        db_session,
        municipality=("5002704", "Campo Grande"),
        state="MS",
        object_description="Manutenção",
    )
    make_tender(db_session, municipality=CUIABA, object_description="Manutenção")

    _match_all(db_session)

    assert _matched(db_session, alert) == {roo.id, ms.id}


def test_sem_uf_nem_municipio_vale_para_tudo(db_session: Session) -> None:
    alert = make_alert(db_session)
    tenders = {
        make_tender(db_session, municipality=m, object_description="Manutenção").id
        for m in (RONDONOPOLIS, CUIABA)
    }

    _match_all(db_session)

    assert _matched(db_session, alert) == tenders


# --- Faixa de valor --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("min_value", "max_value", "expected"),
    [
        (Decimal("1000"), Decimal("50000"), {"10 mil", "sem valor"}),
        (Decimal("10000"), None, {"10 mil", "1 milhão", "sem valor"}),
        (None, Decimal("9999.99"), {"500", "sem valor"}),
        (None, None, {"500", "10 mil", "1 milhão", "sem valor"}),
    ],
)
def test_faixa_de_valor(
    db_session: Session,
    min_value: Decimal | None,
    max_value: Decimal | None,
    expected: set[str],
) -> None:
    alert = make_alert(db_session, min_value=min_value, max_value=max_value)
    values = {
        "500": Decimal("500"),
        "10 mil": Decimal("10000"),
        "1 milhão": Decimal("1000000"),
        "sem valor": None,  # valor não informado entra para não perder oportunidades
    }
    ids = {
        make_tender(db_session, estimated_value=value, object_description="Manutenção").id: label
        for label, value in values.items()
    }

    _match_all(db_session)

    assert {ids[tender_id] for tender_id in _matched(db_session, alert)} == expected


# --- Regras gerais ---------------------------------------------------------------------


def test_alerta_inativo_nao_recebe(db_session: Session) -> None:
    alert = make_alert(db_session, active=False)
    make_tender(db_session, object_description="Manutenção")

    assert _match_all(db_session) == 0
    assert _matched(db_session, alert) == set()


def test_rodar_de_novo_nao_duplica_nem_reabre_o_que_foi_enviado(db_session: Session) -> None:
    alert = make_alert(db_session)
    make_tender(db_session, object_description="Manutenção")
    assert _match_all(db_session) == 1
    match = db_session.scalars(select(AlertMatch)).one()
    match.notified_at = NOW
    db_session.commit()

    assert _match_all(db_session) == 0

    db_session.refresh(match)
    assert match.notified_at == NOW
    assert len(_matched(db_session, alert)) == 1


def test_so_cruza_licitacoes_criadas_depois_da_coleta(db_session: Session) -> None:
    alert = make_alert(db_session)
    old = make_tender(db_session, object_description="Manutenção")
    old.created_at = NOW - timedelta(days=3)
    new = make_tender(db_session, object_description="Manutenção")
    db_session.commit()
    db_session.refresh(new)

    service.match_new_tenders(db_session, created_since=new.created_at - timedelta(seconds=1))

    assert _matched(db_session, alert) == {new.id}


# --- Cadastro --------------------------------------------------------------------------


def _form(**overrides: object) -> AlertForm:
    data: dict[str, object] = {"name": "TI", "email": "ti@empresa.com", "keywords": "computador"}
    form, errors = AlertForm.parse({**data, **overrides}, preferred_states=["MT"])
    assert form is not None, errors
    return form


def test_alerta_novo_ja_casa_com_licitacoes_abertas(db_session: Session) -> None:
    open_ = make_tender(
        db_session,
        object_description="Aquisição de computadores",
        proposals_close_at=NOW + timedelta(days=5),
    )
    make_tender(
        db_session,
        object_description="Aquisição de computadores",
        proposals_close_at=NOW - timedelta(days=1),
    )
    make_tender(db_session, object_description="Aquisição de computadores", proposals_close_at=None)

    alert, matched = service.create_alert(db_session, _form(), now=NOW)

    assert matched == 1
    assert _matched(db_session, alert) == {open_.id}


def test_editar_recalcula_pendentes_e_preserva_enviados(db_session: Session) -> None:
    future = NOW + timedelta(days=5)
    pc = make_tender(db_session, object_description="Computadores", proposals_close_at=future)
    printer = make_tender(db_session, object_description="Impressoras", proposals_close_at=future)
    alert, _ = service.create_alert(db_session, _form(keywords="computador"), now=NOW)
    sent = db_session.scalars(select(AlertMatch).where(AlertMatch.tender_id == pc.id)).one()
    sent.notified_at = NOW
    db_session.commit()

    matched = service.update_alert(db_session, alert, _form(keywords="impressora"), now=NOW)

    assert matched == 1
    # o enviado fica no histórico; o novo critério entra como pendente
    assert _matched(db_session, alert) == {pc.id, printer.id}


def test_palavra_chave_sem_efeito_e_rejeitada(db_session: Session) -> None:
    with pytest.raises(service.IneffectiveKeywordError, match="de, para o"):
        service.create_alert(db_session, _form(keywords="computador\nde\npara o"))

    assert repository.ineffective_keywords(db_session, ["computador"]) == []


def test_desativar_e_reativar(db_session: Session) -> None:
    make_tender(
        db_session, object_description="Computadores", proposals_close_at=NOW + timedelta(days=1)
    )
    alert, matched = service.create_alert(db_session, _form(active=False), now=NOW)
    assert matched == 0

    service.set_active(db_session, alert, True, now=NOW)

    assert alert.active
    assert len(_matched(db_session, alert)) == 1


def test_estatisticas_e_exclusao(db_session: Session) -> None:
    alert = make_alert(db_session)
    make_tender(db_session, object_description="Manutenção")
    _match_all(db_session)

    [stats] = service.list_alerts(db_session)
    assert (stats.matches, stats.pending_email) == (1, 1)
    assert service.recent_matches(db_session, alert.id)[0].tender.object_description == "Manutenção"

    service.delete_alert(db_session, alert)

    assert service.list_alerts(db_session) == []
    assert db_session.scalars(select(AlertMatch)).all() == []
    assert db_session.scalars(select(Tender)).all() != []  # licitações não são apagadas
