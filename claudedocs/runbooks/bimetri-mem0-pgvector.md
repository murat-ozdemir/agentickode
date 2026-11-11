---
title: bimetri — pgvector Postgres + mem0 and daily DB backup
---

# bimetri — pgvector Postgres + mem0 and daily DB backup

## When to Use

- Once per server: switch the stack's `postgres:16-alpine` to `pgvector/pgvector:pg16` and add the
  mem0 server (`docker-compose.bimetri.yml`).
- Daily backups of `agentickode`, `mem0`, `mem0_app` (and mem0's sqlite history) via cron.

The migration is dump/restore into a new volume (`agentickode-app_pgvdata`); the old volume
(`agentickode-app_pgdata`) is never touched, so rollback is just starting the old stack again.
A raw volume swap is not possible: alpine (musl) and debian (glibc) collate text differently.

## Steps

Run on the server, as root, from the repo root (`/opt/agentickode`).

1. Secrets (never paste them anywhere else):
   ```bash
   cp .env.mem0.example .env.mem0 && chmod 600 .env.mem0 && nano .env.mem0
   ```
   `POSTGRES_PASSWORD`, `ADMIN_API_KEY`, `JWT_SECRET`: `openssl rand -hex 32` each. `OPENAI_API_KEY`: real key.
2. Expose mem0 on the LAN for agent machines (default bind is `127.0.0.1`; host port 8890, not 8888,
   which tinyproxy uses on dev-1):
   ```bash
   echo 'MEM0_BIND=192.168.20.50' >> .env
   ```
3. Migrate (aborts if a run is not finished; `FORCE=1` overrides):
   ```bash
   scripts/bimetri/migrate-to-pgvector.sh
   ```
   It stops the backend, dumps to `/var/backups/agentickode/agentickode-premigrate-*.dump`, starts
   postgres on the pgvector image + new volume, restores, compares per-table row counts, creates role
   `mem0` + DBs `mem0`/`mem0_app` + `vector` extension, builds and starts mem0 (v2.2.1 tag), checks
   `/docs` = 200 and keyless `/memories` = 401, and adds `-f docker-compose.bimetri.yml` to `pull-restart.sh`.
4. Daily backup (03:15, 14 days):
   ```bash
   install -m 644 scripts/bimetri/agentickode-backup.cron /etc/cron.d/agentickode-backup
   scripts/bimetri/pg-backup.sh
   ```
   Off-site copy (Hetzner Storage Box sub-account; skipped while `STORAGEBOX` is unset):
   ```bash
   ssh-keygen -t ed25519 -N '' -f /root/.ssh/storagebox_ed25519 -C agentickode-backup@$(hostname)
   ssh-keyscan -p 23 -t ed25519 <sub>.your-storagebox.de > /root/.ssh/storagebox_known_hosts
   ssh-keygen -lf /root/.ssh/storagebox_known_hosts   # compare with Hetzner's published fingerprint
   ssh -p 23 -o UserKnownHostsFile=/root/.ssh/storagebox_known_hosts <sub>@<sub>.your-storagebox.de install-ssh-key < /root/.ssh/storagebox_ed25519.pub
   echo 'STORAGEBOX=<sub>@<sub>.your-storagebox.de' > /etc/default/agentickode-backup
   ```
   The script rsyncs `*.dump` + `mem0-history-*.db` into `agentickode/` (sub-account root) and deletes
   remote files older than `REMOTE_KEEP_DAYS` (60) by the date in the file name; `*-premigrate-*` is kept.
5. From now on every compose command needs the extra file:
   `-f docker-compose.dev.yml -f docker-compose.prod.yml -f docker-compose.swag.yml -f docker-compose.bimetri.yml`.
6. Project memory in run prompts (yama 72). The backend reads `MEM0_URL` (compose sets
   `http://mem0:8000`) and `MEM0_API_KEY` (`.env`). The feature is off while either one is empty.
   ```bash
   scripts/bimetri/mem0-backend-key.sh
   docker compose -p agentickode -f docker-compose.dev.yml -f docker-compose.prod.yml -f docker-compose.swag.yml -f docker-compose.bimetri.yml up -d backend
   ```
   If mem0 has no admin account yet, the script creates one: it asks for an e-mail and a hidden
   password. Until that account exists, `/auth/register` is open to anyone on the LAN.
   The script then creates an `agentickode-backend` key with `ADMIN_API_KEY` and appends it to
   `.env` without printing it. Use `up -d`, not `restart`: `restart` does not re-read `.env`.
   Each run logs `Proje hafızasından N kayıt eklendi`, `Proje hafızasında kayıt yok` or
   `Proje hafızası eklenmedi (...)`. In the last case the run continues without memory.
7. Initial fill of a project's memory (yama 73), once per repo. Run as root (`sudo -i`) so the
   script reads `OPENAI_API_KEY` from `.env.mem0` and `MEM0_API_KEY`/`MEM0_BIND` from `.env`; as
   another user it asks for them with a hidden prompt. It needs a full clone (history is read),
   outside `/opt/agentickode`:
   ```bash
   mkdir -p /root/mem0-bootstrap && cd /root/mem0-bootstrap && git clone https://<gitea>/<owner>/<repo>.git
   ```
   ```bash
   /opt/agentickode/scripts/bimetri/mem0-bootstrap.py --repo <repo>
   ```
   ```bash
   /opt/agentickode/scripts/bimetri/mem0-bootstrap.py --repo <repo> --generate
   ```
   ```bash
   /opt/agentickode/scripts/bimetri/mem0-bootstrap.py --upload mem0-taslak-<owner>-<repo>.jsonl
   ```
   - The first command calls nothing: it lists the files that would go to OpenAI (values of
     password/secret/token/api_key lines are masked) and the estimated cost.
   - `--generate`: gpt-5-mini writes `proje`, `modul`, `karar`, `ders`, `tuzak` records; one
     `ozellik_gecmisi` record per merged PR is built from git without the LLM. Output is a JSONL
     draft; edit or delete lines before uploading. It never overwrites an existing draft.
   - `--upload` writes with `infer=False` (no LLM, one embedding per record), then deletes the
     previous `kaynak=bootstrap` records, so it can be rerun. `ozellik_gecmisi` is never deleted;
     a PR that already has one is skipped.
   - The printed project name must match the AgenticKode project's `<owner>/<repo>` exactly
     (case-sensitive); otherwise pass `--project`.
8. New merges (yama 74a) need no step. When the Gitea PR webhook reports a merge, the backend
   writes one `ozellik_gecmisi` record in the same format (`kaynak=merge`, `infer=False`) in the
   background, under the project's `<repo_owner>/<repo_name>`. A PR that already has one is
   skipped. Check:
   ```bash
   docker logs agentickode-backend-1 2>&1 | grep 'ozellik gecmisi'
   ```
   `... (Org/repo): yazildi`, `: var` (already recorded) or `: kapali` (MEM0_* empty).
9. Memory proposals on merge (yama 74b). After the record above, gpt-5-mini reads the merged
   PR's discussion (PR body, linked issue, comments, review bodies: AI review findings, fix-run
   reports, CI failures) and proposes 0-3 `lesson` / `pitfall` / `decision` records. They wait as
   `pending` rows in `bimetri_memory_proposals` (migration `b045_memory_proposals`, applied on
   backend start). Nothing reaches mem0 until someone approves it on the **Memory** page
   (`/memory`); approval writes it with `infer=False` as `tur` = `ders` / `tuzak` / `karar`,
   `kaynak=proposal`. The menu's **Memory** link shows an amber count while proposals wait
   (polled every 30 s, recounted at once after an approve/reject). Off while `MEM0_OPENAI_API_KEY` is empty; a PR without comments makes no
   LLM call. Setup, as root (`.env` change, so `up -d`, then the frontend rebuild):
   ```bash
   scripts/bimetri/mem0-backend-key.sh
   ```
   ```bash
   docker compose -p agentickode -f docker-compose.dev.yml -f docker-compose.prod.yml -f docker-compose.swag.yml -f docker-compose.bimetri.yml up -d backend
   ```
   ```bash
   docker compose -p agentickode -f docker-compose.dev.yml -f docker-compose.prod.yml -f docker-compose.swag.yml -f docker-compose.bimetri.yml up -d --build frontend
   ```
   The script copies `OPENAI_API_KEY` from `.env.mem0` into `.env` as `MEM0_OPENAI_API_KEY`
   (not `OPENAI_API_KEY`, so no other tool picks it up) without printing it. Optional `.env`:
   `MEMORY_PROPOSAL_MODEL` (default `gpt-5-mini`), `MEMORY_PROPOSAL_LANGUAGE` (default
   `Turkish`). Check after a merge:
   ```bash
   docker logs agentickode-backend-1 2>&1 | grep 'memory proposals'
   ```
   `... : N proposals`, `: no-discussion`, `: exists` (PR already has proposals) or `: disabled`.
