"""
Module 4 - All five multi-agent patterns in ONE Gradio app (one tab per lab).

Each tab is the exact same UI as the standalone lab file, so you can teach one
pattern at a time (python lab4_x_....py) or demo them all together (this file).

Run
---
    pip install -r requirements.txt
    python app_all_patterns.py                 # opens http://127.0.0.1:7860
"""

import gradio as gr

import lab4_1_sequential_expense as lab1
import lab4_2_concurrent_loan as lab2
import lab4_3_handoff_bank_support as lab3
import lab4_4_groupchat_investment as lab4
import lab4_5_magentic_cfo as lab5

OVERVIEW = """
## Module 4 · Multi-Agent Patterns with Microsoft Agent Framework on Foundry

From the **most controlled** pattern to the **most autonomous** one:

| # | Pattern | Use case | How the agents work together | Tools (every agent has 1-2) |
|---|---|---|---|---|
| 4.1 | **Sequential** | Expense claim approval | Fixed order, like an assembly line | **OpenAPI (FX rates)**, Code Interpreter, File Search, ERP function |
| 4.2 | **Concurrent** | Loan application check | Independent checks at the same time, then combine | Bureau / bank / registry functions, Code Interpreter |
| 4.3 | **Handoff** | Bank customer support | The conversation moves to the right specialist | Core-banking functions, Code Interpreter |
| 4.4 | **Group Chat** | Investment committee | Shared discussion, a Chair picks who speaks | Fund-rules & CRM functions, Web Search, Code Interpreter |
| 4.5 | **Magentic** | "Why did profit drop 15%?" | A manager makes and changes its own plan | ERP function, Code Interpreter, **OpenAPI (FX rates)**, Web Search |

### Which pattern when?
| If your task... | Use |
|---|---|
| has fixed steps in order | **Sequential** |
| has independent checks | **Concurrent** |
| needs routing to the right expert | **Handoff** |
| gets better with debate or review | **Group Chat** |
| is open-ended with unknown steps | **Magentic** |
"""


def build_app() -> gr.Blocks:
    with gr.Blocks(title="Module 4 · Multi-Agent Patterns") as app:
        with gr.Tab("🏠 Overview"):
            gr.Markdown(OVERVIEW)
        with gr.Tab("4.1 Sequential"):
            lab1.build_ui()  # created inside the tab, so Gradio renders it here
        with gr.Tab("4.2 Concurrent"):
            lab2.build_ui()  # created inside the tab, so Gradio renders it here
        with gr.Tab("4.3 Handoff"):
            lab3.build_ui()  # created inside the tab, so Gradio renders it here
        with gr.Tab("4.4 Group Chat"):
            lab4.build_ui()  # created inside the tab, so Gradio renders it here
        with gr.Tab("4.5 Magentic"):
            lab5.build_ui()  # created inside the tab, so Gradio renders it here
    return app


if __name__ == "__main__":
    build_app().launch(server_port=7860)
