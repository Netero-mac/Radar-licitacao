"""Coleta manual pela linha de comando.

    python -m app.collect                                   # período padrão (últimos 2 dias)
    python -m app.collect --from 2026-11-01 --to 2026-11-22
    python -m app.collect --from 2026-11-20 --modalidades 6,8

Sai com código 0 em caso de sucesso e 1 se a coleta falhar.
"""

import argparse
import logging
import sys
from collections.abc import Sequence
from datetime import date
from zoneinfo import ZoneInfo

from app.collectors.pncp import PncpClient
from app.collectors.pncp.modalities import MODALITIES
from app.config import get_settings
from app.db import get_sessionmaker
from app.logging_config import configure_logging
from app.models import CollectionStatus, CollectionTrigger
from app.services.collection import default_period, run_collection

logger = logging.getLogger("app.collect")


def _iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"data inválida: {value!r} (use AAAA-MM-DD)") from None


def _modalities(value: str) -> list[int]:
    try:
        codes = [int(part) for part in value.split(",") if part.strip()]
    except ValueError:
        raise argparse.ArgumentTypeError("use códigos numéricos separados por vírgula") from None
    unknown = sorted(set(codes) - MODALITIES.keys())
    if not codes or unknown:
        raise argparse.ArgumentTypeError(f"modalidade(s) desconhecida(s): {unknown}")
    return codes


def build_parser() -> argparse.ArgumentParser:
    modalities_help = ", ".join(f"{code}={name}" for code, name in MODALITIES.items())
    parser = argparse.ArgumentParser(
        prog="python -m app.collect",
        description="Coleta contratações publicadas no PNCP e grava no banco.",
    )
    parser.add_argument(
        "--from", dest="date_from", type=_iso_date, help="data inicial (AAAA-MM-DD)"
    )
    parser.add_argument("--to", dest="date_to", type=_iso_date, help="data final (AAAA-MM-DD)")
    parser.add_argument(
        "--modalidades",
        dest="modalities",
        type=_modalities,
        help=f"códigos separados por vírgula (padrão: PNCP_MODALITIES). {modalities_help}",
    )
    return parser


def resolve_period(
    date_from: date | None, date_to: date | None, lookback_days: int, tz: ZoneInfo
) -> tuple[date, date]:
    """Completa as datas que não foram informadas com o período padrão."""
    default_from, default_to = default_period(lookback_days, tz)
    date_to = date_to or default_to
    date_from = date_from or min(default_from, date_to)
    return date_from, date_to


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    source_tz = ZoneInfo(settings.pncp_timezone)

    date_from, date_to = resolve_period(
        args.date_from, args.date_to, settings.collection_lookback_days, source_tz
    )
    if date_from > date_to:
        parser.error("--from não pode ser posterior a --to")

    with get_sessionmaker()() as session, PncpClient.from_settings(settings) as client:
        run = run_collection(
            session,
            client,
            date_from=date_from,
            date_to=date_to,
            state=settings.pncp_state,
            modalities=args.modalities or settings.pncp_modalities,
            source_tz=source_tz,
            trigger=CollectionTrigger.CLI,
        )
    return 0 if run.status == CollectionStatus.SUCCESS else 1


if __name__ == "__main__":
    sys.exit(main())
