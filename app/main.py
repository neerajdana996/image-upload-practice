from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import check_connection
from app.storage import ensure_bucket


@asynccontextmanager
async def lifespan(app: FastAPI):
    check_connection()
    ensure_bucket()
    yield


app = FastAPI(title="Image Upload Practice", lifespan=lifespan)
