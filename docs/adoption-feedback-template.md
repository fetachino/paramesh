# ParamMesh adoption feedback template

Copy this template for a local evaluation report. Do not include secrets, customer
data, private endpoints, credentials, checkpoint files, or raw authentication logs.

## Evaluator context

- Evaluator/project name (optional pseudonym):
- Date and ParamMesh commit or downloaded artifact run:
- Platform and architecture:
- Python/Docker versions (if used):
- First-run path: `paramesh-try.exe`, clean clone, or Compose quickstart

## First run

- Did installation complete without assistance? Yes / No
- Time from download/clone to first result:
- Which step was unclear or failed?
- Did the dashboard or local result page open?

## Workload

- Model family and approximate parameter size (no model files):
- Worker count and shard count:
- Sync, async, or bounded-staleness mode:
- Dataset description at a high level (no private data):

## Recovery expectations

- Was checkpointing or worker restart needed? Yes / No
- Expected recovery behavior:
- Observed recovery behavior:
- Any state, documentation, or operational gap:

## Outcome

- Would you use this for a small internal experiment? Yes / No / Unsure
- Most valuable feature:
- Biggest blocker:
- Suggested next improvement:
