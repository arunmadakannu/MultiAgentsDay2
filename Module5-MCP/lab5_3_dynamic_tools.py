"""
Lab 5.3 - DYNAMIC TOOLING: India Tax Engine grows without a restart
===================================================================

This app is only the CLIENT. It keeps ONE open connection to tax_server.py.
When the Tax team publishes a new tool on the server (publish_tool.py), the
server sends the MCP notification "tools/list_changed" over that connection and
Microsoft Agent Framework reloads the tool list - this app does nothing.

    Terminal 1:  python tax_server.py                  (Tax team's server, 3 tools)
    Terminal 2:  python lab5_3_dynamic_tools.py        (this app, http://127.0.0.1:7873)
    Terminal 3:  python publish_tool.py calculate_tds  (Tax team publishes tool no. 4)

To reset the demo to 3 tools: restart tax_server.py and this app.
"""

import os
from datetime import datetime
from pathlib import Path

import gradio as gr
import httpx
from dotenv import load_dotenv
from azure.identity.aio import DefaultAzureCredential
from agent_framework import Agent, MCPStreamableHTTPTool
from agent_framework.foundry import FoundryChatClient

HERE = Path(__file__).parent
load_dotenv(HERE / ".env")

TAX_SERVER_URL = "http://127.0.0.1:8766/mcp"
QUESTION = "Calculate GST and TDS on a Rs 5,00,000 consulting invoice. What does the vendor finally receive?"

_credential = DefaultAzureCredential()
_tax_tools: MCPStreamableHTTPTool | None = None   # ONE long-lived connection to the server
_events: list[str] = []
_last_count = 0


def get_client() -> FoundryChatClient:
    return FoundryChatClient(
        project_endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
        model=os.environ.get("FOUNDRY_MODEL", "gpt-5.4-mini"),
        credential=_credential,
    )


def _log(text: str) -> None:
    _events.append(f"- `{datetime.now():%H:%M:%S}` {text}")


async def tax_tools() -> MCPStreamableHTTPTool:
    """Connect once and keep the connection open, so the server can push 'tools changed'."""
    global _tax_tools, _last_count
    if _tax_tools is None:
        tools = MCPStreamableHTTPTool(
            name="india_tax",
            url=TAX_SERVER_URL,
            # read=None: keep listening for server notifications however long the demo pauses
            # (the default gives up after 5 idle minutes)
            http_client=httpx.AsyncClient(timeout=httpx.Timeout(30, read=None)),
        )
        await tools.connect()
        _tax_tools = tools                       # only share it once it is connected
        _last_count = len(tools.functions)
        _log(f"🔌 Connected - agent sees {_last_count} tools")
    return _tax_tools


def tools_panel() -> str:
    """Draw the tool list the CLIENT currently holds in memory (no call to the server)."""
    global _last_count
    if _tax_tools is None:
        return "_Not connected yet - is `python tax_server.py` running?_"
    functions = _tax_tools.functions
    if len(functions) != _last_count:            # the notification already updated the list
        _log(f"🔔 Server said 'tools changed' → agent now sees **{_last_count} → {len(functions)}** tools")
        _last_count = len(functions)
    rows = "\n".join(f"| `{f.name}` | {f.description.splitlines()[0]} |" for f in functions)
    return (f"## 🧰 Tools the agent can see: **{len(functions)}**\n| Tool | What it does |\n|---|---|\n{rows}\n\n"
            "### 📜 Events\n" + "\n".join(_events))


async def connect():
    try:
        await tax_tools()
    except Exception as exc:
        return f"❌ Is `python tax_server.py` running?\n\n`{exc}`"
    return tools_panel()


async def ask(question: str):
    try:
        agent = Agent(
            client=get_client(),
            name="TaxAssistant",
            instructions="You are an India tax assistant. Use ONLY your tools for any tax calculation. "
                         "If you do not have a tool for something, say clearly: 'I do not have a tool for X yet.' "
                         "Show a small table with the amounts.",
            tools=[await tax_tools()],
        )
        response = await agent.run(question)
        used = [c.name for m in response.messages for c in m.contents if c.type == "function_call"]
        return response.text + f"\n\n---\n🔧 Tools used: `{used}`"
    except Exception as exc:
        return f"❌ Is `python tax_server.py` running?\n\n`{exc}`"


def build_ui() -> gr.Blocks:
    with gr.Blocks(title="Lab 5.3 · Dynamic tools") as demo:
        gr.Markdown("## Lab 5.3 · Dynamic tooling: the tax server grows without a restart\n"
                    "`🧮 Tax Assistant ══ one open MCP connection ══ 🌐 tax_server.py`\n\n"
                    "Publish a new tool from another terminal: `python publish_tool.py calculate_tds` "
                    "and watch the tool list change here - this app does nothing.")
        with gr.Row():
            with gr.Column():
                question = gr.Textbox(value=QUESTION, label="Question", lines=2)
                ask_btn = gr.Button("▶ Ask the Tax Assistant", variant="primary")
                answer = gr.Markdown()
            with gr.Column():
                panel = gr.Markdown()

        demo.load(connect, None, panel)                  # connect when the page opens
        gr.Timer(2).tick(tools_panel, None, panel)       # redraw the screen only - no server call
        ask_btn.click(ask, question, answer)
    return demo


if __name__ == "__main__":
    build_ui().launch(server_port=7873)
