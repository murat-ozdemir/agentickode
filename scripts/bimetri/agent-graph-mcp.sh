#!/usr/bin/env bash
# agent-graph-mcp.sh — bimetri patch (D2 phase 1): local code graph (Graphify, graperoot) for the
# workers' agent CLIs, plus a switch that puts every worker in the same mode for a measured run.
#
# From the repo root, as root:
#   scripts/bimetri/agent-graph-mcp.sh install 192.168.20.10 192.168.20.11 192.168.20.12
#   scripts/bimetri/agent-graph-mcp.sh mode graperoot 192.168.20.10 192.168.20.11 192.168.20.12
#   scripts/bimetri/agent-graph-mcp.sh update 192.168.20.10 ...
#   scripts/bimetri/agent-graph-mcp.sh stats 74 192.168.20.10 192.168.20.11 192.168.20.12
# install: pinned venvs under ~/.local/share/bimetri-graph of the worker user, then a first build
#          of both graphs for --repo with timings. Mode stays as it was (none on a new worker).
# mode none|graphify|graperoot: registers (or removes) the stdio MCP server bimetri-graph for
#          Claude (~/.claude.json) and Codex (~/.codex/config.toml), with a 120 s startup timeout,
#          and turns claude.ai connectors off for Claude on the worker. Then runs `claude mcp list`
#          inside --repo, where serve can find the clone; that also runs serve's graph update.
# update:  incremental update of both graphs for --repo, with timings.
# stats RUN_ID: tool calls (graph calls apart), tokens with the cache split and duration of that
#          run's Claude transcript, which only the worker user can read (_agent_run_stats.py).
#          Ask every worker; those that did not run it say so.
# Options: --user <worker user> (default coder), --key <SSH key> (default .ssh/id_ed25519),
#          --repo <clone on the worker> (default /workspaces/Bienport-IoT/platform-backend),
#          --dry-run (print the SSH commands, run nothing). Safe to run again.
set -euo pipefail
cd "$(dirname "$0")/../.."

worker_user=coder
key=.ssh/id_ed25519
repo=/workspaces/Bienport-IoT/platform-backend
dry_run=0
action=""
arg=""
hosts=()
while [ $# -gt 0 ]; do
  case "$1" in
    --user) worker_user=$2; shift 2 ;;
    --key) key=$2; shift 2 ;;
    --repo) repo=$2; shift 2 ;;
    --dry-run) dry_run=1; shift ;;
    -*) echo "unknown option: $1" >&2; exit 2 ;;
    *)
      if [ -z "$action" ]; then action=$1
      elif { [ "$action" = mode ] || [ "$action" = stats ]; } && [ -z "$arg" ]; then arg=$1
      else hosts+=("$1"); fi
      shift ;;
  esac
done
usage="usage: $0 [--user U] [--key FILE] [--repo PATH] [--dry-run] install|update|mode MODE|stats RUN_ID HOST..."
case "$action" in
  install | update) ;;
  mode) case "$arg" in none | graphify | graperoot) ;; *) echo "$usage" >&2; exit 2 ;; esac ;;
  stats) case "$arg" in "" | *[!0-9]*) echo "$usage" >&2; exit 2 ;; esac ;;
  *) echo "$usage" >&2; exit 2 ;;
esac
[ ${#hosts[@]} -gt 0 ] || { echo "$usage" >&2; exit 2; }

program_file=scripts/bimetri/_agent_graph_mcp.py
if [ "$action" = stats ]; then program_file=scripts/bimetri/_agent_run_stats.py; fi
program=$(cat "$program_file")
# install reads its own source plus the frozen locks from stdin (see _agent_graph_mcp.py).
bundle() {
  cat "$program_file"
  for tool in graphify graperoot; do
    echo "### lock: $tool"
    cat "scripts/bimetri/agent-graph-locks/$tool.txt"
  done
}
as_worker="runuser -u $worker_user -- python3 -c $(printf %q "$program")"
case "$action" in
  install) commands=("$as_worker install" "$as_worker update all $(printf %q "$repo")") ;;
  update) commands=("$as_worker update all $(printf %q "$repo")") ;;
  mode) commands=("$as_worker mode $arg"
                  "runuser -l $worker_user -c $(printf %q "cd $(printf %q "$repo") && claude mcp list") 2>&1 | grep -E '^(bimetri-graph|claude\.ai)' || true") ;;
  stats) commands=("$as_worker stats $arg") ;;
esac

for host in "${hosts[@]}"; do
  echo "== $host"
  for i in "${!commands[@]}"; do
    if [ $dry_run = 1 ]; then
      # The program text is long; show its file name instead.
      echo "ssh -i $key root@$host ${commands[$i]//"$(printf %q "$program")"/<$program_file>}"
    elif [ "$action" = install ] && [ "$i" = 0 ]; then
      bundle | ssh -i "$key" "root@$host" "${commands[$i]}"
    else
      ssh -i "$key" "root@$host" "${commands[$i]}" < /dev/null
    fi
  done
done
