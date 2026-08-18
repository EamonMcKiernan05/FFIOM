# Fantasy Football Isle of Man

FPL-style fantasy football for the Isle of Man football leagues (Canada Life Premier League and below). FastAPI + SQLAlchemy backend, vanilla-JS SPA frontend, a .NET scraper for FullTime data, and a native iOS companion app.

**Live:** https://ffiom.com — a single Docker image on `192.168.1.23` (ffiom-prod VM).

## Features

- FPL-style scoring: captain / vice-captain, transfers, chips, gameweek deadlines
- Live data pipeline syncing fixtures, results and tables from the FullTime API
- Performance-adjusted player pricing and price-change engine
- Squad tracking, transfer history, gameweek recaps, H2H and mini-leagues
- 26/27 season: updated league/division config, squad transfer tracking with gameweek-bound transfers and top-ups
- Vanilla-JS SPA (CSS token system, 14 page templates) + iOS app ([FFIOM-IOS-App](https://github.com/EamonMcKiernan05/FFIOM-IOS-App))

## Architecture

One Docker image runs **three** processes under s6-overlay, all as the non-root user `ffiom`:

| Process | Port | Role |
|---|---|---|
| uvicorn (`app.main`) | 8000 | FastAPI game API + frontend |
| FullTimeAPI (.NET 9) | 5000 | Scrapes fulltime.thefa.com via fa_proxy |
| fa_proxy (curl_cffi) | 5001 | Chrome-TLS impersonation proxy (defeats Cloudflare on thefa.com) |

Two SQLite databases, bind-mounted from host folders into the container:

| Mount | Contents |
|---|---|
| `/data/game` | Game DB — users, teams, transfers, leagues (irreplaceable) |
| `/data/ffiom` | FFIOM-DB — players, prices, fixtures (source of truth, rebuilt by the scraper) |

Databases are **never** baked into the image — `data/`, `*.db` and `.env` are git-ignored, and the Dockerfile only creates empty mount-point directories.

The Cloudflare tunnel deliberately does **not** run in the image — it runs on the host as a systemd service (`cloudflared.service`), so the image ships only the three app processes above.

## Repo layout

```
app/                  FastAPI application (routes, auth, scoring, scheduler, models)
FullTimeAPI/          .NET 9 scraper + fa_proxy.py (TLS-impersonation proxy)
static/               Vanilla-JS SPA frontend (pages, css tokens, js)
alembic/              Database migrations
docker/s6/            s6-overlay service definitions (api, faproxy, fulltime)
scripts/              fetch-and-score.py, gen_pages.py, import_season_players.py
tests/                Pytest suite (production DB isolation)
Dockerfile            Multi-stage build: .NET SDK → aspnet:9.0 + python venv + s6-overlay
compose.yaml          Production compose (host .env + bind-mounted DBs)
deploy.sh             Build-kit deploy: docker save | ssh host | docker load
run.py                Dev entrypoint (uvicorn reload — NOT used in the container)
```

## Building the image

```bash
docker compose build        # or: docker build -t ffiom:latest .
```

## Deploying to a host

**Primary flow (repo-based, used for prod):**

1. Push to the repo (`main`).
2. On the VM: `ssh root@192.168.1.23 /home/ffiom/update.sh`
   The script pulls the repo, builds the image, backs up both DBs, swaps the container, health-checks `/api/health` and rolls back on failure.

**Alternative (build-kit flow):**

```bash
bash deploy.sh              # builds locally, transfers the image, restarts the container
```

**First-time host setup:**

1. Install Docker Engine + compose plugin.
2. Create data folders and place the DBs:
   ```
   /home/ffiom/data/game/fantasy_iom.db
   /home/ffiom/data/ffiom/fantasy_iom.db
   ```
3. Create `/home/ffiom/.env` from `.env.example` (secrets: `APP_SECRET_KEY`, Google OAuth creds). Mode 600.
4. Copy `compose.yaml` to `/home/ffiom/` and adjust the volume paths if needed.
5. `cd /home/ffiom && docker compose up -d`
6. Tunnel on the host: `cloudflared service install <token>` (systemd service; token file at `/etc/cloudflared/token`). The tunnel's ingress points at `http://192.168.1.23:8000`.

## Updating

```bash
# push the new code to GitHub, then on the VM:
ssh root@192.168.1.23 /home/ffiom/update.sh
```

Image rebuilds never touch the databases — they live in host folders.

## Key env vars

| Var | Meaning |
|---|---|
| `FULLTIME_API_BASE_URL` | FullTime API base for the scraper |
| `IOM_LEAGUE_ID` | FullTime league ID (IOM Senior Men's) |
| `DIV_PREMIER`, `DIV_2`, `DIV_COMBINATION_1`, `DIV_COMBINATION_2` | Division IDs for the 26/27 season |
| `GW_DEADLINE_HOUR`, `GW_DEADLINE_MINUTE`, `GW_DAY_OF_WEEK` | Gameweek deadline schedule |
| `BONUS_POINTS_HOUR`, `BONUS_POINTS_MINUTE` | Bonus points processing time |
| `APP_SECRET_KEY` | JWT signing key — the app refuses to start with the default value |
| `DATABASE_URL` / `FFIOM_DB_PATH` | Overridden by compose to the in-container mount points |
| `APP_BASE_URL` | Public origin (https://ffiom.com in prod) |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GOOGLE_REDIRECT_URI` | Google OAuth |

## Local development

```bash
source venv/bin/activate
python run.py               # uvicorn reload on :8000 — dev only
```

`compose.override.yaml` (git-ignored) overrides the prod compose for local runs. Tests: `pytest`.

## Notes

- `run.py` uses uvicorn `reload=True` — the container does NOT use it; s6 runs uvicorn directly without reload.
- The game DB has `PRAGMA foreign_keys` deliberately OFF (players live in the separate FFIOM-DB; see `app/database.py`).
- Security audit 2026-07-25 hardened auth (JWT-only, hashed + rotated refresh tokens, rate limits, admin gating, IDOR fixes).
