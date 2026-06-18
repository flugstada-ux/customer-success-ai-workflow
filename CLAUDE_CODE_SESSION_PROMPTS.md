# Claude Code prompts to run before submitting

Use this file to make the session log accurate. Open the project folder in Claude Code and run these prompts or equivalent prompts.

1. Review this project against the assessment requirements. Tell me any missing workflow stages, missing outputs, or weak points before I submit.

2. Run `python workflow.py`. If it fails, debug it and make the smallest safe fix. If it passes, summarize the outputs created.

3. Inspect `outputs/run_base.json`, `outputs/token_usage_summary.csv`, and `outputs/run_summary.json`. Verify that token and cost tracking is present for every major workflow stage.

4. Check whether the routing logic covers immediate resolution, scheduled follow up, and escalation. Suggest any change that would make the logic clearer to a reviewer.

5. Review the README. Make sure a reviewer can run the project with one command and understand what each output means.

6. Give me a final submission readiness checklist for Submission A, Submission B, and Submission C.
