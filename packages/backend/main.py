from pathlib import Path
import logging
import os

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

# Initialize logging configuration based on LOG_LEVEL or DEBUG env vars
log_level_str = os.environ.get("LOG_LEVEL", "DEBUG" if os.environ.get("DEBUG") else "INFO").upper()
log_level = getattr(logging, log_level_str, logging.INFO)

logging.basicConfig(
    level=log_level,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

import re
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database import init_db
from routers import files, chat, artifacts, geocode, streetview, wms, gee, scenarios, rag
from tools import http as http_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield
    await http_client.aclose()


app = FastAPI(title="Disha API", lifespan=lifespan)

from fastapi import Request
from tools.google import google_maps_key_var

@app.middleware("http")
async def extract_google_maps_key(request: Request, call_next):
    key = request.headers.get("x-google-maps-key", "")
    if not key:
        key = request.query_params.get("google_maps_api_key", "")
    token = google_maps_key_var.set(key)
    try:
        response = await call_next(request)
        return response
    finally:
        google_maps_key_var.reset(token)

# Allow only loopback origins. The renderer runs as a file:// or
# http://localhost:* and the Electron preload bridges all other channels.
# Wide-open CORS would let any browser tab on the user's machine hit the
# backend.
_LOOPBACK_RE = re.compile(r"^(file://|app://|https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?)$")

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=_LOOPBACK_RE.pattern,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(files.router, prefix="/api/files", tags=["files"])
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(artifacts.router, prefix="/api/artifacts", tags=["artifacts"])
app.include_router(geocode.router, prefix="/api/geocode", tags=["geocode"])
app.include_router(streetview.router, prefix="/api/streetview", tags=["streetview"])
app.include_router(wms.router, prefix="/api/wms", tags=["wms"])
app.include_router(gee.router, prefix="/api/gee", tags=["gee"])
app.include_router(scenarios.router, prefix="/api/scenarios", tags=["scenarios"])
app.include_router(rag.router, prefix="/api/rag", tags=["rag"])


@app.get("/health")
async def health():
    return {"status": "ok"}
