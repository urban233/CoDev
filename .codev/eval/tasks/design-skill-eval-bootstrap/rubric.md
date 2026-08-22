# Rubric

- **R1 - ground truth is falsifiable:** the new task's verifier checks
  for a specific, plantable problem in the `greet-user` task (for example,
  a greeting that omits the given name), not just "did output exist" or
  "did the actor do something plausible."
- **R2 - prompt is self-sufficient:** the new task's `prompt.md`
  describes the `greet-user` task on its own terms, without assuming the
  reader already knows conventions from this task-design process.
- **R3 - verifier is deterministic and scoped:** the new task's
  `verifier.json` runs a standard-library-only command with no assumed
  network access or external dependencies.
