"""
Lab 4.2 - CONCURRENT pattern: Personal Loan Application Check
=============================================================

Story
-----
A customer applies for a personal loan. Three checks do NOT depend on each
other, so they run AT THE SAME TIME (fan-out). A Loan Officer then combines
the three results into one decision (fan-in).

                    ┌─> 📊 Credit Score Agent ──────────┐
    Application ────┼─> 💰 Income Agent ────────────────┼──> 🏦 Loan Officer (decision)
                    └─> 🕵️ Fraud Check Agent ───────────┘

Tools (each agent has its own)
------------------------------
- Credit Score Agent : get_credit_bureau_report                (function tool)
- Income Agent       : get_bank_statement_summary + Code Interpreter (EMI, DTI maths)
- Fraud Check Agent  : check_company_registry + check_mobile_number (function tools)
- Loan Officer       : record_loan_decision                     (function tool)

Microsoft Agent Framework
-------------------------
ConcurrentBuilder(participants=[...]).with_aggregator(callback) - sends the same
input to every participant in parallel, then hands all results to the aggregator.

The UI shows a timeline so you can SEE the three agents overlap in time.

Run
---
    pip install -r requirements.txt
    python lab4_2_concurrent_loan.py           # opens http://127.0.0.1:7862
"""

import os
import time
import uuid
from pathlib import Path
from typing import Annotated

import gradio as gr
from dotenv import load_dotenv
from azure.identity.aio import DefaultAzureCredential
from agent_framework import Agent, AgentResponse, AgentResponseUpdate
from agent_framework.foundry import FoundryChatClient
from agent_framework.orchestrations import ConcurrentBuilder

HERE = Path(__file__).parent
load_dotenv(HERE / ".env")

# --------------------------------------------------------------------------
# 1. Sample loan applications (only what the customer DECLARED on the form)
# --------------------------------------------------------------------------
SAMPLE_APPLICATIONS = {
    "✅ Arjun – strong profile": """Applicant id: APP-5501
Name: Arjun Mehta, age 34, salaried software engineer
Employer (declared): Infosys Ltd
Mobile: +91-98200-11111
Loan requested: $40,000 personal loan, 36 months, 11% annual interest
Declared net monthly income: $6,500
Declared existing loans: car loan, EMI $900 / month""",
    "⚠️ Sneha – stretched finances": """Applicant id: APP-5502
Name: Sneha Kapoor, age 29, salaried retail manager
Employer (declared): Shoppers Stop Ltd
Mobile: +91-98200-22222
Loan requested: $25,000 personal loan, 48 months, 14% annual interest
Declared net monthly income: $3,200
Declared existing loans: two-wheeler EMI $350, personal loan EMI $800""",
    "❌ Rohan – fraud signals": """Applicant id: APP-5503
Name: Rohan Gupta, age 41, Director
Employer (declared): Nimbus Tech Pvt Ltd
Mobile: +91-70000-33333
Loan requested: $60,000 personal loan, 60 months, 12% annual interest
Declared net monthly income: $9,000
Declared existing loans: none""",
}

AGENTS = {
    "CreditScoreAgent": "📊",
    "IncomeAgent": "💰",
    "FraudCheckAgent": "🕵️",
}

