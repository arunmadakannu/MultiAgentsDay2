# Module 5 – MCP in an Enterprise Setting (Microsoft Agent Framework + Foundry)

Three demos, each a Gradio app, plus `app_all_mcp.py` with all three as tabs.

| Lab | Demo | MCP server | Agent(s) and allowed tools |
|---|---|---|---|
| `lab5_1_local_mcp.py` (7871) | **Local** server – AP invoice desk | `vendor_po_server.py` – stdio, started by the app | Invoice Checker → `get_purchase_order`, `match_invoice_to_po` · Vendor Risk → `get_vendor` |
| `lab5_2_remote_mcp.py` (7872) | **Remote** server – Treasury FX | `fx_server.py` – HTTP on :8765, API key, live ECB rates | Payments Agent → `convert_amount`, `check_fx_limit` |
| `lab5_3_dynamic_tools.py` (7873) | **Dynamic tools** – India tax | `tax_server.py` – HTTP on :8766, 3 → 4 tools live | Tax Assistant → whatever the server offers |

## Setup
```bash
pip install -r requirements.txt
cp .env.example .env         # Foundry endpoint + model + FX_SERVER_API_KEY
az login
```

## Run
```bash
python fx_server.py                  # remote FX server  (Lab 5.2)
python tax_server.py                 # dynamic tax server (Lab 5.3)
python app_all_mcp.py                # http://127.0.0.1:7870
python publish_tool.py calculate_tds # Lab 5.3: the Tax team publishes tool no. 4 (run during the demo)
```

## Demo script
- **5.1** Pick each invoice → the app starts the local server itself; see which tools each agent may use and every tool call.
- **5.2** Ask the question → watch the server terminal log each caller. Click "2nd client" (same server, another app). Click "WITHOUT an API key" → 401.
- **5.3** Ask → "no TDS tool yet". In another terminal run `python publish_tool.py calculate_tds` →
  the app's tool list changes 3 → 4 by itself (the app does nothing). Ask again → full answer.
  To reset to 3 tools, restart `tax_server.py` and the app.

How 5.3 works: `publish_tool.py` calls the server's admin endpoint; the server adds the tool with `mcp.add_tool(...)` and sends the MCP notification
`notifications/tools/list_changed`; Microsoft Agent Framework reloads the tool list on that notification.
