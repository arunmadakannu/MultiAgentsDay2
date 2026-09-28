"""
Lab 4.1 - SEQUENTIAL pattern: Expense Claim Approval
====================================================

Story
-----
An employee submits a travel expense claim. Finance checks it in a fixed order,
like an assembly line. Every agent sees everything the agents before it said.

    Receipt Reader  ->  Calculator  ->  Policy Checker  ->  Approver
    (OpenAPI: FX)      (Code Interp.)    (File Search)       (ERP function)

Tools (each agent has its own)
------------------------------
- OpenAPI tool     : the Receipt Reader converts INR receipts to USD using live
                     ECB exchange rates. Foundry calls the REST API directly.
- Code Interpreter : the Calculator writes and runs real Python to total the
                     receipts and find duplicates (no "mental maths").
- File Search      : the Policy Checker searches the company travel policy
                     (data/travel_policy.md) and quotes the section it used.
- Function tool    : the Approver records the decision in a mock ERP.

Microsoft Agent Framework
-------------------------
SequentialBuilder(participants=[...]) - runs agents one after another and
passes the growing conversation down the chain.

Run
---
    pip install -r requirements.txt
    python lab4_1_sequential_expense.py        # opens http://127.0.0.1:7861
"""

import os
import time
import uuid
from pathlib import Path
from typing import Annotated

import gradio as gr
from dotenv import load_dotenv
from azure.identity.aio import DefaultAzureCredential
from agent_framework import Agent, AgentResponse, AgentResponseUpdate, Message
from agent_framework.foundry import FoundryChatClient
from agent_framework.orchestrations import SequentialBuilder

HERE = Path(__file__).parent
load_dotenv(HERE / ".env")

POLICY_FILE = HERE / "data" / "travel_policy.md"
VECTOR_STORE_CACHE = HERE / "data" / ".policy_vector_store"

# --------------------------------------------------------------------------
# 1. Sample expense claims (what an employee would type or paste in)
# --------------------------------------------------------------------------
SAMPLE_CLAIMS = {
    "✅ Priya – Mumbai client visit (receipts in INR)": """Employee: Priya Sharma (EMP-1042), Sales (based in New York)
Trip: Mumbai client visit, 12-14 Aug 2026 (2 nights). Submitted: 20 Aug 2026
Receipts are in Indian Rupees (INR).
Line items:
1. Hotel - Taj Lands End, 2 nights @ INR 19,000 = INR 38,000   (receipt R-101, 12 Aug)
2. Dinner 12 Aug - INR 4,200                                  (receipt R-102)
3. Lunch 13 Aug - INR 3,100                                   (receipt R-103)
4. Taxi airport to hotel 12 Aug - INR 2,500                   (receipt R-104)
5. Taxi hotel to airport 14 Aug - INR 2,800                   (receipt R-105)
Claimed total: INR 50,600""",
    "⚠️ Rahul – Delhi trip (duplicate + maths error)": """Employee: Rahul Verma (EMP-2208), Operations
Trip: Delhi vendor meeting, 3-4 Sep 2026 (1 night). Submitted: 8 Sep 2026
Line items:
1. Hotel - Lemon Tree Aerocity, 1 night = $190     (receipt R-201)
2. Taxi airport to hotel - $42                      (receipt R-202)
3. Taxi airport to hotel - $42                      (receipt R-202)
4. Lunch 3 Sep - $38                                (receipt R-203)
5. Dinner 3 Sep - $55                               (receipt R-204)
Claimed total: $380""",
    "❌ Anita – Pune plant audit (policy violations, > $1,000)": """Employee: Anita Desai (EMP-3371), Internal Audit
Trip: Pune plant audit, 1-4 Sep 2026 (3 nights). Submitted: 10 Sep 2026
Line items:
1. Hotel - JW Marriott Pune, 3 nights @ $320 = $960 (receipt R-301)
2. Dinner 1 Sep (includes 2 glasses of wine $30) - $95 (receipt R-302)
3. Lunch 2 Sep - $40                                (receipt R-303)
4. Flight Mumbai to Pune, economy - $180            (receipt R-304)
5. Taxi to plant - $20                              (no receipt)
Claimed total: $1,295""",
}

