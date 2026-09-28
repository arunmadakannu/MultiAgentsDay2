"""
Lab 4.5 - MAGENTIC pattern: "Why did our profit drop 15%?"
==========================================================

Story
-----
The CFO asks an OPEN question. Nobody wrote the steps in advance. A Magentic
Manager agent:
    1. writes a PLAN (the "task ledger": facts + plan),
    2. picks the next specialist and tells it exactly what to do,
    3. checks progress after every step (the "progress ledger"),
    4. REPLANS if the team is stuck, and
    5. writes the final answer when the request is satisfied.

                 🧠 Magentic Manager  (plan → assign → check → replan)
        ┌──────────────────┬───────────────────┬──────────────────┐
   📈 Data Analyst    🌐 Market Researcher    ✍️ Report Writer
  (P&L data + Python)  (OpenAPI FX + Web)     (saves the brief)

Tools (each specialist has its own)
-----------------------------------
- Data Analyst      : get_quarterly_pnl (function) + Code Interpreter (variance analysis)
- Market Researcher : fx_rates OpenAPI tool (live ECB USD/INR rates - Foundry calls the
                      REST API itself) + Web Search (copper and freight news; can be
                      switched off in the UI)
- Report Writer     : save_cfo_brief (function - writes outputs/cfo_brief_*.md)
- The Manager has no tools on purpose: it only plans and delegates.

Microsoft Agent Framework
-------------------------
MagenticBuilder(participants=[...], manager_agent=manager, max_round_count=...)
- most flexible, most autonomous pattern - also the most expensive and the least
  predictable, so we cap the rounds and the stalls.

Run
---
    pip install -r requirements.txt
    python lab4_5_magentic_cfo.py              # opens http://127.0.0.1:7865
"""

import os
import time
from datetime import datetime
from pathlib import Path
from typing import Annotated

import gradio as gr
from dotenv import load_dotenv
from azure.identity.aio import DefaultAzureCredential
from agent_framework import Agent, AgentContext, AgentMiddleware, AgentResponse, AgentResponseUpdate, Message
from agent_framework.foundry import FoundryChatClient
from agent_framework.orchestrations import (
    MagenticBuilder,
    MagenticOrchestratorEvent,
    MagenticOrchestratorEventType,
    MagenticProgressLedger,
)

HERE = Path(__file__).parent
OUTPUT_DIR = HERE / "outputs"
load_dotenv(HERE / ".env")

# --------------------------------------------------------------------------
# 1. The CFO's question and the internal data (served by a tool)
# --------------------------------------------------------------------------
CFO_QUESTION = (
    "Operating profit fell about 15% from Q1 to Q2 FY2026 even though revenue went up. "
    "Why? Find the main drivers with numbers, check whether outside market factors explain part of it, "
    "and give me a one-page brief with 3 actions for Q3."
)

INTERNAL_DATA = """Contoso Appliances - P&L by quarter, FY2026 (USD millions)
line_item,Q1,Q2
revenue_air_conditioners,50.0,55.0
revenue_refrigerators,40.0,41.0
revenue_washing_machines,30.0,27.5
raw_materials,52.0,56.9
labour,14.0,14.2
freight,6.0,7.1
other_cogs,6.0,6.0
operating_expenses,22.0,22.1
fx_loss,0.2,0.4

Extra internal facts:
- Copper is the main raw material in ACs and refrigerators. Average copper purchase price: Q1 $8,900/t, Q2 $10,100/t
- Washing machines: North region discount rate went from 4% (Q1) to 9% (Q2) to fight a new competitor
- About 35% of components are imported and paid in USD; the rupee weakened in Q2
- Sea freight contracts were re-priced in April 2026
- FY2026 Q1 = April-June 2025, Q2 = July-September 2025"""

ICONS = {"DataAnalyst": "📈", "MarketResearcher": "🌐", "ReportWriter": "✍️", "MagenticManager": "🧠"}

