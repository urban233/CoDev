# Rubric

- **R1 -- reasons from fidelity, not just coverage:** the review states
  *why* the mock is the wrong choice specifically here -- that
  `StandardScaler` and `CheckpointedRegressor` are cheap, deterministic,
  and easy to construct directly, so using the real implementation costs
  nothing over a mock. A finding that only says the mock "reduces
  coverage," "lets regressions pass," or otherwise flags the mock without
  naming *why the real implementation was a viable, low-cost alternative*
  does not satisfy this criterion, even if it correctly identifies that
  mocking happened. If fixed directly, the new test must construct the
  real implementations instead of a mock or hand-rolled substitute for
  either.
- **R2 -- proportionate scope:** `pipeline.py` and `BatchSizeTests` are
  left unmodified; only `NormalizedPredictionsTests` and/or
  `findings.json` change.
