# Day 2 – Use Case Plan

Status: **PLAN ONLY, no code yet.** Current focus: **Module 4**. Modules 5–7 come later.

---

# Module 4 – Multi-Agent Patterns (Microsoft Agent Framework)

Five labs, one per orchestration pattern, each with its **own simple finance use case**.
They go from the most controlled pattern to the most autonomous one.

| # | Pattern | Use case | One-line idea |
|---|---|---|---|
| 4.1 | **Sequential** | Expense Claim Approval | Steps in a fixed order, like an assembly line |
| 4.2 | **Concurrent** | Loan Application Check | Several checks at the same time, then combine the results |
| 4.3 | **Handoff** | Bank Customer Support | Agents pass the customer to whoever can help |
| 4.4 | **Group Chat** | Investment Committee Meeting | Agents discuss and debate while a chair runs the meeting |
| 4.5 | **Magentic** | CFO asks "Why did profit drop?" | A manager agent makes its own plan and adjusts it as it goes |

---

## 4.1 Sequential – Expense Claim Approval

**Story:** An employee submits a travel expense claim. It must be checked step by step.

```
Receipt Reader → Calculator → Policy Checker → Approver
```

| Agent | Job | Tool |
|---|---|---|
| Receipt Reader | pulls out date, amount and category from the claim | – |
| Calculator | totals the receipts and flags duplicates | **Code Interpreter** |
| Policy Checker | checks the limits in the travel policy | **File Search** |
| Approver | approves, rejects or sends back | – |

**Use when:** each step needs the output of the step before it.
**Watch out:** it's the slowest pattern, and one bad step breaks everything after it.

---

## 4.2 Concurrent – Loan Application Check

**Story:** A customer applies for a personal loan. Three independent checks can run **at the same time**.

```
                ┌→ Credit Score Agent ─┐
Application ────┼→ Income Agent (DTI) ─┼→ Loan Decision
                └→ Fraud Check Agent ──┘
```

| Agent | Job | Tool |
|---|---|---|
| Credit Score Agent | reads the credit report and rates the risk | – |
| Income Agent | calculates debt-to-income ratio from bank statements | **Code Interpreter** |
| Fraud Check Agent | looks for mismatched name, address or employer | – |
| (Aggregator) | combines all three into approve, reject or review | – |

**Use when:** the checks don't depend on each other.
**Measure:** time and token cost, parallel vs one-by-one.

---

## 4.3 Handoff – Bank Customer Support

**Story:** A customer chats with the bank. The front desk agent **hands the customer over** to the right specialist, and a specialist can hand off again.

```
Front Desk ──→ Cards Agent      ("my card is blocked")
           ──→ Loans Agent      ("what's my EMI?")
           ──→ Fraud Agent ──→ 👤 Human Officer  ("I didn't make this payment!")
```

| Agent | Job |
|---|---|
| Front Desk | understands the question and hands off |
| Cards Agent | card block and unblock, limits |
| Loans Agent | EMI, outstanding balance (**Code Interpreter** for the EMI calculation) |
| Fraud Agent | disputed transactions; **hands off to a human** for anything above $500 |

**Use when:** you don't know up front who should handle the request.
**Difference from Manager routing:** the conversation actually *moves* to the new agent; it doesn't come back.

---

## 4.4 Group Chat – Investment Committee Meeting

**Story:** "Should we invest $2M in Company X?" Agents **discuss in one shared chat**. A Chair agent decides who speaks next and when the meeting ends.

```
            Chair (decides who speaks)
       ┌──────────┼──────────┐
  Bull Analyst  Bear Analyst  Risk Officer
      (pros)      (cons)     (numbers, limits)
```

| Agent | Job | Tool |
|---|---|---|
| Chair | picks the next speaker; ends with a final decision | – |
| Bull Analyst | argues for the investment | – |
| Bear Analyst | argues against it | – |
| Risk Officer | checks the numbers: ratios, exposure | **Code Interpreter** |

**Use when:** you want debate, review or back-and-forth for a better answer.
**Watch out:** set a max number of rounds, or the meeting never ends (and cost keeps growing).

---

## 4.5 Magentic – "Why did profit drop 15%?"

**Story:** The CFO asks an **open question** with no fixed steps. A Magentic manager agent:
1. makes a **plan** (a task ledger),
2. gives tasks to specialists,
3. checks progress and **replans** if something fails,
4. writes the final answer.

```
              Magentic Manager (plan → assign → check → replan)
        ┌──────────────┬──────────────┬──────────────┐
  Data Analyst    Market Researcher   Report Writer
 (Code Interp.)    (Bing Search)       (CFO brief)
```

| Agent | Job | Tool |
|---|---|---|
| Magentic Manager | plans, tracks progress, replans | – |
| Data Analyst | analyses sales and cost data, makes charts | **Code Interpreter** |
| Market Researcher | checks outside reasons (FX, raw material prices) | **Bing Grounding** |
| Report Writer | writes a one-page CFO brief | – |

**Use when:** the task is open-ended and you can't draw the steps in advance.
**Watch out:** it's the most powerful pattern and also the most expensive and least predictable.

---

## In every lab: Single agent vs Multi-agent

