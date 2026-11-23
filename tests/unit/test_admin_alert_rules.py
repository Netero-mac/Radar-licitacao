"""Regras de quando avisar o administrador (sem banco: só a sequência de execuções)."""

import pytest

from app.models import CollectionRun, CollectionStatus
from app.services.admin_alerts import AdminAlert, decide, failure_streak, has_problem

OK = "ok"
FAIL = "fail"  # erro na coleta
SEND = "send"  # coleta ok, falha no envio dos resumos


def _runs(*kinds: str) -> list[CollectionRun]:
    """Da mais recente para a mais antiga, como vem do banco."""
    return [
        CollectionRun(
            status=CollectionStatus.FAILED if kind == FAIL else CollectionStatus.SUCCESS,
            notification_failures=2 if kind == SEND else 0,
        )
        for kind in kinds
    ]


def test_problema_e_erro_na_coleta_ou_no_envio() -> None:
    ok, fail, send = _runs(OK, FAIL, SEND)
    assert (has_problem(ok), has_problem(fail), has_problem(send)) == (False, True, True)
    assert not has_problem(CollectionRun(status=CollectionStatus.SUCCESS))  # sem resumo


def test_sequencia_conta_a_partir_da_mais_recente() -> None:
    assert failure_streak(_runs(FAIL, SEND, OK, FAIL)) == 2
    assert failure_streak(_runs(OK, FAIL)) == 0
    assert failure_streak([]) == 0


@pytest.mark.parametrize(
    ("kinds", "expected"),
    [
        ((FAIL, OK), None),  # 1 falha: ainda não avisa
        ((FAIL, FAIL, OK), AdminAlert.FAILING),  # chegou a 2: avisa
        ((SEND, FAIL), AdminAlert.FAILING),  # envio e coleta contam igual
        ((FAIL, FAIL, FAIL), None),  # 3ª seguida: já avisou, não repete
        ((OK, FAIL, FAIL), AdminAlert.RECOVERED),  # voltou depois do aviso
        ((OK, FAIL, OK), None),  # voltou antes de chegar ao aviso: nada a dizer
        ((OK, OK, OK), None),
        ((), None),
    ],
)
def test_decide_com_limite_de_duas(kinds: tuple[str, ...], expected: AdminAlert | None) -> None:
    assert decide(_runs(*kinds), threshold=2) is expected


def test_limite_de_uma_avisa_na_primeira() -> None:
    assert decide(_runs(FAIL, OK), threshold=1) is AdminAlert.FAILING
    assert decide(_runs(OK, FAIL), threshold=1) is AdminAlert.RECOVERED
