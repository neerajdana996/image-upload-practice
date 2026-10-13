# Testing the API with Postman

This guide sets up Postman for the task in [TASK.md](TASK.md) and walks through testing every endpoint. Add each request as you finish the matching step of the task.

The requests use the paths, field names and status codes that the task requires, so they work unchanged against a correct implementation.

## Quick start: import the ready-made collection

The `postman/` folder has everything below already built.

1. Install the Postman desktop app. The web version cannot reach `localhost` without extra setup.
2. Choose **Import** and select both files:
   - `postman/image-upload-practice.postman_collection.json`
   - `postman/local.postman_environment.json`
3. Select `local` in the environment dropdown at the top right.
4. Open the **Flow** folder and send the requests from top to bottom. For "Upload the file", go to the **Body** tab, choose **binary**, and select an image from your computer first.

The collection has three folders:

| Folder | What it covers |
| --- | --- |
| Flow | Create an album, request an upload URL, upload, then confirm the image is `uploaded` |
| Webhook | Calling the webhook by hand: duplicate event, no token, wrong token, unknown object |
| Error cases | 404, 415 and 422 responses |

Every request has tests, shown in the **Test Results** tab of the response. A request fails with 404 until you have built its endpoint, so expect red at the start and work towards all green.

The rest of this guide explains how the collection is put together, so you can build or change requests yourself.

## 1. Install and create a collection

1. Install the Postman desktop app. The web version cannot reach `localhost` without extra setup.
2. Create a collection named `Image Upload Practice`. All requests go in it.
3. Open the collection, go to the **Authorization** tab, and set the type to **No Auth**. The API has no login, and an inherited auth header would break the upload request later.

You can also import a starting set of requests straight from the API: **Import**, then paste `http://localhost:18000/openapi.json`. The routes appear as you build them.

## 2. Create an environment

An environment holds values that requests share, so you never copy ids by hand.

1. Go to **Environments**, create one named `local`.
2. Add these variables:

| Variable | Initial value | Filled by |
| --- | --- | --- |
| `base_url` | `http://localhost:18000` | you |
| `webhook_token` | `dev-webhook-token` | you |
| `album_id` | leave empty | the create-album request |
| `image_id` | leave empty | the upload-slot request |
| `upload_url` | leave empty | the upload-slot request |

3. Save, then select `local` in the environment dropdown at the top right. If no environment is selected, `{{base_url}}` stays as literal text and the request fails.

Use a variable anywhere by writing it in double braces, for example `{{base_url}}/albums`.

## 3. Headers

| Request | Headers you need |
| --- | --- |
| JSON requests to the API | `Content-Type: application/json`. Postman adds it for you when the body is **raw** with **JSON** selected. |
| File upload to the presigned URL | `Content-Type: image/png` (or whatever type you asked for). No `Authorization` header. |
| Webhook | `Authorization: Bearer {{webhook_token}}` and `Content-Type: application/json` |
| `GET` requests | none |

To see exactly what was sent, open the **Console** at the bottom left of Postman after a request. It shows the full request and response, including headers Postman added on its own.

## 4. The requests

Create these in order. Each one builds on the values saved by the one before.

### Create album

- **Method and URL:** `POST {{base_url}}/albums`
- **Body:** raw, JSON

  ```json
  {
    "name": "Holiday"
  }
  ```

- **Scripts, Post-response:**

  ```javascript
  pm.test("album created", () => pm.response.to.have.status(201));
  pm.environment.set("album_id", pm.response.json().id);
  ```

**Expect:** 201 and the new album. After sending, `album_id` in the environment has a value.

### Get album

- **Method and URL:** `GET {{base_url}}/albums/{{album_id}}`

**Expect:** 200 and the album. Change the id to a random UUID and you get 404.

### Request an upload URL

- **Method and URL:** `POST {{base_url}}/albums/{{album_id}}/images`
- **Body:** raw, JSON

  ```json
  {
    "filename": "photo.png",
    "content_type": "image/png"
  }
  ```

- **Scripts, Post-response:**

  ```javascript
  pm.test("upload slot created", () => pm.response.to.have.status(201));
  const body = pm.response.json();
  pm.environment.set("image_id", body.id);
  pm.environment.set("upload_url", body.upload_url);
  ```

**Expect:** 201 with an image id, status `pending`, and an upload URL starting with `http://localhost:19000/`. Change `content_type` to `text/plain` and you get 415.

### Upload the file

This request goes to MinIO, not to the API.

- **Method and URL:** `PUT {{upload_url}}`
- **Authorization tab:** No Auth
- **Headers:** `Content-Type: image/png`
- **Body:** **binary**, then choose an image file from your computer

**Expect:** 200 with an empty body. The file is now visible in the MinIO console at http://localhost:19001 under `images/albums/<album_id>/`.

If it fails:

| Response | Cause |
| --- | --- |
| `SignatureDoesNotMatch` | The URL was signed for a different host than `localhost:19000`. See step 3 of the task. |
| `AccessDenied`, request has expired | The URL is older than its expiry. Send "Request an upload URL" again. |
| An error about multiple authentication types | An `Authorization` header was sent. Set this request to No Auth. |
| Could not send request | `upload_url` is empty. Check that the previous request's script ran and the `local` environment is selected. |

### Check the image status

- **Method and URL:** `GET {{base_url}}/albums/{{album_id}}/images/{{image_id}}`
- **Scripts, Post-response:**

  ```javascript
  pm.test("image is uploaded", () => {
      pm.expect(pm.response.json().status).to.eql("uploaded");
  });
  ```

**Expect:** 200, status `uploaded`, a size, and a view URL. This is the proof that MinIO notified the API. If the status is still `pending`, check the API logs for a `POST /internal/minio-events` line.

### List album images

- **Method and URL:** `GET {{base_url}}/albums/{{album_id}}/images`

**Expect:** 200 and a list containing your image. Copy its view URL into a browser to see the picture.

### Call the webhook yourself

MinIO normally sends this request. Sending it by hand lets you test the token check and what happens when the same event arrives twice.

- **Method and URL:** `POST {{base_url}}/internal/minio-events`
- **Headers:** `Authorization: Bearer {{webhook_token}}`
- **Body:** raw, JSON

  ```json
  {
    "EventName": "s3:ObjectCreated:Put",
    "Key": "images/albums/{{album_id}}/{{image_id}}.png",
    "Records": [
      {
        "eventName": "s3:ObjectCreated:Put",
        "s3": {
          "bucket": { "name": "images" },
          "object": {
            "key": "albums%2F{{album_id}}%2F{{image_id}}.png",
            "size": 12345,
            "contentType": "image/png"
          }
        }
      }
    ]
  }
  ```

Try these cases:

| Case | Change | Expect |
| --- | --- | --- |
| Duplicate event | Send it as is, for an image already uploaded | 200, and the row is unchanged |
| No token | Untick the `Authorization` header | 401 |
| Wrong token | Change the header to `Bearer wrong` | 401 |
| Unknown object | Change the key to an id that does not exist | 200, and a log line in the API |

This body is a cut-down version of a real event. To get a full one, print the request body in your endpoint and upload a file.

## 5. Run the whole flow

1. Open the collection and choose **Run**.
2. Untick "Upload the file". The collection runner often cannot read local files for binary bodies, so do that one by hand.
3. Run "Create album" and "Request an upload URL", send "Upload the file" yourself, then run the two `GET` requests.

Every request with a test script shows a pass or fail in the results.
