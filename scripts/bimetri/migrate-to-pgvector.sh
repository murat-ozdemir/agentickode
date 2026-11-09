#!/usr/bin/env bash
# migrate-to-pgvector.sh — bimetri yamasi: AgenticKode Postgres'ini pgvector imajina tasir,
# mem0 icin rol + DB'leri olusturur ve yigini docker-compose.bimetri.yml ile ayaga kaldirir.
#
# Repo kokunden root olarak calistir (dev-1: cd /opt/agentickode && sudo scripts/bimetri/...).
# Ayarlar (ortam degiskeni):
#   COMPOSE_PROJECT  varsayilan: agentickode
#   COMPOSE_FILES    varsayilan: "docker-compose.dev.yml docker-compose.prod.yml docker-compose.swag.yml"
#   BACKUP_DIR       varsayilan: /var/backups/agentickode
#   PULL_RESTART     varsayilan: ./pull-restart.sh (varsa -f docker-compose.bimetri.yml eklenir)
#   FORCE=1          bitmemis kosu olsa da devam et
#
# Eski volume (agentickode-app_pgdata) silinmez; geri donus komutlari en sonda yazilir.
set -euo pipefail
umask 077

COMPOSE_PROJECT=${COMPOSE_PROJECT:-agentickode}
COMPOSE_FILES=${COMPOSE_FILES:-"docker-compose.dev.yml docker-compose.prod.yml docker-compose.swag.yml"}
BACKUP_DIR=${BACKUP_DIR:-/var/backups/agentickode}
PULL_RESTART=${PULL_RESTART:-./pull-restart.sh}
NEW_VOLUME=agentickode-app_pgvdata
DB_USER=agentickode
DB_NAME=agentickode
TERMINAL_STATUSES="'completed','failed','timeout','cancelled'"

log() { printf '\n==> %s\n' "$*"; }
die() { printf '\nHATA: %s\n' "$*" >&2; exit 1; }

old_args=(-p "$COMPOSE_PROJECT")
for f in $COMPOSE_FILES; do old_args+=(-f "$f"); done
new_args=("${old_args[@]}" -f docker-compose.bimetri.yml)
dc_old() { docker compose "${old_args[@]}" "$@"; }
dc_new() { docker compose "${new_args[@]}" "$@"; }
psql_q() { "$@" exec -T postgres psql -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 -tAq; }

# Tablo basina kesin satir sayisi; tasima oncesi/sonrasi karsilastirilir. Siralama "C" ile
# sabit: alpine (musl) ve debian (glibc) metinleri farkli siralar.
COUNT_SQL="select 'select * from (' || string_agg(format('select %L::text as t, count(*) from public.%I', table_name, table_name), ' union all ') || ') x order by t collate \"C\"' from information_schema.tables where table_schema = 'public' and table_type = 'BASE TABLE' \\gexec"

row_counts() { echo "$COUNT_SQL" | psql_q "$@"; }

# Yarida kalirsa: eski volume'a hic dokunulmaz, eski yigin aynen geri kaldirilabilir.
finished=0
on_exit() {
  [[ $finished == 1 || ${started:-0} == 0 ]] && return
  cat >&2 <<EOF

Tasima yarida kaldi. Eski duruma donmek icin:
  docker compose ${new_args[*]} stop mem0 postgres
  docker compose ${old_args[*]} up -d
Yeniden denemeden once: docker volume rm $NEW_VOLUME (varsa)
EOF
}
trap on_exit EXIT

# --- 0. On kosullar -------------------------------------------------------------------------
[[ -f docker-compose.bimetri.yml ]] || die "repo kokunde degilsin (docker-compose.bimetri.yml yok)."
for f in $COMPOSE_FILES; do [[ -f $f ]] || die "$f bulunamadi."; done
[[ -f .env.mem0 ]] || die ".env.mem0 yok: cp .env.mem0.example .env.mem0 && chmod 600 .env.mem0, sonra doldur."
MEM0_PW=$(sed -n 's/^POSTGRES_PASSWORD=//p' .env.mem0 | tail -1)
[[ -n $MEM0_PW ]] || die ".env.mem0 icinde POSTGRES_PASSWORD bos."
for key in OPENAI_API_KEY ADMIN_API_KEY JWT_SECRET; do
  grep -q "^$key=." .env.mem0 || die ".env.mem0 icinde $key bos."
done
if docker volume inspect "$NEW_VOLUME" >/dev/null 2>&1; then
  die "$NEW_VOLUME zaten var (onceki deneme?). Bos oldugundan eminsen: docker volume rm $NEW_VOLUME"
fi
dc_new config --quiet || die "compose ayarlari gecersiz."
image=$(docker inspect -f '{{.Config.Image}}' "$(dc_old ps -q postgres)" 2>/dev/null || true)
[[ $image == postgres:16* ]] || die "calisan postgres imaji beklenmedik: '${image:-yok}'."

