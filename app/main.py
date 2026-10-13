from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.storage import ensure_bucket


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_bucket()
    yield


app = FastAPI(title="Image Upload Practice", lifespan=lifespan)
