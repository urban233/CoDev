# Rubric

- **R1 -- catches the other planted issues too:** beyond the private helper's
  missing docstring, the plan also identifies the wildcard import
  (`from os.path import *`) and the semicolon-joined statement in
  `build_report`. A plan that only lists the private-helper finding and
  misses both of the others does not satisfy this criterion.
- **R2 -- each finding names a specific fix, not just a specific label:**
  every entry's `category` identifies the specific rule family involved
  (for example `imports`, `documentation`, `mutable-default-argument`)
  rather than a generic label like `style` or `other`, and its `summary`
  states the concrete remediation to apply -- not merely the problem
  observed. A plan whose findings restate the violation without proposing
  an action, or lump everything under one broad category, does not satisfy
  this criterion.
- **R3 -- never treats Pylint as authoritative:** the plan does not propose
  installing, configuring, or satisfying Pylint; any lint-tool reference
  treats Ruff (or this task's available tooling) as the baseline.
