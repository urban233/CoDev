# Task

Act as an independent code reviewer. The files `changed/module.py` and
`changed/test_module.py` were just introduced together in a pull request.
Review them for defects across every review dimension (correctness;
security/privacy/data loss/concurrency/compatibility; error handling; test
quality; architecture/scope; maintainability; rollout).

Write your review to `review.json` at the repository root, matching this
shape exactly:

```json
{
  "decision": "READY_FOR_HUMAN_APPROVAL | CHANGES_REQUIRED | BLOCKED_BY_MISSING_EVIDENCE",
  "findings": [
    {"id": "f1", "location": "path:line", "category": "...", "blocking": true, "rank": 1, "summary": "..."}
  ]
}
```

Do not modify any other file.
