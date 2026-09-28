"""
Tax team's admin script: publish a new tool to the RUNNING tax server.

The agent app is not involved at all. The server loads the tool and notifies
every connected client ("notifications/tools/list_changed").

Run (in a third terminal, while tax_server.py and the agent app are running):
    python publish_tool.py calculate_tds
"""

import sys

import httpx

tool_name = sys.argv[1] if len(sys.argv) > 1 else "calculate_tds"

reply = httpx.post(f"http://127.0.0.1:8766/admin/publish/{tool_name}")
reply.raise_for_status()
tools = reply.json()["tools"]
print(f"🚀 Published '{tool_name}'. The server now has {len(tools)} tools: {tools}")
