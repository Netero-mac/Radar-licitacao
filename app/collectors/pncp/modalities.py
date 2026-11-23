"""Modalidades de contratação do PNCP (Manual de Integração, tabela de domínio).

O endpoint /v1/contratacoes/publicacao exige uma modalidade por consulta, por isso a
coleta percorre a lista configurada em PNCP_MODALITIES.
"""

MODALITIES: dict[int, str] = {
    1: "Leilão - Eletrônico",
    2: "Diálogo Competitivo",
    3: "Concurso",
    4: "Concorrência - Eletrônica",
    5: "Concorrência - Presencial",
    6: "Pregão - Eletrônico",
    7: "Pregão - Presencial",
    8: "Dispensa",
    9: "Inexigibilidade",
    10: "Manifestação de Interesse",
    11: "Pré-qualificação",
    12: "Credenciamento",
    13: "Leilão - Presencial",
}


def modality_name(code: int) -> str:
    return MODALITIES.get(code, f"Modalidade {code}")
