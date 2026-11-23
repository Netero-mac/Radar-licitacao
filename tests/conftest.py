import json
import os
from pathlib import Path
from typing import Any

# Configuração mínima para importar a aplicação sem um .env.
# A URL abaixo não é usada pelos testes unitários (o banco é substituído).
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@localhost:5432/unused")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("LOG_FORMAT", "text")

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> Any:
    """Resposta real da API do PNCP salva em tests/fixtures/pncp/."""
    return json.loads((FIXTURES_DIR / "pncp" / name).read_text(encoding="utf-8"))
