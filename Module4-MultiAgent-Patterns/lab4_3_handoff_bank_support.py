"""
Lab 4.3 - HANDOFF pattern: Bank Customer Support
================================================

Story
-----
A customer chats with the bank. The Front Desk agent understands the problem
and HANDS the customer over to the right specialist. The specialist now owns
the conversation (it does not go back to a manager). A specialist can hand off
again - and the Fraud agent escalates big disputes to a HUMAN officer.

    Front Desk ──> Cards Agent      "my card is blocked"
               ──> Loans Agent      "what if I prepay my home loan?"   (Code Interpreter)
               ──> Fraud Agent ──>  👤 Human Officer  (disputes above $500)

Tools (each agent has its own)
------------------------------
- Front Desk  : get_customer_profile                       (function tool)
- Cards Agent : get_card_status + unblock_card             (function tools)
- Loans Agent : get_loan_details + Code Interpreter        (EMI / prepayment maths)
- Fraud Agent : get_recent_transactions + file_fraud_case  (function tools)
  file_fraud_case applies the bank rule IN CODE: block the card, auto-dispute
  amounts up to $500, and send anything above $500 to a HUMAN officer.

Microsoft Agent Framework
-------------------------
HandoffBuilder(participants=[...]).add_handoff(source, [targets]) - each agent
gets "handoff_to_<Agent>" tools. After an agent answers, the workflow pauses
and asks the USER for the next message (a request_info event).

Run
---
    pip install -r requirements.txt
    python lab4_3_handoff_bank_support.py      # opens http://127.0.0.1:7863
"""

import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Annotated

import gradio as gr
from dotenv import load_dotenv
from azure.identity.aio import DefaultAzureCredential
from agent_framework import Agent, AgentResponse, AgentResponseUpdate
from agent_framework.foundry import FoundryChatClient
from agent_framework.orchestrations import HandoffAgentUserRequest, HandoffBuilder, HandoffSentEvent

HERE = Path(__file__).parent
load_dotenv(HERE / ".env")

# --------------------------------------------------------------------------
# 1. Mock core-banking data for the logged-in customer
# --------------------------------------------------------------------------
CUSTOMER = "Kavya Iyer (customer id CUST-7781), logged in to the bank's mobile app"


def fresh_bank() -> dict:
    return {
        "cards": {
            "4417": {"type": "Credit card", "status": "BLOCKED", "reason": "3 wrong PIN attempts", "limit": 5000},
            "9021": {"type": "Debit card", "status": "ACTIVE", "reason": "", "limit": 1500},
        },
        "loans": {
            "HL-2231": {"type": "Home loan", "outstanding": 84500, "annual_rate_pct": 8.4, "months_left": 180},
            "PL-0937": {"type": "Personal loan", "outstanding": 6200, "annual_rate_pct": 13.5, "months_left": 18},
        },
        "transactions": {
            "4417": [
                {"id": "TX-8811", "date": "2026-09-24 09:12", "merchant": "Blue Tokai Coffee, Mumbai", "amount": 12.50},
                {"id": "TX-8812", "date": "2026-09-24 19:40", "merchant": "Nature's Basket, Mumbai", "amount": 64.00},
                {"id": "TX-8813", "date": "2026-09-25 02:14", "merchant": "ELECTROMART ONLINE, Lagos", "amount": 749.99},
                {"id": "TX-8814", "date": "2026-09-25 02:16", "merchant": "GIFTCARDS-24, Lagos", "amount": 180.00},
            ],
            "9021": [
                {"id": "TX-9901", "date": "2026-09-23 13:05", "merchant": "Uber India", "amount": 7.80},
            ],
        },
        "actions": [],       # every tool call that changed something
        "human_queue": [],   # tickets waiting for a human officer
    }


BANK = fresh_bank()


def _log(action: str) -> None:
    BANK["actions"].append(f"{datetime.now():%H:%M:%S} · {action}")


