#!/usr/bin/env bash
# agent-memory-mcp.sh — bimetri patch (yama 75): point the workers' Claude and Codex at the
# project-memory MCP (memory-mcp service, port 8892).
#
# From the repo root, as root:  scripts/bimetri/agent-memory-mcp.sh 192.168.20.10 192.168.20.11
# Reads BIMETRI_MEMORY_MCP_TOKEN from .env and sends it to each worker over SSH stdin (never
# printed, never on a command line). On the worker, _agent_memory_mcp.py writes the user config
# of the worker user, then `codex mcp list` / `claude mcp list` show the result (token masked).
# Options: --user <worker user> (default coder), --url <MCP URL> (default http://$MEM0_BIND:8892/mcp),
#          --key <SSH key> (default .ssh/id_ed25519, the key AgenticKode uses for the workers).
# Safe to run again: the entry is replaced.
set -euo pipefail
cd "$(dirname "$0")/../.."

value() { { grep -oP "^$1=\K.*" .env 2>/dev/null || true; } | tail -n1 | tr -d "\r\"' "; }

worker_user=coder
url=""
key=.ssh/id_ed25519
hosts=()
while [ $# -gt 0 ]; do
  case "$1" in
    --user) worker_user=$2; shift 2 ;;
    --url) url=$2; shift 2 ;;
    --key) key=$2; shift 2 ;;
    -*) echo "unknown option: $1" >&2; exit 2 ;;
    *) hosts+=("$1"); shift ;;
  esac
done
[ ${#hosts[@]} -gt 0 ] || { echo "usage: $0 [--user U] [--url URL] [--key FILE] HOST..." >&2; exit 2; }

token=$(value BIMETRI_MEMORY_MCP_TOKEN)
[ -n "$token" ] || { echo "ERROR: BIMETRI_MEMORY_MCP_TOKEN is empty in .env" >&2; exit 1; }
if [ -z "$url" ]; then
  bind=$(value MEM0_BIND)
  case "$bind" in
    "" | 127.0.0.1) echo "ERROR: MEM0_BIND is not a LAN address; pass --url" >&2; exit 1 ;;
  esac
  url="http://$bind:8892/mcp"
fi

curl -fsS -m 5 "${url%/mcp}/health" >/dev/null \
  || { echo "ERROR: ${url%/mcp}/health does not answer; start memory-mcp first" >&2; exit 1; }

program=$(cat scripts/bimetri/_agent_memory_mcp.py)
remote="runuser -u $worker_user -- python3 -c $(printf %q "$program") $(printf %q "$url")"
check="runuser -l $worker_user -c 'codex mcp list; claude mcp list' 2>&1 | grep bimetri-memory"
mask='s/(Bearer )[^ "]+/\1***/g'

for host in "${hosts[@]}"; do
  echo "== $host"
  printf '%s\n' "$token" | ssh -i "$key" "root@$host" "$remote"
  ssh -i "$key" "root@$host" "$check" < /dev/null | sed -E "$mask" || echo "   (no bimetri-memory line in mcp list)"
done
