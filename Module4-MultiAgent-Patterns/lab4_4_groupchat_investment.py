"""
Lab 4.4 - GROUP CHAT pattern: Investment Committee Meeting
==========================================================

Story
-----
"Should our fund invest $2M in GreenVolt Batteries?" Three analysts DISCUSS in
one shared chat. A Chair agent runs the meeting: it decides who speaks next,
and when the discussion is good enough it ends the meeting with a decision.

                 🪑 Chair  (picks next speaker / ends meeting)
          ┌─────────────┼──────────────┐
    🐂 Bull Analyst  🐻 Bear Analyst  🛡️ Risk Officer
      (argues for)   (argues against)  (checks numbers vs fund rules)

Tools (each agent has its own)
------------------------------
- Chair        : get_fund_rules                          (function tool)
- Bull Analyst : get_customer_contracts                  (function tool - the CRM / order book)
- Bear Analyst : Web Search                              (Foundry tool - live industry risks)
- Risk Officer : Code Interpreter + get_fund_rules       (ratios in Python, checked against rules)

Microsoft Agent Framework
-------------------------
GroupChatBuilder(participants=[...], orchestrator_agent=chair, max_rounds=n)
- everyone sees the same conversation; the orchestrator agent picks the speaker.
- max_rounds is the safety stop so the meeting (and the bill) cannot run forever.

Run
---
    pip install -r requirements.txt
    python lab4_4_groupchat_investment.py      # opens http://127.0.0.1:7864
"""

import os
import time
from pathlib import Path
from typing import Annotated

import gradio as gr
from dotenv import load_dotenv
from azure.identity.aio import DefaultAzureCredential
from agent_framework import Agent, AgentContext, AgentMiddleware, AgentResponse, AgentResponseUpdate, Message
from agent_framework.foundry import FoundryChatClient
from agent_framework.orchestrations import GroupChatBuilder, GroupChatRequestSentEvent

HERE = Path(__file__).parent
load_dotenv(HERE / ".env")

# --------------------------------------------------------------------------
# 1. The investment memo the committee discusses
# --------------------------------------------------------------------------
SAMPLE_DEALS = {
    "🔋 GreenVolt Batteries – $2M for 4%": """Investment proposal: $2,000,000 for a 4% stake in GreenVolt Batteries Pvt Ltd (EV battery packs, India)
Company id: GREENVOLT
Implied valuation: $50M

Financials (USD millions)      FY2024   FY2025   FY2026
Revenue                          6.2     11.8     19.5
EBITDA                          -2.1     -0.8      1.4
Net debt (end of year)           5.0      6.5      8.0
Cash in bank (end of year)       2.0      4.1      3.5
Management forecast FY2027 revenue: 28.0

Other facts:
- Founders have 12 years of battery industry experience
- Customer contracts and order book: see the CRM (get_customer_contracts)""",
    "🍔 QuickBite Cloud Kitchens – $1.5M for 6%": """Investment proposal: $1,500,000 for a 6% stake in QuickBite Cloud Kitchens (food delivery brands, 3 cities)
Company id: QUICKBITE
Implied valuation: $25M

Financials (USD millions)      FY2024   FY2025   FY2026
Revenue                          3.0      4.1      4.6
EBITDA                          -1.8     -2.2     -2.5
Net debt (end of year)           1.0      2.5      4.0
Cash in bank (end of year)       3.0      1.9      1.1
Management forecast FY2027 revenue: 9.0

Other facts:
- Monthly cash burn is about $210k
- New CFO joined 2 months ago
- Customer / channel data: see the CRM (get_customer_contracts)""",
}

ICONS = {"Chair": "🪑", "BullAnalyst": "🐂", "BearAnalyst": "🐻", "RiskOfficer": "🛡️"}

# --------------------------------------------------------------------------
# 2. Function tools (mock fund policy system and CRM)
# --------------------------------------------------------------------------
FUND_RULES = [
    "R1: Max single investment is $3M",
    "R2: Implied valuation must be <= 5x NEXT year's forecast revenue",
    "R3: Company must be EBITDA positive, or show a clear path to it within 12 months",
    "R4: Any customer or channel above 40% of revenue needs a mitigation plan",
    "R5: Net debt / EBITDA must be below 6x (if EBITDA is positive)",
]

