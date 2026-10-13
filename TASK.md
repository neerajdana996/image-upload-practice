# Task: album image uploads with presigned URLs

Build an API where a client uploads images into an album. The file bytes go straight from the client to MinIO through a presigned URL and never pass through the API. The API must still find out when each upload has finished and record it.

The repo already gives you the running stack, a MinIO client with the bucket created (`app/storage.py`), a Postgres engine and session (`app/database.py`), and a MinIO webhook target pointed at the API. Everything else is yours to build.

## The flow

1. The client creates an album.
2. The client asks the API for an upload slot in that album, sending the filename and content type. The API saves an image row with status `pending` and returns the image id plus a presigned `PUT` URL.
3. The client `PUT`s the file bytes to that URL. This request goes to MinIO, not to the API.
4. MinIO notifies the API that the object was created. The API marks the image `uploaded` and stores its size.
5. The client lists the album and sees the image as `uploaded`, with a URL it can use to view it.

## How the API learns the upload finished

This is the core of the task. Since the upload bypasses the API, something has to tell it. Use **MinIO bucket notifications**: MinIO calls a webhook on the API every time an object is created in the bucket.

- The webhook target is already configured on the `minio` service in `docker-compose.yml`. Its ARN is `arn:minio:sqs::PRIMARY:webhook`, and it posts to `http://api:8000/internal/minio-events`.
- MinIO sends the token as an `Authorization: Bearer <token>` header. The API receives the same token in the `MINIO_WEBHOOK_TOKEN` environment variable.
- Subscribe the bucket to `s3:ObjectCreated:*` events for that ARN. Nothing is subscribed yet, so no events are sent until you do. Do this in code next to `ensure_bucket()` so a fresh `docker compose up` needs no manual steps.
- Add the `POST /internal/minio-events` endpoint to the API. It receives the event, finds the image row from the object key, and marks it `uploaded`.

Do not rely on the client calling a "I'm done" endpoint. A client can crash, lie, or close the tab after the upload succeeds.

## Requirements

**Data**

- `albums`: `id`, `name`, `created_at`.
- `images`: `id`, `album_id`, `filename`, `content_type`, `object_key`, `status` (`pending` or `uploaded`), `size`, `created_at`, `uploaded_at`.
- Object keys follow `albums/{album_id}/{image_id}{extension}` so the webhook can map a key back to a row. Never put the client's filename in the key.

**Endpoints**

The paths, field names and status codes below are required. Use them exactly, so the requests in [POSTMAN.md](POSTMAN.md) work against your API without changes.

| Method | Path | What it does | Success |
| --- | --- | --- | --- |
| POST | `/albums` | Create an album | 201, album |
| GET | `/albums/{album_id}` | Album details | 200, album |
| POST | `/albums/{album_id}/images` | Create a pending image, return a presigned `PUT` URL | 201, image with `upload_url` |
| GET | `/albums/{album_id}/images` | List the album's images | 200, list of images |
| GET | `/albums/{album_id}/images/{image_id}` | One image, so a client can poll its status | 200, image |
| POST | `/internal/minio-events` | Webhook called by MinIO | 200 |

**Request bodies**

`POST /albums`

```json
{
  "name": "Holiday"
}
```

`POST /albums/{album_id}/images`

```json
{
  "filename": "photo.png",
  "content_type": "image/png"
}
```

**Response bodies**

Album:

```json
{
  "id": "5f0c2a4e-8f6b-4a57-9d0e-0f4b3a1c9e21",
  "name": "Holiday",
  "created_at": "2026-10-13T08:30:00Z"
}
```

Image:

```json
{
  "id": "b7a1d2c3-4e5f-4a6b-8c7d-9e0f1a2b3c4d",
  "album_id": "5f0c2a4e-8f6b-4a57-9d0e-0f4b3a1c9e21",
  "filename": "photo.png",
  "content_type": "image/png",
  "status": "uploaded",
  "size": 48213,
  "created_at": "2026-10-13T08:31:00Z",
  "uploaded_at": "2026-10-13T08:31:04Z",
  "url": "http://localhost:19000/images/albums/..."
}
```

- `status` is `pending` or `uploaded`.
- `size`, `uploaded_at` and `url` are `null` while the image is `pending`.
- `url` is a presigned `GET` URL for viewing the file.
- The response to `POST /albums/{album_id}/images` is the same image object with one extra field, `upload_url`, holding the presigned `PUT` URL. No other response includes `upload_url`.
- `object_key` is internal and is not returned.

