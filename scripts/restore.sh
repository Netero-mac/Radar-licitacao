#!/usr/bin/env sh
# Restaura um backup feito por scripts/backup.sh. SUBSTITUI os dados atuais do banco.
#
#   ./scripts/restore.sh backups/radar_2026-11-23_030000.dump
#
# Pare antes a app e o agendador para ninguém gravar durante a restauração:
#   docker compose -f docker-compose.prod.yml stop app scheduler
set -eu

cd "$(dirname "$0")/.."

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
file="${1:-}"

if [ -z "$file" ] || [ ! -s "$file" ]; then
  echo "Uso: $0 <arquivo .dump>" >&2
  exit 2
fi

if [ "${RESTORE_CONFIRM:-}" != "sim" ]; then
  printf 'Isto apaga os dados atuais e restaura %s. Digite "sim" para continuar: ' "$file"
  read -r answer
  [ "$answer" = "sim" ] || { echo "Cancelado."; exit 1; }
fi

docker compose -f "$COMPOSE_FILE" exec -T db \
  sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner' < "$file"
echo "Restaurado: $file. Suba de novo: docker compose -f $COMPOSE_FILE up -d"
