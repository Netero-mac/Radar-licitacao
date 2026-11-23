"""Categorias do painel: agrupamento das licitações por palavras-chave no objeto.

O PNCP não classifica o objeto da contratação, então cada categoria é uma busca
full-text (a mesma da tela de licitações: ignora acentos e a maioria dos plurais).
Uma licitação pode cair em mais de uma categoria — "manutenção de veículos e
computadores" conta nas duas — e as que não casam com nenhuma ficam em "Sem categoria".

Para ajustar, edite as palavras-chave abaixo; a sintaxe é a do campo de busca
(``OR`` entre termos, ``"frase exata"``).

Diferente da busca e dos alertas (app.search_query), aqui não há expansão automática
de singular/plural: a lista é exatamente o que está escrito, e as duas formas aparecem
quando o stemmer de português não as junta ("pneu"/"pneus", "construção"/"construções").
"obra" fica de fora de propósito: casaria com "mão de obra" (terceirização de
serviços), que não é obra.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Category:
    key: str
    name: str
    keywords: tuple[str, ...]

    @property
    def query(self) -> str:
        """Consulta para o websearch_to_tsquery: basta um dos termos."""
        return " OR ".join(self.keywords)


CATEGORIES: tuple[Category, ...] = (
    Category(
        "ti",
        "Tecnologia da informação",
        (
            "computador",
            "notebook",
            "notebooks",
            "impressora",
            "informática",
            "software",
            "softwares",
            "toner",
            "toners",
            '"tecnologia da informação"',
            "nobreak",
            "nobreaks",
        ),
    ),
    Category(
        "obras",
        "Obras e engenharia",
        (
            "obras",
            "pavimentação",
            "reforma",
            "construção",
            "construções",
            "engenharia",
            "asfáltico",
        ),
    ),
    Category(
        "saude",
        "Saúde",
        ("medicamento", "hospitalar", "odontológico", "laboratorial", "laboratoriais", "médico"),
    ),
    Category(
        "alimentacao",
        "Alimentação",
        ('"gêneros alimentícios"', "alimentação", "merenda", "refeição", "refeições", "alimento"),
    ),
    Category(
        "veiculos",
        "Veículos e combustíveis",
        (
            "veículo",
            "combustível",
            "combustíveis",
            "pneu",
            "pneus",
            "automotivo",
            "caminhão",
            "caminhões",
            "ônibus",
        ),
    ),
    Category(
        "limpeza",
        "Limpeza e higiene",
        ("limpeza", "higiene", "higienização", "descartável", "descartáveis"),
    ),
    Category(
        "expediente",
        "Material de expediente",
        ("expediente", "escritório", "papelaria"),
    ),
    Category(
        "mobiliario",
        "Móveis e eletrodomésticos",
        (
            "mobiliário",
            "móvel",
            "móveis",
            "eletrodoméstico",
            '"ar condicionado"',
            "condicionador",
        ),
    ),
)
