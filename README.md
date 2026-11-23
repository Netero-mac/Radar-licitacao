# Radar de Licitações MT

Coleta as contratações publicadas no [PNCP](https://pncp.gov.br), filtra as de Mato Grosso e
avisa pequenas empresas quando surge uma licitação que combina com as palavras-chave delas.

> Projeto em construção, por fases. A documentação completa (arquitetura, diagramas,
> decisões técnicas) entra na Fase 6.

## Como rodar com Docker

```bash
cp .env.example .env          # ajuste a senha do Postgres
docker compose up --build
```

- Aplicação: http://localhost:8000
- Documentação da API: http://localhost:8000/docs
- Saúde: http://localhost:8000/health

As migrations são aplicadas automaticamente ao subir o container.

## Desenvolvimento local (sem Docker para a app)

Requer [uv](https://docs.astral.sh/uv/) e um PostgreSQL acessível (pode ser só o `db` do Compose).

```bash
uv sync                          # cria o .venv com todas as dependências
docker compose up -d db          # sobe apenas o banco
uv run alembic upgrade head      # aplica as migrations
uv run uvicorn app.main:app --reload
```

## Testes e qualidade

```bash
uv run ruff check . && uv run ruff format --check .
uv run pytest                     # unitários + integração (se TEST_DATABASE_URL estiver definida)
```

Os testes de integração usam o banco de `TEST_DATABASE_URL`, que é **apagado e recriado** a
cada execução. O Compose cria esse banco (`<POSTGRES_DB>_test`) automaticamente. Nenhum teste
chama a API real do PNCP: as respostas reais ficam salvas em `tests/fixtures/pncp/`.
