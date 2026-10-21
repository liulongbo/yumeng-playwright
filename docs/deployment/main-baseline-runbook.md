# Single-node baseline: deploy plain `main` (no hybrid topology)

Purpose: run the code that is on `main` as one self-contained Compose project on a single cloud
host, so it can be compared with the hybrid deployment (`lln_1018`: cloud centre + Mac collection
worker over Tailscale). The baseline deliberately has **no** Tailscale, **no** Mac worker, **no**
private-bind addresses, and **no** remote viewer.

This directory is additive deployment scaffolding only; it does not change application code.

## 1. What runs where

| Service | Network | Host port |
|---|---|---|
| `web` (Nginx + built console) | `data` | `${WEB_BIND_PORT:-18080}` → public |
| `api` | `data`, `egress` | `127.0.0.1:${API_BIND_PORT:-18000}` |
| `app-postgres`, `temporal-postgres`, `temporal`, `redis`, `objects` | `data` only | none published |
| `migration`, `objects-init` | `data` | one-shot |
| `intake-worker`, `update-scheduler`, `collection-worker` | `data`, `egress` | none |

`data` is an internal Docker network. Only `web` is reachable from outside; the API port stays on
host loopback and is proxied by the bundled Nginx under `/api/`.

All resources are namespaced by the Compose project name `xingtu-baseline`, so volumes, networks
and container names cannot collide with another Compose project on the same host. Nothing is
installed under `/opt` by this file; the deployment directory is chosen by the operator.

## 2. Prerequisites

- Docker Engine + Compose v2 on the host.
- A private deployment directory outside Git (for example `/opt/yumeng-xingtu-baseline`) that holds
  the checked-out branch plus the filled env files.
- Free host ports `18080` and `18000`. Verify with `ss -lntp` before starting; if either is taken,
  change `WEB_BIND_PORT` / `API_BIND_PORT` instead of touching the existing applications.
- Roughly 3.5–4 GiB of free memory for the full set including Chromium. On a host that already runs
  two applications, confirm headroom with `free -m` and lower the `*_MEMORY_LIMIT` values before
  starting the worker. Without that headroom, start the centre services only and add
  `collection-worker` later.

## 3. First deployment

```sh
# 1) copy the branch (git archive from the pushed branch, or rsync of a clean checkout)
git archive --format=tar origin/deploy/main-single-node | ssh ubuntu@HOST 'tar -x -C /opt/yumeng-xingtu-baseline'

# 2) create the private files from the templates and fill every CHANGE_ME value
cd /opt/yumeng-xingtu-baseline
cp deploy/single-node.env.example deploy/single-node.env
cp deploy/single-node.application.env.example deploy/single-node.application.env
cp deploy/units/unit-server-01.json.example deploy/units/unit-server-01.json
chmod 600 deploy/single-node.env deploy/single-node.application.env

# 3) validate interpolation, then build in dependency order
docker compose --env-file deploy/single-node.env -f deploy/single-node.compose.yaml config >/dev/null
docker compose --env-file deploy/single-node.env -f deploy/single-node.compose.yaml build api
docker compose --env-file deploy/single-node.env -f deploy/single-node.compose.yaml build web collection-worker

# 4) bring up the data plane, then the application plane
docker compose --env-file deploy/single-node.env -f deploy/single-node.compose.yaml up -d \
  app-postgres temporal-postgres redis objects temporal
docker compose --env-file deploy/single-node.env -f deploy/single-node.compose.yaml up -d objects-init
docker compose --env-file deploy/single-node.env -f deploy/single-node.compose.yaml up migration
docker compose --env-file deploy/single-node.env -f deploy/single-node.compose.yaml up -d api web

# 5) console account (password is read from stdin, never echoed)
docker compose --env-file deploy/single-node.env -f deploy/single-node.compose.yaml run --rm --no-deps \
  api sh -lc 'read -r pw; printf "%s\n%s\n" "$pw" "$pw" | xingtu-product create-user --username admin --display-name 管理员 --actor ops'
```

`main` only accepts `xingtu migrate --environment development|test`, which is why the migration job
uses `development`; the flag selects the audit label, not the target database.

## 4. Unit registration and worker

The baseline unit config is `deploy/units/unit-server-01.json` with
`network_mode: "local_development"`, so the worker starts without a `NetworkProof` and without a
proxy; it is explicitly not a mobile-line production unit. Register it once:

```sh
docker compose ... run --rm --no-deps api xingtu register-unit --config /app/units/unit-server-01.json
```

Then `collection-worker` polls `xingtu-unit-server-01`. It runs **headless** Chromium inside the
worker container. There is no interactive login path in this container: a real 星图 session must be
seeded first (for example an approved session snapshot), otherwise tasks stay queued and the unit
remains `SESSION_UNVERIFIED`. Copying the Mac profile to the server is a separate, explicitly
approved decision; the platform may treat the new egress IP as a risk event.

## 5. Verification

```sh
# `main` has no /api/health/live route; a TCP probe is the liveness check.
python3 -c "import socket; socket.create_connection(('127.0.0.1', 18000), 3)"
curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:18080/
curl -fsS http://127.0.0.1:18080/api/health/workers
docker compose --env-file deploy/single-node.env -f deploy/single-node.compose.yaml ps
docker stats --no-stream
ss -lntp | grep -E '18080|18000'
```

Acceptance evidence to record: Compose config parse, image build log, `ps` healthy states, login
page HTTP 200 through `web`, API port reachable, worker registered, per-container memory.

## 6. Isolation rules

- Do not publish `5432`, `7233`, `6379`, `9000` or `9001`; `single-node.compose.yaml` does not.
- Do not reuse an existing Nginx/Baota site, port 80/443 or another application's database.
- Do not run `docker compose down -v`; the volumes hold the only copy of the baseline data.
- Keep `single-node.env` and `single-node.application.env` at mode 600 and out of Git.

## 7. Known limits

- No TLS: the session cookie is configured non-Secure for plain HTTP on a non-standard port.
- No F10 remote takeover and no Mac-side playback.
- `local_development` is not a production line; real egress verification, mobile line proof and
  fail-closed network checks are only covered by the hybrid topology.
