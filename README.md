# Radar de Licitações MT

Coleta as contratações publicadas no [PNCP](https://pncp.gov.br), das UFs configuradas (padrão:
Mato Grosso; pode ser o Brasil inteiro), e avisa pequenas empresas quando surge uma licitação que combina com as palavras-chave delas.

> Projeto em construção, por fases. A documentação completa (arquitetura, diagramas,
> decisões técnicas) entra na Fase 6.

## Como rodar com Docker

```bash
cp .env.example .env          # ajuste a senha do Postgres
docker compose up --build
```

- Aplicação: http://localhost:8000
- Painel: http://localhost:8000/painel
- Alertas (área administrativa): http://localhost:8000/admin/alertas
- E-mails de desenvolvimento (Mailpit): http://localhost:8025
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

## Telas e API

| Endereço | O que é |
|---|---|
| `/` | Licitações mais recentes, com busca e filtros |
| `/licitacoes/{id}` | Detalhe da licitação, com link para o edital no PNCP |
| `/api/tenders` | Mesma listagem em JSON, com os mesmos filtros |
| `/api/tenders/{id}` | Detalhe em JSON |
| `/api/states`, `/api/municipalities?state=MT`, `/api/modalities` | Valores aceitos nos filtros |
| `/docs` | Documentação interativa da API |

**Filtros:** busca no objeto (`q`), UF (`state`), município (código IBGE), modalidade, faixa de
valor estimado, período de publicação e "só com propostas ainda abertas" (inclui as que ainda vão
abrir). Com mais de uma UF coletada, a tela pede a UF antes de listar os municípios.

**Busca textual:** usa o full-text search do PostgreSQL com dicionário `portuguese` + `unaccent`.
Por isso `manutencao` encontra "MANUTENÇÃO" e `computador` encontra "computadores". Aceita
`"frase exata"`, `or` e `-palavra` para excluir.

```bash
curl "http://localhost:8000/api/tenders?q=manutencao&municipality=5107602&open_only=true"
```

Datas dos filtros são dias no fuso de exibição (padrão: Brasília); na API, datas saem em UTC (ISO 8601) e valores
como texto decimal (`"3500000.0000"`) para não perder precisão. As telas funcionam sem
JavaScript; com ele, o HTMX atualiza só a lista ao mudar um filtro.

## Coleta do PNCP