# --------------------------------------------------------------------------
# 2. Tools
# --------------------------------------------------------------------------
# OpenAPI tool: Foundry calls this public REST API directly (ECB rates via
# frankfurter.dev, no key). The time-series endpoint returns daily rates for a range.
FX_RATES_OPENAPI_TOOL = {
    "type": "openapi",
    "openapi": {
        "name": "fx_rates",
        "description": "Official ECB currency exchange rates: one date, or a date range (time series).",
        "auth": {"type": "anonymous"},
        "spec": {
            "openapi": "3.0.1",
            "info": {"title": "Frankfurter FX rates", "version": "1.0"},
            "servers": [{"url": "https://api.frankfurter.dev/v1"}],
            "paths": {
                "/{date_or_range}": {
                    "get": {
                        "operationId": "getRates",
                        "summary": "Rates for a date 'YYYY-MM-DD', a range 'YYYY-MM-DD..YYYY-MM-DD', or 'latest'.",
                        "parameters": [
                            {"name": "date_or_range", "in": "path", "required": True, "schema": {"type": "string"}},
                            {"name": "base", "in": "query", "description": "Base currency, e.g. USD",
                             "schema": {"type": "string"}},
                            {"name": "symbols", "in": "query", "description": "Target currencies, e.g. INR",
                             "schema": {"type": "string"}},
                        ],
                        "responses": {"200": {"description": "Rates"}},
                    }
                }
            },
        },
    },
}

SAVED_BRIEFS: list[str] = []


class TextOnlyTeamHistory(AgentMiddleware):
    """Pass the shared team conversation to each agent as plain text only.

    Magentic broadcasts every agent's messages to the whole team. Tool calls and
    tool results are private to the agent that made them: replaying another agent's
    tool result makes the service reject the request ("No tool call found for
    function call output"). Same idea as MAF's clean_conversation_for_handoff.
    """

    async def process(self, context: AgentContext, call_next) -> None:
        cleaned = []
        for msg in context.messages:
            text = " ".join(c.text for c in msg.contents if c.type == "text" and c.text)
            if text:
                cleaned.append(Message(role=msg.role, contents=[text], author_name=msg.author_name))
        context.messages = cleaned
        await call_next()


def save_cfo_brief(
    title: Annotated[str, "Short title of the brief"],
    markdown: Annotated[str, "The full one-page brief in Markdown"],
) -> str:
    """Save the final CFO brief as a Markdown file in the finance shared folder."""
    OUTPUT_DIR.mkdir(exist_ok=True)
    path = OUTPUT_DIR / f"cfo_brief_{datetime.now():%Y%m%d_%H%M%S}.md"
    path.write_text(f"# {title}\n\n{markdown}", encoding="utf-8")
    SAVED_BRIEFS.append(str(path))
    return f"Saved to {path.name}"


# --------------------------------------------------------------------------
# 3. Foundry client
# --------------------------------------------------------------------------
_credential = None


def get_client() -> FoundryChatClient:
    global _credential
    if _credential is None:
        _credential = DefaultAzureCredential()
    return FoundryChatClient(
        project_endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
        model=os.environ.get("FOUNDRY_MODEL", "gpt-5.4-mini"),
        credential=_credential,
    )


