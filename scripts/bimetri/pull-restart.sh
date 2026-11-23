#!/usr/bin/env bash
# bimetri patch: deploy on dev-1 (git pull + backend restart) without cutting a running run.
#
# The worker lives in the backend container: a restart stops every running run, which then
# starts again from the top (runs #294, #308, #312 on 2026-11-23: one whole 291k-token attempt
# lost, #312's graph measurement doubled). So wait until no run is `running`, then pull and
# restart, checking once more right before the restart.
#
# Install once (as root): ln -sf scripts/bimetri/pull-restart.sh /opt/agentickode/pull-restart.sh
# Usage: sudo /opt/agentickode/pull-restart.sh [--now] [--max-wait MINUTES]
#   --now           restart without waiting
#   --max-wait N    give up after N minutes (default 60) and exit 1 without restarting

set -euo pipefail

main() {
  local now=0 max_wait=60
  while [ $# -gt 0 ]; do
    case "$1" in
      --now) now=1 ;;
      --max-wait) max_wait="$2"; shift ;;
      *) echo "bilinmeyen seçenek: $1" >&2; exit 2 ;;
    esac
    shift
  done

  cd /opt/agentickode
  [ "$now" = 1 ] || wait_for_idle "$max_wait"
  git -c safe.directory=/opt/agentickode pull --ff-only
  [ "$now" = 1 ] || wait_for_idle "$max_wait"
  docker compose -p agentickode -f docker-compose.dev.yml -f docker-compose.prod.yml \
    -f docker-compose.swag.yml -f docker-compose.bimetri.yml restart backend
}

running_runs() {
  docker exec agentickode-postgres-1 sh -c \
    'psql -U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-postgres}" -At -c "select string_agg(id::text, '"', '"' order by id) from task_runs where status = '"'running'"'"'
}

wait_for_idle() {
  local deadline=$(( $(date +%s) + $1 * 60 )) runs
  while true; do
    runs="$(running_runs)" || { echo "koşular okunamadı; yeniden başlatmadım" >&2; exit 1; }
    [ -n "$runs" ] || return 0
    if [ "$(date +%s)" -ge "$deadline" ]; then
      echo "$1 dakikadır koşu bitmedi (#$runs); yeniden başlatmadım. Beklemeden: --now" >&2
      exit 1
    fi
    echo "$(date +%H:%M:%S) koşan koşu var: #$runs; bitmesini bekliyorum"
    sleep 20
  done
}

main "$@"
exit