# --------------------------------------------------------------------------
# 2. Tools
# --------------------------------------------------------------------------
# OpenAPI tool: Foundry itself calls this public REST API (European Central Bank
# rates via frankfurter.dev, no key needed). We only describe the API with an
# OpenAPI spec - no Python code runs on our side for this tool.
FX_RATES_OPENAPI_TOOL = {
    "type": "openapi",
    "openapi": {
        "name": "fx_rates",
        "description": "Official ECB currency exchange rates for a given date.",
        "auth": {"type": "anonymous"},
        "spec": {
            "openapi": "3.0.1",
            "info": {"title": "Frankfurter FX rates", "version": "1.0"},
            "servers": [{"url": "https://api.frankfurter.dev/v1"}],
            "paths": {
                "/{date}": {
                    "get": {
                        "operationId": "getRatesForDate",
                        "summary": "Exchange rates for a date (YYYY-MM-DD) or 'latest'.",
                        "parameters": [
                            {"name": "date", "in": "path", "required": True, "schema": {"type": "string"}},
                            {"name": "base", "in": "query", "description": "Base currency, e.g. INR",
                             "schema": {"type": "string"}},
                            {"name": "symbols", "in": "query", "description": "Target currencies, e.g. USD",
                             "schema": {"type": "string"}},
                        ],
                        "responses": {"200": {"description": "Rates"}},
                    }
                }
            },
        },
    },
}

ERP_POSTINGS: list[str] = []  # what the Approver "posted" to the finance system


def submit_decision_to_erp(
    employee_id: Annotated[str, "Employee id, e.g. EMP-1042"],
    decision: Annotated[str, "APPROVE | APPROVE WITH DEDUCTIONS | SEND BACK | REJECT"],
    amount_approved_usd: Annotated[float, "Amount to reimburse in USD (0 if not approved)"],
    needs_manager_approval: Annotated[bool, "True if the line manager must also approve"],
) -> str:
    """Record the final expense decision in the finance (ERP) system and return a reference number."""
    ref = f"EXP-{uuid.uuid4().hex[:6].upper()}"
    status = "WAITING FOR LINE MANAGER" if needs_manager_approval else "READY FOR PAYMENT"
    if decision.upper() in ("SEND BACK", "REJECT"):
        status = "RETURNED TO EMPLOYEE"
    ERP_POSTINGS.append(f"{ref} · {employee_id} · {decision} · ${amount_approved_usd:,.2f} · {status}")
    return f"Recorded as {ref}. Status: {status}."


AGENT_ICONS = {
    "ReceiptReader": "🧾",
    "Calculator": "🧮",
    "PolicyChecker": "📘",
    "Approver": "✅",
}

# --------------------------------------------------------------------------
# 3. Foundry client + File Search vector store
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


async def ensure_policy_vector_store(client: FoundryChatClient) -> str:
    """Upload the travel policy once and reuse the vector store id afterwards."""
    endpoint = os.environ["FOUNDRY_PROJECT_ENDPOINT"]
    if VECTOR_STORE_CACHE.exists():
        cached_endpoint, _, cached_id = VECTOR_STORE_CACHE.read_text().partition("|")
        if cached_endpoint == endpoint and cached_id:
            return cached_id

    openai_client = client.client  # the project's OpenAI-compatible client
    vector_store = await openai_client.vector_stores.create(name="contoso-travel-policy")
    with POLICY_FILE.open("rb") as f:
        await openai_client.vector_stores.files.upload_and_poll(vector_store_id=vector_store.id, file=f)
    VECTOR_STORE_CACHE.write_text(f"{endpoint}|{vector_store.id}")
    return vector_store.id