10. Browsing records (yama 76). Two read-only views of what mem0 holds:
    - **Memory > Records** tab (`/memory?tab=records`, behind the crew password): pick a
      project, filter by `tur`; shows text, PR, `kaynak` and date, 50 per page. API:
      `GET /api/bimetri/memories?project=<owner>/<repo>[&kind=<tur>][&offset=&limit=]` returns
      `{items, total, offset, limit, kinds}` (`limit` max 200; 503 when mem0 is off, 502 when
      mem0 fails). mem0 has no offset, so each page reads the whole project (`top_k` 1000) and
      the backend slices it (yama 75).
    - mem0's own dashboard, LAN only, at `http://<MEM0_BIND>:8891` (service `mem0-dashboard`,
      built from the v2.2.1 tag). Not behind SWAG: its `Authorization: Bearer` header clashes
      with the crew basic auth, and the browser calls the mem0 API (`:8890`) directly. Log in
      with the mem0 admin from step 6 (`mem0-backend-key.sh`). It can edit and delete records
      and change mem0's LLM/embedder settings (**Configuration**); treat it as an admin tool.
    Setup, as root (new service + CORS env on mem0, so `up -d`, then the frontend rebuild):
    ```bash
    docker compose -p agentickode -f docker-compose.dev.yml -f docker-compose.prod.yml -f docker-compose.swag.yml -f docker-compose.bimetri.yml up -d --build mem0 mem0-dashboard backend frontend
    ```
    Check: `curl -s http://<MEM0_BIND>:8891/api/health` returns JSON.

