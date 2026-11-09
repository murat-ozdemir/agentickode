#!/usr/bin/env bash
# pg-backup.sh — bimetri yamasi: AgenticKode + mem0 veritabanlarinin gunluk yedegi.
#
# Konteynerleri compose etiketiyle bulur (compose dosyasi gerekmez). Cron: agentickode-backup.cron.
# Ayarlar (ortam degiskeni):
#   COMPOSE_PROJECT  varsayilan: agentickode
#   BACKUP_DIR       varsayilan: /var/backups/agentickode
#   KEEP_DAYS        varsayilan: 14
#   DATABASES        varsayilan: "agentickode mem0 mem0_app" (olmayan DB atlanir)
#
# Not: yedek ayni makinede durur; disk kaybina karsi koruma degildir.
set -euo pipefail
umask 077

COMPOSE_PROJECT=${COMPOSE_PROJECT:-agentickode}
BACKUP_DIR=${BACKUP_DIR:-/var/backups/agentickode}
KEEP_DAYS=${KEEP_DAYS:-14}
DATABASES=${DATABASES:-"agentickode mem0 mem0_app"}
DB_USER=agentickode

log() { printf '%s %s\n' "$(date '+%F %T')" "$*"; }

container() {
  docker ps -q --filter "label=com.docker.compose.project=$COMPOSE_PROJECT" \
    --filter "label=com.docker.compose.service=$1" | head -1
}

pg=$(container postgres)
[[ -n $pg ]] || { log "HATA: postgres konteyneri calismiyor"; exit 1; }

install -d -m 700 "$BACKUP_DIR"
stamp=$(date +%Y%m%d-%H%M%S)
failed=0

for db in $DATABASES; do
  exists=$(docker exec "$pg" psql -U "$DB_USER" -d postgres -tAc \
    "select 1 from pg_database where datname = '$db'")
  if [[ $exists != 1 ]]; then
    log "$db yok, atlandi"
    continue
  fi
  out="$BACKUP_DIR/$db-$stamp.dump"
  if docker exec "$pg" pg_dump -U "$DB_USER" -Fc "$db" >"$out.tmp" && [[ -s $out.tmp ]]; then
    mv "$out.tmp" "$out"
    log "$db -> $out ($(du -h "$out" | cut -f1))"
  else
    rm -f "$out.tmp"
    log "HATA: $db yedeklenemedi"
    failed=1
  fi
done

# mem0'in degisiklik gecmisi (sqlite); konteyner yoksa atlanir.
m0=$(container mem0)
if [[ -n $m0 ]]; then
  out="$BACKUP_DIR/mem0-history-$stamp.db"
  if docker exec "$m0" python -c "import sqlite3; sqlite3.connect('/app/history/history.db').backup(sqlite3.connect('/tmp/history-backup.db'))" \
    && docker exec "$m0" cat /tmp/history-backup.db >"$out.tmp"; then
    mv "$out.tmp" "$out"
    docker exec "$m0" rm -f /tmp/history-backup.db
    log "mem0 gecmisi -> $out"
  else
    rm -f "$out.tmp"
    log "HATA: mem0 gecmisi yedeklenemedi"
    failed=1
  fi
fi

find "$BACKUP_DIR" -maxdepth 1 -type f \( -name '*.dump' -o -name 'mem0-history-*.db' \) \
  ! -name '*-premigrate-*' -mtime +"$KEEP_DAYS" -print -delete
exit "$failed"
