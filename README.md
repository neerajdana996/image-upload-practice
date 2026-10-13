# Image Upload Practice

Starting point for an image upload service: FastAPI, MinIO and Postgres run with Docker Compose.
So far the app only sets up its connections: on startup it checks the Postgres connection and makes sure the MinIO bucket exists. There are no routes or tables yet.

The assignment to build on top of this is in [TASK.md](TASK.md).

## Run

```bash
cp .env.example .env   # optional, the defaults work without it
docker compose up -d --build
```

| Service       | URL                                                  |
| ------------- | ---------------------------------------------------- |
| API docs      | http://localhost:8000/docs                           |
| MinIO console | http://localhost:9101 (`minioadmin` / `minioadmin123`) |
| MinIO S3 API  | http://localhost:9100                                |
| Postgres      | `localhost:5433` (`app` / `app_password`, db `images`) |

Host ports are set in `.env`. Postgres and MinIO use 5433 / 9100 / 9101 rather than the usual
5432 / 9000 / 9001 so they don't clash with other local stacks.

## Layout

```
app/
  main.py      FastAPI app, checks Postgres and ensures the bucket on startup
  config.py    settings from environment
  database.py  SQLAlchemy engine, session and Base
  storage.py   MinIO client and ensure_bucket
```

The `app/` directory is mounted into the container and uvicorn runs with `--reload`, so code edits apply without rebuilding.
Changes to `requirements.txt` need `docker compose up -d --build`.

## Stop

```bash
docker compose down      # keep data
docker compose down -v   # also remove the Postgres and MinIO volumes
```
