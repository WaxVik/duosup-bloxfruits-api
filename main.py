import os
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse

APP_NAME = "DuoSup Blox Fruits API"
APP_VERSION = "1.0.0"

# ==========================================
# OUR PRIVATE API KEY
# ==========================================

DUOSUP_API_KEY = os.getenv("DUOSUP_API_KEY", "")

# ==========================================
# UPSTREAM STOCK PROVIDER
# ==========================================

UPSTREAM_URL = os.getenv(
    "UPSTREAM_URL",
    "https://api.parse.bot/scraper/e534d388-6640-4c19-b9b6-b2ba12930793/get_stock",
)

UPSTREAM_API_KEY = os.getenv("UPSTREAM_API_KEY", "")

UPSTREAM_TIMEOUT = float(
    os.getenv("UPSTREAM_TIMEOUT", "20")
)

# ==========================================
# FASTAPI
# ==========================================

app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    description="Private Blox Fruits Stock API for DuoSup",
)


# ==========================================
# AUTHENTICATION
# ==========================================

def require_api_key(
    x_api_key: str | None = Header(default=None),
) -> None:

    if not DUOSUP_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="DUOSUP_API_KEY is not configured.",
        )

    if x_api_key != DUOSUP_API_KEY:
        raise HTTPException(
            status_code=401,
            detail="Invalid API key.",
        )


# ==========================================
# HELPERS
# ==========================================

def pick(
    obj: dict[str, Any],
    *names: str,
    default=None,
):
    for name in names:
        if name in obj and obj[name] is not None:
            return obj[name]

    return default


def normalize_fruit(item: Any) -> dict[str, Any]:

    # If provider returns only a name
    if isinstance(item, str):

        return {
            "name": item,
            "type": None,
            "money_price": None,
            "robux_price": None,
            "image_url": None,
        }

    # Unknown format
    if not isinstance(item, dict):

        return {
            "name": str(item),
            "type": None,
            "money_price": None,
            "robux_price": None,
            "image_url": None,
        }

    return {
        "name": pick(
            item,
            "name",
            "fruit",
            "title",
            default="Unknown",
        ),

        "type": pick(
            item,
            "type",
            "classification",
            default=None,
        ),

        "money_price": pick(
            item,
            "money_price",
            "beli_price",
            "price_beli",
            "price",
            default=None,
        ),

        "robux_price": pick(
            item,
            "robux_price",
            "price_robux",
            "robux",
            default=None,
        ),

        "image_url": pick(
            item,
            "image_url",
            "image",
            default=None,
        ),
    }


def extract_data(payload: Any) -> dict[str, Any]:

    # Some providers return:
    #
    # {
    #   "data": {...}
    # }

    if (
        isinstance(payload, dict)
        and isinstance(payload.get("data"), dict)
    ):
        return payload["data"]

    # Others return the object directly.

    if isinstance(payload, dict):
        return payload

    raise ValueError(
        "Unexpected upstream JSON format."
    )


# ==========================================
# UPSTREAM REQUEST
# ==========================================

async def fetch_upstream() -> dict[str, Any]:

    if not UPSTREAM_API_KEY:

        raise HTTPException(
            status_code=503,
            detail="UPSTREAM_API_KEY is not configured.",
        )

    headers = {
        "X-API-Key": UPSTREAM_API_KEY,
        "Accept": "application/json",
        "User-Agent": (
            "DuoSup-BloxFruits-API/1.0"
        ),
    }

    try:

        async with httpx.AsyncClient(
            timeout=UPSTREAM_TIMEOUT,
            follow_redirects=True,
        ) as client:

            response = await client.post(
                UPSTREAM_URL,
                headers=headers,
                json={},
            )

            response.raise_for_status()

            return response.json()

    except httpx.HTTPStatusError as exc:

        raise HTTPException(
            status_code=502,
            detail=(
                "Upstream stock provider returned "
                f"HTTP {exc.response.status_code}."
            ),
        ) from exc

    except httpx.RequestError as exc:

        raise HTTPException(
            status_code=502,
            detail=(
                "Could not connect to stock provider: "
                f"{exc}"
            ),
        ) from exc

    except ValueError as exc:

        raise HTTPException(
            status_code=502,
            detail=(
                "Stock provider returned invalid JSON."
            ),
        ) from exc


# ==========================================
# NORMALIZE STOCK
# ==========================================

def normalize_stock(
    payload: Any,
) -> dict[str, Any]:

    data = extract_data(payload)

    normal_raw = data.get(
        "normal",
        data.get(
            "normal_now",
            data.get(
                "normal_dealer",
                [],
            ),
        ),
    )

    mirage_raw = data.get(
        "mirage",
        data.get(
            "mirage_now",
            data.get(
                "mirage_dealer",
                [],
            ),
        ),
    )

    normal = [
        normalize_fruit(fruit)
        for fruit in (normal_raw or [])
    ]

    mirage = [
        normalize_fruit(fruit)
        for fruit in (mirage_raw or [])
    ]

    return {

        "status": True,

        "normal": normal,

        "mirage": mirage,

        "normal_resets_at": pick(
            data,
            "normal_resets_at",
            "normal_reset_at",
            default=None,
        ),

        "mirage_resets_at": pick(
            data,
            "mirage_resets_at",
            "mirage_reset_at",
            default=None,
        ),

        "normal_resets_at_epoch": pick(
            data,
            "normal_resets_at_epoch",
            "normal_reset_at_epoch",
            default=None,
        ),

        "mirage_resets_at_epoch": pick(
            data,
            "mirage_resets_at_epoch",
            "mirage_reset_at_epoch",
            default=None,
        ),

        "fetched_at": datetime.now(
            timezone.utc
        ).isoformat(),

        "source": (
            "managed Blox Fruits "
            "stock provider"
        ),
    }


# ==========================================
# PUBLIC ROUTES
# ==========================================

@app.get("/")
async def root():

    return {
        "name": APP_NAME,
        "version": APP_VERSION,
        "status": "online",
        "docs": "/docs",
        "health": "/health",
        "stock": "/info/stock",
    }


@app.get("/health")
async def health():

    return {
        "status": "ok",
        "time": datetime.now(
            timezone.utc
        ).isoformat(),
    }


# ==========================================
# PROTECTED STOCK ROUTES
# ==========================================

@app.get("/info/stock")
async def stock(
    _: None = Depends(require_api_key),
):

    upstream_data = await fetch_upstream()

    return normalize_stock(
        upstream_data
    )


@app.get("/info/stock/raw")
async def stock_raw(
    _: None = Depends(require_api_key),
):

    return JSONResponse(
        content=await fetch_upstream()
    )


@app.get("/info/config")
async def config(
    _: None = Depends(require_api_key),
):

    return {

        "app": APP_NAME,

        "version": APP_VERSION,

        "upstream_configured": bool(
            UPSTREAM_API_KEY
        ),

        "upstream_url": UPSTREAM_URL,

    }


# ==========================================
# LOCAL START
# ==========================================

if __name__ == "__main__":

    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(
            os.getenv(
                "PORT",
                "8000",
            )
        ),
    )