# --------------------------------------------------------------------------
# 2. Function tools (plain Python functions - MAF turns them into tools)
# --------------------------------------------------------------------------
def get_customer_profile() -> dict:
    """Get the logged-in customer's profile: name, segment and which products they hold."""
    return {
        "name": "Kavya Iyer", "customer_id": "CUST-7781", "segment": "Premier",
        "cards": {k: v["type"] for k, v in BANK["cards"].items()},
        "loans": {k: v["type"] for k, v in BANK["loans"].items()},
    }


def get_card_status(card_last4: Annotated[str, "Last 4 digits of the card"]) -> dict:
    """Get the status, type and limit of one of the customer's cards."""
    card = BANK["cards"].get(card_last4)
    return card or {"error": f"No card ending {card_last4}. Customer cards: {list(BANK['cards'])}"}


def unblock_card(card_last4: Annotated[str, "Last 4 digits of the card"]) -> str:
    """Unblock a card that was blocked for wrong PIN attempts (not for fraud)."""
    card = BANK["cards"].get(card_last4)
    if not card:
        return f"No card ending {card_last4}."
    if "fraud" in card["reason"].lower():
        return "Cannot unblock: this card was blocked for suspected fraud. Only the Fraud team can decide."
    card["status"], card["reason"] = "ACTIVE", ""
    _log(f"Card ****{card_last4} UNBLOCKED")
    return f"Card ending {card_last4} is now ACTIVE."


def get_loan_details(loan_id: Annotated[str, "Loan id, e.g. HL-2231, or 'all'"]) -> dict:
    """Get outstanding balance, interest rate and months left for the customer's loans."""
    if loan_id.lower() == "all":
        return BANK["loans"]
    return BANK["loans"].get(loan_id) or {"error": f"Unknown loan. Customer loans: {list(BANK['loans'])}"}


def get_recent_transactions(card_last4: Annotated[str, "Last 4 digits of the card"]) -> list:
    """List the recent transactions on a card."""
    return BANK["transactions"].get(card_last4, [])


def file_fraud_case(
    card_last4: Annotated[str, "Last 4 digits of the card"],
    transaction_ids: Annotated[list[str], "Ids of the transactions the customer did NOT make"],
) -> dict:
    """Open a fraud case: blocks the card, disputes amounts up to $500 and escalates bigger ones to a human officer."""
    card = BANK["cards"].get(card_last4)
    if not card:
        return {"error": f"No card ending {card_last4}."}
    card["status"], card["reason"] = "BLOCKED", "suspected fraud"
    _log(f"Card ****{card_last4} BLOCKED (suspected fraud)")

    result = {"card_blocked": True, "disputes_raised": [], "sent_to_human_officer": []}
    for tx_id in transaction_ids:
        tx = next((t for t in BANK["transactions"].get(card_last4, []) if t["id"] == tx_id), None)
        if not tx:
            continue
        if tx["amount"] <= 500:   # bank rule, enforced in code - not left to the LLM
            dispute_id = f"DSP-{uuid.uuid4().hex[:6].upper()}"
            _log(f"Dispute {dispute_id}: {tx_id} ${tx['amount']:.2f} (auto)")
            result["disputes_raised"].append({"transaction": tx_id, "dispute_id": dispute_id,
                                              "note": "provisional credit in 2 working days"})
        else:
            ticket = f"HUM-{uuid.uuid4().hex[:6].upper()}"
            BANK["human_queue"].append(f"**{ticket}** · {tx_id} · ${tx['amount']:,.2f} · {tx['merchant']}")
            _log(f"Escalated {tx_id} ${tx['amount']:.2f} to human officer ({ticket})")
            result["sent_to_human_officer"].append({"transaction": tx_id, "ticket": ticket,
                                                    "note": "a Fraud Officer will call within 2 hours"})
    return result


# --------------------------------------------------------------------------
# 3. Agents + handoff routes
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


