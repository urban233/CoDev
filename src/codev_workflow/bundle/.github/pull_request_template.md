<!--
  For an AI-driven task, `codev git open-pr`/`mark-ready` already generate
  this body from the task's own recorded evidence and coverage -- don't fill
  this in by hand for that case, and don't pass --body/--body-file to
  override it; the generated body is more accurate and more consistent.
  This template is the shape reference, and the form to fill in by hand for
  a human-authored pull request with no CoDev task behind it.
-->

Closes #

## Summary

<!-- What changed and why, in two or three sentences. Not a file-by-file
     list -- the diff already shows that. If this is hard to write, the
     change is probably too large. -->

## Test plan

<!-- A repeatable list of steps documenting what you did to verify this
     change, with enough detail that someone unfamiliar with the change
     can reproduce the result. Paste the commands you actually ran and
     their actual output -- not the commands you intended to run, and not
     a summary of them. Trimmed output is fine; edited output is not. -->

```console
$
```

**Acceptance criteria from the issue:**

- [ ] Every acceptance criterion in the linked issue is now met, with output above
- [ ] Result reproduces on a clean environment, not only on the machine it was written on

## Scope

**Files outside the change I expected to make:** <!-- none, or list them and say why -->

**Scope deviations from the issue:** <!-- none, or what changed and what prompted it -->

## Assumptions

**Resolved:** <!-- Which `[unverified]` assumptions from the issue were confirmed, and how -->

**Still unverified:** <!-- Any that survive. These stay marked `[unverified]` in the
                          code and docs, and need a follow-up issue linked here. -->

## Review

<!-- If an independent review ran (`review-change`, `pr-review`, or the
     outer loop's specialist reviewers), record its verdict here: READY FOR
     HUMAN APPROVAL, CHANGES REQUIRED, or BLOCKED BY MISSING EVIDENCE --
     plus any residual risks. -->

## Follow-up

<!-- Stubs left in place, scaffolding to delete later, known limitations,
     deferred work. Each one should be a linked issue, not a sentence that
     will be forgotten. Write "none" if there genuinely is none. -->

## Documentation

- [ ] Design doc / brief / delivery plan updated, or unchanged and still accurate