**Error responses**

| Status | When |
| --- | --- |
| 404 | The album or image does not exist, or the image is not in that album |
| 415 | `content_type` does not start with `image/` |
| 401 | The webhook is called without the correct token |
| 422 | The request body is missing a field or an id is malformed. FastAPI does this for you. |

**Rules**

- Presigned URLs expire, 10 minutes or less.
- The webhook rejects requests without the correct auth token.
- The webhook is idempotent. MinIO can deliver the same event more than once.
- An event for a key that matches no row is logged and answered with a 2xx, not an error, so MinIO does not keep retrying it.

## Step by step

Do the steps in order and get each one working before starting the next. Every step ends with a check you can run. The hints are collapsed so you can try first; open them when you are stuck.

Useful while you work:

```bash
docker compose logs -f api
```

```bash
docker compose exec postgres psql -U app -d images
```

To test with Postman instead of `curl`, follow [POSTMAN.md](POSTMAN.md).

Code changes in `app/` reload on their own. The interactive API docs are at http://localhost:18000/docs and the MinIO console is at http://localhost:19001.

### Step 1: Create the tables

Add the `albums` and `images` models and have the tables created when the app starts.

**Check:** `\dt` in `psql` lists both tables.

<details>
<summary>Hints</summary>

- Put the models in a new `app/models.py`. Each one inherits from `Base` in `app/database.py`.
- Use the SQLAlchemy 2.0 style: `id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)`.
- `images.album_id` is a `ForeignKey("albums.id")`.
- `size` and `uploaded_at` are empty until the upload finishes, so they must be nullable: `Mapped[int | None]`.
- Create the tables in the `lifespan` function in `app/main.py` with `Base.metadata.create_all(engine)`. The models module must be imported before that line runs, or `Base` does not know about the tables.
- `create_all` only creates missing tables. It does not change a table that already exists. While you are still changing columns, reset the database with `docker compose down -v` and start again. This deletes all data.

</details>

### Step 2: Album endpoints

Add `POST /albums` and `GET /albums/{album_id}`.

**Check:** you can create an album from the docs page and fetch it back by id. A random id returns 404.

<details>
<summary>Hints</summary>

- Use Pydantic models for the request body and the response, in a new `app/schemas.py`. Set `model_config = ConfigDict(from_attributes=True)` on response models so FastAPI can build them from SQLAlchemy objects.
- Get a database session in a route with `db: Session = Depends(get_db)`.
- To save: `db.add(album)`, then `db.commit()`.
- To load by id: `db.get(Album, album_id)`. It returns `None` when there is no row; raise `HTTPException(status_code=404)` in that case.
- Type the path parameter as `uuid.UUID` and FastAPI rejects malformed ids for you.
- As the file grows, move routes into an `APIRouter` and attach it with `app.include_router(...)`.

</details>

### Step 3: A MinIO client for signing URLs

Create a second MinIO client that signs URLs for the address your machine uses to reach MinIO.

**Check:** in a Python shell inside the container (`docker compose exec api python`), generating a presigned URL returns a URL that starts with `http://localhost:19000/`.

<details>
<summary>Hints</summary>