A coleta usa a [API pública de consulta do PNCP](https://pncp.gov.br/api/consulta/swagger-ui/index.html)
(endpoint `/v1/contratacoes/publicacao`). Como a API exige uma modalidade por consulta, cada
execução percorre as modalidades de `PNCP_MODALITIES`, página a página.

**Abrangência (`PNCP_STATES`):** uma lista de UFs (`MT`, `MT,MS,GO`...) ou vazio/`BR` para o
Brasil inteiro, que é coletado numa consulta só por modalidade, sem filtro de UF. O padrão é `MT`.

| | Só MT | Brasil inteiro |
|---|---|---|
| Licitações por dia (aprox.) | 50 a 70 | 7 mil |
| Requisições por coleta (2 dias, todas as modalidades) | ~15 | ~300 |
| Tempo por coleta | segundos | 10 a 30 min (limite de requisições do PNCP) |
| Crescimento do banco | dezenas de MB/ano | 8 a 10 GB/ano |

```bash
uv run python -m app.collect                                    # últimos 2 dias (padrão)
uv run python -m app.collect --from 2026-11-01 --to 2026-11-22  # período específico
uv run python -m app.collect --modalidades 6,8                  # só pregão eletrônico e dispensa
uv run python -m app.collect --ufs MT,MS                        # outras UFs (ou --ufs BR)
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
- **Educado com a API:** intervalo mínimo entre requisições (`PNCP_REQUEST_INTERVAL_SECONDS`,
  padrão 1 s), o que reduz as respostas 429 nas coletas grandes.
- **Datas:** a API informa horários de Brasília sem fuso (`PNCP_TIMEZONE`); no banco tudo é UTC.
  Nas telas, as datas saem no fuso de `DISPLAY_TIMEZONE`, que por padrão é o horário de Brasília,
  o mesmo dos editais. Em MT o relógio local está 1 hora atrás: 09:00 de Brasília são 08:00 em
  Cuiabá.

Códigos de modalidade: 1 Leilão eletrônico, 2 Diálogo competitivo, 3 Concurso,
4 Concorrência eletrônica, 5 Concorrência presencial, 6 Pregão eletrônico, 7 Pregão presencial,
8 Dispensa, 9 Inexigibilidade, 10 Manifestação de interesse, 11 Pré-qualificação,
12 Credenciamento, 13 Leilão presencial.

## Painel

Em **`/painel`**: totais do período (licitações, valor estimado, propostas abertas, municípios),
ranking de municípios por quantidade e por valor, licitações por categoria e evolução mensal.
Os filtros de período (últimos 3, 6, 12 ou 24 meses, sempre incluindo o mês atual) e de UF
valem para tudo na página.

- Os gráficos usam **Chart.js 4.6.1 via CDN** (jsDelivr, com hash de integridade SRI) e leem a
  API JSON `GET /api/dashboard/summary`, `/municipalities?order=tenders|value&limit=15`,
  `/categories` e `/monthly`, todas com `months` e `state`. Veja em `/docs`.
- Cada gráfico tem uma **tabela equivalente** ("Ver como tabela"), gerada no servidor. Se o CDN
  estiver fora do ar, as tabelas abrem sozinhas.
- **Categorias** são grupos de palavras-chave no objeto, definidos em `app/categories.py`, porque
  o PNCP não classifica o objeto. Uma licitação pode cair em mais de uma categoria.
- Licitações sem valor estimado contam na quantidade, mas não na soma de valores.
- O mês de cada licitação é o da publicação no horário de Brasília (não em UTC).

## Alertas e notificações

Cadastre os alertas em **`/admin/alertas`** (senha `ADMIN_PASSWORD`; também é preciso definir
`SECRET_KEY`). Cada alerta tem:

- **palavras-chave**, uma por linha. Basta uma casar. A busca é a mesma da tela: ignora acentos e
  maiúsculas, acha singular e plural ("obra" encontra "obras", "pneu" encontra "pneus"),
  aceita `"frase exata"` e `-palavra` para excluir;
- **abrangência**: UFs e/ou municípios (por nome, ex.: `Rondonópolis`; nomes repetidos em
  outras UFs como `Pedra Preta/MT`). Sem nenhum dos dois, vale para tudo o que é coletado;
- **faixa de valor** opcional. Licitações sem valor estimado também entram, para não perder
  oportunidades;
- **e-mail** do resumo e, opcionalmente, um **chat do Telegram**.

**Fluxo:** depois de cada coleta, as licitações novas são cruzadas com os alertas ativos e
gravadas em `alert_matches`. O resumo reúne o que ainda não foi enviado. Cada canal (e-mail e
Telegram) tem sua própria marca de envio, então uma licitação nunca sai duas vezes pelo mesmo
canal. Se um envio falhar, ela continua pendente e vai no próximo resumo. Ao criar um alerta, ele
já é cruzado com as licitações que ainda aceitam propostas.

```bash
uv run python -m app.collect   # coleta + cruzamento com os alertas
uv run python -m app.notify    # envia os resumos pendentes
```

Na tela de alertas também há o botão **"Enviar resumos pendentes agora"**. O envio diário
automático entra na Fase 6.

### E-mail

Configure `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURITY` (`starttls`, `ssl` ou `none`),
`SMTP_USERNAME`, `SMTP_PASSWORD` e `SMTP_FROM` no `.env`. Em desenvolvimento, o Docker Compose sobe
o **Mailpit**, que recebe os e-mails sem enviá-los de verdade: veja-os em
<http://localhost:8025>.

### Telegram (opcional)

1. Crie um bot com o [@BotFather](https://t.me/BotFather) e coloque o token em
   `TELEGRAM_BOT_TOKEN`.
2. Mande qualquer mensagem para o bot e abra `https://api.telegram.org/bot<TOKEN>/getUpdates`
   para ver o `chat.id` (ou use `@nome_do_canal`, com o bot como administrador do canal).
3. Informe esse chat no alerta.

O token nunca aparece nos logs: as URLs do httpx ficam fora do log em nível INFO.

## Testes e qualidade

```bash
uv run ruff check . && uv run ruff format --check .
uv run pytest                     # unitários + integração (se TEST_DATABASE_URL estiver definida)
```

Os testes de integração usam o banco de `TEST_DATABASE_URL`, que é **apagado e recriado** a
cada execução. O Compose cria esse banco (`<POSTGRES_DB>_test`) automaticamente. Nenhum teste
chama a API real do PNCP: as respostas reais ficam salvas em `tests/fixtures/pncp/`.
