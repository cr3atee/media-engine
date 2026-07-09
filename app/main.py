from fastapi import FastAPI

from app.core.logging import setup_logging


setup_logging()

app = FastAPI()


@app.get("/")
async def root() -> dict[str, str]:
    return {"status": "ok"}
