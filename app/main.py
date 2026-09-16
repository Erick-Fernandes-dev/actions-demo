"""API mínima para demonstrar o ciclo de vida de uma aplicação no GitHub Actions."""
import os

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

APP_VERSION = os.getenv("APP_VERSION", "dev")

app = FastAPI(title="Actions Demo API", version=APP_VERSION)


class Item(BaseModel):
    name: str
    price: float


_db: dict[int, Item] = {}


@app.get("/health")
def health() -> dict:
    """Usado pelo HEALTHCHECK do Docker, readinessProbe do k8s e smoke test do pipeline."""
    return {"status": "ok", "version": APP_VERSION}


@app.get("/items")
def list_items() -> dict[int, Item]:
    return _db


@app.post("/items", status_code=201)
def create_item(item: Item) -> dict:
    if item.price < 0:
        raise HTTPException(status_code=422, detail="price must be >= 0")
    item_id = len(_db) + 1
    _db[item_id] = item
    return {"id": item_id, **item.model_dump()}


@app.get("/items/{item_id}")
def get_item(item_id: int) -> Item:
    if item_id not in _db:
        raise HTTPException(status_code=404, detail="item not found")
    return _db[item_id]
