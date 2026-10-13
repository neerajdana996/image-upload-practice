# Task: album image uploads with presigned URLs

Build an API where a client uploads images into an album. The file bytes go straight from the client to MinIO through a presigned URL and never pass through the API. The API must still find out when each upload has finished and record it.

The repo already gives you the running stack, a MinIO client with the bucket created (`app/storage.py`), and a Postgres engine and session (`app/database.py`). Everything else is yours to build.

## The flow

1. The client creates an album.
2. The client asks the API for an upload slot in that album, sending the filename and content type. The API saves an image row with status `pending` and returns the image id plus a presigned `PUT` URL.
3. The client `PUT`s the file bytes to that URL. This request goes to MinIO, not to the API.
4. MinIO notifies the API that the object was created. The API marks the image `uploaded` and stores its size.
5. The client lists the album and sees the image as `uploaded`, with a URL it can use to view it.

## How the API learns the upload finished

This is the core of the task. Since the upload bypasses the API, something has to tell it. Use **MinIO bucket notifications**: MinIO calls a webhook on the API every time an object is created in the bucket.

- Turn on a webhook target in the `minio` service in `docker-compose.yml` with `MINIO_NOTIFY_WEBHOOK_ENABLE_<NAME>`, `MINIO_NOTIFY_WEBHOOK_ENDPOINT_<NAME>` and `MINIO_NOTIFY_WEBHOOK_AUTH_TOKEN_<NAME>`. From inside the compose network the API is reachable at `http://api:8000`.
- Subscribe the bucket to `s3:ObjectCreated:*` events for that target. Do this in code next to `ensure_bucket()` so a fresh `docker compose up` needs no manual steps.
- Add a webhook endpoint to the API that receives the event, finds the image row from the object key, and marks it `uploaded`.

Do not rely on the client calling a "I'm done" endpoint. A client can crash, lie, or close the tab after the upload succeeds.

## Requirements

**Data**

- `albums`: id, name, created time.
- `images`: id, album id, original filename, content type, object key, status (`pending` or `uploaded`), size, created time, uploaded time.
- Object keys follow `albums/{album_id}/{image_id}{extension}` so the webhook can map a key back to a row. Never put the client's filename in the key.

**Endpoints** (names are a suggestion)

| Method | Path | What it does |
| --- | --- | --- |
| POST | `/albums` | Create an album |
| GET | `/albums/{album_id}` | Album details |
| POST | `/albums/{album_id}/images` | Create a pending image, return a presigned `PUT` URL |
| GET | `/albums/{album_id}/images` | List images with status; uploaded ones include a presigned `GET` URL |
| GET | `/albums/{album_id}/images/{image_id}` | One image, so a client can poll its status |
| POST | `/internal/minio-events` | Webhook called by MinIO |

**Rules**

- Only `image/*` content types get an upload URL.
- Presigned URLs expire, 10 minutes or less.
- The webhook rejects requests without the correct auth token.
- The webhook is idempotent. MinIO can deliver the same event more than once.
- An event for a key that matches no row is logged and answered with a 2xx, not an error, so MinIO does not keep retrying it.
- An upload to an album that does not exist returns 404.

## Things that will trip you up

- **Presigned URL host.** The API talks to MinIO at `minio:9000`, a name that only resolves inside Docker. A URL signed for that host is useless to a client on your machine, and you cannot just rewrite the host afterwards because the host is part of the signature. Sign with a client configured for the public address (`localhost:9100`). Give that client a fixed `region` so signing does not need a network call to an address the container cannot reach.
- **Startup order.** MinIO starts before the API, so the webhook endpoint is not up when MinIO first looks for it. Check how MinIO behaves in that case and make the subscription step survive it.
- **Event payload.** The object key in the event is URL-encoded, and the event's `Key` field is prefixed with the bucket name.
- **Content type.** If the content type is part of the signed request, the client's `PUT` must send exactly the same `Content-Type` header.

## Done when

- `docker compose up -d --build` on a clean checkout brings everything up with no manual MinIO configuration.
- This works end to end with `curl`: create an album, request an upload URL, `PUT` a file to it, and within a couple of seconds the image shows as `uploaded` in the album listing with the correct size.
- The returned view URL opens the image in a browser.
- A second delivery of the same event changes nothing.
- The README explains how to run it and shows the `curl` commands for the flow.

## Stretch goals

- Clean up `pending` images whose upload URL expired without an upload.
- Push the "uploaded" update to the client with Server-Sent Events or a WebSocket instead of polling.
- Enforce a maximum file size. A presigned `PUT` cannot do this; look at presigned `POST` policies.
- Handle `s3:ObjectRemoved:*` events so the database stays in step with the bucket.
- Add Alembic migrations and tests.