Each lab runs the **same task, same input, same model** in 3 ways:
1. **Single agent**: one agent with all instructions and tools
2. **Multi-agent**: the lab's pattern
3. **Multi-agent + mini model**: specialists on a smaller, cheaper model (optional)

Each run happens 3 times and the results are averaged. The script ends by printing:

| Version | Time (s) | LLM calls | Input tokens | Output tokens | Cost ($) | Correct? |
|---|---|---|---|---|---|---|
| Single agent | | | | | | |
| Multi-agent | | | | | | |
| Multi-agent (mini) | | | | | | |

- Cost = tokens × price per token (kept in `.env` / a config file) + tool charges (Code Interpreter sessions, Bing calls)
- The same runs can be checked in the **Foundry portal → Tracing** (a timeline of each agent step with its time and tokens)

## When should you build a multi-agent system?

**Start with ONE agent.** Split it only when you see one of these signs:

| Sign | Example | Why splitting helps |
|---|---|---|
| **Too many tools** (roughly 10+) | the Module 3 agent with 12 tools picked the wrong tool | each specialist has few tools, so it chooses better |
| **Instructions too long or mixed** | one prompt covering policy, maths, emails and approvals | a short focused prompt per agent |
| **Different skills or models needed** | maths → Code Interpreter; policy → File Search; simple steps → mini model | right tool and model per job, and possibly cheaper |
| **Independent work that can run in parallel** | credit, income and fraud checks | faster (Concurrent) |
| **Separation of duties / security** | the person who prepares a payment must not approve it | give different agents different permissions |
| **Different teams own the parts** | Treasury owns the cash agent, Tax owns the tax agent | each team builds, tests and updates its own agent (A2A in Module 7) |
| **Need a second opinion or review** | investment decision, credit memo | debate and review improve quality (Group Chat) |

**Stay with ONE agent when:**
- the task is simple, with few tools and a short prompt
- speed and cost matter more than anything else
- a single agent already gets the right answer

> Rule of thumb: **Multi-agent is for accuracy, control and ownership, not for speed or cost.**
> Measure the single agent first, then split only if the numbers show a problem.

---

## Wrap-up (10 min): Which pattern when?

| If your task… | Use |
|---|---|
| has fixed steps in order | Sequential |
| has independent checks | Concurrent |
| needs routing to the right expert | Handoff |
| benefits from discussion or review | Group Chat |
| is open-ended with unknown steps | Magentic |

Optional: a table of the time and token cost of each lab, printed at the end of every script.

---

## Decisions needed before coding
1. Are these 5 use cases OK?
2. Format: `.py` files (like `Labfiles/`), Colab `.ipynb`, or both?

---

# Module 5 – MCP in an Enterprise Setting (PLAN – no code yet)

Same format as Module 4: one Gradio app per lab plus one combined app, MAF only, Foundry models,
every agent has 1-2 tools (now served by MCP servers). Each lab has its own finance use case.

| # | Outline topic | Use case | What participants see |
|---|---|---|---|
| 5.1 | MCP as a shared tool contract | **Vendor & PO MCP server** (Accounts Payable) | Build a FastMCP server: tools `get_vendor`, `get_purchase_order`, `match_invoice_to_po`, a policy *resource* and a *prompt*. The UI works like an "MCP Inspector": list tools, call one, see the raw JSON |
| 5.2 | Swap hand-written tools for MCP | **Invoice Approval Desk** (3 agents) | Before: every agent carries its own copy-pasted Python tools. After: all 3 agents connect to the same MCP server. Change one rule on the server and every agent picks it up |
| 5.3 | Local vs remote servers | **Treasury FX Desk** | Local (stdio) = company cash positions, sensitive, same machine · Remote (HTTP) = shared FX-rates server run by Treasury · Foundry-hosted MCP = Foundry calls a public server (Microsoft Learn docs for Dynamics 365 Finance how-to questions). A "where each one belongs" table |
| 5.4 | Auth, secrets, on-behalf-of | **Payroll Query Assistant** | Remote MCP server needs a bearer token. "Logged in as" India or US payroll manager → the same question returns only that country's employees. Secrets come from `.env` / Key Vault, and the server audit log shows who each call was made for |
| 5.5 | Limit each agent's tools | **Vendor Payments Operations** | One server with read tools and write tools (`release_payment`, `change_vendor_bank_account`). The Inquiry agent is read-only (`allowed_tools`), the Payment agent can pay but needs **human approval in the UI**, and no agent may change bank details (bank-detail fraud). A blocked attempt is shown and logged, enforced on both client and server |
| 5.6 | Versioning without breaking live agents | **Month-end Trial Balance server v1 → v2** | v2 adds cost centre and currency. The wrong way (change in place) breaks the live v1 agent; the right way (`/v1` and `/v2` side by side plus a deprecation notice) keeps the old agent working while the new agent uses v2 |

Decisions needed:
1. Remote servers: run on the laptop (localhost HTTP) for 5.3–5.6, and use Microsoft Learn MCP as the Foundry-hosted example (no Azure deployment needed)?
2. On-behalf-of (5.4): simulated user tokens (simple, recommended) or real Entra ID tokens from `az login`?
