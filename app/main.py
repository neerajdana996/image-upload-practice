import io
import uuid
from contextlib import asynccontextmanager
from pathlib import PurePath

from fastapi import Depends, FastAPI, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import Base, engine, get_db
from app.models import Image
from app.schemas import ImageOut
from app.storage import client as minio, ensure_bucket

MAX_UPLOAD_BYTES = settings.max_upload_mb * 1024 * 1024


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    ensure_bucket()
    yield


app = FastAPI(title="Image Upload Practice", lifespan=lifespan)


@app.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    minio.bucket_exists(settings.minio_bucket)
    return {"status": "ok"}


@app.post("/images", response_model=ImageOut, status_code=status.HTTP_201_CREATED)
def upload_image(file: UploadFile, db: Session = Depends(get_db)):
    content_type = file.content_type or ""
    if not content_type.startswith("image/"):
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Only image uploads are allowed"
        )

    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"File exceeds {settings.max_upload_mb} MB limit",
        )
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty file")

    image_id = uuid.uuid4()
    filename = PurePath(file.filename or "upload").name
    object_key = f"{image_id}{PurePath(filename).suffix.lower()}"

    minio.put_object(
        settings.minio_bucket,
        object_key,
        io.BytesIO(data),
        length=len(data),
        content_type=content_type,
    )

    image = Image(
        id=image_id,
        filename=filename,
        content_type=content_type,
        size=len(data),
        object_key=object_key,
    )
    db.add(image)
    try:
        db.commit()
    except Exception:
        minio.remove_object(settings.minio_bucket, object_key)
        raise
    return image


@app.get("/images", response_model=list[ImageOut])
def list_images(limit: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    stmt = select(Image).order_by(Image.created_at.desc()).limit(limit).offset(offset)
    return db.scalars(stmt).all()


def _get_image(image_id: uuid.UUID, db: Session) -> Image:
    image = db.get(Image, image_id)
    if image is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Image not found")
    return image


@app.get("/images/{image_id}", response_model=ImageOut)
def get_image(image_id: uuid.UUID, db: Session = Depends(get_db)):
    return _get_image(image_id, db)


@app.get("/images/{image_id}/file")
def download_image(image_id: uuid.UUID, db: Session = Depends(get_db)):
    image = _get_image(image_id, db)
    obj = minio.get_object(settings.minio_bucket, image.object_key)

    def stream():
        try:
            yield from obj.stream(64 * 1024)
        finally:
            obj.close()
            obj.release_conn()

    return StreamingResponse(
        stream(),
        media_type=image.content_type,
        headers={"Content-Length": str(image.size)},
    )


@app.delete("/images/{image_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_image(image_id: uuid.UUID, db: Session = Depends(get_db)):
    image = _get_image(image_id, db)
    minio.remove_object(settings.minio_bucket, image.object_key)
    db.delete(image)
    db.commit()
