# Customer Success AI Workflow Simulation

This project is a runnable end to end simulation for the AI System Design Assessment. It uses the provided synthetic customer success dataset and demonstrates account review, prioritization, inbound issue handling, customer check in support, output quality review, targeted intervention planning, routing, and evaluation.

## Setup

Use Python 3.10 or newer. No paid API key is required because this assessment implementation simulates model calls deterministically and records estimated tokens and costs for each workflow stage.

```bash
cd crossover_cs_ai_workflow
python workflow.py
```

## What the command does

The workflow reads every CSV in `data/`, builds account context, and runs five representative end to end runs:

1. base
2. renewal_risk
3. support_spike
4. quality_batch
5. segment_decline

Each run produces a JSON output in `outputs/`. The workflow also writes `outputs/token_usage_summary.csv` and `outputs/run_summary.json`.

## Workflow stages implemented

1. Memory and context retrieval from account, product usage, support, calls, check ins, draft outputs, and quality standards.
2. Daily account review using health score, health change, usage trend, ticket load, NPS, renewal timing, and expansion signal.
3. Portfolio prioritization by risk and business impact.
4. Inbound issue handling with routing to immediate resolution, scheduled follow up, or escalation.
5. Structured check in support with agenda, prior call continuity, known risks, and follow up items.
6. Output quality review against the provided standards.
7. Targeted intervention planning for a declining segment.
8. Final routing and evaluation checks.

## Prompt templates

Prompt templates are stored in `workflow.py` in the `PROMPTS` dictionary. In a production implementation, each deterministic function would be replaced with a model call using the same prompt contract, plus structured JSON output validation.

## Token and cost tracking

The project estimates input and output tokens per stage, assigns a model to each stage, and calculates measured cost using the pricing values from the assessment token math workbook. The measured per run cost is stored in each run JSON file. The average measured cost per end to end run is stored in `outputs/run_summary.json`.

## Evaluation logic

The workflow checks that high priority work is not left as passive monitoring, that queue items have owners, and that correction routes exist for outputs that fail quality review. The final evaluation object is included in every run output.