# --------------------------------------------------------------------------
# 2. Mock enterprise systems behind function tools
# --------------------------------------------------------------------------
CREDIT_BUREAU = {
    "APP-5501": {"score": 782, "missed_payments_24m": 0, "card_utilisation_pct": 18,
                 "open_loans": [{"type": "car loan", "emi": 900}], "name_on_file": "Arjun Mehta",
                 "address_match": True},
    "APP-5502": {"score": 655, "missed_payments_24m": 3, "card_utilisation_pct": 72,
                 "open_loans": [{"type": "two-wheeler", "emi": 350}, {"type": "personal loan", "emi": 800}],
                 "name_on_file": "Sneha Kapoor", "address_match": True},
    "APP-5503": {"score": 745, "missed_payments_24m": 0, "card_utilisation_pct": 22,
                 "open_loans": [{"type": "consumer durable loan", "emi": 400}],
                 "name_on_file": "Rohan K. Gupta", "address_match": False},
}
BANK_STATEMENTS = {
    "APP-5501": {"avg_monthly_credit": 6500, "salary_source": "Payroll - INFOSYS LTD", "months_seen": 24,
                 "bounced_payments": 0},
    "APP-5502": {"avg_monthly_credit": 3200, "salary_source": "Payroll - SHOPPERS STOP LTD", "months_seen": 12,
                 "bounced_payments": 2},
    "APP-5503": {"avg_monthly_credit": 9000, "salary_source": "Personal transfers (no payroll credits)",
                 "months_seen": 3, "bounced_payments": 0},
}
COMPANY_REGISTRY = {"infosys ltd": "ACTIVE, registered 1981", "shoppers stop ltd": "ACTIVE, registered 1991"}
MOBILE_REGISTRY = {"+91-98200-11111": 6 * 365, "+91-98200-22222": 4 * 365, "+91-70000-33333": 5}

DECISIONS_LOG: list[str] = []


def get_credit_bureau_report(applicant_id: Annotated[str, "Applicant id, e.g. APP-5501"]) -> dict:
    """Get the applicant's credit bureau report: score, missed payments, utilisation and open loans."""
    return CREDIT_BUREAU.get(applicant_id, {"error": "No bureau record found"})


def get_bank_statement_summary(applicant_id: Annotated[str, "Applicant id, e.g. APP-5501"]) -> dict:
    """Get a summary of the applicant's bank statements: average monthly credits and where they come from."""
    summary = dict(BANK_STATEMENTS.get(applicant_id, {"error": "No statements uploaded"}))
    bureau = CREDIT_BUREAU.get(applicant_id)
    if bureau:
        summary["existing_emis_from_bureau"] = bureau["open_loans"]
    return summary


def check_company_registry(company_name: Annotated[str, "Employer company name"]) -> str:
    """Check whether the employer exists in the official company registry."""
    return COMPANY_REGISTRY.get(company_name.strip().lower(), "NOT FOUND in company registry")


def check_mobile_number(mobile: Annotated[str, "Mobile number, e.g. +91-98200-11111"]) -> dict:
    """Check how long the mobile number has been registered with the telecom operator."""
    days = MOBILE_REGISTRY.get(mobile.strip())
    return {"mobile": mobile, "days_registered": days} if days is not None else {"mobile": mobile, "error": "unknown"}


