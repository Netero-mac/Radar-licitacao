import copy
from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from app.collectors.pncp import PncpTender
from app.collectors.pncp.modalities import modality_name
from app.collectors.pncp.schemas import agency_values, tender_values, to_utc
from app.models import Sphere
from tests.conftest import load_fixture

BRASILIA = ZoneInfo("America/Sao_Paulo")
RAW = load_fixture("publicacao_mt_pregao_eletronico_p1.json")["data"][0]


def test_converte_item_real_da_api() -> None:
    tender = PncpTender.model_validate(RAW)

    values = tender_values(tender, RAW, agency_id=7, source_tz=BRASILIA)

    assert values["pncp_control_number"] == "03347135000116-1-000084/2026"
    assert values["agency_id"] == 7
    assert values["municipality_name"] == "Jaciara"
    assert values["municipality_ibge_code"] == "5104807"
    assert values["state"] == "MT"
    assert values["modality_code"] == 6
    assert values["modality_name"] == "Pregão - Eletrônico"
    assert values["status_code"] == 1
    assert values["status"] == "Divulgada no PNCP"
    assert values["source_url"] == "https://pncp.gov.br/app/editais/03347135000116/2026/84"
    assert values["raw_data"] is RAW


def test_valor_estimado_e_decimal_exato() -> None:
    values = tender_values(PncpTender.model_validate(RAW), RAW, 1, BRASILIA)

    assert values["estimated_value"] == Decimal("5260541.6")
    assert isinstance(values["estimated_value"], Decimal)


def test_valor_estimado_pode_ser_nulo() -> None:
    raw = {**RAW, "valorTotalEstimado": None}

    assert (
        tender_values(PncpTender.model_validate(raw), raw, 1, BRASILIA)["estimated_value"] is None
    )


def test_datas_do_horario_de_brasilia_sao_gravadas_em_utc() -> None:
    values = tender_values(PncpTender.model_validate(RAW), RAW, 1, BRASILIA)

    # "2026-11-18T09:03:41" em Brasília (UTC-3) = 12:03:41 UTC
    assert values["published_at"] == datetime(2026, 11, 18, 12, 3, 41, tzinfo=UTC)
    assert values["proposals_open_at"] == datetime(2026, 11, 19, 10, 0, tzinfo=UTC)
    assert values["proposals_close_at"] == datetime(2026, 12, 2, 12, 0, tzinfo=UTC)
    assert values["pncp_updated_at"] == datetime(2026, 11, 18, 12, 3, 42, tzinfo=UTC)


def test_to_utc_respeita_data_que_ja_tem_fuso() -> None:
    aware = datetime(2026, 11, 18, 9, 0, tzinfo=ZoneInfo("America/Cuiaba"))

    assert to_utc(aware, BRASILIA) == datetime(2026, 11, 18, 13, 0, tzinfo=UTC)
    assert to_utc(None, BRASILIA) is None


def test_datas_de_proposta_podem_faltar() -> None:
    raw = {**RAW, "dataAberturaProposta": None, "dataEncerramentoProposta": None}

    values = tender_values(PncpTender.model_validate(raw), raw, 1, BRASILIA)

    assert values["proposals_open_at"] is None
    assert values["proposals_close_at"] is None


@pytest.mark.parametrize(
    ("esfera", "sphere"),
    [
        ("M", Sphere.MUNICIPAL),
        ("E", Sphere.STATE),
        ("F", Sphere.FEDERAL),
        ("D", Sphere.DISTRICT),
        ("N", Sphere.NOT_APPLICABLE),
    ],
)
def test_esfera_do_orgao(esfera: str, sphere: Sphere) -> None:
    raw = copy.deepcopy(RAW)
    raw["orgaoEntidade"]["esferaId"] = esfera

    values = agency_values(PncpTender.model_validate(raw))

    assert values == {"cnpj": "03347135000116", "name": "MUNICIPIO DE JACIARA", "sphere": sphere}


def test_esfera_desconhecida_gera_erro() -> None:
    raw = copy.deepcopy(RAW)
    raw["orgaoEntidade"]["esferaId"] = "X"

    with pytest.raises(ValueError, match="esfera desconhecida"):
        PncpTender.model_validate(raw).sphere()


def test_item_sem_campo_obrigatorio_e_rejeitado() -> None:
    raw = {key: value for key, value in RAW.items() if key != "numeroControlePNCP"}

    with pytest.raises(ValidationError):
        PncpTender.model_validate(raw)


def test_nome_de_modalidade() -> None:
    assert modality_name(6) == "Pregão - Eletrônico"
    assert modality_name(99) == "Modalidade 99"