# --------------------------------------------------------------------------
# 4. The four agents and the sequential workflow
# --------------------------------------------------------------------------
async def build_workflow():
    client = get_client()
    vector_store_id = await ensure_policy_vector_store(client)

    receipt_reader = Agent(
        client=client,
        name="ReceiptReader",
        instructions=(
            "You read an employee expense claim and turn it into a clean Markdown table with the "
            "columns: #, date, category (hotel/meal/transport/other), description, amount_usd, receipt_id. "
            "Also list: employee, trip city, number of nights, submission date and the claimed total. "
            "If any amount is NOT in USD, call the fx_rates tool with the receipt date, base = that currency "
            "and symbols = USD, and add an amount_usd column (2 decimals) plus the rate you used. "
            "Do not judge the claim - just extract the facts."
        ),
        tools=[FX_RATES_OPENAPI_TOOL],
    )

    calculator = Agent(
        client=client,
        name="Calculator",
        instructions=(
            "You are the maths checker. ALWAYS use the code interpreter (Python) - never do mental maths. "
            "Using the line items from the conversation: "
            "1) add up the receipts, 2) compare with the claimed total, "
            "3) find duplicate receipts (same receipt_id, or same date + amount + description), "
            "4) show the total per category. "
            "If the receipts were converted to USD, report every total in BOTH the original currency and USD. "
            "Reply with a short summary: calculated total, claimed total, difference, duplicates found."
        ),
        tools=[client.get_code_interpreter_tool()],
    )

    policy_checker = Agent(
        client=client,
        name="PolicyChecker",
        instructions=(
            "You check each line item against the company travel policy. All policy limits are in USD, so "
            "ALWAYS compare using the USD amounts (per night, per day and the claim total). ALWAYS search the policy with "
            "the file search tool before answering. For every violation give: line #, the rule broken, "
            "the policy section number (for example 'Section 2.2'), and the amount that is not "
            "reimbursable. Also say if manager approval is required. If there are no violations, say so. "
            "Be precise: a receipt is only required for amounts ABOVE $25 (a $20 item without a receipt is fine). "
            "For meals, first remove alcohol, then compare each day's meal total with the daily allowance."
        ),
        tools=[client.get_file_search_tool(vector_store_ids=[vector_store_id])],
    )

    approver = Agent(
        client=client,
        name="Approver",
        instructions=(
            "You make the final decision using everything above. Reply in this exact format:\n"
            "**Decision:** APPROVE | APPROVE WITH DEDUCTIONS | SEND BACK | REJECT\n"
            "**Amount approved:** $...\n"
            "**Needs line-manager approval:** Yes/No\n"
            "**Reasons:** 2-4 short bullet points\n"
            "Rules: SEND BACK when the maths is wrong or a receipt is duplicated. "
            "Use APPROVE WITH DEDUCTIONS when only part of the claim breaks policy. "
            "ALWAYS record the decision with submit_decision_to_erp and add the reference number to your reply."
        ),
        tools=[submit_decision_to_erp],
    )

    return SequentialBuilder(
        participants=[receipt_reader, calculator, policy_checker, approver],
        intermediate_output_from="all_other",  # stream every agent's answer, not only the last one
    ).build()


