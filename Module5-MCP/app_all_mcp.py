"""
Module 5 - all three MCP demos in ONE Gradio app (one tab per lab).

Run
---
    python fx_server.py        # terminal 1 (for Lab 5.2)
    python tax_server.py       # terminal 2 (for Lab 5.3)
    python app_all_mcp.py      # terminal 3 - opens http://127.0.0.1:7870
Lab 5.1 needs no terminal: the app starts its local server itself.
Lab 5.3: publish the new tool from another terminal: python publish_tool.py calculate_tds
"""

import gradio as gr

import lab5_1_local_mcp as lab1
import lab5_2_remote_mcp as lab2
import lab5_3_dynamic_tools as lab3

OVERVIEW = """
## Module 5 · MCP in an Enterprise Setting

| # | Demo | Use case | Where the MCP server runs |
|---|---|---|---|
| 5.1 | **Local MCP server** | Accounts Payable invoice desk | Started by the app itself, over **stdio** - sensitive data never leaves the machine |
| 5.2 | **Remote MCP server** | Treasury FX service | Its own web service (**HTTP + API key**), shared by many apps |
| 5.3 | **Dynamic tooling** | India tax engine | Remote server that goes from **3 → 4 tools** while running - no restart |

| Local server | Remote server |
|---|---|
| Sensitive data on the same machine | Shared tools used by many teams |
| No network, no login - the process boundary is the security | Needs authentication (API key / Entra ID) |
| One app uses it | Many apps use it, managed centrally |
"""


def build_app() -> gr.Blocks:
    with gr.Blocks(title="Module 5 · MCP") as app:
        with gr.Tab("🏠 Overview"):
            gr.Markdown(OVERVIEW)
        with gr.Tab("5.1 Local MCP"):
            lab1.build_ui()  # created inside the tab, so Gradio renders it here
        with gr.Tab("5.2 Remote MCP"):
            lab2.build_ui()
        with gr.Tab("5.3 Dynamic tools"):
            lab3.build_ui()
    return app


if __name__ == "__main__":
    build_app().launch(server_port=7870)
