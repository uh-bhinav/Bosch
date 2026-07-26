# /test — Run the test suite

Run the pytest suite with verbose output and short tracebacks.

```bash
pytest tests/ -v --tb=short -s
```

If a specific module is mentioned, run only that module's tests:
- `test_step_loader.py` for STEP loading
- `test_draft_analyzer.py` for draft analysis
- `test_undercut_detector.py` for undercut detection
- `test_direction_optimizer.py` for direction optimization
- `test_parting_line.py` for parting line

After running, summarize: total passed, total failed, any errors. If failures exist, read the failing test and the relevant source to diagnose.