CRM = {
    "GREENVOLT": {
        "signed_order_book_usd_m": 32.0, "order_book_period": "next 24 months",
        "customers": [
            {"name": "Two-wheeler OEM A", "share_of_fy2026_revenue_pct": 48, "contract_ends": "2027-12"},
            {"name": "Three-wheeler OEM B", "share_of_fy2026_revenue_pct": 21, "contract_ends": "2028-06"},
            {"name": "Energy storage clients (12)", "share_of_fy2026_revenue_pct": 31, "contract_ends": "various"},
        ],
    },
    "QUICKBITE": {
        "signed_order_book_usd_m": 0.0, "order_book_period": "n/a (consumer orders)",
        "customers": [
            {"name": "Delivery app X", "share_of_fy2026_revenue_pct": 58, "contract_ends": "rolling, commission raised 2026"},
            {"name": "Delivery app Y", "share_of_fy2026_revenue_pct": 32, "contract_ends": "rolling"},
            {"name": "Own website", "share_of_fy2026_revenue_pct": 10, "contract_ends": "-"},
        ],
    },
}


def get_fund_rules() -> list[str]:
    """Get the fund's investment rules that every deal must pass."""
    return FUND_RULES


def get_customer_contracts(company_id: Annotated[str, "Company id from the memo, e.g. GREENVOLT"]) -> dict:
    """Get the company's customer contracts, revenue share per customer and signed order book from the CRM."""
    return CRM.get(company_id.strip().upper(), {"error": "Company not in CRM"})