def record_loan_decision(
    applicant_id: Annotated[str, "Applicant id"],
    decision: Annotated[str, "APPROVE | REFER TO UNDERWRITER | DECLINE"],
    reason: Annotated[str, "One-line reason"],
) -> str:
    """Record the final loan decision in the loan origination system."""
    ref = f"LOS-{uuid.uuid4().hex[:6].upper()}"
    DECISIONS_LOG.append(f"{ref} · {applicant_id} · **{decision}** · {reason}")
    return f"Decision recorded as {ref}."


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
# 4. Three parallel specialists + a Loan Officer aggregator
# --------------------------------------------------------------------------
def build_workflow(application: str):
    client = get_client()

    credit_agent = Agent(
        client=client,
        name="CreditScoreAgent",
        instructions=(
            "You look ONLY at credit history. Call get_credit_bureau_report. "
            "Rate credit risk LOW / MEDIUM / HIGH with 2-3 bullet reasons "
            "(score >= 750 and no missed payments = LOW; score < 680 or 3+ missed payments = HIGH). "
            "Ignore income and fraud."
        ),
        tools=[get_credit_bureau_report],
    )
    income_agent = Agent(
        client=client,
        name="IncomeAgent",
        instructions=(
            "You check affordability. Call get_bank_statement_summary to get the VERIFIED income and ALL "
            "existing EMIs (including ones the customer did not declare). Then ALWAYS use the code "
            "interpreter (Python): 1) new EMI = P*r*(1+r)^n / ((1+r)^n - 1), r = annual rate / 12, "
            "2) DTI = (existing EMIs + new EMI) / verified monthly income. "
            "Rule: DTI <= 40% PASS, 40-50% BORDERLINE, > 50% FAIL. "
            "Reply with: new EMI, total EMIs, DTI %, and PASS / BORDERLINE / FAIL. Ignore fraud and credit score."
        ),
        tools=[get_bank_statement_summary, client.get_code_interpreter_tool()],
    )
    fraud_agent = Agent(
        client=client,
        name="FraudCheckAgent",
        instructions=(
            "You look ONLY for fraud signals. Call check_company_registry for the declared employer and "
            "check_mobile_number for the mobile. Signals: employer not in registry, mobile registered < 90 days. "
            "Give fraud risk LOW / MEDIUM / HIGH (2+ signals = HIGH) and list each signal found."
        ),
        tools=[check_company_registry, check_mobile_number],
    )
    loan_officer = Agent(
        client=client,
        name="LoanOfficer",
        instructions=(
            "You receive three independent reports (credit, income, fraud) for one loan application. "
            "Rules: any HIGH fraud risk -> DECLINE. Income FAIL -> DECLINE. "
            "HIGH or MEDIUM credit risk, or BORDERLINE income -> REFER TO UNDERWRITER. Otherwise APPROVE. "
            "ALWAYS record the decision with record_loan_decision, then reply in this format:\n"
            "**Decision:** APPROVE | REFER TO UNDERWRITER | DECLINE\n"
            "**Why:** 3 short bullets, one per report\n**Reference:** ..."
        ),
        tools=[record_loan_decision],
    )

    async def loan_officer_decision(results) -> str:
        """Fan-in: runs after ALL three parallel agents are done."""
        reports = "\n\n".join(f"### {r.executor_id}\n{r.agent_response.text}" for r in results)
        response = await loan_officer.run(f"Application:\n{application}\n\n"
                                          f"Specialist reports:\n\n{reports}")
        return response.text

    return (
        ConcurrentBuilder(
            participants=[credit_agent, income_agent, fraud_agent],
            intermediate_output_from="all",  # stream each specialist's answer live
        )
        .with_aggregator(loan_officer_decision)
        .build()
    )


# --------------------------------------------------------------------------
# 5. Live view: one panel per agent + a timeline proving they overlap
# --------------------------------------------------------------------------
def render_panel(name: str, state: dict) -> str:
    s = state[name]
    status = "✅ done" if s["end"] else ("⏳ running" if s["start"] else "⏸ waiting")
    code = "".join(
        f"\n\n<details><summary>🐍 Python run by Code Interpreter</summary>\n\n```python\n{c}\n```\n</details>"
        for c in s["code"]
    )
    return f"### {AGENTS[name]} {name}\n_{status}_{code}\n\n{s['text']}"


def render_timeline(state: dict, t0: float, now: float) -> str:
    total = max(now - t0, 0.1)
    width = 40
    lines = ["```text"]
    for name, s in state.items():
        if not s["start"]:
            lines.append(f"{name:<17}|{' ' * width}|")
            continue
        start = (s["start"] - t0) / total
        end = ((s["end"] or now) - t0) / total
        a, b = int(start * width), max(int(end * width), int(start * width) + 1)
        bar = " " * a + "█" * (b - a) + " " * (width - b)
        lines.append(f"{name:<17}|{bar}| {s['start'] - t0:4.1f}s → {(s['end'] or now) - t0:4.1f}s")
    lines.append("```")
    return "\n".join(lines)


