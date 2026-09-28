"""
Lab 5.2 - REMOTE MCP server: Treasury FX Service
================================================

The MCP server (fx_server.py) runs ON ITS OWN as a web service. Any app in the
company can use it over HTTP - if it sends the right API key.

    💸 Payments agent (this app)  ──HTTP + x-api-key──►  🌐 fx_server.py  ──► live ECB rates
    🔍 Inspector (2nd client)     ──HTTP + x-api-key──►        (same server)

Run
---
    python fx_server.py               # terminal 1 - leave it running
    python lab5_2_remote_mcp.py       # terminal 2 - opens http://127.0.0.1:7872
"""

import os
from pathlib import Path

import gradio as gr
import httpx
from dotenv import load_dotenv
from azure.identity.aio import DefaultAzureCredential
from agent_framework import Agent, MCPStreamableHTTPTool
from agent_framework.foundry import FoundryChatClient

HERE = Path(__file__).parent
load_dotenv(HERE / ".env")

FX_SERVER_URL = "http://127.0.0.1:8765/mcp"
API_KEY = os.environ["FX_SERVER_API_KEY"]   # secret from .env - never in the code

QUESTION = ("We must pay a EUR 250,000 supplier invoice today from India Procurement. "
            "What is it in USD, and is it within our daily FX limit?")

_credential = DefaultAzureCredential()


def get_client() -> FoundryChatClient:
    return FoundryChatClient(
        project_endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
        model=os.environ.get("FOUNDRY_MODEL", "gpt-5.4-mini"),
        credential=_credential,
    )


def remote_server(client_name: str, api_key: str | None, allowed_tools: list[str] | None = None):
    """Connect to the remote MCP server over HTTP, sending the API key and our app's name."""
    headers = {"x-client-name": client_name}
    if api_key:
        headers["x-api-key"] = api_key
    return MCPStreamableHTTPTool(
        name="treasury_fx",
        url=FX_SERVER_URL,
        http_client=httpx.AsyncClient(headers=headers, timeout=30),
        allowed_tools=allowed_tools,
    )


def tool_calls(response) -> str:
    lines = []
    for message in response.messages:
        for c in message.contents:
            if c.type == "function_call":
                lines.append(f"- 🔧 `{c.name}({c.arguments})`")
            elif c.type == "function_result":
                lines.append(f"  - ↩️ `{' '.join(str(c.result).split())}`")
    return "\n".join(lines) or "- (no tool calls)"


async def ask_payments_agent(question: str):
    try:
        async with remote_server("payments-agent-app", API_KEY, ["convert_amount", "check_fx_limit"]) as fx:
            agent = Agent(
                client=get_client(),
                name="PaymentsAgent",
                instructions="You help the payments team. Use your tools to convert amounts to USD and check "
                             "the daily FX limit. Answer in 3 short lines: USD amount, rate used, within limit yes/no.",
                tools=[fx],
            )
            response = await agent.run(question)
            return response.text, f"### 🔧 Tool calls sent to the remote server\n{tool_calls(response)}"
    except Exception as exc:
        return f"❌ Could not reach the server - is `python fx_server.py` running?\n\n`{exc}`", ""


async def inspector_list_tools():
    """A second, different client using the same server: list every tool it offers."""
    try:
        async with remote_server("mcp-inspector", API_KEY) as fx:
            rows = "\n".join(f"| `{f.name}` | {f.description} |" for f in fx.functions)
            return f"### 🔍 Tools on the remote server\n| Tool | Description |\n|---|---|\n{rows}"
    except Exception as exc:
        return f"❌ Could not reach the server - is `python fx_server.py` running?\n\n`{exc}`"


async def call_without_key():
    """Same server, no API key: the server must refuse."""
    try:
        async with remote_server("unknown-app", api_key=None) as fx:
            return f"⚠️ Connected without a key - this should not happen. Tools: {[f.name for f in fx.functions]}"
    except Exception as exc:
        return f"### 🚫 Refused without an API key\nThe server answered **401 Unauthorized**.\n\n`{type(exc).__name__}`"


def build_ui() -> gr.Blocks:
    with gr.Blocks(title="Lab 5.2 · Remote MCP") as demo:
        gr.Markdown("## Lab 5.2 · Remote MCP server: Treasury FX Service\n"
                    "`💸 Payments agent ──HTTP + API key──► 🌐 fx_server.py (runs on its own, shared by many apps)`\n\n"
                    "Start the server first in its own terminal: `python fx_server.py` and watch its log.")
        with gr.Row():
            with gr.Column():
                question = gr.Textbox(value=QUESTION, label="Question for the Payments agent", lines=3)
                ask_btn = gr.Button("▶ Ask the Payments agent", variant="primary")
                answer = gr.Markdown()
                calls = gr.Markdown()
            with gr.Column():
                inspect_btn = gr.Button("🔍 2nd client: list server tools")
                no_key_btn = gr.Button("🚫 Call the server WITHOUT an API key")
                side = gr.Markdown()

        ask_btn.click(ask_payments_agent, question, [answer, calls])
        inspect_btn.click(inspector_list_tools, None, side)
        no_key_btn.click(call_without_key, None, side)
    return demo


if __name__ == "__main__":
    build_ui().launch(server_port=7872)
