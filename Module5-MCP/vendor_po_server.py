"""
LOCAL MCP server - Vendor & Purchase Order data (Accounts Payable).

Runs over stdio: the agent app starts this file as a child process on the SAME
machine and talks MCP through stdin/stdout. No port is opened, so nothing on the
network can reach it - the process boundary is the security boundary.

You do not start this file yourself. lab5_1_local_mcp.py starts it.
"""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("vendor-po-server")

# Local ERP extract (in real life: a SQL database on this machine)
VENDORS = {
    "V-100": {"name": "Acme Office Supplies", "risk": "low", "bank_account_changed_days_ago": 900},
    "V-200": {"name": "Brightline Logistics", "risk": "medium", "bank_account_changed_days_ago": 400},
    "V-300": {"name": "QuickShip Traders", "risk": "high", "bank_account_changed_days_ago": 3},
}
PURCHASE_ORDERS = {
    "PO-5001": {"vendor_id": "V-100", "amount": 12000.00, "status": "goods received"},
    "PO-5002": {"vendor_id": "V-200", "amount": 10000.00, "status": "goods received"},
    "PO-5003": {"vendor_id": "V-300", "amount": 48000.00, "status": "goods received"},
}
PRICE_TOLERANCE_PCT = 5.0


@mcp.tool()
def get_vendor(vendor_id: str) -> dict:
    """Get a vendor from the vendor master: name, risk rating and days since bank account change."""
    return VENDORS.get(vendor_id, {"error": f"Vendor {vendor_id} not found"})


@mcp.tool()
def get_purchase_order(po_number: str) -> dict:
    """Get a purchase order: vendor, approved amount and goods-receipt status."""
    return PURCHASE_ORDERS.get(po_number, {"error": f"PO {po_number} not found"})


@mcp.tool()
def match_invoice_to_po(po_number: str, invoice_amount: float) -> dict:
    """Compare an invoice amount with its purchase order. Within 5% = MATCH, otherwise MISMATCH."""
    po = PURCHASE_ORDERS.get(po_number)
    if not po:
        return {"error": f"PO {po_number} not found"}
    variance_pct = round((invoice_amount - po["amount"]) / po["amount"] * 100, 2)
    return {
        "po_amount": po["amount"],
        "invoice_amount": invoice_amount,
        "variance_pct": variance_pct,
        "result": "MATCH" if abs(variance_pct) <= PRICE_TOLERANCE_PCT else "MISMATCH",
    }


if __name__ == "__main__":
    mcp.run()  # stdio transport
