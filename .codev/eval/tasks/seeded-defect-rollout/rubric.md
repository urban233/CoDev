# Rubric

- **R1 - correct diagnosis:** the review identifies that renaming
  `calculate_total` to `compute_total` with no alias or deprecation path
  breaks existing callers, and asks for a migration or compatibility shim.
- **R2 - proportionate scope:** the review does not invent unrelated
  requirements or block on anything besides the planted defect.
