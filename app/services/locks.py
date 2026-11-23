"""Trava no banco para que só uma coleta rode por vez.

Usa um advisory lock do PostgreSQL de sessão, numa conexão própria mantida aberta
durante a coleta. Se o processo morrer, a conexão cai e o PostgreSQL solta a trava
sozinho: não há trava "esquecida" para limpar à mão. Vale entre processos (agendador,
botão "Coletar agora" e CLI) e entre máquinas que usam o mesmo banco.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, func, select

logger = logging.getLogger(__name__)

# Número arbitrário que identifica a trava da coleta no banco.
COLLECTION_LOCK_ID = 7_226_001


@contextmanager
def collection_lock(engine: Engine) -> Iterator[bool]:
    """Tenta pegar a trava sem esperar; devolve False se outra coleta estiver rodando."""
    # AUTOCOMMIT: a conexão segura a trava sem deixar uma transação aberta.
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        acquired = bool(connection.scalar(select(func.pg_try_advisory_lock(COLLECTION_LOCK_ID))))
        try:
            yield acquired
        finally:
            if acquired:
                connection.scalar(select(func.pg_advisory_unlock(COLLECTION_LOCK_ID)))


def collection_running(engine: Engine) -> bool:
    """Há uma coleta rodando agora (em qualquer processo)?"""
    with collection_lock(engine) as acquired:
        return not acquired
