# Independent evaluator protocol

This protocol is for a researcher or small team evaluating ParamMesh without
sharing private data. It produces comparable onboarding feedback; it is not a
performance certification and does not require access to the hosted deployment.

## A. Windows standalone path

1. Download the latest successful `paramesh-windows-launcher` artifact from the
   [Windows launcher workflow](https://github.com/fetachino/paramesh/actions/workflows/windows-launcher.yml).
2. Record the artifact run number and SHA-256 of the downloaded zip:

   ```powershell
   Get-FileHash .\paramesh-windows-launcher.zip -Algorithm SHA256
   ```

3. Extract it, note the start time, and run `paramesh-try.exe`.
4. Record whether the local result page opens, the time to the first result,
   the displayed worker/shard counts, and whether the report JSON downloads.
5. Stop the program with `Ctrl+C`. Do not send the generated report if it
   contains information you do not want to share; the evaluator may report only
   the summary fields from the feedback template.

## B. Clean-clone developer path

Use this path when the evaluator wants to try an importable external model:

```powershell
git clone https://github.com/fetachino/paramesh.git
cd paramesh
python -m pip install uv==0.13.6
uv sync --locked --all-extras --python 3.12
.\.venv\Scripts\python.exe examples\external_linear.py
```

For a repeatable comparison, use a new output directory and record the commit
printed in the manifest:

```powershell
.\.venv\Scripts\python.exe examples\external_benchmark.py `
  --output artifacts\external-evaluator `
  --repetitions 1 `
  --warmup-steps 2 `
  --steps 6
```

The benchmark is a smoke comparison. It must not be reported as a performance
ranking or evidence of multi-host scaling.

## Feedback handoff

Complete [the adoption feedback template](adoption-feedback-template.md). Share
only sanitized answers: platform, elapsed setup time, high-level workload shape,
worker/shard counts, observed recovery expectations, and blockers. Do not share
credentials, customer data, private endpoints, checkpoint files, or raw logs
containing authentication metadata.

An evaluator is considered independently validated only when they complete the
workflow without project-author assistance and return a reproducible summary.
ParamMesh will not claim adoption until multiple independent summaries exist.
