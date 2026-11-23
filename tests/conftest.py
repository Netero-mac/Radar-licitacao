import os

# Configuração mínima para importar a aplicação sem um .env.
# A URL abaixo não é usada pelos testes unitários (o banco é substituído).
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@localhost:5432/unused")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("LOG_FORMAT", "text")