def build_workflow():
    client = get_client()
    context = (
        f"You work for Contoso Bank. The customer is {CUSTOMER}. Be short, friendly and clear. "
        "IMPORTANT: when another agent should handle the request, CALL its handoff_to_<AgentName> tool "
        "right away in the same turn - never just say that you will transfer the customer. "
    )

    front_desk = Agent(
        client=client,
        require_per_service_call_history_persistence=True,  # required by HandoffBuilder
        name="FrontDesk",
        description="Greets the customer and routes the request to the right team.",
        instructions=context + (
            "You are the first point of contact. Use get_customer_profile to greet the customer by name "
            "and to know their products. Do NOT solve problems yourself - hand off: "
            "card blocked / unblock / limits -> CardsAgent; loans, EMI, prepayment -> LoansAgent; "
            "unknown or suspicious transactions -> FraudAgent. "
            "For greetings or unclear requests, ask one short question."
        ),
        tools=[get_customer_profile],
    )
    cards_agent = Agent(
        client=client,
        require_per_service_call_history_persistence=True,
        name="CardsAgent",
        description="Handles card status and unblocking cards blocked for wrong PIN.",
        instructions=context + (
            "You handle cards. Always check get_card_status first. You may unblock a card blocked "
            "for wrong PIN with unblock_card. If the customer mentions payments they did not make, "
            "hand off to FraudAgent. For anything that is not about cards, hand off to FrontDesk."
        ),
        tools=[get_card_status, unblock_card],
    )
    loans_agent = Agent(
        client=client,
        require_per_service_call_history_persistence=True,
        name="LoansAgent",
        description="Answers questions about loans, EMIs and prepayment.",
        instructions=context + (
            "You handle loans. Get the numbers with get_loan_details. For ANY calculation "
            "(EMI, interest saved, new tenure after prepayment) ALWAYS use the code interpreter. "
            "EMI = P*r*(1+r)^n / ((1+r)^n - 1), r = annual rate / 12 / 100. "
            "Show the key numbers in a small table. For non-loan topics, hand off to FrontDesk."
        ),
        tools=[get_loan_details, client.get_code_interpreter_tool()],
    )
    fraud_agent = Agent(
        client=client,
        require_per_service_call_history_persistence=True,
        name="FraudAgent",
        description="Handles unknown or suspicious transactions and disputes.",
        instructions=context + (
            "You handle suspicious transactions. 1) Show recent transactions with get_recent_transactions "
            "and ask the customer to confirm which ones they did NOT make (unless they already said clearly). "
            "2) Call file_fraud_case once with those transaction ids. "
            "3) Explain the result: card blocked, which amounts were disputed automatically, and which were "
            "sent to a human Fraud Officer (never promise a refund for those yourself). "
            "For non-fraud topics, hand off to FrontDesk."
        ),
        tools=[get_recent_transactions, file_fraud_case],
    )

    return (
        HandoffBuilder(name="bank_support", participants=[front_desk, cards_agent, loans_agent, fraud_agent])
        .with_start_agent(front_desk)
        .add_handoff(front_desk, [cards_agent, loans_agent, fraud_agent])
        .add_handoff(cards_agent, [fraud_agent, front_desk])
        .add_handoff(loans_agent, [front_desk])
        .add_handoff(fraud_agent, [front_desk])
        .build()
    )


# --------------------------------------------------------------------------
# 4. Chat session handling (the workflow pauses and waits for the user)
# --------------------------------------------------------------------------
ICONS = {"FrontDesk": "🏦", "CardsAgent": "💳", "LoansAgent": "🏠", "FraudAgent": "🚨"}
SESSIONS: dict[str, dict] = {}   # session id -> {"workflow", "pending_request_id", "trail"}


def side_panel(session: dict | None) -> str:
    trail = " → ".join(session["trail"]) if session else "🏦 FrontDesk"
    actions = "\n".join(f"- {a}" for a in BANK["actions"]) or "_none yet_"
    queue = "\n".join(f"- {q}" for q in BANK["human_queue"]) or "_empty_"
    cards = "\n".join(f"- ****{k}: **{v['status']}** {v['reason']}" for k, v in BANK["cards"].items())
    return (f"### 🔀 Who owns the chat\n{trail}\n\n### 🛠️ Actions taken by agents\n{actions}\n\n"
            f"### 👤 Human officer queue\n{queue}\n\n### 💳 Card status\n{cards}")


