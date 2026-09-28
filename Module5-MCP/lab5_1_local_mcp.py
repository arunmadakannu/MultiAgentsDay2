"""
Lab 5.1 - LOCAL MCP server: Accounts Payable Invoice Desk
=========================================================

The MCP server (vendor_po_server.py) runs LOCALLY: this app starts it as a child
process and talks to it over stdio. Sensitive ERP data never leaves the machine.

    Gradio app ──(starts, stdio)──► vendor_po_server.py  (3 tools)

    🧾 Invoice Checker  -> allowed: get_purchase_order, match_invoice_to_po
    🏢 Vendor Risk      -> allowed: get_vendor

Run
---
    python lab5_1_local_mcp.py        # opens http://127.0.0.1:7871
"""

import os
import sys
from pathlib import Path

import gradio as gr
from dotenv import load_dotenv
from azure.identity.aio import DefaultAzureCredential
from agent_framework import Agent, MCPStdioTool
from agent_framework.foundry import FoundryChatClient

HERE = Path(__file__).parent
load_dotenv(HERE / ".env")

SERVER_SCRIPT = str(HERE / "vendor_po_server.py")

SAMPLE_INVOICES = {
    "✅ INV-1001 · Acme · PO-5001 · $12,000": "Invoice INV-1001 from vendor V-100 for PO-5001, amount $12,000.",
    "⚠️ INV-1002 · Brightline · PO-5002 · $11,200": "Invoice INV-1002 from vendor V-200 for PO-5002, amount $11,200.",
    "❌ INV-1003 · QuickShip · PO-5003 · $48,000": "Invoice INV-1003 from vendor V-300 for PO-5003, amount $48,000.",
}

_credential = DefaultAzureCredential()


def get_client() -> FoundryChatClient:
    return FoundryChatClient(
        project_endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
        model=os.environ.get("FOUNDRY_MODEL", "gpt-5.4-mini"),
        credential=_credential,
    )


def local_server(allowed_tools: list[str]) -> MCPStdioTool:
    """Connect to the local MCP server. allowed_tools = the only tools this agent may use."""
    return MCPStdioTool(
        name="vendor_po",
        command=sys.executable,
        args=[SERVER_SCRIPT],
        allowed_tools=allowed_tools,
    )


def tool_calls(response) -> str:
    """List the MCP tool calls an agent made (name, arguments, result)."""
    lines = []
    for message in response.messages:
        for c in message.contents:
            if c.type == "function_call":
                lines.append(f"- 🔧 `{c.name}({c.arguments})`")
            elif c.type == "function_result":
                lines.append(f"  - ↩️ `{' '.join(str(c.result).split())}`")
    return "\n".join(lines) or "- (no tool calls)"


async def check_invoice(invoice: str):
    client = get_client()

    async with local_server(["get_purchase_order", "match_invoice_to_po"]) as checker_tools, \
               local_server(["get_vendor"]) as risk_tools:

        invoice_checker = Agent(
            client=client,
            name="InvoiceChecker",
            instructions="Check the invoice against its purchase order using your tools. "
                         "Reply in 2-3 lines: PO status, variance %, MATCH or MISMATCH.",
            tools=[checker_tools],
        )
        vendor_risk = Agent(
            client=client,
            name="VendorRisk",
            instructions="Check the vendor with get_vendor. A bank account changed in the last 30 days is a "
                         "fraud warning. Then give the FINAL decision: APPROVE only if the PO check is MATCH and "
                         "vendor risk is low or medium with no fraud warning, otherwise HOLD. "
                         "Format: **Decision:** APPROVE/HOLD, then 2 short reasons.",
            tools=[risk_tools],
        )

        check = await invoice_checker.run(invoice)
        decision = await vendor_risk.run(f"{invoice}\n\nInvoice Checker result:\n{check.text}")

        server_info = (
            "### 🖥️ Local MCP server\n"
            f"- Transport: **stdio** (child process of this app, no network port)\n"
            f"- 🧾 Invoice Checker sees: `{[f.name for f in checker_tools.functions]}`\n"
            f"- 🏢 Vendor Risk sees: `{[f.name for f in risk_tools.functions]}`\n\n"
            f"### 🔧 Tool calls\n**Invoice Checker**\n{tool_calls(check)}\n\n**Vendor Risk**\n{tool_calls(decision)}"
        )
        result = f"### 🧾 Invoice Checker\n{check.text}\n\n### 🏢 Vendor Risk (final decision)\n{decision.text}"
        return result, server_info


def build_ui() -> gr.Blocks:
    with gr.Blocks(title="Lab 5.1 · Local MCP") as demo:
        gr.Markdown("## Lab 5.1 · Local MCP server: Invoice Desk\n"
                    "`Gradio app ──(starts over stdio)──► vendor_po_server.py` · sensitive ERP data stays on this machine")
        with gr.Row():
            with gr.Column():
                sample = gr.Dropdown(list(SAMPLE_INVOICES), value=list(SAMPLE_INVOICES)[0], label="Pick an invoice")
                invoice = gr.Textbox(value=SAMPLE_INVOICES[list(SAMPLE_INVOICES)[0]], label="Invoice", lines=3)
                run_btn = gr.Button("▶ Check invoice", variant="primary")
                server_info = gr.Markdown()
            with gr.Column():
                result = gr.Markdown()

        sample.change(lambda k: SAMPLE_INVOICES[k], sample, invoice)
        run_btn.click(check_invoice, invoice, [result, server_info])
    return demo


if __name__ == "__main__":
    build_ui().launch(server_port=7871)