async def run_application(application: str):
    state = {n: {"text": "", "code": [], "start": None, "end": None} for n in AGENTS}
    t0 = time.perf_counter()
    decision = "_Waiting for all three checks to finish..._"

    def view(extra_stats: str = ""):
        now = time.perf_counter()
        panels = [render_panel(n, state) for n in AGENTS]
        return (*panels, render_timeline(state, t0, now), decision, extra_stats or f"⏱️ {now - t0:.1f}s")

    if not application.strip():
        yield (*["" for _ in AGENTS], "", "Please enter or pick an application.", "")
        return

    try:
        workflow = build_workflow(application)
        async for event in workflow.run(application, stream=True):
            now = time.perf_counter()
            name = event.executor_id if event.executor_id in AGENTS else None

            if event.type == "executor_invoked" and name:
                state[name]["start"] = state[name]["start"] or now
            elif event.type == "executor_completed" and name:
                state[name]["end"] = now
            elif event.type in ("output", "intermediate"):
                data = event.data
                if isinstance(data, AgentResponseUpdate) and name:
                    state[name]["start"] = state[name]["start"] or now
                    for c in data.contents:
                        if c.type == "text":
                            state[name]["text"] += c.text or ""
                        elif c.type == "code_interpreter_tool_call" and c.inputs:
                            if not (getattr(c.raw_representation, "type", "") or "").endswith(".delta"):
                                state[name]["code"].append(c.inputs[0].text)
                elif isinstance(data, AgentResponse) and name and not state[name]["text"]:
                    state[name]["text"] = data.text
                elif isinstance(data, str):  # the aggregator's final decision
                    decision = data
            yield view()
    except Exception as exc:
        decision = f"❌ **Error:** `{type(exc).__name__}: {exc}`"
        yield view("")
        return

    # Show how much time running in parallel saved
    wall = time.perf_counter() - t0
    agent_times = [s["end"] - s["start"] for s in state.values() if s["start"] and s["end"]]
    saved = sum(agent_times) - max(agent_times) if agent_times else 0
    stats = (
        f"⏱️ Wall clock: **{wall:.1f}s** · Sum of the 3 agents' own time: **{sum(agent_times):.1f}s** · "
        f"Running in parallel saved about **{saved:.1f}s**\n\n"
        "**🗂️ Loan system (latest):**\n" + "\n".join(f"- {d}" for d in DECISIONS_LOG[-3:])
    )
    yield view(stats)


# --------------------------------------------------------------------------
# 6. Gradio UI
# --------------------------------------------------------------------------
def build_ui() -> gr.Blocks:
    with gr.Blocks(title="Lab 4.2 · Concurrent") as demo:
        gr.Markdown(
            "## Lab 4.2 · Concurrent pattern: Loan Application Check\n"
            "`Application → [📊 Credit | 💰 Income (Code Interpreter) | 🕵️ Fraud] in parallel → 🏦 Loan Officer`\n\n"
            "The three checks are independent, so they run **at the same time**. Watch the timeline."
        )
        with gr.Row():
            with gr.Column(scale=2):
                sample = gr.Dropdown(list(SAMPLE_APPLICATIONS), label="Pick a sample application",
                                     value=list(SAMPLE_APPLICATIONS)[0])
                application = gr.Textbox(label="Loan application", lines=10,
                                         value=SAMPLE_APPLICATIONS[list(SAMPLE_APPLICATIONS)[0]])
                run_btn = gr.Button("▶ Run concurrent workflow", variant="primary")
            with gr.Column(scale=3):
                gr.Markdown("### 🏦 Loan Officer decision (fan-in)")
                decision = gr.Markdown()
                timeline = gr.Markdown()
                stats = gr.Markdown()
        with gr.Row():
            panels = [gr.Markdown() for _ in AGENTS]

        sample.change(lambda k: SAMPLE_APPLICATIONS[k], sample, application)
        run_btn.click(run_application, application, [*panels, timeline, decision, stats])
    return demo


if __name__ == "__main__":
    build_ui().launch(server_port=7862)