# --------------------------------------------------------------------------
# 4. Manager + specialists
# --------------------------------------------------------------------------
def build_workflow(pnl_data: str, use_web_search: bool, max_rounds: int):
    client = get_client()

    def get_quarterly_pnl() -> str:
        """Get Contoso Appliances' quarterly P&L (CSV, USD millions) and internal cost facts from the ERP."""
        return pnl_data

    data_analyst = Agent(
        client=client,
        name="DataAnalyst",
        middleware=[TextOnlyTeamHistory()],
        description="Pulls the internal P&L from the ERP and analyses it with Python (variance analysis).",
        instructions=(
            "You are a financial data analyst. First call get_quarterly_pnl. Then ALWAYS use the code "
            "interpreter (Python/pandas): operating profit per quarter (revenue - all costs - fx_loss), "
            "change in each line item, and a profit bridge (Q1 profit -> each driver -> Q2 profit). "
            "Report numbers in a small table. Never invent numbers."
        ),
        tools=[get_quarterly_pnl, client.get_code_interpreter_tool()],
    )

    researcher_tools: list = [FX_RATES_OPENAPI_TOOL]
    if use_web_search:
        researcher_tools.append(client.get_web_search_tool(search_context_size="low"))
    market_researcher = Agent(
        client=client,
        name="MarketResearcher",
        middleware=[TextOnlyTeamHistory()],
        description="Finds outside market reasons: USD/INR move (fx_rates tool), copper and freight prices.",
        instructions=(
            "You explain EXTERNAL factors. 1) You MUST call the fx_rates tool twice (never skip it): USD->INR for each quarter, "
            "with date_or_range=2025-04-01..2025-06-30 (Q1) and date_or_range=2025-07-01..2025-09-30 (Q2), base=USD, symbols=INR. Report the average rate per quarter and the % change. "
            "Then apply that % to the ~35% of costs paid in USD. "
            + ("2) Use web search once for copper price and sea freight trends in mid-2025 and cite sources. "
               if use_web_search else
               "2) Web search is OFF: add copper/freight context from general knowledge, labelled 'not verified'. ")
            + "Max 6 bullets. Do not analyse internal P&L data."
        ),
        tools=researcher_tools,
    )

    report_writer = Agent(
        client=client,
        name="ReportWriter",
        middleware=[TextOnlyTeamHistory()],
        description="Writes the final one-page CFO brief and saves it to the shared folder.",
        instructions=(
            "You write a one-page CFO brief in Markdown: headline (one sentence), profit bridge table, "
            "top drivers (internal vs external), and exactly 3 actions for Q3 with the expected impact. "
            "Use only numbers already found by the team. ALWAYS save it with save_cfo_brief, then reply "
            "with the brief and the saved file name."
        ),
        tools=[save_cfo_brief],
    )

    manager = Agent(
        client=client,
        name="MagenticManager",
        instructions="You coordinate a finance team to answer the CFO's question accurately and efficiently.",
    )

    return MagenticBuilder(
        participants=[data_analyst, market_researcher, report_writer],
        manager_agent=manager,
        max_round_count=max_rounds,   # hard cap on coordination rounds (cost control)
        max_stall_count=2,            # replan after 2 rounds with no progress
        max_reset_count=1,
        intermediate_output_from="all_other",  # stream each specialist's work live
    ).build()


# --------------------------------------------------------------------------
# 5. Render plan, manager decisions and agent work
# --------------------------------------------------------------------------
class Board:
    def __init__(self):
        self.plan = ""
        self.decisions: list[str] = []
        self.work: list[dict] = []   # {"agent", "text", "code"}
        self.final = ""

    def agent_step(self, agent: str) -> dict:
        if not self.work or self.work[-1]["agent"] != agent:
            self.work.append({"agent": agent, "text": "", "code": []})
        return self.work[-1]

    def work_md(self) -> str:
        parts = []
        for i, w in enumerate(self.work, 1):
            parts.append(f"#### {i}. {ICONS.get(w['agent'], '🤖')} {w['agent']}")
            for code in w["code"]:
                parts.append(f"<details><summary>🐍 Python run by Code Interpreter</summary>\n\n```python\n{code}\n```\n</details>")
            parts.append(w["text"] or "_working..._")
        return "\n\n".join(parts) or "_Waiting for the manager to assign the first task..._"

    def decisions_md(self) -> str:
        return "\n".join(self.decisions) or "_No decisions yet_"