11. Agent memory tools (yama 75). The run-start section now runs three searches (`proje`;
    knowledge kinds `modul/karar/ders/tuzak/calisma`; `ozellik_gecmisi`) so PR history cannot
    crowd out decisions and pitfalls. The `memory-mcp` service (`backend/mcp/bimetri_memory_server.py`,
    port 8892 on `MEM0_BIND`, streamable HTTP at `/mcp`) gives agents three tools:
    `search_project_memory(project, query, scope=knowledge|history|all)`,
    `list_project_memory(project, kind)` and `propose_memory(project, kind, text, run_id)`.
    Proposals land in `bimetri_memory_proposals` with `source=agent` (migration
    `b046_memory_proposal_source`, applied on backend start; `pr_number` becomes nullable) and wait
    on the **Memory** page like merge proposals (max 3 per run, duplicates of a pending text are
    skipped). Every request needs `Authorization: Bearer <BIMETRI_MEMORY_MCP_TOKEN>`; with the token
    empty the service refuses everything and the run prompt shows no tool hint. It is a separate
    service because the admin MCP mounted on the backend at `/mcp` has no auth. Setup, as root:
    ```bash
    grep -q '^BIMETRI_MEMORY_MCP_TOKEN=.' .env || echo "BIMETRI_MEMORY_MCP_TOKEN=$(openssl rand -hex 32)" >> .env
    ```
    ```bash
    docker compose -p agentickode -f docker-compose.dev.yml -f docker-compose.prod.yml -f docker-compose.swag.yml -f docker-compose.bimetri.yml up -d --build memory-mcp backend frontend
    ```
    Then write the worker users' Claude (`~/.claude.json`, user scope) and Codex
    (`~/.codex/config.toml`, `http_headers`) config; the token goes over SSH stdin, never printed:
    ```bash
    scripts/bimetri/agent-memory-mcp.sh 192.168.20.10 192.168.20.11 192.168.20.12
    ```
    Each host prints `codex: written`, `claude: written` and the `bimetri-memory` lines of
    `codex mcp list` / `claude mcp list` (Claude: `✓ Connected`). Check the service:
    `curl -s http://<MEM0_BIND>:8892/health` = `ok`, `curl -s -o /dev/null -w '%{http_code}' -X POST http://<MEM0_BIND>:8892/mcp` = `401`.
    In a run log the agent's tool calls show as `mcp__bimetri-memory__...` (Claude).

