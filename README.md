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

## Coleta do PNCP

A coleta usa a [API pública de consulta do PNCP](https://pncp.gov.br/api/consulta/swagger-ui/index.html)
(endpoint `/v1/contratacoes/publicacao`), filtrando pela UF de `PNCP_STATE`. Como a API exige
uma modalidade por consulta, cada execução percorre as modalidades de `PNCP_MODALITIES`, página
a página.

```bash
uv run python -m app.collect                                    # últimos 2 dias (padrão)
uv run python -m app.collect --from 2026-11-01 --to 2026-11-22  # período específico
uv run python -m app.collect --modalidades 6,8                  # só pregão eletrônico e dispensa
docker compose exec app python -m app.collect                   # dentro do Docker
```

- **Sem duplicatas:** cada contratação é gravada pelo número de controle do PNCP (upsert).
  Coletar o mesmo período de novo só atualiza o que mudou na API.
- **Resiliente:** novas tentativas com backoff exponencial em erro 5xx, timeout, falha de rede e
  `429` (limite de requisições, que o PNCP aplica de fato). O cabeçalho `Retry-After` é
  respeitado quando vem na resposta.
- **Rastreável:** toda execução fica em `collection_runs`, com páginas lidas, novas, atualizadas
  e a mensagem de erro, se houver. Cada página é salva assim que chega, então uma falha no meio
  não perde o que já foi coletado. O comando sai com código `1` se a coleta falhar.
- **Datas:** a API informa horários de Brasília sem fuso (`PNCP_TIMEZONE`); no banco tudo é UTC.

Códigos de modalidade: 1 Leilão eletrônico, 2 Diálogo competitivo, 3 Concurso,
4 Concorrência eletrônica, 5 Concorrência presencial, 6 Pregão eletrônico, 7 Pregão presencial,
8 Dispensa, 9 Inexigibilidade, 10 Manifestação de interesse, 11 Pré-qualificação,
12 Credenciamento, 13 Leilão presencial.

## Testes e qualidade

```bash
uv run ruff check . && uv run ruff format --check .
uv run pytest                     # unitários + integração (se TEST_DATABASE_URL estiver definida)
```

Os testes de integração usam o banco de `TEST_DATABASE_URL`, que é **apagado e recriado** a
cada execução. O Compose cria esse banco (`<POSTGRES_DB>_test`) automaticamente. Nenhum teste
chama a API real do PNCP: as respostas reais ficam salvas em `tests/fixtures/pncp/`.