async def run_magentic(question: str, data: str, use_web_search: bool, max_rounds: int):
    board = Board()
    start = time.perf_counter()

    def view(stats: str = ""):
        return (board.plan or "_Manager is writing the plan..._", board.decisions_md(), board.work_md(),
                board.final or "_Not ready yet_", stats or f"⏱️ {time.perf_counter() - start:.1f}s")

    task = question  # the internal data is fetched by the DataAnalyst through get_quarterly_pnl
    try:
        workflow = build_workflow(data, use_web_search, int(max_rounds))
        async for event in workflow.run(task, stream=True):
            d = event.data
            if event.type == "magentic_orchestrator" and isinstance(d, MagenticOrchestratorEvent):
                if d.event_type == MagenticOrchestratorEventType.PLAN_CREATED and isinstance(d.content, Message):
                    board.plan = d.content.text
                elif d.event_type == MagenticOrchestratorEventType.REPLANNED and isinstance(d.content, Message):
                    board.plan = "🔁 **REPLANNED**\n\n" + d.content.text
                    board.decisions.append("- 🔁 **Team was stuck → manager wrote a new plan**")
                elif isinstance(d.content, MagenticProgressLedger):
                    ledger = d.content
                    done = ledger.is_request_satisfied.answer is True
                    board.decisions.append(
                        f"- **Round {len(board.decisions) + 1}:** "
                        + ("✅ request satisfied → writing final answer" if done else
                           f"➡️ **{ledger.next_speaker.answer}**: {ledger.instruction_or_question.answer}")
                    )
            elif event.type in ("output", "intermediate"):
                if isinstance(d, AgentResponseUpdate):
                    agent = d.author_name or event.executor_id
                    if agent in ("MagenticManager", "magentic_orchestrator"):
                        board.final += d.text
                        continue
                    step = board.agent_step(agent)
                    for c in d.contents:
                        if c.type == "text":
                            step["text"] += c.text or ""
                        elif c.type == "code_interpreter_tool_call" and c.inputs:
                            if not (getattr(c.raw_representation, "type", "") or "").endswith(".delta"):
                                step["code"].append(c.inputs[0].text)
                elif isinstance(d, AgentResponse):
                    if event.executor_id in ICONS and event.executor_id != "MagenticManager":
                        step = board.agent_step(event.executor_id)
                        step["text"] = step["text"] or d.text
                    else:
                        board.final = d.text
                elif isinstance(d, list) and d and isinstance(d[-1], Message):
                    board.final = d[-1].text   # the manager's final answer
                elif isinstance(d, Message):
                    board.final = d.text
            yield view()
    except Exception as exc:
        board.final = f"❌ **Error:** `{type(exc).__name__}: {exc}`"
        yield view(" ")
        return

    yield view(f"⏱️ **{time.perf_counter() - start:.1f}s** · {len(board.decisions)} manager rounds · "
               f"{len(board.work)} specialist turns · max rounds = {int(max_rounds)}"
               + (f"\n\n💾 Brief saved: `outputs/{Path(SAVED_BRIEFS[-1]).name}`" if SAVED_BRIEFS else ""))


# --------------------------------------------------------------------------
# 6. Gradio UI
# --------------------------------------------------------------------------
def build_ui() -> gr.Blocks:
    with gr.Blocks(title="Lab 4.5 · Magentic") as demo:
        gr.Markdown(
            "## Lab 4.5 · Magentic pattern: \"Why did profit drop 15%?\"\n"
            "`🧠 Manager plans → assigns → checks progress → replans → 📈 Data Analyst (Code Interpreter) | "
            "🌐 Market Researcher (Web Search) | ✍️ Report Writer`\n\n"
            "Nobody wrote the steps. The manager **makes its own plan** and changes it if the team gets stuck."
        )
        with gr.Row():
            with gr.Column(scale=2):
                question = gr.Textbox(label="CFO question", lines=4, value=CFO_QUESTION)
                data = gr.Textbox(label="Internal ERP data (served to the Data Analyst by get_quarterly_pnl)", lines=16, value=INTERNAL_DATA)
                use_web = gr.Checkbox(value=True, label="Market Researcher also uses Web Search (FX rates always come from the OpenAPI tool)")
                max_rounds = gr.Slider(4, 15, value=10, step=1, label="Max manager rounds (cost cap)")
                run_btn = gr.Button("▶ Ask the Magentic team", variant="primary")
                stats = gr.Markdown()
            with gr.Column(scale=3):
                with gr.Tab("📄 Final CFO brief"):
                    final = gr.Markdown()
                with gr.Tab("📋 Manager's plan"):
                    plan = gr.Markdown()
                with gr.Tab("🧭 Manager decisions"):
                    decisions = gr.Markdown()
                with gr.Tab("👥 Specialist work"):
                    work = gr.Markdown()

        run_btn.click(run_magentic, [question, data, use_web, max_rounds], [plan, decisions, work, final, stats])
    return demo


if __name__ == "__main__":
    build_ui().launch(server_port=7865)