12. OpenAI spend card (Dashboard). Shows this month's OpenAI API spend from the Costs API, the
    credits you enter, the remaining balance and a red state when OpenAI answers
    `insufficient_quota` / `credit_balance_exhausted` (one message to the notification channels).
    Create an Admin key (Organization Owner, read-only, Usage scope) at
    `platform.openai.com/settings/organization/admin-keys`, then put it in `.env` without echoing it:
    ```bash
    bash -c 'read -rsp "OPENAI_ADMIN_KEY: " K; echo; sed -i "/^OPENAI_ADMIN_KEY=/d" .env; printf "OPENAI_ADMIN_KEY=%s\n" "$K" >> .env'
    ```
    ```bash
    docker compose -p agentickode -f docker-compose.dev.yml -f docker-compose.prod.yml -f docker-compose.swag.yml -f docker-compose.bimetri.yml up -d backend
    ```
    ```bash
    docker compose -p agentickode -f docker-compose.dev.yml -f docker-compose.prod.yml -f docker-compose.swag.yml -f docker-compose.bimetri.yml up -d --build frontend
    ```
    The backend code is mounted from the repo, so it needs no image build (`--build backend`
    reinstalls apt and pip packages for minutes). Migration `b047_openai_usage` runs on backend start. On the **OpenAI Balance** card, **+** (Add credit): first entry =
    the credit balance on `platform.openai.com/settings/organization/billing` right now, dated
    today; later entries = each top-up. Sync runs every 15 min (`OPENAI_USAGE_POLL_SECONDS`) and on
    the refresh icon.

Rollback (data written after the migration is lost):
```bash
docker compose -p agentickode -f docker-compose.dev.yml -f docker-compose.prod.yml -f docker-compose.swag.yml -f docker-compose.bimetri.yml stop mem0 postgres
docker compose -p agentickode -f docker-compose.dev.yml -f docker-compose.prod.yml -f docker-compose.swag.yml up -d
```
Then remove `-f docker-compose.bimetri.yml` from `pull-restart.sh` (a `.bak-*` copy is kept).

Restore a backup into a running DB: `docker exec -i <postgres> pg_restore -U agentickode -d <db> --clean --if-exists < file.dump`.

## Common Issues

