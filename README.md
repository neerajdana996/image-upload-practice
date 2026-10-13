# Image Upload Practice

FastAPI service that stores image files in MinIO and their metadata in Postgres, all run with Docker Compose.

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

## API

| Method | Path                | Description                         |
| ------ | ------------------- | ----------------------------------- |
| GET    | `/health`           | Checks Postgres and MinIO           |
| POST   | `/images`           | Upload an image (multipart `file`)  |
| GET    | `/images`           | List metadata (`limit`, `offset`)   |
| GET    | `/images/{id}`      | Metadata for one image              |
| GET    | `/images/{id}/file` | Download the image bytes            |
| DELETE | `/images/{id}`      | Delete the image and its metadata   |

```bash
curl -F "file=@photo.png" http://localhost:8000/images
```

Uploads must have an `image/*` content type and be under `MAX_UPLOAD_MB` (default 10).

## Layout

```
app/
  main.py      routes
  config.py    settings from environment
  database.py  SQLAlchemy engine and session
  models.py    Image table
  schemas.py   response models
  storage.py   MinIO client
```

The `app/` directory is mounted into the container and uvicorn runs with `--reload`, so code edits apply without rebuilding.
The table is created on startup with `create_all`; there are no migrations yet.

## Stop

```bash
docker compose down      # keep data
docker compose down -v   # also remove the Postgres and MinIO volumes
```
