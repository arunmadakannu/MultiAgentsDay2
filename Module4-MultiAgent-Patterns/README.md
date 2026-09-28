# Module 4 – Multi-Agent Patterns (Microsoft Agent Framework + Foundry)

Five labs, one per MAF orchestration pattern, each with its own finance use case and its own Gradio app.
`app_all_patterns.py` puts all five in one app with tabs. Every agent has one or two tools.

| File | Pattern | Use case | Agents → tools | Port |
|---|---|---|---|---|
| `lab4_1_sequential_expense.py` | Sequential | Expense claim approval | Receipt Reader → **OpenAPI fx_rates** · Calculator → Code Interpreter · Policy Checker → File Search · Approver → ERP function | 7861 |
| `lab4_2_concurrent_loan.py` | Concurrent | Loan application check | Credit → bureau function · Income → bank-statement function + Code Interpreter · Fraud → registry + mobile functions · Loan Officer → decision function | 7862 |
| `lab4_3_handoff_bank_support.py` | Handoff | Bank customer support chat | Front Desk → profile · Cards → status + unblock · Loans → loan details + Code Interpreter · Fraud → transactions + fraud case (human officer > $500) | 7863 |
| `lab4_4_groupchat_investment.py` | Group Chat | Investment committee | Chair → fund rules · Bull → CRM · Bear → Web Search · Risk Officer → Code Interpreter + fund rules | 7864 |
| `lab4_5_magentic_cfo.py` | Magentic | "Why did profit drop 15%?" | Data Analyst → ERP P&L + Code Interpreter · Market Researcher → **OpenAPI fx_rates** + Web Search · Report Writer → save brief (manager has no tools: it plans) | 7865 |
| `app_all_patterns.py` | all five | tabs | – | 7860 |

## Setup
```bash
pip install -r requirements.txt
cp .env.example .env        # fill in FOUNDRY_PROJECT_ENDPOINT and FOUNDRY_MODEL
az login                    # auth is Entra ID (DefaultAzureCredential) - no API key needed
python app_all_patterns.py  # or any single lab file; open http://127.0.0.1:7860
```

## Notes
- The OpenAPI tool calls the public ECB rates API (api.frankfurter.dev, no key). Foundry calls it server-side.
- Lab 4.1 uploads `data/travel_policy.md` to a Foundry vector store on the first run and caches its id in `data/.policy_vector_store`.
- Lab 4.5 saves the CFO brief to `outputs/`. Untick **Web Search** in the UI if it is not enabled in your project.
- Group Chat and Magentic agents use a small `TextOnlyTeamHistory` middleware: other agents' tool calls are passed on as text only, otherwise the service rejects the replayed tool results.
- Each lab shows the Python that Code Interpreter actually ran (expand "🐍 Python run by Code Interpreter").
