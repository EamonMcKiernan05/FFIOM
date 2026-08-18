# Fantasy Football Isle of Man

FPL-style fantasy football for the Isle of Man football leagues. FastAPI + SQLAlchemy backend, static JS frontend, with a .NET scraper for FullTime data.

**Live:** https://ffiom.com — runs as a single Docker container on `192.168.1.23` (ffiom-prod VM).

## Architecture

One Docker image runs four processes under s6-overlay (all as non-root user `ffiom`):

| Process | Port | Role |
|---|---|---|
| uvicorn (`app.main`) | 8000 | FastAPI game API + frontend |
| FullTimeAPI (.NET 9) | 5000 | Scrapes fulltime.thefa.com via fa_proxy |
| fa_proxy (curl_cffi) | 5001 | Chrome-TLS impersonation proxy (defeats Cloudflare on thefa.com) |

Two SQLite databases, bind-mounted from host folders into the container:

| Mount | Contents |
|---|---|
| `/data/game` | Game DB — users, teams, transfers, leagues (irreplaceable) |
| `/data/ffiom` | FFIOM-DB — players, prices, fixtures (source of truth, rebuilt by scraper) |

Databases are **never** baked into the image — `data/` is in `.dockerignore`, and the Dockerfile only creates empty mount-point directories.

## Building the image

```bash
docker compose build        # or: docker build -t ffiom:latest .
```

Multi-stage build: .NET SDK publishes the scraper, then python + deps + s6-overlay are layered on the aspnet runtime image. Cloudflared is deliberately NOT in the image — the tunnel runs on the host as a systemd service.

## Deploying to a host

1. Install Docker Engine + compose plugin.
2. Transfer the image: `docker save ffiom:latest | gzip | ssh host 'gunzip | docker load'`
3. Create data folders and place the DBs:
   ```
   /home/ffiom/data/game/fantasy_iom.db
   /home/ffiom/data/ffiom/fantasy_iom.db
   ```
4. Create `/home/ffiom/.env` from `.env.example` (secrets: `APP_SECRET_KEY`, Google OAuth creds). Mode 600.
5. Copy `compose.yaml` to `/home/ffiom/` and adjust the volume paths if needed.
6. `cd /home/ffiom && docker compose up -d`
7. Tunnel: `cloudflared service install <token>` (systemd service on the host).

## Updating

```bash
# build new image locally, transfer, swap
docker save ffiom:latest | gzip | ssh host 'gunzip | docker load && docker restart ffiom'
```

Image rebuilds never touch the databases — they live in host folders.

## Key env vars

| Var | Meaning |
|---|---|
| `APP_SECRET_KEY` | JWT signing key — app refuses to start without a non-default value |
| `DATABASE_URL` / `FFIOM_DB_PATH` | Overridden by compose to in-container mount points |
| `APP_BASE_URL` | Public origin (https://ffiom.com in prod) |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GOOGLE_REDIRECT_URI` | OAuth |

## Notes

- `run.py` (dev entrypoint) uses uvicorn `reload=True` — the container does NOT use it; s6 runs uvicorn directly without reload.
- The game DB has `PRAGMA foreign_keys` deliberately OFF (players live in the separate FFIOM-DB; see `app/database.py`).
- Security audit 2026-07-25 hardened auth (JWT-only, hashed+rotated refresh tokens, rate limits, admin gating, IDOR fixes).
