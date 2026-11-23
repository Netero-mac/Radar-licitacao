"""Busca full-text que também acha o plural (e o singular) de cada palavra.

O stemmer de português do PostgreSQL não junta vários plurais: "obra"/"obras",
"pneu"/"pneus", "construção"/"construções", "móvel"/"móveis" viram termos diferentes.
Aqui cada palavra digitada vira (palavra OU suas formas de singular/plural), gerando as
formas pelas regras do português. Formas que não existem não atrapalham: só não casam.

A sintaxe aceita é a mesma do ``websearch_to_tsquery`` (campo de busca e palavras-chave
dos alertas): palavras separadas por espaço (todas obrigatórias), ``OR`` entre termos,
``"frase exata"`` e ``-palavra`` para excluir. Frases não são expandidas: valem como
digitadas. Como no websearch, o E é mais forte que o OU: ``a b OR c`` = a E (b OU c).

A consulta é montada no próprio PostgreSQL (tsquery_and/or/not sobre
websearch_to_tsquery de cada termo), então acentos, maiúsculas e palavras vazias
("de", "para") são tratados como antes.
"""

import re
import unicodedata
from dataclasses import dataclass

from sqlalchemy import ColumnElement, case, func, literal_column

from app.models.tender import SEARCH_CONFIG

SEARCH_REGCONFIG = literal_column(f"'{SEARCH_CONFIG}'::regconfig")

_TOKEN = re.compile(r'-?"[^"]*"?|\S+')
_WORD = re.compile(r"\w+")
_MIN_LENGTH = 3


@dataclass(frozen=True, slots=True)
class Term:
    text: str
    negated: bool = False
    phrase: bool = False


def parse(text: str) -> list[list[Term]]:
    """Grupos ligados por E; dentro de cada grupo, termos ligados por OU."""
    groups: list[list[Term]] = []
    pending_or = False
    for token in _TOKEN.findall(text):
        if token.lower() == "or":
            pending_or = bool(groups)
            continue
        negated = token.startswith("-")
        body = token[1:] if negated else token
        phrase = body.startswith('"')
        if phrase:
            body = body.strip('"').strip()
        if not body:
            continue
        term = Term(body, negated, phrase)
        if pending_or:
            groups[-1].append(term)
        else:
            groups.append([term])
        pending_or = False
    return groups


def _strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _plurals(w: str) -> set[str]:
    if w.endswith("ao"):  # construção → construções (e os raros -ães/-ãos)
        return {w[:-2] + "oes", w[:-2] + "aes", w + "s"}
    if w.endswith("al"):  # hospital → hospitais
        return {w[:-1] + "is"}
    if w.endswith("el"):  # móvel → móveis, papel → papéis
        return {w[:-2] + "eis"}
    if w.endswith("ol"):  # farol → faróis
        return {w[:-2] + "ois"}
    if w.endswith("ul"):  # azul → azuis
        return {w[:-2] + "uis"}
    if w.endswith("il"):  # funil → funis, fóssil → fósseis
        return {w[:-2] + "is", w[:-2] + "eis"}
    if w.endswith("m"):  # item → itens
        return {w[:-1] + "ns"}
    if w.endswith(("r", "z", "s")):  # computador → computadores, mês → meses
        return {w + "es"}
    return {w + "s"}  # obra → obras, pneu → pneus, notebook → notebooks


def _singulars(w: str) -> set[str]:
    forms: set[str] = set()
    if w.endswith(("oes", "aes")):
        forms.add(w[:-3] + "ao")
    if w.endswith("ais"):
        forms.add(w[:-2] + "l")
    elif w.endswith("eis"):
        forms |= {w[:-3] + "el", w[:-3] + "il"}
    elif w.endswith("ois"):
        forms.add(w[:-3] + "ol")
    elif w.endswith("uis"):
        forms.add(w[:-3] + "ul")
    elif w.endswith("is"):
        forms.add(w[:-1] + "l")  # funis → funil
    if w.endswith("ns"):
        forms.add(w[:-2] + "m")
    if w.endswith(("res", "zes", "ses")):
        forms.add(w[:-2])
    if w.endswith("s"):
        forms.add(w[:-1])
    return forms


def variants(word: str) -> list[str]:
    """A palavra e suas prováveis formas de singular e plural (sem acento)."""
    w = _strip_accents(word.lower())
    if len(w) < _MIN_LENGTH or not w.isalpha():
        return [word]
    forms = _plurals(w) | _singulars(w)
    extra = sorted(form for form in forms if len(form) >= _MIN_LENGTH and form != w)
    return [word, *extra]


def _websearch(text: str) -> ColumnElement:
    return func.websearch_to_tsquery(SEARCH_REGCONFIG, text)


def _term_query(term: Term) -> ColumnElement:
    if term.phrase:
        query = _websearch(f'"{term.text}"')
    elif _WORD.fullmatch(term.text):
        word, *others = variants(term.text)
        query = _websearch(word)
        if others:
            # Palavra vazia ("para") não ganha plural: "paras" deixaria de ser vazia.
            expanded = _any([query, *(_websearch(form) for form in others)])
            query = case((func.numnode(query) == 0, query), else_=expanded)
    else:  # "manutenção/reparo", "auto-peças": fica como o websearch entende
        query = _websearch(term.text)
    return func.tsquery_not(query) if term.negated else query


def _any(queries: object) -> ColumnElement:
    items = list(queries)  # type: ignore[call-overload]
    result = items[0]
    for query in items[1:]:
        result = func.tsquery_or(result, query)
    return result


def build_tsquery(text: str) -> ColumnElement:
    """tsquery equivalente ao websearch_to_tsquery(text), com singular/plural."""
    groups = parse(text)
    if not groups:
        return _websearch("")
    result = None
    for group in groups:
        query = _any(_term_query(term) for term in group)
        result = query if result is None else func.tsquery_and(result, query)
    return result
