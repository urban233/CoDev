---
description: Review a GitHub Pull Request with exact snapshot and anchored comments
---

Review GitHub Pull Request $pr in repository $repo using the repository-local
`pr-review` skill. This is a GitHub Pull Request review, not a general local
code review.

First fetch the exact PR context with:

```text
python .agents/skills/pr-review/scripts/publish_review.py --repo $repo --pr $pr --fetch --auth gh --output-dir .codev/pr-review/$pr
```

Read the fetched `metadata.json`, `diff.patch`, and the relevant files,
commits, reviews, comments, and checks. Review the exact head SHA and produce
the required Markdown report and `review.json` with validated inline locations.
Do not modify source files. Do not publish, approve, merge, or request changes
without explicit user authorization. If publishing is authorized, use the
publisher's explicit `--publish` option and preserve its pending-review
default.
