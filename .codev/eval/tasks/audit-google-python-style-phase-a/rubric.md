# Rubric

- **R1 -- catches the concrete planted violations:** beyond any other
  findings, the plan identifies (a) the wildcard import (`from math import
  *`), (b) the illegal `tmp_` binding (`tmp_dialog`), (c) the
  non-PascalCase class name (`helper_panel`), (d) the non-snake_case method
  name (`FormatData`), (e) the missing docstring on `get_view`, and (f) the
  missing `Args` entry for `a_parent` in `__init__`. A plan that omits more
  than one of these six does not satisfy this criterion.
- **R2 -- each finding names a specific fix, not just a specific label:**
  every entry's `category` identifies the specific rule family involved
  (for example `imports`, `naming`, `documentation`) rather than a generic
  label like `style` or `other`, and its `summary` states the concrete
  remediation to apply -- not merely the problem observed. A plan whose
  findings restate the violation without proposing an action, or lump
  everything under one broad category, does not satisfy this criterion.
- **R3 -- never treats Pylint as authoritative:** the plan does not propose
  installing, configuring, or satisfying Pylint; any lint-tool reference
  treats Ruff (or this task's available tooling) as the baseline.