| Problem | Fix |
|---|---|
| `agentickode-app_pgvdata zaten var` | Previous attempt left it. If unused: `docker volume rm agentickode-app_pgvdata` |
| `N kosu bitmemis` | Wait for runs to finish, or `FORCE=1` |
| Row counts differ | Script stops; follow the printed rollback, keep the dump, investigate |
| `port is already allocated` / `address already in use` on 8890 | Change the host port in `docker-compose.bimetri.yml` |
| mem0 `401` from clients | Send `X-API-Key: <ADMIN_API_KEY>` |
| Run log `Proje hafızası eklenmedi (mem0: HTTPStatusError: ... 401 ...)` | `MEM0_API_KEY` revoked or wrong. Remove the line from `.env`, rerun `mem0-backend-key.sh`, then `up -d backend` |
| Run log `... 502 Bad Gateway` | mem0 could not reach OpenAI (key or quota). Check `docker logs agentickode-mem0-1` |
| mem0 log `401 - Your IP is not authorized` | The OpenAI project has an IP allowlist. Add the server's outbound IP: `docker exec agentickode-mem0-1 python -c "import urllib.request;print(urllib.request.urlopen('https://api.ipify.org').read().decode())"` |
| `mem0-bootstrap.py ... zaten var` | A draft (maybe your edited one) exists. Upload it, move it, or pass `--out` |
| `mem0-bootstrap.py` `HATA: ...:N: 'tur' ...` | Line N of the edited draft is invalid JSON or has an unknown `tur`/empty `memory` |
| Runs still log `Proje hafızasında kayıt yok` after upload | Project name differs from the run's `<owner>/<repo>` (case). Re-upload with `--project` |
| `PR #N ozellik gecmisi yazilamadi` | Traceback follows. `401` from mem0: see the key row above; `404` on `/pulls/N/commits` or `/files`: the project token cannot read the repo |
| No `ozellik gecmisi` line after a merge | The PR webhook (pull_request events) is not set on the Gitea repo, or the backend log level hides INFO |
| `PR #N memory proposals failed` | Traceback follows. `401` from api.openai.com: `MEM0_OPENAI_API_KEY` wrong (remove the line, rerun the key script, `up -d backend`); `403`/IP: same allowlist as mem0 |
| `memory proposals ...: disabled` | `MEM0_OPENAI_API_KEY` missing in `.env` or backend not recreated with `up -d backend` |
| Memory page: `Approve failed: mem0 write failed` (502) | mem0 down or key revoked; the proposal stays `pending`, approve again later |
| No **Memory** item in the menu | Frontend not rebuilt: `up -d --build frontend` |
| Dashboard login works but pages show `Network Error` | CORS: mem0 not recreated with `DASHBOARD_URL`, or the page was opened by another host name than `MEM0_BIND`. `up -d mem0`, open `http://<MEM0_BIND>:8891` |
| Dashboard login succeeds (mem0 log: `POST /auth/login` 200) but returns to `/login` | Refresh cookie marked `Secure` over plain HTTP: `mem0-dashboard` lacks `DASHBOARD_URL=http://...:8891`. Set it, `up -d mem0-dashboard` |
| Forgotten mem0 admin password | No reset mail. On the host: `read -rp 'Email: ' EMAIL; read -rsp 'Password: ' PASSWORD; export EMAIL PASSWORD`, then `docker exec -e EMAIL -e PASSWORD -w /app agentickode-mem0-1 python scripts/reset_admin_password.py; unset PASSWORD` (min 8 chars) |
| `mem0-dashboard` build: `Cannot find module '@/lib/runs'` in `./evaluation/...` | Older BuildKit puts the repo's `evaluation` submodule into the subdir context; `docker/mem0-dashboard/Dockerfile` removes it. Keep building through that Dockerfile, not the upstream one |
| Records tab: `Failed to load records: mem0 is not configured` | `MEM0_API_KEY` empty in `.env`; see step 6 |
| No memory log line at all | `MEM0_API_KEY` empty, or backend not recreated (`up -d backend`) |
| `HATA: uzak kopya yuklenemedi` | Key not installed, wrong host key in `storagebox_known_hosts`, or port 23 blocked. Test: `ssh -p 23 -i /root/.ssh/storagebox_ed25519 -o UserKnownHostsFile=/root/.ssh/storagebox_known_hosts <sub>@<sub>.your-storagebox.de ls` |
| `agent-memory-mcp.sh`: `.../health does not answer` | `memory-mcp` not running or `MEM0_BIND` not set: `up -d memory-mcp`, `docker logs agentickode-memory-mcp-1` |
| `claude mcp list` shows `bimetri-memory ... ✗ Failed to connect` | Worker cannot reach `<MEM0_BIND>:8892` (firewall) or the token in `.env` changed; rerun `agent-memory-mcp.sh` after a token change |
| Run prompt has no "Hafıza araçları" lines | `BIMETRI_MEMORY_MCP_TOKEN` missing in `.env` or backend not recreated with `up -d backend` |
| Backend port open but every request times out | Pre-fix symptom: with `--reload` a crashed worker left the reloader holding the port. `docker-compose.bimetri.yml` now sets `UVICORN_RELOAD: ""` so a crash exits the container and Docker restarts it; `PYTHONFAULTHANDLER` prints the stack. Native crashes show in the host's `kern.log` as `segfault ... libpython3.12` |
| Agent proposal refused: `run N does not belong to org/repo` | The agent passed another project's name or a wrong `run_id`; the values are in the prompt's memory section |
| Card: `OPENAI_ADMIN_KEY tanımlı değil` | Key missing in `.env` or backend not recreated with `up -d backend` |
| Balance card red dot, tooltip `OpenAI 403: ... Missing scopes: api.usage.read` | A project key, or an Admin key without Usage read. Create an Admin key with Usage read, rewrite the `.env` line, `up -d backend` |
| Balance card red dot, tooltip `OpenAI 401 ...` | Key revoked or mistyped; rewrite the `.env` line, `up -d backend` |
| Spend chart month total differs from the usage page | Compare the same UTC month; press the refresh icon (late cost is picked up on each sync) |
| Card remaining differs from the billing page | Edit the opening entry (spend earlier that UTC day is counted against it) |
