import pytest

from app.search_query import Term, parse, variants


@pytest.mark.parametrize(
    ("word", "expected"),
    [
        ("obra", "obras"),
        ("obras", "obra"),
        ("pneu", "pneus"),
        ("construção", "construcoes"),
        ("construções", "construcao"),
        ("caminhão", "caminhoes"),
        ("móvel", "moveis"),
        ("móveis", "movel"),
        ("hospitalar", "hospitalares"),
        ("hospitais", "hospital"),
        ("computadores", "computador"),
        ("item", "itens"),
        ("itens", "item"),
        ("combustível", "combustiveis"),
        ("notebook", "notebooks"),
        ("mês", "meses"),
    ],
)
def test_singular_e_plural(word: str, expected: str) -> None:
    forms = variants(word)

    assert forms[0] == word  # a palavra digitada vem primeiro
    assert expected in forms


@pytest.mark.parametrize("word", ["ti", "a", "123", "4x4", "pc"])
def test_palavras_curtas_ou_com_numeros_ficam_como_estao(word: str) -> None:
    assert variants(word) == [word]


def test_sintaxe_do_websearch() -> None:
    assert parse('manutenção "ar condicionado" OR split -veicular') == [
        [Term("manutenção")],
        [Term("ar condicionado", phrase=True), Term("split")],
        [Term("veicular", negated=True)],
    ]
    assert parse('-"mão de obra" or') == [[Term("mão de obra", negated=True, phrase=True)]]
    assert parse("OR obra") == [[Term("obra")]]
    assert parse('  "" - ') == []
