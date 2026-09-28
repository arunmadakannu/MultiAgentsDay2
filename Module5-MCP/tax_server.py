"""
DYNAMIC MCP server - India Tax Engine that grows WITHOUT a restart.

Starts with 3 tools. The Tax team runs  python publish_tool.py calculate_tds ,
which calls POST /admin/publish/calculate_tds on THIS server. The server loads
new_tools/calculate_tds.py while it keeps running, then sends the standard MCP
notification "notifications/tools/list_changed" to every connected client.
Microsoft Agent Framework listens for it and reloads the tool list.

Start it in its own terminal and leave it running:
    python tax_server.py              # http://127.0.0.1:8766/mcp
To reset the demo to 3 tools, restart this server.
"""

import importlib.util
import re
from pathlib import Path

import uvicorn
from mcp.server.fastmcp import FastMCP
from starlette.responses import JSONResponse

NEW_TOOLS = Path(__file__).parent / "new_tools"

mcp = FastMCP("india-tax-server", log_level="WARNING")

GST_RATES = {"consulting": 18, "software": 18, "restaurant": 5, "gold": 3, "books": 0}


@mcp.tool()
def get_gst_rate(category: str) -> dict:
    """Get the GST rate (%) for a category: consulting, software, restaurant, gold, books."""
    rate = GST_RATES.get(category.lower())
    return {"category": category, "gst_rate_pct": rate} if rate is not None else {"error": f"Known: {list(GST_RATES)}"}


@mcp.tool()
def calculate_gst(amount_inr: float, category: str) -> dict:
    """Calculate GST on an amount in INR for a category, and the total invoice value."""
    rate = GST_RATES.get(category.lower())
    if rate is None:
        return {"error": f"Known categories: {list(GST_RATES)}"}
    gst = round(amount_inr * rate / 100, 2)
    return {"amount_inr": amount_inr, "gst_rate_pct": rate, "gst_inr": gst, "total_inr": amount_inr + gst}


@mcp.tool()
def validate_gstin(gstin: str) -> dict:
    """Check that a GSTIN (Indian GST registration number) has the correct 15-character format."""
    valid = bool(re.fullmatch(r"\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]", gstin.upper()))
    return {"gstin": gstin, "valid_format": valid, "state_code": gstin[:2] if valid else None}


# --- Dynamic tooling ---------------------------------------------------------
CONNECTED_CLIENTS = set()   # MCP sessions to notify when the tool list changes


@mcp._mcp_server.list_tools()
async def list_tools_and_remember_client():
    """Same tool list as usual - but remember who asked, so we can notify them later."""
    CONNECTED_CLIENTS.add(mcp._mcp_server.request_context.session)
    return await mcp.list_tools()


async def tell_clients_tools_changed() -> None:
    for session in list(CONNECTED_CLIENTS):
        try:
            await session.send_tool_list_changed()   # MCP: notifications/tools/list_changed
        except Exception:
            CONNECTED_CLIENTS.discard(session)       # that client has disconnected


@mcp.custom_route("/admin/publish/{tool_name}", methods=["POST"])
async def publish_tool(request):
    """Load new_tools/<tool_name>.py and add its function as a new MCP tool - no restart."""
    name = request.path_params["tool_name"]
    spec = importlib.util.spec_from_file_location(name, NEW_TOOLS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    mcp.add_tool(getattr(module, name))
    await tell_clients_tools_changed()
    tools = [t.name for t in await mcp.list_tools()]
    print(f"🚀 Published '{name}' -> server now has {len(tools)} tools: {tools}")
    return JSONResponse({"tools": tools})


if __name__ == "__main__":
    print("India Tax MCP server on http://127.0.0.1:8766/mcp  (Ctrl+C to stop)")
    uvicorn.run(mcp.streamable_http_app(), host="127.0.0.1", port=8766, log_level="warning")
