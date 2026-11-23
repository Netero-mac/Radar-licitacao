"""Unidades da Federação: sigla, código IBGE e nome.

Os dois primeiros dígitos do código IBGE de um município são o código da UF
(ex.: Rondonópolis 5107602 -> 51 = MT).
"""

import json
import unicodedata
from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path

STATES: dict[str, tuple[str, str]] = {
    "AC": ("12", "Acre"),
    "AL": ("27", "Alagoas"),
    "AP": ("16", "Amapá"),
    "AM": ("13", "Amazonas"),
    "BA": ("29", "Bahia"),
    "CE": ("23", "Ceará"),
    "DF": ("53", "Distrito Federal"),
    "ES": ("32", "Espírito Santo"),
    "GO": ("52", "Goiás"),
    "MA": ("21", "Maranhão"),
    "MT": ("51", "Mato Grosso"),
    "MS": ("50", "Mato Grosso do Sul"),
    "MG": ("31", "Minas Gerais"),
    "PA": ("15", "Pará"),
    "PB": ("25", "Paraíba"),
    "PR": ("41", "Paraná"),
    "PE": ("26", "Pernambuco"),
    "PI": ("22", "Piauí"),
    "RJ": ("33", "Rio de Janeiro"),
    "RN": ("24", "Rio Grande do Norte"),
    "RS": ("43", "Rio Grande do Sul"),
    "RO": ("11", "Rondônia"),
    "RR": ("14", "Roraima"),
    "SC": ("42", "Santa Catarina"),
    "SP": ("35", "São Paulo"),
    "SE": ("28", "Sergipe"),
    "TO": ("17", "Tocantins"),
}


def state_name(code: str) -> str:
    return STATES.get(code, (code, code))[1]


def municipality_in_state(ibge_code: str, state: str) -> bool:
    entry = STATES.get(state)
    return entry is not None and ibge_code.startswith(entry[0])


# --- Municípios (lista oficial do IBGE, em app/data/municipalities.json) -----------------

_MUNICIPALITIES_FILE = Path(__file__).parent / "data" / "municipalities.json"


@lru_cache
def municipalities() -> dict[str, tuple[str, str]]:
    """{código IBGE: (nome, UF)} dos 5.571 municípios."""
    rows = json.loads(_MUNICIPALITIES_FILE.read_text(encoding="utf-8"))
    return {code: (name, state) for code, name, state in rows}


def municipality_label(code: str) -> str:
    """5107602 -> "Rondonópolis/MT" (códigos desconhecidos saem como vieram)."""
    entry = municipalities().get(code)
    return f"{entry[0]}/{entry[1]}" if entry else code


def normalize_name(value: str) -> str:
    """Compara nomes sem acento, caixa ou espaços extras ("SÃO  josé" == "sao jose")."""
    decomposed = unicodedata.normalize("NFKD", value)
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(without_accents.casefold().replace("'", " ").split())


@lru_cache
def _by_name() -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    for code, (name, _) in municipalities().items():
        index.setdefault(normalize_name(name), []).append(code)
    return index


class MunicipalityNotFoundError(ValueError):
    pass


def resolve_municipality(text: str, preferred_states: Sequence[str] = ()) -> str:
    """Converte "Rondonópolis", "rondonopolis/mt" ou "5107602" no código IBGE.

    Nomes repetidos em várias UFs (ex.: Pedra Preta, em MT e RN) são resolvidos pelas UFs
    preferidas (as coletadas); se ainda houver dúvida, é preciso informar "Nome/UF".
    """
    text = text.strip()
    if text.isdigit():
        if text in municipalities():
            return text
        raise MunicipalityNotFoundError(f"código IBGE desconhecido: {text}")

    name, _, state = text.rpartition("/") if "/" in text else (text, "", "")
    state = state.strip().upper()
    if state and state not in STATES:
        raise MunicipalityNotFoundError(f"UF desconhecida em {text!r}")
    candidates = _by_name().get(normalize_name(name), [])
    if state:
        candidates = [code for code in candidates if municipalities()[code][1] == state]
    elif len(candidates) > 1 and preferred_states:
        preferred = [c for c in candidates if municipalities()[c][1] in preferred_states]
        candidates = preferred or candidates

    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise MunicipalityNotFoundError(f"município não encontrado: {text!r}")
    options = ", ".join(sorted(municipality_label(code) for code in candidates))
    raise MunicipalityNotFoundError(f"{text!r} existe em mais de uma UF; use {options}")
