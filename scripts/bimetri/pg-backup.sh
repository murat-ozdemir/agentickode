#!/usr/bin/env bash
# pg-backup.sh — bimetri yamasi: AgenticKode + mem0 veritabanlarinin gunluk yedegi.
#
# Konteynerleri compose etiketiyle bulur (compose dosyasi gerekmez). Cron: agentickode-backup.cron.
# Ayarlar (ortam degiskeni):
#   COMPOSE_PROJECT  varsayilan: agentickode
#   BACKUP_DIR       varsayilan: /var/backups/agentickode
#   KEEP_DAYS        varsayilan: 14
#   DATABASES        varsayilan: "agentickode mem0 mem0_app" (olmayan DB atlanir)
#   STORAGEBOX       uzak kopya hedefi, ornek: u173026-sub1@u173026-sub1.your-storagebox.de
#                    (bossa uzaga yuklenmez)
#   STORAGEBOX_PORT  varsayilan: 23
#   STORAGEBOX_DIR   varsayilan: agentickode (alt hesabin kokune gore)
#   STORAGEBOX_KEY   varsayilan: /root/.ssh/storagebox_ed25519
#   STORAGEBOX_KNOWN_HOSTS  varsayilan: /root/.ssh/storagebox_known_hosts
#   REMOTE_KEEP_DAYS varsayilan: 60 (premigrate dokumleri uzakta da silinmez)
# Ayarlar /etc/default/agentickode-backup dosyasindan da okunur (BACKUP_CONF ile degisir).
set -euo pipefail
umask 077

BACKUP_CONF=${BACKUP_CONF:-/etc/default/agentickode-backup}
if [[ -r $BACKUP_CONF ]]; then
  # shellcheck source=/dev/null
  . "$BACKUP_CONF"
fi

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

# Uzak kopya (storage box): rsync ile ekler, eskileri dosya adindaki tarihe gore sftp ile siler.
if [[ -n ${STORAGEBOX:-} ]]; then
  STORAGEBOX_PORT=${STORAGEBOX_PORT:-23}
  STORAGEBOX_DIR=${STORAGEBOX_DIR:-agentickode}
  STORAGEBOX_KEY=${STORAGEBOX_KEY:-/root/.ssh/storagebox_ed25519}
  STORAGEBOX_KNOWN_HOSTS=${STORAGEBOX_KNOWN_HOSTS:-/root/.ssh/storagebox_known_hosts}
  REMOTE_KEEP_DAYS=${REMOTE_KEEP_DAYS:-60}
  ssh_opts=(-i "$STORAGEBOX_KEY" -o BatchMode=yes -o IdentitiesOnly=yes
    -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$STORAGEBOX_KNOWN_HOSTS")

  if rsync -rt --include='*.dump' --include='mem0-history-*.db' --exclude='*' \
    -e "ssh -p $STORAGEBOX_PORT ${ssh_opts[*]}" "$BACKUP_DIR/" "$STORAGEBOX:$STORAGEBOX_DIR/"; then
    log "uzak kopya -> $STORAGEBOX:$STORAGEBOX_DIR/"
    cutoff=$(date -d "-$REMOTE_KEEP_DAYS days" +%Y%m%d)
    sftp_run() { sftp -q -b - -P "$STORAGEBOX_PORT" "${ssh_opts[@]}" "$STORAGEBOX"; }
    if listing=$(echo "ls -1 $STORAGEBOX_DIR" | sftp_run); then
      old=()
      while read -r path; do
        name=${path##*/}
        [[ $name == *-premigrate-* ]] && continue
        [[ $name =~ -([0-9]{8})-[0-9]{6}\.(dump|db)$ ]] || continue
        [[ ${BASH_REMATCH[1]} < $cutoff ]] && old+=("$name")
      done <<<"$listing"
      if ((${#old[@]})); then
        if printf "rm $STORAGEBOX_DIR/%s\n" "${old[@]}" | sftp_run >/dev/null; then
          log "uzakta silindi (${REMOTE_KEEP_DAYS} gunden eski): ${old[*]}"
        else
          log "HATA: uzaktaki eski yedekler silinemedi"
          failed=1
        fi
      fi
    else
      log "HATA: uzak klasor listelenemedi"
      failed=1
    fi
  else
    log "HATA: uzak kopya yuklenemedi"
    failed=1
  fi
fi
exit "$failed"
