import os
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse

APP_VERSION = "2.0.0"

DUOSUP_API_KEY = os.getenv("DUOSUP_API_KEY", "").strip()
UPSTREAM_API_KEY = os.getenv("UPSTREAM_API_KEY", "").strip()
UPSTREAM_URL = os.getenv(
    "UPSTREAM_URL",
    "https://api.parse.bot/scraper/78cf8155-3819-45d0-b799-92f840a94827/get_stock",
).strip()
UPSTREAM_TIMEOUT = float(os.getenv("UPSTREAM_TIMEOUT", "20"))

app = FastAPI(
    title="DuoSup Blox Fruits API",
    version=APP_VERSION,
    description="Private gateway from DuoSup to the Parse Blox Fruits Wiki stock API.",
)


def check_private_key(x_api_key: str | None) -> None:
    if not DUOSUP_API_KEY:
        raise HTTPException(status_code=500, detail="DUOSUP_API_KEY is not configured.")
    if x_api_key != DUOSUP_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key.")


def normalize_stock(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail="Upstream returned invalid JSON.")

    if payload.get("status") not in (None, "success"):
        return payload

    data = payload.get("data")
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="Upstream response has no data object.")

    return {
        "status": "success",
        "data": {
            "normal": data.get("normal") or [],
            "mirage": data.get("mirage") or [],
            "previous_normal": data.get("previous_normal") or [],
            "previous_mirage": data.get("previous_mirage") or [],
            "normal_resets_at": data.get("normal_resets_at"),
            "mirage_resets_at": data.get("mirage_resets_at"),
            "normal_resets_at_epoch": data.get("normal_resets_at_epoch"),
            "mirage_resets_at_epoch": data.get("mirage_resets_at_epoch"),
        },
    }


async def fetch_upstream_stock() -> dict[str, Any]:
    if not UPSTREAM_API_KEY:
        raise HTTPException(status_code=500, detail="UPSTREAM_API_KEY is not configured.")

    try:
        async with httpx.AsyncClient(timeout=UPSTREAM_TIMEOUT) as client:
            response = await client.get(
                UPSTREAM_URL,
                headers={"X-API-Key": UPSTREAM_API_KEY, "Accept": "application/json"},
            )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Upstream API timeout.")
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Upstream request failed: {exc}")

    if response.status_code in (401, 403):
        raise HTTPException(
            status_code=502,
            detail=f"Upstream authentication/access failed ({response.status_code}).",
        )
    if response.status_code == 429:
        raise HTTPException(status_code=502, detail="Upstream rate limit reached.")
    if response.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail=f"Upstream HTTP {response.status_code}: {response.text[:500]}",
        )

    try:
        payload = response.json()
    except ValueError:
        raise HTTPException(status_code=502, detail="Upstream returned non-JSON data.")

    return normalize_stock(payload)


@app.get("/")
async def root() -> dict[str, Any]:
    return {
        "service": "duosup-bloxfruits-api",
        "version": APP_VERSION,
        "status": "ok",
        "endpoints": {"health": "/health", "stock": "/stock", "docs": "/docs"},
    }


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "service": "duosup-bloxfruits-api", "version": APP_VERSION}


@app.get("/stock")
async def stock(x_api_key: str | None = Header(default=None)) -> JSONResponse:
    check_private_key(x_api_key)
    return JSONResponse(content=await fetch_upstream_stock())


@app.get("/api/stock")
async def api_stock(x_api_key: str | None = Header(default=None)) -> JSONResponse:
    check_private_key(x_api_key)
    return JSONResponse(content=await fetch_upstream_stock())
