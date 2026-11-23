"""Unidades da Federação: sigla, código IBGE e nome.

Os dois primeiros dígitos do código IBGE de um município são o código da UF
(ex.: Rondonópolis 5107602 -> 51 = MT).
"""

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