class TextOnlyTeamHistory(AgentMiddleware):
    """Pass the shared meeting conversation to each agent as plain text only.

    Group chat broadcasts every agent's messages to everyone. Tool calls and tool
    results are private to the agent that made them: replaying another agent's
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
# 4. The committee: Chair (orchestrator) + three participants
# --------------------------------------------------------------------------
def build_workflow(max_rounds: int):
    client = get_client()

    chair = Agent(
        client=client,
        name="Chair",
        instructions=(
            "You chair an investment committee. Participants: BullAnalyst, BearAnalyst, RiskOfficer. "
            "Before your first decision, read the rules with get_fund_rules. "
            "Run the meeting in this order: BullAnalyst opens, BearAnalyst challenges, RiskOfficer checks "
            "the numbers against the fund rules. If Bull and Bear still disagree on something important, "
            "give ONE of them a short rebuttal. Then end the meeting. "
            "When you end it, your final message must be:\n"
            "**Decision:** INVEST | INVEST WITH CONDITIONS | DO NOT INVEST\n"
            "**Conditions (if any):** ...\n**Top 3 reasons:** ...\n"
            "Never let the same person speak twice in a row. Any FAILED fund rule means you cannot choose INVEST."
        ),
        tools=[get_fund_rules],
    )
    bull = Agent(
        client=client,
        name="BullAnalyst",
        middleware=[TextOnlyTeamHistory()],
        instructions=(
            "You argue FOR the investment. First call get_customer_contracts to use real contract and "
            "order-book facts. Max 5 bullet points. If others raised concerns, answer them directly. "
            "Do not invent numbers."
        ),
        tools=[get_customer_contracts],
    )
    bear = Agent(
        client=client,
        name="BearAnalyst",
        middleware=[TextOnlyTeamHistory()],
        instructions=(
            "You argue AGAINST the investment - find the biggest risks. Use web search ONCE for current "
            "2026 risks in this company's industry and country (competition, prices, regulation) and cite "
            "the source. Combine that with weaknesses in the memo. Max 5 bullet points. "
            "Answer the Bull's points directly."
        ),
        tools=[client.get_web_search_tool(search_context_size="low")],
    )
    risk_officer = Agent(
        client=client,
        name="RiskOfficer",
        middleware=[TextOnlyTeamHistory()],
        instructions=(
            "You are neutral and only trust numbers. FIRST call get_fund_rules and check exactly those rules "
            "(R1-R5) - do not invent other rules. Then ALWAYS use the code "
            "interpreter (Python) to compute: revenue growth % per year, valuation / next-year revenue, "
            "net debt / EBITDA (FY2026) and cash runway if EBITDA is negative. Use customer shares mentioned "
            "in the conversation for R4. Then show a table with EACH rule marked PASS or FAIL."
        ),
        tools=[client.get_code_interpreter_tool(), get_fund_rules],
    )

    return GroupChatBuilder(
        participants=[bull, bear, risk_officer],
        orchestrator_agent=chair,
        max_rounds=max_rounds,                 # safety stop: the meeting cannot run forever
        intermediate_output_from="all_other",  # stream each speaker's words live
    ).build()


# --------------------------------------------------------------------------
# 5. Render the meeting as it happens
# --------------------------------------------------------------------------
class Meeting:
    def __init__(self):
        self.turns: list[dict] = []   # {"speaker", "round", "text", "code"}
        self.decision = ""

    def _turn(self, speaker: str, round_index: int | None = None) -> dict:
        if not self.turns or self.turns[-1]["speaker"] != speaker:
            self.turns.append({"speaker": speaker, "round": round_index, "text": "", "code": []})
        return self.turns[-1]

    def markdown(self) -> str:
        parts = []
        for t in self.turns:
            rnd = f" · round {t['round'] + 1}" if t["round"] is not None else ""
            parts.append(f"#### {ICONS.get(t['speaker'], '🤖')} {t['speaker']}{rnd}")
            for code in t["code"]:
                parts.append(f"<details><summary>🐍 Python run by Code Interpreter</summary>\n\n```python\n{code}\n```\n</details>")
            parts.append(t["text"] or "_thinking..._")
        return "\n\n".join(parts) or "_The Chair is opening the meeting..._"


async def run_meeting(memo: str, max_rounds: int):
    if not memo.strip():
        yield "Please enter or pick a proposal.", "", ""
        return

    meeting = Meeting()
    start = time.perf_counter()
    try:
        workflow = build_workflow(int(max_rounds))
        async for event in workflow.run(memo, stream=True):
            data = event.data
            if event.type == "group_chat" and isinstance(data, GroupChatRequestSentEvent):
                meeting._turn(data.participant_name, data.round_index)  # Chair gave someone the floor
            elif event.type in ("output", "intermediate"):
                if isinstance(data, AgentResponseUpdate):
                    speaker = data.author_name or event.executor_id
                    if speaker == "Chair":  # the Chair's closing message = the committee decision
                        meeting.decision += data.text
                        continue
                    turn = meeting._turn(speaker)
                    for c in data.contents:
                        if c.type == "text":
                            turn["text"] += c.text or ""
                        elif c.type == "code_interpreter_tool_call" and c.inputs:
                            if not (getattr(c.raw_representation, "type", "") or "").endswith(".delta"):
                                turn["code"].append(c.inputs[0].text)
                elif isinstance(data, AgentResponse) and event.executor_id != "Chair":
                    turn = meeting._turn(event.executor_id)
                    turn["text"] = turn["text"] or data.text
                elif isinstance(data, list) and data:  # final conversation - last message is the Chair's verdict
                    last = data[-1]
                    if isinstance(last, Message):
                        meeting.decision = last.text
                elif isinstance(data, Message):
                    meeting.decision = data.text
            yield meeting.markdown(), meeting.decision or "_Meeting in progress..._", f"⏱️ {time.perf_counter() - start:.1f}s"
    except Exception as exc:
        yield meeting.markdown(), f"❌ **Error:** `{type(exc).__name__}: {exc}`", ""
        return

    spoken = len(meeting.turns)
    yield (meeting.markdown(), meeting.decision or "_No decision - max rounds reached before the Chair closed._",
           f"⏱️ **{time.perf_counter() - start:.1f}s** · {spoken} speaking turns · max rounds = {int(max_rounds)}")


# --------------------------------------------------------------------------
# 6. Gradio UI
# --------------------------------------------------------------------------
def build_ui() -> gr.Blocks:
    with gr.Blocks(title="Lab 4.4 · Group Chat") as demo:
        gr.Markdown(
            "## Lab 4.4 · Group Chat pattern: Investment Committee\n"
            "`🪑 Chair picks the next speaker → 🐂 Bull | 🐻 Bear | 🛡️ Risk Officer (Code Interpreter)`\n\n"
            "Everyone sees the same conversation. The Chair decides who talks and when the meeting ends."
        )
        with gr.Row():
            with gr.Column(scale=2):
                sample = gr.Dropdown(list(SAMPLE_DEALS), label="Pick a proposal", value=list(SAMPLE_DEALS)[0])
                memo = gr.Textbox(label="Investment memo", lines=18, value=SAMPLE_DEALS[list(SAMPLE_DEALS)[0]])
                max_rounds = gr.Slider(3, 10, value=7, step=1, label="Max rounds (safety stop)")
                run_btn = gr.Button("▶ Start the meeting", variant="primary")
                stats = gr.Markdown()
            with gr.Column(scale=3):
                gr.Markdown("### 🪑 Committee decision")
                decision = gr.Markdown()
                gr.Markdown("### 🗣️ Meeting transcript")
                transcript = gr.Markdown()

        sample.change(lambda k: SAMPLE_DEALS[k], sample, memo)
        run_btn.click(run_meeting, [memo, max_rounds], [transcript, decision, stats])
    return demo


if __name__ == "__main__":
    build_ui().launch(server_port=7864)
