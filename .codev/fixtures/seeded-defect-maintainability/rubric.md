# Rubric

- **R1 - correct diagnosis:** the review names the nested `if`/`return`
  pyramid and suggests guard clauses or early returns, without claiming the
  logic is incorrect - it isn't, only hard to follow.
- **R2 - proportionate severity:** unlike the other seeded-defect fixtures,
  this one is a maintainability nit, not a behavioral bug. A reviewer that
  marks it non-blocking while still recording it is behaving correctly; do
  not penalize a non-blocking classification here.
