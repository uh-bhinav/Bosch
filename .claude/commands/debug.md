# /debug — Debug a failing module or endpoint

1. Identify which module/endpoint is failing from the error message.
2. Read the relevant source file and any recent changes.
3. Run the specific test file for that module: `pytest tests/test_{module}.py -v --tb=long -s`
4. If it's an API issue, check: `curl http://localhost:8000/health` first, then hit the failing endpoint directly.
5. Check `config.yaml` for threshold values if the issue is about classifications or scores.
6. Report: root cause, fix, and whether it affects other modules downstream.
