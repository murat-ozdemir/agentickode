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
| No memory log line at all | `MEM0_API_KEY` empty, or backend not recreated (`up -d backend`) |
| `HATA: uzak kopya yuklenemedi` | Key not installed, wrong host key in `storagebox_known_hosts`, or port 23 blocked. Test: `ssh -p 23 -i /root/.ssh/storagebox_ed25519 -o UserKnownHostsFile=/root/.ssh/storagebox_known_hosts <sub>@<sub>.your-storagebox.de ls` |
