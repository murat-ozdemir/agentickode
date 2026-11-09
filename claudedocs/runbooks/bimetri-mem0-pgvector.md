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
5. From now on every compose command needs the extra file:
   `-f docker-compose.dev.yml -f docker-compose.prod.yml -f docker-compose.swag.yml -f docker-compose.bimetri.yml`.

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
| Backups only on the same disk | Copy `/var/backups/agentickode` off-host separately (not covered here) |