- Read "Presigned URL host" under [Things that will trip you up](#things-that-will-trip-you-up) first. It explains why the existing client cannot be used for this.
- Add a `minio_public_endpoint` setting to `app/config.py` with the default `localhost:19000`.
- In `app/storage.py`, create a second `Minio(...)` client with that endpoint and pass `region="us-east-1"`.
- With the region set, signing is pure computation. The container never connects to `localhost:19000`, which is good, because from inside the container that address does not reach MinIO.
- Use this client only for signing. Keep using the original `client` for everything that actually talks to MinIO.

</details>

### Step 4: Hand out upload URLs

Add `POST /albums/{album_id}/images`. It takes a filename and content type, saves a `pending` image row, and returns the image id and a presigned `PUT` URL.

**Check:** the `curl` upload below returns 200, the file appears in the MinIO console under `images/albums/<album_id>/`, and the row in Postgres is still `pending`.

```bash
curl -X PUT -H "Content-Type: image/png" --data-binary @photo.png "<upload_url>"
```

<details>
<summary>Hints</summary>

- Return 404 if the album does not exist and 415 if the content type does not start with `image/`.
- Generate the image id yourself with `uuid.uuid4()` before saving, because you need it to build the object key.
- Take only the extension from the client's filename: `PurePath(filename).suffix.lower()`.
- Sign with the public client: `presigned_put_object(bucket, object_key, expires=timedelta(minutes=10))`.
- Keep the quotes around the URL in `curl`. It contains `&`, which the shell would otherwise interpret.
- If the `PUT` returns `SignatureDoesNotMatch`, the URL was signed for a different host than the one you are calling. Go back to step 3.

</details>

### Step 5: Subscribe the bucket to upload events

Tell MinIO to send an event to the webhook target whenever an object is created in the bucket.

**Check:** repeat the upload from step 4 and watch the API logs. You see `POST /internal/minio-events` with a 404, which is correct for now: MinIO is calling, and the endpoint does not exist yet.

<details>
<summary>Hints</summary>

- Do this in `app/storage.py` right after the bucket is created, so it runs on every startup.
- The classes are in `minio.notificationconfig`:

  ```python
  client.set_bucket_notification(
      settings.minio_bucket,
      NotificationConfig(
          queue_config_list=[
              QueueConfig(
                  queue="arn:minio:sqs::PRIMARY:webhook",
                  events=["s3:ObjectCreated:*"],
                  config_id="uploads",
              )
          ]
      ),
  )
  ```

- Setting the same configuration again replaces it, so running this on every startup is safe.
- You can confirm the subscription in the MinIO console under the bucket's Events tab.

</details>

### Step 6: The webhook endpoint

Add `POST /internal/minio-events`. It checks the token, finds the image row for the uploaded object, and marks it `uploaded`.

**Check:** upload again. Within a second or two the row has status `uploaded`, a size, and an upload time. A `curl` to the endpoint without the token is rejected with 401.

<details>
<summary>Hints</summary>

- Add a `minio_webhook_token` setting to `app/config.py`. The value is already passed to the container as `MINIO_WEBHOOK_TOKEN`.
- Compare the `Authorization` header with `f"Bearer {settings.minio_webhook_token}"` and return 401 if it differs.
- Before writing any logic, print the request body once and upload a file. Seeing a real event makes the rest much easier.
- The event has a `Records` list. For each record, the object key is at `record["s3"]["object"]["key"]` and the size at `record["s3"]["object"]["size"]`.
- The key is URL-encoded. Decode it with `urllib.parse.unquote_plus(key)`.
- Look the row up by its `object_key` column instead of parsing ids out of the key. Add a unique constraint on that column.
- For idempotency: if the row is already `uploaded`, leave it alone and return 200.
- If no row matches, log it and still return 200.

</details>

### Step 7: List the album

Add `GET /albums/{album_id}/images` and `GET /albums/{album_id}/images/{image_id}`. Uploaded images include a URL the client can use to view the file.

**Check:** the listing shows your image as `uploaded`, and pasting its view URL into a browser shows the picture.

<details>
<summary>Hints</summary>

- Query with `db.scalars(select(Image).where(Image.album_id == album_id)).all()`.
- Create the view URL with `presigned_get_object(bucket, object_key, expires=timedelta(minutes=10))` on the public client.
- The URL is not a database column. Add it to the response schema as an optional field and fill it in only when the status is `uploaded`.
- For the single-image route, also check that the image belongs to the album in the path. Return 404 if it does not.

</details>

### Step 8: Prove it from a clean start

Run the whole flow on a fresh stack and write it up.

**Check:** everything in [Done when](#done-when) holds after `docker compose down -v` followed by `docker compose up -d --build`.

<details>
<summary>Hints</summary>

- A clean start is the only way to know that the tables, the bucket and the event subscription are all created by your code and not left over from earlier manual steps.
- To test a duplicate delivery, copy an event body from your logs and send it to the webhook yourself with `curl`, including the `Authorization` header.
- Put the `curl` commands for the full flow in the README as you run them.

</details>

## Things that will trip you up

- **Presigned URL host.** The API talks to MinIO at `minio:9000`, a name that only resolves inside Docker. A URL signed for that host is useless to a client on your machine, and you cannot just rewrite the host afterwards because the host is part of the signature. Sign with a client configured for the public address (`localhost:19000`). Give that client a fixed `region` so signing does not need a network call to an address the container cannot reach.
- **Missed events.** The webhook target has no queue directory, so MinIO does not store events for later delivery. An upload that completes while the API is down may never be reported.
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
