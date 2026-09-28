"""
REMOTE MCP server - Treasury FX Service.

Runs on its own as a web service (Streamable HTTP) that many apps can share:
    http://127.0.0.1:8765/mcp

- Every request must send the header  x-api-key: <FX_SERVER_API_KEY from .env>
- Every request is logged with the caller's name (header x-client-name)
- Rates are LIVE: European Central Bank rates from api.frankfurter.dev

Start it in its own terminal and leave it running:
    python fx_server.py
"""

import os
from datetime import datetime
from pathlib import Path

import httpx
import uvicorn
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from starlette.responses import PlainTextResponse

load_dotenv(Path(__file__).parent / ".env")
API_KEY = os.environ["FX_SERVER_API_KEY"]

mcp = FastMCP("treasury-fx-server", log_level="WARNING")  # keep the console for our own request log

# Daily FX limits per business unit (USD) and what was already used today
DAILY_FX_LIMITS = {
    "India Procurement": {"limit_usd": 250_000, "used_today_usd": 40_000},
    "US Operations": {"limit_usd": 1_000_000, "used_today_usd": 300_000},
}


def _rate(from_currency: str, to_currency: str) -> float:
    reply = httpx.get("https://api.frankfurter.dev/v1/latest",
                      params={"base": from_currency.upper(), "symbols": to_currency.upper()}, timeout=10)
    reply.raise_for_status()
    return reply.json()["rates"][to_currency.upper()]


@mcp.tool()
def get_fx_rate(from_currency: str, to_currency: str) -> dict:
    """Get today's official ECB exchange rate, e.g. EUR -> USD."""
    return {"from": from_currency, "to": to_currency, "rate": _rate(from_currency, to_currency)}


@mcp.tool()
def convert_amount(amount: float, from_currency: str, to_currency: str) -> dict:
    """Convert an amount between currencies at today's official ECB rate."""
    rate = _rate(from_currency, to_currency)
    return {"amount": amount, "from": from_currency, "rate": rate,
            "converted": round(amount * rate, 2), "to": to_currency}


@mcp.tool()
def check_fx_limit(business_unit: str, amount_usd: float) -> dict:
    """Check if a payment in USD fits in the business unit's remaining daily FX limit."""
    bu = DAILY_FX_LIMITS.get(business_unit)
    if not bu:
        return {"error": f"Unknown business unit. Known: {list(DAILY_FX_LIMITS)}"}
    remaining = bu["limit_usd"] - bu["used_today_usd"]
    return {"business_unit": business_unit, "remaining_today_usd": remaining,
            "requested_usd": amount_usd, "within_limit": amount_usd <= remaining}


class RequireApiKey:
    """Tiny ASGI middleware: reject requests without the right API key, log the rest."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope["headers"])
            caller = headers.get(b"x-client-name", b"unknown").decode()
            if headers.get(b"x-api-key", b"").decode() != API_KEY:
                print(f"{datetime.now():%H:%M:%S}  ❌ 401 rejected  caller={caller}")
                await PlainTextResponse("Unauthorized: missing or wrong x-api-key", status_code=401)(scope, receive, send)
                return
            print(f"{datetime.now():%H:%M:%S}  ✅ {scope['method']:<6} caller={caller}")
        await self.app(scope, receive, send)


if __name__ == "__main__":
    print("Treasury FX MCP server on http://127.0.0.1:8765/mcp  (Ctrl+C to stop)")
    uvicorn.run(RequireApiKey(mcp.streamable_http_app()), host="127.0.0.1", port=8765, log_level="warning")