# --- 1. Bitmemis kosu kontrolu --------------------------------------------------------------
active=$(echo "select count(*) from task_runs where status not in ($TERMINAL_STATUSES);" | psql_q dc_old)
if [[ $active != 0 ]]; then
  [[ ${FORCE:-0} == 1 ]] || die "$active kosu bitmemis. Bitmesini bekle ya da FORCE=1 ile calistir."
  log "UYARI: $active bitmemis kosu var, FORCE=1 ile devam ediliyor."
fi

# --- 2. Backend'i durdur, dok al --------------------------------------------------------------
started=1
log "backend durduruluyor"
dc_old stop backend

install -d -m 700 "$BACKUP_DIR"
stamp=$(date +%Y%m%d-%H%M%S)
dump="$BACKUP_DIR/$DB_NAME-premigrate-$stamp.dump"
log "pg_dump -> $dump"
dc_old exec -T postgres pg_dump -U "$DB_USER" -Fc "$DB_NAME" >"$dump.tmp"
mv "$dump.tmp" "$dump"
[[ -s $dump ]] || die "dok bos."
row_counts dc_old >"$BACKUP_DIR/rowcounts-before-$stamp.txt"

# --- 3. pgvector imajina gec, geri yukle ------------------------------------------------------
log "postgres pgvector imajiyla yeni volume'da baslatiliyor"
dc_old stop postgres
dc_new up -d --quiet-pull --wait postgres

log "pg_restore"
dc_new exec -T postgres pg_restore -U "$DB_USER" -d "$DB_NAME" --exit-on-error --single-transaction <"$dump"
row_counts dc_new >"$BACKUP_DIR/rowcounts-after-$stamp.txt"
if ! diff -u "$BACKUP_DIR/rowcounts-before-$stamp.txt" "$BACKUP_DIR/rowcounts-after-$stamp.txt"; then
  die "satir sayilari tutmuyor."
fi
log "satir sayilari ayni ($(wc -l <"$BACKUP_DIR/rowcounts-after-$stamp.txt") tablo)"

# --- 4. mem0 rolu, DB'leri ve vector eklentisi ------------------------------------------------
log "mem0 rolu ve DB'leri olusturuluyor"
pw_sql=${MEM0_PW//\'/\'\'}
dc_new exec -T postgres psql -U "$DB_USER" -d postgres -v ON_ERROR_STOP=1 -q <<SQL
select format('create role mem0 login password %L', '$pw_sql')
  where not exists (select from pg_roles where rolname = 'mem0') \gexec
alter role mem0 password '$pw_sql';
select 'create database mem0 owner mem0'
  where not exists (select from pg_database where datname = 'mem0') \gexec
select 'create database mem0_app owner mem0'
  where not exists (select from pg_database where datname = 'mem0_app') \gexec
\c mem0
create extension if not exists vector;
SQL

# --- 5. Tum yigini ayaga kaldir ---------------------------------------------------------------
log "yigin baslatiliyor (mem0 imaji ilk seferde derlenir)"
dc_new up -d --build --quiet-pull --wait

log "mem0 kontrolu"
dc_new exec -T mem0 python - <<'PY'
import urllib.error, urllib.request
base = "http://127.0.0.1:8000"
assert urllib.request.urlopen(base + "/docs").status == 200
try:
    urllib.request.urlopen(base + "/memories?user_id=x")
    raise SystemExit("anahtarsiz istek reddedilmedi")
except urllib.error.HTTPError as e:
    assert e.code == 401, e.code
print("mem0 ayakta; anahtarsiz istek 401")
PY

# --- 6. pull-restart.sh ------------------------------------------------------------------------
if [[ -f $PULL_RESTART ]] && ! grep -q docker-compose.bimetri.yml "$PULL_RESTART"; then
  cp -p "$PULL_RESTART" "$PULL_RESTART.bak-$stamp"
  sed -i 's/-f docker-compose.swag.yml/& -f docker-compose.bimetri.yml/' "$PULL_RESTART"
  grep -q docker-compose.bimetri.yml "$PULL_RESTART" && log "$PULL_RESTART guncellendi" \
    || log "UYARI: $PULL_RESTART'a -f docker-compose.bimetri.yml elle eklenmeli"
fi

finished=1
cat <<EOF

TAMAM. Dok: $dump
Eski volume (agentickode-app_pgdata) duruyor. Geri donus (tasimadan sonra yazilan veri kaybolur):
  docker compose ${new_args[*]} stop mem0 postgres backend
  docker compose ${old_args[*]} up -d
  # pull-restart.sh'tan -f docker-compose.bimetri.yml'yi cikar (yedegi: $PULL_RESTART.bak-$stamp)
EOF