async def chat(user_message: str, history: list, session_id: str):
    if not user_message.strip():
        yield history, "", session_id, side_panel(SESSIONS.get(session_id))
        return

    history = history + [{"role": "user", "content": user_message}]
    session = SESSIONS.get(session_id)
    try:
        if session is None:  # first message: start a new handoff workflow
            session_id = uuid.uuid4().hex
            session = {"workflow": build_workflow(), "pending_request_id": None, "trail": ["🏦 FrontDesk"]}
            SESSIONS[session_id] = session
            stream = session["workflow"].run(user_message, stream=True)
        else:                # later messages: answer the workflow's pending question
            reply = HandoffAgentUserRequest.create_response(user_message)
            stream = session["workflow"].run(responses={session["pending_request_id"]: reply}, stream=True)

        current_agent = None
        async for event in stream:
            if event.type == "handoff_sent" and isinstance(event.data, HandoffSentEvent):
                src, dst = event.data.source, event.data.target
                session["trail"].append(f"{ICONS.get(dst, '🤖')} {dst}")
                history.append({"role": "assistant", "content": f"🔀 **Handoff:** {src} → {dst}",
                                "metadata": {"title": "Handoff"}})
                current_agent = None
            elif event.type == "request_info" and isinstance(event.data, HandoffAgentUserRequest):
                session["pending_request_id"] = event.request_id  # workflow now waits for the user
            elif event.type == "output":
                data = event.data
                if isinstance(data, AgentResponseUpdate):
                    agent, text = data.author_name or event.executor_id, data.text
                elif isinstance(data, AgentResponse):
                    agent, text = event.executor_id, data.text
                else:
                    continue
                if not text:
                    continue
                if agent != current_agent:
                    history.append({"role": "assistant", "content": f"**{ICONS.get(agent, '🤖')} {agent}:** "})
                    current_agent = agent
                history[-1]["content"] += text
            yield history, "", session_id, side_panel(session)
    except Exception as exc:
        history.append({"role": "assistant", "content": f"❌ Error: `{type(exc).__name__}: {exc}`"})
    yield history, "", session_id, side_panel(session)


def reset():
    global BANK
    BANK = fresh_bank()
    return [], "", "", side_panel(None)


# --------------------------------------------------------------------------
# 5. Gradio UI
# --------------------------------------------------------------------------
EXAMPLES = [
    "Hi, my credit card ending 4417 is not working",
    "I want to prepay $20,000 on my home loan. How much interest do I save?",
    "There are payments from Lagos on my card 4417 that I did not make!",
]


def build_ui() -> gr.Blocks:
    with gr.Blocks(title="Lab 4.3 · Handoff") as demo:
        gr.Markdown(
            "## Lab 4.3 · Handoff pattern: Bank Customer Support\n"
            "`🏦 Front Desk → 💳 Cards | 🏠 Loans (Code Interpreter) | 🚨 Fraud → 👤 Human officer (> $500)`\n\n"
            "The conversation **moves** to the specialist. Try the examples one after another in the same chat."
        )
        session_id = gr.State("")
        with gr.Row():
            with gr.Column(scale=3):
                chatbot = gr.Chatbot(height=520, label="Contoso Bank chat")
                msg = gr.Textbox(placeholder="Type as the customer and press Enter...", show_label=False)
                gr.Examples(EXAMPLES, msg)
                new_btn = gr.Button("🔄 New conversation")
            with gr.Column(scale=2):
                panel = gr.Markdown(side_panel(None))

        msg.submit(chat, [msg, chatbot, session_id], [chatbot, msg, session_id, panel])
        new_btn.click(reset, None, [chatbot, msg, session_id, panel])
    return demo


if __name__ == "__main__":
    build_ui().launch(server_port=7863)
