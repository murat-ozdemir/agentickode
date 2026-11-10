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
#          Claude (~/.claude.json, tools loaded up front, startup waits up to 15 s) and Codex
#          (~/.codex/config.toml, 120 s startup timeout), adds (or removes) a hint to use it in
#          ~/.claude/CLAUDE.md and ~/.codex/AGENTS.md, and turns claude.ai connectors off for
#          Claude on the worker (_agent_graph_config.py). Then runs `claude mcp list` inside
#          --repo, where serve can find the clone; that also brings the graph up to date.
#          With --gate (graph modes only), Claude hooks deny every other tool until the agent has
#          called a graph tool in that session, so a measured run surely uses the graph.
# update:  incremental update of both graphs for --repo, with timings.
# stats RUN_ID: tool calls (graph calls apart), tokens with the cache split and duration of that
#          run's Claude transcript, which only the worker user can read (_agent_run_stats.py).
#          Ask every worker; those that did not run it say so.
# Options: --user <worker user> (default coder), --key <SSH key> (default .ssh/id_ed25519),
#          --repo <clone on the worker> (default /workspaces/Bienport-IoT/platform-backend),
#          --dry-run (print the SSH commands, run nothing), --gate (see mode),
#          --direct (HOST is an SSH destination that logs in as the worker user, e.g. an
#          ~/.ssh/config alias; no root, --user and --key unused). Safe to run again.
set -euo pipefail
cd "$(dirname "$0")/../.."

worker_user=coder
key=.ssh/id_ed25519
repo=/workspaces/Bienport-IoT/platform-backend
dry_run=0
direct=0
gate=
action=""
arg=""
hosts=()
while [ $# -gt 0 ]; do
  case "$1" in
    --user) worker_user=$2; shift 2 ;;
    --key) key=$2; shift 2 ;;
    --repo) repo=$2; shift 2 ;;
    --dry-run) dry_run=1; shift ;;
    --direct) direct=1; shift ;;
    --gate) gate=" gate"; shift ;;
    -*) echo "unknown option: $1" >&2; exit 2 ;;
    *)
      if [ -z "$action" ]; then action=$1
      elif { [ "$action" = mode ] || [ "$action" = stats ]; } && [ -z "$arg" ]; then arg=$1
      else hosts+=("$1"); fi
      shift ;;
  esac
done
usage="usage: $0 [--user U] [--key FILE] [--repo PATH] [--dry-run] [--direct] [--gate] install|update|mode MODE|stats RUN_ID HOST..."
case "$action" in
  install | update) ;;
  mode)
    case "$arg" in none | graphify | graperoot) ;; *) echo "$usage" >&2; exit 2 ;; esac
    if [ -n "$gate" ] && [ "$arg" = none ]; then echo "--gate needs a graph mode" >&2; exit 2; fi ;;
  stats) case "$arg" in "" | *[!0-9]*) echo "$usage" >&2; exit 2 ;; esac ;;
  *) echo "$usage" >&2; exit 2 ;;
esac
[ ${#hosts[@]} -gt 0 ] || { echo "$usage" >&2; exit 2; }

# One program from two files: the config module, then the main one without its import of it.
program_file=scripts/bimetri/_agent_graph_mcp.py
if [ "$action" = stats ]; then
  program_file=scripts/bimetri/_agent_run_stats.py
  program=$(cat "$program_file")
else
  program=$(cat scripts/bimetri/_agent_graph_config.py; grep -v '# bundle: drop$' "$program_file")
fi
# install reads its own source plus the frozen locks from stdin (see _agent_graph_mcp.py).
bundle() {
  printf '%s\n' "$program"
  for tool in graphify graperoot; do
    echo "### lock: $tool"
    cat "scripts/bimetri/agent-graph-locks/$tool.txt"
  done
}
as_worker="runuser -u $worker_user -- python3 -c $(printf %q "$program")"
mcp_list="cd $(printf %q "$repo") && claude mcp list"
mcp_list="runuser -l $worker_user -c $(printf %q "$mcp_list")"
target=(-i "$key")
if [ $direct = 1 ]; then
  as_worker="python3 -c $(printf %q "$program")"
  mcp_list="bash -lc $(printf %q "cd $(printf %q "$repo") && claude mcp list")"
  target=()
fi
case "$action" in
  install) commands=("$as_worker install" "$as_worker update all $(printf %q "$repo")") ;;
  update) commands=("$as_worker update all $(printf %q "$repo")") ;;
  mode) commands=("$as_worker mode $arg$gate"
                  "$mcp_list 2>&1 | grep -E '^(bimetri-graph|claude\.ai)' || true") ;;
  stats) commands=("$as_worker stats $arg") ;;
esac

for host in "${hosts[@]}"; do
  echo "== $host"
  destination=$host
  if [ $direct = 0 ]; then destination=root@$host; fi
  for i in "${!commands[@]}"; do
    if [ $dry_run = 1 ]; then
      # The program text is long; show its file name instead.
      echo "ssh ${target[*]:+${target[*]} }$destination ${commands[$i]//"$(printf %q "$program")"/<$program_file>}"
    elif [ "$action" = install ] && [ "$i" = 0 ]; then
      bundle | ssh "${target[@]}" "$destination" "${commands[$i]}"
    else
      ssh "${target[@]}" "$destination" "${commands[$i]}" < /dev/null
    fi
  done
done
