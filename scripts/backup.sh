#!/usr/bin/env sh
# Backup do banco com pg_dump (formato custom, comprimido), com data e hora no nome.
#
#   ./scripts/backup.sh
#
# Variáveis opcionais:
#   BACKUP_DIR        pasta dos arquivos (padrão: ./backups)
#   BACKUP_KEEP_DAYS  apaga backups mais antigos que isso (padrão: 14; 0 = nunca apaga)
#   COMPOSE_FILE      arquivo do Compose (padrão: docker-compose.prod.yml)
#
# Agendar todo dia às 3h (crontab -e):
#   0 3 * * * cd /caminho/do/projeto && ./scripts/backup.sh >> backups/backup.log 2>&1
set -eu

cd "$(dirname "$0")/.."

# Lê só estas chaves do .env (sem executar o arquivo); o ambiente tem prioridade.
env_value() {
  if [ -f .env ]; then sed -n "s/^$1=//p" .env | tail -n 1; fi
}
BACKUP_DIR="${BACKUP_DIR:-$(env_value BACKUP_DIR)}"
BACKUP_KEEP_DAYS="${BACKUP_KEEP_DAYS:-$(env_value BACKUP_KEEP_DAYS)}"

BACKUP_DIR="${BACKUP_DIR:-./backups}"
BACKUP_KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"

mkdir -p "$BACKUP_DIR"
stamp="$(date +%Y-%m-%d_%H%M%S)"
file="$BACKUP_DIR/radar_${stamp}.dump"

# Grava num arquivo temporário e só renomeia no fim: um backup pela metade
# (disco cheio, banco fora do ar) nunca fica com cara de backup bom.
if ! docker compose -f "$COMPOSE_FILE" exec -T db \
    sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom' > "$file.partial"; then
  rm -f "$file.partial"
  echo "ERRO: o pg_dump falhou; nenhum backup foi gravado." >&2
  exit 1
fi
if [ ! -s "$file.partial" ]; then
  rm -f "$file.partial"
  echo "ERRO: o backup saiu vazio." >&2
  exit 1
fi
mv "$file.partial" "$file"
echo "Backup salvo em $file ($(du -h "$file" | cut -f1))"

if [ "$BACKUP_KEEP_DAYS" -gt 0 ]; then
  find "$BACKUP_DIR" -maxdepth 1 -name 'radar_*.dump' -type f -mtime +"$BACKUP_KEEP_DAYS" \
    -print -exec rm -f {} \; | sed 's/^/Removido (antigo): /'
fi
