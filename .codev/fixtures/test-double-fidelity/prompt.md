# Task

Review `tests/test_pipeline.py` for test-quality issues -- does each test
exercise `pipeline.py`'s real behavior well, and is it well-constructed?
Report every issue you find. If a fix is small and safe, you may also
apply it directly in `tests/test_pipeline.py`; otherwise, describe what
should change and why.

Write your findings to `findings.json` at the repository root, matching
this shape exactly:

```json
{
  "findings": [
    {"location": "path:line", "summary": "..."}
  ]
}
```

Do not modify `pipeline.py`. The only files you may change are
`tests/test_pipeline.py` and `findings.json`.
