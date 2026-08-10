# Rubric

- **R1 - correct diagnosis:** the review explains that the bare
  `except Exception: pass` silently discards every error, including ones
  unrelated to a missing config file, with no logging or signal to the caller.
- **R2 - proportionate scope:** the review does not invent unrelated
  requirements or block on anything besides the planted defect.