# --------------------------------------------------------------------------
# 5. Turn the workflow's event stream into Markdown for the UI
# --------------------------------------------------------------------------
class Transcript:
    """Keeps each agent's streamed text (and any Python it ran) in order."""

    def __init__(self):
        self.steps: list[dict] = []

    def _step(self, agent: str) -> dict:
        if not self.steps or self.steps[-1]["agent"] != agent:
            self.steps.append({"agent": agent, "text": "", "code": []})
        return self.steps[-1]

    def add(self, agent: str, contents) -> None:
        step = self._step(agent)
        for content in contents:
            if content.type == "text":
                step["text"] += content.text or ""
            elif content.type == "code_interpreter_tool_call" and content.inputs:
                raw_type = getattr(content.raw_representation, "type", "") or ""
                if not raw_type.endswith(".delta"):  # keep the finished code, skip partial chunks
                    step["code"].append(content.inputs[0].text)

    def has(self, agent: str) -> bool:
        return any(s["agent"] == agent for s in self.steps)

    def markdown(self) -> str:
        parts = []
        for i, s in enumerate(self.steps, 1):
            icon = AGENT_ICONS.get(s["agent"], "🤖")
            parts.append(f"### Step {i}: {icon} {s['agent']}")
            for code in s["code"]:
                parts.append(f"<details><summary>🐍 Python run by Code Interpreter</summary>\n\n```python\n{code}\n```\n</details>")
            parts.append(s["text"] or "_working..._")
        return "\n\n".join(parts) if parts else "_Waiting for the first agent..._"


async def run_claim(claim_text: str):
    """Gradio handler: streams (transcript, stats) while the workflow runs."""
    if not claim_text.strip():
        yield "Please enter or pick a claim.", ""
        return

    transcript = Transcript()
    start = time.perf_counter()
    yield "_Setting up agents (first run uploads the policy to File Search)..._", ""

    try:
        workflow = await build_workflow()
        async for event in workflow.run(claim_text, stream=True):
            if event.type not in ("output", "intermediate"):
                continue
            data = event.data
            if isinstance(data, AgentResponseUpdate):
                transcript.add(data.author_name or event.executor_id, data.contents)
            elif isinstance(data, AgentResponse):
                for msg in data.messages:
                    transcript.add(msg.author_name or event.executor_id, msg.contents)
            elif isinstance(data, list):  # final conversation: fill in anything not streamed
                for msg in data:
                    if isinstance(msg, Message) and msg.role == "assistant" and msg.author_name \
                            and not transcript.has(msg.author_name):
                        transcript.add(msg.author_name, msg.contents)
            yield transcript.markdown(), f"⏱️ {time.perf_counter() - start:.1f}s"
    except Exception as exc:  # show the error in the UI instead of a blank screen
        yield transcript.markdown() + f"\n\n---\n❌ **Error:** `{type(exc).__name__}: {exc}`", ""
        return

    elapsed = time.perf_counter() - start
    erp = "\n".join(f"- {p}" for p in ERP_POSTINGS[-3:]) or "_nothing posted_"
    yield transcript.markdown(), (f"⏱️ Finished in **{elapsed:.1f}s** · {len(transcript.steps)} agents ran one after another"
                                  f"\n\n**🗂️ ERP postings (latest):**\n{erp}")


# --------------------------------------------------------------------------
# 6. Gradio UI
# --------------------------------------------------------------------------
def build_ui() -> gr.Blocks:
    with gr.Blocks(title="Lab 4.1 · Sequential") as demo:
        gr.Markdown(
            "## Lab 4.1 · Sequential pattern: Expense Claim Approval\n"
            "`🧾 Receipt Reader (OpenAPI: FX rates) → 🧮 Calculator (Code Interpreter) → 📘 Policy Checker (File Search) → ✅ Approver (ERP function)`\n\n"
            "Each agent waits for the one before it and sees everything said so far."
        )
        with gr.Row():
            with gr.Column(scale=2):
                sample = gr.Dropdown(list(SAMPLE_CLAIMS), label="Pick a sample claim", value=list(SAMPLE_CLAIMS)[0])
                claim = gr.Textbox(label="Expense claim", lines=14, value=SAMPLE_CLAIMS[list(SAMPLE_CLAIMS)[0]])
                run_btn = gr.Button("▶ Run sequential workflow", variant="primary")
                stats = gr.Markdown()
            with gr.Column(scale=3):
                output = gr.Markdown(label="Agent steps")

        sample.change(lambda k: SAMPLE_CLAIMS[k], sample, claim)
        run_btn.click(run_claim, claim, [output, stats])
    return demo


if __name__ == "__main__":
    build_ui().launch(server_port=7861)
